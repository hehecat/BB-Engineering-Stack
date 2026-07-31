#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
WORK="$(mktemp -d /tmp/bb-claude-smoke.XXXXXX)"
cleanup() {
  python3 - "$WORK" <<'PY'
import pathlib, shutil, sys
p=pathlib.Path(sys.argv[1]).resolve()
if p.parent == pathlib.Path('/tmp') and p.name.startswith('bb-claude-smoke.'):
    shutil.rmtree(p, ignore_errors=True)
PY
}
trap cleanup EXIT
export BB_STACK_ROOT="$ROOT"
export BB_WORK_ROOT="$WORK"

"$ROOT/00-L0-Runtime/bin/bb-stack" new claude-smoke ./fixture \
  --workflow ctf --platform standalone-ctf --json >/dev/null
OUTPUT="$WORK/output.txt"
"$ROOT/00-L0-Runtime/bin/bb-claude" --profile ctf-quick --engagement claude-smoke -- \
  --print --output-format text --no-session-persistence \
  'Read engagement.yaml and respond with exactly BB_CLAUDE_SMOKE_OK.' >"$OUTPUT"
grep -qx 'BB_CLAUDE_SMOKE_OK' "$OUTPUT"
printf '%s\n' 'BB_CLAUDE_SMOKE_OK'
