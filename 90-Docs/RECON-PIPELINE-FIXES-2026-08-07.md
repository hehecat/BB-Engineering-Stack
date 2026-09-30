# BB Recon Pipeline Fixes — 2026-08-07

> **历史变更记录,非当前行为规范。** 本文记录 2026-08-07 那次 recon 缺陷评审的
> 问题、设计意图与逐条状态(`shipped` / `open`),用于追溯“为什么这样实现”。
> 行为以当前源码与 `99-Verification/scripts/test_recon.py` 为准。
>
> - 状态复核日期:2026-09-30(仅做源码阅读确认,未执行测试)。
> - 本文以**函数名/符号名**定位,不写行号:行号会随重构漂移。需要行号时用
>   `grep -n "def _run_stage" 00-L0-Runtime/lib/bb_stack/recon.py` 之类命令重新定位。
> - 本文不记录任何 engagement 名称、目标数据或本机环境清单;那些属于
>   `$BB_WORK_ROOT/engagements/<slug>/`,不进源码仓库。

涉及文件:
- `00-L0-Runtime/lib/bb_stack/recon.py`(L0 核心)
- `00-L0-Runtime/config/recon.yaml`
- `00-L0-Runtime/config/tools.yaml`
- `00-L0-Runtime/lib/bb_stack/runtime.py`

## 评审结论

原始问题判断成立,但不建议把“输出文件存在”直接改写为 provider 成功。当前实现还有
三个必须一起处理的状态语义:

1. provider 的执行结果需要区分 `completed` / `partial` / `failed` / `missing`,不能继续
   只靠进程 `returncode` 表达。
2. stage 的 `partial` 是依赖可消费的终态,`resume` 不会再次运行它。若没有显式重跑
   机制,配置 API key 或安装 optional provider 后仍无法补齐已有 engagement。
3. `recommended_actions` 表示当前环境可采取的动作,`coverage_gaps` 表示已经执行后确认的
   覆盖缺口。两者数据源不同,不能合并成同一份声明扫描结果。

推荐将修复拆成三个闭环:

- **执行闭环**: attempt 隔离产物 -> 结果分类 -> 可消费 partial -> 下游继续。
- **恢复闭环**: 安装/配置 provider -> 指定 stage 重跑 -> 级联失效并重建下游。
- **诊断闭环**: 声明驱动发现缺口 -> 给出可执行命令 -> doctor/recon status 使用同一探测器。

## 当前实现快照(2026-09-30 复核)

| 概念 | 当前实现(以符号定位) |
|---|---|
| stage 终态 | `TERMINAL_STAGE_STATES = {"completed", "partial", "skipped"}` |
| provider 结果 | `_execute_provider` 返回结构化 dict:`state` / `returncode` / `artifact_usable` / `error_kind` / `command` / `error` |
| attempt 隔离 | `<output>.<n>.attempt.part` 临时路径,成功或可恢复 partial 后原子替换 |
| 超时可回收 | 超时且本次 attempt 文本可用时,`subfinder` 提升为 `state: partial` + `artifact_usable: True`(`_execute_provider` 内 `provider == "subfinder"` 分支) |
| stage 聚合 | required `failed`/`missing` -> `blocked`;required 可消费 `partial` -> 下游继续并记 gap(`_run_stage`) |
| 显式重跑 | `bb-stack recon rerun ENG --stage STAGE [--cascade] [--force]`(`recon.py::rerun`,CLI parser 限 `BASELINE_STAGE_IDS`) |
| 声明驱动推荐 | `_refresh_summary` 扫描 `config["stages"]` 中所有未终态阶段 |
| 超时预算 | `_provider_timeout` 读取 `limits.stage_timeout_seconds`(`config/recon.yaml`) |
| provider 可用性 | `_provider_available`:search provider 查环境变量,`puredns` 查 puredns + massdns,其余 `shutil.which` |

---

## P0-1: required provider 超时 → 整链硬 blocked,部分产出被丢弃

**严重性**: 高。单点故障锁死整条依赖链,已装工具也全部无法自动调用。

**状态: shipped(2026-09-30 源码确认)**,除第 7 条“配置为空提示”外。

- `_execute_provider` 返回结构化结果,含 `state`、`returncode`、`artifact_usable`、
  `command`、`error`;超时且产物可消费时返回 `state: partial`,不伪造 `returncode: 0`。
- 每次执行使用 `<output>.attempt.part` 临时路径,避免把上次遗留文件误判为本次 partial;
  成功或可恢复 partial 后原子提升为正式 artifact。
- 文本输出按完整行 salvage:`_usable_line_output` 只保留完整行,首个明确允许 salvage 的
  provider 是 `subfinder`。
- `_run_stage` 在 required provider 为可消费 `partial` 时完成聚合,stage 标记 `partial`;
  required `failed`/`missing` 仍为 `blocked`。
- partial provider 生成 coverage gap(见 P0-3 的 `_refresh_summary`)。
- `_provider_timeout` 改为实例方法并读取 `limits.stage_timeout_seconds`
  (`00-L0-Runtime/config/recon.yaml`)。

**open(未实现)**: 第 7 条 —— 检测 subfinder provider 配置为空并给出 `configure-provider`
提示尚未实现;`_provider_available` 对 `subfinder` 只检查是否安装,`SEARCH_PROVIDER_ENV`
只覆盖 `exa` / `tavily` / `brave` 的 API key 检测。
**open(未实现)**: 第 6 条的后续 —— 超时预算仍是单一 `stage_timeout_seconds`,尚未拆成
`default_provider_timeout_seconds` + 按 provider override。

**验证**(回归矩阵见文末):fixture 中 subfinder 超时、本次 attempt 有完整行且存在上次旧
artifact 时,只消费本次输出,provider/stage 均为 `partial`,下游继续推进,并产生对应
coverage gap。对应测试:`test_recon.py::test_subfinder_timeout_promotes_only_the_current_attempt_as_partial`。

---

## P0-2: partial 是终态,安装或配置后无法补跑

**严重性**: 高。`TERMINAL_STAGE_STATES` 含 `partial`,普通 `resume` 会永久跳过该 stage。

**状态: shipped(2026-09-30 源码确认)**。

- `bb-stack recon rerun <engagement> --stage <id> --cascade [--force]` 已实现
  (`recon.py::rerun`;CLI parser 含 `--stage`(限 `BASELINE_STAGE_IDS`)、`--cascade`、`--force`)。
- `--cascade` 将目标 stage 及其传递下游重置为 `pending`,按 DAG 顺序重建;无关阶段不重跑。
- 普通 `resume` 不自动重跑所有 partial(刻意保留),避免每次 resume 重复长耗时 provider。
- `install-provider` / `configure-provider` 动作携带可执行 `command`,并有 `rerun-stage`
  建议动作(见 P0-3)。

**验证**:fixture 中确认 rerun 只重跑目标及传递下游,无关阶段不重跑。
对应测试:`test_recon.py::test_rerun_cascades_to_dependents_without_repeating_unrelated_stages`。

---

## P0-3: recommended_actions 是"运行后反射",声明与推荐脱节

**严重性**: 高。工具声明了但推荐不出,且依赖死锁时缺口完全不可见。

**状态: shipped(2026-09-30 源码确认)**。

- `_refresh_summary` 先由**已执行** provider 结果生成 `coverage_gaps`;再对
  `config["stages"]` 做**声明驱动反向扫描**,跳过已终态阶段,为所有不可用 provider 生成
  `recommended_actions`。
- 动作按 provider 去重,同时保留 `stages: [...]`,避免同一工具因多个 stage 重复刷屏。
- required missing 也生成动作并置 `required: true`;未执行阶段的缺失只进
  `recommended_actions`,不提前写入 `coverage_gaps`。
- rerun 建议动作携带完整 argv:`["bb-stack","recon","rerun",<slug>,"--stage",<id>,"--cascade"]`。

**验证**:fixture 中先跑一个阶段,其未运行阶段的 optional provider 也出现在
`recommended_actions`,但 `coverage_gaps` 只包含实际执行后的缺口。
对应测试:`test_recon.py::test_status_recommends_declared_providers_before_their_stage_runs`、
`::test_status_recommends_missing_required_provider_without_running_stage`、
`::test_status_recommends_search_key_configuration_without_install_action`。

---

## P1-4: optional 工具安装无独立入口

**严重性**: 中。安装基础设施完整,但被埋在 profile 安装流程里,`install-provider` 建议无法执行。

**状态: shipped(2026-09-30 源码确认)**。

- `RuntimeManager.install_tools` 内的通用部分已提取为 `install_named_tools(names, *, dry_run)`,
  profile 安装与新 CLI 共用。
- 新增 `bb-stack tool install <name...> [--dry-run] [--json]`(仅这两个标志,没有
  `--optional`;按名安装全部走同一入口)。定义从 `tools.yaml` 的 `installers` 按名读取
  (`kind: go / apt / uv-tool`),执行后跑 `checks` 验证。
- `recommended_actions` 的 `install-provider` 携带
  `command: ["bb-stack","tool","install",<provider>]`;CLI 文本输出用 `shlex.join` 展示,
  JSON 保留 argv 数组。

**验证**:`bb-stack tool install waybackurls` 后 `command -v waybackurls` 命中,
`bb-recon status` 中该 provider 不再出现在 missing。
相关测试:`99-Verification/scripts/test_runtime_installers.py`。

---

## P1-5: bb-stack doctor 与 recon 工具声明不完全对齐

**严重性**: 中。诊断入口与 recon 工具链脱节,无法一键发现 recon 缺装。

**状态: open(2026-09-30 未实现)**。

- `bb-stack doctor` 当前仅有 `--profile` / `--engagement` / `--strict` / `--probe-mcp` /
  `--json`,没有 `recon` section,也没有 `--recon`。
- 尚无共享 `ProviderInventory`;recon status、doctor、tool install post-check 仍各自探测。
- 尚无“`recon.yaml` 中每个 provider 必须存在于 `tools.yaml.installers` 且必要时存在于
  capabilities registry”的漂移契约测试。

**建议(仍未实施)**: 提取共享 `ProviderInventory`;doctor 增加独立 `recon` section
(`required_ready`、`missing_required`、`missing_optional`、`stages`、`providers`);保持顶层
`ready` 的既有 profile 语义,不因 optional recon provider 缺失而置 false;需要严格检查时
新增 `bb-stack doctor --recon --strict`;补漂移契约测试。

**现状替代**: 当前可用 `bb-recon status <engagement> --json` 查看 stage/provider 维度,
用 `bb-stack updates check --all --json` 查看组件目录。

---

## P2-6: subfinder 无 API key(外部前置)

**严重性**: 中(外部依赖)。被动源无 key 会降低覆盖率,但不能断言一定导致变慢;超时的直接
原因仍应以 subfinder 日志和逐源耗时为准。

**状态: partial —— 通用凭据提示 shipped,subfinder 专用检测 open。**

- shipped:search provider 的 API key 由 `_provider_available` / `SEARCH_PROVIDER_ENV`
  检测,缺失时生成 `configure-provider` 动作且不回显 key。
- open:尚未检测 subfinder 自身配置文件是否全空,也不会为它生成 `configure-provider` 提示;
  subfinder 只按“是否安装”判断。
- shipped:凭据只检测“存在/可解析/至少一个非空项”,输出不回显 key,不写入 engagement state、
  日志或源码仓库。

**建议(仍未实施)**: 用户提供 key 后写入 subfinder 实际读取的配置文件,先用
`subfinder -version` 和最小单域命令验证配置路径与 source 可用性,不要只凭固定路径假设;
系统侧在 `recommended_actions`/doctor 增加 `configure-provider: subfinder`,与 P0-3 的
声明驱动扫描同源。

---

## P3-7: 用户环境注意(非 recon 缺陷)

- 用户 shell 中可能存在与 recon provider 同名的 alias(例如把 `gau` 定义成 `git add -u`)。
  recon 的 `_provider_available` 用 `shutil.which`,**不解析 shell alias**,故不影响管线;
  手动调用会踩坑。建议移除 alias 或用完整路径。
- 安装 `gau` 时使用 `tools.yaml` 固定的正确仓库与版本,不要改用其他 repo。

**状态: 环境说明,无代码改动。**

---

## 建议修复顺序(落实状态)

1. **P0-1**(attempt 隔离 + partial 结果 + 格式校验 + timeout 配置化)—— shipped
2. **P0-2**(stage 显式 rerun + DAG cascade)—— shipped
3. **P0-3**(声明驱动推荐,与 coverage gap 分离)—— shipped
4. **P1-4**(`tool install` 命令和共享 named installer)—— shipped
5. **P1-5**(共享 provider inventory + doctor recon section + 漂移测试)—— **open**
6. **P2-6**(subfinder 配置检测与凭据提示)—— **partial**
7. **P3-7**(用户 shell alias 清理)—— 环境说明

## 通用验证

每项修复后:
1. `bb-recon status <engagement> --json` 观察阶段/建议变化。
2. 涉及 L0 源码修改后,跑 `99-Verification/scripts/run-all.sh` 相关测试
   (测试文件: `99-Verification/scripts/test_recon.py`)。
3. 不破坏既有 engagement 状态;真实 engagement 验证前先备份 `recon/state.json` 和 recon
   派生产物。自动化测试使用临时 fixture,**不得**把 engagement 数据写入源码仓库。
4. 新 provider state 或字段需要更新 state schema/migration,验证旧 state 加载后不会丢失
   `accepted` gap、signals、attempts 和 artifact 引用。

## 回归矩阵

| 场景 | 预期 |
|---|---|
| required provider 超时且本次文本有完整行 | provider/stage partial,下游可运行,保留 timeout gap |
| 超时但只有旧 artifact | blocked,不得误消费旧数据 |
| JSON/JSONL 尾部损坏 | JSON 拒绝;JSONL 只保留完整合法行 |
| required provider 非零退出且无可用产物 | blocked,下游 pending |
| optional provider 未安装且 stage 未运行 | 只出现 install action,不产生 coverage gap |
| optional provider 实跑 missing/failed | action + coverage gap |
| 安装 provider 后 rerun --cascade | 只重跑目标及传递下游,新数据向后传播 |
| doctor 默认模式(P1-5 实施后) | optional recon 缺失不破坏既有顶层 ready |
| 旧 schema v1 state | 自动迁移并保持原有接受状态和 artifact 引用 |

## 关键源码位置速查(按符号定位)

| 符号 / 文件 | 内容 |
|---|---|
| `recon.py::TERMINAL_STAGE_STATES` | stage 终态集合(含 `partial`) |
| `recon.py::rerun` | stage 重跑 + `--cascade` |
| `recon.py::_run_stage` | required missing/failed -> blocked;可消费 partial -> 下游继续 |
| `recon.py::_execute_provider` | attempt 隔离、超时杀进程组、结构化结果 |
| `recon.py::_execute_provider`(`provider == "subfinder"`) | 超时 salvage -> `partial` |
| `recon.py::_usable_line_output` | 文本 artifact 完整行校验 |
| `recon.py::_archive_bbot_output` | BBOT 产物归档 |
| `recon.py::_refresh_summary` | coverage gaps(已执行结果)+ 声明驱动 recommended_actions |
| `recon.py::_provider_available` | PATH / 环境变量 / 复合依赖探测(含 puredns + massdns) |
| `recon.py::_provider_timeout` | 读 `limits.stage_timeout_seconds` |
| `recon.py::_execution_gate` | 受保护 workflow + active + 已记录授权 |
| `runtime.py::install_tools` | go / apt / uv-tool 安装 + checks |
| `runtime.py::install_named_tools` | `bb-stack tool install` 共用入口 |
| `runtime.py::bootstrap(include_optional=...)` | Bootstrap 默认不装 optional |
| `config/tools.yaml::installers` | 按名安装的工具定义(固定版本) |
| `config/recon.yaml::limits.stage_timeout_seconds` | provider/stage 超时预算 |
| `config/recon.yaml::stages` | 各阶段 required/optional providers |
