#!/usr/bin/env python3
"""Contract tests for the task-first edition.

The stack must behave as a direct execution tool: every supplied target is
pre-cleared, routing never emits an authorization repair, generated prompts
never tell the agent to ask for scope or permission, and every new engagement
carries a bypass tool policy.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import EngagementManager
from bb_stack.paths import StackPaths
from bb_stack.policy import BYPASS_MODE, policy_for
from bb_stack.profiles import ProfileRegistry
from bb_stack.workspace import WorkspaceManager

FORBIDDEN_PROMPT_PHRASES = (
    "Ask one compact question",
    "authorization.status",
    "written Scope",
    "written scope",
    "user-asserted",
    "pending` or `revoked",
)


class TaskFirstTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-task-first-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_new_engagements_are_precleared_with_bypass_policy(self) -> None:
        manager = EngagementManager(self.paths)
        for workflow in ("assessment", "bug-bounty", "ctf", "lab", "analysis"):
            with self.subTest(workflow=workflow):
                root = manager.create(
                    f"task-first-{workflow}",
                    "https://target.example",
                    workflow=workflow,
                )
                state = manager.validate(root)
                self.assertEqual(state["authorization"]["status"], "exempt")
                self.assertTrue(state["authorization"]["source"])
                self.assertEqual(policy_for(self.paths, root.name).mode, BYPASS_MODE)

    def test_route_never_emits_an_authorization_repair(self) -> None:
        workspace = WorkspaceManager(self.paths)
        workspace.initialize()
        routed = workspace.route(
            kind="web-assessment",
            target="https://target.example",
            slug=None,
            platform=None,
            mode="interactive",
        )
        repairs = "\n".join(routed["repair_commands"])
        self.assertNotIn("engagement authorize", repairs)
        self.assertEqual(routed["authorization"]["status"], "exempt")
        self.assertTrue(routed["ready"] or "bootstrap" in repairs)

    def test_rendered_prompts_do_not_teach_authorization_questions(self) -> None:
        registry = ProfileRegistry(self.paths)
        for name in registry.names():
            with self.subTest(profile=name):
                rendered = registry.render(name)
                content = Path(rendered.output_file).read_text(encoding="utf-8")
                for phrase in FORBIDDEN_PROMPT_PHRASES:
                    self.assertNotIn(phrase, content)

    def test_workspace_router_is_task_first(self) -> None:
        router = (
            ROOT / "02-L2-Workflow-Profiles" / "workspace" / "CLAUDE.md"
        ).read_text(encoding="utf-8")
        self.assertIn("pre-cleared", router)
        self.assertIn("start the first concrete action", router)
        for phrase in FORBIDDEN_PROMPT_PHRASES:
            self.assertNotIn(phrase, router)


if __name__ == "__main__":
    unittest.main(verbosity=2)
