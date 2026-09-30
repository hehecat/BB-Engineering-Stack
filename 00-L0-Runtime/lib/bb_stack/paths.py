from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import StackError, ValidationError
from .io import expand, load_yaml

# Built-in fallbacks. They apply only when the environment and `stack.yaml`
# both stay silent, so a plain source checkout still resolves real paths.
BUILTIN_WORK_ROOT = "BB-Workspaces"
BUILTIN_CONFIG_HOME = Path(".config") / "bb-stack"
BUILTIN_CLAUDE_CONFIG_DIR = Path(".claude")
BUILTIN_RUNTIME = ".runtime"
BUILTIN_VERSION_FILE = "VERSION"
BUILTIN_RUNTIME_PROFILES = "02-L2-Workflow-Profiles/profiles"
BUILTIN_PLATFORMS = "02-L2-Workflow-Profiles/platforms"
BUILTIN_CAPABILITY_PROFILES = "05-L5-MCP-CLI/profiles"
BUILTIN_SKILL_PROFILES = "04-L4-Skills/profiles"
BUILTIN_GLOBAL_PROMPT = "01-L1-Global-Prompt"


def _module_root() -> Path:
    return Path(__file__).resolve().parents[3]


def source_root(env: Mapping[str, str] | None = None) -> Path:
    """`BB_STACK_ROOT` when set, otherwise the tree this package ships in."""
    environment = os.environ if env is None else env
    return (
        Path(environment.get("BB_STACK_ROOT", str(_module_root())))
        .expanduser()
        .resolve()
    )


def load_stack_manifest(root: Path, *, strict: bool = True) -> dict[str, Any]:
    """Read `stack.yaml`; an absent manifest is an empty mapping.

    Callers that only need the optional defaults pass `strict=False` so that a
    malformed manifest degrades to the built-in defaults instead of failing
    while a command line is still being assembled.
    """
    path = root / "stack.yaml"
    if not path.is_file():
        return {}
    try:
        return load_yaml(path)
    except ValidationError:
        if strict:
            raise
        return {}


def _declared(section: Any, key: str) -> str | None:
    if not isinstance(section, Mapping):
        return None
    value = section.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _version_key(label: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", label)) or (0,)


@dataclass(frozen=True)
class StackPaths:
    root: Path
    home: Path
    work_root: Path
    config_home: Path
    claude_config_dir: Path
    claude_config_explicit: bool = False

    @classmethod
    def discover(cls) -> StackPaths:
        home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
        root = source_root()
        if not (root / "stack.yaml").is_file():
            raise StackError(f"BB_STACK_ROOT is not a stack source tree: {root}")
        defaults = load_stack_manifest(root).get("defaults")
        env = dict(os.environ)
        env["HOME"] = str(home)

        def resolution(env_name: str, key: str, builtin: Path) -> Path:
            # Precedence: environment, then `stack.yaml` `defaults.<key>`, then the
            # built-in default relative to the current home directory.
            override = os.environ.get(env_name)
            if override:
                return Path(override).expanduser().resolve()
            declared = _declared(defaults, key)
            if declared is not None:
                expanded = str(expand(declared, env, strict=False))
                return Path(expanded).expanduser().resolve()
            return (home / builtin).expanduser().resolve()

        work_root = resolution("BB_WORK_ROOT", "work_root", Path(BUILTIN_WORK_ROOT))
        config_home = resolution("BB_CONFIG_HOME", "config_home", BUILTIN_CONFIG_HOME)
        claude_config_explicit = bool(os.environ.get("CLAUDE_CONFIG_DIR"))
        claude_config_dir = resolution(
            "CLAUDE_CONFIG_DIR", "claude_config_dir", BUILTIN_CLAUDE_CONFIG_DIR
        )
        return cls(
            root,
            home,
            work_root,
            config_home,
            claude_config_dir,
            claude_config_explicit,
        )

    def manifest(self) -> dict[str, Any]:
        """The stack manifest (`stack.yaml`), re-read on every call."""
        return load_stack_manifest(self.root, strict=False)

    def layer(self, name: str, builtin: str) -> Path:
        """Directory declared as `paths.<name>` in the stack manifest."""
        return self.root / (_declared(self.manifest().get("paths"), name) or builtin)

    def registry(self, name: str, builtin: str) -> Path:
        """Directory declared as `registries.<name>` in the stack manifest."""
        return self.root / (
            _declared(self.manifest().get("registries"), name) or builtin
        )

    @property
    def version_file(self) -> Path:
        """`version_file` from the manifest (`VERSION` by default)."""
        declared = _declared(self.manifest(), "version_file") or BUILTIN_VERSION_FILE
        return self.root / declared

    @property
    def version(self) -> str | None:
        """Contents of `version_file`; None when it is unreadable."""
        try:
            content = self.version_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return content or None

    @property
    def runtime(self) -> Path:
        return self.layer("runtime", BUILTIN_RUNTIME)

    @property
    def runtime_bin(self) -> Path:
        return self.runtime / "bin"

    @property
    def data_root(self) -> Path:
        return self.runtime / "data"

    @property
    def venv(self) -> Path:
        return self.runtime / "venv"

    @property
    def generated(self) -> Path:
        return self.config_home / "generated"

    @property
    def engagements_root(self) -> Path:
        return self.work_root / "engagements"

    @property
    def env_file(self) -> Path:
        return self.config_home / "env.sh"

    def environment(self, artifact_root: Path | None = None) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(self.home),
                "BB_STACK_ROOT": str(self.root),
                "BB_WORK_ROOT": str(self.work_root),
                "BB_CONFIG_HOME": str(self.config_home),
                "BB_DATA_ROOT": str(self.data_root),
            }
        )
        if self.claude_config_explicit:
            env["CLAUDE_CONFIG_DIR"] = str(self.claude_config_dir)
        else:
            env.pop("CLAUDE_CONFIG_DIR", None)
        if artifact_root:
            env["BB_ARTIFACT_ROOT"] = str(artifact_root.resolve())
        else:
            # An inherited value would otherwise leak a stale artifact root into
            # nested calls (capabilities resolve `${BB_ARTIFACT_ROOT}/browser`).
            env.pop("BB_ARTIFACT_ROOT", None)
        env["CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"] = "1"
        env["CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS"] = "1"
        return env

    def runtime_path(self, extra_path: str | None = None) -> str:
        # Newest Node first: `v9.x` must not sort ahead of `v22.x`, so compare the
        # numeric components instead of the directory names.
        nvm_bins = sorted(
            (self.home / ".nvm" / "versions" / "node").glob("*/bin"),
            key=lambda path: _version_key(path.parent.name),
            reverse=True,
        )
        entries = [
            self.runtime_bin,
            self.venv / "bin",
            self.runtime / "toolchains" / "node-current" / "bin",
            self.runtime / "toolchains" / "go-current" / "bin",
            self.runtime / "node_modules" / ".bin",
            self.home / "go" / "bin",
            self.home / ".local" / "bin",
            self.home / ".npm-global" / "bin",
            self.home / ".cargo" / "bin",
            self.home / ".bun" / "bin",
            *nvm_bins,
            Path("/usr/local/go/bin"),
            Path("/usr/local/sbin"),
            Path("/usr/local/bin"),
            Path("/usr/sbin"),
            Path("/usr/bin"),
            Path("/sbin"),
            Path("/bin"),
        ]
        extra = (
            os.environ.get("BB_EXTRA_PATH", "") if extra_path is None else extra_path
        ).split(os.pathsep)
        ordered: list[str] = []
        for entry in [str(path) for path in entries] + extra:
            if entry and entry not in ordered:
                ordered.append(entry)
        return os.pathsep.join(ordered)

    def engagement(self, value: str | Path | None = None) -> Path:
        if value is not None:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute() and "/" not in str(value):
                nested = self.engagements_root / candidate
                legacy = self.work_root / candidate
                candidate = nested if nested.exists() or not legacy.exists() else legacy
            candidate = candidate.resolve()
            if not (candidate / "engagement.yaml").is_file():
                raise StackError(f"not an engagement directory: {candidate}")
            return candidate

        current = Path.cwd().resolve()
        for candidate in (current, *current.parents):
            if (candidate / "engagement.yaml").is_file():
                return candidate
        raise StackError("no engagement supplied and none found from current directory")

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.runtime,
            self.runtime_bin,
            self.data_root,
            self.config_home,
            self.generated,
            self.work_root,
            self.engagements_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
