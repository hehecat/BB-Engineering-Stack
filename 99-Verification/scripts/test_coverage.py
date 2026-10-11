#!/usr/bin/env python3
"""Contract tests for `bb_stack.coverage`, the asset coverage rollup.

`assess` triangulates an engagement's asset list (`notes/asset-inventory.md`),
its captured traffic (`traffic/flows.db`), and its findings/leads plus recon
coverage gaps -- all read-only. These tests pin the per-asset state machine, the
cited ratio definitions, graceful degradation when a source is missing, and the
promise that `assess` never writes anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.coverage import assess
from bb_stack.paths import StackPaths
from bb_stack.traffic import FlowRecord, store_for

INVENTORY_HEADER = (
    "# Asset Inventory\n"
    "\n"
    "Updated: 2026-01-01T00:00:00Z\n"
    "\n"
    "## Live Web Assets (active targets)\n"
    "\n"
    "| Host | Status | Title / Fingerprint | Notes |\n"
    "| --- | --- | --- | --- |\n"
)

FINDINGS_HEADER = (
    "# Findings Live Log\n"
    "\n"
    "| ID | State | Title | Asset | Impact reached | Evidence | Next action |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)

LEADS_HEADER = (
    "# Hypotheses\n"
    "\n"
    "| ID | State | Scope | Class | Surface | Signal | Identity | Evidence | Exact next test |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
)


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-coverage-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.slug = "coverage-fixture"
        self.engagement = self.paths.engagements_root / self.slug
        self.engagement.mkdir(parents=True)
        (self.engagement / "engagement.yaml").write_text(
            f"schema_version: 1\nslug: {self.slug}\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    # -- helpers ---------------------------------------------------------

    def write_inventory(self, rows: list[tuple[str, str]], *, name: str = "asset-inventory.md") -> None:
        lines = [INVENTORY_HEADER]
        for host, status in rows:
            lines.append(f"| `{host}` | {status} | title | note |\n")
        notes = self.engagement / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        (notes / name).write_text("".join(lines), encoding="utf-8")

    def write_findings(self, rows: list[tuple[str, str, str]]) -> None:
        lines = [FINDINGS_HEADER]
        for identifier, state, asset in rows:
            lines.append(f"| {identifier} | {state} | title | {asset} | impact | ev | next |\n")
        notes = self.engagement / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        (notes / "findings-live.md").write_text("".join(lines), encoding="utf-8")

    def write_leads(self, rows: list[tuple[str, str, str]]) -> None:
        lines = [LEADS_HEADER]
        for identifier, state, surface in rows:
            lines.append(
                f"| {identifier} | {state} | in-scope | class | {surface} | signal"
                " | unauthenticated | evidence | next |\n"
            )
        (self.engagement / "hypotheses.md").write_text("".join(lines), encoding="utf-8")

    def write_state(self, gaps: list[dict[str, Any]]) -> None:
        recon = self.engagement / "recon"
        recon.mkdir(parents=True, exist_ok=True)
        (recon / "state.json").write_text(
            json.dumps({"coverage_gaps": gaps}), encoding="utf-8"
        )

    def record_flow(self, host: str) -> None:
        with store_for(self.paths, self.slug) as store:
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

    def status_by_host(self, report: dict[str, Any]) -> dict[str, str]:
        return {entry["host"]: entry["coverage"] for entry in report["by_asset"]}

    # -- inventory only --------------------------------------------------

    def test_inventory_only_is_all_untouched(self) -> None:
        self.write_inventory(
            [("www.example.test", "200"), ("api.example.test", "401")]
        )
        report = assess(self.paths, self.slug)
        self.assertEqual(
            self.status_by_host(report),
            {"www.example.test": "untouched", "api.example.test": "untouched"},
        )
        totals = report["totals"]
        self.assertEqual(totals["assets"], 2)
        self.assertEqual(totals["untouched"], 2)
        self.assertEqual(totals["touched"], 0)
        self.assertEqual(totals["concluded"], 0)
        self.assertEqual(totals["ratio"], 0.0)
        self.assertEqual(totals["evidenced_ratio"], 0.0)
        self.assertEqual(totals["traffic_hosts"], 0)
        self.assertTrue(report["sources"]["inventory"])
        self.assertFalse(report["sources"]["traffic"])

    def test_status_column_is_preserved(self) -> None:
        self.write_inventory([("www.example.test", "301->200")])
        report = assess(self.paths, self.slug)
        self.assertEqual(report["by_asset"][0]["status"], "301->200")

    def test_section_title_is_the_asset_source(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        report = assess(self.paths, self.slug)
        self.assertEqual(
            report["by_asset"][0]["source"], "Live Web Assets (active targets)"
        )

    def test_assets_inventory_filename_is_a_fallback(self) -> None:
        self.write_inventory([("cdn.example.test", "200")], name="assets-inventory.md")
        report = assess(self.paths, self.slug)
        self.assertEqual(report["totals"]["assets"], 1)
        self.assertEqual(report["by_asset"][0]["host"], "cdn.example.test")

    # -- traffic ---------------------------------------------------------

    def test_traffic_marks_asset_touched(self) -> None:
        self.write_inventory(
            [("www.example.test", "200"), ("api.example.test", "401")]
        )
        self.record_flow("www.example.test")
        report = assess(self.paths, self.slug)
        self.assertEqual(
            self.status_by_host(report),
            {"www.example.test": "touched", "api.example.test": "untouched"},
        )
        totals = report["totals"]
        self.assertEqual(totals["touched"], 1)
        self.assertEqual(totals["concluded"], 0)
        self.assertEqual(totals["ratio"], 0.0)
        self.assertEqual(totals["evidenced_ratio"], 0.5)
        self.assertTrue(report["sources"]["traffic"])

    def test_flow_count_is_evidence(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        self.record_flow("www.example.test")
        self.record_flow("www.example.test")
        report = assess(self.paths, self.slug)
        self.assertEqual(report["by_asset"][0]["evidence"]["flows"], 2)

    # -- findings and leads ----------------------------------------------

    def test_finding_concludes_asset(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        self.record_flow("www.example.test")
        self.write_findings([("F-001", "closed", "www.example.test")])
        report = assess(self.paths, self.slug)
        self.assertEqual(report["by_asset"][0]["coverage"], "concluded")
        self.assertEqual(report["by_asset"][0]["evidence"]["findings"], 1)
        self.assertEqual(report["totals"]["ratio"], 1.0)

    def test_finding_without_traffic_still_concludes(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        self.write_findings([("F-001", "confirmed", "www.example.test")])
        report = assess(self.paths, self.slug)
        self.assertEqual(report["by_asset"][0]["coverage"], "concluded")
        self.assertEqual(report["by_asset"][0]["evidence"]["flows"], 0)

    def test_terminal_lead_concludes_non_terminal_does_not(self) -> None:
        self.write_inventory(
            [("killed.example.test", "200"), ("live.example.test", "200")]
        )
        self.record_flow("live.example.test")
        self.write_leads(
            [("H-001", "killed", "killed.example.test"), ("H-002", "queued", "live.example.test")]
        )
        report = assess(self.paths, self.slug)
        self.assertEqual(
            self.status_by_host(report),
            {"killed.example.test": "concluded", "live.example.test": "touched"},
        )

    def test_host_boundary_avoids_partial_matches(self) -> None:
        self.write_inventory(
            [("example.test", "200"), ("www.example.test", "200")]
        )
        self.write_findings([("F-001", "closed", "sub.example.test")])
        report = assess(self.paths, self.slug)
        # `sub.example.test` must not conclude `example.test` (suffix) nor
        # `www.example.test` (sibling).
        self.assertEqual(
            self.status_by_host(report),
            {"example.test": "untouched", "www.example.test": "untouched"},
        )

    # -- gaps ------------------------------------------------------------

    def test_accepted_gap_is_reported_but_not_counted_as_coverage(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        self.write_state(
            [
                {
                    "id": "G-001",
                    "stage": "web-probe",
                    "provider": "httpx",
                    "impact": "coverage",
                    "accepted": True,
                }
            ]
        )
        report = assess(self.paths, self.slug)
        self.assertEqual(report["totals"]["gaps"], 1)
        self.assertEqual(report["totals"]["accepted_gaps"], 1)
        self.assertEqual(report["by_asset"][0]["coverage"], "untouched")
        self.assertEqual(report["totals"]["ratio"], 0.0)
        self.assertTrue(report["sources"]["state"])

    # -- sorting and structure -------------------------------------------

    def test_uncovered_sorts_first_then_less_evidence(self) -> None:
        self.write_inventory(
            [
                ("done.example.test", "200"),
                ("warm.example.test", "200"),
                ("hot.example.test", "200"),
                ("cold.example.test", "200"),
            ]
        )
        self.record_flow("warm.example.test")
        self.record_flow("hot.example.test")
        self.record_flow("hot.example.test")
        self.write_findings([("F-001", "closed", "done.example.test")])
        report = assess(self.paths, self.slug)
        self.assertEqual(
            [entry["host"] for entry in report["by_asset"]],
            [
                "cold.example.test",
                "warm.example.test",
                "hot.example.test",
                "done.example.test",
            ],
        )

    def test_unresolved_lists_everything_not_concluded(self) -> None:
        self.write_inventory(
            [("www.example.test", "200"), ("api.example.test", "401")]
        )
        self.record_flow("api.example.test")
        report = assess(self.paths, self.slug)
        self.assertEqual(
            [entry["host"] for entry in report["unresolved"]],
            ["www.example.test", "api.example.test"],
        )
        reasons = {entry["host"]: entry["reason"] for entry in report["unresolved"]}
        self.assertIn("no traffic", reasons["www.example.test"])
        self.assertIn("traffic observed", reasons["api.example.test"])

    # -- degradation -----------------------------------------------------

    def test_empty_inventory_yields_zero_ratio(self) -> None:
        report = assess(self.paths, self.slug)
        self.assertEqual(report["totals"]["assets"], 0)
        self.assertEqual(report["totals"]["ratio"], 0.0)
        self.assertEqual(report["totals"]["evidenced_ratio"], 0.0)
        self.assertEqual(report["by_asset"], [])
        self.assertEqual(report["unresolved"], [])

    def test_traffic_hosts_outside_inventory_are_unmatched(self) -> None:
        self.record_flow("drift.example.test")
        report = assess(self.paths, self.slug)
        self.assertEqual(
            report["unmatched"], [{"host": "drift.example.test", "flows": 1}]
        )

    def test_missing_and_corrupt_sources_do_not_raise(self) -> None:
        recon = self.engagement / "recon"
        recon.mkdir(parents=True)
        (recon / "state.json").write_text("{not json", encoding="utf-8")
        report = assess(self.paths, self.slug)
        self.assertEqual(report["gaps"], [])
        self.assertEqual(report["totals"]["gaps"], 0)

    # -- read-only guarantee ---------------------------------------------

    def test_assess_writes_nothing(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        self.record_flow("www.example.test")
        db = self.engagement / "traffic" / "flows.db"
        digest = hashlib.sha256(db.read_bytes()).hexdigest()

        before = sorted(p.relative_to(self.engagement) for p in self.engagement.rglob("*"))
        assess(self.paths, self.slug)
        after = sorted(p.relative_to(self.engagement) for p in self.engagement.rglob("*"))

        self.assertEqual(before, after)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), digest)

    def test_assess_does_not_create_a_traffic_store(self) -> None:
        self.write_inventory([("www.example.test", "200")])
        assess(self.paths, self.slug)
        self.assertFalse((self.engagement / "traffic" / "flows.db").exists())
        self.assertFalse((self.engagement / "traffic").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
