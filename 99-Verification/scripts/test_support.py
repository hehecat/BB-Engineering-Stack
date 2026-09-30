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


def isolated_stack_source(
    source: Path, destination: Path, manifest: str | None = None
) -> Path:
    """Symlink a stack source tree into `destination`.

    `manifest` replaces the linked `stack.yaml`, so a test can declare its own
    manifest defaults without touching the real source tree.
    """
    destination.mkdir(parents=True)
    for name in SOURCE_ENTRIES:
        target = source / name
        if name == "stack.yaml" and manifest is not None:
            (destination / name).write_text(manifest, encoding="utf-8")
            continue
        (destination / name).symlink_to(target, target_is_directory=target.is_dir())
    return destination
