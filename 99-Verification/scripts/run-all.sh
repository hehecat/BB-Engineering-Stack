#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
PYTHON="$ROOT/.runtime/venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=python3
export BB_STACK_ROOT="$ROOT"
export PYTHONPATH="$ROOT/00-L0-Runtime/lib${PYTHONPATH:+:$PYTHONPATH}"
STACK="$ROOT/00-L0-Runtime/bin/bb-stack"

doctor_if_installed() {
  local profile="$1"
  local report
  shift

  report="$("$STACK" doctor --profile "$profile" --json)"
  if printf '%s' "$report" | "$PYTHON" -c \
    'import json, sys; raise SystemExit(not json.load(sys.stdin)["skills"]["ready"])'; then
    "$STACK" doctor --profile "$profile" --strict "$@" --json >/dev/null
  else
    printf 'SKIP profile doctor (skills not installed): %s\n' "$profile"
  fi
}

"$PYTHON" -m py_compile "$ROOT"/00-L0-Runtime/lib/bb_stack/*.py
"$PYTHON" "$ROOT/99-Verification/scripts/test_contracts.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_cli.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_lifecycle.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_mail_otp.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_status.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_configuration.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_portable.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_evaluation.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_runtime_installers.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_data.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_updates.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_keysmith.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_android_reverse_skill.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_browser_runtime.py"
"$PYTHON" "$ROOT/99-Verification/scripts/test_workspace.py"
"$STACK" validate --json >/dev/null

if [[ -x "$ROOT/.runtime/venv/bin/python" && -d "$ROOT/.runtime/node_modules" ]]; then
  (
    cd "$ROOT/.runtime"
    node --input-type=module -e \
      "import {webcrack} from 'webcrack'; const r=await webcrack('var x=[\"ok\"];console.log(x[0]);'); if (!r.code.includes('console.log')) process.exit(1)"
  )
  doctor_if_installed ctf-web --probe-mcp
  doctor_if_installed web
  if command -v chromium >/dev/null 2>&1; then
    doctor_if_installed browser-js --probe-mcp
  fi
  if [[ -x "$ROOT/.runtime/bin/jadx" ]] && command -v r2 >/dev/null 2>&1; then
    doctor_if_installed android
    doctor_if_installed reverse
  fi
fi

printf '%s\n' 'BB_STACK_VERIFICATION_OK'
