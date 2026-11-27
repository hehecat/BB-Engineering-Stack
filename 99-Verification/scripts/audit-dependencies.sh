#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=python3

uvx --from pip-audit==2.10.1 pip-audit \
  -r "$ROOT/00-L0-Runtime/config/requirements.lock"

AUDIT_JSON="$(mktemp)"
cleanup() {
  rm -f "$AUDIT_JSON"
}
trap cleanup EXIT

set +e
npm --registry=https://registry.npmjs.org audit --package-lock-only --json \
  --prefix "$ROOT/00-L0-Runtime/config/node-runtime" >"$AUDIT_JSON"
AUDIT_EXIT=$?
set -e

"$PYTHON" - "$AUDIT_JSON" "$AUDIT_EXIT" <<'PY'
import json
import sys
from pathlib import Path

# Unfixable upstream transitive advisories in pinned MCP dependencies
# (`anastasis-mcp-server@1.1.0`, `osint-mcp-server@0.2.0`, `chromium-bidi`
# via `chrome-devtools-mcp@1.10.1`):
# - extract-zip (<=2.0.1, latest is 2.0.1): GHSA-jmr9-qjv8-65gv, GHSA-7pqw-9j4j-h8q3
# - basic-ftp (<=6.2.3 via @puppeteer/browsers -> get-uri): GHSA-c475-qrg2-pj4r,
#   GHSA-5pm8-86m8-9m6r, GHSA-r4jh-29pc-gfqr
# - glob (via js-beautify/rimraf): GHSA-3g3m-2fjr-6pw4
# - minimatch (via editorconfig/glob): GHSA-g3hv-75wg-m249
# - zod (<4.6.6 via anastasis-mcp-server/osint-mcp-server/chromium-bidi): GHSA-mrhx-c7xc-m3w5
ALLOWED_UNFIXABLE_GHSAS = {
    "GHSA-jmr9-qjv8-65gv",
    "GHSA-7pqw-9j4j-h8q3",
    "GHSA-c475-qrg2-pj4r",
    "GHSA-5pm8-86m8-9m6r",
    "GHSA-r4jh-29pc-gfqr",
    "GHSA-3g3m-2fjr-6pw4",
    "GHSA-g3hv-75wg-m249",
    "GHSA-mrhx-c7xc-m3w5",
}

raw = Path(sys.argv[1]).read_text(encoding="utf-8")
exit_code = int(sys.argv[2])
try:
    report = json.loads(raw)
except json.JSONDecodeError as error:
    raise SystemExit(f"npm audit did not return valid JSON (exit {exit_code}): {error}\n{raw}")

if "error" in report:
    raise SystemExit(f"npm audit failed: {report['error']}")

vulnerabilities = report.get("vulnerabilities")
if not isinstance(vulnerabilities, dict):
    raise SystemExit(f"npm audit JSON missing vulnerabilities object (exit {exit_code})")

failures: list[str] = []
allowlisted: list[str] = []
for name, entry in sorted(vulnerabilities.items()):
    severity = entry.get("severity")
    fix_available = bool(entry.get("fixAvailable"))
    advisories = [item for item in entry.get("via", []) if isinstance(item, dict)]
    if severity == "critical":
        failures.append(f"{name}: critical severity (fixAvailable={entry.get('fixAvailable')})")
        continue
    if fix_available:
        failures.append(f"{name}: {severity} severity has fixAvailable={entry.get('fixAvailable')}")
        continue
    for advisory in advisories:
        url = str(advisory.get("url", ""))
        ghsa = url.rstrip("/").rsplit("/", 1)[-1]
        if ghsa not in ALLOWED_UNFIXABLE_GHSAS:
            failures.append(
                f"{name}: unexpected unallowlisted advisory {ghsa or url!r} ({advisory.get('title')})"
            )
        else:
            allowlisted.append(f"{name}:{ghsa}")

if failures:
    for item in failures:
        print(f"AUDIT FAILURE: {item}", file=sys.stderr)
    raise SystemExit(1)

if allowlisted:
    print("Allowed unfixable transitive advisories:", ", ".join(sorted(allowlisted)))
PY

printf '%s\n' 'BB_DEPENDENCY_AUDIT_OK'
