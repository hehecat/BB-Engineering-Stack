"""Engagement HTTP traffic store.

Recon keeps tool output; this keeps the wire. Every request the agent or the
managed browser makes lands here, and the agent reads it back through search --
so hidden parameters, cross-request identity leaks, and ignored endpoints can be
found in traffic that was already captured, instead of only in whatever the last
tool call happened to print.

One SQLite file per engagement (`<engagement>/traffic/flows.db`) keeps the store
bound to the work unit, outside the source repository, and beside the L3 state
that already scopes a target. FTS5 indexes the decoded bodies and headers so a
search is a query rather than a re-scan of files.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .paths import StackPaths

SCHEMA_VERSION = 1

# Decoded bodies are indexed for search; the raw bytes stay in the row. Bodies
# beyond this are indexed only up to the cap so one large download cannot make
# the index itself the problem.
INDEX_TEXT_LIMIT = 256 * 1024

# `read` returns this much body by default. A response body is evidence, not
# context: pull the slice you need rather than the whole artifact.
READ_BYTES_DEFAULT = 16 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class FlowRecord:
    """One captured request/response pair, as the recorder hands it over."""

    method: str
    host: str
    path: str
    scheme: str = "https"
    port: int | None = None
    query: str = ""
    http_version: str = "HTTP/1.1"
    client: str = "agent"
    source: str = ""
    started_at: str = field(default_factory=_now)
    duration_ms: int | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: bytes = b""
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: bytes = b""
    engagement: str = ""

    @property
    def url(self) -> str:
        netloc = self.host if self.port is None else f"{self.host}:{self.port}"
        suffix = f"?{self.query}" if self.query else ""
        return f"{self.scheme}://{netloc}{self.path}{suffix}"


@dataclass(frozen=True)
class FlowSummary:
    """A row as listed by `search`: no bodies, so a listing stays cheap."""

    id: int
    started_at: str
    client: str
    method: str
    host: str
    path: str
    query: str
    status: int | None
    content_type: str
    request_bytes: int
    response_bytes: int
    duration_ms: int | None
    source: str

    @property
    def url(self) -> str:
        suffix = f"?{self.query}" if self.query else ""
        return f"{self.method} {self.host}{self.path}{suffix}"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    client TEXT NOT NULL DEFAULT 'agent',
    source TEXT NOT NULL DEFAULT '',
    scheme TEXT NOT NULL DEFAULT 'https',
    method TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER,
    path TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    http_version TEXT NOT NULL DEFAULT 'HTTP/1.1',
    request_headers TEXT NOT NULL DEFAULT '{}',
    request_headers_text TEXT NOT NULL DEFAULT '',
    request_body BLOB,
    request_text TEXT NOT NULL DEFAULT '',
    response_status INTEGER,
    response_headers TEXT NOT NULL DEFAULT '{}',
    response_headers_text TEXT NOT NULL DEFAULT '',
    response_body BLOB,
    response_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    request_bytes INTEGER NOT NULL DEFAULT 0,
    response_bytes INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS flows_host ON flows(host);
CREATE INDEX IF NOT EXISTS flows_status ON flows(response_status);
CREATE INDEX IF NOT EXISTS flows_started ON flows(started_at);
CREATE INDEX IF NOT EXISTS flows_method ON flows(method);
CREATE INDEX IF NOT EXISTS flows_client ON flows(client);

CREATE VIRTUAL TABLE IF NOT EXISTS flows_fts USING fts5(
    host, path, query, request_headers_text, request_text,
    response_headers_text, response_text,
    content='flows', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS flows_ai AFTER INSERT ON flows BEGIN
    INSERT INTO flows_fts(rowid, host, path, query, request_headers_text, request_text, response_headers_text, response_text)
    VALUES (new.id, new.host, new.path, new.query, new.request_headers_text, new.request_text, new.response_headers_text, new.response_text);
END;
CREATE TRIGGER IF NOT EXISTS flows_ad AFTER DELETE ON flows BEGIN
    INSERT INTO flows_fts(flows_fts, rowid, host, path, query, request_headers_text, request_text, response_headers_text, response_text)
    VALUES ('delete', old.id, old.host, old.path, old.query, old.request_headers_text, old.request_text, old.response_headers_text, old.response_text);
END;
CREATE TRIGGER IF NOT EXISTS flows_au AFTER UPDATE ON flows BEGIN
    INSERT INTO flows_fts(flows_fts, rowid, host, path, query, request_headers_text, request_text, response_headers_text, response_text)
    VALUES ('delete', old.id, old.host, old.path, old.query, old.request_headers_text, old.request_text, old.response_headers_text, old.response_text);
    INSERT INTO flows_fts(rowid, host, path, query, request_headers_text, request_text, response_headers_text, response_text)
    VALUES (new.id, new.host, new.path, new.query, new.request_headers_text, new.request_text, new.response_headers_text, new.response_text);
END;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _decode_body(body: bytes, content_type: str) -> str:
    """Text form of a body for indexing and for `read` without a restart."""
    if not body:
        return ""
    chunk = body[:INDEX_TEXT_LIMIT]
    lowered = (content_type or "").lower()
    if any(
        marker in lowered
        for marker in ("application/octet-stream", "image/", "video/", "audio/", "font/")
    ):
        return ""
    for encoding in ("utf-8", "latin-1"):
        try:
            return chunk.decode(encoding, errors="replace")
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def _fts_query(text: str) -> str | None:
    """Turn free text into an FTS5 query that cannot be a syntax error.

    Raw text goes straight to FTS5 otherwise, where `-`, `:`, `(` and friends
    are operators -- searching for a header name like `X-Internal-Debug`, or a
    URL fragment, would raise `no such column: Debug` instead of searching.
    Every whitespace-separated term becomes its own quoted phrase joined by AND,
    so punctuation is literal and multi-word input still means "all of these".
    """
    terms = [term for term in text.split() if term]
    if not terms:
        return None
    return " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _content_type(headers: dict[str, str]) -> str:
    for name, value in headers.items():
        if name.lower() == "content-type":
            return value
    return ""


def _header_text(headers: dict[str, str]) -> str:
    """Header block as searchable text, one `Name: value` per line.

    A token that only ever appears in a header -- a bearer token, a session
    cookie, an internal `X-` header -- is exactly what is worth finding across
    flows, so headers are indexed rather than stored opaquely.
    """
    return "\n".join(f"{name}: {value}" for name, value in headers.items())


class TrafficStore:
    """SQLite-backed capture for one engagement."""

    def __init__(self, path: Path, *, create: bool = True):
        self.path = Path(path)
        if not create and not self.path.is_file():
            raise ValidationError(f"traffic store not found: {self.path}")
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
            # Traffic carries cookies, tokens, and session identifiers.
            os.chmod(self.path, 0o600)

    # -- writing ---------------------------------------------------------

    def record(self, flow: FlowRecord) -> int:
        request_content_type = _content_type(flow.request_headers)
        response_content_type = _content_type(flow.response_headers)
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO flows (
                    engagement, started_at, client, source, scheme, method, host,
                    port, path, query, http_version, request_headers,
                    request_headers_text, request_body, request_text,
                    response_status, response_headers, response_headers_text,
                    response_body, response_text, content_type, request_bytes,
                    response_bytes, duration_ms
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    flow.engagement,
                    flow.started_at,
                    flow.client,
                    flow.source,
                    flow.scheme,
                    flow.method,
                    flow.host,
                    flow.port,
                    flow.path,
                    flow.query,
                    flow.http_version,
                    json.dumps(flow.request_headers),
                    _header_text(flow.request_headers),
                    sqlite3.Binary(flow.request_body),
                    _decode_body(flow.request_body, request_content_type),
                    flow.response_status,
                    json.dumps(flow.response_headers),
                    _header_text(flow.response_headers),
                    sqlite3.Binary(flow.response_body),
                    _decode_body(flow.response_body, response_content_type),
                    response_content_type,
                    len(flow.request_body),
                    len(flow.response_body),
                    flow.duration_ms,
                ),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    # -- reading ---------------------------------------------------------

    def search(
        self,
        *,
        host: str | None = None,
        path_contains: str | None = None,
        method: str | None = None,
        status: int | None = None,
        client: str | None = None,
        text: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> list[FlowSummary]:
        """List matching flows, newest first, without their bodies."""
        if limit < 1:
            raise ValidationError("search limit must be at least 1")
        clauses: list[str] = []
        parameters: list[Any] = []
        joins = ""
        if text:
            match = _fts_query(text)
            if match is not None:
                joins = " JOIN flows_fts ON flows_fts.rowid = flows.id"
                clauses.append("flows_fts MATCH ?")
                parameters.append(match)
        if host:
            clauses.append("flows.host = ?")
            parameters.append(host)
        if path_contains:
            clauses.append("flows.path LIKE ?")
            parameters.append(f"%{path_contains}%")
        if method:
            clauses.append("UPPER(flows.method) = ?")
            parameters.append(method.upper())
        if status is not None:
            clauses.append("flows.response_status = ?")
            parameters.append(status)
        if client:
            clauses.append("flows.client = ?")
            parameters.append(client)
        if since:
            clauses.append("flows.started_at >= ?")
            parameters.append(since)
        if until:
            clauses.append("flows.started_at <= ?")
            parameters.append(until)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            "SELECT flows.* FROM flows" + joins + where
            + " ORDER BY flows.started_at DESC, flows.id DESC LIMIT ?"
        )
        parameters.append(min(limit, 1000))
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [self._summary(row) for row in rows]

    @staticmethod
    def _summary(row: sqlite3.Row) -> FlowSummary:
        return FlowSummary(
            id=row["id"],
            started_at=row["started_at"],
            client=row["client"],
            method=row["method"],
            host=row["host"],
            path=row["path"],
            query=row["query"],
            status=row["response_status"],
            content_type=row["content_type"],
            request_bytes=row["request_bytes"],
            response_bytes=row["response_bytes"],
            duration_ms=row["duration_ms"],
            source=row["source"],
        )

    def read(
        self, flow_id: int, *, max_bytes: int = READ_BYTES_DEFAULT, raw: bool = False
    ) -> dict[str, Any]:
        """One flow in full, with bodies capped unless `raw` is set."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM flows WHERE id = ?", (flow_id,)
            ).fetchone()
        if row is None:
            raise ValidationError(f"unknown flow id: {flow_id}")
        request_body = bytes(row["request_body"] or b"")
        response_body = bytes(row["response_body"] or b"")
        result: dict[str, Any] = {
            "id": row["id"],
            "engagement": row["engagement"],
            "started_at": row["started_at"],
            "client": row["client"],
            "source": row["source"],
            "request": {
                "method": row["method"],
                "url": f"{row['scheme']}://{row['host']}{row['path']}"
                + (f"?{row['query']}" if row["query"] else ""),
                "http_version": row["http_version"],
                "headers": json.loads(row["request_headers"]),
                "bytes": row["request_bytes"],
            },
            "response": {
                "status": row["response_status"],
                "headers": json.loads(row["response_headers"]),
                "content_type": row["content_type"],
                "bytes": row["response_bytes"],
            },
            "duration_ms": row["duration_ms"],
        }
        for label, body, text in (
            ("request", request_body, row["request_text"]),
            ("response", response_body, row["response_text"]),
        ):
            section = result[label]
            if raw:
                section["body_base64"] = base64.b64encode(body).decode("ascii")
                continue
            if len(body) > max_bytes:
                section["body"] = (text or "")[:max_bytes]
                section["body_truncated"] = True
                section["body_bytes"] = len(body)
            else:
                section["body"] = text
        return result

    def hosts(self) -> list[dict[str, Any]]:
        """Per-host rollup: the shape an operator scans before drilling in."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT host,
                       COUNT(*) AS flows,
                       COUNT(DISTINCT path) AS paths,
                       SUM(CASE WHEN response_status IS NULL THEN 1 ELSE 0 END) AS pending,
                       MIN(started_at) AS first_seen,
                       MAX(started_at) AS last_seen
                FROM flows GROUP BY host ORDER BY flows DESC, host ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            totals = self._connection.execute(
                """
                SELECT COUNT(*) AS flows,
                       COUNT(DISTINCT host) AS hosts,
                       SUM(CASE WHEN response_status IS NULL THEN 1 ELSE 0 END) AS pending
                FROM flows
                """
            ).fetchone()
            per_client = self._connection.execute(
                "SELECT client, COUNT(*) AS flows FROM flows GROUP BY client"
            ).fetchall()
            per_status = self._connection.execute(
                """
                SELECT response_status AS status, COUNT(*) AS flows FROM flows
                GROUP BY response_status ORDER BY flows DESC
                """
            ).fetchall()
            schema = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        return {
            "schema_version": int(schema["value"]) if schema else SCHEMA_VERSION,
            "path": str(self.path),
            "flows": totals["flows"],
            "hosts": totals["hosts"],
            "pending": totals["pending"],
            "by_client": {row["client"]: row["flows"] for row in per_client},
            "by_status": {
                str(row["status"]): row["flows"] for row in per_status
            },
        }

    def diff(self, first_id: int, second_id: int) -> dict[str, Any]:
        """Compare two flows: what changed between two identities or replays.

        Cross-user and cross-replay comparison is the mechanic behind IDOR and
        broken-authorization findings, so it is a first-class query rather than
        something the agent has to eyeball.
        """
        first = self.read(first_id, max_bytes=INDEX_TEXT_LIMIT)
        second = self.read(second_id, max_bytes=INDEX_TEXT_LIMIT)

        def _flatten(flow: dict[str, Any]) -> dict[str, Any]:
            flat = {
                "method": flow["request"]["method"],
                "url": flow["request"]["url"],
                "status": flow["response"]["status"],
            }
            for name, value in flow["request"]["headers"].items():
                flat[f"req:{name.lower()}"] = value
            for name, value in flow["response"]["headers"].items():
                flat[f"res:{name.lower()}"] = value
            flat["response.body"] = flow["response"].get("body", "")
            return flat

        left, right = _flatten(first), _flatten(second)
        changed = {}
        for key in sorted(set(left) | set(right)):
            if left.get(key) != right.get(key):
                changed[key] = {"first": left.get(key), "second": right.get(key)}
        return {
            "first": first_id,
            "second": second_id,
            "identical": not changed,
            "changed": changed,
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> TrafficStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def store_for(paths: StackPaths, slug: str) -> TrafficStore:
    """Open the store belonging to one engagement."""
    root = paths.engagement(slug)
    return TrafficStore(root / "traffic" / "flows.db")
