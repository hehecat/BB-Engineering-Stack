from __future__ import annotations

import platform
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema

from .errors import ValidationError
from .io import load_json

_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")

# Tool -> (executable, version arguments, remediation). Python is not probed
# because the interpreter running the stack is the one that matters.
_RUNTIME_TOOLS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "node": (
        "node",
        ("--version",),
        "install Node.js at or above the required version or run `bb-stack bootstrap`",
    ),
    "claude_code": (
        "claude",
        ("--version",),
        "install Claude Code at or above the required version and put `claude` on PATH",
    ),
}
_RUNTIME_PROBE_TIMEOUT = 15


def validate(instance: Any, schema_path: Path, label: str | None = None) -> None:
    schema = load_json(schema_path)
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    lines = []
    for error in errors[:20]:
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        lines.append(f"{location}: {error.message}")
    if len(errors) > 20:
        lines.append(f"... {len(errors) - 20} more validation errors")
    prefix = label or str(schema_path)
    raise ValidationError(
        prefix + " failed schema validation:\n  " + "\n  ".join(lines)
    )


def version_tuple(value: str | None) -> tuple[int, ...]:
    """Leading numeric components of a version string; empty when unparsable."""
    if not value:
        return ()
    match = _VERSION_RE.search(value)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def runtime_versions(path: str | None = None) -> dict[str, str | None]:
    """Detected versions of the tools `minimum_runtime` constrains.

    `None` means the tool is absent from `path` or did not report a version;
    that is reported rather than raised because installing toolchains belongs
    to `bb-stack bootstrap`, not to source-tree validation.
    """
    detected: dict[str, str | None] = {"python": platform.python_version()}
    for tool, (executable, arguments, _) in _RUNTIME_TOOLS.items():
        binary = shutil.which(executable, path=path)
        if binary is None:
            detected[tool] = None
            continue
        try:
            completed = subprocess.run(
                [binary, *arguments],
                capture_output=True,
                text=True,
                timeout=_RUNTIME_PROBE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            detected[tool] = None
            continue
        detected[tool] = completed.stdout.strip() or completed.stderr.strip() or None
    return detected


def _remedy(tool: str, required: str) -> str:
    probe = _RUNTIME_TOOLS.get(tool)
    if probe is not None:
        return probe[2]
    return f"run the stack with {tool} {required} or newer"


def check_minimum_runtime(
    minimum: Mapping[str, Any], detected: Mapping[str, str | None]
) -> dict[str, Any]:
    """Compare detected tool versions against the declared minimum.

    `satisfied` is False only when a detected tool is older than required. A
    missing or unparsable tool is reported as a check with remediation text so
    an operator can act, but it does not fail validation of the source tree.
    """
    checks: list[dict[str, Any]] = []
    for tool, required in minimum.items():
        if not isinstance(required, str) or not required:
            continue
        found = detected.get(tool)
        if found is None:
            status = "missing"
        elif not version_tuple(found):
            status = "unknown"
        elif version_tuple(found) >= version_tuple(required):
            status = "ok"
        else:
            status = "below-minimum"
        checks.append(
            {
                "tool": tool,
                "required": required,
                "detected": found,
                "status": status,
                "remedy": _remedy(tool, required),
            }
        )
    return {
        "required": dict(minimum),
        "detected": dict(detected),
        "checks": checks,
        "satisfied": all(check["status"] != "below-minimum" for check in checks),
    }
