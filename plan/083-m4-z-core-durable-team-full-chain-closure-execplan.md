# Plan 083：M4-Z(core) Durable Team 全链收口 ExecPlan

> 本计划是 Plan 083 / M4-Z(core) 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停对应动作，并按本计划指定的 Codex 跨会话队列联系审查者取得批示。
> 普通源码、fixture、snapshot、schema、构建、测试、局部竞态或审查问题应在授权范围内自主修复和重跑；原则性边界、授权外高危扩张、
> 未知 mutation 可能被自动重放或资源门 fail-closed 时才停止对应动作。
> 本计划只描述 M4-Z(core)；跨任务路线、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 clean `main@90e905168039effbea796753d0f29148830a243f`，消费已进入主线并分别取得 `M4_S1_PASS`、
`M4_C1_QUERY_PASS`、`M4_S2_PASS`、`M4_C2_CONTROL_PASS` 的 Durable Team S/C 能力，从全新环境完整打通：

```text
创建 Durable Team Session / canonical Root
→ child Agent 与 Team State 协作推进
→ 非 owner 权威查询
→ 客户端断开或进程终止
→ 新进程恢复同一 Session / Root / TeamInstance
→ 继续 mutation 与查询/控制重同步
→ close、archive/unarchive/delete 等生命周期操作与终态
```

本任务以集成验收和产品收口为主，不预设必须增加功能。只有 live 全链暴露真实 correctness 缺口时，才在既有职责内窄修；若强行
复用会造成职责耦合或语义扭曲，可以新建与现有配置、生命周期、错误、测试和观测方式契合的专用能力，但不得重复建设第二套权威体系。

任务结束只允许形成以下诚实结论之一：

- `M4_Z_CORE_PASS`：最终候选的相称门禁、全新 Session/store 正式全链和独立终审均成立，没有未关闭的高/中等级 correctness finding。
- `M4_Z_CORE_FAIL`：在本计划边界内经过合理调试、窄修和复验仍未满足一项或多项宏观验收；必须说明失败接缝、最后有效证据和未满足项。
  资源或基础设施 fail-closed 应单独说明，不能伪装为产品 correctness 失败，也不能冒充 PASS。

### 完成/验收标准

- [ ] 从新的任务专用 store 创建新的 Durable Team Session、canonical Root 和空 TeamInstance；三类身份来源明确且后续不被重铸、映射或
      偷换。Root/child 通过正式产品入口推进 Team State，至少一个 child 成功结果达到 durable commit 并能在后续恢复后观察。
- [ ] 非 owner 通过正式 Session Query 读取同一份自洽 committed Team view；并发、损坏或不可证明时只返回诚实的
      stale/unknown/unavailable/unsupported/incomplete，不拼接不同提交边界或退回第二份状态源。
- [ ] 模拟真实客户端断开，并至少完成一次旧进程真实终止、新进程从同一持久 store 恢复相同 `SessionId`、canonical Root
      `ThreadId`、`TeamInstanceId` 和旧 committed Team State；恢复或 member reload 不自动启动模型、工具或真实 API。
- [ ] 恢复后的 canonical owner 能继续一次或多次 Team mutation，旧状态仍保留；第二 owner 与单独 child resume 都不能取得重叠
      Root authority 或绕过 canonical Root 成功提交。只有旧 authority 真实释放后，新 owner 才能取得写资格。
- [ ] 顶层 `thread/fork`、`/new` 与 slash `/clear` 创建新的 Session/Root/空 TeamInstance，来源 Team 不变；
      `spawn_agent fork_turns=none/all/N` 只改变 child conversation context，child 仍属于原 Session/root/Team。纯 UI clear 不改变领域身份。
- [ ] 通过正式 Control/TUI 路径完成当前领域允许的 online owner 操作与 cold lifecycle 操作。online mutation 只路由 current canonical
      Root owner；cold archive/unarchive/delete 不为控制加载 Agent 或启动 turn/model/API，也不绕过领域能力直接写持久介质。
- [ ] Applied、Rejected、Partial、timeout、response loss、disconnect、late completion 与 Unknown 等代表性结果都通过正式 query
      重建视图。可能已经执行的 mutation 不自动 replay/retry；旧 attachment/read/attempt 的迟到结果不能覆盖更新视图。
- [ ] detach 与 unload/close 保持分离；正常 close、失败 close、mutation-capable descendant barrier、异常进程退出、archive、unarchive、
      delete 及其 partial/unknown 后的恢复资格与权威事实一致。失败 teardown 不伪报完成、不提前释放 authority、不丢失唯一可重试 owner；
      terminal delete 之后不得再被正常恢复误认。
- [ ] Durable、query、control 的默认关闭态，以及 query-only、control-off、legacy/non-durable、单 Agent、普通 V1/V2 和 shared workspace
      路径保持既有行为；非法组合 fail-closed，不自动升级旧 Session 或创建空 Team 覆盖 durable marker。
- [ ] 优先复用 Plan 069/077/078/080 已有领域测试、fresh store、公开 JSON-RPC、client/TUI 状态机和 snapshot 设施；只补能证明全链或真实
      缺口所需的场景/fixture，不另建第二套全链 runner、Session registry、状态源、控制平台、事件总线或审计/可信设施。
- [ ] 实际修改面的 schema、snapshot、API 文档和生成物使用仓库既有工具同步并审阅；无遗留 `*.snap.new`、临时 fixture、调试输出或
      无解释生成差异。只运行覆盖 S/C 完整链与实际修改面的相称门禁，不要求且不运行 full workspace 全量测试。
- [ ] 调试阶段先逐段打通并保留已验证进度，从首个失败接缝继续修复。确认整条产品链已经稳定后，冻结本轮代码与配置，再以新的
      Session/store、无残留任务进程完整运行一轮；只有最终候选的该轮可作为 `M4_Z_CORE_PASS` 正式全链证据。正式轮暴露小问题时允许
      修复，但修复后须重新冻结，并从新的干净领域状态完整重跑最终全链。
- [ ] 执行者完成全部候选实现、门禁、正式轮、自审、候选状态文档和精炼执行日志后形成 clean 本地提交，再按指定队列通知本会话审查者。
      此时 Plan/WBS 只可写 `AWAITING_REVIEW` 或等强候选状态，不提前写 `M4_Z_CORE_PASS`，`doc/WBS-COMPLETED.md` 不提前追加完成历史。
- [ ] 本会话审查者独立终审；真实高/中等级 correctness finding 必须在本范围内交回执行者整改并复验。每轮整改完成后，执行者先提交全部
      变更再重新通知。审查聚焦正确性、功能性、遗漏接缝和局部修复的全局回归，不扩张为重型复跑、审计平台或额外可信体系。
- [ ] 最终通过时由审查者写入精炼验收报告，更新本计划动态状态、受影响 WBS 当前事实和 `doc/WBS-COMPLETED.md`，并提交该验收收口；
      最终检查 `git diff --check`、精确写集、生成物、资源退出、主工作区与全部 worktree 元数据。083 分支/worktree 保持 clean，
      不合并、不推送、不删除 worktree、不重命名或归档分支。失败则保留诚实失败/阻断事实，不追加虚假完成历史。

## 2. 范围

### 允许修改

- `multidev/codex-rs/` 内与 canonical Team durability/read、Root authority、Agent graph/residency、Session/thread lifecycle、app-server v2
  query/control、app-server client、TUI 和既有 feature/config gate 直接相关的实现、测试、fixture、schema、snapshot 与 API 文档。
- 若完整产品链证明现有接缝不足，可在上述职责内重构或增加专用模块/crate/test support；具体 crate、API、RPC、DTO、介质、调用顺序、
  timeout、TUI 布局、fixture 和测试数量由执行者根据 live code 自主选择。
- 为实际变更所必需的 `Cargo.toml`、`Cargo.lock`、`MODULE.bazel.lock`、`BUILD.bazel`、配置 schema、app-server schema 和其它既有生成物；
  只通过仓库规定工具更新并审查。
- `plan/083-m4-z-core-durable-team-full-chain-closure-execplan.md` 的“当前状态”和“关键决策记录”、一份或少量精炼 Plan 083 `agent_log/`，
  以及完成时受影响的 `doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、必要的其它当前四期 WBS 指针与 `doc/WBS-COMPLETED.md`。
- worktree 内既有命令生成的 git-ignored watchdog、任务专用 fresh Session/store 和可再生成测试临时资产；普通依赖下载与只读源码查询。

### 不允许修改或实施

- M4-W0/W1、Workspace Binding/handoff 占位或实现；Plan 082、Publication Critic 三期资产、`training/`、`eval/`、`mydev/`。
- scheduler、自动 spawn/路由、自动 Git/worktree/merge/push、通用 dashboard/daemon manager、第二套 Team State、Session registry、writer
  lock/lease、控制面状态源、事件总线、跨进程 mutation relay/queue/IPC router、补偿事务、强制 takeover 或通用审计/可信平台。
- 完整上游基线升级、性能 benchmark、模型质量测评、真实 API/模型、训练、Docker、CI/PR、发布、上传、付费或其它真实外部状态变更。
- 用户既有 Session/store、来源不明的缓存/资产、其它 worktree 的 tracked/ignored 内容或未提交实现；不覆盖、stash、回退、清理或
  吸收并行任务现场。
- 未经用户后续批准的 merge/rebase/cherry-pick/push、worktree 删除和分支重命名/归档。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、私有模型/测评正文、训练输出/权重、项目外个人文件或私有数据。
- 其它 worktree 的未提交文件内容、diff 或设计；并行核对只使用 branch/HEAD/status、锁/进程/资源元数据和已经进入 `main` 的事实。

### Git-ignored、共享 target 与主工作区边界

全部 tracked 编辑都在 `.claude/worktrees/083-m4-z-core-durable-team-closure` 完成。预计不需要直接修改主工作区 tracked 或 ignored 文件。
本任务已知且获准的跨 worktree git-ignored 例外只有：

- 所有 Cargo/test/clippy/fix/schema generator 等会读写 Rust target 的命令显式复用
  `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`；不创建 Plan 083 大型 target。
- 首轮宽聚焦门禁前，如果实测/合理预计无法安全保持在 270GB 以下，可精确删除上述 target 的 `debug/incremental` 可重建内容；保留
  `debug/deps`。只有该清理仍不足时，才核实并处理能明确证明可重建、且不含源码或证据的 debug 产物，不清理来源不明资产。
- 083 自身 `.codex/build-watchdog/` 与任务专用 `/tmp` fresh Session/store 可由既有命令创建；这些资产不提交。

主物理仓库中的 git-ignored `codex-source-code/` 若确有冻结上游语义疑问，只允许只读核对，不在其中 checkout、fetch、编辑或生成文件。
如果 live 实现还要求直接写主工作区、其它 worktree ignored 资产或项目外路径，先停止该动作，并通过本计划指定队列报告准确路径、原因、
影响与清理责任。

## 3. 硬约束

以下约束具有强制性。不得为了缩小改动、通过测试或快速宣布收口而违反。

1. **精确基线与本地交付**：083 从 clean `main@90e9051...` 建立专用 worktree，只消费已进入该基线的事实。执行者保护主工作区和
   其它 worktree，不读取或修改未提交现场。结束只提交 `worktree-083-m4-z-core-durable-team-closure`；合并、推送与分支归档等待用户批准。
2. **同一权威域闭合全链**：Session/Root lineage、TeamInstance、canonical Team committed state、Root writer authority、query 和
   lifecycle/control 必须继续消费现有同一领域事实。query/control/TUI 不成为第三份当前状态；child writer、client cache、state DB
   locator、一次性 preflight 或 UI availability 都不能替代 canonical Root authority 与 server/领域最终复验。
3. **恢复、成功和生命周期结果诚实**：成功只在对应结果已达到可恢复边界后成立；无法证明 identity、commit、owner、teardown 或冷态
   终态时返回 typed conflict/partial/unknown/unavailable/unsupported/failure，不创建空 Team、不换 ID、不切换状态源、不伪报关闭或删除。
4. **未知 mutation 不重放**：普通测试和实现失败可以修复重跑，但 response loss/timeout/disconnect 后可能已经执行的 mutation 禁止自动
   replay/retry；必须先经正式 query 重读并由用户/测试场景根据权威结果安全继续。迟到 completion 不覆盖新 owner、attachment 或 view。
5. **边界与兼容不扩张**：不等待、占位或实施 W 线，不触碰三期 Plan 082，不新增任务范围外平台。Durable/query/control 默认关闭、
   query-only/control-off/non-durable/shared workspace 等既有路径必须保留；不能为收口机械重写已经验收的 S1/S2/C1/C2。
6. **允许充分调试与自主修复**：在调试期逐段打通、保留已验证进度，从首个未通接缝继续。范围内普通代码、fixture、schema、snapshot、
   build/test、局部竞态和审查 finding 可自主窄修并重跑，无需因一次可修失败停工或整组报废；不得删测试、弱化断言、扩大 fallback 或
   把 skip/旧证据冒充通过。原则性合同冲突、授权外高危动作、未知 mutation replay 风险或资源门拒绝才停止对应动作。
7. **相称门禁与正式证据**：只运行 S/C 全链与实际修改面的 core、thread-store、app-server、protocol、client、TUI、schema、snapshot、
   scoped fix/clippy/fmt 和相邻回归；本任务明确不要求 full workspace 全量测试。先调试稳定、后冻结候选、再从全新 Session/store 完整跑
   一轮，最终 PASS 只引用最终候选的正式轮和未被后续改动推翻的相称门禁。
8. **一次性重型授权与统一入口**：用户已授权本计划范围内必要的聚焦 Cargo build/test/clippy/fix、生成器、snapshot 和修复后重跑，
   无需逐项再次请示。所有重型命令全局串行、显式使用同一 069 `CARGO_TARGET_DIR`，并通过 `multidev/justfile` 已接入的 canonical
   `scripts/with-build-lock.sh`/watchdog；不得 direct Cargo、绕过 wrapper、提高并发上限、并行构建、`cargo clean` 或与 Docker/真实本地
   模型加载/推理重叠。额外授权、计划外变数和实质不确定决策才通过指定队列请示。
9. **Plan 083 临时容量门**：重型命令只以进程级环境变量设置
   `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
   `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`，不修改脚本、配置或长期默认值。每批前后记录项目总占用、069 target、
   `debug/deps`、`debug/incremental` 与 Windows `C:` 实际余量；达到 270GB 后不扩大门禁，285GB 主动停止，290GB 绝对停止。
   Windows `C:`、内存、swap、PSI 与其它根门禁不变并继续 fail-closed，不得用 WSL 虚拟余量代替；任务结束不做无目的清理。
10. **外部与安全禁区**：不调用真实 API/模型，不训练、不运行 Docker、benchmark、CI/PR、发布、上传、付费或远端状态变更；不打开、
    搜索、打印、复制或记录 `.env.local` 内容。测试/fake/offline、真实子进程和未运行项必须清楚区分。
11. **文档、审查与提交顺序**：执行者完成候选实现、正式证据、候选状态文档和执行日志后先提交，再按指定模板通知审查者；通知时
    WBS/Plan 标记 `AWAITING_REVIEW`，不得提前写 PASS 或向 COMPLETED 追加历史。若审查不通过，执行者在同一 worktree 整改、复验、
    提交后再通知；若审查通过，由审查者写验收报告、同步最终 Plan/WBS/COMPLETED 并提交验收收口。任何一方都不得在自身仍有未提交
    变更时发送验收消息，也不得重复发送相同消息。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03c53-7cf4-78e0-bea3-c1eb7c4015da 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。

需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。

执行者最终完成任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<你的执行完成的汇报>”
其中<你的执行完成的汇报>就是你本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。

执行者给审查者发送消息的时候，必须主动表明身份。

每条队列消息开头应明确写“我是 Plan 083 / M4-Z(core) 执行者”。本计划不预先替执行者拼接最终 shell 命令；执行者必须按上文规则把
UUID替换为 `01a03c53-7cf4-78e0-bea3-c1eb7c4015da`，安全处理消息正文中的单引号，并在发送后立即停止会话。

## 4. 软性建议

以下建议基于 `90e9051` live code，只帮助执行者高效收口，不固定实现路线。执行者可以采用更简洁、更优雅、与现有架构更契合的等强
策略，并在关键决策记录中说明有实质影响的偏离。

- 开始时把 Plan 069 的 `core/tests/suite/durable_team_session.rs`、Plan 078 的 AgentControl/residency/ThreadStore lifecycle 回归、
  Plan 077/080 的 app-server `v2/durable_session_query.rs`、client/TUI query/control 状态机和 snapshots 映射到十类产品场景。
  先找真正缺失的跨层接缝，不做全仓 census，也不因“全链”复制每层已有测试。
- 全链主场景宜优先落在已经能够跨进程、调用公开 JSON-RPC 并创建 task-owned store 的既有产品 harness；TUI 的确认、certainty、no-replay
  与重同步可由现有 client/TUI 状态机和 snapshot 在其职责层证明。若 live 架构表明另一组合更清晰，可以自主调整，不强制新增单一巨型测试。
- close、archive/unarchive/delete 会改变后续现场或操作可用性，可以在同一 fresh store 内使用多个新 Session 组成正式场景组，不必为
  追求一条字面线性脚本扭曲领域生命周期。关键是所有场景使用最终候选、全新领域状态且共同证明完整产品链。
- 故障矩阵优先选能代表提交前拒绝、提交后 response loss/unknown、partial cold lifecycle、descendant barrier 与 exact owner replacement 的
  少量确定性 interleaving；不枚举笛卡尔积，不建设通用 fault scheduler、因果追踪或测试专用 daemon。
- 如果初始全链在现有产品上已经成立，只补集成回归、snapshot/fixture 与收口文档即可；如果暴露真实产品缺口，先补最小回归，再在原
  owner 模块修复。不要为了显得“有实现”而改动已通过的 S/C 代码。
- 可使用少量子智能体并行调查互不重叠的 core/thread-store、protocol/server、client/TUI 或独立终审；共享文件和最终集成由单一执行者
  负责，不建立评审委员会、审计清单、签名或机器可信设施。

### 建议的阶段编排与退出条件

**A. 基线、资源与覆盖映射**

- 核对 083/main/069 target/其它 worktree 元数据、无重型 owner和当前容量；映射现有 S/C 测试与十类全链场景，确定首个真实缺口。
- 退出条件：所有目标结果都有现有证据入口或明确待补接缝；没有读取并行未提交现场；首批聚焦命令和容量增长预期明确。

**B. 调试全链与真实缺口修复**

- 用小型 task-owned Session/store 逐段打通创建→child/Team mutation→非 owner query→断开/进程退出→cold resume→继续 mutation→
  query/control resync。遇到缺口先补回归，在职责 owner 内窄修并从首个失败处继续。
- 退出条件：调试现场连续闭合身份、committed state、单一 authority 与正式 query/control 路径；普通问题已修复，不依赖手工改 store。

**C. 分叉、故障、生命周期与关闭态收口**

- 补齐 fork/new/clear 与 child spawn、response loss/unknown/no replay、close/descendant barrier、archive/unarchive/delete/partial 以及 gates/
  non-durable/shared workspace 场景。
- 退出条件：结果未知不自动重放，失败不伪造终态或 authority handoff，所有宏观验收均有相称产品级或职责层回归。

**D. 聚焦门禁、生成物与候选冻结**

- 按实际写集运行必要 crate/协议/schema/snapshot/scoped fix/clippy/fmt 与相邻回归；逐项修复真实 finding并控制 target 增长。
- 退出条件：最终代码和生成物稳定、无遗留临时产物，计划候选状态/日志记录了准确证据与未运行项；不再处于探索性修改阶段。

**E. fresh 正式全链、独立终审与本地交付**

- 冻结代码与配置，从新的 Session/store、无残留任务进程完整运行正式场景组。执行者完成全部候选变更、把 Plan/WBS 标记为
  `AWAITING_REVIEW` 并提交后，按指定队列模板通知审查者。
- 审查 finding 在同一范围内整改并复验；影响正式链的修复完成后重新冻结，并从新的干净状态重跑完整正式场景组。
- 审查通过时由审查者记录报告、同步最终 Plan/WBS/COMPLETED 并提交；不通过时交回执行者继续整改。
- 退出条件：`M4_Z_CORE_PASS` 或有证据的 `M4_Z_CORE_FAIL` 成立；WBS/COMPLETED/日志归位；083 分支 clean，未合并、未推送、未归档。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已在指定 083 worktree 完成 live S/C 全链映射、实现和职责层回归；主工作区、其它 worktree、Plan 082 与 W 线未进入写集。
- 全链暴露并关闭持久 child graph 失败被吞、unloaded Open descendant 绕过 Root close、公开 close 错误类型不准确、V2 缺少终态
  `close_agent`、JSON schema enum payload 键名偏离 serde wire 等 correctness 缺口。
- 新增公开 app-server v2 全链回归，从任务私有 fresh store 创建 Root/child 并提交 Team 事件，真实终止旧 OS 进程后由新进程恢复同一
  Session/Root/TeamInstance，继续 mutation，完成 descendant barrier、显式 child close、owner close、archive/unarchive/delete。
- stable/experimental JSON schema 与 precomputed exports 已用既有生成测试同步；30 项宽聚焦回归、实际修改 crate 的 scoped clippy、
  `just fmt` 和 diff 自审均通过，无 `*.snap.new` 或临时 fixture。
- 冻结候选从新的 TempDir、Session/store 完成正式全链：Nextest run `b0d0eadc-5c49-46d8-9e97-310cf35691ea`，`1/1` 通过；
  watchdog `20260825-235546-1000-2079406` 为 `stop=none / cleanup=none`。
- 首轮审查的两项 finding 已在既有 owner seam 关闭：V2 `close_agent` 先证明当前 AgentControl 成员并拒绝 Root/self；durable child
  participant commit 延后到 Open graph edge 成功之后，确定性 activation 失败复用 Closed edge 与 exact runtime cleanup。
- 命名 participant graph-failure 回归 `2/2`、V2 foreign/Root/self close 回归 `1/1`、fork/resume/crash/V1 close 邻接回归 `7/7`
  和冻结后的 `codex-core` scoped clippy 均通过；既有 30/30、schema 与 client/TUI 证据经首轮审查确认继续有效。
- 新冻结候选从新的 TempDir、Session/store 重跑正式全链：Nextest run `8a93166f-a605-40c5-965d-d69ffa3fa999`，`1/1` 通过；
  watchdog `20260826-004938-1000-2191687` 为 `stop=none / cleanup=none`，退出后无残留任务进程。
- 复审 finding 已在既有 exact-owner/graph seam 关闭：participant activation cleanup 先 teardown captured owner，再取得 exact map lease，
  持 lease 写 Closed edge，最后 exact-retire；teardown、missing/replaced owner 或 graph 写失败均保留 Open edge或受跟踪 owner阻塞 Root close。
- 定向 failure-ordering 回归 `2/2`、graph/Root-close 邻接回归 `6/6`、`codex-core` scoped clippy 与 `fmt-check` 通过；冻结后的
  fresh 正式全链 Nextest `fc6e8c7d-ff74-4af0-9147-a91580541ef8` 为 `1/1`，watchdog
  `20260826-012504-1000-2261794` 为 `stop=none / cleanup=none`，退出后无残留任务进程。

### 当前工作

- `AWAITING_REVIEW`：第二轮 finding 的实现、复验、fresh 正式证据、自审与候选提交已完成，等待指定审查者终审。

### 本任务剩余步骤

- 执行者提交当前 clean 候选并按指定队列再次通知审查者；只有审查通过后，才由审查者同步最终 Plan/WBS/COMPLETED、验收日志与
  收口提交。

### 阻塞项

- 无计划级阻塞。执行时若 canonical lock、cgroup/watchdog、Windows `C:` 实际余量或必要资源计数不可用，按根规则 fail-closed；
  资源拒绝不冒充产品 correctness 失败。

### 当前验收状态

- `AWAITING_REVIEW`：执行者候选无已知未关闭 correctness finding；`M4_Z_CORE_PASS` 仍须由指定审查者终审后决定。

### 交接边界

- Plan 083 完成后冻结本计划；后续路线只链接当前 WBS，不在本计划安排 M4-W0/W1、Plan 082 或其它工作。
- 需要额外授权、计划外变数、不确定决策及最终验收，只按第 3 节指定跨会话队列联系审查者；每次发送后停止会话，不等待、不轮询、
  不重复发送相同消息。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 083 从 clean `main@90e9051...` 建立专用 worktree，结束只提交本地分支 | 保护主工作区与并行现场，遵守用户 Git 停止边界 | Git/交付 | 已采纳 |
| 002 | M4-Z(core) 先验证并组合既有 S/C 产品能力，只有全链暴露真实缺口才修改产品 | 本任务是集成收口，不以代码量代替产品结果 | 范围/实现 | 已采纳 |
| 003 | 职责契合时复用；语义扭曲时允许新建架构内专用能力，但不重复权威体系 | 保持设计干净并给执行者合理路线自由 | 架构 | 已采纳 |
| 004 | 调试阶段保留进度并自主修复重跑；链稳定后才冻结，从全新状态完整跑正式轮 | 兼顾调试效率与最终证据有效性，避免小问题导致无意义整组报废 | 调试/验收 | 已采纳 |
| 005 | 结果未知的 mutation 不自动重放；普通实现/测试失败可窄修重跑 | 区分外部效果唯一性与正常工程调试 | failure | 已采纳 |
| 006 | 本任务只跑 S/C 全链和实际修改面的相称门禁，不跑 full workspace | 用户已明确收口验收边界，避免无关重型扩张 | 测试/资源 | 已采纳 |
| 007 | 一次性重型授权覆盖范围内聚焦命令及修复后重跑；共享 069 target 与临时 270/285/290GB 门限继续适用 | 避免反复请示，同时保持全局构建和宿主资源安全 | build/resources | 已采纳 |
| 008 | 独立终审关闭高/中 correctness finding，不建设额外审计、可信或机器验收体系 | 关注功能正确性与遗漏回归，符合个人开发边界 | review | 已采纳 |
| 009 | 额外授权、计划外变数、不确定决策和最终验收都使用指定 Codex 队列；每次主动表明身份，发送后停止 | 保证跨会话协调可靠且不重复投递 | coordination | 已采纳 |
| 010 | Durable child spawn/resume 先持久化 Open graph edge，再发布 registry/residency；graph 缺失或失败时 fail-closed 并精确清理未发布 runtime | child 已可运行但拓扑不可恢复会破坏 durable success 与 close 证明 | core/graph | 已采纳 |
| 011 | Root close barrier 合并 persisted Open descendants 与 loaded running descendants；公开 Control 映射为 typed `ActiveWriter` | 卸载不等于关闭，Root 终态必须覆盖 cold 可恢复 writer | lifecycle/control | 已采纳 |
| 012 | V2 `close_agent` 复用既有 AgentControl subtree close 与 graph Closed edge，不新增第二套生命周期设施 | 恢复后的 unloaded member 必须有公开、正式、descendant-first 的终态入口 | tools/lifecycle | 已采纳 |
| 013 | 公开 schema 对 enum payload 字段显式使用 serde wire 的 camelCase，并同步 stable/experimental 生成物 | 既有 TypeScript/JSON wire 已是 camelCase，schema 不得给出错误调用合同 | protocol/schema | 已采纳 |
| 014 | V2 `close_agent` 在工具边界以当前 AgentControl registry 证明 target membership，并拒绝 Root/self；V1 显式 ID 合同保持不变 | UUID 解析不是 Team authority，shared manager 中 foreign Session teardown 不可补偿 | tools/ownership | 已采纳 |
| 015 | Durable child Session 可延后 participant activation；owner 先持久化 Open edge，再 commit participant，确定性 activation 失败用既有 Closed edge 与 exact runtime cleanup 收口 | graph 确定失败不得留下不可恢复的 committed phantom participant，也不另建事务或状态源 | core/team/graph | 已采纳 |
| 016 | activation cleanup 复用 explicit close 的 owner 顺序：shutdown captured owner → exact map lease → Closed edge → exact retirement | 任一 teardown/owner/graph 失败都必须保留至少一项 Root close barrier，且持 lease 防止 same-ID replacement 竞态 | core/graph/lifecycle | 已采纳 |
