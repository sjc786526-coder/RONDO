# Plan 077：M4-C1 正式 Durable Session Query ExecPlan

> 本计划是 M4-C1 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通源码、fixture、snapshot 或审查问题可以在范围内
> 自主修复。任何会读写 Rust target 的命令及其重跑只服从本计划第 3 节的逐批额外批准门。
> 本计划只描述正式 Session query；M4-S2、后续 Session control/TUI 和其他跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 clean `main@dfc4278233cf6c361fd6bbef7b3fb6107906f22d`，以 M4-S1 已成立的 canonical durable read model
替换 M4-C0 查询链中的 state-DB/prototype input，形成一条默认关闭、正式只读的纵向能力：

```text
app-server v2 → app-server client → TUI read-only presentation
```

它应当在不加载或恢复 Agent 的前提下发现并查看已持久化的 Durable Team Session，包括查询所在 app-server 已观测到的在线
owner、当前 server 未观测到 resident 的冷态记录（可能来自正常关闭、进程退出或其他不可证明原因）、已归档及当前
不可完整读取的现场；展示可证明的 Session/Root/Team 身份、committed Team State 投影、领域 lifecycle、runtime residency、操作
可用性和视图新鲜度/确定性。这里的“历史 Session”只指过去创建并仍可发现的 durable Session 记录，不扩张为 transcript、CoT、
Team Event 历史、历史成员档案或时间旅行查询。

077 包含 TUI 的**只读查询展示**，但不包含 resume、close、archive、delete 等 control action 或控制型 TUI。任务结束只允许以下
结论之一：

- `M4_C1_QUERY_PASS`：正式查询链、故障语义、聚焦门禁和独立终审均成立，且没有未关闭的高/中等级 correctness finding。
- `REPLAN_REQUIRED`：在本计划边界内不存在诚实完成正式查询的合理路线；必须给出可复核的架构或产品冲突，不能用普通可修的
  编译、测试、fixture、snapshot 或审查失败代替该结论。

### 完成/验收标准

- [ ] 正式 list/read 的 Durable Session/Team 事实来自 M4-S1 canonical durable read model：canonical Root `SessionMeta` durable
      marker、对应 committed Team snapshot 及其领域校验形成同一读取边界；C0 `prototypeFacts`、state DB metadata、live Team cache
      或客户端 cache 均不作为第二份 durable 事实源。正式 query RPC/TUI 不接受 caller-asserted lifecycle 或 prototype fact；旧 C0
      experimental endpoint 是否隔离保留由兼容策略决定，但不得进入正式查询链。
- [ ] 新 app-server 实例/进程使用同一持久目录启动后，无需先 resume/load Session，仍能发现并读取既有 Durable Session；至少覆盖
      查询所在 server 已加载的在线 owner、正常关闭或异常退出后留下且当前 server 未加载的冷态记录、归档和不可用或不完整现场。
      residency 的肯定事实只限查询所在 server 的可观测 owner；当前 server 未观测到 owner 不证明宿主范围内全局 unloaded，无法排除
      其他进程 owner 时必须为 not-observed-here/unknown/owner-unavailable 或等强诚实语义。`dfc4278` 当前没有跨重启 whole-Session
      `open/closing/closed/failed` 的 canonical 持久事实，因此 077 不得把冷态记录直接标为 closed；若实现不能从已有权威事实证明，
      该 lifecycle 轴必须为 unknown/unavailable。具体 wire enum、筛选参数和页面布局不在本计划冻结。
- [ ] SessionId、canonical Root ThreadId、child 归属与 TeamInstanceId 不互相代替；Root/child 查询不会重铸身份、把 child 当新
      Session/Team，或把不匹配 lineage/snapshot 投影为当前 Team。
- [ ] Team 投影只来自一份完整、通过校验的 committed snapshot，并分别保留、核对 canonical durable `commit_generation`（或等强
      单调 commit token）与 Team domain `revision`；二者不得相互代替，也不得被 client request/read ticket generation 代替。损坏、缺失、超限、
      版本不兼容、marker/snapshot 缺半或 identity mismatch 显式成为 unavailable/unsupported/incomplete，而不是空 Team、旧 cache
      或新 ID。
- [ ] domain lifecycle、server-observed runtime residency、operation availability、fact provenance 与 client view freshness/certainty 分轴表达。
      `unloaded` 不等于 `closed`，`loaded` 不等于 `open`，`disconnected/stale` 不改变领域状态，在线 runtime 事实也不覆盖 committed
      Team 事实。后整合者只能在 078 提供 canonical lifecycle fact 后窄接入 closed/closing/failed，不得让 077 先建第二份 lifecycle 状态。
- [ ] 查询展示“操作当前是否可用”但不执行操作。availability 无法从同一查询边界证明时保持 unknown/unavailable；不得由 TUI
      根据文案、按钮状态或零散字段自行推断。
- [ ] list 使用 v2 既有风格的有界 cursor pagination 或等强的现有设施。Root 过滤、同排序键、后端错误、预算耗尽和跨页重读不会
      造成静默遗漏/重复后仍宣称 complete；`complete` 只描述该响应声明的 source/read boundary 被完整遍历。并发 archive 或其他排序
      输入变化时，应使用对分页稳定的排序边界，或诚实 invalidation/incomplete，不要求伪造跨请求全局集合快照。各页/各条目是明确
      读取结果，不把不同时点的零散轴拼成一个全局原子快照。
- [ ] stale、transport lag/disconnect、旧 response、刷新失败或权威重读失败不会恢复为 fresh；恢复 fresh 必须来自一次新的完整
      权威 read。是否采用通知、显式 refresh 或其他简洁路线由实现者决定，不建设通用 reconnect/cache 平台。
- [ ] list/read 不取得 Root writer authority，不 repair/写回 metadata，不持久化查询结果，不 resume/load Session，不启动 Agent、
      model turn、tool、真实 API 或外部副作用，也不产生任何 Team mutation。
- [ ] query 产品能力默认关闭；普通 experimental API capability 本身不能意外打开产品查询。查询若被独立启用，可以只读查看已经
      存在且兼容的 Durable Session，而不要求重新开启 durable 创建/可写 runtime。关闭态和 legacy/non-durable 路径保持原行为，
      legacy 不自动升级或冒充 Durable Team。
- [ ] 所有新增产品查询只进入 app-server v2。TUI 只经 app-server client / `AppServerSession` 消费查询结果，不建立 TUI→core、
      TUI→ThreadStore、TUI→Team State 或持久介质旁路；用户可见的正常、stale、incomplete、unavailable 和损坏状态有相称 snapshot。
- [ ] app-server 的 public JSON-RPC 测试覆盖重启后发现/读取、分页与 source failure、Root/child、正常关闭/异常退出后的冷态记录、
      archived、损坏/不完整、
      不激活和 default-off；client 测试覆盖 view replacement/freshness；TUI 测试覆盖只读交互和 snapshots。测试按职责分层，不用
      mock UI 文案代替 server/read correctness，也不重复建设重型 E2E 平台。
- [ ] client/TUI 至少提供一种有界续页方式，使超过首屏/首页的 Durable Session 与 archived Session 实际可达，并传播 next/incomplete
      语义；慢查询或 backend hang 不阻塞 TUI 主事件循环，旧 connection/attachment 的迟到完成仍不能覆盖新视图。具体按键、布局、
      timeout、后台任务和事件类型不冻结。
- [ ] 调试链完整后，以最终代码/配置和全新的任务专用 Session/store namespace 完整执行一次正式 query 链；“干净”指新的领域状态
      与新的 server/client 现场，不要求删除或冷重建共享 Cargo target。正式轮若暴露可修问题，可修复后用新的领域状态重跑。
- [ ] app-server API 行为变化同步 `app-server/README.md`；所需普通/experimental app-server schema、配置 schema、snapshot、Cargo/Bazel
      生成物按实际变化更新并审查，没有遗留 `*.snap.new`、临时 fixture、调试输出或无解释生成差异。
- [ ] 形成一份精炼执行日志，记录正式状态源、实际 write set、聚焦门禁、fresh-state 正式链、资源前后值和未运行项；不在日志或 Plan
      中安排下游工作。执行者完成自审并本地提交后，由用户指定的本会话审查者独立终审；真实 finding 允许整改和复验。
- [ ] 最终检查 `git diff --check`、精确写集、受保护共享文件、相关测试、主工作区与全部 worktree 元数据；只提交 077 本地分支并
      保持 worktree clean，不合并、不推送、不关闭 worktree、不重命名分支。

## 2. 范围

### 允许修改

以下是 077 的主要实现面。执行者可以复用 C0 模块、重命名/拆分为正式 query 模块，或新建职责清晰的专用能力，不必拘泥于现有
文件名：

- `multidev/codex-rs/app-server-protocol/`：仅 app-server v2 的正式只读 Session query DTO/RPC、协议测试与 schema export。
- `multidev/codex-rs/app-server/`：durable discovery/read projection、只读请求处理、公共 JSON-RPC 集成测试和 API README。
- `multidev/codex-rs/app-server-client/`：typed query client、view freshness/replacement/incomplete 处理及聚焦测试。
- `multidev/codex-rs/tui/`：默认关闭的只读查询入口、展示、交互测试与用户可见 snapshots。
- 本计划的“当前状态”和“关键决策记录”。
- `agent_log/` 下实施时新建的一份 Plan 077 精炼执行日志。

职责确实需要、且强行限制在上述 crate 会泄漏存储细节或扭曲架构时，条件允许做最小扩展：

- `multidev/codex-rs/core/`：只读 query façade/projection；不得借机扩张 Session lifecycle 或 writer 接口。
- `multidev/codex-rs/thread-store/`、`multidev/codex-rs/team-state/`：仅缺失的 storage-neutral、无写副作用 durable discovery/read
  接缝、typed error/projection 与就近测试；不改变 durable commit/authority/介质语义。
- `multidev/codex-rs/state/`：仅正式 Session query 所需的 bounded、typed-error、read-only state-DB candidate locator 及就近测试；
  state DB 只负责候选定位，不成为 Durable Session/Team identity、lifecycle 或 committed state 的权威来源，也不得增加 registry、
  query cache、写回、repair 或 lifecycle 状态。每个候选仍须经 canonical `SessionMeta` 与 committed snapshot 验证。
- `multidev/codex-rs/features/`、`multidev/codex-rs/protocol/`、配置/schema、workspace/Cargo/Bazel manifest/lock 和生成物：仅由真实
  查询实现触发的最小变化。

`app-server-protocol/` 是 077 的查询主面；`multidev/codex-rs/protocol/`、feature/config 和 Cargo 锁文件是与 078/主线整合更容易
冲突的共享代码面，077 可以在本地分支形成完成实现所需的窄差异。WBS 不属于 077 写集，完全留给后整合者。077 不得读取或吸收
078 未提交实现；进入主线时由后整合者以最新 main 为底收敛共享文件。

### 允许只读核对

- 根与 `multidev/` 就近 `AGENTS.md`、README、当前 WBS、Plan 067/069/070/074、相关日志和现行源码/测试。
- 主物理仓库 git-ignored `codex-source-code/` 与冻结 `codex-doc/` 只在确有上游语义疑问时只读核对，不在其中开发、checkout、fetch
  或生成文件。
- 078 及其他 worktree 只查看 branch/HEAD/status、构建锁、资源进程等元数据；不得读取其未提交文件内容。

### 不允许修改或实施

- `doc/WBS.md`、`doc/WBS/*.md`、`doc/WBS-COMPLETED.md`、根 README、既有 plan/日志、`doc/audit-snapshots/`、`eval/`、
  `training/`、`mydev/`、`codex-source-code/`、`codex-doc/`。
- 078 或其他 worktree/分支及其中任何未提交内容；不 merge、rebase、cherry-pick 或复制其实现。
- M4-S2 的 resume/member reload、fork/new/clear、detach、close、archive/unarchive/delete 收口，以及后续正式 Session control/TUI。
- online Team mutation、cold lifecycle control、owner takeover、跨进程 relay/queue/IPC、自动 retry/replay 或直接持久介质写入。
- M4-W0/W1、M4-Z、Publication Critic、Plan 076、上游增量回移或基线升级。
- 通用 dashboard、Session/project/task registry、query cache 平台、新分页体系、第二套 Session/Team read source、第二套 Team State/
  writer authority、通用事件总线、数据审计/可信或严格全局因果设施。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、ignored 私有模型或测评正文、训练输出、权重、项目外个人文件或私有数据。
- 078 或其他 worktree 的未提交文件内容。

### Git-ignored 与主工作区边界

预计全部 tracked 实现、测试、schema、snapshot、Plan 状态和日志都能在 077 worktree 内完成，不需要直接修改主工作区。唯一已知的
跨 worktree git-ignored 写入是用户指定复用的 069 Cargo target；watchdog metrics 留在 077 的 `.codex/`，任务 fixture 放 `/tmp`，
二者均不提交。若执行者发现还必须在主工作区写 ignored 文件、修改项目外状态或读取私密材料才能完成，应先停止该动作并单独汇报。

## 3. 硬约束

以下约束具有强制性。不得为了缩小改动、通过测试或让 UI 看起来完整而违反。

1. **指定基线与并行隔离**：077 固定从 `dfc4278233cf6c361fd6bbef7b3fb6107906f22d` 独立开发；078 同样从该基线开发但拥有
   reload/resume/close 和冷态 lifecycle 主面。077 不依赖 078 未合并事实。若两任务需要编辑同一 core/thread/session/shared 文件，
   先用元数据与双方明确 write set 串行协调；不能协调时暂停该文件，而不是覆盖、stash、复制或猜测另一方修改。谁后进入主线，
   谁/后整合者按届时 WBS 承担 query 与最新 lifecycle 的聚焦兼容验收；077 本地开发不预先吸收 078。任何重型 Cargo 批次的先后与
   时段由用户人工判断和调度，执行者不得自行决定两任务谁先构建。
2. **正式事实源唯一**：Durable Session/Root lineage 使用 canonical ThreadStore/SessionMeta 事实，Team identity/state 使用 S1
   checksummed committed snapshot 及领域校验；两者按同一 durable read 边界交叉验证。state DB 可以作为定位优化，但不能单独证明
   durable identity/state；canonical ThreadStore API 可以拥有 archive/ordering 等 thread metadata 事实，但对应条目仍须通过 Root durable
   marker/snapshot 验证后才能成为 Durable Session view。C0 `prototypeFacts`、rollout guess、live in-memory Team 和 client cache 不得
   补空或升级为正式事实，正式 query 也不得继续接受 caller-asserted lifecycle/prototype input。
3. **只读不激活**：list/read 及为其服务的投影不得取得 writer authority、打开 live writer、repair/写回 metadata、resume/load
   Session、构造 AgentControl、启动 child/runtime/model/tool/API、提交 Team mutation或触发 lifecycle side effect。需要的新接缝必须
   从 API 形状和测试上保持 query-only；无法证明的事实宁可 unavailable/incomplete。
4. **状态轴与读取边界**：identity、domain lifecycle、server-observed runtime residency、operation availability、provenance、canonical
   durable commit generation、Team domain revision、client request/read ticket generation 与 client freshness/certainty 不互相代替。
   canonical commit generation（或等强 token）必须按领域规则单调核对，同代不同状态或 generation 回退不得被一次新请求重新标为 fresh；
   Team revision 仍须作为独立领域事实保留。一个 Team view 只能来自一份完整 committed snapshot；live residency
   可作为独立观察轴，但不能与旧 snapshot 拼成“当前 Team”。`dfc4278` 的 `ShutdownComplete` 在 persistence shutdown 后才作为
   runtime event 发出，现有 StoredThread/marker/snapshot 也没有持久 whole-Session closed fact；077 必须把不可证明的 open/closing/
   closed/failed 显示为 unknown，不得扫描事件猜测或新建 lifecycle 状态源。TUI 恢复 fresh 只能整份替换为新权威 read 或采用等强的
   一致性边界。residency 的肯定事实只覆盖查询所在 app-server 的 owner/live map；本 server 未观测到 resident 时不得推断宿主范围内
   没有其他 owner，除非未来已有独立权威接口能够证明。
5. **分页与故障诚实**：cursor 必须有稳定排序边界和 tie-breaker，或复用等强的既有 keyset；Root/Durable 过滤后继续取页或显式 incomplete，不能
   静默短页后宣称耗尽。后端 unavailable、解析/分类失败、预算耗尽、损坏/不兼容和刷新失败保留 typed 或结构化区分；不得把 partial
   rows、旧 page、零散通知和新 response 拼成 complete/current。若并发变化破坏本次声明的 source/read boundary，必须 invalidation 或
   incomplete；无需建设跨请求全局事务快照或严格因果平台。
6. **只读 query 与 control 分离**：077 可以展示操作 availability，但不得提交 resume、close、archive、unarchive、delete 或 Team
   mutation。既有 C0 mutation/cold-control 只可在原独立 experimental gate 下保持；为拆分 query 所必需的机械隔离可以窄改，但不得
   扩展或改变 control 产品语义。只启用正式 query 时不得暴露或执行 C0 mutation RPC/TUI action；未来 control 的迁移或删除留给后续任务。
7. **启用与兼容**：产品 query gate 默认关闭，关闭态不产生 UI、后台 query/subscribe 或既有行为变化；experimental API capability
   不替代产品 gate。启用 query 不授予 durable writer 能力。legacy/non-durable、marker 缺失或 durable feature 当前关闭时不自动
   初始化空 Team、不改 ID、不写升级 marker；已有兼容 durable 数据只按可证明范围只读展示。
8. **纵向职责**：app-server v2 投影领域结果，client 管理连接/视图新鲜度和有界续页，TUI 只做查询展示。TUI 不持有
   TeamStateHandle 或存储细节，不根据本地 cache 宣称操作可用；list/read/refresh 的慢请求不得阻塞主事件循环，完成结果仍须经过
   connection/attachment/read generation 或等强边界校验。RPC 名、DTO 字段、experimental/stable 标记、排序、timeout、刷新方式、
   后台执行方式和布局由实现者按现行代码选择；不得新增 v1 API，也不得把本任务内部选择提前冻结为后续 control 合同。
9. **验证、修复与正式轮**：先完成源码、测试设计、只读检查、非编译型格式/静态检查和精确重型命令准备；任何会读写 Rust target
   的实际执行另见第 10 条审批门。已批准的有界批次内，源码、fixture、snapshot 或审查 finding 可自主窄修；重型命令的首次执行和
   重跑只能发生在用户该次批准明确包含的命令集合、重试边界与终止条件内，不得弱化语义、测试或 snapshot 凑绿。批次结束、用户把
   heavy 时段切换给 078、批准未包含重跑，或需要扩大 crate/feature/profile/命令集合时，都必须重新请求批准。链完整后才冻结候选，
   并用新的领域 namespace/新 server 现场运行正式链；影响正式链的修复必须再请求相称批次，并用新的领域状态重跑。
10. **重型批次逐次审批、共享 Cargo 与磁盘**：本计划的实现授权**不包含**任何会读写 Rust target 的 build/test/clippy/fix 或
    编译型 schema generator。执行者每次准备进入一个有界重型批次前，必须向用户汇报精确命令、crate/feature/profile 范围、为何需要、
    拟议的重试边界与终止条件、
    预计是否增量复用、069 target/项目/Windows `C:` 实时容量、当前 078 与其他 heavy scope 状态，并等待用户对该批次的额外明确批准
    和人工串行调度；不得自行排队、轮询等待、根据锁空闲推定授权或决定与 078 的先后。获批批次内才可执行，并且所有会读写 Rust
    target 的命令必须全局串行，显式复用唯一 target
    `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`，并走 `multidev/justfile`
    已接入的 canonical build lock/watchdog；不得直接 Cargo、抢占/kill 活跃任务、绕过 watchdog、`cargo clean`、清理 069 缓存或
    静默创建第二个 target。获批时段内若锁状态与用户调度不符，停止启动并汇报，不自行等待抢占。每轮前后记录 RONDO 项目总占用、
    069 target 体积和 Windows `C:` 实际可用空间；240G 后不启动新的宽范围构建，先定位增长并收窄门禁，255G 主动停止，260G
    绝对停止。Windows `C:`、内存、swap、PSI
    与计数器仍服从根规则并 fail-closed；profile/features/toolchain 不兼容时先评估空间和增量代价，不自行清缓存重建。
11. **相称门禁与生成物**：在用户逐批批准后，至少完成实际受影响的 app-server-protocol、app-server、app-server-client、TUI
    聚焦测试与 TUI snapshot 审阅；触碰 core/thread-store/team-state/feature/config 时追加对应 crate/集成测试和生成物。若 shared
    core/protocol 改动按就近规则
    触发 workspace `just test`，必须把它作为单独或明确包含在内的重型批次请求用户批准，且只在资源门成立、用户安排 078 未占锁时运行
    一次相称最终轮；已知外部输入阻断须如实记录，不能冒充通过或
    通过反复宽跑消耗空间。按局部规则先测试，再 scoped `just fix`，最后 `just fmt`；fix/fmt 后不重复测试。
12. **授权与交付**：本任务只授权项目内 deterministic/fake/offline 正确性源码实现、测试代码编写、普通依赖下载/只读源码查询、
    不触发 Rust target 的轻量检查以及本地 Git 提交；重型构建和验证只在第 10 条逐批额外批准后授权。不授权 Docker、真实 API/模型、
    训练、性能测评、CI/PR、发布、上传、付费、远端状态变更、上游升级或主线整合。
    最终只提交 `worktree-077-m4-c1-durable-session-query`，不 merge/rebase/cherry-pick/push，不关闭 worktree 或归档分支。

## 4. 软性建议

以下建议来自 `dfc4278` 的现行接缝，但不固定具体 crate、trait、RPC、DTO、状态枚举、排序或 UI。执行者可以采用更干净、等强的
策略，并在关键决策记录中说明有实质影响的偏离。

- 069 已留下 `core::team::durable` 的窄 committed read 入口，`TeamStateHandle::from_committed_snapshot` 能在无 writer 的前提下
  hydrate 并校验 Team；优先在领域附近形成不泄漏 handle/文件路径的 query projection façade。若职责更适合 thread-store/team-state
  专用 read API，可新建窄能力，不必为“少改 core”把存储细节堆进 app-server。
- 现有 `StoredThread`/ThreadStore list/read 提供候选定位、parent/archive 事实和分页设施，但不会直接给出完整 SessionId/durable marker；
  普通 list 还可能扫描 rollout 并 repair，`use_state_db_only` 又只有 prototype metadata。优先增加或组合明确无写副作用、能够读取
  canonical SessionMeta 并发现 durable marker 的窄路径；正式 Session/Root 身份必须经该 seam 与 snapshot 验证，不要仅凭方法名假设
  query-only，也不要在 app-server 自建第二套目录扫描/registry。
- C0 的 identity/lifecycle/residency/availability/provenance 分轴、稳定双键 cursor、client connection/attachment/read ticket generation、
  stale/unknown 后整份重读和专用 TUI view/model 都是高价值复用输入；`prototypeFacts`、state-DB authority、固定 deadline、在线 mutation、
  cold unarchive preflight、RecencyAt 排序和文本布局不直接正式化。client ticket 只用于拒绝迟到 response，不能冒充 durable commit
  generation 或 Team revision。
- 当前 baseline 只有 archive 持久事实和本 server live residency，可观察不到正常 close 与进程退出的跨重启动因差别，也不能从
  本 server live map 的 absence 证明不存在其他进程 owner。建议让正式 projection
  对 whole-Session lifecycle 保持 typed unknown，并预留消费 owning lifecycle fact 的窄映射；不要由 077 持久化 close marker、读取
  `ShutdownComplete` 猜测终态或侵入 078 的 lifecycle owner。
- list 可以返回有界 summary，read 再返回完整但仍有界的 committed Team projection；也可以采用更合适的单一 projection，只要分页、
  omission、freshness 和故障边界清楚。不要为本任务预建过滤 DSL、全文搜索、通用 dashboard 或历史版本浏览。
- restart 正式链可以用两个 app-server 实例、真实子进程或等强的 test harness；关键是第二个现场只消费持久事实、没有复用 live Root/
  client cache，且全过程无 `/responses`、工具或其他外部副作用，不强制特定 fixture 结构。
- TUI 优先复用 `AppServerSession` 和 C0 专用 view/controller，避免继续扩大 `app.rs`、`chatwidget.rs` 等高触碰大文件；若小范围局部
  修改更清晰，也不强制拆模块。现有 background request → AppEvent 模式可用于避免慢 backend 卡住主事件循环，但允许等强的更优路线。
  只读页面可自主设计，只需让 identity、committed generation、lifecycle/residency、availability 与 stale/incomplete/unavailable
  对用户清楚可见，并让有界续页和 archived 记录实际可达。
- 测试优先复用现有 public JSON-RPC harness、client state machine 和 `insta`；side-effect-free 可用已有 spy/call counter、进程边界或
  前后状态断言证明，不建设通用审计、可信证明或复杂 fault/causal tracing 平台。
- 调试期保留已验证的编译缓存和场景；每次需要实际构建/测试时先提交有界批次给用户人工调度。获批批次内从首个未打通处边修边跑，
  只在纵向链稳定后再请求最后一次 fresh-state 正式轮与必要扩大门禁。如果窄修只影响某个 crate/场景，后续请求应优先收窄到直接
  因果面，不机械推倒整组或反复全量构建。

### 建议的阶段编排与退出条件

**A. 正式 read seam 与状态模型**

- 核对 durable marker/snapshot、ThreadStore discovery、live residency 和 C0 view 的真实接缝，冻结场景和初始 write set，不冻结 wire/UI。
- 退出条件：每个目标轴都能指出 canonical 来源或诚实 unavailable 边界；确认不需要 writer/activation/repair。

**B. app-server v2 正式 query**

- 打通 durable list/read、Root/child classification、committed Team projection、pagination 和 typed failure；补 public JSON-RPC 测试。
- 退出条件：新 server 可从持久状态发现/read，损坏/不完整/legacy/default-off 不伪造事实，调用前后没有 Session/Team side effect。

**C. client 与 TUI 只读链**

- 接通 typed client、view replacement/freshness 和只读 TUI，审阅 normal/stale/incomplete/unavailable snapshots。
- 退出条件：TUI 无 core/store 旁路或 control action，旧 response/cache 不能覆盖新 read，用户能分辨状态轴与不可用原因。

**D. 聚焦门禁、fresh-state 正式链与本地交付**

- 准备必要 schema/生成物、受影响测试和正式链的精确命令，逐批取得用户额外批准和人工串行时段后执行；记录资源值，并以最终实现
  和新领域 namespace 运行正式链。
- 执行者自审、修复并复验后只提交 077，保持 worktree clean，交给本会话审查者独立终审；终审 finding 继续按范围整改。
- 退出条件：相关门禁与正式链有效、未运行项诚实、共享写集可供后整合者窄收敛；未 merge/push。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已确认主工作区 clean `main@dfc4278233cf6c361fd6bbef7b3fb6107906f22d`，并从该提交创建
  `.claude/worktrees/077-m4-c1-durable-session-query` / `worktree-077-m4-c1-durable-session-query`。
- 已阅读根/`multidev/` 规则、README、当前 WBS、Plan 067/069/070/074、M4-S1/C0 最终日志及正式 query 相关源码/测试。
- 已确认 M4-S1 为 `M4_S1_PASS`、M4-C0 为 `M4_C0_PROTOTYPE_PASS`；正式 query 已解锁且不以前置依赖 M4-S2。077 的 TUI 范围仅为
  query-only presentation，控制型 TUI 继续等待后续任务。
- 已确认 `dfc4278` 未持久化 whole-Session `open/closing/closed/failed`；077 只能诚实查询冷态记录并把不可证明的 lifecycle 显示为
  unknown，后续只消费 078/owning lifecycle 提供的 canonical fact，不建立第二状态源。
- 已确认 078 worktree 同样基于 `dfc4278`；执行期间仅核对其 branch/HEAD/status 元数据，未读取其未提交实现。两任务当前共同触及
  `core/src/team/durable.rs`、`thread-store/src/lib.rs`、`thread-store/src/store.rs`，由后整合者收敛，共享 WBS 不在本计划写集。
- 规划时资源快照：RONDO 约 159G，069 target 约 72G，Windows `C:` 可用约 96G；正式执行以每轮实时计数为准。
- 已完成任务合同、query surface 与 durable read model 三路只读专项审阅；全部高/中等级 finding 已关闭，未运行构建或测试。
- 已实现独立默认关闭的 `durable_session_query` feature、稳定 app-server v2 `session/list`/`session/read` DTO/RPC、bounded state-DB
  locator、canonical Root `SessionMeta` 读取、同边界 marker/snapshot 校验、bounded committed Team projection、typed failure 和
  active/archive keyset pagination；没有 writer、repair、resume/load、模型或 control action。
- 已实现 app-server client 的 connection/attachment/read ticket、whole-view replacement、stale 与 committed generation + fingerprint
  高水位，并接入 `/sessions list|next|read|refresh` 的异步、单次 15 秒 timeout、query-only TUI 展示和三组 snapshot。
- 已通过目标代码静态检查和多轮独立只读审查；自审发现并修正 TUI snapshot 夹具与真实 operation/provenance 投影不一致。
  最终契约审查另发现 client 只保存最近一个 Session 高水位会让 `A → B → A` 绕过回退保护；已改为按 Session 保存
  generation+fingerprint，并补返回与 detach 回归。两项均已纳入 client/TUI 稳定重跑；`git diff --check` 通过且无
  `*.snap.new`。
- 已在获批重型时段以共享 069 target、canonical lock/watchdog、`CARGO_BUILD_JOBS=2` 完成 lower/protocol 聚焦门禁 42/42 和
  app-server 聚焦门禁 11/11。早先全九 crate 聚焦批次因 sustained memory PSI 主动停止；后续 client/TUI 聚焦批次因运行中出现
  scope 外 Cargo PID 主动停止且未执行测试，两次均已释放重型资源并如实汇报。
- 用户已批准把 `state/` 四文件纳入上述窄 locator 范围，并批准 077/078 在独立分支保留三个 shared 文件的各自改动；077 不读取、
  复制或覆盖 078，后整合者基于最新 main 做 query/lifecycle 兼容收敛。
- 修正 client 高水位与 TUI 夹具后，client/TUI 聚焦门禁最终稳定通过 23/23、0 flaky、0 retry、3462 skipped；此前调试轮为
  23/23 但含一次临时 SQLite pool timeout 的自动重试，正式证据采用修正后的稳定轮。
- stable/experimental app-server schema generator 各 1/1 通过，配置 schema generator 通过；生成差异只包含正式 Session Query
  request/DTO/bundle/export 与默认关闭 feature 的 6 行配置 schema 增量。
- state/features/team-state/thread-store 四 crate 全量门禁 567/567 通过、1 skipped；九个直接修改 crate 的 scoped `just fix`
  全部通过，最终 target-free `UV_CACHE_DIR=.uv-cache just fmt` 通过，且未在 fix/fmt 后重跑测试。
- workspace `just test` 只运行一次并在测试前被既有 `v8 = 150.4.0` 的缺失官方
  `librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz` 资产 404 阻断；未用不兼容 ABI 资产替换、未启用源码构建、未升级依赖。
  后续收窄的 core/protocol 全量轮在 protocol/077 相关项通过后，因大量 scope 外本地 mock 请求被 502 代理链截获而出现共同失败/超时；
  为避免 1145 个剩余测试继续长超时重试，按外部阻断终止条件由 wrapper 正常中断。本轮只记录为 2538 passed、44 failed、4 timed out、
  1145 not run，不冒充通过，也不把 scope 外基线失败归因于 077。
- 重型证据完成后的独立终审又发现并已窄修四组真实边界：legacy seconds 会形成不推进的 locator cursor；state row/path probe 会吞掉
  corruption 或 OS I/O；无 source generation 的跨页/多 locator-page 查询会过度声明 complete；client list/read 没有共用同 Session
  committed 高水位，也未校验 response identity 与跨请求 canonical Root 稳定性。client 现以独立于 Team 可用性的 client-local
  `Session -> Root` 轴保持已认证身份，错误 Root attachment 即使只收到无 Root/Team 的 typed unavailable 也不能通过。修复只使用已批准写集，没有引入 state registry/cache、
  source-generation 平台或 lifecycle 状态；新增 BLOB/path compression、archive-between-pages、list/read 双向 rollback/fingerprint、identity/root
  mismatch 与原子无部分提交回归。
- 上述终审修复后，正确 workdir 下的 target-free `UV_CACHE_DIR=.uv-cache just fmt` 与 `just fmt-check`、多轮 `git diff --check` 通过；
  lower、app-server、client/TUI 与最终合同审查者对最新 live diff 均未发现剩余高/中等级 finding。
- 用户释放 078 重型时段并授权 077/078 临时使用项目 `270/285/290GB` warn/stop/max 后，最新 review-fix 聚焦正式轮在共享 069 target、
  canonical lock/watchdog、`CARGO_BUILD_JOBS=2` 下通过 64/64：state/thread-store 18/18，app-server/client/TUI 46/46，均 0 failure/error。
  第二组首轮在测试前按 `project_reached_proactive_stop` 主动停止；精确删除 13 个本轮未触碰的陈旧 core/app-server-protocol incremental
  hash 目录 `13,537,357,824 B` 后，同一命令重跑通过。没有删除 `deps`、源码、fixture、JUnit 或其他任务数据。
- 提交级独立验收报告确认主 query 链成立，但发现四个中等级边界：InMemory 易失 metadata 冒充 persisted seam、client 接受矛盾 Team
  projection、双 gate 时 C0 被 `/sessions` 遮蔽、Team authored 文本可伪造 TUI 状态行。四项均已按根因窄修：InMemory 回落默认
  `Unsupported`；client 在提交前强制 `Available <=> Team` 且 viewer 为 canonical Root/Root role；`/sessions` 固定正式 query 并新增
  C0-only `/session-control`（C0-only 仍兼容旧 alias）；正式 renderer 只在展示边界单行化 label/author/summary，不改 canonical state。
- 整改代码经 lower/client、TUI 和完整合同三路只读交叉审查，均未发现剩余高/中等级 finding。正式聚焦轮在默认 features、dev/local、
  共享 069 target 下通过 8/8、4838 skipped，JUnit SHA-256
  `80d41f5afe70128ae9c3ae3855d2e975bb7e1b4c17c27ec53fe9f81db3543096`；随后四 crate scoped `just fix`、target-free
  `just fmt`/`fmt-check`/`git diff --check` 通过，依合同未在 fix/fmt 后重复测试。
- 整改期间 scoped fix 一次因项目到达 285GB 主动停止、一次因瞬时 scope 外 Cargo PID fail-closed；均完整回收且不冒充通过。依用户授权
  精确删除 18 个在本轮前形成且未被整改测试/clippy 触碰的可重建 incremental hash 目录，删除前测得 `6,477,017,088 B`；未动
  `deps`、本轮进度、源码或证据。最终 fix 轮 `stop=none / cleanup=none`，结束项目 `283,521,429,504 B`、target
  `189,474,492,416 B`、Windows `C:` 可用 `78,274,510,848 B`，重型资源已释放。

### 当前工作

- 产品实现、相称回归、生成物、独立验收整改、最终聚焦重型复验、109 文件精确分支 write set 核对和 077 本地提交均已完成；提交后
  worktree clean，交付留在 `worktree-077-m4-c1-durable-session-query`，未 merge/rebase/cherry-pick/push/关闭或重命名。最终 scoped
  fix 结束值：项目 `283,521,429,504 B`、069 target `189,474,492,416 B`、Windows `C:` 可用 `78,274,510,848 B`；
  `stop=none / cleanup=none`，重型资源已释放。

### 本任务剩余步骤

- 本任务范围内无剩余实施步骤；提交级独立只读终审完成后交回用户验收，不 merge/rebase/cherry-pick/push/关闭 worktree/重命名分支。

### 阻塞项

- 无 task-local 阻塞项。
- workspace-wide 验证仍有上述 V8 官方资产缺失和 scope 外 mock/代理环境阻断；它们保留为未通过项，不通过规避 ABI、升级依赖或扩大
  本任务来伪造绿色结果。

### 当前验收状态

- `M4_C1_QUERY_REMEDIATION_PASS / LOCAL_COMMIT_COMPLETE`。最新代码、生成物、独立验收整改、聚焦正式轮、scoped fix 与 077 本地提交
  均完成；workspace 非 077 阻断如实保留。

### 交接边界

- 执行者本地提交后停止，不自行 merge/push/关闭 worktree/归档分支；本会话审查者以提交与 live code/test evidence 验收。
- 077/078 进入主线的顺序不预先固定。后进入者/后整合者以最新 main 窄收敛 shared protocol、feature/config、Cargo lock 与 WBS，并
  运行 query + 最新 lifecycle 聚焦兼容验收；下游路线只见 `doc/WBS.md` 与 `doc/WBS/durable-team-runtime.md`。
- 本任务完成后冻结本计划，不在这里继续维护正式 Session control/TUI 或其他路线。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 077 包含 app-server v2/client/TUI 的 query-only 纵向链，不包含任何 control action | 满足用户对正式查询展示的要求，同时保留 WBS 中 control 等待 M4-S2 的条件边 | 范围/TUI | 已采纳 |
| 002 | 正式 Session/Team 事实只消费 S1 canonical durable read model；`prototypeFacts` 与 state DB prototype 退出正式事实链 | C0 输入只为验证语义，不能成为第二状态源或跨重启 authority | 状态源 | 已采纳 |
| 003 | 冻结分轴、完整重读、stable cursor 与故障诚实语义，不冻结 C0 的 RPC/DTO、排序、deadline、mutation、preflight 或 UI | 保留已验证价值，同时给实现者选择更优正式形态的自由 | API/实现自由 | 已采纳 |
| 004 | `app-server-protocol/` 是 077 query 主面；core `protocol/`、feature/config、Cargo lock 按条件共享，WBS 完全留给后整合者 | 精确区分任务所有权，避免把必要 query 协议误判为全部共享禁区 | 并行/整合 | 已采纳 |
| 005 | 唯一共享大型 target 为 069 target；每个重型批次先获用户额外明确批准并由用户人工调度 077/078 串行，再通过 canonical lock/watchdog 复用，不创建或清理第二套缓存 | 满足用户调度权、缓存一致性与约 82G 告警余量的空间约束 | 构建/磁盘 | 已采纳 |
| 006 | 普通源码问题自主窄修；重型命令及重跑逐批额外批准，最终证据使用最终实现和新的领域状态，不要求 clean rebuild | 给调试合理冗余，同时保留用户调度权，并避免旧现场或旧代码冒充正式 PASS | 执行/验收 | 已采纳 |
| 007 | 规划和实现无需直接修改主工作区；跨 worktree ignored 写入仅限指定 069 target，其他必要 ignored 主区写入须单独汇报 | tracked 交付可完全留在专用 worktree，避免污染用户 checkout | 工作区 | 已采纳 |
| 008 | 执行者只完成实现、自审和本地提交；独立终审由用户指定的本会话审查者负责，finding 可回到执行者整改 | 保持执行与验收职责分离，不把一次失败当作终止 | 审查/交付 | 已采纳 |
| 009 | 077 不把 cold/unloaded 推断为 closed；baseline 上不可证明的 whole-Session lifecycle 为 unknown，后整合者只消费 078 的 canonical fact | S1 当前没有持久 close 状态，猜测或新建 marker 会侵入 S2 并制造第二状态源 | lifecycle/并行 | 已采纳 |
| 010 | runtime residency 只声明查询所在 app-server 的正向 owner 观察；本 server 未命中不能证明全局 unloaded | baseline 没有跨进程 owner absence 的只读权威接口，查询也不得新建 IPC 或取得 authority | residency | 已采纳 |
| 011 | durable commit generation、Team revision 与 client read ticket generation 分开表达和校验 | 三者属于不同一致性边界，互相代替会把旧 committed state 或迟到 response 误标为 fresh | freshness | 已采纳 |
| 012 | locator 使用 state DB 的专用 bounded、typed-error、query-only 接缝，空 preview 也纳入；每个候选仍须经 canonical Root marker/snapshot 认证 | generic thread list 会隐藏部分失败、可扫描/repair 且过滤空 preview；把 SQL/schema 复制到 thread-store 又会造成层次泄漏。用户已明确批准 `state/` 四文件的窄扩展 | state/thread-store | 已采纳 |
| 013 | `session/list`/`session/read` 是稳定 v2 RPC，不标记 experimental；产品 feature 仍按现行 feature stage 记为 Experimental 且默认关闭 | RPC 合同的稳定性与产品 opt-in 生命周期是两条独立轴，普通 experimental API capability 不应成为 query gate | protocol/feature | 已采纳 |
| 014 | committed projection 同时暴露 canonical generation、完整 snapshot SHA-256 fingerprint 和独立 Team revision；client 以 generation+fingerprint 维护同 Session 高水位 | 单独 generation 不能发现同代内容变化，bounded view 或 revision 也不能替代完整 committed identity | core/client | 已采纳 |
| 015 | sustained PSI 后将聚焦批次按 lower/app-server/client+TUI 拆分并固定 `CARGO_BUILD_JOBS=2`；任何 scope 外 Cargo 出现立即停止并重新交还人工调度 | 在不清理共享 target、不弱化门禁的前提下降低峰值，并保持 077/078 串行构建约束 | 构建/资源 | 已采纳 |
| 016 | 077 可在独立分支保留与 078 重叠的三处 additive query 改动：`core/src/team/durable.rs` 拆出 validated-intent 后的只读 snapshot 入口以保留 marker/snapshot typed failure；`thread-store/src/lib.rs` 导出 locator/meta query DTO 与错误；`thread-store/src/store.rs` 为 store trait 增加默认 fail-closed 的只读方法 | 用户已确认 shared 文件本身不阻止轻量并行。整合时须保留 078 对 lifecycle/reload 的所有权，把新增符号按最新 main 加法收敛并完成 query/lifecycle 兼容验收；若出现同一语义所有权竞争则暂停 | shared core/thread-store | 已采纳 |
| 017 | workspace final 不以其他 V8 archive、关闭 sandbox feature、`V8_FROM_SOURCE` 或依赖升级规避 `v8 150.4.0` 的官方 `ptrcomp_sandbox` 资产缺失 | 现有 build script 明确把 pointer compression 与 sandbox 拼入 ABI 资产名，而官方该版本 Linux x86_64 release 只发布普通/ptrcomp/simdutf 变体；替换会伪造验证，源码构建和升级又超出范围与资源门 | workspace/依赖 | 已采纳 |
| 018 | 项目越过 240GB 后只完成单 crate scoped fix，不再运行 workspace 或多 crate 宽门禁；到 254.99GB 后停止所有 target 写入 | 遵守 240/255/260GB 分级门禁，同时在不清缓存的前提下完成直接修改 crate 的 lint；最终只剩 target-free 审查与 Git 交付 | 构建/资源 | 已采纳 |
| 019 | formal path lookup 保留 state fetch unavailable、row corrupt、indexed file missing 与 OS I/O unavailable 的 typed 区分；plain rollout 优先、`.zst` 仅在可证明 missing 时 fallback | Option-only lookup 会把真实 source failure 误报 corruption/NotFound，破坏 query failure honesty | state/thread-store | 已采纳 |
| 020 | locator collection 没有 source generation 时，cursor continuation 或单 RPC 内跨多个 locator page 保守返回 `complete=false/sourceChanged` | keyset 只稳定排序，不能证明 active/archive membership 跨读取不变；不为 077 新建 registry 或 generation 平台 | app-server/pagination | 已采纳 |
| 021 | formal client 的 list/read 共用按 Session 保存的 generation+fingerprint 高水位，并在 apply 前验证 response Session/Root 与跨请求 canonical Root；整页 staged 后原子提交 | ticket 只证明时序，不能阻止旧 committed state、错误 identity 或换 Root 建第二 key 被标 fresh | client/TUI | 已采纳 |
| 022 | 078 接管重型时段后，077 只做 target-free 整改与审查；最终复验须在 078 释放后重新申请并重新过实时容量门禁 | 遵守用户最新人工调度，避免通过排队/锁空闲推定授权或在临界磁盘继续写 target | 构建/调度 | 已采纳 |
| 023 | client-local canonical Root 轴独立于 committed Team 高水位；Team unavailable 时可保留已认证 Root，但不能推进 committed，高水位/Root 只在整个 response `Applied` 后原子更新 | canonical SessionMeta identity 不应因 snapshot 失败而遗失，也不能让 typed unavailable 为错误 Root attachment 背书；该内存同步边界不成为 durable authority 或 query cache | client/identity | 已采纳 |
| 024 | 最终复验仅临时使用用户批准的项目 `270/285/290GB` 门限；触及 stop 后只删除 13 个可重建且在本轮前已陈旧的 incremental hash 目录，再原命令重跑 | 保留 canonical watchdog 和最终代码证据，同时避免清理 `deps`、权威数据或来源不明产物；临时门限不写入仓库 | 资源/清理 | 已采纳 |
| 025 | InMemory store 不覆盖 canonical persisted `SessionMeta` seam，无法证明持久来源的 store 继承默认 `Unsupported` | 易失 metadata 与磁盘 snapshot 不属于同一 durable read boundary，拼接会伪造 `Available` | thread-store/app-server | 已采纳 |
| 026 | formal client 在任何 view/high-water/Root-map 提交前强制 `Available <=> Team`，并要求 Team viewer 等于 canonical Root 且 role 为 Root | ticket、generation 或 fingerprint 不能替代完整 projection 结构与 viewer identity 验证 | client/identity | 已采纳 |
| 027 | 双 gate 时 `/sessions` 固定正式 query、`/session-control` 固定 C0；仅启用 C0 时保留旧 `/sessions` alias，不按参数形状或 parse failure 回退 | 两套 parser 的 `list`、`refresh`、`read` 语义重叠，猜测路由会遮蔽或误触 control | TUI/routing | 已采纳 |
| 028 | Team authored label/author/summary 仅在正式 TUI renderer 边界折叠 whitespace/control 并 trim | 防止伪造结构化状态行，同时保持 canonical snapshot、fingerprint 与原文存储不变 | TUI/rendering | 已采纳 |
| 029 | 独立验收整改沿用任务专用临时 270/285/290GB 门限；仅删除 18 个可证明为本轮前形成且未被整改测试/clippy 触碰的 incremental hash 目录 | 保留正式测试与 scoped-fix 进度，在不动 `deps`、源码或证据的前提下完成 watchdog 门内验证 | 资源/清理 | 已采纳 |
