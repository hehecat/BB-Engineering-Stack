#!/usr/bin/env python3
"""Contract tests for `bb_stack.traffic`, the engagement HTTP traffic store.

The store is the durable half of traffic capture: a recorder or the managed
browser writes flows, and the agent reads them back through `search`, `read`,
and `diff`. These tests pin the behaviour those callers rely on -- filter
dimensions, the FTS index, body truncation, raw access, cross-flow diffing,
file permissions, and the large/binary body limits.
"""

from __future__ import annotations

import base64
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths
from bb_stack.traffic import (
    INDEX_TEXT_LIMIT,
    SCHEMA_VERSION,
    FlowRecord,
    TrafficStore,
    store_for,
)

JSON = {"Content-Type": "application/json"}


class TrafficStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-traffic-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.slug = "traffic-fixture"
        self.engagement = self.paths.engagements_root / self.slug
        self.engagement.mkdir(parents=True)
        (self.engagement / "engagement.yaml").write_text(
            f"schema_version: 1\nslug: {self.slug}\n", encoding="utf-8"
        )
        self.store = store_for(self.paths, self.slug)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    # -- helpers ---------------------------------------------------------

    def record(self, **overrides: Any) -> int:
        fields: dict[str, Any] = {
            "method": "GET",
            "host": "api.example.invalid",
            "path": "/users/1",
            "response_status": 200,
            "response_headers": dict(JSON),
            "response_body": b'{"id": 1}',
        }
        fields.update(overrides)
        return self.store.record(FlowRecord(**fields))

    def ids(self, **query: Any) -> list[int]:
        return [summary.id for summary in self.store.search(**query)]

    # -- search filters --------------------------------------------------

    def test_search_filters_each_dimension(self) -> None:
        first = self.record(started_at="2024-03-01T10:00:00.000+00:00")
        second = self.record(
            method="POST",
            path="/users",
            client="browser",
            response_status=201,
            started_at="2024-03-01T10:01:00.000+00:00",
        )
        third = self.record(
            host="cdn.example.invalid",
            path="/static/app.js",
            client="browser",
            response_status=304,
            started_at="2024-03-01T10:02:00.000+00:00",
        )
        fourth = self.record(
            path="/admin/export",
            query="role=admin",
            response_status=403,
            started_at="2024-03-01T10:03:00.000+00:00",
        )

        self.assertEqual(self.ids(host="api.example.invalid"), [fourth, second, first])
        self.assertEqual(self.ids(host="cdn.example.invalid"), [third])
        self.assertEqual(self.ids(path_contains="/users"), [second, first])
        # Method matching is case-insensitive; the CLI passes whatever the
        # operator typed.
        self.assertEqual(self.ids(method="get"), [fourth, third, first])
        self.assertEqual(self.ids(status=304), [third])
        self.assertEqual(self.ids(client="browser"), [third, second])
        self.assertEqual(
            self.ids(host="api.example.invalid", method="POST"), [second]
        )
        self.assertEqual(self.store.search(status=999), [])

    def test_search_limit_returns_newest_first(self) -> None:
        for index in range(4):
            self.record(started_at=f"2024-03-01T10:0{index}:00.000+00:00")
        newest = self.store.search(limit=2)
        self.assertEqual([summary.started_at for summary in newest], [
            "2024-03-01T10:03:00.000+00:00",
            "2024-03-01T10:02:00.000+00:00",
        ])
        self.assertEqual(len(self.store.search(limit=50)), 4)
        with self.assertRaisesRegex(ValidationError, "at least 1"):
            self.store.search(limit=0)

    def test_search_limit_ceiling_is_one_thousand(self) -> None:
        # `limit` is a page size, and the store clamps it so one listing cannot
        # drag an unbounded result set into the agent's context.
        for index in range(1001):
            self.record(
                path=f"/page/{index}",
                started_at=f"2024-05-01T{index // 3600:02d}:{index // 60 % 60:02d}:{index % 60:02d}.000+00:00",
            )
        capped = self.store.search(limit=5000)
        self.assertEqual(len(capped), 1000)
        self.assertEqual(capped[0].id, 1001)
        self.assertEqual(capped[-1].id, 2)
        self.assertEqual(len(self.store.search(limit=999)), 999)
        self.assertEqual(len(self.store.search(limit=1000)), 1000)
        self.assertEqual(len(self.store.search()), 50)

    def test_search_since_and_until_bound_the_window(self) -> None:
        first = self.record(started_at="2024-03-01T10:00:00.000+00:00")
        second = self.record(started_at="2024-03-01T10:01:00.000+00:00")
        third = self.record(started_at="2024-03-01T10:02:00.000+00:00")
        self.assertEqual(self.ids(since="2024-03-01T10:01:00.000+00:00"), [third, second])
        self.assertEqual(self.ids(until="2024-03-01T10:01:00.000+00:00"), [second, first])
        self.assertEqual(
            self.ids(
                since="2024-03-01T10:00:30.000+00:00",
                until="2024-03-01T10:01:30.000+00:00",
            ),
            [second],
        )

    def test_summary_carries_the_operator_facing_url(self) -> None:
        self.record(path="/admin/export", query="role=admin&page=2")
        summary = self.store.search()[0]
        self.assertEqual(summary.url, "GET api.example.invalid/admin/export?role=admin&page=2")
        self.assertEqual(summary.content_type, "application/json")
        self.assertEqual(summary.response_bytes, len(b'{"id": 1}'))

    # -- FTS index -------------------------------------------------------

    def test_search_text_matches_request_and_response_bodies(self) -> None:
        # The marker tokens appear in no host, path, or query, so a hit proves
        # the decoded bodies are indexed rather than the URL columns alone.
        from_response = self.record(
            response_headers={"Content-Type": "text/html"},
            response_body=b"<html>FindmeResponsetoken marks the body</html>",
        )
        from_request = self.record(
            path="/graphql",
            request_headers=dict(JSON),
            request_body=b'{"query":"Findmerequesttoken"}',
        )
        self.assertEqual(self.ids(text="FindmeResponsetoken"), [from_response])
        self.assertEqual(self.ids(text="findmerequesttoken"), [from_request])
        # The FTS join composes with the structural filters.
        self.assertEqual(
            self.ids(host="api.example.invalid", text="Findmerequesttoken"),
            [from_request],
        )
        self.assertEqual(self.ids(text="nosuchtokenhere"), [])

    def test_search_text_covers_host_path_and_query_columns(self) -> None:
        by_host = self.record(host="reports.example.invalid", path="/index")
        by_path = self.record(path="/internal/debugpanel")
        by_query = self.record(path="/search", query="q=querymarkertoken")
        self.assertEqual(self.ids(text="reports"), [by_host])
        self.assertEqual(self.ids(text="debugpanel"), [by_path])
        self.assertEqual(self.ids(text="querymarkertoken"), [by_query])

    def test_search_text_matches_header_only_tokens(self) -> None:
        # A bearer token, a session cookie, or an internal `X-` header never
        # reaches the body, so the header block is indexed as searchable text of
        # its own, for both directions.
        flow = self.record(
            request_headers={"Authorization": "Bearer lengthyzztokzz"},
            response_headers={
                "X-Internal-Debug": "enabled",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(self.ids(text="lengthyzztokzz"), [flow])
        # A hit is a whole token, not a substring of one.
        self.assertEqual(self.ids(text="lengthyzztok"), [])
        self.assertEqual(self.ids(text="Bearer lengthyzztokzz"), [flow])
        self.assertEqual(self.ids(text="Authorization"), [flow])
        self.assertEqual(self.ids(text="Internal-Debug"), [flow])
        self.assertEqual(self.ids(text="X-Internal-Debug"), [flow])
        self.assertEqual(
            self.store.read(flow)["request"]["headers"]["Authorization"],
            "Bearer lengthyzztokzz",
        )

    def test_search_text_escapes_fts5_operators(self) -> None:
        # Raw text would otherwise reach FTS5 as a query language: `-`, `:`,
        # `(`, and `"` are operators, so `X-Internal-Debug` would raise
        # `no such column: Debug` instead of searching. Escaped terms must be
        # literal and still hit.
        flow = self.record(
            response_headers={"X-Internal-Debug": "1", "Content-Type": "text/html"},
            response_body=b'<a href="/reset-password">Reset</a>',
        )
        for query in ('X-Internal-Debug', "Authorization: Bearer none", "/reset-password", 'weird"quote', "(unbalanced", "AND"):
            with self.subTest(query=query):
                self.assertIsInstance(self.store.search(text=query), list)
        self.assertEqual(self.ids(text="X-Internal-Debug"), [flow])
        self.assertEqual(self.ids(text="/reset-password"), [flow])

    def test_search_text_terms_are_combined_with_and(self) -> None:
        both = self.record(request_headers={"X-Note": "alpha beta"})
        self.record(request_headers={"X-Note": "alpha only"})
        self.assertEqual(self.ids(text="alpha beta"), [both])
        self.assertEqual(len(self.ids(text="alpha")), 2)
        self.assertEqual(self.ids(text="alpha zzznothere"), [])

    def test_blank_search_text_does_not_filter(self) -> None:
        first = self.record(started_at="2024-03-01T10:00:00.000+00:00")
        second = self.record(started_at="2024-03-01T10:01:00.000+00:00")
        self.assertEqual(self.ids(text="   "), [second, first])
        self.assertEqual(self.ids(text=""), [second, first])

    # -- read() ----------------------------------------------------------

    def test_read_truncates_body_and_reports_real_size(self) -> None:
        body = b'{"padding": "' + b"z" * 4096 + b'"}'
        flow = self.record(response_body=body)
        capped = self.store.read(flow, max_bytes=32)["response"]
        self.assertEqual(capped["body"], body.decode()[:32])
        self.assertTrue(capped["body_truncated"])
        self.assertEqual(capped["body_bytes"], len(body))
        self.assertEqual(capped["bytes"], len(body))

        small = self.store.read(self.record(response_body=b"tiny"))["response"]
        self.assertEqual(small["body"], "tiny")
        self.assertNotIn("body_truncated", small)

    def test_read_raw_returns_base64_bodies(self) -> None:
        payload = bytes(range(256))
        flow = self.record(
            request_headers={"Content-Type": "application/octet-stream"},
            request_body=payload,
            response_body=payload,
        )
        result = self.store.read(flow, raw=True)
        self.assertEqual(base64.b64decode(result["request"]["body_base64"]), payload)
        self.assertEqual(base64.b64decode(result["response"]["body_base64"]), payload)
        self.assertNotIn("body", result["response"])

    def test_read_unknown_flow_id_raises(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown flow id"):
            self.store.read(4242)

    # -- diff() ----------------------------------------------------------

    def test_diff_reports_the_cookie_delta(self) -> None:
        # The IDOR workflow compares the same request under two identities, so
        # the cookie is the variable that must surface.
        request = {
            "method": "GET",
            "host": "app.example.invalid",
            "path": "/account",
            "response_status": 200,
            "response_headers": dict(JSON),
            "response_body": b'{"role": "user"}',
        }
        alice = self.record(request_headers={"Cookie": "session=alice"}, **request)
        bob = self.record(request_headers={"Cookie": "session=bob"}, **request)
        delta = self.store.diff(alice, bob)
        self.assertFalse(delta["identical"])
        self.assertEqual(set(delta["changed"]), {"req:cookie"})
        self.assertEqual(delta["changed"]["req:cookie"]["first"], "session=alice")
        self.assertEqual(delta["changed"]["req:cookie"]["second"], "session=bob")

    def test_diff_reports_identical_for_replays(self) -> None:
        request = {
            "method": "GET",
            "host": "app.example.invalid",
            "path": "/account",
            "request_headers": {"Cookie": "session=alice"},
            "response_status": 200,
            "response_headers": dict(JSON),
            "response_body": b'{"role": "user"}',
        }
        first = self.record(**request)
        replay = self.record(**request)
        delta = self.store.diff(first, replay)
        self.assertTrue(delta["identical"])
        self.assertEqual(delta["changed"], {})

        leaked = self.record(**{**request, "response_body": b'{"role": "admin"}'})
        by_body = self.store.diff(replay, leaked)
        self.assertEqual(set(by_body["changed"]), {"response.body"})

    # -- filesystem contract ---------------------------------------------

    def test_store_is_0600_file_in_0700_directory(self) -> None:
        expected = self.engagement / "traffic" / "flows.db"
        self.assertEqual(self.store.path, expected)
        self.assertTrue(expected.is_file())
        self.assertEqual(stat.S_IMODE(expected.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(expected.parent.stat().st_mode), 0o700)

    def test_store_for_targets_the_engagement_traffic_directory(self) -> None:
        self.assertEqual(
            store_for(self.paths, self.slug).path,
            self.paths.engagement(self.slug) / "traffic" / "flows.db",
        )

    def test_missing_store_is_only_opened_explicitly(self) -> None:
        missing = self.engagement / "traffic" / "absent.db"
        with self.assertRaisesRegex(ValidationError, "traffic store not found"):
            TrafficStore(missing, create=False)

    # -- size and media limits -------------------------------------------

    def test_large_body_is_stored_but_indexed_only_up_to_the_cap(self) -> None:
        body = b"ZzBigstarttoken " + b"a" * (300 * 1024) + b" Zzbigendtoken"
        flow = self.record(response_body=body)
        # The write succeeds and the store keeps working.
        self.assertEqual(self.store.stats()["flows"], 1)
        self.assertEqual(self.ids(text="ZzBigstarttoken"), [flow])
        self.assertEqual([host["host"] for host in self.store.hosts()], [
            "api.example.invalid"
        ])
        # Only the first INDEX_TEXT_LIMIT bytes are decoded into the index, so a
        # token past the cap is not searchable even though the bytes are kept.
        self.assertEqual(self.ids(text="Zzbigendtoken"), [])
        # A second write after the large one still lands.
        follow_up = self.record(path="/after", response_body=b"Followuptoken")
        self.assertEqual(self.ids(text="Followuptoken"), [follow_up])

        stored = self.store.read(flow)["response"]
        self.assertEqual(stored["body_bytes"], len(body))
        self.assertTrue(stored["body_truncated"])

    def test_binary_bodies_are_not_indexed_as_text(self) -> None:
        for content_type in ("image/png", "application/octet-stream", "video/mp4"):
            with self.subTest(content_type=content_type):
                bracket = content_type.split("/")[0]
                flow = self.record(
                    path=f"/media/{bracket}",
                    response_headers={"Content-Type": content_type},
                    response_body=b"\x00\x01\x02Binarymarkertoken\xff\xfe",
                )
                self.assertEqual(
                    self.store.read(flow)["response"]["content_type"], content_type
                )
                self.assertEqual(self.store.read(flow)["response"]["body"], "")
                self.assertEqual(self.ids(text="Binarymarkertoken"), [])
                self.assertNotIn(flow, self.ids(host="api.example.invalid", text="binary"))

    # -- browsing and rollups -------------------------------------------

    def test_hosts_and_stats_roll_up_captured_traffic(self) -> None:
        self.record(client="agent", response_status=200)
        self.record(client="browser", response_status=404, path="/missing")
        self.record(client="browser", response_status=None, host="cdn.example.invalid")

        hosts = self.store.hosts()
        self.assertEqual(hosts[0]["host"], "api.example.invalid")
        self.assertEqual(hosts[0]["flows"], 2)
        self.assertEqual(hosts[0]["paths"], 2)
        self.assertEqual(hosts[0]["pending"], 0)
        self.assertEqual(hosts[1]["host"], "cdn.example.invalid")

        stats = self.store.stats()
        self.assertEqual(stats["flows"], 3)
        self.assertEqual(stats["hosts"], 2)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["by_client"], {"agent": 1, "browser": 2})
        self.assertEqual(stats["by_status"], {"200": 1, "404": 1, "None": 1})
        self.assertEqual(stats["schema_version"], SCHEMA_VERSION)
        self.assertEqual(stats["path"], str(self.engagement / "traffic" / "flows.db"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
