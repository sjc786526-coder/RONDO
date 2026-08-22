# Plan 056：方向 1 原生观测有界复测与首个候选决策

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/*.md` 为唯一来源。
>
> 本任务只完成真实测量和候选决策，不实施任何行为优化。执行者收到用户明确引用本计划、并包含 §3 所列真实
> API、50 USD、Docker 与任务内自主整改授权的一次性提示词后，才可进入真实执行。完成后只提交 Plan 056
> worktree；合并、推送和分支归档均等待用户另行批准。

## 1. 目标

### 最终目标

1. 从 Plan 051/v28 的同一冻结 10 题身份派生一个全新的方向 1 单侧测量任务，对 `mydev/` 被测对象串行执行两个
   完整 round，共 20 个正式 run；main 固定为 `gpt-5.6-terra/medium`，Guardian 固定为
   `gpt-5.6-terra/low`。
2. 唯一实验变量是为这 20 个 run 开启 Plan 052 已建立的原生 trace opt-in，并由 API metadata 与原生 trace
   生成 schema-v2 body-free 任务投影；产品默认路径和 agent 行为保持不变。
3. 在 20/20 完整测量成立时，依据两轮实际发生率与影响，在 C1、C2、C11 中最多选择一个首个行为优化候选；若
   无人满足门槛，正式确认“无候选”。C7 继续保持不可测。
4. 如果正式数据产生后发生不可恢复的完整性、预算或资源失败，则按冻结合同关闭为无效 campaign，诚实保存已产生
   的状态和费用，不替换 slot，也不另开第二个付费 campaign。

### 完成/验收标准

- [ ] 在首个真实请求前建立 Plan 056 独立 campaign、batch、task-budget、结果命名空间、方向 1 binary manifest
      和恰好 20 个正式 slot；它们不复用或改写 v28 的 campaign/run ID、预算、结果、账本或 active pointer。
- [ ] 新身份只复用 `eval/locks/p2-b7-canary-baseline-v28.json`（SHA-256
      `a9567cb0ddeaa9c8e7cdfbd7253000a8453ec1ebbb03ca359deae2c048f7880b`）所冻结的同一 10 题任务/镜像身份，
      不按成绩换题、补题或扩大样本。
- [ ] binary manifest 绑定实际执行的已提交 `mydev/` 源码、构建产物和产品身份；模型、effort、provider profile、
      deadline、价格快照、两轮顺序、schema-v2 与 50 USD task-budget 在正式边界前可复验。
- [ ] 正式数据前的 fake、fixture、schema、预算、默认零 API、Docker/runner 入口、投影和必要定向门禁通过；这些检查
      使用与正式命名空间隔离的测试资产，不误占正式 slot。
- [ ] 串行完成 10 题 × 2 轮共 20 个方向 1 run；不运行 Codex 对照、validation、holdout、条件补题、额外 round、
      E-A 或完整数据集。
- [ ] 每个正式 run 都形成唯一的 Terminal-Bench 任务终态、API metadata/费用状态、schema-v2 body-free 方向 1
      投影与可对应的资源记录。有效失败或 reward 0 保持原语义，不因成绩重跑。
- [ ] 20/20 投影通过 exact-schema、完整性、唯一性、来源一致性和 body-free 校验；原始 trace、prompt、响应和工具
      正文只留在规定的 ignored 私有工件中，不进入 Git、公共结果、日志或终端汇报。
- [ ] task-budget 覆盖本任务所有真实 API 请求、上游尝试和必要付费连接检查；最终累计不超过 `50.000000 USD`，
      reservation 与结算闭合，无法确定是否发送或余额不足时停止新请求。
- [ ] Docker 与 Windows `C:` 前后资源事实闭合，没有来源不明对象被清理；任务自建的临时对象要么按 exact identity
      精确清理，要么作为有说明的任务私有工件保留。
- [ ] 有效测量只输出“选择 C1/C2/C11 中一项”或“无候选”之一，并由冻结门槛、两轮分母、任务覆盖及失败/耗时
      影响支持；无效 campaign 不输出行为候选结论。
- [ ] 安排一次聚焦的独立验收，检查 20-slot 分母、观测三源一致性、body-free、预算与 Docker 记录、候选判定和
      Plan 054/055 隔离。普通 finding 由执行者窄修、重跑相关门禁并再次提交审查。
- [ ] 只同步受影响的 WBS、WBS-COMPLETED、日期冻结公共结果/审计快照、本计划当前状态和一份精炼 agent log；
      不在 README 或多份文档重复堆叠执行历史。
- [ ] 只运行受影响模块的相称测试与格式化/静态检查，不运行全 workspace、CI 或 PR。最终 Plan 056 分支已提交且
      worktree 干净；不合并、不推送、不归档。

## 2. 范围

### 允许修改

- `eval/rondo_eval/` 中与 Plan 056 独立身份、20-slot 单侧调度、预算/恢复、原生观测投影、聚合、结算、发布和
  精确清理直接相关的设施；`eval/tests/` 中对应定向测试，以及根 `justfile` 中必要的安全入口。
- `mydev/` 中仅与原生观测正确性直接相关的必要窄修及回归测试；必须继续保持观测默认关闭且产品行为不变。
- Plan 056 新增的 tracked campaign/lock、方向 1 binary manifest 引用、body-free 公共聚合结果，以及本任务直接
  相关的 `plan/`、方向 1/方向 0 WBS、WBS-COMPLETED、审计快照和一份精炼日志。
- 主仓库 common root 下 Plan 056 独占的 ignored `eval-data/` 运行资产、预算账本、bundle/manifest、原始运行工件、
  项目局部缓存和任务自建临时对象。命令仍从任务 worktree 发起，具体边界见 §5。
- 运行冻结 10 题所需的明确 Docker 镜像；缺失时可拉取，拉取和运行并发均为 1。普通项目依赖下载、定向构建、
  测试、格式化和静态检查也在本任务授权内。

### 不允许修改

- prompt、模型可见工具结果、compact、产品重试、Guardian、审批、调度、停止、sandbox、安全策略或其他 agent
  行为；不得实施 C1—C13 中任何优化，也不得恢复 E-A。
- `multidev/`、Publication Critic、Plan 054/055、训练资产、方向 2/3、冻结上游 `codex-source-code/` 或上游基线。
- v28 及其他历史 campaign、run、预算、账本、结果、active pointer、ignored 原始工件或来源不明 Docker/缓存对象。
- 冻结 10 题、模型、effort、provider、正式分母、round 数、候选门槛或 50 USD 上限；不得按成绩补题、补轮、
  替换 slot 或选择性重跑。
- Codex 对照、validation、holdout、额外 round、条件运行、完整 Terminal-Bench、本地模型、训练、云任务、上传、
  上游升级、全 workspace 测试、CI、PR、合并、推送或分支归档。
- 第二套 telemetry、数据库、常驻服务、通用调度平台、签名链，或本任务并不需要的复杂审计、可信、鉴权和严格
  因果证明设施。

### 不允许读取/查看

- `.env.local` 内容；只能按根 `AGENTS.md` 静默检查文件类型、非符号链接、`0600` 和任务所需变量存在且非空，
  并由既有严格 `KEY=VALUE` 数据加载路径向目标进程最小注入，禁止 `source`、搜索、打印、复制或记录其内容。
- Plan 055 worktree 中未提交的 `multidev/` 实现，以及 Plan 054/055 的任务私有、ignored 或未提交资产。
- validation/holdout 题目正文、solution、verifier、逐条结果，或任何非本次冻结 canary 的私有运行正文。
- 项目外个人文件、其他仓库、密钥/凭据和与 Plan 056 无关的 ignored 资产内容。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或得到某个候选结论而违反。

1. **输入与分母固定。** 只运行 v28 冻结的同一 10 题和 `mydev/` 单侧，按预先冻结顺序执行两个完整 round，正式
   分母恰为 20；main 为 `gpt-5.6-terra/medium`，Guardian 为 `gpt-5.6-terra/low`。不运行冻结 Codex，也不
   事后改变题目、镜像、模型、effort、deadline、round、slot 或顺序。
2. **身份全新且执行对象可复验。** Plan 056 必须有独立 campaign/batch/run/task-budget/active pointer/结果
   命名空间；v28 只提供冻结任务与镜像身份。正式 binary manifest 必须绑定实际已提交的方向 1 源码和产物，不能
   用旧 Local bundle、脏工作树或主机默认配置冒充任务身份。
3. **正式边界前允许自主收敛。** 首个真实 API 请求，或正式命名空间中首份非空 API metadata、trace、结果工件，
   以先发生者为准，固定 campaign 和 20 个正式 slot。在此之前，普通接线、依赖、fixture、schema、预算、Docker
   入口和启动问题可自主诊断、窄修并有界重跑；fake/fixture 必须使用隔离命名空间。
4. **正式边界后不得替换数据。** 尚能机械证明未发送请求的 pending slot 可安全恢复；已经发送请求的 slot 不得
   再发送、替换或用新 run ID 补位。只有能证明不会重复请求且继续使用同一冻结 slot/既有完整工件的恢复才可继续；
   无法证明请求是否发送或是否重复时立即停止新请求。已发送 slot 一旦被完整性检查判定为投影缺失、残缺、重复、
   schema 漂移、来源不一致或非 body-free，整包测量关闭为无效，不得重开第二个付费 campaign。
5. **只开观测，不改行为。** 20 个目标 run 显式开启 Plan 052 原生 trace 和 schema-v2 投影；其他路径保持默认
   关闭。opt-in 不得改变请求字节、模型上下文、工具调用/结果、审批、compact、重试、停止、调度或退出码。若
   opt-in 引入新的产品故障，关闭 opt-in 并保留默认行为；可以修复设施和回归测试，但不得自行启动第二个付费
   campaign。
6. **投影完整且严格 body-free。** 每个 slot 的 Terminal-Bench 终态、API metadata、原生 trace 和投影必须一一
   对应并通过既有 exact-schema/allowlist。completed response 缺可靠 usage 拒绝；failed/cancelled/aborted
   inference 缺 usage 时保留类型化终态并标为不可测，不伪造为 0。原始正文只留 ignored 私有区。
7. **预算是单一硬上限。** Plan 056 从 0 开始累计最多 `50.000000 USD`，涵盖正式 run、全部上游 attempts 和确有
   必要的付费连接检查；付费检查不进入 20-run 分母，也不得按成绩触发。可靠 usage 按正式请求前冻结的价格快照
   结算；能机械证明未发送记 `0 USD`；已发送但具体费用不可靠的每次上游尝试保守记 `1 USD`。每次发出下一请求前
   必须预留其最坏可记账费用，余额不足时不发送；进程、修复或 identity 不能重置预算。
8. **候选门槛固定。** C1/C2 只有两轮均出现、覆盖至少 2 个任务，并有观测证明真实遗漏/截断或重复调用耗时负担
   时才可入选；C11 出现影响任务的类型化 request/context failure 时可按严重性入选。多项满足时按任务覆盖、
   失败或耗时影响、行为风险排序且只选一项；无人满足则结论为“无候选”。C7 保持不可测，无效 campaign 不做候选
   推断。
9. **重型资源全局串行。** 重型 Cargo 必须使用根共享构建锁/看门狗；Plan 056 Docker/Terminal-Bench 必须与
   Plan 054 真实 tokenizer/本地模型加载推理、Plan 055 重型 Cargo 及任何其他重型任务互斥。Docker 只处理当前
   明确镜像/任务、并发 1；资源被占用时等待并推进轻量工作，不读取或修改其他任务现场。无法取得锁或可靠资源
   计数时不进入重型/付费阶段。
10. **Docker 资源门遵循根合同。** 运行前后记录 `docker system df` 与 Windows `C:` 实际余量；相对本任务基线
    新增 40 GB 告警、60 GB 主动停止，`C:` 低于 80 GiB 立即停止。不得用 WSL 虚拟余量替代；只清理本任务 exact
    identity/label 创建的对象，不清理来源不明镜像、容器、卷或 cache。
11. **普通故障自主处理，原则边界才停。** 编译/测试失败、短时锁占用、依赖/fixture/schema/runner 接线等可窄修
    问题，由执行者在范围内诊断、等待、修复并有界重跑，不因一次小问题请求人工。达到预算/资源硬停、正式 slot
    完整性失败、可能重复请求、需要改变固定输入或产品行为、读取禁止资产、进入未授权外部状态或大范围越界改造时，
    停止新请求、保存现状并报告。
12. **隔离与交付。** 所有 tracked 实现、测试和文档只在 Plan 056 worktree；主物理根只承担 §5 声明的 ignored
    I/O。不得读取/抄取 Plan 054/055 未提交内容，不 stash、回退、覆盖或删除未知修改。独立审查普通 finding 可由
    执行者自主窄修复验；最终只提交 Plan 056 分支，不合并、不推送、不归档。

## 4. 软性建议

以下内容基于 `main@a206fa3` 的实时代码和资产结构给出，不是固定实现路线。执行者可以根据代码、测试与实际复杂度
采用更小或更优方案，只要满足目标、硬约束和验收标准。

- 职责契合时优先复用现有 `BinaryManifest`/binary freeze、task budget、Docker supervisor、Terminal-Bench runner、
  `enable_local_harness_observation()`、结果 writer 与 `project_task_observation()`。Plan 051 的正式 runner 面向双侧
  A/A、A/B 和条件轮；若强行套用会扭曲 20-slot 单侧语义，可以在这些公共原语上新建一个窄的 Plan 056 orchestration，
  不必把本任务伪装成 schema-v7 公平比较 campaign。
- 可以提供 `initialize|prepare|preflight|run|resume|status|finalize` 一类稳定入口，也可采用同等清楚的更小状态机。
  重点是默认/无付费参数为零 API、同一入口可安全恢复、正式身份与预算不可被主机默认值替换，而不是固定命令名。
- 建议在首个付费请求前完成实现提交和 binary freeze，再建立/校验 20-slot identity。实现过程中可以有必要的任务内
  提交；不要为了单提交形式从脏源码构建正式 binary。
- 可以在每个 slot 发布后立即做投影与三源一致性检查，确认完整后再进入下一个 slot，以便尽早触发硬停。具体状态
  文件拆分、原子写入和恢复算法由执行者选择，不要求新建数据库或通用事务框架。
- paid connectivity check 默认不运行；确有必要时应在冻结身份和 task-budget 下作为明确的非正式 upstream attempt
  有界执行、完整记账，既不占 20 个正式 slot，也不成为补跑入口。
- 聚合器可直接在 schema-v2 安全字段上计算 C1/C2/C11 的两轮发生率、任务覆盖和影响；日期冻结结果只需让结论可
  复核，不需要保存正文、逐请求公开明细、签名链或额外严格因果系统。
- 定向测试宜覆盖：新身份不继承 v28 状态、恰好 20 个 Local slot、默认零 API、预算预留/0/1 USD 结算、pending
  恢复不重发、投影失败关闭、completed 缺 usage、body-free、候选门槛和终态清理。实际测试集合按真实改动收敛，
  不要求为未改模块增加重复测试。
- 独立验收聚焦正式分母、观测一致性、隐私边界、费用/资源闭合、候选门槛和并行任务隔离即可；不要求审查者为本
  任务再建设审计工具。审查窄 finding 修复后只重跑相关门禁。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已确认规划基线为 clean `main@a206fa33e84e1fdb8f661e997b5135aca384128c`，与 `origin/main` 一致。
- 已从该基线创建 `.claude/worktrees/056-direction1-bounded-observation`，分支
  `worktree-056-direction1-bounded-observation`。
- 已核对根/`mydev` AGENTS、README、顶层/方向 0/方向 1 WBS、数据布局、Plan 051/052、Plan 052 最终验收及当前
  运行/投影入口；确认 v28 lock digest 与 Plan 052 schema-v2 发布链。未读取 Plan 055 worktree 的未提交内容。
- 本 ExecPlan 已按当前代码与用户任务边界建立；规划阶段没有运行 Docker、Cargo、真实 API、本地模型或训练，没有
  创建/修改 ignored campaign、预算、run、bundle 或本机配置。

### 当前工作

ExecPlan 规划完成，等待用户把包含一次性授权的执行提示词交给执行者。正式 campaign、20 个 slot 与 50 USD
task-budget 尚未创建，任何真实 API 或 Docker 均未启动。

### 本任务剩余步骤

1. 在 Plan 056 worktree 中盘点并实现所需的独立 identity/runner/预算/投影/聚合能力，先完成无费用定向门禁。
2. 提交并冻结实际被测源码与 binary，创建新的 campaign/batch/task-budget/20-slot 身份，完成付费前检查。
3. 在共享资源空闲时串行执行两轮 20 个正式 run；逐 slot 保存、投影、核对、结算，并按冻结语义恢复或停止。
4. 对有效 20/20 数据执行候选判定，或对不可恢复失败关闭无效 campaign；同步必要结果、WBS、历史和精炼日志。
5. 完成一次独立验收；自主整改普通 finding 并重跑相关门禁，提交 Plan 056 分支并保持 worktree 干净。

### 阻塞项

当前无规划阻塞。执行时若 Plan 054/055 正在占用重型资源，应等待或先推进轻量工作；这不是代码失败，也不授权读取
或修改其现场。

### 当前验收状态

- 规划：完成；任务目标、硬边界、软建议、授权门和三种诚实终态已写入本计划。
- 实施/测量：尚未开始；20-slot identity、binary manifest、预算、Docker/API 证据与候选结论均待执行者落地。
- 未运行：格式化/测试、Cargo、Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、
  CI、PR。
- Git：Plan 056 worktree 的规划交付仅包含本计划；未合并、未推送、未归档。主工作区与
  Plan 052/053/055 worktree 未修改。

### 主工作区 ignored 资产

由于 `RepoPaths` 使用 Git common root 且 `/eval-data/` 被根 `.gitignore` 忽略，执行阶段以下 I/O 会由 Plan 056
worktree 中的命令发起、但物理上发生在主仓库 `/home/sjc/desktop/RONDO` 的 ignored 区或宿主 Docker 中：

- `eval-data/campaigns/`、`eval-data/budgets/`、`eval-data/runs/`、`eval-data/bin/rondo/`、`eval-data/build/`、
  `eval-data/work/` 等现有布局下的 Plan 056 独占 identity、账本、bundle、原始工件和临时对象；实际路径由既有
  布局与实现决定，但必须能由 Plan 056 exact identity 区分，不能复用或改写历史资产。
- 主物理根已有的 `eval/.venv` 与 `eval-data/uv-cache` 可作为项目局部共享环境/缓存使用；不修改全局 Python。
- `rondo.local.toml` 只可由既有配置路径读取任务所需的非密钥机器参数；若确需任务内非密钥调整，应避免覆盖并行
  任务配置并在最终报告说明。`.env.local` 仍绝对禁止打开，只能执行根 AGENTS 允许的静默门禁。
- Docker 镜像、容器、卷、网络与资源记录属于宿主运行状态，不随普通 worktree 隔离；只能创建/清理本任务明确
  标记的对象，并与其他重型任务串行。

执行结束必须单独报告上述区域实际发生的读取、创建、修改、保留和精确清理；规划阶段这些区域均未改动。任何 tracked
文件若被实现发现“只能在主工作区直接修改”，应停止并说明原因，不得绕过 worktree 纪律。

### 交接边界

- 本任务完成并通过独立复核后冻结本计划；候选实现或其他下游任务只交接到 WBS，不在本计划继续展开。
- 执行者最终只提交 Plan 056 分支并保持 worktree 干净；合并本地 `main`、推送 `origin/main` 和分支归档均等待用户
  另行批准。
- 后续获准合并时必须基于届时 `main` 保留已经进入主线的 Plan 054/055 状态，人工整合共享 WBS、WBS-COMPLETED、
  `justfile` 等冲突；不得用 Plan 056 的旧基线版本覆盖较新的主线事实。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 本任务只做同一 10 题、两轮、20 个 RONDO Local 正式 run | 当前目标是补齐方向 1 原生观测覆盖，不是重做双侧基线 | campaign、runner、结果 | 已采纳 |
| 002 | v28 只作为冻结题目/镜像身份来源，Plan 056 使用全新任务身份 | 防止历史 campaign、预算和结果被续写或混淆 | identity、预算、归档 | 已采纳 |
| 003 | Plan 056 独立预算硬上限为 50 USD，不增加 slot 或 round | 增加上游容错余量，同时保持实验分母不变 | 预算、运行 | 已采纳 |
| 004 | 正式边界后不替换已发送 slot，也不启动第二个付费 campaign | 避免用选择性重跑破坏固定测量 | 恢复、失败语义 | 已采纳 |
| 005 | 唯一变量是既有原生 trace + schema-v2 投影，默认产品行为不变 | 当前证据只授权测量，不授权行为优化 | mydev、eval | 已采纳 |
| 006 | C1/C2/C11 最多选一项；门槛无人满足就是“无候选”，C7 不补测 | 防止为推进方向 1 降低证据门槛或扩张任务 | 聚合、WBS | 已采纳 |
| 007 | 职责契合时复用现有设施；强行复用扭曲单侧语义时可新建窄能力 | 保持架构契合和设计干净，同时避免第二套体系 | eval 架构 | 已采纳 |
| 008 | ignored 运行资产位于 Git common root；tracked 交付只在 Plan 056 worktree | 适配现有 RepoPaths 和 `.gitignore`，同时保护主工作区 | 数据、Git | 已采纳 |
| 009 | Plan 054 本地模型、Plan 055 重型 Cargo 与 Plan 056 Docker 全局串行 | 遵守共享宿主资源门并保护并行任务现场 | 资源、排期 | 已采纳 |
| 010 | 本任务只提交工作树，不合并、不推送、不归档 | 用户保留最终集成批准权 | Git 交付 | 已采纳 |
