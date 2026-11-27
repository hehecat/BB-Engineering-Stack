"""Continuous Mode: drive one Engagement through repeated headless agent rounds.

``bb-stack launch`` *execs* an agent: the process becomes the agent and returns
when the human ends the session. Left alone, agents instead **finish** -- they
summarise and stop -- which is why "keep testing until I say stop" cannot be
expressed in a prompt. The loop is not in the model; it is here.

Each round re-derives the launch plan rather than reusing one, so every check the
interactive path performs (required Skills and capabilities) runs again before
every round: the loop adds repetition, never reach. The round then runs as a plain subprocess and the next one resumes from
disk.

Stopping conditions, checked before each round:

- the stop file exists (``<engagement>/.bb-continuous-stop``; dropping it in is
  the "stop" the prompt could not express),
- the Engagement is no longer ``active`` (closed, paused, or otherwise stopped),
- ``--max-rounds`` is reached,
- the agent exits non-zero ``--max-failures`` times in a row.

Nothing here writes to the Engagement: ``checkpoint`` inside the round does.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .backends import BackendRegistry
from .configuration import ConfigurationManager
from .engagement import EngagementManager
from .errors import StackError, ValidationError
from .paths import StackPaths
from .profiles import ProfileRegistry
from .proxy import apply as proxy_apply
from .runtime import RuntimeManager
from .workspace import ROUTES, WorkspaceManager

# One action per round, then a checkpoint, so a killed process costs at most that
# action and the next round resumes from STATUS.md rather than from a
# conversation that is about to be truncated.
ROUND_INSTRUCTION = (
    "Continue this engagement.\n"
    "\n"
    "1. Read STATUS.md and SESSION-HANDOFF.md.\n"
    "2. Do exactly the next action they record -- one action, not a whole phase.\n"
    "3. After it, update STATUS.md and SESSION-HANDOFF.md to describe where you "
    "actually are, then run `bb-stack engagement checkpoint {slug}`.\n"
    "\n"
    "Do not start a new phase. Do not write a report unless the recorded next "
    "action is to write one. Do not summarise for a human at the end -- an "
    "external loop calls you again immediately, and a summary is wasted work."
)

STOP_FILE_NAME = ".bb-continuous-stop"
DEFAULT_ROUNDS = 25
DEFAULT_MAX_FAILURES = 3
DEFAULT_INTERVAL = 0.0
DEFAULT_ROUND_TIMEOUT = 3600


def stop_file_for(engagement: Path) -> Path:
    """The marker whose presence stops the loop."""
    return engagement / STOP_FILE_NAME


def _profile_for(paths: StackPaths, workflow: str) -> str:
    """The workflow profile declared for *workflow* in the stack manifest."""
    manifest = paths.manifest()
    mapping = (manifest.get("defaults") or {}).get("workflow_profiles") or {}
    profile = mapping.get(workflow)
    if not isinstance(profile, str) or not profile:
        raise ValidationError(
            f"no workflow profile is declared for workflow {workflow!r}"
        )
    return profile


def _profile_for_state(paths: StackPaths, state: dict[str, Any]) -> str:
    """Resolve the concrete L2 profile for *state*, preserving routed domains."""
    workflow = str(state["workflow"])
    fallback = _profile_for(paths, workflow)
    kind = (state.get("routing") or {}).get("kind")
    if not kind and (state.get("scope") or {}).get("in_scope"):
        kind = WorkspaceManager._infer_kind(state)
    base_name = str(ROUTES[kind]["profile"]) if kind in ROUTES else fallback
    if state.get("mode") != "continuous":
        return base_name
    registry = ProfileRegistry(paths)
    base = registry.load(base_name)
    matches = sorted(
        name
        for name in registry.names()
        if (definition := registry.load(name))["default_mode"] == "continuous"
        and definition["workflow"] == base["workflow"]
        and definition["l5_profile"] == base["l5_profile"]
    )
    return matches[0] if len(matches) == 1 else base_name


def _fallback_round_env(
    paths: StackPaths, engagement: Path, slug: str, state: dict[str, Any]
) -> dict[str, str]:
    env = paths.environment(engagement / "artifacts")
    machine = ConfigurationManager(paths).effective()
    proxy_apply(env, machine)
    env["PATH"] = paths.runtime_path(machine.get("BB_EXTRA_PATH", ""))
    env["BB_ENGAGEMENT"] = slug
    env["BB_ENGAGEMENT_ROOT"] = str(engagement)
    env["BB_TRAFFIC_DB"] = str(engagement / "traffic" / "flows.db")
    env["BB_ENGAGEMENT_WORKFLOW"] = str(state["workflow"])
    env["BB_AUTHORIZATION_STATUS"] = str(state["authorization"]["status"])
    return env


def run(
    paths: StackPaths,
    slug: str,
    *,
    backend: str | None = None,
    profile: str | None = None,
    max_rounds: int = DEFAULT_ROUNDS,
    max_failures: int = DEFAULT_MAX_FAILURES,
    interval: float = DEFAULT_INTERVAL,
    round_timeout: int = DEFAULT_ROUND_TIMEOUT,
    stop_file: Path | None = None,
    dry_run: bool = False,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    run_command: Callable[..., subprocess.CompletedProcess] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run headless agent rounds until a stopping condition fires.

    Returns the per-round record; the caller decides how to render it. ``dry_run``
    assembles the first round and stops, so the exact command can be inspected
    without launching anything.
    """
    if max_rounds < 1:
        raise ValidationError(f"max_rounds must be at least 1, got {max_rounds}")
    if max_failures < 1:
        raise ValidationError(f"max_failures must be at least 1, got {max_failures}")
    engagement = paths.engagement(slug)
    manager = EngagementManager(paths)
    runtime = RuntimeManager(paths)
    registry = BackendRegistry(paths)
    runner = run_command or subprocess.run
    pause = sleep or time.sleep
    marker = Path(stop_file) if stop_file else stop_file_for(engagement)

    rounds: list[dict[str, Any]] = []
    failures = 0
    reason: str | None = None
    state = manager.validate(engagement)
    chosen = profile or _profile_for_state(paths, state)
    l5_profile = ProfileRegistry(paths).load(chosen)["l5_profile"]

    for number in range(1, max_rounds + 1):
        state = manager.validate(engagement)
        if state["lifecycle"] != "active":
            reason = f"engagement is {state['lifecycle']}"
            break
        if marker.exists():
            reason = f"stop file present: {marker}"
            break

        if (
            not dry_run
            and l5_profile == "browser-js"
            and state["authorization"]["status"]
            in {"verified", "user-asserted", "exempt"}
        ):
            from .browser import BrowserRuntimeManager

            BrowserRuntimeManager(paths).start(engagement)

        # Re-derived every round on purpose: this is where the authorization
        # basis, the installed Skills and the required capabilities are checked,
        # so a round can never run on a stale approval.
        round_env: dict[str, str] = {}
        plan = runtime.launch(
            chosen,
            engagement=engagement,
            platform=None,
            backend_args=None,
            dry_run=True,
            backend=backend,
            env_out=round_env,
        )
        agent = registry.selected(plan.get("backend") or backend)
        command = [
            *plan["command"],
            *agent.headless,
            ROUND_INSTRUCTION.format(slug=slug),
        ]
        record: dict[str, Any] = {
            "round": number,
            "backend": agent.name,
            "profile": chosen,
            "cwd": plan["cwd"],
            "command": command,
        }
        if dry_run:
            record["dry_run"] = True
            rounds.append(record)
            if on_round:
                on_round(record)
            reason = "dry run"
            break

        effective_env = round_env or _fallback_round_env(paths, engagement, slug, state)
        started = time.monotonic()
        try:
            completed = runner(
                command,
                cwd=plan["cwd"],
                env=effective_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=round_timeout,
            )
            record["returncode"] = completed.returncode
            output = completed.stdout or ""
        except subprocess.TimeoutExpired as error:
            record["returncode"] = None
            record["timeout"] = round_timeout
            output = error.stdout if isinstance(error.stdout, str) else ""
        record["seconds"] = round(time.monotonic() - started, 1)
        record["output_tail"] = output.strip()[-2000:]
        record["checkpointed_at"] = _checkpoint_stamp(manager, engagement)

        if record["returncode"] == 0:
            failures = 0
        else:
            failures += 1
            record["consecutive_failures"] = failures
        rounds.append(record)
        if on_round:
            on_round(record)

        if failures >= max_failures:
            reason = f"{failures} consecutive failed rounds"
            break
        if interval and number < max_rounds:
            pause(interval)

    return {
        "engagement": slug,
        "profile": chosen,
        "backend": backend,
        "stop_file": str(marker),
        "rounds": rounds,
        "round_count": len(rounds),
        "stopped_because": reason or f"max_rounds reached ({max_rounds})",
        "last_checkpoint_at": _checkpoint_stamp(manager, engagement),
    }


def _checkpoint_stamp(manager: EngagementManager, engagement: Path) -> Any:
    """The Engagement's recorded checkpoint time, or ``None`` when unreadable."""
    try:
        state = manager.validate(engagement)
    except (StackError, OSError):
        return None
    checkpoint = state.get("checkpoint") or {}
    return checkpoint.get("updated_at")
