# 方向 3 四期：RONDO Multi Durable Team Runtime

最后更新：2026-08-25 ｜ 产品线：RONDO Multi（`multidev/`）｜ 状态：**M4-A、M4-C0、M4-S1、M4-C1 与 M4-S2 已完成；M4-C1 / M4-S2 分别为 `M4_C1_QUERY_PASS` / `M4_S2_PASS`；M4-C2 两轮整改实现已收口并等待独立复验，M4-Z(core) 尚未解锁，M4-W0 继续按条件推进**

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

### 2.1 冻结基线与设施责任

冻结 Codex CLI `v0.147.0` 与当前 RONDO Multi 已提供 thread/Agent 生命周期、V2 Agent graph、canonical Team State、
Root Thread active-writer、app-server v2/TUI 生命周期入口、feature/config 解析及 Git/worktree 观察原语。Plan 069 已在这些接缝上
落地跨进程 Team persistence、Root writer 到 Team durable commit 的连续资格及 durable read model，并通过主体预验收；Plan 074 已把
`#37198` persisted cwd read consistency 按 RONDO 语义窄回移到指定主线，并由 Plan 069 阶段 E 消费、正式复验；M4-S1 已取得最终 PASS。

| 设施 | M4-A 责任级结论 | 第四期消费边界 |
|---|---|---|
| Session/thread lineage | **直接复用** | Session、Root 与 child 关系继续由原生 metadata、fork 与 resume 语义拥有；不得另建 Session 身份 |
| ThreadStore active-writer | **架构内扩展** | 复用 canonical Root 的排他生命周期；S1 让不可伪造的 Root authority 连续覆盖 Team durable commit，不另建 Team lock/lease/registry |
| V2 Agent graph/residency | **直接复用并架构内扩展** | 保留 open member 身份与按需 reload；补足 durable Team identity 与所选 reload 上下文，不保存运行中的 child runtime |
| Team State | **直接复用 canonical 语义并新建专用 durability/read 能力** | 新能力集成在同一权威域，只承载 Team State 的持久提交/恢复/读取，不复制第二套 Team State |
| app-server v2 / TUI | **架构内扩展** | 只投影权威状态并调用领域能力；不成为状态源或通用 dashboard |
| feature/config gate | **架构内扩展** | 增加连贯的 opt-in 组合和 fail-closed 依赖；具体配置形状由消费包决定 |
| Git/worktree 观察 | **直接复用，正式 trust 按条件扩展** | W0 仅使用调用者预置 worktree 与系统 Git 做价值原型；W1 若获 GO，再补足正式 trust/binding 缺口 |

Codex 桌面端 managed worktree、Local/Worktree Handoff、快照和清理不属于冻结 CLI 可复用基线。第四期不移植 Project、queue、
dashboard 或 `/cd`，也不建设第二套 Team State、writer authority、Session 生命周期或控制面状态源。

### 2.2 身份、authority 与耐久结果合同

- 一个 V1 Root Session 使用三类职责明确的身份：`SessionId` 标识 durable Session/root lineage，canonical Root `ThreadId` 锚定原生
  生命周期与 writer authority，`TeamInstanceId` 标识该 lineage 上唯一的 canonical Team 实例；child 有自己的 `ThreadId`，但不
  形成新 Session 或 Team。当前 root 上 `SessionId` 与 `ThreadId` 可同值转换只是实现事实，不是永久表示合同。
- resume、V2 residency reload 与 member reload 恢复同一组三类身份。顶层 `thread/fork`、`/new` 与 slash `/clear` 创建新的
  Session、Root 和空 TeamInstance；`spawn_agent fork_turns=none/all/N` 只改变 child conversation context，始终留在原
  Session/root lineage 与 TeamInstance。旧 Team 引用跨实例 fail-closed，不 remint、不映射、不克隆 Team。
- Team State 继续拥有 Event、Version、route、Fact 等 canonical coordination 语义。S1 的专用 durability/read 能力只负责其跨进程
  定位、持久提交、兼容与恢复结果，不接管 thread history、Agent graph、模型、工具或 Git 资产。
- canonical Root lineage 同时只有一个 Team 写 authority。Root/child mutation 都必须证明 participant 资格并使用同一个 Root
  authority；Team 可以有多个 writer Agent，但它们共享这一进程级资格，child Thread writer 本身不授予 Team 写资格。现有 Root
  active-writer 是唯一排他基础，但须在架构内扩展，使其从
  mutation 开始连续覆盖 durable commit 和成功返回；一次性检查、锁文件探测或另一套 Team writer 体系均不合格。
- canonical mutation 只有在对应结果已可恢复时才能返回成功。不推进 Team revision 的独立状态轴也必须有等价的成功边界；共同
  合同不要求它们共享同一 revision。authority 丢失、提交结果无法判定或 durable 后端不具备排他能力时返回
  conflict/unknown/unavailable/unsupported，不把内存成功冒充 durable 成功。
- 查询只返回一个满足领域不变量的已提交视图；允许明确标记旧视图，或返回 stale/unknown/unavailable，不得把不同提交边界拼成
  当前事实。只读不要求取得 writer authority，但不得绕过 canonical durable read model。
- 正常 owner/Team close 完成必须同时证明应持久的 Team/thread 状态达到承诺边界、所有 descendant runtime 已不再具备提交 Team
  mutation 的能力，且 Root authority 已释放。只要仍有 mutation-capable descendant，close 就必须保持 closing/failed，或在同一
  barrier 内先将其安全 quiesce/close；下游自主选择机制，但不得先释放 authority。持久化或 session task 失败时保留可重试对象，
  不伪报完成；若下游复用显式 discard，它必须单独确认可能丢失未持久数据，不能冒充正常关闭。完整进程退出由操作系统最终释放
  进程锁，但后续加载仍须验证 durable 状态。
- durable marker 与后端不一致、数据缺失/损坏/版本不兼容、lineage 无法证明或 TeamInstance 不匹配时 fail-closed；只有可独立
  验证的兼容部分可显式只读降级，绝不静默创建空 Team、换新 ID、退回内存状态或写另一份存储。
- 在线 canonical mutation 只由持有 Root authority 的已加载 owner runtime 执行；未连接 owner 时控制面只读并报告 unavailable。
  archive/unarchive/delete 走 Codex 原生冷态生命周期能力，不要求先加载 Root，不强制接管活跃 writer，不建设 relay、queue、
  IPC router、补偿事务或 takeover。

### 2.3 与 Codex 对齐的生命周期矩阵

| 操作/现场 | Durable Team V1 语义 |
|---|---|
| resume / member reload | 恢复原 Session、Root、TeamInstance 与自洽 committed Team；V2 只恢复 open member identity/metadata，child runtime 按需 reload，不自动开始 model turn/API |
| 顶层 `thread/fork` | 原生 history 按分叉点复制到新 Session/Root 与新空 TeamInstance；来源 Team 不变，旧 Team 引用在新实例 fail-closed |
| `spawn_agent fork_turns=none/all/N` | 新 child Thread 仍属原 Session/root/Team；参数只决定 conversation context 的无、全量或有界继承 |
| `/new`、slash `/clear` | 新 Session/Root 与新空 Team；原 Session/Team 保留可 resume |
| 纯终端/UI clear | 只清展示，不改变 Session、Team 或 authority |
| TUI switch/unsubscribe、客户端断开（即时） | 只解除附着，不立即 close/unload Team，也不改变 authority |
| 零订阅后的 deferred idle unload | 是独立生命周期动作，必须按对象走 member unload 或 owner/Team close barrier。若目标是 owner/Root，任一 mutation-capable descendant 都会阻止完成和 authority 释放，除非在同一 barrier 内已被安全 quiesce/close；submit failure/timeout 保持 loaded/closing 且不得交接 authority |
| member residency unload | 只卸载满足既有安全条件的 child runtime，保留同一 Session/Team 身份与可恢复 metadata；不 close Team，也不释放 Root authority |
| 正常 owner/Team close | durable Team/thread 边界完成、所有 descendant 已失去 Team mutation 能力且 Root authority 释放后才完成；任一条件失败都保持 closing/failed 并可重试 |
| 存活进程内 session task/shutdown 失败 | 不等同进程退出，不移除唯一可重试 owner，不允许第二 writer 接管或伪报关闭 |
| 完整进程退出 | OS 最终释放进程持有的 writer；所有已报告成功的 Team mutation 下次必须可恢复，未确认提交仍按 unknown/failure 处理 |
| archive Root | 走原生 Root/subtree 路径；Root archive 成功后 Team 保留原 ID 并只读 archived。descendant 部分失败须逐项暴露 |
| unarchive Root | 恢复原 Root 与 TeamInstance；不发明整棵 descendant 批量复活，部分结果按原生事实展示 |
| delete Root | 只有 Root/subtree 与对应 Team durable 删除结果均可确认时才 terminal；部分完成或未知不得展示为正常删除/恢复，也不 re-ID |
| 缺失、损坏、不兼容、lineage/instance mismatch | 显式 unavailable/unsupported 或仅对可验证部分只读降级；不创建空 Team、不重铸旧 ID、不切换状态源 |
| 无 Durable Team marker 的 legacy Session | 保持既有 transcript/thread read/resume，明确为 legacy/non-durable；不冒充恢复 Durable Team，也不自动升级身份 |

### 2.4 启用组合

所有第四期新能力默认关闭，关闭态不改变既有单 Agent、V1、V2、进程内 Team、shared workspace、app-server 或 TUI 行为。

| 有效组合 | 用户可观察结果 |
|---|---|
| MultiAgentV2 关闭，或 Team State 未有效启用 | 保持既有行为；不能创建或恢复为可写 Durable Team。若控制面能独立验证已有兼容 durable 数据，只可只读展示 |
| MultiAgentV2 + Team State 开启，Durable 关闭 | 新的非 durable Session 保持当前进程内 Team State；已有 durable marker 的 lineage 只读或拒绝可写 resume，不能创建空内存 Team 覆盖原实例 |
| MultiAgentV2 + Team State + Durable 开启，且 durable backend 与 canonical Root authority 可用 | 可创建/恢复可写 Durable Team；任一必要能力缺失即 activation/start fail-closed，不静默降为内存 Team |
| Control Surface 开启或关闭 | 可独立开启作历史 durable Session 的只读发现/展示；在线 mutation 仍要求 owner 与上述依赖。关闭时 Durable runtime 仍可经既有领域入口工作 |
| W 关闭 | shared workspace 与既有权限行为不变；已有兼容 binding 只能按消费包明确的只读语义展示，不影响 S/C |
| W0 原型开启 | 仅以预置 worktree 和 deterministic/fake 验证价值，不获得生产 trust/binding 保证；正式 W1 还需要 binding GO、S1 接缝和所选 W-only 增量 |
| 正式 W1 开启 | 仅在 W0 binding GO、MultiAgentV2 + Team State + Durable 与 S1 接缝均成立时合法；否则 fail-closed，不保存孤立 binding、不回退父 cwd |

具体配置 key、解析顺序、backend/格式、crate/module、API/wire、锁/permit、read token、snapshot、一致性标识、调用/重试顺序、
分页、通知、binding/handoff 字段和测试 fixture 均由唯一消费包决定，不属于共同合同。

## 3. 工作包

### M4-A：共同产品合同、生命周期边界与上游增量决策

**结论：`M4_A_GO`。** 当前架构存在一条不重复建设权威体系的合理路线：直接复用 lineage 与 canonical Team State，架构内扩展
Root active-writer、V2 reload、控制面和 gates，并为 canonical Team 增加窄的 durability/read 能力。M4-C0 已完成实验性纵向原型；
M4-S1 已完成阶段 E 并取得 `M4_S1_PASS`；M4-C1 已完成正式只读查询并取得 `M4_C1_QUERY_PASS`；Plan 078 / M4-S2 已完成并取得
`M4_S2_PASS`；
M4-W0 继续按自身条件推进，正式 W1 仍等待 W0 binding GO，且可复用现已成立的 M4-S1 持久接缝。

**上游候选决定**（均不在 M4-A 实施；除下表明确归入消费包独立前置阶段的 `#37847` 外，仍建立独立回移任务）：

| 候选 | 决定 | 消费包与进入主线条件 |
|---|---|---|
| `#37847` reload environment | **采用窄回移**；修复 V2 member eviction/reload 丢失 inherited environment 的当前缺口，保留显式 override 优先，不承担 Team durability、W binding 或新环境管理体系 | Plan 078 独立前置已完成聚焦验收并进入本地 `main`，M4-S2 已消费并取得 `M4_S2_PASS`；不阻塞 S1/C0/C1/W0 |
| `#37198` persisted cwd read consistency | **Plan 074 已完成窄回移，Plan 069 阶段 E 已完成消费与正式复验**；ThreadStore 按已持久事实投影 cwd，不替代 live binding 重验 | M4-S1 与 M4-C1 已消费该持久读取事实；W 后续只按自身边界消费 |
| `#39616` linked-worktree trust | **条件延期并按 RONDO 边界适配**；W0 可用临时 Git 只证明产品价值，不得声称生产 trust | 仅当 W0 给出 binding GO 且 W1 消费 linked-worktree project trust 时采用；须在 M4-W1 开始前进入主线，永不阻塞 S/C |
| `#39153` permission restore | **条件适配，不直接照搬 fallback**；保留显式 override 优先，但 durable binding 的权限缺失/不兼容必须 unavailable/replacement | 仅在 W0 binding GO 后立项；若 W1 采用，须在 M4-W1 PASS 前进入主线，永不阻塞 S/C |

**M4-S1 当前交接**：Plan 069 以第 2 节的三类身份、Root authority、durable success、自洽读取、关闭/失败与在线/冷态责任为输入，
已经实现 canonical Team durability/read 专用能力及 Root writer 的架构内扩展，并覆盖 Root/child 双进程竞争、authority 丢失、损坏
lineage/state、只读非 owner、shutdown 失败及 live child close barrier。阶段 E 又在同一 fresh Session/store 产品链中闭合异常进程退出、
同 identity cold resume、继续 mutation、正常 close 与 persisted read/live override 分工，最终独立终审无高/中等级 finding；介质、格式和
模块/API 仍只是 Plan 069 的实现选择，不上升为通用平台或新的长期权威体系。

**M4-C0 已完成的原型输入**：Plan 070 以同一身份与生命周期矩阵验证了 Session/Team 只读发现、owner 在线操作、代表性 Root-only
cold unarchive、stale/result-unknown 与权威重读，结论为 `M4_C0_PROTOTYPE_PASS`。原型状态按 identity、domain lifecycle、runtime
residency、operation availability、freshness/certainty 与 provenance 分轴；state-DB/prototype input 不冒充 S1 durable read model，
experimental capability 也不替代默认关闭的产品 gate。

**M4-W0 可直接建计划的交接**：只用调用者预置、授权的本地 worktree 和系统 Git，以 deterministic/fake 比较自然语言流程与
binding/replacement/minimal handoff 的产品价值；不依赖生产 S1，也不借用 `#39616` 作权威 trust。W0 自主选择可丢弃原型形状，最终
只能给出 `BINDING_ONLY_GO`、`BINDING_HANDOFF_GO`、`NO_GO` 或 `INCONCLUSIVE_DEFER`；它不实施 W1、不预选正式字段/API，
任一结果都不阻塞 S/C。

### 子线 S：Durable Team Session（必成主线）

#### M4-S1：Team Session 持久生命周期

**当前状态：`M4_S1_PASS`。** Plan 069 已精确消费包含 Plan 074 / `#37198` 窄回移的 `main@62d3ed7`，完成版本化、checksummed
canonical Team snapshot/read/reconcile、typed Root `SessionMeta` lineage、单一 Root authority、默认关闭配置、跨进程 cold resume、
非 owner committed read 与最小 close barrier。从全新 Session/store 执行的阶段 E 正式链及 persisted cwd/live execution override
聚焦回归通过，最终独立终审无高/中等级 correctness finding。

**目标**：让已确认的 canonical Team State 与权威 Root lineage 绑定，并以其单一写 authority 约束可写 Team runtime；mutation
成功后对应状态可恢复，非 owner 能读取自洽的已提交状态；进程退出后仍能定位原 Team Session，并在重新取得写 authority 后加载为
可写状态。

**边界**：只持久化恢复团队语义所需的状态；不保存完整 transcript、reasoning/CoT，不恢复运行中的模型请求、工具调用或
外部副作用，也不把 Team State 塞入单个 thread 的历史充当第二份真相。职责契合时复用所选持久介质的正常提交/快照能力；若其
不足以满足自洽读取合同，ExecPlan 可以选择与现有架构契合的必要读能力，但不形成第二份只读状态源。

**已满足的代码前置**：Plan 074 已把 `#37198` 的 RONDO 窄回移送入指定主线，Plan 069 阶段 E 已完成消费与 ThreadStore read/list
persisted cwd、live execution override 聚焦回归。该增量不替代 Team durable read model 或 W binding 重验。

#### M4-S2：恢复与生命周期收口（Plan 078）

**结果：`M4_S2_PASS`。** Durable Root cold resume、V2 member lazy reload、顶层 fork/new/clear、同 Team child fork、detach/idle unload、
descendant-first close、异常退出与 archive/unarchive/delete 已按原生 Session/ThreadStore 生命周期闭合。失败关闭保留可重试 owner，
late cleanup 使用 exact owner/generation，不会误清 replacement 或提前释放 Root authority；旧版、损坏、身份不一致与部分冷态结果均
fail-closed。外部终审无剩余高/中 correctness finding，详细证据见 `doc/WBS-COMPLETED.md`。

**目标**：按第 2.3 节完整处理 resume/member reload、顶层 `thread/fork`、`spawn_agent fork_turns`、`/new`、slash `/clear`、客户端
detach、正常关闭、完整进程异常终止、archive/unarchive、delete、旧 session、不兼容或损坏状态，使恢复或分叉后的团队身份、权限和
canonical 状态符合原生 Session 语义，无法确认时明确降级或拒绝。

**边界**：不建设多机、复制、高可用、共识或通用事务平台；可选 writer binding 的失败只影响对应 writer，不默认阻止 Team/root
read model 被定位、查看和恢复，也不自动启动其他成员。V2 Root resume 只恢复 open descendant 的身份/metadata，child runtime 按需
reload，不能把旧式 Agent 路径的自动 reopen 行为扩大为本期合同。顶层 `thread/fork` 从新空 TeamInstance 开始；`spawn_agent
fork_turns` 创建的 child Thread 仍属于原 TeamInstance。旧 Team 引用 fail-closed，不建设 Team clone/branch、ID 映射、历史成员
档案或跨 lineage Fact 恢复。只有成功 teardown 或完整进程终止实际释放写 authority 后才允许后续写 owner 接管；存活进程内
shutdown/session-task 失败保持 closing/failed 且可重试，不实现强制接管。
Root/Team close 还必须在释放 authority 前证明所有 descendant 已失去 Team mutation 能力；S2 可阻止 close，或在同一 barrier 内
安全 quiesce/close descendants，但不建设新的 descendant registry 或通用 shutdown 平台。

**子线出口**：新建、推进、顶层 `thread/fork` 到新空 Team、`spawn_agent fork_turns` 新建同 Team child、detach、关闭、进程终止、
恢复、archive/unarchive 与 delete 的生命周期可以稳定重复；失败关闭不伪报完成，恢复和 member reload 不自动触发模型/API，且
功能关闭态无回归。

**PASS 前置**：Plan 078 的独立前置阶段已把 `#37847` 的 RONDO 窄回移送入主线，V2 member residency reload 在显式 override
优先的前提下保留 inherited environment；该增量不自动启动模型/API，也不承担 Team durability、W binding 或新环境管理体系。

### 控制面子线 C：Session app-server v2 / TUI（必成主线）

#### M4-C0：实验性 Session 协议与 TUI 原型（已完成）

**目标**：在 M4-A 的职责边界上验证 Session、Team 和恢复状态的基本查询、操作流与展示方式，为正式控制面拆包提供真实输入。

**结果：`M4_C0_PROTOTYPE_PASS`。** 默认关闭的 experimental app-server v2→app-server client→TUI 纵向流已经闭合；查询不激活
Session，在线 mutation 只路由 current/running canonical Root owner，cold unarchive 只由 fresh prototype projection 证明 Root 后调用
既有权威入口。lag、disconnect、EOF 与真实 response loss 会失效投影或进入 result unknown，不自动重放 mutation；稳定双键 cursor、
DB unavailable/incomplete、ChildOnly、archived child 和关闭态均有聚焦回归。

**边界**：C0 不承诺稳定公共 API 或正式 TUI 验收。所有新增接口只进入 app-server v2 并保持 experimental；控制面不复制
Team State 或 Durable Session，不把 Team Lens 离线结果变成在线状态源，也不建设通用 project/session/task dashboard、
queue dispatcher 或 daemon-wide agents 管理面。只读查询不要求取得写 authority；在线 canonical Team mutation 交给持有写
authority 的 owner runtime，未连接 owner 时返回 conflict/unavailable。archive/unarchive/delete 等冷态生命周期调用权威领域能力，
不要求先加载 Root。控制面不得绕过领域能力直接写持久介质、伪造成功或建设跨进程 mutation 转发平台；TUI unsubscribe、切换或
断开的即时结果只解除附着，但零订阅后的 deferred idle unload 必须调用同一领域 close barrier；存在 mutation-capable descendant
或其他失败时展示 loaded/closing/failed/unknown，且不得交接 Root authority。

**正式拆包输入**：本段形成时点的 Session query 输入已经由 M4-C1 消费；prototype input 不再是正式事实。Session control/TUI
现可基于 M4-C1 query 与 M4-S2 lifecycle 另行立项，并保留 loaded-owner routing、expected-state conflict、result unknown/no replay
与显式重同步
语义；C0 的 RPC、字段、固定 timeout、命令布局和通用 `thread/unarchive` preflight 均不冻结为正式合同。

#### M4-C1：正式 Durable Session Query（Plan 077，已完成）

**结果：`M4_C1_QUERY_PASS`。** 默认关闭的正式 app-server v2→client→TUI 查询链已经基于 canonical persisted `SessionMeta`、
durable marker 与同一完整 committed Team snapshot 闭合。它可在进程重启后有界发现 active/archived Durable Session，分轴展示
Session/Root/Team identity、domain lifecycle、runtime residency、operation availability、provenance 与 freshness；分页 continuation、
source change、损坏、不完整和 backend unavailable 均保守降级，不把不同一致性边界拼成当前事实。

**边界**：查询不加载或恢复 Agent/Session，不取得 writer authority，不启动模型、工具或 API，也不产生 Team mutation。state DB
只定位候选，prototype input 不作为第二份正式状态源；C0 control 继续由独立 gate 和 `/session-control` 入口保护，query-only 配置
不会暴露控制操作。具体 RPC 字段、TUI 布局和内部接缝仍是当前实现，不扩张为通用 registry、dashboard、查询缓存或分页平台。

**交接**：Plan 078 的 `#37847` 前置与 Plan 077 / M4-C1 已先期进入主线；M4-S2 随后完成产品验收，并作为后整合者保留 query read
与 lifecycle write 两侧语义、收敛 shared 接缝。Plan 080 / M4-C2 已消费该交接，并在改产品代码前完成合并树 query×lifecycle
基线 `45/45`，最终候选的同组邻接回归为 `47/47`。

#### M4-C2：正式 Session Control / TUI（Plan 080，两轮整改待复验）

**当前结果：整改实现完成，等待独立复验重判。** 默认关闭的稳定 app-server v2 `session/control`→client→TUI 正式链已闭合。
committed online proof 绑定 live Root owner incarnation；Team mutation gate 与 M4-S2 close barrier 在线性化点复验 exact owner、
instance/revision/commit generation。loaded Root close 只承诺 `OwnerClosed`；cold archive/unarchive/delete 复用 ThreadStore 原生生命周期，
Delete partial 只允许用户在权威重读后显式消费 canonical Root retry anchor，不加载 Agent 或启动 turn/模型/API。

client/TUI 使用 send-once attempt、accepted-read ticket、确认与 typed Applied/Rejected/Partial/Unknown；response loss、timeout、
disconnect、lag、detach、attachment replacement 或 late completion 不自动重放或覆盖新视图，操作后只用正式 query 重建。query/control
gate 独立默认关闭，C0 prototype 保持隔离。TUI 在确认前校验 authority/target 并显示 Session/Root/目标范围，只关闭 control 不 detach
query。fresh Session/store 正式轮覆盖 owner close、cold archive/unarchive、进程重启重建与 delete；首次独立审查发现的 2 High、
5 Medium、1 Low 已完成整改。整改收口复核追加发现的 teardown 后 Team completion 故障也已闭合：不可回滚分支终止 Session loop，
app-server 只移除 exact owner mapping 并保留 replacement，结果保持 typed Unknown。后续复验追加的 residency availability、accepted
handoff terminal unknown、Close/Archive direct race、exact cleanup 与 owner 错误分类亦已形成实现和 13/13 直接回归。当前等待复验确认没有剩余 correctness finding。

**目标**：消费 M4-C1 的权威 Session Query 与 M4-S2 的正式 lifecycle，通过 app-server v2→client→TUI 公开允许的在线 owner 和冷态
Session 控制；操作后、断线、重启、冲突或结果未知时只用正式 query 重建视图，不维护第三份控制状态。

**边界**：在线 mutation 只路由 current canonical Root owner，并由 server 最终核对 identity、generation/state/revision；cold
archive/unarchive/delete 等操作只调用 M4-S2/原生领域能力，不为控制加载 Agent 或启动模型/API。结果未知不自动重放，detach 不等于
unload，deferred unload 与 close 继续服从 close barrier。Plan 080 不建设 relay/queue/daemon manager/第二套 registry，也不实施
M4-W0/W1 或 M4-Z(core)；具体 RPC、DTO、timeout、操作布局和 TUI 交互由 ExecPlan 与 live code 决定。

**出口**：正式控制链、query×lifecycle 合并树回归、fresh Session/store 正式轮和独立终审通过，且 query-only、control-off 与
non-durable 路径无回归，结论为 `M4_C2_CONTROL_PASS`。

**正式 C 线出口**：操作者可以通过公开 app-server v2/TUI 查看和控制允许的 Team Session 生命周期；断线、重启或结果未知后能从
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
M4-S1（M4_S1_PASS）+ M4-C0（M4_C0_PROTOTYPE_PASS）
├─ M4-C1（M4_C1_QUERY_PASS）
└─ M4-S2（M4_S2_PASS）

M4-C1 + M4-S2 → M4-C2 / Plan 080（两轮整改完成，等待独立复验）→ M4-Z(core)（验收后下一必成工作包）

M4-A → M4-W0（原型/价值门）
M4-W0 binding GO + M4-S1 → M4-W1 开始
M4-W1 实现 + M4-S2 → M4-W1 PASS → 可选 Workspace 控制面扩展
M4-W0 NO_GO/INCONCLUSIVE_DEFER ────────────────→ 不阻塞 M4-Z(core)

条件增量边：
#37198 RONDO 窄回移（Plan 074 已完成）→ M4-S1 阶段 E（已完成）→ M4_S1_PASS
#37847 RONDO 窄回移（Plan 078 独立前置已进入 main）→ M4-S2（M4_S2_PASS）
M4-W0 binding GO + W1 消费 linked-worktree trust → #39616 适配 → M4-W1 开始
M4-W0 binding GO + W1 消费 permission continuity → #39153 fail-closed 适配 → M4-W1 PASS
W-only delta ─/→ S/C
```

- M4-A 已以 `M4_A_GO` 串行完成，S/C/W 共同采用第 2 节身份、生命周期、authority 与启用合同。
- M4-C0 已完成并提供拆包输入；Plan 074 / `#37198`、M4-S1、M4-C1 与 M4-S2 已完成。Plan 080 已在合并树补跑 query×lifecycle
  基线、完成正式控制链和 fresh store/restart 场景，并收口两轮独立审查整改；当前等待复验，接受后 S/C 必成子线才进入另行立项的
  M4-Z(core)。M4-W0 继续按自身条件推进。
- M4-W1 只在 binding GO 后开始，并等待 M4-S1 以复用持久接缝；最终 PASS 必须消费已完成的 M4-S2 并把
  resume/replacement binding 收口纳入自身出口，不存在无编号的后置收口包。
- M4-Z(core) 只依赖 S/C 主线。W 若已经进入主线，由后完成者拥有一次兼容验收；W 未进入主线时不制造空实现或占位平台。
- 各工作包内部的模块、测试和审查并行度由对应 ExecPlan 根据当时源码决定。Plan 078 已完成 core/thread/session 的 reload、
  resume、close 与冷态生命周期并收敛 shared read/write 接缝；后续任务只消费其已验收领域能力，不复制第二套生命周期设施。

## 5. 四期与三期的关系

### 5.1 产品与工作包依赖

- 四期不依赖 Publication Critic 模型、训练数据、真实权重、部署资格或横评结果；三期后续工作也不依赖第四期完成。
- 三期 Plan 060/M3-B1b 的 `TECHNICAL_GO`、Plan 064 的 `DATA_GO` 与 Plan 066/M3-B1c 正式训练和验收均已完成；计算 Pod 已删除，
  当前没有活跃云训练任务。后续 M3-C* 仍须各自规划和授权，但与四期没有产品前置关系。
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
| 四期规划、源码研究、文档、轻量实现与非重型测试 | 开发用 Codex、普通 CPU/内存 | 可与三期非重型工作或未来另行授权的云任务并行；不产生 RONDO API/模型费用 |
| M4-W0/W1 临时 Git 正确性验证 | 临时 repository/worktree、普通磁盘 I/O | 不需要真实模型、API、Docker 或长期 Git 资产；可与非重型 S/C 工作并行 |
| 四期 Rust 重型构建或测试 | 仓库共享 Cargo build lock、本地内存与磁盘 | 每批先由用户明确批准并人工调度；获批后所有 worktree 全局串行，按根 `AGENTS.md` 与 Docker、真实本地模型加载/推理互斥 |
| 三期未来另行授权的真实 API 数据合成或横评 | 中转 API 预算与网络 | 不占 Cargo build lock，可与四期开发并行；范围、费用和授权与开发用 Codex 额度完全分开 |
| 三期云端训练（当前无活跃任务） | 未来任务另行授权后使用的云 GPU、预算与工件传输 | M3-B1c 已完成且计算 Pod 已删除；未来任务不占本地 Cargo build lock，但工件传输仍竞争本地网络和磁盘，按实际压力错峰 |
| 三期 M3-C1/M3-C2/M3-D 本地模型与测评 | 本地模型/GPU、可能的 Docker、测评数据与已授权 API | 与四期重型 Cargo、Docker 和其他真实本地模型任务按根资源门禁串行错峰 |
| 任一方向的 Docker 工作 | Docker、本地磁盘和宿主容量 | 第四期默认不需要；若具体任务确有必要，须单独授权并与重型 Cargo、真实本地模型互斥 |

第四期适合把 S、C、可选 W 原型、源码研究、测试设计和审查组织成若干**有界并行**流；共享 core/protocol/TUI 接缝、主线整合
和全局 Cargo build lock 限制同时编码的主线数量。后续 Cargo、clippy、生成器及其它会读写 Rust target 的命令不得由执行者
自行排队：执行者先报告准确命令批次、写集、069 target 与当前资源事实，由用户明确批准并人工决定运行时机；canonical lock/watchdog
只是获批后的 fail-closed 兜底。工具链/profile/features 不兼容时不得静默创建第二个大型 target；先按当前空间事实评估增量重建。
开发用 Codex 额度不等于 RONDO 产品 API 额度；具体资源阈值和看门狗入口统一引用根 `AGENTS.md`，本 WBS 不复制容易漂移的数值。

## 6. 调试与验收原则

- 每个工作包开始前建立独立 ExecPlan，只定义该任务的目标、边界、当时架构接缝和验收，不在本 WBS 预写实现细节。
- 调试阶段保留已验证进度和可恢复现场，从第一个未打通处继续修复；完整产品链打通前不冻结公共 API、持久格式、配置或正式结果。
- S/C 核心链打通后，记录正式验收使用的准确代码与配置版本，稳定必要的外部兼容边界，再从干净的本地 Session/store 状态
  完整运行一轮。这里不永久冻结内部代码、配置结构或持久格式；具体返修与复跑循环由 M4-Z(core) ExecPlan 决定。
- 每个工作包先满足就近 `AGENTS.md` 要求的强制测试、生成物和 TUI snapshot 测试门禁；M4-Z(core) 额外运行相称的 S/C 干净全链验收。
- M4-S1/S2 的 ExecPlan 必须以相称的 deterministic/fake 回归覆盖本 WBS 的耐久成功、单写 authority 覆盖提交、自洽读取、失败不
  伪报完成、Root idle/close 与 mutation-capable live child 的 barrier，以及顶层 `thread/fork` 与 `spawn_agent fork_turns` 的不同
  Team 语义；具体 fixture、竞态 interleaving 和版本标识由任务方案根据真实接缝决定，不为验收建设审计、通用事务或第二套
  跨进程协调平台。
- M4-W0/W1 使用临时 Git repository/worktree 和 deterministic/fake 测试；若 W1 落地，由其自身出口按价值门范围承担完整 binding
  及可选 minimal handoff 验收。
  第四期不新建或运行性能测评。

## 7. 宏观验收

### 7.1 第四期核心 PASS

- 原 Team Session 在进程退出后可以恢复并继续协作；无法恢复时不会被空团队或虚假成功掩盖。
- app-server v2 与 TUI 从权威领域状态展示并控制 Team Session；断线或重启后可以重新同步，不维护第三份状态。
- canonical Root lineage 同时只有一个有效 Team 写 authority，且该 authority 持续覆盖 mutation 的成功提交；第二个进程不能取得
  重叠 authority 或成功提交，单独 resume child Thread 不能绕过 Root 归属提交 mutation。其他客户端仍可只读查看；原 authority
  实际释放后，后续 owner 才能取得写资格。
- 非 owner 并发查询只返回满足领域不变量的自洽已提交状态，或明确 stale/unknown/unavailable；不会把不同一致性边界拼成当前事实。
- persistence shutdown 失败、session task 异常或存活进程内 teardown 未完成不会被报告为关闭完成，原写 authority 仍可定位并重试；
  mutation-capable descendant 存活时同样不得完成 Root/Team close 或释放 authority。只有成功 barrier 或完整进程终止实际释放
  authority 后，其他进程才能接管。若实现范围包含显式 discard，其结果也必须确认 authority 已释放且不得冒充正常关闭。
- resume/member reload 保留原 TeamInstance；顶层 `thread/fork` 让原生 conversation/thread history 按 Codex 规则进入新的 Root
  Thread/Session，并从新的空 TeamInstance 开始，来源 Team 不变，旧 Team 引用 fail-closed。`spawn_agent fork_turns` 创建新的 child
  Thread 但保持原 Session/root lineage 与 TeamInstance；`/new` 与 slash `/clear` 同样创建空 Team，detach 不改变生命周期。
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
- Team 专属 `reset`、顶层 `thread/fork` 时的 Team State 继承、Team clone/branch、ID remint/rewrite 或 old-to-new mapping、历史
  contributor 档案、跨 lineage Fact 恢复、route/wake/retry 克隆、revision/turn 时间旅行、自动重启全部 descendant 或批量复活
  Agent subtree；
- 保存或广播完整 transcript、reasoning/CoT、terminal 输出或 Fact 正文；
- 浏览器后台、远程 SaaS、多用户账号、复杂鉴权、审计/可信平台、严格全局因果或数据资产审计；
- 完整上游基线升级，或任何为第四期新增的真实 API/模型调用、训练、横评、benchmark 与 RONDO 推理成本。
- 与 canonical Root lineage 写 authority 相互竞争的第二套 Team lock、租约、独立存储写入器或 writer registry，以及强制接管、
  抢锁、跨进程 mutation relay/queue/IPC router。第 2 节已选择的专用能力必须集成在既有权威域内，不得形成第二套权威或静默
  回退路径。

## 9. 实施与授权边界

本文只是长程 WBS，不是实施授权。M4-A、M4-C0、Plan 074 / `#37198`、M4-S1、M4-C1 与 M4-S2 已完成；M4-C2 两轮整改实现已收口并等待
独立复验，结论分别见本节和 `doc/WBS-COMPLETED.md`。M4-W0、M4-W1 与 M4-Z(core) 继续服从本 WBS 的条件边；每项实施仍须确认
当时主线、并行 worktree 与授权范围。

Plan 078 已消费 `#37847` 与 M4-C1 最新主线，完成 shared query/lifecycle 接缝收敛并取得 `M4_S2_PASS`。Plan 080 / M4-C2
随后完成合并树 query×lifecycle 回归和正式 Session Control/TUI，并完成两轮独立审查整改；当前等待复验重判。其它上游窄回移仍各自
建立独立任务合同，并按第 3 节条件消费边进入主线；M4-W1 只有在 M4-W0 形成 binding GO 且 M4-S1/M4-S2 接缝成立后才可立项；
可选 Workspace 控制面扩展再等待 M4-W1 PASS，完整基线升级仍是独立方向。

普通第四期实现不需要外部或付费行为；如果具体任务扩展到真实 API、模型、训练、Docker、上传或其他外部状态，必须单独说明
范围并重新授权。
