#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import EngagementManager
from bb_stack.errors import StackError, ValidationError
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

    def test_initialize_uses_selected_root_and_generates_plain_claude_entry(
        self,
    ) -> None:
        result = self.manager.initialize()

        self.assertEqual(result["root"], str(self.paths.work_root))
        self.assertTrue((self.paths.work_root / "CLAUDE.md").is_file())
        self.assertTrue((self.paths.work_root / ".mcp.json").is_file())
        self.assertTrue((self.paths.work_root / ".claude" / "settings.json").is_file())
        self.assertTrue(self.paths.engagements_root.is_dir())
        self.assertTrue((self.paths.work_root / "inbox").is_dir())
        settings = json.loads(
            (self.paths.work_root / ".claude" / "settings.json").read_text()
        )
        self.assertEqual(settings["env"]["BB_WORK_ROOT"], str(self.paths.work_root))
        self.assertEqual(settings["env"]["BB_AGENT_LANGUAGE"], "zh-CN")
        self.assertEqual(settings["env"]["BB_NPM_REGISTRY"], "auto")
        router = (self.paths.work_root / "CLAUDE.md").read_text()
        self.assertIn("bb-stack workspace route", router)
        self.assertIn("android", router)
        self.assertIn("Operate `bb-stack`, MCP, and CLI tools", router)
        self.assertIn("returned repair commands yourself", router)
        self.assertIn("Ask one compact question only", router)
        self.assertIn("使用简体中文编写面向用户的回复", router)
        self.assertIn("authorization.status=verified", router)
        self.assertIn("bb-stack data ensure", router)
        self.assertTrue(self.manager.status()["ready"])

    def test_work_root_cannot_overlap_stack_source(self) -> None:
        for work_root in (ROOT / "nested-work", ROOT.parent):
            with self.subTest(work_root=work_root):
                paths = StackPaths(
                    root=ROOT,
                    home=self.paths.home,
                    work_root=work_root,
                    config_home=self.paths.config_home,
                    claude_config_dir=self.paths.claude_config_dir,
                )
                with self.assertRaises(ValidationError):
                    WorkspaceManager(paths)._validate_root()

    def test_default_home_child_work_root_is_allowed(self) -> None:
        paths = StackPaths(
            root=ROOT,
            home=self.paths.home,
            work_root=self.paths.home / "BB-Workspaces",
            config_home=self.paths.config_home,
            claude_config_dir=self.paths.claude_config_dir,
        )
        WorkspaceManager(paths)._validate_root()

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
        self.assertEqual(result["skill_route"], ["bb-orchestrator"])
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

        android = self.manager.route(
            kind="android",
            target="./inbox/continuous.apk",
            slug="continuous-android",
            platform=None,
            mode="continuous",
        )
        android_prompt = Path(android["prompt_file"]).read_text()
        self.assertIn("mode=continuous", android_prompt)
        self.assertIn("A status update is not a terminal action", android_prompt)

    def test_browser_js_route_uses_analysis_workflow_without_bb_budget(self) -> None:
        self.manager.initialize()
        result = self.manager.route(
            kind="browser-js",
            target="https://example.invalid/app",
            slug="example-js",
            platform=None,
            mode="interactive",
        )

        root = Path(result["engagement"])
        self.assertEqual(result["workflow"], "analysis")
        self.assertEqual(result["platform"], "standalone-analysis")
        self.assertEqual(result["profile"], "browser-js")
        self.assertEqual(result["skill_route"], ["browser-js-orchestrator"])
        self.assertEqual(
            result["browser_start"],
            "bb-stack browser start --engagement example-js",
        )
        self.assertTrue((root / "notes" / "analysis-log.md").is_file())
        self.assertNotIn(
            "Default Production Action Budget",
            (root / "notes" / "SCOPE.md").read_text(),
        )

    def test_workflow_domain_matrix_keeps_profiles_isolated(self) -> None:
        self.manager.initialize()
        assessment = self.manager.route(
            kind="android-assessment",
            target="./inbox/product.apk",
            slug="product-android",
            platform=None,
            mode="continuous",
        )
        analysis = self.manager.route(
            kind="android-analysis",
            target="./inbox/library.apk",
            slug="library-analysis",
            platform=None,
            mode="interactive",
        )
        challenge = self.manager.route(
            kind="ctf-android",
            target="./inbox/challenge.apk",
            slug="challenge-android",
            platform=None,
            mode="interactive",
        )

        self.assertEqual(assessment["workflow"], "assessment")
        self.assertEqual(assessment["profile"], "assessment-android")
        self.assertEqual(assessment["platform"], "authorized-assessment")
        self.assertEqual(
            assessment["skill_route"],
            [
                "security-orchestrator",
                "android-reverse-engineering",
                "android-pentest",
            ],
        )
        assessment_prompt = Path(assessment["prompt_file"]).read_text()
        self.assertIn("Authorized Security Assessment Workflow", assessment_prompt)
        self.assertNotIn("Default Production Action Budget", assessment_prompt)
        self.assertNotIn("verified flag", assessment_prompt)

        self.assertEqual(analysis["workflow"], "analysis")
        self.assertEqual(analysis["profile"], "analysis-android")
        analysis_prompt = Path(analysis["prompt_file"]).read_text()
        self.assertIn("Security Analysis Workflow", analysis_prompt)
        self.assertNotIn("Authorized Security Assessment Workflow", analysis_prompt)

        self.assertEqual(challenge["workflow"], "ctf")
        self.assertEqual(challenge["profile"], "ctf-android")
        challenge_prompt = Path(challenge["prompt_file"]).read_text()
        self.assertIn("CTF Workflow", challenge_prompt)
        self.assertNotIn("Authorized Security Assessment Workflow", challenge_prompt)

    def test_full_security_routes_select_expected_specialists(self) -> None:
        self.manager.initialize()
        cases = {
            "web-assessment": ("assessment-web", "api-security"),
            "ios-assessment": ("assessment-ios", "ios-pentest"),
            "network-assessment": ("assessment-network", "network-pentest"),
            "cloud-assessment": ("assessment-cloud", "cloud-security"),
            "llm-assessment": ("assessment-llm", "llm-security"),
            "source-audit": ("assessment-source", "sast-orchestration"),
            "reverse-analysis": ("analysis-reverse", "reverse-orchestrator"),
        }
        for index, (kind, expected) in enumerate(cases.items(), start=1):
            with self.subTest(kind=kind):
                result = self.manager.route(
                    kind=kind,
                    target=f"./inbox/target-{index}",
                    slug=f"route-{index}",
                    platform=None,
                    mode="interactive",
                )
                self.assertEqual(result["profile"], expected[0])
                self.assertEqual(result["skill_route"][-1], expected[1])
                self.assertEqual(
                    result["workflow"],
                    "assessment" if kind != "reverse-analysis" else "analysis",
                )

    def test_managed_file_changes_are_not_overwritten_without_force(self) -> None:
        self.manager.initialize()
        router = self.paths.work_root / "CLAUDE.md"
        router.write_text(router.read_text() + "local edit\n", encoding="utf-8")

        with self.assertRaisesRegex(StackError, "local changes"):
            self.manager.initialize()
        self.manager.initialize(force=True)
        self.assertNotIn("local edit", router.read_text())

    def test_workspace_never_loads_domain_mcp(self) -> None:
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
