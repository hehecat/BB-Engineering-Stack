from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
from typing import Any

from .errors import StackError, ValidationError
from .io import load_yaml, load_yaml_text
from .paths import StackPaths
from .validation import validate


class SkillRegistry:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.layer = paths.root / "04-L4-Skills"
        self.manifest_path = self.layer / "skills.yaml"
        self.manifest_schema = self.layer / "schema" / "skills.schema.json"
        self.profile_schema = self.layer / "schema" / "profile.schema.json"
        self.profile_dir = self.layer / "profiles"

    def manifest(self) -> dict[str, Any]:
        value = load_yaml(self.manifest_path)
        validate(value, self.manifest_schema, "Skill manifest")
        return value

    def profile_names(self) -> list[str]:
        return sorted(path.stem for path in self.profile_dir.glob("*.yaml"))

    def profile(self, name: str) -> dict[str, Any]:
        path = self.profile_dir / f"{name}.yaml"
        if not path.is_file():
            raise ValidationError(f"unknown Skill profile: {name}")
        value = load_yaml(path)
        validate(value, self.profile_schema, f"Skill profile {name}")
        if value["name"] != name:
            raise ValidationError(f"Skill profile filename/name mismatch: {path}")
        return value

    def source(self, name: str) -> Path:
        skills = self.manifest()["skills"]
        if name not in skills:
            raise ValidationError(f"unknown Skill: {name}")
        source = (self.layer / skills[name]["source"]).resolve()
        try:
            source.relative_to(self.layer.resolve())
        except ValueError as error:
            raise ValidationError(f"Skill source escapes L4: {source}") from error
        return source

    def validate_all(self) -> list[dict[str, str]]:
        manifest = self.manifest()
        results: list[dict[str, str]] = []
        for name, metadata in sorted(manifest["skills"].items()):
            source = (self.layer / metadata["source"]).resolve()
            skill_file = source / "SKILL.md"
            if not skill_file.is_file():
                raise ValidationError(f"missing SKILL.md for {name}: {skill_file}")
            frontmatter = self._frontmatter(skill_file)
            if frontmatter.get("name") != name:
                raise ValidationError(
                    f"Skill frontmatter/name mismatch: {name} != {frontmatter.get('name')}"
                )
            description = frontmatter.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValidationError(f"Skill description is missing: {name}")
            results.append(
                {
                    "name": name,
                    "role": metadata["role"],
                    "digest": self.tree_digest(source),
                    "source": str(source.relative_to(self.paths.root)),
                }
            )

        skill_names = set(manifest["skills"])
        for profile_name in self.profile_names():
            profile = self.profile(profile_name)
            selected = set(profile["required"] + profile["optional"])
            missing = sorted(selected - skill_names)
            if missing:
                raise ValidationError(
                    f"Skill profile {profile_name} references unknown Skills: {', '.join(missing)}"
                )
            if profile["orchestrator"] not in profile["required"]:
                raise ValidationError(
                    f"Skill profile {profile_name} orchestrator must be required"
                )
            role = manifest["skills"][profile["orchestrator"]]["role"]
            if role != "orchestrator":
                raise ValidationError(
                    f"Skill profile {profile_name} orchestrator has role {role}"
                )
        return results

    @staticmethod
    def _frontmatter(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValidationError(f"SKILL.md missing YAML frontmatter: {path}")
        end = text.find("\n---\n", 4)
        if end < 0:
            raise ValidationError(f"SKILL.md frontmatter is not closed: {path}")
        return load_yaml_text(text[4:end], f"SKILL.md frontmatter {path}")

    @staticmethod
    def tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        ignored = {".DS_Store", "README.md"}
        for path in sorted(
            item for item in root.rglob("*") if item.is_file() and item.name not in ignored
        ):
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def selected(self, profile_name: str, include_optional: bool = True) -> list[str]:
        profile = self.profile(profile_name)
        names = list(profile["required"])
        if include_optional:
            names.extend(profile["optional"])
        return list(dict.fromkeys(names))

    def install(
        self,
        profile_name: str,
        *,
        agent: str,
        include_optional: bool = True,
        force: bool = False,
    ) -> list[dict[str, str]]:
        self.validate_all()
        if agent not in {"claude", "codex", "both"}:
            raise ValidationError(f"unsupported Skill agent: {agent}")
        destinations = []
        if agent in {"claude", "both"}:
            destinations.append(("claude", self.paths.claude_config_dir / "skills"))
        if agent in {"codex", "both"}:
            codex_home = Path(os.environ.get("CODEX_HOME", self.paths.home / ".codex"))
            destinations.append(("codex", codex_home.expanduser().resolve() / "skills"))

        results: list[dict[str, str]] = []
        for agent_name, destination_root in destinations:
            destination_root.mkdir(parents=True, exist_ok=True)
            for name in self.selected(profile_name, include_optional):
                source = self.source(name)
                destination = destination_root / name
                state = self._install_one(source, destination, force=force)
                results.append(
                    {
                        "agent": agent_name,
                        "name": name,
                        "state": state,
                        "path": str(destination),
                    }
                )
        return results

    def _install_one(self, source: Path, destination: Path, *, force: bool) -> str:
        if destination.is_symlink():
            if destination.resolve() == source.resolve():
                return "managed"
            if not force:
                raise StackError(f"Skill symlink conflict (use --force): {destination}")
            backup = self._backup_name(destination)
            destination.rename(backup)
            destination.symlink_to(source, target_is_directory=True)
            return f"replaced; backup={backup}"
        if destination.exists():
            if destination.is_dir() and self.tree_digest(destination) == self.tree_digest(source):
                return "compatible-unmanaged"
            if not force:
                raise StackError(f"Skill directory conflict (use --force): {destination}")
            backup = self._backup_name(destination)
            destination.rename(backup)
            destination.symlink_to(source, target_is_directory=True)
            return f"replaced; backup={backup}"
        destination.symlink_to(source, target_is_directory=True)
        return "installed"

    @staticmethod
    def _backup_name(path: Path) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = path.with_name(f"{path.name}.bb-stack-backup.{timestamp}")
        serial = 1
        while candidate.exists() or candidate.is_symlink():
            candidate = path.with_name(
                f"{path.name}.bb-stack-backup.{timestamp}.{serial}"
            )
            serial += 1
        return candidate

    def status(self, profile_name: str, agent: str) -> list[dict[str, str]]:
        destination_root = (
            self.paths.claude_config_dir / "skills"
            if agent == "claude"
            else Path(os.environ.get("CODEX_HOME", self.paths.home / ".codex")) / "skills"
        )
        results = []
        for name in self.selected(profile_name):
            source = self.source(name)
            destination = destination_root / name
            if destination.is_symlink() and destination.resolve() == source.resolve():
                state = "managed"
            elif destination.is_dir():
                state = (
                    "compatible-unmanaged"
                    if self.tree_digest(destination) == self.tree_digest(source)
                    else "conflict"
                )
            else:
                state = "missing"
            results.append({"name": name, "state": state, "path": str(destination)})
        return results
