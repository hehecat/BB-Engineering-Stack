#!/usr/bin/env python3
"""End-to-end tests for the traffic MCP server over a real stdio session.

The server is started as a real subprocess and driven with JSON-RPC line
frames, the same shape `00-L0-Runtime/mcp_probe.mjs` uses, so the tests fail if
the handshake, the tool surface, or the store mapping drift.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.traffic import FlowRecord, TrafficStore  # noqa: E402

SERVER = ROOT / "05-L5-MCP-CLI" / "lib" / "traffic_mcp.py"


class _Session:
    """A live server subprocess speaking JSON-RPC on stdio."""

    def __init__(self, db: Path):
        env = dict(os.environ)
        env["BB_STACK_ROOT"] = str(ROOT)
        env["BB_TRAFFIC_DB"] = str(db)
        env.pop("BB_ENGAGEMENT", None)
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self._id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        message = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            message["params"] = params
        return self._exchange(message)

    def notify(self, method: str, params: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _exchange(self, message: dict) -> dict:
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read()
            raise AssertionError(f"server closed the stream: {stderr}")
        return json.loads(line)

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                stream.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self.process.kill()
            self.process.wait(timeout=10)


def _text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


def _payload(response: dict) -> dict:
    return json.loads(_text(response))


def _record(client: str, cookie: str, path: str, status: int, body: bytes, *, host: str = "api.example.com") -> FlowRecord:
    return FlowRecord(
        method="GET",
        host=host,
        path=path,
        query="",
        client=client,
        request_headers={"Cookie": cookie, "Accept": "application/json"},
        response_status=status,
        response_headers={"Content-Type": "text/plain"},
        response_body=body,
    )


class TrafficMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-traffic-mcp-")
        base = Path(self.temporary.name)
        self.db = base / "traffic" / "flows.db"
        with TrafficStore(self.db) as store:
            store.record(
                _record("alice", "sid=alice", "/admin/users", 200, b"alice private profile")
            )
            store.record(
                _record("bob", "sid=bob", "/admin/users", 200, b"alice private profile")
            )
            store.record(_record("alice", "sid=alice", "/health", 500, b"internal error trace"))
            store.record(
                _record(
                    "browser",
                    "sid=browser",
                    "/static/app.js",
                    200,
                    b"const TOKEN='leakedapi';",
                    host="cdn.example.com",
                )
            )
        self.session = _Session(self.db)

    def tearDown(self) -> None:
        self.session.close()
        self.temporary.cleanup()

    def _handshake(self) -> None:
        initialized = self.session.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "bb-test", "version": "1.0.0"},
            },
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "traffic")
        self.session.notify("notifications/initialized")

    def test_tools_list_exposes_five_tools(self) -> None:
        self._handshake()
        listing = self.session.request("tools/list")
        tools = {tool["name"]: tool for tool in listing["result"]["tools"]}
        self.assertEqual(
            set(tools),
            {
                "list_traffic_hosts",
                "search_traffic",
                "read_flow",
                "traffic_stats",
                "diff_flows",
            },
        )
        for tool in tools.values():
            self.assertTrue(tool["description"].strip())
            self.assertEqual(tool["inputSchema"]["type"], "object")
        self.assertEqual(tools["read_flow"]["inputSchema"]["required"], ["id"])

    def test_search_filters_and_never_returns_bodies(self) -> None:
        self._handshake()
        hits = _payload(self.session.call_tool("search_traffic", {"text": "leakedapi"}))
        self.assertEqual([flow["id"] for flow in hits["flows"]], [4])
        self.assertEqual(hits["flows"][0]["url"], "GET cdn.example.com/static/app.js")
        self.assertEqual(hits["flows"][0]["status"], 200)

        status_hits = _payload(self.session.call_tool("search_traffic", {"status": 500}))
        self.assertEqual([flow["id"] for flow in status_hits["flows"]], [3])

        host_hits = _payload(
            self.session.call_tool(
                "search_traffic", {"host": "api.example.com", "method": "get"}
            )
        )
        self.assertEqual({flow["id"] for flow in host_hits["flows"]}, {1, 2, 3})

        # A listing carries byte counts, never the bytes.
        raw = _text(self.session.call_tool("search_traffic", {"text": "leakedapi"}))
        self.assertNotIn("leakedapi", raw)
        for flow in hits["flows"]:
            self.assertNotIn("body", flow)
            self.assertNotIn("response_body", flow)
        self.assertEqual(hits["flows"][0]["response_bytes"], len(b"const TOKEN='leakedapi';"))

    def test_read_flow_respects_max_bytes_and_flags_truncation(self) -> None:
        self._handshake()
        capped = _payload(self.session.call_tool("read_flow", {"id": 4, "max_bytes": 8}))
        body = capped["flow"]["response"]
        self.assertEqual(body["body"], "const TO")
        self.assertTrue(body["body_truncated"])
        self.assertEqual(body["body_bytes"], len(b"const TOKEN='leakedapi';"))
        self.assertEqual(capped["flow"]["request"]["headers"]["Cookie"], "sid=browser")

        full = _payload(self.session.call_tool("read_flow", {"id": 4, "max_bytes": 4096}))
        self.assertEqual(full["flow"]["response"]["body"], "const TOKEN='leakedapi';")
        self.assertNotIn("body_truncated", full["flow"]["response"])

        raw = _payload(self.session.call_tool("read_flow", {"id": 4, "raw": True}))
        self.assertIn("body_base64", raw["flow"]["response"])

        missing = self.session.call_tool("read_flow", {"id": 999})
        self.assertTrue(missing["result"]["isError"])
        self.assertIn("unknown flow id", _text(missing))

    def test_diff_flows_reports_cookie_difference(self) -> None:
        self._handshake()
        result = _payload(self.session.call_tool("diff_flows", {"first": 1, "second": 2}))
        self.assertFalse(result["identical"])
        self.assertEqual(list(result["changed"]), ["req:cookie"])
        self.assertEqual(
            result["changed"]["req:cookie"], {"first": "sid=alice", "second": "sid=bob"}
        )

    def test_hosts_and_stats_describe_the_capture(self) -> None:
        self._handshake()
        hosts = _payload(self.session.call_tool("list_traffic_hosts", {}))
        by_host = {row["host"]: row for row in hosts["hosts"]}
        self.assertEqual(by_host["api.example.com"]["flows"], 3)
        self.assertEqual(by_host["cdn.example.com"]["flows"], 1)

        stats = _payload(self.session.call_tool("traffic_stats", {}))["stats"]
        self.assertEqual(stats["flows"], 4)
        self.assertEqual(stats["hosts"], 2)
        self.assertEqual(stats["by_status"]["200"], 3)
        self.assertEqual(stats["by_client"]["alice"], 2)


class TrafficMcpConfigTests(unittest.TestCase):
    def test_missing_store_env_exits_nonzero(self) -> None:
        env = dict(os.environ)
        env["BB_STACK_ROOT"] = str(ROOT)
        env.pop("BB_TRAFFIC_DB", None)
        env.pop("BB_ENGAGEMENT", None)
        completed = subprocess.run(
            [sys.executable, str(SERVER)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("BB_TRAFFIC_DB", completed.stderr)

    def test_empty_store_answers_empty_not_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bb-traffic-empty-") as name:
            missing_db = Path(name) / "traffic" / "flows.db"
            session = _Session(missing_db)
            try:
                session.request("initialize", {"protocolVersion": "2024-11-05"})
                session.notify("notifications/initialized")
                hosts = _payload(session.call_tool("list_traffic_hosts", {}))
                self.assertEqual(hosts["hosts"], [])
                search = _payload(session.call_tool("search_traffic", {}))
                self.assertEqual(search["flows"], [])
                stats = _payload(session.call_tool("traffic_stats", {}))["stats"]
                self.assertEqual(stats["flows"], 0)
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
