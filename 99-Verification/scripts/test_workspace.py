#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import EngagementManager
from bb_stack.errors import StackError
from bb_stack.paths import StackPaths
from bb_stack.workspace import WorkspaceManager


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-workspace-")
        home = Path(self.temporary.name) / "home"
        self.paths = StackPaths(
            root=ROOT,
            home=home,
            work_root=Path(self.temporary.name) / "chosen-security-root",
            config_home=home / ".config" / "bb-stack",
            claude_config_dir=home / ".claude",
        )
        self.paths.config_home.mkdir(parents=True)
        self.manager = WorkspaceManager(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_initialize_uses_selected_root_and_generates_plain_claude_entry(self) -> None:
        result = self.manager.initialize()

        self.assertEqual(result["root"], str(self.paths.work_root))
        self.assertTrue((self.paths.work_root / "CLAUDE.md").is_file())
        self.assertTrue((self.paths.work_root / ".mcp.json").is_file())
        self.assertTrue(
            (self.paths.work_root / ".claude" / "settings.json").is_file()
        )
        self.assertTrue(self.paths.engagements_root.is_dir())
        self.assertTrue((self.paths.work_root / "inbox").is_dir())
        settings = json.loads(
            (self.paths.work_root / ".claude" / "settings.json").read_text()
        )
        self.assertEqual(settings["env"]["BB_WORK_ROOT"], str(self.paths.work_root))
        self.assertEqual(settings["env"]["BB_AGENT_LANGUAGE"], "zh-CN")
        router = (self.paths.work_root / "CLAUDE.md").read_text()
        self.assertIn("bb-stack workspace route", router)
        self.assertIn("android", router)
        self.assertIn("使用简体中文编写面向用户的回复", router)
        self.assertTrue(self.manager.status()["ready"])

    def test_claude_local_permissions_survive_workspace_refresh(self) -> None:
        self.manager.initialize()
        local = self.paths.work_root / ".claude" / "settings.local.json"
        local.write_text(
            json.dumps(
                {
                    "$schema": "https://json.schemastore.org/claude-code-settings.json",
                    "env": {
                        "BB_WORK_ROOT": "/old/workspace",
                        "USER_EXTENSION": "keep-me",
                    },
                    "enableAllProjectMcpServers": True,
                    "permissions": {"allow": ["Bash(bb-stack workspace *)"]},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        result = self.manager.initialize()
        migrated = json.loads(local.read_text())
        self.assertTrue(result["local_settings_migrated"])
        self.assertEqual(migrated["env"], {"USER_EXTENSION": "keep-me"})
        self.assertTrue(migrated["enableAllProjectMcpServers"])
        self.assertEqual(
            migrated["permissions"]["allow"], ["Bash(bb-stack workspace *)"]
        )

    def test_route_creates_nested_android_engagement_and_reuses_it(self) -> None:
        self.manager.initialize()
        first = self.manager.route(
            kind="android",
            target="./inbox/demo.apk",
            slug=None,
            platform=None,
            mode=None,
        )

        root = Path(first["engagement"])
        self.assertEqual(root.parent, self.paths.engagements_root)
        self.assertEqual(first["profile"], "ctf-android")
        self.assertEqual(
            first["skill_route"],
            ["reverse-orchestrator", "android-reverse-engineering"],
        )
        self.assertTrue(Path(first["prompt_file"]).is_file())
        self.assertTrue(Path(first["profile_mcp_config"]).is_file())
        self.assertEqual(
            EngagementManager(self.paths).validate(root)["routing"]["kind"],
            "android",
        )

        second = self.manager.route(
            kind=None,
            target=None,
            slug=first["slug"],
            platform=None,
            mode=None,
        )
        self.assertFalse(second["created"])
        self.assertEqual(second["engagement"], first["engagement"])
        self.assertEqual(second["profile"], "ctf-android")

    def test_web_continuous_route_selects_platform_overlay_and_profile(self) -> None:
        self.manager.initialize()
        result = self.manager.route(
            kind="web",
            target="https://example.invalid",
            slug="example-h1",
            platform="hackerone",
            mode="continuous",
        )

        self.assertEqual(result["profile"], "bb-continuous")
        self.assertEqual(result["platform"], "hackerone")
        prompt = Path(result["prompt_file"]).read_text()
        self.assertIn("HackerOne", prompt)

        ctf = self.manager.route(
            kind="ctf-web",
            target="https://ctf.invalid",
            slug="continuous-ctf",
            platform=None,
            mode="continuous",
        )
        self.assertEqual(ctf["profile"], "ctf-replacement")

    def test_managed_file_changes_are_not_overwritten_without_force(self) -> None:
        self.manager.initialize()
        router = self.paths.work_root / "CLAUDE.md"
        router.write_text(router.read_text() + "local edit\n", encoding="utf-8")

        with self.assertRaisesRegex(StackError, "local changes"):
            self.manager.initialize()
        self.manager.initialize(force=True)
        self.assertNotIn("local edit", router.read_text())

    def test_workspace_initializes_without_chromium_and_omits_playwright(self) -> None:
        original_which = shutil.which

        def without_chromium(command: str, path: str | None = None) -> str | None:
            if command in {"chromium", "chromium-browser", "google-chrome"}:
                return None
            return original_which(command, path=path)

        with patch("bb_stack.capabilities.shutil.which", side_effect=without_chromium):
            result = self.manager.initialize()

        self.assertTrue(result["ready"])
        self.assertEqual(result["mcp_servers"], [])
        document = json.loads((self.paths.work_root / ".mcp.json").read_text())
        self.assertEqual(document, {"mcpServers": {}})

    def test_legacy_direct_engagement_is_still_discoverable(self) -> None:
        self.manager.initialize()
        nested = EngagementManager(self.paths).create(
            "legacy-readable", "https://legacy.invalid", workflow="ctf"
        )
        legacy = self.paths.work_root / nested.name
        nested.rename(legacy)

        self.assertEqual(self.paths.engagement("legacy-readable"), legacy)
        listed = EngagementManager(self.paths).list()
        self.assertEqual([item["slug"] for item in listed], ["legacy-readable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
