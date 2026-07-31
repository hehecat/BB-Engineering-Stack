# BB Engineering Stack

简体中文 | [English](README.md)

面向 Claude Code 的可移植、Headless 优先安全测试工作栈，覆盖 CTF Web、
Bug Bounty、VDP、授权 Web/API 测试、Android 静态分析和二进制逆向。

项目把执行环境、Prompt、Skill、MCP/CLI 和测试状态分开管理。换电脑后只需
克隆仓库、执行 bootstrap、恢复机器配置，即可使用相同流程启动 Claude Code。

## 核心能力

- 使用 `bb-stack` 统一完成安装、配置、检查、创建任务、启动 Claude 和更新组件。
- 为 CTF、HackerOne、补天、通用 VDP 和本地 Lab 组合不同 Prompt Overlay。
- 使用独立 Engagement 保存范围、状态、证据、脚本、报告和会话交接信息。
- 通过主编排 Skill 将任务路由到当前需要的漏洞类或分析 Skill。
- 集成 Playwright MCP、HTTP/Recon CLI、OTP 邮箱、Android 和 Reverse 工具。
- 支持 Headless VPS，不要求桌面环境。
- Skill、MCP 和 CLI 使用固定版本，更新需要显式检查、验证和确认。
- 提供静态合同测试和隔离的真实 Claude 行为评测。

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
| L2 | `02-L2-Workflow-Profiles/` | CTF/BB 工作流、领域 Prompt 和平台 Overlay |
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
| `android` | APK 静态或动态分析 | `ctf-android` |
| `reverse` | 本地二进制和未知文件逆向 | `ctf-reverse` |
| `minimal` | 本地 Lab 和最小运行环境 | `lab-replacement` |

## 环境要求

- Linux x86_64 或 arm64
- Python 3.11+
- 已安装并完成登录的 Claude Code
- 能使用 `apt`、Git 和网络下载依赖

桌面环境不是必需条件。浏览器工作默认使用 Headless Chromium 和 Playwright MCP。

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
继续 example-bb
逆向 inbox/demo.apk，先做静态分析
分析 inbox/challenge.bin
```

工作根的 `CLAUDE.md` 会识别任务并调用 `bb-stack workspace route`，自动：

1. 创建或恢复 `engagements/<slug>/`。
2. 选择 CTF Web、Bug Bounty、Android、Reverse 或 Lab 路由。
3. 读取专用 Prompt、Scope、STATUS 和 HANDOFF。
4. 选择主编排 Skill 和当前专项 Skill。
5. 将证据、脚本和报告限制在当前 Engagement。

项目 `.mcp.json` 只加载精简的 Headless 通用 MCP。高上下文 MCP 或需要严格
隔离和复现时，再使用 `bb-stack launch --profile ...`。
首次进入新工作根时，Claude Code 可能要求确认项目级 `.mcp.json`；确认的是
bootstrap 生成的通用 MCP 配置，可先用 `bb-stack workspace status` 查看服务名。

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

Bug Bounty 主要路由：

```text
bb-orchestrator -> bb-methodology -> 当前 Lead 的专项 Skill
```

只有在需要整理提交材料时才进入 SHIP 和报告 Skill。

## Android 和 Reverse

Android APK：

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

二进制逆向：

```bash
bb-stack bootstrap --profile reverse
bb-stack status --profile reverse --strict
bb-stack new reverse-challenge ./challenge.bin --workflow ctf --platform standalone-ctf
bb-stack launch --profile ctf-reverse --engagement reverse-challenge
```

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
```

评测只允许 Claude 读取和写入本地合成 Engagement，不访问测试目标。

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

当前版本：`0.7.0`

CTF Web、Bug Bounty、Android 静态分析和 Reverse Profile 已通过严格状态检查。
CTF Web、Bug Bounty、Android Profile 及普通 `claude` 的 Android 自动路由均已
通过隔离的真实 Claude 行为评测。
