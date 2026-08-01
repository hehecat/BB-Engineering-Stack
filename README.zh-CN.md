# BB Engineering Stack

简体中文 | [English](README.md)

面向 Claude Code 的可移植、Headless 优先安全工作 Harness。覆盖 CTF、Bug
Bounty/VDP、授权 Web/API、Android、iOS、内网、云、LLM/Agent、源码与供应链
评估，以及 Browser-JS 和二进制逆向分析。

项目把执行环境、Prompt、Skill、MCP/CLI 和测试状态分开管理。换电脑后只需
克隆仓库、执行 bootstrap、恢复机器配置，即可使用相同流程启动 Claude Code。

## 核心能力

- 使用 `bb-stack` 统一完成安装、配置、检查、创建任务、启动 Claude 和更新组件。
- 为 CTF、Bug Bounty、授权安全评估、独立分析和本地 Lab 组合不同 Prompt Overlay。
- 使用独立 Engagement 保存范围、状态、证据、脚本、报告和会话交接信息。
- 通过主编排 Skill 将任务路由到当前需要的漏洞类或分析 Skill。
- 集成 Playwright/Chrome DevTools MCP、HTTP/Recon、移动端、网络、源码和 Reverse CLI。
- 集成 Chrome DevTools MCP/CLI 与 `webcrack`，支持浏览器运行时观察、请求调用链
  还原、解混淆、Webpack/Browserify 拆包和最小本地复现。
- 支持 Headless VPS，不要求桌面环境。
- Skill、MCP 和 CLI 使用固定版本，更新需要显式检查、验证和确认。
- 提供静态合同测试和隔离的真实 Claude 行为评测，包括 BB Scope、Lead
  排序、证据分级、动作预算和秘密脱敏决策。

## 设计边界

```text
$BB_STACK_ROOT   项目源码、Prompt、Profile、Skill、Schema、测试
$BB_WORK_ROOT    用户选择的 Claude 安全工作区根目录
$BB_CONFIG_HOME  当前机器配置和生成文件，不进入源码仓库
```

建议默认路径（不是固定路径）：

```text
BB_STACK_ROOT=$HOME/BB-Engineering-Stack
BB_WORK_ROOT=$HOME/BB-Workspaces
BB_CONFIG_HOME=$HOME/.config/bb-stack
```

真实目标数据不得写入本项目源码目录。

`BB_WORK_ROOT` 在初始化时由用户决定。工作区会在其中生成项目级
`CLAUDE.md`、`.mcp.json`、`inbox/` 和 `engagements/`，不要求工作区与
源码目录同名或位于固定位置。

## L0-L5 架构

| 层级 | 目录 | 职责 |
| --- | --- | --- |
| L0 | `00-L0-Runtime/` | bootstrap、PATH、代理、运行时和启动器 |
| L1 | `01-L1-Global-Prompt/` | 与平台无关的全局执行约定 |
| L2 | `02-L2-Workflow-Profiles/` | 工作流 × 领域 × 平台 Prompt 组合 |
| L3 | `03-L3-Engagement-State/` | Scope、STATUS、HANDOFF、生命周期和模板 |
| L4 | `04-L4-Skills/` | Skill 清单、主编排器和专项 Skill |
| L5 | `05-L5-MCP-CLI/` | MCP、CLI、能力注册表和 Doctor 检查 |

辅助目录：

| 目录 | 内容 |
| --- | --- |
| `90-Docs/` | 配置、迁移、更新、验证和维护文档 |
| `99-Verification/` | 隔离测试、空白机器测试和 Claude Smoke Test |

## 支持的 Profile

| Profile | 用途 | Claude Prompt |
| --- | --- | --- |
| `ctf-web` | CTF Web/API | `ctf-quick`、`ctf-replacement` |
| `web` | Bug Bounty/VDP Web/API | `bb-interactive`、`bb-continuous` |
| `assessment-web` | 合同或书面授权的 Web/API 评估 | `assessment-web` |
| `android` | Android CTF | `ctf-android` |
| `assessment-android` / `analysis-android` | Android 安全评估 / 纯分析 | 同名 Prompt |
| `assessment-ios` | iOS/IPA 安全评估 | `assessment-ios` |
| `assessment-network` / `assessment-cloud` | 内网与云安全评估 | 同名 Prompt |
| `assessment-llm` / `assessment-source` | LLM/Agent 与源码供应链评估 | 同名 Prompt |
| `reverse` / `analysis-reverse` | CTF 逆向 / 独立逆向分析 | 对应 Reverse Prompt |
| `browser-js` | 浏览器 JavaScript 分析、运行时逆向和行为改造 | `browser-js` |
| `minimal` | 本地 Lab 和最小运行环境 | `lab-replacement` |

## 环境要求

- Linux x86_64 或 arm64
- Python 3.11+
- Node.js 22 或 24（缺失或版本过旧时 bootstrap 安装固定版本）
- 已安装并完成登录的 Claude Code
- 能使用 `apt`、Git 和网络下载依赖

桌面环境不是必需条件。普通自然语言会话使用 CLI；严格 Web/Browser-JS Profile
按任务加载 Headless Playwright 或 Chrome DevTools MCP。

## 快速安装

```bash
git clone https://github.com/hehecat/BB-Engineering-Stack.git \
  "$HOME/BB-Engineering-Stack"
cd "$HOME/BB-Engineering-Stack"

./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/BB-Workspaces"
source "$HOME/.config/bb-stack/env.sh"

bb-stack configure
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile ctf-web --strict --probe-mcp
bb-stack eval contracts
```

默认 Agent 使用简体中文回复，并用中文编写进度、可见推理摘要、Plan/Todo、
内部状态和会话交接。命令、代码、路径、协议字段、日志和原始错误保持原文。
隐藏的内部推理不会显示；需要说明判断时，Agent 输出简洁、可核验的中文理由。

可在 bootstrap 时选择语言，或之后随时切换：

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/BB-Workspaces" --agent-language zh-CN

bb-stack configure --agent-language en
source "$BB_CONFIG_HOME/env.sh"
bb-stack workspace init
```

切换后重新运行 `bb-stack workspace init` 会刷新工作根 `CLAUDE.md`；已有
Engagement 数据和 `.claude/settings.local.json` 中的 Claude 权限不会被覆盖。
HackerOne 报告仍由平台 Overlay 默认使用英文，补天报告默认使用中文。

也可以选择其他专用目录：

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/Security-Work"
```

## 默认使用：直接启动 Claude

初始化后进入自己选择的工作根，正常运行 Claude Code：

```bash
cd "$BB_WORK_ROOT"
claude
```

之后直接使用自然语言：

```text
这是一个 CTF Web 题目：https://challenge.example
对 https://target.example 做授权 Web 渗透测试
对 inbox/product.apk 做 Android 安全审计
反编译 inbox/library.apk 并还原算法，不做漏洞测试
对书面授权的 10.20.0.0/24 做内网和 AD 安全评估
审计这个 AWS 账户的 IAM 和 S3
测试这个 RAG Agent 的 Prompt Injection、MCP 和 Memory 边界
审计 inbox/repository 的源码、IaC、容器和依赖安全
继续 example-bb
分析 inbox/challenge.bin
分析 https://app.example 的请求签名，并交付可复用 Node 模块
还原 inbox/app.bundle.js 的混淆和 Webpack 模块结构
```

工作根的 `CLAUDE.md` 会识别任务并调用 `bb-stack workspace route`，自动：

1. 创建或恢复 `engagements/<slug>/`。
2. 先判断 CTF、BB、授权评估、独立分析或 Lab，再选择安全领域。
3. 读取专用 Prompt、Scope、STATUS 和 HANDOFF。
4. 选择主编排 Skill 和当前专项 Skill。
5. 将证据、脚本和报告限制在当前 Engagement。

项目 `.mcp.json` 不常驻任何领域 MCP，避免网络、云、源码等任务承担几十个无关
浏览器工具 Schema。需要浏览器的普通会话使用路由结果中的 `browser_start` 命令和
受管 `chrome-devtools` CLI；严格启动只加载当前 Profile 的 MCP。运行中的 Claude
无法热加载 MCP，因此该分工同时保留自然入口和工具隔离。

私有仓库需要当前机器的 GitHub 身份具有访问权限。

## CTF Web

通常直接在工作根启动 `claude` 并描述题目。以下是显式控制方式：

```bash
bb-stack new web-challenge https://challenge.example \
  --workflow ctf \
  --platform standalone-ctf

bb-stack launch --profile ctf-quick --engagement web-challenge
```

主要路由：

```text
ctf-orchestrator -> ctf-web -> 当前漏洞类 Skill
```

脚本保存在 `scripts/`，关键 HTTP、浏览器和其他证据保存在 `artifacts/`。

## Bug Bounty 和 VDP

先安装 Web Profile：

```bash
cd "$BB_STACK_ROOT"
bb-stack bootstrap --profile web
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile web --strict --probe-mcp
```

通用 VDP：

```bash
bb-stack new example-bb https://example.com \
  --workflow bug-bounty \
  --platform generic-vdp \
  --mode interactive

bb-stack launch --profile bb-interactive --engagement example-bb
```

HackerOne：

```bash
bb-stack configure --h1-username YOUR_H1_USERNAME
source "$BB_CONFIG_HOME/env.sh"

bb-stack new h1-program https://target.example \
  --workflow bug-bounty \
  --platform hackerone \
  --mode continuous

bb-stack launch --profile bb-continuous --engagement h1-program
```

补天只需要把平台改为 `butian`：

```bash
bb-stack new butian-program https://target.example \
  --workflow bug-bounty \
  --platform butian
```

每次测试前将当前项目的书面范围、频率、身份和排除项记录到
`notes/SCOPE.md`。不同平台 Overlay 不会互相继承身份字段或报告格式。
DNS、JavaScript、证书或跳转发现的关联资产先进入 `Candidate Assets`，只有书面
规则或用户指令匹配后才能通过 Scope revision 转为主动测试目标。

Bug Bounty 主要路由：

```text
bb-orchestrator -> 当前 Lead 的专项 Skill
```

`bb-methodology` 只在 Lead 队列为空、陈旧或缺少多样性时按需加载。证明采用
`signal -> primitive -> impact -> confirmed` 四级状态；具体影响必须由正负样本、
身份或对象边界支撑，不能由 Schema、空字段或跨系统观察直接推断。

新 Engagement 的 `notes/SCOPE.md` 带有可由项目规则覆盖的生产动作预算：每个
Lead 默认一次最小状态变更、一个不超过 1 KiB 的惰性上传、三个邻近对象、五次
凭据猜测和十次受控 OTP 校验。CTF 与本地 Lab 不使用这些生产默认值。

只有在需要整理提交材料时才进入 SHIP 和报告 Skill。

## 全域授权安全评估

非 Bug Bounty 的书面授权评估使用 `assessment` 工作流，由
`security-orchestrator` 管理 Scope、证据、跨领域交接和检查点。自然语言会自动
选择 Web/API、Android、iOS、Network/AD、Cloud、LLM/Agent 或 Source Profile。

显式安装示例：

```bash
bb-stack bootstrap --profile assessment-android
bb-stack bootstrap --profile assessment-network
bb-stack bootstrap --profile assessment-source
```

Profile 不互相继承。跨领域 Lead 只调用可选 Skill：例如移动端发现 API 越权时，
仍保留 Android Engagement 的 Scope 和报告规则；Bug Bounty 中分析前端签名时，
也不会切换成独立 Browser-JS 工作流。只有主要目标或授权边界变化才创建新的
Engagement。

Cloud Provider CLI、iOS 真机、Frida、Prowler、Steampipe、Checkov、Trivy 等依赖
按 Profile 报告为可选外部能力；没有相应账户、设备或工具时，静态和基础流程仍可
使用，Doctor 会明确列出缺口。

## Android、iOS 和 Reverse

同一 APK 根据用户目标走不同工作流：

```text
Android CTF        -> ctf-android
Android 安全评估   -> assessment-android
反编译/算法还原    -> analysis-android
```

Android CTF 的显式启动：

```bash
bb-stack bootstrap --profile android
bb-stack status --profile android --strict
bb-stack new apk-challenge ./challenge.apk --workflow ctf --platform standalone-ctf
bb-stack launch --profile ctf-android --engagement apk-challenge
```

Android 静态分析安装 Java、ADB、Apktool、固定版本 JADX，并使用
`android-reverse-engineering` 完成框架识别、反编译、Kotlin/R8 名称恢复、API
提取和调用链分析。需要组件安全、设备、Frida、TLS 或运行时验证时切换到
`android-pentest`；连接设备、Frida 和 Objection 属于动态分析可选项。

iOS 授权审计使用 `assessment-ios`，静态分析可在 Linux Headless 环境进行；真机、
越狱、Frida 和 libimobiledevice 能力由 Doctor 单独检查。

二进制逆向：

```bash
bb-stack bootstrap --profile reverse
bb-stack status --profile reverse --strict
bb-stack new reverse-challenge ./challenge.bin --workflow ctf --platform standalone-ctf
bb-stack launch --profile ctf-reverse --engagement reverse-challenge
```

## 浏览器 JavaScript 分析

通常直接在工作根启动 `claude`，描述目标和希望得到的结果：

```text
分析这个网页的前端签名逻辑，最终给我一个 Node 模块
定位页面限制的实现并做可维护的浏览器扩展
还原这个 bundle 的模块结构和关键协议
分析运行时行为，先不要预设最终产物
```

自然语言路由会创建 `analysis` Engagement，并选择：

```text
browser-js-orchestrator
  -> Chrome DevTools CLI/MCP（运行时）
  -> webcrack（选择性静态还原）
  -> ctf-web / api-security / reverse-orchestrator（仅在 Lead 需要时）
```

该流程不预设任务是 CTF、漏洞测试、油猴脚本或浏览器扩展。可能交付解混淆源码、
调用链和协议文档、Node 复现模块、Hook、patched bundle、扩展、用户脚本或其他
直接满足目标的产物。

显式安装和严格启动：

```bash
bb-stack bootstrap --profile browser-js
bb-stack workspace route --kind browser-js \
  --target https://app.example --slug app-js
bb-stack launch --profile browser-js --engagement app-js
bb-stack doctor --profile browser-js --strict --probe-mcp
bb-stack browser status
bb-stack browser stop
```

方法默认从网络、Console、Source Map、脚本和请求 initiator 的运行时基线开始；
优先窄 Hook，断点作为回退；只对高信号 bundle 使用 `webcrack`，避免先处理全部
vendor 代码或盲目搭建完整浏览器补环境。

## Engagement 目录

每个目标使用一个独立目录：

```text
$BB_WORK_ROOT/engagements/<slug>/
  engagement.yaml
  notes/SCOPE.md
  STATUS.md
  SESSION-HANDOFF.md
  notes/
  artifacts/
  scripts/
  reports/
  deliverables/
```

Claude 启动时先读取四个状态文件。切换会话或机器前执行：

```bash
bb-stack engagement checkpoint SLUG
bb-stack engagement pause SLUG --reason 'switching machine'
```

恢复：

```bash
bb-stack engagement resume SLUG
cd "$BB_WORK_ROOT"
claude
```

在 Engagement 目录内运行 `bb-stack status` 时可以自动识别当前任务。严格
Profile 启动仍可使用 `bb-stack launch --profile PROFILE --engagement SLUG`。

## 统一状态检查

```bash
bb-stack status --profile ctf-web --strict
bb-stack status --profile web --platform hackerone --strict
bb-stack status --profile web --engagement PROGRAM-SLUG --strict
```

状态页统一显示：

- 实际目录和运行时版本
- Prompt 组成、模式和 Token 预算
- Engagement 生命周期和下一步
- Claude/Codex Skill 安装状态
- MCP 和 CLI Provider 状态
- 代理是否真正应用
- HackerOne、OTP、文件交付和 Keysmith 状态
- 可直接执行的修复命令

## 代理配置

默认 `direct` 模式。使用本机 mihomo：

```bash
bb-stack configure --proxy-mode mihomo \
  --http-proxy http://127.0.0.1:7890 \
  --socks-proxy socks5://127.0.0.1:7891
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile web --strict
```

状态页会区分“mihomo 端口存在”和“代理环境已经应用”。

## npm 镜像

初始化默认对 npm 官方源和 npmmirror 执行真实包元数据测速，优先使用当前网络更快
的源；安装失败时再尝试另一个。仓库中的 `package-lock.json` 始终保存官方源 URL，
不会被当前机器的 `.npmrc` 或 npm 缓存改写。

```bash
# 推荐：自动选择
bb-stack configure --npm-registry auto

# 也可以显式固定
bb-stack configure --npm-registry npmjs
bb-stack configure --npm-registry npmmirror

# 初始化时直接指定
bb-stack bootstrap --profile ctf-web --npm-registry auto
```

最终使用的 registry 会显示在 bootstrap 输出和 `bb-stack status` 的 Runtime
部分。外网 VPS 通常选择 npmjs，中国大陆网络通常选择 npmmirror。

## OTP 邮箱

OTP 是可选的一方实现，无需额外项目：

```bash
bb-stack mail configure --provider gmail --user operator@gmail.com
bb-stack mail test
bb-stack mail wait --timeout 120 --since 10
```

密码或 OAuth Token 只保存在：

```text
$HOME/.local/share/pentest-mail/config.env
```

## Prompt 与 Keysmith

正常使用推荐 `bb-stack launch`。它会根据 Profile 和 Engagement 动态渲染并传入
一个 Prompt 文件，不要求持久修改 Claude Code。

Keysmith 仅用于希望直接运行原生 `claude` 时的可选持久 Replacement Prompt：

```bash
bb-stack keysmith status
bb-stack keysmith install --profile ctf-replacement --yes
```

是否启用 Keysmith 不影响 `bb-stack launch` 工作流。

## 行为验证

静态合同不调用模型：

```bash
bb-stack eval contracts
```

换电脑、修改 Prompt 或更新路由 Skill 后，可运行隔离的真实 Claude 验证：

```bash
bb-stack eval agent --profile ctf-quick
bb-stack status --profile ctf-web --require-agent-eval --strict

bb-stack eval agent --profile bb-interactive
bb-stack status --profile web --require-agent-eval --strict

bb-stack eval agent --profile browser-js
bb-stack status --profile browser-js --require-agent-eval --strict
```

评测只允许 Claude 读取和写入本地合成 Engagement，不访问测试目标。
`bb-interactive` 评测还会检查相邻资产不自扩 Scope、业务签名 Lead 优先级、
Primitive 与 Impact 区分、跨系统拼链拒绝、最小动作计划、规范日志路径以及
合成 Secret 不泄露。更换模型或修改 Harness 后可用同一命令做 A/B 对比。
`browser-js` 评测检查运行时观察优先、高信号调用链、Hook 优先、最小依赖复现、
差分验证，以及根据目标选择产物而不是固定输出用户脚本。

## Skill、MCP 和工具更新

查看可用更新，不自动修改环境：

```bash
bb-stack updates check --all
```

更新采用检查、暂存、验证、提升和回滚流程，不在后台自动升级。详见
[`90-Docs/UPDATES.md`](90-Docs/UPDATES.md)。

常用检查：

```bash
bb-stack skills validate
bb-stack doctor --profile ctf-web --strict --probe-mcp
```

## 切换电脑

导出不含凭据的机器配置意图：

```bash
bb-stack portable export "$HOME/bb-stack-portable.json"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
```

新电脑克隆仓库并 bootstrap 后，先预览再导入：

```bash
bb-stack portable import "$HOME/bb-stack-portable.json"
bb-stack portable import "$HOME/bb-stack-portable.json" --yes
source "$BB_CONFIG_HOME/env.sh"
```

Engagement 目录和本地凭据由使用者按自己的存储方式复制；portable JSON 只保存
非敏感配置和任务清单，不包含证据、Cookie、Token、邮箱密码或 Claude 登录状态。

## 详细文档

- [快速开始](90-Docs/QUICKSTART.md)
- [机器配置](90-Docs/CONFIGURATION.md)
- [架构设计](90-Docs/ARCHITECTURE.md)
- [迁移说明](90-Docs/MIGRATION.md)
- [更新机制](90-Docs/UPDATES.md)
- [验证方式](90-Docs/VERIFICATION.md)
- [完成审计](90-Docs/COMPLETION-AUDIT.md)

## 项目状态

当前版本：`0.11.0`

17 个运行 Profile 和 52 个固定 Skill 已通过静态合同。真实 Sonnet 路由评测覆盖
13 个自然语言场景；Browser-JS 继续通过 Chrome DevTools MCP、`webcrack` 和隔离
决策评测，Bug Bounty 继续覆盖 Scope、Lead、证据与动作合同。
