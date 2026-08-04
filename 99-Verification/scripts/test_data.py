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
from bb_stack.errors import CommandError, ValidationError
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

    def test_catalog_and_selector_validation(self) -> None:
        manager = DataManager(self.paths)
        unknown_dataset = self._document(self.first_revision)
        unknown_dataset["profiles"]["demo"]["required"][0]["dataset"] = "missing"
        with (
            patch("bb_stack.data.load_yaml", return_value=unknown_dataset),
            patch("bb_stack.data.validate"),
            self.assertRaisesRegex(ValidationError, "unknown dataset"),
        ):
            manager.catalog()

        unknown_bundle = self._document(self.first_revision)
        unknown_bundle["profiles"]["demo"]["required"][0]["bundles"] = ["missing"]
        with (
            patch("bb_stack.data.load_yaml", return_value=unknown_bundle),
            patch("bb_stack.data.validate"),
            self.assertRaisesRegex(ValidationError, "unknown demo bundle"),
        ):
            manager.catalog()

        with self.assertRaisesRegex(ValidationError, "choose either"):
            self.manager.status("demo", profile="demo")
        with self.assertRaisesRegex(ValidationError, "unknown data profile"):
            self.manager.status(profile="missing")
        with self.assertRaisesRegex(ValidationError, "unknown data profile"):
            self.manager.ensure_profile("missing")
        with self.assertRaisesRegex(ValidationError, "unknown demo bundle"):
            self.manager.ensure("demo", ["missing"])

    def test_status_and_profile_ensure_variants(self) -> None:
        with patch("bb_stack.data.load_yaml", return_value=self.document):
            self.assertEqual(self.manager.path("demo"), self.paths.data_root / "demo")
        self.assertFalse(self.manager.status("demo")["ready"])
        self.assertFalse(self.manager.status()["ready"])
        required = self.manager.ensure_profile("demo")
        self.assertEqual(len(required), 1)
        self.assertEqual(required[0]["installed_bundles"], ["alpha"])
        optional = self.manager.ensure_profile("demo", include_optional=True)
        self.assertEqual(optional[0]["installed_bundles"], ["alpha", "beta"])
        ready = self.manager.ensure("demo", ["alpha", "beta"])
        self.assertEqual(ready["state"], "ready")

    def test_invalid_specs_and_remote_output_are_rejected(self) -> None:
        outside = self._document(self.first_revision)
        outside["datasets"]["demo"]["destination"] = str(self.paths.home / "outside")
        with self.assertRaisesRegex(ValidationError, "below BB_DATA_ROOT"):
            self.manager._dataset_spec("demo", outside)

        unsafe = self._document(self.first_revision)
        unsafe["datasets"]["demo"]["bundles"]["alpha"]["paths"] = ["../escape"]
        with self.assertRaisesRegex(ValidationError, "unsafe path"):
            self.manager._dataset_spec("demo", unsafe)
        with self.assertRaisesRegex(ValidationError, "unknown dataset"):
            self.manager._dataset_spec("missing", self.document)
        with (
            patch.object(self.manager, "_run_capture", return_value="invalid"),
            self.assertRaisesRegex(CommandError, "unexpected git ls-remote"),
        ):
            self.manager.update_check("demo")

    def test_command_failures_are_operator_errors(self) -> None:
        with (
            patch("bb_stack.data.subprocess.run", side_effect=OSError("missing")),
            self.assertRaisesRegex(CommandError, "command failed"),
        ):
            self.manager._run(["missing-command"], timeout=1)
        with (
            patch(
                "bb_stack.data.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    1, ["git"], stderr="network failed"
                ),
            ),
            self.assertRaisesRegex(CommandError, "network failed"),
        ):
            self.manager._run_capture(["git"], timeout=1)
        self.assertIsNone(self.manager._git_output(self.paths.home, ["status"]))
        self.assertEqual(self.manager._sparse_paths(self.paths.home), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
