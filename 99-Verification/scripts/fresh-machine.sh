#!/usr/bin/env bash
set -euo pipefail

SOURCE="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SANDBOX="$(mktemp -d /tmp/bb-fresh-machine.XXXXXX)"
cleanup() {
  python3 - "$SANDBOX" <<'PY'
import pathlib, shutil, sys
p=pathlib.Path(sys.argv[1]).resolve()
if p.parent == pathlib.Path('/tmp') and p.name.startswith('bb-fresh-machine.'):
    shutil.rmtree(p, ignore_errors=True)
PY
}
trap cleanup EXIT
ROOT="$SANDBOX/BB-Engineering-Stack"
HOME_TEST="$SANDBOX/home"
mkdir -p "$ROOT" "$HOME_TEST"
rsync -a --exclude='.git' --exclude='.runtime' "$SOURCE/" "$ROOT/"

export HOME="$HOME_TEST"
export BB_STACK_ROOT="$ROOT"
export BB_WORK_ROOT="$HOME_TEST/work"
export BB_CONFIG_HOME="$HOME_TEST/config"
export CLAUDE_CONFIG_DIR="$HOME_TEST/.claude"

"$ROOT/00-L0-Runtime/bin/bootstrap" --profile minimal --skip-tools --json >/dev/null
source "$BB_CONFIG_HOME/env.sh"
bb-stack validate --json >/dev/null
bb-stack doctor --profile minimal --strict --json >/dev/null
bb-stack new fresh-lab ./fixture --workflow lab --platform local-lab --json >/dev/null
bb-claude --profile lab-replacement --engagement fresh-lab --dry-run -- --print smoke >"$SANDBOX/launch.json"
python3 - "$SANDBOX/launch.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d['prompt_mode']=='replacement'
assert d['cwd'].endswith('/fresh-lab')
PY
printf '%s\n' 'BB_FRESH_MACHINE_OK'
