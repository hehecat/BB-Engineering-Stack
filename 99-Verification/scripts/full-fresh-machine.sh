#!/usr/bin/env bash
set -euo pipefail

SOURCE="$(unset CDPATH; cd -- "$(dirname -- "$0")/../.." && pwd)"
SANDBOX="$(mktemp -d /tmp/bb-full-fresh.XXXXXX)"
KEEP="${BB_FULL_FRESH_KEEP:-0}"
PROFILE_TIMEOUT="${BB_FULL_FRESH_PROFILE_TIMEOUT:-1200}"
PROXY_MODE="${BB_FULL_FRESH_PROXY_MODE:-direct}"
HTTP_PROXY_URL="${BB_FULL_FRESH_HTTP_PROXY:-http://127.0.0.1:7890}"
SOCKS_PROXY_URL="${BB_FULL_FRESH_SOCKS_PROXY:-socks5://127.0.0.1:7891}"

case "$PROXY_MODE" in
  direct|mihomo) ;;
  *)
    printf 'full-fresh: unsupported proxy mode: %s\n' "$PROXY_MODE" >&2
    exit 2
    ;;
esac

cleanup() {
  if [[ "$KEEP" == "1" ]]; then
    printf 'full-fresh artifacts: %s\n' "$SANDBOX" >&2
    return
  fi
  python3 - "$SANDBOX" <<'PY'
import pathlib, shutil, sys
p = pathlib.Path(sys.argv[1]).resolve()
if p.parent == pathlib.Path('/tmp') and p.name.startswith('bb-full-fresh.'):
    shutil.rmtree(p, ignore_errors=True)
PY
}
trap cleanup EXIT

ROOT="$SANDBOX/BB-Engineering-Stack"
HOME_TEST="$SANDBOX/home"
REPORT="$SANDBOX/report"
mkdir -p "$ROOT" "$HOME_TEST" "$REPORT"

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
export BB_CONFIG_HOME="$HOME_TEST/.config/bb-stack"
export CLAUDE_CONFIG_DIR="$HOME_TEST/.claude"
export PATH="/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset BB_WORK_ROOT BB_EXTRA_PATH HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy

PROFILES=(
  minimal
  ctf-web
  web
  android
  reverse
  browser-js
  assessment-web
  assessment-android
  assessment-ios
  assessment-network
  assessment-cloud
  assessment-llm
  assessment-source
  analysis-android
  analysis-reverse
)

for profile in "${PROFILES[@]}"; do
  printf 'FULL_FRESH bootstrap=%s\n' "$profile"
  timeout "$PROFILE_TIMEOUT" "$ROOT/00-L0-Runtime/bin/bootstrap" --profile "$profile" \
    --work-root "$HOME_TEST/BB-Workspaces" --agent-language zh-CN \
    --json >"$REPORT/bootstrap-$profile.json"
  # shellcheck source=/dev/null
  source "$BB_CONFIG_HOME/env.sh"
  if [[ "$profile" == "minimal" ]]; then
    cat > "$ROOT/.runtime/bin/claude" <<'SH'
#!/usr/bin/env sh
printf '%s\n' 'claude-test-fixture 0.0.0'
SH
    chmod 0755 "$ROOT/.runtime/bin/claude"
  fi
  if [[ "$profile" == "minimal" && "$PROXY_MODE" == "mihomo" ]]; then
    bb-stack configure --proxy-mode mihomo \
      --http-proxy "$HTTP_PROXY_URL" --socks-proxy "$SOCKS_PROXY_URL" \
      --json >"$REPORT/proxy-configure.json"
    # shellcheck source=/dev/null
    source "$BB_CONFIG_HOME/env.sh"
  fi
  bb-stack doctor --profile "$profile" --strict --json \
    >"$REPORT/doctor-$profile.json"
  bb-stack status --profile "$profile" --strict --json \
    >"$REPORT/status-$profile.json"
done

bb-stack validate --json >"$REPORT/validate.json"
bb-stack eval contracts --json >"$REPORT/contracts.json"
bb-stack workspace status --json >"$REPORT/workspace.json"

python3 - "$REPORT" <<'PY'
import json
from pathlib import Path
import sys

report = Path(sys.argv[1])
for path in sorted(report.glob('doctor-*.json')):
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['ready'], path
for path in sorted(report.glob('status-*.json')):
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['ready'], path
workspace = json.loads((report / 'workspace.json').read_text(encoding='utf-8'))
assert workspace['ready']
assert workspace['mcp_servers'] == []
contracts = json.loads((report / 'contracts.json').read_text(encoding='utf-8'))
assert contracts['passed']
assert contracts['profile_count'] == 17
PY

ROUTES=(
  'ctf-web|https://challenge.example|standalone-ctf|interactive|ctf-quick'
  'web|https://target.example|generic-vdp|interactive|bb-interactive'
  'web|https://h1.example|hackerone|continuous|bb-continuous'
  'web-assessment|https://assessment.example|authorized-assessment|interactive|assessment-web'
  'ctf-android|inbox/challenge.apk|standalone-ctf|interactive|ctf-android'
  'android-assessment|inbox/product.apk|authorized-assessment|interactive|assessment-android'
  'android-analysis|inbox/library.apk|standalone-analysis|interactive|analysis-android'
  'ios-assessment|inbox/product.ipa|authorized-assessment|interactive|assessment-ios'
  'ctf-reverse|inbox/challenge.bin|standalone-ctf|interactive|ctf-reverse'
  'reverse-analysis|inbox/firmware.bin|standalone-analysis|interactive|analysis-reverse'
  'network-assessment|10.20.0.0/24|authorized-assessment|interactive|assessment-network'
  'cloud-assessment|aws-account-fixture|authorized-assessment|interactive|assessment-cloud'
  'llm-assessment|rag-agent-fixture|authorized-assessment|interactive|assessment-llm'
  'source-audit|inbox/repository|authorized-assessment|interactive|assessment-source'
  'browser-js|https://app.example|standalone-analysis|interactive|browser-js'
  'lab|inbox/fixture|local-lab|interactive|lab-replacement'
)

route_index=0
for spec in "${ROUTES[@]}"; do
  IFS='|' read -r kind target platform mode expected_profile <<<"$spec"
  route_index=$((route_index + 1))
  slug="full-fresh-$route_index"
  authorization=()
  case "$platform" in
    generic-vdp|hackerone|authorized-assessment)
      authorization=(
        --authorization-status verified
        --authorization-source "Full fresh-machine fixture authorization"
      )
      ;;
  esac
  bb-stack workspace route --kind "$kind" --target "$target" --slug "$slug" \
    --platform "$platform" --mode "$mode" "${authorization[@]}" --json \
    >"$REPORT/route-$route_index.json"
  python3 - "$REPORT/route-$route_index.json" "$expected_profile" "$platform" "$mode" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
assert d['profile'] == sys.argv[2], d
assert d['platform'] == sys.argv[3], d
assert d['mode'] == sys.argv[4], d
assert not d['repair_commands'], d
assert all(__import__('pathlib').Path(p).is_file() for p in d['state_files'])
PY
done

bb-stack configure --h1-username fresh-operator \
  --filecodebox-url https://filebox.example --json >"$REPORT/configure.json"
# shellcheck source=/dev/null
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile web --platform hackerone --strict --json \
  >"$REPORT/hackerone-status.json"

(
  cd "$ROOT/.runtime"
  node --input-type=module -e \
    "import {webcrack} from 'webcrack'; const r=await webcrack('var x=[\"ok\"];console.log(x[0]);'); if (!r.code.includes('console.log')) process.exit(1)"
)

bb-stack browser start --engagement full-fresh-15 --json \
  >"$REPORT/browser-start.json"
bb-stack browser status --json >"$REPORT/browser-status.json"
bb-stack browser stop --json >"$REPORT/browser-stop.json"

python3 - "$REPORT" <<'PY'
import json
from pathlib import Path
import sys

report = Path(sys.argv[1])
h1 = json.loads((report / 'hackerone-status.json').read_text(encoding='utf-8'))
assert h1['ready']
assert h1['personal']['hackerone']['username'] == 'fresh-operator'
browser = json.loads((report / 'browser-status.json').read_text(encoding='utf-8'))
assert browser['ready'] and browser['state'] == 'ready'
stopped = json.loads((report / 'browser-stop.json').read_text(encoding='utf-8'))
assert not stopped['ready'] and stopped['state'] == 'stopped'
PY

printf 'BB_FULL_FRESH_MACHINE_OK profiles=%s routes=%s\n' \
  "${#PROFILES[@]}" "${#ROUTES[@]}"
