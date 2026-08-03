#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import CommandError
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager
from test_support import isolated_stack_source


class RuntimeInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-installers-")
        base = Path(self.temporary.name)
        stack = base / "stack"
        stack.mkdir()
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

    def test_tool_install_uses_configured_proxy_without_lowercase_residue(self) -> None:
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
        self.assertNotIn("http_proxy", env)
        self.assertNotIn("https_proxy", env)
        self.assertNotIn("all_proxy", env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
