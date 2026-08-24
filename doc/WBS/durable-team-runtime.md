# 方向 3 四期：RONDO Multi Durable Team Runtime

最后更新：2026-08-24 ｜ 产品线：RONDO Multi（`multidev/`）｜ 状态：**长程规划已形成，尚未启动实施**

## 1. 阶段定位

第四期的价值中心是让现有 RONDO Multi 具备可持续使用的 Team 生命周期，而不是建设通用 workspace 平台：

1. **Durable Team Session**：必成主线，使 Team Session 可以跨进程持久化和恢复；
2. **Session Control Surface**：必成主线，通过 app-server v2 与 TUI 查询、恢复和显式控制持久 Session；
3. **Writer Workspace Binding（可选 Minimal Handoff）**：可选增强，把显式 writer 绑定到调用者已准备且授权的 Git worktree；只有价值门
   证明既有 Git 事实和自然语言交接不足时，才附加 minimal Git-native handoff。

worktree 是按需使用的执行隔离能力，不负责 Team 协调、任务拆分、正确性判断或成果整合。shared workspace 继续是默认行为；
W 线先经过原型和价值门，若自然语言安排与既有 Git 工作流已经足够，可以延期或停止，不阻塞 Durable Team Session、
Session 控制面或第四期核心收口。

第四期与 Publication Critic 三期没有产品依赖，可以有界并行。第四期的正确性开发和验收不调用真实 API 或模型，不进行
训练或性能测评；开发用 Codex 的额度消耗与 RONDO 产品运行时完全分离。

## 2. 现有基础、职责与产品边界

### 2.1 冻结基线与复用边界

冻结 Codex CLI `v0.147.0` 已具备 thread/Agent 生命周期、start/resume/fork 的 cwd 与 runtime workspace roots、权限与
sandbox、Git repository/worktree 识别以及 status/diff 等 Git 观察原语。RONDO 继续复用这些设施和系统 Git，不复制一套
Agent runtime 或 Git 实现。

本地 ThreadStore 还已具备按 ThreadId 生效的跨进程 active-writer ownership：create/resume 获得并在 live writer 生命周期内
持有文件锁，竞争写者收到 conflict，成功 shutdown/discard 释放；进程崩溃后由操作系统释放锁，残留锁文件由既有协调清理处理。
thread read/list 等只读路径不要求取得 active writer。第四期直接把这套机制作为 Team Session 单写者基础，不再建设 Team lock、
租约或另一套进程协调。

当前 Team capability 只按权威 participant/thread 身份解析，尚未把 mutation 资格连接到 Root Thread writer ownership；因此本期
仍需增加这条检查接缝。现有锁解决并发所有权，新增接缝只把它提升为 Team 写资格，不复制锁实现。

Codex 桌面端的 managed worktree、Local/Worktree Handoff、快照和清理不是冻结 CLI 源码中可直接复用的 Team Workspace
Runtime。第四期 V1 不把这些产品能力视为现有基线，也不移植完整 Project、queue dispatcher、agents dashboard 或 `/cd`
子系统。

| 领域 | 本阶段职责 | 不承担的职责 |
|---|---|---|
| 现有 Codex core | 继续拥有 thread、Agent、spawn/resume、Root Thread active-writer ownership、cwd、workspace roots、工具执行、sandbox 与审批 | 不复制 Team State，不自动提供 Team writer 的 worktree binding |
| Team State | 继续作为 Event、Version、route、Fact 与团队协作语义的唯一 canonical 来源 | 不管理持久介质、Git 资产或 UI 状态 |
| Durable Team Session | 管理 Team 状态的跨进程生命周期、定位、兼容和恢复结果 | 不接管 thread history、Agent graph、运行中的模型或工具执行 |
| Writer Workspace Binding | 保存恢复 writer 执行上下文所需的最小 binding 语义，并在价值门要求时附加 minimal handoff；调用现有 thread/session/Git 能力验证 | 不拥有、创建、删除或调度 worktree，不形成独立 workspace registry |
| app-server v2 / TUI | 投影权威 Session/Team 状态并提供显式生命周期操作；W 线落地时可按其实际范围增加窄的 binding/handoff 展示与修复入口 | 不成为另一份状态源，不建设通用 project/session/task dashboard |

职责契合时复用现有设施；强行复用会扭曲语义时，只增加解决 Team 特有缺口的专用薄层。新增能力仍遵循现有配置、生命周期、
错误、测试和观测方式，不建设第二套基础体系。

### 2.2 稳定产品合同

- Team 生命周期直接跟随 Codex 已有的 resume、fork、`/new`、`/clear`、detach、进程退出、archive/unarchive 与 delete；不新增
  含义不清的 Team `reset`。
- Team State 继续拥有团队协作语义；Durable Team Session 只负责持久介质、定位、生命周期、兼容与恢复结果。
- 每个 Team Session 首版只有一个活跃进程/协调器写 Team State，但 Team 内允许多个 writer Agent。
- Root Thread 的原生 active-writer ownership 同时是对应 Team Session 的唯一 V1 写入资格。Root 或 child Agent 发起的任何 Team
  mutation 都必须确认当前进程持有该 Team 的 Root Thread writer；单独持有 child Thread writer 不授予 Team 写能力。
- 未持有或无法证明 Root writer ownership 的进程只能读取权威 Team 状态，不能直接修改持久 Team 存储。控制面 mutation 必须
  由已经加载 Root Session 的进程执行；未连接该 owner 时返回 conflict/unavailable，V1 不建设跨进程 mutation 转发平台，也不
  支持强制接管。
- shared workspace 继续是默认行为。研究、审查和只读 Agent 不被强制分配 worktree；只有 Root 明确声明且适合独立开发的
  writer 才可以启用 W 线。
- W 线只接受调用者已经准备、授权且可验证的本地 Git worktree。创建、删除、prune、合并和冲突处理继续属于用户、Root、
  明确 integrator 与系统 Git 工作流。
- RONDO 只保存 writer 恢复所需的最小 binding descriptor 与状态，并复用既有 Session/thread 持久接缝；仅在价值门选择 minimal
  handoff 时保存其结果。
  Git 与文件系统现场对 worktree 是否存在、归属哪个 repository 及实际内容具有权威性。不建立 canonical workspace index、
  ChangeSet registry 或独立 workspace store。
- 若启用 handoff，它是按需形成的一次结构化时点 Git 事实记录或既有 Git 资产引用，足以定位 writer、repository/worktree、
  基线和当前修改状态；它不拥有修改、不管理冲突或清理生命周期，也不声称修改正确。
- app-server 与 TUI 只读取权威领域状态并调用领域能力；断线、恢复中、冲突和结果未知必须如实展示。
- Durable Team Runtime 默认关闭；关闭态不改变现有单 Agent、Team、thread resume、shared workspace、app-server 或 TUI 行为。

### 2.3 与 Codex 对齐的 Session 生命周期

| Codex 操作 | Durable Team V1 语义 |
|---|---|
| resume / member reload | 恢复原 TeamInstance 与原 canonical Team State。Root resume 恢复 V2 Agent graph 中仍为 open 的成员身份和 metadata，但不自动加载 child runtime；成员按现有 V2 residency/reload 规则按需加载，恢复本身不启动 model turn 或真实 API |
| fork（latest 或指定历史位置） | 原生 conversation/thread history 继续按 Codex 的分叉点规则复制，但创建新 Root Thread/Session 与新的空 TeamInstance；来源 Team 保持不变，V1 不继承或克隆 Durable Team State |
| `/new`、slash `/clear` | 创建新 Root Thread/Session 与新的空 TeamInstance；原 Session/Team 保留并可 resume。纯终端/UI 清屏不改变 Session 或 Team |
| TUI 切换、unsubscribe、客户端断开 | 只改变客户端附着与展示，不改变 Team 生命周期，也不据此把 Team 标记为 stopped/closed |
| app-server 正常退出/完整进程终止 | 正常退出先持久化并关闭已加载 thread；完整进程终止最终由操作系统释放仍持有的 writer。所有已成功 Team mutation 仍可恢复，下次 resume 回到原 Team；存活进程内的单个 session/task 失败不等同于完整进程退出 |
| archive Root | 复用 Codex 对 Root 与 spawned subtree 的原生 archive 流程；Team State 随 Root 进入保留但不可写的 archived 状态，不删除 TeamInstance |
| unarchive Root | Root 回到可恢复状态并恢复原 TeamInstance/Team State；descendant 继续服从其原生 archive/Agent graph 状态，不另造批量复活语义 |
| delete Root | 复用 Codex 的 Root/spawned-subtree delete，并永久删除对应 Team State；部分失败必须报告 error/degraded，不得把残留或缺失状态展示为正常可恢复 Team |

fork 后的新 Team 从初始 revision 开始，只自动建立新 Root 的当前运行身份。它不复制来源 Team 的 Event/Version/Fact、participants、
routes/delivery、wake、committed retry、change log、Agent graph、writer binding 或 handoff，也不复制正在运行的 Agent、turn、lock、
loaded/residency 或 child runtime。Codex 原生 fork 仍可按现有规则继承 conversation history、cwd、权限、模型配置并记录
`forked_from_id`；这不构成 Team State 继承或新的 Team provenance registry。

forked conversation history 中已经出现的旧 Event/Version/Route/Fact 引用仍带来源 TeamInstance tag，对新 Team 使用时必须按现有
instance mismatch/`InstanceReset` 规则 fail-closed，不能解析到新对象、静默重铸 ID 或把空 Team 描述成继承成功。若未来真实使用
证明需要复制团队世界状态，再把 ID remint/rewrite、历史 contributor、Fact availability 与 route/wake/retry 取舍作为独立的 Team
clone/branch 能力立项，不塞入 M4-S2。

Codex 当前 archive 会尝试处理 spawned subtree，但既有实现允许个别 descendant 失败时其余对象完成 archive；unarchive 也没有
“整棵树批量复活”的统一语义。RONDO 只让 Team State 跟随 Root 的权威生命周期，并如实投影 descendant 的原生结果，不把这处
现状扩大为新的清理、补偿或事务平台。archive/delete 继续服从原生 active-writer conflict，不允许其他进程借生命周期操作强制
接管或释放 writer。

### 2.4 留给任务级方案决定的内容

本 WBS 不冻结 crate/module 布局、Rust API、wire schema、持久格式、数据库选择、binding descriptor 或 handoff 的字段与载体、
replacement binding 的具体 thread 实现、分页与通知细节、具体错误类型或测试 fixture。上述内容由各工作包在阅读当时主线、
完成必要原型和调试后决定，不得反过来扩大本节的产品职责。

## 3. 工作包

### M4-A：共同产品合同、生命周期边界与上游增量决策

**目标**：统一 Team Session、Team instance、Root thread lineage、控制操作和可选 writer binding 的身份、生命周期、启用边界、
失败责任及共同验收口径。

**边界**：只收敛跨子线必须共享的产品语义，不提前选择持久介质、公共 API、模块布局或 W 线的正式实现，不建设通用框架。

**最小持久正确性合同**：

- 对采用 Team revision 的 canonical mutation，返回成功时对应 revision 已经处于可恢复状态；不推进 Team revision 的独立
  状态轴也须定义等价的耐久成功边界，不能先返回成功再依赖未承诺的后台落盘。
- 并发只读查询必须返回一个完整已提交 Team revision，并明确携带其 TeamInstance/revision；允许返回较旧但完整的 revision，
  或明确报告 stale/unknown/unavailable，不得把两个 revision 的字段、分页或投影拼成撕裂状态。该合同不要求新增 Team read lock。
- 已有持久标记但后端缺失、损坏或版本不兼容时明确失败或降级，不得静默创建空 Team 冒充恢复。
- 身份优先绑定既有 SessionId 与 Root ThreadId，并在 resume 时保留原 TeamInstanceId；无充分证据不引入第三套 Team Session identity。
- fork 永远使用新的 Root Thread/Session 与新的空 TeamInstance；来源关系只复用 Codex 原生 thread lineage，不复制 Team revision，
  也不为来源 TeamInstance 或旧引用增加映射层。
- “关闭/卸载完成”必须同时意味着应持久的 Team/thread 状态达到承诺边界，且对应 Root Thread writer guard 已经释放。持久化 shutdown
  失败、session loop/task 异常退出或进程内 teardown 未完成时，状态保持 closing/failed 并允许重试，不能报告完成或移除唯一可重试
  的运行对象。若任务级方案确需暴露已有 discard 能力，它是独立且显式确认的失败恢复动作，必须说明未持久数据可能丢失，不得
  伪装成正常关闭；本 WBS 不要求新增通用 discard/cleanup 控制面。

**Root writer 复用合同**：

- Root Thread 的既有 active-writer ownership 是 Team Session 的唯一 V1 写者门。第二个进程 create/resume 同一 Root Thread 时
  复用原生 conflict 并拒绝，不新增 Team lock、租约、lock file 或进程 registry。
- 其他客户端可以只读定位和查看权威 Team Session；需要 mutation 的控制操作必须路由到持有 Root writer 的进程，不能由只读
  控制端绕过 Root Session 直接写 Team 持久介质。这里的“路由”只指请求已经连接的 owner Session；若未连接 owner，返回
  conflict/unavailable，不新增跨进程 relay、queue 或 IPC router。
- Root 与 child 的 mutation 使用同一资格检查。另一个进程即使成功 resume 某个 child Thread，也只获得该 child 的 thread writer，
  不得据此加载第二份可写 Team runtime 或提交 Team mutation。
- V1 不支持强制接管、抢锁或静默接管。正常退出后由既有 shutdown 释放；异常退出后依赖操作系统文件锁释放与现有残留文件清理，
  后续进程再按原生 resume 取得 Root writer。这里的异常退出指持有锁的完整进程终止；存活 app-server 内的 session/task 失败不会
  自动释放操作系统锁，必须按上一节报告失败并保留重试或显式 discard 路径。
- 无法从所选 ThreadStore 后端和 Root lineage 可靠证明 active-writer ownership 时，Team mutation fail-closed 并报告
  unavailable/unsupported。只有 M4-A 证明现有机制无法承载该合同，才更新 WBS 另行考虑专用 Team 写者机制；不得在 V1 内
  预建或静默回退第二套锁。

**启用与能力合同**：

- 定义 Durable Session、Session 控制面、可选 writer binding 与现有 MultiAgentV2、`team_state_enabled` 的有效组合；非法组合
  fail-closed，每种关闭态都保持既有行为。
- 对外形成一套连贯的 opt-in 语义；具体配置形状和内部子开关由任务级方案按职责决定。
- 首次创建 durable session 前验证所需持久能力和权威 lineage material。仅有内存能力且没有满足合同的 durable authority 时
  报告 unavailable/unsupported，不能把进程内 Team 冒充 durable。
- 首次加载可写 Team runtime 前还须验证 Root Thread active-writer ownership；只读打开不需要取得该写者资格。

**上游增量决策门**：

- 产品基线仍是 `v0.147.0`；`v0.149.1` 只作为对照，只选择性吸收具体 PR，不视为完整基线升级。M4-A 只评估与本期缺口
  直接相关的上游窄增量，不假定完整 `v0.149.1` 已存在。
- `#37847` 的 Agent reload environment 与 `#37198` 的 persisted cwd read consistency 是 S/C 线候选；它们不能替代实际执行前的
  binding 验证。
- `#39616` 的 linked-worktree trust 是 W 线候选前置；`#39153` 的 permission restore 只有在 W 权限合同明确后才评估适配，
  不接受失效权限静默回退默认值。
- M4-A 对每项只形成复用、窄回移、按 RONDO 语义适配或不采用的结论。任何实际回移另建独立任务合同；完整 Project、queue、
  dashboard、`/cd` 或整体基线升级不混入第四期。

**条件消费边**：

- S/C 选中的窄增量必须在首个实际消费它的 S/C 工作包达到 PASS 前进入主线；对应 ExecPlan 只消费已进入主线的实现与事实，
  不把并行 backport worktree 当作已满足前置。
- `#39616` 若被 M4-A 指定为 M4-W0 权威 trust 结论的基础，必须先于 M4-W0 进入主线；否则 M4-W0 不得借用该结论，且该增量
  只有在 M4-W1 立项后确认为必要时才须在 M4-W1 开始前完成。
- `#39153` 只在 M4-W0 形成 binding GO 后评估适配；若 M4-W1 采用它，适配实现必须在 M4-W1 PASS 前进入主线。
- W 专属增量不阻塞 M4-S1、M4-C0 或后续 S/C 工作包启动和收口。

**交接**：M4-A 是四期唯一共同实施入口。完成后 M4-S1、M4-C0 和 M4-W0 可以有界并行；正式 W 实现仍等待 binding GO 与
M4-S1 的持久接缝。

### 子线 S：Durable Team Session（必成主线）

#### M4-S1：Team Session 持久生命周期

**目标**：让已确认的 canonical Team State 与权威 Root lineage 绑定，并以 Root Thread active-writer ownership 约束可写 Team
runtime；mutation 成功后对应 revision 可恢复，非 owner 能读取一个完整已提交 revision；进程退出后仍能定位原 Team Session，
并在重新取得 Root writer 后加载为可写状态。

**边界**：只持久化恢复团队语义所需的状态；不保存完整 transcript、reasoning/CoT，不恢复运行中的模型请求、工具调用或
外部副作用，也不把 Team State 塞入单个 thread 的历史充当第二份真相。读一致性复用所选持久介质的正常提交/快照能力，具体
机制由 ExecPlan 决定，不增加 Team read lock 或第二份只读 store。

#### M4-S2：恢复与生命周期收口

**目标**：按第 2.3 节完整处理 resume/member reload、fork、`/new`、slash `/clear`、客户端 detach、正常关闭、完整进程异常
终止、archive/unarchive、delete、旧 session、不兼容或损坏状态，使恢复或分叉后的团队身份、权限和 canonical 状态符合原生 Session
语义，无法确认时明确降级或拒绝。

**边界**：不建设多机、复制、高可用、共识或通用事务平台；可选 writer binding 的失败只影响对应 writer，不默认阻止 Team/root
read model 被定位、查看和恢复，也不自动启动其他成员。V2 Root resume 只恢复 open descendant 的身份/metadata，child runtime 按需
reload，不能把旧式 Agent 路径的自动 reopen 行为扩大为本期合同。任何 fork 都从新空 TeamInstance 开始；旧 Team 引用
fail-closed，不建设 Team clone/branch、ID 映射、历史成员档案或跨 lineage Fact 恢复。只有成功 teardown 或完整进程终止实际释放
Root writer 后才允许后续 resume；存活进程内 shutdown/session-task 失败保持 closing/failed 且可重试，不实现强制接管。

**子线出口**：新建、推进、fork 到新空 Team、detach、关闭、进程终止、恢复、archive/unarchive 与 delete 的生命周期可以稳定重复；
失败关闭不伪报完成，恢复和 member reload 不自动触发模型/API，且功能关闭态无回归。

### 控制面子线 C：Session app-server v2 / TUI（必成主线）

#### M4-C0：实验性 Session 协议与 TUI 原型

**目标**：在 M4-A 的职责边界上验证 Session、Team 和恢复状态的基本查询、操作流与展示方式，为正式控制面拆包提供真实输入。

**边界**：C0 不承诺稳定公共 API 或正式 TUI 验收。所有新增接口只进入 app-server v2 并保持 experimental；控制面不复制
Team State 或 Durable Session，不把 Team Lens 离线结果变成在线状态源，也不建设通用 project/session/task dashboard、
queue dispatcher 或 daemon-wide agents 管理面。只读查询不要求取得 Root writer；任何状态修改都交给持有 Root writer 的
已加载 Root Session 处理，未连接到该写者时返回 conflict/unavailable，不得直接写持久介质、伪造成功或建设跨进程 mutation
转发平台。TUI unsubscribe、切换或断开不改变 Team 生命周期。

**后续工作包**：M4-C0 完成且 M4-S1 提供真实 Session read model 后，再按当时接缝建立少量可独立验收的 Session query M4-C*；
M4-S2 的恢复行为收口后，再建立 Session control/TUI M4-C*。当前不预定具体 RPC、UI 布局或包数。

**子线出口**：操作者可以通过公开 app-server v2/TUI 查看和控制允许的 Team Session 生命周期；断线、重启或结果未知后能从
权威领域状态重建当前视图并安全继续，不绕过现有权限和审批，不自动启动 Agent、模型或真实 API。

### 子线 W：Writer Workspace Binding（可选 Minimal Handoff）

#### M4-W0：Binding 原型与价值门

**目标**：用预置本地 Git worktree 验证 Team writer 在首次动作、reload/resume、失效 binding 和 handoff 场景中的真实产品缺口，
并判断产品机制相对自然语言安排是否具有足够的重复性与安全收益。

**边界**：只做最小接缝原型和 deterministic/fake 正确性验证，不建设 workspace store、registry、provisioning、cleanup、
workspace snapshot、integration workspace 或正式公共 API，也不调用真实模型或 API。

**价值门输出**：

- `BINDING_ONLY_GO`：不可绕过的首次动作前 binding、跨进程重验、fail-closed 与 replacement binding 具有产品价值；成果交接继续
  使用现有 Git status/diff/ref 和自然语言，不新增结构化 handoff。
- `BINDING_HANDOFF_GO`：除 binding 外，证据还证明 minimal structured handoff 具有独立价值；M4-W1 才包含该窄能力。
- `NO_GO`：自然语言安排和现有 Git 工作流已经足够，W 线停止。
- `INCONCLUSIVE_DEFER`：证据不足，保留结论但不启动 M4-W1。

后两种结果不阻塞 S/C 与 M4-Z(core)；M4-W1 的最终范围必须服从本门结论，不得从 binding-only GO 扩张出 handoff 子系统。

#### M4-W1：Writer Workspace Binding（可选 Minimal Handoff）

**开始前置**：M4-W0 形成 `BINDING_ONLY_GO` 或 `BINDING_HANDOFF_GO`，且 M4-S1 已提供可复用的持久 Session/thread 接缝。

**目标**：将显式 writer 绑定到调用者已准备、授权且可验证的本地 Git worktree，在首次模型或工具动作及每次 reload/resume 前，
通过原生 cwd、workspace roots、permission、sandbox 与 thread 生命周期强制并重新验证绑定；仅在 `BINDING_HANDOFF_GO` 时附加
可检查的 minimal Git-native handoff。

**PASS 前置**：M4-S2 已提供正式恢复行为，M4-W1 的 reload/resume、失效隔离和 replacement binding 已在该行为上完成收口；
M4-W1 实际消费的上游窄增量也已进入主线。M4-W1 可以在开始前置成立后并行开发，但不得在满足本门前宣告 PASS。

**边界**：

- writer/integrator 是 binding 或能力，不新增 Team Role，不建立第二套 spawn、Agent registry、scheduler 或自动路由。
- binding 不得扩大 Agent 原有宿主文件、Git、sandbox 或审批权限；Workspace Binding、cwd、workspace roots 与有效权限必须在
  writer 第一次可观察动作前生效。
- worktree 缺失、repository 失配、trust 或权限不兼容时，将对应 binding 标记为 unavailable/unknown，拒绝自动加载、执行或
  重新绑定，绝不静默退回父 cwd。
- 显式修复不承诺原 ThreadId 原地切换 workspace。用户、Root 或明确 integrator 先处理旧 binding 与未 handoff 成果，验证新的
  worktree、roots 和权限后，再建立 replacement binding；不得静默覆盖旧 binding。
- 若 W0 选择 minimal handoff，它只记录或引用可核对的时点 Git 事实与现成成果，不强行复用 Team State 的自由文本 `handoff`
  字段，不成为 ChangeSet registry，不自动 merge、cherry-pick、判断正确性或解决冲突；binding-only 范围不新增该能力。
- RONDO binding 能力、Git 操作方和所选执行环境必须能共同直接访问并验证同一 repository/worktree；不能满足时返回 unsupported。
  远程 client 本身不构成拒绝理由，但远程 workspace controller、多机同步和跨文件系统 worktree 不属于本期。
- RONDO 不 create/adopt/remove/prune worktree，不复制 ignored 文件或 `.env.local`，不清理、回收或恢复 Git 资产。

**可选控制面扩展**：M4-W1 PASS 后，可以另行建立窄的 binding、失效展示和 replacement binding 操作包；仅在 W1 包含 minimal
handoff 时投影其状态。该扩展不扩张为通用 workspace dashboard，也不阻塞 Session 控制面或 M4-Z(core)。

**子线出口**：两个 writer 可以绑定两个预置 worktree，首次可观察动作和基于 M4-S2 的 reload/resume 均使用并重新验证正确执行
上下文；失效只使对应 writer unavailable，关闭态保持现有 shared workspace 行为。若范围包含 minimal handoff，它还须可定位、
可检查且不声称正确；binding-only PASS 不以新 handoff 能力为前置。

### M4-Z(core)：Durable Team 全链收口

**目标**：完整打通 Team Session 创建、Team/Agent 状态推进、进程或连接中断、恢复、继续控制和显式生命周期操作，确认 S/C 主线
形成独立可用的 Durable Team Runtime。

**边界**：M4-Z(core) 不以 W 线 GO 或完成为前置，不加入性能 benchmark、模型质量横评或与阶段目标无关的平台建设。若 M4-W1 已进入
主线，则增加一条相称的 Session resume + binding 兼容验收，并仅在 W1 范围包含时纳入 handoff；若 W 线延期，则第四期核心照常收口。

## 4. 四期内部串并行关系

```text
M4-A
├─ M4-S1 → M4-S2
└─ M4-C0

M4-S1 + M4-C0 → Session query M4-C*
Session query M4-C* + M4-S2 → Session control/TUI M4-C* → M4-Z(core)

M4-A → M4-W0（原型/价值门）
M4-W0 binding GO + M4-S1 → M4-W1 开始
M4-W1 实现 + M4-S2 → M4-W1 PASS → 可选 Workspace 控制面扩展
M4-W0 NO_GO/INCONCLUSIVE_DEFER ────────────────→ 不阻塞 M4-Z(core)

条件增量边：
selected S/C delta → 首个消费它的 S/C 工作包 PASS
#39616 → M4-W0（仅当作为权威 trust 前置）；否则按需 → M4-W1 开始
M4-W0 binding GO → #39153 按需适配 → M4-W1 PASS
W-only delta ─/→ S/C
```

- M4-A 先串行完成，避免 S/C/W 各自发明身份、生命周期或第二份状态。
- M4-S1、M4-C0 与 M4-W0 在 M4-A 后可以并行；正式 Session query 等待 M4-S1，正式 Session control/TUI 再等待 M4-S2。
- M4-W1 只在 binding GO 后开始，并等待 M4-S1 以复用持久接缝；开发可以与 M4-S2 并行，但最终 PASS 必须等待 M4-S2 并把
  resume/replacement binding 收口纳入自身出口，不存在无编号的后置收口包。
- M4-Z(core) 只依赖 S/C 主线。W 若已经进入主线，由后完成者拥有一次兼容验收；W 未进入主线时不制造空实现或占位平台。
- 各工作包内部的模块、测试和审查并行度由对应 ExecPlan 根据当时源码决定。共享 core/protocol/TUI 接缝和 WBS 由单一集成者
  收敛，避免并行 Agent 争写同一公共面。

## 5. 四期与三期的关系

### 5.1 产品与工作包依赖

- 四期不依赖 Publication Critic 模型、训练数据、真实权重、部署资格或横评结果；三期后续工作也不依赖第四期完成。
- 三期 Plan 060/M3-B1b 的后续执行，以及其正式结果到达后对冻结 v8 的有界预算适配复核，都可以和四期 M4-A、M4-S*、
  M4-C* 或可选 M4-W* 工作包有界并行。M3-B1c 只有在 Plan 060 训练资格 GO、冻结 v8 数据 GO 与新的正式训练授权同时成立后
  才具备另行规划条件；四期不参与或替代这些前置。
- 三期 M3-C1/M3-C2/M3-D 若与四期同时修改 `multidev/` 公共协议、Team 生命周期、app-server/TUI 或共享配置，分别在独立
  worktree 开发，进入主线时串行整合；不存在固定的三期或四期优先顺序。
- 每个工作包从开始时的最新主线建立任务合同。并行工作只共享已经进入主线的稳定事实，不以其他 worktree 中尚未合并的
  方案或结果作为前置。
- 当三期或四期中第二项能力进入正式收口时，只要另一项已经进入主线，由后完成者拥有唯一一条 fake/offline 的 Critic +
  durable Team resume 组合回归；writer binding 已进入主线时才纳入 binding 路径，并仅在 W1 范围包含时纳入 handoff。
  该测试不调用真实模型或 API，不重复建设，也不把两个阶段改成互相前置。

### 5.2 资源使用与竞争

| 工作类型 | 默认资源 | 与其他工作的关系 |
|---|---|---|
| 四期规划、源码研究、文档、轻量实现与非重型测试 | 开发用 Codex、普通 CPU/内存 | 可与三期云训练、数据合成和模型链监控并行；不产生 RONDO API/模型费用 |
| M4-W0/W1 临时 Git 正确性验证 | 临时 repository/worktree、普通磁盘 I/O | 不需要真实模型、API、Docker 或长期 Git 资产；可与非重型 S/C 工作并行 |
| 四期 Rust 重型构建或测试 | 仓库共享 Cargo build lock、本地内存与磁盘 | 所有 worktree 全局串行；按根 `AGENTS.md` 与 Docker、真实本地模型加载/推理互斥 |
| 三期已授权的真实 API 数据合成或横评 | 中转 API 预算与网络 | 不占 Cargo build lock，可与四期开发并行；范围、费用和授权与开发用 Codex 额度完全分开 |
| 三期 M3-B1b/M3-B1c 云端训练 | 相应任务获得授权后使用的云 GPU、预算与工件传输 | 云计算不占本地 Cargo build lock；Plan 060 尚无正式训练资格 GO，M3-B1c 尚不具备启动条件；获批后的 bundle、checkpoint 与结果传输仍竞争本地网络和磁盘，按实际压力错峰 |
| 三期 M3-C1/M3-C2/M3-D 本地模型与测评 | 本地模型/GPU、可能的 Docker、测评数据与已授权 API | 与四期重型 Cargo、Docker 和其他真实本地模型任务按根资源门禁串行错峰 |
| 任一方向的 Docker 工作 | Docker、本地磁盘和宿主容量 | 第四期默认不需要；若具体任务确有必要，须单独授权并与重型 Cargo、真实本地模型互斥 |

第四期适合把 S、C、可选 W 原型、源码研究、测试设计和审查组织成若干**有界并行**流；共享 core/protocol/TUI 接缝、主线整合
和全局 Cargo build lock 限制同时编码的主线数量。开发用 Codex 额度不等于 RONDO 产品 API 额度；具体资源阈值和看门狗入口
统一引用根 `AGENTS.md`，本 WBS 不复制容易漂移的数值。

## 6. 调试与验收原则

- 每个工作包开始前建立独立 ExecPlan，只定义该任务的目标、边界、当时架构接缝和验收，不在本 WBS 预写实现细节。
- 调试阶段保留已验证进度和可恢复现场，从第一个未打通处继续修复；完整产品链打通前不冻结公共 API、持久格式、配置或正式结果。
- S/C 核心链打通后，记录正式验收使用的准确代码与配置版本，稳定必要的外部兼容边界，再从干净的本地 Session/store 状态
  完整运行一轮。这里不永久冻结内部代码、配置结构或持久格式；具体返修与复跑循环由 M4-Z(core) ExecPlan 决定。
- 每个工作包先满足就近 `AGENTS.md` 要求的强制测试、生成物和 TUI snapshot 测试门禁；M4-Z(core) 额外运行相称的 S/C 干净全链验收。
- M4-S1/S2 使用 deterministic/fake 故障与并发回归覆盖两条窄边界：持久化 shutdown 失败或 session task 异常时不得报告关闭完成、
  不得遗失存活进程内 writer guard 的重试路径；若实际范围包含 discard，再验证其显式数据丢失语义。writer mutation 与非 owner
  并发 read 时，只能返回一个完整已提交 revision 或明确 stale/unknown/unavailable。该验证不建设 Team read lock、审计或跨进程
  协调平台。
- M4-S2 另以一条 deterministic/fake fork 回归确认：原生 conversation history 按所选分叉点进入新 thread，新 TeamInstance 为空，
  来源 Team 不变，fork history 中的旧 Team 引用对新实例返回 instance mismatch/`InstanceReset`；不为测试建设 ID remint 或 lineage
  恢复设施。
- M4-W0/W1 使用临时 Git repository/worktree 和 deterministic/fake 测试；若 W1 落地，由其自身出口按价值门范围承担完整 binding
  及可选 minimal handoff 验收。
  第四期不新建或运行性能测评。

## 7. 宏观验收

### 7.1 第四期核心 PASS

- 原 Team Session 在进程退出后可以恢复并继续协作；无法恢复时不会被空团队或虚假成功掩盖。
- app-server v2 与 TUI 从权威领域状态展示并控制 Team Session；断线或重启后可以重新同步，不维护第三份状态。
- 持有 Root Thread writer 的进程是唯一 Team 写者；竞争 Root resume 被原生 conflict 拒绝，单独 resume child Thread 不能绕过
  Root ownership 提交 mutation。其他客户端仍可只读查看；原写者成功关闭或完整进程终止释放 writer 后，后续 resume 才能取得写资格。
- 非 owner 并发查询只返回带 TeamInstance/revision 的完整已提交状态，或明确 stale/unknown/unavailable；不会观察到跨 revision 撕裂。
- persistence shutdown 失败、session task 异常或存活进程内 teardown 未完成不会被报告为关闭完成，Root writer 仍可定位并重试；
  只有成功关闭或完整进程终止实际释放 writer 后，其他进程才能 resume；若实现范围包含显式 discard，其结果也必须先确认 writer
  已释放且不得冒充正常关闭。
- resume/member reload 保留原 TeamInstance；任何 fork 都让原生 conversation/thread history 按 Codex 规则进入新 Thread/Session，
  但 Durable Team 从新的空 TeamInstance 开始，来源 Team 不变，旧 Team 引用 fail-closed。`/new` 与 slash `/clear` 同样创建空 Team，
  detach 不改变生命周期。
- V2 resume 恢复 Agent graph 的身份/metadata 但不自动启动 child runtime 或 model turn；archive/unarchive/delete 的 Team 结果跟随
  Root 原生生命周期，部分失败明确暴露且不冒充正常可恢复状态。
- 功能关闭态和普通 shared workspace 路径保持现有行为。
- 正确性验收不使用真实 API、真实模型、训练、Docker 或性能测评。
- W 线无论 GO、延期或停止，都不影响以上 S/C 核心能力达到 PASS。

### 7.2 可选 W 线 PASS

- 两个 writer 可以绑定两个调用者预置并授权的 worktree，首个可观察动作就在正确 workspace。
- cwd、workspace roots 与权限正确生效且不扩大原授权；writer 修改互不污染，也不触碰用户当前 checkout。
- reload/进程重启后重新验证原 binding；worktree 缺失、repository 失配或权限不兼容时，仅对应 writer unavailable，
  绝不回退父 cwd，Team/root read model 仍可恢复和查看。
- replacement binding 不静默覆盖旧 binding 或未交接成果；若 W0 选择 minimal handoff，它可检查、可定位，但不声称正确且
  不自动 merge；binding-only PASS 不要求新增 handoff。
- W 线关闭时保持现有 shared workspace 行为。

## 8. 非目标

- RONDO-managed worktree provisioning、create/adopt/remove/prune、ignored 文件复制、managed workspace snapshot、自动 cleanup
  或 Git 资产恢复；
- canonical workspace index、Workspace ChangeSet registry、通用 workspace/session/task registry 或独立 workspace store；
- 通用 Project API、queue dispatcher、agents dashboard、daemon 管理面或完整 `/cd` 移植；
- 自动拆任务、自动 spawn、自动 Agent 路由、新 Agent-to-Agent 协议、自由群聊或大规模 swarm；
- 自动 merge/cherry-pick、冲突修复、修改正确性判断、更新 `main`、fetch/push、PR、CI 或远端发布；
- 多机/远程 workspace controller、跨文件系统 worktree、分布式 Session、高可用、复制、共识或通用事务平台；
- 第二套 Team State、thread history、Agent graph、trace 或事件总线；
- Team 专属 `reset`、fork 时的 Team State 继承、Team clone/branch、ID remint/rewrite 或 old-to-new mapping、历史 contributor 档案、
  跨 lineage Fact 恢复、route/wake/retry 克隆、revision/turn 时间旅行、自动重启全部 descendant 或批量复活 Agent subtree；
- 保存或广播完整 transcript、reasoning/CoT、terminal 输出或 Fact 正文；
- 浏览器后台、远程 SaaS、多用户账号、复杂鉴权、审计/可信平台、严格全局因果或数据资产审计；
- 完整上游基线升级，或任何为第四期新增的真实 API/模型调用、训练、横评、benchmark 与 RONDO 推理成本。
- 专用 Team lock、read lock、租约、强制接管、抢锁、跨进程 mutation relay/queue/IPC router、绕过已加载 Root Session 的独立
  存储写入器或第二套 writer registry；除非未来证明确有独立需求并重新立项。

## 9. 实施与授权边界

本文只是长程 WBS，不是实施授权。M4-A 是唯一实施入口；M4-A、M4-S1、M4-S2、M4-C0、M4-W0 和 M4-Z(core) 是独立工作包，
各自启动时须按 `plan/plan-example.md` 建立 ExecPlan、确认当时主线和并行 worktree 状态并取得实施授权。

后续正式 Session M4-C* 等真实 read model 后再更新本 WBS、编号并分别建立 ExecPlan；M4-W1 只有在 M4-W0 形成 binding GO 且
M4-S1 接缝成立后才可立项，最终 PASS 等待 M4-S2；可选 Workspace 控制面扩展再等待 M4-W1 PASS。任何上游窄回移另建独立
任务合同，并按第 3 节条件消费边进入主线；完整基线升级仍是独立方向。

普通第四期实现不需要外部或付费行为；如果具体任务扩展到真实 API、模型、训练、Docker、上传或其他外部状态，必须单独说明
范围并重新授权。
