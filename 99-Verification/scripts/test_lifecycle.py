#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import (
    EngagementManager,
    infer_asset,
    normalize_target,
)
from bb_stack.errors import CommandError, StackError, ValidationError
from bb_stack.io import dump_yaml, load_yaml
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
        self.assertIn("verify", state["current"]["next_action"].lower())
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

    def test_target_normalization_edges(self) -> None:
        ipv6, sensitive = normalize_target("https://[2001:db8::1]:8443/path?secret=1")
        self.assertEqual(ipv6["pattern"], "https://[2001:db8::1]:8443/path")
        self.assertIsNotNone(sensitive)
        self.assertEqual(
            infer_asset("192.0.2.4"), {"type": "host", "pattern": "192.0.2.4"}
        )
        self.assertEqual(infer_asset("fixture.zip")["type"], "other")
        with self.assertRaisesRegex(ValidationError, "invalid target URL"):
            normalize_target("https:///missing-host")
        with self.assertRaisesRegex(ValidationError, "invalid target URL port"):
            normalize_target("https://example.invalid:invalid")
        with self.assertRaisesRegex(ValidationError, "control characters"):
            normalize_target("bad\ntarget")

    def test_create_rejects_invalid_contract_combinations(self) -> None:
        cases = (
            ({"slug": "Bad", "workflow": "ctf"}, "slug"),
            ({"slug": "bad-workflow", "workflow": "missing"}, "unsupported workflow"),
            (
                {"slug": "bad-mode", "workflow": "ctf", "mode": "batch"},
                "unsupported mode",
            ),
            (
                {"slug": "bad-platform", "workflow": "ctf", "platform": "missing"},
                "unknown platform",
            ),
            (
                {"slug": "bad-mapping", "workflow": "ctf", "platform": "hackerone"},
                "does not support workflow",
            ),
            (
                {
                    "slug": "bad-auth",
                    "workflow": "assessment",
                    "authorization_status": "exempt",
                },
                "protected workflows require",
            ),
            (
                {
                    "slug": "missing-source",
                    "workflow": "assessment",
                    "authorization_status": "verified",
                },
                "authorization source is required",
            ),
            (
                {
                    "slug": "ctf-auth",
                    "workflow": "ctf",
                    "authorization_status": "verified",
                },
                "uses exempt authorization",
            ),
        )
        for arguments, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValidationError, message),
            ):
                self.manager.create(target="example.invalid", **arguments)

        root = self.manager.create("duplicate", "example.invalid", workflow="ctf")
        self.assertTrue(root.is_dir())
        with self.assertRaisesRegex(StackError, "already exists"):
            self.manager.create("duplicate", "example.invalid", workflow="ctf")

    def test_validation_authorization_and_listing_edges(self) -> None:
        missing = self.paths.engagements_root / "missing"
        with self.assertRaisesRegex(ValidationError, "missing engagement.yaml"):
            self.manager.validate(missing)

        root = self.manager.create(
            "edge-state", "example.invalid", workflow="assessment"
        )
        with self.assertRaisesRegex(ValidationError, "does not require"):
            exempt = self.manager.create("edge-ctf", "example.invalid", workflow="ctf")
            self.manager.authorize(exempt, status="pending", source=None)
        with self.assertRaisesRegex(ValidationError, "unsupported authorization"):
            self.manager.authorize(root, status="invalid", source=None)

        pending = self.manager.authorize(root, status="pending", source=None)
        self.assertEqual(pending["authorization"]["status"], "pending")
        same = self.manager.transition(root, pending["lifecycle"])
        self.assertEqual(same["lifecycle"], "active")
        with self.assertRaisesRegex(ValidationError, "invalid lifecycle transition"):
            self.manager.transition(root, "preview")
        checkpointed = self.manager.checkpoint(root)
        self.assertEqual(checkpointed["slug"], "edge-state")

        state = load_yaml(root / "engagement.yaml")
        state["slug"] = "wrong"
        dump_yaml(root / "engagement.yaml", state)
        listed = self.manager.list()
        self.assertTrue(any("error" in item for item in listed))

    def test_validation_detects_missing_control_and_sensitive_files(self) -> None:
        root = self.manager.create(
            "sensitive-edge",
            "https://user:secret@example.invalid/path",
            workflow="bug-bounty",
        )
        sensitive = root / "notes" / "TARGET.local.json"
        sensitive.unlink()
        with self.assertRaisesRegex(ValidationError, "missing sensitive target"):
            self.manager.validate(root)

        sensitive.write_text('{"target":"https://example.invalid"}\n', encoding="utf-8")
        sensitive.chmod(0o644)
        with self.assertRaisesRegex(ValidationError, "permissions"):
            self.manager.validate(root)
        sensitive.chmod(0o600)
        (root / "STATUS.md").unlink()
        with self.assertRaisesRegex(ValidationError, "missing engagement control"):
            self.manager.validate(root)

    def test_legacy_migration_copies_only_allowed_content(self) -> None:
        source = Path(self.temporary.name) / "legacy-content"
        source.mkdir()
        (source / "notes.txt").write_text("keep\n", encoding="utf-8")
        (source / "cookies.txt").write_text("drop\n", encoding="utf-8")
        created = self.manager.migrate_legacy(
            source,
            "migrated-content",
            "example.invalid",
            workflow="bug-bounty",
            platform="generic-vdp",
            yes=True,
        )
        self.assertTrue((created / "legacy-import" / "notes.txt").is_file())
        self.assertFalse((created / "legacy-import" / "cookies.txt").exists())
        with self.assertRaisesRegex(ValidationError, "not a directory"):
            self.manager.migrate_legacy(
                source / "missing",
                "missing-source",
                "example.invalid",
                workflow="bug-bounty",
                platform="generic-vdp",
                yes=True,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
