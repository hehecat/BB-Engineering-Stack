from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema

from .errors import ValidationError
from .io import load_json


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
    raise ValidationError(prefix + " failed schema validation:\n  " + "\n  ".join(lines))


def require_file(path: Path, label: str | None = None) -> None:
    if not path.is_file():
        raise ValidationError(f"missing {label or 'file'}: {path}")


def require_directory(path: Path, label: str | None = None) -> None:
    if not path.is_dir():
        raise ValidationError(f"missing {label or 'directory'}: {path}")
