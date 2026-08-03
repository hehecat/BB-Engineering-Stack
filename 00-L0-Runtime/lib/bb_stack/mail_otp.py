from __future__ import annotations

import argparse
import getpass
import imaplib
import json
import os
import re
import shlex
import ssl
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .errors import StackError
from .io import atomic_write


class MailOtpError(StackError):
    pass


_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_CONTEXT_CODE = re.compile(
    r"(?i)(?:verification(?:\s+code)?|security(?:\s+code)?|"
    r"one[ -]?time(?:\s+(?:code|password))?|otp|passcode|code|pin)"
    r"(?:\s+(?:is|number))?\s*[:#-]?\s*"
    r"([A-Z0-9]{2,5}(?:[ -][A-Z0-9]{2,5}){1,2}|[A-Z0-9]{4,10})"
)
_SIX_DIGIT = re.compile(r"(?<!\d)(\d{6,8})(?!\d)")
_SHORT_DIGIT = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_CONFIG_ORDER = (
    "MAIL_OTP_PROVIDER",
    "MAIL_OTP_HOST",
    "MAIL_OTP_PORT",
    "MAIL_OTP_USER",
    "MAIL_OTP_AUTH",
    "MAIL_OTP_PASSWORD",
    "MAIL_OTP_ACCESS_TOKEN",
    "MAIL_OTP_FOLDER",
    "MAIL_OTP_SECURITY",
    "MAIL_OTP_POLL_INTERVAL",
)
_PROVIDERS = {
    "gmail": "imap.gmail.com",
    "outlook": "outlook.office365.com",
}


def config_path(home: Path) -> Path:
    return home / ".local" / "share" / "pentest-mail" / "config.env"


def parse_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    invalid: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if not match:
            invalid.append(str(number))
            continue
        try:
            parsed = shlex.split(match.group(2), comments=True, posix=True)
        except ValueError:
            invalid.append(str(number))
            continue
        if len(parsed) > 1:
            invalid.append(str(number))
            continue
        values[match.group(1)] = parsed[0] if parsed else ""
    if invalid:
        raise MailOtpError("invalid mailbox config lines: " + ", ".join(invalid))
    return values


def load_config(path: Path, *, require_secure: bool = True) -> dict[str, str]:
    if not path.is_file():
        raise MailOtpError(f"mailbox config does not exist: {path}")
    mode = path.stat().st_mode & 0o777
    if require_secure and mode != 0o600:
        raise MailOtpError(
            f"mailbox config must have mode 600, found {mode:03o}: {path}"
        )
    return parse_config(path)


def write_config(path: Path, values: dict[str, str]) -> None:
    lines = ["# Managed by bb-stack mail. Keep this file mode 600."]
    names = [name for name in _CONFIG_ORDER if name in values]
    names.extend(sorted(set(values) - set(names)))
    for name in names:
        value = values[name]
        if "\n" in value or "\r" in value:
            raise MailOtpError(f"mailbox config value contains a newline: {name}")
        lines.append(f"{name}={shlex.quote(value)}")
    atomic_write(path, "\n".join(lines) + "\n", 0o600)


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    user: str
    auth: str
    password: str | None
    access_token: str | None
    folder: str
    security: str
    poll_interval: float

    @classmethod
    def from_values(cls, values: dict[str, str]) -> MailSettings:
        host = values.get("MAIL_OTP_HOST", "").strip()
        user = values.get("MAIL_OTP_USER", "").strip()
        auth = values.get("MAIL_OTP_AUTH", "password").strip().lower()
        security = values.get("MAIL_OTP_SECURITY", "ssl").strip().lower()
        if not host or not user:
            raise MailOtpError("MAIL_OTP_HOST and MAIL_OTP_USER are required")
        if auth not in {"password", "oauth2"}:
            raise MailOtpError("MAIL_OTP_AUTH must be password or oauth2")
        if security not in {"ssl", "starttls"}:
            raise MailOtpError("MAIL_OTP_SECURITY must be ssl or starttls")
        try:
            port = int(
                values.get("MAIL_OTP_PORT", "993" if security == "ssl" else "143")
            )
            poll_interval = float(values.get("MAIL_OTP_POLL_INTERVAL", "5"))
        except ValueError as error:
            raise MailOtpError(
                "MAIL_OTP_PORT and MAIL_OTP_POLL_INTERVAL must be numeric"
            ) from error
        if not 1 <= port <= 65535:
            raise MailOtpError("MAIL_OTP_PORT must be between 1 and 65535")
        if not 1 <= poll_interval <= 60:
            raise MailOtpError(
                "MAIL_OTP_POLL_INTERVAL must be between 1 and 60 seconds"
            )
        password = values.get("MAIL_OTP_PASSWORD") or None
        access_token = values.get("MAIL_OTP_ACCESS_TOKEN") or None
        if auth == "password" and not password:
            raise MailOtpError(
                "MAIL_OTP_PASSWORD is required for password authentication"
            )
        if auth == "oauth2" and not access_token:
            raise MailOtpError(
                "MAIL_OTP_ACCESS_TOKEN is required for oauth2 authentication"
            )
        return cls(
            host=host,
            port=port,
            user=user,
            auth=auth,
            password=password,
            access_token=access_token,
            folder=values.get("MAIL_OTP_FOLDER", "INBOX") or "INBOX",
            security=security,
            poll_interval=poll_interval,
        )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def _html_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except (AssertionError, ValueError):
        return value
    return parser.text()


def message_text(message: Any) -> str:
    chunks: list[str] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_maintype() != "text":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b""
            value = payload.decode(
                part.get_content_charset() or "utf-8", errors="replace"
            )
        if not isinstance(value, str):
            continue
        chunks.append(
            _html_text(value) if part.get_content_type() == "text/html" else value
        )
        if sum(len(chunk) for chunk in chunks) >= 300_000:
            break
    return "\n".join(chunks)[:300_000]


def extract_codes(subject: str, body: str) -> list[str]:
    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = re.sub(r"[ -]", "", value).upper()
        if not 4 <= len(normalized) <= 10 or not normalized.isalnum():
            return
        if not any(character.isdigit() for character in normalized):
            return
        if normalized not in candidates:
            candidates.append(normalized)

    combined = f"{subject}\n{body}"
    for match in _CONTEXT_CODE.finditer(combined):
        add(match.group(1))
    for match in _SIX_DIGIT.finditer(combined):
        add(match.group(1))
    for match in _SHORT_DIGIT.finditer(subject):
        add(match.group(1))
    return candidates


@dataclass(frozen=True)
class MailResult:
    uid: str
    received_at: str | None
    sender: str
    subject: str
    code: str | None


class MailOtpClient:
    def __init__(self, settings: MailSettings):
        self.settings = settings

    def _connect(self) -> imaplib.IMAP4:
        context = ssl.create_default_context()
        connection: imaplib.IMAP4 | None = None
        try:
            if self.settings.security == "ssl":
                connection = imaplib.IMAP4_SSL(
                    self.settings.host,
                    self.settings.port,
                    ssl_context=context,
                    timeout=20,
                )
            else:
                connection = imaplib.IMAP4(
                    self.settings.host, self.settings.port, timeout=20
                )
                connection.starttls(ssl_context=context)
            if self.settings.auth == "password":
                connection.login(self.settings.user, self.settings.password or "")
            else:
                payload = (
                    f"user={self.settings.user}\x01"
                    f"auth=Bearer {self.settings.access_token}\x01\x01"
                ).encode()
                connection.authenticate("XOAUTH2", lambda _: payload)
            status, _ = connection.select(self.settings.folder, readonly=True)
            if status != "OK":
                raise MailOtpError(
                    f"unable to select mailbox folder: {self.settings.folder}"
                )
            return connection
        except MailOtpError:
            if connection is not None:
                self._close(connection)
            raise
        except (imaplib.IMAP4.error, OSError) as error:
            if connection is not None:
                self._close(connection)
            detail = _safe_field(str(error))
            raise MailOtpError(
                "mailbox connection or authentication failed: " + detail
            ) from error

    @staticmethod
    def _close(connection: imaplib.IMAP4) -> None:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    def test(self) -> None:
        connection = self._connect()
        self._close(connection)

    def list_messages(
        self,
        *,
        since_minutes: int,
        limit: int,
        sender: str | None = None,
        subject: str | None = None,
        unseen: bool = False,
    ) -> list[MailResult]:
        if not 1 <= since_minutes <= 43_200:
            raise MailOtpError("since must be between 1 and 43200 minutes")
        if not 1 <= limit <= 100:
            raise MailOtpError("limit must be between 1 and 100")
        threshold = datetime.now(UTC) - timedelta(minutes=since_minutes)
        search_date = (
            f"{threshold.day:02d}-{_MONTHS[threshold.month - 1]}-{threshold.year:04d}"
        )
        connection = self._connect()
        try:
            criteria: list[str] = ["SINCE", search_date]
            if unseen:
                criteria.append("UNSEEN")
            status, data = connection.uid("search", None, *criteria)
            if status != "OK":
                raise MailOtpError("mailbox search failed")
            raw_uids = data[0] if data else b""
            uids = raw_uids.split() if isinstance(raw_uids, bytes) else []
            results: list[MailResult] = []
            scan_limit = min(max(limit * 10, 50), 500)
            for uid in reversed(uids[-scan_limit:]):
                result = self._fetch_one(connection, uid, threshold)
                if result is None:
                    continue
                if sender and sender.casefold() not in result.sender.casefold():
                    continue
                if subject and subject.casefold() not in result.subject.casefold():
                    continue
                results.append(result)
                if len(results) >= limit:
                    break
            return results
        except imaplib.IMAP4.error as error:
            detail = _safe_field(str(error))
            raise MailOtpError("mailbox search or fetch failed: " + detail) from error
        finally:
            self._close(connection)

    def _fetch_one(
        self,
        connection: imaplib.IMAP4,
        uid: bytes,
        threshold: datetime,
    ) -> MailResult | None:
        status, data = connection.uid(
            "fetch", uid, "(INTERNALDATE BODY.PEEK[]<0.1048576>)"
        )
        if status != "OK" or not data:
            return None
        metadata = b""
        raw_message = b""
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                metadata = item[0] if isinstance(item[0], bytes) else b""
                raw_message = item[1] if isinstance(item[1], bytes) else b""
                break
        if not raw_message:
            return None
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        received = _message_datetime(message.get("Date"), metadata)
        if received is not None and received < threshold:
            return None
        subject = _safe_field(str(message.get("Subject") or ""))
        sender = _safe_field(str(message.get("From") or ""))
        codes = extract_codes(subject, message_text(message))
        return MailResult(
            uid=uid.decode("ascii", errors="replace"),
            received_at=received.isoformat() if received else None,
            sender=sender,
            subject=subject,
            code=codes[0] if codes else None,
        )


def _message_datetime(date_header: str | None, metadata: bytes) -> datetime | None:
    if date_header:
        try:
            value = parsedate_to_datetime(date_header)
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            pass
    internal = imaplib.Internaldate2tuple(metadata)
    if internal:
        return datetime.fromtimestamp(time.mktime(internal), UTC)
    return None


def _safe_field(value: str, limit: int = 240) -> str:
    return _CONTROL.sub(" ", value).strip()[:limit]


def _read_secret(prompt: str, *, stdin: bool) -> str:
    if stdin:
        value = sys.stdin.readline().rstrip("\r\n")
    elif sys.stdin.isatty():
        value = getpass.getpass(prompt)
    else:
        raise MailOtpError(
            "use --password-stdin or --token-stdin in a non-interactive shell"
        )
    if not value:
        raise MailOtpError("secret value must not be empty")
    return value


def _mail_settings(path: Path) -> MailSettings:
    return MailSettings.from_values(load_config(path))


def _output(value: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, indent=2, ensure_ascii=True))
    elif isinstance(value, str):
        print(value)
    else:
        print(value)


def _configure(args: argparse.Namespace, path: Path) -> int:
    values = load_config(path, require_secure=False) if path.is_file() else {}
    user = args.user or values.get("MAIL_OTP_USER")
    if not user and sys.stdin.isatty():
        user = input("Mailbox address: ").strip()
    if not user:
        raise MailOtpError("--user is required in a non-interactive shell")
    provider = args.provider
    if provider == "auto":
        domain = user.rsplit("@", 1)[-1].lower()
        if domain in {"gmail.com", "googlemail.com"}:
            provider = "gmail"
        elif domain in {"outlook.com", "hotmail.com", "live.com"}:
            provider = "outlook"
        else:
            provider = "generic"
    host = args.host or _PROVIDERS.get(provider) or values.get("MAIL_OTP_HOST")
    if not host:
        raise MailOtpError("--host is required for a generic IMAP provider")
    auth = args.auth or values.get("MAIL_OTP_AUTH", "password")
    security = args.security or values.get("MAIL_OTP_SECURITY", "ssl")
    port = (
        args.port
        if args.port is not None
        else int(values.get("MAIL_OTP_PORT", "993" if security == "ssl" else "143"))
    )
    if not 1 <= port <= 65535:
        raise MailOtpError("port must be between 1 and 65535")
    poll_interval = (
        args.poll_interval
        if args.poll_interval is not None
        else float(values.get("MAIL_OTP_POLL_INTERVAL", "5"))
    )
    if not 1 <= poll_interval <= 60:
        raise MailOtpError("poll interval must be between 1 and 60 seconds")
    configured = dict(values)
    configured.update(
        {
            "MAIL_OTP_PROVIDER": provider,
            "MAIL_OTP_HOST": host,
            "MAIL_OTP_PORT": str(port),
            "MAIL_OTP_USER": user,
            "MAIL_OTP_AUTH": auth,
            "MAIL_OTP_FOLDER": args.folder or values.get("MAIL_OTP_FOLDER", "INBOX"),
            "MAIL_OTP_SECURITY": security,
            "MAIL_OTP_POLL_INTERVAL": str(poll_interval),
        }
    )
    if auth == "password":
        configured.pop("MAIL_OTP_ACCESS_TOKEN", None)
        if not args.no_secret and (
            args.password_stdin or not configured.get("MAIL_OTP_PASSWORD")
        ):
            configured["MAIL_OTP_PASSWORD"] = _read_secret(
                "Mailbox app password: ", stdin=args.password_stdin
            )
    else:
        configured.pop("MAIL_OTP_PASSWORD", None)
        if not args.no_secret and (
            args.token_stdin or not configured.get("MAIL_OTP_ACCESS_TOKEN")
        ):
            configured["MAIL_OTP_ACCESS_TOKEN"] = _read_secret(
                "OAuth2 access token: ", stdin=args.token_stdin
            )
    write_config(path, configured)
    _output({"configured": True, "path": str(path), "provider": provider}, args.json)
    return 0


def _set_password(args: argparse.Namespace, path: Path) -> int:
    values = load_config(path)
    values["MAIL_OTP_AUTH"] = "password"
    values["MAIL_OTP_PASSWORD"] = _read_secret(
        "Mailbox app password: ", stdin=args.password_stdin
    )
    values.pop("MAIL_OTP_ACCESS_TOKEN", None)
    write_config(path, values)
    _output({"updated": True, "path": str(path)}, args.json)
    return 0


def _query(args: argparse.Namespace, path: Path) -> int:
    client = MailOtpClient(_mail_settings(path))
    if args.mail_action == "test":
        client.test()
        _output({"status": "ok"} if args.json else "MAIL_OTP_OK", args.json)
        return 0
    if args.mail_action == "wait":
        if not 1 <= args.timeout <= 3600:
            raise MailOtpError("timeout must be between 1 and 3600 seconds")
        deadline = time.monotonic() + args.timeout
        while True:
            messages = client.list_messages(
                since_minutes=args.since,
                limit=10,
                sender=args.sender,
                subject=args.subject,
                unseen=args.unseen,
            )
            match = next((item for item in messages if item.code), None)
            if match:
                _emit_result(match, args.json)
                return 0
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MailOtpError(f"no OTP found within {args.timeout} seconds")
            time.sleep(min(client.settings.poll_interval, remaining))
    messages = client.list_messages(
        since_minutes=args.since,
        limit=args.limit if args.mail_action == "list" else 50,
        sender=args.sender,
        subject=args.subject,
        unseen=args.unseen,
    )
    if args.mail_action == "list":
        if args.json:
            _output([asdict(item) for item in messages], True)
        else:
            for item in messages:
                print(
                    "\t".join(
                        (
                            item.received_at or "unknown-time",
                            f"uid={item.uid}",
                            f"from={item.sender or '-'}",
                            f"subject={item.subject or '-'}",
                            f"code={item.code or '-'}",
                        )
                    )
                )
        return 0
    match = next((item for item in messages if item.code), None)
    if not match:
        raise MailOtpError(f"no OTP found in the last {args.since} minutes")
    _emit_result(match, args.json)
    return 0


def _emit_result(result: MailResult, json_output: bool) -> None:
    _output(asdict(result) if json_output else result.code or "", json_output)


def add_mail_subcommands(parser: argparse.ArgumentParser) -> None:
    subcommands = parser.add_subparsers(dest="mail_action", required=True)
    configure = subcommands.add_parser(
        "configure", help="write a mode-600 mailbox config"
    )
    _add_configure_arguments(configure)
    set_password = subcommands.add_parser(
        "set-pass", help="replace the mailbox app password"
    )
    set_password.add_argument("--password-stdin", action="store_true")
    set_password.add_argument("--config", type=Path)
    set_password.add_argument("--json", action="store_true")
    test = subcommands.add_parser(
        "test", help="test IMAP authentication and folder access"
    )
    _add_query_arguments(test, since=False)
    latest = subcommands.add_parser("latest", help="print the newest matching OTP")
    _add_query_arguments(latest, since=True)
    wait = subcommands.add_parser("wait", help="poll until an OTP arrives")
    wait.add_argument("--timeout", type=int, default=120)
    _add_query_arguments(wait, since=True)
    listing = subcommands.add_parser(
        "list", help="list recent message metadata and extracted codes"
    )
    listing.add_argument("--limit", type=int, default=5)
    _add_query_arguments(listing, since=True, default_since=1440)


def _add_configure_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        choices=["auto", "gmail", "outlook", "generic"],
        default="auto",
    )
    parser.add_argument("--user")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--folder")
    parser.add_argument("--security", choices=["ssl", "starttls"])
    parser.add_argument("--auth", choices=["password", "oauth2"])
    parser.add_argument("--poll-interval", type=float)
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--no-secret", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--json", action="store_true")


def _add_query_arguments(
    parser: argparse.ArgumentParser,
    *,
    since: bool,
    default_since: int = 10,
) -> None:
    if since:
        parser.add_argument("--since", type=int, default=default_since)
    else:
        parser.set_defaults(since=10)
    parser.set_defaults(limit=10)
    parser.add_argument("--from", dest="sender")
    parser.add_argument("--subject")
    parser.add_argument("--unseen", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--json", action="store_true")


def run_mail_command(args: argparse.Namespace, home: Path) -> int:
    path = (args.config or config_path(home)).expanduser().resolve()
    if args.mail_action == "configure":
        return _configure(args, path)
    if args.mail_action == "set-pass":
        return _set_password(args, path)
    return _query(args, path)


def _standalone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mail-otp", description="retrieve lab mailbox OTP codes"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test", action="store_true")
    mode.add_argument("--wait", type=int, metavar="SECONDS")
    mode.add_argument("--list", type=int, metavar="N")
    parser.add_argument("--since", type=int)
    parser.add_argument("--from", dest="sender")
    parser.add_argument("--subject")
    parser.add_argument("--unseen", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def _standalone_namespace(argv: Sequence[str]) -> argparse.Namespace:
    parser = _standalone_parser()
    args = parser.parse_args(argv)
    if args.test:
        args.mail_action = "test"
        args.since = args.since if args.since is not None else 10
        args.limit = 10
    elif args.wait is not None:
        args.mail_action = "wait"
        args.timeout = args.wait
        args.since = args.since if args.since is not None else 10
        args.limit = 10
    elif args.list is not None:
        args.mail_action = "list"
        args.limit = args.list
        args.since = args.since if args.since is not None else 1440
    else:
        args.mail_action = "latest"
        args.limit = 10
        args.since = args.since if args.since is not None else 10
    return args


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        actions = {"configure", "set-pass", "test", "latest", "wait", "list"}
        if arguments and arguments[0] in actions:
            parser = argparse.ArgumentParser(prog="mail-otp")
            add_mail_subcommands(parser)
            args = parser.parse_args(arguments)
        else:
            args = _standalone_namespace(arguments)
        home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
        return run_mail_command(args, home)
    except (MailOtpError, OSError, ValueError) as error:
        print(f"mail-otp: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
