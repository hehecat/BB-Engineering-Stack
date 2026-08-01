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
if git -C "$SOURCE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  (
    cd "$SOURCE"
    git ls-files --cached --others --exclude-standard -z |
      rsync -a --from0 --files-from=- ./ "$ROOT/"
  )
else
  rsync -a --exclude='.git' --exclude='.runtime' "$SOURCE/" "$ROOT/"
fi

export HOME="$HOME_TEST"
export BB_STACK_ROOT="$ROOT"
export BB_CONFIG_HOME="$HOME_TEST/config"
export CLAUDE_CONFIG_DIR="$HOME_TEST/.claude"

"$ROOT/00-L0-Runtime/bin/bootstrap" --profile minimal --skip-tools \
  --work-root "$HOME_TEST/chosen-workspace" --json >/dev/null
source "$BB_CONFIG_HOME/env.sh"
[[ "$BB_WORK_ROOT" == "$HOME_TEST/chosen-workspace" ]]
[[ -f "$BB_WORK_ROOT/CLAUDE.md" ]]
[[ -f "$BB_WORK_ROOT/.mcp.json" ]]
[[ -f "$BB_WORK_ROOT/.claude/settings.json" ]]
[[ -d "$BB_WORK_ROOT/engagements" ]]
bb-stack validate --json >/dev/null
bb-stack eval contracts --json >/dev/null
bb-stack doctor --profile minimal --strict --json >/dev/null
bb-stack status --profile minimal --strict --json >/dev/null
(
  cd "$ROOT/.runtime"
  node --input-type=module -e \
    "import {webcrack} from 'webcrack'; const r=await webcrack('var x=[\"ok\"];console.log(x[0]);'); if (!r.code.includes('console.log')) process.exit(1)"
)
command -v mail-otp >/dev/null
bb-stack mail --help >/dev/null
bb-stack configure --h1-username fresh-operator --json >/dev/null
bb-stack portable export "$SANDBOX/portable.json" --json >/dev/null
bb-stack portable inspect "$SANDBOX/portable.json" --json >/dev/null
bb-stack portable import "$SANDBOX/portable.json" --json >/dev/null
bb-stack new fresh-lab ./fixture --workflow lab --platform local-lab --json >/dev/null
bb-claude --profile lab-replacement --engagement fresh-lab --dry-run -- --print smoke >"$SANDBOX/launch.json"
python3 - "$SANDBOX/launch.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d['prompt_mode']=='replacement'
assert d['cwd'].endswith('/fresh-lab')
PY
printf '%s\n' 'BB_FRESH_MACHINE_OK'
