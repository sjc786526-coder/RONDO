# Plan 086：#39616 Linked-Worktree Trust RONDO 窄适配 ExecPlan

> 本计划是 Plan 086 / `#39616` 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并通过本计划指定的跨会话队列请求确认；范围内普通实现、fixture、
> 构建、测试和审查问题允许自主修复与重跑。
> 本计划只描述 `#39616` 窄适配；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 `main@39fe9a87814c035baff734448bf206300ea0a9b7`，把 OpenAI Codex PR
[`#39616`](https://github.com/openai/codex/pull/39616) 的 exact commit
[`bc3545b805de6e91a11b88114fe1673b678633ca`](https://github.com/openai/codex/commit/bc3545b805de6e91a11b88114fe1673b678633ca)
所修复的安全语义窄适配到 RONDO Multi：只有能够证明自己已由目标主仓注册并且确实归属该主仓的 linked worktree，才允许继承
主仓的 project trust。

本任务吸收产品语义和相称兼容边界，不机械 cherry-pick，不升级冻结的 Codex CLI `v0.147.0` 基线，不另造 M4-W0.5 或新的价值门。
通过后的唯一成功结论为 `M4_W_39616_ADAPTATION_PASS`。

### 完成/验收标准

- [x] 普通主仓、其嵌套目录，以及由该主仓合法注册且归属关系可证明的 linked worktree，继续得到正确的 project trust 结论；合法
      linked worktree 仍能使用主仓信任所允许的现有 project config、hooks、MCP 和其他 trust-controlled 能力。
- [x] linked worktree 继承主仓 trust 前，必须闭合当前 checkout、worktree Git directory、其指向当前 checkout 的回链、common Git
      directory、主 checkout 与 common directory 归属之间的验证；其中任一必要关系不能证明时，不得返回主仓 trust key。
- [x] 伪造、未注册、缺失、不完整、归属不一致、回链或 common directory 不匹配、symlink/异常体积元数据，以及验证期间发生代表性
      替换或变化的现场均 fail-closed；不得通过 fallback、路径形状猜测或旧缓存继承受信任主仓。
- [x] 在只信任目标主仓、没有单独信任非法 checkout 的现场中，该 checkout 的 project config、hooks、MCP server 和其他现有
      trust-controlled 设置保持 disabled/不可用；至少有行为级证据证明 host MCP 不会因为伪造的 linked-worktree 关系而启动，而合法
      registered linked worktree 的对应行为不退化。用户对当前 checkout 的独立显式 trust 仍按既有优先级工作。
- [x] 所有把 repository root 用作 trust 查询、trust 持久化目标或 trust-controlled config 消费依据的现有入口采用一致的已验证结论，
      不留下可借用旧 resolver 或并行路径绕过窄适配的入口；非安全用途的邻接消费者只做保持兼容所必需的调整。
- [x] 合法 linked worktree 的既有受支持形式保持可用，包括相称覆盖的路径 alias、独立 Git directory 和平台相关原生路径；不得为了
      拒绝伪造现场而把 linked worktree 普遍降级为 untrusted。
- [x] 普通非 worktree、明确 untrusted、仓库外路径、找不到 Git 元数据、shared workspace 和现有 S/C/W0 关闭态不发生无关变化；
      Plan 084 的 `BINDING_ONLY_GO`、四期 S/C 既有 PASS 以及三期现场保持不变。
- [x] 正反场景完全使用测试自有的临时 Git repository/worktree、deterministic/fake/offline 设施；不得修改 RONDO 主工作区、其他任务
      worktree 或真实用户 repository，也不建设通用 workspace registry、审计/可信平台或第二套权限体系。
- [x] 调试阶段允许保留已验证进度，从首个未打通处自主窄修、重跑；全流程稳定后冻结代码与配置，并从全新临时 Git 现场完整运行一轮
      正反主场景和必要聚焦门禁，以该干净轮作为正式结果。影响正式链的后续修复须重新形成干净正式轮。
- [x] 按实际写集完成格式化、必要生成物、局部 fix/lint、受影响 crate 的聚焦测试及相称邻接回归；资源拒绝、skip、未运行和基础设施
      失败如实记录，不冒充通过，也不通过删测试、弱化断言或扩大 fallback 凑绿。
- [x] 执行者完成自审并形成 clean 的待验收本地提交；指定审查者完成独立 correctness/security 审查，普通 finding 允许执行者在同一
      worktree 自主整改、复验、提交并再次通知，直至没有未关闭的高/中等级 finding 或审查者明确判定任务失败。
- [x] 独立验收通过后，精炼更新 `doc/WBS.md` 与 `doc/WBS/durable-team-runtime.md`：标记 `#39616` 已完成并把下一工作包指向
      `#39153`；向 `doc/WBS-COMPLETED.md` 追加一次历史摘要，冻结本计划并记录 `M4_W_39616_ADAPTATION_PASS`。不得提前启动或实现
      `#39153`、M4-W1 或其他后续任务。
- [x] 最终检查精确写集、临时产物、`git diff --check`、主工作区和全部 worktree 元数据；只提交
      `worktree-086-linked-worktree-trust-adaptation` 本地分支并保持 086 worktree clean，不合并、不推送、不关闭 worktree，也不归档或
      重命名分支，等待用户另行批准整合。

## 2. 范围

### 允许修改

- `multidev/` 内与 linked-worktree project trust 验证、必要 Git/path 基础能力、现有 trust 查询/持久化/消费接缝及其正确性测试直接
  相关的源码、测试支持、manifest 和确有需要的生成物。执行者可根据 live code 选择职责最契合的已有模块，或新建边界清楚的专用
  能力；本计划不预选最终 crate、类型、函数、数据布局或测试拆分。
- 本计划的“当前状态”和“关键决策记录”，以及一份精炼实施日志
  `agent_log/2026-08-26-plan086-linked-worktree-trust-adaptation.md`；审查者可另建一份精炼独立验收日志。
- `doc/WBS.md`、`doc/WBS/durable-team-runtime.md` 与 `doc/WBS-COMPLETED.md`，但仅在独立验收通过后同步本任务已经形成的当前事实、
  下一指针和历史完成证据，不复制执行流水或规划下游实现。
- 测试自有 `TempDir`、`/tmp` 或 086 worktree 内明确 ignored 的临时目录，用于 deterministic Git repository/worktree fixture、调试
  输出和正式轮临时现场；临时对象必须可精确归属本任务并由 fixture 正常回收。

### 允许只读核对

- 根与 `multidev/` 就近 `AGENTS.md`、README、当前 WBS/四期子 WBS、Plan 084、相关历史日志/验收报告、Git 历史，以及 live
  Git/path、config loader、project trust、hooks、MCP、permission/exec policy、app-server/TUI trust 入口和相邻测试源码。
- 上游 PR `#39616`、exact commit `bc3545b...`、其 parent/diff/测试及普通 Git/path 官方资料；可使用只读网络源码查询、`/tmp`
  临时 checkout，或只读的本地 `codex-source-code/` 快照，但不得修改该快照或把上游当前 main 当作 RONDO 基线。
- 其他 worktree 只查看 branch/HEAD/status、构建锁、资源占用和重型任务是否活跃等元数据；不得读取其未提交文件内容或私有工件正文。

### 不允许修改

- `#39153` permission restore、正式 M4-W1、primary binding、scoped out-of-binding write authorization、replacement binding，或把
  Plan 084 的 test-only 原型扩张为生产实现。
- workspace registry/manager、worktree create/adopt/remove/prune 生命周期、managed worktree、读取隔离、第二套 permission/trust
  体系、自动 merge/cherry-pick/冲突解决/成果判断，以及新的 TUI/workspace 控制面。
- `mydev/`、冻结上游基线、完整上游升级、Plan 082 保留卷或三期资产、其他任务 worktree/分支、真实用户 repository、CI/PR、发布或
  远端资源。
- 与本任务无关的 README、既有 plan/日志、冻结研究/审计材料、共享构建脚本和永久资源阈值；确有邻接兼容需要时只做最小必要调整，
  不夹带 S/C 已完成链返工或无关重构。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、项目外个人文件或私有数据、Plan 082 保留卷/训练资产正文、其他 worktree 的未提交文件内容，
  以及与本任务无关的 ignored 私有模型/训练/测评资产。

### Git-ignored 与主工作区边界

所有 tracked 编辑都在
`/home/sjc/desktop/RONDO/.claude/worktrees/086-linked-worktree-trust-adaptation/` 完成并提交；当前没有必须直接写入主工作区的
git-ignored 业务资产。exact upstream 可经只读网络或 `/tmp` 核对，不要求在主工作区创建源码副本；临时 Git fixture 由测试在
task-owned 临时目录创建和回收，不操作 RONDO 自身 worktree。

重型 Rust 命令会通过仓库既有入口使用全局构建锁、写 086 worktree 自己的 ignored watchdog metrics，并按用户授权复用 069 worktree
的 ignored Cargo target；这些是预期运行状态，不是 tracked 产品修改。除准确的 086 Git 元数据、全局锁、086 watchdog metrics、
069 target 和 task-owned 临时 fixture 外，不得直接写主工作区或其他 worktree。若 live 实现证明必须新增其他 ignored/跨 worktree
写入，执行前通过指定队列说明准确路径、用途、体积和清理责任并取得批示。

## 3. 硬约束

以下约束只冻结产品语义、原则性安全、资源和交付边界；不锁死实现布局、API、Git 探测方式、错误类型或测试数量。

1. **指定基线与现场隔离**：086 从当时最新且 clean 的本地 `main@39fe9a8...` 创建。执行期间不自行 rebase/merge 后续 main，不复用、
   整理、修改或删除任何历史分支、Plan 082/其他 worktree 与保留资产；并行 main 变化留给获批整合者处理。
2. **语义适配而非基线升级**：先冻结 exact upstream commit 相对其 parent 的安全增量、RONDO 当前缺口、现有消费者和兼容边界，再实现
   RONDO 等强语义。不得机械 cherry-pick、整包复制上游架构或顺带升级 `v0.147.0`；上游具体文件拆分、helper、常量和测试组织不是
   本计划的固定设计。
3. **注册与归属可证明才继承**：linked worktree 只有在当前 checkout、对应 worktree Git directory、backlink、common directory 和
   主 checkout ownership 的必要关系共同成立时，才可解析为主仓 trust target。任一关系缺失、不可读、歧义、失配或在验证中变化，
   都必须不继承主仓 trust；不得静默退回旧 resolver、父 cwd、路径形状猜测或缓存结论。
4. **统一 trust 结论**：project config layer、hooks、MCP、exec policy/permission 等现有 trust-controlled 设置，以及 app-server/TUI
   中 trust 查询或持久化目标，必须共享同一安全结论或等强单一权威能力。可以保留非安全 Git grouping/显示消费者的现有职责，但不得
   让任何命名不同的入口重新推导一个更宽松的主仓 trust。
5. **合法现场不普遍退化**：普通 repository 与合法 registered linked worktree 均须继续工作；实现必须对 RONDO 已支持的平台和路径形式
   保持相称兼容，并覆盖上游增量明确保护的 alias、separate Git directory 和原生路径类别。这里的 separate Git directory 兼容指主
   checkout 使用独立 Git directory 时，其合法 registered linked worktree 仍可证明归属；不得把任意非-worktree `.git` 文件指针当成
   可继承主仓 trust。平台特有限制应由条件测试和诚实 unsupported 表达，不得用扩大 trust 的 fallback 掩盖。
6. **相称的路径与变化防护**：对参与 trust 决策的小型 Git metadata 采用有界读取，并拒绝 symlink、异常类型/体积和不一致身份；必须有
   deterministic 证据覆盖代表性的 stat/read/canonicalization 期间替换或 metadata swap。目标是闭合实际 trust 漏洞，不建设通用
   文件证明、严格因果、签名、receipt 或审计平台。
7. **架构自由但不重复体系**：职责契合时复用现有 filesystem/path/Git/config/lifecycle/error/test/observability 设施；强行复用会造成
   耦合或语义扭曲时，可新建一个与现有架构契合的窄能力。不得复制第二套 project trust、workspace、permission、Git 生命周期或
   config loader。
8. **测试只操作 task-owned Git 现场**：fixture 可以调用本机 Git 创建、移动、修复和清理自己创建的临时 repository/worktree；不得
   把产品能力扩张为用户 worktree 管理器，也不得读取或修改 RONDO 主仓/其他 worktree 的内容来构造验收。
9. **允许调试、修复与重跑**：普通代码、fixture、跨平台、编译、生成物和测试问题由执行者自主窄修、多轮重跑，不设机械失败次数限制，
   也不因一个窄修可解决的失败停止汇报。不得删除测试、弱化不变量、扩大 fallback 或改变 PASS 口径凑绿；原则性边界冲突、授权外动作
   或合理整改后仍不能形成有效结果时，才通过队列请示。
10. **共享构建入口和唯一 target**：本任务范围内必要的格式化、生成器、聚焦/邻接 Cargo build/test/fix/lint 及修复后重跑已经一次授权，
    无需逐项再次请示。所有重型命令全局串行，必须经根 `scripts/with-build-lock.sh` 或已接入它的 `multidev/justfile` 配方，显式复用
    `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target` 作为唯一
    `CARGO_TARGET_DIR`；不得 direct Cargo、另建 target、提高既有并发上限、绕过锁/watchdog，或与 Docker、真实本地模型加载/推理、
    其他重型 Cargo 同时运行。
11. **Plan 086 临时容量门**：重型命令只以进程级环境变量设置
    `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
    `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`；这是本任务临时数值，不修改或覆盖仓库永久配置。每个重型批次前后核对项目总占用、
    069 target、增长显著的 target 子目录和 Windows `C:` 实际余量；270GB 告警，285GB 主动停止，290GB 绝对停止，根规则的 Windows
    `C:`、内存、swap、PSI、锁和其他 fail-closed 门禁继续生效，WSL 虚拟余量不得替代宿主计数。
12. **资源不足时只做保守清理**：先缩窄批次或等待资源窗口；确需释放空间时，只能在确认没有 active build、取得共享锁并精确核对路径后，
    保守清理上述 069 target 中可再生的 `debug/incremental`，记录清理前后体积。不得运行广义 `cargo clean`，不得删除 `debug/deps`、
    release 工件、其他 target、来源不明缓存或任何 Plan 082/用户资产。
13. **聚焦优先，扩大门禁按实际风险决定**：先运行实际修改 crate 与 trust 主场景所需的最小门禁和邻接回归。若实际改动触及 shared
    core/config 且聚焦门已通过，执行者已获授权在资源门通过后从冻结代码运行一次相称的最终完整门禁；是否需要及其准确范围由 live
    diff、现有测试职责和资源风险决定，不为形式完整机械扩大到无关 benchmark、S/C 全链或 `--all-features`。
14. **外部与秘密禁区**：允许普通依赖下载、只读上游源码查询和测试中的本地 Git 子进程；不调用真实 API/模型，不运行 Docker，不训练、
    不做性能测评，不操作云资源/Plan 082 保留卷，不发布、上传、付费、推送远端或运行 CI/PR。不得打开、搜索、打印、复制或记录
    `.env.local` 内容。deterministic/fake/offline、真实本机 Git fixture 和未运行项必须明确区分。
15. **候选提交、审查与最终文档顺序**：执行者完成实现、正式轮、自审、计划状态与精炼实施日志后提交 086 分支，再用下述队列通知审查者；
    不得提前把 WBS/COMPLETED 写成已通过。审查 finding 在同一范围内整改、复验、提交后再次通知。审查通过后由审查者写独立报告、
    接受 `M4_W_39616_ADAPTATION_PASS`、同步最终 Plan/WBS/COMPLETED 并提交。任何一方发送验收消息前自身写集都必须 clean；全程
    不合并、不推送，整合和远端发布必须等待用户另行批准。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03e03-8666-7d41-b9d6-7dfb1237481b 替换。
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

执行者给审查者发送任何消息时，必须主动表明身份，并把“我是 Plan 086 / #39616 执行者”放在每条队列消息开头。已在本计划授权内的普通
实现选择、小修和重跑不重复请示；消息发送后停止会话，不等待、不轮询、不重复投递。

## 4. 软性建议

以下建议基于 `main@39fe9a8...` live code 和 exact upstream 增量，只帮助执行者快速定位高价值接缝，不固定最终路线。执行者可以采用
更简洁、优雅且与现有架构更契合的等强方案，并在关键决策记录中说明有实质影响的偏离。

- 当前 `codex-git-utils` 的 trust resolver 已能识别普通 repository 与 `.git` 指向 `worktrees/<name>` 的路径形状，但尚未核对
  worktree admin `gitdir` backlink、`commondir`、registered checkout 和主 checkout ownership。优先评估在该唯一基础能力上闭合验证，
  再让消费者自然获得更严格结论；如果职责边界更适合窄拆模块，也可调整，不必照搬上游 `trust.rs` 文件布局。
- 上游增量为原生路径字节、有界 metadata 读取和 filesystem abstraction 增加了必要支持。可优先复用 RONDO 现有
  `ExecutorFileSystem`、`PathUri`、absolute/native path 与 canonicalization 语义，保持 host/remote executor 和跨平台边界；如 live code
  已有更小的等强能力，避免重复建设 helper。
- 开始实现前列出 resolver 的直接调用方并按职责分类：config loader/active project、app-server thread start 的 trust 持久化、TUI
  onboarding，以及 realtime/workspace grouping 等邻接使用。安全入口必须统一；纯显示或 grouping 入口只需验证 tighter resolver 没有造成
  无关退化，不必为了名称统一做大重构。
- 测试可按少量职责清楚的簇组织，而非笛卡尔积：普通主仓与真实 `git worktree add` 正例；手工可控 metadata 的 forged/missing/
  mismatch/symlink/oversize/swap 反例；alias、separate Git dir、平台原生路径兼容；project layer/hooks/MCP 的行为级消费回归。优先复用
  现有 config loader、hooks list、core integration 和 filesystem override fixture，只有职责不契合时才补专用 test support。
- MCP 行为证据重点是非法 checkout 不加载/不启动 project-local host MCP，合法 registered worktree 仍能启动；无需真实网络服务、真实
  模型或新审计记录。hooks/config/exec policy 同理验证最终消费结果，不需要为每个配置键复制整套攻击矩阵。
- 调试先跑最窄 resolver/config 测试，从第一个真实失败处修复；主链打通后再补跨平台/竞态与邻接行为。冻结后从全新 `TempDir` 完成
  一轮正式场景，日志只记录 exact upstream/gap 结论、关键实现、正式命令/结果、资源快照、未运行项和已知边界。
- 可以用少量子智能体分别做 exact diff/消费者调查、fixture 复核和最终只读审查，但由单一执行者负责共享实现和提交，避免多人同时编辑
  核心文件或建立评审委员会。审查聚焦实际 correctness/security 与局部回归，不扩张为额外平台或重复重跑最重门禁。

### 建议的阶段编排与退出条件

**A. 上游语义与 RONDO 缺口冻结**

- 核对 086 HEAD/分支、全部 worktree clean 元数据、共享 build lock/069 target/宿主资源，以及 exact commit 相对 parent 的生产与测试增量。
- 枚举 live resolver、trust 查询/持久化/消费入口和现有测试，形成最小 gap list；不预选最终实现布局。
- 退出条件：攻击路径、合法兼容边界、直接消费者和首批最窄测试入口明确，没有把 `#39153` 或 W1 混入。

**B. RONDO 窄适配**

- 先以最小测试复现伪造 checkout 借用主仓 trust，再闭合 resolver/path 基础能力和必要消费接缝；普通编译/fixture/平台问题边修边跑。
- 退出条件：合法 registered worktree 仍解析正确，代表性 forged/missing/mismatch/change 现场 fail-closed，且没有并行旧 trust 路径。

**C. 正反场景与干净正式轮**

- 收口 config/hooks/MCP 及实际受影响邻接消费者的行为回归、平台路径兼容和 metadata 变化测试；只跑与实际写集相称的门禁。
- 全链稳定后冻结代码，从全新临时 repository/worktree 运行一轮正反主场景与必要聚焦/邻接门；如 shared core/config 变化确有必要，再按
  资源门判断是否执行一次相称最终完整门禁。
- 退出条件：正式轮能同时证明不误拒合法 worktree、不接受伪造 worktree；所有测试/资源结果和未运行项诚实可追溯，无待决任务内 finding。

**D. 本地提交、独立审查与收口**

- 执行者更新计划当前状态与实施日志，检查 diff/生成物/所有 worktree 元数据后提交 086 分支，按指定队列通知审查者并停止。
- 审查 finding 在同一范围内整改、复验、提交后再次通知；审查通过后由审查者记录独立报告，精炼同步最终 Plan/WBS/COMPLETED 并提交。
- 退出条件：`M4_W_39616_ADAPTATION_PASS` 成立，086 branch/worktree clean；仍不合并、不推送，`#39153` 只获得下一任务启动资格。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 clean，`main@39fe9a87814c035baff734448bf206300ea0a9b7` 比
  `origin/main@014934a62538297a88815c98e4c920cbdec27c65` 领先 29；全部已登记 worktree 无未提交修改，历史分支和 Plan 082 现场均保留。
- 2026-08-26：从该最新 local main 创建
  `.claude/worktrees/086-linked-worktree-trust-adaptation` / `worktree-086-linked-worktree-trust-adaptation`，未复用或整理任何历史现场。
- 2026-08-26：阅读根/`multidev/` 规则、README、当前 WBS、四期子 WBS、plan 模板、Plan 084 与相关日志；核对 069 shared target
  当前存在且约 179G。规划期间未运行 Cargo、Docker、真实 API/模型、训练或测评。
- 2026-08-26：只读核对 upstream PR `#39616` / exact commit `bc3545b...`。上游安全增量验证 worktree `gitdir` backlink、
  `commondir`、registered checkout 与主 checkout ownership，拒绝 missing/oversized/symlinked/mismatched/swapped metadata，并保护
  alias、separate Git dir、非 UTF-8 POSIX/native path 等合法形式；它是产品语义参考，不是机械移植合同。
- 2026-08-26：核对 live RONDO 缺口：当前 resolver 对 linked worktree 只验证 `.git` 指向 `<common>/worktrees/<name>` 的目录形状后
  即返回推测主根，尚未证明 checkout 已注册或归属；config loader、active project、app-server/TUI trust target 和邻接 realtime context
  直接消费该 resolver，现有合法 worktree/config/hooks 测试尚未闭合伪造现场和 host MCP 启动反例。
- 2026-08-26：完成本 ExecPlan，冻结安全语义、兼容、资源、重跑、审查和本地提交边界；当前没有必须直接写主工作区的 ignored 业务资产，
  预期运行状态仅为全局锁、086 ignored watchdog metrics、069 ignored target 与 task-owned 临时 Git fixture。
- 2026-08-26：执行者重新核对 exact upstream `bc3545b...` 相对 parent 的 12 文件增量及 live resolver/消费者；确认 config loader、active
  project、app-server/TUI trust target 与 realtime grouping 均共享 `codex-git-utils` 的 resolver，不需要新增并行 trust 入口或消费者 plumbing。
- 2026-08-26：在 `codex-git-utils` 的专用 trust 模块闭合 `.git` pointer、worktree admin directory、`gitdir` backlink、`commondir`、registered
  checkout、common directory 与 main checkout ownership；小型 Git metadata 采用 64KiB 有界二进制读取并拒绝 symlink/异常类型，路径字节通过
  `PathUri::join_native_bytes` 保留跨主机 POSIX 非 UTF-8 语义。
- 2026-08-26：补齐 resolver、config、hooks 与 host MCP 正反覆盖；正式成功轮为 resolver/path/config 21/21、合法 config/hooks 2/2、host
  MCP 1/1、app-server hooks 1/1，均使用测试自有新 `TempDir`/真实本机 Git fixture。非法 checkout 不继承主仓 config/permission/MCP，合法
  registered worktree 不退化，当前 checkout 的独立显式 trust 仍生效。
- 2026-08-26：`just fmt` 与 scoped `just fix -p codex-utils-path-uri -p codex-git-utils -p codex-core -p codex-app-server` 通过。一次合并行为批次
  被 watchdog 以持续 memory full PSI 主动停止（exit 125，未作为测试结果），随后保留进度并拆窄通过；未清理 069 target，项目峰值未触及
  285GB 主动停止线。
- 2026-08-26：独立审查确认 resolver 闭环正确，但发现 nested linked-worktree cwd 的 `active_project` 未读取 checkout root 显式 trust。执行者
  复用 config loader 的 checkout-root 定位能力，将 active-project 优先级统一为 exact cwd、checkout root、已验证继承 root；nested cwd 的
  trusted/untrusted 正反覆盖与 host MCP/config/permission 行为共 2/2 通过，受影响 `codex-config`/`codex-core` scoped fix 通过。
- 2026-08-26：最终独立复验确认第一轮 P2 已关闭，无剩余高、中等级 correctness/security finding；接受
  `M4_W_39616_ADAPTATION_PASS`，并按合同同步 Plan/WBS/COMPLETED。未重复运行已通过的重型安全矩阵。
- 2026-08-26：用户批准本地整合；验收头 `36633dcec146a457e2be148b77b9849ab55f28f9` 已 fast-forward 进入本地 `main`，
  无冲突、未覆盖并行工作、未推送远端。原 086 分支已按仓库规范归档到 `zz-done/`。

### 当前工作

- 本任务实现、整改、独立复验、权威文档收口与本地整合均已完成；计划冻结。

### 本任务剩余步骤

- 无任务内剩余步骤。`#39153` 已获得下一任务启动资格但尚未启动；M4-W1 继续等待 `#39153` 完成并进入主线。

### 阻塞项

- 无计划级阻塞。sandbox 内首次重型入口因无法核对 systemd heavy scope 以 exit 84 fail-closed，随后使用同一 canonical lock/watchdog 在
  获授权的宿主入口完成；一次 exit 125 资源停止已通过拆窄批次解决，未清理 target 或扩大授权。

### 当前验收状态

- `COMPLETED / ACCEPTED / INTEGRATED`；验收通过、任务目标完成，结论为 `M4_W_39616_ADAPTATION_PASS`。
  Plan 086 已进入本地 `main`，下一工作包为 `#39153`，但尚未启动。

### 交接边界

- 本任务完成后冻结此计划；后续只链接当前 WBS，不在本计划继续实现或安排 `#39153`、M4-W1 或 Workspace 控制面。
- 已授权范围内的普通实现、测试、修复和重跑由执行者自主完成；额外授权、计划外变数、不确定决策与最终验收只按第 3 节指定队列联系
  审查者。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 086 从 clean `main@39fe9a8...` 建立指定专用 worktree，完成后只保留 clean 本地提交 | 遵循仓库工作流并保护 main、Plan 082 与历史现场 | Git/交付 | 已采纳 |
| 002 | 只适配 `#39616@bc3545b...` 的产品安全语义，不 cherry-pick、不升级冻结基线 | RONDO Multi 已有自身架构与增量，机械移植会扩大范围 | 基线/范围 | 已采纳 |
| 003 | 不另造 M4-W0.5 或价值门；唯一成功结论为 `M4_W_39616_ADAPTATION_PASS` | 本任务是正式安全前置，不重新裁决 W0 产品价值 | 终态/WBS | 已采纳 |
| 004 | 主仓 trust 继承以 registered checkout 与 repository ownership 的可证明闭环为硬语义，不能证明即 fail-closed | 直接闭合无关 checkout 伪造 `.git` 借用 trust 的风险 | trust/安全 | 已采纳 |
| 005 | trust 查询、持久化与消费入口采用一致结论，非安全邻接用途只做必要兼容 | 防止 config/hooks/MCP 绕过，同时避免无关重构 | 架构/消费者 | 已采纳 |
| 006 | 职责契合时复用，语义扭曲时允许新建架构内窄能力；不预选上游模块布局 | 保持优雅干净并给执行者实现自由，不复制第二套体系 | 架构 | 已采纳 |
| 007 | 正反测试使用 task-owned 临时 Git 现场，调试允许自主窄修重跑，稳定后才从干净状态形成正式轮 | 避免一次可修失败报废整组，同时保留可信的最终正确性证据 | 测试/调试 | 已采纳 |
| 008 | 重型命令复用 069 target，临时采用 270/285/290GB 项目门限；不足时只允许保守清理其 `debug/incremental` | 遵循用户本任务资源授权，不另建 target 或扩大清理范围 | 构建/资源 | 已采纳 |
| 009 | 执行者先提交候选并经指定队列请求审查；审查通过后才同步 PASS/WBS/COMPLETED | 区分候选实现与独立接受的完成事实 | 审查/文档 | 已采纳 |
| 010 | 所有队列消息主动表明 Plan 086 执行者身份；计划内普通小修/重跑自主完成 | 保持跨会话协作可靠且不过度请示 | 协作 | 已采纳 |
| 011 | 当前无须直接写主工作区 ignored 业务资产；全局锁、086 watchdog metrics、069 target 和临时 Git fixture 是唯一预期运行状态 | 明确 gitignore 例外而不把运行状态冒充产品修改 | ignored/现场 | 已采纳 |
| 012 | 最终只提交 086 worktree；本地 main 合并与远端推送均等待用户另行批准 | 服从本次明确交付边界 | Git/交付 | 已采纳 |
| 013 | 只有 `#39616` 独立验收并获批进入 main 后，`#39153` 才获得启动资格；M4-W1 继续锁定 | 维持 WBS 已冻结的严格串行关系 | WBS/交接 | 已采纳 |
| 014 | 将安全闭环从 `info.rs` 收口到 `codex-git-utils` 专用 trust 模块，所有既有消费者继续共享同一导出函数 | 保持唯一权威 resolver，同时避免把安全验证混入普通 Git 信息收集 | trust/架构 | 已采纳 |
| 015 | 为 Git metadata 增加 `PathUri::join_native_bytes`，不把元数据先转成 lossy UTF-8/native host 路径 | 保留 remote executor、POSIX 非 UTF-8 与 Windows 拒绝边界，避免复制路径体系 | path/兼容 | 已采纳 |
| 016 | 行为测试同时覆盖非法继承、合法注册与当前 checkout 独立显式 trust，直接观察 config/permission、MCP ready 与启动 marker | 证明 fail-closed 不会把显式用户授权或合法 worktree 一并降级 | 消费/测试 | 已采纳 |
| 017 | 合并 core/app-server 行为批次被 memory PSI 停止后保留编译进度并拆成窄批次，不清理 target | 遵循调试保留进度和资源 fail-closed 约束，避免把设施停止冒充产品失败 | 构建/资源 | 已采纳 |
| 018 | active project 复用 config loader 的 checkout-root 定位，按 exact cwd、checkout root、已验证继承 root 查询显式 trust | 与 config layer 的既有优先级一致；checkout root 仅用于当前 checkout 的直接决定，主仓继承仍只由 hardened resolver 授权 | config/trust | 已采纳 |
| 019 | 最终独立复验接受 `M4_W_39616_ADAPTATION_PASS`；`#39153` 只成为下一工作包，不因 086 尚未整合而提前启动 | 第一轮 P2 已关闭，安全闭环与相称行为证据完整；继续遵守本地整合授权边界 | 验收/WBS | 已采纳 |
| 020 | 用户批准后以 fast-forward 把验收头并入本地 `main`，不推送；`#39153` 获得启动资格但不自动启动 | 完成本次明确整合授权，同时保持远端与后继任务的独立授权边界 | Git/交接 | 已采纳 |
