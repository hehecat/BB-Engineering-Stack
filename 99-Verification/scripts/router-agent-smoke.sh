#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
WORK="$(mktemp -d /tmp/bb-router-agent.XXXXXX)"
cleanup() {
  rm -rf -- "$WORK"
}
trap cleanup EXIT

export BB_STACK_ROOT="$ROOT"
export BB_WORK_ROOT="$WORK/work"
export BB_CONFIG_HOME="$WORK/config"
"$ROOT/00-L0-Runtime/bin/bb-stack" workspace init --json >/dev/null

PROMPT='Classify each independent user request using the workspace router. Do not run tools or create Engagements. Return one JSON object whose keys are the case ids and values are objects with exactly kind and platform.

web_ctf: 这是一个 Web CTF 题目：https://challenge.example
hackerone: 测试 HackerOne 项目 https://target.example
network: 对书面授权的 10.20.0.0/24 做内网和 AD 安全评估
android_ctf: 这是 Android CTF，题目文件 inbox/challenge.apk
android_assessment: 对 inbox/product.apk 做组件、存储、TLS 和 Frida 安全测试
android_analysis: 反编译 inbox/library.apk 并还原签名算法，不做漏洞测试
ios: 对 inbox/product.ipa 做授权移动端安全审计
reverse: 分析 inbox/firmware.bin 的协议和算法，不是 CTF
cloud: 审计授权 AWS 账户的 IAM、S3 和权限提升路径
llm: 测试这个 RAG Agent 的间接 Prompt Injection、MCP 和 Memory 边界
source: 审计 inbox/repository 的源码、IaC、容器和依赖安全
browser_js: 分析 https://app.example 的前端签名并交付 Node 模块
lab: 在本地 fixture 中复现这个受控漏洞。'

OUTPUT="$WORK/output.json"
(
  cd "$BB_WORK_ROOT"
  claude --print --output-format text --no-session-persistence \
    --tools "" --effort low --model "${BB_ROUTER_EVAL_MODEL:-sonnet}" \
    --max-budget-usd "${BB_ROUTER_EVAL_BUDGET:-1.0}" "$PROMPT"
) >"$OUTPUT"

python3 - "$OUTPUT" <<'PY'
import json
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
start, end = text.find("{"), text.rfind("}")
if start < 0 or end < start:
    raise SystemExit("router evaluation did not return a JSON object")
result = json.loads(text[start : end + 1])
expected = {
    "web_ctf": ("ctf-web", "standalone-ctf"),
    "hackerone": ("web", "hackerone"),
    "network": ("network-assessment", "authorized-assessment"),
    "android_ctf": ("ctf-android", "standalone-ctf"),
    "android_assessment": ("android-assessment", "authorized-assessment"),
    "android_analysis": ("android-analysis", "standalone-analysis"),
    "ios": ("ios-assessment", "authorized-assessment"),
    "reverse": ("reverse-analysis", "standalone-analysis"),
    "cloud": ("cloud-assessment", "authorized-assessment"),
    "llm": ("llm-assessment", "authorized-assessment"),
    "source": ("source-audit", "authorized-assessment"),
    "browser_js": ("browser-js", "standalone-analysis"),
    "lab": ("lab", "local-lab"),
}
failures = []
for key, (kind, platform) in expected.items():
    actual = result.get(key, {})
    if actual.get("kind") != kind or actual.get("platform") != platform:
        failures.append(f"{key}: expected {kind}/{platform}, got {actual}")
if failures:
    raise SystemExit("\n".join(failures))
print(f"BB_ROUTER_AGENT_OK cases={len(expected)}")
PY
