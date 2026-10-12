"""Asset coverage assessment for one engagement.

Answers "how much of this engagement is still untested?" by triangulating facts
that already exist on disk. ``assess`` is strictly read-only: it never creates a
state file, and it never writes to the traffic store.

Four sources, cross-checked:

1. The asset list, from both places it is written:
   a. ``notes/asset-inventory.md`` -- the hand-curated list. The canonical shape
      is a markdown table with a ``Host`` column (hosts wrapped in backticks);
      any ``##`` section may carry one such table, and its ``Status`` column is
      preserved. ``assets-inventory.md`` is accepted as a fallback filename.
   b. ``recon/inventory/*`` -- the accepted scope as recon wrote it: one host or
      URL per line in ``scope-targets.txt``, ``scope-hosts.txt``,
      ``scope-urls.txt`` and ``subdomains.txt``. A live engagement often has no
      hand-written inventory at all, so without this source coverage would report
      "no assets" for work that plainly exists. The hand-written list wins on
      conflict because only it carries a status. ``candidates.jsonl`` in the same
      directory is **not** read: it holds discoveries that failed the scope check,
      and an unauthorised host is not an asset to cover.
2. ``traffic/flows.db`` -- which hosts actually received traffic. A missing or
   empty store is not an error, it just means "no traffic evidence". The store
   is opened through a read-only SQLite URI rather than through ``TrafficStore``
   because opening a store rewrites its ``schema_version`` meta row; coverage
   must not mutate the thing it measures.
3. ``notes/findings-live.md`` and ``hypotheses.md`` -- which assets have a
   conclusion. ``recon/state.json`` ``coverage_gaps[]`` is reported as
   engagement-level known gaps.
4. ``recon/state.json`` ``stages`` -- how far the recon *pipeline* got, reported
   under ``recon``. Asset coverage says nothing about stages that never ran, and
   an engagement can ship a complete-looking asset list while most stages are
   still ``pending``. Every stage state is counted; ``incomplete`` totals the
   non-terminal ones, using recon's own definition of terminal
   (``TERMINAL_STAGE_STATES``: ``completed``, ``partial``, ``skipped``).

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

``gate`` turns those numbers into a verdict, but only against thresholds the
operator declares. It measures two independent things: how much of the *asset
list* carries evidence, and how far the *recon pipeline* got
(``max_incomplete_stages``). An engagement can satisfy every asset threshold
while most stages never ran -- the asset list is simply short, and a short list
is cheap to cover -- so a gate meant to mean "the work is done" has to constrain
both. There is deliberately no built-in convergence standard: with no threshold
supplied the gate fails and says so, because "covered enough" is a decision the
engagement owner makes, not one the code guesses.
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
from .recon import TERMINAL_STAGE_STATES

# `assets-inventory.md` is the name one real engagement shipped; accept both.
INVENTORY_FILES = ("asset-inventory.md", "assets-inventory.md")
FINDINGS_FILE = Path("notes") / "findings-live.md"
HYPOTHESES_FILE = Path("hypotheses.md")
TRAFFIC_DB = Path("traffic") / "flows.db"
STATE_FILE = Path("recon") / "state.json"

# What recon writes under `recon/inventory/`: the accepted scope, one asset per
# line. Read because a live engagement frequently has no hand-written
# `notes/asset-inventory.md` at all. `candidates.jsonl` sits in the same
# directory and is deliberately **not** read -- it holds discoveries that failed
# the scope check, and counting an unauthorised host as an asset would inflate
# `untouched` and deflate `ratio`, the same reason an accepted gap is not
# coverage.
RECON_INVENTORY = Path("recon") / "inventory"
RECON_ASSET_FILES = (
    "scope-targets.txt",
    "scope-hosts.txt",
    "scope-urls.txt",
    "subdomains.txt",
)

# A lead only counts as a conclusion once it is settled.
TERMINAL_LEAD_STATES = {"validated", "killed"}

# The convergence criteria a gate may declare. Nothing here is a default:
# `gate` rejects unknown names so a typo cannot silently drop a threshold.
GATE_PARAMETERS = (
    "min_evidenced_ratio",
    "max_untouched",
    "max_unresolved_leads",
    "require_no_unmatched",
    "max_incomplete_stages",
)

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


def _markdown_inventory(root: Path) -> list[_Asset]:
    """Assets from the hand-written inventory; first usable file wins."""
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


def _recon_inventory(root: Path) -> list[_Asset]:
    """Assets recon already wrote, in the shape recon writes them.

    A live engagement usually has no hand-written inventory; the assets sit
    where recon left them, one host (or URL) per line. Those lines go through
    the same normaliser as inventory cells, because recon writes URLs in the
    scope files. These rows carry no status -- recon does not record one.
    """
    directory = root / RECON_INVENTORY
    assets: list[_Asset] = []
    seen: set[str] = set()
    for name in RECON_ASSET_FILES:
        text = _read_text(directory / name)
        if text is None:
            continue
        for line in text.splitlines():
            host = _normalize_host(line)
            if not host or host in seen:
                continue
            seen.add(host)
            assets.append(_Asset(host, None, f"recon/inventory/{name}"))
    return assets


def _inventory(root: Path) -> list[_Asset]:
    """Every asset the engagement declares: hand-written first, then recon's.

    Merged rather than either/or: the hand-written list is curated but partial,
    and recon's is machine-written but blind to status. On conflict the
    hand-written row survives, so a status never degrades to ``None``.
    """
    assets = _markdown_inventory(root)
    seen = {asset.host for asset in assets}
    for asset in _recon_inventory(root):
        if asset.host in seen:
            continue
        seen.add(asset.host)
        assets.append(asset)
    return assets


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


def _recon_stages(path: Path) -> dict[str, Any] | None:
    """Stage completion from ``recon/state.json``; ``None`` when there is no state.

    ``incomplete`` counts every stage that is not terminal, using recon's own
    terminal set. A missing or unreadable state file yields ``None`` rather than
    a zeroed rollup: "no stages recorded" and "no stages left" are opposite
    facts, and a gate must not read the second out of the first.
    """
    if not path.is_file():
        return None
    try:
        state = load_json(path)
    except ValidationError:
        return None
    stages = state.get("stages")
    if not isinstance(stages, dict):
        return None
    by_state: dict[str, int] = {}
    unfinished: list[str] = []
    for stage_id, stage in stages.items():
        name = stage.get("state") if isinstance(stage, dict) else None
        if not isinstance(name, str) or not name:
            name = "unknown"
        by_state[name] = by_state.get(name, 0) + 1
        if name not in TERMINAL_STAGE_STATES:
            unfinished.append(str(stage_id))
    total = sum(by_state.values())
    terminal = sum(
        count for name, count in by_state.items() if name in TERMINAL_STAGE_STATES
    )
    return {
        "stages": total,
        "terminal": terminal,
        "incomplete": total - terminal,
        "by_state": dict(sorted(by_state.items())),
        # Named, so a failing `max_incomplete_stages` can say which stages to run
        # rather than only how many are left.
        "incomplete_stages": sorted(unfinished),
    }


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
    stages = _recon_stages(root / STATE_FILE)

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
        "recon": stages,
        "unresolved": unresolved,
        "unmatched": unmatched,
        "sources": {
            "inventory": bool(assets),
            "traffic": bool(traffic),
            "findings": bool(findings),
            "leads": bool(leads),
            "state": bool(gaps),
            "recon_stages": stages is not None,
        },
    }


def _gate_ratio(value: Any, name: str) -> float:
    """A declared ratio threshold, rejected unless it lies in ``[0, 1]``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(
            f"{name} must be a number in [0,1], got {value!r}"
        )
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValidationError(f"{name} must be in [0,1], got {value!r}")
    return number


def _gate_count(value: Any, name: str) -> int:
    """A declared count threshold, rejected unless it is non-negative."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            f"{name} must be a non-negative integer, got {value!r}"
        )
    if value < 0:
        raise ValidationError(f"{name} must be non-negative, got {value!r}")
    return value


def gate(
    paths: StackPaths,
    slug: str,
    *,
    min_evidenced_ratio: float | None = None,
    max_untouched: int | None = None,
    max_unresolved_leads: int | None = None,
    require_no_unmatched: bool = False,
    max_incomplete_stages: int | None = None,
    **unknown: Any,
) -> dict[str, Any]:
    """Decide whether ``assess`` meets the convergence criteria the operator set.

    Every criterion is opt-in and inclusive at its boundary (``actual ==
    threshold`` passes). The criteria and what they compare, verbatim:

    - ``min_evidenced_ratio`` (ratio in ``[0, 1]``) -- ``totals.evidenced_ratio
      >= threshold``.
    - ``max_untouched`` (non-negative count) -- ``totals.untouched <= threshold``.
    - ``max_unresolved_leads`` (non-negative count) -- ``len(unresolved) <=
      threshold`` (everything not concluded, whether or not it saw traffic).
    - ``require_no_unmatched`` -- ``len(unmatched) == 0``, i.e. no host seen only
      in traffic is missing from the inventory.
    - ``max_incomplete_stages`` (non-negative count) -- ``recon.incomplete <=
      threshold``: how many recon stages have not reached a terminal state. This
      is the one criterion that ignores the asset list, so a short inventory
      cannot satisfy it by being cheap to cover. With no ``recon/state.json`` the
      check cannot be evaluated and therefore fails: an unmeasurable stage
      budget is not a budget that was met.

    No threshold is required and none is assumed: called without criteria the
    gate returns ``passed=False`` with ``checks == []`` and a ``reason`` saying
    why, so a missing convergence standard can never read as a pass. Unknown
    parameter names and out-of-range values raise ``ValidationError``.
    """
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValidationError(
            f"unknown gate parameter(s): {names}; known: "
            + ", ".join(GATE_PARAMETERS)
        )

    report = assess(paths, slug)
    totals = report["totals"]
    checks: list[dict[str, Any]] = []

    if min_evidenced_ratio is not None:
        threshold = _gate_ratio(min_evidenced_ratio, "min_evidenced_ratio")
        actual = totals["evidenced_ratio"]
        passed = actual >= threshold
        checks.append(
            {
                "name": "min_evidenced_ratio",
                "threshold": threshold,
                "actual": actual,
                "passed": passed,
                "why": (
                    f"evidenced_ratio {actual:.3f} is at or above {threshold:.3f}"
                    if passed
                    else f"evidenced_ratio {actual:.3f} is below {threshold:.3f}"
                ),
            }
        )

    if max_untouched is not None:
        threshold = _gate_count(max_untouched, "max_untouched")
        actual = totals["untouched"]
        passed = actual <= threshold
        checks.append(
            {
                "name": "max_untouched",
                "threshold": threshold,
                "actual": actual,
                "passed": passed,
                "why": (
                    f"untouched {actual} is at most {threshold}"
                    if passed
                    else f"untouched {actual} exceeds {threshold}"
                ),
            }
        )

    if max_unresolved_leads is not None:
        threshold = _gate_count(max_unresolved_leads, "max_unresolved_leads")
        actual = len(report["unresolved"])
        passed = actual <= threshold
        checks.append(
            {
                "name": "max_unresolved_leads",
                "threshold": threshold,
                "actual": actual,
                "passed": passed,
                "why": (
                    f"unresolved {actual} is at most {threshold}"
                    if passed
                    else f"unresolved {actual} exceeds {threshold}"
                ),
            }
        )

    if require_no_unmatched is not False:
        if not isinstance(require_no_unmatched, bool):
            raise ValidationError(
                f"require_no_unmatched must be a boolean, got {require_no_unmatched!r}"
            )
        actual = len(report["unmatched"])
        passed = actual == 0
        checks.append(
            {
                "name": "require_no_unmatched",
                "threshold": 0,
                "actual": actual,
                "passed": passed,
                "why": (
                    "no traffic host is missing from the inventory"
                    if passed
                    else f"{actual} traffic host(s) are absent from the inventory"
                ),
            }
        )

    if max_incomplete_stages is not None:
        threshold = _gate_count(max_incomplete_stages, "max_incomplete_stages")
        recon = report["recon"]
        actual = recon["incomplete"] if recon else None
        passed = actual is not None and actual <= threshold
        if actual is None:
            why = "no recon/state.json to measure recon stages against"
        elif passed:
            why = f"incomplete recon stages {actual} is at most {threshold}"
        else:
            why = f"incomplete recon stages {actual} exceeds {threshold}"
        checks.append(
            {
                "name": "max_incomplete_stages",
                "threshold": threshold,
                "actual": actual,
                "passed": passed,
                "why": why,
            }
        )

    if not checks:
        return {
            "passed": False,
            "checks": [],
            "failing": [],
            "reason": "no gate threshold supplied",
            "report": report,
        }

    failing = [check for check in checks if not check["passed"]]
    return {
        "passed": not failing,
        "checks": checks,
        "failing": failing,
        "reason": None,
        "report": report,
    }
