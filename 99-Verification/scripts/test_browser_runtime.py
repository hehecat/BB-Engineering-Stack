#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.browser import BrowserRuntimeManager
from bb_stack.capabilities import CapabilityRegistry
from bb_stack.engagement import EngagementManager
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
