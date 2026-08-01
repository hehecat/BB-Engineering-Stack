from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import socket
import stat
import subprocess
from typing import Any
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from . import __version__
from .capabilities import CapabilityRegistry
from .configuration import MACHINE_CONFIG_KEYS, load_machine_config
from .engagement import EngagementManager
from .errors import StackError, ValidationError
from .evaluation import EvaluationManager
from .io import load_yaml
from .keysmith import KeysmithAdapter
from .mail_otp import MailOtpError, MailSettings, load_config as load_mail_config
from .paths import StackPaths
from .profiles import ProfileRegistry
from .runtime import RuntimeManager
from .skills import SkillRegistry
from .workspace import WorkspaceManager


class StackStatus:
    def __init__(self, paths: StackPaths):
        self.paths = paths

    def collect(
        self,
        profile: str,
        *,
        workflow_profile: str | None = None,
        platform: str | None = None,
        probe_mcp: bool = False,
        include_high_context_mcp: bool = False,
        check_external: bool = False,
        engagement: str | None = None,
        require_agent_eval: bool = False,
    ) -> dict[str, Any]:
        skill_registry = SkillRegistry(self.paths)
        capability_registry = CapabilityRegistry(self.paths)
        skill_registry.profile(profile)
        capability_registry.profile(profile)

        machine_config_path = self.paths.config_home / "config.env"
        machine_config, invalid_config = load_machine_config(machine_config_path)
        actions: list[dict[str, str]] = []

        paths_report = self._paths(profile, actions)
        workspace_report = WorkspaceManager(self.paths).status()
        if not workspace_report["ready"]:
            self._action(
                actions,
                "required",
                "workspace.initialize",
                "Initialize or refresh the natural-language Claude workspace",
                "bb-stack workspace init",
            )
        config_report = self._config(
            profile,
            machine_config_path,
            machine_config,
            invalid_config,
            actions,
        )
        proxy_report = self._proxy(machine_config, actions)
        runtime_report = self._runtime(profile, actions)
        engagement_report = self._engagement(profile, engagement, actions)
        selected_engagement = engagement_report["selected"]
        if (
            selected_engagement
            and engagement_report["profile_matches"]
            and platform
            and platform != selected_engagement["platform"]
        ):
            raise ValidationError(
                f"platform {platform} does not match engagement platform "
                f"{selected_engagement['platform']}"
            )
        selected_platform = platform
        selected_workflow_profile = workflow_profile
        if selected_engagement and engagement_report["profile_matches"]:
            selected_platform = selected_platform or selected_engagement["platform"]
            if not selected_workflow_profile:
                selected_workflow_profile = self._workflow_profile_for_mode(
                    selected_engagement["workflow"],
                    profile,
                    selected_engagement["mode"],
                )
        prompt_report = self._prompt(
            profile, selected_workflow_profile, selected_platform, actions
        )
        evaluation_report = self._evaluation(
            prompt_report.get("selected"),
            prompt_report.get("output_file"),
            require_agent_eval,
            actions,
        )
        skills_report = self._skills(profile, actions)
        capabilities_report = self._capabilities(
            profile,
            capability_registry,
            probe_mcp=probe_mcp,
            include_high_context=include_high_context_mcp,
            actions=actions,
        )
        personal_report = self._personal(
            profile,
            machine_config,
            prompt_report.get("platform"),
            capability_registry,
            check_external=check_external,
            actions=actions,
        )
        keysmith_report = self._keysmith(profile, actions)

        required_failures = [
            action for action in actions if action["level"] == "required"
        ]
        ready = bool(
            not required_failures
            and paths_report["ready"]
            and workspace_report["ready"]
            and config_report["ready"]
            and proxy_report["ready"]
            and runtime_report["ready"]
            and prompt_report["ready"]
            and evaluation_report["ready"]
            and engagement_report["ready"]
            and skills_report["ready"]
            and capabilities_report["ready"]
            and personal_report["ready"]
        )
        return {
            "schema_version": 1,
            "ready": ready,
            "profile": profile,
            "paths": paths_report,
            "workspace": workspace_report,
            "machine_config": config_report,
            "proxy": proxy_report,
            "runtime": runtime_report,
            "prompt": prompt_report,
            "evaluation": evaluation_report,
            "engagement": engagement_report,
            "skills": skills_report,
            "capabilities": capabilities_report,
            "personal": personal_report,
            "keysmith": keysmith_report,
            "actions": actions,
        }

    def _paths(
        self, profile: str, actions: list[dict[str, str]]
    ) -> dict[str, Any]:
        definitions = {
            "home": (self.paths.home, True),
            "stack_root": (self.paths.root, True),
            "work_root": (self.paths.work_root, True),
            "engagements_root": (self.paths.engagements_root, True),
            "config_home": (self.paths.config_home, True),
            "claude_config_dir": (self.paths.claude_config_dir, False),
            "runtime": (self.paths.runtime, True),
        }
        items: dict[str, dict[str, Any]] = {}
        for name, (path, required) in definitions.items():
            exists = path.is_dir()
            writable = exists and os.access(path, os.W_OK)
            items[name] = {
                "path": str(path),
                "exists": exists,
                "writable": writable,
                "required": required,
            }
            if required and not exists:
                self._action(
                    actions,
                    "required",
                    f"path.{name}",
                    f"Create or bootstrap missing {name}: {path}",
                    f"bb-stack bootstrap --profile {profile}",
                )
            elif required and not writable:
                self._action(
                    actions,
                    "required",
                    f"path.{name}.writable",
                    f"Make {name} writable: {path}",
                    None,
                )
        return {
            "ready": all(
                item["exists"] and item["writable"]
                for item in items.values()
                if item["required"]
            ),
            "claude_config_explicit": self.paths.claude_config_explicit,
            "items": items,
        }

    def _config(
        self,
        profile: str,
        path: Path,
        values: dict[str, str],
        invalid: list[str],
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        present = path.is_file()
        mode = stat.S_IMODE(path.stat().st_mode) if present else None
        if not present:
            self._action(
                actions,
                "required",
                "config.missing",
                "Create machine-local config.env through bootstrap",
                f"bb-stack bootstrap --profile {profile}",
            )
        if present and mode != 0o600:
            self._action(
                actions,
                "required",
                "config.permissions",
                "Set config.env permissions to 600",
                f"chmod 600 {shlex.quote(str(path))}",
            )
        if invalid:
            self._action(
                actions,
                "required",
                "config.syntax",
                "Fix unsupported config.env assignments: " + ", ".join(invalid),
                None,
            )
        known = set(MACHINE_CONFIG_KEYS)
        return {
            "ready": present and mode == 0o600 and not invalid,
            "path": str(path),
            "present": present,
            "mode": f"{mode:03o}" if mode is not None else None,
            "invalid_lines": invalid,
            "known_keys": sorted(key for key in values if key in known),
            "unknown_keys": sorted(key for key in values if key not in known),
        }

    def _proxy(
        self, config: dict[str, str], actions: list[dict[str, str]]
    ) -> dict[str, Any]:
        mode = config.get("BB_PROXY_MODE", "unset")
        http_url = config.get("BB_HTTP_PROXY", "")
        socks_url = config.get("BB_SOCKS_PROXY", "")
        http_endpoint = self._url_endpoint(http_url)
        socks_endpoint = self._url_endpoint(socks_url)
        http_listening = self._tcp_ready(*http_endpoint) if http_endpoint else False
        socks_listening = self._tcp_ready(*socks_endpoint) if socks_endpoint else False
        proxy_variables = (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
        active = {
            name: self._redact_url(os.environ.get(name, ""))
            for name in proxy_variables
            if os.environ.get(name)
        }
        expected_http = self._redact_url(http_url)
        expected_socks = self._redact_url(socks_url)
        if mode == "mihomo":
            required_applied = bool(
                active.get("HTTP_PROXY") == expected_http
                and active.get("HTTPS_PROXY") == expected_http
                and active.get("ALL_PROXY") == expected_socks
            )
            lower_conflict = bool(
                (active.get("http_proxy") and active["http_proxy"] != expected_http)
                or (
                    active.get("https_proxy")
                    and active["https_proxy"] != expected_http
                )
                or (active.get("all_proxy") and active["all_proxy"] != expected_socks)
            )
            applied = required_applied and not lower_conflict
            ready = bool(http_listening and applied)
            if not http_listening:
                self._action(
                    actions,
                    "required",
                    "proxy.service",
                    "Start the configured mihomo HTTP listener",
                    None,
                )
            if not applied:
                self._action(
                    actions,
                    "required",
                    "proxy.environment",
                    "Reload the generated environment so proxy variables reach bb-stack",
                    f"source {shlex.quote(str(self.paths.env_file))}",
                )
        elif mode == "direct":
            applied = not active
            ready = applied
            if not applied:
                self._action(
                    actions,
                    "required",
                    "proxy.environment",
                    "Clear stale proxy variables by reloading the generated environment",
                    f"source {shlex.quote(str(self.paths.env_file))}",
                )
            if http_listening:
                self._action(
                    actions,
                    "info",
                    "proxy.available",
                    "mihomo is reachable but BB_PROXY_MODE is direct",
                    None,
                )
        else:
            applied = False
            ready = False
            self._action(
                actions,
                "required",
                "proxy.mode",
                "Set the proxy mode through bb-stack configure",
                "bb-stack configure --proxy-mode direct",
            )
        return {
            "ready": ready,
            "configured_mode": mode,
            "configured_http": expected_http or None,
            "configured_socks": expected_socks or None,
            "http_listener": http_listening,
            "socks_listener": socks_listening,
            "active_environment": active,
            "configuration_applied": applied,
        }

    def _runtime(
        self, profile: str, actions: list[dict[str, str]]
    ) -> dict[str, Any]:
        status = RuntimeManager(self.paths).runtime_status()
        versions: dict[str, str | None] = {}
        for name, command in status["commands"].items():
            versions[name] = self._command_version(name, command) if command else None
        required_commands = ("python3", "node", "npm", "git", "claude")
        missing = [name for name in required_commands if not status["commands"].get(name)]
        if not status["venv"] or not status["node_modules"] or missing:
            self._action(
                actions,
                "required",
                "runtime.bootstrap",
                "Bootstrap missing runtime dependencies",
                f"bb-stack bootstrap --profile {profile}",
            )
        return {
            **status,
            "ready": bool(status["venv"] and status["node_modules"] and not missing),
            "missing_required_commands": missing,
            "versions": versions,
        }

    def _prompt(
        self,
        profile: str,
        workflow_profile: str | None,
        platform: str | None,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        selected = workflow_profile or self._default_workflow_profile(profile)
        if not selected:
            self._action(
                actions,
                "required",
                "prompt.profile",
                f"No L2 workflow Prompt profile is mapped to {profile}",
                None,
            )
            return {"ready": False, "selected": None, "available": []}
        registry = ProfileRegistry(self.paths)
        definition = registry.load(selected)
        if definition["l5_profile"] != profile or definition["skill_profile"] != profile:
            raise ValidationError(
                f"workflow profile {selected} does not use L4/L5 profile {profile}"
            )
        render = registry.render(selected, platform=platform)
        return {
            "ready": render.token_estimate <= render.budget,
            "selected": selected,
            "prompt_mode": render.prompt_mode,
            "workflow": render.workflow,
            "platform": render.platform,
            "token_estimate": render.token_estimate,
            "budget": render.budget,
            "output_file": render.output_file,
            "source_fragments": render.source_fragments,
            "available": registry.names(),
        }

    def _evaluation(
        self,
        workflow_profile: str | None,
        prompt_file: str | None,
        required: bool,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not workflow_profile:
            return {
                "ready": not required,
                "required": required,
                "profile": None,
                "state": "unavailable",
                "prompt_matches": False,
                "version_matches": False,
                "contract_matches": False,
                "latest": None,
            }
        manager = EvaluationManager(self.paths)
        current_contract: str | None = None
        try:
            latest = manager.latest(workflow_profile)
            current_contract = manager.contract_sha256(workflow_profile)
        except (ValidationError, OSError, ValueError) as error:
            latest = {
                "passed": False,
                "profile": workflow_profile,
                "error": error.__class__.__name__,
            }
        prompt_matches = False
        if latest and prompt_file and Path(prompt_file).is_file():
            digest = hashlib.sha256(Path(prompt_file).read_bytes()).hexdigest()
            prompt_matches = latest.get("prompt_sha256") == digest
        version_matches = bool(
            latest and latest.get("stack_version") == __version__
        )
        contract_matches = bool(
            latest
            and current_contract
            and latest.get("contract_sha256") == current_contract
        )
        passed = bool(
            latest
            and latest.get("passed")
            and prompt_matches
            and version_matches
            and contract_matches
        )
        if latest is None:
            state = "not-run"
            message = f"Run the isolated Agent behavior evaluation for {workflow_profile}"
        elif not latest.get("passed"):
            state = "failed"
            message = f"Re-run the failed Agent behavior evaluation for {workflow_profile}"
        elif not prompt_matches or not version_matches or not contract_matches:
            state = "stale"
            message = (
                "Re-run Agent evaluation after stack, Prompt, or evaluation contract "
                f"changes for {workflow_profile}"
            )
        else:
            state = "passed"
            message = ""
        if not passed:
            self._action(
                actions,
                "required" if required else "optional",
                "evaluation.agent",
                message,
                f"bb-stack eval agent --profile {workflow_profile}",
            )
        return {
            "ready": passed if required else True,
            "required": required,
            "profile": workflow_profile,
            "state": state,
            "prompt_matches": prompt_matches,
            "version_matches": version_matches,
            "contract_matches": contract_matches,
            "latest": latest,
        }

    def _skills(self, profile: str, actions: list[dict[str, str]]) -> dict[str, Any]:
        registry = SkillRegistry(self.paths)
        definition = registry.profile(profile)
        required = set(definition["required"])
        agents: dict[str, Any] = {}
        for agent in ("claude", "codex"):
            items = registry.status(profile, agent)
            missing_required = sorted(
                item["name"]
                for item in items
                if item["name"] in required and item["state"] in {"missing", "conflict"}
            )
            agents[agent] = {
                "ready": not missing_required,
                "required": len(required),
                "selected": len(items),
                "states": self._state_counts(items),
                "missing_required": missing_required,
            }
        if not agents["claude"]["ready"]:
            self._action(
                actions,
                "required",
                "skills.claude",
                "Install required Claude Skills",
                f"bb-stack skills install --profile {profile} --agent claude --required-only",
            )
        if not agents["codex"]["ready"]:
            self._action(
                actions,
                "optional",
                "skills.codex",
                "Install the same profile for Codex when it will share this stack",
                f"bb-stack skills install --profile {profile} --agent codex --required-only",
            )
        return {
            "ready": agents["claude"]["ready"],
            "orchestrator": definition["orchestrator"],
            "agents": agents,
        }

    def _engagement(
        self,
        profile: str,
        value: str | None,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        manager = EngagementManager(self.paths)
        inventory = manager.list()
        selected_path: Path | None = None
        explicit = value is not None
        if explicit:
            selected_path = self.paths.engagement(value)
        else:
            try:
                selected_path = self.paths.engagement()
            except StackError:
                pass

        selected = None
        profile_matches = True
        if selected_path:
            state = manager.validate(selected_path)
            compatible_profiles = self._capability_profiles_for_workflow(
                state["workflow"]
            )
            expected_profile = self._capability_profile_for_workflow(state["workflow"])
            profile_matches = profile in compatible_profiles
            selected = {
                "slug": state["slug"],
                "path": str(selected_path),
                "workflow": state["workflow"],
                "platform": state["platform"],
                "mode": state["mode"],
                "lifecycle": state["lifecycle"],
                "phase": state["phase"],
                "next_action": state["current"]["next_action"],
                "checkpoint_updated_at": state["checkpoint"]["updated_at"],
                "expected_profile": expected_profile,
                "compatible_profiles": compatible_profiles,
            }
            if not profile_matches:
                self._action(
                    actions,
                    "required",
                    "engagement.profile",
                    f"Use profile {expected_profile} for engagement {state['slug']}",
                    f"bb-stack status --profile {expected_profile} --engagement {state['slug']}",
                )
        invalid = [item["slug"] for item in inventory if "error" in item]
        lifecycle_counts: dict[str, int] = {}
        for item in inventory:
            lifecycle = item.get("lifecycle", "invalid")
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
        return {
            "ready": bool((not explicit or selected) and profile_matches),
            "selected": selected,
            "profile_matches": profile_matches,
            "auto_detected": bool(selected and not explicit),
            "count": len(inventory),
            "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
            "invalid": sorted(invalid),
        }

    def _default_workflow_profile(self, capability_profile: str) -> str | None:
        stack = load_yaml(self.paths.root / "stack.yaml")
        return stack["defaults"]["capability_profiles"].get(capability_profile)

    def _capability_profile_for_workflow(self, workflow: str) -> str:
        stack = load_yaml(self.paths.root / "stack.yaml")
        profile_name = stack["defaults"]["workflow_profiles"][workflow]
        return ProfileRegistry(self.paths).load(profile_name)["l5_profile"]

    def _capability_profiles_for_workflow(self, workflow: str) -> list[str]:
        stack = load_yaml(self.paths.root / "stack.yaml")
        registry = ProfileRegistry(self.paths)
        return sorted(
            capability
            for capability, profile_name in stack["defaults"]["capability_profiles"].items()
            if registry.load(profile_name)["workflow"] == workflow
        )

    def _workflow_profile_for_mode(
        self, workflow: str, capability_profile: str, mode: str
    ) -> str:
        registry = ProfileRegistry(self.paths)
        matches = []
        for name in registry.names():
            definition = registry.load(name)
            if (
                definition["workflow"] == workflow
                and definition["l5_profile"] == capability_profile
                and definition["default_mode"] == mode
            ):
                matches.append(name)
        if len(matches) != 1:
            raise ValidationError(
                f"expected one {workflow}/{capability_profile}/{mode} workflow profile, "
                f"found {len(matches)}"
            )
        return matches[0]

    def _capabilities(
        self,
        profile: str,
        registry: CapabilityRegistry,
        *,
        probe_mcp: bool,
        include_high_context: bool,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        artifact_root = self.paths.generated / "status" / profile / "artifacts"
        report = registry.doctor(profile, artifact_root)
        if not report["ready"]:
            self._action(
                actions,
                "required",
                "capabilities.required",
                "Install missing required capabilities: "
                + ", ".join(report["missing_required"]),
                f"bb-stack doctor --profile {profile} --strict",
            )
        mcp_path = self.paths.generated / "status" / profile / "mcp.json"
        rendered = registry.render_mcp(
            profile,
            mcp_path,
            artifact_root=artifact_root,
            include_high_context=include_high_context,
        )
        probe = registry.probe_mcp(mcp_path) if probe_mcp else None
        probe_ready = True
        if probe is not None:
            probe_ready = all(item.get("connected") for item in probe.values())
            if not probe_ready:
                self._action(
                    actions,
                    "required",
                    "mcp.handshake",
                    "One or more selected MCP servers failed their handshake",
                    f"bb-stack doctor --profile {profile} --probe-mcp",
                )
        providers = report["providers"]
        return {
            "ready": bool(report["ready"] and probe_ready),
            "required_ready": report["ready"],
            "missing_required": report["missing_required"],
            "capability_count": len(report["capabilities"]),
            "provider_states": self._state_counts(
                [
                    {
                        "state": "ready" if item["usable"] else "missing",
                        "name": item["name"],
                    }
                    for item in providers.values()
                ]
            ),
            "mcp_config": str(mcp_path),
            "mcp_servers": sorted(rendered["mcpServers"]),
            "high_context_included": include_high_context,
            "probe": probe if probe is not None else "not-run",
        }

    def _personal(
        self,
        profile: str,
        config: dict[str, str],
        platform: str | None,
        registry: CapabilityRegistry,
        *,
        check_external: bool,
        actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        configured_env = self.paths.environment()
        configured_env.update(config)
        configured_env["PATH"] = self.paths.runtime_path()
        providers = registry.registry()["providers"]
        capability_profile = registry.profile(profile)
        selected_capabilities = set(
            capability_profile["required"] + capability_profile["optional"]
        )
        mail_relevant = "otp.mail" in selected_capabilities
        delivery_relevant = "delivery.file-share" in selected_capabilities
        mail = registry.provider_status("mail-otp", providers["mail-otp"], configured_env)
        delivery = registry.provider_status(
            "filecodebox", providers["filecodebox"], configured_env
        )
        mail_config = self.paths.home / ".local" / "share" / "pentest-mail" / "config.env"
        mail_mode = stat.S_IMODE(mail_config.stat().st_mode) if mail_config.is_file() else None
        mail_config_valid = False
        mail_config_error = None
        mail_provider = None
        mail_auth = None
        if mail_config.is_file() and mail_mode == 0o600:
            try:
                mail_values = load_mail_config(mail_config)
                mail_settings = MailSettings.from_values(mail_values)
                mail_config_valid = True
                configured_provider = mail_values.get("MAIL_OTP_PROVIDER", "")
                mail_provider = (
                    configured_provider
                    if configured_provider in {"gmail", "outlook", "generic"}
                    else "custom"
                )
                mail_auth = mail_settings.auth
            except MailOtpError as error:
                mail_config_error = str(error)
        mail_usable = bool(mail["present"] and mail_config_valid)
        username = config.get("BB_H1_USERNAME", "").strip()
        identity_required = platform == "hackerone"
        if identity_required and not username:
            self._action(
                actions,
                "required",
                "identity.hackerone",
                "Set BB_H1_USERNAME before using the HackerOne overlay",
                "bb-stack configure --h1-username USERNAME",
            )
        if mail_config.is_file() and mail_mode == 0o600 and not mail_config_valid:
            self._action(
                actions,
                "required",
                "mail.configuration",
                "Fix mailbox configuration: " + (mail_config_error or "invalid config"),
                "bb-stack mail configure",
            )
        elif mail_relevant and not mail_usable:
            message = (
                "Configure the optional lab mailbox with bb-stack mail configure"
                if mail["present"]
                else (
                    "Run bootstrap to install the mail-otp adapter, then configure "
                    "the lab mailbox"
                )
            )
            self._action(
                actions,
                "optional",
                "mail.otp",
                message,
                "bb-stack mail configure",
            )
        if mail_mode is not None and mail_mode != 0o600:
            self._action(
                actions,
                "required",
                "mail.permissions",
                "Set mailbox config permissions to 600",
                f"chmod 600 {shlex.quote(str(mail_config))}",
            )
        delivery_url = config.get("BB_FILECODEBOX_URL", "")
        delivery_endpoint = self._redact_url(delivery_url)
        delivery_url_valid = not delivery_url or self._valid_delivery_url(delivery_url)
        if delivery_url and not delivery_url_valid:
            self._action(
                actions,
                "required",
                "delivery.url",
                "Set BB_FILECODEBOX_URL to a valid HTTP or HTTPS URL",
                "bb-stack configure --filecodebox-url https://filebox.example",
            )
        elif delivery_relevant and not delivery["usable"]:
            self._action(
                actions,
                "optional",
                "delivery.filecodebox",
                "Set BB_FILECODEBOX_URL when file handoff is needed",
                "bb-stack configure --filecodebox-url https://filebox.example",
            )
        external = {"mail": "not-run", "delivery": "not-run"}
        if check_external:
            if mail_mode is not None and mail_mode != 0o600:
                external["mail"] = "invalid-permissions"
            elif mail_config.is_file() and not mail_config_valid:
                external["mail"] = "invalid-config"
            else:
                external["mail"] = self._check_mail(
                    {**mail, "usable": mail_usable}
                )
            external["delivery"] = self._check_delivery(
                config.get("BB_FILECODEBOX_URL", ""), config
            )
        required_ready = bool(
            (not identity_required or username)
            and delivery_url_valid
        )
        mail_ready = bool(
            mail_mode in {None, 0o600}
            and (not mail_config.is_file() or mail_config_valid)
        )
        return {
            "ready": required_ready and mail_ready,
            "platform": platform,
            "agent_language": config.get("BB_AGENT_LANGUAGE", "zh-CN"),
            "hackerone": {
                "required": identity_required,
                "configured": bool(username),
                "username": username or None,
            },
            "mail_otp": {
                "command": mail["resolved"] if mail["present"] else None,
                "config": str(mail_config),
                "configured": mail_config.is_file(),
                "mode": f"{mail_mode:03o}" if mail_mode is not None else None,
                "configuration_valid": mail_config_valid,
                "provider": mail_provider,
                "auth": mail_auth,
                "error": mail_config_error,
                "usable": mail_usable and mail_mode == 0o600,
            },
            "file_delivery": {
                "configured": delivery["configuration"] == "ready",
                "endpoint": delivery_endpoint or None,
                "usable": delivery["usable"] and delivery_url_valid,
            },
            "external_checks": external,
        }

    def _keysmith(
        self, profile: str, actions: list[dict[str, str]]
    ) -> dict[str, Any]:
        try:
            status = KeysmithAdapter(self.paths).status()
            result = {
                "source_cached": status.get("source_cached", False),
                "deployed": status.get("deployed", False),
                "managed_prompt_matches": status.get("managed_prompt_matches", False),
                "doctor_available": status.get("doctor", {}).get("available", True),
                "profile": (status.get("deployment") or {}).get("profile"),
            }
        except Exception as error:
            result = {
                "source_cached": False,
                "deployed": False,
                "managed_prompt_matches": False,
                "doctor_available": False,
                "profile": None,
                "error": error.__class__.__name__,
            }
        replacement_profile = {
            "minimal": "lab-replacement",
            "ctf-web": "ctf-replacement",
        }.get(profile)
        result["recommended_profile"] = replacement_profile
        deployed_profile_valid = True
        deployed_l5_profile = None
        if result["deployed"] and result["profile"]:
            try:
                deployed_l5_profile = ProfileRegistry(self.paths).load(
                    result["profile"]
                )["l5_profile"]
            except ValidationError:
                deployed_profile_valid = False
        result["matches_selected_profile"] = bool(
            deployed_profile_valid and deployed_l5_profile == profile
        )
        if not deployed_profile_valid:
            self._action(
                actions,
                "required",
                "keysmith.profile",
                "Repair or uninstall the active Keysmith deployment; its profile is unknown",
                "bb-stack keysmith status",
            )
        if result["deployed"] and not result["managed_prompt_matches"]:
            self._action(
                actions,
                "required",
                "keysmith.drift",
                "Repair or uninstall the active Keysmith deployment; its managed Prompt changed",
                "bb-stack keysmith status",
            )
        return result

    @staticmethod
    def render_text(report: dict[str, Any]) -> str:
        state = "READY" if report["ready"] else "NEEDS ATTENTION"
        lines = [f"BB Engineering Stack: {state}", f"Profile: {report['profile']}", ""]
        lines.append("Paths")
        for name, item in report["paths"]["items"].items():
            marker = "OK" if item["exists"] and (item["writable"] or not item["required"]) else "MISS"
            lines.append(f"  [{marker}] {name}: {item['path']}")
        runtime = report["runtime"]
        workspace = report["workspace"]
        lines.extend(
            [
                "",
                "Claude Workspace",
                f"  [{'OK' if workspace['ready'] else 'MISS'}] root={workspace['root']}",
                f"  entry={workspace['default_entry']}",
                f"  MCP servers={workspace['mcp_servers']}",
            ]
        )
        lines.extend(
            [
                "",
                "Runtime",
                f"  [{'OK' if runtime['ready'] else 'MISS'}] venv={runtime['venv']} node_modules={runtime['node_modules']}",
                f"  npm registry configured={runtime['npm_registry']['configured']} resolved={runtime['npm_registry']['resolved'] or 'not-recorded'}",
            ]
        )
        version_parts = [
            f"{name}={version}"
            for name, version in runtime["versions"].items()
            if version and name in {"python3", "node", "go", "claude", "codex"}
        ]
        lines.append("  " + " | ".join(version_parts))
        prompt = report["prompt"]
        lines.extend(
            [
                "",
                "Prompt",
                f"  [{'OK' if prompt['ready'] else 'MISS'}] {prompt.get('selected') or 'unmapped'} "
                f"mode={prompt.get('prompt_mode', 'n/a')} platform={prompt.get('platform', 'n/a')} "
                f"tokens={prompt.get('token_estimate', 0)}/{prompt.get('budget', 0)}",
            ]
        )
        evaluation = report["evaluation"]
        evaluation_mark = (
            "OK"
            if evaluation["state"] == "passed"
            else "MISS" if evaluation["required"] else "OPT"
        )
        lines.append(
            f"  [{evaluation_mark}] agent-eval={evaluation['state']} "
            f"profile={evaluation['profile'] or 'none'}"
        )
        engagement = report["engagement"]
        selected_engagement = engagement["selected"]
        if selected_engagement:
            engagement_text = (
                f"{selected_engagement['slug']} workflow={selected_engagement['workflow']} "
                f"lifecycle={selected_engagement['lifecycle']} phase={selected_engagement['phase']}"
            )
        else:
            engagement_text = "none selected"
        lines.extend(
            [
                "",
                "Engagement State",
                f"  [{'OK' if engagement['ready'] else 'MISS'}] {engagement_text} "
                f"inventory={engagement['count']} states={engagement['lifecycle_counts']}",
            ]
        )
        skills = report["skills"]
        claude = skills["agents"]["claude"]
        codex = skills["agents"]["codex"]
        lines.extend(
            [
                "",
                "Skills",
                f"  [{'OK' if claude['ready'] else 'MISS'}] Claude required={claude['required']} selected={claude['selected']} states={claude['states']}",
                f"  [{'OK' if codex['ready'] else 'OPT'}] Codex required={codex['required']} selected={codex['selected']} states={codex['states']}",
                f"  orchestrator={skills['orchestrator']}",
            ]
        )
        capabilities = report["capabilities"]
        probe = capabilities["probe"]
        probe_text = "not-run" if probe == "not-run" else str(
            {name: value.get("connected", False) for name, value in probe.items()}
        )
        lines.extend(
            [
                "",
                "MCP And CLI",
                f"  [{'OK' if capabilities['ready'] else 'MISS'}] capabilities={capabilities['capability_count']} providers={capabilities['provider_states']}",
                f"  MCP servers={capabilities['mcp_servers']} probe={probe_text}",
            ]
        )
        proxy = report["proxy"]
        personal = report["personal"]
        lines.extend(
            [
                "",
                "Personal Configuration",
                f"  [{'OK' if proxy['ready'] else 'MISS'}] proxy mode={proxy['configured_mode']} applied={proxy['configuration_applied']} http_listener={proxy['http_listener']}",
                f"  [OK] Agent language={personal['agent_language']}",
                f"  [{'OK' if personal['hackerone']['configured'] else 'OPT'}] HackerOne username={personal['hackerone']['username'] or 'unset'} required={personal['hackerone']['required']}",
                f"  [{'OK' if personal['mail_otp']['usable'] else 'OPT'}] mail OTP configured={personal['mail_otp']['configured']} valid={personal['mail_otp']['configuration_valid']} command={bool(personal['mail_otp']['command'])}",
                f"  [{'OK' if personal['file_delivery']['usable'] else 'OPT'}] file delivery={personal['file_delivery']['endpoint'] or 'unset'}",
                f"  [{'OK' if report['keysmith']['deployed'] else 'OPT'}] Keysmith cached={report['keysmith']['source_cached']} deployed={report['keysmith']['deployed']} profile={report['keysmith']['profile'] or 'none'}",
            ]
        )
        lines.extend(["", "Next Actions"])
        if not report["actions"]:
            lines.append("  None")
        for action in report["actions"]:
            lines.append(f"  [{action['level'].upper()}] {action['message']}")
            if action.get("command"):
                lines.append(f"    $ {action['command']}")
        return "\n".join(lines)

    @staticmethod
    def _state_counts(items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            state = str(item["state"])
            counts[state] = counts.get(state, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _command_version(name: str, command: str) -> str | None:
        arguments = [command, "version" if name == "go" else "--version"]
        try:
            completed = subprocess.run(
                arguments,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        line = completed.stdout.strip().splitlines()
        return line[0][:160] if line else None

    @staticmethod
    def _url_endpoint(value: str) -> tuple[str, int] | None:
        if not value:
            return None
        parsed = urlparse(value)
        if not parsed.hostname:
            return None
        try:
            parsed_port = parsed.port
        except ValueError:
            return None
        if parsed_port:
            port = parsed_port
        elif parsed.scheme == "https":
            port = 443
        else:
            port = 80
        return parsed.hostname, port

    @staticmethod
    def _tcp_ready(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            return False

    @staticmethod
    def _redact_url(value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname:
            return "configured-invalid-url"
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        try:
            parsed_port = parsed.port
        except ValueError:
            return "configured-invalid-url"
        port = f":{parsed_port}" if parsed_port else ""
        return f"{parsed.scheme}://{host}{port}"

    @staticmethod
    def _valid_delivery_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
            parsed_port = parsed.port
        except ValueError:
            return False
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and (parsed_port is None or 1 <= parsed_port <= 65535)
        )

    @staticmethod
    def _check_mail(mail: dict[str, Any]) -> str:
        if not mail["usable"]:
            return "not-configured"
        try:
            completed = subprocess.run(
                [mail["resolved"], "--test"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "failed"
        return "passed" if completed.returncode == 0 else "failed"

    @staticmethod
    def _check_delivery(url: str, config: dict[str, str]) -> str:
        if not url:
            return "not-configured"
        if not StackStatus._valid_delivery_url(url):
            return "invalid-config"
        mode = config.get("BB_PROXY_MODE", "direct")
        proxy = config.get("BB_HTTP_PROXY", "")
        handler = ProxyHandler({"http": proxy, "https": proxy}) if mode == "mihomo" else ProxyHandler({})
        opener = build_opener(handler)
        endpoint = url.rstrip("/") + "/health"
        try:
            response = opener.open(
                Request(endpoint, headers={"User-Agent": "bb-stack-status/0.2"}),
                timeout=15,
            )
            response.close()
        except OSError:
            return "failed"
        return "passed"

    @staticmethod
    def _action(
        actions: list[dict[str, str]],
        level: str,
        identifier: str,
        message: str,
        command: str | None,
    ) -> None:
        item = {"level": level, "id": identifier, "message": message}
        if command:
            item["command"] = command
        actions.append(item)
