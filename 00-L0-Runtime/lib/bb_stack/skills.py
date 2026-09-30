from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backends import BackendRegistry
from .errors import StackError, ValidationError
from .io import load_yaml, load_yaml_text
from .paths import StackPaths
from .validation import validate

# Provenance values that explicitly record "no named upstream". They are a
# named, greppable review backlog rather than a silent omission; every other
# provenance value must be auditable, i.e. carry repository and revision.
UNSOURCED_PROVENANCE = frozenset({"stack", "local-snapshot"})


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
            provenance = metadata["provenance"]
            if provenance not in UNSOURCED_PROVENANCE:
                missing = sorted(
                    key for key in ("repository", "revision") if not metadata.get(key)
                )
                if missing:
                    raise ValidationError(
                        f"vendored Skill {name} declares provenance {provenance!r} "
                        f"but is missing upstream {', '.join(missing)}"
                    )
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
            item
            for item in root.rglob("*")
            if item.is_file() and item.name not in ignored
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
        targets = self._targets(agent)
        shared = self._shared_roots(targets)
        names = self.selected(profile_name, include_optional)
        results: list[dict[str, str]] = []
        written: set[Path] = set()
        for backend_name, destination_root in targets:
            root = destination_root.resolve()
            # Several backends read the same skill directory (omp, opencode and
            # cursor-agent all use `~/.agents/skills`). The physical path is
            # installed once; every backend is still reported, flagged so the
            # operator can see which entry performed the write.
            if root in written:
                for name in names:
                    source = self.source(name)
                    destination = destination_root / name
                    results.append(
                        {
                            "agent": backend_name,
                            "name": name,
                            "state": self._state(source, destination),
                            "path": str(destination),
                            "shared": True,
                        }
                    )
                continue
            written.add(root)
            destination_root.mkdir(parents=True, exist_ok=True)
            for name in names:
                source = self.source(name)
                destination = destination_root / name
                state = self._install_one(source, destination, force=force)
                results.append(
                    {
                        "agent": backend_name,
                        "name": name,
                        "state": state,
                        "path": str(destination),
                        "shared": root in shared,
                    }
                )
        return results

    def _targets(self, agent: str) -> list[tuple[str, Path]]:
        """Resolve *agent* to `(backend name, skills root)` pairs.

        *agent* is `"all"` or any backend declared in `backends.yaml`; the
        registry owns both the name set and each backend's `skills_root`, so a
        new CLI never needs a code change here.
        """
        registry = BackendRegistry(self.paths)
        declared = registry.names()
        if agent == "all":
            selected = declared
        elif agent in declared:
            selected = [agent]
        else:
            raise ValidationError(
                f"unsupported Skill agent: {agent}; declared backends: "
                f"{', '.join(declared)}"
            )
        return [(name, registry.get(name).skills_root) for name in selected]

    @staticmethod
    def _shared_roots(targets: list[tuple[str, Path]]) -> set[Path]:
        counts: dict[Path, int] = {}
        for _, root in targets:
            resolved = root.resolve()
            counts[resolved] = counts.get(resolved, 0) + 1
        return {root for root, count in counts.items() if count > 1}

    def _state(self, source: Path, destination: Path) -> str:
        """Non-mutating status of *destination* against *source*."""
        if destination.is_symlink() and destination.resolve() == source.resolve():
            return "managed"
        if destination.is_dir():
            return (
                "compatible-unmanaged"
                if self.tree_digest(destination) == self.tree_digest(source)
                else "conflict"
            )
        return "missing"

    def _install_one(self, source: Path, destination: Path, *, force: bool) -> str:
        if destination.is_symlink():
            if destination.resolve() == source.resolve():
                return "managed"
            # A symlink at a managed destination is always a product of an
            # earlier install: every managed path is written by this method
            # alone and it only ever creates symlinks there, never real
            # directory content. A stale link (e.g. left behind by a previous
            # stack source tree) is therefore rebuilt in place rather than
            # treated as user content; self-healing here keeps `bb-stack
            # update` running without forcing `--force` on the operator. The
            # link target itself is never modified, and the previous target is
            # reported for auditability.
            previous = os.readlink(destination)
            destination.unlink()
            destination.symlink_to(source, target_is_directory=True)
            return f"relinked; previous={previous}"
        if destination.exists():
            if destination.is_dir() and self.tree_digest(
                destination
            ) == self.tree_digest(source):
                return "compatible-unmanaged"
            if not force:
                raise StackError(
                    f"Skill directory conflict (use --force): {destination}"
                )
            backup = self._backup_name(destination)
            destination.rename(backup)
            destination.symlink_to(source, target_is_directory=True)
            return f"replaced; backup={backup}"
        destination.symlink_to(source, target_is_directory=True)
        return "installed"

    @staticmethod
    def _backup_name(path: Path) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        candidate = path.with_name(f"{path.name}.bb-stack-backup.{timestamp}")
        serial = 1
        while candidate.exists() or candidate.is_symlink():
            candidate = path.with_name(
                f"{path.name}.bb-stack-backup.{timestamp}.{serial}"
            )
            serial += 1
        return candidate

    def status(self, profile_name: str, agent: str) -> list[dict[str, str]]:
        targets = self._targets(agent)
        shared = self._shared_roots(targets)
        results: list[dict[str, str]] = []
        for backend_name, destination_root in targets:
            for name in self.selected(profile_name):
                source = self.source(name)
                destination = destination_root / name
                results.append(
                    {
                        "agent": backend_name,
                        "name": name,
                        "state": self._state(source, destination),
                        "path": str(destination),
                        "shared": destination_root.resolve() in shared,
                    }
                )
        return results
