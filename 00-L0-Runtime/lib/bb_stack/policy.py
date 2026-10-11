"""Engagement-level tool-call policy for the BB MCP layer.

The host harness gates tool calls in coarse presets, and retuning those presets
means patching the harness. Our own MCP servers are ours to gate, so call
interception lives here: every tool call is evaluated against a small rule set
before the handler runs.

Evaluation is a four-phase pipeline, and the order *is* the semantics:

1. **deny rules** -- absolute; no mode and no allow rule can override them
2. **mode short-circuit** -- ``bypass`` allows everything, ``read-only`` denies
   every non-read-only tool, ``default`` decides nothing and falls through
3. **allow rules / read-only auto-pass** -- first matching allow rule wins,
   otherwise a read-only tool is allowed
4. **interactive confirmation** -- when nothing above decided, the call is put
   to a caller-injected callback; with no callback, or on any answer that is
   not an explicit allow, the call is *denied* (fail-closed)

Interaction is deliberately fail-closed: a missing or ambiguous confirmation
must never silently permit a tool call.

Rule sources
------------

The shipped defaults live in this module. An engagement may override them with
``<engagement>/policy.yaml``::

    mode: default          # read-only | default | bypass
    read_only:             # extra read-only tool patterns (defaults kept)
      - "mcp__traffic__*"
    deny:                  # evaluated first, first match wins
      - "dangerous(...)"                 # string form: tool-name pattern
      - tool: "write_file"               # mapping form
        when:                            # optional argument conditions (ANDed)
          arg_contains: {path: "/etc/"}
        message: "writes outside the engagement"
        updated_input: {force: null}     # null deletes the key
    allow:                 # evaluated after deny, first match wins
      - tool: "read_flow"
        when: {arg_present: [id]}

Tool-name patterns
------------------

* ``"*"`` matches every tool.
* ``"Name(...)"`` matches ``Name`` and any tool name *starting* with ``Name``.
* anything else is an fnmatch-style glob (``?`` and ``*`` inside the name).

Argument conditions (all conditions in one ``when`` are ANDed):

* ``arg_equals``   -- ``{key: value}``: ``arguments[key] == value``
* ``arg_contains`` -- ``{key: substring}``: substring of ``str(arguments[key])``
* ``arg_in``       -- ``{key: [values]}``: ``arguments[key]`` is in the list
* ``arg_present``  -- ``[key, ...]``: key exists with a non-empty value

A missing file means the defaults, which never allow everything: read-only
tools pass, everything else is asked (and denied when nobody can answer).
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .io import load_yaml
from .paths import StackPaths

__all__ = [
    "ALLOW",
    "ASK",
    "BYPASS_MODE",
    "CONDITION_KINDS",
    "DEFAULT_ALLOW",
    "DEFAULT_DENY",
    "DEFAULT_MODE",
    "DEFAULT_READ_ONLY_TOOLS",
    "DENY",
    "Decision",
    "MODES",
    "POLICY_FILENAME",
    "READ_ONLY_MODE",
    "Rule",
    "ToolPolicy",
    "policy_for",
]

POLICY_FILENAME = "policy.yaml"

# Decision behaviors.
ALLOW = "allow"
DENY = "deny"
ASK = "ask"
BEHAVIORS = (ALLOW, DENY, ASK)

# Policy modes. See the module docstring for their phase-2 semantics.
READ_ONLY_MODE = "read-only"
DEFAULT_MODE = "default"
BYPASS_MODE = "bypass"
MODES = (READ_ONLY_MODE, DEFAULT_MODE, BYPASS_MODE)

# Read-only tool-name patterns. In the default mode these run without
# confirmation. They are *globs describing the shape of a read-only tool*, not
# one server's literal names: a policy layer cannot know which servers exist,
# and the earlier literal set (`list_hosts`, `search`, …) matched no real tool
# at all, so every server would have had to re-declare its own names or be
# refused. Servers that name a read-only tool outside these shapes declare it
# with `read_only:` in policy.yaml, and a tool that mutates must never be named
# to match them.
DEFAULT_READ_ONLY_TOOLS: tuple[str, ...] = (
    "read_*",
    "*_read",
    "list_*",
    "*_list",
    "*_hosts",
    "search_*",
    "*_search",
    "diff_*",
    "*_diff",
    "stats",
    "*_stats",
    "get_*",
)

# Shipped defaults. Deny and allow are empty on purpose: the default posture is
# "read-only auto-passes, everything else asks", never "allow everything".
DEFAULT_DENY: tuple[str | Mapping[str, Any], ...] = ()
DEFAULT_ALLOW: tuple[str | Mapping[str, Any], ...] = ()

CONDITION_KINDS = ("arg_equals", "arg_contains", "arg_in", "arg_present")


def _tool_matches(pattern: str, tool_name: str) -> bool:
    """True when *tool_name* is selected by a tool-name *pattern*."""
    if pattern == "*":
        return True
    if pattern.endswith("(...)"):
        prefix = pattern[: -len("(...)")]
        return bool(prefix) and (tool_name == prefix or tool_name.startswith(prefix))
    return fnmatch.fnmatchcase(tool_name, pattern)


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


@dataclass(frozen=True)
class Condition:
    """One argument test inside a rule's ``when`` block."""

    kind: str
    key: str
    value: Any = None

    def matches(self, arguments: Mapping[str, Any]) -> bool:
        if self.kind == "arg_present":
            return self.key in arguments and _present(arguments[self.key])
        if self.key not in arguments:
            return False
        actual = arguments[self.key]
        if self.kind == "arg_equals":
            return actual == self.value
        if self.kind == "arg_contains":
            return isinstance(self.value, str) and self.value in str(actual)
        if self.kind == "arg_in":
            return actual in self.value
        return False


@dataclass(frozen=True)
class Rule:
    """A single deny or allow rule."""

    tool: str
    behavior: str
    conditions: tuple[Condition, ...] = ()
    message: str = ""
    updated_input: Mapping[str, Any] | None = None

    def matches(self, tool_name: str, arguments: Mapping[str, Any]) -> bool:
        return _tool_matches(self.tool, tool_name) and all(
            condition.matches(arguments) for condition in self.conditions
        )

    def rewrite(self, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
        """Arguments after this rule's ``updated_input``; None when it has none."""
        if self.updated_input is None:
            return None
        updated = dict(arguments)
        for key, value in self.updated_input.items():
            if value is None:
                updated.pop(key, None)
            else:
                updated[key] = value
        return updated


@dataclass(frozen=True)
class Decision:
    """The verdict for one tool call."""

    behavior: str
    message: str = ""
    updated_input: dict[str, Any] | None = None
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.behavior == ALLOW

    @property
    def denied(self) -> bool:
        return self.behavior == DENY


def _parse_when(raw: Any, *, where: str, source: str) -> tuple[Condition, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise ValidationError(f"{where}.when in {source} must be a mapping")
    unknown = sorted(set(raw) - set(CONDITION_KINDS))
    if unknown:
        raise ValidationError(
            f"{where}.when in {source} has unknown condition(s): "
            f"{', '.join(unknown)} (allowed: {', '.join(CONDITION_KINDS)})"
        )
    conditions: list[Condition] = []
    for kind, payload in raw.items():
        if kind == "arg_present":
            if not isinstance(payload, list) or not all(
                isinstance(key, str) and key for key in payload
            ):
                raise ValidationError(
                    f"{where}.when.arg_present in {source} must be a list of argument names"
                )
            conditions.extend(Condition("arg_present", key) for key in payload)
            continue
        if not isinstance(payload, Mapping):
            raise ValidationError(
                f"{where}.when.{kind} in {source} must be a mapping of argument name -> value"
            )
        for key, value in payload.items():
            if not isinstance(key, str) or not key:
                raise ValidationError(
                    f"{where}.when.{kind} in {source} keys must be argument names"
                )
            if kind == "arg_in" and not isinstance(value, list):
                raise ValidationError(
                    f"{where}.when.arg_in in {source} values must be lists"
                )
            conditions.append(Condition(kind, key, value))
    return tuple(conditions)


def _parse_rule(entry: Any, behavior: str, *, index: int, source: str) -> Rule:
    where = f"{behavior}[{index}]"
    if isinstance(entry, str):
        if not entry.strip():
            raise ValidationError(f"{where} in {source} must not be empty")
        return Rule(tool=entry.strip(), behavior=behavior)
    if not isinstance(entry, Mapping):
        raise ValidationError(
            f"{where} in {source} must be a tool-name string or a mapping"
        )
    unknown = sorted(set(entry) - {"tool", "when", "message", "updated_input"})
    if unknown:
        raise ValidationError(
            f"{where} in {source} has unknown key(s): {', '.join(unknown)} "
            "(allowed: tool, when, message, updated_input)"
        )
    tool = entry.get("tool", "*")
    if not isinstance(tool, str) or not tool.strip():
        raise ValidationError(f"{where}.tool in {source} must be a non-empty string")
    message = entry.get("message", "")
    if not isinstance(message, str):
        raise ValidationError(f"{where}.message in {source} must be a string")
    updated = entry.get("updated_input")
    if updated is not None and not isinstance(updated, Mapping):
        raise ValidationError(
            f"{where}.updated_input in {source} must be a mapping"
        )
    return Rule(
        tool=tool.strip(),
        behavior=behavior,
        conditions=_parse_when(entry.get("when"), where=where, source=source),
        message=message,
        updated_input=dict(updated) if updated is not None else None,
    )


def _parse_rules(raw: Any, behavior: str, *, source: str) -> tuple[Rule, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValidationError(f"{behavior} in {source} must be a list")
    return tuple(
        _parse_rule(entry, behavior, index=index, source=source)
        for index, entry in enumerate(raw)
    )


class ToolPolicy:
    """Rule set + mode used to gate tool calls for one engagement."""

    def __init__(
        self,
        *,
        mode: str = DEFAULT_MODE,
        deny: tuple[Rule, ...] = (),
        allow: tuple[Rule, ...] = (),
        read_only: tuple[str, ...] = DEFAULT_READ_ONLY_TOOLS,
        source: str | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValidationError(
                f"unknown policy mode {mode!r} (allowed: {', '.join(MODES)})"
            )
        self.mode = mode
        self.deny = deny
        self.allow = allow
        self.read_only = read_only
        self.source = source

    # -- construction ---------------------------------------------------

    @classmethod
    def default(cls) -> ToolPolicy:
        """The shipped posture: read-only passes, everything else asks."""
        return cls()

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, Any], *, source: str | None = None
    ) -> ToolPolicy:
        label = source or "<policy>"
        unknown = sorted(set(data) - {"mode", "deny", "allow", "read_only"})
        if unknown:
            raise ValidationError(
                f"unknown policy key(s) in {label}: {', '.join(unknown)} "
                "(allowed: mode, deny, allow, read_only)"
            )
        mode = data.get("mode", DEFAULT_MODE)
        extra_read_only = data.get("read_only", []) or []
        if not isinstance(extra_read_only, list) or not all(
            isinstance(item, str) and item for item in extra_read_only
        ):
            raise ValidationError(
                f"read_only in {label} must be a list of non-empty tool patterns"
            )
        return cls(
            mode=mode,
            deny=_parse_rules(data.get("deny"), DENY, source=label),
            allow=_parse_rules(data.get("allow"), ALLOW, source=label),
            read_only=DEFAULT_READ_ONLY_TOOLS + tuple(extra_read_only),
            source=source,
        )

    @classmethod
    def from_engagement(cls, paths: StackPaths, slug: str | None = None) -> ToolPolicy:
        """Load ``<engagement>/policy.yaml``; an absent file means the defaults."""
        root = paths.engagement(slug)
        path = root / POLICY_FILENAME
        if not path.is_file():
            return cls.default()
        return cls.from_mapping(load_yaml(path), source=str(path))

    # -- queries --------------------------------------------------------

    def is_read_only(self, tool_name: str) -> bool:
        return any(_tool_matches(pattern, tool_name) for pattern in self.read_only)

    def evaluate(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        can_use_tool: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> Decision:
        """Decide one call through the four-phase pipeline."""
        args = dict(arguments or {})

        # Phase 1 -- deny rules are absolute.
        for rule in self.deny:
            if rule.matches(tool_name, args):
                return Decision(
                    DENY,
                    rule.message or f"tool {tool_name!r} denied by engagement policy",
                    rule.rewrite(args),
                    "deny-rule",
                )

        # Phase 2 -- mode short-circuit.
        if self.mode == BYPASS_MODE:
            return Decision(ALLOW, reason="mode=bypass")
        if self.mode == READ_ONLY_MODE:
            if self.is_read_only(tool_name):
                return Decision(ALLOW, reason="mode=read-only")
            return Decision(
                DENY,
                f"mode=read-only denies non-read-only tool {tool_name!r}",
                reason="mode=read-only",
            )

        # Phase 3 -- allow rules, then read-only auto-pass.
        for rule in self.allow:
            if rule.matches(tool_name, args):
                return Decision(
                    ALLOW, rule.message, rule.rewrite(args), "allow-rule"
                )
        if self.is_read_only(tool_name):
            return Decision(ALLOW, reason="read-only")

        # Phase 4 -- confirm, fail-closed to deny.
        return self._confirm(tool_name, args, can_use_tool)

    def _confirm(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        can_use_tool: Callable[[str, dict[str, Any]], Any] | None,
    ) -> Decision:
        if can_use_tool is None:
            return Decision(
                DENY,
                f"no confirmation handler for {tool_name!r}; denied (fail-closed)",
                reason="fail-closed",
            )
        try:
            answer = can_use_tool(tool_name, arguments)
        except Exception as error:  # noqa: BLE001 - fail closed on any failure
            return Decision(
                DENY,
                f"confirmation handler failed for {tool_name!r}: {error}",
                reason="fail-closed",
            )
        return self._coerce_answer(answer, tool_name)

    @staticmethod
    def _coerce_answer(answer: Any, tool_name: str) -> Decision:
        if isinstance(answer, Decision) and answer.behavior in BEHAVIORS:
            return answer
        if isinstance(answer, bool):
            return Decision(ALLOW if answer else DENY, reason="confirm")
        if isinstance(answer, str) and answer in BEHAVIORS:
            return Decision(answer, reason="confirm")
        if isinstance(answer, Mapping):
            behavior = answer.get("behavior")
            if behavior in BEHAVIORS:
                updated = answer.get("updated_input")
                message = answer.get("message", "")
                return Decision(
                    behavior,
                    message if isinstance(message, str) else "",
                    dict(updated) if isinstance(updated, Mapping) else None,
                    "confirm",
                )
        return Decision(
            DENY,
            f"confirmation for {tool_name!r} was not an explicit allow; denied (fail-closed)",
            reason="fail-closed",
        )


def policy_for(paths: StackPaths, slug: str | None = None) -> ToolPolicy:
    """Convenience constructor for the engagement's policy."""
    return ToolPolicy.from_engagement(paths, slug)
