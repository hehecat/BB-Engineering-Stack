from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .configuration import ConfigurationManager, url_origin
from .errors import StackError, ValidationError
from .io import atomic_write, load_json, load_yaml
from .paths import StackPaths
from .skills import SkillRegistry
from .validation import validate

PORTABLE_KIND = "bb-stack-portable"
PORTABLE_SCHEMA_VERSION = 1
PORTABLE_CONFIG_KEYS = (
    "BB_PROXY_MODE",
    "BB_HTTP_PROXY",
    "BB_SOCKS_PROXY",
    "BB_H1_USERNAME",
    "BB_FILECODEBOX_URL",
    "BB_AGENT_LANGUAGE",
    "BB_NPM_REGISTRY",
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PortableManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.schema = paths.root / "schema" / "portable.schema.json"
        self.configuration = ConfigurationManager(paths)

    def export(self, output: Path, *, force: bool = False) -> dict[str, Any]:
        output = output.expanduser().resolve()
        if output.exists() and not force:
            raise StackError(f"portable document already exists: {output}")
        document = self._document()
        validate(document, self.schema, "portable export")
        atomic_write(
            output, json.dumps(document, indent=2, ensure_ascii=True) + "\n", 0o600
        )
        return {
            "exported": True,
            "path": str(output),
            "schema_version": PORTABLE_SCHEMA_VERSION,
            "engagement_count": len(document["engagements"]),
            "excluded": document["excluded"],
        }

    def inspect(self, source: Path) -> dict[str, Any]:
        source = source.expanduser().resolve()
        document = self._load(source)
        return {
            "valid": True,
            "path": str(source),
            "kind": document["kind"],
            "schema_version": document["schema_version"],
            "created_at": document["created_at"],
            "source_stack_version": document["source"]["stack_version"],
            "root_intent": document["root_intent"],
            "configured_keys": sorted(document["machine_config"]),
            "profiles": document["profiles"],
            "engagements": document["engagements"],
            "excluded": document["excluded"],
            "restore_checklist": document["restore_checklist"],
        }

    def import_document(
        self, source: Path, *, yes: bool = False, force: bool = False
    ) -> dict[str, Any]:
        source = source.expanduser().resolve()
        document = self._load(source)
        current = self.configuration.read() if self.configuration.path.is_file() else {}
        imported = document["machine_config"]
        decisions: list[dict[str, str]] = []
        updates: dict[str, str] = {}
        for key in PORTABLE_CONFIG_KEYS:
            if key not in imported:
                continue
            incoming = imported[key]
            existing = current.get(key, "")
            if existing == incoming:
                decision = "same"
            elif existing and not force:
                decision = "skip-nonempty"
            else:
                decision = "set"
                updates[key] = incoming
            decisions.append({"key": key, "decision": decision})
        result: dict[str, Any] = {
            "source": str(source),
            "preview": not yes,
            "force": force,
            "decisions": decisions,
            "changed": sorted(updates),
            "restore_checklist": document["restore_checklist"],
            "engagement_inventory": document["engagements"],
            "roots_unchanged": True,
        }
        if yes:
            configured = self.configuration.configure(updates)
            result["imported"] = True
            result["config"] = configured
        else:
            result["imported"] = False
        return result

    def _load(self, source: Path) -> dict[str, Any]:
        document = load_json(source)
        validate(document, self.schema, f"portable document {source}")
        if document.get("kind") != PORTABLE_KIND:
            raise ValidationError("unsupported portable document kind")
        return document

    def _document(self) -> dict[str, Any]:
        config = self.configuration.effective()
        machine_config = {
            "BB_PROXY_MODE": config["BB_PROXY_MODE"],
            "BB_HTTP_PROXY": url_origin(config["BB_HTTP_PROXY"], {"http", "https"}),
            "BB_SOCKS_PROXY": url_origin(
                config["BB_SOCKS_PROXY"], {"socks5", "socks5h"}
            ),
            "BB_H1_USERNAME": config["BB_H1_USERNAME"],
            "BB_FILECODEBOX_URL": url_origin(
                config["BB_FILECODEBOX_URL"], {"http", "https"}
            ),
            "BB_AGENT_LANGUAGE": config["BB_AGENT_LANGUAGE"],
            "BB_NPM_REGISTRY": config["BB_NPM_REGISTRY"],
        }
        if any(value is None for value in machine_config.values()):
            raise ValidationError(
                "machine configuration contains an invalid portable URL"
            )
        engagements = self._engagement_inventory()
        mail_configured = (
            self.paths.home / ".local" / "share" / "pentest-mail" / "config.env"
        ).is_file()
        return {
            "kind": PORTABLE_KIND,
            "schema_version": PORTABLE_SCHEMA_VERSION,
            "created_at": _now(),
            "source": {"stack_version": __version__},
            "root_intent": {
                "stack_root": self._root_intent(self.paths.root),
                "work_root": self._root_intent(self.paths.work_root),
                "config_home": self._root_intent(self.paths.config_home),
                "claude_config_dir": self._root_intent(self.paths.claude_config_dir),
            },
            "machine_config": machine_config,
            "profiles": self._installed_profiles(),
            "engagements": engagements,
            "excluded": [
                "BB_EXTRA_PATH and old-machine absolute paths",
                "mailbox passwords and OAuth tokens",
                "Claude authentication, cookies, sessions, JWTs, and private keys",
                "Engagement evidence, credentials, generated MCP state, and runtime dependencies",
                "Keysmith generated Prompt and deployment state",
            ],
            "restore_checklist": [
                {
                    "component": "source",
                    "required": True,
                    "action": "Clone the stack source and run bootstrap before import",
                },
                {
                    "component": "engagements",
                    "required": bool(engagements),
                    "action": "Restore BB_WORK_ROOT from its separate encrypted backup",
                },
                {
                    "component": "mail-otp",
                    "required": mail_configured,
                    "action": "Run bb-stack mail configure and restore the secret locally",
                },
                {
                    "component": "claude-auth",
                    "required": True,
                    "action": "Authenticate Claude Code on the destination machine",
                },
            ],
        }

    def _root_intent(self, path: Path) -> dict[str, str | None]:
        try:
            relative = path.resolve().relative_to(self.paths.home.resolve())
        except ValueError:
            return {"kind": "custom", "path": None}
        value = str(relative)
        return {"kind": "home-relative", "path": value if value != "." else ""}

    def _installed_profiles(self) -> dict[str, list[str]]:
        registry = SkillRegistry(self.paths)
        result: dict[str, list[str]] = {"claude": [], "codex": []}
        for agent, profiles in result.items():
            for profile in registry.profile_names():
                required = set(registry.profile(profile)["required"])
                statuses = registry.status(profile, agent)
                ready = {item["name"] for item in statuses if item["state"] == "ready"}
                if required <= ready:
                    profiles.append(profile)
        return result

    def _engagement_inventory(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        from .engagement import EngagementManager

        for root in EngagementManager(self.paths).roots():
            state_path = root / "engagement.yaml"
            if not state_path.is_file():
                continue
            state = load_yaml(state_path)
            required = {
                "slug",
                "workflow",
                "platform",
                "mode",
                "lifecycle",
                "phase",
                "checkpoint",
            }
            if not required <= set(state):
                continue
            result.append(
                {
                    "slug": state["slug"],
                    "workflow": state["workflow"],
                    "platform": state["platform"],
                    "mode": state["mode"],
                    "lifecycle": state["lifecycle"],
                    "phase": state["phase"],
                    "checkpoint": {
                        "file": state["checkpoint"].get(
                            "handoff_file", "SESSION-HANDOFF.md"
                        ),
                        "updated_at": state["checkpoint"].get("updated_at"),
                    },
                }
            )
        return result
