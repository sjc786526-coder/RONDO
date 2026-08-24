# Plan 067：M4-A 独立验收审查

日期：2026-08-24
首轮审查对象：`c9a6f8795a2e55f7d358a57ab558350158a5f505`
整改复审对象：`304510dcf16055bb69a9086f227e0ded132a9a8e`
最终结论：**PASS；接受 `M4_A_GO`，无未关闭的高/中等级 correctness finding。**

## 审查范围与方法

- 核对提交父级、精确写集、工作树状态、`git diff --check`、第四期 WBS、冻结证据、ExecPlan 与执行日志。
- 以当前主线 `doc/WBS.md`、现行 Session/AgentControl/Team State/ThreadStore/app-server/TUI 源码和既有测试定义复核身份、
  authority、生命周期、启用组合、失败结果及 S1/C0/W0 交接。
- 只读复核四项官方上游 PR 的主题、合并状态和消费语义。未运行 Cargo、Docker、真实 API/模型、训练、测评或全 workspace 测试；
  本次是合同与源码事实审查，静态证据足够。

## 首轮 Findings（均已关闭）

### [M1] Root close/idle unload 未禁止仍存活 descendant 跨 authority 继续写入

共同合同已经规定 Root 与 child 共用同一 Root authority、child residency unload 不释放 authority，但零订阅 deferred idle unload 与
owner/Team close 只写到“Root close 成功时释放 authority”，没有冻结仍可执行 Team mutation 的 descendant 必须先被安全处置。当前源码中：

- `AgentControl` 和其中的 canonical `TeamStateHandle` 由整棵 root tree 共享：
  `multidev/codex-rs/core/src/agent/control.rs:93-116`；
- app-server 按具体 ThreadId 独立触发 idle unload：
  `multidev/codex-rs/app-server/src/request_processors/thread_lifecycle.rs:349-380,402-451`；
- running child 不满足普通 residency unload 条件，可能在 Root 空闲时仍存活：
  `multidev/codex-rs/core/src/agent/control/residency.rs:217-232`；
- `/new`、slash `/clear` 主要解除订阅，不会同步关闭整棵 Team：
  `multidev/codex-rs/tui/src/app/session_lifecycle.rs:645-679`、
  `multidev/codex-rs/tui/src/app/thread_routing.rs:16-27`。

若下游把 Root Thread unload 成功直接等同于 Root authority 可释放，旧 child 仍可能提交 mutation，而另一进程同时取得 Root authority，
破坏单 writer 产品合同。

**必须闭合的产品结果**：只要任一 descendant runtime 仍具备提交 Team mutation 的能力，Root/Team close 就不得完成或释放 authority；
实现也可以在同一 close barrier 内先把这些 descendants 安全 quiesce/close。只冻结该结果，不规定锁、permit、调用顺序或状态机。
把 Root-idle-with-live-child 纳入 S1/S2 的聚焦 deterministic/fake 回归交接即可；C0 只诚实投影 closing/failed/unknown，不另建控制设施。

### [M2] 第四期当前 WBS 保留了已失效的三期前置和资源状态

`doc/WBS/durable-team-runtime.md:291-293,310` 仍称 Plan 060 尚无训练资格 GO、M3-B1c 尚不具备启动条件；当前主线
`doc/WBS.md:42-63` 已明确 Plan 060 `TECHNICAL_GO`、Plan 064 `DATA_GO`、Plan 066/M3-B1c 正式训练与验收完成，计算 Pod 已删除。
第四期 WBS 是持续维护的当前路线权威，此处会让后续执行者错误安排依赖和资源。

**必须修复**：仅依据当前已提交 main 窄同步第 5 节，写明三/四期无产品前置、M3-B1c 已完成且当前无活跃云训练任务；不要读取或吸收
Plan 068 未提交内容，也不要在本任务改顶层 WBS、COMPLETED 或三期方向 WBS。

### [L1] ExecPlan 的当前工作状态停留在提交前

`plan/067-m4-a-durable-team-runtime-common-contract-execplan.md:224-230` 仍写“正在执行本地提交”，但审查对象已经提交且 067 worktree
在审查开始时 clean。该问题不单独阻断 GO，但应随本轮修复把当前工作/剩余步骤改为真实的本地提交与复审状态，避免冻结计划自相矛盾。

## 审查者替用户作出的决策

- 采用 M1 的最小产品边界：**mutation-capable descendant 存活时不得释放 Root authority**；具体选择阻止 Root close，还是在 barrier
  内安全 quiesce descendants，由 S1/S2 按现有架构自主决定。无需新增第二套 registry、审计、可信或事务平台。
- 三期当前事实以已提交 `doc/WBS.md` 为准；Plan 068 仅是并行 worktree，不把其未提交状态写进 067 合同。
- 不扩大验证：修复后只需文档链接/术语/允许写集、`git diff --check` 和针对上述合同的静态复核，无需 Cargo 或其他重型测试。

## 已通过部分

- 精确写集、主线基准、Plan 068 隔离、身份与 fork/spawn/resume 区分、durable success、committed read、关闭失败、partial/unknown、
  legacy/fail-closed、启用组合、设施责任分级以及四项上游候选的消费边均基本正确。
- S1/C0/W0 交接保持实现自由，没有预选存储、锁、字段、API 或测试机制，也没有建设第二套 Team State/authority/lifecycle/control。
- 未发现要求 `REPLAN_REQUIRED` 的架构性阻塞；修复 M1/M2 后仍预期可以给出 `M4_A_GO`。

## 最终复审结果

- M1 已关闭：共同合同、生命周期矩阵、S1/S2 回归交接、C0 展示边界与第四期核心 PASS 均明确 mutation-capable descendant
  存活时不得完成 Root/Team close 或释放 authority；下游仍可自主选择阻止 close，或在同一 barrier 内安全 quiesce/close
  descendants，没有预选锁、permit、状态机或调用顺序。
- M2 已关闭：第四期 WBS 已仅依据已提交 main 同步 Plan 060 `TECHNICAL_GO`、Plan 064 `DATA_GO`、Plan 066/M3-B1c 完成、计算
  Pod 已删除且当前无活跃云训练；未吸收 Plan 068 未提交状态，也未修改共享顶层 WBS、COMPLETED 或三期方向 WBS。
- L1 已关闭：ExecPlan 已把执行者侧内容、整改提交与外部独立复审所有权区分清楚，不再声称正在执行首次提交。
- 整改提交精确修改五个获准路径，067 worktree 在复审开始时 clean，`git diff --check` 通过；静态复核未发现身份、authority、
  durable/read/close、启用矩阵、上游消费边或 S1/C0/W0 交接回归。合同任务无需 Cargo、Docker 或其他重型验证。

最终接受 `M4_A_GO`：共同边界已经足以让 M4-S1、M4-C0、M4-W0 分别建立 ExecPlan，同时其存储、API、锁、状态机、测试 fixture
与原型内部路线仍保持开放。未发现 `REPLAN_REQUIRED` 级架构阻塞。
