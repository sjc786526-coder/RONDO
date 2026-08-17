# Multi M-2 选择性路由纵切 ExecPlan

> 本计划是本任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述 Multi M-2；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在已经合入 `main` 的 M-1 团队世界状态之上，完成 RONDO Multi 的选择性路由真实产品纵切，证明团队信息可以按
Root 的判断跨 Agent 流动，同时始终只有一份 Harness 持有的 canonical 团队状态：

> Root 选择一个 Event 路由给目标 Agent → canonical 可见性与工作指派先成立 → 投递紧凑通知 →
> 目标从团队状态读取完整 Version chain → 在同一 Event 下追加自己的 Version → Root 再次获得协调机会 →
> 指派按明确生命周期结束。

路由工具名、领域类型、状态表示、通知适配层、幂等实现、模块边界和必要的局部重构由执行者依据实时源码自主决定。
计划固定的是产品行为、失败语义和验收边界，不预先写死实现路线。

### 完成/验收标准

- [ ] 上述 Root/目标 Agent 链路通过真实 RONDO Multi Agent/session/team tool/communication/sampling/wait 接缝的
      无 API 集成测试可复现；纯领域状态机测试只能作为补充，不能代替产品纵切。
- [ ] Root 能以 Event 为单位向同一团队实例内的已登记目标授予不可撤销的可见性；可见性使目标能读取完整
      Version chain，并按第一版权限模型在同一 Event 下追加 Version，但不复制或分叉 canonical Event。
- [ ] 工作指派是有稳定身份和明确进行中/终态的 canonical 对象。相同逻辑 route 的重试不重复授予对象或创建
      指派；不同的合法指派仍可独立存在并分别结束。
- [ ] route 的 canonical 提交先让可见性和所需指派成立，随后才尝试通知。目标一旦收到通知，就已经能读取该
      Event、取得完整 chain 并执行被授予的贡献操作，不存在“通知已到但目标仍读不到 Event”的时序。
- [ ] 通知只携带完成定位和行动所需的紧凑标识/提示，不复制 Event 标题、summary、handoff 或 Version chain 正文；
      完整内容始终从 canonical 团队状态与既有有界历史查询获取。
- [ ] 通知失败不回滚已经提交的可见性或指派，也不伪装成整体未发生；失败在 canonical 状态或等价的权威结果中
      明确可见且可幂等重试。重复 route、重复通知重试及提交后失败都不得制造重复对象或破坏既有状态。
- [ ] 三种投递意图分别有产品级验收：目标正在运行时只排队，在既有安全边界进入其上下文且不另起一轮；目标
      空闲且工作指派要求开始/继续时触发下一轮；目标空闲但只是信息通知时只排队、不主动唤起。信息通知不应被
      强行等同为进行中的工作指派。
- [ ] 同一 Event 的多作者 chain 跑通：目标看到路由后的完整旧 chain，追加自己的 Version 后 Root 通过 M-1
      既有团队变化/wait 语义获得新的协调机会，并看到同一个 Event 下的完整新 chain。
- [ ] 结束指派后的活动视图严格服从 WBS 第 13 条谓词并成对验收：目标仍有自己的未终态 Version 或该 Event 下
      其他进行中指派时继续可见；没有任何活动理由时退出活动视图，但不可撤销可见性仍允许其通过有界查询读取历史。
- [ ] 并发与拒绝路径得到定向覆盖：至少包括相同 route 重试、相同通知重试、并发结束同一指派，以及结束一个
      指派但保留另一个活动理由；不得出现重复对象、丢更新、终态倒退或无关对象被批量改变。
- [ ] route 权限只来自调用 Session 的权威团队身份。非 Root 发起 route、未知/未登记目标、跨团队实例引用、
      未知调用身份和无权结束指派均 fail-closed；不能信任模型自报的 root/actor/target/team 字段。
- [ ] M-1 已验收的不变量继续成立，尤其是单一 canonical 状态、不可变 authored Version、追加式历史、request-only
      活动投影、同一 sampling 的 retry 快照一致性、可见性决定读写资格、Root wait 不丢变化和默认关闭能力。
- [ ] 必要的领域测试、并发/幂等测试和真实产品纵切测试通过；`just fmt`、`just fmt-check`、受影响 package 的定向
      lint/fix 与定向 Rust 测试通过。不扩大为全 workspace 测试，不用 Docker、真实 API 或本地模型冒充本阶段证据。
- [ ] diff、受保护文件和意外生成物检查完成；本计划状态、精炼 `agent_log/` 及 Multi 子 WBS 的 M-2 当前事实已
      同步；完整成果提交在本工作树分支后停止，未合并、未推送。

## 2. 范围

### 允许修改

- `multidev/` 中实现 M-2 所必需的 `codex-team-state` 领域状态、现有 AgentControl/通信/工具/投影接缝、构建清单、
  生成文件和定向测试。
- 为真实产品纵切所必需的最小局部重构；如果实时源码证明无法在 `multidev/` 内干净完成，可修改少量共享构建或
  测试接缝，但不得改变 RONDO Local/L6 的产品语义。
- 本文件、M-2 精炼 `agent_log/`，以及完成时 `doc/WBS/multi-agent-trusted-evidence.md` 中 M-2 的当前状态与证据。
- 任务所需的普通依赖处理和只读源码/文档查询；不包含真实外部服务写入或付费调用。
- TUI/app-server 不是计划交付面；只有实时产品链证明存在不可绕开的接缝时，才允许做最小必要修改，并同步对应
  schema、文档或 snapshot 门禁。不得借此扩展产品界面。

### 不允许修改

- 顶层 `doc/WBS.md` 与 `doc/WBS-COMPLETED.md`。两者正与 L6 并行集成，本任务不抢写，待 L6 集成后再窄同步。
- `mydev/`、`training/`、Local 测评设施、L6 plan/源码/测试/模型工件，以及
  `.claude/worktrees/037-l6-first-lora-paired-artifacts` 内任何内容。
- `codex-source-code/` 上游只读快照、冻结 `codex-doc/`、历史审计快照，以及既有历史 plan/log 的结论。
- M-3 的 Fact、证据索引与 observation 下钻；M-4 的 orphan 退休、状态转储和发布频率统计；M-5 的 runtime bundle、
  Docker、真实 API、付费运行与退化测评。
- Event 关系图、只读贡献档位、跨进程团队状态持久化、新调度器、第二套 Agent-to-Agent 通信协议、全局订阅、
  复杂 ACL/审计/可信体系或 shared workspace 协调。
- 上游基线升级、正式 eval campaign、结果账本、云端训练、模型上传下载或任何无关功能与重构。

### 不允许读取/查看

- `.env.local` 的内容；本任务不需要密钥，也不得打开、搜索、打印、复制或记录该文件。
- `rondo.local.toml` 的内容；本任务不依赖本机模型或 provider 配置。
- L6 worktree 的未提交文件、生成物、训练数据正文、模型权重、adapter、私有评测原件，以及其他项目外个人文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **隔离执行**：所有受跟踪编辑、格式化、构建、测试和提交只在
   `.claude/worktrees/040-multi-m2-selective-routing`（分支 `worktree-040-multi-m2-selective-routing`）进行。
   不进入或修改 L6 工作树；不回退、覆盖、stash、移动或清理来源不明的现有修改。
2. **语义来源与单一状态**：M-2 以 `doc/WBS/multi-agent-trusted-evidence.md` 的设计语义合同和 M-2 完成标准为准。
   Event、Version、可见性、指派及其投递状态只从每棵存活 Root 树的 canonical 团队状态派生；通知、prompt、
   history、rollout 或模型回复不得成为第二份事实来源。发现合同内部无法同时满足时才暂停请求裁决。
3. **提交先于通知**：同一 route 的可见性与所需指派必须在通知可能被目标观察前 canonical 提交成功。通知是提交
   之后的副作用；失败不得回滚或隐藏提交，重试不得重做提交或制造重复 canonical 对象；若底层是至少一次投递，
   重复紧凑通知必须可识别且不能破坏状态。
4. **可见性、指派与活动视图分离**：可见性一经授予不可撤销，决定读取与第一版贡献资格；指派有独立生命周期；
   活动视图只按 WBS 第 13 条谓词计算。结束指派只能撤掉对应纳入理由，不能删除历史或误伤其他理由。
5. **三种投递语义与既有执行面**：运行中排队、空闲工作唤起、空闲信息只排队三种行为不可互换；不得通过 interrupt
   冒充正常 route，也不得新建调度器、Agent-to-Agent 协议或全局订阅。具体复用哪一层既有通信 API 由执行者决定。
6. **身份与权限 fail-closed**：只有权威 Session 身份证明为当前团队 Root 时才能 route；目标必须是同一团队实例内
   已登记参与者。指派结束与通知重试同样只能由明确授权的权威身份执行；未知、矛盾、跨实例或模型自报身份均拒绝。
7. **真实纵切与范围内回归**：必须通过真实 RONDO Multi 工具与 Agent/session/communication/sampling/wait 接缝验证
   行为，不能只测领域 API。保留 M-1 已验收语义和关闭态；不得为凑绿弱化测试、安全、权限或时序断言。
8. **资源与外部边界**：不得直接运行 Cargo。Rust test/fix/clippy 等重型入口必须使用仓库现有、已接入根
   `scripts/with-build-lock.sh` 的 `just` 配方，使用项目根内受监控 target，并与 L6 本地模型/Docker及其他重型任务
   串行；拿不到锁、cgroup、Windows `C:` 实际余量或资源计数器时 fail-closed。禁止 Docker、真实 API、付费测评、
   本地模型加载/推理、训练、数据外发、远端状态修改、系统配置和全局工具链变更。
9. **允许自修复重跑**：普通编译、格式、fixture、时序或窄实现问题可以在范围内自行分析、修复并定向重跑，不因
   首次小失败就停止。只有触及原则性边界、需要未授权高危能力、计划合同必须变化、资源门禁持续不可满足，或多次
   合理尝试后仍存在实质阻塞时才暂停汇报；不得用重试绕过门禁或把 skip/未运行写成通过。
10. **提交交接**：完成后检查 diff、受保护路径、主工作区/各 worktree 现场及意外生成物，更新允许的任务记录，在
    工作树分支提交完整成果并停止。不合并 `main`、不推送、不删除 worktree，等待独立审查者验收。

## 4. 软性建议

以下内容是基于 `main@2f732405` 实时源码的高性价比建议，不是固定约束。执行者可依据代码、测试和复杂度采用更小、
更清晰或更可靠的等价方案，并在关键决策记录中简要说明重要取舍。

- 优先在既有 `codex-team-state` 内增量表达 Event 可见性、指派生命周期与可重试投递结果，并继续由
  `AgentControl` 共享同一个 `TeamStateHandle`；若实际依赖关系显示其他局部边界更清晰，可以调整。
- 模型工具可以新增窄 route 操作，并在既有 update 面或另一窄操作中结束指派/重试通知；名称、schema 和返回结构
  不预先规定。保持调用方负担小，稳定 retry identity 优先由 Harness 提供而不是要求模型记忆。
- 现有 `InterAgentCommunication`、submission queue、`trigger_turn`、Agent status 与 V2 residency 已覆盖大部分
  投递原语，可优先复用；紧凑 route 通知只需团队实例/Event/指派等必要定位信息与动作提示，具体最小字段由实现测试决定。
- 通知失败注入可以用小型可替换适配点或既有 test support 完成；第一版只需 session 内明确、可重试的状态，不需要
  持久化 outbox、消息中间件、分布式事务或复杂审计流水。
- route mutation 可一次性校验 actor、target、Event、retry identity 后提交，减少“半授权”状态；采用何种锁、enum、
  generation 或 receipt 表示由执行者选择，只要并发和幂等测试能直接证明不变量。
- 现有 `team_world_state.rs` 已较大。产品测试可新建聚焦 M-2 的 integration suite，领域测试也可按职责新分文件；
  这是可维护性建议，不要求为了形式搬迁既有测试。
- 先用窄领域测试站稳可见性/指派/幂等与活动谓词，再接通信三分支和完整产品链通常更易定位问题；若实现依赖更适合
  另一顺序，执行者可自主调整。
- 保持 `features.multi_agent_v2.team_state_enabled` 默认关闭通常最省兼容成本；除非真实接缝要求，不新增配置项、
  app-server wire API 或 TUI。若生成文件因实际 schema/依赖变化而更新，应使用仓库已有生成工具并审查差异。
- 定向门禁优先覆盖 `codex-team-state`、M-2 产品集成 suite、实际受影响的 core/通信用例和 scoped fix；不要因为
  `codex-core` 较大就机械扩大到全 workspace。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已核对根 `AGENTS.md`、`README.md`、顶层 WBS、方向 3 子 WBS、计划模板、M-1 ExecPlan/最终验收与实时源码接缝。
- 已确认 `main` 与 `origin/main` 均为 `2f732405`，主工作区干净；M-1 已验收并合入，M-2 前置满足。
- 已从 `main@2f732405` 创建本专用 worktree 与本地分支；未进入或读取 L6 worktree 内容。
- 已建立本 ExecPlan。
- **M-2 实现已完成**：
  - 领域层（`codex-team-state`）新增 `RouteId`、`TeamRoute`、`RouteDuty`（notice/assigned/ended）与
    `DeliveryState`（pending/delivered/failed）；route 提交逻辑单列 `store/route.rs`，沿用"先全量校验、
    再一次性提交"结构。第 13 条活动谓词补齐第三个纳入理由，`is_visible_to` 增加不可撤销 route 授权。
  - 幂等：`committed` retry 账本泛化为 `CommittedRequest`/`CommittedOutcome` 枚举，publish 与 route 共享
    同一 `(actor, request_id)` 命名空间，跨类型复用同一 retry identity 被拒绝；另外「同一目标同一 Event 上
    已有进行中指派」直接返回原指派，避免重复 route 叠加第二份工作。
  - 产品层新增 `team_route` 与 `team_route_update`（`end` / `retry_notice`）两个工具，注册在既有
    `team_state_enabled` 门内；通知发送与失败记录集中在 `team_tools/notice.rs`，复用既有
    `ensure_v2_agent_loaded` + `send_inter_agent_communication`，未新建调度器或第二套协议。
  - 三种投递意图由 `duty` 推导 `trigger_turn`，运行中/空闲由既有执行面在 `active_turn` 锁下裁决，
    未自行读取 Agent status。稳定团队协议前缀升版至 v2 并说明 route 语义。
- 定向门禁全部通过（详见"当前验收状态"）。

### 当前工作

实现与定向验证已完成，成果已提交在本工作树分支，等待独立审查。

### 本任务剩余步骤

- 无。交由独立审查者验收。

### 阻塞项

无。L6 在独立 worktree 并行，不构成产品代码阻塞；仅在重型资源门禁上与本任务串行。

### 当前验收状态

- 规划与现场核对：已完成。
- M-2 实现、格式化、lint：已完成。`just fmt` / `just fmt-check` 通过，
  `just fix -p codex-team-state` 与 `just fix -p codex-core` 无告警。
- 定向测试（均经根共享构建锁执行）：
  - `just test -p codex-team-state`：75/75 通过（M-1 原 46 项 + M-2 新增 29 项）。
  - `just test -p codex-core --test all -- suite::team_world_state suite::team_routing`：12/12 通过
    （M-1 产品纵切 9 项无退化 + M-2 新增 3 项）。
  - `just test -p codex-core --lib -- tools::`：415/415 通过；`-- context::`：99/99 通过；
    `-- team`：9/9 通过（含 M-2 新增 7 项 route 工具用例）。
- 顶层 `doc/WBS.md` / `doc/WBS-COMPLETED.md`：按本任务边界明确不修改，待 L6 集成后再窄同步。
- Docker、真实 API、本地模型、全 workspace 测试：不在授权范围，未运行。

### 执行期环境说明

本机 shell 预置了 `HTTP(S)_PROXY` / `ALL_PROXY` 环境变量，会让 wiremock 起的本地 mock server 无法被
被测进程连通；该现象对 M-1 既有 suite 同样出现，与本次改动无关。定向集成测试均在显式清除这些代理变量后
执行（`env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy just test ...`）。
未修改任何宿主机或仓库配置。

### 交接边界

- 执行者在本工作树完成、提交并停止；独立审查者对照本计划、实时 WBS、代码 diff 与定向测试证据验收。
- 本任务完成后冻结本计划；M-3 及以后只链接 `doc/WBS/multi-agent-trusted-evidence.md`，不在本计划继续展开。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | M-2 固定产品行为、失败语义和验收，不预先锁死工具名、领域表示或模块布局 | 用户要求只保留必要硬边界，给执行者选择更优实现的空间 | `multidev/` M-2 | 已采纳 |
| 002 | route 的 canonical 可见性/所需指派先提交，通知作为提交后的可重试副作用 | 排除“通知已到但无权限”，同时允许通知暂时失败而不破坏团队事实 | route 与投递 | 已采纳 |
| 003 | 可见性与指派保持分离；工作 route 建立指派，信息型通知不为唤起而伪造工作指派 | 这是 WBS 第 21 条与三分支投递语义共同要求，也使活动谓词保持准确 | 领域模型与活动视图 | 已采纳 |
| 004 | 优先复用现有 inter-agent communication/queue/trigger-turn 原语，但只作为软建议 | 实时源码已有合适接缝；保留执行者在局部架构上的自主权 | 通知接缝 | 已采纳 |
| 005 | 顶层 WBS/WBS-COMPLETED 本任务不修改 | L6 分支正修改共享文档，避免并行冲突；Multi 子 WBS 足以记录 M-2 专用事实 | 文档交付 | 已采纳 |
| 006 | 用领域测试加无 API 的真实 Agent 产品纵切验收，不跑全 workspace | 能证明功能与接缝正确，同时遵守轻量、定向测试偏好 | 测试范围 | 已采纳 |
| 007 | 普通窄失败允许执行者自行修复并定向重跑，原则边界或持续实质阻塞才暂停 | 避免可恢复小问题打断执行，又不放松安全与资源门禁 | 执行流程 | 已采纳 |
| 008 | 指派用独立对象 `TeamRoute`（含 `RouteId` 与 `RouteDuty`），不作为 `TeamVersion` 的第三条生命周期轴 | 指派要有独立身份、可并存、可分别结束，而 `LifecycleAxis` 的同轴去重模型表达不了这一点 | 领域模型 | 已采纳 |
| 009 | 信息型 route 用独立 `RouteDuty::Notice`，永不进入活动视图、不发 wake | 保证「只告知」不被伪造成进行中工作，同时仍授予不可撤销可见性 | 活动谓词与投递 | 已采纳 |
| 010 | publish 与 route 共用同一 `(actor, request_id)` retry 命名空间，跨类型复用直接判 `RetryIdentityReused` | 分开命名空间会让同一 identity 在两类操作间静默生效，等于放弃"重试不产生重复对象"的保证 | 幂等 | 已采纳 |
| 011 | 除 retry identity 外，再对「同一目标在同一 Event 上已有进行中指派」去重 | 不同轮次的重复 route 不是重放，但叠加第二份指派会让"结束一个指派"留下无法解释的活动残留 | route 提交 | 已采纳 |
| 012 | `trigger_turn` 只由 `duty` 推导，运行中/空闲交给既有执行面在 `active_turn` 锁下裁决 | 自行读取 Agent status 是锁外快照，必然有竞态；既有路径已原子区分排队与唤起 | 投递接缝 | 已采纳 |
| 013 | 通知投递失败只记在 route 的 `DeliveryState` 上，工具仍返回成功 | route 的 canonical 事实已经成立，把它报成失败会诱导模型重做一次授权 | 失败语义 | 已采纳 |
| 014 | 投影中 route 行按可见性收敛：Root 见全部，成员只见发给自己的 | 选择性传播若在视图里泄露"还发给了谁"，等于抵消了它自己 | 投影 | 已采纳 |
| 015 | 集成测试断言改为基于 mock server 完整请求日志的显式谓词，不依赖单个 mock 的 `single_request()` | `ResponseMock` 在匹配阶段就记录请求（含它随后拒绝的），其计数含义是"是否被询问"而非"是否应答" | 测试设施 | 已采纳 |
