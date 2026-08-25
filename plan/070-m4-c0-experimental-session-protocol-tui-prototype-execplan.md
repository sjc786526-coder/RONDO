# Plan 070：M4-C0 实验性 Session 协议与 TUI 原型 ExecPlan

> 本计划是 M4-C0 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通实现、构建、测试、snapshot 或审查问题
> 可以在范围内自主修复和重跑。
> 本计划只描述 C0；后续正式 query/control/TUI 工作包、顺序和依赖以 `doc/WBS.md`、
> `doc/WBS/multi-agent-trusted-evidence.md` 与 `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 `main@445b6eae7f1df5bfd106fcd963141173a1292af5` 建立一条默认关闭的最小纵向原型：

```text
experimental app-server v2 → app-server client → TUI
```

用真实产品代码和可重复交互验证 Session/Team 的发现、读取、状态投影、代表性操作与失效后重同步语义；明确区分领域
lifecycle、owner/runtime residency 和客户端同步状态。C0 可以使用明确标注的原型输入补足 S1 尚不存在的事实，但不得把模拟、
缓存或进程内 Team State 宣称为 S1 的 durable read model，也不得提前冻结正式 RPC、字段或 UI 布局。

任务结束只允许以下结论之一：

- `M4_C0_PROTOTYPE_PASS`：纵向原型、故障场景和聚焦门禁成立，原型保留/丢弃项及正式 C* 拆包输入已经形成，且没有未关闭的
  C0 correctness finding。
- `REPLAN_REQUIRED`：指定边界内不存在诚实完成纵向验证的合理路线；必须给出可复核的架构冲突，不能用普通可修实现或测试失败
  代替该结论。

### 完成/验收标准

- [ ] 所有新增协议只位于 app-server v2 experimental surface，并按现有 experimental API 机制生成和验证 schema；
      `experimentalApi` capability 只是协议使用条件，不能单独启用 C0 产品原型。
- [ ] C0 有独立、默认关闭的产品 opt-in。关闭时不出现原型 UI、不新增后台查询/订阅、不改变既有 thread/session、TUI、
      单 Agent 或 Multi 行为；仅打开通用 experimental API capability 仍不能启用原型。
- [ ] 最小发现/读取纵向流能表达 Session、canonical Root、Team identity（已知或明确未知/原型）、领域 lifecycle、owner/runtime
      residency、操作可用性和客户端视图新鲜度；这些轴不能用一个含混状态互相替代。
- [ ] `unloaded/resumable`、`closed`、`archived`、owner unavailable、断线/stale 和结果 unknown 在协议与 TUI 中可区分；
      `closing/failed/partial/unknown` 不展示为 success、closed、deleted 或 authority 已交接。
- [ ] 查询只读取现有只读来源或明确的原型输入，不取得 writer、不 repair/写回 metadata、不 resume/load Session、不启动 Agent、
      model turn、真实 API 或其他外部副作用。S1 尚未提供的 durable Team/recovery 事实必须显示来源限制或 unavailable/unknown，
      不能由 C0 猜造。
- [ ] 至少验证一条已加载 owner 的在线 canonical Team mutation。成功只能来自当前 owner runtime 的领域能力；non-owner、
      child-only、owner 未连接或身份无法证明时不能成功写入，且不得新增跨进程 relay、queue、IPC router 或 takeover。
- [ ] 至少验证一条现有权威冷态 lifecycle 流。它通过既有领域入口完成，不直接写 Thread/Team 持久介质，不为操作先加载 Root；
      冲突、部分完成、失败或结果无法确认必须诚实返回和展示。
- [ ] client/TUI 对事件 lag、transport disconnect 和 mutation 响应丢失有明确状态转换：先使投影 stale 或 result-unknown，再通过
      一次新的权威读取重建；重读前不自动重放非幂等 mutation，重读失败时保持失效/不可用而不是恢复为 success。
- [ ] unsubscribe、TUI switch 和即时 disconnect 只改变客户端附着/同步状态，不改变 Team lifecycle；若复用零订阅 deferred idle
      unload，它只能走现有领域 close barrier，不能由 C0 客户端自行推导 close 成功。
- [ ] TUI 新增的 C0 查询和操作全部经 app-server client / `AppServerSession` 路径，不新增 TUI→core、TUI→Team State 或
      TUI→持久介质旁路；用户可见的代表性状态、错误和未知结果有相称 `insta` snapshot。
- [ ] 代表性场景至少覆盖：loaded owner/current、unloaded resumable、closed/archived、owner unavailable、non-owner/child-only
      操作拒绝、cold lifecycle、lag、disconnect、response lost/result unknown、权威重读成功与失败，以及原型关闭态。
- [ ] 协议行为由 app-server 公共 JSON-RPC 集成测试覆盖；client 同步/未知结果状态与 TUI 交互分别放入现有 crate 的聚焦测试，
      不以 mock UI 文案测试替代 server/client correctness，也不重复建设重型端到端设施。
- [ ] app-server API 变化同步 `app-server/README.md`，实验 schema 与必要配置 schema/生成物由仓库命令更新并审查；没有遗留
      `*.snap.new`、临时 fixture、调试输出或未解释生成差异。
- [ ] 形成一份精炼执行日志，记录原型数据来源、实际选择的在线/冷态操作、故障注入与验收结果、哪些原型接缝建议保留或丢弃，
      以及可交给 WBS 单一整合者的正式 query（等待 S1）和正式 control/TUI（等待 S2）拆分输入；日志只记历史，不自行编号或排期
      后续工作包。
- [ ] 执行者完成范围内自审；必要时可用有界子智能体做独立模块复核，最终由用户指定的本会话审查者独立验收。真实 correctness
      finding 在范围内自主修复并复验；普通窄问题允许多轮修复/重跑，不因首次失败停工，也不得通过弱化语义、测试或 snapshots 凑绿。
- [ ] 最终检查精确写集、受保护共享文件、`git diff --check`、相关测试、主工作区和全部 worktree 元数据；只提交 070 本地分支并
      保持工作树干净，不合并、不推送、不关闭 worktree、不重命名分支。

## 2. 范围

### 允许修改

以下是任务拥有的主要实现面；执行者可在这些 crate 内新建职责清晰的专用模块，或复用现有模块，而不必拘泥于当前文件名：

- `multidev/codex-rs/app-server-protocol/`：仅 v2 experimental Session/Team 原型协议、协议测试与生成 schema。
- `multidev/codex-rs/app-server/`：只读投影、owner 在线路由、权威冷态 lifecycle 接缝、公共 JSON-RPC 集成测试和 API README。
- `multidev/codex-rs/app-server-client/`：C0 请求封装、投影同步/失效/未知结果接缝及聚焦测试。
- `multidev/codex-rs/tui/`：默认关闭的最小原型、必要的 app-server session wiring、交互测试与用户可见 snapshots。
- 本计划的“当前状态”和“关键决策记录”。
- `agent_log/2026-08-24-plan070-m4-c0-experimental-session-control.md`：实施时新建的一份精炼日志。

以下共享面只在职责确实需要且无法通过上述任务专属模块干净闭合时条件允许：

- `multidev/codex-rs/features/`、`multidev/codex-rs/core/`、`multidev/codex-rs/protocol/` 中最小的 product gate、只读投影或
  owner-domain 接缝及其就近测试；
- 相应 `config.schema.json`、workspace/Cargo/Bazel manifest/lock 和生成物。

触碰条件共享面前先核对 069/068 worktree 的当前路径写集。若存在并发争写，暂停该共享文件编辑并由用户指定串行所有者；不读取或
吸收其他 worktree 的未提交实现。普通调研笔记和可丢弃故障注入产物放 `/tmp`，不提交。

### 允许只读核对

- 根/`multidev/` `AGENTS.md`、README、当前 WBS、Plan 067、相关历史计划/日志，以及 Session/thread、AgentControl、Team State、
  app-server v2/client/TUI、feature/config 和测试设施的现行源码。
- `multidev/codex-rs/team-state/` 与 `multidev/codex-rs/thread-store/` 只用于理解 069 拥有的 canonical durable 边界；070 不在其中
  开发。若实现必须改变这些 crate，视为所有权边界扩张，先停止并请求用户重新分配。
- 主物理仓库 git-ignored `codex-source-code/` 与冻结 `codex-doc/` 只在确有上游行为疑问时只读核对；不需要也不允许在其中开发、
  checkout、fetch 或生成文件。
- 068/069 及其他 worktree 只查看 branch/HEAD/status 路径、构建锁和资源进程等元数据；不得读取其未提交文件内容或依赖其结果。

### 不允许修改

- `doc/WBS.md`、`doc/WBS/*.md`、`doc/WBS-COMPLETED.md`、README（app-server API README 除外）、既有 plan/日志、
  `doc/audit-snapshots/`、`eval/`、`training/`、`mydev/`、`codex-source-code/`、`codex-doc/`。
- Plan 068/069 的 worktree、分支、未提交内容及其 Publication Critic、durable store/read model、Root authority 或恢复实现。
- `multidev/codex-rs/team-state/`、`multidev/codex-rs/thread-store/` 的实现与测试。
- S1 持久介质/canonical durable read model/durable commit、S2 完整恢复与 close barrier、正式 C* API/TUI、W0/W1、M4-Z，
  以及 `#37198`、`#37847` 或其他上游回移。
- 通用 dashboard、project/session/task registry、跨进程 mutation relay/queue、第二套 Team State/Session store/client authority、
  数据审计/可信平台或性能测评设施。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、ignored 私有模型/测评正文、训练输出、权重，以及项目外个人文件或私有数据。
- 068/069 或其他 worktree 的未提交文件内容。

### Git-ignored 与主工作区边界

预计所有 tracked 实现、测试、schema、snapshot、计划状态和日志都能在 070 worktree 内完成；本任务没有必须直接写入主工作区的
git-ignored 工作。共享构建锁和监控 target 由仓库既有 `just`/watchdog 入口管理，不手改 `.codex/` 或锁状态。若实现者发现必须在
主工作区写 ignored 文件、修改项目外状态或读取私密运行材料才能完成，应先停止该动作并单独汇报，不能把它当作普通实现步骤。

## 3. 硬约束

以下约束具有强制性。不得为了缩小改动、通过测试或让原型看起来完整而违反。

1. **指定基线与并行隔离**：070 从 `445b6ea` 独立开发，只消费已经进入该基线的事实。068 拥有 Publication Critic，069 拥有
   durable Team/read/Root authority；070 不读取、修改、合并、rebase 或依赖其未提交内容。共享 WBS、manifest/lock、生成 schema
   和不可避免的 common/core/protocol/config wiring 只允许一个任务在同一时点编辑，并在最终整合边界串行吸收最新 main。070 首次
   以及每次重新取得重型任务所有权前，都必须确认前一任务的 Cargo/Docker/真实本地模型进程已经实际退出；未退出则等待，不并发抢占。
2. **双重启用边界**：协议必须是 v2 experimental，产品原型还必须有独立 opt-in，且默认关闭。客户端声明 experimental API
   capability 不能替代产品 gate；关闭态不能留下后台工作或用户可见变化。
3. **单一权威与来源诚实**：Thread/Session、live owner 与 canonical Team State 继续由现有领域拥有。C0 只投影或调用，不直接写
   持久介质、不维护第三份领域状态。客户端可以缓存明确可失效的 view，但 cache 不是 authority；模拟/fixture/进程内来源必须在
   类型、结果或 UI 中诚实表达原型边界，不能冒充 S1 durable read model。app-server/TUI 不得取得原始 `TeamStateHandle` 来建立
   自己的控制语义；若需要 live Team 接缝，由实际 loaded root domain 提供窄投影/命令委派。
4. **状态轴分离**：identity、domain lifecycle、owner/runtime residency、operation availability、view freshness/result certainty
   必须可独立表达。`unloaded` 不是 `closed`，`disconnected` 不改变 Team lifecycle，`result unknown` 不是 failure 或 success，
   `partial/closing/failed` 也不能被压平为终态成功。
5. **只读不激活**：发现和读取不得取得 writer、repair/写回 metadata、resume/load Session、启动 Agent/model/API 或用 mutation
   修补视图。无法从当前权威源证明的字段宁可 unknown/unavailable；`#37198` 和 S1 未进主线前不得声称 persisted cwd 或 durable
   Team consistency 已成立。
6. **操作按职责路由**：在线 canonical mutation 只交给已加载、身份可证明的 owner runtime；non-owner、child-only 或 owner
   unavailable 必须拒绝/不可用。冷态 lifecycle 只调用现有权威领域入口。C0 不实现 owner takeover、跨进程转发、补偿事务、
   盲重试或直接存储写入。
7. **未知结果先失效再重读**：lag、disconnect 或已发 mutation 的响应/解码结果丢失后，客户端立即失效相关投影；非幂等 mutation
   在新的权威 read 解析前绝不自动重放。通知只可作为失效/刷新提示，未观察到 lag 不构成 freshness 证明；重连、切换或新 read 后的
   迟到响应/事件不得覆盖新视图。恢复为 fresh 的事实必须来自同一个已确认的权威 read 边界；没有一致性证明时，不能把旧 cache、
   零散通知和新响应拼成“当前事实”。
8. **TUI 只消费 app-server**：C0 新行为不得从 TUI 直接调用 core/Team State/store。switch、unsubscribe 和断连只改变附着与
   client sync；任何 close/unload 仍由 server 领域 lifecycle 决定。UI 布局可自主设计，但必须让危险的可操作/不可操作状态和
   stale/result-unknown 对用户清楚可见。
9. **聚焦验证且不弱化**：优先复用现有 app-server 公共 JSON-RPC、client transport 和 TUI snapshot 设施。协议、server、client、
   TUI 各自只补职责相称的测试；故障注入必须位于可重复边界，不建设审计、可信证明或通用 chaos 平台。普通失败由执行者自主修复、
   重跑和复验，原则性边界冲突或授权外扩张才暂停。
10. **生成、资源与交付**：协议变化按局部规则运行普通及 experimental app-server schema generator；配置变化才运行 config schema，
    依赖变化才更新 Cargo/Bazel lock。Rust 构建、test、fix 和 schema generator 必须使用 `multidev/justfile` 已接入的共享锁/看门狗，
    不绕过并发和资源上限。只做本地 deterministic/fake/offline 正确性验证；不授权 Docker、真实 API/模型、训练、性能测评、CI/PR、
    发布、上传、付费或远端状态变更；Plan 068 已取得的模型、Docker、权重和远端授权不传递给 070。最终只本地提交 070，不合并、
    不推送。

## 4. 软性建议

以下建议来自 `445b6ea` 的现行接缝，不固定具体 RPC、字段、模块、状态枚举或 UI 布局。执行者可以采用更干净、等强的策略，并在
关键决策记录中说明有实质影响的偏离。

- 先冻结场景和状态轴，再设计 wire/UI。现有 `thread/list`、`thread/read`、loaded status/enrichment、archive/unarchive/delete
  领域入口已经覆盖不少 Session 事实；优先扩展/组合这些能力，不必复制 thread discovery 或 lifecycle。但普通 list 路径可能扫描
  rollout 并 repair metadata，C0 的纯查询承诺应选择明确无写回的路径或专用只读接缝，不能仅凭 RPC 名假设无副作用。
- live Team 事实可由当前 root tree 的 canonical Team domain 形成有界只读投影；unloaded Team 在 S1 前没有 durable 来源时应
  明确 unavailable/unknown。优先增加窄的领域 projection/control facade，由 loaded root 委派，而不是把 `TeamStateHandle` 暴露给
  app-server/TUI 或让它们理解 TeamStore 内部结构；`ThreadManager::agent_control()` 新建的 control 也绝不能充当现有 Team owner。
- 在线操作可从现有 Team mutation 中选择一条最能验证 owner 路由且 fixture 简洁的代表；冷态流可从 archive/unarchive 等现有入口
  选择。不要为了覆盖操作数量扩大 C0，也不要选择会迫使 C0 实现 S2 正确性的路线。
- `app-server-client` 已有 typed request errors、`Lagged`、`Disconnected` 和 in-process/remote 统一事件面；可在 client 或 TUI 专用
  controller 上增加窄的 projection sync/result-certainty 层。保持 transport error 与领域失败分层，不必为 C0 建通用 offline cache
  或自动 reconnect 平台。当前 remote path 没有完整 lag/rebind 保证，真实 disconnect 场景需要新的 connection epoch/替换连接或
  等强窄接缝；旧连接响应和重新附着不能自动复用。
- TUI 已通过 `AppServerSession` 使用 app-server。优先新建专用、可测试的原型 view/model，而不是继续扩大 `app.rs`、
  `chatwidget.rs` 等高触碰大文件；但若局部扩展更清晰，不强制拆模块。
- 对响应丢失，可在“server 已接收/可能提交、client 未收到 response”的可重复测试接缝注入故障；随后证明 UI 进入
  result-unknown、不会自动重发，并以 read 结果解析。无需建设生产 chaos 或精确分布式因果追踪。
- 事件通知可用于触发失效，不必承担权威状态复制；发现 gap 时以重读为准。若最终选择无专用通知的 request/refresh 原型也能完整
  验证场景，可以保留该更简路线。
- 整份替换相关投影通常是最简单的重同步策略；若现有协议更适合带版本/代际证明的一致性 delta 或分页重读，也可采用等强方案，
  只要恢复为 fresh 的边界清楚且旧代响应不能污染新视图。
- 调试期从第一个未打通处边修边跑并保留已验证进度。纵向链完整后，再从干净的 deterministic/fake 状态完整执行一次代表性场景
  和聚焦门禁，以该轮作为正式 C0 结果；不因早期一次失败丢弃整组已验证进度。

### 建议的阶段编排与退出条件

**A. 场景与当前接缝**

- 冻结代表性 read、owner operation、cold lifecycle、lag/disconnect/response-lost 场景和每个状态轴的可观察结果；不冻结 schema/UI。
- 核对 068/069 status 路径和共享构建资源，明确 task-owned 与条件共享写集。
- 退出条件：每个场景都能指出当前权威来源或诚实的原型/unavailable 边界，不依赖其他未合并 worktree。

**B. 最小 read projection**

- 打通 experimental server→client 的发现/读取，投影 identity、lifecycle、residency/availability 和 freshness/provenance。
- 用公共 JSON-RPC 测试证明 unloaded 查询不激活 Session，并覆盖原型关闭态。
- 退出条件：loaded/unloaded/closed/archived/owner-unavailable/unknown 不混淆，S1 缺口没有被缓存或 fixture 填成正式事实。

**C. 操作路由与失败表达**

- 接通一条 owner 在线 mutation 和一条 cold lifecycle；验证 non-owner、child-only、owner unavailable、partial/unknown。
- 在可重复接缝注入 response lost，证明 mutation 不被盲重放。
- 退出条件：成功只来自对应权威领域入口，失败和未知不产生表面成功或旁路写入。

**D. TUI 与重同步**

- 加入默认关闭的最小交互；lag/disconnect/unknown 后使 view 失效，并通过显式/受控重连后的权威 read 恢复。
- 覆盖 switch/unsubscribe/detach 不改变 lifecycle 和关键用户可见 snapshots。
- 退出条件：纵向场景在同一状态模型上闭合，TUI 没有 core/store 旁路，也没有未审查 snapshot。

**E. 干净验收、终审与冻结**

- 更新 app-server README、生成物、Plan 当前状态与精炼日志；记录保留/丢弃接缝和正式 C* 拆包实证输入。
- 建议聚焦门禁：`just test -p codex-app-server-protocol`、`just test -p codex-app-server-client`、
  `just test -p codex-app-server`、`just test -p codex-tui`，并按实际写集运行 `just write-app-server-schema`、
  `just write-app-server-schema --experimental`、必要时 `just write-config-schema` 以及局部 `just fix -p ...`/`just fmt`。
  所有命令从 `multidev/` 入口运行并服从共享锁；具体过滤器可在调试期收窄。
- protocol 生成后同时审查稳定输出没有泄漏 experimental surface；TUI 测试后用现有 `cargo insta` 查看 pending snapshots，逐个读取
  并只接受本任务有意的变化。
- 若确实修改 common/core/protocol，先完成各受影响 crate 门禁，再在最终串行整合边界按就近规则只运行一次必要的完整 `just test`；
  不在调试期反复跑全量。执行者自审并修复真实 finding；若使用有界子智能体复核也同样复验，最后检查 diff、snapshots、生成物和
  全部 worktree 元数据，再交给用户指定的本会话审查者独立验收。
- 退出条件：`M4_C0_PROTOTYPE_PASS` 或有证据的 `REPLAN_REQUIRED` 成立；本地提交干净，未运行项如实记录。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 070 从指定基线建立并完成根/`multidev/`/TUI 就近规则与本计划复核；未读取或吸收 068/069 未提交内容。
- 阶段 A–D 已完成：state-DB-only discovery、无 history read、loaded Root 窄 Team façade、Root-only `SetRootState`、既有
  `thread/unarchive` 冷态入口、client freshness/result-certainty 状态机与默认关闭的 `/sessions` 原型已纵向打通。
- v2 experimental schema 的 stable/experimental 两种生成测试均通过；修正了 nested experimental DTO 向 stable schema 泄漏，
  stable loose/precomputed 输出无 Session 原型符号，当前仅 experimental precomputed bundle 有预期差异。
- app-server 公共 JSON-RPC 场景通过 8/8，覆盖双 gate、无 state DB、不激活查询、prototype lifecycle、cold archive/unarchive、
  loaded child/non-owner 拒绝、loaded owner mutation 与 stale precondition；client 39/39、协议 291/291、TUI 原型 7/7 通过。
- 四份 TUI snapshot 已逐项读取并接受；fixture 的 operation/provenance 组合已与 server 实际可产生的保守投影对齐，当前无
  pending snapshot 或 `*.snap.new`。
- 范围内自审移除了 `loaded owner → open`、`non-owner/child-only → partial` 的 lifecycle 推断；非 archived lifecycle 现在只有显式
  prototype input 才赋值，否则保持 `unknown/unavailable`，不再用 runtime residency 代替领域事实。修复后 server 8/8、TUI 6/6 复验通过。
- 阶段 E 的 config schema 已串行生成并审查，差异仅为 managed/regular 两处默认关闭的
  `experimental_session_control: boolean`；稳定 app-server schema 无 experimental Session 符号泄漏。
- 单次完整 workspace 门禁已执行至完整汇总：checksum-verified Codex V8 入口编译成功并运行 14,380 项，14,364 通过、1 项重试后
  通过、16 项失败、24 项跳过。16 项均位于 070 精确写集之外：8 项 Publication Critic 基线/fixture 问题、2 项 sandbox network
  probe 环境失败、2 项 realtime 超时和 4 项 zsh-fork 超时；070 新增及聚焦门禁没有失败。
- 独立正确性复核的第一轮两个 finding 已修复并聚焦复验：在线 Team operation 现在由 current map entry 与运行态 residency lease
  共同保护，已停止但仍映射的 Root fail-closed；lag/disconnect/EOF 会在真实 App 事件路径立即追加 `view=stale` 的保留投影。第二轮
  只读复核明确 PASS，没有新增 correctness finding。
- 最终六个受影响 crate 的 `just fix` 无警告通过，随后 `just fmt` 通过；最终精确写集、生成物、snapshot 与 worktree metadata 已检查。
- 正式资源恢复使用单 Cargo job 并五次只清理 070 可再生 `target/debug/incremental`；保留 deps/fingerprint/build/gn/V8 与产品、测试
  二进制。用户授权的 11 个旧 eval 版本共 33 个 bundle 目录也已精确删除，四个里程碑版本保持不变。

### 当前工作

- 无；本计划已完成并冻结，全部 tracked 交付内容由本节所在的 070 本地提交承载。

### 本任务剩余步骤

- 无。

### 阻塞项

- 当前无阻塞；069 已暂停且用户已把共享 config/features/core 编辑权串行授予 070，070 未读取或吸收 069 未提交内容。

### 当前验收状态

- A–E 功能、聚焦证据、schema、完整门禁证据与独立复核均已形成，执行者结论为 `M4_C0_PROTOTYPE_PASS` 候选；完整门禁的 16 项
  失败已定位到 070 精确写集之外并如实保留。Docker、真实 API/模型、训练、测评、CI/PR、远端状态均未使用。

### 交接边界

- C0 完成后冻结本计划。原型保留/丢弃和拆包实证先记入本任务日志；正式 Session query/control/TUI 的当前路线、编号和依赖由获批的
  WBS 单一整合者基于最新 main 窄同步，执行者不得在并行分支直接改写共享 WBS。
- 070 只本地提交并停止。合并、推送、WBS/COMPLETED 同步、分支归档或删除 worktree均等待用户另行批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | C0 冻结场景、职责和失败语义，不冻结 RPC 字段、状态 enum 或 UI 布局 | 原型目标是为正式拆包提供真实输入，过早稳定会把 S1/S2 尚未形成的接缝固化 | protocol/client/TUI | 已采纳 |
| 002 | experimental API capability 与产品原型 opt-in 分离，二者均须满足且产品 gate 默认关闭 | 当前 TUI 本身会声明 experimental capability；单靠它不能保证用户可见原型默认关闭 | enablement | 已采纳 |
| 003 | C0 可消费 live canonical Team、ThreadStore/lifecycle 事实和显式原型输入，但只形成可失效 projection | S1 read model 尚不存在；既不能等待 S1，也不能新建第三份 Session/Team 状态冒充 durable authority | state source | 已采纳 |
| 004 | lifecycle、owner/runtime residency、operation availability 与 client freshness/result certainty 是独立轴 | unloaded/resumable、closed、owner unavailable、disconnect 和 unknown 有不同责任与恢复路径 | projection/UI | 已采纳 |
| 005 | lag/disconnect/response lost 统一先失效投影；非幂等 mutation 只能在权威重读后由用户重新决定 | transport 失败无法证明 mutation 未执行，自动 retry 会重复副作用 | client semantics | 已采纳 |
| 006 | 在线操作只路由 live owner，冷态操作只调用既有领域 lifecycle；不建设 relay/takeover/direct store write | 保持 M4-A owner 分工并避免侵入 S1/S2 | control seam | 已采纳 |
| 007 | TUI 新能力全部通过 app-server client，client cache 只保存可失效 view | 防止 TUI 成为第三状态源或形成 TUI→core 旁路 | TUI architecture | 已采纳 |
| 008 | 主实现面允许按职责复用或新建专用模块；条件 core/config 接缝只在必要时串行触碰 | 保持设计优雅，同时减少与 069 及共享生成物的并行冲突 | write set | 已采纳 |
| 009 | 普通实现/测试/snapshot finding 可自主修复重跑，只有原则冲突或授权外扩张才暂停 | 给执行者合理调试余量，不弱化 correctness 边界 | execution | 已采纳 |
| 010 | 实施只做本地 deterministic/fake/offline 正确性与本地提交，不使用外部资源，也不合并推送 | C0 不需要模型、API、Docker、CI/PR 或远端状态；用户保留整合批准 | resources/Git | 已采纳 |
| 011 | 产品 opt-in 使用独立 `experimental_session_control` feature，server 与 TUI 都执行 gate | TUI 已默认声明 experimental API capability，capability 不能证明用户启用了产品原型 | feature/config | 已采纳 |
| 012 | 在线代表操作采用 canonical Team 的 Root-only `SetRootState`，冷态代表操作复用 `thread/unarchive` | 前者可直接验证 owner/预条件，后者不加载 Root 且避免 delete/archive 的额外破坏与 shutdown 语义 | control/lifecycle | 已采纳 |
| 013 | C0 不新增 Team notification 或通用 transport reconnect；显式权威 read 重建整份 view，connection/attachment epoch 拒绝迟到响应 | 通知只能作为失效提示，完整 reconnect 会越入 S2；C0 需要的是可重复的 stale/result-unknown 与新连接重读接缝 | client/TUI | 已采纳 |
| 014 | 专用 optimistic Team RPC 的 invalid-request 可归为已知无副作用拒绝；既有 `thread/unarchive` 一旦提交，任何错误都归为 result unknown | Team domain 的参数、owner 与 precondition 错误是原子拒绝；通用 unarchive 可能在介质移动后才报告错误，不能安全声称未执行或重放 | client semantics | 已采纳 |
| 015 | runtime residency 不推导 domain lifecycle；除 archived 权威事实外，只有显式 prototype input 可填 lifecycle | loaded/child/owner unavailable 只证明运行时驻留或 owner 可达性，不能证明 open、partial、closing 或其他领域状态 | projection/UI | 已采纳 |
| 016 | operation availability 的 provenance 下沉到每个操作，不用一个聚合来源覆盖 Team 与 ThreadStore 两类事实 | track、archive、unarchive 来自不同职责边界；聚合来源会把 cold lifecycle 误标为 live owner 或反之 | protocol/projection/UI | 已采纳 |
| 017 | 完整门禁在普通 V8 上游资产 404 后改用仓库既有 checksum-verified Codex V8 入口，并以 `CARGO_BUILD_JOBS=1` 从保留缓存完成 | 两个入口共享 build lock/watchdog/Nextest/JUnit；校验资产入口避免外部 404，单作业使内存 PSI 稳定且不改变测试语义 | validation/resources | 已采纳 |
| 018 | live-owner operation 在 ThreadManager current-entry read lease 内取得 CodexThread 同步 residency lease；shutdown 先以 write lease 标记不可用 | 单独检查 registry 指针会让已停止但尚未移除的 Root 短暂冒充 loaded owner；同步 lease 不跨 await，也不建设第二套 runtime | core/app-server | 已采纳 |
| 019 | lag、disconnect 与 event-stream EOF 在失效 client view 后立即把 retained projection 作为 `view=stale` 追加到 TUI 历史 | 只改变内部 gate 会让最后一份用户可见投影仍显示 fresh；保留投影既不伪造新事实，也明确要求重连/刷新 | client/TUI | 已采纳 |
