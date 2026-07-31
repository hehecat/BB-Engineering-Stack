#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import CommandError
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager


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
        with patch.object(
            self.manager, "_download_tool_archive", return_value=archive
        ):
            self.manager._install_tool("demo", spec, {"PATH": "/usr/bin:/bin"})
        wrapper = self.paths.runtime_bin / "demo"
        self.assertTrue(wrapper.is_symlink())
        self.assertTrue(self.manager._tool_ready(spec, {"PATH": self.paths.runtime_path()}))

    def test_zip_traversal_is_rejected(self) -> None:
        archive = Path(self.temporary.name) / "escape.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escape", "unexpected")
        destination = Path(self.temporary.name) / "extract"
        destination.mkdir()
        with zipfile.ZipFile(archive) as handle:
            with self.assertRaises(CommandError):
                RuntimeManager._safe_extract_zip(handle, destination)
        self.assertFalse((Path(self.temporary.name) / "escape").exists())

    def test_deb_installer_uses_pinned_local_archive(self) -> None:
        archive = Path(self.temporary.name) / "tool.deb"
        archive.write_bytes(b"test-only")
        spec = {"kind": "deb", "checks": ["demo"], "files": {}}
        with (
            patch.object(self.manager, "_download_tool_archive", return_value=archive),
            patch("bb_stack.runtime.shutil.which", return_value="/usr/bin/apt-get"),
            patch.object(self.manager, "_run") as run,
        ):
            self.manager._install_tool("demo", spec, {"PATH": "/usr/bin:/bin"})
        run.assert_called_once_with(
            ["/usr/bin/apt-get", "install", "-y", str(archive)],
            env={"PATH": "/usr/bin:/bin"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
