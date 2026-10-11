"""Asset coverage assessment for one engagement.

Answers "how much of this engagement is still untested?" by triangulating facts
that already exist on disk. ``assess`` is strictly read-only: it never creates a
state file, and it never writes to the traffic store.

Three sources, cross-checked:

1. ``notes/asset-inventory.md`` -- the asset list. The canonical shape is a
   markdown table with a ``Host`` column (hosts wrapped in backticks); any
   ``##`` section may carry one such table. ``assets-inventory.md`` is accepted
   as a fallback filename.
2. ``traffic/flows.db`` -- which hosts actually received traffic. A missing or
   empty store is not an error, it just means "no traffic evidence". The store
   is opened through a read-only SQLite URI rather than through ``TrafficStore``
   because opening a store rewrites its ``schema_version`` meta row; coverage
   must not mutate the thing it measures.
3. ``notes/findings-live.md`` and ``hypotheses.md`` -- which assets have a
   conclusion. ``recon/state.json`` ``coverage_gaps[]`` is reported as
   engagement-level known gaps.

Per-asset state machine (highest evidence wins):

- ``concluded`` -- a finding row names the asset, or a hypothesis/lead row for it
  reached a terminal state (``validated`` or ``killed``). The asset was assessed
  and closed one way or the other.
- ``touched`` -- no conclusion, but at least one traffic flow hit the host.
- ``untouched`` -- present in the inventory, yet absent from traffic and from any
  finding or terminal lead.

``accepted-gap`` is deliberately **not** an asset state. ``coverage_gaps[]`` are
scoped to a recon *stage/provider*, not to an asset, so a gap cannot be attached
to a single host without guessing. They are reported verbatim under ``gaps``.
Even where a gap could be tied to an asset, an ``accepted`` gap is a declared
decision to stop, not evidence that the asset was exercised -- counting it as
coverage would inflate the ratio, so the ratio counts only concluded assets.

Ratios in ``totals``:

- ``ratio`` = concluded / assets (share fully assessed).
- ``evidenced_ratio`` = (touched + concluded) / assets (share with any evidence,
  i.e. "has this asset even been touched"). Both are ``0.0`` for an empty
  inventory.

``by_asset`` is sorted least-covered first: ``untouched`` before ``touched``
before ``concluded``, then by ascending evidence volume, then by host.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ValidationError
from .io import load_json
from .paths import StackPaths

# `assets-inventory.md` is the name one real engagement shipped; accept both.
INVENTORY_FILES = ("asset-inventory.md", "assets-inventory.md")
FINDINGS_FILE = Path("notes") / "findings-live.md"
HYPOTHESES_FILE = Path("hypotheses.md")
TRAFFIC_DB = Path("traffic") / "flows.db"
STATE_FILE = Path("recon") / "state.json"

# A lead only counts as a conclusion once it is settled.
TERMINAL_LEAD_STATES = {"validated", "killed"}

# Ordering for "least covered first".
_COVERAGE_ORDER = {"untouched": 0, "touched": 1, "concluded": 2}
# A host token must not sit inside a longer token (`example.com` must not match
# `www.example.com` or `notexample.com`).
_BOUNDARY = "[A-Za-z0-9._-]"


@dataclass(frozen=True)
class _Table:
    """One parsed markdown table and the `##` section that held it."""

    section: str | None
    header: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class _Asset:
    host: str
    status: str | None
    source: str | None


@dataclass(frozen=True)
class _Record:
    """One findings/leads table row; `text` is every cell joined for matching."""

    identifier: str
    state: str
    text: str


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-+:?", cell or "") is not None for cell in cells
    )


def _markdown_tables(text: str) -> list[_Table]:
    """Every markdown table in `text`, tagged with its `##` section."""
    tables: list[_Table] = []
    section: str | None = None
    header: list[str] | None = None
    rows: list[list[str]] = []

    def flush() -> None:
        nonlocal header, rows
        if header is not None:
            tables.append(_Table(section, header, rows))
        header, rows = None, []

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip() or None
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = _split_row(line)
            if header is None:
                if _is_separator(cells):
                    continue
                header = [cell.lower() for cell in cells]
                continue
            if _is_separator(cells):
                continue
            rows.append(cells)
            continue
        flush()
    flush()
    return tables


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _normalize_host(value: str) -> str:
    """Bare, lowercase hostname or IP from a messy cell/traffic value."""
    host = value.strip().strip("`").strip("*").strip().strip("`").strip()
    if not host:
        return ""
    if "://" in host:
        parsed = urlparse(host)
        host = parsed.netloc or parsed.path
    elif "@" in host.split("/")[0]:
        host = host.split("@", 1)[1]
    host = host.split("/")[0].split("?")[0]
    if host.startswith("["):  # IPv6 literal such as `[::1]:443`
        host = host.split("]", 1)[0].lstrip("[")
    elif ":" in host:
        host = host.split(":", 1)[0]
    return host.strip().rstrip(".").lower()


def _inventory(root: Path) -> list[_Asset]:
    for name in INVENTORY_FILES:
        text = _read_text(root / "notes" / name)
        if text is None:
            continue
        assets: list[_Asset] = []
        seen: set[str] = set()
        for table in _markdown_tables(text):
            if "host" not in table.header:
                continue
            host_i = table.header.index("host")
            status_i = (
                table.header.index("status") if "status" in table.header else None
            )
            for row in table.rows:
                if host_i >= len(row):
                    continue
                host = _normalize_host(row[host_i])
                if not host or host in seen:
                    continue
                seen.add(host)
                status = None
                if status_i is not None and status_i < len(row):
                    status = row[status_i].strip().strip("`") or None
                assets.append(_Asset(host, status, table.section))
        # The first inventory file that exists wins; only fall back when it has
        # no usable `Host` table either.
        if assets:
            return assets
    return []


def _traffic_hosts(db: Path) -> dict[str, int]:
    """Host -> flow count from a read-only handle; empty when unavailable."""
    if not db.is_file():
        return {}
    try:
        uri = db.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    except (sqlite3.Error, ValueError):
        return {}
    try:
        rows = connection.execute(
            "SELECT host, COUNT(*) FROM flows GROUP BY host"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    hosts: dict[str, int] = {}
    for host, flows in rows:
        key = _normalize_host(str(host))
        if key:
            hosts[key] = hosts.get(key, 0) + int(flows)
    return hosts


def _records(path: Path, marker: str) -> list[_Record]:
    """Rows of every table in `path` whose header carries `marker`."""
    text = _read_text(path)
    if text is None:
        return []
    records: list[_Record] = []
    for table in _markdown_tables(text):
        if "id" not in table.header or "state" not in table.header:
            continue
        if marker not in table.header:
            continue
        id_i = table.header.index("id")
        state_i = table.header.index("state")
        for row in table.rows:
            records.append(
                _Record(
                    row[id_i].strip() if id_i < len(row) else "",
                    row[state_i].strip().lower() if state_i < len(row) else "",
                    " ".join(row),
                )
            )
    return records


def _gaps(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        state = load_json(path)
    except ValidationError:
        return []
    gaps = state.get("coverage_gaps")
    if not isinstance(gaps, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        cleaned.append(
            {
                "id": gap.get("id"),
                "stage": gap.get("stage"),
                "provider": gap.get("provider"),
                "impact": gap.get("impact"),
                "accepted": bool(gap.get("accepted")),
            }
        )
    return cleaned


def _matcher(host: str) -> re.Pattern[str]:
    return re.compile(
        f"(?<!{_BOUNDARY}){re.escape(host)}(?!{_BOUNDARY})", re.IGNORECASE
    )


def assess(paths: StackPaths, slug: str) -> dict[str, Any]:
    """Coverage rollup for one engagement; reads only, writes nothing."""
    root = paths.engagement(slug)

    assets = _inventory(root)
    traffic = _traffic_hosts(root / TRAFFIC_DB)
    findings = _records(root / FINDINGS_FILE, "asset")
    leads = _records(root / HYPOTHESES_FILE, "surface")
    gaps = _gaps(root / STATE_FILE)

    by_asset: list[dict[str, Any]] = []
    for asset in assets:
        pattern = _matcher(asset.host)
        flows = traffic.get(asset.host, 0)
        matched_findings = sum(1 for record in findings if pattern.search(record.text))
        matched_leads = [record for record in leads if pattern.search(record.text)]
        conclusive = any(
            record.state in TERMINAL_LEAD_STATES for record in matched_leads
        )
        if matched_findings or conclusive:
            coverage = "concluded"
        elif flows:
            coverage = "touched"
        else:
            coverage = "untouched"
        by_asset.append(
            {
                "host": asset.host,
                "status": asset.status,
                "coverage": coverage,
                "evidence": {
                    "flows": flows,
                    "findings": matched_findings,
                    "leads": len(matched_leads),
                },
                "source": asset.source,
            }
        )

    def evidence_total(entry: dict[str, Any]) -> int:
        return sum(entry["evidence"].values())

    by_asset.sort(
        key=lambda entry: (
            _COVERAGE_ORDER[entry["coverage"]],
            evidence_total(entry),
            entry["host"],
        )
    )

    total = len(by_asset)
    untouched = sum(1 for entry in by_asset if entry["coverage"] == "untouched")
    touched = sum(1 for entry in by_asset if entry["coverage"] == "touched")
    concluded = total - untouched - touched

    unresolved = [
        {
            "host": entry["host"],
            "coverage": entry["coverage"],
            "reason": (
                "no traffic observed and no conclusion recorded"
                if entry["coverage"] == "untouched"
                else "traffic observed but no finding or terminal lead"
            ),
        }
        for entry in by_asset
        if entry["coverage"] != "concluded"
    ]

    inventory_hosts = {asset.host for asset in assets}
    unmatched = [
        {"host": host, "flows": flows}
        for host, flows in sorted(traffic.items(), key=lambda kv: (-kv[1], kv[0]))
        if host not in inventory_hosts
    ]

    return {
        "engagement": slug,
        "totals": {
            "assets": total,
            "untouched": untouched,
            "touched": touched,
            "concluded": concluded,
            "uncovered": untouched,
            "ratio": concluded / total if total else 0.0,
            "evidenced_ratio": (touched + concluded) / total if total else 0.0,
            "traffic_hosts": len(traffic),
            "findings": len(findings),
            "leads": len(leads),
            "gaps": len(gaps),
            "accepted_gaps": sum(1 for gap in gaps if gap["accepted"]),
        },
        "by_asset": by_asset,
        "gaps": gaps,
        "unresolved": unresolved,
        "unmatched": unmatched,
        "sources": {
            "inventory": bool(assets),
            "traffic": bool(traffic),
            "findings": bool(findings),
            "leads": bool(leads),
            "state": bool(gaps),
        },
    }
