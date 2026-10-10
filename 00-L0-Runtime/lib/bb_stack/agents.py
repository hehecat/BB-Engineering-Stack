"""Delegation roster.

The host harness owns the agent loop and already exposes a subagent tool, so
this module does not implement one. It owns the domain half of a delegation:
which role may be handed a lead, which L5 capabilities that role may touch,
where it may write, and where it must leave its result.

Two properties make it more than a table:

* **Capability and Skill names are cross-checked** against the L5 capability
  registry and the L4 Skill manifest, so a roster entry cannot drift into
  naming something that does not exist.
* **Write sets are checked for nesting**, both between roles and within one
  fan-out batch. The harness gives every subagent the same filesystem, so two
  workers pointed at overlapping directories is a real collision -- unlike a
  process-isolated SDK, which can hand each child its own world.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .capabilities import CapabilityRegistry
from .errors import ValidationError
from .io import load_yaml
from .paths import StackPaths
from .skills import SkillRegistry
from .validation import validate


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    skill: str
    capabilities: tuple[str, ...]
    writes: tuple[str, ...]
    max_turns: int

    def output_dir(self, slice_id: str) -> str:
        """Directory one slice of this role writes to.

        Each slice gets its own child of the role's first whitelisted root, so
        two slices of the *same* role never share a directory either.
        """
        return str(PurePosixPath(self.writes[0]) / slice_id)


def _covers(parent: str, child: str) -> bool:
    """True when *child* is *parent* or lives underneath it."""
    base = PurePosixPath(parent.rstrip("/"))
    other = PurePosixPath(child.rstrip("/"))
    return other == base or base in other.parents


class AgentRoster:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.layer = paths.root / "04-L4-Skills"
        self.config_path = self.layer / "agents.yaml"
        self.schema_path = self.layer / "schema" / "agents.schema.json"

    def document(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            raise ValidationError(f"missing delegation roster: {self.config_path}")
        value = load_yaml(self.config_path)
        validate(value, self.schema_path, "delegation roster")
        return value

    def defaults(self) -> dict[str, Any]:
        return dict(self.document()["defaults"])

    def names(self) -> list[str]:
        return sorted(self.document()["agents"])

    def get(self, name: str) -> Agent:
        agents = self.document()["agents"]
        if name not in agents:
            raise ValidationError(
                f"unknown delegation role: {name}; declared: {', '.join(sorted(agents))}"
            )
        raw = agents[name]
        return Agent(
            name=name,
            description=raw["description"],
            skill=raw["skill"],
            capabilities=tuple(raw["capabilities"]),
            writes=tuple(raw["writes"]),
            max_turns=raw["max_turns"],
        )

    def validate_all(self) -> list[str]:
        document = self.document()
        skills = SkillRegistry(self.paths).manifest()["skills"]
        capabilities = set(CapabilityRegistry(self.paths).registry()["capabilities"])
        known_skills = set(skills)
        for name in sorted(document["agents"]):
            agent = self.get(name)
            if agent.skill not in known_skills:
                raise ValidationError(
                    f"delegation role {name} names unknown L4 Skill {agent.skill!r}"
                )
            missing = sorted(set(agent.capabilities) - capabilities)
            if missing:
                raise ValidationError(
                    f"delegation role {name} names unknown L5 capabilities: "
                    + ", ".join(missing)
                )
            self._check_own_write_sets(name, agent.writes)
        return sorted(document["agents"])

    @staticmethod
    def _check_own_write_sets(name: str, writes: tuple[str, ...]) -> None:
        """One role's own roots must not nest.

        Cross-role overlap is a *runtime* question -- two roles may legitimately
        share a parent as long as no two slices in the same batch land inside
        each other -- so it is enforced by `plan()` on the concrete output
        directories. What is checked here is the definition itself: a role whose
        roots contain one another cannot state where its own output goes.
        """
        for index, first in enumerate(writes):
            for second in writes[index + 1 :]:
                if _covers(first, second) or _covers(second, first):
                    raise ValidationError(
                        f"delegation role {name} declares nested write roots: "
                        f"{first!r} and {second!r}"
                    )

    def system_segment(self, names: list[str] | None = None) -> str:
        """Routing guidance for the orchestrator, in the shape norma uses.

        norma injects the worker tool names so the coordinator knows what it can
        hand out; the same is needed here, because a role that cannot be told
        apart will not be picked correctly.
        """
        selected = names or self.names()
        lines = [
            "# Delegation roster",
            "",
            "Delegate through the host's subagent tool. Pick one role per "
            "independent unit and give it a self-contained task.",
            "",
        ]
        for name in selected:
            agent = self.get(name)
            lines.append(f"- `{name}` — {agent.description.strip()}")
        return "\n".join(lines)

    def plan(
        self, requests: list[dict[str, str]], *, depth: int = 0
    ) -> dict[str, Any]:
        """Validate a fan-out batch and return one delegation package per item.

        A request is `{agent, task, id}`. The plan is the contract the
        orchestrator then hands to the harness; nothing here executes work.
        """
        defaults = self.defaults()
        if depth >= defaults["max_depth"]:
            raise ValidationError(
                f"delegation depth {depth} reached max_depth "
                f"{defaults['max_depth']}; a delegated role must not delegate again"
            )
        if not requests:
            raise ValidationError("a delegation batch needs at least one request")
        if len(requests) > defaults["max_parallel"]:
            raise ValidationError(
                f"batch of {len(requests)} exceeds max_parallel "
                f"{defaults['max_parallel']}; split it or raise the default"
            )
        packages: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for request in requests:
            for field in ("agent", "task", "id"):
                if not isinstance(request.get(field), str) or not request[field].strip():
                    raise ValidationError(
                        f"delegation request is missing a non-empty {field!r}: {request}"
                    )
            slice_id = request["id"]
            if slice_id in seen_ids:
                raise ValidationError(f"duplicate delegation id in batch: {slice_id}")
            seen_ids.add(slice_id)
            agent = self.get(request["agent"])
            packages.append(
                {
                    "id": slice_id,
                    "agent": agent.name,
                    "skill": agent.skill,
                    "task": request["task"],
                    "capabilities": sorted(agent.capabilities),
                    "writes": agent.output_dir(slice_id),
                    "declared_writes": list(agent.writes),
                    "max_turns": agent.max_turns,
                    "result": f"{agent.output_dir(slice_id)}/"
                    f"{defaults['result_file']}",
                }
            )
        self._check_batch_write_sets(packages)
        return {
            "schema_version": 1,
            "depth": depth,
            "max_parallel": defaults["max_parallel"],
            "result_file": defaults["result_file"],
            "packages": packages,
        }

    @staticmethod
    def _check_batch_write_sets(packages: list[dict[str, Any]]) -> None:
        for index, package in enumerate(packages):
            for other in packages[index + 1 :]:
                if _covers(package["writes"], other["writes"]) or _covers(
                    other["writes"], package["writes"]
                ):
                    raise ValidationError(
                        f"delegation write collision in batch: {package['id']} "
                        f"{package['writes']!r} overlaps {other['id']} "
                        f"{other['writes']!r}"
                    )
