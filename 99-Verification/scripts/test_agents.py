#!/usr/bin/env python3
"""Delegation roster contracts.

The roster exists so a fan-out cannot collide on the shared filesystem the host
harness gives every subagent. These tests pin the refusals, not the happy path
alone: each `assertRaises` case is one that a permissive implementation would
let through.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.agents import AgentRoster
from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths
from bb_stack.traffic import FlowRecord, store_for


def _roster_document(agents: str, *, max_parallel: int = 4, max_depth: int = 2) -> str:
    return f"""schema_version: 1
defaults:
  max_parallel: {max_parallel}
  max_depth: {max_depth}
  result_file: result.json
agents:
{agents}
"""


class AgentRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-agents-")
        home = Path(self.temporary.name)
        self.paths = StackPaths(
            root=ROOT,
            home=home,
            work_root=home / "work",
            config_home=home / "config",
            claude_config_dir=home / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _roster_from(self, document: str) -> AgentRoster:
        path = Path(self.temporary.name) / "agents.yaml"
        path.write_text(document, encoding="utf-8")
        roster = AgentRoster(self.paths)
        roster.config_path = path
        return roster

    def test_declared_roster_validates_and_names_are_stable(self) -> None:
        roster = AgentRoster(self.paths)
        names = roster.validate_all()
        self.assertEqual(names, roster.names())
        self.assertIn("web-prover", names)
        self.assertIn("evidence-writer", names)
        self.assertEqual(roster.defaults()["result_file"], "result.json")

    def test_every_role_capability_exists_in_the_l5_registry(self) -> None:
        """A renamed capability must break validation, not a live run."""
        document = _roster_document(
            """  ghost:
    description: A role naming a capability that does not exist.
    skill: bb-recon
    capabilities: [recon.not-a-real-capability]
    writes: [artifacts/ghost]
    max_turns: 10
"""
        )
        roster = self._roster_from(document)
        with self.assertRaisesRegex(ValidationError, "unknown L5 capabilities"):
            roster.validate_all()

    def test_every_role_skill_exists_in_the_l4_manifest(self) -> None:
        document = _roster_document(
            """  ghost:
    description: A role naming a Skill that does not exist.
    skill: not-a-real-skill
    capabilities: [http.raw]
    writes: [artifacts/ghost]
    max_turns: 10
"""
        )
        roster = self._roster_from(document)
        with self.assertRaisesRegex(ValidationError, "unknown L4 Skill"):
            roster.validate_all()

    def test_one_roles_own_write_roots_may_not_nest(self) -> None:
        """A role that cannot say where its output goes is a definition bug."""
        document = _roster_document(
            """  nested:
    description: A role whose own write roots contain one another.
    skill: bb-recon
    capabilities: [http.raw]
    writes: [artifacts/nested, artifacts/nested/deeper]
    max_turns: 10
"""
        )
        roster = self._roster_from(document)
        with self.assertRaisesRegex(ValidationError, "nested write roots"):
            roster.validate_all()

    def test_slices_of_one_role_get_separate_directories(self) -> None:
        roster = AgentRoster(self.paths)
        plan = roster.plan(
            [
                {"agent": "web-prover", "task": "prove A", "id": "slice-a"},
                {"agent": "web-prover", "task": "prove B", "id": "slice-b"},
            ]
        )
        writes = [package["writes"] for package in plan["packages"]]
        self.assertEqual(len(set(writes)), 2)
        for package in plan["packages"]:
            self.assertTrue(package["writes"].startswith("artifacts/web/"))
            self.assertTrue(package["result"].endswith("/result.json"))

    def test_plan_refuses_duplicate_ids(self) -> None:
        roster = AgentRoster(self.paths)
        with self.assertRaisesRegex(ValidationError, "duplicate delegation id"):
            roster.plan(
                [
                    {"agent": "web-prover", "task": "a", "id": "same"},
                    {"agent": "recon-runner", "task": "b", "id": "same"},
                ]
            )

    def test_plan_refuses_batches_over_max_parallel(self) -> None:
        roster = AgentRoster(self.paths)
        requests = [
            {"agent": "recon-runner", "task": f"t{i}", "id": f"r{i}"} for i in range(5)
        ]
        with self.assertRaisesRegex(ValidationError, "exceeds max_parallel"):
            roster.plan(requests)

    def test_plan_refuses_a_delegated_role_that_delegates_again(self) -> None:
        roster = AgentRoster(self.paths)
        with self.assertRaisesRegex(ValidationError, "max_depth"):
            roster.plan([{"agent": "web-prover", "task": "a", "id": "a"}], depth=2)

    def test_plan_refuses_unknown_role(self) -> None:
        roster = AgentRoster(self.paths)
        with self.assertRaisesRegex(ValidationError, "unknown delegation role"):
            roster.plan([{"agent": "nope", "task": "a", "id": "a"}])

    def test_plan_refuses_incomplete_request(self) -> None:
        roster = AgentRoster(self.paths)
        with self.assertRaisesRegex(ValidationError, "non-empty 'task'"):
            roster.plan([{"agent": "web-prover", "id": "a"}])

    def test_batch_write_collision_is_refused(self) -> None:
        """The case the whole write-set mechanism exists for.

        Two roles may declare roots that contain one another; only the concrete
        slice directories decide whether a batch collides. Here role `outer`
        writes `artifacts/outer/` and role `inner` writes `artifacts/outer/inner/`,
        and the batch picks a slice id that lands the two inside each other.
        """
        document = _roster_document(
            """  outer:
    description: A role whose slice directory can contain another role's.
    skill: bb-recon
    capabilities: [http.raw]
    writes: [artifacts/outer]
    max_turns: 10
  inner:
    description: A role that deliberately lands under the other role's slice.
    skill: bb-recon
    capabilities: [http.raw]
    writes: [artifacts/outer/inner]
    max_turns: 10
"""
        )
        roster = self._roster_from(document)
        self.assertEqual(roster.validate_all(), ["inner", "outer"])
        with self.assertRaisesRegex(ValidationError, "write collision in batch"):
            roster.plan(
                [
                    {"agent": "outer", "task": "a", "id": "inner"},
                    {"agent": "inner", "task": "b", "id": "leaf"},
                ]
            )

    def test_system_segment_hands_the_orchestrator_its_options(self) -> None:
        roster = AgentRoster(self.paths)
        segment = roster.system_segment(["web-prover", "evidence-writer"])
        self.assertIn("`web-prover`", segment)
        self.assertIn("`evidence-writer`", segment)
        self.assertNotIn("`recon-runner`", segment)

    # -- suggest ---------------------------------------------------------

    def _engagement(self, slug: str) -> Path:
        root = self.paths.engagements_root / slug
        root.mkdir(parents=True, exist_ok=True)
        (root / "engagement.yaml").write_text(
            f"schema_version: 1\nslug: {slug}\n", encoding="utf-8"
        )
        return root

    def _inventory(self, slug: str, rows: list[tuple[str, str]]) -> Path:
        root = self._engagement(slug)
        notes = root / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        text = "# Asset Inventory\n\n| Host | Status | Notes |\n| --- | --- | --- |\n"
        for host, status in rows:
            text += f"| {host} | {status} | |\n"
        (notes / "asset-inventory.md").write_text(text, encoding="utf-8")
        return root

    def _lead(self, slug: str, host: str, state: str) -> None:
        (self.paths.engagements_root / slug / "hypotheses.md").write_text(
            "# Hypotheses\n\n"
            "| ID | State | Scope | Class | Surface | Signal |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            f"| H-1 | {state} | in-scope | auth | {host} | signal |\n",
            encoding="utf-8",
        )

    def _flow(self, slug: str, host: str) -> None:
        with store_for(self.paths, slug) as store:
            store.record(
                FlowRecord(
                    method="GET",
                    host=host,
                    path="/",
                    response_status=200,
                    response_headers={"Content-Type": "text/html"},
                    response_body=b"ok",
                )
            )

    def _suggestion_fixture(self, slug: str = "suggest-fixture") -> str:
        """One untouched host, one touched host, and one unmatched traffic host.

        `zzz` is untouched with zero evidence; `aaa` is touched by a flow and an
        open (non-terminal) lead, so it carries two evidence points; `drift`
        appeared only in traffic, so it is unmatched with one flow.
        """
        self._inventory(
            slug,
            [("zzz.example.invalid", "502"), ("aaa.example.invalid", "200")],
        )
        self._lead(slug, "aaa.example.invalid", "open")
        self._flow(slug, "aaa.example.invalid")
        self._flow(slug, "drift.example.invalid")
        return slug

    def test_suggest_ranks_untouched_then_least_evidenced(self) -> None:
        slug = self._suggestion_fixture()
        result = AgentRoster(self.paths).suggest(self.paths, slug)

        self.assertFalse(result["role_assigned"])
        self.assertEqual(result["max_parallel"], 4)
        self.assertEqual(
            [candidate["host"] for candidate in result["candidates"]],
            [
                "zzz.example.invalid",
                "drift.example.invalid",
                "aaa.example.invalid",
            ],
        )
        self.assertEqual(
            [candidate["priority"] for candidate in result["candidates"]], [1, 2, 3]
        )
        self.assertEqual(
            [candidate["coverage"] for candidate in result["candidates"]],
            ["untouched", "unmatched", "touched"],
        )
        for candidate in result["candidates"]:
            self.assertTrue(candidate["reason"])
            self.assertTrue(candidate["hint"])

    def test_suggest_dedupes_a_host_seen_in_both_sources(self) -> None:
        """`unresolved` and `unmatched` are disjoint in practice, not by luck."""
        host = "dup.example.invalid"
        report = {
            "by_asset": [
                {
                    "host": host,
                    "status": None,
                    "coverage": "untouched",
                    "evidence": {"flows": 0, "findings": 0, "leads": 0},
                    "source": "inventory",
                }
            ],
            "unresolved": [
                {
                    "host": host,
                    "coverage": "untouched",
                    "reason": "no traffic observed and no conclusion recorded",
                }
            ],
            "unmatched": [{"host": host, "flows": 2}],
            "sources": {"inventory": True, "traffic": True},
        }
        with patch("bb_stack.agents.assess", return_value=report):
            result = AgentRoster(self.paths).suggest(self.paths, "dup-fixture")
        self.assertEqual(
            [candidate["host"] for candidate in result["candidates"]], [host]
        )

    def test_suggest_limit_caps_and_rejects_below_one(self) -> None:
        slug = self._suggestion_fixture("suggest-limit")
        roster = AgentRoster(self.paths)

        capped = roster.suggest(self.paths, slug, limit=2)
        self.assertEqual(
            [candidate["host"] for candidate in capped["candidates"]],
            ["zzz.example.invalid", "drift.example.invalid"],
        )
        self.assertEqual(capped["available"], 3)

        with self.assertRaisesRegex(ValidationError, "limit"):
            roster.suggest(self.paths, slug, limit=0)

    def test_suggest_never_names_a_declared_role_without_an_agent(self) -> None:
        """Picking a role is the caller's decision, not a guess from coverage."""
        slug = self._suggestion_fixture("suggest-roles")
        roster = AgentRoster(self.paths)
        result = roster.suggest(self.paths, slug)

        text = json.dumps(result)
        for name in roster.names():
            self.assertNotIn(name, text)
        self.assertFalse(result["role_assigned"])
        self.assertIn("role", result["note"])

    def test_suggest_requests_pass_plan_verbatim_and_unknown_role_is_refused(
        self,
    ) -> None:
        slug = self._suggestion_fixture("suggest-plan")
        roster = AgentRoster(self.paths)

        result = roster.suggest(self.paths, slug, agent="web-prover")
        self.assertTrue(result["role_assigned"])
        self.assertEqual(result["agent"], "web-prover")
        self.assertEqual(result["writes"], ["artifacts/web/"])
        self.assertEqual(result["result_file"], "result.json")

        requests = result["requests"]
        self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertEqual(request["agent"], "web-prover")
            self.assertTrue(request["task"])
            self.assertTrue(request["writes"].startswith("artifacts/web/"))
            self.assertTrue(request["result"].endswith("/result.json"))

        # Unchanged, extra keys and all, the batch must satisfy `plan()`.
        plan = roster.plan(requests)
        self.assertEqual(len(plan["packages"]), len(requests))

        with self.assertRaisesRegex(ValidationError, "unknown delegation role"):
            roster.suggest(self.paths, slug, agent="nope")


if __name__ == "__main__":
    unittest.main(verbosity=2)
