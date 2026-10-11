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

from bb_stack.policy import DEFAULT_MODE, ToolPolicy  # noqa: E402
from bb_stack.traffic import FlowRecord, TrafficStore  # noqa: E402

SERVER = ROOT / "05-L5-MCP-CLI" / "lib" / "traffic_mcp.py"

sys.path.insert(0, str(SERVER.parent))
import traffic_mcp  # noqa: E402


class _Session:
    """A live server subprocess speaking JSON-RPC on stdio."""

    def __init__(self, db: Path, env_extra: dict | None = None):
        env = dict(os.environ)
        env["BB_STACK_ROOT"] = str(ROOT)
        env["BB_TRAFFIC_DB"] = str(db)
        env.pop("BB_ENGAGEMENT", None)
        if env_extra:
            env.update(env_extra)
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


class _StubServer:
    """Stands in for TrafficServer when driving `_handle` in-process."""

    def __init__(self, policy: ToolPolicy):
        self.policy = policy
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"tool": name, "arguments": arguments}


def _call(server: _StubServer, name: str, arguments: dict) -> dict:
    return traffic_mcp._handle(
        server,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


class TrafficMcpPolicyGateTests(unittest.TestCase):
    """The `tools/call` policy gate, exercised through the real dispatcher."""

    def test_deny_rule_stops_the_tool_and_reports_isError(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "deny": [
                    {
                        "tool": "read_flow",
                        "when": {"arg_equals": {"id": 1}},
                        "message": "flow 1 is out of bounds",
                    }
                ]
            }
        )
        server = _StubServer(policy)
        result = _call(server, "read_flow", {"id": 1})["result"]
        self.assertTrue(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("out of bounds", text)
        self.assertIn("deny-rule", text)
        self.assertEqual(server.calls, [])  # the handler never ran

    def test_ask_without_channel_is_denied_fail_closed(self) -> None:
        # No policy rule decides, and the tool is not read-only, so the pipeline
        # reaches the ask phase -- which must fail closed with no channel.
        server = _StubServer(ToolPolicy(mode=DEFAULT_MODE, read_only=()))
        result = _call(server, "read_flow", {"id": 1})["result"]
        self.assertTrue(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("no interactive channel", text)
        self.assertIn("fail-closed", text)
        self.assertEqual(server.calls, [])

    def test_updated_input_rewrites_and_is_reported(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "allow": [
                    {
                        "tool": "read_flow",
                        "when": {"arg_equals": {"id": 4}},
                        "updated_input": {"max_bytes": 8},
                    }
                ]
            }
        )
        server = _StubServer(policy)
        result = _call(server, "read_flow", {"id": 4, "max_bytes": 4096})["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(server.calls, [("read_flow", {"id": 4, "max_bytes": 8})])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["policy"]["effective_arguments"], {"id": 4, "max_bytes": 8})

    def test_read_only_tool_passes_the_default_posture(self) -> None:
        server = _StubServer(traffic_mcp._augment_read_only(ToolPolicy.default()))
        result = _call(server, "list_traffic_hosts", {})["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(server.calls, [("list_traffic_hosts", {})])

    def test_policy_evaluation_failure_fails_closed(self) -> None:
        class _Boom(ToolPolicy):
            def evaluate(self, *args, **kwargs):
                raise RuntimeError("boom")

        server = _StubServer(_Boom())
        result = _call(server, "read_flow", {"id": 1})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("fail-closed", result["content"][0]["text"])
        self.assertEqual(server.calls, [])


class TrafficMcpPolicyFileTests(unittest.TestCase):
    """The policy is picked up from `<engagement>/policy.yaml` over stdio."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-traffic-policy-")
        base = Path(self.temporary.name)
        self.db = base / "traffic" / "flows.db"
        with TrafficStore(self.db) as store:
            store.record(
                _record("alice", "sid=alice", "/admin/users", 200, b"alice private profile")
            )
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
            store.record(_record("alice", "sid=alice", "/health", 500, b"internal error trace"))
        self.work = base / "work"
        self.slug = "traffic-policy-fixture"
        self.engagement = self.work / "engagements" / self.slug
        self.engagement.mkdir(parents=True)
        (self.engagement / "engagement.yaml").write_text(
            f"schema_version: 1\nslug: {self.slug}\n", encoding="utf-8"
        )
        self.session: _Session | None = None

    def tearDown(self) -> None:
        if self.session is not None:
            self.session.close()
        self.temporary.cleanup()

    def _open(self, policy_text: str) -> _Session:
        (self.engagement / "policy.yaml").write_text(policy_text, encoding="utf-8")
        self.session = _Session(
            self.db,
            env_extra={"BB_WORK_ROOT": str(self.work), "BB_ENGAGEMENT": self.slug},
        )
        self.session.request("initialize", {"protocolVersion": "2024-11-05"})
        self.session.notify("notifications/initialized")
        return self.session

    def test_deny_and_rewrite_apply_end_to_end(self) -> None:
        session = self._open(
            "deny:\n"
            "  - tool: read_flow\n"
            "    when: {arg_equals: {id: 1}}\n"
            '    message: "flow 1 is out of bounds"\n'
            "allow:\n"
            "  - tool: read_flow\n"
            "    when: {arg_equals: {id: 2}}\n"
            "    updated_input: {max_bytes: 8}\n"
        )
        # The denied flow is never read: its body cannot appear in the error.
        denied = session.call_tool("read_flow", {"id": 1})
        self.assertTrue(denied["result"]["isError"])
        self.assertIn("out of bounds", _text(denied))
        self.assertNotIn("alice private profile", _text(denied))

        # The allow rule rewrote the arguments, and says so.
        rewritten = _payload(session.call_tool("read_flow", {"id": 2, "max_bytes": 4096}))
        self.assertEqual(rewritten["flow"]["response"]["body"], "const TO")
        self.assertTrue(rewritten["flow"]["response"]["body_truncated"])
        self.assertEqual(rewritten["policy"]["effective_arguments"], {"id": 2, "max_bytes": 8})

        # A flow the policy does not name reads in full, unannotated.
        untouched = _payload(session.call_tool("read_flow", {"id": 3}))
        self.assertEqual(untouched["flow"]["response"]["body"], "internal error trace")
        self.assertNotIn("policy", untouched)

    def test_broken_policy_file_fails_closed(self) -> None:
        session = self._open("mode: nope\n")
        refused = session.call_tool("read_flow", {"id": 3})
        self.assertTrue(refused["result"]["isError"])
        self.assertIn("fail-closed", _text(refused))
        self.assertNotIn("internal error trace", _text(refused))


if __name__ == "__main__":
    unittest.main()
