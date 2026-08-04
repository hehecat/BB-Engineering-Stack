#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.browser import BrowserRuntimeManager
from bb_stack.capabilities import CapabilityRegistry
from bb_stack.engagement import EngagementManager
from bb_stack.errors import CommandError
from bb_stack.io import dump_json
from bb_stack.paths import StackPaths


class BrowserRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-browser-runtime-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / ".claude",
        )

    def tearDown(self) -> None:
        BrowserRuntimeManager(self.paths).stop()
        self.temporary.cleanup()

    def test_browser_js_mcp_connects_to_managed_cdp(self) -> None:
        output = Path(self.temporary.name) / "mcp.json"
        original_status = CapabilityRegistry.provider_status

        def provider_status(
            registry: CapabilityRegistry,
            name: str,
            provider: dict[str, object],
            env: dict[str, str],
        ) -> dict[str, object]:
            if name == "chrome-devtools-mcp":
                return {
                    "name": name,
                    "kind": "mcp",
                    "present": True,
                    "resolved": "fixture",
                    "locator_detail": "fixture",
                    "configuration": "ready",
                    "configuration_detail": [],
                    "usable": True,
                    "placement": "shared-main",
                }
            return original_status(registry, name, provider, env)

        with (
            patch.dict(
                os.environ,
                {"BB_BROWSER_URL": "http://127.0.0.1:49152"},
                clear=False,
            ),
            patch.object(
                CapabilityRegistry,
                "provider_status",
                provider_status,
            ),
        ):
            document = CapabilityRegistry(self.paths).render_mcp(
                "browser-js",
                output,
                artifact_root=Path(self.temporary.name) / "artifacts",
            )
        server = document["mcpServers"]["chrome-devtools"]
        self.assertIn("--browser-url=http://127.0.0.1:49152", server["args"])
        self.assertNotIn("--executable-path", server["args"])

    def test_browser_command_keeps_chromium_sandbox_enabled(self) -> None:
        command = BrowserRuntimeManager._browser_command(
            "/usr/bin/chromium",
            49152,
            Path(self.temporary.name) / "profile",
            None,
        )
        self.assertNotIn("--no-sandbox", command)
        self.assertIn("--remote-debugging-port=49152", command)

    def test_browser_state_is_scoped_to_each_engagement(self) -> None:
        first = EngagementManager(self.paths).create(
            "browser-one", "https://one.invalid", workflow="analysis"
        )
        second = EngagementManager(self.paths).create(
            "browser-two", "https://two.invalid", workflow="analysis"
        )
        self.assertNotEqual(
            BrowserRuntimeManager._state_path(first),
            BrowserRuntimeManager._state_path(second),
        )

    def test_start_requires_chromium(self) -> None:
        engagement = EngagementManager(self.paths).create(
            "browser-missing", "https://missing.invalid", workflow="analysis"
        )
        manager = BrowserRuntimeManager(self.paths)
        with (
            patch("bb_stack.browser.shutil.which", return_value=None),
            self.assertRaisesRegex(CommandError, "Chromium or Chrome"),
        ):
            manager.start(engagement)

    def test_start_reuses_ready_runtime(self) -> None:
        engagement = EngagementManager(self.paths).create(
            "browser-ready", "https://ready.invalid", workflow="analysis"
        )
        manager = BrowserRuntimeManager(self.paths)
        ready = {
            "schema_version": 1,
            "ready": True,
            "browser_url": "http://127.0.0.1:49152",
        }
        with (
            patch.object(manager, "status", return_value=ready),
            patch.object(manager, "_configure_cli") as configure,
        ):
            result = manager.start(engagement)
        self.assertEqual(result["state"], "ready")
        configure.assert_called_once_with(ready["browser_url"])

    def test_start_persists_owned_runtime_state(self) -> None:
        engagement = EngagementManager(self.paths).create(
            "browser-start", "https://start.invalid", workflow="analysis"
        )
        manager = BrowserRuntimeManager(self.paths)

        def status(path: Path) -> dict[str, object]:
            state_path = manager._state_path(path)
            if not state_path.is_file():
                return {"schema_version": 1, "ready": False, "state": "stopped"}
            state = json.loads(state_path.read_text(encoding="utf-8"))
            return state | {"ready": True, "state": "ready"}

        with (
            patch.object(manager, "status", side_effect=status),
            patch("bb_stack.browser.shutil.which", return_value="/usr/bin/chromium"),
            patch(
                "bb_stack.browser.ConfigurationManager.effective",
                return_value={"BB_PROXY_MODE": "none", "BB_HTTP_PROXY": ""},
            ),
            patch.object(manager, "_allocate_port", return_value=49152),
            patch(
                "bb_stack.browser.subprocess.Popen",
                return_value=SimpleNamespace(pid=43210),
            ),
            patch.object(manager, "_endpoint_ready", return_value=True),
            patch.object(manager, "_configure_cli") as configure,
        ):
            result = manager.start(engagement)
        self.assertEqual(result["state"], "started")
        self.assertEqual(result["pid"], 43210)
        self.assertEqual(result["port"], 49152)
        configure.assert_called_once_with("http://127.0.0.1:49152")
        self.assertEqual(manager._state_path(engagement).stat().st_mode & 0o777, 0o600)

    def test_status_and_stop_recover_from_corrupt_or_stale_state(self) -> None:
        engagement = EngagementManager(self.paths).create(
            "browser-stale", "https://stale.invalid", workflow="analysis"
        )
        manager = BrowserRuntimeManager(self.paths)
        state_path = manager._state_path(engagement)
        state_path.parent.mkdir(parents=True)
        state_path.write_text("not-json\n", encoding="utf-8")
        self.assertFalse(manager.status(engagement)["ready"])
        stopped = manager.stop(engagement)
        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(state_path.exists())

        dump_json(
            state_path,
            {
                "pid": 43210,
                "profile_dir": str(engagement / "profile"),
                "engagement": str(engagement),
            },
        )
        with (
            patch.object(manager, "_process_matches", return_value=True),
            patch.object(manager, "_terminate") as terminate,
            patch.object(manager, "_stop_cli"),
        ):
            manager.stop(engagement)
        terminate.assert_called_once()

    def test_cli_configuration_reports_failure_and_stop_is_idempotent(self) -> None:
        manager = BrowserRuntimeManager(self.paths)
        cli = self.paths.runtime / "node_modules" / ".bin" / "chrome-devtools"
        failure = subprocess.CompletedProcess(
            [str(cli)], 2, stdout="", stderr="configuration failed"
        )
        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("bb_stack.browser.subprocess.run", return_value=failure),
            patch.object(manager, "_stop_cli"),
            self.assertRaisesRegex(CommandError, "configuration failed"),
        ):
            manager._configure_cli("http://127.0.0.1:49152")

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("bb_stack.browser.subprocess.run") as run,
        ):
            manager._stop_cli()
        run.assert_called_once()

    def test_browser_command_includes_proxy_when_configured(self) -> None:
        command = BrowserRuntimeManager._browser_command(
            "/usr/bin/chromium",
            49152,
            Path(self.temporary.name) / "profile",
            "http://127.0.0.1:7890",
        )
        self.assertIn("--proxy-server=http://127.0.0.1:7890", command)

    def test_endpoint_port_and_process_helpers(self) -> None:
        manager = BrowserRuntimeManager(self.paths)
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"webSocketDebuggerUrl":"ws://fixture"}'
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch(
            "bb_stack.browser.http.client.HTTPConnection", return_value=connection
        ):
            self.assertTrue(manager._endpoint_ready(49152))

        response.read.return_value = b"not-json"
        with patch(
            "bb_stack.browser.http.client.HTTPConnection", return_value=connection
        ):
            self.assertFalse(manager._endpoint_ready(49152))
        self.assertGreater(manager._allocate_port(), 0)

        profile = Path(self.temporary.name) / "profile"
        command = (
            f"chromium --user-data-dir={profile} --remote-debugging-port=1".encode()
        )
        with patch("pathlib.Path.read_bytes", return_value=command):
            self.assertTrue(manager._process_matches(123, profile))
        with patch("pathlib.Path.read_bytes", side_effect=OSError("gone")):
            self.assertFalse(manager._process_matches(123, profile))
        self.assertFalse(manager._process_matches(1, profile))

        with patch("bb_stack.browser.os.waitpid", return_value=(123, 0)):
            self.assertTrue(manager._child_exited(123))
        with (
            patch("bb_stack.browser.os.waitpid", side_effect=ChildProcessError),
            patch("pathlib.Path.exists", return_value=False),
        ):
            self.assertTrue(manager._child_exited(123))

    def test_start_failure_terminates_spawned_process(self) -> None:
        engagement = EngagementManager(self.paths).create(
            "browser-failure", "https://failure.invalid", workflow="analysis"
        )
        manager = BrowserRuntimeManager(self.paths)
        with (
            patch("bb_stack.browser.shutil.which", return_value="/usr/bin/chromium"),
            patch(
                "bb_stack.browser.ConfigurationManager.effective",
                return_value={"BB_PROXY_MODE": "none", "BB_HTTP_PROXY": ""},
            ),
            patch.object(manager, "_allocate_port", return_value=49152),
            patch(
                "bb_stack.browser.subprocess.Popen",
                return_value=SimpleNamespace(pid=43210),
            ),
            patch.object(manager, "_endpoint_ready", return_value=False),
            patch.object(manager, "_child_exited", return_value=True),
            patch.object(manager, "_terminate_owned") as terminate,
            self.assertRaisesRegex(CommandError, "exited early"),
        ):
            manager.start(engagement)
        terminate.assert_called_once_with(43210)
        self.assertFalse(manager._state_path(engagement).exists())

    def test_global_status_and_stop_aggregate_managed_instances(self) -> None:
        first = EngagementManager(self.paths).create(
            "browser-global-one", "https://one.invalid", workflow="analysis"
        )
        second = EngagementManager(self.paths).create(
            "browser-global-two", "https://two.invalid", workflow="analysis"
        )
        manager = BrowserRuntimeManager(self.paths)
        for engagement in (first, second):
            dump_json(manager._state_path(engagement), {"engagement": str(engagement)})
        statuses = [
            {"ready": True, "engagement": str(first)},
            {"ready": False, "engagement": str(second)},
        ]
        with (
            patch(
                "bb_stack.browser.EngagementManager.roots", return_value=[first, second]
            ),
            patch.object(manager, "_status_one", side_effect=statuses),
        ):
            status = manager.status()
        self.assertTrue(status["ready"])
        self.assertEqual(len(status["instances"]), 2)

        with (
            patch(
                "bb_stack.browser.EngagementManager.roots", return_value=[first, second]
            ),
            patch.object(manager, "_stop_one", side_effect=statuses) as stop_one,
            patch.object(manager, "_stop_cli") as stop_cli,
        ):
            stopped = manager.stop()
        self.assertFalse(stopped["ready"])
        self.assertEqual(stop_one.call_count, 2)
        stop_cli.assert_called_once()

    def test_termination_only_targets_owned_process_group(self) -> None:
        manager = BrowserRuntimeManager(self.paths)
        profile = Path(self.temporary.name) / "profile"
        with (
            patch.object(manager, "_process_matches", return_value=False),
            patch.object(manager, "_terminate_owned") as terminate,
        ):
            manager._terminate(123, profile)
        terminate.assert_not_called()

        with patch(
            "bb_stack.browser.os.killpg", side_effect=ProcessLookupError
        ) as killpg:
            manager._terminate_owned(123)
        killpg.assert_called_once()

        with (
            patch("bb_stack.browser.os.killpg") as killpg,
            patch("bb_stack.browser.os.waitpid", return_value=(123, 0)),
        ):
            manager._terminate_owned(123)
        killpg.assert_called_once()

    def test_managed_cdp_serves_real_cli_calls(self) -> None:
        env = self.paths.environment()
        env["PATH"] = self.paths.runtime_path()
        if not any(
            shutil.which(name, path=env["PATH"])
            for name in ("chromium", "chromium-browser", "google-chrome")
        ):
            self.skipTest("Chromium is unavailable")
        cli = ROOT / ".runtime" / "node_modules" / ".bin" / "chrome-devtools"
        if not cli.is_file():
            self.skipTest("managed chrome-devtools CLI is unavailable")

        engagement = EngagementManager(self.paths).create(
            "browser-check",
            "https://example.invalid",
            workflow="analysis",
            platform="standalone-analysis",
            route_kind="browser-js",
        )
        started = BrowserRuntimeManager(self.paths).start(engagement)
        self.assertTrue(started["ready"])
        completed = subprocess.run(
            [str(cli), "list_pages", "--output-format=json"],
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["pages"])

        mcp_path = Path(self.temporary.name) / "browser-mcp.json"
        document = CapabilityRegistry(self.paths).render_mcp(
            "browser-js", mcp_path, artifact_root=engagement / "artifacts"
        )
        server = document["mcpServers"]["chrome-devtools"]
        launch = {"command": server["command"], "args": server["args"]}
        mcp_probe = ROOT / ".runtime" / "mcp_probe.mjs"
        probed = subprocess.run(
            [
                shutil.which("node", path=env["PATH"]),
                str(mcp_probe),
                json.dumps(launch),
                json.dumps({"name": "list_pages", "arguments": {}}),
            ],
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(probed.returncode, 0, probed.stderr)
        result = json.loads(probed.stdout)
        self.assertTrue(result["connected"])
        self.assertFalse(result["call"].get("isError", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
