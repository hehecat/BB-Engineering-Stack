#!/usr/bin/env python3
from __future__ import annotations

import json
import fcntl
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import CommandError, StackError, ValidationError
from bb_stack.paths import StackPaths
from bb_stack.self_update import BOOTSTRAP_TIMEOUT_SECONDS, SelfUpdateManager


class SelfUpdateManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-self-update-")
        self.base = Path(self.temporary.name)
        self.remote = self.base / "remote.git"
        self.seed = self.base / "seed"
        self.source = self.base / "stack"
        self._git(self.base, "init", "--bare", str(self.remote))
        self._git(self.base, "init", "--initial-branch=master", str(self.seed))
        self._write_release("old")
        self._commit_and_push("initial")
        self._git(self.base, "clone", str(self.remote), str(self.source))

        home = self.base / "home"
        self.paths = StackPaths(
            self.source,
            home,
            self.base / "work",
            self.base / "config",
            home / ".claude",
        )
        engagement = self.paths.work_root / "engagements" / "fixture"
        engagement.mkdir(parents=True)
        self.evidence = engagement / "evidence.txt"
        self.evidence.write_text("preserve me\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _git(cwd: Path, *arguments: str) -> str:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "user.name=BB Stack Tests",
                "-c",
                "user.email=bb-stack-tests@example.invalid",
                *arguments,
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def _write_release(self, release: str) -> None:
        (self.seed / "00-L0-Runtime/bin").mkdir(parents=True, exist_ok=True)
        (self.seed / "stack.yaml").write_text(
            f"schema_version: 1\nrelease: {release}\n", encoding="utf-8"
        )
        bootstrap = self.seed / "00-L0-Runtime/bin/bootstrap"
        bootstrap.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            'mkdir -p "$BB_CONFIG_HOME"\n'
            f"printf '{release} %s\\n' \"$*\" >> \"$BB_CONFIG_HOME/bootstrap.log\"\n"
            f"printf '{{\"schema_version\":1,\"release\":\"{release}\"}}\\n'\n",
            encoding="utf-8",
        )
        bootstrap.chmod(0o755)

    def _commit_and_push(self, message: str) -> str:
        self._git(self.seed, "add", ".")
        self._git(self.seed, "commit", "-m", message)
        if not self._git(self.seed, "remote"):
            self._git(self.seed, "remote", "add", "origin", str(self.remote))
        self._git(self.seed, "push", "origin", "master")
        return self._git(self.seed, "rev-parse", "HEAD")

    def _publish_update(self) -> str:
        self._write_release("new")
        return self._commit_and_push("release update")

    def test_rejects_a_non_git_source_tree(self) -> None:
        non_git = self.base / "not-git"
        non_git.mkdir()
        paths = StackPaths(
            non_git,
            self.paths.home,
            self.paths.work_root,
            self.paths.config_home,
            self.paths.claude_config_dir,
        )
        with self.assertRaisesRegex(StackError, "Git repository"):
            SelfUpdateManager(paths).update(profile="minimal", check_only=True)

    def test_rejects_conflicting_non_refresh_modes_at_the_manager_boundary(self) -> None:
        with self.assertRaisesRegex(ValidationError, "mutually exclusive"):
            SelfUpdateManager(self.paths).update(check_only=True, dry_run=True)

    def test_check_allows_a_dirty_source_tree_without_mutation(self) -> None:
        (self.source / "stack.yaml").write_text("local edit\n", encoding="utf-8")
        result = SelfUpdateManager(self.paths).update(profile="minimal", check_only=True)
        self.assertEqual(result["state"], "current")
        self.assertEqual((self.source / "stack.yaml").read_text(), "local edit\n")

    def test_real_update_rejects_a_dirty_source_tree_before_fetching(self) -> None:
        (self.source / "stack.yaml").write_text("local edit\n", encoding="utf-8")
        with self.assertRaisesRegex(StackError, "uncommitted changes"):
            SelfUpdateManager(self.paths).update(profile="minimal")
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())

    def test_real_update_allows_untracked_runtime_artifacts(self) -> None:
        artifact = self.source / ".spec-workflow" / "runtime-state.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("keep me\n", encoding="utf-8")
        remote_commit = self._publish_update()

        result = SelfUpdateManager(self.paths).update(profile="minimal")

        self.assertEqual(result["after"], remote_commit)
        self.assertEqual(artifact.read_text(encoding="utf-8"), "keep me\n")

    def test_real_update_does_not_merge_a_different_remote_branch(self) -> None:
        with self.assertRaisesRegex(StackError, "switch to stable first"):
            SelfUpdateManager(self.paths).update(profile="minimal", branch="stable")
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())

    def test_detached_head_can_update_an_explicit_branch(self) -> None:
        before = self._git(self.source, "rev-parse", "HEAD")
        remote_commit = self._publish_update()
        self._git(self.source, "checkout", "--detach", before)

        result = SelfUpdateManager(self.paths).update(
            profile="minimal", branch="master"
        )

        self.assertEqual(result["current_branch"], None)
        self.assertEqual(result["after"], remote_commit)
        self.assertEqual(self._git(self.source, "branch", "--show-current"), "")

    def test_real_update_validates_worktree_after_acquiring_lock(self) -> None:
        manager = SelfUpdateManager(self.paths)
        events: list[str] = []
        original_lock = manager._update_lock
        original_clean_check = manager._require_clean_worktree

        @contextmanager
        def observed_lock():
            with original_lock():
                events.append("lock")
                yield

        def observed_clean_check() -> None:
            events.append("clean")
            original_clean_check()

        with (
            patch.object(manager, "_update_lock", observed_lock),
            patch.object(manager, "_require_clean_worktree", observed_clean_check),
            patch.object(manager, "_refresh", return_value={"state": "current"}),
        ):
            manager.update(profile="minimal")

        self.assertLess(events.index("lock"), events.index("clean"))

    def test_real_update_rechecks_worktree_after_fetch(self) -> None:
        remote_commit = self._publish_update()
        before = self._git(self.source, "rev-parse", "HEAD")
        manager = SelfUpdateManager(self.paths)
        original_read_remote_commit = manager._read_remote_commit

        def dirty_worktree_after_fetch(
            remote: str, branch: str, *, dry_run: bool
        ) -> str:
            commit = original_read_remote_commit(remote, branch, dry_run=dry_run)
            (self.source / "stack.yaml").write_text(
                "changed during fetch\n", encoding="utf-8"
            )
            return commit

        with (
            patch.object(
                manager,
                "_read_remote_commit",
                side_effect=dirty_worktree_after_fetch,
            ),
            self.assertRaisesRegex(StackError, "changed during update"),
        ):
            manager.update(profile="minimal")

        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), before)
        self.assertNotEqual(before, remote_commit)

    def test_real_update_rechecks_checkout_after_fetch(self) -> None:
        remote_commit = self._publish_update()
        before = self._git(self.source, "rev-parse", "HEAD")
        self._git(self.source, "branch", "side", before)
        manager = SelfUpdateManager(self.paths)
        original_read_remote_commit = manager._read_remote_commit

        def switch_branch_after_fetch(
            remote: str, branch: str, *, dry_run: bool
        ) -> str:
            commit = original_read_remote_commit(remote, branch, dry_run=dry_run)
            self._git(self.source, "switch", "side")
            return commit

        with (
            patch.object(
                manager,
                "_read_remote_commit",
                side_effect=switch_branch_after_fetch,
            ),
            self.assertRaisesRegex(StackError, "checkout changed during update"),
        ):
            manager.update(profile="minimal")

        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), before)
        self.assertNotEqual(before, remote_commit)

    def test_real_update_rejects_a_concurrent_refresh(self) -> None:
        self.paths.config_home.mkdir(parents=True)
        lock_path = self.paths.config_home / "update.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(StackError, "already in progress"):
                SelfUpdateManager(self.paths).update(profile="minimal")
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())

    def test_check_reports_remote_update_without_changing_source_or_workspace(self) -> None:
        remote_commit = self._publish_update()
        before = self._git(self.source, "rev-parse", "HEAD")

        result = SelfUpdateManager(self.paths).update(
            profile="minimal", check_only=True
        )

        self.assertEqual(result["state"], "update_available")
        self.assertEqual(result["before"], before)
        self.assertEqual(result["remote_commit"], remote_commit)
        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), before)
        self.assertIn("release: old", (self.source / "stack.yaml").read_text())
        self.assertFalse((self.paths.config_home / "bootstrap.log").exists())
        self.assertEqual(self.evidence.read_text(encoding="utf-8"), "preserve me\n")

    def test_dry_run_uses_ls_remote_without_fetching_or_bootstrapping(self) -> None:
        remote_commit = self._publish_update()
        before = self._git(self.source, "rev-parse", "HEAD")

        result = SelfUpdateManager(self.paths).update(
            profile="minimal", dry_run=True
        )

        self.assertEqual(result["state"], "remote_differs")
        self.assertEqual(result["relationship"], "unknown_without_fetch")
        self.assertEqual(result["remote_commit"], remote_commit)
        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), before)
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())
        self.assertFalse((self.paths.config_home / "bootstrap.log").exists())

    def test_fast_forwards_then_runs_the_updated_bootstrap_in_a_child_process(self) -> None:
        remote_commit = self._publish_update()

        result = SelfUpdateManager(self.paths).update(profile="minimal")

        self.assertEqual(result["state"], "updated")
        self.assertTrue(result["updated"])
        self.assertEqual(result["after"], remote_commit)
        self.assertEqual(result["bootstrap"]["release"], "new")
        self.assertIn(f"git merge --ff-only {remote_commit}", result["commands"])
        log = (self.paths.config_home / "bootstrap.log").read_text(encoding="utf-8")
        calls = log.splitlines()
        self.assertEqual(len(calls), 2)
        self.assertIn("--dry-run", calls[0])
        self.assertNotIn("--dry-run", calls[1])
        self.assertEqual(self.evidence.read_text(encoding="utf-8"), "preserve me\n")

    def test_fast_forward_uses_the_revision_captured_by_fetch(self) -> None:
        fetched_commit = self._publish_update()
        manager = SelfUpdateManager(self.paths)
        original_relationship = manager._relationship

        def overwrite_fetch_head_after_comparison(local: str, remote: str) -> str:
            relationship = original_relationship(local, remote)
            self._write_release("newer")
            self._commit_and_push("later release")
            self._git(self.source, "fetch", "origin", "master")
            return relationship

        with patch.object(
            manager, "_relationship", side_effect=overwrite_fetch_head_after_comparison
        ):
            result = manager.update(profile="minimal")

        self.assertEqual(result["remote_commit"], fetched_commit)
        self.assertEqual(result["after"], fetched_commit)
        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), fetched_commit)

    def test_bootstrap_failure_reports_the_source_refresh_boundary(self) -> None:
        self._publish_update()
        bootstrap = self.seed / "00-L0-Runtime/bin/bootstrap"
        with bootstrap.open("a", encoding="utf-8") as stream:
            stream.write("exit 7\n")
        remote_commit = self._commit_and_push("broken bootstrap")

        with self.assertRaisesRegex(CommandError, "source advanced to"):
            SelfUpdateManager(self.paths).update(profile="minimal")

        self.assertEqual(self._git(self.source, "rev-parse", "HEAD"), remote_commit)

    def test_requires_an_explicit_profile_when_old_install_has_no_state(self) -> None:
        with self.assertRaisesRegex(StackError, "--profile"):
            SelfUpdateManager(self.paths).update()

    def test_uses_the_profile_saved_by_bootstrap(self) -> None:
        self.paths.config_home.mkdir(parents=True)
        (self.paths.config_home / "install.json").write_text(
            json.dumps({"schema_version": 1, "profile": "web"}) + "\n",
            encoding="utf-8",
        )

        result = SelfUpdateManager(self.paths).update(dry_run=True)

        self.assertEqual(result["profile"], "web")

    def test_git_network_waits_have_a_bounded_timeout(self) -> None:
        manager = SelfUpdateManager(self.paths)
        with (
            patch(
                "bb_stack.self_update.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["git", "fetch"], 300),
            ) as run,
            self.assertRaisesRegex(CommandError, "timed out"),
        ):
            manager._git("fetch", "origin", "master")
        self.assertEqual(run.call_args.kwargs["timeout"], 300)

    def test_bootstrap_wait_has_a_bounded_timeout(self) -> None:
        manager = SelfUpdateManager(self.paths)
        with (
            patch(
                "bb_stack.self_update.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["bootstrap"], BOOTSTRAP_TIMEOUT_SECONDS),
            ) as run,
            self.assertRaisesRegex(CommandError, "bootstrap timed out"),
        ):
            manager._run_bootstrap(
                "minimal",
                dry_run=True,
                include_optional=False,
                skip_tools=False,
                skip_node=False,
                skip_skills=False,
            )
        self.assertEqual(run.call_args.kwargs["timeout"], BOOTSTRAP_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
