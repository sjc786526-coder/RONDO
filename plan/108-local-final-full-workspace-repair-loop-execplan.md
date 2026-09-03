# Plan 108：RONDO Local 最终全 Workspace 测试与修复闭环 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

对应 WBS：`doc/WBS.md` 的“产品线配套补齐与逐条收口”阶段二中，Local 空间门之后的
“全量测试 → 必要修复与复验 → 最终全量通过 → 功能冻结”。
执行基线：`main@a3288f2d4e84f894902845343e86be12974594bd`，Codex CLI 基线仍冻结为 `v0.147.0`。

## 1. 目标

### 最终目标

对当前 RONDO Local 发布候选运行 Linux、default features、standard local Nextest 的完整 workspace 测试；若测试或
正式入口暴露问题，自主完成范围内的诊断、修复和相称定向复验，再在新的干净候选提交上重跑同一完整门禁，直至形成
与最终代码严格对应、可独立验收的全绿发布候选基线。

本任务负责 Local 正确性收口与实质代码/功能冻结，不负责打 tag、发布、更新下载链接或删除构建缓存。

### 完成/验收标准

- [ ] 启动前确认执行 worktree、候选提交、共享构建锁、Windows `C:` 实际余量、项目占用及唯一 Local target 满足根
      `AGENTS.md` 与现行 watchdog 的启动条件；保留 clean 的 111 历史 worktree，不擅自整理或删除任何空间对象。
- [ ] 完整门禁严格使用
      `just --justfile mydev/justfile test-with-codex-v8-conservative --locked`，覆盖完整 Local workspace，并确认
      checksum-verified V8、`CARGO_BUILD_JOBS=1`、LLD 单线程、`CARGO_INCREMENTAL=0`、全局共享锁、资源 watchdog 与
      主物理仓库唯一 `.codex/cargo-target/rondo-local` 均按预期生效。
- [ ] 首次完整轮尽量取得完整故障集合。每项实际 failure、error、timeout、retry/flaky 或设施阻断均得到足以指导处置的
      归因；范围内问题完成相称修复与定向复验，不把产品缺陷冒充环境波动，也不把环境故障冒充代码通过。
- [ ] 最后一次影响 Local 产品、测试、fixture、snapshot、生成物、Cargo/Nextest 配置、依赖、build script 或正式执行口径
      的改动完成后，先形成明确、干净、可定位的候选提交，再重新运行同一完整门禁。若首次完整轮本就在 clean exact
      commit 上满足全部最终条件，且之后没有上述实质修改，该轮可以直接作为最终轮。
- [ ] 最终轮退出成功；所有实际运行测试通过，零 failure、零 error、零 timeout、零 retry/flaky。任何 retry-pass 都不能
      计作最终轮，需要先归因并在新的完整轮中证明零 retry。skip、ignored、filtered/未运行及 setup 项分别统计和报告，
      不计入 passed；所有实际运行的 setup 必须成功。
- [ ] 每项实质修复都有与风险和影响相称的定向回归证据。没有删除有效测试、无理由增加 skip/ignore、弱化断言、扩大通用
      timeout、关闭安全/审批逻辑、改变默认值或使用 stale binary 来换取绿色。
- [ ] 最终 JUnit、wrapper summary、生效的 Nextest 配置、关键资源结果、必要 console 记录及其校验值轻量保留，足以复核
      exact candidate、命令、实际计数、V8/target/锁/watchdog/incremental 状态、返回码和资源终态；证据不依赖 113
      worktree 永久存在，也不新建数据库、通用采集平台、签名链或可信体系。
- [ ] 无遗留 `.snap.new`、意外的 worktree-local `target/`、非预期 lockfile 漂移或无法解释的生成物；tracked diff、主工作区、
      113 worktree、共享 ignored 资产和其它 worktree 状态均经收尾检查。
- [ ] 执行者更新本计划动态状态和一份精炼实施日志，只提交
      `worktree-113-plan108-local-full-workspace` 并保持 worktree clean，然后交给计划制定者独立验收；未经用户后续明确
      批准，不合并 `main`、不推送、不归档/释放 worktree、不删除 target、不打 tag 或发布。
- [ ] 独立验收确认最终证据与最终代码一致、范围内发现闭合且无未关闭 correctness finding。用户另行批准合并和推送后，
      exact main 的 Local 轻量 CI 全绿，WBS 与完成记录如实标记 Local 最终全量基线及实质代码/功能冻结，Plan 108 才整体完成。

## 2. 范围

### 允许修改

- `mydev/` 内由本次完整 workspace 实际暴露问题所需的 Local 产品代码、测试、fixture、snapshot、生成文件、Cargo/Nextest
  配置、依赖与构建脚本。
- 与失败或正式入口直接相关的根共享构建/测试设施、相邻回归和当前维护文档。职责契合时优先复用；若强行复用会造成耦合
  或语义扭曲，可以建立与现有架构契合的专用能力，但不得重复建设第二套构建、测试或结果体系。
- 本 ExecPlan 的“当前状态”和“关键决策记录”、一份精炼 `agent_log/`，以及在相应事实成立后由执行者或审查者按职责更新的
  `doc/WBS.md`、`doc/WBS-COMPLETED.md` 与必要验收/集成日志。
- 普通依赖与 checksum-verified V8 工件下载、测试直接需要的只读源码/文档查询、task-owned `/tmp` 与测试 `TempDir`，
  以及下节明确列出的 git-ignored 路径。

### 不允许修改

- `multidev/` 的产品代码、功能、测试、配置或既有冻结语义。若修复必须改动会影响 Multi 产品行为或既有测试合同的共享设施，
  暂停并交由用户决定，不得借 Local 收口破坏 Multi 冻结。
- 冻结的 Codex CLI `v0.147.0` 上游基线、`codex-source-code/`、既有方向终态、任何实验资格结论或产品默认值。
- 与本轮失败无关的新产品功能、性能优化/测评、训练路线、第二套测试体系、版本号、CHANGELOG、README 下载链接、release
  workflow、tag 或 Release 对象。
- 现有共享 target、缓存、其它 worktree、分支、历史证据、模型/数据资产或来源不明对象的删除、移动、裁剪、清空、stash、
  覆盖或清理。本任务新产生的对象同样不含删除授权。
- Docker、真实 API、真实本地模型、GPU/RunPod、训练、付费、发布、上传或其它真实外部状态变更。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/API Key、项目外个人文件或私有数据。
- 冻结 qualification/unseen 测试正文、模型权重、其它 worktree 的未提交 diff 或 ignored 资产正文。

### Git-ignored 与主物理工作区边界

受跟踪编辑全部在
`/home/sjc/desktop/RONDO/.claude/worktrees/113-plan108-local-full-workspace/` 完成。以下路径不会进入分支 diff，
但执行期间会由正式入口使用或需要直接写入主物理仓库，交付时必须单独报告：

- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-local/`：全项目唯一 Local Cargo target。所有重型构建与测试都必须
  继续复用它，绝不在 worktree、`mydev/codex-rs/target/`、`/tmp` 或其它位置创建第二套 target。
- 113 worktree 内 `.codex/build-watchdog/`：现有 wrapper 自动生成的逐轮 metrics、summary、Nextest 配置和 JUnit；它是
  调试与原始证据现场，不是受跟踪交付物。
- `/home/sjc/desktop/RONDO/test-data/_retained-test-evidence/plan108-local-final-full-workspace/`：直接写主物理工作区的
  轻量保留目录，用于保存最终轮现成证据与完成修复闭环所必需的诊断证据，使后续释放 worktree 不影响复核。

规划阶段没有需要直接改在主工作区的 tracked 文件。除上述路径和普通 task-owned 临时目录外，若执行意外要求写入其它
主工作区 ignored 路径，应先报告准确路径、用途、预计体积与保留责任并取得用户同意。

## 3. 硬约束

以下约束只固定任务边界、正式测试口径、资源安全、诚实判定和 Git 停止点；不固定模块布局、故障调查顺序、修复方案、
调试轮数或逐测试矩阵。

1. **正式入口与唯一 target**：完整 workspace 只能使用计划写明的 Local conservative 入口。所有重型 Cargo 构建、lint 和
   测试都经受跟踪的 `just` 路径进入根共享锁与 watchdog；不得直接 Cargo、绕过/降低看门狗、提高并发、覆盖
   `CARGO_TARGET_DIR` 或建立第二套 target。Local/Multi/Docker/真实模型等重型任务保持全局串行。
2. **资源门 fail-closed**：无法取得共享锁、cgroup、Windows `C:` 实际余量或其它必要资源计数器时不得启动或继续；不得用
   WSL 虚拟余量替代宿主容量。达到 watchdog 门限时保留已验证进度并如实停止，不自行删资源；如需释放，只能报告精确对象、
   占用、影响和建议，等待用户对明确目标另行授权。
3. **允许调试闭环**：首次完整轮是 commissioning/诊断轮，不因少量失败报废编译进度。执行者可以自主进行合理次数的聚焦
   复现、修复、定向复验和完整重跑；不得设置“失败一次即停止”的机械规则，也不得在原因未变化时盲目重复昂贵全量。
4. **最终轮绑定最终候选**：最终轮开始前工作树必须 clean，HEAD 必须是包含全部实质修改的候选提交。其后只允许更新 Plan、
   实施/验收日志及权威状态记录；若审查整改再次改动产品、测试、fixture、snapshot、Cargo/Nextest、依赖、build script 或
   正式运行口径，必须先定向验证，再在新的 clean candidate 上重跑同一完整门禁。
5. **修复正确性优先**：真实产品缺陷须按产品问题解决并配相称回归；环境或 non-hermetic 问题须修其真实边界，不得通过弱化
   产品、测试、安全或审批语义掩盖。允许选择比窄补丁更干净的局部重构或专用设施，只要职责明确、架构契合且不重复建设。
6. **最终严格零 retry**：最终通过只能由正式命令、JUnit、wrapper summary 与必要 console 信息共同支持；failure/error/timeout/
   retry/flaky 均须为零。skip、ignored、filtered、setup、未运行和 blocked 单列，任何基础设施阻断都不能计作通过。
7. **证据够用即可**：复用 wrapper 已产出的 JUnit、`summary.env`、`metrics.csv` 和 Nextest 配置，辅以必要 console 与精炼日志；
   不为本任务开发通用证据 schema、审计/可信/因果/隐私设施。复制 retained evidence 不得改写原始内容，校验值须可复算。
8. **外部与秘密边界**：允许普通依赖/V8 下载和只读网络查询；测试应保持 deterministic/fake/offline/loopback。不得读取秘密、
   调用真实外部服务、发送项目数据、运行真实模型、Docker/训练或产生费用；意外外联按失败处理，不以既有凭据继续。
9. **Multi 冻结边界**：不得实质修改 `multidev/`。根共享设施的窄修只有在不改变 Multi 产品行为与既有测试合同且为 Local
   闭环所必需时才可继续；否则停下请求用户决定。
10. **Git 与验收停止点**：未知修改全部保留。执行者完成实现、最终门禁、动态 Plan 和精炼日志后只提交 113 分支并保持
    worktree clean；不得合并、推送、tag、发布、归档/释放 worktree 或删除 target。独立验收由计划制定者完成，main 集成与
    推送必须等待用户后续明确批准。

## 4. 软性建议

以下内容用于帮助执行者收敛，不是固定路线。执行者可依据 live code、实际故障和资源状态采用更优、更干净的方案，并把真正
影响架构、范围或正式口径的选择记入关键决策记录。

- 启动前做一次足够的 preflight 即可，复用已完成的空间门结论，不重建容量盘点或额外审计设施。正式环境可清理会污染测试
  语义的代理、颜色等交互 shell 变量，同时保留 V8/普通依赖下载所需的正常网络路径，并记录真正影响结果的环境口径。
- 初始完整轮尽量一次跑完以获得全局故障集合。锁瞬时占用可等待后重试；资源门主动停止或网络/V8 阻断应先处理原因并保留
  编译进度，不清空 target、不从头冷构建。
- 可按产品缺陷、测试/fixture/snapshot/生成物、资源竞争/non-hermetic、跨 crate 兼容、调度/入口和外部设施阻断分组，先用
  合适的最小过滤器或 crate 门禁复现，再选择最契合现有架构的修复。顺序与具体实现由执行者判断。
- 定向复验也应复用唯一共享 target、锁与 watchdog；若预计普通窄入口会重新生成大量 incremental，可优先考虑用 conservative
  入口配合过滤器或其它同等安全方式，避免无谓占用，但不为此扭曲调试效率或另建 target。
- 已知故障全部闭合后再冻结候选并启动最终轮。若首次轮已满足全部条件，则直接保留该轮证据，不做没有新增信息的重复全量。
- retained 目录只保留最终证据和真正有助于解释修复的诊断材料；执行细节写入一份精炼实施日志。最终数量以实际输出为准，
  不套用 Multi 的测试数，也不把 JUnit 中的 setup 计进 nextest passed。
- 独立审查优先复核 diff、JUnit/summary/metrics/console、候选提交和 ignored 现场；最终证据已经完整覆盖时，不为形式再次运行
  全 workspace。只有审查整改触及实质代码或正式口径时，才要求新的完整轮。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-09-03：确认规划起点的主工作区 clean，`main == origin/main ==
  a3288f2d4e84f894902845343e86be12974594bd`；111 是 clean 的已归档历史 worktree，不阻塞本任务。
- 2026-09-03：Local 独立空间门已在主线记录 `SPACE_GATE_PASS`：项目约 67.5 GB、唯一 Local target 约 19.8 GB、Multi
  target 不存在；预计完整 Local 轮后项目约 278--308 GB，低于 350 GB 告警线。本计划不重复释放或删除任何对象。
- 2026-09-03：从该 exact main 建立专用工作树
  `.claude/worktrees/113-plan108-local-full-workspace` 与分支 `worktree-113-plan108-local-full-workspace`。
- 2026-09-03：已阅读根/`mydev` 规则、README、当前 WBS、计划模板、Plan 105/107、相关实施/验收日志、Local 空间门和
  现行 Local conservative/V8/watchdog 入口，并冻结本 ExecPlan。规划阶段未运行 Cargo、未写共享 target/测试证据、未删除
  资源，也未执行 Docker、真实 API/模型、tag、发布、合并或推送。

### 当前工作

- ExecPlan 已冻结，等待执行者在 113 worktree 内开始 preflight 与首次完整 workspace。

### 本任务剩余步骤

- 完成轻量 preflight，在 clean exact candidate 上运行首次完整 Local workspace。
- 若有问题，完成归因、范围内修复和相称定向复验；冻结新候选后重跑同一完整门禁，直至最终轮满足全部条件。
- 轻量保留最终证据，更新动态 Plan 与精炼实施日志，提交并保持 113 worktree clean。
- 由计划制定者独立验收；如有影响实质代码或正式口径的整改，完成定向复验与新的最终完整轮。
- 验收通过后等待用户批准 main 合并与推送；获批后完成 Local 轻量 CI 终验和正确的 WBS/完成记录收口。

### 阻塞项

- 无。执行授权由用户随执行者提示词一次性授予；合并和推送仍保留为后续停止点。

### 当前验收状态

- `PLANNED / EXECUTION_NOT_STARTED / MERGE_PUSH_NOT_AUTHORIZED`。

### 交接边界

- Plan 108 完成后冻结本计划；下一工作包只由 WBS 指向 Local 发布，不在本计划打 tag、发布或展开发布方案。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 108 只负责 Local 最终全量、修复闭环与功能冻结；发布和缓存删除另行处理 | 正确性、发布和不可逆清理具有不同停止点与授权性质 | 范围、交接 | 已采纳 |
| 002 | 完整轮统一使用 Local `test-with-codex-v8-conservative --locked` 并绝对复用唯一 `rondo-local` target | 这是现行受保护的完整 workspace 入口，也满足用户对构建资产唯一性的明确要求 | 构建、测试、磁盘 | 已采纳 |
| 003 | commissioning 阶段保留已验证进度并允许自主修复；最终结果必须来自最终候选的 clean 完整轮 | 避免窄问题浪费昂贵编译，同时保证证据与代码严格对应 | 调试、正式结果 | 已采纳 |
| 004 | 首次完整轮若满足全部最终条件可直接作为最终轮；任何 retry/flaky 都必须通过新的零 retry 完整轮消除 | 既避免无信息重复，也落实本任务更严格的最终稳定性口径 | 验收、资源 | 已采纳 |
| 005 | 复用 wrapper 原生证据并把必要副本放入主物理 retained path，不新建审计或可信设施 | 现有 JUnit、summary、metrics、配置和日志足以支持独立验收 | 证据、复杂度 | 已采纳 |
| 006 | 执行者只提交 113 分支；计划制定者审查，main 合并和推送必须再由用户批准 | 遵守用户指定的角色与 Git 停止点 | Git、验收 | 已采纳 |
| 007 | 使用 worktree 序号 113，而不复用历史 `worktree-108-*` 命名 | 仓库已有 `zz-done/worktree-108-multi-space-gate-release`，新序号避免分支身份碰撞 | 工作树、历史 | 已采纳 |
