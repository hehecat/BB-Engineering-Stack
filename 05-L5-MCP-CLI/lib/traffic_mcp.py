#!/usr/bin/env python3
"""stdio MCP server exposing the engagement HTTP traffic store for retrieval.

The recorder (the managed proxy) writes flows into a SQLite store owned by
``bb_stack.traffic``; this server is the read-only side. An agent investigates
captured traffic the way a human pentester revisits a proxy history: scan the
hosts, narrow with a text/status/method filter, pull one flow, and diff two
flows that differ only by identity (the IDOR query).

The server speaks JSON-RPC 2.0 line frames on stdio and implements only the
handshake, ``tools/list`` and ``tools/call`` itself, so it carries no MCP SDK
dependency. ``00-L0-Runtime/mcp_probe.mjs`` documents the client-side shape.

Store location, in priority order:

* ``BB_TRAFFIC_DB`` -- absolute path to the sqlite file (the canonical variable
  the recorder/proxy and ``bb-traffic`` export).
* ``BB_ENGAGEMENT`` -- engagement slug, resolved through
  ``bb_stack.traffic.store_for`` when the absolute path is absent.

Both unset is a configuration error: report it on stderr and exit non-zero. A
set-but-absent file is *not* an error -- it only means no flow has been recorded
yet, so every query answers empty.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Import the runtime without assuming the launcher put its lib on the path.
# The script lives inside the stack, so derive the root from its own location
# first; a stale BB_STACK_ROOT in the environment must not shadow the sibling
# runtime it ships with.
_SCRIPT_ROOT = Path(__file__).resolve().parents[2]
if (_SCRIPT_ROOT / "00-L0-Runtime" / "lib" / "bb_stack").is_dir():
    _STACK_ROOT = _SCRIPT_ROOT
else:
    _STACK_ROOT = Path(os.environ.get("BB_STACK_ROOT") or _SCRIPT_ROOT)
_L0_LIB = _STACK_ROOT / "00-L0-Runtime" / "lib"
if str(_L0_LIB) not in sys.path:
    sys.path.insert(0, str(_L0_LIB))

from bb_stack.errors import StackError, ValidationError  # noqa: E402
from bb_stack.paths import StackPaths  # noqa: E402
from bb_stack.policy import (  # noqa: E402
    ASK,
    DEFAULT_MODE,
    Decision,
    ToolPolicy,
    policy_for,
)
from bb_stack.traffic import (  # noqa: E402
    READ_BYTES_DEFAULT,
    TrafficStore,
    store_for,
)

SERVER_NAME = "traffic"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 200
READ_BYTES_MAX = 1024 * 1024

_WORKFLOW_HINT = (
    "Cheap to expensive: start with list_traffic_hosts for the shape of the "
    "capture, narrow with search_traffic, then read_flow one id. Bodies are "
    "omitted from listings on purpose."
)


class TrafficServer:
    """Owns the store handle and dispatches JSON-RPC requests."""

    def __init__(self, db_path: Path, *, policy: ToolPolicy | None = None):
        self.db_path = db_path
        self.policy = policy if policy is not None else ToolPolicy.default()
        self._store: TrafficStore | None = None

    # -- store -----------------------------------------------------------

    def store(self) -> TrafficStore | None:
        """The open store, or None while no flow has been recorded yet."""
        if self._store is not None:
            return self._store
        if not self.db_path.is_file():
            return None
        self._store = TrafficStore(self.db_path, create=False)
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def _empty(self, note: str) -> dict[str, Any]:
        return {"note": note, "db": str(self.db_path)}

    # -- tool implementations -------------------------------------------

    def list_hosts(self, arguments: dict[str, Any]) -> Any:
        store = self.store()
        if store is None:
            return {"hosts": [], **self._empty("no traffic recorded yet")}
        hosts = store.hosts()
        return {"hosts": hosts, "count": len(hosts), "db": str(self.db_path)}

    def search(self, arguments: dict[str, Any]) -> Any:
        limit = _coerce_int(arguments.get("limit"), SEARCH_LIMIT_DEFAULT)
        limit = max(1, min(limit, SEARCH_LIMIT_MAX))
        # `text` is an FTS query; an empty string is not a valid MATCH argument.
        text = _coerce_str(arguments.get("text")) or None
        status = arguments.get("status")
        status = None if status is None else _coerce_int(status, None)
        filters = {
            "host": _coerce_str(arguments.get("host")) or None,
            "path_contains": _coerce_str(arguments.get("path_contains")) or None,
            "method": _coerce_str(arguments.get("method")) or None,
            "status": status,
            "client": _coerce_str(arguments.get("client")) or None,
            "text": text,
            "since": _coerce_str(arguments.get("since")) or None,
            "until": _coerce_str(arguments.get("until")) or None,
            "limit": limit,
        }
        store = self.store()
        if store is None:
            return {"count": 0, "limit": limit, "flows": [], **self._empty("no traffic recorded yet")}
        summaries = store.search(**filters)
        return {
            "count": len(summaries),
            "limit": limit,
            "db": str(self.db_path),
            "flows": [
                {
                    "id": item.id,
                    "url": item.url,
                    "method": item.method,
                    "host": item.host,
                    "path": item.path,
                    "query": item.query,
                    "status": item.status,
                    "content_type": item.content_type,
                    "client": item.client,
                    "source": item.source,
                    "started_at": item.started_at,
                    "request_bytes": item.request_bytes,
                    "response_bytes": item.response_bytes,
                    "duration_ms": item.duration_ms,
                }
                for item in summaries
            ],
        }

    def read_flow(self, arguments: dict[str, Any]) -> Any:
        flow_id = _require_int(arguments, "id")
        max_bytes = _coerce_int(arguments.get("max_bytes"), READ_BYTES_DEFAULT)
        max_bytes = max(1, min(max_bytes, READ_BYTES_MAX))
        raw = bool(arguments.get("raw", False))
        store = self.store()
        if store is None:
            raise _ToolError(f"no traffic recorded yet; unknown flow id: {flow_id}")
        return {
            "db": str(self.db_path),
            "flow": store.read(flow_id, max_bytes=max_bytes, raw=raw),
        }

    def stats(self, arguments: dict[str, Any]) -> Any:
        store = self.store()
        if store is None:
            return {**self._empty("no traffic recorded yet"), "stats": store_stats_empty(self.db_path)}
        return {"stats": store.stats()}

    def diff(self, arguments: dict[str, Any]) -> Any:
        first = _require_int(arguments, "first")
        second = _require_int(arguments, "second")
        store = self.store()
        if store is None:
            raise _ToolError("no traffic recorded yet; nothing to diff")
        return store.diff(first, second)

    # -- dispatch --------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        handlers = {
            "list_traffic_hosts": self.list_hosts,
            "search_traffic": self.search,
            "read_flow": self.read_flow,
            "traffic_stats": self.stats,
            "diff_flows": self.diff,
        }
        handler = handlers.get(name)
        if handler is None:
            raise _ToolError(f"unknown tool: {name}")
        return handler(arguments)


class _ToolError(Exception):
    """A tool-level failure surfaced to the caller as `isError`."""


def store_stats_empty(db_path: Path) -> dict[str, Any]:
    from bb_stack.traffic import SCHEMA_VERSION

    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(db_path),
        "flows": 0,
        "hosts": 0,
        "pending": 0,
        "by_client": {},
        "by_status": {},
    }


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise _ToolError(f"expected a string, got {type(value).__name__}")


def _coerce_int(value: Any, default: int | None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        raise _ToolError("expected an integer, got boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise _ToolError(f"expected an integer, got {value!r}")


def _require_int(arguments: dict[str, Any], key: str) -> int:
    if key not in arguments:
        raise _ToolError(f"missing required parameter: {key}")
    value = _coerce_int(arguments.get(key), None)
    if not isinstance(value, int):
        raise _ToolError(f"parameter {key} must be an integer")
    return value


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "list_traffic_hosts",
        "Start here. One rollup row per captured host (flow count, distinct "
        "paths, pending responses, first/last seen) so you see the shape of the "
        "capture before pulling any flow. " + _WORKFLOW_HINT,
        {},
        [],
    ),
    _tool(
        "search_traffic",
        "Find captured flows by filter, newest first, returning summaries only "
        "(never bodies). Filter by host, path substring, method, response "
        "status, client identity, time window, or a full-text query across "
        "request/response text ('text', SQLite FTS syntax) to hunt hidden "
        "parameters and forgotten endpoints. Use it after list_traffic_hosts to "
        "narrow down, then read_flow the id that matters. Each result carries "
        "the full URL and id.",
        {
            "host": {"type": "string", "description": "exact host match"},
            "path_contains": {"type": "string", "description": "substring of the path"},
            "method": {"type": "string", "description": "HTTP method, case-insensitive"},
            "status": {"type": "integer", "description": "exact response status code"},
            "client": {"type": "string", "description": "recording client/identity"},
            "text": {"type": "string", "description": "full-text query over request and response bodies/headers"},
            "since": {"type": "string", "description": "ISO8601 lower bound on started_at"},
            "until": {"type": "string", "description": "ISO8601 upper bound on started_at"},
            "limit": {"type": "integer", "description": f"max rows (default {SEARCH_LIMIT_DEFAULT}, cap {SEARCH_LIMIT_MAX})"},
        },
        [],
    ),
    _tool(
        "read_flow",
        "Read one captured flow in full by id: request/response headers, bodies, "
        "status, timing. Bodies are capped at max_bytes and flagged "
        "body_truncated; raise max_bytes only when the slice you already have is "
        "not enough. Set raw=true to get base64 bodies instead of decoded text. "
        "Use it last, once search_traffic has given you an id.",
        {
            "id": {"type": "integer", "description": "flow id from search_traffic"},
            "max_bytes": {"type": "integer", "description": f"body cap (default {READ_BYTES_DEFAULT})"},
            "raw": {"type": "boolean", "description": "return base64 bodies instead of decoded text"},
        },
        ["id"],
    ),
    _tool(
        "traffic_stats",
        "Capture-wide counters: number of flows/hosts, pending responses, and "
        "breakdowns by client identity and response status. Use it to confirm a "
        "capture is populated and to spot identities/statuses before filtering.",
        {},
        [],
    ),
    _tool(
        "diff_flows",
        "Compare two flows field by field (method, URL, status, every request and "
        "response header, response body) and report exactly what changed. This is "
        "the IDOR / broken-authorization query: diff the same request made as two "
        "different identities, or two replays, and a changed cookie, "
        "authorization header, or body reveals the difference in access.",
        {
            "first": {"type": "integer", "description": "first flow id"},
            "second": {"type": "integer", "description": "second flow id"},
        },
        ["first", "second"],
    ),
]

TOOL_NAMES = {tool["name"] for tool in TOOLS}

# Every tool this server exposes only *reads* engagement state -- the recorder
# owns the store, not us. They all join the policy's read-only set so the
# shipped posture ("read-only passes, everything else asks") stays usable: the
# policy's generic read-only patterns (`list_hosts`, `search`, ...) do not match
# this server's names on their own.
READ_ONLY_TOOLS: tuple[str, ...] = tuple(tool["name"] for tool in TOOLS)


def _augment_read_only(base: ToolPolicy) -> ToolPolicy:
    """*base* with this server's read-only tools folded in (defaults kept)."""
    return ToolPolicy(
        mode=base.mode,
        deny=base.deny,
        allow=base.allow,
        read_only=base.read_only
        + tuple(name for name in READ_ONLY_TOOLS if name not in base.read_only),
        source=base.source,
    )


def _resolve_policy() -> ToolPolicy:
    """The engagement policy, with the failure modes the spec pins down.

    * No engagement to resolve (or no ``policy.yaml``) -- the shipped default.
    * A ``policy.yaml`` that cannot be read or parsed -- fail closed: deny
      every call rather than let a broken rule set silently open the server.

    Neither path may take the server down; both log one line to stderr.
    """
    slug = os.environ.get("BB_ENGAGEMENT", "").strip() or None
    try:
        base = policy_for(StackPaths.discover(), slug)
    except ValidationError as error:
        # The file exists but could not be read or parsed. A broken rule set
        # must never silently open the server: deny everything.
        return _fail_closed(str(error))
    except StackError as error:
        print(f"bb-traffic-mcp: no engagement policy ({error}); using defaults", file=sys.stderr)
        base = ToolPolicy.default()
    except Exception as error:  # noqa: BLE001 - unknown trouble also fails closed
        return _fail_closed(str(error))
    return _augment_read_only(base)


def _fail_closed(detail: str) -> ToolPolicy:
    print(
        f"bb-traffic-mcp: policy unreadable ({detail}); denying every call "
        "(fail-closed)",
        file=sys.stderr,
    )
    # No read-only augmentation on purpose: fail-closed means *nothing* runs.
    return ToolPolicy(
        mode=DEFAULT_MODE, deny=(), allow=(), read_only=(), source="fail-closed"
    )


def _resolve_db_path() -> Path:
    explicit = os.environ.get("BB_TRAFFIC_DB", "").strip()
    if explicit:
        return Path(explicit)
    slug = os.environ.get("BB_ENGAGEMENT", "").strip()
    if slug:
        return store_for(StackPaths.discover(), slug).path
    print(
        "bb-traffic-mcp: no traffic store configured; set BB_TRAFFIC_DB to the "
        "sqlite file (or BB_ENGAGEMENT to the engagement slug)",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _content(payload: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": False,
    }


def _error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _policy_denial(name: str, decision: Decision) -> str:
    """The `isError` text for a call the policy refused."""
    if decision.behavior == ASK:
        return (
            f"policy asks to confirm {name!r} and this stdio server has no "
            "interactive channel; denied (fail-closed)"
        )
    reason = decision.reason or decision.behavior
    detail = decision.message or f"tool {name!r} denied by engagement policy"
    if reason == "fail-closed":
        return (
            f"policy asked to confirm {name!r} but no interactive channel "
            f"exists; denied (fail-closed): {detail}"
        )
    return f"policy denied {name!r} [{reason}]: {detail}"


def _annotated(payload: Any, decision: Decision) -> Any:
    """*payload* with the rewrite that produced it recorded under `policy`."""
    note = {"effective_arguments": decision.updated_input, "reason": decision.reason}
    if isinstance(payload, dict):
        return {**payload, "policy": note}
    return {"policy": note, "result": payload}


def _handle(server: TrafficServer, request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    if method == "initialize":
        params = request.get("params") or {}
        requested = params.get("protocolVersion")
        protocol = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
        result = {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        return {"result": result}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return {}  # notifications carry no id and get no response
    if method == "ping":
        return {"result": {}}
    if method == "tools/list":
        return {"result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {"result": _error("tools/call arguments must be an object")}
        if name not in TOOL_NAMES:
            return {"result": _error(f"unknown tool: {name}")}
        # Policy gate runs before the handler; an exception here must not crash
        # the server, so it fails closed with the reason on stderr.
        try:
            decision = server.policy.evaluate(name, arguments)
        except Exception as error:  # noqa: BLE001 - policy trouble fails closed
            print(f"bb-traffic-mcp: policy failed for {name!r}: {error}", file=sys.stderr)
            return {
                "result": _error(
                    f"policy evaluation failed for {name!r}: {error}; denied (fail-closed)"
                )
            }
        if not decision.allowed:
            return {"result": _error(_policy_denial(name, decision))}
        # An allow rule may rewrite the arguments (the rewrite is surfaced in
        # the result under `policy`, never applied silently).
        effective = decision.updated_input if decision.updated_input is not None else arguments
        try:
            payload = server.call(name, effective)
        except _ToolError as error:
            return {"result": _error(str(error))}
        except StackError as error:
            return {"result": _error(f"{error.__class__.__name__}: {error}")}
        if decision.updated_input is not None:
            payload = _annotated(payload, decision)
        return {"result": _content(payload)}
    raise _MethodNotFound(method or "")


class _MethodNotFound(Exception):
    pass


def _respond(request: dict[str, Any], outcome: dict[str, Any], *, error: bool = False) -> None:
    if "id" not in request:
        return
    envelope: dict[str, Any] = {"jsonrpc": "2.0", "id": request["id"]}
    envelope.update(outcome)
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    db_path = _resolve_db_path()
    server = TrafficServer(db_path, policy=_resolve_policy())
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                print(f"bb-traffic-mcp: skipping non-JSON line: {line[:120]}", file=sys.stderr)
                continue
            if not isinstance(request, dict):
                continue
            try:
                outcome = _handle(server, request)
            except _MethodNotFound as error:
                _respond(
                    request,
                    {"error": {"code": -32601, "message": f"method not found: {error}"}},
                )
                continue
            except Exception as error:  # pragma: no cover - defensive
                _respond(
                    request,
                    {"error": {"code": -32603, "message": f"internal error: {error}"}},
                )
                continue
            if outcome:
                _respond(request, outcome)
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:  # pragma: no cover - defensive
        print(f"bb-traffic-mcp: {error}", file=sys.stderr)
        raise SystemExit(1)
