"""Agent backend adapters.

Every agent CLI exposes a different mechanism for the two things this stack
owns: the routed Prompt and the per-profile MCP servers. This module turns
`00-L0-Runtime/config/backends.yaml` into that capability matrix and applies it
to a launch command, so `runtime.launch()` holds no backend-specific flag
names.

An unavailable capability is reported, never silently skipped: a launch that
cannot inject a replacement Prompt fails with the backend named.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import StackError, ValidationError
from .io import dump_json, dump_yaml, load_yaml
from .paths import StackPaths
from .validation import validate


class _PatchLoader(yaml.SafeLoader):
    """SafeLoader that tolerates DSH's `!!js` loader expressions.

    `dsh --dump-config` emits expressions such as `!!js process.env.DSH_TOOLS_MODE`
    for values the profile leaves to the environment. The tag is DSH-specific and
    the value is irrelevant here, so it is read as an opaque string.
    """


_PatchLoader.add_multi_constructor(
    "tag:yaml.org,2002:js",
    lambda loader, _suffix, node: loader.construct_scalar(node)
    if isinstance(node, yaml.ScalarNode)
    else None,
)


def read_patch(path: Path) -> list[Any]:
    """Read a DSH patch overlay as a list, tolerating `!!js` expressions."""
    if not path.is_file():
        return []
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_PatchLoader)
    if loaded is None:
        return []
    if not isinstance(loaded, list):
        raise ValidationError(f"patch overlay {path} must be a YAML list")
    return loaded


def write_patch(path: Path, entries: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(entries, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _toml_string(value: str) -> str:
    """Encode *value* as a TOML basic string for a `-c key=value` override."""
    return json.dumps(value)


# DSH restricts `serverName` to this alphabet and length. The stack's provider
# names (playwright, chrome-devtools, …) satisfy it, but a future provider that
# does not must fail loudly rather than produce an unloadable patch.
DSH_SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@dataclass(frozen=True)
class Backend:
    name: str
    label: str
    command: str
    bin_env: str | None
    config_base: str | None
    skills_root: Path
    context_files: tuple[str, ...]
    headless: tuple[str, ...]
    prompt_append: dict[str, Any]
    prompt_replace: dict[str, Any]
    mcp: dict[str, Any]
    capabilities: frozenset[str]

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def binary(self, runtime_path: str | None = None) -> str | None:
        override = os.environ.get(self.bin_env) if self.bin_env else None
        if override:
            return override
        return shutil.which(self.command, path=runtime_path)

    def prompt_injector(self, prompt_mode: str) -> dict[str, Any]:
        if prompt_mode == "replacement":
            return self.prompt_replace
        return self.prompt_append

    def apply_prompt(
        self,
        *,
        prompt_mode: str,
        prompt_file: Path,
        command: list[str],
        env: dict[str, str],
        work_dir: Path,
    ) -> dict[str, Any]:
        """Extend *command*/*env* so this backend receives the routed Prompt."""
        injector = self.prompt_injector(prompt_mode)
        style = injector["style"]
        record: dict[str, Any] = {"backend": self.name, "style": style, "mode": prompt_mode}
        if style == "flag-file":
            command.extend([injector["flag"], str(prompt_file)])
            record["flag"] = injector["flag"]
        elif style == "flag-text":
            command.extend([injector["flag"], str(prompt_file)])
            record["flag"] = injector["flag"]
        elif style == "config-text":
            command.extend(
                [
                    injector["flag"],
                    f"{injector['key']}={_toml_string(prompt_file.read_text(encoding='utf-8'))}",
                ]
            )
            record["key"] = injector["key"]
        elif style == "config-file":
            command.extend(
                [injector["flag"], f"{injector['key']}={_toml_string(str(prompt_file))}"]
            )
            record["key"] = injector["key"]
        elif style == "patch-config":
            path = work_dir / injector["patch"]
            config = self._patch_persona(injector, env)
            prompt_text = prompt_file.read_text(encoding="utf-8")
            if prompt_mode == "replacement":
                config["personaPrefix"] = prompt_text
            else:
                existing = config.get("personaSuffix") or ""
                config["personaSuffix"] = (
                    f"{existing}\n\n{prompt_text}" if existing else prompt_text
                )
            entries = [
                entry
                for entry in read_patch(path)
                if not (isinstance(entry, dict) and entry.get("id") == injector["entry"])
            ]
            entries.append(
                {"id": injector["entry"], "name": injector["plugin"], "config": config}
            )
            write_patch(path, entries)
            record["patch"] = str(path)
            record["keys"] = sorted(config)
            # The Prompt lives in the same overlay as the MCP entries, so the
            # launcher flag is claimed here too; `apply_mcp` adds it only when
            # it is not already present.
            flag = self.mcp.get("flag")
            if flag and flag not in command:
                command.extend([flag, str(path)])
        elif style == "env-config":
            _merge_env_config(
                env,
                injector["env"],
                {"agent": {injector["agent"]: {"prompt": str(prompt_file)}}},
            )
            record["env"] = injector["env"]
            record["agent"] = injector["agent"]
            record["agent_flag"] = ["--agent", injector["agent"]]
            command.extend(["--agent", injector["agent"]])
        elif style == "context-only":
            # The CLI has no Prompt channel; it reads the workspace context
            # files, which still carry the routed policy. Reported, not hidden.
            record["delivered"] = "context-files"
        else:
            raise StackError(
                f"agent backend {self.name!r} cannot inject a "
                f"{prompt_mode} Prompt; run with --backend claude or add a "
                f"working prompt injector to backends.yaml"
            )
        return record

    def _patch_persona(
        self, injector: dict[str, Any], env: dict[str, str]
    ) -> dict[str, Any]:
        """Read the profile's current system-prompt config through `probe`.

        A DSH patch replaces a plugin's whole `config` instead of merging into
        it, so the injector has to write back the fields it is not changing.
        Probing the live profile keeps that from silently dropping the harness's
        own persona text when a future release adds or renames a field.
        """
        binary = self.binary(env.get("PATH"))
        if not binary:
            raise StackError(
                f"agent backend {self.name!r} binary was not found for its probe"
            )
        completed = subprocess.run(
            [binary, *injector["probe"]],
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise StackError(
                f"agent backend {self.name!r} probe failed: "
                + (completed.stderr.strip() or f"exit {completed.returncode}")
            )
        try:
            document = yaml.load(completed.stdout, Loader=_PatchLoader)
        except yaml.YAMLError as error:
            raise StackError(
                f"agent backend {self.name!r} probe output is not YAML: {error}"
            ) from error
        for entry in document or []:
            if isinstance(entry, dict) and entry.get("id") == injector["entry"]:
                config = entry.get("config")
                return dict(config) if isinstance(config, dict) else {}
        return {}

    def render_servers(self, servers: dict[str, Any]) -> Any:
        """Return MCP servers in this backend's native configuration shape."""
        fmt = self.mcp.get("format", "mcpServers")
        if fmt == "mcpServers":
            return {"mcpServers": servers}
        if fmt == "opencode":
            converted: dict[str, Any] = {}
            for name, server in servers.items():
                command = [server["command"], *server.get("args", [])]
                entry: dict[str, Any] = {"type": "local", "command": command, "enabled": True}
                if server.get("env"):
                    entry["environment"] = dict(server["env"])
                elif server.get("type") == "http" and server.get("url"):
                    entry = {"type": "remote", "url": server["url"], "enabled": True}
                converted[name] = entry
            return {"mcp": converted}
        raise ValidationError(f"unsupported MCP format for {self.name}: {fmt}")

    def apply_mcp(
        self,
        *,
        servers: dict[str, Any],
        rendered_file: Path,
        command: list[str],
        env: dict[str, str],
        work_dir: Path,
    ) -> dict[str, Any]:
        """Extend *command*/*env* so this backend receives *servers*."""
        record: dict[str, Any] = {
            "backend": self.name,
            "style": self.mcp["style"],
            "servers": sorted(servers),
        }
        if not servers:
            record["style"] = "none"
            return record
        style = self.mcp["style"]
        if style == "flag-file":
            command.extend([self.mcp["flag"], str(rendered_file)])
            if self.mcp.get("strict_flag"):
                command.append(self.mcp["strict_flag"])
            record["path"] = str(rendered_file)
        elif style == "config-table":
            table = self.mcp["table"]
            for name, server in servers.items():
                prefix = f"{table}.{name}"
                command.extend(
                    [self.mcp["flag"], f"{prefix}.command={_toml_string(server['command'])}"]
                )
                if server.get("args"):
                    args = ", ".join(_toml_string(a) for a in server["args"])
                    command.extend([self.mcp["flag"], f"{prefix}.args=[{args}]"])
                if server.get("env"):
                    pairs = ", ".join(
                        f"{k}={_toml_string(v)}" for k, v in sorted(server["env"].items())
                    )
                    command.extend([self.mcp["flag"], f"{prefix}.env={{{pairs}}}"])
        elif style == "project-file":
            target = work_dir / self.mcp["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            dump_json(target, self.render_servers(servers))
            record["path"] = str(target)
        elif style == "patch-file":
            path = work_dir / self.mcp["patch"]
            entries = read_patch(path)
            for name, server in servers.items():
                if not DSH_SERVER_NAME.match(name):
                    raise ValidationError(
                        f"MCP server name {name!r} cannot be a DSH serverName "
                        f"(expected [A-Za-z0-9_-]{{1,32}})"
                    )
                config: dict[str, Any] = {"serverName": name}
                if server.get("command"):
                    config["transport"] = "stdio"
                    config["command"] = server["command"]
                    config["args"] = list(server.get("args", []))
                    if server.get("env"):
                        config["env"] = dict(server["env"])
                else:
                    config["transport"] = "streamable-http"
                    config["url"] = server.get("url", "")
                    if server.get("headers"):
                        config["headers"] = dict(server["headers"])
                entries.append(
                    {
                        "insert": [
                            {
                                "id": f"mcp-{name}",
                                "name": self.mcp["plugin"],
                                "config": config,
                            }
                        ]
                    }
                )
            write_patch(path, entries)
            record["patch"] = str(path)
            if self.mcp["flag"] not in command:
                command.extend([self.mcp["flag"], str(path)])
        elif style == "env-config":
            _merge_env_config(env, self.mcp["env"], self.render_servers(servers))
            record["env"] = self.mcp["env"]
        else:
            raise StackError(
                f"agent backend {self.name!r} cannot receive MCP servers; "
                f"drop --include-high-context-mcp or use --backend claude"
            )
        return record


def _merge_env_config(env: dict[str, str], variable: str, payload: dict[str, Any]) -> None:
    """Deep-merge *payload* into the JSON object already held by *variable*."""
    current: dict[str, Any] = {}
    if env.get(variable):
        try:
            parsed = json.loads(env[variable])
        except json.JSONDecodeError as error:
            raise ValidationError(
                f"{variable} is not valid JSON; refusing to overwrite it"
            ) from error
        if not isinstance(parsed, dict):
            raise ValidationError(f"{variable} must hold a JSON object")
        current = parsed
    _deep_merge(current, payload)
    env[variable] = json.dumps(current, separators=(",", ":"))


def _deep_merge(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _deep_merge(existing, value)
        else:
            target[key] = value


class BackendRegistry:
    """Reads and validates the declared agent backends."""

    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.config_path = paths.root / "00-L0-Runtime" / "config" / "backends.yaml"
        self.schema_path = (
            paths.root / "00-L0-Runtime" / "config" / "backends.schema.json"
        )

    def document(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise ValidationError(f"missing backend registry: {self.config_path}")
        value = load_yaml(self.config_path)
        validate(value, self.schema_path, "backend registry")
        return value

    def names(self) -> list[str]:
        return sorted(self.document()["backends"])

    def default_name(self) -> str:
        document = self.document()
        name = document["default"]
        if name not in document["backends"]:
            raise ValidationError(f"default backend is not declared: {name}")
        return name

    def base_path(self, name: str) -> Path:
        document = self.document()
        if name not in document["paths"]:
            raise ValidationError(f"undeclared backend path base: {name}")
        base = document["paths"][name]["base"]
        home = self.paths.home
        mapping = {
            "claude_config": self.paths.claude_config_dir,
            "codex_home": Path(os.environ.get("CODEX_HOME", home / ".codex")),
            "user_agents": home / ".agents",
            "omp_agent": Path(
                os.environ.get("PI_CODING_AGENT_DIR", home / ".omp" / "agent")
            ),
            "dsh_home": Path(os.environ.get("DSH_HOME", home / ".dsh")),
            "opencode_config": Path(
                os.environ.get("OPENCODE_CONFIG_DIR", home / ".config" / "opencode")
            ),
            "cursor_config": home / ".cursor",
            "home": home,
        }
        if base not in mapping:
            raise ValidationError(f"unknown backend path base: {base}")
        return mapping[base].expanduser().resolve()

    def get(self, name: str) -> Backend:
        document = self.document()
        backends = document["backends"]
        if name not in backends:
            raise ValidationError(
                f"unknown agent backend: {name}; declared: {', '.join(sorted(backends))}"
            )
        raw = backends[name]
        paths = document["paths"]
        if raw["skills_dir"] not in paths:
            raise ValidationError(
                f"backend {name} references undeclared skills_dir path: {raw['skills_dir']}"
            )
        entry = paths[raw["skills_dir"]]
        skills_root = (self.base_path(raw["skills_dir"]) / entry["sub"]).resolve()
        return Backend(
            name=name,
            label=raw["label"],
            command=raw["command"],
            bin_env=raw.get("bin_env"),
            config_base=raw.get("config_base"),
            skills_root=skills_root,
            context_files=tuple(raw["context_files"]),
            headless=tuple(raw["headless"]),
            prompt_append=dict(raw["prompt"]["append"]),
            prompt_replace=dict(raw["prompt"]["replace"]),
            mcp=dict(raw["mcp"]),
            capabilities=frozenset(raw["capabilities"]),
        )

    def selected(self, name: str | None) -> Backend:
        return self.get(name or self._environment_default() or self.default_name())

    def _environment_default(self) -> str | None:
        value = os.environ.get("BB_AGENT_BACKEND")
        if not value:
            return None
        if value not in self.document()["backends"]:
            raise ValidationError(f"BB_AGENT_BACKEND names an unknown backend: {value}")
        return value

    def validate_all(self) -> list[str]:
        document = self.document()
        declared = set(document["backends"])
        if document["default"] not in declared:
            raise ValidationError(
                f"default backend is not declared: {document['default']}"
            )
        for name in sorted(declared):
            backend = self.get(name)
            # A backend that claims a capability must actually be able to
            # deliver it; the registry is the single place that promise lives.
            if "prompt-append" in backend.capabilities:
                style = backend.prompt_append["style"]
                if style in {"unsupported", "context-only"}:
                    raise ValidationError(
                        f"backend {name} claims prompt-append but its injector is {style}"
                    )
            if "prompt-replace" in backend.capabilities:
                style = backend.prompt_replace["style"]
                if style in {"unsupported", "context-only"}:
                    raise ValidationError(
                        f"backend {name} claims prompt-replace but its injector is {style}"
                    )
            for capability in (
                "mcp-flag",
                "mcp-table",
                "mcp-project-file",
                "mcp-env-config",
            ):
                if capability in backend.capabilities and backend.mcp["style"] == "unsupported":
                    raise ValidationError(
                        f"backend {name} claims {capability} but declares no MCP channel"
                    )
        return sorted(declared)
