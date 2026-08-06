from __future__ import annotations

import fcntl
import json
import shlex
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import CommandError, StackError, ValidationError
from .io import load_json
from .paths import StackPaths

INSTALL_STATE_SCHEMA_VERSION = 1
GIT_TIMEOUT_SECONDS = 300
BOOTSTRAP_TIMEOUT_SECONDS = 1800


class SelfUpdateManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.commands: list[str] = []

    def update(
        self,
        *,
        profile: str | None = None,
        remote: str = "origin",
        branch: str | None = None,
        check_only: bool = False,
        dry_run: bool = False,
        include_optional: bool = False,
        skip_tools: bool = False,
        skip_node: bool = False,
        skip_skills: bool = False,
    ) -> dict[str, Any]:
        self.commands = []
        if check_only and dry_run:
            raise ValidationError("check_only and dry_run are mutually exclusive")
        self._validate_repository()
        current_branch = self._current_branch(required=branch is None)
        selected_branch = branch or current_branch
        self._validate_remote(remote)
        selected_profile = (
            profile
            if profile is not None
            else None if check_only else self._saved_profile()
        )
        if check_only or dry_run:
            before = self._git_output("rev-parse", "HEAD")
            remote_commit = self._read_remote_commit(
                remote, selected_branch, dry_run=dry_run
            )
            relationship = (
                "current" if before == remote_commit else "unknown_without_fetch"
            ) if dry_run else self._relationship(before, remote_commit)
            common = {
                "schema_version": 1,
                "operation": "stack-source-update",
                "root": str(self.paths.root),
                "remote": remote,
                "branch": selected_branch,
                "current_branch": current_branch,
                "profile": selected_profile,
                "before": before,
                "remote_commit": remote_commit,
                "relationship": relationship,
                "check": check_only,
                "dry_run": dry_run,
            }
            if check_only:
                return {
                    **common,
                    "state": self._check_state(relationship),
                    "updated": False,
                    "after": before,
                    "bootstrap": None,
                    "commands": self.commands,
                }
            if relationship in {"local_ahead", "diverged"}:
                raise StackError(
                    f"local branch is {relationship.replace('_', ' ')} relative to "
                    f"{remote}/{selected_branch}; publish or reconcile the local commits first"
                )
            return {
                **common,
                "state": (
                    "would_refresh" if relationship == "current" else "remote_differs"
                ),
                "updated": False,
                "after": before,
                "bootstrap": None,
                "commands": self.commands,
            }

        with self._update_lock():
            self._require_clean_worktree()
            current_branch = self._current_branch(required=branch is None)
            selected_branch = branch or current_branch
            if selected_branch is None:
                raise StackError("detached HEAD requires --branch for update")
            if current_branch is not None and selected_branch != current_branch:
                raise StackError(
                    f"cannot update {remote}/{selected_branch} while {current_branch} "
                    f"is checked out; switch to {selected_branch} first"
                )
            return self._refresh(
                remote=remote,
                branch=selected_branch,
                current_branch=current_branch,
                profile=selected_profile,
                include_optional=include_optional,
                skip_tools=skip_tools,
                skip_node=skip_node,
                skip_skills=skip_skills,
            )

    def _refresh(
        self,
        *,
        remote: str,
        branch: str,
        current_branch: str | None,
        profile: str,
        include_optional: bool,
        skip_tools: bool,
        skip_node: bool,
        skip_skills: bool,
    ) -> dict[str, Any]:
        before = self._git_output("rev-parse", "HEAD")
        remote_commit = self._read_remote_commit(remote, branch, dry_run=False)
        self._require_clean_worktree(
            message="Stack source changed during update; rerun after reviewing the change"
        )
        observed_branch = self._current_branch(required=False)
        observed_head = self._git_output("rev-parse", "HEAD")
        if observed_branch != current_branch or observed_head != before:
            raise StackError(
                "Stack source checkout changed during update; rerun from the intended "
                "branch or detached commit"
            )
        relationship = self._relationship(before, remote_commit)
        if relationship in {"local_ahead", "diverged"}:
            raise StackError(
                f"local branch is {relationship.replace('_', ' ')} relative to "
                f"{remote}/{branch}; publish or reconcile the local commits first"
            )

        # Use the immutable object ID captured by fetch. FETCH_HEAD is shared
        # repository state and another Git process may replace it concurrently.
        self._git("merge", "--ff-only", remote_commit, record=True)
        after = self._git_output("rev-parse", "HEAD")
        if after != remote_commit:
            raise StackError(
                f"fast-forward did not reach {remote}/{branch}: "
                f"expected {remote_commit}, got {after}"
            )

        try:
            self._run_bootstrap(
                profile,
                dry_run=True,
                include_optional=include_optional,
                skip_tools=skip_tools,
                skip_node=skip_node,
                skip_skills=skip_skills,
            )
            bootstrap = self._run_bootstrap(
                profile,
                dry_run=False,
                include_optional=include_optional,
                skip_tools=skip_tools,
                skip_node=skip_node,
                skip_skills=skip_skills,
            )
        except CommandError as error:
            raise CommandError(
                f"Stack source advanced to {after}, but local refresh failed; "
                f"rerun update after fixing the installation issue: {error}"
            ) from error
        return {
            "schema_version": 1,
            "operation": "stack-source-update",
            "root": str(self.paths.root),
            "remote": remote,
            "branch": branch,
            "current_branch": current_branch,
            "profile": profile,
            "before": before,
            "remote_commit": remote_commit,
            "relationship": relationship,
            "check": False,
            "dry_run": False,
            "state": "updated" if after != before else "refreshed",
            "updated": after != before,
            "after": after,
            "bootstrap": bootstrap,
            "work_root": str(self.paths.work_root),
            "commands": self.commands,
        }

    @contextmanager
    def _update_lock(self):
        self.paths.config_home.mkdir(parents=True, exist_ok=True)
        lock_path = self.paths.config_home / "update.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise StackError(
                    "another bb-stack update is already in progress; "
                    "wait for it to finish and rerun"
                ) from error
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @property
    def install_state(self) -> Path:
        return self.paths.config_home / "install.json"

    def _saved_profile(self) -> str:
        if not self.install_state.is_file():
            raise StackError(
                "no saved bootstrap profile; run bb-stack update --profile PROFILE once"
            )
        try:
            state = load_json(self.install_state)
        except ValidationError as error:
            raise StackError(
                f"invalid install state {self.install_state}; rerun with --profile PROFILE"
            ) from error
        profile = state.get("profile")
        if (
            state.get("schema_version") != INSTALL_STATE_SCHEMA_VERSION
            or not isinstance(profile, str)
            or not profile
        ):
            raise StackError(
                f"invalid install state {self.install_state}; rerun with --profile PROFILE"
            )
        return profile

    def _validate_repository(self) -> None:
        completed = self._git("rev-parse", "--show-toplevel", check=False)
        if completed.returncode != 0:
            raise StackError(
                f"BB_STACK_ROOT is not a Git repository: {self.paths.root}"
            )
        top_level = Path(completed.stdout.strip()).resolve()
        if top_level != self.paths.root.resolve():
            raise StackError(
                f"BB_STACK_ROOT must be the Git repository root: {self.paths.root}"
            )

    def _require_clean_worktree(
        self, *, message: str = "Stack source has uncommitted changes; commit or move them before updating"
    ) -> None:
        status = self._git_output("status", "--porcelain", "--untracked-files=normal")
        if status:
            raise StackError(message)

    def _current_branch(self, *, required: bool) -> str | None:
        branch = self._git_output("branch", "--show-current")
        if not branch and required:
            raise StackError("Stack source is in detached HEAD state; pass --branch")
        return branch or None

    def _validate_remote(self, remote: str) -> None:
        completed = self._git("remote", "get-url", remote, check=False)
        if completed.returncode != 0:
            raise StackError(f"Git remote does not exist: {remote}")

    def _read_remote_commit(
        self, remote: str, branch: str, *, dry_run: bool
    ) -> str:
        if dry_run:
            completed = self._git(
                "ls-remote",
                "--exit-code",
                "--heads",
                remote,
                f"refs/heads/{branch}",
                record=True,
            )
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            if len(lines) != 1:
                raise StackError(f"remote branch does not exist: {remote}/{branch}")
            return lines[0].split(maxsplit=1)[0]

        self._git("fetch", "--quiet", remote, branch, record=True)
        return self._git_output("rev-parse", "FETCH_HEAD")

    def _relationship(self, local: str, remote: str) -> str:
        if local == remote:
            return "current"
        if self._is_ancestor(local, remote):
            return "behind"
        if self._is_ancestor(remote, local):
            return "local_ahead"
        return "diverged"

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        completed = self._git(
            "merge-base", "--is-ancestor", ancestor, descendant, check=False
        )
        if completed.returncode not in {0, 1}:
            raise CommandError("git merge-base failed while comparing update commits")
        return completed.returncode == 0

    @staticmethod
    def _check_state(relationship: str) -> str:
        return {
            "current": "current",
            "behind": "update_available",
            "local_ahead": "local_ahead",
            "diverged": "diverged",
        }[relationship]

    def _run_bootstrap(
        self,
        profile: str,
        *,
        dry_run: bool,
        include_optional: bool,
        skip_tools: bool,
        skip_node: bool,
        skip_skills: bool,
    ) -> dict[str, Any]:
        command = [
            str(self.paths.root / "00-L0-Runtime" / "bin" / "bootstrap"),
            "--profile",
            profile,
            "--work-root",
            str(self.paths.work_root),
        ]
        if include_optional:
            command.append("--with-optional")
        if skip_tools:
            command.append("--skip-tools")
        if skip_node:
            command.append("--skip-node")
        if skip_skills:
            command.append("--skip-skills")
        if dry_run:
            command.append("--dry-run")
        command.append("--json")
        self.commands.append(shlex.join(command))
        env = self.paths.environment()
        env["PATH"] = self.paths.runtime_path()
        try:
            completed = subprocess.run(
                command,
                cwd=self.paths.root,
                env=env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                timeout=BOOTSTRAP_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise CommandError(
                "updated bootstrap timed out after "
                f"{BOOTSTRAP_TIMEOUT_SECONDS} seconds"
            ) from error
        except OSError as error:
            raise CommandError(f"failed to start updated bootstrap: {error}") from error
        if completed.returncode != 0:
            raise CommandError(
                f"updated bootstrap failed with exit code {completed.returncode}"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise CommandError("updated bootstrap returned invalid JSON") from error
        if not isinstance(result, dict):
            raise CommandError("updated bootstrap returned a non-object result")
        return result

    def _git_output(self, *arguments: str) -> str:
        return self._git(*arguments).stdout.strip()

    def _git(
        self,
        *arguments: str,
        check: bool = True,
        record: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = ["git", *arguments]
        if record:
            self.commands.append(shlex.join(command))
        try:
            completed = subprocess.run(
                command,
                cwd=self.paths.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise CommandError(
                f"git command timed out after {GIT_TIMEOUT_SECONDS} seconds: "
                f"{shlex.join(command)}"
            ) from error
        except OSError as error:
            raise CommandError(f"failed to start git: {error}") from error
        if check and completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            suffix = f": {detail}" if detail else ""
            raise CommandError(f"command failed: {shlex.join(command)}{suffix}")
        return completed
