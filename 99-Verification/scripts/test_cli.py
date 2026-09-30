#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.cli import (
    _reload_command,
    build_parser,
    command,
    default_capability_profile,
    emit,
    main,
)
from bb_stack.capabilities import CapabilityRegistry
from bb_stack.engagement import EngagementManager
from bb_stack.errors import StackError, ValidationError
from bb_stack.paths import StackPaths
from bb_stack.profiles import ProfileRegistry
from bb_stack.skills import SkillRegistry
from test_support import isolated_stack_source


def _capabilities_ready():
    """Clear the capability gate while keeping the real MCP render."""
    real_doctor = CapabilityRegistry.doctor

    def doctor(self, profile_name, artifact_root=None):
        report = real_doctor(self, profile_name, artifact_root)
        report["ready"] = True
        report["missing_required"] = []
        return report

    return patch.object(CapabilityRegistry, "doctor", doctor)


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
        return self.run_paths_command(arguments, self.paths)

    def run_paths_command(self, arguments: list[str], paths: StackPaths) -> int:
        args = self.parser.parse_args(arguments)
        with redirect_stdout(StringIO()):
            return command(args, paths)

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
            ["recon", "status"],
            ["tool", "install", "waybackurls", "--dry-run"],
            ["skills", "list"],
            ["mcp", "probe", "/tmp/mcp.json"],
            ["doctor"],
            ["keysmith", "status"],
            ["update", "--profile", "minimal", "--check"],
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

    def test_update_dispatches_stack_source_refresh(self) -> None:
        manager = MagicMock()
        manager.update.return_value = {"state": "updated"}
        with patch("bb_stack.cli.SelfUpdateManager", return_value=manager):
            self.assertEqual(
                self.run_command(
                    [
                        "update",
                        "--profile",
                        "web",
                        "--remote",
                        "upstream",
                        "--branch",
                        "stable",
                        "--skip-tools",
                        "--json",
                    ]
                ),
                0,
            )
        manager.update.assert_called_once_with(
            profile="web",
            remote="upstream",
            branch="stable",
            check_only=False,
            dry_run=False,
            include_optional=False,
            skip_tools=True,
            skip_node=False,
            skip_skills=False,
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

    def test_recon_dispatch_covers_every_action(self) -> None:
        manager = MagicMock()
        manager.run.return_value = {"state": "baseline_completed"}
        manager.resume.return_value = {"state": "baseline_completed"}
        manager.status.return_value = {"state": "needs_agent_decision"}
        manager.rerun.return_value = {"state": "baseline_completed"}
        manager.expand.return_value = {"id": "B-001-api"}
        manager.close.return_value = {"state": "closed_with_gaps"}
        cases = (
            ["recon", "run", "fixture", "--mode", "baseline"],
            ["recon", "resume", "fixture"],
            ["recon", "status", "fixture"],
            ["recon", "rerun", "fixture", "--stage", "passive-assets", "--cascade", "--force"],
            [
                "recon",
                "expand",
                "fixture",
                "--area",
                "api",
                "--target",
                "https://example.invalid/graphql",
                "--reason",
                "GraphQL signal",
                "--signal",
                "S-001",
            ],
            [
                "recon",
                "close",
                "fixture",
                "--reason",
                "Coverage reviewed",
                "--accept-gap",
                "javascript-api.jsluice",
                "--accept-signal",
                "S-002",
                "--accept-candidate",
                "C-0123456789ab",
            ],
        )
        with (
            patch("bb_stack.cli.ReconManager", return_value=manager),
            patch("bb_stack.cli.StackPaths.engagement", return_value=Path("/tmp/fixture")),
        ):
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    self.assertEqual(self.run_command(arguments), 0)
        manager.run.assert_called_once_with(Path("/tmp/fixture"), mode="baseline")
        manager.resume.assert_called_once_with(Path("/tmp/fixture"))
        manager.status.assert_called_once_with(Path("/tmp/fixture"))
        manager.rerun.assert_called_once_with(
            Path("/tmp/fixture"),
            stage_id="passive-assets",
            cascade=True,
            force=True,
        )
        manager.expand.assert_called_once_with(
            Path("/tmp/fixture"),
            area="api",
            target="https://example.invalid/graphql",
            reason="GraphQL signal",
            signal_id="S-001",
        )
        manager.close.assert_called_once_with(
            Path("/tmp/fixture"),
            reason="Coverage reviewed",
            accept_gaps=["javascript-api.jsluice"],
            accept_signals=["S-002"],
            accept_candidates=["C-0123456789ab"],
        )

    def test_tool_install_dispatches_named_installer(self) -> None:
        manager = MagicMock()
        manager.install_named_tools.return_value = [
            {"component": "tool:waybackurls", "state": "planned"}
        ]
        with patch("bb_stack.cli.RuntimeManager", return_value=manager):
            self.assertEqual(
                self.run_command(
                    ["tool", "install", "waybackurls", "gau", "--dry-run"]
                ),
                0,
            )
        manager.install_named_tools.assert_called_once_with(
            ["waybackurls", "gau"], dry_run=True
        )

    @contextmanager
    def pinned_validate(self, detected: dict[str, str | None]):
        """`validate` with the registries stubbed and runtime detection pinned."""
        with ExitStack() as stack:
            runtime = stack.enter_context(
                patch("bb_stack.cli.RuntimeManager")
            ).return_value
            runtime.validate_config.return_value = {}
            profiles = stack.enter_context(
                patch("bb_stack.cli.ProfileRegistry")
            ).return_value
            profiles.validate_all.return_value = []
            skills = stack.enter_context(
                patch("bb_stack.cli.SkillRegistry")
            ).return_value
            skills.validate_all.return_value = []
            capabilities = stack.enter_context(
                patch("bb_stack.cli.CapabilityRegistry")
            ).return_value
            capabilities.validate_all.return_value = []
            updates = stack.enter_context(
                patch("bb_stack.cli.UpdateManager")
            ).return_value
            updates.validate_catalog.return_value = {}
            stack.enter_context(
                patch("bb_stack.cli.runtime_versions", return_value=detected)
            )
            yield

    def test_launch_dispatches_the_selected_backend(self) -> None:
        engagements = EngagementManager(self.paths)
        root = engagements.create(
            "cli-omp",
            "https://example.invalid",
            workflow="ctf",
            platform="standalone-ctf",
        )
        omp = str(self.paths.home / "omp-stub")
        output = StringIO()
        with (
            patch.object(SkillRegistry, "status", return_value=[]),
            _capabilities_ready(),
            patch.dict(os.environ, {"OMP_BIN": omp}),
            redirect_stdout(output),
        ):
            args = self.parser.parse_args(
                [
                    "launch",
                    "--profile",
                    "ctf-quick",
                    "--engagement",
                    str(root),
                    "--backend",
                    "omp",
                    "--dry-run",
                ]
            )
            self.assertEqual(command(args, self.paths), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["backend"], "omp")
        self.assertEqual(report["command"][0], omp)
        self.assertIn("--append-system-prompt", report["command"])

    def test_parser_profile_defaults_come_from_the_stack_manifest(self) -> None:
        source = isolated_stack_source(
            ROOT,
            Path(self.temporary.name) / "source",
            manifest=(
                "schema_version: 1\n"
                "defaults:\n"
                "  profile: lab-replacement\n"
                "  capability_profiles:\n"
                "    lab-replacement: lab-replacement\n"
                "    minimal: lab-replacement\n"
            ),
        )
        with patch.dict(os.environ, {"BB_STACK_ROOT": str(source)}):
            parser = build_parser()
            for arguments in (["status"], ["bootstrap"], ["doctor"]):
                with self.subTest(arguments=arguments):
                    self.assertEqual(parser.parse_args(arguments).profile, "minimal")
            for arguments in (["launch"], ["eval", "agent"]):
                with self.subTest(arguments=arguments):
                    self.assertEqual(
                        parser.parse_args(arguments).profile, "lab-replacement"
                    )

    def test_capability_default_requires_a_unique_manifest_mapping(self) -> None:
        ambiguous = {
            "defaults": {
                "profile": "shared",
                "capability_profiles": {"ctf-web": "shared", "web": "shared"},
            }
        }
        self.assertEqual(default_capability_profile(ambiguous), "ctf-web")
        unique = {
            "defaults": {
                "profile": "shared",
                "capability_profiles": {"ctf-web": "other", "web": "shared"},
            }
        }
        self.assertEqual(default_capability_profile(unique), "web")

    def test_configure_reload_hint_quotes_the_environment_file(self) -> None:
        base = Path(self.temporary.name) / "home with spaces"
        paths = StackPaths(ROOT, base, base / "work", base / "config", base / ".claude")
        configuration = MagicMock()
        configuration.configure.return_value = {}
        runtime = MagicMock()
        runtime.write_environment.return_value = paths.env_file
        workspace = MagicMock()
        workspace.initialize.return_value = {}
        output = StringIO()
        with (
            patch("bb_stack.cli.ConfigurationManager", return_value=configuration),
            patch("bb_stack.cli.RuntimeManager", return_value=runtime),
            patch("bb_stack.cli.WorkspaceManager", return_value=workspace),
            redirect_stdout(output),
        ):
            args = self.parser.parse_args(["configure", "--proxy-mode", "direct", "--json"])
            self.assertEqual(command(args, paths), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["reload"], "source '" + str(paths.env_file) + "'")
        self.assertEqual(_reload_command(paths), report["reload"])

    def test_validate_rejects_a_version_file_that_disagrees_with_the_package(
        self,
    ) -> None:
        source = isolated_stack_source(ROOT, Path(self.temporary.name) / "versioned")
        base = Path(self.temporary.name)
        paths = StackPaths(
            source,
            base,
            base / "work",
            base / "config",
            base / ".claude",
        )
        detected = {"python": "3.12.13", "node": "v22.23.2", "claude_code": "2.1.223"}
        version_file = source / "VERSION"
        version_file.write_text("0.0.1\n", encoding="utf-8")
        with self.pinned_validate(detected):
            with self.assertRaisesRegex(ValidationError, "0.0.1"):
                self.run_paths_command(["validate"], paths)
            version_file.unlink()
            self.assertEqual(self.run_paths_command(["validate"], paths), 0)

    def test_validate_reports_minimum_runtime_findings(self) -> None:
        below = {"python": "3.10.7", "node": "v22.23.2", "claude_code": "2.1.223"}
        with self.pinned_validate(below):
            with self.assertRaisesRegex(
                ValidationError, "minimum runtime not satisfied"
            ) as caught:
                self.run_command(["validate"])
        message = str(caught.exception)
        self.assertIn("python", message)
        self.assertIn("3.11", message)
        self.assertNotIn("claude_code", message)

        for detected, expected in (
            (
                {"python": "3.12.13", "node": "v22.23.2", "claude_code": None},
                {"python": "ok", "node": "ok", "claude_code": "missing"},
            ),
            (
                {
                    "python": "3.12.13",
                    "node": "not-a-version",
                    "claude_code": "2.1.223 (Claude Code)",
                },
                {"python": "ok", "node": "unknown", "claude_code": "ok"},
            ),
        ):
            with self.subTest(detected=detected):
                output = StringIO()
                with self.pinned_validate(detected), redirect_stdout(output):
                    args = self.parser.parse_args(["validate", "--json"])
                    self.assertEqual(command(args, self.paths), 0)
                minimum = json.loads(output.getvalue())["minimum_runtime"]
                self.assertTrue(minimum["satisfied"])
                self.assertEqual(
                    {check["tool"]: check["status"] for check in minimum["checks"]},
                    expected,
                )

    def test_main_converts_expected_errors_to_exit_two(self) -> None:
        parsed = self.parser.parse_args(["paths"])
        stderr = StringIO()
        with (
            patch("bb_stack.cli.build_parser") as parser,
            patch("bb_stack.cli.StackPaths.discover", return_value=self.paths),
            patch("bb_stack.cli.command", side_effect=StackError("fixture failure")),
            patch.dict(os.environ, {"BB_STACK_DEBUG": "0"}),
            redirect_stderr(stderr),
        ):
            parser.return_value.parse_args.return_value = parsed
            self.assertEqual(main(), 2)
        self.assertIn("fixture failure", stderr.getvalue())

    def test_main_labels_unexpected_errors_and_points_at_validate(self) -> None:
        parsed = self.parser.parse_args(["paths"])
        failure = KeyError("capability_profiles")
        stderr = StringIO()
        with (
            patch("bb_stack.cli.build_parser") as parser,
            patch("bb_stack.cli.StackPaths.discover", return_value=self.paths),
            patch("bb_stack.cli.command", side_effect=failure),
            patch.dict(os.environ, {"BB_STACK_DEBUG": "0"}),
            redirect_stderr(stderr),
        ):
            parser.return_value.parse_args.return_value = parsed
            self.assertEqual(main(), 2)
        message = stderr.getvalue()
        self.assertIn("KeyError: 'capability_profiles'", message)
        self.assertIn("`bb-stack validate`", message)

    def test_main_reraises_instead_of_converting_when_debugging(self) -> None:
        parsed = self.parser.parse_args(["paths"])
        for failure in (
            StackError("fixture failure"),
            KeyError("capability_profiles"),
        ):
            with (
                self.subTest(error=type(failure).__name__),
                patch("bb_stack.cli.build_parser") as parser,
                patch("bb_stack.cli.StackPaths.discover", return_value=self.paths),
                patch("bb_stack.cli.command", side_effect=failure),
                patch.dict(os.environ, {"BB_STACK_DEBUG": "1"}),
            ):
                parser.return_value.parse_args.return_value = parsed
                with self.assertRaises(type(failure)):
                    main()

    def test_main_treats_a_blank_debug_flag_as_disabled(self) -> None:
        parsed = self.parser.parse_args(["paths"])
        failure = KeyError("capability_profiles")
        stderr = StringIO()
        with (
            patch("bb_stack.cli.build_parser") as parser,
            patch("bb_stack.cli.StackPaths.discover", return_value=self.paths),
            patch("bb_stack.cli.command", side_effect=failure),
            patch.dict(os.environ, {"BB_STACK_DEBUG": ""}),
            redirect_stderr(stderr),
        ):
            parser.return_value.parse_args.return_value = parsed
            self.assertEqual(main(), 2)
        self.assertIn("KeyError", stderr.getvalue())


class ManifestResolutionTests(unittest.TestCase):
    """`stack.yaml` resolution for paths, profiles, and tool discovery.

    These live beside the CLI tests because this shard owns `test_cli.py` only;
    every module under test is the one the CLI resolves its defaults from.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-manifest-")
        self.base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            self.base,
            self.base / "work",
            self.base / "config",
            self.base / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registry_directories_come_from_the_declared_manifest(self) -> None:
        source = isolated_stack_source(
            ROOT,
            self.base / "source",
            manifest=(
                "schema_version: 1\n"
                "paths:\n"
                "  runtime: .custom-runtime\n"
                "  global_prompt: prompts\n"
                "registries:\n"
                "  runtime_profiles: custom/profiles\n"
                "  platforms: custom/platforms\n"
                "  skill_profiles: custom/skills\n"
                "  capability_profiles: custom/capabilities\n"
            ),
        )
        paths = StackPaths(
            source,
            self.base,
            self.base / "work",
            self.base / "config",
            self.base / ".claude",
        )
        registry = ProfileRegistry(paths)
        self.assertEqual(registry.profile_dir, source / "custom" / "profiles")
        self.assertEqual(registry.platform_dir, source / "custom" / "platforms")
        self.assertEqual(registry.skill_profile_dir, source / "custom" / "skills")
        self.assertEqual(
            registry.capability_profile_dir, source / "custom" / "capabilities"
        )
        self.assertEqual(registry.workflow_dir, source / "custom" / "workflows")
        self.assertEqual(registry.global_prompt_dir, source / "prompts")
        self.assertEqual(paths.runtime, source / ".custom-runtime")

    def test_empty_skill_profile_registry_is_not_a_missing_registry(self) -> None:
        profiles = self.base / "empty-profiles"
        profiles.mkdir()
        with self.assertRaises(ValidationError):
            ProfileRegistry._require_named_file(
                profiles,
                "ctf-web",
                ".yaml",
                "Skill profile",
                allow_missing_registry=True,
            )
        absent = self.base / "absent-profiles"
        self.assertEqual(
            ProfileRegistry._require_named_file(
                absent,
                "ctf-web",
                ".yaml",
                "Skill profile",
                allow_missing_registry=True,
            ),
            absent / "ctf-web.yaml",
        )

    def test_environment_drops_an_inherited_artifact_root(self) -> None:
        with patch.dict(os.environ, {"BB_ARTIFACT_ROOT": "/stale/artifacts"}):
            self.assertNotIn("BB_ARTIFACT_ROOT", self.paths.environment())
        artifact_root = self.base / "artifacts"
        self.assertEqual(
            self.paths.environment(artifact_root)["BB_ARTIFACT_ROOT"],
            str(artifact_root.resolve()),
        )

    def test_environment_drops_an_inherited_claude_config_dir(self) -> None:
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/stale/claude"}):
            self.assertNotIn("CLAUDE_CONFIG_DIR", self.paths.environment())
        explicit = StackPaths(
            ROOT,
            self.base,
            self.base / "work",
            self.base / "config",
            self.base / ".claude",
            True,
        )
        self.assertEqual(
            explicit.environment()["CLAUDE_CONFIG_DIR"], str(self.base / ".claude")
        )

    def test_runtime_path_orders_nvm_versions_numerically(self) -> None:
        versions = self.base / ".nvm" / "versions" / "node"
        for version in ("v9.11.2", "v10.4.0", "v22.23.2"):
            (versions / version / "bin").mkdir(parents=True)
        ordered = [
            entry
            for entry in self.paths.runtime_path().split(os.pathsep)
            if ".nvm" in entry
        ]
        self.assertEqual(
            ordered,
            [
                str(versions / "v22.23.2" / "bin"),
                str(versions / "v10.4.0" / "bin"),
                str(versions / "v9.11.2" / "bin"),
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
