#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.engagement import EngagementManager
from bb_stack.errors import ValidationError
from bb_stack.io import dump_json, dump_yaml, load_json, load_yaml
from bb_stack.paths import StackPaths
from bb_stack.recon import BASELINE_STAGE_IDS, ReconManager

# Unused by real processes, so ``os.getpgid`` fails and ``_provider_pgid``
# falls back to the pid while ``os.killpg`` stays patched.
FAKE_PROVIDER_PID = 3_900_001


class FakeProviderProcess:
    """Minimal ``subprocess.Popen`` stand-in for provider execution tests."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        timeout: bool = False,
        pid: int = FAKE_PROVIDER_PID,
    ) -> None:
        self.pid = pid
        self.returncode = returncode
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self._stdout = stdout
        self._stderr = stderr
        self._timeout = timeout

    def communicate(
        self, input: str | None = None, timeout: float | None = None
    ) -> tuple[str, str]:
        if self._timeout:
            raise subprocess.TimeoutExpired("provider", timeout or 0)
        return self._stdout, self._stderr

    def poll(self) -> int | None:
        return None if self._timeout else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -signal.SIGKILL


def _process_alive(pid: int) -> bool:
    """True while ``pid`` still runs; a zombie counts as terminated."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    return stat.rsplit(") ", 1)[1][:1] not in {"Z", "X", "x"}


class ReconManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-recon-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        engagements = EngagementManager(self.paths)
        self.engagement = engagements.create(
            "recon-fixture",
            "https://example.invalid/",
            workflow="bug-bounty",
            authorization_source="Fixture program scope",
            authorization_status="verified",
        )
        self.data = MagicMock()
        self.data.ensure.return_value = {"state": "ready"}
        self.manager = ReconManager(self.paths, data_manager=self.data)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _complete_provider(
        self,
        provider: str,
        command: list[str],
        output: Path,
        log: Path,
    ) -> dict[str, object]:
        output.parent.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix == ".jsonl":
            output.write_text(
                '{"host":"example.invalid","url":"https://example.invalid/"}\n',
                encoding="utf-8",
            )
        else:
            output.write_text("example.invalid\n", encoding="utf-8")
        log.write_text("fixture provider completed\n", encoding="utf-8")
        return {"returncode": 0, "command": command, "error": None}

    def _set_scope(self, assets: list[dict[str, str]]) -> None:
        path = self.engagement / "engagement.yaml"
        state = load_yaml(path)
        state["scope"]["in_scope"] = assets
        dump_yaml(path, state)

    def test_protected_engagement_requires_active_verified_authorization(self) -> None:
        pending = EngagementManager(self.paths).create(
            "pending-recon",
            "example.invalid",
            workflow="bug-bounty",
        )
        with self.assertRaisesRegex(ValidationError, "recorded authorization"):
            self.manager.run(pending)

        EngagementManager(self.paths).transition(
            self.engagement, "paused", "fixture pause"
        )
        with self.assertRaisesRegex(ValidationError, "lifecycle is paused"):
            self.manager.run(self.engagement)

    def test_run_creates_deterministic_artifacts_and_visible_optional_gaps(self) -> None:
        required = set(self.manager.required_providers())
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            report = self.manager.run(self.engagement)

        self.assertEqual(list(report["stages"]), list(BASELINE_STAGE_IDS))
        self.assertTrue(
            all(
                item["state"] in {"completed", "partial"}
                for item in report["stages"].values()
            )
        )
        self.assertEqual(report["state"], "needs_agent_decision")
        self.assertTrue(report["coverage_gaps"])
        self.assertTrue((self.engagement / "recon/state.json").is_file())
        self.assertTrue((self.engagement / "recon/coverage.json").is_file())
        for relative in (
            "inventory",
            "dns",
            "services",
            "urls",
            "javascript",
            "api",
            "cloud",
            "source",
            "leads",
            "logs",
            "branches",
        ):
            self.assertTrue((self.engagement / "recon" / relative).is_dir())
        status = (self.engagement / "STATUS.md").read_text(encoding="utf-8")
        handoff = (self.engagement / "SESSION-HANDOFF.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("<!-- bb-recon:start -->", status)
        self.assertIn("Recon coverage", handoff)

    def test_missing_required_provider_blocks_stage_and_dependents(self) -> None:
        required = set(self.manager.required_providers()) - {"subfinder"}
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            report = self.manager.run(self.engagement)

        self.assertEqual(report["state"], "blocked")
        self.assertEqual(report["stages"]["passive-assets"]["state"], "blocked")
        self.assertIn("subfinder", report["stages"]["passive-assets"]["missing"])
        self.assertEqual(report["stages"]["dns-resolution"]["state"], "pending")

    def test_status_recommends_declared_providers_before_their_stage_runs(self) -> None:
        required = set(self.manager.required_providers())
        with patch.object(
            self.manager,
            "_provider_available",
            side_effect=lambda name: name in required,
        ):
            report = self.manager.status(self.engagement)

        actions = report["recommended_actions"]
        providers = {item.get("provider") for item in actions if item["action"] == "install-provider"}
        self.assertTrue({"arjun", "gau", "naabu", "puredns", "waybackurls"}.issubset(providers))
        self.assertNotIn("arjun", {item["provider"] for item in report["coverage_gaps"]})

    def test_status_recommends_missing_required_provider_without_running_stage(self) -> None:
        with patch.object(
            self.manager,
            "_provider_available",
            side_effect=lambda name: name != "subfinder",
        ):
            report = self.manager.status(self.engagement)

        actions = [
            item
            for item in report["recommended_actions"]
            if item["action"] == "install-provider" and item.get("provider") == "subfinder"
        ]
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0]["required"])
        self.assertIn("passive-assets", actions[0]["stages"])

    def test_status_recommends_search_key_configuration_without_install_action(self) -> None:
        with patch.object(self.manager, "_provider_available", return_value=False):
            report = self.manager.status(self.engagement)

        actions = {
            item["provider"]: item
            for item in report["recommended_actions"]
            if item["action"] == "configure-provider"
        }
        self.assertEqual(actions["exa"]["environment_variable"], "EXA_API_KEY")
        self.assertEqual(actions["tavily"]["environment_variable"], "TAVILY_API_KEY")
        self.assertEqual(actions["brave"]["environment_variable"], "BRAVE_SEARCH_API_KEY")
        self.assertNotIn("exa", {
            item.get("provider")
            for item in report["recommended_actions"]
            if item["action"] == "install-provider"
        })

    def test_resume_only_retries_unfinished_work(self) -> None:
        available = set(self.manager.required_providers()) - {"subfinder"}
        calls: list[str] = []

        def execute(
            provider: str,
            command: list[str],
            output: Path,
            log: Path,
        ) -> dict[str, object]:
            calls.append(provider)
            return self._complete_provider(provider, command, output, log)

        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in available,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            self.manager.run(self.engagement)
        completed_before = list(calls)

        available.add("subfinder")
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in available,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            report = self.manager.resume(self.engagement)

        self.assertNotEqual(report["state"], "blocked")
        for provider in completed_before:
            self.assertEqual(calls.count(provider), completed_before.count(provider))
        self.assertEqual(calls.count("subfinder"), 1)

    def test_rerun_cascades_to_dependents_without_repeating_unrelated_stages(self) -> None:
        required = set(self.manager.required_providers())
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            initial = self.manager.run(self.engagement)
            report = self.manager.rerun(
                self.engagement,
                stage_id="passive-assets",
                cascade=True,
                force=True,
            )

        self.assertEqual(
            report["stages"]["organization-assets"]["attempts"],
            initial["stages"]["organization-assets"]["attempts"],
        )
        self.assertEqual(
            report["stages"]["passive-assets"]["attempts"],
            initial["stages"]["passive-assets"]["attempts"] + 1,
        )
        self.assertEqual(
            report["stages"]["dns-resolution"]["attempts"],
            initial["stages"]["dns-resolution"]["attempts"] + 1,
        )

    def test_stage_data_is_ensured_on_demand(self) -> None:
        required = set(self.manager.required_providers())
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            self.manager.run(self.engagement)

        calls = {(call.args[0], tuple(call.args[1])) for call in self.data.ensure.call_args_list}
        self.assertIn(("seclists", ("dns",)), calls)
        self.assertIn(("seclists", ("web",)), calls)
        self.assertIn(("trickest-wordlists", ("recon",)), calls)

    def test_provider_adapters_match_multi_target_input_contracts(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        (recon / "inventory/scope-hosts.txt").write_text(
            "example.invalid\nsecond.example.net\n", encoding="utf-8"
        )
        (recon / "urls/urls.txt").write_text(
            "https://example.invalid/app.js\n"
            "https://example.invalid/index.html\n",
            encoding="utf-8",
        )
        output = recon / "inventory/provider.out"

        subfinder = self.manager._provider_command(
            "subfinder", "passive-assets", "example.invalid", recon, output
        )
        self.assertIn("-dL", subfinder)
        self.assertIn(str(recon / "inventory/scope-hosts.txt"), subfinder)

        bbot = self.manager._provider_command(
            "bbot", "organization-assets", "example.invalid", recon, output
        )
        self.assertIn("-f", bbot)
        self.assertIn("-om", bbot)
        self.assertNotIn("-p", bbot)
        self.assertIn("second.example.net", bbot)
        self.assertIn("--output-dir", bbot)
        self.assertIn("--name", bbot)

        puredns = self.manager._provider_command(
            "puredns", "dns-active", "example.invalid", recon, output
        )
        self.assertEqual(puredns[1], "bruteforce")
        self.assertIn(str(recon / "inventory/scope-hosts.txt"), puredns)

        wayback = self.manager._provider_command(
            "waybackurls", "crawl-archives", "example.invalid", recon, output
        )
        self.assertEqual(wayback, ["waybackurls"])
        self.assertEqual(
            self.manager._provider_stdin("waybackurls", recon),
            "example.invalid\nsecond.example.net\n",
        )

        jsluice = self.manager._provider_command(
            "jsluice", "javascript-api", "example.invalid", recon, output
        )
        self.assertEqual(jsluice, ["jsluice", "urls"])
        self.assertEqual(
            self.manager._provider_stdin("jsluice", recon),
            "https://example.invalid/app.js\n",
        )

        for provider in ("exa", "tavily", "brave"):
            command = self.manager._provider_command(
                provider, "organization-assets", "example.invalid", recon, output
            )
            self.assertEqual(command[0], "bb-search")
            self.assertIn(provider, command)

    def test_provider_availability_is_credential_specific(self) -> None:
        with patch.dict(os.environ, {"EXA_API_KEY": "fixture-exa"}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            os.environ.pop("BRAVE_SEARCH_API_KEY", None)
            self.assertTrue(self.manager._provider_available("exa"))
            self.assertFalse(self.manager._provider_available("tavily"))
            self.assertFalse(self.manager._provider_available("brave"))
        with patch.dict(os.environ, {"TAVILY_API_KEY": "   "}, clear=False):
            os.environ.pop("EXA_API_KEY", None)
            self.assertFalse(self.manager._provider_available("tavily"))
            os.environ["EXA_API_KEY"] = "fixture-exa"
            self.assertTrue(self.manager._provider_available("exa"))

    def test_provider_availability_requires_both_puredns_binaries(self) -> None:
        def which(name: str, **_: object) -> str | None:
            return f"/usr/bin/{name}" if name == "puredns" else None

        with patch("bb_stack.recon.shutil.which", side_effect=which):
            self.assertFalse(self.manager._provider_available("puredns"))
        with patch("bb_stack.recon.shutil.which", return_value="/usr/bin/tool"):
            self.assertTrue(self.manager._provider_available("puredns"))
            self.assertTrue(self.manager._provider_available("subfinder"))
        with patch("bb_stack.recon.shutil.which", return_value=None):
            self.assertFalse(self.manager._provider_available("puredns"))
            self.assertFalse(self.manager._provider_available("subfinder"))


    def test_bbot_output_is_archived_to_the_declared_artifact(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/organization-assets.bbot.jsonl"
        log = recon / "logs/organization-assets.bbot.log"
        command = self.manager._provider_command(
            "bbot", "organization-assets", "example.invalid", recon, output
        )

        def run_bbot(command: list[str], **_: object) -> FakeProviderProcess:
            output_dir = Path(command[command.index("--output-dir") + 1])
            scan_name = command[command.index("--name") + 1]
            generated = output_dir / scan_name / "output.json"
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text('{"type":"DNS_NAME","data":"example.invalid"}\n')
            return FakeProviderProcess()

        with patch("bb_stack.recon.subprocess.Popen", side_effect=run_bbot):
            result = self.manager._execute_provider("bbot", command, output, log)

        self.assertEqual(result["returncode"], 0)
        self.assertEqual(
            output.read_text(encoding="utf-8"),
            '{"type":"DNS_NAME","data":"example.invalid"}\n',
        )

    def test_bbot_success_without_generated_output_is_a_failure(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/organization-assets.bbot.jsonl"
        log = recon / "logs/organization-assets.bbot.log"
        output.write_text("stale artifact\n", encoding="utf-8")
        command = self.manager._provider_command(
            "bbot", "organization-assets", "example.invalid", recon, output
        )

        with patch(
            "bb_stack.recon.subprocess.Popen",
            return_value=FakeProviderProcess(),
        ):
            result = self.manager._execute_provider("bbot", command, output, log)

        self.assertEqual(result["returncode"], 1)
        self.assertEqual(result["error"], "BBOT did not create output.json")
        self.assertFalse(output.exists())

    def test_subfinder_timeout_promotes_only_the_current_attempt_as_partial(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/passive-assets.subfinder.txt"
        log = recon / "logs/passive-assets.subfinder.log"
        output.write_text("stale.example.invalid\n", encoding="utf-8")
        command = self.manager._provider_command(
            "subfinder", "passive-assets", "example.invalid", recon, output
        )

        def timeout(command: list[str], **_: object) -> FakeProviderProcess:
            attempt = Path(command[command.index("-o") + 1])
            attempt.write_text("fresh.example.invalid\n", encoding="utf-8")
            return FakeProviderProcess(timeout=True)

        kill_calls: list[tuple[int, int]] = []

        def fake_killpg(pgid: int, sig: int) -> None:
            if sig == 0:
                raise ProcessLookupError(pgid)
            kill_calls.append((pgid, sig))

        with (
            patch("bb_stack.recon.subprocess.Popen", side_effect=timeout),
            patch("os.killpg", side_effect=fake_killpg),
        ):
            result = self.manager._execute_provider("subfinder", command, output, log)

        self.assertEqual(kill_calls, [(FAKE_PROVIDER_PID, signal.SIGTERM)])
        self.assertEqual(result["state"], "partial")
        self.assertTrue(result["artifact_usable"])
        self.assertEqual(output.read_text(encoding="utf-8"), "fresh.example.invalid\n")
        self.assertIn("TimeoutExpired", log.read_text(encoding="utf-8"))
        self.assertIn(
            f"process_group: {FAKE_PROVIDER_PID}", log.read_text(encoding="utf-8")
        )

    def test_provider_success_without_attempt_file_replaces_stale_output(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/passive-assets.subfinder.txt"
        log = recon / "logs/passive-assets.subfinder.log"
        output.write_text("stale.example.invalid\n", encoding="utf-8")
        command = self.manager._provider_command(
            "subfinder", "passive-assets", "example.invalid", recon, output
        )

        with patch(
            "bb_stack.recon.subprocess.Popen",
            return_value=FakeProviderProcess(stdout="fresh.example.invalid\n"),
        ):
            result = self.manager._execute_provider("subfinder", command, output, log)

        self.assertEqual(result["state"], "completed")
        self.assertEqual(output.read_text(encoding="utf-8"), "fresh.example.invalid\n")

    def test_stdout_provider_success_replaces_stale_output(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/passive-assets.assetfinder.txt"
        log = recon / "logs/passive-assets.assetfinder.log"
        output.write_text("stale.example.invalid\n", encoding="utf-8")
        command = self.manager._provider_command(
            "assetfinder", "passive-assets", "example.invalid", recon, output
        )

        with patch(
            "bb_stack.recon.subprocess.Popen",
            return_value=FakeProviderProcess(stdout="fresh.example.invalid\n"),
        ):
            result = self.manager._execute_provider("assetfinder", command, output, log)

        self.assertEqual(result["state"], "completed")
        self.assertEqual(output.read_text(encoding="utf-8"), "fresh.example.invalid\n")

    def test_provider_launch_isolates_the_process_group(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/passive-assets.assetfinder.txt"
        log = recon / "logs/passive-assets.assetfinder.log"
        command = self.manager._provider_command(
            "assetfinder", "passive-assets", "example.invalid", recon, output
        )
        launches: list[dict[str, object]] = []

        def fake_popen(
            execution_command: list[str], **kwargs: object
        ) -> FakeProviderProcess:
            launches.append({"command": execution_command, **kwargs})
            return FakeProviderProcess(stdout="fresh.example.invalid\n")

        with patch("bb_stack.recon.subprocess.Popen", side_effect=fake_popen):
            result = self.manager._execute_provider(
                "assetfinder", command, output, log
            )

        self.assertEqual(result["state"], "completed")
        self.assertEqual(len(launches), 1)
        self.assertIs(launches[0]["start_new_session"], True)
        self.assertEqual(launches[0]["stdin"], subprocess.PIPE)

    def test_provider_timeout_terminates_the_whole_process_group(self) -> None:
        self.manager._ensure_layout(self.engagement)
        recon = self.engagement / "recon"
        output = recon / "inventory/passive-assets.assetfinder.txt"
        log = recon / "logs/passive-assets.assetfinder.log"
        marker = Path(self.temporary.name) / "grandchild.pid"
        script = Path(self.temporary.name) / "provider_with_grandchild.py"
        script.write_text(
            "import subprocess, sys, time\n"
            "child = subprocess.Popen(\n"
            "    [sys.executable, '-c', 'import time; time.sleep(300)']\n"
            ")\n"
            f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(300)\n",
            encoding="utf-8",
        )
        command = [sys.executable, str(script)]

        with patch.object(self.manager, "_provider_timeout", return_value=1):
            result = self.manager._execute_provider("assetfinder", command, output, log)

        self.assertEqual(
            sorted(result),
            [
                "artifact_usable",
                "command",
                "error",
                "error_kind",
                "returncode",
                "state",
            ],
        )
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_kind"], "timeout")
        grandchild = int(marker.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _process_alive(grandchild):
            time.sleep(0.05)
        self.assertFalse(
            _process_alive(grandchild),
            f"grandchild {grandchild} outlived the provider timeout",
        )

    def test_required_partial_provider_allows_dependents_and_creates_gap(self) -> None:
        required = set(self.manager.required_providers())

        def execute(
            provider: str,
            command: list[str],
            output: Path,
            log: Path,
        ) -> dict[str, object]:
            result = self._complete_provider(provider, command, output, log)
            if provider == "subfinder":
                result.update(
                    {
                        "state": "partial",
                        "returncode": 1,
                        "artifact_usable": True,
                        "error": "provider timed out",
                    }
                )
            return result

        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            report = self.manager.run(self.engagement)

        self.assertEqual(report["stages"]["passive-assets"]["state"], "partial")
        self.assertNotEqual(report["stages"]["dns-resolution"]["state"], "pending")
        gaps = {item["id"] for item in report["coverage_gaps"]}
        self.assertIn("passive-assets.subfinder", gaps)
        reruns = [
            item
            for item in report["recommended_actions"]
            if item["action"] == "rerun-stage"
        ]
        self.assertEqual(reruns[0]["stage"], "passive-assets")
        self.assertIn("--cascade", reruns[0]["command"])

    def test_provider_timeout_uses_recon_configuration(self) -> None:
        self.assertEqual(self.manager._provider_timeout("subfinder"), 900)

    def test_legacy_state_is_migrated_before_schema_validation(self) -> None:
        state = self.manager.status(self.engagement)
        state.pop("scope_candidates")
        state["stages"].pop("cloud-source")
        state["signals"] = [
            {
                "id": "legacy-graphql",
                "kind": "graphql-endpoint",
                "area": "graphql",
                "target": "https://example.invalid/graphql",
                "status": "pending",
            }
        ]
        dump_json(self.engagement / "recon/state.json", state)

        migrated = self.manager.status(self.engagement)

        self.assertEqual(migrated["scope_candidates"], [])
        self.assertIn("cloud-source", migrated["stages"])
        self.assertEqual(migrated["stages"]["cloud-source"]["state"], "pending")
        self.assertEqual(
            migrated["signals"],
            [
                {
                    "id": "legacy-graphql",
                    "type": "graphql-endpoint",
                    "area": "graphql",
                    "value": "https://example.invalid/graphql",
                    "state": "open",
                    "source": "recon/state.json",
                }
            ],
        )
        self.assertEqual(
            load_json(self.engagement / "recon/state.json")["signals"],
            migrated["signals"],
        )

    def test_expand_preserves_reason_and_does_not_replace_baseline(self) -> None:
        with (
            patch.object(self.manager, "_provider_available", return_value=True),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            branch = self.manager.expand(
                self.engagement,
                area="api",
                target="https://example.invalid/graphql",
                reason="GraphQL endpoint observed in JavaScript",
            )

        self.assertEqual(branch["area"], "api")
        self.assertEqual(branch["state"], "completed")
        self.assertEqual(branch["reason"], "GraphQL endpoint observed in JavaScript")
        status = self.manager.status(self.engagement)
        self.assertEqual(len(status["branches"]), 1)
        self.assertEqual(status["stages"]["scope"]["state"], "pending")

    def test_expand_rejects_targets_outside_written_scope(self) -> None:
        with self.assertRaisesRegex(ValidationError, "outside written scope"):
            self.manager.expand(
                self.engagement,
                area="api",
                target="https://api.example.invalid/graphql",
                reason="Candidate endpoint requires scope review",
            )

    def test_passive_discovery_is_partitioned_before_active_stages(self) -> None:
        required = set(self.manager.required_providers())

        def execute(
            provider: str,
            command: list[str],
            output: Path,
            log: Path,
        ) -> dict[str, object]:
            result = self._complete_provider(provider, command, output, log)
            if provider == "subfinder":
                output.write_text(
                    "example.invalid\napi.example.invalid\noutside.example.org\n",
                    encoding="utf-8",
                )
            return result

        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            self.manager.run(self.engagement)

        active = (self.engagement / "recon/dns/candidates.txt").read_text(
            encoding="utf-8"
        )
        candidates = (self.engagement / "recon/inventory/candidates.jsonl").read_text(
            encoding="utf-8"
        )
        self.assertIn("example.invalid", active)
        self.assertNotIn("api.example.invalid", active)
        self.assertNotIn("outside.example.org", active)
        self.assertIn('"value": "api.example.invalid"', candidates)
        self.assertIn('"scope_state": "candidate"', candidates)

    def test_domain_scope_promotes_matching_discovered_subdomains(self) -> None:
        self._set_scope([{"type": "domain", "pattern": "example.invalid"}])
        required = set(self.manager.required_providers())

        def execute(
            provider: str,
            command: list[str],
            output: Path,
            log: Path,
        ) -> dict[str, object]:
            result = self._complete_provider(provider, command, output, log)
            if provider == "subfinder":
                output.write_text(
                    "api.example.invalid\noutside.example.org\n", encoding="utf-8"
                )
            return result

        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            self.manager.run(self.engagement)

        active = (self.engagement / "recon/dns/candidates.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("api.example.invalid", active)
        self.assertNotIn("outside.example.org", active)

    def test_all_written_scope_assets_seed_recon_inputs(self) -> None:
        self._set_scope(
            [
                {"type": "domain", "pattern": "example.invalid"},
                {"type": "host", "pattern": "second.example.net"},
            ]
        )
        required = set(self.manager.required_providers())
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            self.manager.run(self.engagement)

        active = (self.engagement / "recon/dns/candidates.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("example.invalid", active)
        self.assertIn("second.example.net", active)

    def test_normalization_emits_adaptive_signals(self) -> None:
        required = set(self.manager.required_providers())

        def execute(
            provider: str,
            command: list[str],
            output: Path,
            log: Path,
        ) -> dict[str, object]:
            result = self._complete_provider(provider, command, output, log)
            if provider == "katana":
                output.write_text(
                    '{"url":"https://example.invalid/graphql"}\n'
                    '{"url":"https://example.invalid/assets/app.js.map"}\n',
                    encoding="utf-8",
                )
            return result

        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            report = self.manager.run(self.engagement)

        signal_types = {item["type"] for item in report["signals"]}
        self.assertIn("graphql-endpoint", signal_types)
        self.assertIn("source-map", signal_types)
        self.assertTrue(all(item["state"] == "open" for item in report["signals"]))
        self.assertTrue(
            any(item["action"] == "expand" for item in report["recommended_actions"])
        )

        gaps = [item["id"] for item in report["coverage_gaps"]]
        with self.assertRaisesRegex(ValidationError, "open adaptive signals"):
            self.manager.close(
                self.engagement,
                reason="Fixture baseline reviewed",
                accept_gaps=gaps,
            )

        signal = next(
            item for item in report["signals"] if item["type"] == "graphql-endpoint"
        )
        with (
            patch.object(self.manager, "_provider_available", return_value=True),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            branch = self.manager.expand(
                self.engagement,
                area=signal["area"],
                target=signal["value"],
                reason="Investigate normalized signal",
                signal_id=signal["id"],
            )
        updated = self.manager.status(self.engagement)
        consumed = next(item for item in updated["signals"] if item["id"] == signal["id"])
        self.assertEqual(consumed["state"], "expanded")
        self.assertEqual(consumed["branch_id"], branch["id"])

    def test_close_requires_explicit_scope_candidate_decisions(self) -> None:
        required = set(self.manager.required_providers())

        def execute(
            provider: str,
            command: list[str],
            output: Path,
            log: Path,
        ) -> dict[str, object]:
            result = self._complete_provider(provider, command, output, log)
            if provider == "subfinder":
                output.write_text("api.example.invalid\n", encoding="utf-8")
            return result

        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(self.manager, "_execute_provider", side_effect=execute),
        ):
            report = self.manager.run(self.engagement)

        gaps = [item["id"] for item in report["coverage_gaps"]]
        with self.assertRaisesRegex(ValidationError, "scope candidates"):
            self.manager.close(
                self.engagement,
                reason="Fixture baseline reviewed",
                accept_gaps=gaps,
            )
        candidate_ids = [item["id"] for item in report["scope_candidates"]]
        closed = self.manager.close(
            self.engagement,
            reason="Candidate assets deferred pending written scope revision",
            accept_gaps=gaps,
            accept_candidates=candidate_ids,
        )
        self.assertEqual(closed["state"], "closed_with_gaps")

    def test_close_rejects_unfinished_baseline_and_unacknowledged_gaps(self) -> None:
        with self.assertRaisesRegex(ValidationError, "baseline stages"):
            self.manager.close(self.engagement, reason="fixture complete")

        required = set(self.manager.required_providers())
        with (
            patch.object(
                self.manager,
                "_provider_available",
                side_effect=lambda name: name in required,
            ),
            patch.object(
                self.manager, "_execute_provider", side_effect=self._complete_provider
            ),
        ):
            report = self.manager.run(self.engagement)

        with self.assertRaisesRegex(ValidationError, "coverage gaps"):
            self.manager.close(self.engagement, reason="fixture complete")

        gap_ids = [item["id"] for item in report["coverage_gaps"]]
        closed = self.manager.close(
            self.engagement,
            reason="Optional enrichment deferred after baseline completion",
            accept_gaps=gap_ids,
        )
        self.assertEqual(closed["state"], "closed_with_gaps")
        self.assertTrue(closed["closed_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
