#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import StackError, ValidationError
from bb_stack.io import dump_json
from bb_stack.paths import StackPaths
from bb_stack.skills import SkillRegistry
from bb_stack.updates import UpdateManager


class UpdateManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-updates-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / ".claude",
        )
        self.manager = UpdateManager(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def component(checker: str, **values: object) -> dict[str, object]:
        return {
            "name": "fixture",
            "category": "tools",
            "target": "fixture",
            "checker": checker,
            "license": "MIT",
            **values,
        }

    def test_tool_inventory_covers_every_installer_kind(self) -> None:
        cases = (
            (
                {"kind": "go", "package": "example.test/tool/cmd/demo@v1.2.3"},
                "go",
            ),
            ({"kind": "pipx", "package": "demo==1.2.3"}, "pypi"),
            ({"kind": "pipx", "package": "demo"}, "manual"),
            (
                {
                    "kind": "git-data",
                    "repository": "https://github.com/example/demo",
                    "revision": "a" * 40,
                },
                "github-commit",
            ),
            (
                {
                    "kind": "archive-binary",
                    "files": {
                        "amd64": {
                            "url": "https://github.com/example/demo/releases/download/v1.2.3/demo.tar.gz"
                        }
                    },
                },
                "github-release",
            ),
            (
                {
                    "kind": "archive-tree",
                    "files": {"amd64": {"url": "https://example.test/demo.zip"}},
                },
                "manual",
            ),
            ({"kind": "apt", "packages": ["demo"]}, "apt"),
            ({"kind": "service"}, "manual"),
            ({"kind": "unknown"}, "manual"),
        )
        for spec, checker in cases:
            with self.subTest(kind=spec["kind"]):
                self.assertEqual(
                    self.manager._tool_inventory("demo", spec)["checker"], checker
                )

    def test_check_one_covers_static_and_remote_checkers(self) -> None:
        manual = self.manager._check_one(self.component("manual", current="1"))
        self.assertEqual(manual["status"], "manual")
        owned = self.manager._check_one(
            self.component("stack-owned", local_digest="a" * 64)
        )
        self.assertEqual(owned["status"], "stack-owned")
        apt = self.manager._check_one(self.component("apt"))
        self.assertEqual(apt["status"], "system-managed")

        github = self.component(
            "github-commit",
            repository="https://github.com/example/demo",
            branch="main",
            current="a" * 40,
        )
        with patch.object(self.manager, "_git_remote_revision", return_value="b" * 40):
            checked = self.manager._check_one(github)
        self.assertEqual(checked["status"], "update-available")

        release = self.component(
            "github-release",
            repository="https://github.com/example/demo",
            current="v1.0.0",
        )
        with patch.object(self.manager, "_git_latest_tag", return_value="v1.0.0"):
            self.assertEqual(self.manager._check_one(release)["status"], "current")

        npm = self.component("npm", current="1.0.0")
        with patch.object(
            self.manager,
            "_request_json",
            return_value={
                "version": "2.0.0",
                "license": "Apache-2.0",
                "repository": {"url": "git+https://github.com/example/demo.git"},
            },
        ):
            self.assertEqual(self.manager._check_one(npm)["status"], "license-review")

        pypi = self.component("pypi", package="demo", current="1.0.0")
        with patch.object(
            self.manager,
            "_request_json",
            return_value={
                "info": {
                    "version": "1.0.0",
                    "project_url": "https://example.test",
                    "license": "MIT",
                }
            },
        ):
            self.assertEqual(self.manager._check_one(pypi)["status"], "current")

        go = self.component("go", package="example.test/demo", current="v1.0.0")
        with patch.object(
            self.manager, "_request_json", return_value={"Version": "v2.0.0"}
        ):
            self.assertEqual(self.manager._check_one(go)["status"], "update-available")
        with self.assertRaisesRegex(ValidationError, "unsupported update checker"):
            self.manager._check_one(self.component("unknown"))

    def test_github_tree_status_variants(self) -> None:
        base = self.component(
            "github-tree",
            repository="https://github.com/example/demo",
            branch="main",
            subpath="skill",
            current_revision="a" * 40,
            current_digest="1" * 64,
            local_digest="1" * 64,
        )
        with patch.object(self.manager, "_git_remote_revision", return_value="a" * 40):
            self.assertEqual(self.manager._check_one(base)["status"], "current")
        drifted = dict(base, local_digest="2" * 64)
        with patch.object(self.manager, "_git_remote_revision", return_value="a" * 40):
            self.assertEqual(self.manager._check_one(drifted)["status"], "local-drift")
        with (
            patch.object(self.manager, "_git_remote_revision", return_value="b" * 40),
            patch.object(self.manager, "_github_tree_digest", return_value="3" * 64),
        ):
            self.assertEqual(
                self.manager._check_one(base)["status"], "update-available"
            )

    def test_check_safely_converts_expected_failures(self) -> None:
        component = self.component("manual")
        http_error = HTTPError("https://example.test", 403, "limited", {}, BytesIO())
        try:
            with patch.object(self.manager, "_check_one", side_effect=http_error):
                self.assertEqual(
                    self.manager._check_safely(component)["status"], "rate-limited"
                )
        finally:
            http_error.close()
        with patch.object(
            self.manager, "_check_one", side_effect=ValueError("bad data")
        ):
            result = self.manager._check_safely(component)
        self.assertEqual(result["status"], "check-error")
        self.assertIn("bad data", result["error"])

    def test_approval_and_repository_helpers(self) -> None:
        self.assertEqual(
            self.manager._approval_text("reviewer", " reviewer ", 20), "reviewer"
        )
        for value, message in (
            ("", "empty"),
            ("x" * 21, "too long"),
            ("bad\ntext", "control"),
        ):
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValidationError, message),
            ):
                self.manager._approval_text("reviewer", value, 20)
        self.assertEqual(
            self.manager._github_slug("https://github.com/example/demo.git"),
            "example/demo",
        )
        with self.assertRaisesRegex(ValidationError, "not a GitHub"):
            self.manager._github_slug("https://example.test/example/demo")
        with self.assertRaisesRegex(ValidationError, "invalid GitHub"):
            self.manager._github_slug("https://github.com/example")
        self.assertEqual(
            self.manager._repository_url("git+https://github.com/example/demo.git"),
            "https://github.com/example/demo",
        )
        self.assertEqual(
            self.manager._repository_url({"url": "git+https://example.test/demo.git"}),
            "https://example.test/demo",
        )
        self.assertIsNone(self.manager._repository_url({"url": 1}))
        self.assertEqual(
            self.manager._summary([{"status": "current"}, {"status": "current"}]),
            {"total": 2, "current": 2},
        )

    def test_candidate_digest_and_lock_canonicalization(self) -> None:
        candidate = Path(self.temporary.name) / "candidate"
        candidate.mkdir()
        for name in ("package.json", "package-lock.json", "mcp_probe.mjs"):
            (candidate / name).write_text(name, encoding="utf-8")
        digest = self.manager._candidate_content_digest(
            self.component("npm"), candidate
        )
        self.assertEqual(len(digest), 64)
        (candidate / "mcp_probe.mjs").unlink()
        with self.assertRaisesRegex(ValidationError, "missing a regular file"):
            self.manager._candidate_content_digest(self.component("npm"), candidate)
        with self.assertRaisesRegex(ValidationError, "unsupported"):
            self.manager._candidate_content_digest(self.component("manual"), candidate)

        lock = {
            "packages": {
                "": {},
                "node_modules/a": {
                    "resolved": "https://registry.npmmirror.com/a/-/a-1.0.0.tgz"
                },
                "node_modules/b": "invalid",
            }
        }
        self.manager._canonicalize_npm_lock(lock, "https://registry.npmmirror.com")
        self.assertTrue(
            lock["packages"]["node_modules/a"]["resolved"].startswith(
                "https://registry.npmjs.org/"
            )
        )

    def test_stage_state_machine(self) -> None:
        candidate = Path(self.temporary.name) / "stage"
        candidate.mkdir()
        component = self.component(
            "github-tree", current_digest="1" * 64, target="fixture"
        )

        def stage(
            _component: dict[str, object],
            _revision: str,
            _candidate: Path,
            manifest: dict[str, object],
        ) -> None:
            manifest["candidate_digest"] = "2" * 64

        with (
            patch.object(
                self.manager,
                "check",
                return_value={
                    "results": [
                        {"status": "update-available", "current": "a", "latest": "b"}
                    ]
                },
            ),
            patch.object(
                self.manager, "inventory", return_value={"fixture": component}
            ),
            patch.object(self.manager, "_fresh_candidate", return_value=candidate),
            patch.object(self.manager, "_stage_github_tree", side_effect=stage),
            patch.object(self.manager, "_validate_candidate_document"),
        ):
            result = self.manager._stage_locked("fixture")
        self.assertEqual(result["state"], "staged")

        with (
            patch.object(
                self.manager,
                "check",
                return_value={"results": [{"status": "current"}]},
            ),
            self.assertRaisesRegex(StackError, "not stageable"),
        ):
            self.manager._stage_locked("fixture")

    def test_candidate_validation_success_and_failure(self) -> None:
        candidate = Path(self.temporary.name) / "skill__fixture"
        payload = candidate / "payload"
        payload.mkdir(parents=True)
        (payload / "SKILL.md").write_text(
            "---\nname: fixture\ndescription: fixture\n---\n\nFixture.\n",
            encoding="utf-8",
        )
        digest = SkillRegistry.tree_digest(payload)
        manifest = {
            "schema_version": 1,
            "component": "skill.fixture",
            "category": "skills",
            "checker": "github-tree",
            "current": "a",
            "latest": "b",
            "created_at": "2026-08-03T00:00:00Z",
            "state": "staged",
            "candidate_digest": digest,
        }
        dump_json(candidate / "candidate.json", manifest)
        component = self.component(
            "github-tree", name="skill.fixture", target="fixture"
        )
        with patch.object(
            self.manager, "inventory", return_value={"skill.fixture": component}
        ):
            validated = self.manager._validate_candidate(candidate)
        self.assertEqual(validated["state"], "validated")

        (payload / "SKILL.md").write_text("changed\n", encoding="utf-8")
        manifest["state"] = "staged"
        dump_json(candidate / "candidate.json", manifest)
        with (
            patch.object(
                self.manager, "inventory", return_value={"skill.fixture": component}
            ),
            self.assertRaises(ValidationError),
        ):
            self.manager._validate_candidate(candidate)
        failed = json.loads((candidate / "candidate.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["state"], "validation-failed")

    def test_approve_promote_and_rollback_dispatch(self) -> None:
        candidate = Path(self.temporary.name) / "candidate-state"
        candidate.mkdir()
        manifest = {
            "component": "fixture",
            "state": "validated",
            "latest": "b",
        }
        component = self.component("github-tree", target="fixture")
        with (
            patch.object(self.manager, "_candidate", return_value=candidate),
            patch.object(self.manager, "_load_candidate", return_value=manifest),
            patch.object(
                self.manager, "inventory", return_value={"fixture": component}
            ),
            patch.object(
                self.manager, "_candidate_content_digest", return_value="digest"
            ),
            patch.object(self.manager, "_operation_lock", return_value=nullcontext()),
        ):
            approved = self.manager.approve(
                "fixture", reviewer="Reviewer", note="Looks good"
            )
        self.assertEqual(approved["approval"]["content_digest"], "digest")

        manifest["approval"] = {"content_digest": "digest"}
        backup = Path(self.temporary.name) / "backup"
        backup.mkdir()
        with (
            patch.object(self.manager, "_candidate", return_value=candidate),
            patch.object(self.manager, "_load_candidate", return_value=manifest),
            patch.object(
                self.manager, "inventory", return_value={"fixture": component}
            ),
            patch.object(
                self.manager, "_candidate_content_digest", return_value="digest"
            ),
            patch.object(
                self.manager,
                "check",
                return_value={
                    "results": [{"status": "update-available", "latest": "b"}]
                },
            ),
            patch.object(self.manager, "_new_backup", return_value=backup),
            patch.object(self.manager, "_promote_skill") as promote,
        ):
            promoted = self.manager._promote_locked("fixture")
        self.assertEqual(promoted["state"], "promoted")
        promote.assert_called_once()

        promoted["backup"] = str(backup)
        with (
            patch.object(self.manager, "_candidate", return_value=candidate),
            patch.object(self.manager, "_load_candidate", return_value=promoted),
            patch.object(
                self.manager, "inventory", return_value={"fixture": component}
            ),
            patch.object(self.manager, "_backup_root", return_value=backup.parent),
            patch.object(self.manager, "_rollback_skill") as rollback,
        ):
            rolled_back = self.manager._rollback_locked("fixture")
        self.assertEqual(rolled_back["state"], "rolled-back")
        rollback.assert_called_once()

    def test_transaction_guards_reject_invalid_state(self) -> None:
        candidate = Path(self.temporary.name) / "guard"
        candidate.mkdir()
        with (
            patch.object(self.manager, "_candidate", return_value=candidate),
            patch.object(
                self.manager,
                "_load_candidate",
                return_value={"component": "fixture", "state": "staged"},
            ),
            patch.object(self.manager, "_operation_lock", return_value=nullcontext()),
            self.assertRaisesRegex(ValidationError, "validated before approval"),
        ):
            self.manager.approve("fixture", reviewer="Reviewer")

        with (
            patch.object(self.manager, "_candidate", return_value=candidate),
            patch.object(
                self.manager,
                "_load_candidate",
                return_value={"component": "fixture", "state": "validated"},
            ),
            patch.object(
                self.manager,
                "inventory",
                return_value={"fixture": self.component("github-tree")},
            ),
            self.assertRaisesRegex(ValidationError, "requires explicit review"),
        ):
            self.manager._promote_locked("fixture")

        with (
            patch.object(self.manager, "_candidate", return_value=candidate),
            patch.object(
                self.manager,
                "_load_candidate",
                return_value={"component": "fixture", "state": "validated"},
            ),
            self.assertRaisesRegex(ValidationError, "not promoted"),
        ):
            self.manager._rollback_locked("fixture")

    def test_git_remote_and_tag_parsing(self) -> None:
        completed = subprocess.CompletedProcess(
            ["git"], 0, stdout=f"{'a' * 40}\trefs/heads/main\n", stderr=""
        )
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/git"),
            patch("bb_stack.updates.subprocess.run", return_value=completed),
        ):
            self.assertEqual(
                self.manager._git_remote_revision("https://example.test/repo", "main"),
                "a" * 40,
            )

        tags = subprocess.CompletedProcess(
            ["git"],
            0,
            stdout=(
                f"{'a' * 40}\trefs/tags/v1.2.0\n"
                f"{'b' * 40}\trefs/tags/v2.0.0\n"
                f"{'c' * 40}\trefs/tags/latest\n"
            ),
            stderr="",
        )
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/git"),
            patch("bb_stack.updates.subprocess.run", return_value=tags),
        ):
            self.assertEqual(
                self.manager._git_latest_tag("https://example.test/repo"), "v2.0.0"
            )

    def test_candidate_environment_isolated_and_chromium_optional(self) -> None:
        candidate = Path(self.temporary.name) / "candidate"
        with patch("bb_stack.updates.shutil.which", return_value="/usr/bin/chromium"):
            env = self.manager._candidate_environment(candidate)
        self.assertEqual(env["HOME"], str(candidate / "sandbox-home"))
        self.assertEqual(env["BB_ARTIFACT_ROOT"], str(candidate / "artifacts"))
        self.assertEqual(env["BB_BROWSER_URL"], "http://127.0.0.1:9222")
        self.assertEqual(env["BB_CHROMIUM_BIN"], "/usr/bin/chromium")
        self.assertFalse((candidate / "sandbox-home").stat().st_mode & 0o077)
        with patch("bb_stack.updates.shutil.which", return_value=None):
            without_chromium = self.manager._candidate_environment(candidate / "other")
        self.assertNotIn("BB_CHROMIUM_BIN", without_chromium)

    def test_candidate_lifecycle_helpers_and_bulk_validation(self) -> None:
        root = Path(self.temporary.name) / "candidate-root"
        root.mkdir()
        first = root / "skill__first"
        first.mkdir()
        dump_json(
            first / "candidate.json",
            {
                "schema_version": 1,
                "component": "skill.first",
                "category": "skills",
                "checker": "manual",
                "current": "a",
                "latest": "b",
                "created_at": "2026-08-03T00:00:00Z",
                "state": "review-required",
                "reason": "manual",
            },
        )
        superseded = root / "skill__first.superseded.old"
        superseded.mkdir()
        dump_json(superseded / "candidate.json", {})
        with (
            patch.object(self.manager, "_candidate_root", return_value=root),
            patch.object(
                self.manager, "_validate_candidate", return_value={"state": "ok"}
            ) as validate,
            patch.object(self.manager, "_operation_lock", return_value=nullcontext()),
        ):
            result = self.manager.validate_candidates()
            second = self.manager._fresh_candidate("skill.first")
            child = self.manager._new_child(root, "child")
        self.assertEqual(result, [{"state": "ok"}])
        validate.assert_called_once_with(first)
        self.assertEqual(second.name, "skill__first")
        self.assertTrue(child.is_dir())

    def test_remote_request_and_git_failures_are_explicit(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        response.read.return_value = b"{}"
        response.json = None
        with (
            patch("bb_stack.updates.urlopen", return_value=response),
            patch.dict(os.environ, {"GITHUB_TOKEN": "secret"}),
        ):
            value = self.manager._request_json("https://api.github.com/repos/demo")
        self.assertEqual(value, {})

        with (
            patch("bb_stack.updates.shutil.which", return_value=None),
            self.assertRaisesRegex(StackError, "git is required"),
        ):
            self.manager._git_remote_revision("https://example.test/repo", "main")
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/git"),
            patch(
                "bb_stack.updates.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["git"], 1, stdout="", stderr="network down"
                ),
            ),
            self.assertRaisesRegex(StackError, "network down"),
        ):
            self.manager._git_remote_revision("https://example.test/repo", "main")
        invalid = subprocess.CompletedProcess(
            ["git"], 0, stdout="not-a-revision\trefs/heads/main\n", stderr=""
        )
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/git"),
            patch("bb_stack.updates.subprocess.run", return_value=invalid),
            self.assertRaisesRegex(ValidationError, "invalid Git revision"),
        ):
            self.manager._git_remote_revision("https://example.test/repo", "main")

        with (
            patch("bb_stack.updates.shutil.which", return_value=None),
            self.assertRaisesRegex(StackError, "git is required"),
        ):
            self.manager._git_latest_tag("https://example.test/repo")

    def test_command_runner_accepts_isolated_candidate_environment(self) -> None:
        env = {"HOME": "/tmp/candidate-home", "PATH": "/usr/bin"}
        with patch("bb_stack.updates.subprocess.run") as run:
            self.manager._run(["npm", "ci"], env=env, timeout=180)
        run.assert_called_once_with(
            ["npm", "ci"], env=env, text=True, timeout=180, check=True
        )

        with (
            patch(
                "bb_stack.updates.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["npm", "ci"], 180),
            ),
            self.assertRaisesRegex(StackError, "command failed"),
        ):
            self.manager._run(["npm", "ci"], env=env, timeout=180)
        no_tags = subprocess.CompletedProcess(
            ["git"], 0, stdout="deadbeef\trefs/tags/nightly\n", stderr=""
        )
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/git"),
            patch("bb_stack.updates.subprocess.run", return_value=no_tags),
            self.assertRaisesRegex(ValidationError, "stable numeric"),
        ):
            self.manager._git_latest_tag("https://example.test/repo")

    def test_download_and_mcp_candidate_validation(self) -> None:
        destination = Path(self.temporary.name) / "download" / "payload.bin"
        destination.parent.mkdir()
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        response.read.side_effect = [b"payload", b""]
        with patch("bb_stack.updates.urlopen", return_value=response):
            self.manager._download("https://example.test/payload", destination)
        self.assertEqual(destination.read_bytes(), b"payload")
        self.assertFalse(destination.with_suffix(".bin.part").exists())

        candidate = Path(self.temporary.name) / "mcp-candidate"
        candidate.mkdir()
        (candidate / "mcp_probe.mjs").write_text("probe", encoding="utf-8")
        component = self.component(
            "npm", name="mcp.fixture", target="fixture-package", provider="fixture"
        )
        provider = {"mcp": {"command": "node", "args": ["/runtime/node_modules/x"]}}
        completed = subprocess.CompletedProcess(
            ["bwrap"], 0, stdout='{"connected": true, "tool_count": 3}', stderr=""
        )
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/tool"),
            patch.object(self.manager, "_run"),
            patch(
                "bb_stack.updates.CapabilityRegistry.registry",
                return_value={"providers": {"fixture": provider}},
            ),
            patch("bb_stack.updates.subprocess.run", return_value=completed),
        ):
            result = self.manager._validate_npm_mcp(component, candidate)
        self.assertEqual(result["mcp_handshake"], "passed")
        self.assertEqual(result["tool_count"], 3)

        failed = subprocess.CompletedProcess(
            ["bwrap"], 0, stdout='{"connected": false, "error": "broken"}', stderr=""
        )
        with (
            patch("bb_stack.updates.shutil.which", return_value="/usr/bin/tool"),
            patch.object(self.manager, "_run"),
            patch(
                "bb_stack.updates.CapabilityRegistry.registry",
                return_value={"providers": {"fixture": provider}},
            ),
            patch("bb_stack.updates.subprocess.run", return_value=failed),
            self.assertRaisesRegex(StackError, "handshake failed"),
        ):
            self.manager._validate_npm_mcp(component, candidate)

    def test_stage_github_tree_extracts_and_validates_skill_payload(self) -> None:
        archive = Path(self.temporary.name) / "skill.tar.gz"
        payload = b"---\nname: fixture\ndescription: fixture\n---\n\nFixture skill.\n"
        with tarfile.open(archive, "w:gz") as handle:
            info = tarfile.TarInfo("demo-revision/skill/SKILL.md")
            info.size = len(payload)
            handle.addfile(info, BytesIO(payload))
        candidate = Path(self.temporary.name) / "candidate"
        candidate.mkdir()
        component = self.component(
            "github-tree",
            name="skill.fixture",
            target="fixture",
            repository="https://github.com/example/demo",
            subpath="skill",
        )
        manifest: dict[str, object] = {}

        def download(_url: str, destination: Path) -> None:
            destination.write_bytes(archive.read_bytes())

        with patch.object(self.manager, "_download", side_effect=download):
            self.manager._stage_github_tree(component, "a" * 40, candidate, manifest)
        staged = candidate / "payload" / "SKILL.md"
        self.assertTrue(staged.is_file())
        self.assertEqual(
            manifest["source"],
            "https://github.com/example/demo/tree/" + "a" * 40 + "/skill",
        )
        self.assertRegex(str(manifest["candidate_digest"]), r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
