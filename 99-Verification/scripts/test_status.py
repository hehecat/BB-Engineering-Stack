#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack import __version__
from bb_stack.capabilities import CapabilityRegistry
from bb_stack.engagement import EngagementManager
from bb_stack.evaluation import EvaluationManager
from bb_stack.paths import StackPaths
from bb_stack.status import StackStatus, load_machine_config


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-status-")
        home = Path(self.temporary.name)
        self.paths = StackPaths(
            root=ROOT,
            home=home,
            work_root=home / "work",
            config_home=home / "config",
            claude_config_dir=home / ".claude",
        )
        for directory in (
            self.paths.work_root,
            self.paths.config_home,
            self.paths.claude_config_dir,
        ):
            directory.mkdir(parents=True)
        self.manager = StackStatus(self.paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(self, content: str, mode: int = 0o600) -> Path:
        path = self.paths.config_home / "config.env"
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_collect_has_stable_sections_and_redacts_url_secrets(self) -> None:
        self.write_config(
            'BB_PROXY_MODE="direct"\n'
            'BB_HTTP_PROXY="http://proxy-user:proxy-secret@127.0.0.1:7890/path"\n'
            'BB_SOCKS_PROXY="socks5://socks-user:socks-secret@127.0.0.1:7891"\n'
            'BB_H1_USERNAME=""\n'
            'BB_FILECODEBOX_URL="https://box-user:box-secret@example.invalid/private?token=url-secret"\n'
            'BB_EXTRA_PATH=""\n'
        )
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "ALL_PROXY": "",
                "http_proxy": "",
                "https_proxy": "",
                "all_proxy": "",
            },
            clear=False,
        ):
            report = self.manager.collect("ctf-web")

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["machine_config"]["mode"], "600")
        self.assertEqual(
            report["personal"]["file_delivery"]["endpoint"],
            "https://example.invalid",
        )
        self.assertFalse(report["personal"]["file_delivery"]["usable"])
        self.assertIn(
            "delivery.url",
            {item["id"] for item in report["actions"]},
        )
        for section in (
            "paths",
            "workspace",
            "machine_config",
            "proxy",
            "runtime",
            "prompt",
            "evaluation",
            "engagement",
            "skills",
            "capabilities",
            "personal",
            "keysmith",
            "actions",
        ):
            self.assertIn(section, report)
        encoded = json.dumps(report)
        for secret in (
            "proxy-user",
            "proxy-secret",
            "socks-user",
            "socks-secret",
            "box-user",
            "box-secret",
            "url-secret",
            "/private",
        ):
            self.assertNotIn(secret, encoded)

    def test_direct_mode_rejects_upper_or_lower_proxy_residue(self) -> None:
        for variable in ("HTTPS_PROXY", "https_proxy"):
            actions: list[dict[str, str]] = []
            clean = {
                name: ""
                for name in (
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "ALL_PROXY",
                    "http_proxy",
                    "https_proxy",
                    "all_proxy",
                )
            }
            clean[variable] = "http://user:secret@127.0.0.1:7890/path"
            with patch.dict(os.environ, clean, clear=False):
                report = self.manager._proxy({"BB_PROXY_MODE": "direct"}, actions)
            self.assertFalse(report["ready"])
            self.assertFalse(report["configuration_applied"])
            self.assertEqual(actions[0]["id"], "proxy.environment")
            self.assertNotIn("secret", json.dumps(report))

    def test_hackerone_identity_is_only_required_for_hackerone(self) -> None:
        registry = CapabilityRegistry(self.paths)
        actions: list[dict[str, str]] = []
        report = self.manager._personal(
            "web",
            {},
            "hackerone",
            registry,
            check_external=False,
            actions=actions,
        )
        self.assertFalse(report["ready"])
        self.assertTrue(report["hackerone"]["required"])
        self.assertIn("identity.hackerone", {item["id"] for item in actions})

        actions = []
        report = self.manager._personal(
            "ctf-web",
            {},
            "standalone-ctf",
            registry,
            check_external=False,
            actions=actions,
        )
        self.assertTrue(report["ready"])
        self.assertFalse(report["hackerone"]["required"])

    def test_machine_config_reports_syntax_and_never_evaluates_shell(self) -> None:
        marker = self.paths.home / "must-not-exist"
        path = self.write_config(
            f'BB_PROXY_MODE="direct"\nBAD-NAME=x\nBB_EXTRA_PATH="$(touch {marker})"\n'
        )
        values, invalid = load_machine_config(path)
        self.assertEqual(values["BB_PROXY_MODE"], "direct")
        self.assertIn("line 2", invalid)
        self.assertFalse(marker.exists())

    def test_external_mail_check_stops_on_bad_config_permissions(self) -> None:
        mail_config = (
            self.paths.home / ".local" / "share" / "pentest-mail" / "config.env"
        )
        mail_config.parent.mkdir(parents=True)
        mail_config.write_text('MAIL_PASSWORD="private"\n', encoding="utf-8")
        mail_config.chmod(0o644)
        actions: list[dict[str, str]] = []
        with patch.object(self.manager, "_check_mail") as check_mail:
            report = self.manager._personal(
                "web",
                {},
                None,
                CapabilityRegistry(self.paths),
                check_external=True,
                actions=actions,
            )
        check_mail.assert_not_called()
        self.assertEqual(report["external_checks"]["mail"], "invalid-permissions")
        self.assertFalse(report["ready"])
        self.assertIn("mail.permissions", {item["id"] for item in actions})

    def test_partial_mail_config_is_not_reported_usable(self) -> None:
        mail_config = (
            self.paths.home / ".local" / "share" / "pentest-mail" / "config.env"
        )
        mail_config.parent.mkdir(parents=True)
        mail_config.write_text('MAIL_OTP_HOST="imap.example.test"\n', encoding="utf-8")
        mail_config.chmod(0o600)
        actions: list[dict[str, str]] = []
        with patch.object(self.manager, "_check_mail") as check_mail:
            report = self.manager._personal(
                "web",
                {},
                None,
                CapabilityRegistry(self.paths),
                check_external=True,
                actions=actions,
            )
        check_mail.assert_not_called()
        self.assertFalse(report["mail_otp"]["configuration_valid"])
        self.assertFalse(report["mail_otp"]["usable"])
        self.assertEqual(report["external_checks"]["mail"], "invalid-config")
        self.assertFalse(report["ready"])
        self.assertIn("mail.configuration", {item["id"] for item in actions})

    def test_repair_commands_follow_selected_profile(self) -> None:
        actions: list[dict[str, str]] = []
        self.paths.work_root.rmdir()
        self.manager._paths("reverse", actions)
        command = next(
            item["command"] for item in actions if item["id"] == "path.work_root"
        )
        self.assertEqual(command, "bb-stack bootstrap --profile reverse")

    def test_engagement_drives_platform_mode_and_identity_checks(self) -> None:
        self.write_config('BB_PROXY_MODE="direct"\nBB_H1_USERNAME=""\n')
        EngagementManager(self.paths).create(
            "h1-demo",
            "https://example.invalid",
            workflow="bug-bounty",
            platform="hackerone",
            mode="continuous",
        )
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "ALL_PROXY": "",
                "http_proxy": "",
                "https_proxy": "",
                "all_proxy": "",
            },
            clear=False,
        ):
            report = self.manager.collect("web", engagement="h1-demo")
        self.assertEqual(report["prompt"]["selected"], "bb-continuous")
        self.assertEqual(report["prompt"]["platform"], "hackerone")
        self.assertFalse(report["personal"]["ready"])
        self.assertEqual(report["engagement"]["selected"]["slug"], "h1-demo")

        mismatch = self.manager.collect("ctf-web", engagement="h1-demo")
        self.assertFalse(mismatch["engagement"]["profile_matches"])
        self.assertIn(
            "engagement.profile",
            {item["id"] for item in mismatch["actions"]},
        )

    def test_ctf_domain_profiles_are_compatible_and_mode_selects_prompt(self) -> None:
        self.write_config('BB_PROXY_MODE="direct"\n')
        EngagementManager(self.paths).create(
            "apk-ctf",
            "./challenge.apk",
            workflow="ctf",
            platform="standalone-ctf",
            mode="interactive",
        )
        actions: list[dict[str, str]] = []
        engagement = self.manager._engagement("android", "apk-ctf", actions)
        self.assertTrue(engagement["profile_matches"])
        self.assertIn("android", engagement["selected"]["compatible_profiles"])
        self.assertIn("reverse", engagement["selected"]["compatible_profiles"])

        EngagementManager(self.paths).create(
            "continuous-ctf",
            "https://challenge.invalid",
            workflow="ctf",
            platform="standalone-ctf",
            mode="continuous",
        )
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "ALL_PROXY": "",
                "http_proxy": "",
                "https_proxy": "",
                "all_proxy": "",
            },
            clear=False,
        ):
            report = self.manager.collect("ctf-web", engagement="continuous-ctf")
        self.assertEqual(report["prompt"]["selected"], "ctf-replacement")

    def test_agent_evaluation_is_stale_when_contract_changes(self) -> None:
        prompt = Path(self.temporary.name) / "rendered-prompt.md"
        prompt.write_text("evaluation prompt\n", encoding="utf-8")
        latest = {
            "passed": True,
            "profile": "ctf-quick",
            "stack_version": __version__,
            "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "contract_sha256": "old-contract",
        }
        actions: list[dict[str, str]] = []
        with (
            patch.object(EvaluationManager, "latest", return_value=latest),
            patch.object(
                EvaluationManager,
                "contract_sha256",
                return_value="current-contract",
            ),
        ):
            report = self.manager._evaluation("ctf-quick", str(prompt), False, actions)

        self.assertEqual(report["state"], "stale")
        self.assertTrue(report["prompt_matches"])
        self.assertTrue(report["version_matches"])
        self.assertFalse(report["contract_matches"])
        self.assertEqual(actions[0]["id"], "evaluation.agent")
        self.assertEqual(actions[0]["level"], "optional")


if __name__ == "__main__":
    unittest.main(verbosity=2)
