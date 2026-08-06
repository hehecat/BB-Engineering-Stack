from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .configuration import ConfigurationManager, url_origin
from .errors import CommandError, ValidationError
from .paths import StackPaths

EXPIRY_STYLES = ("day", "hour", "minute", "count", "forever")
_PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _origin(paths: StackPaths) -> str:
    configured = ConfigurationManager(paths).effective().get("BB_FILECODEBOX_URL", "")
    origin = url_origin(configured, {"http", "https"})
    if not origin:
        raise ValidationError(
            "BB_FILECODEBOX_URL is not configured; run "
            "bb-stack configure --filecodebox-url https://filebox.example"
        )
    return origin.rstrip("/")


def _request_environment(paths: StackPaths) -> dict[str, str]:
    machine = ConfigurationManager(paths).effective()
    environment = paths.environment()
    for name in _PROXY_ENV_NAMES:
        environment.pop(name, None)
    if machine["BB_PROXY_MODE"] == "mihomo":
        environment.update(
            {
                "HTTP_PROXY": machine["BB_HTTP_PROXY"],
                "HTTPS_PROXY": machine["BB_HTTP_PROXY"],
                "ALL_PROXY": machine["BB_SOCKS_PROXY"],
            }
        )
    environment["PATH"] = paths.runtime_path(machine.get("BB_EXTRA_PATH", ""))
    return environment


def _token_config(token: str) -> str:
    if any(character in token for character in ("\x00", "\r", "\n")):
        raise ValidationError("FileCodeBox token contains an invalid control character")
    escaped = token.replace("\\", "\\\\").replace('"', '\\"')
    return f'header = "Authorization: Bearer {escaped}"\n'


def _file_form(source: Path) -> str:
    escaped = str(source).replace("\\", "\\\\").replace('"', '\\"')
    return f'file=@"{escaped}"'


def _response_error(raw: str, fallback: str) -> str:
    if raw:
        try:
            response = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(response, dict):
            return str(response.get("detail", response.get("msg", response)))
        return str(response)
    return fallback or "unknown FileCodeBox error"


def upload_file(
    paths: StackPaths,
    source: Path,
    *,
    expire_value: int = 1,
    expire_style: str = "day",
    token: str | None = None,
) -> dict[str, Any]:
    """Upload one file through FileCodeBox's ordinary multipart API."""
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"upload source is not a file: {source}")
    if expire_value < 1:
        raise ValidationError("expire value must be at least 1")
    if expire_style not in EXPIRY_STYLES:
        raise ValidationError(
            "expire style must be one of: " + ", ".join(EXPIRY_STYLES)
        )

    origin = _origin(paths)
    endpoint = urljoin(origin + "/", "share/file/")
    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "600",
        "--request",
        "POST",
        endpoint,
        "--form",
        _file_form(source),
        "--form",
        f"expire_value={expire_value}",
        "--form",
        f"expire_style={expire_style}",
    ]
    curl_config = None
    if token:
        command.extend(["--config", "-"])
        curl_config = _token_config(token)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=curl_config,
            env=_request_environment(paths),
            timeout=615,
            check=False,
        )
    except FileNotFoundError as error:
        raise CommandError("curl is required for FileCodeBox uploads") from error
    except subprocess.TimeoutExpired as error:
        raise CommandError("FileCodeBox upload timed out after 615 seconds") from error

    raw = completed.stdout.strip()
    if completed.returncode != 0:
        detail = _response_error(raw, completed.stderr.strip())
        raise CommandError(f"FileCodeBox upload failed: {detail}")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CommandError("FileCodeBox returned invalid JSON") from error
    if not isinstance(response, dict):
        raise CommandError("FileCodeBox returned a JSON value that is not an object")
    if response.get("code") != 200:
        detail = response.get("detail", response.get("msg", response))
        raise CommandError(f"FileCodeBox rejected upload: {detail}")
    detail = response.get("detail")
    if not isinstance(detail, dict) or not detail.get("code"):
        raise CommandError("FileCodeBox response did not include a share code")
    return {
        "provider": "filecodebox",
        "endpoint": endpoint,
        "source": str(source),
        "share_code": str(detail["code"]),
        "name": detail.get("name", source.name),
        "expire_value": expire_value,
        "expire_style": expire_style,
        "share_url": f"{origin}/share/select/?code={detail['code']}",
    }


def add_filecodebox_subcommands(parser: Any) -> None:
    filecodebox = parser.add_parser(
        "filecodebox", help="upload files through the configured FileCodeBox API"
    )
    subcommands = filecodebox.add_subparsers(dest="filecodebox_command", required=True)
    upload = subcommands.add_parser(
        "upload", help="upload one file and return its FileCodeBox share code"
    )
    upload.add_argument("source", type=Path)
    upload.add_argument("--expire-value", type=int, default=1)
    upload.add_argument("--expire-style", choices=EXPIRY_STYLES, default="day")
    upload.add_argument(
        "--token-stdin",
        action="store_true",
        help="read an optional FileCodeBox Bearer token from stdin",
    )
    upload.add_argument("--json", action="store_true")


def run_filecodebox_command(args: Any, paths: StackPaths) -> int:
    if args.filecodebox_command != "upload":
        raise ValidationError(
            f"unsupported filecodebox command: {args.filecodebox_command}"
        )
    token = None
    if args.token_stdin:
        token = sys.stdin.readline().strip()
        if not token:
            raise ValidationError("--token-stdin did not provide a token")
    result = upload_file(
        paths,
        args.source,
        expire_value=args.expire_value,
        expire_style=args.expire_style,
        token=token,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0
