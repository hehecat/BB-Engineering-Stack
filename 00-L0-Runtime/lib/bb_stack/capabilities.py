from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from .errors import CommandError, ValidationError
from .io import dump_json, expand, load_json, load_yaml
from .paths import StackPaths
from .validation import validate


class CapabilityRegistry:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.layer = paths.root / "05-L5-MCP-CLI"
        self.registry_path = self.layer / "capabilities.yaml"
        self.registry_schema = self.layer / "schema" / "capabilities.schema.json"
        self.profile_schema = self.layer / "schema" / "profile.schema.json"
        self.profile_dir = self.layer / "profiles"

    def registry(self) -> dict[str, Any]:
        value = load_yaml(self.registry_path)
        validate(value, self.registry_schema, "capability registry")
        return value

    def profile_names(self) -> list[str]:
        return sorted(path.stem for path in self.profile_dir.glob("*.yaml"))

    def profile(self, name: str) -> dict[str, Any]:
        path = self.profile_dir / f"{name}.yaml"
        if not path.is_file():
            raise ValidationError(f"unknown L5 profile: {name}")
        value = load_yaml(path)
        validate(value, self.profile_schema, f"L5 profile {name}")
        if value["name"] != name:
            raise ValidationError(f"L5 profile filename/name mismatch: {path}")
        return value

    def validate_all(self) -> list[str]:
        registry = self.registry()
        providers = registry["providers"]
        mcp_names: dict[str, str] = {}
        for provider_name, provider in providers.items():
            if provider["kind"] != "mcp":
                continue
            server_name = provider["mcp"]["name"]
            if server_name in mcp_names:
                raise ValidationError(
                    f"MCP server name {server_name!r} is shared by providers "
                    f"{mcp_names[server_name]!r} and {provider_name!r}"
                )
            mcp_names[server_name] = provider_name
        for capability_name, capability in registry["capabilities"].items():
            missing = sorted(set(capability["providers"]) - set(providers))
            if missing:
                raise ValidationError(
                    f"capability {capability_name} references unknown providers: "
                    + ", ".join(missing)
                )
        known = set(registry["capabilities"])
        names = self.profile_names()
        for name in names:
            profile = self.profile(name)
            overlap = set(profile["required"]) & set(profile["optional"])
            if overlap:
                raise ValidationError(
                    f"L5 profile {name} repeats capabilities: {', '.join(sorted(overlap))}"
                )
            missing = (set(profile["required"]) | set(profile["optional"])) - known
            if missing:
                raise ValidationError(
                    f"L5 profile {name} references unknown capabilities: "
                    + ", ".join(sorted(missing))
                )
        return names

    def side_effects(self, profile_name: str) -> list[str]:
        registry = self.registry()
        profile = self.profile(profile_name)
        selected = profile["required"] + profile["optional"]
        provider_names = {
            provider
            for capability in selected
            for provider in registry["capabilities"][capability]["providers"]
        }
        return sorted(
            {
                effect
                for provider in provider_names
                for effect in registry["providers"][provider]["side_effects"]
            }
        )

    def _environment(self, artifact_root: Path | None) -> dict[str, str]:
        env = self.paths.environment(artifact_root)
        env["PATH"] = self.paths.runtime_path()
        if not env.get("BB_CHROMIUM_BIN"):
            chromium = (
                shutil.which("chromium", path=env["PATH"])
                or shutil.which("chromium-browser", path=env["PATH"])
                or shutil.which("google-chrome", path=env["PATH"])
            )
            if chromium:
                env["BB_CHROMIUM_BIN"] = chromium
        if artifact_root:
            engagement = artifact_root.resolve().parent
            state_path = engagement / ".bb-stack" / "browser" / "runtime.json"
            if state_path.is_file():
                try:
                    state = load_json(state_path)
                except ValidationError:
                    state = {}
                browser_url = state.get("browser_url")
                if isinstance(browser_url, str):
                    env["BB_BROWSER_URL"] = browser_url
        return env

    def provider_status(
        self, name: str, provider: dict[str, Any], env: dict[str, str]
    ) -> dict[str, Any]:
        locator = expand(provider["locator"], env, strict=False)
        present, resolved, detail = self._locate(locator, env)
        config_state, config_detail = self._configuration(
            provider.get("configuration"), env
        )
        usable = present and config_state != "missing"
        return {
            "name": name,
            "kind": provider["kind"],
            "present": present,
            "resolved": resolved,
            "locator_detail": detail,
            "configuration": config_state,
            "configuration_detail": config_detail,
            "usable": usable,
            "placement": provider["placement"],
        }

    @staticmethod
    def _locate(locator: dict[str, Any], env: dict[str, str]) -> tuple[bool, str, str]:
        kind = locator["type"]
        if kind == "command":
            resolved = shutil.which(locator["value"], path=env.get("PATH"))
            return bool(resolved), resolved or locator["value"], "command"
        if kind == "path":
            value = Path(locator["value"])
            interpreter = locator.get("interpreter")
            if interpreter:
                interpreter_path = shutil.which(interpreter, path=env.get("PATH"))
                if not interpreter_path:
                    return False, str(value), f"missing interpreter: {interpreter}"
            return value.exists(), str(value), "path"
        if kind == "tcp":
            host, port = locator["host"], int(locator["port"])
            try:
                with socket.create_connection((host, port), timeout=0.4):
                    return True, f"{host}:{port}", "tcp connected"
            except OSError as error:
                return False, f"{host}:{port}", error.__class__.__name__
        return False, str(locator), f"unsupported locator: {kind}"

    def _configuration(
        self, configuration: dict[str, Any] | None, env: dict[str, str]
    ) -> tuple[str, list[str]]:
        if not configuration:
            return "not-required", []
        config = expand(configuration, env, strict=False)
        checks: list[bool] = []
        details: list[str] = []
        for filename in config.get("files_all", []):
            found = Path(filename).exists()
            checks.append(found)
            if not found:
                details.append(f"missing file: {filename}")
        files_any = config.get("files_any", [])
        if files_any:
            found = any(Path(filename).exists() for filename in files_any)
            checks.append(found)
            if not found:
                details.append("none of files_any exist")
        for variable in config.get("env_all", []):
            found = bool(env.get(variable))
            checks.append(found)
            if not found:
                details.append(f"missing env: {variable}")
        modules = config.get("python_modules", [])
        if modules:
            python = str(config.get("python_from", self.paths.venv / "bin" / "python"))
            code = (
                "import importlib.util,sys;"
                "sys.exit(0 if all(importlib.util.find_spec(x) for x in sys.argv[1:]) else 1)"
            )
            try:
                completed = subprocess.run(
                    [python, "-c", code, *modules],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                )
                found = completed.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                found = False
            checks.append(found)
            if not found:
                details.append("missing Python modules: " + ", ".join(modules))
        if not checks or all(checks):
            return "ready", details
        return ("missing" if config.get("required") else "optional-missing"), details

    def doctor(
        self, profile_name: str, artifact_root: Path | None = None
    ) -> dict[str, Any]:
        self.validate_all()
        registry = self.registry()
        profile = self.profile(profile_name)
        env = self._environment(artifact_root)
        provider_names: set[str] = set()
        selected_capabilities = profile["required"] + profile["optional"]
        for capability_name in selected_capabilities:
            provider_names.update(
                registry["capabilities"][capability_name]["providers"]
            )
        providers = {
            name: self.provider_status(name, registry["providers"][name], env)
            for name in sorted(provider_names)
        }
        capabilities: dict[str, Any] = {}
        for capability_name in selected_capabilities:
            contract = registry["capabilities"][capability_name]
            statuses = [providers[name]["usable"] for name in contract["providers"]]
            ready = all(statuses) if contract["strategy"] == "all" else any(statuses)
            capabilities[capability_name] = {
                "required": capability_name in profile["required"],
                "strategy": contract["strategy"],
                "providers": contract["providers"],
                "ready": ready,
            }
        missing_required = sorted(
            name for name in profile["required"] if not capabilities[name]["ready"]
        )
        return {
            "schema_version": 1,
            "profile": profile_name,
            "ready": not missing_required,
            "missing_required": missing_required,
            "capabilities": capabilities,
            "providers": providers,
        }

    def render_mcp(
        self,
        profile_name: str,
        output: Path,
        *,
        artifact_root: Path,
        include_high_context: bool = False,
    ) -> dict[str, Any]:
        report = self.doctor(profile_name, artifact_root)
        registry = self.registry()
        profile = self.profile(profile_name)
        env = self._environment(artifact_root)
        servers: dict[str, Any] = {}
        selected = profile["required"] + profile["optional"]
        required = set(profile["required"])
        for capability_name in selected:
            capability = registry["capabilities"][capability_name]
            for provider_name in capability["providers"]:
                provider = registry["providers"][provider_name]
                if provider["kind"] != "mcp":
                    continue
                status = report["providers"][provider_name]
                if not status["usable"]:
                    continue
                if (
                    provider["placement"] == "subagent-inline"
                    and capability_name not in required
                    and not include_high_context
                ):
                    continue
                mcp = expand(provider["mcp"], env)
                server: dict[str, Any] = {
                    "type": mcp["transport"],
                    "command": mcp["command"],
                    "args": mcp["args"],
                }
                servers[mcp["name"]] = server
        document = {"mcpServers": servers}
        dump_json(output, document)
        return document

    def probe_mcp(self, config_path: Path, timeout: int = 25) -> dict[str, Any]:
        config = load_json(config_path)
        servers = config.get("mcpServers")
        if not isinstance(servers, dict):
            raise ValidationError(f"invalid MCP config: {config_path}")
        probe = self.paths.runtime / "mcp_probe.mjs"
        node = shutil.which("node", path=self.paths.runtime_path())
        if not probe.is_file() or not node:
            raise CommandError("MCP probe runtime is not bootstrapped")
        env = self._environment(config_path.parent)
        results: dict[str, Any] = {}
        for name, server in servers.items():
            launch = {"command": server["command"], "args": server.get("args", [])}
            try:
                completed = subprocess.run(
                    [node, str(probe), json.dumps(launch)],
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                try:
                    result = json.loads(completed.stdout)
                except json.JSONDecodeError:
                    result = {
                        "connected": False,
                        "error": completed.stderr.strip() or completed.stdout.strip(),
                    }
            except subprocess.TimeoutExpired:
                result = {"connected": False, "error": f"timeout after {timeout}s"}
            results[name] = result
        return results
