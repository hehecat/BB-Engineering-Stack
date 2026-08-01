from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from typing import Any

from .configuration import ConfigurationManager
from .engagement import EngagementManager
from .errors import CommandError
from .io import dump_json, load_json
from .paths import StackPaths


class BrowserRuntimeManager:
    """Own one isolated Chromium CDP process for an active work unit."""

    HOST = "127.0.0.1"
    PORT = 9222

    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.state_path = paths.config_home / "browser-runtime.json"

    def start(self, engagement: Path) -> dict[str, Any]:
        engagement = engagement.resolve()
        EngagementManager(self.paths).validate(engagement)
        current = self.status()
        if current["ready"] and current.get("engagement") == str(engagement):
            self._configure_cli(current["browser_url"])
            return current | {"state": "ready"}
        if current["ready"]:
            self.stop()
        elif self.state_path.is_file():
            self.stop()
        elif self._endpoint_ready():
            raise CommandError(
                f"browser CDP port {self.PORT} is occupied by an unmanaged process"
            )

        env = self.paths.environment(engagement / "artifacts")
        env["PATH"] = self.paths.runtime_path()
        chromium = (
            shutil.which("chromium", path=env["PATH"])
            or shutil.which("chromium-browser", path=env["PATH"])
            or shutil.which("google-chrome", path=env["PATH"])
        )
        if not chromium:
            raise CommandError("Chromium or Chrome is required for managed browser work")

        runtime_dir = engagement / ".bb-stack" / "browser"
        profile_dir = runtime_dir / "profile"
        log_path = engagement / "artifacts" / "browser" / "chromium-cdp.log"
        profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            chromium,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            f"--remote-debugging-address={self.HOST}",
            f"--remote-debugging-port={self.PORT}",
            f"--user-data-dir={profile_dir}",
            "about:blank",
        ]
        machine = ConfigurationManager(self.paths).effective()
        if machine["BB_PROXY_MODE"] == "mihomo":
            command.insert(-1, f"--proxy-server={machine['BB_HTTP_PROXY']}")
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        null_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            pid = os.posix_spawn(
                chromium,
                command,
                env,
                file_actions=[
                    (os.POSIX_SPAWN_DUP2, null_fd, 0),
                    (os.POSIX_SPAWN_DUP2, log_fd, 1),
                    (os.POSIX_SPAWN_DUP2, log_fd, 2),
                ],
                setsid=True,
            )
        finally:
            os.close(null_fd)
            os.close(log_fd)
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self._endpoint_ready():
                    break
                if self._child_exited(pid):
                    raise CommandError(
                        f"Chromium CDP exited early; inspect {log_path}"
                    )
                time.sleep(0.2)
            else:
                raise CommandError(
                    f"Chromium CDP did not become ready; inspect {log_path}"
                )

            browser_url = f"http://{self.HOST}:{self.PORT}"
            state = {
                "schema_version": 1,
                "pid": pid,
                "engagement": str(engagement),
                "profile_dir": str(profile_dir),
                "log": str(log_path),
                "browser_url": browser_url,
            }
            dump_json(self.state_path, state, 0o600)
            self._configure_cli(browser_url)
        except Exception:
            self.state_path.unlink(missing_ok=True)
            self._terminate_owned(pid)
            raise
        return self.status() | {"state": "started"}

    def status(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        if self.state_path.is_file():
            try:
                state = load_json(self.state_path)
            except Exception:
                state = {}
        ready = bool(
            state
            and self._process_matches(
                int(state.get("pid", 0)), Path(str(state.get("profile_dir", "")))
            )
            and self._endpoint_ready()
        )
        return {
            "schema_version": 1,
            "ready": ready,
            "state": "ready" if ready else "stopped",
            "pid": state.get("pid"),
            "engagement": state.get("engagement"),
            "browser_url": state.get(
                "browser_url", f"http://{self.HOST}:{self.PORT}"
            ),
            "log": state.get("log"),
        }

    def stop(self) -> dict[str, Any]:
        self._stop_cli()
        state: dict[str, Any] = {}
        if self.state_path.is_file():
            try:
                state = load_json(self.state_path)
            except Exception:
                state = {}
        pid = int(state.get("pid", 0))
        profile_dir = Path(str(state.get("profile_dir", "")))
        if self._process_matches(pid, profile_dir):
            self._terminate(pid, profile_dir)
        self.state_path.unlink(missing_ok=True)
        return {
            "schema_version": 1,
            "ready": False,
            "state": "stopped",
            "engagement": state.get("engagement"),
        }

    def _configure_cli(self, browser_url: str) -> None:
        cli = self.paths.runtime / "node_modules" / ".bin" / "chrome-devtools"
        if not cli.is_file():
            raise CommandError("managed chrome-devtools CLI is not installed")
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

    def _endpoint_ready(self) -> bool:
        try:
            connection = http.client.HTTPConnection(self.HOST, self.PORT, timeout=0.5)
            connection.request("GET", "/json/version")
            response = connection.getresponse()
            payload = response.read()
            connection.close()
            return response.status == 200 and "webSocketDebuggerUrl" in json.loads(
                payload.decode("utf-8")
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _process_matches(pid: int, profile_dir: Path) -> bool:
        if pid <= 1 or not profile_dir:
            return False
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            return False
        return str(profile_dir).encode() in command and b"remote-debugging-port" in command

    @staticmethod
    def _child_exited(pid: int) -> bool:
        try:
            exited_pid, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return not Path(f"/proc/{pid}").exists()
        return exited_pid == pid

    def _terminate(self, pid: int, profile_dir: Path) -> None:
        if not self._process_matches(pid, profile_dir):
            return
        self._terminate_owned(pid)

    @staticmethod
    def _terminate_owned(pid: int) -> None:
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
            if exited_pid == pid or not Path(f"/proc/{pid}").exists():
                return
            time.sleep(0.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
