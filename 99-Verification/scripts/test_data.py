#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.data import DataManager
from bb_stack.errors import CommandError
from bb_stack.paths import StackPaths


class DataManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-data-")
        root = Path(self.temporary.name)
        self.source = root / "source"
        self.source.mkdir()
        self._git("init", "--quiet", "--initial-branch=main")
        self._git("config", "user.name", "Test User")
        self._git("config", "user.email", "test@example.invalid")
        for relative, content in (
            ("alpha/a.txt", "alpha\n"),
            ("beta/b.txt", "beta\n"),
        ):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "initial")
        self.first_revision = self._git_output("rev-parse", "HEAD")
        self.paths = StackPaths(
            root=root / "stack",
            home=root / "home",
            work_root=root / "work",
            config_home=root / "config",
            claude_config_dir=root / "claude",
        )
        self.manager = DataManager(self.paths)
        self.document = self._document(self.first_revision)
        self.catalog_patch = patch.object(
            self.manager, "catalog", return_value=self.document
        )
        self.catalog_patch.start()

    def tearDown(self) -> None:
        self.catalog_patch.stop()
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.source), *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def _git_output(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.source), *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def _document(self, revision: str) -> dict:
        return {
            "schema_version": 1,
            "datasets": {
                "demo": {
                    "repository": str(self.source),
                    "revision": revision,
                    "branch": "main",
                    "destination": str(self.paths.data_root / "demo"),
                    "license": "test",
                    "network_timeout_seconds": 30,
                    "retry_attempts": 1,
                    "bundles": {
                        "alpha": {
                            "paths": ["alpha"],
                            "sentinels": ["alpha/a.txt"],
                        },
                        "beta": {
                            "paths": ["beta"],
                            "sentinels": ["beta/b.txt"],
                        },
                        "complete": {
                            "paths": ["."],
                            "sentinels": ["alpha/a.txt", "beta/b.txt"],
                        },
                    },
                }
            },
            "profiles": {
                "demo": {
                    "required": [{"dataset": "demo", "bundles": ["alpha"]}],
                    "optional": [{"dataset": "demo", "bundles": ["beta"]}],
                }
            },
        }

    def test_missing_partial_union_and_complete_states(self) -> None:
        self.assertEqual(self.manager.dataset_status("demo")["state"], "missing")
        result = self.manager.ensure("demo", ["alpha"])
        self.assertEqual(result["state"], "installed")
        partial = self.manager.dataset_status("demo")
        self.assertEqual(partial["state"], "partial")
        self.assertEqual(partial["installed_bundles"], ["alpha"])

        self.manager.ensure("demo", ["beta"])
        selected = self.manager.dataset_status("demo", ["alpha", "beta"])
        self.assertEqual(selected["state"], "ready")
        self.assertEqual(selected["sparse_paths"], ["alpha", "beta"])
        self.assertEqual(self.manager.dataset_status("demo")["state"], "partial")

        self.manager.ensure("demo")
        complete = self.manager.dataset_status("demo")
        self.assertEqual(complete["state"], "ready")
        self.assertEqual(complete["sparse_paths"], ["."])

    def test_stale_revision_update_preserves_existing_bundles(self) -> None:
        self.manager.ensure("demo", ["alpha"])
        marker = self.source / "version.txt"
        marker.write_text("second\n", encoding="utf-8")
        self._git("add", "version.txt")
        self._git("commit", "--quiet", "-m", "second")
        second_revision = self._git_output("rev-parse", "HEAD")
        self.document["datasets"]["demo"]["revision"] = second_revision

        stale = self.manager.dataset_status("demo", ["alpha"])
        self.assertEqual(stale["state"], "stale")
        self.manager.ensure("demo", ["beta"])
        ready = self.manager.dataset_status("demo", ["alpha", "beta"])
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["current_revision"], second_revision)

    def test_failed_stage_preserves_installed_dataset(self) -> None:
        self.manager.ensure("demo", ["alpha"])
        revision = self.manager.dataset_status("demo", ["alpha"])["current_revision"]
        original = self.manager._run

        def fail_fetch(command: list[str], *, timeout: int) -> None:
            if "fetch" in command:
                raise CommandError("injected fetch failure")
            original(command, timeout=timeout)

        with (
            patch.object(self.manager, "_run", side_effect=fail_fetch),
            self.assertRaisesRegex(CommandError, "injected fetch failure"),
        ):
            self.manager.ensure("demo", ["beta"])
        after = self.manager.dataset_status("demo", ["alpha"])
        self.assertEqual(after["state"], "ready")
        self.assertEqual(after["current_revision"], revision)

    def test_dry_run_does_not_create_data_directories(self) -> None:
        result = self.manager.ensure("demo", ["alpha"], dry_run=True)
        self.assertEqual(result["state"], "planned")
        self.assertFalse(self.paths.data_root.exists())

    def test_incompatible_destination_is_never_replaced(self) -> None:
        destination = self.paths.data_root / "demo"
        destination.mkdir(parents=True)
        marker = destination / "owner.txt"
        marker.write_text("user data\n", encoding="utf-8")
        with self.assertRaisesRegex(CommandError, "refusing to replace"):
            self.manager.ensure("demo", ["alpha"])
        self.assertEqual(marker.read_text(encoding="utf-8"), "user data\n")

    def test_profile_optional_bundle_does_not_block_readiness(self) -> None:
        self.manager.ensure("demo", ["alpha"])
        report = self.manager.status(profile="demo")
        self.assertTrue(report["ready"])
        self.assertEqual(report["items"]["demo"]["missing_bundles"], ["beta"])

    def test_update_check_compares_pinned_and_remote_revisions(self) -> None:
        newer = "f" * 40
        with patch.object(
            self.manager,
            "_run_capture",
            return_value=f"{newer}\trefs/heads/main",
        ):
            report = self.manager.update_check("demo")
        self.assertTrue(report["items"]["demo"]["update_available"])
        self.assertEqual(report["items"]["demo"]["latest_revision"], newer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
