# Plan 088：#39153 Permission Restore Fail-Closed RONDO 窄适配 ExecPlan

> 本计划是 Plan 088 / `#39153` 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并通过本计划指定的跨会话队列请求确认；范围内普通实现、fixture、
> 构建、测试和审查问题允许自主修复与重跑。
> 本计划只描述 `#39153` fail-closed 窄适配；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 `main@c9cf868622cc137afe0e2de42ae9d0a7fd948b2c`，把 OpenAI Codex PR
[`#39153`](https://github.com/openai/codex/pull/39153) 的 exact commit
[`539a09cb28ca1ded4278c6d54716abbacab42428`](https://github.com/openai/codex/commit/539a09cb28ca1ded4278c6d54716abbacab42428)
所修复的权限上下文连续性窄适配到 RONDO Multi：cold resume 与顶层 `thread/fork` 在没有对应显式请求 override 时，恢复最近持久设置的
approval policy、approvals reviewer 与 active permission-profile identity；profile identity 必须通过当前配置、Plan 086 hardened
project trust 与当前 requirements 重新解析，不直接恢复历史权限快照。

RONDO 不采用上游对缺失、无效或不兼容 profile 静默切换当前默认配置的宽松行为。明确持久化过的 active profile 当前不能合法解析时，
resume/fork 必须在 runtime/fork 变得可执行、可继续或产生工具副作用前 fail-closed；从未记录 active profile 的 legacy thread 继续使用当前配置。
本任务吸收产品语义而非机械 cherry-pick，不升级冻结的 Codex CLI `v0.147.0` 基线，也不预建 M4-W1。通过后的唯一成功结论为
`M4_W_39153_ADAPTATION_PASS`。

### 完成/验收标准

- [x] cold resume 与顶层 `thread/fork` 都能恢复最近有效持久设置的 approval policy、approvals reviewer 与 active profile identity；
      legacy JSONL 与 paginated history、最后一次 settings update、paginated source 的现有加载/边界路径均得到相称覆盖。
- [x] 新产生的 canonical persisted history 在普通真实 turn、settings update 与会重建 bounded model context 的 compaction 路径上保留恢复
      active profile identity 所需的最小事实；旧历史缺少该事实时仍按 legacy 兼容处理，不从 concrete permission snapshot 猜测 identity。
- [x] 每个设置域都保持“合法显式请求 override > 最近持久设置 > 当前配置”的优先级；显式权限 override 必须绕过无效的历史 profile
      identity 并按当前配置正常解析，显式无效 override 继续走既有错误语义，不能由历史值或默认值掩盖。
- [x] 只恢复 active profile identity，不恢复持久历史里的 concrete `PermissionProfile`、sandbox、filesystem/network 或 workspace-roots
      快照；当前同名 profile 定义、project trust 与 requirements 决定实际运行权限，当前约束更严格时不得恢复越界权限。
- [x] 若最近设置明确记录了 active profile，但该 profile 当前已删除、改名、父 profile 缺失、定义损坏/循环、被 requirements 禁止或
      以其他方式不兼容，resume/fork 明确失败或 unavailable；不得切换 configured default，即使该默认看似更保守，也不得扩大或改变
      sandbox/filesystem/network 权限、approval policy 或 reviewer。
- [x] 最近持久设置没有 active profile identity 的 thread 不回填更早的 identity，也不恢复历史 concrete permission snapshot；从未记录
      active profile 的 legacy thread、没有相关持久设置的 thread 和普通当前配置路径保持兼容。
- [x] fail-closed 发生在 runtime/fork 变得可执行或可继续、初始化可能产生副作用的 MCP/tool 链、开始 model turn 或产生工具副作用之前；
      若既有架构先记录明确 failed/unavailable 且不可执行的 fork，可保留该生命周期，但不得报告成功、带默认权限继续或留下可执行半成品。
- [x] 普通新建 thread、已运行 thread 的既有 resume 语义、普通 fork、shared workspace、功能关闭态、S/C 已完成链和 Plan 086 hardened
      trust 不发生无关变化；auto-review/reviewer 恢复链有与实际写集相称的兼容证据。
- [x] 正反场景使用 task-owned 临时 config、store、thread、history 和 deterministic/fake/offline 设施；不得污染主工作区、其他 worktree
      或真实用户数据，也不建设通用 permission/workspace registry、第二套恢复状态、审计/可信平台或严格因果设施。
- [x] 调试阶段保留已验证进度，从首个未打通处自主窄修和重跑；全流程稳定后冻结代码与配置，从全新临时现场完成一轮 resume/fork 正反
      主场景及必要聚焦门禁，以该干净轮作为正式结果。影响正式链的后续修复须重新形成相称的干净正式轮。
- [x] 按实际写集完成格式化、必要生成物、scoped fix/lint、受影响 app-server/config/core 等聚焦测试与相称邻接回归；资源拒绝、skip、
      未运行和基础设施失败如实记录，不通过删测试、弱化断言或扩大 fallback 凑绿。
- [x] 执行者形成 clean 的待验收本地提交并通过指定队列请求审查；范围内普通 finding 可自主整改、复验、提交并再次通知，直至独立审查
      没有未关闭的高/中等级 correctness/security finding，或审查者明确判定任务失败。
- [x] 独立验收通过后，审查者精炼同步本计划、`doc/WBS.md`、`doc/WBS/durable-team-runtime.md` 与
      `doc/WBS-COMPLETED.md`，记录 `M4_W_39153_ADAPTATION_PASS` 已验收、等待用户批准整合，M4-W1 仍锁定；只有 088 获批进入 local
      main 后，整合阶段才把当前指针改为“另行规划 M4-W1（尚未启动）”。不得自动启动、实现或排期 M4-W1，也不得改写 087 的三期状态。
- [x] 最终检查精确写集、临时产物、`git diff --check`、主工作区和全部 worktree 元数据；只提交
      `worktree-088-permission-restore-adaptation` 本地分支并保持 088 worktree clean，不合并、不推送、不关闭 worktree，也不归档或
      重命名分支，等待用户另行批准整合。

## 2. 范围

### 允许修改

- `multidev/` 内与 resume/fork 最近持久权限设置提取、canonical rollout/history 的必要向后兼容 identity 事实、显式 override 优先级、
  当前 permission profile catalog/project trust/requirements 解析、运行时副作用前拒绝及其正确性测试直接相关的源码、测试支持、
  manifest、app-server 行为文档和确有需要的生成物。
  执行者可复用职责契合的现有设施，或新建一个与现有架构契合的窄能力；本计划不预选 crate、文件、类型、函数、内部字段、错误类型或
  测试拆分。
- 本计划的“当前状态”和“关键决策记录”，以及一份精炼实施日志
  `agent_log/2026-08-26-plan088-permission-restore-adaptation.md`；审查者可另建精炼独立审查日志。
- `doc/WBS.md`、`doc/WBS/durable-team-runtime.md` 与 `doc/WBS-COMPLETED.md`，但只在独立验收通过后同步本任务已经形成的当前事实、
  条件指针和历史证据。若 087 已先进入主线，088 后整合者必须加法式保留其最新三期状态；不得修改
  `doc/WBS/multi-agent-trusted-evidence.md`。
- `/tmp`、测试自有 `TempDir` 或 088 worktree 内明确 ignored 的 task-owned 临时目录，用于只读上游 diff、临时 config/store/thread、
  deterministic/fake fixture、调试输出和正式轮现场；对象须能精确归属本任务并正常回收。

### 允许只读核对

- 根与 `multidev/` 就近 `AGENTS.md`、README、当前 WBS/四期子 WBS、Plan 084/086、相关日志/验收报告、Git 历史，以及 live resume/fork、
  rollout/history、config、permission profile、requirements、project trust、reviewer/auto-review、thread store 与相邻测试源码。
- 上游 PR `#39153`、exact commit `539a09c...`、其 parent/diff/测试与官方资料；可使用只读网络查询、`/tmp` 临时下载或只读的本地
  `codex-source-code/` 快照，但不得修改快照、fetch/切换其中基线或把上游当前 main 当作 RONDO 基线。
- 其他 worktree 只查看 branch/HEAD/status、构建锁、资源占用和重型任务是否活跃等元数据；不得读取其未提交文件内容或私有工件正文。

### 不允许修改

- M4-W1、primary write binding、scoped out-of-binding write authorization、replacement binding，或为这些后续能力预建字段、持久格式、
  permit/token/API、控制面和恢复规则。
- 新审批系统、permission/workspace registry、第二套 config loader/recovery state、读取隔离、workspace manager、自动 Git 操作，或 S/C
  已完成链和 Plan 086 trust 结论的返工/放宽。
- `mydev/`、冻结上游基线、087 的 `eval/`/`training/`/Plan/WBS 写集、Plan 082/087 资产、其他任务 worktree/分支、真实用户 repository、
  CI/PR、发布与远端资源。
- 与本任务无关的 README、既有 plan/日志、冻结研究/审计材料、共享构建脚本和永久资源阈值；不夹带 TUI Workspace 控制面、无关重构、
  性能测评或未来平台建设。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、项目外个人文件或私有数据、Plan 082/087 保留资产正文、其他 worktree 的未提交文件内容，以及与本
  任务无关的 ignored 私有模型、训练或测评资产。

### Git-ignored 与主工作区边界

所有 tracked 编辑都在
`/home/sjc/desktop/RONDO/.claude/worktrees/088-permission-restore-adaptation/` 完成并提交；当前没有必须直接写入主工作区的
git-ignored 业务资产。exact upstream 通过只读网络或 `/tmp` 核对；临时 config/store/thread/fixture 由测试在 task-owned 目录创建，
不操作 RONDO 自身 repository/worktree 作为产品 fixture。

重型 Rust 命令会通过仓库既有入口使用全局构建锁、写 088 worktree 自己的 ignored watchdog metrics，并按用户授权复用 069 worktree
的 ignored Cargo target；这些是预期运行状态，不是 tracked 产品修改。除准确的 088 Git 元数据、全局锁、088 watchdog metrics、
069 target 与 task-owned 临时现场外，不得直接写主工作区或其他 worktree。若 live 实现证明必须新增其他 ignored/跨 worktree 写入，
执行前通过指定队列说明准确路径、用途、体积和清理责任并取得批示。

## 3. 硬约束

以下约束只冻结产品语义、原则性安全、资源和交付边界；不锁死实现布局、API、内部数据结构、错误表现或测试数量。

1. **指定基线与并行隔离**：088 从当时最新且 clean 的本地 `main@c9cf868...` 创建。执行期间不自行 rebase/merge 后续 main，不修改、
   整理或删除 069/086/087 及其他 worktree、分支或资产；并行 main 变化留给获批整合者加法式处理。
2. **语义适配而非基线升级**：先核对 exact upstream commit 相对 parent 的产品语义、RONDO 当前缺口和消费者，再实现 RONDO 等强或
   更保守语义。不得机械 cherry-pick、整包复制上游架构或顺带升级 `v0.147.0`；上游文件布局、helper 和测试数量不是固定设计。
3. **分域优先级与三态区分**：合法显式请求 override 对对应设置域始终优先；没有显式值时才使用最近持久设置。恢复链必须区分
   “legacy 从未记录 identity”“最近设置明确没有 named identity/已清除”“最近设置明确记录 `Some(id)`”三种语义；前两者使用当前配置
   且不得向前复活更老 identity，第三种当前无效时 fail-closed。无效显式 override 不得被持久值或默认值掩盖。
4. **恢复 identity，不恢复历史权限快照**：持久 profile 只能作为 identity 输入当前 config/catalog、Plan 086 hardened project trust
   与 requirements 的正常解析链。当前同名 profile 已合法改变时使用当前定义；当前 requirements 使其权限更窄时服从当前约束，绝不
   信任历史 concrete profile、sandbox、roots、filesystem/network 或其他权限副本。
5. **明确持久 profile 失效即 fail-closed**：`Some(id)` 当前缺失、改名、损坏、循环、父项缺失、被 requirements 禁止或不兼容时，
   resume/fork 必须返回明确错误或 unavailable，不得改用 configured/required default、父 cwd、历史 concrete snapshot 或宽松 fallback。
   只有合法显式权限 override 可以按优先级绕过该无效历史 identity。
6. **副作用前拒绝**：profile 恢复与当前解析必须在 runtime/fork 变得可执行或可继续、MCP/tool/model 初始化或其他工具副作用前完成。
   若现有架构先物化明确 failed/unavailable 且不可执行的 fork 记录，可以保留该生命周期；失败不得报告成功、留下可执行半成品、改变
   reviewer/policy、扩大权限或悄悄返回一个使用默认 profile 的可继续结果。
7. **一条恢复与解析语义**：legacy/paginated history、loaded/unloaded source、settings update 与 fork 边界可以有不同读取机制，但必须
   收敛到同一优先级和 fail-closed 结论；不得新增并行 permission/config/recovery 权威或绕过现有 requirements/project trust 的入口。
8. **架构自由但不重复体系**：职责契合时复用现有 history/config/lifecycle/error/test/observability 设施；强行复用会造成耦合或语义
   扭曲时，可新建职责清楚的窄能力。不得建设通用 registry、审计/可信平台、严格因果证明或第二套审批/恢复/权限体系。
9. **允许调试、修复与重跑**：普通代码、fixture、跨平台、编译、生成物和测试问题由执行者自主窄修、多轮重跑，不设机械失败次数限制，
   不因一个窄修可解决的问题停止。不得删除测试、弱化不变量、放宽 fail-closed 或改变 PASS 口径凑绿；原则边界冲突、授权外动作或
   合理整改后仍不能形成有效结果时，才通过队列请示。
10. **共享构建入口和唯一 target**：必要的格式化、生成器、受影响 app-server/config/core 等聚焦与邻接 Cargo build/test/fix/lint 及
    修复后重跑已一次授权，无需逐项再次请示。所有重型命令全局串行，必须经根 `scripts/with-build-lock.sh` 或已接入它的
    `multidev/justfile` 入口，显式复用
    `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target` 作为唯一
    `CARGO_TARGET_DIR`；不得 direct Cargo、另建 target、提高并发上限、绕过 lock/watchdog，或与 Docker、真实本地模型、其他重型
    Cargo 同时运行。每个重型批次前仍须核对共享锁、项目占用和 Windows `C:` 实际余量，任一必要计数器不可用即 fail-closed。
11. **Plan 088 临时容量门**：重型命令只以命令级环境变量设置
    `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
    `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`；不得修改仓库脚本、配置或长期默认。根规则的 Windows `C:`、内存、swap、PSI、
    lock 和其他门禁继续生效，WSL 虚拟余量不得替代宿主容量。
12. **资源不足时只做保守清理**：先缩窄批次或等待资源窗口；确需释放空间时，只能在确认没有 active build、取得共享锁并精确核对路径后，
    清理由 Cargo 可再生的 069 target `debug/incremental/`，记录清理前后体积。目录不存在或仍不足则停止重型批次并报告；不得执行广义
    `cargo clean`，不得删除整个 target、`debug/deps`、release 工件、来源不明缓存、087/训练资产或其他 worktree 内容。
13. **聚焦优先，扩大门禁按实际风险决定**：不强制重复 Plan 086 linked-worktree 安全矩阵。若实际修改 shared core 生产代码且聚焦门
    已通过，执行者可在资源门通过后从冻结代码运行一次相称的最终完整 `just test`；否则以受影响模块门禁为准，不为形式完整扩大到
    无关 S/C 全链、benchmark 或 `--all-features`。`fmt`/`fix` 后是否重跑由就近 `AGENTS.md` 与实际风险共同决定。
14. **外部与秘密禁区**：允许普通依赖下载、只读上游源码查询和 deterministic/fake/offline 测试；不调用真实 API/模型，不运行 Docker，
    不训练、不做性能测评，不操作云资源/Plan 082/087 资产，不发布、上传、付费、推送远端或运行 CI/PR。不得打开、搜索、打印、复制或
    记录 `.env.local` 内容；skip、未运行、真实本机进程与 fake/offline 证据必须明确区分。
15. **提交、审查与文档顺序**：执行者完成实现、正式轮、自审、计划状态与精炼实施日志后提交 088 分支，再用下述队列通知审查者；不得
    提前把 WBS/COMPLETED 写成已通过。审查 finding 在同一范围内整改、复验、提交后再次通知。审查通过后由审查者写独立报告、接受
    `M4_W_39153_ADAPTATION_PASS`、同步最终 Plan/WBS/COMPLETED 并提交；WBS 此时记录已验收但待整合，M4-W1 仍锁定。发送验收消息前
    执行者自身写集必须 clean；全程不合并、不推送，整合和远端发布等待用户另行批准。

### 审查者跨会话队列（以下逐字照录用户追加要求，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03e5f-30ae-7e43-b56e-371a601b0952 替换。
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

为满足上述身份要求，执行者每条队列消息都必须以“我是 Plan 088 / #39153 执行者。”开头。已在本计划授权内的普通实现选择、小修和重跑
不重复请示；消息发送后立即停止会话，不等待、不轮询、不重复投递。

## 4. 软性建议

以下建议基于 `main@c9cf868...` live code 与 exact upstream 增量，只帮助执行者快速定位高价值接缝，不固定最终路线。执行者可以采用
更简洁、优雅且与现有架构更契合的等强方案，并在关键决策记录中说明有实质影响的偏离。

- 当前 `ThreadSettingsApplied` 已持久化 policy/reviewer/concrete permission/active identity，协议中的其他 snapshot 也能表达 identity；但
  普通真实 turn 写出的 `TurnContext` 目前只有 policy/reviewer/concrete permission，没有 active identity，paginated bounded context 因而
  可能缺少初始或较早选择。可优先评估在 canonical history 的现有向后兼容形状上补足最小 identity 事实，并扩展一条统一的“最近持久
  恢复设置”能力；具体 carrier/类型由执行者选择，但不能另建第二份持久状态。
- exact upstream 把 reviewer-only 提取扩成 policy/reviewer/active-profile 三元组，并为 config 增加内部 persisted-ID 来源；RONDO 需要保留
  其显式 override 优先与当前重解析思路，但把 invalid/missing/disallowed profile 的 default fallback 改为明确拒绝。无需复制上游的文件
  拆分、helper 名称或整套测试。
- 高价值实现检查点是：`None` identity 与 invalid `Some(id)` 不混淆；合法显式 permission override 在检查 invalid persisted ID 之前生效；
  同名 profile 当前定义改变时确实按新定义编译；requirements 收紧不会恢复历史越界权限，也不会把不允许的 identity 静默换成默认。
- 测试可按少量职责簇组织，而非笛卡尔积：最近设置提取；core/config 当前重解析与 fail-closed；legacy/paginated cold resume；legacy/
  paginated fork；显式 override；missing/renamed/invalid/cycle/requirements 反例；new/legacy/auto-review 邻接兼容。优先复用已有 app-server
  `TempDir`、history-mode 与 config/requirements fixture，职责不契合时再补专用 test support。
- paginated resume/fork 需要留意 compaction/bounded suffix、source 已加载时的 live config snapshot、未加载且有边界时的 latest model
  context，以及 `excludeTurns` 不返回历史但仍需恢复设置的路径；不必为此建设通用分页状态或新的 thread store。
- 当前 cold resume 的 config cwd 与 fork 的 stored cwd 来源并不完全相同。执行者应核对 profile 通过哪一个既有 canonical persisted cwd/
  project trust 上下文重解析；若确有直接缺口，只闭合本任务所需接缝并复用 Plan 074/086 结论，不扩张成全面 cwd 或 trust 重构。
- 调试先跑最窄提取/config 测试，从首个真实失败处修复；主链打通后再补 resume/fork 行为与邻接兼容。冻结后从全新 task-owned
  config/store/thread 执行一轮正式正反场景，日志只记录 exact gap、关键实现、正式命令/结果、资源事实、未运行项和已知边界。
- 可以用少量子智能体做 exact diff/消费者调查、测试覆盖复核或最终只读自审，但由单一执行者负责共享实现和提交。审查聚焦实际
  correctness/security 与局部修复造成的全局回归，不扩张为额外平台、复杂审计或重复重跑最重门禁。

### 建议的阶段编排与退出条件

**A. 上游语义与现有接缝冻结**

- 核对 088 HEAD/分支、并行 worktree 元数据、共享 build lock/069 target/宿主资源，以及 exact commit 相对 parent 的生产与测试增量。
- 枚举 live persisted settings、resume/fork、config/profile/requirements 与副作用启动接缝，形成最小 gap list；不预选最终实现布局。
- 退出条件：恢复来源/优先级、legacy 区分、invalid persisted profile 的拒绝点和首批最窄测试入口明确，没有把 W1 混入。

**B. Fail-closed 窄适配**

- 先闭合最近设置提取、override 优先和当前 profile 重解析，再让 cold resume/fork 共用等强语义；普通编译、fixture 和测试问题边修边跑。
- 退出条件：合法恢复、显式 override、legacy 当前配置和 invalid persisted profile 的副作用前拒绝均在 live code 成立，没有 default fallback
  或第二套恢复路径。

**C. 正反验证与干净正式轮**

- 收口 legacy/paginated、最后更新、profile 变化、requirements、fork、auto-review 与实际受影响邻接回归，只跑与写集相称的门禁。
- 全链稳定后冻结代码，从全新 task-owned config/store/thread 完成正式主场景；所有资源结果、skip、未运行项和基础设施失败如实记录。
- 退出条件：正式轮同时证明正确恢复、正确拒绝与 legacy/new 兼容，且没有待决任务内 finding。

**D. 本地提交、独立审查与收口**

- 执行者更新计划状态与实施日志，检查 diff/生成物/worktree 元数据后提交 088 分支，按指定队列通知审查者并停止。
- 审查 finding 在同一范围内整改、复验、提交后再次通知；审查通过后由审查者记录独立报告并同步 Plan/WBS/COMPLETED。
- 退出条件：`M4_W_39153_ADAPTATION_PASS` 已验收，088 branch/worktree clean，WBS 记录待用户批准整合且 M4-W1 仍锁定；仍不合并、
  不推送。只有后续获批进入 local main 时才把 M4-W1 指向另行规划。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 clean，`main@c9cf868622cc137afe0e2de42ae9d0a7fd948b2c` 比
  `origin/main@014934a62538297a88815c98e4c920cbdec27c65` 领先 35；Plan 086 已进入主线，087 仍在独立 worktree 并修改三期
  `eval/`、`training/` 与 WBS 写集，088 不读取或覆盖其未提交内容。
- 2026-08-26：从该最新 local main 创建
  `.claude/worktrees/088-permission-restore-adaptation` / `worktree-088-permission-restore-adaptation`，未复用或整理任何历史现场。
- 2026-08-26：阅读根/`multidev/` 规则、README、当前 WBS、四期子 WBS、plan 模板、Plan 086 及相关日志；确认 088 是独立 W-only
  前置，通过并进入 main 后也只解锁 M4-W1 的另行规划资格，不自动启动后续任务。
- 2026-08-26：只读核对 upstream PR `#39153` / exact commit `539a09c...`（parent `6f95f19...`，11 文件，+935/-268）。上游恢复
  policy/reviewer/active-profile identity 并通过当前 config/requirements 重解析，但 invalid/missing/disallowed profile 会回退当前默认；
  RONDO 明确反转这一边界为 fail-closed。冻结本地 `codex-source-code/` 不含该对象且保持未修改。
- 2026-08-26：核对 live RONDO 接缝：`ThreadSettingsApplied` 已持久化三项与 active identity，但普通真实 turn 的 `TurnContext` 目前不写
  active identity，paginated bounded context 可能因此缺失可恢复 identity；app-server resume/fork 只恢复 reviewer，config 已有 catalog/
  Plan 086 trust/requirements 解析。088 需要补足 canonical history 的最小向后兼容 identity 事实、统一 policy/profile 恢复、当前重解析
  来源与 invalid persisted profile 的副作用前拒绝，不需要第二套权限/恢复状态。
- 2026-08-26：确认 069 shared target 存在（规划时约 197G，展示值），本次计划沿用用户指定的唯一 target、命令级 270/285/290GB
  门限与保守 incremental 清理边界；规划期间未运行 Cargo、Docker、真实 API/模型、训练或测评。
- 2026-08-26：完成本 ExecPlan，冻结产品语义、资源、重跑、队列审查和本地提交边界；当前没有必须直接写主工作区的 ignored 业务资产。
- 2026-08-26：以 exact patch `sha256:21f58639f92dbc86790359333fc8cf57c980afc5c29402bdaafe4fdf5cb8037b`
  复核上游增量，并完成 live writer、bounded history、cold resume、loaded/unloaded/boundary fork、current config/requirements 与副作用顺序核对。
- 2026-08-26：在 canonical `TurnContext` 增加向后兼容的 presence-aware active-profile identity；普通 turn 与所有共用 writer 的 compaction
  路径都持久化三态事实。新增一条 recent-settings 投影，统一处理 policy、reviewer、identity、同一 turn 内 settings update 与 legacy
  边界；cold resume 和顶层 fork 均在 config load 前合并，显式 typed/raw override 保持优先。
- 2026-08-26：为 Config 增加内部 persisted-profile 来源，仍复用当前 catalog、profile compile、Plan 086 trust、workspace roots、network 与
  requirements 链；missing/invalid/disallowed/concrete-requirement fallback 对该来源返回明确错误，合法显式权限 override 先清除该来源。
- 2026-08-26：完成 task-owned fake/offline 正反验证：protocol 三态 serde `1/1`，core persisted-profile 聚焦 `6/6`，app-server lib
  `279/279`，legacy/paginated cold resume 与 fork 集成 `5/5`；最终 scoped clippy fix 与统一 fmt 通过。正式批次均经共享锁/看门狗，
  `stop=none`、`cleanup=none`，未运行 Docker、真实 API/模型、训练、测评或完整 workspace 门禁。
- 2026-08-26：完成执行者静态自审与独立只读复核；未发现高/中等级 correctness finding。复核指出 paginated invalid-profile 和 fork
  override 可增加直接负向集成证据，但共享 merge/config 路径、paginated 正向集成和严格 config 单测已覆盖产品语义，未扩成重复矩阵。
- 2026-08-26：审查者逐链核对实现与保存的 watchdog/JUnit，并经三路独立只读复核确认无高/中等级 correctness/security finding；接受
  一项不阻塞的副作用顺序测试余项，形成独立验收报告并同步 Plan/WBS/COMPLETED，结论为 `M4_W_39153_ADAPTATION_PASS`。
- 2026-08-26：用户后续要求关闭该低等级测试余项；在既有 invalid-profile 集成场景中比较失败前后 `thread/list` 的完整 ID 集合，并断言
  消息缓冲区没有 `thread/started`，未增加生产代码、helper 或副作用审计设施。单项聚焦复验 `1/1` 通过，随后 fmt 通过。
- 2026-08-26：审查者复核提交 `ea99e979`、消息缓冲语义及保存的 watchdog/JUnit，确认窄修关闭 015 的低等级测试保障余项且没有引入
  新 finding；`M4_W_39153_ADAPTATION_PASS` 保持成立。

### 当前工作

- 产品实现、独立验收与测试-only 防回归加固复核均已完成；`M4_W_39153_ADAPTATION_PASS` 成立，当前只等待获批整合本地 `main`。

### 本任务剩余步骤

- 等待用户批准是否整合本地 main；获批进入 main 后才把当前指针改为“另行规划 M4-W1（尚未启动）”。

### 阻塞项

- 无。重型命令开始前仍须通过共享锁、宿主资源和 Windows `C:` 实际余量门；资源门失败时按本计划缩窄、等待或保守清理，不冒充产品失败。

### 当前验收状态

- `ACCEPTED / TASK_GOAL_COMPLETE / M4_W_39153_ADAPTATION_PASS / PENDING_LOCAL_MAIN_INTEGRATION`；测试-only follow-up 已复核，M4-W1
  仍锁定且未规划。

### 交接边界

- 本任务完成后冻结此计划；088 只有在独立验收通过、用户批准并进入 local main 后，才使 `#39616 → #39153` 前置闭合，并且只把
  M4-W1 指向另行规划，不在本计划内继续维护后续路线。
- 已授权范围内普通实现、测试、修复和重跑由执行者自主完成；额外授权、计划外变数、不确定决策与最终验收只按第 3 节指定队列联系审查者。
- 088 与 087 后续进入 main 时，后整合者加法式保留另一任务已进入主线的 WBS 状态，不整段覆盖；本分支不合并、不推送。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 成功结论统一为 `M4_W_39153_ADAPTATION_PASS` | 与 WBS 及用户口径一致 | 验收/文档 | 已采纳 |
| 002 | 每个设置域采用“合法显式 override > 最近持久设置 > 当前配置”；invalid persisted profile 只在没有显式权限 override 时触发拒绝 | 保留请求优先级，同时避免历史失效权限被默认值掩盖 | resume/fork/config | 已采纳 |
| 003 | 只恢复 active profile identity，并通过当前 catalog、Plan 086 trust 与 requirements 重新解析 | 历史 concrete 权限快照可能过时或越界 | permission/config | 已采纳 |
| 004 | `Some(id)` 当前无效 fail-closed；legacy 缺失或最近明确清除 identity 时使用当前配置，且不回填更老 profile | 反转上游宽松 fallback，同时保持 legacy 与显式清除语义 | 兼容/安全 | 已采纳 |
| 005 | 不新增 W1 binding/scoped authorization/replacement 状态、持久格式或控制面 | 088 只是独立前置适配 | 范围/WBS | 已采纳 |
| 006 | 实现布局、内部 helper/类型、错误表现和测试拆分由执行者按 live code 自主决定，只禁止第二套权威体系 | 保留优雅、干净且不过度受限的实现空间 | 架构/测试 | 已采纳 |
| 007 | 重型命令复用 069 target，使用命令级 270/285/290GB 门限；资源不足只可条件清理其 `debug/incremental` | 服从用户本任务一次资源授权且保护并行资产 | 构建/资源 | 已采纳 |
| 008 | 聚焦/邻接门禁优先；只有 shared core 实际生产写集与风险证明需要时才执行一次相称最终完整门禁 | 保证 correctness，不重复最重矩阵或为形式扩大测试 | 测试 | 已采纳 |
| 009 | 执行者先提交 clean 候选，再以指定队列、指定 UUID 和主动身份请求审查；普通小修/重跑自主完成 | 保持跨会话审查可靠且不给小问题设置机械停机点 | 协作/审查 | 已采纳 |
| 010 | 最终只提交 088 worktree；本地 main 合并与远端推送均等待用户批准，087/088 文档冲突加法式整合 | 保护并行现场与用户整合决定 | Git/交付 | 已采纳 |
| 011 | `TurnContext` 使用双层可选字段表达 legacy missing、explicit null 与 `Some(id)`，真实 turn 和 compaction 复用同一 writer | bounded canonical history 必须保留最小 identity 事实，同时不能从历史 concrete permission 猜测 | protocol/history | 已采纳 |
| 012 | recent-settings 投影按设置域逆序解析；最近 legacy `TurnContext` 也是 identity 边界，不向前复活更老 ID，同一 turn 内的 settings update 可覆盖 stale compaction context | 同时满足 RONDO 三态硬约束和既有 compaction 时序 | app-server/history | 已采纳 |
| 013 | persisted profile 作为 Config 内部来源进入既有当前解析链，并在 profile allowlist 与 concrete requirement 两个 fallback 点对该来源转为 error | 复用单一 config/trust/requirements 权威，阻止无效历史 identity 静默换默认 | core/config | 已采纳 |
| 014 | 正式门禁采用 protocol serde、core 六项、app-server 全库与 legacy/paginated resume/fork 五项集成，不扩大到完整 workspace | shared core 风险已由直接配置单测、全 app-server lib 和端到端主链覆盖；完整 workspace 与本任务写集不成比例 | 测试 | 已采纳 |
| 015 | 首次独立验收接受一项低风险测试余项：invalid-profile 反例未直接断言 child/started 不存在，但静态生命周期顺序已在创建前拒绝 | 当时产品路径正确且分层证据与任务风险相称；后由 016 关闭测试余项 | 验收/测试 | 已被 016 闭合 |
| 016 | 用户后续收紧 015：只在现有 invalid-profile 场景断言 thread ID 集合不变且无 `thread/started`，不新增审计设施、不重跑宽门禁 | 关闭明确的防回归证据缺口，同时保持 follow-up 最小 | 测试 | 已验证 |
