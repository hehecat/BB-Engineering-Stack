from __future__ import annotations

import fcntl
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .errors import CommandError, ValidationError
from .io import expand, load_yaml
from .paths import StackPaths
from .validation import validate


class DataManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.config = paths.root / "00-L0-Runtime" / "config"

    def catalog(self) -> dict[str, Any]:
        document = load_yaml(self.config / "data-catalog.yaml")
        validate(
            document,
            self.config / "data-catalog.schema.json",
            "data catalog",
        )
        datasets = document["datasets"]
        for profile_name, profile in document["profiles"].items():
            for requirement in profile["required"] + profile["optional"]:
                dataset_name = requirement["dataset"]
                if dataset_name not in datasets:
                    raise ValidationError(
                        f"data profile {profile_name} references unknown dataset: {dataset_name}"
                    )
                unknown = set(requirement["bundles"]) - set(
                    datasets[dataset_name]["bundles"]
                )
                if unknown:
                    raise ValidationError(
                        f"data profile {profile_name} references unknown {dataset_name} "
                        f"bundle(s): {', '.join(sorted(unknown))}"
                    )
        for name in datasets:
            self._dataset_spec(name, document)
        return document

    def validate_config(self) -> dict[str, Any]:
        document = self.catalog()
        return {
            "datasets": sorted(document["datasets"]),
            "profiles": sorted(document["profiles"]),
        }

    def path(self, dataset: str) -> Path:
        return self._destination(self._dataset_spec(dataset))

    def status(
        self,
        dataset: str | None = None,
        *,
        profile: str | None = None,
    ) -> dict[str, Any]:
        if dataset and profile:
            raise ValidationError("choose either a dataset or a profile")
        document = self.catalog()
        required: dict[str, set[str]] = {}
        optional: dict[str, set[str]] = {}
        if profile:
            if profile not in document["profiles"]:
                raise ValidationError(f"unknown data profile: {profile}")
            for level, target in (("required", required), ("optional", optional)):
                for item in document["profiles"][profile][level]:
                    target.setdefault(item["dataset"], set()).update(item["bundles"])
            selected = sorted(set(required) | set(optional))
        elif dataset:
            self._dataset_spec(dataset, document)
            selected = [dataset]
            required[dataset] = set(document["datasets"][dataset]["bundles"])
        else:
            selected = sorted(document["datasets"])
            required = {
                name: set(spec["bundles"])
                for name, spec in document["datasets"].items()
            }
        items: dict[str, dict[str, Any]] = {}
        for name in selected:
            bundles = sorted(required.get(name, set()) | optional.get(name, set()))
            item = self.dataset_status(name, bundles, document=document)
            item["required_bundles"] = sorted(required.get(name, set()))
            item["optional_bundles"] = sorted(optional.get(name, set()))
            items[name] = item
        ready = all(
            items[name]["source_ready"]
            and set(items[name]["required_bundles"]).issubset(
                items[name]["installed_bundles"]
            )
            for name in required
        )
        return {
            "schema_version": 1,
            "ready": ready,
            "profile": profile,
            "items": items,
        }

    def dataset_status(
        self,
        dataset: str,
        bundles: list[str] | None = None,
        *,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        catalog = document or self.catalog()
        spec = self._dataset_spec(dataset, catalog)
        selected = bundles or sorted(spec["bundles"])
        self._validate_bundles(dataset, spec, selected)
        destination = self._destination(spec)
        present = destination.exists()
        managed = (destination / ".git").is_dir()
        remote = (
            self._git_output(destination, ["remote", "get-url", "origin"])
            if managed
            else None
        )
        revision = (
            self._git_output(destination, ["rev-parse", "HEAD"]) if managed else None
        )
        remote_matches = bool(
            remote
            and self._normalize_repository(remote)
            == self._normalize_repository(spec["repository"])
        )
        revision_matches = revision == spec["revision"]
        sparse_paths = self._sparse_paths(destination) if managed else []
        installed = [
            name
            for name in selected
            if (name != "complete" or sparse_paths == ["."])
            and all(
                (destination / path).is_file()
                for path in spec["bundles"][name]["sentinels"]
            )
        ]
        missing = sorted(set(selected) - set(installed))
        source_ready = bool(managed and remote_matches and revision_matches)
        if not present:
            state = "missing"
        elif not managed or not remote_matches:
            state = "incompatible"
        elif not revision_matches:
            state = "stale"
        elif missing:
            state = "partial"
        else:
            state = "ready"
        return {
            "name": dataset,
            "state": state,
            "destination": str(destination),
            "repository": spec["repository"],
            "expected_revision": spec["revision"],
            "current_revision": revision,
            "source_ready": source_ready,
            "managed_source": bool(managed and remote_matches),
            "sparse_paths": sparse_paths,
            "installed_bundles": sorted(installed),
            "missing_bundles": missing,
            "selected_bundles": sorted(selected),
        }

    def ensure_profile(
        self,
        profile: str,
        *,
        include_optional: bool = False,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        document = self.catalog()
        if profile not in document["profiles"]:
            raise ValidationError(f"unknown data profile: {profile}")
        requirements = list(document["profiles"][profile]["required"])
        if include_optional:
            requirements.extend(document["profiles"][profile]["optional"])
        merged: dict[str, list[str]] = {}
        for item in requirements:
            merged.setdefault(item["dataset"], []).extend(item["bundles"])
        return [
            self.ensure(
                name,
                sorted(set(bundles)),
                dry_run=dry_run,
                document=document,
            )
            for name, bundles in sorted(merged.items())
        ]

    def ensure(
        self,
        dataset: str,
        bundles: list[str] | None = None,
        *,
        dry_run: bool = False,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        catalog = document or self.catalog()
        spec = self._dataset_spec(dataset, catalog)
        selected = bundles or (
            ["complete"] if "complete" in spec["bundles"] else sorted(spec["bundles"])
        )
        selected = sorted(set(selected))
        self._validate_bundles(dataset, spec, selected)
        before = self.dataset_status(dataset, selected, document=catalog)
        if before["state"] == "ready":
            return {"component": f"data:{dataset}", "state": "ready", **before}
        if before["state"] == "incompatible":
            raise CommandError(
                f"refusing to replace unmanaged or unexpected data directory: {before['destination']}"
            )
        requested_paths = self._bundle_paths(spec, selected)
        existing_paths = before["sparse_paths"] if before["managed_source"] else []
        desired_paths = sorted(set(existing_paths) | set(requested_paths))
        if "." in desired_paths:
            desired_paths = ["."]
        if dry_run:
            return {
                "component": f"data:{dataset}",
                "state": "planned",
                "destination": before["destination"],
                "bundles": selected,
                "sparse_paths": desired_paths,
            }
        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        lock_root = self.paths.data_root / ".locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_path = lock_root / f"{dataset}.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self.dataset_status(dataset, selected, document=catalog)
            if current["state"] == "ready":
                return {"component": f"data:{dataset}", "state": "ready", **current}
            if current["state"] == "incompatible":
                raise CommandError(
                    f"refusing to replace unmanaged or unexpected data directory: {current['destination']}"
                )
            if current["managed_source"]:
                existing_paths = current["sparse_paths"]
                desired_paths = sorted(set(existing_paths) | set(requested_paths))
                if "." in desired_paths:
                    desired_paths = ["."]
            self._install(dataset, spec, selected, desired_paths)
        after = self.dataset_status(dataset, selected, document=catalog)
        if after["state"] != "ready":
            raise CommandError(
                f"data installation did not satisfy {dataset}: {after['state']}"
            )
        return {
            "component": f"data:{dataset}",
            **after,
            "dataset_state": after["state"],
            "state": "installed",
        }

    def update_check(self, dataset: str | None = None) -> dict[str, Any]:
        document = self.catalog()
        selected = [dataset] if dataset else sorted(document["datasets"])
        items: dict[str, dict[str, Any]] = {}
        for name in selected:
            spec = self._dataset_spec(name, document)
            output = self._run_capture(
                [
                    "git",
                    "ls-remote",
                    "--exit-code",
                    spec["repository"],
                    f"refs/heads/{spec['branch']}",
                ],
                timeout=int(spec.get("network_timeout_seconds", 600)),
            )
            fields = output.split()
            if len(fields) < 2 or len(fields[0]) != 40:
                raise CommandError(f"unexpected git ls-remote output for {name}")
            latest = fields[0]
            items[name] = {
                "pinned_revision": spec["revision"],
                "latest_revision": latest,
                "update_available": latest != spec["revision"],
                "branch": spec["branch"],
            }
        return {"schema_version": 1, "items": items}

    def _install(
        self,
        dataset: str,
        spec: dict[str, Any],
        bundles: list[str],
        sparse_paths: list[str],
    ) -> None:
        destination = self._destination(spec)
        staging_root = self.paths.data_root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f"{dataset}-", dir=staging_root))
        backup = destination.with_name(f".{destination.name}.backup-{os.getpid()}")
        timeout = int(spec.get("network_timeout_seconds", 600))
        attempts = int(spec.get("retry_attempts", 3))
        try:
            self._run(["git", "init", "--quiet", str(stage)], timeout=30)
            self._run(
                [
                    "git",
                    "-C",
                    str(stage),
                    "remote",
                    "add",
                    "origin",
                    spec["repository"],
                ],
                timeout=30,
            )
            if sparse_paths != ["."]:
                self._run(
                    ["git", "-C", str(stage), "sparse-checkout", "init", "--cone"],
                    timeout=30,
                )
                self._run(
                    [
                        "git",
                        "-C",
                        str(stage),
                        "sparse-checkout",
                        "set",
                        "--cone",
                        "--",
                        *sparse_paths,
                    ],
                    timeout=30,
                )
            last_error: CommandError | None = None
            for attempt in range(attempts):
                try:
                    self._run(
                        [
                            "git",
                            "-C",
                            str(stage),
                            "fetch",
                            "--quiet",
                            "--depth",
                            "1",
                            "--filter=blob:none",
                            "origin",
                            spec["revision"],
                        ],
                        timeout=timeout,
                    )
                    last_error = None
                    break
                except CommandError as error:
                    last_error = error
                    if attempt + 1 < attempts:
                        time.sleep(min(2**attempt, 4))
            if last_error:
                raise last_error
            self._run(
                [
                    "git",
                    "-C",
                    str(stage),
                    "checkout",
                    "--quiet",
                    "--detach",
                    "FETCH_HEAD",
                ],
                timeout=timeout,
            )
            missing = [
                sentinel
                for bundle in bundles
                for sentinel in spec["bundles"][bundle]["sentinels"]
                if not (stage / sentinel).is_file()
            ]
            if missing:
                raise CommandError(
                    f"staged {dataset} is incomplete; missing: {', '.join(sorted(set(missing)))}"
                )
            if destination.exists():
                os.replace(destination, backup)
            try:
                os.replace(stage, destination)
            except Exception:
                if backup.exists() and not destination.exists():
                    os.replace(backup, destination)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _dataset_spec(
        self,
        dataset: str,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        catalog = document or load_yaml(self.config / "data-catalog.yaml")
        if dataset not in catalog["datasets"]:
            raise ValidationError(f"unknown dataset: {dataset}")
        spec = expand(catalog["datasets"][dataset], self.paths.environment())
        destination = self._destination(spec)
        for bundle_name, bundle in spec["bundles"].items():
            for value in bundle["paths"] + bundle["sentinels"]:
                path = Path(value)
                if path.is_absolute() or ".." in path.parts:
                    raise ValidationError(
                        f"unsafe path in {dataset}/{bundle_name}: {value}"
                    )
        if (
            destination == self.paths.data_root
            or self.paths.data_root not in destination.parents
        ):
            raise ValidationError(
                f"dataset destination must be below BB_DATA_ROOT: {destination}"
            )
        return spec

    def _destination(self, spec: dict[str, Any]) -> Path:
        return Path(spec["destination"]).expanduser().resolve()

    @staticmethod
    def _validate_bundles(
        dataset: str, spec: dict[str, Any], bundles: list[str]
    ) -> None:
        unknown = set(bundles) - set(spec["bundles"])
        if unknown:
            raise ValidationError(
                f"unknown {dataset} bundle(s): {', '.join(sorted(unknown))}"
            )

    @staticmethod
    def _bundle_paths(spec: dict[str, Any], bundles: list[str]) -> list[str]:
        return sorted(
            {path for bundle in bundles for path in spec["bundles"][bundle]["paths"]}
        )

    @staticmethod
    def _normalize_repository(value: str) -> str:
        return value.removesuffix(".git").rstrip("/")

    @staticmethod
    def _git_output(root: Path, arguments: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), *arguments],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        return completed.stdout.strip() or None

    @classmethod
    def _sparse_paths(cls, root: Path) -> list[str]:
        if not (root / ".git").is_dir():
            return []
        output = cls._git_output(root, ["sparse-checkout", "list"])
        return output.splitlines() if output else ["."]

    @staticmethod
    def _run(command: list[str], *, timeout: int) -> None:
        try:
            subprocess.run(
                command,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=True,
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as error:
            detail = getattr(error, "stderr", None)
            suffix = f": {str(detail).strip()}" if detail else ""
            raise CommandError(
                f"command failed: {shlex.join(command)}{suffix}"
            ) from error

    @staticmethod
    def _run_capture(command: list[str], *, timeout: int) -> str:
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=True,
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as error:
            detail = getattr(error, "stderr", None)
            suffix = f": {str(detail).strip()}" if detail else ""
            raise CommandError(
                f"command failed: {shlex.join(command)}{suffix}"
            ) from error
        return completed.stdout.strip()
