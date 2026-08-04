#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import CommandError, ValidationError
from bb_stack.io import dump_json
from bb_stack.keysmith import KeysmithAdapter
from bb_stack.paths import StackPaths


class KeysmithAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-keysmith-")
        base = Path(self.temporary.name)
        home = base / "home"
        self.paths = StackPaths(
            ROOT,
            home,
            base / "work",
            base / "config",
            home / ".claude",
        )
        self.source = base / "source"
        self.source.mkdir()
        (self.source / "claude-instruct.py").write_text(
            "#!/usr/bin/env python3\n", encoding="utf-8"
        )
        self.adapter = KeysmithAdapter(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_source_override_and_validation(self) -> None:
        with patch.dict(os.environ, {"BB_KEYSMITH_SOURCE": str(self.source)}):
            self.assertEqual(self.adapter.source(fetch=False), self.source)

        invalid = Path(self.temporary.name) / "invalid"
        invalid.mkdir()
        with (
            patch.dict(os.environ, {"BB_KEYSMITH_SOURCE": str(invalid)}),
            self.assertRaisesRegex(ValidationError, "invalid Keysmith source"),
        ):
            self.adapter.source(fetch=False)

    def test_cached_source_revision_is_pinned(self) -> None:
        revision = self.adapter.config["revision"]
        completed = subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{revision}\n", stderr=""
        )
        with patch("bb_stack.keysmith.subprocess.run", return_value=completed):
            self.adapter._verify_source(self.source, require_revision=True)

    def test_default_source_cache_fetches_and_reports_revision(self) -> None:
        cache = self.paths.config_home / "keysmith-cache"
        self.adapter.config["cache_dir"] = str(cache)

        def run(command: list[str], *, capture: bool = False) -> object:
            del capture
            if command[1] == "clone":
                cache.mkdir(parents=True)
                (cache / "claude-instruct.py").write_text(
                    "#!/usr/bin/env python3\n", encoding="utf-8"
                )
            return subprocess.CompletedProcess(command, 0)

        revision = self.adapter.config["revision"]
        completed = subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{revision}\n", stderr=""
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.adapter, "_run", side_effect=run) as invoked,
            patch("bb_stack.keysmith.subprocess.run", return_value=completed),
        ):
            fetched = self.adapter.fetch()
        self.assertEqual(invoked.call_count, 2)
        self.assertEqual(fetched["source"], str(cache))
        self.assertEqual(fetched["revision"], revision)

        cache.rename(cache.with_name("removed-cache"))
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(CommandError, "not cached"),
        ):
            self.adapter.source(fetch=False)

        mismatch = subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{'0' * 40}\n", stderr=""
        )
        with (
            patch("bb_stack.keysmith.subprocess.run", return_value=mismatch),
            self.assertRaisesRegex(ValidationError, "revision mismatch"),
        ):
            self.adapter._verify_source(self.source, require_revision=True)

    def test_run_wraps_process_failures(self) -> None:
        with (
            patch("bb_stack.keysmith.subprocess.run", side_effect=OSError("missing")),
            self.assertRaisesRegex(CommandError, "Keysmith command failed"),
        ):
            self.adapter._run(["missing"])

        failure = subprocess.CalledProcessError(2, ["tool"], stderr="specific failure")
        with (
            patch("bb_stack.keysmith.subprocess.run", side_effect=failure),
            self.assertRaisesRegex(CommandError, "specific failure"),
        ):
            self.adapter._run(["tool"], capture=True)

    def test_install_requires_confirmation_standard_home_and_replacement(self) -> None:
        with self.assertRaisesRegex(ValidationError, "explicit --yes"):
            self.adapter.install("ctf-replacement", yes=False)

        nonstandard = StackPaths(
            ROOT,
            self.paths.home,
            self.paths.work_root,
            self.paths.config_home,
            Path(self.temporary.name) / "other-claude",
        )
        with self.assertRaisesRegex(ValidationError, "standard"):
            KeysmithAdapter(nonstandard).install("ctf-replacement", yes=True)

        rendered = SimpleNamespace(prompt_mode="native", output_file="unused")
        with (
            patch("bb_stack.keysmith.ProfileRegistry.render", return_value=rendered),
            self.assertRaisesRegex(ValidationError, "replacement profile"),
        ):
            self.adapter.install("ctf", yes=True)

    def test_install_writes_managed_prompt_settings_and_private_deployment(
        self,
    ) -> None:
        prompt = Path(self.temporary.name) / "rendered.md"
        prompt.write_text("managed prompt\n", encoding="utf-8")
        rendered = SimpleNamespace(prompt_mode="replacement", output_file=str(prompt))
        settings = self.paths.claude_config_dir / "settings.json"
        settings.parent.mkdir(parents=True)
        dump_json(settings, {"existing": True})
        with (
            patch("bb_stack.keysmith.ProfileRegistry.render", return_value=rendered),
            patch.object(self.adapter, "source", return_value=self.source),
            patch.object(self.adapter, "_run") as run,
        ):
            deployment = self.adapter.install("ctf-replacement", yes=True)

        run.assert_called_once()
        self.assertEqual(deployment["profile"], "ctf-replacement")
        self.assertEqual(
            json.loads(settings.read_text(encoding="utf-8"))["systemPrompt"],
            "managed prompt\n",
        )
        self.assertEqual(self.adapter.deployment.stat().st_mode & 0o777, 0o600)

    def test_status_reports_uncached_valid_and_invalid_doctor(self) -> None:
        with patch.object(
            self.adapter, "source", side_effect=CommandError("not cached")
        ):
            status = self.adapter.status()
        self.assertFalse(status["source_cached"])
        self.assertIn("not cached", status["doctor"]["reason"])

        completed = subprocess.CompletedProcess(
            ["python3"], 0, stdout='{"healthy": true}', stderr=""
        )
        with (
            patch.object(self.adapter, "source", return_value=self.source),
            patch.object(self.adapter, "_run", return_value=completed),
        ):
            status = self.adapter.status()
        self.assertTrue(status["source_cached"])
        self.assertTrue(status["doctor"]["healthy"])

        invalid = subprocess.CompletedProcess(
            ["python3"], 0, stdout="not-json", stderr=""
        )
        with (
            patch.object(self.adapter, "source", return_value=self.source),
            patch.object(self.adapter, "_run", return_value=invalid),
            self.assertRaisesRegex(CommandError, "invalid JSON"),
        ):
            self.adapter.status()

    def test_status_detects_managed_prompt_drift(self) -> None:
        system_prompt = Path(self.temporary.name) / "system.md"
        system_prompt.write_text("changed", encoding="utf-8")
        dump_json(
            self.adapter.deployment,
            {
                "system_prompt": str(system_prompt),
                "prompt_sha256": hashlib.sha256(b"original").hexdigest(),
            },
        )
        with patch.object(
            self.adapter, "source", side_effect=CommandError("not cached")
        ):
            status = self.adapter.status()
        self.assertTrue(status["deployed"])
        self.assertFalse(status["managed_prompt_matches"])

    def test_uninstall_requires_confirmation_and_cleans_owned_setting(self) -> None:
        with self.assertRaisesRegex(ValidationError, "explicit --yes"):
            self.adapter.uninstall(yes=False)

        prompt = "managed prompt"
        settings = self.paths.claude_config_dir / "settings.json"
        settings.parent.mkdir(parents=True)
        dump_json(settings, {"systemPrompt": prompt, "existing": True})
        dump_json(
            self.adapter.deployment,
            {
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "system_prompt": str(Path(self.temporary.name) / "system.md"),
            },
        )
        collision = self.adapter.deployment.with_suffix(".uninstalled.json")
        collision.write_text("{}\n", encoding="utf-8")
        with (
            patch.object(self.adapter, "source", return_value=self.source),
            patch.object(self.adapter, "_run") as run,
        ):
            result = self.adapter.uninstall(yes=True)

        run.assert_called_once()
        self.assertTrue(result["settings_cleaned"])
        self.assertNotIn(
            "systemPrompt", json.loads(settings.read_text(encoding="utf-8"))
        )
        self.assertFalse(self.adapter.deployment.exists())
        self.assertTrue(
            self.adapter.deployment.with_name(
                "keysmith-deployment.uninstalled.1.json"
            ).is_file()
        )

    def test_uninstall_preserves_setting_that_is_no_longer_owned(self) -> None:
        settings = self.paths.claude_config_dir / "settings.json"
        settings.parent.mkdir(parents=True)
        dump_json(settings, {"systemPrompt": "user changed"})
        dump_json(
            self.adapter.deployment,
            {"prompt_sha256": hashlib.sha256(b"managed").hexdigest()},
        )
        with (
            patch.object(self.adapter, "source", return_value=self.source),
            patch.object(self.adapter, "_run"),
        ):
            result = self.adapter.uninstall(yes=True)
        self.assertFalse(result["settings_cleaned"])
        self.assertEqual(
            json.loads(settings.read_text(encoding="utf-8"))["systemPrompt"],
            "user changed",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
