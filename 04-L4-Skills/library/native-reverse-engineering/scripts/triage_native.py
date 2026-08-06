#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60
VERSION_ARGUMENTS = {
    "file": ["--version"],
    "readelf": ["--version"],
    "objdump": ["--version"],
    "nm": ["--version"],
    "strings": ["--version"],
    "rabin2": ["-v"],
    "checksec": ["--version"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_environment() -> dict[str, str]:
    """Pin the C locale so binutils output field names stay stable."""
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def trim_output(path: Path) -> bool:
    size = path.stat().st_size
    if size <= MAX_OUTPUT_BYTES:
        return False
    with path.open("r+b") as handle:
        handle.truncate(MAX_OUTPUT_BYTES)
    return True


def tool_identity(command: str) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        return {"present": False, "path": None, "version": None}
    version = None
    try:
        completed = subprocess.run(
            [executable, *VERSION_ARGUMENTS[command]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
            check=False,
            env=stable_environment(),
        )
        version = completed.stdout.splitlines()[0][:512] if completed.stdout else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"present": True, "path": executable, "version": version}


def run_probe(
    output_root: Path,
    name: str,
    command: list[str],
    *,
    timeout: int,
) -> dict[str, Any]:
    executable = shutil.which(command[0])
    result: dict[str, Any] = {
        "available": executable is not None,
        "command": command,
        "exit_code": None,
        "output": None,
        "stderr": None,
        "timed_out": False,
        "truncated": False,
    }
    if executable is None:
        return result

    output_path = output_root / f"{name}.txt"
    result["output"] = output_path.name
    try:
        with output_path.open("wb") as stdout:
            completed = subprocess.run(
                [executable, *command[1:]],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                env=stable_environment(),
            )
        result["exit_code"] = completed.returncode
        if completed.stderr:
            result["stderr"] = completed.stderr.decode("utf-8", errors="replace")[:4096]
    except subprocess.TimeoutExpired as error:
        result["timed_out"] = True
        if error.stderr:
            result["stderr"] = error.stderr.decode("utf-8", errors="replace")[:4096]
    result["truncated"] = trim_output(output_path)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory a native artifact without executing it."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-probe timeout in seconds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.input.expanduser().resolve(strict=True)
    if not source.is_file():
        raise SystemExit(f"input is not a regular file: {source}")
    if args.timeout < 1 or args.timeout > 300:
        raise SystemExit("timeout must be between 1 and 300 seconds")

    output_root = args.output.expanduser().resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    before = sha256(source)
    probes = {
        "file": ["file", "-b", "--", str(source)],
        "readelf-header": ["readelf", "-hW", str(source)],
        "readelf-program-headers": ["readelf", "-lW", str(source)],
        "readelf-sections": ["readelf", "-SW", str(source)],
        "readelf-dynamic": ["readelf", "-dW", str(source)],
        "readelf-symbols": ["readelf", "-sW", str(source)],
        "readelf-relocations": ["readelf", "-rW", str(source)],
        "readelf-notes": ["readelf", "-nW", str(source)],
        "objdump-metadata": ["objdump", "-f", "-p", str(source)],
        "nm-symbols": ["nm", "-an", str(source)],
        "strings": ["strings", "-a", "-n", "6", str(source)],
        "rabin2-info": ["rabin2", "-I", str(source)],
        "rabin2-imports": ["rabin2", "-i", str(source)],
        "rabin2-exports": ["rabin2", "-E", str(source)],
        "rabin2-sections": ["rabin2", "-S", str(source)],
        "checksec": ["checksec", f"--file={source}"],
    }
    results = {
        name: run_probe(
            output_root,
            name,
            command,
            timeout=args.timeout,
        )
        for name, command in probes.items()
    }
    after = sha256(source)
    summary = {
        "schema_version": 1,
        "input": {
            "path": str(source),
            "size": source.stat().st_size,
            "sha256": before,
            "unchanged": before == after,
        },
        "limits": {
            "per_probe_timeout_seconds": args.timeout,
            "max_output_bytes": MAX_OUTPUT_BYTES,
        },
        "tools": {command: tool_identity(command) for command in VERSION_ARGUMENTS},
        "probes": results,
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    if before != after:
        raise SystemExit("input changed during triage")
    print(summary_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as error:
        print(f"triage failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
