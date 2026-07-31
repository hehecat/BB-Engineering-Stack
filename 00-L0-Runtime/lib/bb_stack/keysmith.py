from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .errors import CommandError, ValidationError
from .io import atomic_write, dump_json, load_json, load_yaml
from .paths import StackPaths
from .profiles import ProfileRegistry
from .validation import validate


class KeysmithAdapter:
    """Pinned deployment adapter; Keysmith is not a second Prompt source."""

    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.stack = load_yaml(paths.root / "stack.yaml")
        validate(self.stack, paths.root / "schema" / "stack.schema.json", "stack manifest")
        self.config = self.stack["keysmith"]
        self.deployment = paths.config_home / "keysmith-deployment.json"

    def source(self, *, fetch: bool) -> Path:
        override = os.environ.get("BB_KEYSMITH_SOURCE")
        if override:
            source = Path(override).expanduser().resolve()
            self._verify_source(source, require_revision=False)
            return source
        cache_value = self.config["cache_dir"].replace(
            "${BB_CONFIG_HOME}", str(self.paths.config_home)
        )
        source = Path(cache_value).expanduser().resolve()
        if not source.exists():
            if not fetch:
                raise CommandError("Keysmith source is not cached; run keysmith install")
            source.parent.mkdir(parents=True, exist_ok=True)
            self._run(["git", "clone", self.config["repository"], str(source)])
            self._run(["git", "-C", str(source), "checkout", self.config["revision"]])
        self._verify_source(source, require_revision=True)
        return source

    def fetch(self) -> dict[str, Any]:
        source = self.source(fetch=True)
        return {
            "schema_version": 1,
            "source": str(source),
            "repository": self.config["repository"],
            "revision": self.config["revision"],
            "deployed": self.deployment.is_file(),
        }

    def _verify_source(self, source: Path, *, require_revision: bool) -> None:
        script = source / "claude-instruct.py"
        if not script.is_file():
            raise ValidationError(f"invalid Keysmith source: {source}")
        if require_revision:
            completed = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            actual = completed.stdout.strip()
            if actual != self.config["revision"]:
                raise ValidationError(
                    f"Keysmith revision mismatch: {actual or 'unknown'} != {self.config['revision']}"
                )

    @staticmethod
    def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            detail = ""
            if isinstance(error, subprocess.CalledProcessError):
                detail = (error.stderr or error.stdout or "").strip()
            raise CommandError(
                f"Keysmith command failed: {' '.join(command)}" + (f": {detail}" if detail else "")
            ) from error

    def install(self, profile: str, *, yes: bool) -> dict[str, Any]:
        if not yes:
            raise ValidationError("persistent Keysmith deployment requires explicit --yes")
        if self.paths.claude_config_dir != self.paths.home / ".claude":
            raise ValidationError(
                "Keysmith runtime currently requires Claude's standard $HOME/.claude directory"
            )
        rendered = ProfileRegistry(self.paths).render(profile)
        if rendered.prompt_mode != "replacement":
            raise ValidationError(
                "Keysmith persistent runtime replaces Claude's native system Prompt; "
                "select a replacement profile"
            )
        source = self.source(fetch=True)
        script = source / "claude-instruct.py"
        memory = self.paths.root / "00-L0-Runtime" / "config" / "keysmith-memory.md"
        append = self.paths.root / "00-L0-Runtime" / "config" / "keysmith-append.md"
        self._run(
            [
                "python3",
                str(script),
                "install",
                "--scope",
                "user",
                "--name",
                "bb-stack-runtime",
                "--file",
                str(memory),
                "--runtime",
                "--append-file",
                str(append),
                "--yes",
            ]
        )

        prompt_content = Path(rendered.output_file).read_text(encoding="utf-8")
        keysmith_dir = self.paths.claude_config_dir / "keysmith"
        system_path = keysmith_dir / "system-prompt.md"
        append_path = keysmith_dir / "append-prompt.md"
        atomic_write(system_path, prompt_content)
        atomic_write(append_path, "\n")
        settings_path = self.paths.claude_config_dir / "settings.json"
        settings = load_json(settings_path) if settings_path.is_file() else {}
        settings["systemPrompt"] = prompt_content
        dump_json(settings_path, settings)
        deployment = {
            "schema_version": 1,
            "profile": profile,
            "prompt_mode": rendered.prompt_mode,
            "prompt_sha256": hashlib.sha256(prompt_content.encode("utf-8")).hexdigest(),
            "system_prompt": str(system_path),
            "append_prompt": str(append_path),
            "keysmith_source": str(source),
            "keysmith_revision": self.config["revision"],
        }
        dump_json(self.deployment, deployment, 0o600)
        return deployment

    def status(self) -> dict[str, Any]:
        deployment = load_json(self.deployment) if self.deployment.is_file() else None
        managed_match = False
        if deployment and Path(deployment["system_prompt"]).is_file():
            content = Path(deployment["system_prompt"]).read_bytes()
            managed_match = hashlib.sha256(content).hexdigest() == deployment["prompt_sha256"]
        try:
            source = self.source(fetch=False)
        except CommandError as error:
            return {
                "schema_version": 1,
                "deployed": bool(deployment),
                "managed_prompt_matches": managed_match,
                "deployment": deployment,
                "source_cached": False,
                "doctor": {"available": False, "reason": str(error)},
            }
        completed = self._run(
            ["python3", str(source / "claude-instruct.py"), "doctor", "--json"],
            capture=True,
        )
        try:
            doctor = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise CommandError("Keysmith doctor returned invalid JSON") from error
        return {
            "schema_version": 1,
            "deployed": bool(deployment),
            "managed_prompt_matches": managed_match,
            "deployment": deployment,
            "source_cached": True,
            "doctor": doctor,
        }

    def uninstall(self, *, yes: bool) -> dict[str, Any]:
        if not yes:
            raise ValidationError("Keysmith uninstall requires explicit --yes")
        source = self.source(fetch=False)
        deployment = load_json(self.deployment) if self.deployment.is_file() else None
        self._run(
            [
                "python3",
                str(source / "claude-instruct.py"),
                "uninstall",
                "--scope",
                "user",
                "--name",
                "bb-stack-runtime",
                "--runtime",
                "--yes",
            ]
        )
        settings_path = self.paths.claude_config_dir / "settings.json"
        settings_cleaned = False
        if deployment and settings_path.is_file():
            settings = load_json(settings_path)
            current = settings.get("systemPrompt")
            if isinstance(current, str):
                digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
                if digest == deployment.get("prompt_sha256"):
                    settings.pop("systemPrompt", None)
                    dump_json(settings_path, settings)
                    settings_cleaned = True
        if self.deployment.exists():
            backup = self.deployment.with_suffix(".uninstalled.json")
            serial = 1
            while backup.exists():
                backup = self.deployment.with_name(f"keysmith-deployment.uninstalled.{serial}.json")
                serial += 1
            self.deployment.rename(backup)
        return {"schema_version": 1, "uninstalled": True, "settings_cleaned": settings_cleaned}
