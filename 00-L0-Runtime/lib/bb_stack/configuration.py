from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import StackError, ValidationError
from .io import atomic_write
from .paths import StackPaths

MACHINE_CONFIG_DEFAULTS = {
    "BB_PROXY_MODE": "direct",
    "BB_HTTP_PROXY": "http://127.0.0.1:7890",
    "BB_SOCKS_PROXY": "socks5://127.0.0.1:7891",
    "BB_H1_USERNAME": "",
    "BB_FILECODEBOX_URL": "",
    "BB_AGENT_LANGUAGE": "zh-CN",
    "BB_NPM_REGISTRY": "auto",
    "BB_PYPI_INDEX": "https://pypi.org/simple",
    "BB_EXTRA_PATH": "",
}
MACHINE_CONFIG_KEYS = tuple(MACHINE_CONFIG_DEFAULTS)
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$")
# Literal right-hand side: one wrapping quote pair is stripped, nothing else.
_LITERAL_RHS = re.compile(r"'([^']*)'|\"([^\"]*)\"|(.*)", re.S)


def parse_literal_rhs(rhs: str) -> str:
    """Return the literal value of a config.env right-hand side.

    The right-hand side is never shell-evaluated: comments, expansions and
    escapes are preserved verbatim.  Only a single matching pair of wrapping
    quotes is stripped.
    """
    match = _LITERAL_RHS.fullmatch(rhs)
    for group in match.groups() if match else (rhs,):
        if group is not None:
            return group
    return rhs


def serialize_literal(value: str) -> str:
    """Encode *value* so ``parse_literal_rhs(serialize_literal(v)) == v``.

    ``shlex.quote`` is preferred (it produces the canonical shell form), but
    it is only used when its output round-trips through the literal parser —
    e.g. a value containing an apostrophe expands to ``'"'"'`` which a literal
    reader would keep verbatim.  Otherwise the value is emitted raw, wrapping
    it in the opposite quote style only when it otherwise looks quoted.
    """
    if "\n" in value:
        raise ValidationError("config.env values must not contain newlines")
    quoted = shlex.quote(value)
    if parse_literal_rhs(quoted) == value:
        return quoted
    if value.startswith("'") and value.endswith("'") and "'" not in value[1:-1]:
        return f'"{value}"'
    if value.startswith('"') and value.endswith('"') and '"' not in value[1:-1]:
        return f"'{value}'"
    return value


def load_machine_config(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse literal KEY=value assignments without evaluating shell syntax."""
    if not path.is_file():
        return {}, []
    values: dict[str, str] = {}
    invalid: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if not match:
            invalid.append(f"line {number}")
            continue
        values[match.group(1)] = parse_literal_rhs(match.group(2))
    return values, invalid


def url_origin(value: str, schemes: set[str]) -> str | None:
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in schemes or not parsed.hostname:
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{host}{suffix}"


class ConfigurationManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.path = paths.config_home / "config.env"

    def read(self) -> dict[str, str]:
        values, invalid = load_machine_config(self.path)
        if invalid:
            raise ValidationError(
                "unsupported config.env assignments: " + ", ".join(invalid)
            )
        return values

    def effective(self) -> dict[str, str]:
        values = dict(MACHINE_CONFIG_DEFAULTS)
        values.update(
            {key: value for key, value in self.read().items() if key in values}
        )
        return values

    def configure(self, updates: dict[str, str]) -> dict[str, Any]:
        unsupported = sorted(set(updates) - set(MACHINE_CONFIG_KEYS))
        if unsupported:
            raise ValidationError(
                "unsupported machine setting(s): " + ", ".join(unsupported)
            )
        current = self.read() if self.path.is_file() else {}
        merged = dict(MACHINE_CONFIG_DEFAULTS)
        merged.update(current)
        changed = sorted(
            key for key, value in updates.items() if merged.get(key) != value
        )
        merged.update(updates)
        self.validate(merged)
        self.write(merged)
        return {
            "path": str(self.path),
            "changed": changed,
            "unchanged": sorted(set(updates) - set(changed)),
        }

    def write(self, values: dict[str, str]) -> None:
        known = dict(MACHINE_CONFIG_DEFAULTS)
        known.update({key: values[key] for key in MACHINE_CONFIG_KEYS if key in values})
        unknown = {key: value for key, value in values.items() if key not in known}
        lines = [
            "# Managed by bb-stack configure.",
            "# Values are read literally: one wrapping quote pair is stripped, nothing else.",
            "# Store mailbox credentials and engagement secrets in their dedicated locations.",
        ]
        lines.extend(
            f"{key}={serialize_literal(known[key])}" for key in MACHINE_CONFIG_KEYS
        )
        if unknown:
            lines.extend(
                [
                    "",
                    "# Preserved extension settings (not exported by bb-stack portable).",
                ]
            )
            lines.extend(
                f"{key}={serialize_literal(unknown[key])}" for key in sorted(unknown)
            )
        atomic_write(self.path, "\n".join(lines) + "\n", 0o600)

    # Keys shared with portable documents (see 90-Docs/CONFIGURATION.md).
    PORTABLE_CONFIG_KEYS = (
        "BB_PROXY_MODE",
        "BB_HTTP_PROXY",
        "BB_SOCKS_PROXY",
        "BB_H1_USERNAME",
        "BB_FILECODEBOX_URL",
        "BB_AGENT_LANGUAGE",
        "BB_NPM_REGISTRY",
    )
    _PORTABLE_ORIGIN_SCHEMES = {
        "BB_HTTP_PROXY": frozenset({"http", "https"}),
        "BB_SOCKS_PROXY": frozenset({"socks5", "socks5h"}),
        "BB_FILECODEBOX_URL": frozenset({"http", "https"}),
    }

    def portable_config(self, values: dict[str, str] | None = None) -> dict[str, Any]:
        """Project machine configuration onto the portable seven-key subset.

        URL-typed keys are normalized to their origin; an invalid value is an
        error rather than a ``null`` placeholder.
        """
        resolved = self.effective() if values is None else values
        projected: dict[str, Any] = {}
        for key in self.PORTABLE_CONFIG_KEYS:
            value = resolved.get(key, "")
            schemes = self._PORTABLE_ORIGIN_SCHEMES.get(key)
            if schemes is None:
                projected[key] = value
                continue
            origin = url_origin(value, set(schemes))
            if origin is None:
                raise ValidationError(f"{key} is not a valid portable value")
            projected[key] = origin
        return projected

    def snapshot(self) -> dict[str, Any]:
        values = self.effective()
        projected = self.portable_config(values)
        projected["BB_EXTRA_PATH"] = values["BB_EXTRA_PATH"]
        return {
            "path": str(self.path),
            "values": projected,
            "unknown_keys": sorted(set(self.read()) - set(MACHINE_CONFIG_KEYS)),
        }

    @staticmethod
    def validate(values: dict[str, str]) -> None:
        mode = values.get("BB_PROXY_MODE", "")
        if mode not in {"direct", "mihomo"}:
            raise ValidationError("BB_PROXY_MODE must be direct or mihomo")
        ConfigurationManager._validate_url(
            "BB_HTTP_PROXY", values.get("BB_HTTP_PROXY", ""), {"http", "https"}
        )
        ConfigurationManager._validate_url(
            "BB_SOCKS_PROXY",
            values.get("BB_SOCKS_PROXY", ""),
            {"socks5", "socks5h"},
        )
        delivery = values.get("BB_FILECODEBOX_URL", "")
        if delivery:
            parsed = urlparse(delivery)
            origin = url_origin(delivery, {"http", "https"})
            if (
                origin is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValidationError(
                    "BB_FILECODEBOX_URL must be an HTTP(S) origin without credentials, path, query, or fragment"
                )
        username = values.get("BB_H1_USERNAME", "")
        if any(character.isspace() or ord(character) < 32 for character in username):
            raise ValidationError(
                "BB_H1_USERNAME must not contain whitespace or control characters"
            )
        if len(username) > 100:
            raise ValidationError("BB_H1_USERNAME is too long")
        if values.get("BB_AGENT_LANGUAGE") not in {"zh-CN", "en"}:
            raise ValidationError("BB_AGENT_LANGUAGE must be zh-CN or en")
        npm_registry = values.get("BB_NPM_REGISTRY", "")
        if npm_registry not in {"auto", "npmjs", "npmmirror"}:
            ConfigurationManager._validate_url(
                "BB_NPM_REGISTRY", npm_registry, {"https"}
            )
        pypi_index = values.get("BB_PYPI_INDEX", "")
        if not pypi_index or url_origin(pypi_index, {"http", "https"}) is None:
            raise ValidationError("BB_PYPI_INDEX must be an HTTP(S) URL")
        parsed_index = urlparse(pypi_index)
        if (
            parsed_index.username is not None
            or parsed_index.password is not None
            or parsed_index.query
            or parsed_index.fragment
        ):
            raise ValidationError(
                "BB_PYPI_INDEX must not contain credentials, query, or fragment"
            )
        extra_path = values.get("BB_EXTRA_PATH", "")
        for item in extra_path.split(os.pathsep):
            if item and not Path(item).expanduser().is_absolute():
                raise ValidationError("BB_EXTRA_PATH entries must be absolute paths")

    @staticmethod
    def _validate_url(name: str, value: str, schemes: set[str]) -> None:
        if not value:
            raise ValidationError(f"{name} must not be empty")
        try:
            parsed = urlparse(value)
        except ValueError as error:
            raise ValidationError(f"{name} is invalid") from error
        if url_origin(value, schemes) is None:
            raise ValidationError(
                f"{name} must use one of: {', '.join(sorted(schemes))}"
            )
        if parsed.username is not None or parsed.password is not None:
            raise ValidationError(f"{name} must not contain credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValidationError(
                f"{name} must be an endpoint origin without path, query, or fragment"
            )

    def interactive_updates(self) -> dict[str, str]:
        if not sys.stdin.isatty():
            raise StackError("configure requires options when stdin is not interactive")
        current = self.effective()

        def ask(label: str, key: str) -> str:
            value = input(f"{label} [{current[key]}]: ").strip()
            return value if value else current[key]

        return {
            "BB_PROXY_MODE": ask("Proxy mode (direct/mihomo)", "BB_PROXY_MODE"),
            "BB_HTTP_PROXY": ask("HTTP proxy origin", "BB_HTTP_PROXY"),
            "BB_SOCKS_PROXY": ask("SOCKS proxy origin", "BB_SOCKS_PROXY"),
            "BB_H1_USERNAME": ask("HackerOne username", "BB_H1_USERNAME"),
            "BB_FILECODEBOX_URL": ask("FileCodeBox origin", "BB_FILECODEBOX_URL"),
            "BB_AGENT_LANGUAGE": ask("Agent language (zh-CN/en)", "BB_AGENT_LANGUAGE"),
            "BB_NPM_REGISTRY": ask(
                "npm registry (auto/npmjs/npmmirror/HTTPS URL)",
                "BB_NPM_REGISTRY",
            ),
            "BB_PYPI_INDEX": ask(
                "Python package index URL", "BB_PYPI_INDEX"
            ),
            "BB_EXTRA_PATH": ask("Extra PATH entries", "BB_EXTRA_PATH"),
        }
