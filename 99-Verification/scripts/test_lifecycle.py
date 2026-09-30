#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
from bb_stack.skills import SkillRegistry
from bb_stack.validation import validate


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
        self.assertEqual(
            self.manager.validate(assessment)["overlays"]["delivery"],
            ["authorized-assessment"],
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

    def test_user_asserted_authorization_permits_active_work(self) -> None:
        root = self.manager.create(
            "user-asserted-assessment",
            "https://example.invalid",
            workflow="assessment",
            authorization_source="Own application under test",
        )
        state = self.manager.validate(root)
        self.assertEqual(state["authorization"]["status"], "user-asserted")
        self.assertNotIn("Record and verify", state["current"]["next_action"])
        scope = (root / "notes" / "SCOPE.md").read_text(encoding="utf-8")
        self.assertIn("- Status: user-asserted", scope)
        status = (root / "STATUS.md").read_text(encoding="utf-8")
        handoff = (root / "SESSION-HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("| Authorization | user-asserted |", status)
        self.assertIn("## Blockers\n\nNone.", status)
        self.assertIn("- Authorization: user-asserted", handoff)
        self.assertIn("## External Dependency\n\nNone.", handoff)
        claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("`user-asserted`", claude)
        self.assertIn("`pending`", claude)

        pending = self.manager.create(
            "pending-promoted",
            "https://example.invalid",
            workflow="assessment",
        )
        state = self.manager.authorize(
            pending,
            status="user-asserted",
            source="User-stated basis: own artifact, recorded at route time",
        )
        self.assertEqual(state["authorization"]["status"], "user-asserted")
        self.assertNotIn("Record and verify", state["current"]["next_action"])

        runtime = RuntimeManager(self.paths)
        # Skill installation and the Claude Code binary are environment
        # prerequisites, not the gate under test: stub them so the
        # protected-workflow authorization path is what launch evaluates.
        claude = str(self.paths.home / "claude-stub")
        with (
            patch.object(SkillRegistry, "status", return_value=[]),
            patch.dict(os.environ, {"CLAUDE_BIN": claude}),
        ):
            result = runtime.launch(
                "assessment-web",
                engagement=root,
                platform=None,
                claude_args=[],
                dry_run=True,
            )
        self.assertEqual(result["profile"], "assessment-web")
        self.assertEqual(result["cwd"], str(root))
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["command"][0], claude)

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
            "state-test",
            "example.invalid",
            workflow="bug-bounty",
            authorization_source="Own asset under test",
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
        with self.assertRaisesRegex(CommandError, "authorization basis"):
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

    def test_validate_requires_authorization_source_for_asserted_status(self) -> None:
        root = self.manager.create(
            "source-gate",
            "https://example.invalid",
            workflow="assessment",
            authorization_source="Own application under test",
        )
        state = self.manager.validate(root)
        self.assertEqual(state["authorization"]["status"], "user-asserted")
        self.assertEqual(
            state["authorization"]["source"], "Own application under test"
        )

        pending = self.manager.create(
            "source-gate-pending", "https://example.invalid", workflow="assessment"
        )
        self.assertIsNone(self.manager.validate(pending)["authorization"]["source"])

        damaged = load_yaml(root / "engagement.yaml")
        damaged["authorization"]["source"] = None
        dump_yaml(root / "engagement.yaml", damaged)
        with self.assertRaisesRegex(ValidationError, "requires an authorization source"):
            self.manager.validate(root)

    def test_revoked_authorization_blocks_resume_until_reauthorized(self) -> None:
        root = self.manager.create(
            "revoked-resume",
            "https://example.invalid",
            workflow="assessment",
            authorization_source="Written statement 2026-08-03",
        )
        revoked = self.manager.authorize(
            root, status="revoked", source="Authorization withdrawn 2026-08-04"
        )
        self.assertEqual(revoked["lifecycle"], "blocked")

        with self.assertRaisesRegex(ValidationError, "authorization is revoked"):
            self.manager.transition(root, "active")
        self.assertEqual(self.manager.validate(root)["lifecycle"], "blocked")

        self.manager.authorize(
            root, status="user-asserted", source="Re-authorized 2026-08-05"
        )
        resumed = self.manager.transition(root, "active")
        self.assertEqual(resumed["lifecycle"], "active")
        self.assertIsNone(resumed["current"]["stop_reason"])

        exempt = self.manager.create("exempt-resume", "example.invalid", workflow="ctf")
        self.manager.transition(exempt, "blocked", "fixture")
        self.assertEqual(
            self.manager.transition(exempt, "active")["lifecycle"], "active"
        )

    def test_failed_create_leaves_no_partial_engagement(self) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated write failure")

        with (
            patch.object(EngagementManager, "_write_control_files", explode),
            self.assertRaises(OSError),
        ):
            self.manager.create("partial-failure", "example.invalid", workflow="ctf")

        self.assertFalse((self.paths.engagements_root / "partial-failure").exists())
        self.assertEqual(
            sorted(
                path.name for path in self.paths.engagements_root.glob(".partial-*")
            ),
            [],
        )
        self.assertEqual(self.manager.roots(), [])

        retry = self.manager.create(
            "partial-failure", "example.invalid", workflow="ctf"
        )
        self.assertEqual(retry.name, "partial-failure")
        self.assertEqual(
            [item for item in self.manager.list() if "error" in item], []
        )

    def test_reference_templates_only_contain_runtime_used_files(self) -> None:
        layer = ROOT / "03-L3-Engagement-State"
        validate(
            load_yaml(layer / "templates" / "engagement.yaml"),
            layer / "schema" / "engagement.schema.json",
            "reference engagement template",
        )
        self.assertEqual(
            sorted(
                str(path.relative_to(layer / "templates"))
                for path in (layer / "templates").rglob("*")
                if path.is_file()
            ),
            [
                ".gitignore",
                "engagement.yaml",
                "hypotheses.md",
                "notes/LAB-CREDS.local.md.example",
                "notes/findings-live.md",
            ],
        )

    def test_platform_delivery_overlay_names_a_registered_overlay(self) -> None:
        registry = load_yaml(
            ROOT / "02-L2-Workflow-Profiles" / "platforms" / "platforms.yaml"
        )["platforms"]
        overlay_dir = ROOT / "02-L2-Workflow-Profiles" / "platforms"
        for platform, contract in sorted(registry.items()):
            with self.subTest(platform=platform):
                overlay = contract["delivery_overlay"]
                self.assertIn(overlay, registry)
                self.assertTrue(
                    (overlay_dir / f"{overlay}.md").is_file(),
                    f"platform {platform} points at undefined overlay {overlay}",
                )
                root = self.manager.create(
                    f"overlay-{platform}",
                    "example.invalid",
                    workflow=contract["workflows"][0],
                    platform=platform,
                )
                self.assertEqual(
                    self.manager.validate(root)["overlays"]["delivery"], [overlay]
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
