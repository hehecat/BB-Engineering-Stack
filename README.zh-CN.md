# BB Engineering Stack

简体中文 | [English](README.md)

面向 Claude Code 的可移植安全工作流程。初始化一次后，日常使用以自然语言为
主：用户描述目标和目的，Claude 自动选择 CTF、Bug Bounty、授权评估、独立分析或
本地 Lab，并管理对应的 Prompt、Skill、MCP/CLI、Scope、状态和证据目录。

覆盖 Web/API、Android、iOS、Browser-JS、二进制逆向、内网/AD、云、LLM/Agent、
源码、IaC、容器和供应链分析。

## 最短使用路径

### 让 Claude 初始化

新机器需要先安装并登录 Claude Code，然后：

```bash
git clone YOUR_PRIVATE_REMOTE "$HOME/BB-Engineering-Stack"
cd "$HOME/BB-Engineering-Stack"
claude
```

对 Claude 说：

```text
按推荐默认值初始化这个安全工作栈。先检查现有环境和配置，需要我决定的内容再集中问我。
```

仓库根目录的 `CLAUDE.md` 会让 Claude 检查现有安装、推荐工作根、执行初始化并验证
结果。默认工作根建议为 `$HOME/BB-Workspaces`，但不是固定路径。

也可以只手动执行一次最小初始化：

```bash
./00-L0-Runtime/bin/bootstrap --profile minimal \
  --work-root "$HOME/BB-Workspaces"
```

`minimal` 只建立自然语言控制面。Web、Android、Reverse 等能力在任务首次需要时由
Claude 按路由结果安装，不要求用户预先选择 Profile。

### 日常使用

推荐从工作根启动 Claude：

```bash
cd "$HOME/BB-Workspaces"
claude
```

随后直接描述任务，例如：

```text
这是一个 CTF Web 题目：https://challenge.example
对 https://target.example 做 Bug Bounty 测试，直到我叫停
这是 HackerOne 项目，先读取我提供的 Scope 再开始
对 inbox/product.apk 做 Android 安全评估
反编译 inbox/library.apk，还原签名算法，不做漏洞测试
分析 https://app.example 的请求签名并交付可复用 Node 模块
对书面授权的 10.20.0.0/24 做内网和 AD 评估
审计这个 AWS 账户的 IAM 和对象存储
测试这个 RAG Agent 的 Prompt Injection、MCP 和 Memory 边界
审计 inbox/repository 的源码、IaC、容器和依赖
继续 example-bb
检查当前环境、代理、Skill 和 MCP 是否正常
```

用户不需要记忆 Profile、route kind、Engagement 命令、MCP 启动方式或修复命令。

## Claude 会自动做什么

工作根的项目级 `CLAUDE.md` 要求 Claude：

1. 从用户目的判断工作流、领域和平台，而不是让用户选择内部 Profile。
2. 创建或恢复 `engagements/<slug>/`，读取专用 Prompt、Scope、STATUS 和 HANDOFF。
3. 检查当前任务需要的 Skill、MCP 和 CLI；缺少时自己安装、修复并重新验证。
4. 只加载当前编排器和当前 Lead 需要的专项 Skill，避免 Profile 互相污染。
5. 将大输出、证据、脚本和报告保存在当前 Engagement，不污染源码仓库。
6. 取得实质进展后更新状态和交接；连续模式不会只汇报状态后停下。
7. 环境、代理、身份、邮箱、交付和更新请求作为工作栈维护处理，不创建目标任务。

Claude 会先检查本地文件、配置和状态。只有以下信息无法推断且会改变下一步时，才会
主动集中询问一次：

- 缺少目标、文件或明确的分析目标；
- 多个活动任务都可能是用户所说的“继续”；
- 真实目标缺少必要的书面 Scope、速率限制或排除项；
- 下一步确实需要账号、凭据、邮箱授权、设备或云身份；
- 交付形式会显著影响 Browser-JS 或独立分析的实现。

CTF 和本地文件分析不会重复询问授权。普通 Web/API 目标在没有更广 Scope 时只把用户
明确给出的目标作为活动范围，其他关联资产先记录为 candidate。

## 用户只需要提供什么

最小输入通常是“目标或文件 + 想完成的事情”。真实目标建议同时提供：

- 项目平台，例如 HackerOne、补天、通用 VDP 或合同评估；
- 书面 Scope、Out-of-Scope、速率和副作用限制；
- 需要使用的测试账号或实验设备。

个人功能按需配置，不阻塞首次使用。可以直接对 Claude 说：

```text
使用本机 mihomo，HTTP 端口 7890，SOCKS 端口 7891
设置我的 HackerOne 用户名
配置 FileCodeBox 作为交付渠道
配置测试邮箱自动读取 OTP
检查依赖、Skill 和 MCP 是否有可用更新，但先不要升级
```

密码、Token 和邮箱授权保存在机器本地的受限文件中，不进入 Prompt、Git、报告或普通
聊天记录。Keysmith 是显式可选能力，不会在普通任务中自动部署或修改。

## 工作目录

```text
$BB_STACK_ROOT/                 # 本仓库：运行时定义、Prompt、Skill、Schema、测试
$BB_WORK_ROOT/
  CLAUDE.md                     # Claude 自然语言路由器
  inbox/                        # 尚未分类的输入文件
  engagements/
    <slug>/                     # 每个目标或分析任务的独立状态和产物
$BB_CONFIG_HOME/                # 当前机器的非仓库配置和生成状态
```

目标数据不得写入 `$BB_STACK_ROOT`。切换电脑时分别迁移源码、机器配置意图和
Engagement 数据。

## L0-L5

| 层级 | 目录 | 责任 |
| --- | --- | --- |
| L0 | `00-L0-Runtime/` | 初始化、PATH、代理、运行时和启动器 |
| L1 | `01-L1-Global-Prompt/` | 用户语言和通用操作约定 |
| L2 | `02-L2-Workflow-Profiles/` | 工作流、领域、平台 Prompt 和自然语言路由 |
| L3 | `03-L3-Engagement-State/` | Scope、状态、证据索引和会话交接 |
| L4 | `04-L4-Skills/` | 主编排器和专项知识 |
| L5 | `05-L5-MCP-CLI/` | 浏览器、HTTP、移动端、Reverse 等执行能力 |

Prompt 决定任务边界和连续性，Skill 提供专项方法，MCP/CLI 负责执行，文件保存跨会话
状态。跨领域 Lead 可以调用专项 Skill，但不会悄悄切换工作流、Scope 或报告规则。

## 运维与开发文档

普通使用不需要阅读下面的 CLI 文档。迁移、排障、开发或自动化时再查看：

- [快速安装与显式命令](90-Docs/QUICKSTART.md)
- [机器配置、代理和个人集成](90-Docs/CONFIGURATION.md)
- [架构与路由](90-Docs/ARCHITECTURE.md)
- [Engagement 运维](90-Docs/OPERATIONS.md)
- [切换电脑](90-Docs/MIGRATION.md)
- [Skill、MCP 和工具更新](90-Docs/UPDATES.md)
- [验证与真实 Claude 行为测试](90-Docs/VERIFICATION.md)
- [Keysmith 可选集成](90-Docs/KEYSMITH.md)

仓库维护者提交前运行：

```bash
./99-Verification/scripts/run-all.sh
./99-Verification/scripts/fresh-machine.sh
```

全 Profile 网络重型验收使用 `full-fresh-machine.sh`，不属于普通用户流程。
