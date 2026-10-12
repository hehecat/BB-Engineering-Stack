"""Engagement knowledge graph.

The graph is a *derived index*, never a source of truth. Authority stays with
the artifacts an operator already maintains -- `notes/asset-inventory.md`,
`recon/inventory/*`, `recon/state.json`, `hypotheses.md`,
`notes/findings-live.md`, and the captured traffic under `traffic/flows.db`.
`build` reads those and rewrites the graph from scratch, so there is exactly one
direction of truth and no write-drift to reconcile.

Its job is context economy: the orchestration layer reads a `summary` and then
pulls individual `node`/`neighbors` records on demand, instead of re-loading
every markdown file to answer "what do we have and what touches what".

Layout mirrors `bb_stack.traffic`: SQLite under `<engagement>/graph/nodes.db`,
file mode 0600 and directory mode 0700, an `XxxStore` + `xxx_for(paths, slug)`
pair, and `ValidationError` for anything actionable.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .paths import StackPaths

SCHEMA_VERSION = 1

# Node kinds the importer can produce. `asset`, `service`, `endpoint` describe
# real surface; the rest describe the engagement's reasoning about it.
NODE_KINDS = (
    "asset",
    "service",
    "endpoint",
    "finding",
    "lead",
    "evidence",
    "recon-branch",
    "coverage-gap",
)

# Edge kinds. `exposes` walks a host down to its services and endpoints;
# `targets` links a recon branch to the asset it was opened against;
# `evidenced-by` and `leads-to` tie reasoning nodes to the surface they touch.
EDGE_KINDS = ("exposes", "targets", "evidenced-by", "leads-to")

# Source names accepted by `build(source=...)`; each maps to one importer.
SOURCE_NAMES = ("asset-inventory", "recon", "hypotheses", "findings", "traffic")

# A hostname: dot-separated labels, at least one dot, no scheme/path.
_HOST_RE = re.compile(
    r"\b((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,})\b"
)
# Something that reads like an artifact path or file reference in a cell.
_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:md|json|txt|html|js|log)\b")
_SEPARATOR_RE = re.compile(r"^:?-{2,}:?$")

# Boundary safety for `neighbors`: a hub node can otherwise expand without end.
NEIGHBORS_MAX_NODES_DEFAULT = 200
NEIGHBORS_MAX_DEPTH = 5


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _merge_attrs(existing: str, incoming: dict[str, Any]) -> str:
    """Merge `incoming` over already-stored attrs so rebuilds can enrich."""
    try:
        base = json.loads(existing) if existing else {}
    except (TypeError, ValueError):
        base = {}
    if not isinstance(base, dict):
        base = {}
    base.update(incoming)
    return json.dumps(base, ensure_ascii=False, sort_keys=True)


def _cell_attr(value: str) -> str:
    return value.strip()


def _clean_host(raw: str) -> str:
    """Pull a bare hostname out of an inventory cell (steppings, backticks)."""
    token = raw.strip().strip("`").strip()
    token = token.rstrip(".,;:")
    if "://" in token:
        token = token.split("://", 1)[1]
    token = token.split("/", 1)[0]
    token = token.split("?", 1)[0].split("#", 1)[0]
    if token.startswith("*."):
        token = token[2:]
    host = token.split(":", 1)[0].strip().lower()
    if not host or "." not in host:
        return ""
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", host):
        return ""
    return host


def _hosts_in(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _HOST_RE.finditer(text or ""):
        host = match.group(1).lower()
        if "." in host:
            seen.setdefault(host, None)
    return list(seen)


# -- markdown table parsing --------------------------------------------------


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _iter_tables(text: str) -> Iterable[tuple[list[str], list[tuple[int, list[str]]]]]:
    """Yield `(header, [(lineno, cells), ...])` for each markdown table.

    A table is a header row followed by a separator row; data rows run until a
    line that is not a table row. Prose outside tables is never emitted, which
    is what keeps bullet notes out of the asset set.
    """
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "|" not in line or not line.strip().startswith("|"):
            index += 1
            continue
        header = _split_row(line)
        if index + 1 >= len(lines):
            index += 1
            continue
        separator = _split_row(lines[index + 1])
        if not separator or not all(_SEPARATOR_RE.match(cell) for cell in separator):
            index += 1
            continue
        rows: list[tuple[int, list[str]]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            cells = _split_row(lines[cursor])
            if cells:
                rows.append((cursor + 1, cells))
            cursor += 1
        yield header, rows
        index = cursor


def _header_map(header: list[str]) -> dict[str, int]:
    return {name.strip().lower(): position for position, name in enumerate(header)}


def _row_value(cells: list[str], header: list[str], *names: str) -> str:
    positions = _header_map(header)
    for name in names:
        position = positions.get(name)
        if position is not None and position < len(cells):
            return cells[position]
    return ""


# -- asset inventory ---------------------------------------------------------


def _parse_asset_inventory(
    text: str, skipped: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Assets from every markdown table that has a `Host` column.

    Rows are skipped -- and counted, never raised on -- when the host cell is
    missing, malformed, or too short to be a hostname. Only in-table rows count;
    a table without a `Host`/`Hostname` column is not an asset table at all.
    """
    assets: list[dict[str, Any]] = []
    for header, rows in _iter_tables(text):
        columns = _header_map(header)
        host_column = columns.get("host", columns.get("hostname"))
        if host_column is None:
            continue
        for line_number, cells in rows:
            if len(cells) < len(header):
                skipped.append(
                    {
                        "source": "asset-inventory",
                        "line": line_number,
                        "reason": "row has fewer cells than the header",
                        "row": " | ".join(cells)[:200],
                    }
                )
                continue
            host = _clean_host(cells[host_column])
            if not host:
                skipped.append(
                    {
                        "source": "asset-inventory",
                        "line": line_number,
                        "reason": "unrecognised host cell",
                        "row": " | ".join(cells)[:200],
                    }
                )
                continue
            attrs: dict[str, Any] = {}
            status = _row_value(cells, header, "status")
            title = _row_value(cells, header, "title", "title / fingerprint")
            notes = _row_value(cells, header, "notes")
            if status:
                attrs["status"] = _cell_attr(status)
            if title:
                attrs["title"] = _cell_attr(title)
            if notes:
                attrs["notes"] = _cell_attr(notes)
            assets.append({"host": host, "attrs": attrs})
    return assets


# Recon's accepted scope, one host or URL per line. `candidates.jsonl` lives in
# the same directory and is not read: it holds discoveries that failed the scope
# check, and an unauthorised host is not an asset.
_RECON_INVENTORY_FILES = (
    ("scope-targets.txt", "recon-inventory"),
    ("scope-hosts.txt", "recon-inventory"),
    ("scope-urls.txt", "recon-inventory"),
    ("subdomains.txt", "recon-inventory"),
)


def _parse_recon_inventory(root: Path) -> list[dict[str, Any]]:
    """Assets from the flat files recon writes under `recon/inventory/`.

    A live engagement frequently has no hand-written inventory at all -- the
    hosts sit where recon left them, and without this source the graph would be
    empty for work that plainly exists. Lines are hosts or URLs, so each goes
    through the same cleaner as an inventory cell.

    Entries the cleaner rejects are dropped silently rather than counted as
    skipped: these files hold IP literals, bare ports and comment lines by
    design, and reporting each one would bury the real parse failures.
    """
    directory = root / "recon" / "inventory"
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, source in _RECON_INVENTORY_FILES:
        path = directory / name
        if not path.is_file():
            continue
        for raw in _read_text_if(path).splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            host = _clean_host(line)
            if not host or host in seen:
                continue
            seen.add(host)
            assets.append({"host": host, "attrs": {}, "source": source})
    return assets


# -- recon state -------------------------------------------------------------


def _parse_recon_state(state: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    branches: list[dict] = []
    for branch in state.get("branches") or []:
        if not isinstance(branch, dict):
            continue
        identifier = str(branch.get("id") or "").strip()
        if not identifier:
            continue
        branches.append(
            {
                "id": identifier,
                "area": str(branch.get("area") or ""),
                "target": str(branch.get("target") or ""),
                "state": str(branch.get("state") or ""),
                "reason": str(branch.get("reason") or ""),
                "providers": list(branch.get("providers") or {}),
            }
        )
    gaps: list[dict] = []
    for gap in state.get("coverage_gaps") or []:
        if not isinstance(gap, dict):
            continue
        identifier = str(gap.get("id") or "").strip()
        if not identifier:
            continue
        gaps.append(
            {
                "id": identifier,
                "stage": str(gap.get("stage") or ""),
                "provider": str(gap.get("provider") or ""),
                "impact": str(gap.get("impact") or ""),
                "accepted": bool(gap.get("accepted")),
            }
        )
    return branches, gaps


# -- hypotheses / findings ---------------------------------------------------


def _iter_reasoning_rows(
    text: str, *, require: tuple[str, ...]
) -> list[dict[str, str]]:
    """Rows of any table whose header carries `ID` plus all of `require`."""
    found: list[dict[str, str]] = []
    for header, rows in _iter_tables(text):
        lowered = {name.strip().lower() for name in header}
        if "id" not in lowered:
            continue
        if not all(name.lower() in lowered for name in require):
            continue
        for _line_number, cells in rows:
            if len(cells) < len(header):
                continue
            record = {
                header[position].strip(): cells[position]
                for position in range(min(len(header), len(cells)))
            }
            if record.get("ID", "").strip():
                found.append(record)
    return found


def _extract_references(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _REFERENCE_RE.finditer(text or ""):
        seen.setdefault(match.group(0), None)
    return list(seen)


# -- store -------------------------------------------------------------------


@dataclass
class BuildResult:
    """What one `build` produced, in the shape callers get back."""

    nodes: dict[str, int] = field(default_factory=dict)
    edges: dict[str, int] = field(default_factory=dict)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, Any] = field(default_factory=dict)
    built_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "skipped": self.skipped,
            "sources": self.sources,
            "built_at": self.built_at,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    attrs TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(engagement, kind, key)
);
CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(engagement, kind);
CREATE INDEX IF NOT EXISTS nodes_key ON nodes(engagement, kind, key);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement TEXT NOT NULL,
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    kind TEXT NOT NULL,
    attrs TEXT NOT NULL DEFAULT '{}',
    UNIQUE(engagement, src, dst, kind)
);
CREATE INDEX IF NOT EXISTS edges_src ON edges(engagement, src);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(engagement, dst);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class GraphStore:
    """SQLite-backed derived graph for one engagement."""

    def __init__(self, path: Path, engagement: str, *, create: bool = True):
        self.path = Path(path)
        self.engagement = engagement
        if not create and not self.path.is_file():
            raise ValidationError(f"graph store not found: {self.path}")
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._connection.commit()
        if create:
            os.chmod(self.path, 0o600)

    # -- low-level writes ------------------------------------------------

    def _clear(self) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM edges WHERE engagement = ?", (self.engagement,)
            )
            self._connection.execute(
                "DELETE FROM nodes WHERE engagement = ?", (self.engagement,)
            )
            self._connection.commit()

    def _upsert_node(
        self,
        kind: str,
        key: str,
        *,
        label: str = "",
        attrs: dict[str, Any] | None = None,
        source: str = "",
    ) -> int:
        now = _now()
        with self._lock:
            row = self._connection.execute(
                "SELECT id, attrs FROM nodes WHERE engagement = ? AND kind = ? AND key = ?",
                (self.engagement, kind, key),
            ).fetchone()
            if row is None:
                cursor = self._connection.execute(
                    """
                    INSERT INTO nodes
                        (engagement, kind, key, label, attrs, source, first_seen, last_seen)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        self.engagement,
                        kind,
                        key,
                        label,
                        json.dumps(attrs or {}, ensure_ascii=False, sort_keys=True),
                        source,
                        now,
                        now,
                    ),
                )
                self._connection.commit()
                return int(cursor.lastrowid)
            merged = _merge_attrs(row["attrs"], attrs or {})
            self._connection.execute(
                """
                UPDATE nodes
                   SET label = CASE WHEN ? = '' THEN label ELSE ? END,
                       attrs = ?, source = CASE WHEN ? = '' THEN source ELSE ? END,
                       last_seen = ?
                 WHERE id = ?
                """,
                (label, label, merged, source, source, now, row["id"]),
            )
            self._connection.commit()
            return int(row["id"])

    def _upsert_edge(
        self, src: int, dst: int, kind: str, attrs: dict[str, Any] | None = None
    ) -> None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, attrs FROM edges
                 WHERE engagement = ? AND src = ? AND dst = ? AND kind = ?
                """,
                (self.engagement, src, dst, kind),
            ).fetchone()
            payload = json.dumps(attrs or {}, ensure_ascii=False, sort_keys=True)
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO edges (engagement, src, dst, kind, attrs)
                    VALUES (?,?,?,?,?)
                    """,
                    (self.engagement, src, dst, kind, payload),
                )
            else:
                self._connection.execute(
                    "UPDATE edges SET attrs = ? WHERE id = ?",
                    (_merge_attrs(row["attrs"], attrs or {}), row["id"]),
                )
            self._connection.commit()

    # -- build -----------------------------------------------------------

    def build(
        self,
        paths: StackPaths,
        slug: str,
        *,
        source: str | Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Rebuild the whole graph from the engagement's authoritative files."""
        root = paths.engagement(slug)
        selected = _selected_sources(source)
        result = BuildResult(built_at=_now())
        asset_ids: dict[str, int] = {}

        self._clear()

        counted_nodes: dict[str, set[str]] = {}
        counted_edges: dict[str, set[tuple[int, int]]] = {}

        def _record_node(kind: str, key: str) -> None:
            counted_nodes.setdefault(kind, set()).add(key)

        def _record_edge(kind: str, src: int, dst: int) -> None:
            counted_edges.setdefault(kind, set()).add((src, dst))

        # 1. assets, from the hand-written inventory and from recon's own
        inventory_path = root / "notes" / "asset-inventory.md"
        if "asset-inventory" in selected:
            entry: dict[str, Any] = {"assets": 0, "skipped": 0}
            if inventory_path.is_file():
                text = _read_text(inventory_path)
                for asset in _parse_asset_inventory(text, result.skipped):
                    node_id = self._upsert_node(
                        "asset",
                        asset["host"],
                        label=asset["host"],
                        attrs=asset["attrs"],
                        source="asset-inventory",
                    )
                    asset_ids[asset["host"]] = node_id
                    entry["assets"] += 1
                    _record_node("asset", asset["host"])
            recon_assets = _parse_recon_inventory(root)
            for asset in recon_assets:
                if asset["host"] in asset_ids:
                    # The hand-written row already claimed this host and carries
                    # more than recon knows (a status); recon only contributes
                    # hosts nothing else recorded.
                    continue
                node_id = self._upsert_node(
                    "asset",
                    asset["host"],
                    label=asset["host"],
                    attrs=asset["attrs"],
                    source=asset["source"],
                )
                asset_ids[asset["host"]] = node_id
                entry["assets"] += 1
                _record_node("asset", asset["host"])
            entry["skipped"] = sum(
                1 for item in result.skipped if item["source"] == "asset-inventory"
            )
            # Only "absent" when neither source had anything to read.
            if not inventory_path.is_file() and not recon_assets:
                entry["absent"] = True
            result.sources["asset-inventory"] = entry

        # 2. recon branches and coverage gaps
        if "recon" in selected:
            entry = {"branches": 0, "coverage_gaps": 0}
            state_path = root / "recon" / "state.json"
            if state_path.is_file():
                state = json.loads(_read_text(state_path))
                branches, gaps = _parse_recon_state(state)
                for branch in branches:
                    label = branch["target"] or branch["area"] or branch["id"]
                    branch_id = self._upsert_node(
                        "recon-branch",
                        branch["id"],
                        label=label,
                        attrs={
                            "area": branch["area"],
                            "target": branch["target"],
                            "state": branch["state"],
                            "reason": branch["reason"],
                            "providers": branch["providers"],
                        },
                        source="recon",
                    )
                    entry["branches"] += 1
                    _record_node("recon-branch", branch["id"])
                    target_host = _clean_host(branch["target"])
                    if target_host and target_host in asset_ids:
                        self._upsert_edge(
                            branch_id,
                            asset_ids[target_host],
                            "targets",
                            {"target": branch["target"]},
                        )
                        _record_edge("targets", branch_id, asset_ids[target_host])
                for gap in gaps:
                    self._upsert_node(
                        "coverage-gap",
                        gap["id"],
                        label=f"{gap['stage']}/{gap['provider']}".strip("/"),
                        attrs={
                            "stage": gap["stage"],
                            "provider": gap["provider"],
                            "impact": gap["impact"],
                            "accepted": gap["accepted"],
                        },
                        source="recon",
                    )
                    entry["coverage_gaps"] += 1
                    _record_node("coverage-gap", gap["id"])
            else:
                entry["absent"] = True
            result.sources["recon"] = entry

        # 3. hypotheses (leads)
        if "hypotheses" in selected:
            entry = {"leads": 0, "evidence": 0, "edges": 0}
            for row in _iter_reasoning_rows(
                _read_text_if(root / "hypotheses.md"),
                require=("state",),
            ):
                identifier = row.get("ID", "").strip()
                surface = row.get("Surface", "").strip()
                label = surface or row.get("Class", "").strip() or identifier
                lead_id = self._upsert_node(
                    "lead",
                    identifier,
                    label=label,
                    attrs={key: value for key, value in row.items() if value},
                    source="hypotheses",
                )
                entry["leads"] += 1
                _record_node("lead", identifier)
                touched = " ".join(
                    row.get(column, "")
                    for column in ("Surface", "Signal", "Class", "Evidence")
                )
                entry["edges"] += self._link_reasoning(
                    lead_id, touched, "leads-to", asset_ids, _record_edge
                )
                entry["evidence"] += self._link_evidence(
                    lead_id, row.get("Evidence", ""), _record_node, _record_edge
                )
            result.sources["hypotheses"] = entry

        # 4. findings
        if "findings" in selected:
            entry = {"findings": 0, "evidence": 0, "edges": 0}
            for row in _iter_reasoning_rows(
                _read_text_if(root / "notes" / "findings-live.md"),
                require=("title",),
            ):
                identifier = row.get("ID", "").strip()
                title = row.get("Title", "").strip()
                finding_id = self._upsert_node(
                    "finding",
                    identifier,
                    label=title or identifier,
                    attrs={key: value for key, value in row.items() if value},
                    source="findings",
                )
                entry["findings"] += 1
                _record_node("finding", identifier)
                touched = " ".join(
                    row.get(column, "")
                    for column in ("Title", "Asset", "Impact reached", "Evidence")
                )
                entry["edges"] += self._link_reasoning(
                    finding_id, touched, "evidenced-by", asset_ids, _record_edge
                )
                entry["evidence"] += self._link_evidence(
                    finding_id, row.get("Evidence", ""), _record_node, _record_edge
                )
            result.sources["findings"] = entry

        # 5. traffic: what was actually touched
        if "traffic" in selected:
            result.sources["traffic"] = self._import_traffic(
                root, asset_ids, _record_node, _record_edge
            )

        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', ?)",
                (result.built_at,),
            )
            self._connection.commit()
        result.nodes = {kind: len(keys) for kind, keys in counted_nodes.items()}
        result.edges = {kind: len(keys) for kind, keys in counted_edges.items()}
        return result.as_dict()

    def _link_reasoning(
        self,
        node_id: int,
        text: str,
        edge_kind: str,
        asset_ids: dict[str, int],
        record_edge: Any,
    ) -> int:
        """Link a finding/lead to the known assets whose hosts appear in it."""
        created = 0
        for host in _hosts_in(text):
            target = asset_ids.get(host)
            if target is None:
                continue
            self._upsert_edge(node_id, target, edge_kind, {"host": host})
            record_edge(edge_kind, node_id, target)
            created += 1
        return created

    def _link_evidence(
        self,
        node_id: int,
        evidence_cell: str,
        record_node: Any,
        record_edge: Any,
    ) -> int:
        created = 0
        for reference in _extract_references(evidence_cell):
            evidence_id = self._upsert_node(
                "evidence",
                reference,
                label=reference,
                attrs={},
                source="evidence",
            )
            record_node("evidence", reference)
            self._upsert_edge(node_id, evidence_id, "evidenced-by", {})
            record_edge("evidenced-by", node_id, evidence_id)
            created += 1
        return created

    def _import_traffic(
        self,
        root: Path,
        asset_ids: dict[str, int],
        record_node: Any,
        record_edge: Any,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {"services": 0, "endpoints": 0}
        flows_path = root / "traffic" / "flows.db"
        if not flows_path.is_file():
            entry["absent"] = True
            return entry
        from .traffic import TrafficStore

        with TrafficStore(flows_path, create=False) as store:
            for host_row in store.hosts():
                host = _clean_host(str(host_row["host"]))
                if not host:
                    continue
                asset_id = asset_ids.get(host)
                if asset_id is None:
                    asset_id = self._upsert_node(
                        "asset",
                        host,
                        label=host,
                        attrs={
                            "observed_in_traffic": True,
                            "flows": host_row["flows"],
                            "paths": host_row["paths"],
                        },
                        source="traffic",
                    )
                    asset_ids[host] = asset_id
                    record_node("asset", host)
                else:
                    self._upsert_node(
                        "asset",
                        host,
                        attrs={
                            "observed_in_traffic": True,
                            "flows": host_row["flows"],
                            "paths": host_row["paths"],
                        },
                    )
                service_id = self._upsert_node(
                    "service",
                    host,
                    label=host,
                    attrs={
                        "flows": host_row["flows"],
                        "paths": host_row["paths"],
                        "first_seen": host_row["first_seen"],
                        "last_seen": host_row["last_seen"],
                    },
                    source="traffic",
                )
                entry["services"] += 1
                record_node("service", host)
                self._upsert_edge(asset_id, service_id, "exposes", {"host": host})
                record_edge("exposes", asset_id, service_id)
                seen_paths: dict[str, Any] = {}
                for summary in store.search(host=host, limit=1000):
                    seen_paths.setdefault(
                        summary.path,
                        {"methods": set(), "status": summary.status},
                    )
                    seen_paths[summary.path]["methods"].add(summary.method)
                for path, info in seen_paths.items():
                    endpoint_id = self._upsert_node(
                        "endpoint",
                        f"{host}{path}",
                        label=f"{host}{path}",
                        attrs={
                            "host": host,
                            "path": path,
                            "methods": sorted(info["methods"]),
                            "status": info["status"],
                        },
                        source="traffic",
                    )
                    entry["endpoints"] += 1
                    record_node("endpoint", f"{host}{path}")
                    self._upsert_edge(
                        service_id, endpoint_id, "exposes", {"host": host, "path": path}
                    )
                    record_edge("exposes", service_id, endpoint_id)
        return entry

    # -- queries ---------------------------------------------------------

    def summary(self, *, top: int = 20) -> dict[str, Any]:
        """Counts by kind plus the heaviest nodes, with no node content."""
        if top < 0:
            raise ValidationError("summary top must not be negative")
        with self._lock:
            kind_rows = self._connection.execute(
                "SELECT kind, COUNT(*) AS n FROM nodes WHERE engagement = ? GROUP BY kind",
                (self.engagement,),
            ).fetchall()
            edge_rows = self._connection.execute(
                "SELECT kind, COUNT(*) AS n FROM edges WHERE engagement = ? GROUP BY kind",
                (self.engagement,),
            ).fetchall()
            degree_rows = self._connection.execute(
                """
                SELECT node_id, COUNT(*) AS degree FROM (
                    SELECT src AS node_id FROM edges WHERE engagement = ?
                    UNION ALL
                    SELECT dst AS node_id FROM edges WHERE engagement = ?
                ) GROUP BY node_id
                """,
                (self.engagement, self.engagement),
            ).fetchall()
            built = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'built_at'"
            ).fetchone()
        degrees = {row["node_id"]: row["degree"] for row in degree_rows}
        heaviest: dict[str, list[dict[str, Any]]] = {}
        for kind in NODE_KINDS:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT id, key, label FROM nodes WHERE engagement = ? AND kind = ?",
                    (self.engagement, kind),
                ).fetchall()
            ranked = sorted(
                (
                    {
                        "id": row["id"],
                        "key": row["key"],
                        "label": row["label"],
                        "degree": degrees.get(row["id"], 0),
                    }
                    for row in rows
                ),
                key=lambda item: (-item["degree"], item["key"]),
            )
            heaviest[kind] = ranked[:top]
        return {
            "engagement": self.engagement,
            "built_at": built["value"] if built else None,
            "totals": {
                "nodes": sum(row["n"] for row in kind_rows),
                "edges": sum(row["n"] for row in edge_rows),
            },
            "kinds": {row["kind"]: row["n"] for row in kind_rows},
            "edge_kinds": {row["kind"]: row["n"] for row in edge_rows},
            "top": {kind: nodes for kind, nodes in heaviest.items() if nodes},
        }

    def search(
        self,
        *,
        kind: str | None = None,
        label_contains: str | None = None,
        key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Light node listing: identity and source only, no attrs."""
        if limit < 1:
            raise ValidationError("search limit must be at least 1")
        clauses = ["engagement = ?"]
        parameters: list[Any] = [self.engagement]
        if kind:
            clauses.append("kind = ?")
            parameters.append(kind)
        if key:
            clauses.append("key = ?")
            parameters.append(key)
        if label_contains:
            clauses.append("label LIKE ?")
            parameters.append(f"%{label_contains}%")
        query = (
            "SELECT id, kind, key, label, source, first_seen, last_seen FROM nodes"
            f" WHERE {' AND '.join(clauses)} ORDER BY kind, key LIMIT ?"
        )
        parameters.append(min(limit, 1000))
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "key": row["key"],
                "label": row["label"],
                "source": row["source"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
            }
            for row in rows
        ]

    def node(self, kind: str, key: str) -> dict[str, Any] | None:
        """One node in full, with its incident edges."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM nodes WHERE engagement = ? AND kind = ? AND key = ?",
                (self.engagement, kind, key),
            ).fetchone()
            if row is None:
                return None
            edges = self._connection.execute(
                """
                SELECT id, src, dst, kind, attrs FROM edges
                 WHERE engagement = ? AND (src = ? OR dst = ?)
                 ORDER BY id
                """,
                (self.engagement, row["id"], row["id"]),
            ).fetchall()
        return {
            "id": row["id"],
            "kind": row["kind"],
            "key": row["key"],
            "label": row["label"],
            "attrs": json.loads(row["attrs"]),
            "source": row["source"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "edges": [
                {
                    "id": edge["id"],
                    "src": edge["src"],
                    "dst": edge["dst"],
                    "kind": edge["kind"],
                    "direction": "out" if edge["src"] == row["id"] else "in",
                    "attrs": json.loads(edge["attrs"]),
                }
                for edge in edges
            ],
        }

    def neighbors(
        self,
        node_id: int,
        *,
        kinds: Iterable[str] | None = None,
        direction: str = "both",
        depth: int = 1,
        max_nodes: int = NEIGHBORS_MAX_NODES_DEFAULT,
    ) -> dict[str, Any]:
        """Expand the subgraph around a node, bounded by `max_nodes`."""
        if direction not in ("both", "out", "in"):
            raise ValidationError("direction must be one of: both, out, in")
        if depth < 0:
            raise ValidationError("depth must not be negative")
        if max_nodes < 1:
            raise ValidationError("max_nodes must be at least 1")
        depth = min(depth, NEIGHBORS_MAX_DEPTH)
        kind_filter = {kind for kind in kinds} if kinds else None

        with self._lock:
            origin = self._connection.execute(
                "SELECT id FROM nodes WHERE engagement = ? AND id = ?",
                (self.engagement, node_id),
            ).fetchone()
        if origin is None:
            raise ValidationError(f"unknown node id: {node_id}")

        # `_edge_rows` takes the lock itself, so the walk must not hold it.
        frontier = {node_id}
        visited = {node_id}
        frontier_at = {node_id: 0}
        truncated = False
        while frontier:
            next_frontier: set[int] = set()
            for current in frontier:
                level = frontier_at[current] + 1
                if level > depth:
                    continue
                rows = self._edge_rows(current, direction)
                for row in rows:
                    other = row["dst"] if row["src"] == current else row["src"]
                    if other in visited:
                        continue
                    if len(visited) >= max_nodes:
                        truncated = True
                        continue
                    visited.add(other)
                    frontier_at[other] = level
                    next_frontier.add(other)
            frontier = next_frontier

        placeholders = ",".join("?" for _ in visited)
        with self._lock:
            node_rows = self._connection.execute(
                f"SELECT id, kind, key, label, source FROM nodes WHERE id IN ({placeholders})",
                tuple(visited),
            ).fetchall()
            edge_rows = self._connection.execute(
                f"""
                SELECT id, src, dst, kind, attrs FROM edges
                 WHERE engagement = ? AND src IN ({placeholders}) AND dst IN ({placeholders})
                """,
                (self.engagement, *visited, *visited),
            ).fetchall()

        nodes = [
            {
                "id": row["id"],
                "kind": row["kind"],
                "key": row["key"],
                "label": row["label"],
                "source": row["source"],
            }
            for row in node_rows
            if row["id"] == node_id
            or kind_filter is None
            or row["kind"] in kind_filter
        ]
        kept = {node["id"] for node in nodes}
        edges = [
            {
                "id": edge["id"],
                "src": edge["src"],
                "dst": edge["dst"],
                "kind": edge["kind"],
                "attrs": json.loads(edge["attrs"]),
            }
            for edge in edge_rows
            if edge["src"] in kept and edge["dst"] in kept
        ]
        return {
            "origin": node_id,
            "depth": depth,
            "direction": direction,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
        }

    def _edge_rows(self, node_id: int, direction: str) -> list[sqlite3.Row]:
        if direction == "out":
            clause = "src = ?"
            parameters = (self.engagement, node_id)
        elif direction == "in":
            clause = "dst = ?"
            parameters = (self.engagement, node_id)
        else:
            clause = "(src = ? OR dst = ?)"
            parameters = (self.engagement, node_id, node_id)
        with self._lock:
            return self._connection.execute(
                f"SELECT src, dst FROM edges WHERE engagement = ? AND {clause}",
                parameters,
            ).fetchall()

    def stats(self) -> dict[str, Any]:
        """Store health and shape, for `bb-stack` status surfaces."""
        with self._lock:
            nodes = self._connection.execute(
                "SELECT COUNT(*) AS n FROM nodes WHERE engagement = ?",
                (self.engagement,),
            ).fetchone()["n"]
            edges = self._connection.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE engagement = ?",
                (self.engagement,),
            ).fetchone()["n"]
            kind_rows = self._connection.execute(
                "SELECT kind, COUNT(*) AS n FROM nodes WHERE engagement = ? GROUP BY kind",
                (self.engagement,),
            ).fetchall()
            schema = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            built = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'built_at'"
            ).fetchone()
        return {
            "schema_version": int(schema["value"]) if schema else SCHEMA_VERSION,
            "path": str(self.path),
            "engagement": self.engagement,
            "built_at": built["value"] if built else None,
            "nodes": nodes,
            "edges": edges,
            "by_kind": {row["kind"]: row["n"] for row in kind_rows},
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# -- helpers -----------------------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_text_if(path: Path) -> str:
    return _read_text(path) if path.is_file() else ""


def _selected_sources(source: str | Iterable[str] | None) -> set[str]:
    if source is None:
        return set(SOURCE_NAMES)
    if isinstance(source, str):
        requested = {source}
    else:
        requested = set(source)
    unknown = requested - set(SOURCE_NAMES)
    if unknown:
        raise ValidationError(
            "unknown graph source(s): "
            + ", ".join(sorted(unknown))
            + "; expected one of: "
            + ", ".join(SOURCE_NAMES)
        )
    return requested


def graph_for(paths: StackPaths, slug: str) -> GraphStore:
    """Open the derived graph belonging to one engagement."""
    root = paths.engagement(slug)
    return GraphStore(root / "graph" / "nodes.db", slug)


def build(
    paths: StackPaths,
    slug: str,
    *,
    source: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    """Rebuild an engagement's graph from its authoritative artifacts."""
    with graph_for(paths, slug) as store:
        return store.build(paths, slug, source=source)
