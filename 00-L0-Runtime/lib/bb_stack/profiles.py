from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
from typing import Any

from .configuration import ConfigurationManager
from .errors import ValidationError
from .io import dump_json, load_yaml, read_fragments
from .paths import StackPaths
from .validation import validate


WORKFLOW_FILES = {
    "bug-bounty": "bb-core.md",
    "ctf": "ctf-core.md",
    "lab": "lab-core.md",
}


def estimate_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = len(text) - cjk
    return max(1, cjk + math.ceil(non_cjk / 4))


@dataclass(frozen=True)
class RenderResult:
    schema_version: int
    profile: str
    prompt_mode: str
    workflow: str
    platform: str
    mode: str
    domain_prompt: str | None
    l5_profile: str
    skill_profile: str
    source_fragments: list[str]
    token_estimate: int
    budget: int
    output_file: str
    engagement: str | None


class ProfileRegistry:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.profile_dir = paths.root / "02-L2-Workflow-Profiles" / "profiles"
        self.platform_dir = paths.root / "02-L2-Workflow-Profiles" / "platforms"
        self.workflow_dir = paths.root / "02-L2-Workflow-Profiles" / "workflows"
        self.schema = (
            paths.root / "02-L2-Workflow-Profiles" / "schema" / "profile.schema.json"
        )
        self.platform_registry_path = self.platform_dir / "platforms.yaml"
        self.platform_schema = (
            paths.root / "02-L2-Workflow-Profiles" / "schema" / "platforms.schema.json"
        )

    def names(self) -> list[str]:
        return sorted(path.stem for path in self.profile_dir.glob("*.yaml"))

    def load(self, name: str) -> dict[str, Any]:
        path = self.profile_dir / f"{name}.yaml"
        if not path.is_file():
            raise ValidationError(f"unknown runtime profile: {name}")
        profile = load_yaml(path)
        validate(profile, self.schema, f"runtime profile {name}")
        if profile["name"] != name:
            raise ValidationError(f"profile filename/name mismatch: {path}")
        workflow = profile["workflow"]
        if workflow not in WORKFLOW_FILES:
            raise ValidationError(f"unsupported workflow in {path}: {workflow}")
        if profile.get("domain_prompt"):
            self._require_named_file(
                self.workflow_dir / "domains",
                profile["domain_prompt"],
                ".md",
                "domain Prompt",
            )
        self._require_named_file(self.platform_dir, profile["platform"], ".md", "platform")
        self._require_named_file(
            self.paths.root / "05-L5-MCP-CLI" / "profiles",
            profile["l5_profile"],
            ".yaml",
            "L5 profile",
        )
        self._require_named_file(
            self.paths.root / "04-L4-Skills" / "profiles",
            profile["skill_profile"],
            ".yaml",
            "Skill profile",
            allow_missing_registry=True,
        )
        return profile

    @staticmethod
    def _require_named_file(
        directory: Path,
        name: str,
        suffix: str,
        label: str,
        *,
        allow_missing_registry: bool = False,
    ) -> Path:
        path = directory / f"{name}{suffix}"
        if not path.is_file() and not (allow_missing_registry and not any(directory.glob("*"))):
            raise ValidationError(f"unknown {label}: {name}")
        return path

    def validate_all(self) -> list[str]:
        platforms = load_yaml(self.platform_registry_path)
        validate(platforms, self.platform_schema, "platform registry")
        for name in platforms["platforms"]:
            if not (self.platform_dir / f"{name}.md").is_file():
                raise ValidationError(f"platform registry is missing Prompt overlay: {name}.md")
        names = self.names()
        if not names:
            raise ValidationError("no runtime profiles found")
        for name in names:
            profile = self.load(name)
            platform = platforms["platforms"][profile["platform"]]
            if profile["workflow"] not in platform["workflows"]:
                raise ValidationError(
                    f"profile {name} workflow is incompatible with platform {profile['platform']}"
                )
        return names

    def render(
        self,
        name: str,
        *,
        platform: str | None = None,
        engagement: Path | None = None,
        output_dir: Path | None = None,
    ) -> RenderResult:
        profile = self.load(name)
        engagement_data: dict[str, Any] | None = None
        if engagement is not None:
            engagement_data = load_yaml(engagement / "engagement.yaml")
            if engagement_data.get("workflow") != profile["workflow"]:
                raise ValidationError(
                    "profile/engagement workflow mismatch: "
                    f"{profile['workflow']} != {engagement_data.get('workflow')}"
                )
            platform = platform or str(engagement_data["platform"])
        platform = platform or str(profile["platform"])
        platform_path = self.platform_dir / f"{platform}.md"
        if not platform_path.is_file():
            raise ValidationError(f"unknown platform: {platform}")
        platform_registry = load_yaml(self.platform_registry_path)
        validate(platform_registry, self.platform_schema, "platform registry")
        if platform not in platform_registry["platforms"]:
            raise ValidationError(f"platform is not registered: {platform}")
        if profile["workflow"] not in platform_registry["platforms"][platform]["workflows"]:
            raise ValidationError(
                f"workflow {profile['workflow']} is incompatible with platform {platform}"
            )

        fragments: list[Path] = []
        if profile["prompt_mode"] == "replacement":
            fragments.append(
                self.paths.root / "01-L1-Global-Prompt" / "replacement-runtime.md"
            )
        fragments.extend(
            [
                self.paths.root / "01-L1-Global-Prompt" / "personal-security.md",
                self.paths.root
                / "01-L1-Global-Prompt"
                / "languages"
                / f"{ConfigurationManager(self.paths).effective()['BB_AGENT_LANGUAGE']}.md",
                self.workflow_dir / WORKFLOW_FILES[profile["workflow"]],
            ]
        )
        if profile.get("domain_prompt"):
            fragments.append(
                self.workflow_dir / "domains" / f"{profile['domain_prompt']}.md"
            )
        fragments.append(platform_path)
        resolved = [path.resolve() for path in fragments]
        if len(resolved) != len(set(resolved)):
            raise ValidationError(f"duplicate prompt fragment in profile {name}")

        mode_contract = self._mode_contract(profile["default_mode"])
        header = (
            "<!-- Generated by bb-stack; edit source fragments, not this file. -->\n"
            f"<!-- profile={name} workflow={profile['workflow']} "
            f"platform={platform} mode={profile['default_mode']} -->\n\n"
        )
        content = header + read_fragments(fragments) + "\n" + mode_contract
        token_estimate = estimate_tokens(content)
        budget = int(profile["max_custom_tokens"])
        if token_estimate > budget:
            raise ValidationError(
                f"profile {name} exceeds custom Prompt budget: "
                f"{token_estimate} > {budget} estimated tokens"
            )

        scope = engagement.name if engagement else "global"
        target_dir = output_dir or self.paths.generated / "profiles" / scope / name
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = "system.md" if profile["prompt_mode"] == "replacement" else "append.md"
        output = target_dir / filename
        output.write_text(content, encoding="utf-8")
        result = RenderResult(
            schema_version=1,
            profile=name,
            prompt_mode=str(profile["prompt_mode"]),
            workflow=str(profile["workflow"]),
            platform=platform,
            mode=str(profile["default_mode"]),
            domain_prompt=profile.get("domain_prompt"),
            l5_profile=str(profile["l5_profile"]),
            skill_profile=str(profile["skill_profile"]),
            source_fragments=[str(path.relative_to(self.paths.root)) for path in fragments],
            token_estimate=token_estimate,
            budget=budget,
            output_file=str(output),
            engagement=str(engagement) if engagement else None,
        )
        dump_json(target_dir / "manifest.json", asdict(result))
        return result

    @staticmethod
    def _mode_contract(mode: str) -> str:
        if mode == "continuous":
            behavior = (
                "Continue the active workflow after each material tool result while a useful "
                "in-scope action remains. A status update is not a terminal action. Checkpoint "
                "before an explicit stop, a genuine external blocker, or exhausted in-scope leads."
            )
        else:
            behavior = (
                "Complete the requested bounded task, preserve material artifacts, and checkpoint "
                "the exact next action before yielding when work remains."
            )
        return "# Active Mode\n\n" + behavior + "\n"
