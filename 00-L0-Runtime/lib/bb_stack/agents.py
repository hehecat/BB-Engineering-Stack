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
from .coverage import assess
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


# One objective sentence per coverage state. These name what was and was not
# observed; they deliberately name no role, because coverage carries no domain
# information and picking a role is the caller's decision.
_SUGGEST_HINTS = {
    "untouched": "no flows captured and no terminal conclusion recorded",
    "touched": "flows captured but no finding and no terminal lead recorded",
    "unmatched": "traffic captured for a host that is absent from the inventory",
}


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

    def suggest(
        self,
        paths: StackPaths,
        slug: str,
        *,
        agent: str | None = None,
        limit: int = 4,
    ) -> dict[str, Any]:
        """Rank candidate work items for one engagement, from coverage alone.

        The candidates are the ``unresolved`` entries (assets with no traffic
        and no conclusion, and assets with traffic but no closed lead) plus any
        ``unmatched`` traffic hosts -- traffic the inventory never listed, which
        is a self-discovered asset. Ordering is deterministic: ``untouched``
        first, then the least-evidenced, then host order; a host never appears
        twice.

        What coverage *cannot* supply is a role. It records what was observed,
        not what kind of asset this is, so with no ``agent`` this returns
        targets only -- each with an objective ``hint`` and no role -- and says
        so explicitly (``role_assigned: False``). Pass ``agent`` to get one
        request per candidate that ``plan()`` accepts verbatim. This method
        never runs ``plan()``'s write-set check: candidate production and batch
        validation stay separate.
        """
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValidationError(f"limit must be a positive integer, got {limit!r}")
        if limit < 1:
            raise ValidationError(f"limit must be at least 1, got {limit!r}")

        report = assess(paths, slug)
        evidence = {
            entry["host"]: sum(entry["evidence"].values())
            for entry in report["by_asset"]
        }

        found: list[tuple[str, str, str, int]] = []
        seen: set[str] = set()
        for entry in report["unresolved"]:
            host = entry["host"]
            if host in seen:
                continue
            seen.add(host)
            found.append(
                (host, entry["coverage"], entry["reason"], evidence.get(host, 0))
            )
        for entry in report["unmatched"]:
            host = entry["host"]
            if host in seen:
                continue
            seen.add(host)
            found.append(
                (
                    host,
                    "unmatched",
                    "traffic observed for a host that is absent from the inventory",
                    entry["flows"],
                )
            )

        found.sort(
            key=lambda item: (0 if item[1] == "untouched" else 1, item[3], item[0])
        )
        candidates = [
            {
                "host": host,
                "coverage": coverage,
                "reason": reason,
                "priority": index + 1,
                "hint": _SUGGEST_HINTS[coverage],
            }
            for index, (host, coverage, reason, _) in enumerate(found[:limit])
        ]

        defaults = self.defaults()
        result: dict[str, Any] = {
            "schema_version": 1,
            "engagement": slug,
            "max_parallel": defaults["max_parallel"],
            "role_assigned": agent is not None,
            "available": len(found),
            "sources": report["sources"],
            "candidates": candidates,
        }
        if agent is None:
            result["note"] = (
                "coverage carries no domain information, so no role is inferred; "
                "the caller decides the role. Re-run with an agent name to emit "
                "requests ready for the plan file."
            )
            return result

        role = self.get(agent)
        requests: list[dict[str, str]] = []
        for candidate in candidates:
            slice_id = candidate["host"]
            directory = role.output_dir(slice_id)
            result_path = f"{directory}/{defaults['result_file']}"
            requests.append(
                {
                    "id": slice_id,
                    "agent": role.name,
                    "task": (
                        f"One candidate asset for engagement {slug!r}: "
                        f"{candidate['host']} (coverage={candidate['coverage']}). "
                        f"{candidate['hint']}. Decide whether it is in scope and "
                        f"reach a recorded conclusion. Write only under "
                        f"{directory}/ and leave {result_path} with the "
                        f"conclusion (status, evidence, next action)."
                    ),
                    "writes": directory,
                    "result": result_path,
                }
            )
        result.update(
            {
                "agent": role.name,
                "skill": role.skill,
                "result_file": defaults["result_file"],
                "writes": list(role.writes),
                "requests": requests,
            }
        )
        return result
