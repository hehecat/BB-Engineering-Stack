#!/usr/bin/env python3
"""Contract tests for `bb_stack.continuous`, the headless round loop.

`continuous` exists because an agent cannot loop itself -- it finishes. These
tests pin the loop's boundaries: what stops it, that one round is one action plus
a checkpoint, and that the launch plan is re-derived before *every* round rather
than reused from the first.

The authorization gate itself is deliberately not faked here: it lives inside
`RuntimeManager.launch`, which this module calls per round precisely so it stays
in front of every round. `test_every_round_goes_through_the_launch_plan` pins
that delegation; `launch`'s own tests pin the check.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack import continuous
from bb_stack.continuous import ROUND_INSTRUCTION, STOP_FILE_NAME, run, stop_file_for
from bb_stack.engagement import EngagementManager
from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


class ContinuousTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-continuous-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.slug = "continuous-fixture"
        self.manager = EngagementManager(self.paths)
        self.create()
        self.engagement = self.paths.engagement(self.slug)
        self.plans: list[dict[str, Any]] = []
        self.commands: list[list[str]] = []

    def create(self, slug: str | None = None, **overrides: Any) -> None:
        kwargs: dict[str, Any] = {
            "workflow": "assessment",
            "platform": "authorized-assessment",
            "mode": "continuous",
            "authorization_source": "fixture: own asset",
            "authorization_status": "user-asserted",
        }
        kwargs.update(overrides)
        self.manager.create(slug or self.slug, "https://example.invalid", **kwargs)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fake_launch(self, profile: str, **kwargs: Any) -> dict[str, Any]:
        self.plans.append({"profile": profile, **kwargs})
        return {
            "command": ["agent", "--flag"],
            "cwd": str(self.engagement),
            "backend": "claude",
        }

    def fake_runner(self, *codes: int):
        pending = list(codes) or [0]

        def run_command(command: list[str], **_: Any) -> FakeCompleted:
            self.commands.append(command)
            return FakeCompleted(
                returncode=pending.pop(0) if len(pending) > 1 else pending[0],
                stdout="did a thing\n",
            )

        return run_command

    def loop(self, *, codes: tuple[int, ...] = (), **kwargs: Any) -> dict[str, Any]:
        with patch.object(continuous.RuntimeManager, "launch", side_effect=self.fake_launch):
            return run(
                self.paths,
                self.slug,
                run_command=self.fake_runner(*codes),
                sleep=lambda _: None,
                **kwargs,
            )

    # -- one round -------------------------------------------------------

    def test_a_round_is_headless_and_carries_the_one_action_instruction(self) -> None:
        result = self.loop(max_rounds=1)
        self.assertEqual(result["round_count"], 1)
        command = self.commands[0]
        self.assertIn("-p", command)  # the backend's declared headless flag
        self.assertEqual(command[-1], ROUND_INSTRUCTION.format(slug=self.slug))
        self.assertIn("one action, not a whole phase", command[-1])
        self.assertIn("checkpoint", command[-1])

    def test_dry_run_assembles_without_running_anything(self) -> None:
        result = self.loop(max_rounds=3, dry_run=True)
        self.assertEqual(self.commands, [])
        self.assertEqual(result["stopped_because"], "dry run")
        self.assertTrue(result["rounds"][0]["dry_run"])

    # -- stopping conditions ---------------------------------------------

    def test_stop_file_ends_the_loop_before_the_next_round(self) -> None:
        marker = stop_file_for(self.engagement)
        self.assertEqual(marker.name, STOP_FILE_NAME)
        created = False

        def create_then_run(command: list[str], **_: Any) -> FakeCompleted:
            nonlocal created
            self.commands.append(command)
            if not created:
                marker.write_text("stop\n", encoding="utf-8")
                created = True
            return FakeCompleted()

        with patch.object(continuous.RuntimeManager, "launch", side_effect=self.fake_launch):
            result = run(
                self.paths, self.slug, run_command=create_then_run, max_rounds=5
            )
        self.assertEqual(len(self.commands), 1)
        self.assertIn("stop file present", result["stopped_because"])

    def test_max_rounds_bounds_the_loop(self) -> None:
        result = self.loop(max_rounds=3)
        self.assertEqual(len(self.commands), 3)
        self.assertIn("max_rounds reached", result["stopped_because"])

    def test_consecutive_failures_stop_the_loop(self) -> None:
        result = self.loop(codes=(1,), max_rounds=10, max_failures=2)
        self.assertEqual(len(self.commands), 2)
        self.assertIn("consecutive failed rounds", result["stopped_because"])
        self.assertEqual(result["rounds"][-1]["consecutive_failures"], 2)

    def test_a_success_resets_the_failure_budget(self) -> None:
        # fail, succeed (resets), then three successes: the loop runs its full
        # budget instead of stopping on a cumulative failure count.
        result = self.loop(codes=(1, 0, 0), max_rounds=4, max_failures=2)
        self.assertEqual(len(self.commands), 4)
        self.assertIn("max_rounds reached", result["stopped_because"])

    def test_an_inactive_engagement_stops_the_loop(self) -> None:
        # Close it the way the runtime does -- the loop reads lifecycle from the
        # Engagement itself, so nothing here needs a manager method.
        file = self.engagement / "engagement.yaml"
        file.write_text(
            file.read_text(encoding="utf-8").replace(
                "lifecycle: active", "lifecycle: closed"
            ),
            encoding="utf-8",
        )
        result = self.loop(max_rounds=5)
        self.assertEqual(self.commands, [])
        self.assertIn("closed", result["stopped_because"])

    # -- the gate stays --------------------------------------------------

    def test_every_round_goes_through_the_launch_plan(self) -> None:
        # Re-deriving is what keeps the authorization, Skill and capability
        # checks in front of every round rather than only the first.
        self.loop(max_rounds=3)
        self.assertEqual(len(self.plans), 3)
        for plan in self.plans:
            self.assertEqual(plan["profile"], "assessment-web")
            self.assertTrue(plan["dry_run"])
            self.assertEqual(plan["engagement"], self.engagement)
            self.assertIsNone(plan["backend_args"])

    def test_an_unauthorized_engagement_never_reaches_a_round(self) -> None:
        other = "continuous-pending"
        self.create(other, authorization_status="pending")
        # Deliberately unpatched: the real launch is what enforces the gate, and
        # it rejects the engagement before any Skills or capability check runs.
        with self.assertRaises(Exception) as caught:
            run(self.paths, other, run_command=self.fake_runner())
        self.assertIn("authorization", str(caught.exception).lower())
        self.assertEqual(self.commands, [])

    def test_a_workflow_without_a_declared_profile_is_rejected(self) -> None:
        # Every supported workflow is mapped today; the guard exists so a new one
        # cannot silently launch some other profile.
        self.assertEqual(
            continuous._profile_for(self.paths, "assessment"), "assessment-web"
        )
        with self.assertRaises(ValidationError):
            continuous._profile_for(self.paths, "no-such-workflow")

    def test_bounds_must_be_positive(self) -> None:
        for kwargs in ({"max_rounds": 0}, {"max_failures": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    run(self.paths, self.slug, **kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
