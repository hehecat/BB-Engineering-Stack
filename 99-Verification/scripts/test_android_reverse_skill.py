#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.paths import StackPaths
from bb_stack.skills import SkillRegistry
from bb_stack.updates import UpdateManager


class AndroidReverseSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-android-skill-")
        self.workspace = Path(self.temporary.name)
        self.skill = ROOT / "04-L4-Skills/vendor/community/android-reverse-engineering"
        self.scripts = self.skill / "scripts"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(
        self, name: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.scripts / name), *arguments],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_registry_and_stack_adaptation(self) -> None:
        paths = StackPaths(
            ROOT,
            self.workspace / "home",
            self.workspace / "work",
            self.workspace / "config",
            self.workspace / ".claude",
        )
        registry = SkillRegistry(paths)
        profile = registry.profile("android")
        self.assertIn("android-reverse-engineering", profile["required"])
        source = registry.source("android-reverse-engineering")
        frontmatter = registry._frontmatter(source / "SKILL.md")
        self.assertEqual(frontmatter["name"], "android-reverse-engineering")
        content = (source / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", content)
        self.assertIn("bb-stack bootstrap --profile android", content)

        update = UpdateManager(paths).inventory({"skills"})[
            "skill.android-reverse-engineering"
        ]
        self.assertEqual(update["checker"], "manual")
        self.assertEqual(update["license"], "Apache-2.0")
        self.assertEqual(update["current"], "e8dde9d058badbd5a62265d5d23e81f0ea8f04dd")

    def test_shell_scripts_parse(self) -> None:
        for script in sorted(self.scripts.glob("*.sh")):
            completed = subprocess.run(
                ["bash", "-n", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(
                completed.returncode, 0, f"{script.name}: {completed.stderr}"
            )

    @unittest.skipUnless(
        shutil.which("unzip") and shutil.which("strings"),
        "fingerprint requires unzip and strings",
    )
    def test_fingerprint_detects_native_kotlin_http_stack(self) -> None:
        apk = self.workspace / "fixture.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("META-INF/fixture.kotlin_module", b"fixture")
            archive.writestr(
                "classes.dex",
                b"\x00Lretrofit2/http/GET;\x00Lokhttp3/OkHttpClient;\x00"
                b"Lorg/koin/core/Koin;\x00",
            )
        completed = self.run_script("fingerprint.sh", str(apk))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Native Android (Kotlin)", completed.stdout)
        self.assertIn("Retrofit", completed.stdout)
        self.assertIn("OkHttp", completed.stdout)
        self.assertIn("Koin", completed.stdout)

    def test_api_extraction_finds_retrofit_and_urls(self) -> None:
        source = self.workspace / "sources"
        source.mkdir()
        (source / "Api.java").write_text(
            """\
import retrofit2.http.GET;
interface Api {
  String BASE_URL = "https://api.example.test";
  @GET("/v1/users") Object users();
}
""",
            encoding="utf-8",
        )
        completed = self.run_script("find-api-calls.sh", str(source))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Retrofit Annotations", completed.stdout)
        self.assertIn("/v1/users", completed.stdout)
        self.assertIn("api.example.test", completed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
