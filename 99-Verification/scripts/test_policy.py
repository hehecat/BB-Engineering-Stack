#!/usr/bin/env python3
"""Contract tests for `bb_stack.policy`, the MCP-layer tool-call policy.

The policy decides `allow`/`deny`/`ask` before an MCP handler runs, through a
four-phase pipeline whose order is the semantics: deny rules are absolute, the
mode short-circuits, allow rules and read-only tools pass, and anything left
goes to an injected confirmation callback -- which is fail-closed. These tests
pin each phase and the failure mode callers depend on: a call that cannot be
confirmed must be denied, never silently allowed.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths
from bb_stack.policy import (
    ALLOW,
    ASK,
    BYPASS_MODE,
    DEFAULT_MODE,
    DENY,
    Decision,
    READ_ONLY_MODE,
    Rule,
    ToolPolicy,
    policy_for,
)


class PolicyTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-policy-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.slug = "policy-fixture"
        self.engagement = self.paths.engagements_root / self.slug
        self.engagement.mkdir(parents=True)
        (self.engagement / "engagement.yaml").write_text(
            f"schema_version: 1\nslug: {self.slug}\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_policy(self, text: str) -> None:
        (self.engagement / "policy.yaml").write_text(text, encoding="utf-8")


class DenyPriorityTests(PolicyTestBase):
    def test_deny_rule_beats_bypass_mode(self) -> None:
        policy = ToolPolicy.from_mapping(
            {"mode": BYPASS_MODE, "deny": ["destroy(...)"]}
        )
        decision = policy.evaluate("destroy", {"target": "db"})
        self.assertEqual(decision.behavior, DENY)
        self.assertEqual(decision.reason, "deny-rule")

    def test_deny_rule_beats_allow_rule(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "mode": DEFAULT_MODE,
                "deny": ["write_file"],
                "allow": ["write_file"],
            }
        )
        self.assertEqual(policy.evaluate("write_file", {}).behavior, DENY)

    def test_deny_rule_beats_read_only_auto_pass(self) -> None:
        # `search_traffic` matches the shipped read-only globs, yet an explicit
        # deny must still override it.
        policy = ToolPolicy.from_mapping({"deny": ["search_traffic"]})
        self.assertEqual(policy.evaluate("search_traffic", {}).behavior, DENY)

    def test_deny_message_and_updated_input_are_carried(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "deny": [
                    {
                        "tool": "shell",
                        "message": "no shells here",
                        "updated_input": {"flag": None},
                    }
                ]
            }
        )
        decision = policy.evaluate("shell", {"flag": "--force", "keep": 1})
        self.assertEqual(decision.behavior, DENY)
        self.assertEqual(decision.message, "no shells here")
        self.assertEqual(decision.updated_input, {"keep": 1})


class ModeTests(PolicyTestBase):
    def test_read_only_mode_allows_read_only_tool(self) -> None:
        policy = ToolPolicy.from_mapping({"mode": READ_ONLY_MODE})
        self.assertEqual(policy.evaluate("search_traffic", {}).behavior, ALLOW)

    def test_read_only_mode_denies_mutating_tool_even_with_allow_rule(self) -> None:
        # The mode short-circuits before allow rules, so the allow is ignored.
        policy = ToolPolicy.from_mapping(
            {"mode": READ_ONLY_MODE, "allow": ["write_file"]}
        )
        decision = policy.evaluate("write_file", {})
        self.assertEqual(decision.behavior, DENY)
        self.assertEqual(decision.reason, "mode=read-only")

    def test_bypass_allows_unknown_tool(self) -> None:
        policy = ToolPolicy.from_mapping({"mode": BYPASS_MODE})
        self.assertEqual(policy.evaluate("totally_unknown", {}).behavior, ALLOW)

    def test_default_mode_does_not_short_circuit(self) -> None:
        # In default mode an unknown tool is not allowed; it is asked.
        policy = ToolPolicy.from_mapping({"mode": DEFAULT_MODE})
        self.assertEqual(policy.evaluate("totally_unknown", {}).behavior, DENY)


class AllowAndReadOnlyTests(PolicyTestBase):
    def test_read_only_tool_auto_passes_in_default_mode(self) -> None:
        policy = ToolPolicy.default()
        decision = policy.evaluate("search_traffic", {"host": "example.com"})
        self.assertEqual(decision.behavior, ALLOW)
        self.assertEqual(decision.reason, "read-only")

    def test_allow_rule_grants_mutating_tool(self) -> None:
        policy = ToolPolicy.from_mapping({"allow": ["write_file"]})
        self.assertEqual(policy.evaluate("write_file", {}).behavior, ALLOW)

    def test_first_matching_allow_rule_wins(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "allow": [
                    {"tool": "svc", "message": "first"},
                    {"tool": "svc", "message": "second"},
                ]
            }
        )
        decision = policy.evaluate("svc", {})
        self.assertEqual(decision.message, "first")

    def test_extra_read_only_pattern_from_mapping(self) -> None:
        policy = ToolPolicy.from_mapping({"read_only": ["mcp__traffic__read_*"]})
        self.assertTrue(policy.is_read_only("mcp__traffic__read_flow"))
        self.assertFalse(policy.is_read_only("mcp__traffic__delete_flow"))

    def test_read_only_defaults_are_kept_when_extended(self) -> None:
        policy = ToolPolicy.from_mapping({"read_only": ["extra"]})
        self.assertTrue(policy.is_read_only("search_traffic"))  # default entry retained
        self.assertTrue(policy.is_read_only("extra"))


class ToolPatternTests(PolicyTestBase):
    def test_prefix_pattern_matches_name_and_prefixed_names(self) -> None:
        policy = ToolPolicy.from_mapping({"allow": ["web(...)"]})
        self.assertEqual(policy.evaluate("web", {}).behavior, ALLOW)
        self.assertEqual(policy.evaluate("web_fetch", {}).behavior, ALLOW)

    def test_glob_pattern_matches(self) -> None:
        policy = ToolPolicy.from_mapping({"allow": ["mcp__traffic__*"]})
        self.assertEqual(
            policy.evaluate("mcp__traffic__read_flow", {}).behavior, ALLOW
        )

    def test_non_matching_pattern_falls_through_to_deny(self) -> None:
        policy = ToolPolicy.from_mapping({"allow": ["web(...)"]})
        self.assertEqual(policy.evaluate("shell", {}).behavior, DENY)


class ArgumentConditionTests(PolicyTestBase):
    def test_arg_contains_triggers_deny(self) -> None:
        policy = ToolPolicy.from_mapping(
            {"deny": [{"tool": "fetch", "when": {"arg_contains": {"url": "/admin"}}}]}
        )
        self.assertEqual(
            policy.evaluate("fetch", {"url": "https://x/admin"}).behavior, DENY
        )
        # A different url is not matched by the deny rule, so it falls through
        # to phase 4 and is denied for lack of a handler -- but not by the rule.
        other = policy.evaluate("fetch", {"url": "https://x/home"})
        self.assertEqual(other.reason, "fail-closed")

    def test_arg_equals(self) -> None:
        policy = ToolPolicy.from_mapping(
            {"allow": [{"tool": "http", "when": {"arg_equals": {"method": "GET"}}}]}
        )
        self.assertEqual(
            policy.evaluate("http", {"method": "GET"}).behavior, ALLOW
        )
        self.assertEqual(policy.evaluate("http", {"method": "POST"}).behavior, DENY)

    def test_arg_in(self) -> None:
        policy = ToolPolicy.from_mapping(
            {"allow": [{"tool": "http", "when": {"arg_in": {"scheme": ["http", "https"]}}}]}
        )
        self.assertEqual(policy.evaluate("http", {"scheme": "https"}).behavior, ALLOW)
        self.assertEqual(policy.evaluate("http", {"scheme": "ftp"}).behavior, DENY)

    def test_arg_present(self) -> None:
        policy = ToolPolicy.from_mapping(
            {"allow": [{"tool": "http", "when": {"arg_present": ["id"]}}]}
        )
        self.assertEqual(policy.evaluate("http", {"id": 3}).behavior, ALLOW)
        self.assertEqual(policy.evaluate("http", {"id": ""}).behavior, DENY)
        self.assertEqual(policy.evaluate("http", {}).behavior, DENY)

    def test_conditions_are_anded(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "allow": [
                    {
                        "tool": "http",
                        "when": {
                            "arg_equals": {"method": "GET"},
                            "arg_present": ["id"],
                        },
                    }
                ]
            }
        )
        self.assertEqual(policy.evaluate("http", {"method": "GET", "id": 1}).behavior, ALLOW)
        self.assertEqual(policy.evaluate("http", {"method": "GET"}).behavior, DENY)


class UpdatedInputTests(PolicyTestBase):
    def test_null_deletes_a_dangerous_flag(self) -> None:
        policy = ToolPolicy.from_mapping(
            {
                "allow": [
                    {
                        "tool": "shell",
                        "updated_input": {"force": None, "audit": True},
                    }
                ]
            }
        )
        decision = policy.evaluate("shell", {"force": "--force", "cmd": "ls"})
        self.assertEqual(decision.behavior, ALLOW)
        self.assertEqual(
            decision.updated_input, {"cmd": "ls", "audit": True}
        )

    def test_original_arguments_are_not_mutated(self) -> None:
        policy = ToolPolicy.from_mapping(
            {"allow": [{"tool": "shell", "updated_input": {"force": None}}]}
        )
        original = {"force": "--force"}
        policy.evaluate("shell", original)
        self.assertEqual(original, {"force": "--force"})

    def test_no_updated_input_means_none(self) -> None:
        policy = ToolPolicy.from_mapping({"allow": ["shell"]})
        self.assertIsNone(policy.evaluate("shell", {"a": 1}).updated_input)


class ConfirmationTests(PolicyTestBase):
    def test_ask_without_callback_fails_closed_to_deny(self) -> None:
        policy = ToolPolicy.from_mapping({"mode": DEFAULT_MODE})
        decision = policy.evaluate("mutating_tool", {})
        self.assertEqual(decision.behavior, DENY)
        self.assertEqual(decision.reason, "fail-closed")

    def test_callback_true_allows(self) -> None:
        policy = ToolPolicy.default()
        seen: list[tuple[str, dict[str, Any]]] = []

        def confirm(name: str, arguments: dict[str, Any]) -> bool:
            seen.append((name, arguments))
            return True

        decision = policy.evaluate("mutating_tool", {"x": 1}, can_use_tool=confirm)
        self.assertEqual(decision.behavior, ALLOW)
        self.assertEqual(seen, [("mutating_tool", {"x": 1})])

    def test_callback_false_denies(self) -> None:
        policy = ToolPolicy.default()
        decision = policy.evaluate(
            "mutating_tool", {}, can_use_tool=lambda name, args: False
        )
        self.assertEqual(decision.behavior, DENY)

    def test_callback_returning_none_fails_closed(self) -> None:
        policy = ToolPolicy.default()
        decision = policy.evaluate(
            "mutating_tool", {}, can_use_tool=lambda name, args: None
        )
        self.assertEqual(decision.behavior, DENY)
        self.assertEqual(decision.reason, "fail-closed")

    def test_callback_raising_fails_closed(self) -> None:
        def boom(name: str, arguments: dict[str, Any]) -> bool:
            raise RuntimeError("no terminal")

        policy = ToolPolicy.default()
        decision = policy.evaluate("mutating_tool", {}, can_use_tool=boom)
        self.assertEqual(decision.behavior, DENY)
        self.assertEqual(decision.reason, "fail-closed")

    def test_callback_may_return_a_decision(self) -> None:
        policy = ToolPolicy.default()
        decision = policy.evaluate(
            "mutating_tool",
            {},
            can_use_tool=lambda name, args: Decision(ALLOW, updated_input={"safe": True}),
        )
        self.assertEqual(decision.behavior, ALLOW)
        self.assertEqual(decision.updated_input, {"safe": True})

    def test_read_only_tool_never_reaches_the_callback(self) -> None:
        policy = ToolPolicy.default()
        called = {"n": 0}

        def confirm(name: str, args: dict[str, Any]) -> bool:
            called["n"] += 1
            return False

        self.assertEqual(
            policy.evaluate("search_traffic", {}, can_use_tool=confirm).behavior, ALLOW
        )
        self.assertEqual(called["n"], 0)


class FileLoadingTests(PolicyTestBase):
    def test_missing_policy_file_uses_default_posture(self) -> None:
        policy = policy_for(self.paths, self.slug)
        self.assertEqual(policy.mode, DEFAULT_MODE)
        self.assertEqual(policy.evaluate("search_traffic", {}).behavior, ALLOW)
        self.assertEqual(policy.evaluate("mutating", {}).behavior, DENY)
        self.assertEqual(policy.evaluate("mutating", {}).reason, "fail-closed")

    def test_empty_policy_file_is_still_default_posture(self) -> None:
        self.write_policy("{}\n")
        policy = policy_for(self.paths, self.slug)
        self.assertEqual(policy.mode, DEFAULT_MODE)
        self.assertEqual(policy.evaluate("search_traffic", {}).behavior, ALLOW)
        self.assertEqual(policy.evaluate("mutating", {}).behavior, DENY)

    def test_file_rules_are_loaded(self) -> None:
        self.write_policy(
            "mode: default\n"
            "deny:\n"
            "  - tool: fetch\n"
            "    when:\n"
            "      arg_contains: {url: /admin}\n"
            "allow:\n"
            "  - http\n"
        )
        policy = policy_for(self.paths, self.slug)
        self.assertEqual(policy.source, str(self.engagement / "policy.yaml"))
        self.assertEqual(
            policy.evaluate("fetch", {"url": "http://x/admin"}).behavior, DENY
        )
        self.assertEqual(policy.evaluate("http", {}).behavior, ALLOW)


class ValidationTests(PolicyTestBase):
    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolPolicy.from_mapping({"mode": "yolo"})

    def test_unknown_top_level_key_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolPolicy.from_mapping({"modes": "default"})

    def test_unknown_condition_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolPolicy.from_mapping(
                {"deny": [{"tool": "x", "when": {"arg_smells": {"a": 1}}}]}
            )

    def test_unknown_rule_key_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolPolicy.from_mapping({"deny": [{"tool": "x", "because": "no"}]})

    def test_bad_rule_type_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolPolicy.from_mapping({"deny": [42]})

    def test_arg_in_requires_a_list(self) -> None:
        with self.assertRaises(ValidationError):
            ToolPolicy.from_mapping(
                {"allow": [{"tool": "x", "when": {"arg_in": {"a": "b"}}}]}
            )


class DecisionApiTests(PolicyTestBase):
    def test_decision_helpers(self) -> None:
        policy = ToolPolicy.from_mapping({"allow": ["x"]})
        decision = policy.evaluate("x", {})
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.denied)

    def test_rule_rewrite_returns_none_without_updated_input(self) -> None:
        self.assertIsNone(Rule(tool="x", behavior=ALLOW).rewrite({"a": 1}))

    def test_ask_constant_is_not_a_rule_behavior(self) -> None:
        # `ask` is phase-4 only; no built-in rule emits it.
        policy = ToolPolicy.default()
        self.assertNotEqual(policy.evaluate("search_traffic", {}).behavior, ASK)


if __name__ == "__main__":
    unittest.main()
