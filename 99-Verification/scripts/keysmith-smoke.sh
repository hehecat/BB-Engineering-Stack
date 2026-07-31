#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
HOME_TEST="$(mktemp -d /tmp/bb-keysmith-smoke.XXXXXX)"
cleanup() {
  python3 - "$HOME_TEST" <<'PY'
import pathlib, shutil, sys
p=pathlib.Path(sys.argv[1]).resolve()
if p.parent == pathlib.Path('/tmp') and p.name.startswith('bb-keysmith-smoke.'):
    shutil.rmtree(p, ignore_errors=True)
PY
}
trap cleanup EXIT
export HOME="$HOME_TEST"
export BB_STACK_ROOT="$ROOT"
export BB_WORK_ROOT="$HOME_TEST/work"
export BB_CONFIG_HOME="$HOME_TEST/config"
export CLAUDE_CONFIG_DIR="$HOME_TEST/.claude"

if [[ -z "${BB_KEYSMITH_SOURCE:-}" ]]; then
  if [[ -f /tmp/claude-keysmith/claude-instruct.py ]]; then
    export BB_KEYSMITH_SOURCE=/tmp/claude-keysmith
  else
    printf '%s\n' 'keysmith-smoke: set BB_KEYSMITH_SOURCE to a checked-out pinned source' >&2
    exit 2
  fi
fi

"$ROOT/00-L0-Runtime/bin/bb-stack" keysmith install --profile ctf-replacement --yes --json >/dev/null
"$ROOT/00-L0-Runtime/bin/bb-stack" keysmith status --json >"$HOME_TEST/status.json"
python3 - "$HOME_TEST/status.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d['deployed'] and d['managed_prompt_matches']
assert d['doctor']['shell_wrapper_managed']
assert d['doctor']['system_prompt_exists'] and d['doctor']['append_prompt_exists']
PY
"$ROOT/00-L0-Runtime/bin/bb-stack" keysmith uninstall --yes --json >/dev/null
printf '%s\n' 'BB_KEYSMITH_SMOKE_OK'
