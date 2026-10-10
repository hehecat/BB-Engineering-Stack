"""Record proxied HTTP/HTTPS traffic into an engagement's traffic store.

`bb_stack.traffic` is the store; this module is the recorder. It is a
[mitmproxy addon](https://docs.mitmproxy.org/stable/addons-overview/), so every
request and response that the agent or the managed browser sends through the
proxy is written to `<engagement>/traffic/flows.db` and can be read back with
`bb-stack traffic search|read|hosts|stats|diff`.

Run it through the stack wrapper (it resolves the engagement and exports the
store path for you)::

    bb-traffic --engagement <slug>

or standalone, with the store path passed explicitly::

    mitmdump -s 00-L0-Runtime/lib/bb_stack/traffic_proxy.py \
        --set bb_traffic_db=/abs/path/engagements/<slug>/traffic/flows.db

Decisions worth knowing before reading the code:

* **Configuration channel.** The mitmproxy option ``bb_traffic_db`` (settable
  with ``--set bb_traffic_db=<flows.db>``) is authoritative, and ``BB_TRAFFIC_DB``
  only supplies its default. One mechanism owns the value, and an operator who
  starts mitmdump by hand gets the same behaviour as the wrapper. Likewise
  ``bb_traffic_engagement`` (default ``BB_ENGAGEMENT``) resolves the store
  through ``traffic.store_for`` when no db path was given.
* **Repeated headers** are joined with ``, `` in wire order, per RFC 7230
  section 3.2.2, and the first spelling of the field name wins. ``set-cookie`` is
  the known lossy case: ``, `` also appears inside an ``Expires`` attribute, and
  a ``dict[str, str]`` has nowhere else to put the second value.
* **Bodies** are capped at ``MAX_BODY_BYTES`` per direction. A response that
  declares a larger body is streamed by mitmproxy (``flow.response.stream``) so
  the proxy never holds a whole download in memory; uncompressed streams are
  tapped so the leading ``MAX_BODY_BYTES`` are still captured, compressed ones
  keep only the metadata. The trade-off is explicit: for such a flow no other
  addon sees a buffered response body either. A request body is never streamed
  (huge uploads are not the case this store exists for) and is simply truncated.
  Truncation and capture failures are recorded in ``source`` as
  ``truncated=request`` / ``truncated=response`` so a stored body is never
  mistaken for a whole one.
* **client** cannot be proven: mitmproxy sees a proxied TCP peer, not a process
  (no ``SO_PEERCRED`` on a forwarded connection). The label is therefore a
  heuristic -- a listener port named in ``bb_traffic_browser_ports`` wins,
  otherwise a browser ``User-Agent`` marker, otherwise ``agent`` -- and the raw
  connection facts (listen address, client address, ALPN) are kept in ``source``
  so the guess can be checked and corrected later.
* The addon is **fail-open**: every hook swallows its own errors, so a broken
  store can never take the proxy (and therefore the engagement's traffic) down.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # mitmproxy is only needed when the addon is actually run by the proxy.
    from mitmproxy import ctx
except ImportError:  # pragma: no cover - lets tests and tooling import this file
    ctx = None  # type: ignore[assignment]

LOG = logging.getLogger("bb_stack.traffic_proxy")

MAX_BODY_BYTES = 2 * 1024 * 1024
"""Per-direction cap on the body bytes handed to the store.

Chosen as "more than any API response an assessment cares about, little enough
that a stray media download cannot bloat the db". Bodies above it are truncated
(or, for a declared-huge response, never buffered by mitmproxy at all) and the
loss is marked in ``source``.
"""

BROWSER_UA_MARKERS = (
    "mozilla/",
    "headlesschrome",
    "chrome/",
    "chromium/",
    "firefox/",
    "gecko/",
    "safari/",
    "edg/",
    "opr/",
)

_ERROR_TEXT_LIMIT = 160


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    """``getattr`` for duck-typed flows; mitmproxy objects are not always set."""
    return getattr(value, name, default) if value is not None else default


# -- field extraction -----------------------------------------------------


def _header_value(headers: Any, name: str) -> str | None:
    """One header value, case-insensitively, or ``None``."""
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    if value is not None:
        return str(value)
    try:
        items = headers.items()
    except AttributeError:
        return None
    for key, item in items:
        if str(key).lower() == name:
            return str(item)
    return None


def _headers_to_dict(headers: Any) -> dict[str, str]:
    """Headers as ``dict[str, str]``, repeats joined per RFC 7230 3.2.2."""
    merged: dict[str, str] = {}
    spelling: dict[str, str] = {}
    if headers is None:
        return merged
    for name, value in headers.items():
        key = spelling.setdefault(str(name).lower(), str(name))
        if key in merged:
            merged[key] = f"{merged[key]}, {value}"
        else:
            merged[key] = str(value)
    return merged


def _content_length(headers: Any) -> int | None:
    value = _header_value(headers, "content-length")
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _is_encoded(headers: Any) -> bool:
    value = _header_value(headers, "content-encoding")
    return value is not None and value.strip().lower() not in ("", "identity")


def _split_target(target: str) -> tuple[str, str]:
    """Split a request target into ``(path, query)``.

    ``Request.path`` is normally origin-form (``/a/b?c=d``, or ``*`` for
    ``OPTIONS``), but a proxied request line may still carry the absolute form;
    both land in the store as a path plus a raw query string.
    """
    if target.startswith(("http://", "https://")):
        parts = urlsplit(target)
        return parts.path or "/", parts.query
    path, _, query = target.partition("?")
    return path, query


def _body(message: Any, tapped: bytearray | None = None) -> tuple[bytes, bool]:
    """``(stored body, truncated)`` for one message, bounded by the cap."""
    if message is None:
        return b"", False
    raw = _attribute(message, "raw_content")
    if raw is None:
        if tapped is not None:
            return bytes(tapped), True
        # No content: either the operator streamed this body away, or it is
        # legitimately absent. Only a declared body counts as a loss.
        return b"", bool(_content_length(_attribute(message, "headers")) or 0)
    if len(raw) > MAX_BODY_BYTES:
        if _is_encoded(_attribute(message, "headers")):
            # A prefix of a compressed stream is not decodable and would be
            # indexed as garbage; keep the metadata, drop the bytes.
            return b"", True
        return raw[:MAX_BODY_BYTES], True
    try:
        content = message.get_content(strict=False)
    except Exception:  # mitmproxy raises ValueError on some invalid bodies
        LOG.warning("could not decode body; storing raw bytes", exc_info=True)
        content = raw
    if content is None:
        content = raw
    if len(content) > MAX_BODY_BYTES:
        return content[:MAX_BODY_BYTES], True
    return content, False


def _duration_ms(start: Any, end: Any) -> int | None:
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return max(0, int(round((float(end) - float(start)) * 1000)))


def _iso(timestamp: Any) -> str:
    if not isinstance(timestamp, (int, float)):
        return datetime.now(UTC).isoformat(timespec="milliseconds")
    return datetime.fromtimestamp(float(timestamp), UTC).isoformat(
        timespec="milliseconds"
    )


def _address(value: Any) -> str:
    try:
        host, port = value[0], value[1]
    except (TypeError, IndexError, KeyError):
        return str(value) if value else "?"
    return f"{host}:{port}"


def _clip(text: str, limit: int = _ERROR_TEXT_LIMIT) -> str:
    flattened = " ".join(str(text).split())
    return flattened if len(flattened) <= limit else flattened[: limit - 1] + "\u2026"


def _client_label(flow: Any, browser_ports: frozenset[int]) -> str:
    """Best-effort ``browser`` / ``agent`` label; see the module docstring."""
    connection = _attribute(flow, "client_conn")
    if browser_ports and connection is not None:
        local = _attribute(connection, "sockname")
        try:
            if len(local) > 1 and int(local[1]) in browser_ports:
                return "browser"
        except (TypeError, ValueError):
            pass
    request = _attribute(flow, "request")
    agent = _header_value(_attribute(request, "headers"), "user-agent")
    if agent and any(marker in agent.lower() for marker in BROWSER_UA_MARKERS):
        return "browser"
    return "agent"


def _source(
    flow: Any, *, truncated: list[str] | tuple[str, ...] = (), error: str | None = None
) -> str:
    """Where a recorded flow came from, plus how complete its bodies are."""
    parts = ["mitmproxy"]
    connection = _attribute(flow, "client_conn")
    mode = _attribute(connection, "proxy_mode")
    spec = _attribute(mode, "full_spec")
    if isinstance(spec, str) and spec:
        parts.append(f"mode={spec}")
    listen = _attribute(connection, "sockname")
    if listen:
        parts.append(f"listen={_address(listen)}")
    peer = _attribute(connection, "peername")
    if peer:
        parts.append(f"client={_address(peer)}")
    alpn = _attribute(connection, "alpn")
    if alpn:
        if isinstance(alpn, bytes):
            alpn = alpn.decode("ascii", "replace")
        parts.append(f"alpn={alpn}")
    if truncated:
        parts.append("truncated=" + "+".join(sorted(dict.fromkeys(truncated))))
    if error:
        parts.append("error=" + _clip(error))
    return " ".join(parts)


# -- the store, imported lazily -------------------------------------------


def _stack_library() -> Path:
    return Path(__file__).resolve().parents[1]


def _extend_import_path() -> None:
    """Make the stack's own library importable from mitmproxy's interpreter.

    The proxy runs as an isolated tool (pipx/uv-tool), so neither ``bb_stack``
    nor the ``yaml`` it needs is on its ``sys.path``. Candidates are *appended*,
    never prepended: mitmproxy keeps its own (pinned) dependencies, and only the
    genuinely missing modules come from the stack tree.
    """
    roots = [Path(__file__).resolve().parents[3]]
    declared = os.environ.get("BB_STACK_ROOT")
    if declared:
        roots.append(Path(declared).expanduser())
    candidates: list[Path] = [_stack_library()]
    for root in roots:
        candidates.append(root / "00-L0-Runtime" / "lib")
        venv = root / ".runtime" / "venv"
        candidates.extend(sorted((venv / "lib").glob("python*/site-packages")))
        candidates.append(venv / "Lib" / "site-packages")
    for candidate in candidates:
        text = str(candidate)
        if candidate.is_dir() and text not in sys.path:
            sys.path.append(text)


_STORE_API: tuple[Any, Any, Any, Any] | None = None
_STORE_IMPORT_ERROR: str | None = None


def _store_api() -> tuple[Any, Any, Any, Any] | None:
    """``(FlowRecord, TrafficStore, store_for, StackPaths)`` or ``None``."""
    global _STORE_API, _STORE_IMPORT_ERROR
    if _STORE_API is not None:
        return _STORE_API
    if _STORE_IMPORT_ERROR is not None:
        return None

    def load() -> tuple[Any, Any, Any, Any]:
        from bb_stack.paths import StackPaths
        from bb_stack.traffic import FlowRecord, TrafficStore, store_for

        return FlowRecord, TrafficStore, store_for, StackPaths

    try:
        api = load()
    except ImportError:
        _extend_import_path()
        try:
            api = load()
        except ImportError as error:
            _STORE_IMPORT_ERROR = (
                f"cannot import bb_stack.traffic ({error}); start the proxy with "
                "bb-traffic, or point BB_STACK_ROOT at the stack source tree"
            )
            LOG.error("traffic recording disabled: %s", _STORE_IMPORT_ERROR)
            return None
    _STORE_API = api
    return api


class TrafficRecorder:
    """Turns mitmproxy flows into store rows, one engagement at a time."""

    def __init__(self, store: Any = None) -> None:
        self._lock = threading.Lock()
        self._store = store
        self._taps: dict[str, bytearray] = {}
        self._disabled: str | None = None

    # -- configuration ----------------------------------------------------

    def option(self, name: str, default: str = "") -> str:
        if ctx is None:
            return default
        try:
            value = getattr(ctx.options, name, None)
        except Exception:
            return default
        return value.strip() if isinstance(value, str) else default

    def browser_ports(self) -> frozenset[int]:
        raw = self.option("bb_traffic_browser_ports")
        ports = set()
        for item in raw.split(","):
            item = item.strip()
            if item.isdigit():
                ports.add(int(item))
        return frozenset(ports)

    def reconfigure(self, updated: Any) -> None:
        """Drop the store when its options change; the next flow re-opens it."""
        if {"bb_traffic_db", "bb_traffic_engagement"} & set(updated or ()):
            self.close()
            self._disabled = None

    # -- store lifecycle --------------------------------------------------

    def _open_store(self) -> Any:
        with self._lock:
            if self._store is not None:
                return self._store
            if self._disabled is not None:
                return None
            api = _store_api()
            if api is None:
                self._disabled = _STORE_IMPORT_ERROR or "traffic store unavailable"
                return None
            _, TrafficStore, store_for, StackPaths = api
            path = self.option("bb_traffic_db")
            slug = self.option("bb_traffic_engagement")
            if not path and not slug:
                self._disabled = (
                    "no store configured: pass --set bb_traffic_db=<flows.db> "
                    "(or BB_TRAFFIC_DB), or --set bb_traffic_engagement=<slug>"
                )
                LOG.error("traffic recording disabled: %s", self._disabled)
                return None
            try:
                if path:
                    store = TrafficStore(Path(path).expanduser())
                else:
                    store = store_for(StackPaths.discover(), slug)
            except Exception as error:  # a bad path must not stop the proxy
                self._disabled = f"cannot open traffic store: {error}"
                LOG.error("traffic recording disabled: %s", self._disabled)
                return None
            self._store = store
            LOG.info("recording traffic to %s", _attribute(store, "path", path))
            return store

    def prepare(self) -> None:
        """Open the store during startup so misconfiguration is visible."""
        self._open_store()

    def close(self) -> None:
        with self._lock:
            store, self._store = self._store, None
        if store is not None:
            try:
                store.close()
            except Exception:
                LOG.warning("closing the traffic store failed", exc_info=True)

    # -- recording --------------------------------------------------------

    def install_response_tap(self, flow: Any) -> None:
        """Stream a declared-oversized response, tapping its leading bytes.

        Called from ``responseheaders``. Without this, mitmproxy would buffer the
        whole body (its default) before the ``response`` hook runs; with it the
        body is passed through untouched but never accumulated, except for the
        cap-sized prefix kept when the body is not compressed.
        """
        response = _attribute(flow, "response")
        if response is None:
            return
        declared = _content_length(_attribute(response, "headers"))
        if declared is None or declared <= MAX_BODY_BYTES:
            return
        prefix: bytearray | None = None
        if not _is_encoded(_attribute(response, "headers")):
            prefix = bytearray()
            self._taps[str(_attribute(flow, "id", ""))] = prefix

        def tap(chunk: bytes) -> bytes:
            if prefix is not None and len(prefix) < MAX_BODY_BYTES:
                prefix.extend(chunk[: MAX_BODY_BYTES - len(prefix)])
            return chunk

        response.stream = tap
        LOG.info(
            "streaming %s body of %d bytes (%s)",
            _attribute(flow, "id", "?"),
            declared,
            "keeping a prefix" if prefix is not None else "metadata only",
        )

    def record(self, flow: Any, *, response: Any = None, error: Any = None) -> None:
        """Append one flow to the store; never raise."""
        try:
            store = self._open_store()
            if store is None:
                return
            api = _store_api()
            assert api is not None
            FlowRecord = api[0]
            request = _attribute(flow, "request")
            if response is None:
                response = _attribute(flow, "response")
            error = error if error is not None else _attribute(flow, "error")
            tapped = self._taps.pop(str(_attribute(flow, "id", "")), None)

            truncated: list[str] = []
            request_body, request_truncated = _body(request)
            if request_truncated:
                truncated.append("request")
            response_body, response_truncated = _body(response, tapped)
            if response_truncated:
                truncated.append("response")

            started = _attribute(request, "timestamp_start")
            ended = None
            if response is not None:
                ended = _attribute(response, "timestamp_end")
                if ended is None:
                    ended = _attribute(response, "timestamp_start")
            elif error is not None:
                ended = _attribute(error, "timestamp")
            path, query = _split_target(str(_attribute(request, "path", "") or ""))
            message = _attribute(error, "msg") if error is not None else None

            store.record(
                FlowRecord(
                    method=str(_attribute(request, "method", "") or ""),
                    host=str(_attribute(request, "host", "") or ""),
                    path=path,
                    scheme=str(_attribute(request, "scheme", "") or "https"),
                    port=_attribute(request, "port"),
                    query=query,
                    http_version=str(
                        _attribute(request, "http_version", "") or "HTTP/1.1"
                    ),
                    client=_client_label(flow, self.browser_ports()),
                    source=_source(flow, truncated=truncated, error=message),
                    started_at=_iso(started),
                    duration_ms=_duration_ms(started, ended),
                    request_headers=_headers_to_dict(_attribute(request, "headers")),
                    request_body=request_body,
                    response_status=_attribute(response, "status_code"),
                    response_headers=_headers_to_dict(_attribute(response, "headers")),
                    response_body=response_body,
                    engagement=self.option("bb_traffic_engagement"),
                )
            )
        except Exception:
            LOG.exception("could not record flow; the proxy keeps running")


_RECORDER = TrafficRecorder()


# -- mitmproxy addon entry points -----------------------------------------


def load(loader: Any) -> None:
    """Declare the recorder's options (mitmproxy ``load`` event)."""
    loader.add_option(
        "bb_traffic_db",
        str,
        os.environ.get("BB_TRAFFIC_DB", ""),
        "Path to the engagement traffic store (flows.db) this proxy records into.",
    )
    loader.add_option(
        "bb_traffic_engagement",
        str,
        os.environ.get("BB_ENGAGEMENT", ""),
        "Engagement slug; resolves <engagement>/traffic/flows.db when "
        "bb_traffic_db is unset.",
    )
    loader.add_option(
        "bb_traffic_browser_ports",
        str,
        os.environ.get("BB_TRAFFIC_BROWSER_PORTS", ""),
        "Comma-separated proxy listen ports that belong to the managed browser, "
        "used to label flows as `browser` instead of `agent`.",
    )


def configure(updated: Any) -> None:
    _RECORDER.reconfigure(updated)


def running() -> None:
    """Open the store once the options are final (mitmproxy ``running``)."""
    _RECORDER.prepare()


def done() -> None:
    _RECORDER.close()


def responseheaders(flow: Any) -> None:
    try:
        _RECORDER.install_response_tap(flow)
    except Exception:
        LOG.exception("could not install the response tap")


def response(flow: Any) -> None:
    _RECORDER.record(flow)


def error(flow: Any) -> None:
    """A flow that never got a response: the request itself is the evidence."""
    _RECORDER.record(flow, error=_attribute(flow, "error"))
