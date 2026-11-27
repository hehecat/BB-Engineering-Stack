#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import CommandError, ValidationError
from bb_stack.paths import StackPaths
from bb_stack.runtime import (
    APT_TIMEOUT_SECONDS,
    BREW_TIMEOUT_SECONDS,
    BUILD_TIMEOUT_SECONDS,
    UV_TOOL_INSTALL_TIMEOUT_SECONDS,
    RuntimeManager,
)
from bb_stack.validation import validate
from test_support import isolated_stack_source


class RuntimeInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-installers-")
        base = Path(self.temporary.name)
        # launch() resolves the agent backend registry, so the temporary root
        # has to expose the real stack source tree rather than an empty dir.
        stack = isolated_stack_source(ROOT, base / "stack")
        self.paths = StackPaths(
            stack,
            base / "home",
            base / "work",
            base / "config",
            base / ".claude",
        )
        self.paths.runtime_bin.mkdir(parents=True)
        self.manager = RuntimeManager(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_archive_tree_installs_managed_executable(self) -> None:
        archive = Path(self.temporary.name) / "tool.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("bin/demo", "#!/bin/sh\nprintf demo\\n")
            handle.writestr("lib/data.txt", "fixture")
        spec = {
            "kind": "archive-tree",
            "checks": ["demo"],
            "format": "zip",
            "destination": str(self.paths.runtime / "tools" / "demo-1"),
            "executables": {"demo": "bin/demo"},
            "files": {},
        }
        with patch.object(self.manager, "_download_tool_archive", return_value=archive):
            self.manager._install_tool("demo", spec, {"PATH": "/usr/bin:/bin"})
        wrapper = self.paths.runtime_bin / "demo"
        self.assertTrue(wrapper.is_symlink())
        self.assertTrue(
            self.manager._tool_ready(spec, {"PATH": self.paths.runtime_path()})
        )

    def test_zip_traversal_is_rejected(self) -> None:
        archive = Path(self.temporary.name) / "escape.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escape", "unexpected")
        destination = Path(self.temporary.name) / "extract"
        destination.mkdir()
        with zipfile.ZipFile(archive) as handle, self.assertRaises(CommandError):
            RuntimeManager._safe_extract_zip(handle, destination)
        self.assertFalse((Path(self.temporary.name) / "escape").exists())

    def test_tar_relative_symlink_inside_destination_is_allowed(self) -> None:
        archive = Path(self.temporary.name) / "node.tar"
        payload = b"#!/usr/bin/env node\n"
        with tarfile.open(archive, "w") as handle:
            target = tarfile.TarInfo("node/lib/node_modules/npm/bin/npm-cli.js")
            target.size = len(payload)
            handle.addfile(target, __import__("io").BytesIO(payload))
            link = tarfile.TarInfo("node/bin/npm")
            link.type = tarfile.SYMTYPE
            link.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
            handle.addfile(link)

        destination = Path(self.temporary.name) / "node-extract"
        destination.mkdir()
        with tarfile.open(archive) as handle:
            RuntimeManager._safe_extract(handle, destination)

        npm = destination / "node" / "bin" / "npm"
        self.assertTrue(npm.is_symlink())
        self.assertEqual(
            npm.resolve(),
            (destination / "node/lib/node_modules/npm/bin/npm-cli.js").resolve(),
        )

    def test_tar_symlink_outside_destination_is_rejected(self) -> None:
        archive = Path(self.temporary.name) / "escape.tar"
        with tarfile.open(archive, "w") as handle:
            link = tarfile.TarInfo("node/bin/npm")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../../outside"
            handle.addfile(link)
        destination = Path(self.temporary.name) / "tar-extract"
        destination.mkdir()
        with tarfile.open(archive) as handle, self.assertRaises(CommandError):
            RuntimeManager._safe_extract(handle, destination)

    def test_deb_installer_uses_pinned_local_archive(self) -> None:
        archive = Path(self.temporary.name) / "tool.deb"
        archive.write_bytes(b"test-only")
        spec = {"kind": "deb", "checks": ["demo"], "files": {}}
        with (
            patch.object(self.manager, "_download_tool_archive", return_value=archive),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/apt-get"),
            patch("bb_stack.runtime.os.geteuid", return_value=1000),
            patch.object(self.manager, "_run") as run,
        ):
            self.manager._install_tool("demo", spec, {"PATH": "/usr/bin:/bin"})
        run.assert_called_once_with(
            ["sudo", "/usr/bin/apt-get", "install", "-y", str(archive)],
            env={"PATH": "/usr/bin:/bin"},
            timeout=APT_TIMEOUT_SECONDS,
        )

    def test_uv_tool_installs_into_stack_managed_directories(self) -> None:
        spec = {
            "kind": "uv-tool",
            "checks": ["demo"],
            "package": "demo==1.2.3",
            "python": "3.12",
        }
        env = {"PATH": self.paths.runtime_path()}
        with (
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/uv"),
            patch.object(self.manager, "_run") as run,
        ):
            self.manager._install_tool("demo", spec, env)
        expected_env = {
            **env,
            "UV_TOOL_BIN_DIR": str(self.paths.runtime_bin),
            "UV_TOOL_DIR": str(self.paths.runtime / "uv-tools"),
        }
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[:3], ["/usr/bin/uv", "tool", "install"])
        self.assertIn("demo==1.2.3", args)
        self.assertEqual(args[args.index("--python") + 1], "3.12")
        self.assertIn("--default-index", args)
        self.assertEqual(
            args[args.index("--default-index") + 1], self.manager._pypi_index()
        )
        self.assertEqual(run.call_args.kwargs["env"], expected_env)
        self.assertEqual(
            run.call_args.kwargs["timeout"], UV_TOOL_INSTALL_TIMEOUT_SECONDS
        )

    def test_git_build_creates_managed_executable(self) -> None:
        destination = self.paths.runtime / "tools" / "demo-1.0.0"
        spec = {
            "kind": "git-build",
            "checks": ["demo"],
            "repository": "https://example.invalid/demo.git",
            "revision": "a" * 40,
            "destination": str(destination),
            "build": ["make"],
            "executables": {"demo": "bin/demo"},
        }

        def prepare(*_: object) -> None:
            target = destination / "bin/demo"
            target.parent.mkdir(parents=True)
            target.write_text("#!/bin/sh\n", encoding="utf-8")

        with (
            patch.object(self.manager, "_install_git_data", side_effect=prepare),
            patch.object(self.manager, "_run") as run,
        ):
            self.manager._install_tool("demo", spec, {"PATH": "/usr/bin:/bin"})

        run.assert_called_once_with(
            ["make"],
            cwd=destination,
            env={"PATH": "/usr/bin:/bin"},
            timeout=BUILD_TIMEOUT_SECONDS,
        )
        wrapper = self.paths.runtime_bin / "demo"
        self.assertTrue(wrapper.is_symlink())
        self.assertEqual(wrapper.resolve(), (destination / "bin/demo").resolve())
        self.assertEqual(
            (destination / ".bb-stack-build-revision").read_text(encoding="utf-8"),
            "a" * 40 + "\n",
        )

    def test_bootstrap_dry_run_has_no_persistent_writes(self) -> None:
        base = Path(self.temporary.name) / "dry-run"
        stack = isolated_stack_source(ROOT, base / "stack")
        paths = StackPaths(
            stack,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        result = RuntimeManager(paths).bootstrap(
            "minimal",
            skip_tools=True,
            skip_node=True,
            skip_skills=True,
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertFalse(paths.runtime.exists())
        self.assertFalse(paths.work_root.exists())
        self.assertFalse(paths.config_home.exists())

    def test_bootstrap_launcher_dry_run_survives_missing_runtime_dependencies(
        self,
    ) -> None:
        base = Path(self.temporary.name) / "launcher-dry-run"
        stack = isolated_stack_source(ROOT, base / "stack")
        home = base / "home"
        env = {
            "HOME": str(home),
            "BB_STACK_ROOT": str(stack),
            "BB_CONFIG_HOME": str(base / "config"),
            "BB_WORK_ROOT": str(base / "work"),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        }

        completed = subprocess.run(
            [
                str(stack / "00-L0-Runtime/bin/bootstrap"),
                "--profile",
                "minimal",
                "--dry-run",
                "--json",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["runtime_bootstrap_required"])
        self.assertFalse((stack / ".runtime").exists())

    def test_bootstrap_runtime_readiness_requires_pip(self) -> None:
        base = Path(self.temporary.name) / "launcher-no-pip"
        stack = isolated_stack_source(ROOT, base / "stack")
        python = stack / ".runtime/venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/bin/sh\n"
            'case "$*" in\n'
            '  *"import pip,"*) exit 1 ;;\n'
            "  *) exit 0 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        env = {
            "HOME": str(base / "home"),
            "BB_STACK_ROOT": str(stack),
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        }

        completed = subprocess.run(
            [str(stack / "00-L0-Runtime/bin/bootstrap"), "--dry-run", "--json"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["runtime_bootstrap_required"])

    def test_bootstrap_records_the_profile_after_success(self) -> None:
        workspace = {
            "root": str(self.paths.work_root),
            "default_entry": f"cd {self.paths.work_root} && claude",
        }
        with (
            patch("bb_stack.runtime.CapabilityRegistry.profile"),
            patch("bb_stack.runtime.SkillRegistry.profile"),
            patch.object(
                self.manager,
                "_python_runtime",
                return_value={"component": "python-runtime", "state": "ready"},
            ),
            patch.object(self.manager, "_install_wrappers", return_value=[]),
            patch.object(self.manager, "_write_env"),
            patch(
                "bb_stack.runtime.WorkspaceManager.initialize", return_value=workspace
            ),
        ):
            self.manager.bootstrap(
                "web",
                skip_tools=True,
                skip_node=True,
                skip_skills=True,
            )

        state = json.loads(
            (self.paths.config_home / "install.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state, {"schema_version": 1, "profile": "web"})

    def test_auto_npm_registry_prefers_official_then_falls_back(self) -> None:
        self.assertEqual(
            self.manager.npm_registry_candidates("auto"),
            [
                "https://registry.npmjs.org",
                "https://registry.npmmirror.com",
            ],
        )
        self.assertEqual(
            self.manager.npm_registry_candidates("npmmirror"),
            ["https://registry.npmmirror.com"],
        )
        with patch.object(
            self.manager,
            "_npm_registry_latency",
            side_effect=lambda value: 0.1 if value.endswith("npmmirror.com") else 0.5,
        ):
            self.assertEqual(
                self.manager.available_npm_registries("auto"),
                [
                    "https://registry.npmmirror.com",
                    "https://registry.npmjs.org",
                ],
            )
        with patch.object(
            self.manager,
            "_npm_registry_latency",
            side_effect=lambda value: 0.1 if value.endswith("npmmirror.com") else None,
        ):
            self.assertEqual(
                self.manager.resolve_npm_registry(),
                "https://registry.npmmirror.com",
            )

    def test_node_toolchain_rejects_unsupported_major(self) -> None:
        config = {"minimum_major": 22, "maximum_major": 22}
        with patch(
            "bb_stack.runtime.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["node", "--version"], 0, "v24.13.1\n"
            ),
        ):
            self.assertFalse(
                self.manager._toolchain_version_ready("node", "/usr/bin/node", config)
            )
        with patch(
            "bb_stack.runtime.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["node", "--version"], 0, "v22.23.2\n"
            ),
        ):
            self.assertTrue(
                self.manager._toolchain_version_ready("node", "/usr/bin/node", config)
            )

    def test_git_data_retries_and_cleans_partial_clone(self) -> None:
        destination = self.paths.runtime / "data" / "fixture"
        spec = {
            "kind": "git-data",
            "checks": [],
            "repository": "https://example.invalid/fixture.git",
            "revision": "a" * 40,
            "destination": str(destination),
            "sparse_paths": ["Discovery/Web-Content"],
            "network_timeout_seconds": 45,
            "retry_attempts": 3,
        }
        fetch_attempts = 0
        fetch_timeouts: list[int | None] = []

        def run(command: list[str], **kwargs: object) -> None:
            nonlocal fetch_attempts
            if "init" in command:
                (destination / ".git").mkdir(parents=True)
            if "fetch" in command:
                fetch_attempts += 1
                fetch_timeouts.append(kwargs.get("timeout"))
                if fetch_attempts == 1:
                    raise CommandError("transient clone failure")

        with (
            patch.object(self.manager, "_run", side_effect=run),
            patch("bb_stack.runtime.time.sleep") as sleep,
        ):
            self.manager._install_tool("fixture", spec, {"PATH": "/usr/bin:/bin"})

        self.assertEqual(fetch_attempts, 2)
        self.assertEqual(fetch_timeouts, [45, 45])
        sleep.assert_called_once_with(2)
        self.assertTrue((destination / ".git").is_dir())
        self.assertFalse(destination.with_name(".fixture.bb-stack-installing").exists())

    def test_git_data_preserves_unknown_existing_directory(self) -> None:
        destination = self.paths.runtime / "data" / "fixture"
        destination.mkdir(parents=True)
        spec = {
            "kind": "git-data",
            "checks": [],
            "repository": "https://example.invalid/fixture.git",
            "revision": "a" * 40,
            "destination": str(destination),
        }
        with self.assertRaises(CommandError):
            self.manager._install_tool("fixture", spec, {"PATH": "/usr/bin:/bin"})
        self.assertTrue(destination.is_dir())

    def test_tool_install_replaces_inherited_proxy_with_uppercase_only(self) -> None:
        document = {
            "profiles": {"fixture": {"required": ["demo"], "optional": []}},
            "installers": {
                "demo": {
                    "kind": "git-data",
                    "checks": [],
                    "repository": "https://example.invalid/demo.git",
                    "revision": "a" * 40,
                    "destination": str(self.paths.runtime / "data" / "demo"),
                }
            },
        }
        machine = {
            "BB_PROXY_MODE": "mihomo",
            "BB_HTTP_PROXY": "http://127.0.0.1:17890",
            "BB_SOCKS_PROXY": "socks5://127.0.0.1:17891",
        }
        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective",
                return_value=machine,
            ),
            patch.dict(
                os.environ,
                {
                    "http_proxy": "http://stale.invalid",
                    "HTTPS_PROXY": "http://old.invalid",
                },
                clear=False,
            ),
            patch.object(self.manager, "_tool_ready", side_effect=[False, True]),
            patch.object(self.manager, "_install_tool") as install,
        ):
            result = self.manager.install_tools("fixture", False, dry_run=False)

        self.assertEqual(result, [{"component": "tool:demo", "state": "installed"}])
        env = install.call_args.args[2]
        self.assertEqual(env["HTTP_PROXY"], machine["BB_HTTP_PROXY"])
        self.assertEqual(env["HTTPS_PROXY"], machine["BB_HTTP_PROXY"])
        self.assertEqual(env["ALL_PROXY"], machine["BB_SOCKS_PROXY"])
        # Only the uppercase spelling is written back -- it is what every client
        # checked reads -- and clearing both spellings first is what makes the
        # stale inherited values above disappear rather than survive alongside.
        for name in ("http_proxy", "https_proxy", "all_proxy"):
            self.assertNotIn(name, env)

    def test_run_and_registry_helpers_handle_failures_and_malformed_state(self) -> None:
        with patch("bb_stack.runtime.subprocess.run") as run:
            self.manager._run(["fixture"], timeout=3)
        run.assert_called_once()

        with (
            patch(
                "bb_stack.runtime.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["fixture"], 3),
            ),
            self.assertRaisesRegex(CommandError, "command failed"),
        ):
            self.manager._run(["fixture"], timeout=3)

        state = Path(self.temporary.name) / "registry.json"
        self.assertEqual(self.manager._npm_registry_state(state), {})
        state.write_text("not-json", encoding="utf-8")
        self.assertEqual(self.manager._npm_registry_state(state), {})
        state.write_text("[]", encoding="utf-8")
        self.assertEqual(self.manager._npm_registry_state(state), {})
        state.write_text(
            json.dumps({"configured": "auto", "resolved": 42, "extra": "ignored"}),
            encoding="utf-8",
        )
        self.assertEqual(
            self.manager._npm_registry_state(state), {"configured": "auto"}
        )

    def test_npm_latency_accepts_success_and_rejects_network_failures(self) -> None:
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with (
            patch("bb_stack.runtime.urlopen", return_value=response),
            patch("bb_stack.runtime.time.monotonic", side_effect=[10.0, 10.25]),
        ):
            self.assertEqual(
                self.manager._npm_registry_latency("https://npm.test"), 0.25
            )
        response.status = 500
        with patch("bb_stack.runtime.urlopen", return_value=response):
            self.assertIsNone(self.manager._npm_registry_latency("https://npm.test"))
        with patch("bb_stack.runtime.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(self.manager._npm_registry_latency("https://npm.test"))

    def test_tool_ready_covers_git_service_archive_and_post_check(self) -> None:
        env = {"PATH": "/usr/bin:/bin"}
        destination = self.paths.runtime / "data" / "fixture"
        (destination / ".git").mkdir(parents=True)
        git_spec = {
            "kind": "git-data",
            "destination": str(destination),
            "revision": "a" * 40,
            "sparse_paths": ["Discovery"],
        }
        revision = subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{'a' * 40}\n", stderr=""
        )
        sparse = subprocess.CompletedProcess(
            ["git"], 0, stdout="Discovery\n", stderr=""
        )
        with patch("bb_stack.runtime.subprocess.run", side_effect=[revision, sparse]):
            self.assertTrue(self.manager._tool_ready(git_spec, env))
        mismatch = subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{'b' * 40}\n", stderr=""
        )
        with patch("bb_stack.runtime.subprocess.run", return_value=mismatch):
            self.assertFalse(self.manager._tool_ready(git_spec, env))

        service = {"kind": "service", "host": "127.0.0.1", "port": 1}
        with patch("bb_stack.runtime.socket.create_connection"):
            self.assertTrue(self.manager._tool_ready(service, env))
        with patch(
            "bb_stack.runtime.socket.create_connection", side_effect=OSError("closed")
        ):
            self.assertFalse(self.manager._tool_ready(service, env))

        archive = self.paths.runtime / "tools" / "fixture"
        executable = archive / "bin" / "demo"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        wrapper = self.paths.runtime_bin / "demo"
        wrapper.symlink_to(executable)
        archive_spec = {
            "kind": "archive-tree",
            "destination": str(archive),
            "executables": {"demo": "bin/demo"},
        }
        self.assertTrue(self.manager._tool_ready(archive_spec, env))
        wrapper.unlink()
        self.assertFalse(self.manager._tool_ready(archive_spec, env))

        post_check = Path(self.temporary.name) / "post-check"
        post_check.touch()
        with patch("bb_stack.runtime.shutil.which", return_value="/bin/demo"):
            self.assertTrue(
                self.manager._tool_ready(
                    {"kind": "go", "checks": ["demo"], "post_check": str(post_check)},
                    env,
                )
            )

    def test_install_tool_dispatch_and_post_install_guards(self) -> None:
        env = {"PATH": "/usr/bin:/bin"}
        with (
            patch("bb_stack.runtime.shutil.which", return_value=None),
            self.assertRaisesRegex(CommandError, "Go is required"),
        ):
            self.manager._install_tool(
                "demo", {"kind": "go", "package": "example/demo@v1"}, env
            )
        with self.assertRaisesRegex(CommandError, "not running"):
            self.manager._install_tool("demo", {"kind": "service"}, env)
        with self.assertRaisesRegex(CommandError, "unsupported installer"):
            self.manager._install_tool("demo", {"kind": "unknown"}, env)

        spec = {
            "kind": "go",
            "package": "example/demo@v1",
            "post_install": ["demo", "setup"],
            "post_check": str(Path(self.temporary.name) / "missing"),
        }
        with (
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/go"),
            patch.object(self.manager, "_run") as run,
        ):
            self.manager._install_tool("demo", spec, env)
        self.assertEqual(run.call_count, 2)

    def test_install_tools_batches_apt_and_rejects_unknown_profile(self) -> None:
        document = {
            "profiles": {"fixture": {"required": ["first", "second"], "optional": []}},
            "installers": {
                "first": {"kind": "apt", "packages": ["one"], "checks": ["one"]},
                "second": {
                    "kind": "apt",
                    "packages": ["two", "one"],
                    "checks": ["two"],
                },
            },
        }
        machine = {
            "BB_PROXY_MODE": "direct",
            "BB_HTTP_PROXY": "",
            "BB_SOCKS_PROXY": "",
        }
        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective", return_value=machine
            ),
            self.assertRaisesRegex(ValidationError, "unknown tool profile"),
        ):
            self.manager.install_tools("missing", False, dry_run=True)

        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective", return_value=machine
            ),
            patch("bb_stack.runtime.platform.system", return_value="Linux"),
            patch.object(
                self.manager, "_tool_ready", side_effect=[False, False, True, True]
            ),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/apt-get"),
            patch("bb_stack.runtime.os.geteuid", return_value=0),
            patch.object(self.manager, "_run") as run,
        ):
            result = self.manager.install_tools("fixture", False, dry_run=False)

        self.assertEqual([item["state"] for item in result], ["installed", "installed"])
        commands = [entry.args[0] for entry in run.call_args_list]
        updates = [command for command in commands if command[-1] == "update"]
        installs = [command for command in commands if "install" in command]
        self.assertEqual(len(updates), 1)
        installed_packages: set[str] = set()
        for command in installs:
            self.assertIn("-y", command)
            installed_packages.update(command[command.index("-y") + 1 :])
        self.assertEqual(installed_packages, {"one", "two"})
        self.assertFalse(
            any(len(command) == command.index("-y") + 1 for command in installs),
            "apt install must never run without explicit packages",
        )

    def test_install_named_tools_selects_only_requested_installers(self) -> None:
        document = {
            "profiles": {"fixture": {"required": ["first"], "optional": ["second"]}},
            "installers": {
                "first": {
                    "kind": "go",
                    "package": "example/first@v1",
                    "checks": ["first"],
                },
                "second": {
                    "kind": "go",
                    "package": "example/second@v1",
                    "checks": ["second"],
                },
            },
        }
        machine = {
            "BB_PROXY_MODE": "direct",
            "BB_HTTP_PROXY": "",
            "BB_SOCKS_PROXY": "",
        }
        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective", return_value=machine
            ),
            patch.object(self.manager, "_ensure_toolchain"),
            patch.object(self.manager, "_tool_ready", return_value=False),
        ):
            result = self.manager.install_named_tools(
                ["second", "second"], dry_run=True
            )

        self.assertEqual(result, [{"component": "tool:second", "state": "planned"}])
        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            self.assertRaisesRegex(ValidationError, "unknown tool installer"),
        ):
            self.manager.install_named_tools(["missing"], dry_run=True)

    def _fixture_document(self) -> dict:
        return {
            "profiles": {"fixture": {"required": ["req"], "optional": ["opt"]}},
            "installers": {
                "req": {
                    "kind": "go",
                    "package": "example/req@v1",
                    "checks": ["req"],
                },
                "opt": {
                    "kind": "go",
                    "package": "example/opt@v1",
                    "checks": ["opt"],
                },
            },
        }

    def _direct_machine(self) -> dict:
        return {
            "BB_PROXY_MODE": "direct",
            "BB_HTTP_PROXY": "",
            "BB_SOCKS_PROXY": "",
        }

    def test_optional_installer_failure_degrades_without_aborting(self) -> None:
        document = self._fixture_document()

        def install(name: str, spec: dict, env: dict) -> None:
            if name == "opt":
                raise CommandError("optional component unreachable")

        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective",
                return_value=self._direct_machine(),
            ),
            patch.object(self.manager, "_ensure_toolchain"),
            patch.object(self.manager, "_tool_ready", side_effect=[False, True, False]),
            patch.object(self.manager, "_install_tool", side_effect=install),
        ):
            result = self.manager.install_tools("fixture", True, dry_run=False)

        self.assertEqual(
            [(item["component"], item["state"]) for item in result],
            [("tool:req", "installed"), ("tool:opt", "unavailable")],
        )

    def test_required_installer_failure_still_aborts(self) -> None:
        document = self._fixture_document()
        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective",
                return_value=self._direct_machine(),
            ),
            patch.object(self.manager, "_ensure_toolchain"),
            patch.object(self.manager, "_tool_ready", return_value=False),
            patch.object(
                self.manager,
                "_install_tool",
                side_effect=CommandError("required component failed"),
            ),
            self.assertRaisesRegex(CommandError, "required component failed"),
        ):
            self.manager.install_tools("fixture", True, dry_run=False)

    def test_optional_apt_batch_failure_degrades_and_required_continues(self) -> None:
        document = {
            "profiles": {"fixture": {"required": ["req"], "optional": ["opt"]}},
            "installers": {
                "req": {"kind": "apt", "packages": ["req-pkg"], "checks": ["req"]},
                "opt": {"kind": "apt", "packages": ["opt-pkg"], "checks": ["opt"]},
            },
        }

        def run(command: list[str], **_kwargs: object) -> None:
            if "install" in command and "opt-pkg" in command:
                raise CommandError("optional apt transaction failed")

        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective",
                return_value=self._direct_machine(),
            ),
            patch("bb_stack.runtime.platform.system", return_value="Linux"),
            patch.object(self.manager, "_tool_ready", side_effect=[False, False, True]),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/apt-get"),
            patch("bb_stack.runtime.os.geteuid", return_value=0),
            patch.object(self.manager, "_run", side_effect=run),
        ):
            result = self.manager.install_tools("fixture", True, dry_run=False)

        self.assertEqual(
            [(item["component"], item["state"]) for item in result],
            [("tool:req", "installed"), ("tool:opt", "unavailable")],
        )

    def test_install_tools_dry_run_plans_optional_without_installing(self) -> None:
        document = self._fixture_document()
        with (
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective",
                return_value=self._direct_machine(),
            ),
            patch.object(self.manager, "_ensure_toolchain"),
            patch.object(self.manager, "_tool_ready", return_value=False),
            patch.object(self.manager, "_install_tool") as install,
        ):
            result = self.manager.install_tools("fixture", True, dry_run=True)

        self.assertEqual(
            [(item["component"], item["state"]) for item in result],
            [("tool:req", "planned"), ("tool:opt", "planned")],
        )
        install.assert_not_called()

    def test_run_timeout_error_names_command_and_budget(self) -> None:
        with (
            patch(
                "bb_stack.runtime.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["fixture"], 7),
            ),
            self.assertRaises(CommandError) as context,
        ):
            self.manager._run(["fixture", "--flag"], timeout=7)

        message = str(context.exception)
        self.assertIn("fixture --flag", message)
        self.assertIn("timed out after 7s", message)

    def test_tools_schema_enforces_per_kind_required_fields(self) -> None:
        schema = ROOT / "00-L0-Runtime/config/tools.schema.json"

        def document(installer: dict) -> dict:
            return {
                "schema_version": 1,
                "profiles": {"fixture": {"required": [], "optional": []}},
                "installers": {"demo": installer},
            }

        valid = [
            {"kind": "apt", "checks": ["x"], "packages": ["x"]},
            {"kind": "go", "checks": ["x"], "package": "example/x@v1"},
            {"kind": "pipx", "checks": ["x"], "package": "x==1"},
            {"kind": "uv-tool", "checks": ["x"], "package": "x==1"},
            {"kind": "service", "checks": [], "host": "127.0.0.1", "port": 1},
            {"kind": "deb", "checks": ["x"], "files": {}},
            {"kind": "archive-binary", "checks": ["x"], "binary": "x", "files": {}},
            {
                "kind": "archive-tree",
                "checks": ["x"],
                "format": "zip",
                "destination": "/tmp/x",
                "executables": {"x": "bin/x"},
                "files": {},
            },
            {
                "kind": "git-data",
                "checks": [],
                "repository": "https://example.invalid/x.git",
                "revision": "a" * 40,
                "destination": "/tmp/x",
            },
            {
                "kind": "git-build",
                "checks": ["x"],
                "repository": "https://example.invalid/x.git",
                "revision": "a" * 40,
                "destination": "/tmp/x",
                "build": ["make"],
                "executables": {"x": "bin/x"},
            },
        ]
        for installer in valid:
            validate(document(installer), schema, "fixture")

        invalid = [
            {"kind": "apt", "checks": ["x"]},
            {"kind": "go", "checks": ["x"]},
            {"kind": "pipx", "checks": ["x"]},
            {"kind": "uv-tool", "checks": ["x"]},
            {"kind": "service", "checks": []},
            {"kind": "service", "checks": [], "host": "127.0.0.1"},
            {"kind": "deb", "checks": ["x"]},
            {"kind": "archive-binary", "checks": ["x"]},
            {"kind": "archive-tree", "checks": ["x"], "files": {}, "format": "zip"},
            {"kind": "git-data", "checks": [], "destination": "/tmp/x"},
            {
                "kind": "git-build",
                "checks": ["x"],
                "repository": "https://example.invalid/x.git",
                "revision": "a" * 40,
                "destination": "/tmp/x",
            },
        ]
        for installer in invalid:
            with self.assertRaises(ValidationError, msg=str(installer)):
                validate(document(installer), schema, "fixture")

    def test_runtime_status_reports_paths_commands_and_registry(self) -> None:
        self.paths.runtime.mkdir(parents=True, exist_ok=True)
        (self.paths.runtime / "npm-registry.json").write_text(
            '{"configured":"auto","resolved":"https://registry.npmjs.org"}\n',
            encoding="utf-8",
        )
        machine = {"BB_NPM_REGISTRY": "auto"}
        with (
            patch(
                "bb_stack.runtime.ConfigurationManager.effective", return_value=machine
            ),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/fixture"),
        ):
            status = self.manager.runtime_status()
        self.assertEqual(status["npm_registry"]["configured"], "auto")
        self.assertEqual(
            status["npm_registry"]["resolved"], "https://registry.npmjs.org"
        )
        self.assertEqual(status["commands"]["git"], "/usr/bin/fixture")

    def _launch_mocks(self, workflow: str):
        prompt = Path(self.temporary.name) / "generated" / "prompt.md"
        render = SimpleNamespace(
            skill_profile="minimal",
            l5_profile="minimal",
            output_file=str(prompt),
            prompt_mode="append",
        )
        profiles = MagicMock()
        profiles.load.return_value = {"workflow": workflow}
        profiles.render.return_value = render
        skills = MagicMock()
        skills.profile.return_value = {"required": []}
        skills.status.return_value = []
        capabilities = MagicMock()
        capabilities.side_effects.return_value = ["filesystem-write"]
        capabilities.doctor.return_value = {"ready": True, "missing_required": []}
        capabilities.render_mcp.return_value = {"mcpServers": {}}
        data = MagicMock()
        data.ensure_profile.return_value = {"ready": True}
        return profiles, skills, capabilities, data

    def test_launch_allows_protected_workflow_without_engagement(self) -> None:
        profiles, skills, capabilities, data = self._launch_mocks("assessment")
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.SkillRegistry", return_value=skills),
            patch("bb_stack.runtime.CapabilityRegistry", return_value=capabilities),
            patch("bb_stack.runtime.DataManager", return_value=data),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/claude"),
        ):
            plan = self.manager.launch(
                "assessment-web",
                engagement=None,
                platform=None,
                claude_args=[],
                dry_run=True,
            )
        self.assertEqual(plan["profile"], "assessment-web")

    def test_launch_rejects_inactive_but_allows_pending_authorization(self) -> None:
        engagement = Path(self.temporary.name) / "engagement"
        profiles, skills, capabilities, data = self._launch_mocks("bug-bounty")
        inactive = {
            "slug": "fixture",
            "lifecycle": "paused",
            "authorization": {"status": "verified"},
        }
        engagement_manager = MagicMock()
        engagement_manager.validate.return_value = inactive
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.StackPaths.engagement", return_value=engagement),
            patch(
                "bb_stack.runtime.EngagementManager",
                return_value=engagement_manager,
            ),
            self.assertRaisesRegex(CommandError, "resume or reopen"),
        ):
            self.manager.launch(
                "ctf-web",
                engagement=engagement,
                platform=None,
                claude_args=[],
                dry_run=True,
            )

        pending = inactive | {
            "lifecycle": "active",
            "workflow": "bug-bounty",
            "platform": "generic-vdp",
            "authorization": {"status": "pending"},
        }
        engagement_manager.validate.return_value = pending
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.StackPaths.engagement", return_value=engagement),
            patch(
                "bb_stack.runtime.EngagementManager",
                return_value=engagement_manager,
            ),
            patch("bb_stack.runtime.SkillRegistry", return_value=skills),
            patch("bb_stack.runtime.CapabilityRegistry", return_value=capabilities),
            patch("bb_stack.runtime.DataManager", return_value=data),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/claude"),
        ):
            plan = self.manager.launch(
                "ctf-web",
                engagement=engagement,
                platform=None,
                claude_args=[],
                dry_run=True,
            )
        self.assertEqual(plan["cwd"], str(engagement))

    def test_launch_dry_run_builds_isolated_command(self) -> None:
        prompt = Path(self.temporary.name) / "generated" / "prompt.md"
        render = SimpleNamespace(
            skill_profile="minimal",
            l5_profile="minimal",
            output_file=str(prompt),
            prompt_mode="append",
        )
        profiles = MagicMock()
        profiles.load.return_value = {"workflow": "analysis"}
        profiles.render.return_value = render
        skills = MagicMock()
        skills.profile.return_value = {"required": []}
        skills.status.return_value = []
        capabilities = MagicMock()
        capabilities.side_effects.return_value = ["filesystem-write"]
        capabilities.doctor.return_value = {"ready": True, "missing_required": []}
        capabilities.render_mcp.return_value = {
            "mcpServers": {"fixture": {"command": "fixture"}}
        }
        data = MagicMock()
        data.ensure_profile.return_value = {"ready": True}
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.SkillRegistry", return_value=skills),
            patch("bb_stack.runtime.CapabilityRegistry", return_value=capabilities),
            patch("bb_stack.runtime.DataManager", return_value=data),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/claude"),
        ):
            result = self.manager.launch(
                "analysis",
                engagement=None,
                platform="standalone-analysis",
                claude_args=["--model", "sonnet"],
                dry_run=True,
                include_high_context_mcp=True,
            )
        self.assertEqual(result["command"][0], "/usr/bin/claude")
        self.assertIn("--append-system-prompt-file", result["command"])
        self.assertIn("--strict-mcp-config", result["command"])
        self.assertEqual(result["side_effects"], ["filesystem-write"])

    def test_launch_rejects_missing_skills_capabilities_and_claude(self) -> None:
        render = SimpleNamespace(
            skill_profile="minimal",
            l5_profile="minimal",
            output_file=str(Path(self.temporary.name) / "prompt.md"),
            prompt_mode="replacement",
        )
        profiles = MagicMock()
        profiles.load.return_value = {"workflow": "analysis"}
        profiles.render.return_value = render
        skills = MagicMock()
        skills.profile.return_value = {"required": ["required-skill"]}
        skills.status.return_value = [{"name": "required-skill", "state": "missing"}]
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.SkillRegistry", return_value=skills),
            self.assertRaisesRegex(CommandError, "required Skills"),
        ):
            self.manager.launch(
                "analysis", engagement=None, platform=None, claude_args=[], dry_run=True
            )

        skills.profile.return_value = {"required": []}
        skills.status.return_value = []
        capabilities = MagicMock()
        capabilities.side_effects.return_value = []
        capabilities.doctor.return_value = {
            "ready": False,
            "missing_required": ["fixture"],
        }
        data = MagicMock()
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.SkillRegistry", return_value=skills),
            patch("bb_stack.runtime.CapabilityRegistry", return_value=capabilities),
            patch("bb_stack.runtime.DataManager", return_value=data),
            self.assertRaisesRegex(CommandError, "required capabilities"),
        ):
            self.manager.launch(
                "analysis", engagement=None, platform=None, claude_args=[], dry_run=True
            )

        capabilities.doctor.return_value = {"ready": True, "missing_required": []}
        capabilities.render_mcp.return_value = {"mcpServers": {}}
        with (
            patch("bb_stack.runtime.ProfileRegistry", return_value=profiles),
            patch("bb_stack.runtime.SkillRegistry", return_value=skills),
            patch("bb_stack.runtime.CapabilityRegistry", return_value=capabilities),
            patch("bb_stack.runtime.DataManager", return_value=data),
            patch.dict(os.environ, {"CLAUDE_BIN": ""}),
            patch("bb_stack.runtime.shutil.which", return_value=None),
            self.assertRaisesRegex(CommandError, "Claude Code CLI"),
        ):
            self.manager.launch(
                "analysis", engagement=None, platform=None, claude_args=[], dry_run=True
            )

    def test_select_platform_file_supports_linux_and_darwin_arches(self) -> None:
        files = {
            "x86_64": {"archive": "lin64"},
            "aarch64": {"archive": "linarm"},
            "darwin-x86_64": {"archive": "mac64"},
            "darwin-aarch64": {"archive": "macarm"},
        }
        with (
            patch("bb_stack.runtime.platform.system", return_value="Darwin"),
            patch("bb_stack.runtime.platform.machine", return_value="arm64"),
        ):
            key, spec = self.manager._select_platform_file(files, "demo", "archive")
            self.assertEqual((key, spec["archive"]), ("darwin-aarch64", "macarm"))
        with (
            patch("bb_stack.runtime.platform.system", return_value="Darwin"),
            patch("bb_stack.runtime.platform.machine", return_value="x86_64"),
        ):
            key, spec = self.manager._select_platform_file(files, "demo", "archive")
            self.assertEqual((key, spec["archive"]), ("darwin-x86_64", "mac64"))
        with (
            patch("bb_stack.runtime.platform.system", return_value="Linux"),
            patch("bb_stack.runtime.platform.machine", return_value="aarch64"),
        ):
            key, spec = self.manager._select_platform_file(files, "demo", "archive")
            self.assertEqual((key, spec["archive"]), ("aarch64", "linarm"))

    def test_darwin_homebrew_batching_and_optional_degradation(self) -> None:
        document = {
            "profiles": {
                "fixture": {"required": ["req", "browser"], "optional": ["opt"]}
            },
            "installers": {
                "req": {
                    "kind": "apt",
                    "packages": ["req-pkg"],
                    "brew": ["req-brew"],
                    "checks": ["req"],
                },
                "browser": {
                    "kind": "apt",
                    "packages": ["chromium"],
                    "brew_casks": ["chromium"],
                    "checks": ["chromium"],
                },
                "opt": {
                    "kind": "apt",
                    "packages": ["opt-pkg"],
                    "brew": ["opt-brew"],
                    "checks": ["opt"],
                },
            },
        }
        machine = self._direct_machine()

        def run(command: list[str], **_kwargs: object) -> None:
            if "opt-brew" in command:
                raise CommandError("optional brew install failed")

        with (
            patch("bb_stack.runtime.platform.system", return_value="Darwin"),
            patch("bb_stack.runtime.load_yaml", return_value=document),
            patch("bb_stack.runtime.validate"),
            patch(
                "bb_stack.runtime.ConfigurationManager.effective",
                return_value=machine,
            ),
            patch.object(
                self.manager,
                "_tool_ready",
                side_effect=[False, False, False, True, True],
            ),
            patch(
                "bb_stack.runtime.shutil.which", return_value="/opt/homebrew/bin/brew"
            ),
            patch.object(self.manager, "_run", side_effect=run) as run_mock,
        ):
            result = self.manager.install_tools("fixture", True, dry_run=False)

        self.assertEqual(
            [(item["component"], item["state"]) for item in result],
            [
                ("tool:req", "installed"),
                ("tool:browser", "installed"),
                ("tool:opt", "unavailable"),
            ],
        )
        commands = [entry.args[0] for entry in run_mock.call_args_list]
        self.assertEqual(commands[0], ["/opt/homebrew/bin/brew", "install", "req-brew"])
        self.assertEqual(
            commands[1],
            ["/opt/homebrew/bin/brew", "install", "--cask", "chromium"],
        )
        self.assertEqual(commands[2], ["/opt/homebrew/bin/brew", "install", "opt-brew"])
        self.assertTrue(
            all(
                entry.kwargs["env"].get("HOMEBREW_NO_AUTO_UPDATE") == "1"
                for entry in run_mock.call_args_list
            )
        )
        self.assertEqual(
            run_mock.call_args_list[0].kwargs["timeout"], BREW_TIMEOUT_SECONDS
        )

    def test_darwin_pipx_uses_homebrew_and_probe_gates_stub(self) -> None:
        env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin"}
        which_results = [None, "/opt/homebrew/bin/brew", "/opt/homebrew/bin/pipx"]
        with (
            patch("bb_stack.runtime.platform.system", return_value="Darwin"),
            patch("bb_stack.runtime.shutil.which", side_effect=which_results),
            patch.object(self.manager, "_run") as run,
        ):
            self.manager._install_tool(
                "demo", {"kind": "pipx", "package": "demo==1.0.0"}, env
            )
        self.assertEqual(
            run.call_args_list[0].args[0], ["/opt/homebrew/bin/brew", "install", "pipx"]
        )
        self.assertEqual(run.call_args_list[1].args[0][0], "/opt/homebrew/bin/pipx")

        java_spec = {
            "kind": "apt",
            "checks": ["java"],
            "darwin_probe": ["java", "-version"],
        }
        with (
            patch("bb_stack.runtime.platform.system", return_value="Darwin"),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/java"),
            patch(
                "bb_stack.runtime.subprocess.run",
                return_value=subprocess.CompletedProcess(["java"], 1),
            ),
        ):
            self.assertFalse(self.manager._tool_ready(java_spec, env))
        with (
            patch("bb_stack.runtime.platform.system", return_value="Darwin"),
            patch(
                "bb_stack.runtime.shutil.which",
                return_value="/opt/homebrew/opt/openjdk/bin/java",
            ),
            patch(
                "bb_stack.runtime.subprocess.run",
                return_value=subprocess.CompletedProcess(["java"], 0),
            ),
        ):
            self.assertTrue(self.manager._tool_ready(java_spec, env))

    def test_git_data_and_archive_mirror_fallbacks(self) -> None:
        mirror_repo = Path(self.temporary.name) / "mirror-repo"
        mirror_repo.mkdir()
        subprocess.run(
            ["git", "-C", str(mirror_repo), "init", "--quiet", "--initial-branch=main"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(mirror_repo), "config", "user.name", "Test"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(mirror_repo),
                "config",
                "user.email",
                "t@example.invalid",
            ],
            check=True,
        )
        (mirror_repo / "README.md").write_text("ok\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(mirror_repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(mirror_repo), "commit", "--quiet", "-m", "init"],
            check=True,
        )
        revision = subprocess.check_output(
            ["git", "-C", str(mirror_repo), "rev-parse", "HEAD"], text=True
        ).strip()
        destination = self.paths.runtime / "tools" / "mirror-git"
        git_spec = {
            "kind": "git-data",
            "checks": [],
            "repository": str(Path(self.temporary.name) / "missing-primary.git"),
            "mirrors": [str(mirror_repo)],
            "revision": revision,
            "destination": str(destination),
            "retry_attempts": 1,
        }
        self.manager._install_git_data(
            "mirror-git", git_spec, {"PATH": self.paths.runtime_path()}
        )
        self.assertTrue((destination / "README.md").is_file())

        mirror_dir = Path(self.temporary.name) / "artifact-mirror"
        mirror_dir.mkdir()
        payload = b"verified-archive-bytes"
        sha256 = __import__("hashlib").sha256(payload).hexdigest()
        (mirror_dir / "demo-1.0.tar.gz").write_bytes(payload)
        bad_mirror = Path(self.temporary.name) / "bad-mirror"
        bad_mirror.mkdir()
        (bad_mirror / "demo-1.0.tar.gz").write_bytes(b"tampered")
        arch = __import__("platform").machine()
        file_entry = {
            "archive": "demo-1.0.tar.gz",
            "url": (Path(self.temporary.name) / "missing.tar.gz").as_uri(),
            "mirrors": [(bad_mirror / "demo-1.0.tar.gz").as_uri()],
            "sha256": sha256,
        }
        archive_spec = {
            "kind": "archive-binary",
            "checks": ["demo"],
            "binary": "demo",
            "files": {
                arch: file_entry,
                "darwin-aarch64": file_entry,
                "darwin-x86_64": file_entry,
            },
        }
        with patch.dict(os.environ, {"BB_ARTIFACT_MIRROR": str(mirror_dir)}):
            cached = self.manager._download_tool_archive("demo", archive_spec)
        self.assertEqual(cached.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
