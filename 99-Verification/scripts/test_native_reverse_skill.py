#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.capabilities import CapabilityRegistry
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager
from bb_stack.skills import SkillRegistry


class NativeReverseSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-native-skill-")
        self.workspace = Path(self.temporary.name)
        self.skill = ROOT / "04-L4-Skills/library/native-reverse-engineering"
        self.script = self.skill / "scripts/triage_native.py"
        self.paths = StackPaths(
            ROOT,
            self.workspace / "home",
            self.workspace / "work",
            self.workspace / "config",
            self.workspace / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registry_profiles_and_tool_contracts(self) -> None:
        skills = SkillRegistry(self.paths)
        self.assertEqual(
            skills._frontmatter(self.skill / "SKILL.md")["name"],
            "native-reverse-engineering",
        )
        self.assertIn(
            "native-reverse-engineering", skills.profile("reverse")["required"]
        )
        self.assertIn(
            "native-reverse-engineering",
            skills.profile("analysis-reverse")["required"],
        )
        assessment = skills.profile("assessment-reverse")
        self.assertEqual(assessment["orchestrator"], "security-orchestrator")
        self.assertNotIn("solve-challenge", assessment["required"])

        capabilities = CapabilityRegistry(self.paths)
        for profile_name in ("reverse", "analysis-reverse", "assessment-reverse"):
            profile = capabilities.profile(profile_name)
            self.assertIn("native.triage", profile["required"])
            self.assertIn("native.static", profile["required"])
        registry = capabilities.registry()
        self.assertEqual(registry["capabilities"]["native.triage"]["strategy"], "all")
        self.assertNotIn("jadx", registry["capabilities"]["native.static"]["providers"])

        tools = RuntimeManager(self.paths).validate_config()["tool_profiles"]
        self.assertIn("assessment-reverse", tools)

    @unittest.skipUnless(
        all(shutil.which(command) for command in ("file", "readelf", "objdump")),
        "native triage requires file and binutils",
    )
    def test_real_elf_triage_is_read_only_and_structured(self) -> None:
        source = Path(sys.executable).resolve()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        output = self.workspace / "triage"
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(source),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["input"]["sha256"], before)
        self.assertTrue(summary["input"]["unchanged"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertEqual(summary["probes"]["file"]["exit_code"], 0)
        self.assertEqual(summary["tools"]["file"]["path"], shutil.which("file"))
        self.assertTrue(summary["tools"]["file"]["version"])
        self.assertIn("ELF", (output / "file.txt").read_text())
        self.assertIn(
            "Entry point address", (output / "readelf-header.txt").read_text()
        )

    def test_triage_rejects_nonempty_output(self) -> None:
        output = self.workspace / "existing"
        output.mkdir()
        (output / "owned.txt").write_text("keep", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(Path(sys.executable).resolve()),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("not empty", completed.stderr)
        self.assertEqual((output / "owned.txt").read_text(), "keep")

    def test_triage_never_executes_the_input(self) -> None:
        marker = self.workspace / "executed"
        source = self.workspace / "untrusted-fixture"
        source.write_text(
            f"#!/bin/sh\nprintf executed > {marker}\n",
            encoding="utf-8",
        )
        source.chmod(0o755)
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(source),
                "--output",
                str(self.workspace / "script-triage"),
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
