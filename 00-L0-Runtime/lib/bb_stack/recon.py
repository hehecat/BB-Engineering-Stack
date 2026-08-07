from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

from .data import DataManager
from .engagement import EngagementManager, PROTECTED_WORKFLOWS
from .errors import CommandError, ValidationError
from .io import atomic_write, dump_json, load_json, load_yaml
from .paths import StackPaths
from .validation import validate

BASELINE_STAGE_IDS = (
    "scope",
    "organization-assets",
    "passive-assets",
    "dns-active",
    "dns-resolution",
    "web-probe",
    "vhost-content",
    "network-services",
    "crawl-archives",
    "javascript-api",
    "cloud-source",
    "templates",
    "normalize",
    "coverage",
)
TERMINAL_STAGE_STATES = {"completed", "partial", "skipped"}
RECON_DIRS = (
    "inventory",
    "dns",
    "services",
    "urls",
    "javascript",
    "api",
    "cloud",
    "source",
    "findings",
    "leads",
    "logs",
    "branches",
)
CONTROL_BLOCK_START = "<!-- bb-recon:start -->"
CONTROL_BLOCK_END = "<!-- bb-recon:end -->"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ReconManager:
    def __init__(
        self,
        paths: StackPaths,
        *,
        data_manager: DataManager | None = None,
    ) -> None:
        self.paths = paths
        self.data_manager = data_manager or DataManager(paths)
        self.config_path = paths.root / "00-L0-Runtime" / "config" / "recon.yaml"
        self.schema_path = (
            paths.root / "00-L0-Runtime" / "config" / "recon.schema.json"
        )
        self.config = load_yaml(self.config_path)
        validate(self.config, self.schema_path, "recon pipeline")
        self._validate_pipeline()

    def required_providers(self) -> list[str]:
        return sorted(
            {
                provider
                for stage in self.config["stages"]
                for provider in stage["required_providers"]
            }
        )

    def run(self, engagement: Path, *, mode: str = "adaptive") -> dict[str, Any]:
        root, engagement_state = self._execution_gate(engagement)
        if mode not in {"baseline", "adaptive"}:
            raise ValidationError(f"unsupported recon mode: {mode}")
        self._ensure_layout(root)
        with self._lock(root):
            state = self._load_or_initialize(root, engagement_state, mode=mode)
            if state.get("closed_at"):
                raise ValidationError("recon is closed; start a new Engagement to run again")
            state["mode"] = mode
            state["state"] = "running"
            state["updated_at"] = _now()
            self._save(root, state)
            self._run_unfinished(root, engagement_state, state)
            return self._finalize(root, state)

    def resume(self, engagement: Path) -> dict[str, Any]:
        root, engagement_state = self._execution_gate(engagement)
        self._ensure_layout(root)
        with self._lock(root):
            state = self._load_or_initialize(root, engagement_state, mode="adaptive")
            if state.get("closed_at"):
                raise ValidationError("recon is closed and cannot be resumed")
            state["state"] = "running"
            state["updated_at"] = _now()
            self._save(root, state)
            self._run_unfinished(root, engagement_state, state)
            return self._finalize(root, state)

    def rerun(
        self,
        engagement: Path,
        *,
        stage_id: str,
        cascade: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        root, engagement_state = self._execution_gate(engagement)
        specs = {spec["id"]: spec for spec in self.config["stages"]}
        if stage_id not in specs:
            raise ValidationError(f"unknown recon stage: {stage_id}")
        self._ensure_layout(root)
        with self._lock(root):
            state = self._load_or_initialize(root, engagement_state, mode="adaptive")
            if state.get("closed_at"):
                raise ValidationError("recon is closed and cannot be rerun")
            current = state["stages"][stage_id]
            if current["state"] == "completed" and not force:
                raise ValidationError(
                    f"recon stage is completed; use --force to rerun: {stage_id}"
                )
            selected = {stage_id}
            if cascade:
                changed = True
                while changed:
                    changed = False
                    for spec in self.config["stages"]:
                        if spec["id"] in selected:
                            continue
                        if selected.intersection(spec["depends_on"]):
                            selected.add(spec["id"])
                            changed = True
            for selected_id in selected:
                stage = state["stages"][selected_id]
                stage["state"] = "pending"
                stage["started_at"] = None
                stage["completed_at"] = None
                stage["providers"] = {}
                stage["missing"] = []
                stage["errors"] = []
                stage["artifacts"] = []
            state["state"] = "running"
            state["updated_at"] = _now()
            self._save(root, state)
            self._run_unfinished(root, engagement_state, state)
            return self._finalize(root, state)

    def status(self, engagement: Path) -> dict[str, Any]:
        root = self.paths.engagement(engagement)
        engagement_state = EngagementManager(self.paths).validate(root)
        self._ensure_layout(root)
        state = self._load_or_initialize(root, engagement_state, mode="adaptive")
        self._refresh_summary(state)
        self._save(root, state)
        return state

    def expand(
        self,
        engagement: Path,
        *,
        area: str,
        target: str,
        reason: str,
        signal_id: str | None = None,
    ) -> dict[str, Any]:
        root, engagement_state = self._execution_gate(engagement)
        if area not in self.config["expansions"]:
            raise ValidationError(f"unsupported recon expansion area: {area}")
        target = self._validated_text(target, "expansion target")
        reason = self._validated_text(reason, "expansion reason")
        if not self._scope_matches(target, engagement_state["scope"]):
            raise ValidationError(
                f"expansion target is outside written scope: {target}"
            )
        self._ensure_layout(root)
        with self._lock(root):
            state = self._load_or_initialize(root, engagement_state, mode="adaptive")
            if state.get("closed_at"):
                raise ValidationError("recon is closed and cannot accept expansions")
            selected_signal = None
            if signal_id:
                selected_signal = next(
                    (item for item in state["signals"] if item["id"] == signal_id),
                    None,
                )
                if selected_signal is None:
                    raise ValidationError(f"unknown adaptive signal id: {signal_id}")
                if selected_signal["state"] != "open":
                    raise ValidationError(
                        f"adaptive signal is not open: {signal_id}"
                    )
                if selected_signal["area"] != area or selected_signal["value"] != target:
                    raise ValidationError(
                        f"expansion does not match adaptive signal: {signal_id}"
                    )
            branch_number = len(state["branches"]) + 1
            branch_id = f"B-{branch_number:03d}-{area}"
            branch_root = root / "recon" / "branches" / branch_id
            branch_root.mkdir(parents=True, exist_ok=False)
            providers = self.config["expansions"][area]
            branch: dict[str, Any] = {
                "id": branch_id,
                "area": area,
                "target": target,
                "reason": reason,
                "state": "running",
                "created_at": _now(),
                "completed_at": None,
                "providers": {},
                "artifacts": [],
            }
            for provider in providers:
                if not self._provider_available(provider):
                    branch["providers"][provider] = {
                        "state": "missing",
                        "error": "provider is not installed",
                    }
                    continue
                output = branch_root / f"{provider}{self._output_suffix(provider)}"
                log = root / "recon" / "logs" / f"{branch_id}.{provider}.log"
                command = self._provider_command(
                    provider, area, target, root / "recon", output
                )
                result = self._execute_provider(provider, command, output, log)
                provider_state = "completed" if result["returncode"] == 0 else "failed"
                branch["providers"][provider] = {
                    "state": provider_state,
                    "command": result["command"],
                    "error": result["error"],
                    "artifact": self._relative(root, output) if output.exists() else None,
                    "log": self._relative(root, log),
                }
                if output.exists():
                    branch["artifacts"].append(self._relative(root, output))
            completed = any(
                item["state"] == "completed" for item in branch["providers"].values()
            )
            branch["state"] = "completed" if completed else "blocked"
            branch["completed_at"] = _now() if completed else None
            dump_json(branch_root / "branch.json", branch)
            state["branches"].append(branch)
            if not completed:
                state["signals"].append(
                    {
                        "id": f"{branch_id}.provider-gap",
                        "type": "expansion-provider-gap",
                        "area": area,
                        "value": target,
                        "state": "open",
                        "source": self._relative(root, branch_root / "branch.json"),
                        "branch_id": branch_id,
                    }
                )
            elif selected_signal is not None:
                selected_signal["state"] = "expanded"
                selected_signal["branch_id"] = branch_id
            state["updated_at"] = _now()
            self._refresh_summary(state)
            self._save(root, state)
            self._sync_control_files(root, state)
            return branch

    def close(
        self,
        engagement: Path,
        *,
        reason: str,
        accept_gaps: list[str] | None = None,
        accept_signals: list[str] | None = None,
        accept_candidates: list[str] | None = None,
    ) -> dict[str, Any]:
        root, engagement_state = self._execution_gate(engagement)
        reason = self._validated_text(reason, "close reason")
        self._ensure_layout(root)
        with self._lock(root):
            state = self._load_or_initialize(root, engagement_state, mode="adaptive")
            unfinished = [
                stage_id
                for stage_id, stage in state["stages"].items()
                if stage["state"] not in TERMINAL_STAGE_STATES
            ]
            if unfinished:
                raise ValidationError(
                    "cannot close recon with unfinished baseline stages: "
                    + ", ".join(unfinished)
                )
            known_gaps = {gap["id"] for gap in state["coverage_gaps"]}
            accepted = set(accept_gaps or [])
            unknown = accepted - known_gaps
            if unknown:
                raise ValidationError(
                    "unknown coverage gap ids: " + ", ".join(sorted(unknown))
                )
            unaccepted = known_gaps - accepted
            if unaccepted:
                raise ValidationError(
                    "cannot close recon with unacknowledged coverage gaps: "
                    + ", ".join(sorted(unaccepted))
                )
            open_signals = {
                item["id"]
                for item in state["signals"]
                if item.get("state") == "open"
            }
            accepted_signals = set(accept_signals or [])
            unknown_signals = accepted_signals - open_signals
            if unknown_signals:
                raise ValidationError(
                    "unknown or non-open adaptive signal ids: "
                    + ", ".join(sorted(unknown_signals))
                )
            unaccepted_signals = open_signals - accepted_signals
            if unaccepted_signals:
                raise ValidationError(
                    "cannot close recon with open adaptive signals: "
                    + ", ".join(sorted(unaccepted_signals))
                )
            open_candidates = {
                item["id"]
                for item in state["scope_candidates"]
                if item.get("state") == "candidate"
            }
            accepted_candidates = set(accept_candidates or [])
            unknown_candidates = accepted_candidates - open_candidates
            if unknown_candidates:
                raise ValidationError(
                    "unknown or non-open scope candidate ids: "
                    + ", ".join(sorted(unknown_candidates))
                )
            unaccepted_candidates = open_candidates - accepted_candidates
            if unaccepted_candidates:
                raise ValidationError(
                    "cannot close recon with unresolved scope candidates: "
                    + ", ".join(sorted(unaccepted_candidates))
                )
            timestamp = _now()
            for gap in state["coverage_gaps"]:
                gap["accepted"] = gap["id"] in accepted
            for signal in state["signals"]:
                if signal["id"] in accepted_signals:
                    signal["state"] = "accepted"
                    signal["accepted_reason"] = reason
            for candidate in state["scope_candidates"]:
                if candidate["id"] in accepted_candidates:
                    candidate["state"] = "accepted"
                    candidate["accepted_reason"] = reason
            has_accepted_limits = bool(
                known_gaps or accepted_signals or accepted_candidates
            )
            state["state"] = "closed_with_gaps" if has_accepted_limits else "completed"
            state["close_reason"] = reason
            state["closed_at"] = timestamp
            state["updated_at"] = timestamp
            self._save(root, state)
            self._sync_control_files(root, state)
            return state

    def _run_unfinished(
        self,
        root: Path,
        engagement_state: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        targets = self._targets(engagement_state)
        for spec in self.config["stages"]:
            stage = state["stages"][spec["id"]]
            if stage["state"] in TERMINAL_STAGE_STATES:
                continue
            dependencies = [state["stages"][name]["state"] for name in spec["depends_on"]]
            if not all(item in TERMINAL_STAGE_STATES for item in dependencies):
                stage["state"] = "pending"
                continue
            self._run_stage(root, targets, engagement_state["scope"], spec, stage)
            state["scope_candidates"] = self._load_scope_candidates(root)
            if spec["id"] == "normalize" and stage["state"] in TERMINAL_STAGE_STATES:
                self._discover_signals(root, state)
            state["updated_at"] = _now()
            self._refresh_summary(state)
            self._save(root, state)

    def _run_stage(
        self,
        root: Path,
        targets: list[str],
        scope: dict[str, Any],
        spec: dict[str, Any],
        stage: dict[str, Any],
    ) -> None:
        stage["state"] = "running"
        stage["attempts"] += 1
        stage["started_at"] = _now()
        stage["completed_at"] = None
        stage["missing"] = []
        stage["errors"] = []
        stage["providers"] = {}
        stage["artifacts"] = []

        try:
            for requirement in spec["data"]:
                self.data_manager.ensure(
                    requirement["dataset"], list(requirement["bundles"])
                )
        except (CommandError, ValidationError, OSError) as error:
            stage["state"] = "blocked"
            stage["errors"].append(f"data: {error}")
            return

        required_missing = [
            provider
            for provider in spec["required_providers"]
            if not self._provider_available(provider)
        ]
        if required_missing:
            stage["state"] = "blocked"
            stage["missing"] = required_missing
            for provider in required_missing:
                stage["providers"][provider] = {
                    "state": "missing",
                    "required": True,
                    "error": "provider is not installed",
                }
            return

        self._prepare_stage_inputs(root / "recon", spec["id"], targets, scope)
        target = targets[0]
        providers = spec["required_providers"] + spec["optional_providers"]
        optional_gap = False
        required_failure = False
        for provider in providers:
            required = provider in spec["required_providers"]
            if not self._provider_available(provider):
                optional_gap = True
                stage["missing"].append(provider)
                stage["providers"][provider] = {
                    "state": "missing",
                    "required": required,
                    "error": "provider is not installed",
                }
                continue
            output = self._stage_output(root / "recon", spec, provider)
            log = root / "recon" / "logs" / f"{spec['id']}.{provider}.log"
            command = self._provider_command(
                provider, spec["id"], target, root / "recon", output
            )
            result = self._execute_provider(provider, command, output, log)
            provider_state = result.get(
                "state",
                "completed" if result["returncode"] == 0 else "failed",
            )
            succeeded = provider_state == "completed"
            usable_partial = (
                provider_state == "partial" and result.get("artifact_usable", False)
            )
            if not succeeded and not usable_partial:
                stage["errors"].append(f"{provider}: {result['error']}")
                if required:
                    required_failure = True
                else:
                    optional_gap = True
            elif usable_partial:
                stage["errors"].append(f"{provider}: {result['error']}")
                optional_gap = True
            stage["providers"][provider] = {
                "state": provider_state,
                "required": required,
                "command": result["command"],
                "error": result["error"],
                "artifact": self._relative(root, output) if output.exists() else None,
                "log": self._relative(root, log),
            }
            if result.get("artifact_usable", output.exists()) and output.exists():
                stage["artifacts"].append(self._relative(root, output))

        if required_failure:
            stage["state"] = "blocked"
            return
        self._finalize_stage_artifacts(
            root / "recon", spec["id"], stage, scope=scope, targets=targets
        )
        stage["state"] = "partial" if optional_gap else "completed"
        stage["completed_at"] = _now()

    def _execute_provider(
        self,
        provider: str,
        command: list[str],
        output: Path,
        log: Path,
    ) -> dict[str, Any]:
        output.parent.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        env = self.paths.environment(output.parent)
        env["PATH"] = self.paths.runtime_path()
        recon_root = self._recon_root(output)
        attempt = output.with_name(f".{output.name}.attempt.part")
        uses_attempt = str(output) in command
        execution_command = [
            str(attempt) if uses_attempt and item == str(output) else item
            for item in command
        ]
        if uses_attempt:
            attempt.unlink(missing_ok=True)
        try:
            completed = subprocess.run(
                execution_command,
                env=env,
                text=True,
                input=self._provider_stdin(provider, recon_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._provider_timeout(provider),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            atomic_write(log, f"{error.__class__.__name__}: {error}\n")
            if provider == "subfinder" and self._usable_line_output(attempt):
                os.replace(attempt, output)
                return {
                    "state": "partial",
                    "returncode": 1,
                    "artifact_usable": True,
                    "command": command,
                    "error_kind": "timeout",
                    "error": str(error),
                }
            attempt.unlink(missing_ok=True)
            return {
                "state": "failed",
                "returncode": 1,
                "artifact_usable": False,
                "command": command,
                "error_kind": "timeout",
                "error": str(error),
            }
        except OSError as error:
            attempt.unlink(missing_ok=True)
            atomic_write(log, f"{error.__class__.__name__}: {error}\n")
            return {
                "state": "failed",
                "returncode": 1,
                "artifact_usable": False,
                "command": command,
                "error_kind": "execution",
                "error": str(error),
            }
        atomic_write(
            log,
            f"command: {shlex.join(command)}\n"
            f"exit_code: {completed.returncode}\n\n"
            f"{completed.stderr}",
        )
        if completed.returncode == 0 and provider == "bbot":
            output.unlink(missing_ok=True)
            if not self._archive_bbot_output(command, output):
                error = "BBOT did not create output.json"
                atomic_write(log, f"{log.read_text(encoding='utf-8')}error: {error}\n")
                return {
                    "state": "failed",
                    "returncode": 1,
                    "artifact_usable": False,
                    "command": command,
                    "error": error,
                }
        if completed.returncode == 0:
            if uses_attempt and attempt.exists():
                os.replace(attempt, output)
            elif uses_attempt:
                atomic_write(output, completed.stdout)
            elif provider != "bbot":
                atomic_write(output, completed.stdout)
        else:
            attempt.unlink(missing_ok=True)
        error = completed.stderr.strip() or None
        return {
            "state": "completed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "artifact_usable": completed.returncode == 0 and output.exists(),
            "command": command,
            "error": error,
        }

    @staticmethod
    def _usable_line_output(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return False
        atomic_write(path, "\n".join(lines) + "\n")
        return True

    @staticmethod
    def _archive_bbot_output(command: list[str], output: Path) -> bool:
        """Move BBOT's scan-directory JSON artifact into the stage contract."""
        try:
            output_dir = Path(command[command.index("--output-dir") + 1])
            scan_name = command[command.index("--name") + 1]
        except (ValueError, IndexError):
            return False
        generated = output_dir / scan_name / "output.json"
        if generated.is_file():
            atomic_write(output, generated.read_text(encoding="utf-8"))
            return True
        return False

    def _provider_command(
        self,
        provider: str,
        stage: str,
        target: str,
        recon_root: Path,
        output: Path,
    ) -> list[str]:
        host = self._target_host(target)
        base_url = target if target.startswith(("http://", "https://")) else f"https://{host}"
        candidates = recon_root / "dns" / "candidates.txt"
        live_urls = recon_root / "services" / "live-urls.txt"
        scope_hosts = recon_root / "inventory" / "scope-hosts.txt"
        seclists = self.paths.data_root / "seclists"
        limits = self.config["limits"]
        bbot_targets = sorted(self._read_lines([scope_hosts])) or [host]
        scope_host_arg = ",".join(bbot_targets)
        bbot_flags = (
            ["cloud-enum", "code-enum"]
            if stage in {"cloud-source", "cloud", "source"}
            else ["subdomain-enum"]
        )
        commands: dict[str, list[str]] = {
            "subfinder": [
                "subfinder",
                "-dL",
                str(scope_hosts),
                "-rl",
                str(limits["dns_requests_per_second"]),
                "-silent",
                "-o",
                str(output),
            ],
            "assetfinder": ["assetfinder", "--subs-only", host],
            "amass": [
                "amass",
                "enum",
                "-passive",
                "-df",
                str(scope_hosts),
                "-o",
                str(output),
            ],
            "bbot": [
                "bbot",
                "-t",
                *bbot_targets,
                "-f",
                *bbot_flags,
                "-rf",
                "passive",
                "-om",
                "json",
                "-eom",
                "csv",
                "txt",
                "--output-dir",
                str(output.parent / ".bbot"),
                "--name",
                output.stem,
                "-c",
                f"web.http_rate_limit={limits['http_requests_per_second']}",
                "-y",
            ],
            "asnmap": ["asnmap", "-d", scope_host_arg, "-json", "-silent"],
            "alterx": [
                "alterx",
                "-l",
                str(recon_root / "inventory/subdomains.txt"),
                "-silent",
                "-o",
                str(output),
            ],
            "puredns": [
                "puredns",
                "bruteforce",
                str(seclists / "Discovery/DNS/subdomains-top1million-20000.txt"),
                "-d",
                str(scope_hosts),
                "--rate-limit",
                str(limits["dns_requests_per_second"]),
                "--write",
                str(output),
            ],
            "dnsx": (
                [
                    "dnsx",
                    "-d",
                    str(scope_hosts),
                    "-w",
                    str(seclists / "Discovery/DNS/subdomains-top1million-20000.txt"),
                    "-silent",
                    "-json",
                    "-auto-wildcard",
                    "-rl",
                    str(limits["dns_requests_per_second"]),
                    "-o",
                    str(output),
                ]
                if stage == "dns-active"
                else [
                    "dnsx",
                    "-l",
                    str(candidates),
                    "-a",
                    "-aaaa",
                    "-cname",
                    "-json",
                    "-silent",
                    "-rl",
                    str(limits["dns_requests_per_second"]),
                    "-o",
                    str(output),
                ]
            ),
            "httpx": [
                "httpx",
                "-l",
                str(candidates),
                "-status-code",
                "-title",
                "-tech-detect",
                "-json",
                "-silent",
                "-rl",
                str(limits["http_requests_per_second"]),
                "-o",
                str(output),
            ],
            "ffuf": [
                "ffuf",
                "-u",
                base_url.rstrip("/") + "/FUZZ",
                "-w",
                str(seclists / "Discovery/Web-Content/common.txt"),
                "-ac",
                "-mc",
                "200,201,204,301,302,307,401,403",
                "-t",
                "20",
                "-rate",
                str(limits["fuzz_requests_per_second"]),
                "-maxtime",
                str(limits["stage_timeout_seconds"]),
                "-noninteractive",
                "-of",
                "json",
                "-o",
                str(output),
            ],
            "naabu": [
                "naabu",
                "-list",
                str(candidates),
                "-rate",
                str(limits["network_packets_per_second"]),
                "-silent",
                "-json",
                "-o",
                str(output),
            ],
            "nmap": [
                "nmap",
                "-sV",
                "--top-ports",
                "100",
                "--max-rate",
                str(limits["network_packets_per_second"]),
                "--host-timeout",
                "10m",
                "-iL",
                str(candidates),
                "-oX",
                str(output),
            ],
            "katana": [
                "katana",
                "-list",
                str(live_urls),
                "-depth",
                "3",
                "-rate-limit",
                str(limits["http_requests_per_second"]),
                "-js-crawl",
                "-known-files",
                "all",
                "-field-scope",
                "rdn",
                "-jsonl",
                "-silent",
                "-o",
                str(output),
            ],
            "gau": ["gau", "--subs", "--threads", "5"],
            "waybackurls": ["waybackurls"],
            "jsluice": ["jsluice", "urls"],
            "arjun": [
                "arjun",
                "-i",
                str(live_urls),
                "-oJ",
                str(output),
                "--rate-limit",
                str(limits["fuzz_requests_per_second"]),
                "--stable",
                "-q",
            ],
            "trufflehog": (
                ["trufflehog", "git", "--json", "--no-update", target]
                if stage == "source"
                else [
                    "trufflehog",
                    "filesystem",
                    "--json",
                    "--no-update",
                    str(recon_root / "source"),
                ]
            ),
            "nuclei": [
                "nuclei",
                "-l",
                str(live_urls),
                "-severity",
                "critical,high,medium",
                "-rate-limit",
                str(limits["http_requests_per_second"]),
                "-jsonl",
                "-silent",
                "-o",
                str(output),
            ],
        }
        if provider not in commands:
            raise ValidationError(f"no recon command adapter for provider: {provider}")
        return commands[provider]

    def _provider_stdin(self, provider: str, recon_root: Path) -> str | None:
        if provider in {"gau", "waybackurls"}:
            return "".join(
                f"{value}\n"
                for value in sorted(
                    self._read_lines([recon_root / "inventory" / "scope-hosts.txt"])
                )
            )
        if provider == "jsluice":
            values = {
                value
                for value in self._read_lines([recon_root / "urls" / "urls.txt"])
                if re.search(r"\.js(?:[?#]|$)", value, flags=re.IGNORECASE)
            }
            return "".join(f"{value}\n" for value in sorted(values))
        return None

    @staticmethod
    def _recon_root(output: Path) -> Path:
        for parent in output.parents:
            if parent.name == "recon":
                return parent
        raise ValidationError(f"provider output is outside a recon directory: {output}")

    def _prepare_stage_inputs(
        self,
        recon_root: Path,
        stage: str,
        targets: list[str],
        scope: dict[str, Any],
    ) -> None:
        scope_hosts = {
            host
            for target in targets
            if (host := self._target_host(target))
        }
        scope_urls = {
            target
            for target in targets
            if target.startswith(("http://", "https://"))
        }
        if stage == "scope":
            self._write_lines(recon_root / "inventory" / "scope-targets.txt", set(targets))
            self._write_lines(recon_root / "inventory" / "scope-hosts.txt", scope_hosts)
            self._write_lines(recon_root / "inventory" / "scope-urls.txt", scope_urls)
        if stage in {"dns-active", "dns-resolution", "web-probe", "network-services"}:
            sources = [recon_root / "inventory" / "subdomains.txt"]
            if stage != "dns-active":
                sources.append(recon_root / "dns" / "active.txt")
            values = self._read_asset_values(sources)
            values.update(scope_hosts)
            values = {value for value in values if self._scope_matches(value, scope)}
            self._write_lines(recon_root / "dns" / "candidates.txt", values)
        if stage in {"crawl-archives", "javascript-api", "templates"}:
            live = recon_root / "services" / "live-urls.txt"
            if not live.exists():
                fallback_urls = scope_urls or {f"https://{host}" for host in scope_hosts}
                self._write_lines(live, fallback_urls)

    def _finalize_stage_artifacts(
        self,
        recon_root: Path,
        stage_id: str,
        stage: dict[str, Any],
        *,
        scope: dict[str, Any],
        targets: list[str],
    ) -> None:
        outputs = [
            Path(artifact) if Path(artifact).is_absolute() else recon_root.parent / artifact
            for artifact in stage["artifacts"]
        ]
        if stage_id == "passive-assets":
            discovered = self._read_asset_values(outputs)
            in_scope = self._partition_discoveries(
                recon_root, discovered, scope, source="passive-assets"
            )
            self._write_lines(
                recon_root / "inventory" / "subdomains.txt",
                in_scope,
            )
        elif stage_id == "dns-active":
            discovered = self._read_asset_values(outputs)
            in_scope = self._partition_discoveries(
                recon_root, discovered, scope, source="dns-active"
            )
            self._write_lines(
                recon_root / "dns" / "active.txt", in_scope
            )
        elif stage_id == "web-probe":
            urls: set[str] = set()
            for path in outputs:
                for item in self._read_json_lines(path):
                    url = item.get("url")
                    if isinstance(url, str):
                        urls.add(url)
            urls = self._partition_discoveries(
                recon_root, urls, scope, source="web-probe"
            )
            self._write_lines(recon_root / "services" / "live-urls.txt", urls)
        elif stage_id == "crawl-archives":
            urls = set()
            for path in outputs:
                if path.suffix == ".jsonl":
                    for item in self._read_json_lines(path):
                        value = item.get("url") or item.get("request", {}).get("endpoint")
                        if isinstance(value, str):
                            urls.add(value)
                else:
                    urls.update(self._read_lines([path]))
            urls = self._partition_discoveries(
                recon_root, urls, scope, source="crawl-archives"
            )
            self._write_lines(recon_root / "urls" / "urls.txt", urls)

    def _partition_discoveries(
        self,
        recon_root: Path,
        values: set[str],
        scope: dict[str, Any],
        *,
        source: str,
    ) -> set[str]:
        accepted: set[str] = set()
        candidates_path = recon_root / "inventory" / "candidates.jsonl"
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        for item in self._read_json_lines(candidates_path):
            value = item.get("value")
            item_source = item.get("source")
            if isinstance(value, str) and isinstance(item_source, str):
                candidates[(value, item_source)] = item
        for value in sorted(values):
            normalized = self._discovery_value(value)
            if not normalized:
                continue
            if self._scope_matches(normalized, scope):
                accepted.add(normalized)
                continue
            key = (normalized, source)
            candidates[key] = {
                "value": normalized,
                "kind": "url" if self._is_url(normalized) else "host",
                "scope_state": "candidate",
                "source": source,
            }
        content = "".join(
            json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n"
            for _, item in sorted(candidates.items())
        )
        atomic_write(candidates_path, content)
        return accepted

    def _discover_signals(self, root: Path, state: dict[str, Any]) -> None:
        recon_root = root / "recon"
        sources = [
            recon_root / "services" / "live-urls.txt",
            recon_root / "urls" / "urls.txt",
            *sorted((recon_root / "javascript").glob("*")),
            *sorted((recon_root / "api").glob("*")),
            *sorted((recon_root / "cloud").glob("*")),
        ]
        found: dict[tuple[str, str], dict[str, str]] = {}
        for path in sources:
            if not path.is_file():
                continue
            values = self._read_asset_values([path])
            for value in values:
                signal = self._signal_for(value)
                if signal:
                    signal_type, area = signal
                    found[(signal_type, value)] = {
                        "type": signal_type,
                        "area": area,
                        "value": value,
                        "source": self._relative(root, path),
                    }
        previous = {
            (item.get("type"), item.get("value")): item
            for item in state.get("signals", [])
            if item.get("type") and item.get("value")
        }
        signals: list[dict[str, Any]] = []
        for index, key in enumerate(sorted(found), start=1):
            item: dict[str, Any] = {
                "id": f"S-{index:03d}",
                **found[key],
                "state": "open",
            }
            old = previous.get(key)
            if old:
                item["state"] = old.get("state", "open")
                if old.get("branch_id"):
                    item["branch_id"] = old["branch_id"]
                if old.get("accepted_reason"):
                    item["accepted_reason"] = old["accepted_reason"]
            signals.append(item)
        state["signals"] = signals

    @staticmethod
    def _signal_for(value: str) -> tuple[str, str] | None:
        lowered = value.lower()
        if lowered.startswith(("ws://", "wss://")):
            return "websocket", "api"
        if re.search(r"(?:^|[/_.-])graphql(?:[/?#]|$)", lowered):
            return "graphql-endpoint", "graphql"
        if re.search(r"/(?:openapi|swagger)(?:[.-][^/?#]+)?\.(?:json|ya?ml)(?:[?#]|$)", lowered):
            return "api-schema", "api"
        if re.search(r"\.js\.map(?:[?#]|$)", lowered):
            return "source-map", "javascript"
        if re.search(r"\.js(?:[?#]|$)", lowered):
            return "javascript-bundle", "javascript"
        if any(
            marker in lowered
            for marker in (
                ".s3.amazonaws.com",
                "storage.googleapis.com/",
                ".blob.core.windows.net/",
            )
        ):
            return "cloud-identifier", "cloud"
        return None

    def _load_or_initialize(
        self,
        root: Path,
        engagement_state: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        path = root / "recon" / "state.json"
        if path.is_file():
            legacy = load_json(path)
            if not self._state_needs_migration(legacy):
                return legacy
            return self._migrate_state(root, legacy, engagement_state, mode)
        timestamp = _now()
        stages = self._new_stages()
        state: dict[str, Any] = {
            "schema_version": 1,
            "engagement": engagement_state["slug"],
            "mode": mode,
            "state": "pending",
            "created_at": timestamp,
            "updated_at": timestamp,
            "closed_at": None,
            "close_reason": None,
            "stages": stages,
            "branches": [],
            "signals": [],
            "scope_candidates": [],
            "coverage_gaps": [],
            "recommended_actions": [],
        }
        self._save(root, state)
        self._sync_control_files(root, state)
        return state

    @staticmethod
    def _state_needs_migration(state: dict[str, Any]) -> bool:
        required = {
            "schema_version", "engagement", "mode", "state", "created_at",
            "updated_at", "closed_at", "close_reason", "stages", "branches",
            "signals", "scope_candidates", "coverage_gaps", "recommended_actions",
        }
        if state.get("schema_version") != 1 or not required.issubset(state):
            return True
        stages = state.get("stages")
        if not isinstance(stages, dict) or any(
            stage_id not in stages for stage_id in BASELINE_STAGE_IDS
        ):
            return True
        for signal in state.get("signals", []):
            if not isinstance(signal, dict) or not {
                "id", "type", "area", "value", "state", "source"
            }.issubset(signal):
                return True
        return False

    def _new_stages(self) -> dict[str, dict[str, Any]]:
        return {
            spec["id"]: {
                "state": "pending",
                "depends_on": list(spec["depends_on"]),
                "required_providers": list(spec["required_providers"]),
                "optional_providers": list(spec["optional_providers"]),
                "attempts": 0,
                "started_at": None,
                "completed_at": None,
                "providers": {},
                "missing": [],
                "errors": [],
                "artifacts": [],
            }
            for spec in self.config["stages"]
        }

    def _migrate_state(
        self,
        root: Path,
        legacy: dict[str, Any],
        engagement_state: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        """Normalize state written by older recon executors to the current contract."""
        timestamp = _now()
        state: dict[str, Any] = {
            "schema_version": 1,
            "engagement": str(legacy.get("engagement") or engagement_state["slug"]),
            "mode": legacy.get("mode") if legacy.get("mode") in {"baseline", "adaptive"} else mode,
            "state": legacy.get("state") if legacy.get("state") in {
                "pending", "running", "blocked", "needs_agent_decision",
                "baseline_completed", "completed", "closed_with_gaps",
            } else "pending",
            "created_at": legacy.get("created_at") or timestamp,
            "updated_at": legacy.get("updated_at") or timestamp,
            "closed_at": legacy.get("closed_at"),
            "close_reason": legacy.get("close_reason"),
            "stages": {},
            "branches": legacy.get("branches") if isinstance(legacy.get("branches"), list) else [],
            "signals": [],
            "scope_candidates": [],
            "coverage_gaps": [],
            "recommended_actions": [],
        }
        old_stages = legacy.get("stages") if isinstance(legacy.get("stages"), dict) else {}
        for spec in self.config["stages"]:
            old = old_stages.get(spec["id"])
            if not isinstance(old, dict):
                state["stages"][spec["id"]] = self._new_stages()[spec["id"]]
                continue
            current = self._new_stages()[spec["id"]]
            if old.get("state") in {"pending", "running", "completed", "partial", "blocked", "skipped"}:
                current["state"] = old["state"]
            current["attempts"] = old.get("attempts", 0) if isinstance(old.get("attempts", 0), int) and old.get("attempts", 0) >= 0 else 0
            current["started_at"] = old.get("started_at")
            current["completed_at"] = old.get("completed_at")
            current["missing"] = [item for item in old.get("missing", []) if isinstance(item, str)]
            current["errors"] = [item for item in old.get("errors", []) if isinstance(item, str)]
            current["artifacts"] = [item for item in old.get("artifacts", []) if isinstance(item, str)]
            providers = old.get("providers") if isinstance(old.get("providers"), dict) else {}
            for provider, detail in providers.items():
                if not isinstance(provider, str) or not isinstance(detail, dict):
                    continue
                provider_state = detail.get("state")
                if provider_state not in {"missing", "completed", "partial", "failed"}:
                    provider_state = "failed"
                item: dict[str, Any] = {
                    "state": provider_state,
                    "error": detail.get("error") if isinstance(detail.get("error"), (str, type(None))) else str(detail.get("error")),
                }
                if isinstance(detail.get("required"), bool):
                    item["required"] = detail["required"]
                if isinstance(detail.get("command"), list) and all(isinstance(value, str) for value in detail["command"]):
                    item["command"] = detail["command"]
                if "artifact" in detail and isinstance(detail.get("artifact"), (str, type(None))):
                    item["artifact"] = detail.get("artifact")
                if isinstance(detail.get("log"), str):
                    item["log"] = detail["log"]
                current["providers"][provider] = item
            state["stages"][spec["id"]] = current

        for index, signal in enumerate(legacy.get("signals", []), start=1):
            if not isinstance(signal, dict):
                continue
            value = signal.get("value", signal.get("target"))
            signal_type = signal.get("type", signal.get("kind"))
            if not isinstance(value, str) or not value or not isinstance(signal_type, str) or not signal_type:
                continue
            state["signals"].append({
                "id": str(signal.get("id") or f"S-{index:03d}"),
                "type": signal_type,
                "area": str(signal.get("area") or "web"),
                "value": value,
                "state": signal.get("state") if signal.get("state") in {"open", "expanded", "accepted"} else "open",
                "source": str(signal.get("source") or "recon/state.json"),
            })
        candidates = legacy.get("scope_candidates", [])
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("value"), str):
                    continue
                value = candidate["value"]
                source = str(candidate.get("source") or "recon/inventory/candidates.jsonl")
                digest = hashlib.sha256(f"{value}\0{source}".encode()).hexdigest()[:12]
                state["scope_candidates"].append({
                    "id": str(candidate.get("id") or f"C-{digest}"),
                    "value": value,
                    "kind": candidate.get("kind") if candidate.get("kind") in {"host", "url", "other"} else ("url" if self._is_url(value) else "host"),
                    "state": candidate.get("state") if candidate.get("state") in {"candidate", "accepted"} else "candidate",
                    "source": source,
                })
        for gap in legacy.get("coverage_gaps", []):
            if not isinstance(gap, dict) or not all(isinstance(gap.get(key), str) for key in ("id", "stage", "provider")):
                continue
            state["coverage_gaps"].append({
                "id": gap["id"],
                "stage": gap["stage"],
                "provider": gap["provider"],
                "impact": str(gap.get("impact") or "optional enrichment was not completed"),
                "accepted": bool(gap.get("accepted", False)),
            })
        actions = legacy.get("recommended_actions", [])
        if isinstance(actions, list):
            state["recommended_actions"] = [
                {"action": item["action"], "reason": item["reason"], **{
                    key: value for key, value in item.items() if key not in {"action", "reason"}
                }}
                for item in actions
                if isinstance(item, dict) and isinstance(item.get("action"), str) and isinstance(item.get("reason"), str)
            ]
        return state

    def _refresh_summary(self, state: dict[str, Any]) -> None:
        gaps: list[dict[str, Any]] = []
        for stage_id, stage in state["stages"].items():
            for provider, detail in stage["providers"].items():
                partial = detail["state"] == "partial"
                if not partial and (
                    detail["state"] not in {"missing", "failed"}
                    or detail.get("required")
                ):
                    continue
                gaps.append(
                    {
                        "id": f"{stage_id}.{provider}",
                        "stage": stage_id,
                        "provider": provider,
                        "impact": (
                            "provider returned usable but incomplete output"
                            if partial
                            else "optional enrichment was not completed"
                        ),
                        "accepted": False,
                    }
                )
        previous_acceptance = {
            item["id"]: item.get("accepted", False)
            for item in state.get("coverage_gaps", [])
        }
        for gap in gaps:
            gap["accepted"] = previous_acceptance.get(gap["id"], False)
        state["coverage_gaps"] = gaps
        install_actions: dict[str, dict[str, Any]] = {}
        for gap in gaps:
            if self._provider_available(gap["provider"]):
                continue
            install_actions[gap["provider"]] = {
                "action": "install-provider",
                "provider": gap["provider"],
                "stage": gap["stage"],
                "stages": [gap["stage"]],
                "required": False,
                "command": ["bb-stack", "tool", "install", gap["provider"]],
                "reason": gap["impact"],
            }
        for spec in self.config["stages"]:
            stage_id = spec["id"]
            if state["stages"][stage_id]["state"] in TERMINAL_STAGE_STATES:
                continue
            required_providers = set(spec["required_providers"])
            for provider in spec["required_providers"] + spec["optional_providers"]:
                if self._provider_available(provider):
                    continue
                required = provider in required_providers
                action = install_actions.setdefault(
                    provider,
                    {
                        "action": "install-provider",
                        "provider": provider,
                        "stage": stage_id,
                        "stages": [],
                        "required": required,
                        "command": ["bb-stack", "tool", "install", provider],
                        "reason": (
                            "required provider is not installed"
                            if required
                            else "optional provider is not installed"
                        ),
                    },
                )
                if stage_id not in action["stages"]:
                    action["stages"].append(stage_id)
                if required:
                    action["required"] = True
                    action["reason"] = "required provider is not installed"
        state["recommended_actions"] = [
            install_actions[provider] for provider in sorted(install_actions)
        ]
        state["recommended_actions"].extend(
            {
                "action": "rerun-stage",
                "provider": provider,
                "stage": stage_id,
                "command": [
                    "bb-stack",
                    "recon",
                    "rerun",
                    state["engagement"],
                    "--stage",
                    stage_id,
                    "--cascade",
                ],
                "reason": "provider execution did not complete",
            }
            for stage_id, stage in state["stages"].items()
            for provider, detail in stage["providers"].items()
            if detail["state"] in {"partial", "failed"}
            and self._provider_available(provider)
        )
        state["recommended_actions"].extend(
            {
                "action": "expand",
                "signal": signal["id"],
                "area": signal["area"],
                "target": signal["value"],
                "reason": f"Investigate {signal['type']} signal",
            }
            for signal in state.get("signals", [])
            if signal.get("state") == "open"
        )
        state["recommended_actions"].extend(
            {
                "action": "review-scope-candidate",
                "candidate": candidate["id"],
                "target": candidate["value"],
                "reason": "Discovery is inert until the written scope is revised",
            }
            for candidate in state.get("scope_candidates", [])
            if candidate.get("state") == "candidate"
        )
        blocked = any(stage["state"] == "blocked" for stage in state["stages"].values())
        unfinished = any(
            stage["state"] not in TERMINAL_STAGE_STATES
            for stage in state["stages"].values()
        )
        if state.get("closed_at"):
            return
        if blocked:
            state["state"] = "blocked"
        elif unfinished:
            state["state"] = "running"
        elif (
            gaps
            or any(item.get("state") == "open" for item in state["signals"])
            or any(
                item.get("state") == "candidate"
                for item in state.get("scope_candidates", [])
            )
        ):
            state["state"] = "needs_agent_decision"
        else:
            state["state"] = "baseline_completed"

    def _finalize(self, root: Path, state: dict[str, Any]) -> dict[str, Any]:
        self._refresh_summary(state)
        state["updated_at"] = _now()
        self._save(root, state)
        self._sync_control_files(root, state)
        return state

    def _execution_gate(
        self, engagement: Path
    ) -> tuple[Path, dict[str, Any]]:
        root = self.paths.engagement(engagement)
        state = EngagementManager(self.paths).validate(root)
        if state["workflow"] not in PROTECTED_WORKFLOWS:
            raise ValidationError("recon execution requires a protected workflow")
        if state["lifecycle"] != "active":
            raise ValidationError(
                f"recon execution requires active lifecycle; lifecycle is {state['lifecycle']}"
            )
        if state["authorization"]["status"] != "verified":
            raise ValidationError("recon execution requires verified authorization")
        return root, state

    def _validate_pipeline(self) -> None:
        ids = [stage["id"] for stage in self.config["stages"]]
        if tuple(ids) != BASELINE_STAGE_IDS:
            raise ValidationError("recon stage order does not match the baseline contract")
        if len(ids) != len(set(ids)):
            raise ValidationError("recon pipeline contains duplicate stage ids")
        seen: set[str] = set()
        for stage in self.config["stages"]:
            unknown = set(stage["depends_on"]) - seen
            if unknown:
                raise ValidationError(
                    f"recon stage {stage['id']} has forward or unknown dependencies: "
                    + ", ".join(sorted(unknown))
                )
            overlap = set(stage["required_providers"]) & set(
                stage["optional_providers"]
            )
            if overlap:
                raise ValidationError(
                    f"recon stage {stage['id']} repeats providers: "
                    + ", ".join(sorted(overlap))
                )
            seen.add(stage["id"])

    def _provider_available(self, provider: str) -> bool:
        if provider == "puredns":
            return bool(
                shutil.which("puredns", path=self.paths.runtime_path())
                and shutil.which("massdns", path=self.paths.runtime_path())
            )
        return bool(shutil.which(provider, path=self.paths.runtime_path()))

    def _provider_timeout(self, provider: str) -> int:
        return int(self.config["limits"]["stage_timeout_seconds"])

    def _stage_output(
        self, recon_root: Path, spec: dict[str, Any], provider: str
    ) -> Path:
        return (
            recon_root
            / spec["artifact_dir"]
            / f"{spec['id']}.{provider}{self._output_suffix(provider)}"
        )

    @staticmethod
    def _output_suffix(provider: str) -> str:
        if provider in {
            "bbot",
            "dnsx",
            "httpx",
            "jsluice",
            "katana",
            "naabu",
            "nuclei",
            "trufflehog",
        }:
            return ".jsonl"
        if provider == "ffuf" or provider == "arjun" or provider == "asnmap":
            return ".json"
        if provider == "nmap":
            return ".xml"
        return ".txt"

    def _save(self, root: Path, state: dict[str, Any]) -> None:
        validate(
            state,
            self.paths.root
            / "03-L3-Engagement-State"
            / "schema"
            / "recon-state.schema.json",
            "recon state",
        )
        dump_json(root / "recon" / "state.json", state)
        coverage = {
            "schema_version": 1,
            "engagement": state["engagement"],
            "state": state["state"],
            "updated_at": state["updated_at"],
            "stages": {
                stage_id: {
                    "state": stage["state"],
                    "missing": stage["missing"],
                    "errors": stage["errors"],
                    "artifacts": stage["artifacts"],
                }
                for stage_id, stage in state["stages"].items()
            },
            "coverage_gaps": state["coverage_gaps"],
            "signals": state["signals"],
            "scope_candidates": state["scope_candidates"],
            "recommended_actions": state["recommended_actions"],
        }
        dump_json(root / "recon" / "coverage.json", coverage)

    def _sync_control_files(self, root: Path, state: dict[str, Any]) -> None:
        completed = sum(
            stage["state"] in TERMINAL_STAGE_STATES
            for stage in state["stages"].values()
        )
        total = len(state["stages"])
        gaps = len(state["coverage_gaps"])
        signals = len(state["signals"])
        candidates = sum(
            item.get("state") == "candidate"
            for item in state.get("scope_candidates", [])
        )
        block = (
            f"{CONTROL_BLOCK_START}\n"
            "## Recon Coverage\n\n"
            f"- State: `{state['state']}`\n"
            f"- Baseline stages: {completed}/{total}\n"
            f"- Coverage gaps: {gaps}\n"
            f"- Adaptive signals: {signals}\n"
            f"- Scope candidates: {candidates}\n"
            "- Contract: `recon/coverage.json`\n"
            f"{CONTROL_BLOCK_END}"
        )
        self._replace_control_block(root / "STATUS.md", block)
        handoff_block = block.replace("## Recon Coverage", "## Recon coverage")
        self._replace_control_block(root / "SESSION-HANDOFF.md", handoff_block)

    @staticmethod
    def _replace_control_block(path: Path, block: str) -> None:
        content = path.read_text(encoding="utf-8")
        pattern = re.compile(
            re.escape(CONTROL_BLOCK_START)
            + r".*?"
            + re.escape(CONTROL_BLOCK_END),
            flags=re.DOTALL,
        )
        if pattern.search(content):
            updated = pattern.sub(block, content, count=1)
        else:
            updated = content.rstrip() + "\n\n" + block + "\n"
        atomic_write(path, updated)

    def _ensure_layout(self, root: Path) -> None:
        recon = root / "recon"
        recon.mkdir(parents=True, exist_ok=True)
        for relative in RECON_DIRS:
            (recon / relative).mkdir(parents=True, exist_ok=True)

    def _load_scope_candidates(self, root: Path) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self._read_json_lines(
            root / "recon" / "inventory" / "candidates.jsonl"
        ):
            value = item.get("value")
            source = item.get("source")
            if not isinstance(value, str) or not isinstance(source, str):
                continue
            digest = hashlib.sha256(f"{value}\0{source}".encode()).hexdigest()[:12]
            result.append(
                {
                    "id": f"C-{digest}",
                    "value": value,
                    "kind": item.get("kind", "other"),
                    "state": item.get("state", item.get("scope_state", "candidate")),
                    "source": source,
                }
            )
        return sorted(result, key=lambda item: item["id"])

    @contextmanager
    def _lock(self, root: Path) -> Iterator[None]:
        lock_path = root / "recon" / ".lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    @staticmethod
    def _targets(engagement_state: dict[str, Any]) -> list[str]:
        return [
            str(item["pattern"])
            for item in engagement_state["scope"]["in_scope"]
        ]

    @staticmethod
    def _target_host(target: str) -> str:
        if target.startswith(("http://", "https://")):
            return urlparse(target).hostname or target
        if "/" in target:
            try:
                return str(ipaddress.ip_network(target, strict=False).network_address)
            except ValueError:
                pass
        return target.split("/", 1)[0].removeprefix("*.")

    @classmethod
    def _scope_matches(cls, value: str, scope: dict[str, Any]) -> bool:
        if any(cls._asset_matches(value, item) for item in scope["out_of_scope"]):
            return False
        return any(cls._asset_matches(value, item) for item in scope["in_scope"])

    @classmethod
    def _asset_matches(cls, value: str, asset: dict[str, Any]) -> bool:
        asset_type = asset["type"]
        pattern = str(asset["pattern"]).strip()
        parsed = urlparse(value) if cls._is_url(value) else None
        host = (parsed.hostname if parsed else cls._discovery_value(value)) or ""
        host = host.lower().rstrip(".")

        if asset_type == "url-prefix":
            scope_url = urlparse(pattern)
            if not scope_url.hostname:
                return False
            if parsed is None:
                return host == scope_url.hostname.lower().rstrip(".")
            if parsed.scheme.lower() != scope_url.scheme.lower():
                return False
            if parsed.netloc.lower() != scope_url.netloc.lower():
                return False
            prefix = scope_url.path or "/"
            candidate_path = parsed.path or "/"
            return candidate_path == prefix or candidate_path.startswith(
                prefix.rstrip("/") + "/"
            )
        if asset_type in {"host", "domain"}:
            expected = cls._target_host(pattern).lower().rstrip(".")
            wildcard = pattern.startswith("*.")
            if asset_type == "host":
                return host == expected
            if wildcard:
                return host.endswith("." + expected)
            return host == expected or host.endswith("." + expected)
        if asset_type == "cidr":
            try:
                return ipaddress.ip_address(host) in ipaddress.ip_network(
                    pattern, strict=False
                )
            except ValueError:
                return False
        if asset_type == "repository":
            return value.rstrip("/") == pattern.rstrip("/")
        return value == pattern

    @staticmethod
    def _is_url(value: str) -> bool:
        return value.startswith(("http://", "https://", "ws://", "wss://"))

    @classmethod
    def _discovery_value(cls, value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        if cls._is_url(value):
            parsed = urlparse(value)
            return value if parsed.hostname else None
        if " " in value or value.startswith(("{", "[")):
            return None
        return value.rstrip(".").lower()

    @staticmethod
    def _validated_text(value: str, label: str) -> str:
        if not value or any(ord(character) < 32 for character in value):
            raise ValidationError(f"{label} contains empty or control characters")
        return value

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        return str(path.resolve().relative_to(root.resolve()))

    @staticmethod
    def _read_lines(paths: list[Path]) -> set[str]:
        values: set[str] = set()
        for path in paths:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                value = line.strip()
                if value:
                    values.add(value)
        return values

    @classmethod
    def _read_asset_values(cls, paths: list[Path]) -> set[str]:
        values: set[str] = set()
        for path in paths:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    item = None
                if isinstance(item, dict):
                    candidates = [
                        item.get("url"),
                        item.get("data"),
                        item.get("host"),
                        item.get("hostname"),
                        item.get("name"),
                        item.get("domain"),
                    ]
                    request = item.get("request")
                    if isinstance(request, dict):
                        candidates.append(request.get("endpoint"))
                    for candidate in candidates:
                        if isinstance(candidate, str):
                            filename = item.get("filename")
                            if (
                                candidate.startswith("/")
                                and isinstance(filename, str)
                                and cls._is_url(filename)
                            ):
                                candidate = urljoin(filename, candidate)
                            normalized = cls._discovery_value(candidate)
                            if normalized:
                                values.add(normalized)
                    continue
                normalized = cls._discovery_value(raw)
                if normalized:
                    values.add(normalized)
        return values

    @staticmethod
    def _write_lines(path: Path, values: set[str]) -> None:
        atomic_write(path, "".join(f"{value}\n" for value in sorted(values)))

    @staticmethod
    def _read_json_lines(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        result: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result
