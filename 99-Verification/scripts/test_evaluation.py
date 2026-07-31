#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.evaluation import EvaluationManager
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
        self.assertEqual(report["profile_count"], 7)
        self.assertEqual(report["check_count"], 42)

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

    def test_contract_digest_changes_with_routed_skill_content(self) -> None:
        manager = EvaluationManager(self.paths)
        with patch.object(SkillRegistry, "tree_digest", return_value="digest-a"):
            first = manager.contract_sha256("ctf-quick")
        with patch.object(SkillRegistry, "tree_digest", return_value="digest-b"):
            second = manager.contract_sha256("ctf-quick")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
