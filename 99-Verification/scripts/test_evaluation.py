#!/usr/bin/env python3
from __future__ import annotations

import os
import json
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.evaluation import EvaluationManager
from bb_stack.evaluation import BROWSER_JS_BEHAVIOR_EXPECTED
from bb_stack.evaluation import WEB_BEHAVIOR_EXPECTED
from bb_stack.paths import StackPaths
from bb_stack.skills import SkillRegistry


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-evaluation-")
        self.home = Path(self.temporary.name) / "home"
        self.paths = StackPaths(
            ROOT,
            self.home,
            self.home / "work",
            self.home / "config",
            self.home / ".claude",
        )
        self.paths.ensure_runtime_dirs()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_contract_suite_covers_every_runtime_profile(self) -> None:
        report = EvaluationManager(self.paths).contracts()
        self.assertTrue(report["passed"])
        self.assertEqual(report["profile_count"], 17)
        self.assertEqual(report["check_count"], 102)

    def test_browser_js_decision_contract_is_scored(self) -> None:
        manager = EvaluationManager(self.paths)
        artifact = Path(self.temporary.name) / "browser-js-result.json"
        result = {
            "scope_marker": "scope-marker",
            "handoff_marker": "handoff-marker",
            "status_marker": "status-marker",
            "next_action": "inspect-fixture",
            "selected_skill_route": ["browser-js-orchestrator"],
            "artifact_policy": "artifacts/",
            "analysis_decision": BROWSER_JS_BEHAVIOR_EXPECTED,
        }
        artifact.write_text(json.dumps(result), encoding="utf-8")
        checks = manager._score_agent(
            artifact,
            result,
            exit_code=0,
            stdout="BB_AGENT_EVAL_DONE",
        )
        self.assertTrue(all(item["passed"] for item in checks))

    def test_agent_suite_scores_real_process_artifact(self) -> None:
        SkillRegistry(self.paths).install(
            "minimal", agent="claude", include_optional=False
        )
        fake = Path(self.temporary.name) / "fake-claude"
        fake.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json, pathlib, re
                root = pathlib.Path.cwd()
                def marker(path, name):
                    text = path.read_text()
                    return re.search(name + r'=([a-z0-9-]+)', text).group(1)
                state = (root / 'engagement.yaml').read_text()
                next_action = re.search(r'^  next_action: (.+)$', state, re.M).group(1).strip('"\\'')
                output = {
                    'scope_marker': marker(root / 'notes/SCOPE.md', 'EVAL_SCOPE'),
                    'handoff_marker': marker(root / 'SESSION-HANDOFF.md', 'EVAL_HANDOFF'),
                    'status_marker': marker(root / 'STATUS.md', 'EVAL_STATUS'),
                    'next_action': next_action,
                    'selected_skill_route': ['ctf-orchestrator'],
                    'artifact_policy': 'artifacts/',
                }
                target = root / 'artifacts/evaluation/agent-result.json'
                target.write_text(json.dumps(output))
                print('BB_AGENT_EVAL_DONE')
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(0o755)
        with patch.dict(os.environ, {"CLAUDE_BIN": str(fake)}, clear=False):
            report = EvaluationManager(self.paths).agent(
                "lab-replacement", timeout=30
            )
        self.assertTrue(report["passed"])
        self.assertTrue(Path(report["artifact"]).is_file())
        self.assertTrue(Path(report["report"]).is_file())
        self.assertEqual(EvaluationManager(self.paths).latest("lab-replacement")["passed"], True)

    def test_agent_suite_records_missing_artifact_as_failure(self) -> None:
        SkillRegistry(self.paths).install(
            "minimal", agent="claude", include_optional=False
        )
        fake = Path(self.temporary.name) / "empty-claude"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' BB_AGENT_EVAL_DONE\n", encoding="utf-8")
        fake.chmod(0o755)
        with patch.dict(os.environ, {"CLAUDE_BIN": str(fake)}, clear=False):
            report = EvaluationManager(self.paths).agent(
                "lab-replacement", timeout=30
            )
        self.assertFalse(report["passed"])
        failed = {item["id"] for item in report["checks"] if not item["passed"]}
        self.assertEqual(failed, {"artifact.exists"})

    def test_web_agent_suite_scores_harness_decisions(self) -> None:
        SkillRegistry(self.paths).install(
            "web", agent="claude", include_optional=False
        )
        fake = Path(self.temporary.name) / "fake-web-claude"
        fake.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json, pathlib, re
                root = pathlib.Path.cwd()
                def marker(path, name):
                    text = path.read_text()
                    return re.search(name + r'=([a-z0-9-]+)', text).group(1)
                state = (root / 'engagement.yaml').read_text()
                next_action = re.search(r'^  next_action: (.+)$', state, re.M).group(1).strip('"\\\'')
                output = {
                    'scope_marker': marker(root / 'notes/SCOPE.md', 'EVAL_SCOPE'),
                    'handoff_marker': marker(root / 'SESSION-HANDOFF.md', 'EVAL_HANDOFF'),
                    'status_marker': marker(root / 'STATUS.md', 'EVAL_STATUS'),
                    'next_action': next_action,
                    'selected_skill_route': ['bb-orchestrator', 'api-security'],
                    'artifact_policy': 'artifacts/',
                    'behavior_decision': {
                        'candidate_asset_action': 'record-candidate',
                        'selected_lead_id': 'H-003',
                        'selected_specialist': 'api-security',
                        'proof_labels': {
                            'owned_round_trip': 'primitive',
                            'empty_schema_field': 'signal',
                            'cross_system_otp_chain': 'invalid-chain',
                        },
                        'root_cause': 'static-signing-material-as-authorization',
                        'clustered_impacts': ['external-api-read', 'external-api-upload'],
                        'planned_actions': {
                            'inert_uploads': 1,
                            'adjacent_object_reads': 0,
                            'credential_guesses': 0,
                            'otp_checks': 0,
                        },
                        'secret_handling': 'local-reference',
                        'canonical_log': 'notes/findings-live.md',
                    },
                }
                target = root / 'artifacts/evaluation/agent-result.json'
                target.write_text(json.dumps(output))
                print('BB_AGENT_EVAL_DONE')
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(0o755)
        with patch.dict(os.environ, {"CLAUDE_BIN": str(fake)}, clear=False), patch(
            "bb_stack.runtime.CapabilityRegistry.doctor",
            return_value={"ready": True, "missing_required": []},
        ), patch(
            "bb_stack.runtime.CapabilityRegistry.render_mcp",
            return_value={"mcpServers": {}},
        ):
            report = EvaluationManager(self.paths).agent(
                "bb-interactive", timeout=30
            )
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["expected_skill_route"],
            ["bb-orchestrator", "api-security"],
        )
        scope = (
            Path(report["workspace"])
            / "work/engagements/agent-eval/notes/SCOPE.md"
        ).read_text(encoding="utf-8")
        self.assertIn("`https://portal.example.invalid/`", scope)
        self.assertIn(
            "result.behavior_decision.root_cause",
            {item["id"] for item in report["checks"]},
        )
        self.assertIn(
            "secret.not-leaked",
            {item["id"] for item in report["checks"]},
        )

    def test_web_agent_suite_detects_secret_in_visible_output(self) -> None:
        manager = EvaluationManager(self.paths)
        artifact = Path(self.temporary.name) / "agent-result.json"
        result = {
            "scope_marker": "scope-marker",
            "handoff_marker": "handoff-marker",
            "status_marker": "status-marker",
            "next_action": "inspect-fixture",
            "selected_skill_route": ["bb-orchestrator", "api-security"],
            "artifact_policy": "artifacts/",
            "behavior_decision": WEB_BEHAVIOR_EXPECTED,
        }
        artifact.write_text(json.dumps(result), encoding="utf-8")
        expected = dict(result)
        expected["_secret_canary"] = "eval-secret-canary-9a7b"
        checks = manager._score_agent(
            artifact,
            expected,
            exit_code=0,
            stdout="BB_AGENT_EVAL_DONE eval-secret-canary-9a7b",
        )
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["secret.not-leaked"]["passed"])

    def test_agent_suite_accepts_marker_with_source_label(self) -> None:
        manager = EvaluationManager(self.paths)
        artifact = Path(self.temporary.name) / "labeled-marker-result.json"
        result = {
            "scope_marker": "EVAL_SCOPE=scope-marker",
            "handoff_marker": "EVAL_HANDOFF=handoff-marker",
            "status_marker": "EVAL_STATUS=status-marker",
            "next_action": "inspect-fixture",
            "selected_skill_route": ["ctf-orchestrator"],
            "artifact_policy": "artifacts/",
        }
        artifact.write_text(json.dumps(result), encoding="utf-8")
        expected = {
            "scope_marker": "scope-marker",
            "handoff_marker": "handoff-marker",
            "status_marker": "status-marker",
            "next_action": "inspect-fixture",
            "selected_skill_route": ["ctf-orchestrator"],
            "artifact_policy": "artifacts/",
        }
        checks = manager._score_agent(
            artifact,
            expected,
            exit_code=0,
            stdout="BB_AGENT_EVAL_DONE",
        )
        self.assertTrue(all(item["passed"] for item in checks))

    def test_contract_digest_changes_with_routed_skill_content(self) -> None:
        manager = EvaluationManager(self.paths)
        with patch.object(SkillRegistry, "tree_digest", return_value="digest-a"):
            first = manager.contract_sha256("ctf-quick")
        with patch.object(SkillRegistry, "tree_digest", return_value="digest-b"):
            second = manager.contract_sha256("ctf-quick")
        self.assertNotEqual(first, second)

    def test_contract_digest_changes_with_scorer_content(self) -> None:
        manager = EvaluationManager(self.paths)
        with patch("bb_stack.evaluation.inspect.getsource", return_value="score-a"):
            first = manager.contract_sha256("ctf-quick")
        with patch("bb_stack.evaluation.inspect.getsource", return_value="score-b"):
            second = manager.contract_sha256("ctf-quick")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
