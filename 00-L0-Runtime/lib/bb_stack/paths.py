from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import StackError


def _module_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _expand(value: str, env: Mapping[str, str]) -> Path:
    expanded = value
    for name, replacement in env.items():
        expanded = expanded.replace("${" + name + "}", replacement)
    return Path(os.path.expanduser(os.path.expandvars(expanded))).resolve()


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
        root = (
            Path(os.environ.get("BB_STACK_ROOT", str(_module_root())))
            .expanduser()
            .resolve()
        )
        if not (root / "stack.yaml").is_file():
            raise StackError(f"BB_STACK_ROOT is not a stack source tree: {root}")
        work_root = (
            Path(os.environ.get("BB_WORK_ROOT", str(home / "BB-Workspaces")))
            .expanduser()
            .resolve()
        )
        config_home = (
            Path(os.environ.get("BB_CONFIG_HOME", str(home / ".config" / "bb-stack")))
            .expanduser()
            .resolve()
        )
        claude_config_explicit = bool(os.environ.get("CLAUDE_CONFIG_DIR"))
        claude_config_dir = (
            Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
            .expanduser()
            .resolve()
        )
        return cls(
            root,
            home,
            work_root,
            config_home,
            claude_config_dir,
            claude_config_explicit,
        )

    @property
    def runtime(self) -> Path:
        return self.root / ".runtime"

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
        env["CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"] = "1"
        env["CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS"] = "1"
        return env

    def runtime_path(self, extra_path: str | None = None) -> str:
        nvm_bins = sorted(
            (self.home / ".nvm" / "versions" / "node").glob("*/bin"), reverse=True
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


def relative_to_home(path: Path, home: Path) -> str:
    try:
        return "$HOME/" + str(path.resolve().relative_to(home.resolve()))
    except ValueError:
        return str(path.resolve())
