# BB Recon Pipeline Fixes — 2026-08-07

修复清单,供新 session 统一实施。来源:在 `8x8-com-bb` engagement 手工推进 recon 时
发现的系统性问题,已通过源码阅读与实跑验证。

涉及文件:
- `00-L0-Runtime/lib/bb_stack/recon.py`(L0 核心)
- `00-L0-Runtime/config/recon.yaml`
- `00-L0-Runtime/config/tools.yaml`
- `00-L0-Runtime/lib/bb_stack/runtime.py`

## 评审结论

原始问题判断成立,但不建议把"输出文件存在"直接改写为 provider 成功。当前实现还有
三个必须一起处理的状态语义:

1. provider 的执行结果需要区分 `completed` / `partial` / `failed` / `missing`,不能继续
   只靠进程 `returncode` 表达。
2. stage 的 `partial` 当前是依赖可消费的终态,`resume` 不会再次运行它。若没有显式重跑
   机制,配置 API key 或安装 optional provider 后仍无法补齐已有 engagement。
3. `recommended_actions` 表示当前环境可采取的动作,`coverage_gaps` 表示已经执行后确认的
   覆盖缺口。两者数据源不同,不能合并成同一份声明扫描结果。

推荐将修复拆成三个闭环:

- **执行闭环**: attempt 隔离产物 -> 结果分类 -> 可消费 partial -> 下游继续。
- **恢复闭环**: 安装/配置 provider -> 指定 stage 重跑 -> 级联失效并重建下游。
- **诊断闭环**: 声明驱动发现缺口 -> 给出可执行命令 -> doctor/recon status 使用同一探测器。

## 环境现状(验证基线)

| 项 | 值 |
|---|---|
| 已装 required | subfinder, dnsx, httpx, ffuf, katana, nuclei |
| 已装 optional | alterx, nmap, **jsluice(2026-08-07 手动装)** |
| 未装 optional | bbot, amass, asnmap, assetfinder, gau, waybackurls, naabu, puredns, arjun |
| 8x8 recon 状态 | `passive-assets` blocked(subfinder 300s 超时) |
| subfinder API key | `~/.config/subfinder/provider-config.yaml` 40 源全空 |

---

## P0-1: required provider 超时 → 整链硬 blocked,部分产出被丢弃

**严重性**: 高。单点故障锁死整条依赖链,已装工具(alterx/nmap/jsluice)也全部无法自动调用。

**现象**: `bb-recon run/resume` 时,`passive-assets` 阶段 subfinder 执行 300 秒超时,
即使已经产出 949 个子域名,仍被判 `failed` → stage `blocked` → 下游 11 个阶段全部
`pending`,信号永不生成。

**根因**(`recon.py`):
- `_execute_provider` 超时分支直接返回 `returncode: 1`,不归档已产出文件(`recon.py:467-469`)
- `_run_stage` 对 required 失败一律 `blocked` + return(`recon.py:383-392`)
- `_provider_timeout` 默认 300s,白名单仅 `{bbot, nmap, nuclei, ffuf, puredns}` 900s(`recon.py:1283-1284`)
- 叠加诱因:subfinder 无 API key,仅公共源,21 个根域 300s 跑不完

**修复建议**:
1. `_execute_provider` 返回结构化结果,至少包含 `state`, `returncode`, `error_kind`,
   `artifact_usable`, `command`, `error`;超时且产物可消费时返回 `state: partial`,不要伪造
   `returncode: 0`。
2. 每次执行使用 attempt 临时路径,例如 `<output>.attempt-<n>.part`,避免把上次遗留文件误判
   为本次 partial。成功或可恢复 partial 后再原子提升为正式 artifact。
3. partial 判定必须按格式验证,不能只判断 `exists()` 或文件非空:
   - 行格式和 JSONL 可保留完整行,丢弃未完成的尾行;
   - JSON/XML 只有完整解析成功才可消费;
   - `subfinder` 文本输出可作为首个明确允许 salvage 的 provider。
4. `_run_stage` 在 required provider 为 `partial` 且 artifact 可消费时完成聚合,stage 标记
   `partial`,下游允许消费;required `failed`/`missing` 仍保持 `blocked`。
5. partial provider 必须生成 coverage gap,包括 required provider 的 partial。否则 recon
   可以在没有任何待确认缺口的情况下关闭,与"基线不完整"的事实不符。
6. `_provider_timeout` 改为实例方法并读取配置。短期统一使用
   `limits.stage_timeout_seconds=900`;后续可把配置拆成
   `default_provider_timeout_seconds` 和按 provider override,避免"stage timeout"同时表示
   单个进程超时和整个 stage 预算。
7. 检测 subfinder provider 配置为空时给出 `configure-provider` 提示,但不要把无 key 直接
   判为不可运行;公共源仍然可以产生有效结果。

**验证**: 构造 subfinder 超时 fixture,本次 attempt 生成 949 条且存在上次旧 artifact。修复后
只消费本次 949 条,provider/stage 均为 `partial`,日志保留 timeout,下游开始推进,并生成
`passive-assets.subfinder` coverage gap。

---

## P0-2: partial 是终态,安装或配置后无法补跑

**严重性**: 高。当前 `TERMINAL_STAGE_STATES` 包含 `partial`,`resume` 会永久跳过该 stage。
同时,已完成的下游阶段不会因上游新增结果自动失效。仅修复 P0-1 会让首轮可继续,但会
破坏后续补全能力。

**修复建议**:
1. 新增 `bb-stack recon rerun <engagement> --stage <id> --cascade`。默认只允许重跑
   `partial`/`blocked` stage;`--force` 才允许重跑 completed stage。
2. `--cascade` 将目标 stage 及其传递下游重置为 `pending`,清理派生聚合文件,但保留 provider
   原始 artifact 和日志的 attempt 历史,然后按 DAG 顺序重建。
3. 不建议让普通 `resume` 自动重跑所有 partial。否则每次 resume 都会重复长耗时 provider,
   且新增上游结果不会可靠地传播到已完成下游。
4. `install-provider` / `configure-provider` 动作应附带建议的 rerun 命令和受影响 stage。

**验证**: 首次 subfinder partial 后完整推进;补充配置后执行
`recon rerun ... --stage passive-assets --cascade`,确认 passive-assets 及其传递下游 attempts
增加,无关的 `organization-assets` 不重跑,新子域能进入后续 DNS/Web 产物。

---

## P0-3: recommended_actions 是"运行后反射",声明与推荐脱节

**严重性**: 高。工具声明了但推荐不出,且依赖死锁时缺口完全不可见。

**现象**: `tools.yaml`/`recon.yaml` 声明了全部 optional 工具,但 `bb-recon status` 的
`recommended_actions` 只包含**已运行阶段**缺失的 provider。
- 当前 8x8 推荐 6 条,全部来自已 run 的 `organization-assets`/`passive-assets`
- **未运行阶段的 optional 完全不出现**: `arjun`, `gau`, `naabu`, `puredns`, `waybackurls`
- `bb-stack doctor` 中 jsluice/bbot/amass 等出现 0 次

**根因**(`recon.py:1153-1183`): `_refresh_summary` 遍历 `state["stages"][...]["providers"]`
(运行时反射),而 `providers` 字典只在 stage 实际 run 过才填充(`_run_stage`)。阶段没跑
→ 字典空 → 无建议。形成死锁:需要 jsluice 的阶段没跑 → 不推荐 jsluice → 不装 →
阶段跑了也跳过。

**修复建议**: `_refresh_summary` 增加**声明驱动反向扫描**,但只用于
`recommended_actions`,不要把未执行阶段的缺失提前写入 `coverage_gaps`:

```python
for spec in self.config["stages"]:
    stage = state["stages"][spec["id"]]
    if stage["state"] in TERMINAL_STAGE_STATES:
        continue  # 已运行阶段使用实际 provider 结果
    for provider in spec["required_providers"] + spec["optional_providers"]:
        if not self._provider_available(provider):
            # 生成声明型 install-provider 建议,标注 required/stage/command
            pass
```

动作应按 provider 去重,同时保留 `stages: [...]`,避免 amass/bbot 因多个 stage 重复刷屏。
required missing 也必须生成动作;当前 `_refresh_summary` 的 `detail.get("required")` 过滤会使
真正阻塞管线的 required provider 反而没有安装建议。

效果: 无论阶段是否运行过,所有未装 provider 都出现在 `recommended_actions`,但只有实际
执行后 missing/failed/partial 的 provider 才进入 `coverage_gaps`。

**验证**: 修复后 `bb-recon status 8x8-com-bb --json`,`recommended_actions` 含
`arjun`, `gau`, `naabu`, `puredns`, `waybackurls`(此前缺失的 5 个)。

---

## P1-4: optional 工具安装无独立入口(install_tools 已存在但未暴露)

**严重性**: 中。安装基础设施完整,但被埋在 profile 安装流程里,无 `tool install` 命令,
`install-provider` 建议无法执行。

**现状**:
- `runtime.py:701` 有完整 `install_tools(profile, include_optional, ...)`,支持
  `kind: go / apt / uv-tool`,带 `checks` 验证
- `tools.yaml` 的 `installers` 有 41 个工具定义(含全部 recon providers,带固定版本)
- 但仅 `runtime.py:76` 在 profile 安装时调用,且 `include_optional: bool = False`(默认不装 optional)
- 顶层 CLI(`bb-stack --help`)无工具安装命令
- `recommended_actions` 的 `install-provider` 只是字符串,无执行路径

**修复建议**:
1. 先将 `RuntimeManager.install_tools(profile, ...)` 内的通用部分提取为
   `install_named_tools(names, *, dry_run)`,profile 安装和新 CLI 共用它。新增
   `bb-stack tool install <name...> [--dry-run] [--json]`;指定名字时不需要 `--optional`。
   从 `tools.yaml` installers 按名读取定义,执行后跑 `checks` 验证。注意:
   - `kind: go` → `go install <package>`(package 已含固定版本,如
     `github.com/BishopFox/jsluice/cmd/jsluice@0ddfab15...`)
   - `kind: apt` → apt 安装
   - `kind: uv-tool` → 复用现有 `uv tool install --python 3.12 --force <package>`
   - 装到 `paths.runtime_path()`(recon 用 `shutil.which(provider, path=runtime_path)` 检测)
2. 让 `recommended_actions` 携带 `command: ["bb-stack", "tool", "install", name]`,CLI
   文本输出再用 `shlex.join` 展示,JSON 中保留 argv 数组。
3. 复查 `bootstrap` 的 `include_optional` 语义,确认是否为有意默认 False(若是,保留,
   但独立命令补上入口)。
4. 增加 unknown installer、重复名称、已安装幂等、apt 批处理、uv-tool Python 版本和
   post-check 失败测试。

**验证**: `bb-stack tool install waybackurls` 后 `command -v waybackurls` 命中,
`bb-recon status` 中 `waybackurls` 不再出现在 missing。

---

## P1-5: bb-stack doctor 与 recon 工具声明不完全对齐

**严重性**: 中。诊断入口与 recon 工具链脱节,无法一键发现 recon 缺装。

**现象**: `bb-stack doctor --json` 的 `capabilities.providers` 仅 20 项 profile 能力
(curl/ffuf/httpx/sqlmap/jq 等),不含 subfinder/dnsx/katana/nuclei/bbot/amass/jsluice;
jsluice 在 doctor 输出中出现 0 次。

**根因修正**: `05-L5-MCP-CLI/capabilities.yaml` 已声明 `subfinder`, `bbot`, `amass`,
`jsluice` 以及 `recon.*` capabilities;`profiles/web.yaml` 也选择了部分 recon capability。
实际问题是 doctor 按 profile capability 计算和展示,而 recon pipeline 又从
`recon.yaml` 独立声明 required/optional,两份声明可能漂移,且 doctor 没有展示 stage 维度。

**修复建议**:
1. 提取共享 `ProviderInventory`,统一 PATH、复合依赖(如 puredns + massdns)和配置状态探测,
   供 recon status、doctor、tool install post-check 使用。
2. doctor 新增独立 `recon` section,读取 `recon.yaml` 并输出
   `required_ready`, `missing_required`, `missing_optional`, `stages`, `providers`。
3. 保持顶层 `ready` 的既有 profile 语义,不要因为任意 optional recon provider 缺失而置
   `ready=false`,避免破坏 `doctor --strict` 和现有 profile 验证。需要严格检查 recon 时新增
   `bb-stack doctor --recon --strict` 或专用 profile。
4. 增加契约测试,确保 `recon.yaml` 中的每个 provider 都存在于 `tools.yaml.installers`,
   且必要时存在于 capabilities registry,从源头阻止三份清单漂移。

**验证**: `bb-stack doctor --json` 的 `recon.providers` 列出 `subfinder`(装)、
`jsluice`(装)、`bbot`/`amass`(缺)等,`recon.required_ready` 反映 required provider 状态,
顶层 `ready` 保持既有 profile 语义。

---

## P2-6: subfinder 无 API key(外部前置,超时的影响因素)

**严重性**: 中(外部依赖)。40 个被动源全空会降低覆盖率,但不能断言一定导致变慢;
新增 API source 也可能增加调用量。超时的直接原因仍应以 subfinder 日志和逐源耗时为准。

**现状**: `~/.config/subfinder/provider-config.yaml` 40 源全部无有效 key。

**修复建议**:
1. 用户提供可用 key 后写入 subfinder 实际读取的配置文件,先用 `subfinder -version` 和
   最小单域命令验证配置路径与 source 可用性,不要只凭固定路径假设。
2. 系统侧:检测 config 全空时,在 recommended_actions 或 doctor 增加
   `configure-provider: subfinder` 建议(与 P0-3 的声明驱动扫描同源)。
3. 配置凭据只检测“存在/可解析/至少一个非空项”,输出中不回显 key;不要把凭据内容写入
   engagement state、日志或源码仓库。

**验证**: 配置后至少一个 authenticated source 可用;随后通过 P0-2 的显式 rerun 机制重跑,
比较完成时间和结果数。验收标准是可恢复和覆盖改善,不是强制要求 300s 内完成。

---

## P3-7: 用户环境注意(非 recon 缺陷)

- 用户 zsh 中 `gau` 是 `git add --update` 的 alias。recon 的 `_provider_available`
  用 `shutil.which`(不解析 shell alias),故**不影响管线**,但用户手动 `gau` 会踩坑。
  建议在 `.zshrc` 移除该 alias 或用完整路径 `$HOME/go/bin/gau`。
- 注意 gau 的正确安装源是 `github.com/lc/gau/v2/cmd/gau@v2.2.4`(tools.yaml 已固定),
  不要用其他仓库。

---

## 建议修复顺序

1. **P0-1**(attempt 隔离 + partial 结果 + 格式校验 + timeout 配置化)
2. **P0-2**(stage 显式 rerun + DAG cascade)—— 与 P0-1 同一批交付
3. **P0-3**(声明驱动推荐,与 coverage gap 分离)
4. **P1-4**(`tool install` 命令和共享 named installer)
5. **P1-5**(共享 provider inventory + doctor recon section + 漂移测试)
6. **P2-6**(subfinder 配置检测与凭据提示)
7. **P3-7**(用户 shell alias 清理)

## 通用验证

每项修复后:
1. `bb-recon status 8x8-com-bb --json` 观察阶段/建议变化
2. 涉及 L0 源码修改后,跑 `99-Verification/scripts/run-all.sh` 相关测试
   (测试文件: `99-Verification/scripts/test_recon.py`)
3. 不破坏现有 engagement 状态(`8x8-com-bb`, `lixiang-com-bb`, `sanmen-gov-butian-bb`,
   `jtexpress-butian-bb`)
4. 所有真实 engagement 验证前先备份 `recon/state.json` 和 recon 派生产物;自动化测试使用
   临时 fixture,不得把 engagement 数据写入源码仓库。
5. 新 provider state 或字段需要更新 state schema/migration,验证旧 state 加载后不会丢失
   `accepted` gap、signals、attempts 和 artifact 引用。

## 最小测试矩阵

| 场景 | 预期 |
|---|---|
| required provider 超时且本次文本有完整行 | provider/stage partial,下游可运行,保留 timeout gap |
| 超时但只有旧 artifact | blocked,不得误消费旧数据 |
| JSON/JSONL 尾部损坏 | JSON 拒绝;JSONL 只保留完整合法行 |
| required provider 非零退出且无可用产物 | blocked,下游 pending |
| optional provider 未安装且 stage 未运行 | 只出现 install action,不产生 coverage gap |
| optional provider 实跑 missing/failed | action + coverage gap |
| 安装 provider 后 rerun --cascade | 只重跑目标及传递下游,新数据向后传播 |
| doctor 默认模式 | optional recon 缺失不破坏既有顶层 ready |
| 旧 schema v1 state | 自动迁移并保持原有接受状态和 artifact 引用 |

## 关键源码位置速查

| 位置 | 内容 |
|---|---|
| `recon.py:383-392` | required 缺失/失败 → blocked |
| `recon.py:396-409` | optional 缺失 → 跳过(不自动装) |
| `recon.py:457-469` | 执行 provider,超时分支丢弃产出 |
| `recon.py:1153-1183` | `_refresh_summary` recommended_actions(运行后反射) |
| `recon.py:1283-1284` | `_provider_timeout` 白名单 |
| `runtime.py:701` | `install_tools`(go/apt/uv-tool, checks) |
| `runtime.py:50-51` | `include_optional=False` 默认 |
| `config/tools.yaml` | `installers` 41 个工具定义(固定版本) |
| `config/recon.yaml:10-122` | 各阶段 required/optional providers |
