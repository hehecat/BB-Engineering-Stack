#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.configuration import ConfigurationManager
from bb_stack.engagement import EngagementManager
from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths
from bb_stack.portable import PortableManager


class PortableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-portable-")
        self.base = Path(self.temporary.name)
        self.source_home = self.base / "source-home"
        self.source = StackPaths(
            ROOT,
            self.source_home,
            self.source_home / "work",
            self.source_home / "config",
            self.source_home / ".claude",
        )
        self.source.ensure_runtime_dirs()
        self.source_config = ConfigurationManager(self.source)
        self.source_config.configure(
            {
                "BB_PROXY_MODE": "mihomo",
                "BB_HTTP_PROXY": "http://127.0.0.1:7890",
                "BB_SOCKS_PROXY": "socks5://127.0.0.1:7891",
                "BB_H1_USERNAME": "portable-user",
                "BB_FILECODEBOX_URL": "https://files.example.test",
                "BB_AGENT_LANGUAGE": "en",
                "BB_EXTRA_PATH": str(self.source_home / "private-bin"),
            }
        )
        EngagementManager(self.source).create(
            "portable-ctf", "https://challenge.invalid", workflow="ctf"
        )
        mail = self.source_home / ".local/share/pentest-mail/config.env"
        mail.parent.mkdir(parents=True)
        mail.write_text('MAIL_PASSWORD="mail-secret-value"\n', encoding="utf-8")
        mail.chmod(0o600)
        secret = (
            self.source.engagements_root
            / "portable-ctf/notes/LAB-CREDS.local.md"
        )
        secret.write_text("engagement-secret-value\n", encoding="utf-8")
        secret.chmod(0o600)
        self.bundle = self.base / "portable.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_export_is_valid_and_excludes_secrets_and_absolute_roots(self) -> None:
        manager = PortableManager(self.source)
        exported = manager.export(self.bundle)
        self.assertTrue(exported["exported"])
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o600)
        raw = self.bundle.read_text(encoding="utf-8")
        self.assertNotIn("mail-secret-value", raw)
        self.assertNotIn("engagement-secret-value", raw)
        self.assertNotIn(str(self.source_home), raw)
        document = json.loads(raw)
        self.assertNotIn("BB_EXTRA_PATH", document["machine_config"])
        self.assertEqual(document["machine_config"]["BB_AGENT_LANGUAGE"], "en")
        inspected = manager.inspect(self.bundle)
        self.assertTrue(inspected["valid"])
        self.assertEqual(inspected["engagements"][0]["slug"], "portable-ctf")
        self.assertEqual(
            inspected["root_intent"]["work_root"],
            {"kind": "home-relative", "path": "work"},
        )

    def test_import_previews_then_honors_conflicts_and_force(self) -> None:
        PortableManager(self.source).export(self.bundle)
        target_home = self.base / "target-home"
        target = StackPaths(
            ROOT,
            target_home,
            target_home / "destination-work",
            target_home / "destination-config",
            target_home / ".claude",
        )
        target.ensure_runtime_dirs()
        target_config = ConfigurationManager(target)
        target_config.configure(
            {"BB_PROXY_MODE": "direct", "BB_H1_USERNAME": "destination-user"}
        )
        manager = PortableManager(target)
        preview = manager.import_document(self.bundle)
        self.assertTrue(preview["preview"])
        self.assertFalse(preview["imported"])
        self.assertEqual(target_config.effective()["BB_PROXY_MODE"], "direct")
        imported = manager.import_document(self.bundle, yes=True)
        decisions = {item["key"]: item["decision"] for item in imported["decisions"]}
        self.assertEqual(decisions["BB_PROXY_MODE"], "skip-nonempty")
        self.assertEqual(decisions["BB_H1_USERNAME"], "skip-nonempty")
        forced = manager.import_document(self.bundle, yes=True, force=True)
        self.assertIn("BB_PROXY_MODE", forced["changed"])
        self.assertEqual(target_config.effective()["BB_PROXY_MODE"], "mihomo")
        self.assertEqual(target_config.effective()["BB_H1_USERNAME"], "portable-user")
        self.assertEqual(target_config.effective()["BB_AGENT_LANGUAGE"], "en")
        self.assertEqual(target.work_root, target_home / "destination-work")

    def test_rejects_unknown_or_mutated_document(self) -> None:
        PortableManager(self.source).export(self.bundle)
        document = json.loads(self.bundle.read_text(encoding="utf-8"))
        document["machine_config"]["MAIL_PASSWORD"] = "not-permitted"
        self.bundle.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(ValidationError):
            PortableManager(self.source).inspect(self.bundle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
