#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import EngagementManager
from bb_stack.errors import CommandError, ValidationError
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-lifecycle-")
        home = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT, home, home / "work", home / "config", home / ".claude"
        )
        self.manager = EngagementManager(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workflow_specific_trees(self) -> None:
        ctf = self.manager.create("web-ctf", "https://ctf.invalid", workflow="ctf")
        lab = self.manager.create("local-lab", "./fixture.zip", workflow="lab")
        assessment = self.manager.create(
            "network-review", "10.0.0.0/24", workflow="assessment"
        )
        h1 = self.manager.create(
            "h1-program",
            "https://example.invalid",
            workflow="bug-bounty",
            platform="hackerone",
        )
        self.assertTrue((ctf / "notes" / "solve-log.md").is_file())
        self.assertTrue((lab / "notes" / "experiment-log.md").is_file())
        self.assertTrue((assessment / "notes" / "findings-live.md").is_file())
        self.assertEqual(
            self.manager.validate(assessment)["platform"], "authorized-assessment"
        )
        h1_state = self.manager.validate(h1)
        self.assertEqual(ctf.parent, self.paths.engagements_root)
        self.assertTrue(h1_state["identity"]["request_identification"]["enabled"])
        self.assertEqual(
            h1_state["identity"]["request_identification"]["value_from"],
            "BB_H1_USERNAME",
        )
        self.assertEqual(h1_state["overlays"]["delivery"], ["hackerone"])
        self.assertEqual(h1_state["scope"]["candidates"], [])
        self.assertEqual(h1_state["authorization"]["status"], "pending")
        self.assertIsNone(h1_state["authorization"]["source"])
        scope = (h1 / "notes" / "SCOPE.md").read_text(encoding="utf-8")
        self.assertIn("## Candidate Assets", scope)
        self.assertIn("| Inert upload | 1 file, at most 1 KiB |", scope)
        self.assertTrue((h1 / "notes" / "findings-live.md").is_file())
        self.assertIn(
            "do not create a parallel findings log",
            (h1 / "CLAUDE.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "`authorization.status` to be `verified`",
            (h1 / "CLAUDE.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "| Authorization | pending |",
            (h1 / "STATUS.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "- Authorization: pending",
            (h1 / "SESSION-HANDOFF.md").read_text(encoding="utf-8"),
        )

    def test_authorization_requires_source_and_explicit_verification(self) -> None:
        root = self.manager.create(
            "authorization-test",
            "https://example.invalid",
            workflow="assessment",
        )
        state = self.manager.validate(root)
        self.assertEqual(state["authorization"]["status"], "pending")
        with self.assertRaises(ValidationError):
            self.manager.authorize(root, status="verified", source=None)
        state = self.manager.authorize(
            root,
            status="verified",
            source="Signed assessment statement 2026-08-03",
        )
        self.assertEqual(state["authorization"]["status"], "verified")
        self.assertEqual(state["scope"]["revision"], 2)
        self.assertIn(
            "- Status: verified",
            (root / "notes" / "SCOPE.md").read_text(encoding="utf-8"),
        )
        status = (root / "STATUS.md").read_text(encoding="utf-8")
        handoff = (root / "SESSION-HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("| Authorization | verified |", status)
        self.assertIn("## Blockers\n\nNone.", status)
        self.assertIn("- Authorization: verified", handoff)
        self.assertIn("## External Dependency\n\nNone.", handoff)
        self.assertIn("select the first scoped assessment lead", status)

        state = self.manager.authorize(
            root,
            status="revoked",
            source="Assessment authorization withdrawn 2026-08-03",
        )
        self.assertEqual(state["lifecycle"], "blocked")
        status = (root / "STATUS.md").read_text(encoding="utf-8")
        handoff = (root / "SESSION-HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("| Lifecycle | blocked |", status)
        self.assertIn("| Authorization | revoked |", status)
        self.assertIn("Authorization is revoked", status)
        self.assertIn("- Lifecycle: blocked", handoff)
        self.assertIn("- Authorization: revoked", handoff)

    def test_sensitive_url_details_are_kept_out_of_shared_state(self) -> None:
        secret = "TOPSECRET"
        root = self.manager.create(
            "secret-target",
            f"https://alice:{secret}@example.invalid/api?token={secret}#fragment",
            workflow="bug-bounty",
        )
        state_text = (root / "engagement.yaml").read_text(encoding="utf-8")
        scope_text = (root / "notes" / "SCOPE.md").read_text(encoding="utf-8")
        self.assertNotIn(secret, state_text)
        self.assertNotIn(secret, scope_text)
        self.assertIn("https://example.invalid/api", scope_text)
        sensitive = root / "notes" / "TARGET.local.json"
        self.assertEqual(
            json.loads(sensitive.read_text())["target"].split(":", 2)[1], "//alice"
        )
        self.assertEqual(sensitive.stat().st_mode & 0o777, 0o600)

    def test_lifecycle_and_secret_permissions(self) -> None:
        root = self.manager.create(
            "state-test", "example.invalid", workflow="bug-bounty"
        )
        self.assertEqual(
            self.manager.transition(root, "paused", "checkpoint")["lifecycle"], "paused"
        )
        self.assertIn(
            "| Lifecycle | paused |",
            (root / "STATUS.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.manager.transition(root, "active")["lifecycle"], "active")
        self.assertEqual(
            self.manager.transition(root, "closed", "done")["lifecycle"], "closed"
        )
        self.assertIn(
            "- Lifecycle: closed",
            (root / "SESSION-HANDOFF.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.manager.transition(root, "active")["lifecycle"], "active")
        secret = root / "notes" / "LAB-CREDS.local.md"
        secret.write_text("test-only\n", encoding="utf-8")
        secret.chmod(0o644)
        with self.assertRaises(ValidationError):
            self.manager.validate(root)
        secret.chmod(0o600)
        self.manager.validate(root)

    def test_legacy_migration_defaults_to_preview(self) -> None:
        source = Path(self.temporary.name) / "legacy"
        source.mkdir()
        destination = self.manager.migrate_legacy(
            source,
            "migrated",
            "example.invalid",
            workflow="bug-bounty",
            platform="generic-vdp",
            yes=False,
        )
        self.assertFalse(destination.exists())

    def test_launch_requires_active_verified_protected_engagement(self) -> None:
        runtime = RuntimeManager(self.paths)
        with self.assertRaisesRegex(CommandError, "requires an Engagement"):
            runtime.launch(
                "bb-interactive",
                engagement=None,
                platform=None,
                claude_args=[],
                dry_run=True,
            )

        root = self.manager.create(
            "launch-gate",
            "https://example.invalid",
            workflow="bug-bounty",
        )
        with self.assertRaisesRegex(CommandError, "verified authorization"):
            runtime.launch(
                "bb-interactive",
                engagement=root,
                platform=None,
                claude_args=[],
                dry_run=True,
            )
        self.manager.authorize(
            root,
            status="verified",
            source="Signed rules of engagement",
        )
        self.manager.transition(root, "paused", "operator checkpoint")
        with self.assertRaisesRegex(CommandError, "paused"):
            runtime.launch(
                "bb-interactive",
                engagement=root,
                platform=None,
                claude_args=[],
                dry_run=True,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
