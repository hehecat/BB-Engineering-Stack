#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"

uvx --from pip-audit==2.10.1 pip-audit \
  -r "$ROOT/00-L0-Runtime/config/requirements.lock"
npm --registry=https://registry.npmjs.org audit --package-lock-only \
  --prefix "$ROOT/00-L0-Runtime/config/node-runtime"

printf '%s\n' 'BB_DEPENDENCY_AUDIT_OK'
