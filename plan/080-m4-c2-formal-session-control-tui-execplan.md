# Plan 080：M4-C2 正式 Session Control / TUI ExecPlan

> 本计划是 Plan 080 / M4-C2 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停对应动作，按本计划指定的 Codex 跨会话队列联系审查者取得批示；普通源码、
> fixture、snapshot、构建、测试或审查问题应在范围内自主窄修并重跑。原则性边界、授权外高危扩张或资源门 fail-closed 时才停止对应动作。
> 本计划只描述正式 Session Control / TUI；M4-Z(core)、M4-W0/W1 与其他跨任务路线以 `doc/WBS.md` 和
> `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 clean `main@0d842e0f568791765eed4eced46674b55ae0106e`，消费 M4-C1 已验收的正式 Durable Session Query 与
M4-S2 已验收的恢复/生命周期领域能力，完成一条默认关闭的正式控制链：

```text
app-server v2 → app-server client → TUI → authoritative Session query resync
```

操作者能够查看并控制领域状态允许的 Durable Team Session 生命周期。在线 mutation 只到达当前 canonical Root owner；冷态
archive、unarchive、delete 等操作只调用 M4-S2/原生 ThreadStore 生命周期；断线、重启、冲突或结果未知后，客户端不猜测、不自动重放
可能已执行的 mutation，而是通过正式 Session Query 重新同步。Plan 080 不提前实施 M4-Z(core)。

任务结束只允许以下结论之一：

- `M4_C2_CONTROL_PASS`：正式控制链、相关回归、fresh 正式轮和独立终审成立，且没有未关闭的高/中等级 correctness finding。
- `REPLAN_REQUIRED`：live 架构与本计划原则性边界存在无法在范围内诚实解决的冲突；普通可修的编译、测试、fixture、snapshot、容量整理或
  审查失败不能代替该结论。

### 完成/验收标准

- [x] 在修改产品代码前，先于最终合并树补跑 M4-C1 query read seam × M4-S2 lifecycle write seam 聚焦回归；通过后才作为 Plan 080
      基线。若暴露真实接缝缺陷，先形成回归并在 Plan 080 职责内窄修、重跑，不把 078 合流时的静态/格式检查冒充测试通过。
- [x] app-server v2 公开正式、typed 的 Durable Session 控制面，让操作者能发起当前领域可证明且 query 允许的在线 canonical
      Root owner lifecycle mutation、经 M4-S2 barrier 的显式 Session close，以及 cold archive/unarchive/delete。既有
      `thread/resume` 等正式领域能力可直接复用；不因 query 的 operation availability 字段机械新建一对一 RPC，也不要求保留
      C0 的 RPC、字段、代表性 mutation、固定 timeout 或命令布局。resume 可以有意激活 Root runtime，但不自动开始 model turn/API；
      它不属于下述无激活的 cold 操作。
- [x] 控制成功只来自现有 canonical Team/Session/ThreadStore 领域能力的成功边界。app-server、client 与 TUI 都不直接写 Team State、
      ThreadStore、rollout、snapshot 或其他持久介质，也不建立第二份 Session lifecycle/control 状态。
- [x] 在线 mutation 绑定发起时的正式 query proof（Session/Root/Team lineage 与 instance、committed generation/fingerprint）、目标
      expected state/revision，并在 server 端最终重验 current canonical Root owner 及相关 proof。错误 owner、replacement owner、陈旧前置条件或
      读后已变化均不提交成功；client read ticket、Team revision、query committed generation/fingerprint、close/owner generation 不可互相冒充。
- [x] cold archive/unarchive/delete 复用 M4-S2 已验收的 Root/subtree/ThreadStore 能力，不为操作加载 Agent、启动 model turn、工具或 API；
      active writer、descendant、partial、unknown、unsupported、conflict 与 failure 保留真实结果。delete 的测试只作用于任务专用 fixture。
- [x] mutation 已提交后遇到 response loss、timeout、disconnect、lag、EOF 或无法分类的 transport error 时，不自动 replay/retry；客户端进入
      stale/result-unknown（或等强明确状态），迟到 completion 不覆盖更新的 connection/attachment/view。只有新的正式 query 可以恢复
      fresh；已证明未提交的 preflight rejection 可安全修正后重新操作。
- [x] 每次操作完成、拒绝或结果未知后，TUI 都从正式 `session/list` / `session/read` 语义重读或明确等待用户重同步；不以 mutation response、
      UI cache 或 C0 projection 维护第三份当前状态。重启后可仅凭持久领域状态重建展示与可用操作。
- [x] detach、unsubscribe、切换与即时 disconnect 只解除客户端附着，不改变 Session/Team lifecycle。deferred idle unload、online close 和会
      移除 owner 的生命周期路径继续经过 M4-S2 close barrier；close failure、mutation-capable descendant、replacement owner 与 late
      completion 均不得伪报 closed、移除唯一可重试 owner或提前释放 authority。
- [x] TUI 以权威 query 的 availability/freshness/certainty 驱动展示；领域当前不能从既有 owner/store/barrier 事实证明的状态保持
      typed unknown，不为 UI 新建 whole-Session lifecycle registry。危险或终态操作有清楚确认，成功、拒绝、unknown/stale 与重同步结果对
      操作者可区分；UI 布局与交互方式由执行者自主选择。所有用户可见变化有相称 `insta` snapshot。
- [x] 正式 control 独立默认关闭；query-only、control-off、C0 experimental 隔离、legacy/non-durable、单 Agent、普通 V1/V2、Durable
      runtime 与 shared workspace 路径无回归。启用 control 不扩大原有 sandbox/approval，也不自动启用真实模型/API。
- [x] public JSON-RPC、client 状态机、TUI 与必要领域测试按职责覆盖 owner/precondition、cold lifecycle、unknown/no replay、显式重读、
      detach/close barrier、default-off 与非 Durable 兼容；不为同一语义堆叠重复重型测试或建设新 E2E/审计平台。
- [x] 调试全链打通后冻结本轮代码与配置，用新的任务专用 Session/store 完整运行一次正式控制场景。若该轮暴露可修问题，保留未受影响的
      已验证进度，修复后用新的领域状态重跑受影响场景；不以 `cargo clean` 定义 fresh。
- [x] app-server API 行为同步 `app-server/README.md`；实际受影响的普通/experimental app-server schema、配置 schema、Cargo/Bazel 生成物和
      TUI snapshots 使用仓库既有工具更新并审查，无遗留 `*.snap.new`、临时 fixture、调试输出或无解释生成差异。
- [x] 执行日志精炼记录实际控制集合/写集、首批兼容门、聚焦测试、fresh 正式轮、容量前后值、独立终审和未运行项；WBS 只更新当前阶段
      与交接，完成历史只追加到 `doc/WBS-COMPLETED.md`，不在多处复制执行流水账。
- [x] 最终检查 `git diff --check`、精确写集、受保护文件、相关测试、项目与 069 target 资源、主工作区和全部 worktree 元数据；只在 080
      分支形成 clean 本地提交，不合并、不推送、不删除 worktree、不重命名分支。

## 2. 范围

### 允许修改

以下是主要实现面，文件名与模块拆分不是固定路线。职责契合时可复用 C0/C1/S2；强行复用会扭曲语义时，可以新建与现有配置、生命周期、
错误、测试和观测方式契合的专用能力，但不重复建设第二套体系。

- `multidev/codex-rs/app-server-protocol/`：正式 app-server v2 control DTO/RPC、协议测试与 schema export。
- `multidev/codex-rs/app-server/`：query-to-control preflight/final revalidation、online owner 路由、cold lifecycle 适配、公共 JSON-RPC 测试和
  API README。
- `multidev/codex-rs/app-server-client/`：attachment/read/mutation attempt 状态、result certainty、unknown/no replay 与权威重同步。
- `multidev/codex-rs/tui/`：正式控制入口、展示、确认、错误/unknown/stale/refresh 交互、测试与 snapshots。
- 真实控制链证明需要时，可最小修改 `multidev/codex-rs/core/`、`thread-store/`、`team-state/`、`protocol/`、`features/`、配置、test support、
  Cargo/Bazel manifest/lock 与生成物；只增加缺失的 storage-neutral 领域接缝，不把 control 逻辑下沉为第二份 authority。
- 本计划“当前状态”和“关键决策记录”、`doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、完成时的
  `doc/WBS-COMPLETED.md`，以及一份或少量有实质内容的 Plan 080 `agent_log/`。
- 为首批合并树回归发现的真实 query/lifecycle 接缝缺陷补回归并窄修，即使缺陷位于上述相邻共享模块。

### 不允许修改

- M4-W0/W1、Workspace Binding/handoff、自动 worktree/Git 操作、Publication Critic、`eval/`、`training/`、`mydev/` 或 M4-Z(core) 实现。
- canonical Team State、ThreadStore、Session registry、event bus、writer authority 或 lifecycle 的第二套实现；通用 mutation relay/queue、
  daemon-wide Session manager、takeover、补偿事务、自动重试平台、dashboard、审计/可信或严格全局因果体系。
- 完整上游基线升级、其它上游增量、真实 API/模型、Docker、训练、测评、benchmark、CI/PR、发布、上传、付费或其它远端状态变更。
- 用户既有 Session/store 数据、069 的 `debug/deps` 和其它非本任务明确授权的缓存/资产；079 review worktree 及其三期现场。
- 未经用户批准的 merge/rebase/cherry-pick/push、worktree 删除或分支重命名/归档。

### 不允许读取/查看

- `.env.local` 内容、密钥/凭据、私有模型/测评正文、训练输出/权重、项目外个人文件和私有数据。
- `.claude/worktrees/079-review-3bb1253` 的 tracked/ignored 内容、diff、日志或三期现场；其它 worktree 的未提交文件内容。

### Git-ignored 与主工作区边界

全部 tracked 编辑应在 `.claude/worktrees/080-m4-c2-session-control-tui` 完成，预计不需要直接修改主工作区 tracked 或 ignored 文件。
已知且获准的跨 worktree ignored 例外只有：

- 首次重型门禁前，精确清理并后续复用
  `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target/debug/incremental`；
  保留 `target/debug/deps` 与其它仍有复用价值或来源不明的产物。
- 所有获批的 Cargo/test/clippy/fix/generator 命令继续写同一个 069 `target`，不创建 Plan 080 大型 target。
- 080 自身 `.codex/build-watchdog/`、任务专用 `/tmp` Session/store fixture，以及现有项目内共享 UV cache 的正常写入；这些都不提交。

如果 live 实现还要求直接写主工作区、其它 worktree ignored 资产或项目外路径，先停止该动作并报告准确路径、原因、影响与清理责任。

## 3. 硬约束

以下约束具有强制性。不得为了缩小改动、通过测试或让 UI 看起来完整而违反。

1. **精确基线与本地交付**：080 只消费 `main@0d842e0...` 已进入主线的事实，在专用 worktree/分支开发。执行期间不读取或修改
   079 review 现场。结束只提交 080 本地分支；合并、推送、worktree 删除和分支归档等待用户批准。
2. **单一权威与 server-side precondition**：正式 query 是控制面的状态读取来源，现有 canonical Root/Team/ThreadStore 能力是 mutation
   权威。UI/client 的 freshness 或 availability 只允许发起请求；server 必须绑定并最终重验 query lineage/Team instance/committed
   generation 与目标 expected state 等必要 proof。不能证明的 lifecycle/availability 保持 typed unknown，不能直接写权威状态或补建新 registry。
3. **mutation 结果诚实且不自动重放**：只有可确认的领域成功才报告 success；明确无副作用 rejection 与可能已经执行的 unknown 分开。
   timeout、response loss、disconnect 或不可分类错误后禁止自动 replay/retry，先 stale/unknown，再由新的正式 query 重建视图。普通代码或
   preflight 问题可修复重跑，但不能借此重放一个结果未知的 mutation。
4. **online/cold 分责**：在线 canonical mutation 只路由 current loaded Root owner；没有有效 owner 时 conflict/unavailable。cold lifecycle
   只走 M4-S2/原生领域能力，不为方便加载 Agent、启动模型/API、强制 takeover 或直接改介质。partial/unknown 不折叠为正常终态。
5. **detach 与 close barrier 不退化**：detach/unsubscribe/switch/disconnect 不改变领域 lifecycle；deferred unload、close 和可能移除 owner 的
   cold consumer 保留 exact owner/generation、descendant admission、late completion 与 replacement owner 保护，失败保留可重试对象。
6. **默认关闭与兼容**：正式 control 使用明确、默认关闭的产品 gate；query-only 不暴露 mutation，control-off 不产生后台控制工作。
   legacy/non-durable、单 Agent、普通 V1/V2、C0 experimental 隔离与 shared workspace 保持既有行为；缺失/损坏/不兼容不空建、不换 ID、
   不静默升级或切换状态源。
7. **允许有界调试、修复和复跑**：从第一个未打通接缝边修边跑，保留已经验证的进度。普通 correctness、build、fixture、snapshot 和审查
   finding 可自主窄修并在本授权范围重跑；不得删测试、弱化断言、扩大 fallback 或过早冻结凑绿。只有原则边界冲突、授权外高危扩张、
   未知 mutation 可能被重放、共享资产所有权冲突或资源门 fail-closed 才暂停对应动作。
8. **正确性测试而非测评平台**：只运行受影响 crate、协议生成、TUI snapshot、合并树兼容与 fresh 正式链所需的 deterministic/fake/
   offline/必要真实子进程测试。不调用真实 API/模型，不运行 Docker、训练、测评、benchmark、CI/PR 或发布；skip、未运行和基础设施失败
   不得表述为通过。除非用户另行扩大授权，不运行全 workspace 门禁。
9. **Plan 080 一次性重型授权**：用户已经批准本计划范围内必要的聚焦 Cargo build/test/clippy/fix、schema generator、snapshot 生成和
   修复后重跑，无需逐项再次请示；授权不覆盖全 workspace、其它任务、外部行为或扩大后的高危操作。所有重型命令全局串行，并与
   Docker、真实本地模型加载/推理互斥。
10. **共享 target 与临时容量门**：第一次重型命令前确认没有其它 Cargo/Docker/本地模型重型 owner，记录项目与 069 target 准确体积，
    仅清理已授权的 069 `target/debug/incremental` 可重建内容并复测体积。随后所有会读写 Rust target 的命令必须显式使用
    `CARGO_TARGET_DIR=/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`，通过
    `multidev/justfile` 已接入的 canonical `scripts/with-build-lock.sh`/watchdog 运行；不得 direct Cargo、禁用 wrapper、提高现有并发上限、
    并行构建或创建第二个大型 target。
11. **任务局部 270/285/290GB 门限**：Plan 080 重型命令只用进程级环境变量设置
    `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
    `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`，不修改脚本、配置或长期文档默认值。达到 270GB 后停止扩大测试范围并定位增长；
    达到 285GB 主动停止，290GB 绝对停止。Windows `C:`、内存、swap、PSI、Docker 与其它根门禁不变且继续 fail-closed；不得用 WSL
    虚拟余量代替宿主容量。每批前后保留 wrapper summary 和项目/target/Windows `C:` 实际值；必要时仍只能精确删除 069
    `debug/incremental` 中可重建部分。任务结束不保留任何全局 override，默认门限自然恢复。
12. **文档与生成物归位**：API 文档、schema、snapshot、Plan 状态、WBS 当前事实、COMPLETED 历史和 agent_log 各归其位；不在 Plan/
    README/log 中复制下游路线，不建设额外机器验收、审计或签名设施。
13. **跨会话请示与收口**：需要额外授权、出现计划外变数或不确定事项时，只按下述用户指定的 `codex queue` 方式联系审查者并以其
    回复为批示；不用文件、终端输出或人工提醒传话。每次发送后停止会话，不等待、不轮询、不重复发送；任务完成后必须在所有变更和本地提交完成后，
    按指定模板发送唯一的最终验收消息，然后停止会话。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

联系审查者，按照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：

```text
codex queue --thread UUID --message 'XXX'
```

其中UUID用审查者的会话的UUID： 01a03a62-346a-7211-9b28-18dc28cff513 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：

```text
codex queue --thread UUID --message 'XXX'
```

的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的/消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。

需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。

执行者最终完成任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：

```text
codex queue --thread UUID --message 'XXX'
```

其中UUID用  01a03a62-346a-7211-9b28-18dc28cff513 替换，这是审查者的会话的UUID。
XXX用以下内容代替：

“执行者完成了，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<你的执行完成的汇报>”

其中<你的执行完成的汇报>就是你本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：

```text
codex queue --thread UUID --message 'XXX'
```

的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。

## 4. 软性建议

以下建议基于 `0d842e0` live code，只帮助执行者高效收敛，不固定 crate、RPC 名称、DTO、操作枚举、timeout、调用顺序、TUI 布局、测试数量
或内部机制。执行者可以采用更简洁、更优雅且与现有架构契合的等强策略，并在关键决策记录中说明有实质影响的偏离。

- C1 的正式主面在 `app-server-protocol/src/protocol/v2/durable_session_query.rs`、app-server
  `request_processors/durable_session_query*.rs`、client `durable_session_query.rs` 与 TUI `durable_session_query*.rs`。优先扩展正式 query
  的 availability/freshness 语义并在操作后整份重读，不复制 projection 或分页状态。
- C0 的 `experimental_session_control` server/client/TUI 状态机已经验证 attachment/read/mutation generation、loaded-owner routing、
  expected-state conflict、unknown/no replay 和显式 refresh，可复用其职责清楚的同步机制；`prototypeFacts`、`SetRootState`、
  `/session-control` 文本布局和固定 timeout 只是原型选择，可以替换或删除正式链中的依赖。
- M4-S2 的 close/owner/residency 逻辑集中在现有 core AgentControl/ThreadManager、app-server thread lifecycle 与 ThreadStore
  archive/unarchive/delete 路径。先定位缺失的公开 façade 或结果类型；现有领域能力足够时只做窄适配，语义被扭曲时再新建专用能力，
  不把 app-server 变成 coordinator。
- 正式操作可以按 live 能力分为 owner-only、cold、当前不可用三类。query 与 server 共享同一 operation eligibility 语义或等强的单一
  判定入口通常更干净；无论采用何种 API，都要让 client/TUI 的旧读只能触发最终会被 server revalidate 的请求。
- 控制面跨 protocol/server/client/TUI，若现有中央文件已经过大，优先增加职责明确的 sibling module；不要为了强行复用继续膨胀
  `tui/src/app.rs`、`chatwidget.rs` 或 core 大模块，也不要机械追求改动行数最小而制造耦合。
- 测试可以分层：首批合并树 query×lifecycle 兼容；领域 owner/close/cold partial；public JSON-RPC；client unknown/no replay/late response；
  TUI confirmation/stale/resync snapshots；最后 fresh 产品链。每个语义由最合适层拥有，避免在所有层复制相同故障矩阵。
- 任务无需节省额度，效率优先。执行者确认有必要时，可使用更多子智能体并行调查不重叠的 protocol/server、client/TUI 或做独立终审，
  数量不超过当前最大并发配置且不铺张浪费；共享代码和最终集成由单一执行者负责，不建立评审委员会、审计清单或可信设施。

### 建议的阶段编排与退出条件

**A. 基线、缓存与合并树兼容门**

- 核对 main/080/069/077/078 与其它 worktree 元数据；确认无重型 owner，记录容量，按硬约束清理 069 incremental。
- 在未修改产品代码的 `0d842e0` 合并树上运行 query×lifecycle 聚焦回归；真实缺陷补回归、窄修、重跑。
- 退出条件：兼容基线有效，资源记录完整，未把基础设施阻断或旧证据冒充通过。

**B. 正式 protocol/server 与领域接缝**

- 根据 live capability 确定正式操作与结果/precondition 形状，打通 online owner 和 cold lifecycle，更新 public JSON-RPC 测试。
- 退出条件：所有 success 来自权威领域边界，错误 owner/stale precondition/partial/unknown fail-closed，无 store 旁路或自动激活。

**C. client/TUI 控制与重同步**

- 接通一次 mutation attempt 的 certainty、no replay、操作后正式 query 重读，以及 TUI 展示/确认/错误/unknown/stale/refresh。
- 退出条件：disconnect/timeout/late completion 不覆盖新视图，detach 不改 lifecycle，query-only/control-off 路径保持隔离。

**D. 聚焦门禁与生成物**

- 按实际写集运行受影响 crate、schema、snapshot、scoped fix/clippy/fmt 与相邻回归；逐个关闭真实 finding，控制测试范围与 target 增长。
- 退出条件：最终代码上的必要聚焦门通过，生成物已审阅，无 `*.snap.new` 或无解释差异；未运行项诚实记录。

**E. fresh 正式轮、独立终审与本地交付**

- 冻结本轮代码/配置，在新的 Session/store 跑正式 list/read→online/cold control→query resync→restart rebuild 场景；由未参与主体实现的
  审查者复核 authority、unknown/no replay、close/replacement/late completion、非激活 cold 操作与关闭态。
- 退出条件：正式轮对应最终候选，无未关闭高/中 correctness finding；Plan/WBS/COMPLETED/log 精炼同步，080 分支在所有变更完成后提交且 clean，
  不合并/推送。随后把原本要向用户输出的完整汇报填入用户指定模板，用唯一的 `codex queue` 消息通知审查者，发送后立即停止会话，不等待或轮询。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已核对 clean `main@0d842e0f568791765eed4eced46674b55ae0106e`、`origin/main@305f904...` 与全部 worktree 元数据；
  077、078 clean，未读取或修改 079 review 三期现场。
- 已从指定基线创建 `.claude/worktrees/080-m4-c2-session-control-tui` / `worktree-080-m4-c2-session-control-tui`。
- 已阅读根/`multidev/` 规则、README、当前 WBS、模板、Plan 070/077/078、相关完成记录、build watchdog 与 live query/control/lifecycle
  源码和测试。
- 已确认 078 合流只完成 shared 接缝静态/格式收敛，query×lifecycle 聚焦回归尚未运行；它是执行阶段第一批重型门禁。
- 计划期间的只读容量快照为：项目 `262,408,503,296 B`、069 target `187,705,122,816 B`、其中 `debug/incremental`
  `97,147,797,504 B`、`debug/deps` `91,746,553,856 B`、Windows `C:` 可用 `77,772,234,752 B`；核对时无 Cargo/Rust 重型 owner。
  这些是易漂移快照，执行者须在首次清理/构建前重新实测，并额外确认 Docker/本地模型 owner。
- 已完成三路只读专项梳理、主审查者复核与独立合同审查；无高/中等级计划 finding。计划未冻结 C0 RPC/UI/timeout
  或具体内部路线，未运行构建、测试或缓存清理。
- 执行阶段 A 已完成：宿主侧确认无 Cargo/Rust、Docker、RONDO heavy scope 或 GPU compute owner；授权清理前项目/069 target/
  incremental/deps 为 `262,408,773,632 / 187,705,122,816 / 97,147,797,504 / 91,746,553,856 B`，清理后为
  `168,019,832,832 / 93,316,182,016 / 102,400 / 91,746,553,856 B`，只移除了 069 `debug/incremental` 内容。
- 未改产品代码的合并树 query×lifecycle 聚焦门精确选择 45 项；44 项首轮通过，唯一 loopback 场景因 localhost 被代理为 HTTP 502
  而在 mutation 前失败，随后以新的临时 Session/store、明确 localhost `NO_PROXY` 和 `--retries 0` 复验 `1/1` 通过。两批
  watchdog 均 `stop=none / cleanup=none`，阶段 A 基线成立。
- 阶段 B/C 已完成单一稳定 v2 `session/control`：正式 query 提供 control proof/availability，server 在请求执行前重投影并精确比较
  proof；online `SetRootState` 在 durable mutation 线性化点复验 Team instance/revision/commit generation，`Close` 复用 M4-S2 owner
  removal barrier，cold archive/unarchive/delete 复用 ThreadStore 原生生命周期。typed Applied/Rejected/Partial/Unknown 贯穿
  protocol→client→TUI，transport 结果未知不自动重放。
- 正式 TUI `/session-control` 已完成 query-driven 展示、危险操作确认、accepted-read ticket、15 秒 timeout、late completion 隔离、
  detach/disconnect/lag/attachment replacement stale/unknown 与操作后自动正式重读；query/control 两个默认关闭 gate 相互独立，双开时
  正式入口优先，C0 prototype 仍由原 gate 隔离。
- 阶段 D 已更新 app-server README、stable/experimental app-server schema、config schema 与两份 TUI snapshot；generator、scoped fix、
  scoped clippy、fmt/fmt-check 和 diff 检查均通过，无 `*.snap.new`。最终正式控制聚焦轮 `17/17`，query×lifecycle 邻接回归
  `47/47`，均使用 canonical lock/watchdog、指定 069 target、`--retries 0` 且 `stop=none / cleanup=none`。
- 阶段 E 使用新的任务专用 Session/store 完成 list/read→owner close→query resync→cold archive/unarchive→进程重启→list/read rebuild
  →delete→SessionNotFound；操作未启动 turn 或模型。该 fresh 场景包含在最终 `17/17` 中。未参与主体实现的只读独立终审未发现
  high/medium correctness finding。
- 最终重型轮后的项目/069 target 为 `251,315,224,576 / 176,363,339,776 B`，未触及 270GB 告警线；未运行 Docker、真实 API/模型、
  训练、测评、benchmark、CI/PR 或 full-workspace 门禁。

### 当前工作

- 产品实现、生成物、fresh 正式轮、聚焦回归和独立终审均已完成；正在同步权威文档、执行日志并形成 080 clean 本地任务提交。

### 本任务剩余步骤

- 完成精确写集/资源/worktree 元数据复核，在 080 分支形成 clean 本地任务提交。
- 把最终 TUI 汇报原样嵌入用户指定模板，以声明“我是 Plan 080 / M4-C2 执行者”开头发送唯一跨会话验收消息，然后立即停止会话。

### 阻塞项

- 无计划级阻塞。执行时若 canonical lock、Windows `C:` 实际余量、cgroup/watchdog 或必要资源计数不可用，按根规则 fail-closed 并处理
  对应资源问题；不把资源拒绝当作产品失败。

### 当前验收状态

- `M4_C2_CONTROL_PASS`：阶段 A--E、fresh 正式轮和独立终审均已完成，无未关闭的高/中 correctness finding。

### 交接边界

- 执行者从阶段 A 开始；不得把计划编制时的源码调查、WBS 更新或历史 077/078 证据冒充 Plan 080 产品实现与验收。
- 额外授权、计划外变数、需要批示的不确定项以及最终验收交接，都只使用本计划指定的 `codex queue --thread 01a03a62-346a-7211-9b28-18dc28cff513`；
  每次发送后停止会话，不等待、不轮询、不重复发送。
- Plan 080 完成后冻结本计划；M4-Z(core) 与其它后续工作只链接当前 WBS，不在本计划继续规划。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 080 从 clean `main@0d842e0...` 建立专用 worktree，结束只提交本地分支 | 保护主工作区与并行现场，遵守用户 Git 停止边界 | Git/交付 | 已采纳 |
| 002 | 第一批重型门禁先跑未改产品代码的合并树 query×lifecycle 聚焦回归 | 077/078 shared 接缝只做过静态收敛，不能把历史分支证据当合并树测试 | 基线/验收 | 已采纳 |
| 003 | 正式 control 消费 C1 query 与 S2 lifecycle；C0 只保留有价值的场景/同步语义，不冻结实现布局 | 避免 prototype input/状态源进入正式链，也给执行者选择更优 API/UI 的空间 | 架构/control | 已采纳 |
| 004 | online owner mutation、cold lifecycle 与 query resync 分责；所有 success 由领域层拥有 | 防止控制面成为 writer/状态源，同时保持现有 Root authority 与 ThreadStore 生命周期 | authority/lifecycle | 已采纳 |
| 005 | 结果未知的 mutation 不自动重放；普通未提交问题和代码 finding 可窄修重跑 | 同时保护外部效果唯一性与调试效率，不因一次可修失败整组报废 | failure/debug | 已采纳 |
| 006 | 只清 069 `debug/incremental` 并复用同一 target；临时 270/285/290GB 仅通过命令环境变量生效 | 保留高价值缓存并在当前容量下安全构建，不永久抬高项目门禁 | build/resources | 已采纳 |
| 007 | 所有 tracked 变更留在 080 worktree；唯一预期跨 worktree ignored 写是 069 target | 当前任务不需要主工作区私有配置或其它现场，便于审查和清理 | worktree/ignored | 已采纳 |
| 008 | 终审只要求关闭高/中 correctness finding；不建设额外审计、可信或机器验收体系 | 关注功能正确性并避免为个人开发制造第二套冗余平台 | review/scope | 已采纳 |
| 009 | 请示、批示和最终验收交接只使用用户指定的 Codex 跨会话队列，发送后停止会话 | 确保执行者与审查者跨会话消息可靠交付，不用文件、终端或人工提醒绕路 | coordination/handoff | 已采纳 |
| 010 | 执行者发送的每一条审查者跨会话队列消息都在开头明确声明“我是 Plan 080 / M4-C2 执行者” | 避免跨会话沟通中身份混淆；该要求同样适用于最终验收消息 | coordination/handoff | 已采纳 |
| 011 | 正式控制采用单一稳定 v2 `session/control`；online Root state/close 与 cold archive/unarchive/delete 共用 query proof 和 typed certainty，resume 复用正式 `thread/resume` | 避免复制 C0 多 RPC/projection，也不为已有 resume 重建一套协议；一个入口便于 server final revalidation 与 client no-replay | protocol/control | 已采纳 |
| 012 | `Close` 的成功 effect 命名为 `OwnerClosed`，后续正式 query 的 whole-Session lifecycle 仍可为 `Unknown` | M4-S2 能权威证明 loaded canonical Root owner 已经过 barrier 并移除，但没有 whole-Session lifecycle registry；避免为 UI 虚构更强终态或另建状态轴 | lifecycle/UI | 已采纳 |
