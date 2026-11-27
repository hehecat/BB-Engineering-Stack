#!/usr/bin/env python3
"""Lightweight, injection-safe radare2 JSON query helper with optional disk cache.

Gives agents fast function tables, per-symbol disassembly/pseudo-C, and xrefs
without MCP schema overhead or raw r2 flag guesswork.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_SAFE_TARGET = re.compile(r"^[A-Za-z0-9_.:+-]{1,128}$")


def _validate_target(target: str) -> str:
    value = target.strip()
    if not _SAFE_TARGET.match(value):
        raise SystemExit(
            f"invalid target {target!r}; expected symbol or hex address matching "
            f"{_SAFE_TARGET.pattern}"
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_r2(binary: Path, script: str, timeout: int) -> str:
    r2 = shutil.which("r2")
    if not r2:
        raise SystemExit("r2 (radare2) is not on PATH; install with: bb-stack tool install radare2")
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    completed = subprocess.run(
        [r2, "-2", "-q", "-c", script, "--", str(binary)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise SystemExit(f"r2 query failed: {detail}")
    return completed.stdout.strip()


def _cached_json(cache_dir: Path | None, key: str, loader: Any) -> Any:
    if cache_dir is None:
        return loader()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    value = loader()
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return value


def _parse_json_line(raw: str) -> Any:
    for line in reversed(raw.splitlines()):
        stripped = line.strip()
        if stripped.startswith(("[", "{")):
            return json.loads(stripped)
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query radare2 deterministically in JSON without executing the binary."
    )
    parser.add_argument("--input", required=True, type=Path, help="Binary file to inspect")
    parser.add_argument("--cache-dir", type=Path, help="Optional directory to cache r2 JSON results")
    parser.add_argument("--timeout", type=int, default=120, help="r2 timeout in seconds")
    sub = parser.add_subparsers(dest="action", required=True)

    funcs = sub.add_parser("functions", help="List analyzed functions sorted by size")
    funcs.add_argument("--filter", default="", help="Case-insensitive substring filter on function name")
    funcs.add_argument("--limit", type=int, default=100, help="Maximum functions returned")

    disasm = sub.add_parser("disasm", help="Disassemble one function or address")
    disasm.add_argument("--target", required=True, help="Function name or hex address (e.g. main or 0x401000)")
    disasm.add_argument("--pseudo", action="store_true", help="Include r2 pdc pseudo-decompilation")

    xrefs = sub.add_parser("xrefs", help="List cross-references to an address or symbol")
    xrefs.add_argument("--target", required=True, help="Symbol or hex address")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    binary = args.input.expanduser().resolve(strict=True)
    if not binary.is_file():
        raise SystemExit(f"input is not a regular file: {binary}")
    if args.timeout < 1 or args.timeout > 600:
        raise SystemExit("timeout must be between 1 and 600 seconds")
    digest = _sha256(binary)[:16]

    if args.action == "functions":
        raw_items = _cached_json(
            args.cache_dir,
            f"{digest}-functions",
            lambda: _parse_json_line(_run_r2(binary, "aa; aflj", args.timeout)),
        )
        needle = args.filter.lower()
        items = [
            {
                "name": item.get("name"),
                "address": hex(int(item.get("offset", 0))),
                "size": int(item.get("size", 0)),
                "blocks": int(item.get("nbbs", 0)),
                "callrefs": len(item.get("callrefs") or []),
            }
            for item in (raw_items or [])
            if not needle or needle in str(item.get("name", "")).lower()
        ]
        items.sort(key=lambda row: (-row["size"], row["address"]))
        payload: dict[str, Any] = {
            "binary": str(binary),
            "total_matched": len(items),
            "functions": items[: max(1, args.limit)],
        }
    elif args.action == "disasm":
        target = _validate_target(args.target)
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", target)
        ops = _cached_json(
            args.cache_dir,
            f"{digest}-pdfj-{safe_key}",
            lambda: _parse_json_line(_run_r2(binary, f"aa; s {target}; pdfj", args.timeout)),
        )
        payload = {"binary": str(binary), "target": target, "function": ops}
        if args.pseudo:
            payload["pseudo"] = _run_r2(binary, f"aa; s {target}; pdc", args.timeout)
    else:
        target = _validate_target(args.target)
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", target)
        refs = _cached_json(
            args.cache_dir,
            f"{digest}-axtj-{safe_key}",
            lambda: _parse_json_line(_run_r2(binary, f"aa; axtj @ {target}", args.timeout)),
        )
        payload = {"binary": str(binary), "target": target, "xrefs": refs}

    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
