from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

import yaml

from .errors import ValidationError


_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    value: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in value
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_yaml_text(content: str, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(content, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as error:
        raise ValidationError(f"failed to read YAML {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"expected a YAML mapping in {label}")
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValidationError(f"failed to read YAML {path}: {error}") from error
    return load_yaml_text(content, str(path))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"failed to read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"expected a JSON object in {path}")
    return value


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def dump_yaml(path: Path, value: Mapping[str, Any], mode: int | None = None) -> None:
    content = yaml.safe_dump(
        dict(value), sort_keys=False, allow_unicode=False, default_flow_style=False
    )
    atomic_write(path, content, mode)


def dump_json(path: Path, value: Mapping[str, Any], mode: int | None = None) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=True) + "\n", mode)


def expand(value: Any, env: Mapping[str, str], *, strict: bool = True) -> Any:
    if isinstance(value, str):
        missing = sorted(set(_ENV_RE.findall(value)) - set(env))
        if strict and missing:
            raise ValidationError("undefined environment variable(s): " + ", ".join(missing))
        result = _ENV_RE.sub(lambda match: env.get(match.group(1), match.group(0)), value)
        return os.path.expanduser(result)
    if isinstance(value, list):
        return [expand(item, env, strict=strict) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, env, strict=strict) for key, item in value.items()}
    return value


def read_fragments(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ValidationError(f"failed to read prompt fragment {path}: {error}") from error
        if not content:
            raise ValidationError(f"empty prompt fragment: {path}")
        parts.append(content)
    return "\n\n".join(parts) + "\n"
