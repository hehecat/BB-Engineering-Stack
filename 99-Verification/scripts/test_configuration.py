#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.configuration import ConfigurationManager
from bb_stack.errors import StackError, ValidationError
from bb_stack.io import atomic_write
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager
from test_support import isolated_stack_source


class ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-configuration-")
        base = Path(self.temporary.name)
        self.home = base / "home"
        stack = isolated_stack_source(ROOT, base / "stack")
        self.paths = StackPaths(
            stack,
            self.home,
            self.home / "work",
            self.home / "config",
            self.home / ".claude",
        )
        self.paths.ensure_runtime_dirs()
        self.manager = ConfigurationManager(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_configure_writes_mode_600_and_preserves_extensions(self) -> None:
        self.manager.path.write_text('CUSTOM_EXTENSION="value"\n', encoding="utf-8")
        result = self.manager.configure(
            {
                "BB_PROXY_MODE": "mihomo",
                "BB_H1_USERNAME": "operator-name",
                "BB_AGENT_LANGUAGE": "en",
                "BB_NPM_REGISTRY": "npmjs",
            }
        )
        self.assertEqual(
            result["changed"],
            [
                "BB_AGENT_LANGUAGE",
                "BB_H1_USERNAME",
                "BB_NPM_REGISTRY",
                "BB_PROXY_MODE",
            ],
        )
        values = self.manager.read()
        self.assertEqual(values["CUSTOM_EXTENSION"], "value")
        self.assertEqual(values["BB_PROXY_MODE"], "mihomo")
        self.assertEqual(values["BB_AGENT_LANGUAGE"], "en")
        self.assertEqual(values["BB_NPM_REGISTRY"], "npmjs")
        self.assertEqual(self.manager.path.stat().st_mode & 0o777, 0o600)

    def test_hash_in_value_is_not_treated_as_a_comment(self) -> None:
        self.manager.path.write_text(
            "MAIL_OTP_PASSWORD=p@ss#2024\n", encoding="utf-8"
        )
        values = self.manager.read()
        self.assertEqual(values["MAIL_OTP_PASSWORD"], "p@ss#2024")
        self.manager.write(values)
        self.assertEqual(self.manager.read()["MAIL_OTP_PASSWORD"], "p@ss#2024")

    def test_value_with_spaces_does_not_break_effective(self) -> None:
        self.manager.path.write_text("BACKUP_DIR=/srv/a b\n", encoding="utf-8")
        self.assertEqual(self.manager.read()["BACKUP_DIR"], "/srv/a b")
        self.assertEqual(self.manager.effective()["BB_PROXY_MODE"], "direct")

    def test_quotes_expansions_and_backslashes_are_literal(self) -> None:
        self.manager.path.write_text(
            "\n".join(
                (
                    "UNQUOTED=a b",
                    'DOUBLE="a b"',
                    "SINGLE='a b'",
                    "EXPANSION=$HOME/x",
                    r"BACKSLASH=a\b",
                    "",
                )
            ),
            encoding="utf-8",
        )
        values = self.manager.read()
        self.assertEqual(values["UNQUOTED"], "a b")
        self.assertEqual(values["DOUBLE"], "a b")
        self.assertEqual(values["SINGLE"], "a b")
        self.assertEqual(values["EXPANSION"], "$HOME/x")
        self.assertEqual(values["BACKSLASH"], r"a\b")

    def test_write_read_is_idempotent_for_awkward_values(self) -> None:
        samples = {
            "HASH_VALUE": "p@ss#2024",
            "SPACE_VALUE": "/srv/a b",
            "SINGLE_QUOTED": "'quoted'",
            "DOUBLE_QUOTED": '"quoted"',
            "EXPANSION": "$HOME/etc",
            "BACKSLASH": r"a\b",
            "APOSTROPHE": "it's",
            "BOTH_QUOTES": "a'b\"c",
            "EMPTY": "",
            "TRAILING_HASH": "value # not a comment",
        }
        self.manager.write(samples)
        read_back = self.manager.read()
        for key, value in samples.items():
            self.assertEqual(read_back[key], value, key)
        first = self.manager.path.read_text(encoding="utf-8")
        self.manager.write(read_back)
        self.assertEqual(self.manager.path.read_text(encoding="utf-8"), first)

    def test_line_without_assignment_is_reported(self) -> None:
        self.manager.path.write_text(
            "THIS IS NOT AN ASSIGNMENT\n", encoding="utf-8"
        )
        with self.assertRaises(ValidationError) as context:
            self.manager.read()
        self.assertIn("line 1", str(context.exception))

    def test_snapshot_rejects_invalid_proxy_url(self) -> None:
        self.manager.path.write_text("BB_HTTP_PROXY=not-a-url\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.manager.snapshot()

    def test_atomic_write_preserves_existing_mode(self) -> None:
        target = self.home / "SCOPE.md"
        target.write_text("old\n", encoding="utf-8")
        target.chmod(0o644)
        atomic_write(target, "new\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.assertEqual(target.read_text(encoding="utf-8"), "new\n")

    def test_atomic_write_honors_explicit_mode(self) -> None:
        target = self.home / "config.env"
        atomic_write(target, "BB_PROXY_MODE=direct\n", 0o600)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(target.read_text(encoding="utf-8"), "BB_PROXY_MODE=direct\n")

    def test_validation_rejects_credentials_and_relative_extra_path(self) -> None:
        with self.assertRaises(ValidationError):
            self.manager.configure(
                {"BB_HTTP_PROXY": "http://user:secret@127.0.0.1:7890"}
            )
        with self.assertRaises(ValidationError):
            self.manager.configure({"BB_EXTRA_PATH": "relative/bin"})
        with self.assertRaises(ValidationError):
            self.manager.configure({"BB_AGENT_LANGUAGE": "fr"})
        with self.assertRaises(ValidationError):
            self.manager.configure({"BB_NPM_REGISTRY": "http://registry.example"})

    def test_generated_environment_does_not_execute_config_syntax(self) -> None:
        marker = self.home / "must-not-exist"
        self.manager.path.write_text(
            "\n".join(
                (
                    'BB_PROXY_MODE="direct"',
                    'BB_HTTP_PROXY="http://127.0.0.1:7890"',
                    'BB_SOCKS_PROXY="socks5://127.0.0.1:7891"',
                    'BB_EXTRA_PATH="$(touch ' + str(marker) + ')"',
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.manager.path.chmod(0o600)
        RuntimeManager(self.paths).write_environment()
        subprocess.run(
            ["bash", "-c", f"source {self.paths.env_file!s}"],
            check=True,
            env={"HOME": str(self.home)},
        )
        self.assertFalse(marker.exists())

    def test_noninteractive_prompt_has_explicit_error(self) -> None:
        with (
            patch("sys.stdin.isatty", return_value=False),
            self.assertRaises(StackError),
        ):
            self.manager.interactive_updates()


if __name__ == "__main__":
    unittest.main(verbosity=2)
