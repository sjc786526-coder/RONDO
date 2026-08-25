# Plan 074：#37198 Persisted CWD Read Consistency 窄回移

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 普通实现、编译、测试、fixture 或兼容问题由执行者自主窄修并重跑，不属于改变任务合同。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

以冻结 Codex CLI `v0.147.0` 和当前 RONDO Multi 架构为基线，选择性吸收上游
[#37198](https://github.com/openai/codex/pull/37198)（exact merge commit
`547080e4d690cdeea12f427a8d9c5165928821ed`）中与本地 ThreadStore persisted cwd 读取一致性直接相关的能力：

- `thread/read` 与 `thread/list` 投影同一份可信的已持久 cwd 事实；
- 显式 live cwd/workspace override 仍按当前产品优先级决定实际执行上下文；
- persisted read projection 不成为 writer binding、workspace trust 或 live permission authority；
- 缺失、损坏、不兼容或无法与目标 rollout 对应的 metadata 不制造虚假 cwd，也不静默扩大执行权限；
- 该独立增量达到可进入 `main` 的本地交付状态，为 Plan 069 阶段 E 解除代码前置，但不在本任务中执行阶段 E。

这是对一个已确认缺口的窄回移/适配，不是上游基线升级，也不要求逐行复刻上游提交。

### 完成/验收标准

- [ ] **真实差异闭合**：核对官方 PR/exact commit、冻结 `v0.147.0` 源码和当前 RONDO 实现，明确哪些上游变化仍是当前缺口；只实现
  persisted cwd 读取一致性所需的增量，不夹带其它上游行为。
- [ ] **权威读取一致**：当当前 ThreadStore 的权威持久 metadata 含可用的非空 cwd 时，按 thread ID 的读取和基于同一持久索引的 list
  稳定投影该值；按 rollout path 读取时，只有 metadata 确实对应所请求的 resolved rollout 才可覆盖 rollout 内的旧 cwd。
- [ ] **诚实的失败/回退**：persisted cwd 缺失、为空、损坏、不合法、不兼容或 metadata 指向另一 rollout 时，不返回伪造值；可以按现有
  架构选择明确错误/unavailable，或回退到可独立验证且仍适用的 rollout 事实，具体策略以 live 接缝的最小正确实现为准。
- [ ] **read 与 live execution 分离**：产品回归证明 `thread/read`、state-backed `thread/list` 与恢复响应中的 thread projection 使用同一
  persisted cwd，同时显式 resume/live cwd 或 workspace roots override 仍决定实际 session execution cwd/roots；投影值不能覆盖、降级或
  暗中补授权给 live override。
- [ ] **权限语义不扩大**：若所选 cwd 会影响既有 permission profile 投影，使用当前架构的既有推导规则保持二者自洽；该投影不被用作
  新的运行授权事实，恢复或读取不会扩大 approval、sandbox、workspace roots 或其它执行上下文。
- [ ] **聚焦回归**：覆盖 persisted cwd 存在、缺失/空、代表性不合法或不兼容、rollout mismatch、read/list 一致性、显式 live override
  优先级，以及 Plan 069 durable Session 的直接相邻接缝。测试验证产品可观察结果，不只检查字段赋值或 mock 调用次数。
- [ ] **本地门禁与审查**：受影响 ThreadStore/app-server/core 聚焦测试、相称 lint、`just fmt`/格式检查与 `git diff --check` 通过；独立审查
  无未关闭的高/中等级 correctness finding。普通 finding 可自主修复、重跑和复验，不因首次可修复失败整组作废。
- [ ] **干净本地交付**：074 工作树形成干净本地提交并如实记录未运行项；未经用户后续批准，不合入/推送 `main`，不执行 Plan 069
  阶段 E，也不宣布 `M4-S1 PASS`。

## 2. 范围

### 允许修改

- `multidev/codex-rs/thread-store/` 内与 local ThreadStore read/list、metadata 选择、cwd/permission projection 直接相关的实现和聚焦测试。
- 为闭合真实产品消费边界所必需的少量相邻 `multidev/codex-rs/app-server/` 或 `core/` 测试/代码；优先复用现有 API 与 test helper，
  不为本任务新增正式控制面能力。
- 若真实编译接缝确有需要，可做最小公共 wiring、manifest/lock/schema/snapshot 修改；开始前先确认没有并行任务持有该共享写集，并使用
  仓库既有生成工具。预计本窄回移不需要新依赖或协议形状。
- 本计划允许更新的动态章节、一份精炼 `agent_log/`，以及 074 自有的 ignored 测试 fixture/watchdog 证据。
- 只读核对官方 PR/commit、冻结 `codex-source-code/` 快照、已提交主线源码与文档；允许普通只读网络源码查询。
- 工具链和构建身份兼容时，通过显式 `CARGO_TARGET_DIR` 复用 069 工作树中现有约 38 GB Cargo target；若真实不兼容，只重建受影响部分。

### 不允许修改

- Plan 069 工作树的 tracked 源码、计划或日志，以及它的阶段 E 状态；复用其 ignored Cargo target 是本任务唯一明确的跨工作树写入例外。
- Plan 073 的 Publication Critic、候选选择、eval、真实模型/权重、Docker、ignored 资产、计划、日志或任何未提交现场；也不读取其 diff。
- M4-S2、正式 Session query/control/TUI、M4-W0/W1、workspace binding/handoff、Publication Critic 或 M4-Z 组合回归。
- 完整上游 `v0.149.1` 升级、其它上游 PR，或新的 workspace registry、权限/鉴权体系、ThreadStore/read source、writer lease/registry、
  审计/可信/机器验收平台。
- `README.md`、历史 plan/log/audit snapshot。共享 WBS 在 074 实现分支不更新；获批整合时由单一整合者基于最新 `main` 窄同步，避免
  覆盖并行 073 或其它已进入主线的事实。
- Docker、真实 API/模型、训练、性能测评、CI/PR、发布、上传、付费或其它外部状态变更。
- merge/rebase/cherry-pick 其它任务、推送、删除 worktree、清理 069 target、归档/重命名分支，或未经用户批准把 074 合入 `main`。

### 不允许读取/查看

- `.env.local` 内容、密钥/凭据、模型权重正文、私有测评正文，以及 Plan 073 或其它 worktree 的未提交文件内容/diff。

### Git-ignored 与主工作区边界

所有 tracked 编辑都在 `.claude/worktrees/074-persisted-cwd-read-consistency` 完成，不预计需要直接修改主工作区。主物理仓库中的
git-ignored `codex-source-code/` 只作冻结源码的只读对照，不写入；074 自有 fixture 与 watchdog 证据只由既有命令创建在任务工作树。
若复用构建缓存，唯一允许写入的跨工作树 ignored 路径是
`.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`，且只能通过受监控的 Cargo/`just` 流程使用，不手工编辑、清理
或提交。若实现意外要求直接写主工作区或其它 ignored 资产，先停止该动作并单独报告准确路径、原因及影响。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部进度而违反。

1. **精确基线与现场隔离**：074 从 clean `main@f2f1aeb4f3cd96befefabfa294f8ece31f2ea23c` 创建，所有 tracked 实现只在
   `worktree-074-persisted-cwd-read-consistency` 完成。只使用已经进入该基线的事实，不吸收或覆盖 073 未提交现场，不修改保留的
   069 工作树 tracked 内容。
2. **窄回移而非版本升级**：以官方 `547080e4...` 的产品结果为对照，结合当前 RONDO 架构选择直接回移、窄适配或等强实现；不得整体
   升级到 `v0.149.1`，也不得顺带移植同版本其它修复。若当前已存在等强保证，只补必要回归并记录差异结论。
3. **persisted projection 不等于 live binding**：ThreadStore 的 persisted cwd 只拥有 read/list projection 责任。实际运行的 cwd、
   workspace roots、sandbox、approval 和权限继续由现有 resume/start/config override 与 runtime 编译链决定；不得从 read projection
   推导新的写资格、worktree trust 或运行授权。
4. **覆盖必须有对应关系**：只有非空且按现有路径/metadata 合同可用的 persisted cwd 才能覆盖旧 rollout cwd；按 rollout path 读取时还
   必须证明 metadata 指向所请求的 resolved rollout。无法证明时不得跨 rollout 拼接 cwd、permission 或其它 metadata，也不得用进程当前
   cwd、空路径或默认 workspace 冒充已持久事实。
5. **权限投影保持既有语义**：当读取选择的 cwd 变化时，与 cwd 相关的 legacy permission projection 必须按现有 helper/合同重新保持
   自洽；typed/现代 permission metadata 的既有语义不因本任务扩大。异常数据采用现有架构契合的保守结果，不新增权限体系或宽松 fallback。
6. **聚焦测试与有界调试**：先用最小 ThreadStore 回归定位并打通核心差异，再闭合一条真实 app-server/core 消费链和 069 相邻回归。
   普通代码、构建、测试、fixture 或平台适配问题应从首个未通处自主修复重跑；不得删测试、弱化断言或扩大 fallback 凑绿。稳定后以最终
   代码和全新小型 fixture 完整运行一次聚焦正式轮；不要求 `cargo clean` 或全 workspace 测试。
7. **共享重型资源严格串行**：任何重型 Cargo 构建/测试前确认 073 的真实本地模型、Docker 和其它构建进程已经退出；资源仍在使用时
   等待，不终止、不接管其它任务。Rust 构建、测试、lint 与生成器必须走 `multidev/justfile`/canonical heavy lock/watchdog，保持既有
   并发和资源门限；拿不到锁、cgroup、Windows `C:` 实际余量或计数器时 fail-closed。
8. **缓存复用不破坏隔离**：只有工具链、features、profile 和构建身份兼容时才显式指向 069 target；复用不授权读取/修改 069 tracked
   文件或其它 ignored 资产，也不授权 clean/删除该缓存。若命中不足或不兼容，只增量重建受影响部分，不为工作树隔离制造无意义全量重建。
9. **审查与本地停止点**：独立审查只聚焦范围内可复现的高/中 correctness 和局部修复引入的相邻回归，不建设额外审计设施。所有 finding
   关闭后检查 diff、生成物、主工作区/各 worktree 元数据与资源退出状态，形成 clean 074 本地提交后停止；merge、push、WBS 主线同步和
   分支归档均等待用户批准。
10. **诚实的阶段结论**：074 本地通过只能表述为回移实现/预验收完成、等待主线整合。只有 074 获批进入 `main` 后，WBS 才可窄更新为
    “`#37198` 前置完成，Plan 069 阶段 E 待执行”；本任务无权提前宣布 `M4-S1 PASS`。

## 4. 软性建议

以下内容用于帮助执行者高效收敛，不固定具体文件、helper、错误枚举、测试数量或逐行补丁。执行者可依据 live code 和测试采用更简洁、
更契合当前架构的等强策略；重要偏离写入关键决策记录即可。

- 从官方 3-file diff 与当前 `thread-store/src/local/read_thread.rs` 的旧测试入手，先区分“仍缺失的产品行为、RONDO 已有的后续演进、只需
  测试适配的上游形状”，避免全仓 census 或机械 cherry-pick。
- 优先让 persisted cwd 的选择发生在 ThreadStore 已有 metadata/rollout 合并接缝，并复用现有 rollout path resolution 与 permission
  projection helper。若一个窄 helper 能让 read-by-id/read-by-path 规则更清楚，可以增加；不要为了抽象而拆出新 crate 或状态层。
- ThreadStore 单元回归适合覆盖 stale/empty/mismatched metadata 与 permission projection；一条 app-server 集成回归适合同时观察
  `thread/read`、state-backed `thread/list`、resume response projection 和显式 live cwd。若当前测试组织有更小的等强切片，可自主选择。
- 当前 state-DB-only list 已直接投影持久 metadata；其它 scan/repair list 模式可能按既有合同用 rollout 修复索引。不要为了表面统一而
  改写这些模式，除非聚焦证据证明它们也违反本任务的权威读取边界。
- “不合法/不兼容”只冻结不伪造、不扩权的结果边界。应先确认当前 metadata/path 类型的实际有效性合同，再决定保留独立可信 rollout
  值、返回错误或 unavailable；不必为假设中的损坏格式预建迁移器或校验平台。
- 调试期保留已验证进度，只重跑失败点及直接邻近切片；核心链稳定后再冻结候选，使用全新临时 home/state/rollout fixture 跑一轮聚焦
  正式验证。格式/fix 位于仓库规定的最终顺序，未重跑项如实记录。
- 可使用少量子智能体做相互独立的上游差异核对、测试接缝检查或最终 code review；共享源码/计划由单一执行者整合，避免并行编辑同一
  ThreadStore 文件。审查结论以可复现 correctness 证据为准。

### 建议的阶段编排与退出条件

**A. 差异核对**

- 对比官方 `547080e4...`、冻结 `v0.147.0` 和当前 RONDO ThreadStore/app-server 行为，确认真实缺口、RONDO 特有接缝及预期写集。
- 退出条件：产品差异和最小消费链已明确；没有把 073、069 阶段 E 或其它上游增量纳入任务。

**B. 窄回移/适配**

- 实现 persisted cwd 对 read-by-id/read-by-rollout 的安全覆盖，并保持 read/list、permission projection 与 live override 的职责分离。
- 退出条件：最小领域回归通过，缺失/不匹配状态没有虚假 cwd 或权限扩大，显式 live override 行为保持不变。

**C. 聚焦验证与修复**

- 在共享资源可用时运行受影响 ThreadStore、app-server/core 和 069 durable Session 相邻门禁；普通 finding、编译和 fixture 问题自主窄修，
  从未打通处继续。
- 退出条件：最终代码上完成一轮全新 fixture 的聚焦正式验证；格式、相称 lint 和 diff 检查通过，资源进程真实退出。

**D. 独立审查与本地交付**

- 独立复核产品边界、异常状态、live override、权限不扩大及相邻回归；关闭真实高/中 finding，更新精炼日志和计划动态状态并提交。
- 退出条件：074 worktree clean、本地提交完整、无未关闭高/中 correctness finding；未合入/推送、未修改共享 WBS、未执行 069 阶段 E。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已完成阶段 A：官方 `547080e4...`、冻结 `v0.147.0` 与当前 RONDO 的差异核对确认缺口真实；073/069 tracked 现场未读取或修改。
- 已完成阶段 B：匹配同一 resolved rollout 的持久绝对 cwd 可统一覆盖 read-by-ID/read-by-path，并按该 cwd 重新推导 legacy permission；
  跨 rollout metadata 整体不合并，空/相对 cwd 只回退到可验证的同 lineage rollout，否则明确失败。
- 已闭合真实消费链：cold `thread/read` 与 state-only `thread/list` 投影相同 persisted cwd；显式 resume cwd/workspace roots 仍只决定 live execution
  响应，不能被 persisted projection 覆盖或补授权；state-only 相对 cwd 明确失败而不被 app-server 进程 cwd 绝对化。
- 已完成阶段 C 的产品门禁：`codex-thread-store` 190/190、最终 fresh-fixture 聚焦轮 3/3、单独 resume 复验 1/1、ThreadStore clippy、
  `just fmt` 与 `git diff --check` 通过；全部重型命令使用 canonical lock/watchdog 和兼容的 069 ignored target。
- 已完成阶段 D 独立审查：首轮发现同 lineage 的空/相对 cwd 回退后 path-read 未重算 legacy permission；修复并补回归后 test 1/1、clippy
  通过，同一上下文独立审查者复验 `ACCEPT`，无剩余高/中 correctness finding。
- 外部验收发现 rollout cwd 在 matching persisted overlay 前被过早拒绝；现已把 cwd 有效性裁决延后到最终 projection，并覆盖空/相对 rollout
  cwd、matching history/permission 与 mismatch fail-closed。新回归 1/1、ThreadStore 191/191、app-server 2/2、ThreadStore clippy 均通过。
- 外部复验已接受整改提交 `8c60ad4ae411d6f314c0432dc6531e8bab8d5fb8`，确认上一轮中等级 finding 已关闭，范围内无剩余
  高/中等级 correctness finding；最终报告见 `agent_log/2026-08-25-024006-plan074-external-reacceptance.md`。
- 相邻 069 core cold-resume 测试在未修改的 mock sampling 链上两次因 `/v1/responses` 第五次请求返回 502 而超时；无 cwd/ThreadStore
  断言失败。联合 app-server clippy 同样被未修改 core 的 `MutexGuard` 跨 await 既有禁止项阻断，074 自身告警已关闭并由专属 clippy 通过。

### 当前工作

- 实现、聚焦验证和外部验收均已完成；用户已批准同步权威文档并把 074 合入本地 `main`，本计划随该整合冻结。

### 本任务剩余步骤

- 无任务内实现或验收步骤；Plan 069 后续吸收最新 `main` 并执行阶段 E，继续由其自身合同和四期 WBS 管理。

### 阻塞项

- 当前无产品/代码阻塞。069 mock 失败和 core 既有 clippy 阻断仍按外部审查决策保持非阻断，不扩大 074 修改范围。

### 当前验收状态

- `PLAN_074_COMPLETE / EXTERNAL_ACCEPTED / MAIN_INTEGRATED`。

### 交接边界

- 074 已按用户批准随本次权威文档同步进入本地 `main`；本任务未推送、未归档分支，也未执行 Plan 069 阶段 E。
- Plan 069 吸收最新 `main` 并执行阶段 E 继续以 `doc/WBS/durable-team-runtime.md` 和 Plan 069 合同为准，不在本计划安排或执行。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 从 clean `main@f2f1aeb4...` 创建独立 074 worktree，只在其中交付 tracked 变更 | 保护 073 未提交现场与保留的 069 阶段 E 分支 | Git/并行隔离 | 已采纳 |
| 002 | 以官方 `547080e4...` 的产品结果为对照，允许直接回移、窄适配或当前架构下的等强实现 | 当前 RONDO 已在冻结基线上演进，不应机械复制或扩大成版本升级 | 上游适配 | 已采纳 |
| 003 | persisted cwd 是 ThreadStore read/list projection；显式 live override 与 runtime 权限链继续拥有实际执行绑定 | 同时闭合读取一致性并避免把历史事实冒充运行授权 | 产品语义 | 已采纳 |
| 004 | 069 tracked 现场保持只读；唯一例外是在构建身份兼容时经 canonical lock/watchdog 复用其 ignored Cargo target | 避免约 38 GB 无意义 clean rebuild，并为 069 阶段 E 保留热缓存 | 构建资产 | 已采纳 |
| 005 | 074 实现分支不修改共享 WBS；获批整合者在最新 main 上只记录“前置完成、069 阶段 E 待执行” | 避免并行文档覆盖，也防止窄回移提前宣告 M4-S1 PASS | 文档/交接 | 已采纳 |
| 006 | 普通失败和审查 finding 自主窄修重跑；稳定后才运行全新小型 fixture 的聚焦正式轮 | 保留已验证进度，避免一次窄失败报废整组，同时不弱化最终证据 | 调试/验收 | 已采纳 |
| 007 | read-by-rollout-path 只有在 SQLite rollout path 可解析且与请求 canonical path 完全相同时才合并整份 metadata | 硬约束禁止跨 rollout 拼接 cwd、permission 或其它 metadata；只保护 cwd 会留下同类 lineage 污染 | ThreadStore read | 已采纳 |
| 008 | 空/相对 cwd 只可从同 ID 的 SessionMeta 绝对 cwd 回退；state-only 列表无独立 rollout 验证时明确失败 | 保持旧 rollout 的诚实恢复能力，同时阻止 app-server 把空/相对路径按进程 cwd 伪造为持久事实 | 异常读取 | 已采纳 |
| 009 | persisted cwd 只更新 StoredThread 投影及 legacy permission 自洽计算；resume 的 live cwd/workspace roots 继续由现有 config override 链拥有 | 产品回归证明 read projection 与 execution binding 可同时观察且互不覆盖 | 权限/运行时 | 已采纳 |
| 010 | rollout 读取先提取 lineage/内容，cwd 有效性只在 exact matching metadata 合并后的公共投影出口裁决 | 可信 persisted absolute cwd 必须能修复同 lineage 的旧空/相对 cwd，同时 mismatch 仍需在最终出口 fail-closed | read/history 顺序 | 已采纳 |
