from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from uuid import uuid4

from . import __version__
from .capabilities import CapabilityRegistry
from .engagement import EngagementManager
from .errors import CommandError, ValidationError
from .io import atomic_write, dump_json, dump_yaml, load_json, load_yaml
from .paths import StackPaths
from .profiles import ProfileRegistry
from .runtime import RuntimeManager
from .skills import SkillRegistry
from .validation import validate


STATE_FILES = (
    "engagement.yaml",
    "notes/SCOPE.md",
    "SESSION-HANDOFF.md",
    "STATUS.md",
)
ROUTE_TERMINALS = {
    "minimal": "ctf-orchestrator",
    "ctf-web": "ctf-web",
    "web": "bb-methodology",
    "android": "android-pentest",
    "reverse": "reverse-orchestrator",
}
SCENARIOS = {
    "minimal": (
        "A local fixture needs first-pass reproduction and classification. "
        "Select the workflow orchestrator before any specialist analysis."
    ),
    "ctf-web": (
        "The supplied challenge is a headless HTTP application with a JSON API "
        "and browser client. Select the matching Web specialist Skill."
    ),
    "web": (
        "This is the first turn of a new API object-access lead. Select the master "
        "Bug Bounty startup methodology before vulnerability-specific payloads."
    ),
    "android": (
        "The supplied artifact is an APK requiring manifest and bytecode triage. "
        "Select the Android specialist Skill after the reverse router."
    ),
    "reverse": (
        "The supplied artifact is an unknown native executable. Select the reverse "
        "engineering router before choosing a debugger or decompiler."
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


class EvaluationManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.profile_registry = ProfileRegistry(paths)
        self.skill_registry = SkillRegistry(paths)
        self.capability_registry = CapabilityRegistry(paths)
        self.result_schema = (
            paths.root / "schema" / "agent-evaluation-result.schema.json"
        )
        self.root = paths.config_home / "evaluations"

    def contracts(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        profile_names = self.profile_registry.validate_all()
        self.skill_registry.validate_all()
        self.capability_registry.validate_all()
        for name in profile_names:
            definition = self.profile_registry.load(name)
            render = self.profile_registry.render(name)
            content = Path(render.output_file).read_text(encoding="utf-8")
            required_skills = set(
                self.skill_registry.profile(render.skill_profile)["required"]
            )
            orchestrator = self.skill_registry.profile(render.skill_profile)[
                "orchestrator"
            ]
            skill_route = self._skill_route(render.l5_profile)
            self._check(
                checks,
                f"{name}.orchestrator",
                orchestrator in required_skills,
                f"{orchestrator} is required by {render.skill_profile}",
            )
            self._check(
                checks,
                f"{name}.state-resume",
                all(state_file in content for state_file in STATE_FILES),
                "Prompt names all four L3 resume files",
            )
            self._check(
                checks,
                f"{name}.artifact-policy",
                "artifacts/" in content,
                "Prompt names the Engagement artifact directory",
            )
            self._check(
                checks,
                f"{name}.skill-routing",
                all(f"`{skill_name}`" in content for skill_name in skill_route),
                f"Prompt includes route {' -> '.join(skill_route)}",
            )
            domain = definition.get("domain_prompt")
            domain_fragment = (
                f"02-L2-Workflow-Profiles/workflows/domains/{domain}.md"
                if domain
                else None
            )
            self._check(
                checks,
                f"{name}.domain",
                domain_fragment is None or domain_fragment in render.source_fragments,
                "Configured domain Prompt is rendered exactly once",
            )
            self._check(
                checks,
                f"{name}.budget",
                render.token_estimate <= render.budget,
                f"Prompt estimate {render.token_estimate}/{render.budget}",
            )
        return {
            "schema_version": 1,
            "suite": "contracts",
            "passed": all(item["passed"] for item in checks),
            "profile_count": len(profile_names),
            "check_count": len(checks),
            "checks": checks,
        }

    def agent(
        self,
        profile: str,
        *,
        timeout: int = 180,
        model: str | None = "sonnet",
        max_budget_usd: float = 1.0,
    ) -> dict[str, Any]:
        if timeout < 10 or timeout > 1800:
            raise ValidationError(
                "agent evaluation timeout must be between 10 and 1800 seconds"
            )
        if max_budget_usd <= 0 or max_budget_usd > 10:
            raise ValidationError(
                "agent evaluation budget must be greater than 0 and at most 10 USD"
            )
        definition = self.profile_registry.load(profile)
        capability_profile = str(definition["l5_profile"])
        self._skill_route(capability_profile)
        self.root.mkdir(parents=True, exist_ok=True)
        workspace = self.root / "runs" / f"{profile}-latest"
        self._reset_workspace(workspace)
        eval_paths = StackPaths(
            root=self.paths.root,
            home=self.paths.home,
            work_root=workspace / "work",
            config_home=self.paths.config_home,
            claude_config_dir=self.paths.claude_config_dir,
            claude_config_explicit=self.paths.claude_config_explicit,
        )
        slug = "agent-eval"
        engagement = EngagementManager(eval_paths).create(
            slug,
            "./evaluation-fixture",
            workflow=str(definition["workflow"]),
            platform=str(definition["platform"]),
            mode=str(definition["default_mode"]),
            title=f"Agent Evaluation: {profile}",
        )
        expected = self._prepare_fixture(
            engagement, capability_profile, profile=profile
        )
        artifact = engagement / "artifacts" / "evaluation" / "agent-result.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        launch = RuntimeManager(eval_paths).launch(
            profile,
            engagement=engagement,
            platform=None,
            claude_args=[],
            dry_run=True,
        )
        command = list(launch["command"])
        prompt_flag = (
            "--system-prompt-file"
            if launch["prompt_mode"] == "replacement"
            else "--append-system-prompt-file"
        )
        prompt_path = Path(command[command.index(prompt_flag) + 1])
        prompt_sha256 = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
        contract_sha256 = self.contract_sha256(profile)
        command.extend(
            [
                "--print",
                "--output-format",
                "text",
                "--no-session-persistence",
                "--permission-mode",
                "acceptEdits",
                "--tools",
                "Read,Write",
                "--effort",
                "low",
                "--max-budget-usd",
                str(max_budget_usd),
            ]
        )
        if model:
            command.extend(["--model", model])
        command.append(self._agent_prompt())
        env = eval_paths.environment(engagement / "artifacts")
        env["PATH"] = eval_paths.runtime_path()
        started = time.monotonic()
        exit_code: int | None = None
        process_error: str | None = None
        stdout = ""
        stderr = ""
        try:
            completed = subprocess.run(
                command,
                cwd=engagement,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            stdout = self._as_text(error.stdout)
            stderr = self._as_text(error.stderr)
            process_error = f"timeout after {timeout} seconds"
        except OSError as error:
            process_error = f"{error.__class__.__name__}: {error}"
        duration = round(time.monotonic() - started, 3)
        atomic_write(workspace / "stdout.txt", stdout, 0o600)
        atomic_write(workspace / "stderr.txt", stderr, 0o600)
        checks = self._score_agent(
            artifact,
            expected,
            exit_code=exit_code,
            stdout=stdout,
        )
        if process_error:
            checks.insert(
                0,
                {
                    "id": "process.error",
                    "passed": False,
                    "detail": process_error,
                },
            )
        passed = all(item["passed"] for item in checks)
        report = {
            "schema_version": 1,
            "suite": "agent-startup",
            "stack_version": __version__,
            "passed": passed,
            "profile": profile,
            "capability_profile": capability_profile,
            "expected_skill_route": expected["selected_skill_route"],
            "prompt_sha256": prompt_sha256,
            "contract_sha256": contract_sha256,
            "created_at": _now(),
            "duration_seconds": duration,
            "exit_code": exit_code,
            "workspace": str(workspace),
            "artifact": str(artifact),
            "stdout": str(workspace / "stdout.txt"),
            "stderr": str(workspace / "stderr.txt"),
            "checks": checks,
        }
        latest = self.root / f"latest-{profile}.json"
        dump_json(latest, report, 0o600)
        report["report"] = str(latest)
        return report

    def latest(self, profile: str) -> dict[str, Any] | None:
        path = self.root / f"latest-{profile}.json"
        if not path.is_file():
            return None
        report = load_json(path)
        return {
            "path": str(path),
            "passed": bool(report.get("passed")),
            "profile": report.get("profile"),
            "created_at": report.get("created_at"),
            "duration_seconds": report.get("duration_seconds"),
            "stack_version": report.get("stack_version"),
            "prompt_sha256": report.get("prompt_sha256"),
            "contract_sha256": report.get("contract_sha256"),
            "failed_checks": [
                item.get("id")
                for item in report.get("checks", [])
                if not item.get("passed")
            ],
        }

    def _prepare_fixture(
        self, engagement: Path, capability_profile: str, *, profile: str
    ) -> dict[str, Any]:
        nonce = uuid4().hex[:12]
        skill_route = self._skill_route(capability_profile)
        expected = {
            "scope_marker": f"scope-{nonce}",
            "handoff_marker": f"handoff-{nonce}",
            "status_marker": f"status-{nonce}",
            "next_action": f"inspect-evaluation-scenario-{nonce}",
            "selected_skill_route": skill_route,
            "artifact_policy": "artifacts/",
        }
        self._append(
            engagement / "notes" / "SCOPE.md",
            f"\nEvaluation marker: EVAL_SCOPE={expected['scope_marker']}\n",
        )
        self._append(
            engagement / "SESSION-HANDOFF.md",
            f"\nEvaluation marker: EVAL_HANDOFF={expected['handoff_marker']}\n",
        )
        self._append(
            engagement / "STATUS.md",
            f"\nEvaluation marker: EVAL_STATUS={expected['status_marker']}\n",
        )
        state_path = engagement / "engagement.yaml"
        state = load_yaml(state_path)
        state["current"]["next_action"] = expected["next_action"]
        dump_yaml(state_path, state)
        scenario = (
            "# Agent Evaluation Scenario\n\n"
            f"Runtime profile: `{profile}`\n\n"
            f"{SCENARIOS[capability_profile]}\n"
        )
        scenario_path = {
            "bug-bounty": engagement / "notes" / "EVALUATION-LEAD.md",
            "ctf": engagement / "challenge" / "EVALUATION.md",
            "lab": engagement / "fixture" / "EVALUATION.md",
        }[state["workflow"]]
        scenario_path.parent.mkdir(parents=True, exist_ok=True)
        scenario_path.write_text(scenario, encoding="utf-8")
        return expected

    def _score_agent(
        self,
        artifact: Path,
        expected: dict[str, Any],
        *,
        exit_code: int | None,
        stdout: str,
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        self._check(checks, "process.exit", exit_code == 0, f"exit_code={exit_code}")
        self._check(
            checks,
            "process.marker",
            "BB_AGENT_EVAL_DONE" in stdout,
            "completion marker is present in stdout",
        )
        self._check(
            checks,
            "artifact.exists",
            artifact.is_file(),
            "agent-result.json exists under artifacts/evaluation",
        )
        if not artifact.is_file():
            return checks
        try:
            result = load_json(artifact)
            validate(result, self.result_schema, "agent evaluation result")
        except (ValidationError, OSError, ValueError) as error:
            self._check(checks, "artifact.schema", False, str(error))
            return checks
        self._check(checks, "artifact.schema", True, "result matches schema")
        for key, value in expected.items():
            self._check(
                checks,
                f"result.{key}",
                result.get(key) == value,
                f"{key} matches the fixture contract",
            )
        return checks

    @staticmethod
    def _agent_prompt() -> str:
        return (
            "Run the normal startup and complete route selection for this already "
            "classified work unit. Report the complete policy route without invoking "
            "either Skill. Do not solve the scenario, execute commands, or access any "
            "network. Read "
            "engagement.yaml, notes/SCOPE.md, SESSION-HANDOFF.md, STATUS.md, and the "
            "evaluation scenario under challenge/, notes/, or fixture/. Create "
            "artifacts/evaluation/agent-result.json as one JSON object with exactly "
            "these keys: scope_marker, handoff_marker, status_marker, next_action, "
            "selected_skill_route, artifact_policy. Marker values follow EVAL_SCOPE, "
            "EVAL_HANDOFF, and EVAL_STATUS. next_action is the exact engagement.yaml "
            "current.next_action. selected_skill_route is an ordered JSON array naming "
            "the initial orchestrator/router and then the terminal profile Skill selected "
            "for this scenario; omit a duplicate terminal when the orchestrator is the "
            "terminal profile Skill. Do not stop the reported route at the orchestrator "
            "when the active domain Prompt names a terminal specialist. "
            "artifact_policy is the literal top-level workflow artifact "
            "root named by the active Prompt, not this evaluation subdirectory, and must "
            "include its trailing slash. After writing valid JSON, print exactly "
            "BB_AGENT_EVAL_DONE."
        )

    def contract_sha256(self, profile: str) -> str:
        definition = self.profile_registry.load(profile)
        capability_profile = str(definition["l5_profile"])
        skill_route = self._skill_route(capability_profile)
        digest = hashlib.sha256()
        values = [
            self.result_schema.read_text(encoding="utf-8"),
            self._agent_prompt(),
            SCENARIOS[capability_profile],
        ]
        for name in skill_route:
            values.extend(
                [name, self.skill_registry.tree_digest(self.skill_registry.source(name))]
            )
        for value in values:
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def _skill_route(self, capability_profile: str) -> list[str]:
        if capability_profile not in ROUTE_TERMINALS:
            raise ValidationError(
                f"agent evaluation has no route contract for {capability_profile}"
            )
        skill_profile = self.skill_registry.profile(capability_profile)
        orchestrator = str(skill_profile["orchestrator"])
        terminal = ROUTE_TERMINALS[capability_profile]
        route = [orchestrator]
        if terminal != orchestrator:
            route.append(terminal)
        for name in route:
            self.skill_registry.source(name)
        return route

    def _reset_workspace(self, workspace: Path) -> None:
        runs = (self.root / "runs").resolve()
        target = workspace.resolve()
        try:
            target.relative_to(runs)
        except ValueError as error:
            raise CommandError(
                "evaluation workspace escapes the managed runs directory"
            ) from error
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _append(path: Path, content: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)

    @staticmethod
    def _as_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return (
            value.decode("utf-8", errors="replace")
            if isinstance(value, bytes)
            else value
        )

    @staticmethod
    def _check(
        checks: list[dict[str, Any]], identifier: str, passed: bool, detail: str
    ) -> None:
        checks.append({"id": identifier, "passed": bool(passed), "detail": detail})
