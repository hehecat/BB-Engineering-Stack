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
python3 - "$SOURCE" "$ROOT" <<'PY'
from pathlib import Path
import os
import shutil
import subprocess
import sys

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
tracked = subprocess.run(
    ["git", "-C", str(source), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    stdout=subprocess.PIPE,
    check=False,
).stdout.split(b"\0")
if tracked and tracked[0]:
    relatives = [Path(value.decode()) for value in tracked if value]
else:
    relatives = [
        path.relative_to(source)
        for path in source.rglob("*")
        if ".git" not in path.parts and ".runtime" not in path.parts
    ]
for relative in relatives:
    origin = source / relative
    target = destination / relative
    if origin.is_symlink():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(os.readlink(origin), target_is_directory=origin.is_dir())
    elif origin.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    elif origin.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
PY

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
cat > "$ROOT/.runtime/bin/claude" <<'SH'
#!/usr/bin/env sh
printf '%s\n' 'claude-test-fixture 0.0.0'
SH
chmod 0755 "$ROOT/.runtime/bin/claude"
bb-stack validate --json >/dev/null
bb-stack eval contracts --json >/dev/null
bb-stack doctor --profile minimal --strict --json >/dev/null
STATUS_REPORT="$(bb-stack status --profile minimal --json)"
if ! printf '%s' "$STATUS_REPORT" | python3 -c \
  'import json, sys; raise SystemExit(not json.load(sys.stdin)["ready"])'; then
  printf '%s\n' 'fresh-machine status is not ready:' "$STATUS_REPORT" >&2
  exit 1
fi
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
