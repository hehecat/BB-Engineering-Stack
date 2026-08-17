from __future__ import annotations

import hashlib
import json
import re
import shlex
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .capabilities import CapabilityRegistry
from .configuration import ConfigurationManager
from .engagement import AUTHORIZED_STATUSES, EngagementManager
from .errors import StackError, ValidationError
from .io import atomic_write, dump_json, dump_yaml, load_json
from .paths import StackPaths
from .profiles import ProfileRegistry
from .skills import SkillRegistry

WORKSPACE_SCHEMA_VERSION = 1
MANAGED_ENV_KEYS = {
    "BB_STACK_ROOT",
    "BB_WORK_ROOT",
    "BB_CONFIG_HOME",
    "BB_PROXY_MODE",
    "BB_HTTP_PROXY",
    "BB_SOCKS_PROXY",
    "BB_H1_USERNAME",
    "BB_FILECODEBOX_URL",
    "BB_AGENT_LANGUAGE",
    "BB_NPM_REGISTRY",
    "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS",
    "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS",
    "PATH",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
}
ROUTES: dict[str, dict[str, Any]] = {
    "ctf-web": {
        "workflow": "ctf",
        "platform": "standalone-ctf",
        "profile": "ctf-quick",
        "skill_profile": "ctf-web",
        "l5_profile": "ctf-web",
        "skill_route": ["ctf-orchestrator", "ctf-web"],
        "slug_suffix": "ctf",
    },
    "web": {
        "workflow": "bug-bounty",
        "platform": "generic-vdp",
        "profile": "bb-interactive",
        "skill_profile": "web",
        "l5_profile": "web",
        "skill_route": ["bb-orchestrator"],
        "slug_suffix": "bb",
    },
    "web-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-web",
        "skill_profile": "assessment-web",
        "l5_profile": "assessment-web",
        "skill_route": ["security-orchestrator", "api-security"],
        "slug_suffix": "pentest",
    },
    "ctf-android": {
        "workflow": "ctf",
        "platform": "standalone-ctf",
        "profile": "ctf-android",
        "skill_profile": "android",
        "l5_profile": "android",
        "skill_route": ["reverse-orchestrator", "android-reverse-engineering"],
        "slug_suffix": "apk-ctf",
    },
    "android": {
        "workflow": "ctf",
        "platform": "standalone-ctf",
        "profile": "ctf-android",
        "skill_profile": "android",
        "l5_profile": "android",
        "skill_route": ["reverse-orchestrator", "android-reverse-engineering"],
        "slug_suffix": "apk",
    },
    "android-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-android",
        "skill_profile": "assessment-android",
        "l5_profile": "assessment-android",
        "skill_route": [
            "security-orchestrator",
            "android-reverse-engineering",
            "android-pentest",
        ],
        "slug_suffix": "android",
    },
    "android-analysis": {
        "workflow": "analysis",
        "platform": "standalone-analysis",
        "profile": "analysis-android",
        "skill_profile": "analysis-android",
        "l5_profile": "analysis-android",
        "skill_route": ["reverse-orchestrator", "android-reverse-engineering"],
        "slug_suffix": "apk-analysis",
    },
    "ios-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-ios",
        "skill_profile": "assessment-ios",
        "l5_profile": "assessment-ios",
        "skill_route": ["security-orchestrator", "ios-pentest"],
        "slug_suffix": "ios",
    },
    "ctf-reverse": {
        "workflow": "ctf",
        "platform": "standalone-ctf",
        "profile": "ctf-reverse",
        "skill_profile": "reverse",
        "l5_profile": "reverse",
        "skill_route": ["reverse-orchestrator", "native-reverse-engineering"],
        "slug_suffix": "reverse-ctf",
    },
    "reverse": {
        "workflow": "ctf",
        "platform": "standalone-ctf",
        "profile": "ctf-reverse",
        "skill_profile": "reverse",
        "l5_profile": "reverse",
        "skill_route": ["reverse-orchestrator", "native-reverse-engineering"],
        "slug_suffix": "reverse",
    },
    "reverse-analysis": {
        "workflow": "analysis",
        "platform": "standalone-analysis",
        "profile": "analysis-reverse",
        "skill_profile": "analysis-reverse",
        "l5_profile": "analysis-reverse",
        "skill_route": ["reverse-orchestrator", "native-reverse-engineering"],
        "slug_suffix": "analysis",
    },
    "reverse-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-reverse",
        "skill_profile": "assessment-reverse",
        "l5_profile": "assessment-reverse",
        "skill_route": ["security-orchestrator", "native-reverse-engineering"],
        "slug_suffix": "native",
    },
    "network-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-network",
        "skill_profile": "assessment-network",
        "l5_profile": "assessment-network",
        "skill_route": ["security-orchestrator", "network-pentest"],
        "slug_suffix": "network",
    },
    "cloud-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-cloud",
        "skill_profile": "assessment-cloud",
        "l5_profile": "assessment-cloud",
        "skill_route": ["security-orchestrator", "cloud-security"],
        "slug_suffix": "cloud",
    },
    "llm-assessment": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-llm",
        "skill_profile": "assessment-llm",
        "l5_profile": "assessment-llm",
        "skill_route": ["security-orchestrator", "llm-security"],
        "slug_suffix": "llm",
    },
    "source-audit": {
        "workflow": "assessment",
        "platform": "authorized-assessment",
        "profile": "assessment-source",
        "skill_profile": "assessment-source",
        "l5_profile": "assessment-source",
        "skill_route": ["security-orchestrator", "sast-orchestration"],
        "slug_suffix": "audit",
    },
    "browser-js": {
        "workflow": "analysis",
        "platform": "standalone-analysis",
        "profile": "browser-js",
        "skill_profile": "browser-js",
        "l5_profile": "browser-js",
        "skill_route": ["browser-js-orchestrator"],
        "slug_suffix": "js",
    },
    "lab": {
        "workflow": "lab",
        "platform": "local-lab",
        "profile": "lab-replacement",
        "skill_profile": "minimal",
        "l5_profile": "minimal",
        "skill_route": ["ctf-orchestrator"],
        "slug_suffix": "lab",
    },
}


class WorkspaceManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.marker = paths.work_root / ".bb-stack" / "workspace.json"
        self.router_source = (
            paths.root / "02-L2-Workflow-Profiles" / "workspace" / "CLAUDE.md"
        )

    @property
    def managed_paths(self) -> dict[str, Path]:
        return {
            "CLAUDE.md": self.paths.work_root / "CLAUDE.md",
            ".mcp.json": self.paths.work_root / ".mcp.json",
            ".claude/settings.json": (
                self.paths.work_root / ".claude" / "settings.json"
            ),
        }

    def initialize(
        self, *, force: bool = False, dry_run: bool = False
    ) -> dict[str, Any]:
        self._validate_root()
        content = self._render_managed_content()
        previous = self._read_marker()
        conflicts = self._conflicts(previous, force)
        if conflicts:
            raise StackError(
                "workspace managed file(s) contain local changes: "
                + ", ".join(conflicts)
                + "; move the changes or rerun workspace init --force"
            )

        directories = [
            self.paths.work_root,
            self.paths.engagements_root,
            self.paths.work_root / "inbox",
            self.paths.work_root / ".claude",
            self.paths.work_root / ".bb-stack" / "artifacts",
            self.paths.work_root / ".bb-stack" / "generated",
        ]
        digests = {
            relative: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for relative, value in content.items()
        }
        marker = {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "stack_version": __version__,
            "stack_root": str(self.paths.root),
            "work_root": str(self.paths.work_root),
            "machine_config_digest": self._machine_config_digest(),
            "managed_files": digests,
        }
        local_settings_migrated = self._local_settings_needs_migration()
        if not dry_run:
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)
            self._migrate_local_settings()
            for relative, value in content.items():
                atomic_write(self.paths.work_root / relative, value)
            dump_json(self.marker, marker)
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "ready": not dry_run,
            "dry_run": dry_run,
            "root": str(self.paths.work_root),
            "engagements_root": str(self.paths.engagements_root),
            "managed_files": sorted(content),
            "local_settings_migrated": local_settings_migrated,
            "mcp_servers": sorted(json.loads(content[".mcp.json"])["mcpServers"]),
            "default_entry": f"cd {shlex.quote(str(self.paths.work_root))} && claude",
        }

    def status(self) -> dict[str, Any]:
        marker = self._read_marker()
        try:
            expected_content = self._render_managed_content()
            expected_hashes = {
                relative: hashlib.sha256(value.encode("utf-8")).hexdigest()
                for relative, value in expected_content.items()
            }
        except (OSError, ValidationError):
            expected_hashes = {}
        items: dict[str, dict[str, Any]] = {}
        managed_hashes = marker.get("managed_files", {}) if marker else {}
        for relative, path in self.managed_paths.items():
            exists = path.is_file()
            digest = self._digest(path) if exists else None
            managed = managed_hashes.get(relative)
            items[relative] = {
                "path": str(path),
                "exists": exists,
                "managed": bool(managed),
                "unchanged": bool(managed and digest == managed),
                "current": bool(expected_hashes.get(relative) == digest),
            }
        directories = {
            "engagements": self.paths.engagements_root.is_dir(),
            "inbox": (self.paths.work_root / "inbox").is_dir(),
        }
        marker_matches = bool(
            marker
            and marker.get("stack_version") == __version__
            and marker.get("stack_root") == str(self.paths.root)
            and marker.get("work_root") == str(self.paths.work_root)
            and marker.get("machine_config_digest") == self._machine_config_digest()
            and managed_hashes == expected_hashes
        )
        ready = bool(
            marker_matches
            and all(directories.values())
            and all(
                item["exists"] and item["unchanged"] and item["current"]
                for item in items.values()
            )
        )
        mcp_servers: list[str] = []
        mcp_path = self.managed_paths[".mcp.json"]
        if mcp_path.is_file():
            try:
                mcp_servers = sorted(load_json(mcp_path).get("mcpServers", {}))
            except ValidationError:
                ready = False
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "ready": ready,
            "root": str(self.paths.work_root),
            "engagements_root": str(self.paths.engagements_root),
            "marker": str(self.marker),
            "marker_matches": marker_matches,
            "directories": directories,
            "managed_files": items,
            "mcp_servers": mcp_servers,
            "repair_command": "bb-stack workspace init",
            "default_entry": f"cd {shlex.quote(str(self.paths.work_root))} && claude",
        }

    def route(
        self,
        *,
        kind: str | None,
        target: str | None,
        slug: str | None,
        platform: str | None,
        mode: str | None,
        authorization_source: str | None = None,
        authorization_status: str | None = None,
    ) -> dict[str, Any]:
        if kind is not None and kind not in ROUTES:
            raise ValidationError(f"unknown workspace route kind: {kind}")
        manager = EngagementManager(self.paths)
        root: Path | None = None
        state: dict[str, Any] | None = None
        created = False

        if slug is not None:
            try:
                root = self.paths.engagement(slug)
                state = manager.validate(root)
            except StackError:
                if target is None:
                    raise
        if root is None and target is not None:
            matches = self._matching_engagements(manager, target, kind)
            if len(matches) > 1:
                raise StackError(
                    "multiple engagements match the target: "
                    + ", ".join(path.name for path, _ in matches)
                )
            if matches:
                root, state = matches[0]
        if state is not None:
            if authorization_status or authorization_source:
                state = manager.authorize(
                    root,
                    status=authorization_status or "user-asserted",
                    source=authorization_source,
                )
            stored_kind = state.get("routing", {}).get("kind")
            resolved_kind = kind or stored_kind or self._infer_kind(state)
            route = ROUTES[resolved_kind]
            if state["workflow"] != route["workflow"]:
                raise ValidationError(
                    f"route {resolved_kind} is incompatible with engagement workflow {state['workflow']}"
                )
            if platform and platform != state["platform"]:
                raise ValidationError(
                    f"platform {platform} does not match engagement platform {state['platform']}"
                )
            if mode and mode != state["mode"]:
                raise ValidationError(
                    f"mode {mode} does not match engagement mode {state['mode']}"
                )
            kind = resolved_kind
            if stored_kind is None:
                state["routing"] = {"kind": kind}
                dump_yaml(root / "engagement.yaml", state)
                state = manager.validate(root)
        else:
            if target is None:
                raise ValidationError("a new route requires --target")
            if kind is None:
                raise ValidationError("a new route requires --kind")
            route = ROUTES[kind]
            selected_platform = platform or route["platform"]
            selected_mode = mode or "interactive"
            selected_slug = slug or self._available_slug(
                self._slug_for(target, route["slug_suffix"])
            )
            root = manager.create(
                selected_slug,
                target,
                workflow=route["workflow"],
                platform=selected_platform,
                mode=selected_mode,
                authorization_source=authorization_source,
                authorization_status=authorization_status,
                route_kind=kind,
            )
            state = manager.validate(root)
            created = True

        assert root is not None and state is not None and kind is not None
        route = ROUTES[kind]
        if kind == "web" and state["mode"] == "continuous":
            profile_name = "bb-continuous"
        elif kind == "ctf-web" and state["mode"] == "continuous":
            profile_name = "ctf-replacement"
        else:
            profile_name = route["profile"]
        rendered = ProfileRegistry(self.paths).render(
            profile_name, platform=state["platform"], engagement=root
        )
        profile_mcp = root / ".bb-stack" / "mcp.json"
        capability_registry = CapabilityRegistry(self.paths)
        capability_registry.render_mcp(
            rendered.l5_profile, profile_mcp, artifact_root=root / "artifacts"
        )
        capability_status = capability_registry.doctor(
            rendered.l5_profile, root / "artifacts"
        )
        skill_registry = SkillRegistry(self.paths)
        skill_status = skill_registry.status(rendered.skill_profile, "claude")
        required_skills = set(
            skill_registry.profile(rendered.skill_profile)["required"]
        )
        missing_skills = sorted(
            item["name"]
            for item in skill_status
            if item["name"] in required_skills
            and item["state"] in {"missing", "conflict"}
        )
        repair_commands: list[str] = []
        authorization_ready = bool(
            state["workflow"] not in {"bug-bounty", "assessment"}
            or state["authorization"]["status"] in AUTHORIZED_STATUSES
        )
        if not authorization_ready:
            repair_commands.append(
                "bb-stack engagement authorize "
                f"{shlex.quote(state['slug'])} --status user-asserted "
                "--source \"user statement recorded in SCOPE.md\""
            )
        if missing_skills or not capability_status["ready"]:
            repair_commands.append(
                f"bb-stack bootstrap --profile {shlex.quote(rendered.skill_profile)}"
            )
        workspace_status = self.status()
        if not workspace_status["ready"]:
            repair_commands.insert(0, "bb-stack workspace init")
        state_files = [
            root / "engagement.yaml",
            root / "notes" / "SCOPE.md",
            root / "SESSION-HANDOFF.md",
            root / "STATUS.md",
        ]
        return {
            "schema_version": 1,
            "ready": not repair_commands,
            "kind": kind,
            "created": created,
            "engagement": str(root),
            "slug": state["slug"],
            "workflow": state["workflow"],
            "platform": state["platform"],
            "mode": state["mode"],
            "lifecycle": state["lifecycle"],
            "authorization": state["authorization"],
            "profile": profile_name,
            "prompt_file": rendered.output_file,
            "state_files": [str(path) for path in state_files],
            "skill_route": route["skill_route"],
            "missing_required_skills": missing_skills,
            "missing_required_capabilities": capability_status["missing_required"],
            "project_mcp_servers": workspace_status["mcp_servers"],
            "profile_mcp_config": str(profile_mcp),
            "repair_commands": repair_commands,
            "strict_launch": (
                f"bb-stack launch --profile {shlex.quote(profile_name)} "
                f"--engagement {shlex.quote(state['slug'])}"
            ),
            "browser_start": (
                "bb-stack browser start --engagement " + shlex.quote(state["slug"])
            ),
            "next_action": state["current"]["next_action"],
        }

    def _render_managed_content(self) -> dict[str, str]:
        if not self.router_source.is_file():
            raise ValidationError(
                f"missing workspace router template: {self.router_source}"
            )
        router = (
            "<!-- Generated by bb-stack; refresh with `bb-stack workspace init`. -->\n\n"
            + self.router_source.read_text(encoding="utf-8").strip()
            + "\n"
        )
        machine = ConfigurationManager(self.paths).effective()
        language_path = (
            self.paths.root
            / "01-L1-Global-Prompt"
            / "languages"
            / f"{machine['BB_AGENT_LANGUAGE']}.md"
        )
        if not language_path.is_file():
            raise ValidationError(f"missing Agent language Prompt: {language_path}")
        router += "\n" + language_path.read_text(encoding="utf-8").strip() + "\n"
        settings_env = {
            "BB_STACK_ROOT": str(self.paths.root),
            "BB_WORK_ROOT": str(self.paths.work_root),
            "BB_CONFIG_HOME": str(self.paths.config_home),
            "BB_DATA_ROOT": str(self.paths.data_root),
            "BB_PROXY_MODE": machine["BB_PROXY_MODE"],
            "BB_HTTP_PROXY": machine["BB_HTTP_PROXY"],
            "BB_SOCKS_PROXY": machine["BB_SOCKS_PROXY"],
            "BB_H1_USERNAME": machine["BB_H1_USERNAME"],
            "BB_FILECODEBOX_URL": machine["BB_FILECODEBOX_URL"],
            "BB_AGENT_LANGUAGE": machine["BB_AGENT_LANGUAGE"],
            "BB_NPM_REGISTRY": machine["BB_NPM_REGISTRY"],
            "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
            "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
            "PATH": self.paths.runtime_path(machine.get("BB_EXTRA_PATH", "")),
        }
        if machine["BB_PROXY_MODE"] == "mihomo":
            settings_env.update(
                {
                    "HTTP_PROXY": machine["BB_HTTP_PROXY"],
                    "HTTPS_PROXY": machine["BB_HTTP_PROXY"],
                    "ALL_PROXY": machine["BB_SOCKS_PROXY"],
                    "http_proxy": "",
                    "https_proxy": "",
                    "all_proxy": "",
                }
            )
        else:
            settings_env.update(
                {
                    name: ""
                    for name in (
                        "HTTP_PROXY",
                        "HTTPS_PROXY",
                        "ALL_PROXY",
                        "http_proxy",
                        "https_proxy",
                        "all_proxy",
                    )
                }
            )
        settings = {
            "$schema": "https://json.schemastore.org/claude-code-settings.json",
            "env": settings_env,
        }
        with tempfile.TemporaryDirectory(prefix="bb-workspace-mcp-") as temporary:
            generated_mcp = Path(temporary) / "mcp.json"
            mcp = CapabilityRegistry(self.paths).render_mcp(
                "workspace",
                generated_mcp,
                artifact_root=self.paths.work_root / ".bb-stack" / "artifacts",
            )
        return {
            "CLAUDE.md": router,
            ".mcp.json": json.dumps(mcp, indent=2, ensure_ascii=True) + "\n",
            ".claude/settings.json": (
                json.dumps(settings, indent=2, ensure_ascii=True) + "\n"
            ),
        }

    def _local_settings_needs_migration(self) -> bool:
        path = self.paths.work_root / ".claude" / "settings.local.json"
        if not path.is_file():
            return False
        try:
            document = load_json(path)
        except ValidationError:
            return False
        env = document.get("env")
        return isinstance(env, dict) and bool(MANAGED_ENV_KEYS & set(env))

    def _migrate_local_settings(self) -> None:
        path = self.paths.work_root / ".claude" / "settings.local.json"
        if not path.is_file():
            return
        try:
            document = load_json(path)
        except ValidationError:
            return
        env = document.get("env")
        if not isinstance(env, dict):
            return
        preserved = {
            key: value for key, value in env.items() if key not in MANAGED_ENV_KEYS
        }
        if preserved:
            document["env"] = preserved
        else:
            document.pop("env", None)
        atomic_write(path, json.dumps(document, indent=2, ensure_ascii=True) + "\n")

    def _read_marker(self) -> dict[str, Any]:
        if not self.marker.is_file():
            return {}
        try:
            marker = load_json(self.marker)
        except ValidationError:
            return {}
        return (
            marker if marker.get("schema_version") == WORKSPACE_SCHEMA_VERSION else {}
        )

    def _conflicts(self, previous: dict[str, Any], force: bool) -> list[str]:
        if force:
            return []
        previous_hashes = previous.get("managed_files", {})
        conflicts: list[str] = []
        for relative, path in self.managed_paths.items():
            if not path.exists():
                continue
            expected = previous_hashes.get(relative)
            if expected is None or self._digest(path) != expected:
                conflicts.append(relative)
        return conflicts

    def _validate_root(self) -> None:
        root = self.paths.work_root.resolve()
        home = self.paths.home.resolve()
        if root == home or home.is_relative_to(root):
            raise ValidationError("BB_WORK_ROOT must not equal or contain HOME")
        reserved = (
            self.paths.root.resolve(),
            self.paths.config_home.resolve(),
            self.paths.claude_config_dir.resolve(),
        )
        if any(
            root == path or root.is_relative_to(path) or path.is_relative_to(root)
            for path in reserved
        ):
            raise ValidationError(
                "BB_WORK_ROOT must not equal, contain, or be contained by the stack source, config home, or Claude config"
            )

    def _matching_engagements(
        self, manager: EngagementManager, target: str, kind: str | None
    ) -> list[tuple[Path, dict[str, Any]]]:
        expected_workflow = ROUTES[kind]["workflow"] if kind else None
        result: list[tuple[Path, dict[str, Any]]] = []
        for root in manager.roots():
            try:
                state = manager.validate(root)
            except ValidationError:
                continue
            if expected_workflow and state["workflow"] != expected_workflow:
                continue
            patterns = {item["pattern"] for item in state["scope"]["in_scope"]}
            if target in patterns:
                result.append((root, state))
        return result

    def _available_slug(self, base: str) -> str:
        candidate = base
        number = 2
        while (self.paths.engagements_root / candidate).exists():
            candidate = f"{base}-{number}"
            number += 1
        return candidate

    @staticmethod
    def _slug_for(target: str, suffix: str) -> str:
        value = target
        if target.startswith(("http://", "https://")):
            value = urlparse(target).hostname or target
            value = value.removeprefix("www.")
        else:
            value = Path(target).stem or target
        base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "work"
        return base if base.endswith(f"-{suffix}") else f"{base}-{suffix}"

    @staticmethod
    def _infer_kind(state: dict[str, Any]) -> str:
        if state["workflow"] == "bug-bounty":
            return "web"
        pattern = state["scope"]["in_scope"][0]["pattern"].lower()
        suffix = Path(pattern).suffix
        if state["workflow"] == "assessment":
            asset_type = state["scope"]["in_scope"][0]["type"]
            if suffix in {".apk", ".xapk", ".aab", ".jar", ".aar"}:
                return "android-assessment"
            if suffix == ".ipa":
                return "ios-assessment"
            if asset_type == "cidr":
                return "network-assessment"
            if asset_type == "repository":
                return "source-audit"
            if asset_type == "other":
                return "reverse-assessment"
            return "web-assessment"
        if state["workflow"] == "lab":
            return "lab"
        if state["workflow"] == "analysis":
            if suffix in {".apk", ".xapk", ".aab", ".jar", ".aar"}:
                return "android-analysis"
            if pattern.startswith(("http://", "https://")) or suffix in {
                ".js",
                ".mjs",
                ".cjs",
            }:
                return "browser-js"
            return "reverse-analysis"
        if pattern.startswith(("http://", "https://")):
            return "ctf-web"
        if suffix in {".apk", ".xapk", ".aab", ".jar", ".aar"}:
            return "ctf-android"
        return "ctf-reverse"

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _machine_config_digest(self) -> str:
        try:
            value: Any = ConfigurationManager(self.paths).effective()
        except ValidationError:
            path = self.paths.config_home / "config.env"
            value = {
                "invalid_config_sha256": self._digest(path) if path.is_file() else None
            }
        content = json.dumps(
            value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(content).hexdigest()
