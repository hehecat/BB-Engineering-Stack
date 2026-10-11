#!/usr/bin/env python3
"""Contract tests for `bb_stack.graph`, the engagement knowledge graph.

The graph is a derived index: `build` reads the authoritative artifacts
(asset inventory, recon state, hypotheses, findings, captured traffic) and
rewrites a SQLite graph an orchestration layer can query cheaply -- `summary`
first, then `node`/`neighbors` on demand. These tests pin the parse rules, the
rebuild-is-idempotent property, the query surface, the traversal boundary, and
file permissions, using a synthetic engagement only.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import ValidationError
from bb_stack.graph import (
    SCHEMA_VERSION,
    SOURCE_NAMES,
    GraphStore,
    build,
    graph_for,
)
from bb_stack.paths import StackPaths
from bb_stack.traffic import FlowRecord, store_for

INVENTORY = """\
# Asset Inventory

Updated: 2024-01-01T00:00:00Z

## Live Web Assets (active targets)

| Host | Status | Title / Fingerprint | Notes |
| --- | --- | --- | --- |
| `alpha.example.invalid` | 200 | Alpha portal | HSTS |
| beta.example.invalid | 301->200 | Beta redirect | CDN |
| | 200 | no host here | skipped |
| `not-a-host` | 200 | bad host | skipped |
| truncated | 200 | too few cells |

## Non asset table

| Key | Value |
| --- | --- |
| owner | team |
| region | eu |
"""

HYPOTHESES = """\
# Hypotheses

| ID | State | Scope | Class | Surface | Signal | Identity | Evidence | Exact next test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H-001 | active | in-scope | authz | alpha.example.invalid portal | SSO present | unauthenticated | notes/asset-inventory.md | probe redirect |
| H-002 | queued | in-scope | idor | unknown.example.invalid | ids | unauthenticated | recon/state.json | try id swap |

## H-001: portal authz
"""

FINDINGS = """\
# Findings Live Log

| ID | State | Title | Asset | Impact reached | Evidence | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| F-001 | candidate | Reflected marker on beta | beta.example.invalid | reflected input | notes/asset-inventory.md; recon/state.json | confirm |

## Entry Template
"""

RECON_STATE = {
    "schema_version": 1,
    "engagement": "graph-fixture",
    "mode": "baseline",
    "state": "baseline_completed",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-02T00:00:00Z",
    "closed_at": None,
    "close_reason": None,
    "stages": {"recon": {"state": "completed"}},
    "branches": [
        {
            "id": "B-1",
            "area": "web",
            "target": "alpha.example.invalid",
            "reason": "login surface",
            "state": "running",
            "created_at": "2024-01-01T00:00:00Z",
            "completed_at": None,
            "providers": {"httpx": {"state": "completed", "error": None}},
            "artifacts": [],
        }
    ],
    "signals": [],
    "scope_candidates": [],
    "coverage_gaps": [
        {
            "id": "web.httpx",
            "stage": "web",
            "provider": "httpx",
            "impact": "optional enrichment skipped",
            "accepted": False,
        }
    ],
    "recommended_actions": [],
}


class GraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-graph-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.slug = "graph-fixture"
        self.engagement = self.paths.engagements_root / self.slug
        (self.engagement / "notes").mkdir(parents=True)
        (self.engagement / "recon").mkdir()
        (self.engagement / "engagement.yaml").write_text(
            f"schema_version: 1\nslug: {self.slug}\n", encoding="utf-8"
        )
        (self.engagement / "notes" / "asset-inventory.md").write_text(
            INVENTORY, encoding="utf-8"
        )
        (self.engagement / "notes" / "findings-live.md").write_text(
            FINDINGS, encoding="utf-8"
        )
        (self.engagement / "hypotheses.md").write_text(HYPOTHESES, encoding="utf-8")
        (self.engagement / "recon" / "state.json").write_text(
            json.dumps(RECON_STATE), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def seed_traffic(self) -> None:
        store = store_for(self.paths, self.slug)
        try:
            store.record(
                FlowRecord(
                    method="GET",
                    host="gamma.example.invalid",
                    path="/api/v1/users",
                    response_status=200,
                )
            )
            store.record(
                FlowRecord(
                    method="POST",
                    host="gamma.example.invalid",
                    path="/api/v1/users",
                    response_status=201,
                )
            )
            store.record(
                FlowRecord(
                    method="GET",
                    host="gamma.example.invalid",
                    path="/health",
                    response_status=200,
                )
            )
        finally:
            store.close()

    def result(self, **kwargs: Any) -> dict[str, Any]:
        return build(self.paths, self.slug, **kwargs)

    # -- build -----------------------------------------------------------

    def test_build_counts_nodes_and_edges(self) -> None:
        result = self.result()
        self.assertEqual(result["nodes"]["asset"], 2)
        self.assertEqual(result["nodes"]["lead"], 2)
        self.assertEqual(result["nodes"]["finding"], 1)
        self.assertEqual(result["nodes"]["recon-branch"], 1)
        self.assertEqual(result["nodes"]["coverage-gap"], 1)
        self.assertEqual(result["nodes"]["evidence"], 2)
        self.assertEqual(result["edges"]["targets"], 1)
        # lead -> asset (alpha), finding -> asset (beta), plus three
        # distinct evidenced-by links that resolve to known artifacts.
        self.assertEqual(result["edges"]["leads-to"], 1)
        self.assertEqual(result["edges"]["evidenced-by"], 5)
        self.assertEqual(result["sources"]["asset-inventory"]["assets"], 2)

    def test_build_skips_unparseable_rows(self) -> None:
        result = self.result()
        skipped = result["skipped"]
        self.assertEqual(result["sources"]["asset-inventory"]["skipped"], 3)
        self.assertEqual(len(skipped), 3)
        self.assertIn("unrecognised host cell", {item["reason"] for item in skipped})
        self.assertIn(
            "row has fewer cells than the header",
            {item["reason"] for item in skipped},
        )
        # The non-asset table contributes neither assets nor skips.
        self.assertNotIn("owner", json.dumps(result))

    def test_rebuild_is_idempotent(self) -> None:
        first = self.result()
        with graph_for(self.paths, self.slug) as store:
            store.build(self.paths, self.slug)
            second = store.build(self.paths, self.slug)
            self.assertEqual(store.stats()["nodes"], self._total(second, "nodes"))
        self.assertEqual(first["nodes"], second["nodes"])
        self.assertEqual(first["edges"], second["edges"])

    @staticmethod
    def _total(result: dict[str, Any], key: str) -> int:
        return sum(result[key].values())

    def test_build_rejects_unknown_source(self) -> None:
        with self.assertRaises(ValidationError):
            self.result(source="nope")

    def test_traffic_produces_services_and_endpoints(self) -> None:
        self.seed_traffic()
        result = self.result()
        self.assertEqual(result["nodes"]["service"], 1)
        self.assertEqual(result["nodes"]["endpoint"], 2)
        self.assertEqual(result["edges"]["exposes"], 3)
        with graph_for(self.paths, self.slug) as store:
            asset = store.node("asset", "gamma.example.invalid")
            assert asset is not None
            self.assertTrue(asset["attrs"]["observed_in_traffic"])
            self.assertEqual(asset["attrs"]["flows"], 3)

    def test_source_filter_limits_import(self) -> None:
        result = self.result(source="recon")
        self.assertEqual(set(result["sources"]), {"recon"})
        self.assertNotIn("asset", result["nodes"])

    def test_sources_constant_is_complete(self) -> None:
        self.assertEqual(
            set(SOURCE_NAMES),
            {"asset-inventory", "recon", "hypotheses", "findings", "traffic"},
        )

    # -- queries ---------------------------------------------------------

    def test_summary_reports_counts_without_content(self) -> None:
        self.result()
        with graph_for(self.paths, self.slug) as store:
            summary = store.summary(top=2)
        self.assertEqual(summary["kinds"]["asset"], 2)
        self.assertEqual(summary["totals"]["nodes"], 9)
        self.assertIsNotNone(summary["built_at"])
        self.assertEqual(len(summary["top"]["asset"]), 2)
        # alpha is targeted by a branch and a lead, so it leads on degree.
        top_asset = summary["top"]["asset"][0]
        self.assertEqual(top_asset["key"], "alpha.example.invalid")
        self.assertGreater(top_asset["degree"], 0)
        self.assertNotIn("attrs", top_asset)

    def test_search_filters(self) -> None:
        self.result()
        with graph_for(self.paths, self.slug) as store:
            self.assertEqual(len(store.search(kind="asset")), 2)
            self.assertEqual(
                [row["key"] for row in store.search(kind="asset", key="beta.example.invalid")],
                ["beta.example.invalid"],
            )
            self.assertEqual(
                [row["key"] for row in store.search(label_contains="unknown")],
                ["H-002"],
            )
            self.assertEqual(store.search(kind="asset", label_contains="nope"), [])
            self.assertNotIn("attrs", store.search(kind="finding")[0])
            with self.assertRaises(ValidationError):
                store.search(limit=0)

    def test_node_includes_attrs_and_edges(self) -> None:
        self.result()
        with graph_for(self.paths, self.slug) as store:
            node = store.node("asset", "alpha.example.invalid")
            assert node is not None
            self.assertEqual(node["attrs"]["status"], "200")
            self.assertEqual(node["attrs"]["title"], "Alpha portal")
            edge_kinds = {edge["kind"] for edge in node["edges"]}
            self.assertIn("targets", edge_kinds)
            self.assertIn("leads-to", edge_kinds)
            self.assertIsNone(store.node("asset", "missing.example.invalid"))

    def test_neighbors_traverses_bounded_subgraph(self) -> None:
        self.seed_traffic()
        self.result()
        with graph_for(self.paths, self.slug) as store:
            lead = store.node("lead", "H-001")
            assert lead is not None
            subgraph = store.neighbors(lead["id"], depth=1)
            self.assertEqual(subgraph["origin"], lead["id"])
            keys = {node["key"] for node in subgraph["nodes"]}
            self.assertIn("alpha.example.invalid", keys)
            self.assertIn("notes/asset-inventory.md", keys)
            # kind filter keeps the origin but drops the evidence neighbour.
            filtered = store.neighbors(
                lead["id"], depth=1, kinds=["asset"]
            )
            self.assertEqual(
                {node["key"] for node in filtered["nodes"]},
                {"H-001", "alpha.example.invalid"},
            )
            out_only = store.neighbors(lead["id"], depth=1, direction="out")
            self.assertEqual({node["key"] for node in out_only["nodes"]}, keys)
            in_only = store.neighbors(lead["id"], depth=1, direction="in")
            self.assertEqual({node["key"] for node in in_only["nodes"]}, {"H-001"})
            truncated = store.neighbors(lead["id"], depth=1, max_nodes=1)
            self.assertTrue(truncated["truncated"])

    def test_neighbors_validates_arguments(self) -> None:
        self.result()
        with graph_for(self.paths, self.slug) as store:
            lead = store.node("lead", "H-001")
            assert lead is not None
            with self.assertRaises(ValidationError):
                store.neighbors(lead["id"], direction="sideways")
            with self.assertRaises(ValidationError):
                store.neighbors(lead["id"], depth=-1)
            with self.assertRaises(ValidationError):
                store.neighbors(lead["id"], max_nodes=0)
            with self.assertRaises(ValidationError):
                store.neighbors(999999)

    def test_stats_shape(self) -> None:
        self.result()
        with graph_for(self.paths, self.slug) as store:
            stats = store.stats()
        self.assertEqual(stats["schema_version"], SCHEMA_VERSION)
        self.assertEqual(stats["engagement"], self.slug)
        self.assertEqual(stats["nodes"], 9)
        self.assertEqual(stats["path"], str(self.engagement / "graph" / "nodes.db"))
        self.assertIsNotNone(stats["built_at"])

    # -- storage ---------------------------------------------------------

    def test_store_permissions(self) -> None:
        self.result()
        db = self.engagement / "graph" / "nodes.db"
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(db.parent.stat().st_mode), 0o700
        )

    def test_missing_engagement_raises(self) -> None:
        with self.assertRaises(ValidationError):
            GraphStore(self.engagement / "graph" / "nodes.db", self.slug, create=False)


if __name__ == "__main__":
    unittest.main()
