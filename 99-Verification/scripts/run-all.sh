#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PYTHON="$ROOT/.runtime/venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=python3
export BB_STACK_ROOT="$ROOT"
export PYTHONPATH="$ROOT/00-L0-Runtime/lib${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" -m py_compile "$ROOT"/00-L0-Runtime/lib/bb_stack/*.py
"$PYTHON" "$ROOT/99-Verification/scripts/test_contracts.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_lifecycle.py"
"$ROOT/00-L0-Runtime/bin/bb-stack" validate --json >/dev/null

if [[ -x "$ROOT/.runtime/venv/bin/python" && -d "$ROOT/.runtime/node_modules" ]]; then
  "$ROOT/00-L0-Runtime/bin/bb-stack" doctor --profile ctf-web --strict --probe-mcp --json >/dev/null
  "$ROOT/00-L0-Runtime/bin/bb-stack" doctor --profile web --strict --json >/dev/null
fi

printf '%s\n' 'BB_STACK_VERIFICATION_OK'
