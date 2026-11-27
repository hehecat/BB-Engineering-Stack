from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from .configuration import ConfigurationManager
from .engagement import EngagementManager
from .errors import CommandError, ValidationError
from .io import dump_json, load_json
from .paths import StackPaths
from .proxy import PROXY_MODES, PROXY_VARIABLES, active_url, apply as proxy_apply


class BrowserRuntimeManager:
    """Own one isolated Chromium CDP process for an active work unit."""

    HOST = "127.0.0.1"

    def __init__(self, paths: StackPaths):
        self.paths = paths

    @staticmethod
    def _state_path(engagement: Path) -> Path:
        return engagement / ".bb-stack" / "browser" / "runtime.json"

    @staticmethod
    def _configured_proxy(machine: dict[str, Any]) -> str | None:
        mode = str(machine.get("BB_PROXY_MODE") or "direct")
        if mode not in PROXY_MODES:
            return None
        return (active_url(machine, "http") or active_url(machine, "socks")) or None

    def _resolve_mitmdump(self, path_env: str) -> str:
        bundled = self.paths.runtime_bin / "mitmdump"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
        found = shutil.which("mitmdump", path=path_env)
        if found:
            return found
        raise CommandError(
            "mitmdump (mitmproxy) is required for --record-traffic; "
            "install it with: bb-stack tool install mitmproxy"
        )

    def _start_traffic_recorder(
        self,
        engagement: Path,
        slug: str,
        runtime_dir: Path,
        machine: dict[str, Any],
        base_env: dict[str, str],
    ) -> dict[str, Any]:
        mode = str(machine.get("BB_PROXY_MODE") or "direct")
        upstream_http = active_url(machine, "http") if mode in PROXY_MODES else ""
        upstream_socks = active_url(machine, "socks") if mode in PROXY_MODES else ""
        if upstream_socks and not upstream_http:
            raise CommandError(
                "browser --record-traffic cannot chain through a SOCKS-only proxy; "
                "configure BB_PROXY_MODE=http or mihomo, or use direct mode"
            )
        mitmdump = self._resolve_mitmdump(base_env["PATH"])
        addon = self.paths.root / "00-L0-Runtime" / "lib" / "bb_stack" / "traffic_proxy.py"
        traffic_db = engagement / "traffic" / "flows.db"
        confdir = runtime_dir / "mitmproxy"
        confdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_path = engagement / "artifacts" / "browser" / "traffic-proxy.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        port = self._allocate_port()

        recorder_env = dict(base_env)
        lib_dir = str(self.paths.root / "00-L0-Runtime" / "lib")
        existing_py = recorder_env.get("PYTHONPATH", "")
        recorder_env["PYTHONPATH"] = f"{lib_dir}:{existing_py}" if existing_py else lib_dir
        recorder_env["BB_TRAFFIC_DB"] = str(traffic_db)
        recorder_env["BB_ENGAGEMENT"] = slug

        command = [
            mitmdump,
            "--listen-host",
            self.HOST,
            "-p",
            str(port),
            "--set",
            f"confdir={confdir}",
            "-s",
            str(addon),
            "--set",
            f"bb_traffic_db={traffic_db}",
            "--set",
            f"bb_traffic_engagement={slug}",
            "--set",
            f"bb_traffic_browser_ports={port}",
        ]
        if upstream_http:
            command.extend(["--mode", f"upstream:{upstream_http}"])

        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        null_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            process = subprocess.Popen(
                command,
                stdin=null_fd,
                stdout=log_fd,
                stderr=log_fd,
                env=recorder_env,
                start_new_session=True,
                close_fds=True,
            )
            pid = process.pid
        finally:
            os.close(null_fd)
            os.close(log_fd)

        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self._tcp_ready(port):
                    break
                if self._child_exited(pid):
                    raise CommandError(
                        f"browser traffic recorder exited early; inspect {log_path}"
                    )
                time.sleep(0.2)
            else:
                raise CommandError(
                    f"browser traffic recorder did not become ready; inspect {log_path}"
                )
        except Exception:
            self._terminate_owned(pid)
            raise

        return {
            "traffic_recording": True,
            "traffic_pid": pid,
            "traffic_port": port,
            "traffic_db": str(traffic_db),
            "traffic_log": str(log_path),
            "proxy_url": f"http://{self.HOST}:{port}",
        }

    def start(
        self, engagement: Path, *, record_traffic: bool = False
    ) -> dict[str, Any]:
        engagement = engagement.resolve()
        engagement_state = EngagementManager(self.paths).validate(engagement)
        state_path = self._state_path(engagement)
        current = self.status(engagement)
        if current["ready"] and (
            not record_traffic or current.get("traffic_recording", False)
        ):
            self._configure_cli(current["browser_url"])
            return current | {"state": "ready"}
        if state_path.is_file() or current.get("ready"):
            self.stop(engagement)

        env = self.paths.environment(engagement / "artifacts")
        machine = ConfigurationManager(self.paths).effective()
        if str(machine.get("BB_PROXY_MODE") or "direct") in PROXY_MODES:
            proxy_apply(env, machine)
        else:
            for name in PROXY_VARIABLES:
                env.pop(name, None)
        env["PATH"] = self.paths.runtime_path(machine.get("BB_EXTRA_PATH", ""))
        chromium = (
            shutil.which("chromium", path=env["PATH"])
            or shutil.which("chromium-browser", path=env["PATH"])
            or shutil.which("google-chrome", path=env["PATH"])
        )
        if not chromium:
            raise CommandError(
                "Chromium or Chrome is required for managed browser work"
            )

        runtime_dir = engagement / ".bb-stack" / "browser"
        profile_dir = runtime_dir / "profile"
        log_path = engagement / "artifacts" / "browser" / "chromium-cdp.log"
        profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        recorder: dict[str, Any] | None = None
        if record_traffic:
            recorder = self._start_traffic_recorder(
                engagement,
                str(engagement_state["slug"]),
                runtime_dir,
                machine,
                env,
            )
            proxy = recorder["proxy_url"]
        else:
            proxy = self._configured_proxy(machine)

        port = self._allocate_port()
        command = self._browser_command(
            chromium,
            port,
            profile_dir,
            proxy,
            ignore_cert_errors=bool(recorder),
        )
        pid = 0
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
        except Exception:
            if recorder is not None:
                self._terminate_owned(int(recorder["traffic_pid"]))
            raise
        finally:
            os.close(null_fd)
            os.close(log_fd)
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self._endpoint_ready(port):
                    break
                if self._child_exited(pid):
                    raise CommandError(f"Chromium CDP exited early; inspect {log_path}")
                time.sleep(0.2)
            else:
                raise CommandError(
                    f"Chromium CDP did not become ready; inspect {log_path}"
                )

            browser_url = f"http://{self.HOST}:{port}"
            state: dict[str, Any] = {
                "schema_version": 1,
                "pid": pid,
                "engagement": str(engagement),
                "profile_dir": str(profile_dir),
                "log": str(log_path),
                "browser_url": browser_url,
                "port": port,
            }
            if recorder is not None:
                state.update(
                    {
                        "traffic_recording": True,
                        "traffic_pid": recorder["traffic_pid"],
                        "traffic_port": recorder["traffic_port"],
                        "traffic_db": recorder["traffic_db"],
                        "traffic_log": recorder["traffic_log"],
                    }
                )
            dump_json(state_path, state, 0o600)
            self._configure_cli(browser_url)
        except Exception:
            state_path.unlink(missing_ok=True)
            self._terminate_owned(pid)
            if recorder is not None:
                self._terminate_owned(int(recorder["traffic_pid"]))
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
        browser_ok = bool(
            state
            and self._process_matches(
                int(state.get("pid", 0)), Path(str(state.get("profile_dir", "")))
            )
            and port > 0
            and self._endpoint_ready(port)
        )
        recording_configured = bool(state.get("traffic_recording"))
        traffic_ok = True
        if recording_configured:
            t_pid = int(state.get("traffic_pid", 0))
            t_port = int(state.get("traffic_port", 0))
            t_db = Path(str(state.get("traffic_db", "")))
            traffic_ok = bool(
                self._traffic_process_matches(t_pid, t_db)
                and t_port > 0
                and self._tcp_ready(t_port)
            )
        ready = browser_ok and traffic_ok
        report: dict[str, Any] = {
            "schema_version": 1,
            "ready": ready,
            "state": "ready" if ready else "stopped",
            "pid": state.get("pid"),
            "engagement": state.get("engagement", str(engagement)),
            "browser_url": state.get("browser_url"),
            "port": state.get("port"),
            "log": state.get("log"),
            "traffic_recording": bool(recording_configured and traffic_ok),
        }
        if recording_configured:
            report["traffic_port"] = state.get("traffic_port")
            report["traffic_db"] = state.get("traffic_db")
        return report

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
        t_pid = int(state.get("traffic_pid", 0))
        t_db = Path(str(state.get("traffic_db", "")))
        if t_pid > 1 and self._traffic_process_matches(t_pid, t_db):
            self._terminate_owned(t_pid)
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

    def _tcp_ready(self, port: int) -> bool:
        try:
            with socket.create_connection((self.HOST, port), timeout=0.4):
                return True
        except OSError:
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
        *,
        ignore_cert_errors: bool = False,
    ) -> list[str]:
        command = [
            chromium,
            "--headless",
            "--disable-gpu",
            f"--remote-debugging-address={cls.HOST}",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "about:blank",
        ]
        if proxy:
            command.insert(-1, f"--proxy-server={proxy}")
        if ignore_cert_errors:
            command.insert(-1, "--ignore-certificate-errors")
        return command

    @staticmethod
    def _traffic_process_matches(pid: int, traffic_db: Path) -> bool:
        if pid <= 1 or not str(traffic_db):
            return False
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            return False
        return (
            f"bb_traffic_db={traffic_db}".encode() in command
            and b"traffic_proxy.py" in command
        )

    @staticmethod
    def _process_matches(pid: int, profile_dir: Path) -> bool:
        if pid <= 1 or not profile_dir:
            return False
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            return False
        return (
            str(profile_dir).encode() in command and b"remote-debugging-port" in command
        )

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
