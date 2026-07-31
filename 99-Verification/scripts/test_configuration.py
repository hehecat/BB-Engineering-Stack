#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.configuration import ConfigurationManager
from bb_stack.errors import StackError, ValidationError
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager


class ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-configuration-")
        self.home = Path(self.temporary.name) / "home"
        self.paths = StackPaths(
            ROOT,
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
            }
        )
        self.assertEqual(
            result["changed"],
            ["BB_AGENT_LANGUAGE", "BB_H1_USERNAME", "BB_PROXY_MODE"],
        )
        values = self.manager.read()
        self.assertEqual(values["CUSTOM_EXTENSION"], "value")
        self.assertEqual(values["BB_PROXY_MODE"], "mihomo")
        self.assertEqual(values["BB_AGENT_LANGUAGE"], "en")
        self.assertEqual(self.manager.path.stat().st_mode & 0o777, 0o600)

    def test_validation_rejects_credentials_and_relative_extra_path(self) -> None:
        with self.assertRaises(ValidationError):
            self.manager.configure(
                {"BB_HTTP_PROXY": "http://user:secret@127.0.0.1:7890"}
            )
        with self.assertRaises(ValidationError):
            self.manager.configure({"BB_EXTRA_PATH": "relative/bin"})
        with self.assertRaises(ValidationError):
            self.manager.configure({"BB_AGENT_LANGUAGE": "fr"})

    def test_generated_environment_does_not_execute_config_syntax(self) -> None:
        marker = self.home / "must-not-exist"
        self.manager.path.write_text(
            '\n'.join(
                (
                    'BB_PROXY_MODE="direct"',
                    'BB_HTTP_PROXY="http://127.0.0.1:7890"',
                    'BB_SOCKS_PROXY="socks5://127.0.0.1:7891"',
                    'BB_EXTRA_PATH="$(touch ' + str(marker) + ')"',
                    '',
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
        with patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(StackError):
                self.manager.interactive_updates()


if __name__ == "__main__":
    unittest.main(verbosity=2)
