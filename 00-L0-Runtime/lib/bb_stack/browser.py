from __future__ import annotations

import http.client
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .configuration import ConfigurationManager
from .engagement import EngagementManager
from .errors import CommandError, ValidationError
from .io import dump_json, load_json
from .paths import StackPaths

CHROMIUM_COMMANDS = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)
MACOS_CHROMIUM_BUNDLES = (
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
)


def find_chromium(
    env: Mapping[str, str],
    *,
    which: Callable[..., str | None] = shutil.which,
) -> str | None:
    """Locate a Chrome or Chromium executable from config, PATH, or macOS bundles."""
    path = env.get("PATH")
    configured = env.get("BB_CHROMIUM_BIN", "").strip()
    if configured:
        expanded = str(Path(configured).expanduser())
        return which(expanded, path=path) or which(configured, path=path)
    for command in CHROMIUM_COMMANDS:
        found = which(command, path=path)
        if found:
            return found
    if platform.system() == "Darwin":
        home = Path(env.get("HOME", str(Path.home())))
        candidates = (
            *MACOS_CHROMIUM_BUNDLES,
            str(home / "Applications/Chromium.app/Contents/MacOS/Chromium"),
            str(home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        )
        for candidate in candidates:
            found = which(candidate, path=path)
            if found:
                return found
    return None


class BrowserRuntimeManager:
    """Own one isolated Chromium CDP process for an active work unit."""

    HOST = "127.0.0.1"
    START_TIMEOUT_SECONDS = 30

    def __init__(self, paths: StackPaths):
        self.paths = paths

    @staticmethod
    def _log_excerpt(log_path: Path, max_lines: int = 20, max_chars: int = 2000) -> str:
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        if not content:
            return ""
        tail = "\n".join(content.splitlines()[-max_lines:])
        if len(tail) > max_chars:
            tail = tail[-max_chars:]
        return tail

    @staticmethod
    def _state_path(engagement: Path) -> Path:
        return engagement / ".bb-stack" / "browser" / "runtime.json"

    def start(self, engagement: Path) -> dict[str, Any]:
        engagement = engagement.resolve()
        EngagementManager(self.paths).validate(engagement)
        state_path = self._state_path(engagement)
        current = self.status(engagement)
        if current["ready"]:
            self._configure_cli(current["browser_url"])
            return current | {"state": "ready"}
        if state_path.is_file():
            self.stop(engagement)

        env = self.paths.environment(engagement / "artifacts")
        env["PATH"] = self.paths.runtime_path()
        chromium = find_chromium(env, which=shutil.which)
        if not chromium:
            raise CommandError(
                "Chromium or Chrome is required for managed browser work"
            )

        if not env.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
        self.paths.home.mkdir(parents=True, exist_ok=True)
        runtime_dir = engagement / ".bb-stack" / "browser"
        profile_dir = runtime_dir / "profile"
        log_path = engagement / "artifacts" / "browser" / "chromium-cdp.log"
        profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        port = self._allocate_port()
        machine = ConfigurationManager(self.paths).effective()
        proxy = (
            machine["BB_HTTP_PROXY"] if machine["BB_PROXY_MODE"] == "mihomo" else None
        )
        command = self._browser_command(chromium, port, profile_dir, proxy)
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        null_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            process = subprocess.Popen(
                command,
                stdin=null_fd,
                stdout=log_fd,
                stderr=log_fd,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
            pid = process.pid
        finally:
            os.close(null_fd)
            os.close(log_fd)
        try:
            deadline = time.monotonic() + self.START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if self._endpoint_ready(port):
                    break
                if self._child_exited(pid):
                    excerpt = self._log_excerpt(log_path)
                    message = (
                        f"Chromium CDP exited early ({chromium}); inspect {log_path}"
                    )
                    raise CommandError(f"{message}\n{excerpt}" if excerpt else message)
                time.sleep(0.2)
            else:
                excerpt = self._log_excerpt(log_path)
                message = f"Chromium CDP did not become ready ({chromium}); inspect {log_path}"
                raise CommandError(f"{message}\n{excerpt}" if excerpt else message)

            browser_url = f"http://{self.HOST}:{port}"
            state = {
                "schema_version": 1,
                "pid": pid,
                "engagement": str(engagement),
                "profile_dir": str(profile_dir),
                "log": str(log_path),
                "browser_url": browser_url,
                "port": port,
            }
            dump_json(state_path, state, 0o600)
            self._configure_cli(browser_url)
        except Exception:
            state_path.unlink(missing_ok=True)
            self._terminate_owned(pid)
            if hasattr(process, "poll"):
                process.poll()
            raise
        return self.status(engagement) | {"state": "started"}

    def status(self, engagement: Path | None = None) -> dict[str, Any]:
        if engagement is None:
            instances = [
                self._status_one(root)
                for root in EngagementManager(self.paths).roots()
                if self._state_path(root).is_file()
            ]
            ready = [item for item in instances if item["ready"]]
            return {
                "schema_version": 1,
                "ready": bool(ready),
                "state": "ready" if ready else "stopped",
                "instances": instances,
            }
        return self._status_one(engagement.resolve())

    def _status_one(self, engagement: Path) -> dict[str, Any]:
        state_path = self._state_path(engagement)
        state: dict[str, Any] = {}
        if state_path.is_file():
            try:
                state = load_json(state_path)
            except ValidationError:
                state = {}
        port = int(state.get("port", 0))
        ready = bool(
            state
            and self._process_matches(
                int(state.get("pid", 0)), Path(str(state.get("profile_dir", "")))
            )
            and port > 0
            and self._endpoint_ready(port)
        )
        return {
            "schema_version": 1,
            "ready": ready,
            "state": "ready" if ready else "stopped",
            "pid": state.get("pid"),
            "engagement": state.get("engagement", str(engagement)),
            "browser_url": state.get("browser_url"),
            "port": state.get("port"),
            "log": state.get("log"),
        }

    def stop(self, engagement: Path | None = None) -> dict[str, Any]:
        if engagement is None:
            stopped = [
                self._stop_one(root)
                for root in EngagementManager(self.paths).roots()
                if self._state_path(root).is_file()
            ]
            self._stop_cli()
            return {
                "schema_version": 1,
                "ready": False,
                "state": "stopped",
                "instances": stopped,
            }
        self._stop_cli()
        return self._stop_one(engagement.resolve())

    def _stop_one(self, engagement: Path) -> dict[str, Any]:
        state_path = self._state_path(engagement)
        state: dict[str, Any] = {}
        if state_path.is_file():
            try:
                state = load_json(state_path)
            except ValidationError:
                state = {}
        pid = int(state.get("pid", 0))
        profile_dir = Path(str(state.get("profile_dir", "")))
        if self._process_matches(pid, profile_dir):
            self._terminate(pid, profile_dir)
        state_path.unlink(missing_ok=True)
        return {
            "schema_version": 1,
            "ready": False,
            "state": "stopped",
            "engagement": state.get("engagement"),
        }

    def _configure_cli(self, browser_url: str) -> None:
        cli = self.paths.runtime / "node_modules" / ".bin" / "chrome-devtools"
        if not cli.is_file():
            return
        env = self.paths.environment()
        env["PATH"] = self.paths.runtime_path()
        self._stop_cli()
        completed = subprocess.run(
            [
                str(cli),
                "start",
                f"--browserUrl={browser_url}",
                "--categoryExtensions=false",
                "--categoryPerformance=false",
                "--performanceCrux=false",
                "--usageStatistics=false",
                "--screenshotFormat=webp",
                "--screenshotMaxWidth=1600",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise CommandError(
                "failed to configure chrome-devtools CLI: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )

    def _stop_cli(self) -> None:
        cli = self.paths.runtime / "node_modules" / ".bin" / "chrome-devtools"
        if not cli.is_file():
            return
        env = self.paths.environment()
        env["PATH"] = self.paths.runtime_path()
        subprocess.run(
            [str(cli), "stop"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )

    def _endpoint_ready(self, port: int) -> bool:
        try:
            connection = http.client.HTTPConnection(self.HOST, port, timeout=0.5)
            connection.request("GET", "/json/version")
            response = connection.getresponse()
            payload = response.read()
            connection.close()
            return response.status == 200 and "webSocketDebuggerUrl" in json.loads(
                payload.decode("utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @classmethod
    def _allocate_port(cls) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((cls.HOST, 0))
            return int(listener.getsockname()[1])

    @classmethod
    def _browser_command(
        cls,
        chromium: str,
        port: int,
        profile_dir: Path,
        proxy: str | None,
    ) -> list[str]:
        command = [
            chromium,
            "--headless",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-search-engine-choice-screen",
            "--password-store=basic",
            "--use-mock-keychain",
            f"--remote-debugging-address={cls.HOST}",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "about:blank",
        ]
        if proxy:
            command.insert(-1, f"--proxy-server={proxy}")
        return command

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        if pid <= 1:
            return False
        if platform.system() != "Darwin":
            return Path(f"/proc/{pid}").exists()
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        stat = completed.stdout.strip()
        return completed.returncode == 0 and bool(stat) and not stat.startswith("Z")

    @staticmethod
    def _process_matches(pid: int, profile_dir: Path) -> bool:
        if pid <= 1 or not profile_dir:
            return False
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            if platform.system() != "Darwin":
                return False
            completed = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if completed.returncode != 0:
                return False
            return (
                str(profile_dir) in completed.stdout
                and "remote-debugging-port" in completed.stdout
            )
        return (
            str(profile_dir).encode() in command and b"remote-debugging-port" in command
        )

    @classmethod
    def _child_exited(cls, pid: int) -> bool:
        try:
            exited_pid, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return not cls._pid_exists(pid)
        return exited_pid == pid

    def _terminate(self, pid: int, profile_dir: Path) -> None:
        if not self._process_matches(pid, profile_dir):
            return
        self._terminate_owned(pid)

    @classmethod
    def _terminate_owned(cls, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                exited_pid, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                exited_pid = 0
            if exited_pid == pid or not cls._pid_exists(pid):
                return
            time.sleep(0.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
