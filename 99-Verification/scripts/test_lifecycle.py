#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import EngagementManager
from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-lifecycle-")
        home = Path(self.temporary.name)
        self.paths = StackPaths(ROOT, home, home / "work", home / "config", home / ".claude")
        self.manager = EngagementManager(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workflow_specific_trees(self) -> None:
        ctf = self.manager.create("web-ctf", "https://ctf.invalid", workflow="ctf")
        lab = self.manager.create("local-lab", "./fixture.zip", workflow="lab")
        h1 = self.manager.create(
            "h1-program", "https://example.invalid", workflow="bug-bounty", platform="hackerone"
        )
        self.assertTrue((ctf / "notes" / "solve-log.md").is_file())
        self.assertTrue((lab / "notes" / "experiment-log.md").is_file())
        h1_state = self.manager.validate(h1)
        self.assertEqual(ctf.parent, self.paths.engagements_root)
        self.assertTrue(h1_state["identity"]["request_identification"]["enabled"])
        self.assertEqual(
            h1_state["identity"]["request_identification"]["value_from"], "BB_H1_USERNAME"
        )
        self.assertEqual(h1_state["overlays"]["delivery"], ["hackerone"])

    def test_lifecycle_and_secret_permissions(self) -> None:
        root = self.manager.create("state-test", "example.invalid", workflow="bug-bounty")
        self.assertEqual(self.manager.transition(root, "paused", "checkpoint")["lifecycle"], "paused")
        self.assertEqual(self.manager.transition(root, "active")["lifecycle"], "active")
        self.assertEqual(self.manager.transition(root, "closed", "done")["lifecycle"], "closed")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
