#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.cli import build_parser, command, emit, main
from bb_stack.errors import StackError
from bb_stack.paths import StackPaths


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-cli-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.parser = build_parser()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_command(self, arguments: list[str]) -> int:
        args = self.parser.parse_args(arguments)
        with redirect_stdout(StringIO()):
            return command(args, self.paths)

    def test_parser_accepts_every_command_family(self) -> None:
        cases = (
            ["paths", "--json"],
            ["validate", "--json"],
            ["configure", "--show"],
            ["portable", "export", "/tmp/portable.yaml"],
            ["eval", "contracts"],
            ["status"],
            ["mail", "list"],
            ["filecodebox", "upload", "/tmp/artifact.zip"],
            ["bootstrap", "--dry-run"],
            ["workspace", "status"],
            ["browser", "status"],
            ["data", "status"],
            ["profile", "list"],
            ["new", "fixture", "https://example.invalid"],
            ["engagement", "list"],
            ["skills", "list"],
            ["mcp", "probe", "/tmp/mcp.json"],
            ["doctor"],
            ["keysmith", "status"],
            ["updates", "check"],
            ["launch", "--dry-run"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    self.parser.parse_args(arguments).command, arguments[0]
                )

    def test_emit_supports_text_and_structured_output(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            emit("plain")
            emit({"ready": True})
        self.assertIn("plain", output.getvalue())
        self.assertIn('"ready": true', output.getvalue())

    def test_data_dispatch_covers_status_ensure_path_and_update(self) -> None:
        manager = MagicMock()
        manager.status.return_value = {"ready": False}
        manager.ensure.return_value = {"state": "installed"}
        manager.ensure_profile.return_value = {"state": "installed"}
        manager.path.return_value = Path("/managed/data")
        manager.update_check.return_value = {"state": "current"}
        with patch("bb_stack.cli.DataManager", return_value=manager):
            self.assertEqual(self.run_command(["data", "status", "--strict"]), 1)
            self.assertEqual(
                self.run_command(["data", "ensure", "seclists", "--dry-run"]), 0
            )
            self.assertEqual(
                self.run_command(["data", "ensure", "--profile", "ctf-web"]), 0
            )
            self.assertEqual(self.run_command(["data", "path", "seclists"]), 0)
            self.assertEqual(
                self.run_command(["data", "update", "seclists", "--check"]), 0
            )
            with self.assertRaisesRegex(StackError, "exactly one"):
                self.run_command(["data", "ensure"])
        manager.ensure.assert_called_once()
        manager.ensure_profile.assert_called_once()

    def test_updates_dispatch_covers_every_transaction(self) -> None:
        manager = MagicMock()
        for method in (
            "check",
            "stage",
            "validate_candidates",
            "approve",
            "promote",
            "rollback",
        ):
            getattr(manager, method).return_value = {"operation": method}
        cases = (
            ["updates", "check", "--skills"],
            ["updates", "stage", "skill.fixture"],
            ["updates", "validate", "skill.fixture"],
            [
                "updates",
                "approve",
                "skill.fixture",
                "--reviewer",
                "Reviewer",
                "--note",
                "reviewed",
            ],
            ["updates", "promote", "skill.fixture"],
            ["updates", "rollback", "skill.fixture"],
        )
        with patch("bb_stack.cli.UpdateManager", return_value=manager):
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    self.assertEqual(self.run_command(arguments), 0)
        manager.check.assert_called_once_with({"skills"}, None)
        manager.approve.assert_called_once_with(
            "skill.fixture", reviewer="Reviewer", note="reviewed"
        )

    def test_keysmith_and_browser_dispatch(self) -> None:
        keysmith = MagicMock()
        keysmith.fetch.return_value = {"state": "fetched"}
        keysmith.install.return_value = {"state": "installed"}
        keysmith.status.return_value = {"state": "ready"}
        keysmith.uninstall.return_value = {"state": "removed"}
        keysmith_cases = (
            ["keysmith", "fetch"],
            ["keysmith", "install", "--profile", "ctf-replacement", "--yes"],
            ["keysmith", "status"],
            ["keysmith", "uninstall", "--yes"],
        )
        with patch("bb_stack.cli.KeysmithAdapter", return_value=keysmith):
            for arguments in keysmith_cases:
                self.assertEqual(self.run_command(arguments), 0)

        browser = MagicMock()
        browser.status.return_value = {"state": "stopped"}
        browser.stop.return_value = {"state": "stopped"}
        with patch("bb_stack.cli.BrowserRuntimeManager", return_value=browser):
            self.assertEqual(self.run_command(["browser", "status"]), 0)
            self.assertEqual(self.run_command(["browser", "stop"]), 0)
        browser.status.assert_called_once_with(None)
        browser.stop.assert_called_once_with(None)

    def test_main_converts_expected_errors_to_exit_two(self) -> None:
        parsed = self.parser.parse_args(["paths"])
        stderr = StringIO()
        with (
            patch("bb_stack.cli.build_parser") as parser,
            patch("bb_stack.cli.StackPaths.discover", return_value=self.paths),
            patch("bb_stack.cli.command", side_effect=StackError("fixture failure")),
            redirect_stderr(stderr),
        ):
            parser.return_value.parse_args.return_value = parsed
            self.assertEqual(main(), 2)
        self.assertIn("fixture failure", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
