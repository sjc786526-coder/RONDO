# Plan 084：M4-W0 Writer Workspace Binding 原型与价值门 ExecPlan

> 本计划是 M4-W0 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并通过本计划指定的跨会话队列请求确认；范围内普通实现、fixture、
> 构建、测试和审查问题允许自主修复与重跑。
> 本计划只描述 W0；W 线后续路线、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 `main@c16ca65f3e5ba455d1037258948f1d0a4acb1eda`，使用调用者预先准备并授权的本地 Git worktree、现有系统 Git 与
deterministic/fake，比较现有“自然语言安排 + Git status/diff/ref”流程和最小 Writer Workspace Binding 原型：验证两个 writer 的
首次可观察动作、reload/resume 重验、失效隔离与 replacement binding，并单独判断 minimal structured handoff 是否具有不能由现有
Git 事实与自然语言交接替代的价值。

本任务是价值原型，不实施正式 M4-W1，不预选正式字段、API、持久格式、模块布局或控制面。任务结束必须且只能形成以下一个终态：

- `BINDING_ONLY_GO`：可重复证据证明 binding 具有明确产品价值，但现有 Git 事实与自然语言足以完成成果交接；
- `BINDING_HANDOFF_GO`：可重复证据同时证明 binding 与 minimal structured handoff 分别具有独立产品价值；
- `NO_GO`：同口径比较证明现有自然语言安排与 Git 工作流已经足够，W 线停止；
- `INCONCLUSIVE_DEFER`：在本任务边界内无法形成有效、充分的比较证据，W 线延期且不得启动 W1。

### 完成/验收标准

- [ ] 使用任务自有临时 Git repository 创建两个相互可区分的预置 worktree 和两个 writer 场景；fixture 可从干净状态重复建立、运行和
      清理，不读取或依赖 RONDO 其他 worktree 的未提交内容。
- [ ] 在同一 fixture、同一 fake writer 动作和同一可观察口径下形成现有流程 baseline 与 binding candidate 对照；baseline 如实使用现有
      自然语言任务说明及 Git status/diff/ref，不人为削弱它，也不把原型内部断言当成用户可见价值。
- [ ] 两个 writer 的 candidate 首次可观察动作可靠落在各自 worktree。binding 校验可以发生在此前，也允许先创建尚未执行任务的 dormant
      runtime；但任何模型请求、工具执行、文件/Git 读写或其它代表 writer 的可观察动作/副作用都不能先于有效执行上下文生效。
- [ ] reload/resume 场景会重新核对原 binding 与当前 Git/执行上下文，而不是仅复用旧内存结论或继承发起者当前 cwd；重验成功后才允许
      fake writer 动作，失败则给出诚实不可用结果。
- [ ] 代表性失效至少覆盖 worktree 缺失、repository 失配，以及权限或所选执行上下文不兼容；每种失效只使对应 writer unavailable/
      unsupported，不静默退回父 cwd，不污染另一 writer，也不扩大既有 sandbox、workspace roots、Git 或宿主文件权限。
- [ ] replacement binding 由显式动作建立。失败或未完成的 replacement 不覆盖旧 binding；旧 worktree 中尚未处理的 Git 事实或成果不会
      因换绑被隐藏、改写或宣称已交接。该证明不得借机实现自动 merge、cherry-pick、冲突解决或正确性判断。
- [ ] binding 价值和 handoff 价值分别裁决。只有在 binding 已成立且存在一个可重复的 handoff 专属失败——该失败在已有 Git
      status/diff/ref 与合理自然语言交接下仍不能闭合，而最小结构化信息能直接闭合——才允许 `BINDING_HANDOFF_GO`；否则 binding GO
      必须收敛为 `BINDING_ONLY_GO`。
- [ ] 终态有直接、可重新运行的测试/原型证据与精炼对照结论支持，并明确区分“原型可行”“产品价值”“生产 trust/binding 保证”；
      `INCONCLUSIVE_DEFER` 只用于证据确实不足，普通可修实现或测试失败不构成该终态。
- [ ] W0 关闭态及现有 shared workspace 默认行为不变。原型若进入产品源码，必须保持 test-only 或明确 experimental/default-off，且不形成
      稳定公共能力；若终态为 `NO_GO` 或 `INCONCLUSIVE_DEFER`，不得遗留没有消费方的生产占位代码、配置或 schema。
- [ ] 测试复用既有正确性设施并聚焦实际实现面；临时 Git fixture、fake 动作与故障场景足以复现结论，不新增通用 fault scheduler、
      workspace registry、审计/可信平台或第二套测试体系。
- [ ] 调试期允许从首个未打通处边修边跑并保留已验证进度；全流程稳定后，冻结代码与配置，从全新临时 repository/worktree 完整运行一轮
      W0 场景及必要聚焦门禁，以该轮作为正式证据。修复若影响该正式链，应重新冻结并从干净 fixture 重跑。
- [ ] 生成物、格式、局部 lint/fix、相关 crate 测试及相邻回归按实际写集完成；未运行项与资源拒绝如实记录，skip、fake、离线结果或
      基础设施失败不冒充通过。
- [ ] 执行者完成范围内自审并形成一个待验收本地提交；本会话审查者独立复核比较公平性、产品价值、边界和相称回归。普通 finding 由
      执行者在同一 worktree 自主修复、复验、提交并再次通知，不建设额外审计或机器验收系统。
- [ ] 最终检查精确写集、临时产物、`git diff --check`、主工作区和全部 worktree 元数据；只提交 084 本地分支并保持 worktree clean，
      不合并、不推送、不关闭 worktree、不归档或重命名分支。

## 2. 范围

### 允许修改

- `multidev/codex-rs/` 内与 W0 最小原型、现有 cwd/workspace/permission/Git 接缝及 deterministic/fake 正确性测试直接相关的源码、
  测试支持与必要 manifest/生成物。执行者可根据 live code 选择职责最契合的现有模块，或新建一个边界清楚的专用原型模块；不按本计划
  中提到的候选文件锁死路线。
- 本计划的“当前状态”和“关键决策记录”。
- `doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、`doc/WBS/multi-agent-trusted-evidence.md`：只同步实际 W0 当前终态和由该终态直接
  决定的 W 线当前事实；不得复制执行历史或提前安排 W1 实现。
- `agent_log/2026-08-26-plan084-m4-w0-binding-value-gate.md`：一份精炼实施日志；审查者可另建一份精炼独立验收日志。
- `doc/WBS-COMPLETED.md`：仅由审查者在独立验收通过并接受四选一终态后追加一次历史摘要。

临时 repository/worktree、fake 运行材料和调试输出放任务拥有的 `TempDir`、`/tmp` 或 084 worktree 内明确 ignored 的临时目录；除非
现有测试规范要求，不提交 raw 流水或另建证据 schema。依赖或配置确有变化时才更新相应 lock/schema，不为原型预建空占位。

### 允许只读核对

- 根与 `multidev/` 就近 `AGENTS.md`、README、当前 WBS、Plan 067/069/074/078/083、相关历史日志/审计快照，以及现行
  AgentControl、spawn/reload/resume、Thread/Session cwd、workspace roots、permission、Git 观察和测试 fixture 源码。
- Git 历史、系统 Git 帮助和普通只读源码查询；本任务不需要以 `codex-source-code/` 或未回移上游增量作为正确性前置。
- Plan 082 和其他 worktree 仅查看 branch/HEAD/status 路径、进程、构建锁、容量与下载是否处于空闲等元数据；不得读取其未提交文件内容、
  工件正文或把其结果作为 W0 前置。

### 不允许修改

- Plan 082 或其他任务的 worktree、分支、源码、文档、训练工件、下载任务与临时现场；`mydev/`、`eval/`、`training/`、
  `codex-source-code/`、`codex-doc/`、README、既有 plan/日志与冻结审计/研究材料。
- 正式 M4-W1、`#39616`、`#39153` 或其他上游增量回移/升级；Workspace 控制面扩展也不属于本任务。
- 不重做 M4-Z(core)，不改变或重新裁决既有 `M4_Z_CORE_PASS`；W0 对相邻 shared code 的必要窄改不得扩张成 S/C 全链重开。
- 产品侧 create/adopt/remove/prune worktree，workspace registry/store/provisioning/snapshot/cleanup、ChangeSet 平台、Team Role、
  第二套 Agent registry/scheduler/spawn/路由、自动 merge/cherry-pick/冲突处理或修改正确性判断。
- 永久资源门限、共享构建脚本/配置、CI/PR、发布配置、远端资源或任何与 W0 无关的公共设施。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、ignored 私有训练/模型/测评正文、Plan 082 工件与未提交内容，以及项目外个人文件或私有数据。

### Git-ignored 与主工作区边界

所有 tracked 编辑都在
`/home/sjc/desktop/RONDO/.claude/worktrees/084-m4-w0-binding-value-gate/` 完成并提交，当前没有必须直接写入主工作区的
git-ignored 业务资产。临时 Git fixture 使用任务自有临时目录并由测试清理，不在主工作区创建长期 worktree。

聚焦 Rust 命令会通过仓库既有入口写共享 `.codex/` 构建锁/看门狗状态，并按授权复用 069 worktree 的 ignored Cargo target；这是唯一
预期的跨 worktree 本地写入，不是 tracked 产品修改。执行者不得手改锁状态、读取 069 源码现场或清理未知产物。若 live 实现证明必须
直接写主工作区 ignored 文件或新增其他跨 worktree 写入，先停止该动作并通过指定队列单独说明准确路径、用途、体积与清理责任。

## 3. 硬约束

以下约束只冻结价值门、公平比较、原则性安全、资源与交付边界；不锁死 crate、类型、字段、原型形状、Git 命令组合或测试数量。

1. **指定基线与并行隔离**：084 只消费已经进入 `c16ca65...` 的事实。主工作区当前 clean 且领先 `origin/main` 一个本地文档提交；084
   不推送它。Plan 082 与其他 worktree 保持原样，不读取、修改、合并、rebase、清理或依赖其未提交/未整合内容；并行期间 main 前进也不
   自行 rebase，后续整合由获批整合者处理。
2. **不预设 GO 且比较同口径**：baseline 与 candidate 必须使用同一任务意图、Git fixture、fake writer 动作和观察点。不得通过构造
   不合理自然语言、隐藏已有 Git 事实、扩大原型观察能力或把安全偏好本身当成数据来制造 GO；同样不得因原型窄小而忽略已重复出现的
   首次动作、恢复、失效或换绑缺口。deterministic/fake 只能证明控制面是否结构性强制、重验和隔离，不能伪装成真实模型遵循自然语言的
   频率统计；最终价值结论必须保持这一证据强度边界。
3. **binding 是执行前提而非提示词别名**：要支持 binding GO，原型必须在 writer 第一次可观察动作前把所选 worktree 与有效 cwd、
   workspace roots、permission/sandbox、repository 预期和执行上下文共同核对并生效；单纯向模型追加路径文本、事后检查落点或只保存
   一条 metadata 不足以证明 binding 价值。
4. **reload/resume 必须重验**：原型不得把历史 cwd、旧进程内缓存或当前发起者 cwd 当成仍有效 binding；缺失、失配或不可访问时诚实
   unavailable/unsupported，并禁止代表 writer 的后续动作。W0 只证明原型语义，不声称已达到 `#39616` 生产 trust 或 W1 持久保证。
5. **失效隔离与权限不扩大**：一个 writer 的 binding 失败不得禁用/重绑另一个 writer，也不得回落到父 cwd、仓库根或其他可写路径。
   binding 不能授予调用者原本没有的读写、Git、sandbox、审批或宿主权限；能力无法共同访问并验证同一 worktree 时返回 unsupported。
6. **replacement 与 handoff 分责**：replacement 必须显式、先核对新 binding，并保留旧 binding/未交接成果的诚实状态；不承诺原
   ThreadId 原地换 workspace。handoff 先以现有 Git status/diff/ref 与自然语言为完整 baseline，只有独立缺口证据才允许最小结构化原型，
   且它不成为 ChangeSet/成果 registry、不声称变更正确、不自动执行 Git 集成操作。
7. **W0 原型不冒充 W1**：所有新行为保持 test-only 或 experimental/default-off，现有 shared workspace、单 Agent、V1/V2、S/C
   durability/control 和关闭态不变。不得增加稳定公共 API、持久 workspace registry、正式控制面或为未来预留无人消费的配置/字段。
8. **优雅复用但不强行复用**：职责契合时复用现有 config、Thread/Session 生命周期、错误、测试和观测设施；强行复用会耦合或扭曲语义时，
   可新建一个架构内专用原型能力。不得复制第二套 Agent/Session/Team/Git 生命周期或为 W0 建通用平台。
9. **任务 Git fixture 严格自有**：测试可以创建、修改和清理自己创建的临时 repository/worktree；清理前必须精确证明对象属于本任务。
   不允许产品代码接管用户 worktree 生命周期，不允许测试操作 RONDO 自身 worktree 或来源不明 Git 资产。
10. **允许调试、修复与重跑**：先逐段调试，保留已验证进度，从首个未打通处继续；范围内 correctness、fixture、snapshot、Git 兼容、
    编译和测试问题自主窄修并重跑，不设机械失败次数限制，也不因一次可修失败形成 `INCONCLUSIVE_DEFER`。不得删除测试、弱化断言、
    扩大 fallback 或改变价值口径凑绿；原则性边界冲突、授权外动作或合理窄修后仍无法有效比较时才通过队列请示。
11. **一次性重型授权与统一入口**：用户已授权本任务范围内必要的聚焦 Cargo build/test/fix/lint、生成器、snapshot 及修复后重跑，无需逐项
    再次请示。重型命令全局串行，显式复用
    `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target` 作为 `CARGO_TARGET_DIR`，并通过
    `multidev/justfile` 已接入的 canonical `scripts/with-build-lock.sh`/watchdog；不得 direct Cargo、绕过 wrapper、提高并发、并行构建、
    `cargo clean`，或与 Docker/真实本地模型加载推理重叠。
12. **Plan 084 临时容量门与 Plan 082 错峰**：所有重型命令只以进程级环境变量设置
    `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
    `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`，不得修改永久脚本或配置。每个重型批次前后记录项目总占用、069 target、
    `debug/deps`、`debug/incremental` 与 Windows `C:` 实际余量；270GB 后停止扩大测试范围，285GB 主动停止，290GB 绝对停止，根规则的
    Windows `C:`、内存、swap、PSI 与 fail-closed 门禁继续生效。若当前体积和增长趋势不能保证下一批保持在 270GB 内，可保守清理 069
    中明确的 task target `debug/incremental`；不得运行 `cargo clean`、默认删除约 140GB deps 或清理来源不明缓存。Plan 082 云端训练可继续，
    但其大型下载与 084 重型 Cargo 必须错峰；开始重型批次前只确认下载已暂停、完成或空闲，不操作 Plan 082 下载任务本身。
13. **聚焦验证与正式轮**：只运行实际修改 crate 和 W0 场景所需的最小门禁及相邻回归，不运行 full workspace、benchmark 或无关 S/C
    全链。遵循 `multidev/AGENTS.md` 的格式、局部 fix/lint、测试入口和生成物规则；资源拒绝先等待或缩窄下一批，不绕过门禁。
14. **外部与安全禁区**：不调用真实模型/API，不运行 Docker，不训练、不做性能测评，不使用 Plan 082 云端授权，不发布、上传、付费、
    修改远端资源或运行 CI/PR；不打开、搜索、打印、复制或记录 `.env.local` 内容。所有证据明确标为 deterministic/fake/offline，并把
    真实本地系统 Git 子进程与任务自有临时 repository/worktree fixture 和 fake 模型/动作证据分开说明。
15. **待验收、审查与提交顺序**：执行者完成原型、测试、候选四选一终态、WBS 待验收状态和精炼日志后自审并提交，再通过下述队列通知
    审查者；通知时不得提前向 `doc/WBS-COMPLETED.md` 写入已验收历史。审查不通过时在同一 worktree 整改、复验、提交后再次通知；审查
    通过后由审查者写独立报告、接受唯一终态、同步最终 WBS/COMPLETED/Plan 并提交。任何一方都不得在自身有未提交变更时发送验收消息。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03d4c-7d3d-76a2-b80b-e837ab7cb986 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。

需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。

执行者完成最终任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<执行者的完成汇报>”
其中
<执行者的完成汇报>就是执行者本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）执行者你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。

执行者给审查者发送消息的时候，必须主动表明身份。

每条队列消息开头明确写“我是 Plan 084 / M4-W0 执行者”。已在本计划授权内的普通修复、重跑和实现选择不重复请示；发送后停止会话，
不等待、不轮询、不重复发送相同消息。

## 4. 软性建议

以下建议基于 `c16ca65...` live code，只帮助执行者快速找到有价值的原型接缝，不固定 API、字段、模块、Git 探测命令或 fixture 形状。
执行者可以采用更简洁、优雅且与现有架构更契合的等强方案，并在关键决策记录中说明有实质影响的偏离。

- 当前 V2 spawn 从发起 turn 构造 child config，并把 turn cwd 与 permission profile 带给 child；followup/reload 同样从当前发起 turn 构造
  resume config。可先用测试证明这与“writer 自己的稳定 workspace binding”是否存在真实差异，再决定在 AgentControl、独立原型 seam
  或测试 harness 中落地；不要仅凭源码形状预判 GO。
- 现有 Config/TurnEnvironment、workspace roots、permission profile、ThreadStore persisted cwd、AgentControl reload 与系统 Git 已提供很多
  基元。职责契合时直接组合；若把 binding 硬塞进现有 Team State、role 或通用 metadata 会扭曲职责，可以新建窄的 W0 专用类型/模块。
- fixture 可为一个临时 repository 加两个 linked worktree，各自使用不同 branch/ref/marker。可由既有 test support 封装少量 Git 命令，
  但无需建设通用 Git runner、workspace manager 或生产 trust validator。
- “首次动作”可用一个记录 effective cwd/repository/ref 并进行最小文件操作的 fake executor 表达；重点是 admission 顺序与错误结果可观察，
  不需要真实模型，也不要用只检查结构体字段的静态单测替代全部行为证据。
- baseline/candidate 场景保持少而有代表性：双 writer 首次动作、进程内卸载后 reload 或等强 cold resume、三类失效、replacement 失败/成功
  与旧成果可见性。可按最清楚的职责拆成数个聚焦测试，不强制单一巨型端到端测试或场景笛卡尔积。
- handoff 评估应在 binding 场景稳定后单独进行。先给合理自然语言说明并让消费者核对 source worktree、status/diff/ref；如果已经可定位和
  检查成果，就记录 `BINDING_ONLY_GO` 的依据，不要为了代码量创造结构化 handoff。如果仍有可重复、与 binding 无关的歧义，再原型化
  能闭合该歧义的最少信息，字段与保存方式仍留给未来 W1 决定。现有 Team State optional handoff 若职责契合，可作为对照候选；不强制
  复用，也不另建第二套 handoff store/protocol。
- 调试阶段使用可重复 seed/输入，从未打通处继续窄修；稳定后删除调试捷径和临时产物，从新的 TempDir 完整跑一轮。最终日志记录场景、
  baseline 与 candidate 的可观察差异、终态推导、实际命令/结果、资源快照和未运行项即可，不新增签名、receipt、因果证明或审计表。
- 可以用少量子智能体分别做代码接缝调查、fixture/test 复核和最终只读审查；共享代码、WBS 和最终集成由单一执行者负责，避免多人并发写
  同一文件或建立评审委员会。

### 建议的阶段编排与退出条件

**A. 基线、现场与比较口径**

- 核对 084 HEAD/分支、Plan 082/其他 worktree 元数据、共享 target/锁/宿主容量与下载空闲状态；不读取并行未提交内容。
- 冻结 baseline/candidate 共用的 fixture、fake writer 动作、观察点和四终态推导规则。
- 退出条件：比较没有人为削弱 baseline，所有目标场景都有现有设施入口或明确的最小原型缺口，首批测试与资源增长预期清楚。

**B. 临时 Git fixture 与 binding 主场景**

- 先打通两个预置 worktree、两个 writer 的首次动作，再打通 reload/resume 重验；普通 Git/fixture/编译问题从首个失败处修复重跑。
- 退出条件：candidate 能在动作前建立并验证上下文，或已有充分 baseline 证据表明不需要它；fixture 完全 task-owned 且可重复清理。

**C. 失效、replacement 与 handoff 独立比较**

- 收口缺失、repository 失配、权限/执行上下文不兼容的单 writer 隔离，以及 replacement 对旧 binding/成果的处理。
- 在不改变 binding 比较口径的前提下，单独比较自然语言 + Git 事实和最小 structured handoff 候选。
- 退出条件：binding 与 handoff 各自有可观察结论；没有因 binding GO 自动扩张 handoff，也没有 silent parent-cwd fallback。

**D. 聚焦门禁与候选终态冻结**

- 按实际写集完成相关 crate 测试、必要生成物、相邻回归、局部 fix/lint/fmt 和 diff 自审；移除无消费的生产占位与临时产物。
- 冻结代码/配置后，从全新临时 repository/worktree 完整运行正式 W0 场景，记录唯一候选终态、命令结果、资源快照与未运行项。
- 退出条件：四种终态之一有直接可重复证据；普通 finding 已修复，无待决的任务内 correctness 缺口。

**E. 本地提交、独立验收与收口**

- 执行者把 Plan/WBS 标记为待验收，写精炼日志，检查所有工作树元数据后提交 084 分支；按指定队列通知审查者并停止。
- 审查 finding 在同一范围内整改、复验、提交后再次通知；审查者接受终态后写报告并同步最终 Plan/WBS/COMPLETED，仍不合并、不推送。
- 退出条件：`BINDING_ONLY_GO`、`BINDING_HANDOFF_GO`、`NO_GO` 或 `INCONCLUSIVE_DEFER` 唯一成立；084 分支 clean，本地提交完整，等待
  用户另行批准整合。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 clean，`main@c16ca65...` 比 `origin/main@014934a...` 领先一个本地提交；该提交正是用户说明的三份
  Durable Team 文档修正，未推送。
- 2026-08-26：从该最新 clean main 创建
  `.claude/worktrees/084-m4-w0-binding-value-gate` / `worktree-084-m4-w0-binding-value-gate`。
- 2026-08-26：阅读根/`multidev/` 规则、README、当前/四期 WBS、plan 模板、Plan 067/069/074/083、相关快照与 live
  spawn/reload/cwd/workspace/permission/Git 测试接缝；未读取 Plan 082 内容、`.env.local` 或 ignored 私有资产。
- 2026-08-26：完成本 ExecPlan，冻结 W0 的公平比较、四选一价值门、轻量原型、资源、重跑、审查和本地交付边界；规划期间未运行
  Cargo、Docker、真实模型/API、训练或测评，未修改主工作区和其他 worktree。
- 2026-08-26：执行者在指定 `ef16e8c...` worktree 完成 live 接缝核对与两个只读调查，确认现有 V2 spawn/resume/reload 继续从
  当前发起 turn 取得 cwd、workspace roots 与 permission，尚无 repository/worktree identity binding。
- 2026-08-26：新增 `cfg(test)` 的 AgentControl 邻接原型与 task-owned 真实 Git repository/two-linked-worktree fixture；同一 fake
  action 已覆盖公平 baseline、首次动作、cold reload 重验、缺失/同路径换库/权限/roots/执行环境失配、失效隔离和事务式 replacement。
- 2026-08-26：正式聚焦轮从全新 `TempDir` fixture 运行 5 项 W0 场景与 3 项 spawn/resume/reload 相邻回归，Nextest
  `9b80362c-1181-4a45-8fe9-2ed2a43cedda` 为 8/8；`just fix -p codex-core` 与 `just fmt` 通过。独立只读复核无阻断 finding，
  其唯一 Git signing 可重复性建议已窄修并在正式轮复验。
- 2026-08-26：证据支持唯一执行者候选 `BINDING_ONLY_GO`：结构性 binding 有明确价值，合理自然语言加 branch/HEAD/status/diff
  已足以定位换绑前后成果，未形成 structured handoff 独有且可重复的缺口；该结论仍待指定审查者接受。
- 2026-08-26：指定审查者在 `17fb9d7...` 首次验收中拒绝候选并指出两个 P2：初次 bind 先于授权读取目标 Git、fake action 实际
  路径未受 binding root 与 permission 约束；同时要求补强 cold reload 失效、各失败隔离与公平 baseline。执行者逐条核对，确认问题存在。
- 2026-08-26：整改保持 test-only 原型边界：初次 bind 先做不读取目标内容的 roots/permission admission；实际 action 只接受普通相对
  组件，按真实目标检查现有 filesystem policy，并逐组件拒绝 symlink 后才写入。测试补足未授权缺失目标的拒绝顺序、父目录/绝对路径/
  symlink 越界无副作用、cold reload 缺失拒绝、repository/permission/roots/执行环境失败后的另一 writer 可用性，以及显式任务文本与 Git facts。
- 2026-08-26：整改正式轮从全新 `TempDir` 运行原 5 项 W0 场景与 3 项相邻回归，Nextest
  `de36d02e-b180-49a1-b271-0b0e9de3b80b` 为 8/8；scoped fix/fmt 通过且未产生额外代码修写。整改后唯一执行者候选仍为
  `BINDING_ONLY_GO`，等待指定审查者复验。
- 2026-08-26：指定审查者复验 `17fb9d7...c187083...` 整改增量、实际实现与保存的 JUnit/watchdog，确认两个 P2 和直接证据缺口均已
  闭合，无剩余 correctness/functionality finding；最终接受唯一终态 `BINDING_ONLY_GO`。本任务验收通过、目标完成，未重跑重型 Cargo。
- 2026-08-26：用户批准整合后，以 no-ff merge `df0e2902117139a100294cf08ab61edb46f633c0` 将已验收的 084 分支合入
  本地 `main`；随后只同步本交付事实并提交，未推送远端。

### 当前工作

- W0 原型、整改、聚焦正式轮、最终独立验收与本地 main 整合全部完成，计划冻结；未实施正式 W1，也未推送远端。

### 本任务剩余步骤

- 本任务内无剩余步骤。本地 main 已完成整合；远端推送不在本次授权内。

### 阻塞项

- 无计划级阻塞。执行期若 Plan 082 大型下载活跃，则等待其暂停、完成或空闲后再取得重型 Cargo 时段，不操作该下载。
- canonical 构建锁、cgroup/watchdog、Windows `C:` 实际余量或必要资源计数不可用时按根规则 fail-closed；资源拒绝不冒充产品
  correctness 失败或 W0 价值终态。

### 当前验收状态

- `COMPLETED / ACCEPTED / MERGED_LOCAL_MAIN`；最终唯一终态为 `BINDING_ONLY_GO`，验收通过、任务目标完成。

### 交接边界

- 本任务完成后冻结此计划；W0 的后续影响只链接当前 WBS，不在本计划实施或安排 M4-W1、上游适配或 Workspace 控制面扩展。
- 额外授权、计划外变数、不确定决策与最终验收只按第 3 节指定队列联系审查者；普通实现和测试问题在授权范围内自主处理。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 084 从 clean `main@c16ca65...` 建立指定专用 worktree，完成后只保留 clean 本地提交 | 包含用户授权的三份文档修正，同时保护 main、Plan 082 与其他现场 | Git/交付 | 已采纳 |
| 002 | baseline 与 candidate 同口径比较，终态严格四选一且不预设 GO | W0 是产品价值门，不是为 W1 寻找论证 | 价值门 | 已采纳 |
| 003 | binding 与 minimal handoff 分别证明；binding GO 不自动带出 handoff | 现有 Git status/diff/ref 和自然语言可能已经足够交接 | 范围/终态 | 已采纳 |
| 004 | W0 允许 test-only 或 experimental/default-off 原型，但不实施稳定 W1 能力 | 保留真实行为证据，同时不提前冻结生产设计 | 原型/架构 | 已采纳 |
| 005 | 临时 Git repository/worktree fixture 全部 task-owned；产品不接管用户 Git 资产生命周期 | 既满足重复性，也避免越界形成 workspace 平台 | 测试/Git | 已采纳 |
| 006 | 职责契合时复用，语义扭曲时允许新建架构内窄能力，但不复制第二套体系 | 保持设计优雅、干净且给执行者实现自由 | 架构 | 已采纳 |
| 007 | 普通实现/fixture/构建问题允许自主窄修和多轮重跑，稳定后才从全新状态形成正式轮 | 避免一次可修失败导致整组报废，又不弱化原则性边界 | 调试/验收 | 已采纳 |
| 008 | 聚焦 Cargo 已一次授权，复用 069 target 和临时 270/285/290GB 门限，并与 Plan 082 大型下载错峰 | 控制当前大型项目/target 的宿主资源风险，避免把规划时点容量当成长期常量 | 构建/资源 | 已采纳 |
| 009 | 跨会话请示与验收使用用户指定队列；执行者每次主动表明身份、发送后停止且不重复投递 | 保证执行者与本会话审查者可靠协调 | 协作 | 已采纳 |
| 010 | 执行者先提交待验收实现，审查者接受终态后再同步 COMPLETED；全程不合并、不推送 | 区分候选结论与独立验收结论，遵守用户 Git 停止边界 | 审查/文档 | 已采纳 |
| 011 | 当前无须直接写主工作区 ignored 业务资产；仅 canonical 锁/看门狗与 069 ignored target 是预期共享写入 | 明确 gitignore 例外，不把共享构建状态误作产品修改 | ignored/现场 | 已采纳 |
| 012 | W0 原型放在 AgentControl 邻接的 `cfg(test)` 专用模块，不增加产品 API、配置、schema、持久状态或 feature gate | 该位置能消费真实 `Config`/permission 接缝并保持价值原型边界，不为 W1 预冻正式设计 | 原型/架构 | 已采纳 |
| 013 | binding admission/revalidation 同时核对精确 worktree top-level、Git common-dir/git-dir、调用者预授权 roots、写权限与执行环境；reload 只从不可变 binding 和当前授权重建 | 覆盖 live caller-relative 缺口且不扩大权限，不把旧内存结论或父 cwd 当作恢复依据 | binding/正确性 | 已采纳 |
| 014 | replacement 先完整建立并验证候选 runtime 后才替换；旧/新成果只以现有路径说明与 branch/HEAD/status/diff 观察交接 | 失败保留旧 binding，且实证未出现 structured handoff 才能闭合的独有缺口 | replacement/handoff | 已采纳 |
| 015 | 唯一终态收敛为 `BINDING_ONLY_GO`，并保持“原型可行/产品价值”与生产 trust 保证分离 | 同口径 deterministic/真实 Git 证据支持 binding，未支持 handoff；指定审查者已最终接受 | 价值门/验收 | 已采纳 |
| 016 | 初次 admission 在任何目标 path/Git 读取前先核对调用者精确 roots 与写策略；actual action 再以普通相对组件、真实目标 policy 和 no-symlink walk 约束 bound root | 闭合首次验收的授权顺序与跨 writer 写入 P2，同时不预建 W1 race-free 文件能力 | 权限/执行 | 已采纳 |
| 017 | baseline 把合理任务文本、branch/HEAD/status/diff 与同一 fake action 组成显式对照；补足 cold invalidation 与各类失败的另一 writer 隔离后维持 `BINDING_ONLY_GO` | 整改增强证据公平性与直接性，最终复验确认未产生 structured handoff 独有缺口 | 价值门/测试 | 已采纳 |
| 018 | 用户批准后以 no-ff merge 将最终验收提交整合到本地 main；本批只追加准确整合事实，不推送 | 遵守 worktree 交付流程，并区分本地整合与远端发布授权 | Git/交付 | 已采纳 |
