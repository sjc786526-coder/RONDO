# Plan 051：方向 0 首次 schema v7 正式 Canary 与稳定重跑入口

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/*.md` 为唯一来源。
>
> 用户已一次性授权本任务范围内的共享构建锁、精确镜像 Docker、真实 API、最多 400 USD 累计预算、
> 自主窄修、successor identity、无人值守连续运行和任务自有资源清理。执行阶段的原授权**不包含**把任务分支
> 合并到 `main` 或推送远端；最终验收通过后，用户已另行批准提交、合并、推送与分支归档，见决策 012。

## 1. 目标

### 最终目标

1. 在 RONDO Local 源码基线 `54f62e5f7e86a7ab0d4f8d788eafec7176809395` 与冻结 Codex CLI
   `v0.147.0`（commit `be6e8eac029b183056b7e4402879f15d2c85f61b`）上，使用同一冻结中转站、
   `gpt-5.6-terra`、双方 main 为 `medium` 且双方 Guardian 为 `low`，完成首次正式 schema v7 十题 canary，形成可归因、
   可结算、可归档的 RONDO Local 基线。
2. 在现有 `rondo_eval`、Terminal-Bench 与 `just` 设施上固化轻量稳定入口，使后续 Local 优化只需提供新的
   Local 源码/bundle、campaign identity、价格快照和当次预算，即可完成准备、运行或恢复、聚合、结算、清理、
   归档与相对上一正式基线的比较。

### 完成/验收标准

- [x] 新正式 identity 使用 campaign schema v7、全新 campaign/batch/run IDs，产品为 `rondo-local`；不继承或
      改写 v1—v22 的 continuation、结果、run ID、费用或预算余额。首个 identity 按现有编号应为 v23；若被设施
      缺陷阻断，后续使用顺延的新 identity。
- [x] RONDO 侧 manifest 精确绑定从 `54f62e5...` 构建并冻结的 Local runtime bundle；Codex 侧精确绑定
      `v0.147.0@be6e8eac...` 的已验证 runtime bundle。旧 `cb652e1...` Local bundle 不能作为本轮产品基线。
- [x] 10 个既有 canary、共享 catalog、task/image digest、两侧 main/Guardian 模型与 effort、provider profile、
      价格快照、deadline、task-major 顺序、三次严格多数合同及 400 USD 任务预算均在首个真实请求前冻结并可复验。
- [x] 无 API 阶段保持零真实请求、零费用：相关 focused tests 通过；仍有效的 Oracle proof 被复用，失效部分才重跑；
      十题双侧 stub preflight 串行通过，证明两侧生成相同的 Terra main-medium/Guardian-low 任务无关请求合同。
- [x] 正式序列完成 fresh wire canary、RONDO A/A 两轮、RONDO/Codex A/B 各一轮、所有差异题的条件加跑、严格多数
      聚合、结算、归档与清理；基础与条件运行均按任务交错执行，不运行 validation、holdout 或 E-A。
- [x] 每个 schema v7 identity 仍是最多 321 槽：1 个 wire 槽、40 条基础逻辑链、最多 40 条条件逻辑链，每条逻辑链
      最多 4 次 attempt。普通 provider、断流、超时、Docker、runner、resume、结算或归档故障可在既有 attempt、
      任务预算与安全边界内自动恢复；不因一次可窄修问题等待人工确认。
- [x] wire 的普通 provider/断流/超时在同一 wire 槽、任务预算与冻结合同内有界自动重试；每个已发送请求仍按计费
      三分法落账，不因一次瞬态失败直接废弃整个任务。合同、安全、预算或资源门失败继续 fail-closed。
- [x] 所有 identity 共用一个任务级 400 USD 累计预算。请求有可靠 usage 时按冻结 Terra 价格结算；已发送但无法获得
      可靠 usage/计费终态时本地任务账本记 `1.000000 USD`；能证明未发送时记 `0.000000 USD`。identity、进程、
      worktree 或代码窄修均不能重置累计费用，达到 400 USD 后不能再发送请求。
- [x] 已完成槽位在普通进程重启后不重复发送；未完成槽位可继续。已形成的有效产品结果不因分数不好而选择性重跑；
      只有原 campaign 因设施缺陷失效或冻结运行代码发生必要修复时，才以全新 successor identity 继续相应正式比较，
      且旧 identity、旧结果和旧费用保持只读。
- [x] 最终正式基线至少有 8 个共同有效任务，并输出 A/A 一致性、跨侧比较、方向性结果、`sigma`、`base_delta`、
      聚合 `delta`、条件题与双方多数结果。稳定差异、无差异或有效任务失败都如实保留，不为改善成绩重跑。
- [x] 每个请求都有可复算的结算类别和任务级累计；最终累计不超过 400 USD，所有 reservation 已结清，没有无法解释的
      running slot、活动 campaign lease 或本任务残留容器。非零供应商实际账单未知时继续记 `actual_usd=null`，
      `1 USD` 只表述为本地预算估算。
- [x] Docker 与 Windows `C:` 前后资源事实完整；稳定入口完成至少一次无 API 的准备、进程中断后恢复、终态归档/清理
      验证。默认调用或缺少明确 paid action 时不得意外发出真实请求；一旦在已授权 identity 上正式启动，应连续运行到
      campaign 终态或明确硬停。
- [x] 只运行受影响的必要测试，不运行全 workspace、CI 或 PR 流程；同步方向 0 WBS、WBS-COMPLETED、计划当前状态和
      一份精炼 agent log。任务 worktree 与必要的任务专用 results worktree 均提交且状态清楚，不合并 `main`、不推送。

## 2. 范围

### 允许修改

- `eval/rondo_eval/terminal_bench/` 中与 Local bundle 注入、schema v7 identity、wire、runner/resume、聚合、
  结算、清理和归档直接相关的现有实现。
- `eval/rondo_eval/api_budget_proxy.py` 及其他现有 eval 通用模块中与任务级累计预算、Terra profile、`1 USD`
  fallback 和稳定恢复直接相关的窄改动。
- `eval/tests/` 中对应 focused 回归、必要的 schema/fixture，以及根 `justfile` 中一个轻量统一入口。
- 新 campaign lock、active pointer、正式结果与聚合；`doc/WBS.md`、`doc/WBS/eval-benchmark.md`、
  `doc/WBS-COMPLETED.md`、本计划和一份精炼 `agent_log`。
- 项目专用 `.claude/worktrees/`：实现 worktree、冻结源码/构建用 detached measurement worktree，以及现有结果发布
  合同确实要求的任务专用 results worktree。它们只能服务 Plan 051。
- 主仓库 common root 下的 ignored 本地运行资产：`rondo.local.toml` 的本任务必要非密钥 profile/价格字段，
  `eval-data/` 内的 bundle、Oracle/preflight receipt、campaign state、预算账本、raw run 和任务自有临时对象。
  这些是工作树运行时共用的本地资产，不是 Git 交付物；具体边界见 §5“主工作区 ignored 资产”。

### 不允许修改

- `mydev/` 的 RONDO Local 产品行为、`multidev/` 的 RONDO Multi 产品行为或两份 Multi 三期研究稿。
- `codex-source-code/` 的内容、上游版本/commit、依赖版本或依赖锁；冻结 Codex bundle 只允许校验，校验失败时才按
  既有 v0.147.0 freeze 流程重建。
- v1—v22 的 lock/result/ledger/artifact/receipt/聚合及来源不明的现有 Docker、eval-data 或 worktree 资产。
- 10 个 canary 题集、基础轮数、三次严格多数、比较判据、Terra main-medium/Guardian-low、冻结 provider、产品行为或
  400 USD 上限。
- validation、holdout、E-A、完整 Terminal-Bench、本地模型、训练、上游升级、CI、PR 或新的测评/可信/签名/审计平台。

### 不允许读取/查看

- `.env.local` 内容；只能按根 `AGENTS.md` 静默验证 regular file、非 symlink、`0600` 与任务所需变量存在且非空，
  并由现有严格数据解析器最小注入目标子进程，禁止 `source`。
- 非 canary 的 validation/holdout 任务正文、solution、verifier、日志、单任务结果或其他私有数据。
- 与本任务无关的个人文件、其他仓库、本机密钥/凭据或来源不明的本地运行资产内容。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **比较输入固定。** 两侧均使用 `gpt-5.6-terra`；main 均为 `medium`，Guardian 均为 `low`；provider 保持执行启动时
   冻结的现有中转站 profile。正式数据开始后不得改变模型、effort、价格、provider、deadline、题集、顺序、
   重复合同或聚合公式。当前 ignored profile 仍激活 Sol/high，执行者必须在无 API 阶段通过显式任务选择或必要的
   最小本地配置调整完成 Terra main-medium/Guardian-low 切换，并由 tracked identity 冻结结果；不能把本机默认值
   当作已满足。冻结 Codex 的 Guardian 自动选择 `low` 是本轮明确合同，不得投影成 `medium`。
2. **产品与上游固定。** 本轮 Local 源码基线是 `54f62e5...`；评测设施后续提交不改变这个产品源码身份。
   当前 Local bundle 必须由该源码构建；冻结 Codex 只允许 `v0.147.0@be6e8eac...`，不做上游升级。
3. **公平合同固定。** 只运行既有 10 canary；基础形态为 RONDO A/A 两轮和 RONDO/Codex A/B 各一轮；按任务交错；
   基础 A/B 任一方向不同即触发该题每侧总观测数恰为 3，严格多数聚合；共同有效任务少于 8 不能称正式基线。
4. **任务级预算固定。** 本任务从 0 开始、累计最多 `400.000000 USD`，覆盖 wire、基础轮、条件加跑、所有
   provider/infra attempts 和所有 repair/successor identity。每个新请求必须由同一个任务级预算事实做 admission，
   不能只看当前 identity 的局部余额；identity 数量不设人为上限，但不能重置费用。
5. **计费三分法固定。** 可靠 usage 按首个正式请求前刷新并冻结的 Terra 价格计算；已发往中转站但 usage 或计费
   终态不可靠时恰记 `1.000000 USD`；能证明未发出时恰记 `0.000000 USD`。fallback 不冒充供应商账单，也不能
   抹掉请求已发送的事实。预算与槽位状态应在每次请求结束后尽快 durable 落盘。
6. **恢复允许有冗余但仍有界。** wire 普通 provider/断流/超时应在 wire 槽、任务预算与冻结合同内有界自动重试；
   每条任务逻辑链最多 4 个预冻结 attempt，不覆盖旧 run ID。普通瞬态故障、窄设施缺陷和进程中断应自主诊断、
   窄修、复验、恢复或建立 successor；不得沿用旧 Plan 020 的“同类小故障第二次即必须人工解锁”作为本任务常规
   停止条件。不得突破单链 attempt、321 槽、累计预算或安全硬停。
7. **结果不可挑选。** pass 与正常 reward 0/有效失败都是产品结果；不得因成绩不好删题、丢样本或重跑。
   设施缺陷使 identity 无效或运行代码必须窄修时，保留旧 identity 并以新 ID 重新开始必要比较；不得覆盖、回填或
   假装延续旧 identity。
8. **重型资源全局串行。** Cargo 构建必须走根共享 `scripts/with-build-lock.sh`（优先既有 `just`），并满足 cgroup、
   项目 180/195/200 GB 与 Windows `C:` 50 GB 构建门禁；Docker/Terminal-Bench 必须与 Cargo、本地模型和其他
   正式跑批互斥、单任务/单镜像、并发 1。拿不到锁或计数器时 fail-closed。
9. **正式 Docker 资源门禁。** 开始前后记录 `docker system df` 与 Windows `C:` 实际余量；本任务 Docker 新增
   40 GB 告警、60 GB 主动停止，`C:` 低于 80 GiB 立即停止。只清理由本任务 exact identity/label 明确创建的对象，
   不清理来源不明的镜像、容器、卷或 cache。
10. **默认不付费，授权后连续。** 稳定入口的默认动作、缺参和准备/检查路径都必须零真实请求；付费路径必须消费
    已冻结 identity 与明确 paid action。用户在本计划顶部的一次授权已覆盖本 campaign 及 successor，运行期间不因
    wire、provider、Docker、runner、resume、结算或归档的普通故障重复询问。
11. **只有原则性硬停才请求用户。** 达到 400 USD、中转站明确额度耗尽、资源看门狗/60 GB/80 GiB 门限触发、
    潜在秘密或非 canary 数据外发，或继续必须改变模型/effort/provider/题集/重复/判据/产品行为/上游版本，或进入
    validation、holdout、本地模型、训练等未授权范围时停止。停止前不得再发送请求，并保留可解释终态。
12. **Git 隔离。** 保留主工作区现有未推送提交和未跟踪 Multi 研究稿；不 stash、移动、覆盖或删除来源不明修改。
    实现和 tracked identity 在 Plan 051 worktree；结果发布若因现有合同必须使用 distinct results worktree，则该树也
    必须任务专用并从已提交 identity 派生。执行完成只提交相关 worktree；未经用户另行批准不合并 `main`、不推送、
    不归档分支。
13. **轻量实现。** 不建数据库、签名链、复杂可信/授权/审计设施或通用调度平台；不为了推测性问题大改框架。
    修复先以 focused 回归复现，尽量复用已有 budget proxy、Oracle、stub producer、runner、Docker supervisor、
    result/archive 和原子 JSON 状态。

## 4. 软性建议

以下内容基于当前代码给出，但不是固定实现路线。执行者可以依据复现、测试和实际运行采用更小或更优方案，只要满足
目标、硬约束与验收标准。

- 可为现有 successor 入口增加显式 Local runtime bundle 输入/manifest 校验，而不是从 v22 lock 复制旧 bundle；
  同时让 wire、preflight、paid worker 都只从新 identity 读取模型、effort、bundle 与 profile，清理生产路径中的
  Sol/旧 bundle 假设。历史 fixture 中用于验证旧 schema 的 Sol 字面量不必无差别清理。
- 跨 identity 预算可在现有 JSON ledger 上增加一个轻量“Plan 051 task envelope”，或实现等价的聚合 admission；
  最小可观测字段建议包含 `task_budget_id`、`cap_usd`、`spent_usd`、`reserved_usd`、identity/batch 引用、请求结算
  类别和 hard-stop 状态。不要求数据库或通用租户系统。
- `1 USD` fallback 可作为新的明确 settlement kind，并让结果/metadata 校验识别“已结算但 usage 不可靠”；若响应
  仍有完整可验证产品结果，可保留结果，若响应不完整则仍归 infra。不要把“usage 无效”与“任务结果无效”强行混成
  同一个判断。
- 统一入口可采用一个 `just` recipe 加 `prepare|run|resume|status|finalize` 动作，也可由一个窄 CLI 状态机承载；
  重点是默认安全、一次启动连续推进、同一入口可恢复，而不是固定命名或参数布局。
- 可以保留现有 bounded diagnosis 信息用于自动决策和日志，但普通外部瞬态无需人工命令解锁；识别为本地设施缺陷时
  先暂停新请求、窄修和无 API 复验，再创建 successor。更好的等价恢复策略可以替代这一建议。
- 优先复用仍匹配 task/source/image/runner/verifier/seccomp 的 Oracle proof；只有依赖漂移或验证失败的题才重跑。
- focused tests 至少覆盖：显式当前 Local bundle、Terra main-medium/Guardian-low 全链投影、wire 瞬态有界自动重试、任务预算跨
  successor 不清零、1/0 USD 三分法、崩溃恢复不重复发送、普通 infra 自动进入下一 attempt、有效结果不选择性
  重跑、默认入口零 API、终态清理。
  可按实际改动增减测试文件，不要求重跑整个 `eval-test`，除非执行者判断本次集中改动已达到阶段级全量门槛。
- 建议先提交可执行 harness，再生成并提交正式 identity；随后从该提交派生 distinct results worktree。最终结果分支可在
  审查前保持单独提交，不需要为方便审查擅自合并回 `main`。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已从 `main@54f62e5` 创建 `.claude/worktrees/051-direction0-schema-v7-canary`，分支
  `worktree-051-direction0-schema-v7-canary`；创建时主工作区比 `origin/main` 超前 1 个提交，仅有两份未跟踪
  Multi 三期研究稿，没有其他登记 worktree。
- 规划期间外部并行任务将主工作区推进到 clean `main@9bd38fc` 并与 `origin/main` 对齐；Plan 051 未参与该提交，
  worktree 仍按用户要求冻结在任务启动点 `54f62e5`，未 rebase、merge 或覆盖并行结果。
- 已核对 Plan 020/021、方向 0 WBS、schema v7 实现、现有 `just` 入口与相关测试。active pointer 为
  `null`，最高历史 identity 是 v22/schema v6，现有 321 槽与公平比较设施可复用。
- 已确认执行前的真实缺口：successor 继承旧 `cb652e1...` Local bundle；若干 wire/诊断/batch 路径仍含 Sol 或旧
  effort 假设，wire 外层 `max_retries=0`；v7 identity 当前把 prior 置零；未知 usage 按完整 reservation 结算；
  旧诊断门会让普通同类 infra 等人工处理；尚无贯通 freeze/identity/preflight/run/resume/archive 的稳定入口。
- 只读解析确认主仓库 ignored `rondo.local.toml` 已定义 Terra 价格快照（2026-08-21），但 active main/Guardian
  仍为 Sol/high；`.env.local` 仅检查为 regular file、`0600`，未读取内容。
- 用户在执行中明确修订 effort 合同：双方主模型保持 `medium`，双方审批模型/Guardian 改为 `low`；实现与测试已按
  该合同投影，不修改冻结 Codex 上游逻辑。
- 已从 clean detached `54f62e5...` 源码经共享构建锁和看门狗冻结并完整复验新的 Local runtime bundle；现有
  Codex `v0.147.0@be6e8eac...` bundle 自包含校验通过，因此未重建上游。
- schema v7 显式 bundle、Terra effort 投影、wire 有界重试/恢复、跨 identity 400 USD envelope、1/0 USD fallback
  与稳定入口已落地。外部独立验收随后发现入口仍把首次 Local commit/Plan 051 envelope 固定在 loader 中；整改后
  `just eval-plan051 initialize|prepare|preflight|run|resume|finalize|compare` 已贯通显式 campaign/batch、新 Local
  commit/manifest、价格日期和独立任务预算。Plan 051 保留历史预算路径，后续授权按 task-budget ID 使用新文件，不能
  覆盖或继承本轮余额；默认入口仍为 idle 且零请求。
- 依次冻结并关闭 v23—v28 六个 identity：v23—v26 在零 API 阶段暴露并关闭本地 preflight/runner 适配缺口；
  v27 的十题双侧 stub preflight 通过，正式 wire 与首个 RONDO 槽可靠结算后暴露 schema v7 结果发布缺口，按
  无新请求恢复路径结算 `$0.270445` 并保持旧结果只读；修复后由全新 v28 接续。
- v28 的 20 个 stub side、10 份 receipt 全部通过，随后正式完成 wire、RONDO A/A 两轮以及 RONDO/Codex A/B
  各一轮。40 个产品槽全部有效，400/400 个上游 attempt 均有可靠 usage；没有基础差异题，故冻结的条件槽保持
  未激活，不作选择性加跑。
- v28 正式聚合为 `passed`：10/10 个共同有效任务，Local 三轮观察均为 5/10，Codex A/B 为 5/10；
  `sigma=0`、`base_delta=0`、`delta=0`，A/A、cross-side 与 directional 三层均通过。成功题为 `fix-git`、
  `headless-terminal`、`sanitize-git-repo`、`sqlite-db-truncate`、`vulnerable-secret`，其余五题双方均为有效失败。
- v27 费用 `$0.270445`，v28 本 identity 费用 `$9.142443`（含 wire `$0.116195`），Plan 051 任务累计
  `$9.412888`；`actual_usd=null`，任务 envelope 已关闭且无 active identity，剩余 `$390.587112`，未命中硬停。
- 正式聚合与 40 条 result 已发布到任务专用 results worktree。Docker 前后均为 26 images / 11.5 GB、0
  container、0 volume、0 build cache，VHDX 前后均为 `69,467,111,424` bytes；campaign 记录的 Windows `C:`
  可用空间为 `183,926,632,448 -> 183,749,709,824` bytes，收尾独立读数为 `183,738,654,720` bytes。

### 当前工作

实现、无 API 预检、正式 API、聚合、结算、结果发布与资源清理均已完成。任务内首次干净上下文审查发现并促成修复
active pointer；外部独立验收提交 `de2cc24` 又发现稳定重跑入口仍固定首次 Local/预算，以及合法 `failed` 会在闭合前
返回 2。首轮整改把新任务输入与稳定合同分离，并补上显式 `finalize` 收口与相对比较；第二次验收提交 `8b43a0c` 进一步
发现 `run`/`resume` 没有自动复用收口，且 blocked 会误入相对比较器。两项控制流均已窄修：passed/failed 的正式启动与
恢复入口共用同一预算/pointer 终态，blocked 保持 3/successor 且不生成 comparison；v28 的 tracked public baseline
字节不变。第三次验收提交 `2683336` 又定位到 envelope close 与 pointer retire 之间的中断窗口，以及正式终态/退出码
错配可能返回成功；`finalize` 现会在 runner 前直接恢复已闭合 identity，所有错配均明确失败。相关 9 模块 362/362
通过；最终独立验收提交 `afb9021` 另以 32/32 个入口相关用例复核正常、blocked、closed-envelope 恢复、预算隔离与
相对基线，结论为 `PASS`，无剩余 correctness/functionality finding。

### 本任务剩余步骤

无。任务目标和独立验收均已完成，本计划随交付冻结为历史合同；后续 Local 优化或新 baseline 只由 WBS 重新排期。

### 阻塞项

当前无计划层阻塞。执行时若命中 §3.11 的原则性硬停，本任务保持 blocked 并带上累计费用、最后安全状态和继续所需的
唯一用户决策；普通窄故障不列为用户阻塞。

### 当前验收状态

- 实现与无 API 定向门禁：整改完成；相关 9 模块 Python 回归 362/362（含新任务 budget/identity、统一入口、
  run/resume/finalize 的 passed/failed 终态、闭合后恢复、退出码错配、blocked、相对基线、pair/results 与历史 v28 loader）通过。语法编译与
  diff whitespace 在最终提交前复验；
  全 workspace、CI、PR、validation/holdout 均未运行。
- Docker/stub 与正式 API：完成；v28 为有效正式基线，所有有效 pass、reward 0 与任务失败均原样保留。
- 预算、归档与清理：完成；任务累计 `$9.412888`，无 active identity、running slot、容器、volume 或任务网络。
- Git：v23—v28 lock、raw result、ledger 与 tracked public baseline 保持只读；本轮只新增正式结果、派生 comparison
  和入口整改。最终验收后用户已授权把 execution/results 提交合并到 `main`、推送 `origin/main` 并归档本地分支。
- 独立审查：任务内与外部独立审查发现的 active pointer、稳定重跑输入、failed/blocked 终态及崩溃恢复 finding 均已
  窄修并复验；最终报告为 `agent_log/2026-08-21-174146-plan051-final-independent-acceptance.md`，结论 `PASS`。

### 主工作区 ignored 资产

以下路径因根 `.gitignore` 和 `RepoPaths.common_root` 设计，只存在于主仓库物理根
`/home/sjc/desktop/RONDO`，不会复制进普通 worktree。相关命令仍应从 Plan 051 worktree 发起，tracked 代码与
identity 仍落在任务树；这里只说明必要的本地共享 I/O：

- `.env.local`：只能由严格 loader 静默校验和最小注入；不编辑、不打开、不输出。
- `rondo.local.toml`：稳定入口会从 common root 读取其中现有中转站与 Terra 价格。若实现能显式选择已有 Terra alias，
  无需改 host-wide active model；若现有 loader 确实要求，则只做本任务必要的非密钥 profile/价格最小调整。
  两种路线都必须冻结价格/profile digest，不改变中转站身份，不写入 key。
- `eval-data/`：新 Local bundle、既有/新 Codex bundle、Oracle proof、stub receipt、task-level budget、campaign
  state、raw artifacts 与临时对象按现有布局写在这里；只清理 Plan 051 明确创建的临时对象。
- `eval/.venv`：worktree 内不复制 ignored 虚拟环境；现有 `just`/`uv --no-sync` 入口继续使用 common root 的共享
  eval 环境与 `eval-data/uv-cache`，不修改全局 Python 环境。
- `codex-source-code/`：只读核对上游 catalog/source；不能修改。冻结上游构建继续使用既有隔离 scratch 流程。

这不授权在主工作区修改 tracked 文件，也不授权触碰两份未跟踪 Multi 研究稿。若现有结果发布器要求 distinct results
worktree，那是 tracked result 的既有架构要求，不是把结果直接写入主工作区；该辅助树必须任务专用并单独提交。

### 交接边界

- 本任务完成并通过独立审查后冻结本计划。用户已另行批准合并本地 `main`、推送 `origin/main` 与归档分支。
- 后续 Local 内核优化与新基线重跑只由 WBS 重新排期；不在本计划追加下游路线。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 首次正式比较固定 Local `54f62e5...` 与 Codex `be6e8eac...` | 用户要求以执行开始时当前 Local 和同一冻结上游形成基线；避免评测设施提交漂移产品身份 | bundle、identity、结果 | 已采纳 |
| 002 | 不另跑付费 pilot，三次严格多数在正式数据前冻结 | 用户已给出重复合同；额外 pilot 只增加成本与服务端时间漂移 | comparison、预算 | 已采纳 |
| 003 | 400 USD 是跨全部 identity 的任务预算，不是每个 campaign 的 cap | repair/successor 不得通过换 ID 清零费用 | identity、budget proxy、结算 | 已采纳 |
| 004 | 普通故障保留最多 4 attempt 的有界冗余，identity 数量不设人为上限 | 兼顾无人值守恢复与槽位/预算安全；纠正旧合同对窄故障过早停机 | runner、resume、successor | 已采纳 |
| 005 | 统一入口默认零 API，显式 paid 后持续到终态或硬停 | 防止误付费，同时避免每个普通错误重复等待人工确认 | just/CLI、运行状态机 | 已采纳 |
| 006 | 允许现有发布合同所需的 task-owned distinct results worktree | 当前 baseline 明确拒绝把 tracked 结果写回执行 harness checkout；保持 clean harness 与 durable 发布 | worktree、结果提交 | 已采纳 |
| 007 | 执行和审查阶段只提交任务 worktree，不合并或推送 | 用户对执行阶段给出的 Git 边界优先于任务原稿中的最终交付条目 | Git 交付 | 执行阶段已采纳；交付时由 012 覆盖 |
| 008 | 双方 main 固定 `medium`，双方 Guardian 固定 `low` | 用户在执行中明确修订原 main/Guardian 均为 medium 的合同；冻结 Codex 本身也会为 Guardian 选择 low | provider projection、identity、preflight、wire、正式运行 | 已采纳 |
| 009 | 后续正式 baseline 用显式 Local commit/manifest、campaign/batch、价格日期和新 task-budget ID/cap 初始化 | 每次运行输入不能固化为首次 Plan 051 常量；新授权不得覆盖或复用已关闭的 400 USD envelope | loader、identity、task budget、统一入口 | 已采纳 |
| 010 | 相对基线从同一 results worktree 自动选择最新兼容 schema v7 正式结果，首轮输出 `first_formal_baseline` | 比人工传入前驱路径更小且可避免选错；独立文件不改历史 tracked public baseline 字节 | aggregate、results、compare | 已采纳 |
| 011 | `finalize` 在进入 runner 前恢复已闭合 envelope 的 pointer，并严格匹配终态/退出码 | envelope close 与 pointer retire 是两个原子步骤，必须能从中间中断恢复且不能误报成功 | formal entry、crash recovery | 已采纳 |
| 012 | 最终验收通过后提交文档、合并 execution/results 到本地 `main`、推送 `origin/main` 并归档分支 | 用户在最终验收后另行明确授权交付 | Git 交付 | 已采纳 |
