# Plan 056：方向 1 原生观测有界复测与首个候选决策

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/*.md` 为唯一来源。
>
> 本任务只完成真实测量和候选决策，不实施任何行为优化。执行者收到用户明确引用本计划、并包含 §3 所列真实
> API、累计 100 USD、Docker 与任务内自主整改授权的一次性提示词后，才可进入真实执行。完成后只提交 Plan 056
> worktree；合并、推送和分支归档均等待用户另行批准。

## 0. 2026-08-22 追加与变更授权

用户在 v1 已按原合同关闭为无效 campaign 后追加授权；本节与原授权共同生效，冲突时以本节为准，未修改的安全、
资源、模型、题目、禁止事项和交付边界继续有效。

- v1 的 invalid 终态、`0.631065 USD`、原始工件和公共无效结果永久保留，但不再代表整个 Plan 056 任务失败。
- Plan 056 累计真实 API 硬上限从 50 USD 提高为 `100.000000 USD`。v1、所有真实 rehearsal、诊断性付费运行、
  main/Guardian attempts、必要连接检查和后续正式 campaign 共同计入同一累计上限；进程、identity、预算文件或
  campaign 重启不得归零。
- 允许开发性 rehearsal 使用同一冻结 10 题逐步扩展覆盖；进入最终正式测量前，至少连续完成一次完整 10 题单轮
  rehearsal，并核对运行、观测、投影、费用结算和资源收尾。rehearsal 请求计费但不进入正式分母，也不能替换
  正式 slot。
- 取消“发生正式数据后不得启动第二个付费 campaign”的限制。可修复的实现、runner、Docker、预算、trace、投影、
  schema、归档、恢复、测试或发布问题应先如实关闭受影响 campaign，修复并回归，然后以全新 identity 从第一题
  干净重启；同一 campaign 内已发送 slot 仍不得直接重发或替换。
- 完整 rehearsal 后提交并冻结实际源码，重新构建正式 binary manifest，再创建全新的 campaign/batch/run/预算
  子身份和结果命名空间，执行固定两轮、恰好 20 个正式 run。旧 v1、rehearsal 和无效 campaign 均不得混入分母。
- reward 0、任务正常失败、无候选或表现不理想只要终态/usage/trace/投影完整，就是有效结果而非重跑理由。首个
  可信 20/20 campaign 即为最终测量并停止付费运行。
- 任务只在累计 100 USD 达限、资源硬门、无法在授权范围内修复的完整性/原则问题，或需要改变固定实验条件/产品
  行为时彻底失败。最终仍须完成干净上下文独立只读验收，真实 finding 影响数据可信度时废弃对应 campaign 并在
  余额内干净重跑，直至通过或触发上述终止条件。

## 1. 目标

### 最终目标

1. 从 Plan 051/v28 的同一冻结 10 题身份派生一个全新的方向 1 单侧测量任务，对 `mydev/` 被测对象串行执行两个
   完整 round，共 20 个正式 run；main 固定为 `gpt-5.6-terra/medium`，Guardian 固定为
   `gpt-5.6-terra/low`。
2. 唯一实验变量是为这 20 个 run 开启 Plan 052 已建立的原生 trace opt-in，并由 API metadata 与原生 trace
   生成 schema-v2 body-free 任务投影；产品默认路径和 agent 行为保持不变。
3. 在 20/20 完整测量成立时，依据两轮实际发生率与影响，在 C1、C2、C11 中最多选择一个首个行为优化候选；若
   无人满足门槛，正式确认“无候选”。C7 继续保持不可测。
4. 可修复设施问题导致 campaign 无效时保留其状态与费用，修复后以全新 identity 干净重启；达到首个可信 20/20
   后停止。只有累计预算、资源硬门、不可修复完整性或原则边界才构成整个任务的失败终态。

### 完成/验收标准

- [ ] 在完整 10 题单轮 rehearsal 通过后，为最终测量建立全新的 campaign、batch、预算子身份、结果命名空间、
      binary manifest 和恰好 20 个正式 slot；不得复用或改写 v1/rehearsal/v28 的身份、结果或工件。
- [x] 新身份只复用 `eval/locks/p2-b7-canary-baseline-v28.json`（SHA-256
      `a9567cb0ddeaa9c8e7cdfbd7253000a8453ec1ebbb03ca359deae2c048f7880b`）所冻结的同一 10 题任务/镜像身份，
      不按成绩换题、补题或扩大样本。
- [ ] 最终 binary manifest 绑定 rehearsal 后实际提交的 `mydev/` 源码、构建产物和产品身份；模型、effort、provider
      profile、deadline、价格快照、两轮顺序、schema-v2 与累计 100 USD task-budget 在正式边界前可复验。
- [x] fake/fixture/定向门禁通过，并至少连续完成一次真实 10 题单轮 rehearsal；其 identity、工件和费用与最终正式
      命名空间隔离，不误占正式 slot。
- [ ] 串行完成 10 题 × 2 轮共 20 个方向 1 run；不运行 Codex 对照、validation、holdout、条件补题、额外 round、
      E-A 或完整数据集。
- [ ] 每个正式 run 都形成唯一的 Terminal-Bench 任务终态、API metadata/费用状态、schema-v2 body-free 方向 1
      投影与可对应的资源记录。有效失败或 reward 0 保持原语义，不因成绩重跑。
- [ ] 20/20 投影通过 exact-schema、完整性、唯一性、来源一致性和 body-free 校验；原始 trace、prompt、响应和工具
      正文只留在规定的 ignored 私有工件中，不进入 Git、公共结果、日志或终端汇报。
- [ ] task-budget 覆盖 v1、全部 rehearsal/诊断、所有正式 campaign、上游尝试和必要付费连接检查；最终累计不超过
      `100.000000 USD`，
      reservation 与结算闭合，无法确定是否发送或余额不足时停止新请求。
- [ ] Docker 与 Windows `C:` 前后资源事实闭合，没有来源不明对象被清理；任务自建的临时对象要么按 exact identity
      精确清理，要么作为有说明的任务私有工件保留。
- [ ] 首个可信 20/20 只输出“选择 C1/C2/C11 中一项”或“无候选”之一，并由冻结门槛、两轮分母、任务覆盖及失败/耗时
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
- 使用冻结 10 题进行隔离的开发性 rehearsal；允许从少量代表 slot 扩大到完整单轮，并在可修复设施问题后创建
  新的 rehearsal 或正式 campaign。所有真实请求计入同一 100 USD envelope。

### 不允许修改

- prompt、模型可见工具结果、compact、产品重试、Guardian、审批、调度、停止、sandbox、安全策略或其他 agent
  行为；不得实施 C1—C13 中任何优化，也不得恢复 E-A。
- `multidev/`、Publication Critic、Plan 054/055、训练资产、方向 2/3、冻结上游 `codex-source-code/` 或上游基线。
- v28、v1 及其他历史 campaign/run/结果/ignored 原始工件；预算只允许按追加授权单调扩容和续接，不得覆盖历史费用。
- 冻结 10 题、模型、effort、provider、每个正式 campaign 的 20-run 分母、round 数或候选门槛；不得按成绩补题、
  补轮、替换 slot 或选择性重跑。
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
3. **先 rehearsal，再正式冻结。** 允许从少量 slot 开始开发性真实 rehearsal，并至少连续完成一次 10 题单轮；
   所有费用累计但数据不进入正式分母。完整 rehearsal 后提交源码、重新构建 manifest，并为正式 20-run 建立全新
   identity；fake、rehearsal、无效和正式命名空间必须隔离。
4. **正式边界后不得替换数据。** 尚能机械证明未发送请求的 pending slot 可安全恢复；已经发送请求的 slot 不得
   再发送、替换或用新 run ID 补位。只有能证明不会重复请求且继续使用同一冻结 slot/既有完整工件的恢复才可继续；
   无法证明请求是否发送或是否重复时立即停止新请求。已发送 slot 一旦被完整性检查判定为投影缺失、残缺、重复、
   schema 漂移、来源不一致或非 body-free，当前 campaign 关闭为无效；修复后只能用全新 identity 从第一题重启，
   不能把修复前后的数据混入同一个分母。
5. **只开观测，不改行为。** 20 个目标 run 显式开启 Plan 052 原生 trace 和 schema-v2 投影；其他路径保持默认
   关闭。opt-in 不得改变请求字节、模型上下文、工具调用/结果、审批、compact、重试、停止、调度或退出码。若
   opt-in 引入新的产品故障，关闭 opt-in 并保留默认行为；可以修复设施、回归并启动全新 rehearsal/正式 campaign，
   但不得改变产品行为。
6. **投影完整且严格 body-free。** 每个 slot 的 Terminal-Bench 终态、API metadata、原生 trace 和投影必须一一
   对应并通过既有 exact-schema/allowlist。completed response 缺可靠 usage 拒绝；failed/cancelled/aborted
   inference 缺 usage 时保留类型化终态并标为不可测，不伪造为 0。原始正文只留 ignored 私有区。
7. **预算是单一硬上限。** Plan 056 从 v1 的 `0.631065 USD` 继续累计，所有 v1/rehearsal/诊断/正式 campaign、
   main/Guardian attempts 和必要连接检查合计最多 `100.000000 USD`；非正式请求不进入 20-run 分母，也不得按
   成绩触发。可靠 usage 按请求前冻结的价格快照
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
    问题，由执行者在范围内诊断、等待、修复并重跑，不因一次小问题请求人工。单个 campaign 的正式 slot 完整性
    失败或可能重复请求时先停止并关闭该 campaign；修复后可新建 identity。只有预算/资源硬停、需改变固定输入或
    产品行为、读取禁止资产、进入未授权外部状态或无法修复的原则问题才停止整个任务。
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
- 已提交 Plan 056 orchestration、每 attempt 未定价兜底、20-slot 状态机、单 slot 恢复边界、body-free 发布和
  17 项直接回归；实现基线为 `2765ff8f82ce21262af46bdf93a62c75b381b631`。
- 已从该 clean source 构建并复验 RONDO Local runtime bundle：CLI SHA-256 `7d960131...016f`、code-mode host
  `5b9dcd88...afb6`、bwrap `77360cb7...2c4c`。campaign lock 为 `e3b7c3ea...14dd`，固定 v28 同一 10 题、
  round-major 20 slot、Terra medium/low 和 50 USD task budget。
- 10/10 零 API Docker/Harbor 预检完成。正式 campaign 发布 `r01-t01-db-wal-recovery` 后，
  `r01-t02-extract-elf` 已发送但在 schema-v2 投影时触发 `rollout trace lifecycle is incomplete`；状态机按合同将
  整包标记 `sent_slot_execution_or_projection_failed`，未继续剩余 18 slot，也未补跑或另开 campaign。
- finalizer 已发布日期冻结 body-free invalid 结果，关闭 task budget 与 active pointer。总计 25 次上游尝试、
  `0.631065 USD`、reservation 0；正式分母仍为 20，发布 1，候选推断为 null。
- 实测暴露的两个设施问题已窄修：持久化预算的只读 totals 汇总，以及 runtime-end 晚于 tool-end 时 Team Lens 的
  假阴性。后者只读重放第 2 题私有 trace 后 terminal availability 为 available，但已经关闭的无效 campaign
  不回滚。相关 Python 定向集合 69/69 通过。
- 追加授权后的 rehearsal-v2 已从第一题干净启动：前 2 题完整发布且第 2 题通过 v1 的旧投影故障点；第 3 题请求与
  Terminal-Bench trial 已完成，但收尾时 Docker 实时事实命令连续两次失败，因而按合同关闭为 invalid，未发送后续
  7 题。v2 固定 34 attempts、`0.569748 USD`，Plan 056 累计 `1.200813 USD`，reservation 0；公共无效结果、
  原始工件和资源收尾均保留。
- Docker 失败没有触发容量/增长门，也没有遗留 Plan 056 容器、网络或卷。设施窄修保留实时、fail-closed 采样，
  仅允许调用方设置有界 sample 总时限和只读命令重试次数；Plan 056 使用 60 秒、最多 4 次，其他调用方默认仍为
  30 秒、2 次，并增加对应回归。
- rehearsal-v3 以全新 identity 完成 10/10 零 API preflight，并从第一题干净运行。前 3 题完整发布，第 4 题
  请求与 trial 完成后被 projector 判定 terminal runtime metadata 不完整，campaign 因已发送 slot 立即关闭，
  后 6 题未发送。v3 固定 52 attempts、`0.842369 USD`，Plan 056 累计 `2.043182 USD`，reservation 0；公共
  body-free 无效结果、原始工件和资源收尾均保留。
- v3 第 4 题的只读复投影定位到一个 `exec_command` 在 sandbox open 阶段被拒绝：产品按既有语义返回完整
  code-mode terminal result，但此时尚不存在原生 process runtime begin/end。projector 已窄化为只接受这一个
  机械完整形态，普通缺失、单侧 runtime、`write_stdin` 或不完整 result 仍 fail-closed；v3 原 trace 离线复投影
  已得到合法 schema-v2 body-free 聚合。
- v3 全 campaign Docker 与 VHDX 增长均为 0，Windows `C:` 余量未触发硬门，最终没有 Plan 056 容器、网络、卷
  或 build cache；采样重试链在 v2 的旧故障点及 v3 后续收尾均成功。
- rehearsal-v4 完成 10/10 零 API preflight 和连续 10 题真实单轮；10 个 slot 均完成来源复验与发布，其中
  Terminal-Bench 6 pass/4 fail，属于有效 rehearsal 结果而非重跑理由。v4 固定 111 attempts、`1.970204 USD`，
  Plan 056 累计 222 attempts/`4.013386 USD`，reservation 0；结果为 `rehearsal_complete`，不执行候选判断。
- v4 Docker/VHDX 增长均为 0，10 份 slot receipt 完整，Windows `C:` 从 193,259,507,712 降至
  192,947,449,856 bytes，最终没有 Plan 056 容器、网络、卷或 build cache。执行中两次遇到并行重任务短时持锁，
  均等待后继续，没有修改并行任务现场。
- 首次 v4 finalize 暴露 finalized outcome allowlist 遗漏 `rehearsal_complete`；公共聚合已经有效，状态机在写 final
  state 前 fail-closed。mode-aware allowlist 和回归已补齐，同一 campaign 离线幂等 finalize 成功，没有新请求。
- formal-v5 绑定提交 `c2be21d01ae34c971b9f75334b265191bce0acbd`，使用重新构建的静态 RONDO Local
  legacy/companion/runtime bundle；10/10 零 API preflight 完整。正式运行前 3 个 slot 完整发布，第 4 个 slot
  已开始上游尝试但未获得 HTTP 响应，旧 body-free metadata 没有表达这个生命周期终态，projector 按严格合同拒绝，
  campaign 因而关闭为 invalid，后 16 个 slot 未发送。v5 固定 42 attempts、`1.637680 USD`，Plan 056 累计
  264 attempts/`5.651066 USD`、reservation 0；公共无效结果、原始工件和资源记录均保留。
- v5 失败只读诊断确认不是 SSE 终态枚举漂移，而是 transport open 在响应头前失败。设施修复新增精确
  `stream_end_kind=open_error`，只允许 `status=0`、无 usage 和无 terminal event 的已开始尝试；旧 v5 缺字段仍被
  拒绝，不能离线复投影或恢复。非 SSE 响应另以 `non_sse` 明确分类。预算代理、投影器与正负回归正在以 formal-v6
  新 identity 收口。

### 当前工作

v1、rehearsal-v2、rehearsal-v3、完整 rehearsal-v4 与无效 formal-v5 均已按真实终态关闭并保留。当前正在完成
`open_error` 设施修复与定向回归，随后提交并冻结新源码、重建 binary manifest 并创建 formal-v6；新的正式
20-run 将从第一题以全新 identity 干净启动，费用从 `5.651066 USD` 单调累计。

### 本任务剩余步骤

1. 提交并冻结包含 `open_error` 修复的源码，重新构建 binary manifest，创建全新 formal-v6 campaign 并完成
   10/10 零 API preflight。
2. 从第一题串行执行固定两轮 20/20；首个可信 20/20 形成候选或“无候选”结论后停止付费运行。
3. 同步公共结果、累计费用、资源、WBS、WBS-COMPLETED 和精炼日志。
4. 完成上下文干净的独立只读验收；整改真实 finding，必要时废弃受影响 campaign 并在余额内干净重跑。
5. 提交 Plan 056 最终分支并保持 worktree 干净；不合并、不推送、不归档。

### 阻塞项

无阻塞。v1 不可续发或改写；新请求只能属于追加授权后的 rehearsal 或全新正式 identity，并继续遵守共享资源锁。

### 当前验收状态

- v1：invalid 并永久保留；20 固定 slot 中 1 个发布、第 2 个已发送后完整性失败、18 个未启动；25 attempts、
  `0.631065 USD`、无候选结论。
- 设施整改：只读预算 totals、Team Lens 合法事件交错、Plan 056 Docker 事实采集的有界瞬时恢复，以及合法
  pre-runtime sandbox denial 的投影均已窄修并通过定向回归；v2/v3 分别结算 34/52 attempts、
  `0.569748/0.842369 USD`；v4 完整 10/10 为 111 attempts/`1.970204 USD`，累计 `4.013386 USD`。
- formal-v5：invalid 并永久保留；20 固定 slot 中 3 个发布、第 4 个已发送后因响应前连接失败缺少可投影终态而
  关闭、16 个未启动；42 attempts、`1.637680 USD`、无候选结论。累计 264 attempts/`5.651066 USD`。
- 最终测量：完整单轮 rehearsal 已通过；`open_error` 窄修、formal-v6 binary 复冻和可信 20/20 待完成；最终独立
  验收待完成。
- 未运行：Codex 对照、validation、holdout、E-A、完整数据集、全 workspace、CI、PR、本地模型、训练、云任务或上传。
- Git：只在 Plan 056 worktree 提交；未合并、未推送、未归档，未读取或修改 Plan 054/055 私有资产。

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

实际保留的 Plan 056 ignored 资产为：detached source worktree
`eval-data/sources/plan056-rondo-local-2765ff8f/` 与 `eval-data/sources/plan056-rondo-local-c2be21d0/`；对应 Cargo
target、两代 legacy/companion/runtime bundle；v1、rehearsal-v2/v3/v4、formal-v5 五个独占 campaign；batch/task
budget 与 Plan 056 build/preflight/paid/close metrics。复用了项目局部 `eval/.venv`、`eval-data/uv-cache`、既有
bwrap 资产和 v28 Terminal-Bench source。10 个 pinned Docker image 保留不清理；Plan 056 容器、网络、卷均已精确
清空，formal-v5 Docker/VHDX 增长均为 0，Docker total 仍为 11.5 GB。

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
| 003 | Plan 056 所有真实请求累计硬上限为 100 USD，从 v1 的 0.631065 USD 单调续接 | 用户 2026-08-22 追加授权；campaign/进程重启不能重置费用 | 预算、运行 | 已变更 |
| 004 | 同一 campaign 已发送 slot 不替换；设施问题关闭当前 campaign 后可用全新 identity 从第一题重启 | 既避免混合修复前后数据，也允许把可修复链路问题跑通 | 恢复、失败语义 | 已变更 |
| 005 | 唯一变量是既有原生 trace + schema-v2 投影，默认产品行为不变 | 当前证据只授权测量，不授权行为优化 | mydev、eval | 已采纳 |
| 006 | C1/C2/C11 最多选一项；门槛无人满足就是“无候选”，C7 不补测 | 防止为推进方向 1 降低证据门槛或扩张任务 | 聚合、WBS | 已采纳 |
| 007 | 职责契合时复用现有设施；强行复用扭曲单侧语义时可新建窄能力 | 保持架构契合和设计干净，同时避免第二套体系 | eval 架构 | 已采纳 |
| 008 | ignored 运行资产位于 Git common root；tracked 交付只在 Plan 056 worktree | 适配现有 RepoPaths 和 `.gitignore`，同时保护主工作区 | 数据、Git | 已采纳 |
| 009 | Plan 054 本地模型、Plan 055 重型 Cargo 与 Plan 056 Docker 全局串行 | 遵守共享宿主资源门并保护并行任务现场 | 资源、排期 | 已采纳 |
| 010 | 本任务只提交工作树，不合并、不推送、不归档 | 用户保留最终集成批准权 | Git 交付 | 已采纳 |
| 011 | 正式测量前至少完成一次连续 10 题单轮真实 rehearsal；首个可信正式 20/20 即停止 | 高效暴露设施问题，同时防止按成绩挑选 campaign | rehearsal、正式运行 | 已采纳 |
| 012 | 响应头前的已开始上游尝试使用精确 `open_error` 终态；不接受旧记录缺失枚举 | 既让未来连接失败可投影，又不放宽或改写 formal-v5 历史 | API metadata、投影、恢复 | 已采纳 |
