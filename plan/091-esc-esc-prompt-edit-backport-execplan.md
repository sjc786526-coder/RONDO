# Plan 091：#37421 Esc-Esc 历史提示词编辑回归窄适配 ExecPlan

> 本计划是 Plan 091 / `#37421` 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改；完成标准只更新勾选状态，不改写口径。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；范围内普通实现、fixture、编译、测试和审查问题允许自主窄修与重跑。
> 本计划只描述本次独立上游适配，不改变 `doc/WBS.md` 与 `doc/WBS/*.md` 中的跨任务路线、顺序和依赖。

## 1. 目标

### 最终目标

基于 clean `main@02fe2b42fb8b85d58d4039e93137df62d3b6d258` 和冻结 Codex CLI `v0.147.0`，在 RONDO Multi 中选择性吸收
OpenAI Codex issue [#37421](https://github.com/openai/codex/issues/37421) / PR
[#37622](https://github.com/openai/codex/pull/37622)（exact commit
[`266c6920d9b82fe4d68959529565256b12a9be99`](https://github.com/openai/codex/commit/266c6920d9b82fe4d68959529565256b12a9be99)）的必要产品语义：

- Esc-Esc 选中的历史用户提示词即使只存在于当前会话 replay buffer、尚未进入已加载 turn 快照，也能被正确定位和恢复；
- 新分支建立在所选用户消息之前，源线程与其历史保持不变；
- 已持久快照、resume、分页 transcript、完成 turn 和代表性中断 turn 的既有编辑行为保持一致；
- 重建定位视图不制造重复、错序、错误归属或元数据丢失。

这是冻结基线上的独立窄适配，不是 `v0.148.0` 基线升级，也不重新打开多智能体第四期。通过后的唯一产品结论为
`UPSTREAM_37421_BACKPORT_PASS`。

### 完成/验收标准

- [x] **根因回归成立**：在当前 RONDO 代码上稳定证明 transcript/turn 快照尚未含所选实时 turn、而 replay buffer 已含其有效通知时，
      旧实现无法定位正确分叉点；验证排除普通输入状态、键盘路由或 overlay 选择错误等不同根因。
- [x] **快照与实时 turn 一致可见**：prompt-edit 分叉定位同时消费已加载 turn 快照和当前线程尚未归档的有效 buffered turn；快照中的旧
      prompt 与只存在于 buffer 的新 prompt 都能恢复。
- [x] **正确分叉且源线程不变**：分叉发生在所选用户消息之前；新线程不重复包含所选 turn，源 rollout/thread 的内容、顺序、归属和状态
      不因编辑操作改变。
- [x] **重建保真且去重**：同一 turn/item 同时出现在快照与 buffer、通知重复或完成状态随后到达时，不重复插入 turn/item，不覆盖已重建
      的必要 items，不改变有效顺序或跨 turn 归属；完成状态、错误与相关时间信息按实际通知保留。
- [x] **生命周期场景一致**：正常新会话、resume、已加载分页历史、完成 turn 与代表性的 interrupted/terminated turn 获得相称覆盖；已有更老
      的分页 prompt 仍可编辑，分页合并后的 ordinal/选择不退化。
- [x] **诚实失败**：目标确实不存在、没有合法分叉点、目标 turn 仍进行中、所选 prompt 不是合法 turn 起点、当前线程已切换或既有状态禁止
      编辑时，继续返回现有明确失败/不可用结果，不启动伪分支、不修改源线程。
- [x] **相邻行为不退化**：普通输入、单次 Esc、Esc-Esc/方向键/Enter 之外的键盘行为、正常 TUI 启动，以及既有 review-hidden prompt、
      mention/attachment 恢复和 first-prompt 新线程行为保持不变；若没有用户可见 UI 文案/渲染变化，不制造无意义 snapshot churn。
- [x] **RONDO Multi 既有链不回归**：M4-S2/S/C/W1 已完成的 durable session、恢复、分页 transcript 和生命周期产品语义保持现状；本任务
      不重新裁决或改写其完成结论。
- [x] **聚焦门禁通过**：根因回归、相邻 prompt-edit/backtrack/pagination/resume 测试、受影响 `codex-tui` 必要测试、scoped fix/lint、
      `just fmt`/格式检查和 `git diff --check` 通过；按实际写集选择必要门禁，不要求 full workspace 或 `--all-features`。
- [x] **独立验收与本地交付**：独立审查关闭范围内高/中等级 correctness finding；Plan 091 动态状态、精炼日志和完成记录准确，091 分支形成
      clean 本地提交。执行者按本计划指定的跨会话队列交付并在每条消息中主动表明 Plan 091 执行者身份。验收通过可记录
      `COMPLETED / ACCEPTED / UPSTREAM_37421_BACKPORT_PASS / MAIN_INTEGRATION_PENDING / NOT_PUSHED`；只有用户另行批准并实际完成后才记录
      `INTEGRATED / PUSHED`。

## 2. 范围

### 允许修改

- `multidev/codex-rs/tui/` 内与 prompt edit、backtrack、线程事件 replay、历史重建及其直接回归测试相关的代码和 test support。
- 若聚焦测试暴露同一根因或不可避免的直接编译接缝，可修改少量相邻 RONDO Multi 代码、fixture、snapshot 或生成物；不得借此改变
  app-server 对外协议或线程持久格式。执行者可复用职责契合的设施，也可在强行复用会扭曲语义时新建架构内的窄能力。
- 本计划“当前状态”和“关键决策记录”、一份精炼 Plan 091 实施日志；审查者可另建一份精炼独立验收日志，并在验收通过后向
  `doc/WBS-COMPLETED.md` 添加一条准确的完成记录。本任务不改变当前阶段、后续工作包或跨任务依赖，因此不更新顶层/子 WBS。
- `/tmp`、测试自己的 `TempDir` 和 091 worktree 内明确 task-owned 的 ignored 临时目录，用于上游 diff、deterministic/fake/offline
  fixture、调试输出和最终聚焦轮。
- 只读核对官方 issue/PR/exact commit/release、Git 历史、冻结 `codex-source-code/`、当前已提交源码、相关 plan/log/WBS 和测试；普通依赖
  下载与只读网络源码查询已获授权。
- 使用本计划指定的 `codex queue` 跨会话队列向审查者请示额外授权/计划外变数/不确定项，提交最终完成汇报，以及按审查意见反馈整改结果；
  每条消息必须主动表明 Plan 091 执行者身份，发送后停止当前会话，不轮询、不重复发送。
- 通过共享构建锁/看门狗显式复用 Plan 069 的唯一 Cargo target；资源确实不足时，按本计划硬约束保守清理其中可明确归属且可再生的
  debug/incremental 构建产物。

### 不允许修改

- Codex CLI `v0.147.0` 基线标识、整个上游基线、`codex-source-code/` 快照，或 `#38605`、其他 transcript/resume/preview/TUI 修复。
- `mydev/`；方向 1、方向 3 Publication Critic/Route O、多智能体三期或已收口第四期的产品合同、路线、依赖和 S/C/W 结论。
- app-server 对外协议、线程持久化格式、permission 合同，或新的 transcript store、history registry、投影/审计/可信体系。
- 与根因无关的 Esc-Esc 问题、键盘状态机改造、全产品 transcript 重构、无关重构、性能测评或未来设施预建。
- Plan 090 及其他任务的 worktree、分支、源码、计划、日志、未合并成果、ignored 资产或未提交现场；本计划明确授权的 069 ignored Cargo
  target 是唯一写入例外。不得读取其他任务的未提交文件内容/diff。
- README、顶层/子 WBS、既有 plan/log/audit/research 历史；不得用 Plan 091 改写 `M4_W1_PASS / PHASE_4_COMPLETE` 或 Route O 状态。
- 真实 API/模型、Docker、训练、性能测评、CI/PR、发布、上传、付费或其它外部状态变更。
- 自行 merge/rebase/cherry-pick 后续 `main`、推送、归档/重命名分支、删除 worktree，或未经用户批准把 091 合入 `main`。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、项目外个人文件或私有数据、无关模型/训练/测评正文，以及其他 worktree 的未提交内容。

### Git-ignored 与主工作区边界

所有 tracked 编辑都在
`/home/sjc/desktop/RONDO/.claude/worktrees/091-esc-esc-prompt-edit-backport/` 完成并提交。当前没有必须直接修改主工作区的
git-ignored 业务资产：主物理仓库中的 `codex-source-code/` 只读，上游临时 patch 可落 `/tmp`；不得 fetch、checkout 或改写该快照。

重型 Rust 命令按授权写 091 自有 ignored watchdog metrics，并复用
`/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`；这些是预期构建状态，不是 tracked
产品修改，也不授权读取/修改 069 tracked 文件。若实现意外要求新增主工作区或其他跨 worktree ignored 写入，执行前单独报告准确路径、
用途、预计体积和清理责任；普通 task-owned `/tmp`/`TempDir` 不属于该意外扩围。

## 3. 硬约束

以下约束只冻结产品语义、原则边界、资源门和交付停止点，不固定具体文件、helper、API、数据结构、错误文本或测试数量。

1. **指定基线与并行隔离**：091 从 clean `main@02fe2b42...` 创建。执行期间不自行吸收后续 main，不修改、整理、删除或读取 Plan 090
   及其他 worktree 的未提交现场；后续获批整合必须基于届时实际 main 加法式保留并行成果。
2. **语义适配而非版本升级**：以 exact upstream `266c6920...` 的产品行为和测试为对照，结合 RONDO 当前接缝选择原位窄改、提取小能力或
   等强实现；不得机械覆盖文件、整体 cherry-pick `v0.148.0` 或夹带其他上游增量。若 RONDO 已有等强保证，只补真实缺口与回归。
3. **临时一致视图，不改源 authority**：prompt-edit 定位必须在当前线程的已加载快照与有效 replay 通知之上形成顺序一致的临时视图，
   再复用或等强实现既有 fork-before-selected 规则；不得把临时重建结果回写为新的持久/内存权威，不得修改源线程或建设第二套历史存储。
4. **ID 去重、归属和完成元数据保真**：重建只消费定位语义真正需要的 turn/item 通知，按 turn/item identity 去重并保持通知顺序与 turn
   归属；完成通知更新状态、错误和相关时间字段时不得覆盖此前重建的必要 items。未知、不匹配、缺少起点或无关事件按现有边界忽略或
   诚实失败，不猜测、跨 turn 拼接或制造伪完成。
5. **既有分叉与失败合同不变**：合法选择只在对应用户 turn 之前分叉并恢复原 prompt/attachment/mention；in-progress、mid-turn steer、
   hidden review、目标缺失、线程已切换及其它现有拒绝边界继续由既有产品语义裁决。不得用宽松 fallback、重新排序或复制历史来凑成功。
6. **分页/resume 只做相称兼容**：分页历史和 resume 是本回归必须保持的消费场景，不是重写分页加载、transcript UI 或 durable lifecycle 的
   授权。只有聚焦证据证明同一根因触及相邻接缝时才作必要窄修，并补对应回归。
7. **允许调试、修复和重跑**：普通代码、fixture、跨平台、编译、格式、生成物、测试或审查问题由执行者自主从首个未通处窄修并多轮重跑，
   不设机械失败次数限制。不得删除测试、弱化断言、放宽失败合同或扩大范围凑绿；原则边界冲突、授权外动作或安全资源门持续不可满足时
   才停止并报告。
8. **聚焦验证与最终稳定轮**：调试期保留已验证进度，只重跑受影响切片；核心链稳定后冻结代码与配置，从全新 task-owned fixture 运行一轮
   根因与必要相邻场景，并以最终代码上的该轮和相称 crate 门禁作为正式证据。复用 target 不等于复用产品 fixture，不要求 clean build。
9. **共享构建入口与唯一 target**：所有重型 Cargo build/test/fix/lint 全局串行，必须经根 `scripts/with-build-lock.sh` 或已接入它的
   `multidev/justfile`，显式使用上述 069 target；不得 direct Cargo、另建 target、提高并发、绕过 watchdog/lock，或与 Docker、真实
   本地模型、其他重型 Cargo 并发。每批前重查锁、项目占用、Windows `C:` 实际余量和必要计数器，任一不可用即 fail-closed。
10. **Plan 091 临时容量门**：重型命令只以命令级环境变量设置
    `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
    `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`；不得修改仓库脚本、配置或长期默认。根规则的 Windows `C:`、内存、swap、PSI、lock
    与其他门禁继续生效，WSL 虚拟余量不得替代宿主容量。
11. **资源不足时保守清理**：先等待资源窗口并缩窄批次。确需释放空间时，必须先确认没有其他 owner 使用 069 target，再只清理能够明确
    归属、可由 Cargo 再生且位于该 target 的必要 debug 或 incremental 产物，优先最小范围并记录前后体积；不得删除整个 target、release
    工件、来源不明缓存、Cargo registry、模型、Docker 数据、源码、worktree 或其他任务资产。清理后重查全部门禁，仍不安全则停止重型批次。
12. **外部、秘密与证据边界**：只允许 deterministic/fake/offline 测试、普通依赖下载和只读上游查询；不调用真实 API/模型，不运行
    Docker，不训练、不测评、不发布/上传/付费。skip、未运行、资源拒绝和基础设施失败不得表述为通过，也不得读取或记录秘密。
13. **审查、文档与本地停止点**：执行者完成全部实现、最终轮、自审、Plan 动态状态和精炼日志后只提交 091 分支并保持 worktree clean，
    再严格按下节跨会话队列通知本计划制定者独立验收；每条消息必须主动表明 Plan 091 执行者身份。额外授权、计划外变数或不确定项也只用
    该队列请示并等待批示。范围内 finding 在同一分支自主整改、复验、提交后再反馈；验收通过后由审查者同步最终 Plan 和
    `doc/WBS-COMPLETED.md` 并提交。全程不合并、不推送、不归档、不删除 worktree；这些动作等待用户另行批准。

### 审查者跨会话队列（以下内容逐字照录用户要求，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a04085-ede1-7aa3-b2fe-886cec8e13ec 替换。
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

## 4. 软性建议

以下建议帮助执行者快速收敛，不固定实现布局或测试矩阵。执行者可依据 live code、测试和更优设计调整，重要偏离写入关键决策记录即可。

- 从现有 `ForkSessionForPromptEdit`、`ThreadEventStore`、`backtrack_fork_before_turn_id` 和
  `prompt_edit_forks_before_selected_prompt_and_preserves_source` 入手，先建立“所选 turn 只在 replay buffer”的失败证据，再决定原位合成
  或提取职责清楚的小 helper；不必全仓 census。
- 上游只重建定位所需的 user/review items，并用 completion 通知补状态/错误/时间；这是高价值语义参照，但 RONDO 可选择更契合当前
  event-store 生命周期的等强组织。避免用完成 turn 整体覆盖已合成 items，也避免把所有 ThreadItem 搬入第二份历史模型。
- 测试可按少量职责簇组织：snapshot-only 旧 prompt；buffer-only Completed/Interrupted prompt；snapshot/buffer 重叠去重与正确
  fork-before；一条现有 resume/pagination 代表路径；既有拒绝和键盘邻接。不要做无收益笛卡尔矩阵。
- 如果实现不改变可见 UI 文案或渲染，不需要新增 snapshot；若确有可见变化，则按就近 TUI 规范审查并接受对应 snapshot。
- 格式、scoped fix/lint 和测试的最终顺序遵循就近 `AGENTS.md`；只跑受影响的 `codex-tui` 与真实相邻目标，不为形式完整扩大到 full
  workspace。调试失败先修复未通点，稳定后才跑最终聚焦轮。
- 可以使用少量子智能体做上游差异核对、测试覆盖检查或最终只读 code review；共享实现与提交由单一执行者负责，避免并行编辑同一文件。

### 建议的阶段编排与退出条件

**A. 根因与差异确认**

- 对比 exact upstream、冻结 `v0.147.0` 和 RONDO live handler/test，先建立 buffer-only selected turn 的稳定回归并明确预期写集。
- 退出条件：证据证明 #37421 根因真实存在，且没有把 Plan 090、#38605、键盘问题或通用 transcript 重构纳入任务。

**B. 窄适配**

- 在 RONDO 架构内形成 prompt-edit 所需的 snapshot + buffer 一致视图，保持 ID 去重、顺序/归属、completion 元数据、既有 fork/failure 语义
  和源线程不变。
- 退出条件：buffer-only 与 snapshot-only 目标都能正确恢复和分叉，重复/中断/无效目标没有伪成功。

**C. 聚焦验证与稳定轮**

- 自主关闭范围内普通问题，覆盖必要 resume/pagination/键盘和 M4 邻接风险；资源门允许后运行最终聚焦轮、相称 crate 门禁和格式/diff 检查。
- 退出条件：最终代码上的正式证据有效，未运行项如实记录，无意外生成物或重型进程残留。

**D. 独立审查与本地交付**

- 提交待验收实现并保持 worktree clean，再按指定跨会话队列主动声明 Plan 091 执行者身份并发送完整汇报；由计划制定者复核目标、源线程
  不变、重建保真、失败合同、范围和资源证据。真实 finding 在同一 worktree 闭合、复验、提交后再通过同一队列反馈。
- 退出条件：091 分支 clean、无未关闭高/中 correctness finding，完成记录准确；本地验收通过但不合入、不推送。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 `main@02fe2b42fb8b85d58d4039e93137df62d3b6d258` clean，本地领先 `origin/main` 11 个提交；Plan 090
  工作树存在且基于同一提交，未读取或修改其未提交现场。
- 2026-08-26：从该 clean main 创建
  `.claude/worktrees/091-esc-esc-prompt-edit-backport` / `worktree-091-esc-esc-prompt-edit-backport`。
- 2026-08-26：只读核对根/`multidev`/TUI 规范、README、顶层与方向 3 WBS、plan 模板、Plan 069/074/088、相关日志和当前 TUI 接缝；
  当前路线不因 091 改变，规划阶段只新增本计划。
- 2026-08-26：核对官方 issue/PR/release 和 exact commit。上游只改 TUI prompt-edit handler 与既有集成测试；当前 RONDO handler 仍仅 clone
  snapshot turns，#37421 根因在 live code 中存在，且 RONDO 已有 durable/pagination 增量需要窄适配保护。
- 2026-08-26：资源只读快照为项目根 `256,008,237,056` bytes（`du -sh` 约 `239G`）、069 target `196,698,349,568` bytes
  （debug 约 `184G`，其中 incremental `30,305,673,216` bytes）；Windows `C:` 实际余量 `49,249,705,984` bytes，低于现行
  `50,000,000,000` bytes 停机线。canonical lock 无 holder，未发现 Cargo/rustc/nextest 进程；本次规划未运行或清理任何 Cargo 资产。
- 2026-08-26：完成 prompt-edit 的只读 snapshot + replay-buffer 临时 turn 投影、buffer-only 端到端根因回归，以及 completed/interrupted、
  去重、归属和 completion 元数据单测；`just fmt`、`just fmt-check` 与 `git diff --check` 通过，独立只读审查无高/中 correctness finding。
- 2026-08-26：在 canonical lock 可取得、无 Cargo/rustc/nextest 进程且无活跃 RONDO heavy scope 时，精确清理 069 target 中 6 个可再生
  `debug/incremental` 目录，共约 `5,031,600,128` bytes；target 降至 `191,791,996,928` bytes、项目根降至
  `251,158,675,456` bytes，但 WSL 内清理未返还 Windows 宿主空间，未启动任何 Cargo payload。
- 2026-08-26：用户补充授权 Plan 091 的 Windows `C:` 停止线临时降为 `30,000,000,000` bytes，仅允许按重型命令设置进程级
  `RONDO_BUILD_WINDOWS_C_FREE_STOP_BYTES=30000000000`；其余资源门、共享 target 和安全边界不变，不修改任何长期配置。
- 2026-08-26：最终聚焦稳定轮通过 20/20，覆盖 prompt-edit 临时投影、buffer-only completed/interrupted、snapshot/buffer 去重、正确
  fork-before、源线程不变、既有拒绝边界、Esc/Vim、首提示词和分页路径；分页 fake WebSocket 仅在测试命令级设置 loopback
  `NO_PROXY`，未改产品或全局代理配置。
- 2026-08-26：`codex-tui` crate 批次实际为 3436 passed（其中 1 项重试后通过）、3 failed、4 skipped；3 项失败均来自相对 `HEAD` 无
  Plan 091 差异的 durable-session 既有 fixture/snapshot（缺少 `setRootState`），该批不表述为通过，也不跨范围代修。scoped
  `just fix -p codex-tui`、`just fmt`、`just fmt-check` 与 `git diff --check` 均通过。
- 2026-08-26：退出资源核验 Windows `C:` 实际余量 `48,965,611,520` bytes、项目根 `262,085,918,121` bytes、069 target
  `203,508,220,866` bytes；canonical lock 可取得，无 Cargo/rustc/nextest 进程和活跃 RONDO build scope，watchdog 各正式批次均
  `stop=none cleanup=none`。

### 当前工作

- 实现、正式聚焦验证、scoped fix、格式检查、资源退出检查、执行日志、独立验收和完成记录均已完成；Plan 091 已在专用分支本地接受。

### 本任务剩余步骤

- 无任务内剩余步骤。合并本地 `main`、推送、分支归档和 worktree 清理等待用户另行批准，不影响本轮完成结论。

### 阻塞项

- 当前无阻塞。每个 Plan 091 重型批次仍须重读 Windows `C:` 实际余量；低于用户临时授权的 `30,000,000,000` bytes 停止线时
  fail-closed，不得使用 WSL 虚拟余量替代、继续无必要清理、下调其它门限或绕过 watchdog。

### 当前验收状态

- `COMPLETED / ACCEPTED / UPSTREAM_37421_BACKPORT_PASS / MAIN_INTEGRATION_PENDING / NOT_PUSHED`。独立验收未发现高、中等级 correctness
  finding；完整 `codex-tui` crate 额外批次的 3 项 durable-session 基线 fixture/snapshot 欠账经复核与 Plan 091 无差异，不阻断本任务。

### 交接边界

- 091 worktree 已完成实现、验证、提交和独立验收；实现提交为 `d68db9743e6208b5cdcc062c05a1c1094740a355`，独立验收见
  `agent_log/2026-08-26-183420-plan091-independent-acceptance.md`。
- 本地分支已记录 `COMPLETED / ACCEPTED / UPSTREAM_37421_BACKPORT_PASS`；主线合并、推送、分支归档和 worktree 清理仍等待用户批准，
  不在本计划自动执行。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 从 clean `main@02fe2b42...` 创建独立 091 worktree，只在其中保存 tracked 变更 | 保护并行 Plan 090 与主工作区，冻结可复现基线 | Git/并行隔离 | 已采纳 |
| 002 | exact `266c6920...` 只作为产品语义与测试参照，允许 RONDO 等强窄适配 | 当前 RONDO 已有分页/durable 增量，机械覆盖会破坏本地演进 | 上游适配 | 已采纳 |
| 003 | 修复聚焦 prompt-edit 的临时一致视图，不新建 transcript/history authority | 根因是 lookup 视图漏掉 buffered turn，不需要扩大为存储体系 | 架构/范围 | 已采纳 |
| 004 | 091 不更新顶层/子 WBS；独立验收通过后只向 COMPLETED 添加独立维护记录 | 本任务不改变三期 Route O、四期完成态或跨任务路线 | 文档 | 已采纳 |
| 005 | 复用唯一 069 target，并只用命令级 270/285/290GB 临时门；Windows `C:` 等根门继续有效 | 避免第二套重型 target，同时不改长期资源政策或突破宿主容量边界 | 资源 | 已采纳 |
| 006 | 普通问题自主修复重跑，稳定后再跑最终聚焦轮 | 保留调试进度并避免窄问题导致无意义中止，同时保证最终证据对应最终代码 | 执行/验收 | 已采纳 |
| 007 | 本地独立验收可完成 Plan 091，但 `INTEGRATED/PUSHED` 只在用户另行批准并实际执行后记录 | 服从用户本轮明确的 Git 停止点，不提前冒充主线状态 | 交付/Git | 已采纳 |
| 008 | 在 TUI app 内新增只读 `prompt_edit_history` 临时投影模块，handler 与既有 backtrack resolver 只负责原有编排/裁决 | 避免继续扩张 2680 行 event dispatcher，也不把投影写回 `ThreadEventStore` 或建设第二套历史 authority | 架构/测试 | 已采纳 |
| 009 | Plan 091 重型命令只以进程级环境变量把 Windows `C:` 停止线临时设为 30GB，其余门禁和长期配置不变 | 执行用户补充授权，同时把例外严格限制在本计划单批受监督 Cargo 命令 | 资源 | 已采纳 |
| 010 | fake loopback WebSocket 测试仅以命令级 `NO_PROXY=127.0.0.1,localhost` 绕过宿主代理；不改 fixture 产品语义或全局配置 | 环境代理变量原先截获 loopback 连接，listener 始终未收到握手；命令级例外恢复 deterministic/offline 路径 | 测试环境 | 已采纳 |
| 011 | 完整 crate 门禁中 3 项 durable-session 基线 fixture/snapshot 失败如实保留，不在 091 代修 | 失败文件相对 `HEAD` 无 091 差异且根因是既有 `setRootState` 欠账，扩修会越出 #37421 窄适配 | 范围/验收 | 已采纳 |
| 012 | 独立验收接受实现与正式聚焦证据，记录 `UPSTREAM_37421_BACKPORT_PASS`；不为三项既有 crate 欠账新增重型复跑 | 代码、测试、JUnit、资源和范围复核均无高/中 correctness finding，现有证据足以裁决本任务 | 验收/交付 | 已采纳 |
