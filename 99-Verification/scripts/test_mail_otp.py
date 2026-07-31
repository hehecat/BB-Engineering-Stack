#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from email.message import EmailMessage
from email import policy as email_policy
from email.parser import BytesParser
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.mail_otp import (
    MailOtpClient,
    MailOtpError,
    MailSettings,
    add_mail_subcommands,
    config_path,
    extract_codes,
    load_config,
    main,
    message_text,
    parse_config,
    run_mail_command,
    write_config,
)

import argparse


class FakeImap:
    def __init__(self, messages: dict[bytes, bytes]):
        self.messages = messages
        self.login_args: tuple[str, str] | None = None
        self.auth_payload: bytes | None = None
        self.selected: tuple[str, bool] | None = None
        self.select_status = "OK"
        self.logged_out = False

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.login_args = (user, password)
        return "OK", [b"logged in"]

    def authenticate(self, mechanism: str, callback: object) -> tuple[str, list[bytes]]:
        self.auth_payload = callback(b"")  # type: ignore[operator]
        return "OK", [mechanism.encode()]

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.selected = (folder, readonly)
        return self.select_status, [str(len(self.messages)).encode()]

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        if command == "search":
            return "OK", [b" ".join(self.messages)]
        if command == "fetch":
            uid = args[0]
            assert isinstance(uid, bytes)
            metadata = (
                b'1 (UID ' + uid + b' INTERNALDATE "31-Jul-2026 10:00:00 +0000")'
            )
            return "OK", [(metadata, self.messages[uid]), b")"]
        raise AssertionError(command)

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return "BYE", [b"logout"]


def make_message(subject: str, body: str, *, html: bool = False) -> bytes:
    message = EmailMessage()
    message["Date"] = datetime.now(timezone.utc)
    message["From"] = "Lab Login <login@example.test>"
    message["To"] = "operator@example.test"
    message["Subject"] = subject
    message.set_content(body, subtype="html" if html else "plain")
    return message.as_bytes()


class MailOtpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-mail-otp-")
        self.home = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_config_round_trip_is_literal_and_mode_600(self) -> None:
        path = config_path(self.home)
        marker = self.home / "must-not-exist"
        values = {
            "MAIL_OTP_HOST": "imap.example.test",
            "MAIL_OTP_USER": "operator@example.test",
            "MAIL_OTP_PASSWORD": f"space # $() ' ; touch {marker}",
            "MAIL_OTP_AUTH": "password",
        }
        write_config(path, values)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(load_config(path), values)
        self.assertFalse(marker.exists())

    def test_config_parser_rejects_unsupported_lines(self) -> None:
        path = self.home / "invalid.env"
        path.write_text("MAIL_OTP_HOST=ok\nBAD-NAME=value\n", encoding="utf-8")
        with self.assertRaisesRegex(MailOtpError, "invalid mailbox config lines: 2"):
            parse_config(path)

    def test_settings_require_matching_secret(self) -> None:
        password = MailSettings.from_values(
            {
                "MAIL_OTP_HOST": "imap.example.test",
                "MAIL_OTP_USER": "operator@example.test",
                "MAIL_OTP_PASSWORD": "app-pass",
            }
        )
        self.assertEqual(password.port, 993)
        oauth = MailSettings.from_values(
            {
                "MAIL_OTP_HOST": "imap.example.test",
                "MAIL_OTP_USER": "operator@example.test",
                "MAIL_OTP_AUTH": "oauth2",
                "MAIL_OTP_ACCESS_TOKEN": "access-token",
            }
        )
        self.assertEqual(oauth.auth, "oauth2")

    def test_extracts_contextual_plain_html_and_split_codes(self) -> None:
        plain = make_message("Sign-in", "Your verification code is 123-456.")
        html = make_message("Security code AB12CD", "<b>OTP: 847291</b>", html=True)
        parsed_plain = BytesParser(policy=email_policy.default).parsebytes(plain)
        parsed_html = BytesParser(policy=email_policy.default).parsebytes(html)
        plain_codes = extract_codes(
            str(parsed_plain["Subject"]), message_text(parsed_plain)
        )
        html_codes = extract_codes(
            str(parsed_html["Subject"]), message_text(parsed_html)
        )
        self.assertEqual(plain_codes[0], "123456")
        self.assertIn("847291", html_codes)
        self.assertIn("AB12CD", html_codes)

    def test_fake_imap_password_query_returns_latest_code(self) -> None:
        fake = FakeImap(
            {
                b"10": make_message("Older", "No code in this message."),
                b"11": make_message("Login code", "Your one-time code is 642913."),
            }
        )
        settings = MailSettings.from_values(
            {
                "MAIL_OTP_HOST": "imap.example.test",
                "MAIL_OTP_USER": "operator@example.test",
                "MAIL_OTP_PASSWORD": "private-app-pass",
            }
        )
        with patch("bb_stack.mail_otp.imaplib.IMAP4_SSL", return_value=fake):
            results = MailOtpClient(settings).list_messages(since_minutes=10, limit=5)
        self.assertEqual(results[0].uid, "11")
        self.assertEqual(results[0].code, "642913")
        self.assertEqual(fake.login_args, ("operator@example.test", "private-app-pass"))
        self.assertEqual(fake.selected, ("INBOX", True))
        self.assertTrue(fake.logged_out)

    def test_fake_imap_oauth_payload_is_xoauth2(self) -> None:
        fake = FakeImap({})
        settings = MailSettings.from_values(
            {
                "MAIL_OTP_HOST": "imap.example.test",
                "MAIL_OTP_USER": "operator@example.test",
                "MAIL_OTP_AUTH": "oauth2",
                "MAIL_OTP_ACCESS_TOKEN": "oauth-secret",
            }
        )
        with patch("bb_stack.mail_otp.imaplib.IMAP4_SSL", return_value=fake):
            MailOtpClient(settings).test()
        self.assertIn(b"auth=Bearer oauth-secret", fake.auth_payload or b"")

    def test_select_failure_closes_authenticated_connection(self) -> None:
        fake = FakeImap({})
        fake.select_status = "NO"
        settings = MailSettings.from_values(
            {
                "MAIL_OTP_HOST": "imap.example.test",
                "MAIL_OTP_USER": "operator@example.test",
                "MAIL_OTP_PASSWORD": "private-app-pass",
            }
        )
        with (
            patch("bb_stack.mail_otp.imaplib.IMAP4_SSL", return_value=fake),
            self.assertRaisesRegex(MailOtpError, "unable to select"),
        ):
            MailOtpClient(settings).test()
        self.assertTrue(fake.logged_out)

    def test_configure_from_stdin_never_prints_password(self) -> None:
        parser = argparse.ArgumentParser()
        add_mail_subcommands(parser)
        args = parser.parse_args(
            [
                "configure",
                "--provider",
                "gmail",
                "--user",
                "operator@gmail.com",
                "--password-stdin",
                "--json",
            ]
        )
        stdout = StringIO()
        with patch("sys.stdin", StringIO("super-private-app-password\n")), redirect_stdout(stdout):
            self.assertEqual(run_mail_command(args, self.home), 0)
        output = stdout.getvalue()
        self.assertNotIn("super-private-app-password", output)
        self.assertEqual(json.loads(output)["provider"], "gmail")
        values = load_config(config_path(self.home))
        self.assertEqual(values["MAIL_OTP_HOST"], "imap.gmail.com")

    def test_missing_config_fails_without_creating_state(self) -> None:
        with (
            patch.dict(os.environ, {"HOME": str(self.home)}),
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(main(["--test"]), 2)
        self.assertFalse(config_path(self.home).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
