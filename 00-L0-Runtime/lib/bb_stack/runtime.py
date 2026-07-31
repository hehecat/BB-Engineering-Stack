from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
from urllib.request import urlopen

from .capabilities import CapabilityRegistry
from .configuration import ConfigurationManager, load_machine_config
from .errors import CommandError, StackError, ValidationError
from .io import atomic_write, expand, load_yaml
from .paths import StackPaths
from .profiles import ProfileRegistry
from .skills import SkillRegistry
from .validation import validate


class RuntimeManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.config = paths.root / "00-L0-Runtime" / "config"

    def bootstrap(
        self,
        profile: str,
        *,
        include_optional: bool = False,
        skip_tools: bool = False,
        skip_node: bool = False,
        skip_skills: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        CapabilityRegistry(self.paths).profile(profile)
        SkillRegistry(self.paths).profile(profile)
        self.paths.ensure_runtime_dirs()
        actions: list[dict[str, Any]] = []
        actions.append(self._python_runtime(dry_run))
        if not skip_node:
            actions.append(self._node_runtime(dry_run))
        actions.extend(self._install_wrappers(dry_run))
        self._write_env(dry_run)
        actions.append(
            {"component": "env", "state": "planned" if dry_run else "ready", "path": str(self.paths.env_file)}
        )
        if not skip_tools:
            actions.extend(self.install_tools(profile, include_optional, dry_run=dry_run))
        if not skip_skills:
            if dry_run:
                actions.append({"component": "skills", "state": "planned", "profile": profile})
            else:
                installed = SkillRegistry(self.paths).install(
                    profile, agent="claude", include_optional=include_optional, force=False
                )
                actions.append(
                    {
                        "component": "skills",
                        "state": "ready",
                        "profile": profile,
                        "count": len(installed),
                    }
                )
        return {"schema_version": 1, "profile": profile, "dry_run": dry_run, "actions": actions}

    def validate_config(self) -> dict[str, Any]:
        tools = load_yaml(self.config / "tools.yaml")
        toolchains = load_yaml(self.config / "toolchains.yaml")
        validate(tools, self.config / "tools.schema.json", "tool installer manifest")
        validate(toolchains, self.config / "toolchains.schema.json", "toolchain manifest")
        known = set(tools["installers"])
        for name, profile in tools["profiles"].items():
            missing = (set(profile["required"]) | set(profile["optional"])) - known
            if missing:
                raise ValidationError(
                    f"tool profile {name} references unknown installers: {', '.join(sorted(missing))}"
                )
        return {"tool_profiles": sorted(tools["profiles"]), "toolchains": sorted(toolchains["toolchains"])}

    def _run(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> None:
        try:
            subprocess.run(command, env=env, cwd=cwd, timeout=timeout, check=True)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise CommandError(f"command failed: {shlex.join(command)}: {error}") from error

    def _python_runtime(self, dry_run: bool) -> dict[str, Any]:
        python = self.paths.venv / "bin" / "python"
        requirements = self.config / "requirements.lock"
        stamp = self.paths.runtime / "python.stamp"
        digest = self._digest_files([requirements, self.paths.root / "pyproject.toml"])
        if dry_run:
            return {"component": "python-runtime", "state": "planned", "path": str(python)}
        if python.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == digest:
            return {"component": "python-runtime", "state": "ready", "path": str(python)}
        if not python.is_file():
            self._run([sys.executable, "-m", "venv", str(self.paths.venv)])
        self._run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements),
            ]
        )
        self._run([str(python), "-m", "pip", "install", "--no-deps", "-e", str(self.paths.root)])
        atomic_write(stamp, digest + "\n")
        return {"component": "python-runtime", "state": "ready", "path": str(python)}

    def _node_runtime(self, dry_run: bool) -> dict[str, Any]:
        source = self.config / "node-runtime"
        stamp = self.paths.runtime / "node.stamp"
        digest = self._digest_files([source / "package.json", source / "package-lock.json"])
        if dry_run:
            return {
                "component": "node-runtime",
                "state": "planned",
                "path": str(self.paths.runtime / "node_modules"),
            }
        self._ensure_toolchain("node")
        npm = shutil.which("npm", path=self.paths.runtime_path())
        if not npm:
            raise CommandError("npm is required to bootstrap MCP packages")
        if (
            (self.paths.runtime / "node_modules").is_dir()
            and (self.paths.runtime / "mcp_probe.mjs").is_file()
            and stamp.is_file()
            and stamp.read_text(encoding="utf-8").strip() == digest
        ):
            return {
                "component": "node-runtime",
                "state": "ready",
                "path": str(self.paths.runtime / "node_modules"),
            }
        for name in ("package.json", "package-lock.json"):
            shutil.copy2(source / name, self.paths.runtime / name)
        self._run(
            [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", str(self.paths.runtime)]
        )
        shutil.copy2(
            self.paths.root / "05-L5-MCP-CLI" / "lib" / "mcp_probe.mjs",
            self.paths.runtime / "mcp_probe.mjs",
        )
        atomic_write(stamp, digest + "\n")
        return {
            "component": "node-runtime",
            "state": "ready",
            "path": str(self.paths.runtime / "node_modules"),
        }

    @staticmethod
    def _digest_files(paths: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _ensure_toolchain(self, name: str) -> None:
        config = load_yaml(self.config / "toolchains.yaml")["toolchains"][name]
        existing = shutil.which(name, path=self.paths.runtime_path())
        if existing and self._toolchain_version_ready(name, existing, config):
            return
        if platform.system() != "Linux" or platform.machine() not in config["files"]:
            raise CommandError(
                f"{name} is missing or too old; portable bootstrap supports Linux x86_64/aarch64"
            )
        file_spec = config["files"][platform.machine()]
        cache = self.paths.runtime / "cache"
        toolchains = self.paths.runtime / "toolchains"
        cache.mkdir(parents=True, exist_ok=True)
        toolchains.mkdir(parents=True, exist_ok=True)
        archive = cache / file_spec["archive"]
        if not archive.is_file() or self._sha256(archive) != file_spec["sha256"]:
            temporary = archive.with_suffix(archive.suffix + ".part")
            try:
                with urlopen(file_spec["url"], timeout=120) as response, temporary.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
                if self._sha256(temporary) != file_spec["sha256"]:
                    raise CommandError(f"checksum mismatch for {file_spec['archive']}")
                os.replace(temporary, archive)
            finally:
                if temporary.exists():
                    temporary.unlink()
        target = toolchains / f"{name}-{config['version']}-{platform.machine()}"
        if not target.is_dir():
            with tempfile.TemporaryDirectory(prefix=f"{name}-extract-", dir=toolchains) as temporary_dir:
                temporary_path = Path(temporary_dir)
                with tarfile.open(archive) as handle:
                    self._safe_extract(handle, temporary_path)
                extracted = temporary_path / file_spec["top_directory"]
                if not extracted.is_dir():
                    raise CommandError(f"archive layout mismatch for {name}")
                extracted.rename(target)
        current = toolchains / f"{name}-current"
        replacement = toolchains / f".{name}-current.{os.getpid()}"
        replacement.symlink_to(target.name, target_is_directory=True)
        os.replace(replacement, current)

    def _toolchain_version_ready(self, name: str, command: str, config: dict[str, Any]) -> bool:
        try:
            completed = subprocess.run(
                [command, "--version" if name == "node" else "version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
            )
        except OSError:
            return False
        match = __import__("re").search(r"(?:v|go)([0-9]+)\.([0-9]+)", completed.stdout)
        if not match:
            return False
        major, minor = int(match.group(1)), int(match.group(2))
        if name == "node":
            return major >= int(config["minimum_major"])
        minimum = tuple(int(item) for item in str(config["minimum"]).split("."))
        return (major, minor) >= minimum

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
        base = destination.resolve()
        for member in archive.getmembers():
            if member.isdev() or member.isfifo():
                raise CommandError(f"archive contains a special file: {member.name}")
            target = (destination / member.name).resolve()
            try:
                target.relative_to(base)
            except ValueError as error:
                raise CommandError(f"archive path escapes destination: {member.name}") from error
            if member.issym() or member.islnk():
                link_target = Path(member.linkname)
                if link_target.is_absolute() or ".." in link_target.parts:
                    raise CommandError(f"archive link escapes destination: {member.name}")
        archive.extractall(destination)

    def _install_wrappers(self, dry_run: bool) -> list[dict[str, Any]]:
        wrappers = [
            "bb-stack",
            "bb-claude",
            "bootstrap",
            "mail-otp",
            "mail-otp-config",
            "mail-otp-set-pass",
        ]
        results = []
        local_bin = self.paths.home / ".local" / "bin"
        if not dry_run:
            local_bin.mkdir(parents=True, exist_ok=True)
        for name in wrappers:
            source = self.paths.root / "00-L0-Runtime" / "bin" / name
            destination = local_bin / name
            if not dry_run:
                source.chmod(source.stat().st_mode | 0o755)
                if destination.is_symlink() and destination.resolve() == source.resolve():
                    state = "ready"
                elif destination.exists() or destination.is_symlink():
                    state = "conflict"
                else:
                    destination.symlink_to(source)
                    state = "installed"
            else:
                state = "planned"
            results.append(
                {"component": f"wrapper:{name}", "state": state, "path": str(destination)}
            )
        pentest = self.paths.runtime_bin / "pentest-python"
        content = (
            "#!/usr/bin/env sh\n"
            f'exec "{self.paths.venv / "bin" / "python"}" "$@"\n'
        )
        if not dry_run:
            atomic_write(pentest, content, 0o755)
        results.append(
            {"component": "wrapper:pentest-python", "state": "planned" if dry_run else "ready", "path": str(pentest)}
        )
        return results

    def _write_env(self, dry_run: bool) -> None:
        if dry_run:
            return
        config_env = self.paths.config_home / "config.env"
        if not config_env.exists():
            shutil.copy2(self.config / "env.example", config_env)
            config_env.chmod(0o600)
        else:
            self._migrate_config_env(config_env)
            config_env.chmod(0o600)
        _, invalid = load_machine_config(config_env)
        if invalid:
            raise ValidationError(
                "unsupported config.env assignments: " + ", ".join(invalid)
            )
        effective = ConfigurationManager(self.paths).effective()
        lines = [
            "# Generated by bb-stack. Source this file from your shell rc.",
            "# config.env was parsed as literal data; this file never sources it.",
            *(
                f"export {key}={shlex.quote(value)}"
                for key, value in effective.items()
            ),
        ]
        if self.paths.claude_config_explicit:
            lines.append(
                f"export CLAUDE_CONFIG_DIR={shlex.quote(str(self.paths.claude_config_dir))}",
            )
        else:
            lines.append("unset CLAUDE_CONFIG_DIR")
        lines.extend(
            [
                f"export BB_CONFIG_HOME={shlex.quote(str(self.paths.config_home))}",
                f"export BB_STACK_ROOT={shlex.quote(str(self.paths.root))}",
                f"export BB_WORK_ROOT={shlex.quote(str(self.paths.work_root))}",
                f"export PATH={shlex.quote(self.paths.runtime_path(effective['BB_EXTRA_PATH']))}",
                'case "${BB_PROXY_MODE:-direct}" in',
                "  mihomo)",
                '    export HTTP_PROXY="${BB_HTTP_PROXY:-http://127.0.0.1:7890}"',
                '    export HTTPS_PROXY="${BB_HTTP_PROXY:-http://127.0.0.1:7890}"',
                '    export ALL_PROXY="${BB_SOCKS_PROXY:-socks5://127.0.0.1:7891}"',
                "    unset http_proxy https_proxy all_proxy",
                "    ;;",
                "  direct) unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy ;;",
                '  *) printf "bb-stack: unknown BB_PROXY_MODE=%s\\n" "$BB_PROXY_MODE" >&2 ;;',
                "esac",
                "",
            ]
        )
        content = "\n".join(lines)
        atomic_write(self.paths.env_file, content, 0o600)

    def write_environment(self) -> Path:
        self.paths.ensure_runtime_dirs()
        self._write_env(False)
        return self.paths.env_file

    def _migrate_config_env(self, config_env: Path) -> None:
        content = config_env.read_text(encoding="utf-8")
        managed_paths = {
            "BB_STACK_ROOT",
            "BB_WORK_ROOT",
            "BB_CONFIG_HOME",
            "CLAUDE_CONFIG_DIR",
        }
        assignment = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=")
        kept: list[str] = []
        keys: set[str] = set()
        for line in content.splitlines():
            match = assignment.match(line)
            if match and match.group(1) in managed_paths:
                continue
            if match:
                keys.add(match.group(1))
            kept.append(line)
        example = (self.config / "env.example").read_text(encoding="utf-8")
        additions = []
        for line in example.splitlines():
            match = assignment.match(line)
            if match and match.group(1) not in keys:
                additions.append(line)
                keys.add(match.group(1))
        migrated = "\n".join(kept).strip() + "\n"
        if additions:
            migrated += "\n" + "\n".join(additions) + "\n"
        if migrated != content:
            backup = config_env.with_name("config.env.pre-path-migration")
            if not backup.exists():
                shutil.copy2(config_env, backup)
                backup.chmod(0o600)
            atomic_write(config_env, migrated, 0o600)

    def install_tools(
        self, profile: str, include_optional: bool, *, dry_run: bool
    ) -> list[dict[str, Any]]:
        document = load_yaml(self.config / "tools.yaml")
        validate(document, self.config / "tools.schema.json", "tool installer manifest")
        if profile not in document["profiles"]:
            raise ValidationError(f"unknown tool profile: {profile}")
        selected = list(document["profiles"][profile]["required"])
        if include_optional:
            selected.extend(document["profiles"][profile]["optional"])
        selected = list(dict.fromkeys(selected))
        env = self.paths.environment()
        if any(document["installers"][name]["kind"] == "go" for name in selected):
            self._ensure_toolchain("go")
        env["PATH"] = self.paths.runtime_path()
        env["GOBIN"] = str(self.paths.home / "go" / "bin")
        results: list[dict[str, Any]] = []
        apt_pending: list[str] = []
        apt_names: list[str] = []

        for name in selected:
            spec = document["installers"][name]
            expanded = expand(spec, env, strict=False)
            if self._tool_ready(expanded, env):
                results.append({"component": f"tool:{name}", "state": "ready"})
                continue
            kind = expanded["kind"]
            if kind == "apt":
                apt_pending.extend(expanded["packages"])
                apt_names.append(name)
                continue
            if dry_run:
                results.append({"component": f"tool:{name}", "state": "planned"})
                continue
            self._install_tool(name, expanded, env)
            if not self._tool_ready(expanded, env):
                raise CommandError(f"tool installer completed but check still fails: {name}")
            results.append({"component": f"tool:{name}", "state": "installed"})

        if apt_pending:
            if dry_run:
                results.extend(
                    {"component": f"tool:{name}", "state": "planned"} for name in apt_names
                )
            else:
                apt = shutil.which("apt-get", path=env["PATH"])
                if not apt:
                    raise CommandError("apt-get is unavailable; install system packages manually")
                prefix = [] if os.geteuid() == 0 else ["sudo"]
                self._run([*prefix, apt, "update"], env=env)
                self._run(
                    [*prefix, apt, "install", "-y", *sorted(set(apt_pending))], env=env
                )
                for name in apt_names:
                    spec = expand(document["installers"][name], env, strict=False)
                    if not self._tool_ready(spec, env):
                        raise CommandError(
                            f"apt completed but tool check still fails: {name}"
                        )
                    results.append({"component": f"tool:{name}", "state": "installed"})
        return results

    def _tool_ready(self, spec: dict[str, Any], env: dict[str, str]) -> bool:
        if spec["kind"] == "git-data":
            destination = Path(spec["destination"])
            if not (destination / ".git").is_dir():
                return False
            result = subprocess.run(
                ["git", "-C", str(destination), "rev-parse", "HEAD"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.stdout.strip() != spec["revision"]:
                return False
            sparse_paths = spec.get("sparse_paths", [])
            if sparse_paths:
                sparse = subprocess.run(
                    ["git", "-C", str(destination), "sparse-checkout", "list"],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                configured = {line.strip() for line in sparse.stdout.splitlines() if line.strip()}
                return sparse.returncode == 0 and configured == set(sparse_paths)
            return True
        if spec["kind"] == "service":
            try:
                with socket.create_connection((spec["host"], int(spec["port"])), timeout=0.4):
                    return True
            except OSError:
                return False
        commands_ready = all(shutil.which(item, path=env["PATH"]) for item in spec.get("checks", []))
        post_check = spec.get("post_check")
        return commands_ready and (not post_check or Path(post_check).exists())

    def _install_tool(self, name: str, spec: dict[str, Any], env: dict[str, str]) -> None:
        kind = spec["kind"]
        if kind == "go":
            go = shutil.which("go", path=env["PATH"])
            if not go:
                raise CommandError(f"Go is required to install {name}")
            self._run([go, "install", spec["package"]], env=env)
        elif kind == "pipx":
            pipx = shutil.which("pipx", path=env["PATH"])
            if not pipx:
                apt = shutil.which("apt-get", path=env["PATH"])
                if not apt:
                    raise CommandError(f"pipx is required to install {name}")
                prefix = [] if os.geteuid() == 0 else ["sudo"]
                self._run([*prefix, apt, "update"], env=env)
                self._run([*prefix, apt, "install", "-y", "pipx"], env=env)
                pipx = shutil.which("pipx", path=env["PATH"])
                if not pipx:
                    raise CommandError(f"pipx installation did not expose its command for {name}")
            self._run([pipx, "install", spec["package"]], env=env)
        elif kind == "git-data":
            destination = Path(spec["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise CommandError(f"non-managed data destination already exists: {destination}")
            clone = ["git", "clone", "--filter=blob:none"]
            if spec.get("sparse_paths"):
                clone.append("--no-checkout")
            clone.extend([spec["repository"], str(destination)])
            self._run(clone, env=env)
            if spec.get("sparse_paths"):
                self._run(
                    ["git", "-C", str(destination), "sparse-checkout", "set", *spec["sparse_paths"]],
                    env=env,
                )
            self._run(["git", "-C", str(destination), "checkout", spec["revision"]], env=env)
        elif kind == "archive-binary":
            if platform.system() != "Linux" or platform.machine() not in spec["files"]:
                raise CommandError(f"archive installer for {name} supports Linux x86_64/aarch64")
            file_spec = spec["files"][platform.machine()]
            cache = self.paths.runtime / "cache"
            cache.mkdir(parents=True, exist_ok=True)
            archive = cache / file_spec["archive"]
            if not archive.is_file() or self._sha256(archive) != file_spec["sha256"]:
                temporary = archive.with_suffix(archive.suffix + ".part")
                try:
                    with urlopen(file_spec["url"], timeout=120) as response, temporary.open("wb") as handle:
                        shutil.copyfileobj(response, handle)
                    if self._sha256(temporary) != file_spec["sha256"]:
                        raise CommandError(f"checksum mismatch for {file_spec['archive']}")
                    os.replace(temporary, archive)
                finally:
                    if temporary.exists():
                        temporary.unlink()
            with tempfile.TemporaryDirectory(prefix=f"{name}-extract-", dir=self.paths.runtime) as temporary_dir:
                temporary_path = Path(temporary_dir)
                with tarfile.open(archive) as handle:
                    self._safe_extract(handle, temporary_path)
                candidates = [
                    path for path in temporary_path.rglob(spec["binary"]) if path.is_file()
                ]
                if len(candidates) != 1:
                    raise CommandError(f"archive did not contain one {spec['binary']} binary")
                destination = self.paths.runtime_bin / spec["binary"]
                shutil.copy2(candidates[0], destination)
                destination.chmod(0o755)
        elif kind == "service":
            raise CommandError(f"service {name} is not running; configure it outside bootstrap")
        else:
            raise CommandError(f"unsupported installer kind for {name}: {kind}")
        if spec.get("post_install") and not Path(str(spec.get("post_check", ""))).exists():
            self._run(list(spec["post_install"]), env=env)

    def launch(
        self,
        profile_name: str,
        *,
        engagement: Path | None,
        platform: str | None,
        claude_args: list[str],
        dry_run: bool,
        include_high_context_mcp: bool = False,
    ) -> dict[str, Any]:
        if engagement is not None:
            engagement = self.paths.engagement(engagement)
            cwd = engagement
            artifact_root = engagement / "artifacts"
        else:
            cwd = Path.cwd().resolve()
            artifact_root = cwd / ".bb-stack" / "artifacts"
            artifact_root.mkdir(parents=True, exist_ok=True)
        render = ProfileRegistry(self.paths).render(
            profile_name, platform=platform, engagement=engagement
        )
        skill_registry = SkillRegistry(self.paths)
        required_skills = set(skill_registry.profile(render.skill_profile)["required"])
        missing_skills = [
            item["name"]
            for item in skill_registry.status(render.skill_profile, "claude")
            if item["name"] in required_skills
            and item["state"] in {"missing", "conflict"}
        ]
        if missing_skills:
            raise CommandError(
                "required Skills are not installed: "
                + ", ".join(sorted(missing_skills))
                + f"; run bb-stack skills install --profile {render.skill_profile} --required-only"
            )
        output_dir = Path(render.output_file).parent
        mcp_path = output_dir / "mcp.json"
        capability_registry = CapabilityRegistry(self.paths)
        capability_report = capability_registry.doctor(render.l5_profile, artifact_root)
        if not capability_report["ready"]:
            raise CommandError(
                "required capabilities are missing: "
                + ", ".join(capability_report["missing_required"])
                + f"; run bb-stack doctor --profile {render.l5_profile}"
            )
        mcp = capability_registry.render_mcp(
            render.l5_profile,
            mcp_path,
            artifact_root=artifact_root,
            include_high_context=include_high_context_mcp,
        )
        claude = os.environ.get("CLAUDE_BIN") or shutil.which(
            "claude", path=self.paths.runtime_path()
        )
        if not claude:
            raise CommandError("Claude Code CLI was not found")
        command = [claude]
        prompt_flag = (
            "--system-prompt-file"
            if render.prompt_mode == "replacement"
            else "--append-system-prompt-file"
        )
        command.extend([prompt_flag, render.output_file])
        if mcp["mcpServers"]:
            command.extend(["--mcp-config", str(mcp_path), "--strict-mcp-config"])
        command.extend(claude_args)
        result = {
            "schema_version": 1,
            "profile": profile_name,
            "prompt_mode": render.prompt_mode,
            "cwd": str(cwd),
            "command": command,
            "mcp_servers": sorted(mcp["mcpServers"]),
        }
        if dry_run:
            return result
        env = self.paths.environment(artifact_root)
        env["PATH"] = self.paths.runtime_path()
        os.chdir(cwd)
        os.execvpe(command[0], command, env)
        raise AssertionError("os.execvpe returned unexpectedly")

    def runtime_status(self) -> dict[str, Any]:
        commands = {}
        for name in ("python3", "node", "npm", "go", "git", "claude", "codex"):
            commands[name] = shutil.which(name, path=self.paths.runtime_path())
        return {
            "schema_version": 1,
            "paths": {
                "stack_root": str(self.paths.root),
                "work_root": str(self.paths.work_root),
                "config_home": str(self.paths.config_home),
                "runtime": str(self.paths.runtime),
            },
            "env_file": self.paths.env_file.is_file(),
            "venv": (self.paths.venv / "bin" / "python").is_file(),
            "node_modules": (self.paths.runtime / "node_modules").is_dir(),
            "commands": commands,
        }
