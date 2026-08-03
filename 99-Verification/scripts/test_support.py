from __future__ import annotations

from pathlib import Path

SOURCE_ENTRIES = (
    "00-L0-Runtime",
    "01-L1-Global-Prompt",
    "02-L2-Workflow-Profiles",
    "03-L3-Engagement-State",
    "04-L4-Skills",
    "05-L5-MCP-CLI",
    "schema",
    "pyproject.toml",
    "stack.yaml",
)


def isolated_stack_source(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    for name in SOURCE_ENTRIES:
        target = source / name
        (destination / name).symlink_to(target, target_is_directory=target.is_dir())
    return destination
