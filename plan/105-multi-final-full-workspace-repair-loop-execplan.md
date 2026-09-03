# Plan 105：RONDO Multi 最终全 Workspace 测试与修复闭环 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

对应 WBS：`doc/WBS.md` 的“产品线配套补齐与逐条收口”阶段一中，Multi 空间门之后的
“全量测试 → 必要修复与复验 → 最终全量通过 → 功能冻结”。
执行基线：`main@b943fd006db2fe879dd255e6d3ec791c23003687`，Codex CLI 基线仍冻结为 `v0.147.0`。

## 1. 目标

### 最终目标

在用户完成本轮独立空间释放后，对当前 RONDO Multi 发布候选运行 Linux、default features、standard local
Nextest 的完整 workspace 测试；自主诊断并修复测试实际暴露的范围内问题，完成相称的定向复验，并在最终实现冻结后
重跑同一全量门禁，直至形成一份与最终代码严格对应、可以交由审查者验收和进入后续发布任务的全绿结果。

本任务负责正确性收口与 Multi 实质代码/功能冻结，不负责发布、打 tag、更新发布链接，也不负责测试后的构建缓存删除。

### 完成/验收标准

- [ ] 执行前确认用户正在进行的独立空间释放已经结束；主工作区、107 工作树、共享构建锁、Windows `C:` 实际余量、
      项目占用及唯一 Multi target 均满足根 `AGENTS.md` 和现行 watchdog 的启动条件。若前置尚未完成，只等待或报告，
      本任务不擅自清理任何既有资产。
- [ ] 通过 `multidev/justfile` 的 `test-with-codex-v8-conservative --locked` 入口完整执行当前 workspace；使用
      checksum-verified V8、`CARGO_BUILD_JOBS=1`、LLD 单线程、`CARGO_INCREMENTAL=0`、共享构建锁和资源看门狗，
      不改用 `--all-features`，不把全部 ignored tests 强行纳入本轮口径。
- [ ] 初始全量所见的每项有效 failure、error、timeout 和异常 retry 都有清楚分类。范围内缺陷先聚焦复现，再以产品修复、
      fixture/snapshot/生成物更新或测试设施修复等合适方式解决，并完成与实际影响相称的定向回归；基础设施阻断与代码失败
      分开记录。
- [ ] 最终产品代码、测试、配置和生成物冻结后，在 clean exact HEAD 上再次完整运行相同全量门禁，得到零 failure、零 error、
      零 timeout。若首次全量已经在 clean exact HEAD 上全绿且之后没有任何会影响代码、测试或运行口径的改动，该轮可以直接
      作为最终轮，不为形式重复一次同等重型测试。
- [ ] 最终轮如有 retry，逐项确认首次现象和最终状态：确定性产品或测试设施问题必须修复；可明确归因于端口、teardown、
      loopback 或调度瞬态的问题，经新进程定向无 retry 复核后可以接受。skip/ignored/未运行不计为 passed，数量及相较
      Plan 093 基线的显著变化有简要解释。
- [ ] 修复遵循就近架构与测试惯例；功能或测试语义变更配有能防止回归的相称测试。没有为了凑绿而删除覆盖、弱化断言、
      扩大通用 timeout、增加宽泛 skip/ignore、关闭安全检查或改变既有默认行为。
- [ ] 最终全量的现成 watchdog/JUnit 证据得到轻量保留，至少可确认 exact commit、实际命令与构建方式、测试/skip/retry 计数、
      返回状态、耗时、资源停止/清理状态和 JUnit SHA-256；不另建数据库、签名链、证据图或通用审计设施。
- [ ] 无 `.snap.new`、非预期 lockfile 漂移或无法解释的生成物；任务差异、工作树和共享 ignored 资产均经自检，实施日志诚实区分
      已通过、skip、未运行与基础设施阻断。
- [ ] 执行者更新本计划动态状态和一份精炼 `agent_log/`，只提交 107 工作树分支并保持 worktree clean，向用户提交完成汇报供
      计划制定者审查。未经用户后续明确批准，不合并 `main`、不推送、不打 tag、不发布、不归档或释放工作树。
- [ ] 计划制定者独立审查正确性、修复范围、最终 JUnit/summary、资源状态、意外生成物与 Git 停止点；High/Medium correctness
      finding 关闭后才可记录 `ACCEPTED / MULTI_FUNCTIONALLY_FROZEN`，并由审查者同步受影响的 WBS 与完成记录。

## 2. 范围

### 允许修改

- `multidev/` 内由本次全 workspace 测试实际暴露问题所需的产品代码、测试、fixture、snapshot、生成文件、Cargo 配置与依赖。
- 与失败直接相关的根共享构建/测试入口、helper、轻量回归和当前维护文档。职责契合时复用既有设施；强行复用会造成耦合或
  语义扭曲时，可以建立职责清楚的专用能力，但不得重复建设第二套构建、测试或结果体系。
- 本 ExecPlan 的“当前状态”和“关键决策记录”、一份精炼实施日志；审查通过后由审查者更新 `doc/WBS.md`、
  `doc/WBS-COMPLETED.md` 及必要的验收日志，准确记录 Multi 正确性收口和冻结状态。
- 普通依赖下载、checksum-verified V8 工件、与测试直接相关的只读源码/文档查询、task-owned `/tmp`、测试 `TempDir`、
  107 工作树内的 ignored 调试输出，以及下节列出的主物理仓库 ignored 路径。

### 不允许修改

- `mydev/` 的 RONDO Local 产品代码、测试、配置与语义；本任务不得提前开展 WBS 阶段二。
- 冻结的 Codex CLI `v0.147.0` 上游基线、`codex-source-code/`、既有方向终态、Publication Critic 质量资格结论、
  default-off 姿态或未解锁的方向 3 工作包四。
- 与全量失败无关的产品能力、测评/训练路线、仓库发布工程、版本号、CHANGELOG、README 发布链接、release workflow、tag 或发布对象。
- 现有共享 target、其他 worktree、分支、缓存、历史测试证据或来源不明资产的删除、移动、裁剪、清空、stash、覆盖或清理。
- Docker、真实 API、真实本地模型、GPU/RunPod、训练、冻结测评集释放、真实数据外发、付费或其它外部状态变更。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/API Key、项目外个人文件或私有数据。
- 冻结 qualification/unseen 测试正文、模型权重、其它 worktree 的未提交 diff 或 ignored 资产正文。

### Git-ignored 与主物理工作区边界

受跟踪编辑全部在
`/home/sjc/desktop/RONDO/.claude/worktrees/107-multi-full-workspace-closure/` 完成。以下内容受根
`.gitignore` 覆盖，但测试入口会跨 linked worktree 直接使用主物理仓库中的项目唯一资产，因此执行者应在交付时单独汇报；
它们不会出现在 107 分支 diff 中：

- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi/`：唯一允许使用和继续加热的 Multi Cargo target。即使空间任务
  已将其清空或删除，正式入口也只能在这个 canonical 路径重建，绝不在工作树、`multidev/codex-rs/target`、`/tmp` 或其它位置
  新建第二套 target。
- 107 工作树内 `.codex/build-watchdog/`：既有 wrapper 自动生成的逐轮临时 metrics、summary、nextest config 与 JUnit。
- `/home/sjc/desktop/RONDO/test-data/_retained-test-evidence/plan105-multi-final-full-workspace/`：只轻量保留最终全量现成证据及必要
  失败诊断，不扩展为新的证据平台；该路径需要直接写主物理工作区，以便 107 worktree 后续释放后仍可复核。

除上述路径及普通 task-owned 临时目录外，若执行意外要求写入其它主工作区 ignored 路径，先向用户报告准确路径、用途、预计体积与
保留/清理责任并取得授权。

## 3. 硬约束

以下约束只固定任务边界、正式测试口径、资源安全、诚实判定与 Git 停止点，不固定具体模块布局、修复方案、调试轮数或逐测试矩阵。

1. **空间前置与资源门**：用户侧空间释放完成且只读 preflight 通过后才启动重型测试。本任务不得自行删除或搬移资源；不能读取
   Windows `C:` 实际余量、共享锁、cgroup 或其它必要计数器时 fail-closed，不得用 WSL 虚拟余量替代，也不得降低现行阈值。
2. **唯一正式入口与 target**：所有重型 Cargo 构建、lint 和测试经根共享锁/watchdog 接入的既有 `just` 入口执行。完整 workspace
   固定使用 `test-with-codex-v8-conservative --locked`；不得直接 Cargo、绕过看门狗、提高并发、覆盖 `CARGO_TARGET_DIR`，或建立
   第二套 target。Multi/Local/Docker/真实模型等重型任务保持全局串行。
3. **调试进度可保留**：初始全量是 commissioning/诊断轮，不因一次失败就报废已验证编译进度或清空 target。执行者可以自主进行
   任意合理次数的聚焦复现、窄修、定向复验和同口径全量重跑；不得设置“失败一次即停止”或机械重试次数上限，也不得在原因未变时
   盲目反复运行昂贵全量。
4. **最终轮对应最终代码**：最后一次会影响 Multi 产品、测试、fixture、snapshot、Cargo/Nextest 配置、依赖图、build script 或
   正式运行口径的改动完成后，必须提交并冻结 exact HEAD，再跑完整 workspace。其后仅允许更新 Plan、日志和完成记录；若审查整改
   再次改动上述内容，定向验证后必须重跑同一全量门禁。
5. **自主修复但不越界**：当前基线可稳定复现的产品 bug、测试/fixture/snapshot/生成物缺口、非 hermetic 问题、跨 crate 兼容问题及
   直接相关的构建设施问题均可自主修复。需要升级上游基线、改变对外协议或既有权限/生命周期合同、重定义产品目标、打开默认关闭能力、
   跨入 Local 阶段，或明显扩成独立大型项目时，停止扩围并请求用户决定。
6. **正确性优先**：修 bug 先复现并补相称回归；不得把真实产品缺陷归为环境波动，不得用旧 binary、stale artifact、mock 替代本应
   运行的产品路径。允许选择比窄补丁更干净的局部重构或专用能力，只要与现有配置、生命周期、错误、测试和观测方式一致且不重复建设。
7. **诚实结果**：只有最终 full workspace 的命令、JUnit 与 wrapper summary 同时支持，才能记录最终通过。failure/error/timeout 为零
   是硬门；skip、ignored、retry-pass、未运行和 blocked 分开报告。资源停机、V8/依赖取得失败或宿主设施问题只能记为基础设施阻断，
   不得冒充代码通过或任务完成。
8. **证据从简**：优先复用 wrapper 已生成的 JUnit、`summary.env`、`metrics.csv` 和 nextest config，只增加一份精炼说明或实施日志。
   不为本任务开发通用采集器、manifest schema、签名、可信校验、因果归因或隐私平台。
9. **外部与秘密边界**：本任务只允许 deterministic/fake/offline/loopback 测试、普通依赖与 V8 下载、只读网络查询和本机 browser
   opener stub。不得读取秘密、调用真实外部服务、发送项目数据或产生费用；测试意外尝试外部访问时应隔离并按失败性质处理。
10. **Git 与审查停止点**：未知修改全部保留。执行者完成实现、验证、动态 Plan 和精炼日志后，只提交
    `worktree-107-multi-full-workspace-closure` 并保持 worktree clean；不得合并、推送、打 tag、发布、归档/释放 worktree 或删除
    Multi target。计划制定者在同一工作树独立审查；只有用户另行批准后才进行 main 集成与推送。

## 4. 软性建议

以下内容用于帮助执行者收敛，不是固定路线。执行者可以依据 live code、失败性质和资源状态采用更优、更干净的方案，并把真正影响
架构、范围或正式口径的选择记入关键决策记录。

- 开始前可先确认 107 基线、共享 target 现状、重型进程与空间门，不必重复前置空间任务的盘点或重建另一套检查脚本。
- 初始完整轮尽量一次跑完以获得全局故障集合。若 wrapper 因明确的瞬时锁占用在 payload 前拒绝启动，可等待冲突结束后重试；若因
  资源门主动停止，应保留进度并先解决同一阻断原因，不盲跑。
- 失败可按产品缺陷、测试/fixture、生成物/snapshot、环境瞬态和基础设施阻断分组。先用最小过滤器或 crate 门禁复现，修复后跑受影响
  crate/相邻合同；具体顺序由依赖关系和节省重型轮次的价值决定。
- 职责契合时复用既有 helper 与测试设施；若复用会让语义变形或高耦合，可以新建窄而专用的能力。复杂度由实际缺陷决定，不强求
  最小行数，也不借机预建未来平台。
- 在所有已知故障和定向门禁闭合后再提交候选并启动最终完整轮。首次完整轮若没有发现问题且其 exact HEAD、工作树状态和证据都满足
  最终要求，可直接收口，不额外消耗一次全量资源。
- 最终证据可从 wrapper run 目录择取必要文件复制到主物理 retained path，并在日志记录 exact commit、命令、构建方式相对 Plan 093
  的 `CARGO_INCREMENTAL=0` 差异、计数、耗时、资源终态和 JUnit hash；无需保留每次成功的冗余副本。
- 可使用少量子智能体做失败分组、相邻源码调查或最终只读自检，但重型 Cargo 必须全局串行，共享代码编辑和提交由执行者统一收口。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-09-02：确认主工作区 clean，`main` 与 `origin/main` 同为
  `b943fd006db2fe879dd255e6d3ec791c23003687`；现有 106 worktree 为已归档、clean 的 Plan 104 历史现场。
- 2026-09-02：从该基线建立专用工作树
  `.claude/worktrees/107-multi-full-workspace-closure` 与分支 `worktree-107-multi-full-workspace-closure`。
- 2026-09-02：已阅读根/`multidev` 规则、README、当前 WBS、计划模板、Plan 093/104、相关全量实施与验收日志、
  `doc/development-environment.md` 和当前 conservative/V8/watchdog 入口，并冻结本 ExecPlan。
- 2026-09-02：用户说明前置任务已完成、空间资源正在释放；本规划没有运行 Cargo、写入共享 target/测试证据、删除资源，
  也没有执行 Docker、真实 API/模型、发布或其它外部动作。
- 2026-09-02：并行的空间门任务随后完成并在 `main@d9dc3d51` 记录 `SPACE_GATE_PASS`：精确释放两条产品 target 的
  `debug/incremental` 与 clean 的 106 历史 worktree，项目释放约 59.7 GiB，Windows `C:` 实测可用约 109.8 GB；
  保留唯一 Multi target 的 `deps`、fingerprint 与 build 缓存。该提交只新增空间门日志，与 107 基线之间无产品或共享设施差异。

- 2026-09-02：preflight 通过（Windows `C:` 可用 109.8 GB、项目 168.7 GB、唯一 Multi target 104 GB 且无并发重型进程），
  以 `test-with-codex-v8-conservative --locked` 完成初始全 workspace 诊断轮：`14713 tests run, 14707 passed,
  6 failed, 24 skipped, 3 flaky`，watchdog `stop_reason=none`，JUnit SHA-256
  `3628c33baa26b73941c1053de4b77fb4691412c28fad11209046d4ee2317659f`。
- 2026-09-02：6 项 failure 全部归因完毕，均非 Multi 产品缺陷。4 项 `codex-exec`（`suite::approval_policy::` ×3、
  `suite::resume::exec_resume_preserves_cli_configuration_overrides`）源于 agent shell 的 `FORCE_COLOR=3`：产品刻意
  尊重 `FORCE_COLOR`，导致 exec 头部即使写入管道也带 ANSI 属性，断言纯文本子串失败。2 项
  `suite::fuzzy_file_search::` 是 app-server `initialize` 撞上 10 秒期限；隔离复跑同样 12 项为 0.17–1.4 秒
  （全套 1.68 秒），确认是四个 app-server 同波启动的宿主争用。
- 2026-09-02：已落地修复并冻结实现于 `2199316c`。`.config/nextest.toml` 把
  `suite::fuzzy_file_search::` 并入既有 `app_server_integration`（max-threads=1），与相邻 zsh-fork override 对同一症状的
  处置一致；未放宽任何 timeout、未弱化断言、未新增 skip。`doc/development-environment.md` 记录跑本地套件前需清空代理与
  `FORCE_COLOR`。定向复验（新进程、`--retries 0`）22/22 通过，覆盖 fuzzy-file-search、zsh-fork、
  `sandbox_with_network_proxy` 与全部 4 项 exec。

- 2026-09-02：GitHub 直连恢复后，用户单独授权删除本任务新增的
  `.codex/cargo-target/rondo-multi/debug/incremental/`（20 GB，conservative 入口不使用），
  仅删该目录，项目降至 316.2 GB。随后在 clean HEAD `39d5841f`（相对实现冻结点 `2199316c` 只多出 Plan/日志提交）
  上完成最终同口径全量：

  ```
  14713 tests run: 14713 passed (4 slow), 24 skipped
  ```

  零 failure、零 error、零 timeout、**零 retry/flaky**；watchdog `stop_reason=none`、`cleanup_reason=none`。
  JUnit SHA-256 `97fb4a43daf397c46d45b7f3ff3b82f7accb0604a614926d0e3f4c66ebb3c2fc`
  （JUnit 内 `tests="14714"` 比 nextest 计数多 1，是把 `@setup-script:publication-critic-service-unix` 也算作一项）。
  资源终态：项目 316.7 GB（峰值 320.3 GB）、Multi target 257.9 GB、Windows `C:` 可用 118.2 GB、
  内存峰值 8.3 GB、PSI 0。

### 当前工作

- 全部已知问题闭合，最终全量已通过并留证，等待计划制定者独立验收。

### 本任务剩余步骤

- 计划制定者独立验收；finding 如需改代码则在同一分支修复、定向复验并重跑最终全量。
- 验收通过后由审查者记录 `ACCEPTED / MULTI_FUNCTIONALLY_FROZEN` 并同步 WBS 与完成记录。

### 阻塞项

- 无。

### 当前验收状态

- `PLANNED / SPACE_GATE_PASS / IMPLEMENTED@2199316c / FINAL_FULL_RUN_GREEN@39d5841f / NOT_MERGED / NOT_PUSHED / PENDING_REVIEW`。

### 交接边界

- 本任务验收后冻结计划；后续 Multi 发布、发布复验、构建缓存删除和 Local 阶段只按 WBS 另行立项或授权，不在本计划追加。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 105 只承接 Multi 的最终全量正确性与修复闭环；空间清理视为外部前置，发布和缓存删除留给 WBS 后续 | 避免把不同风险和授权性质的任务重新捆绑 | 范围、授权、交接 | 已采纳 |
| 002 | 全量统一使用 `test-with-codex-v8-conservative --locked`，并绝对复用主物理仓库唯一 `rondo-multi` target | 这是现行受跟踪的完整 workspace 安全入口，也满足用户对唯一 target 的明确要求 | 构建、测试、磁盘 | 已采纳 |
| 003 | 初始完整轮作为 commissioning；保留进度自主修复，最终代码冻结后才确认正式结果 | 避免小问题导致重型进度报废，同时保证最终结果对应最终代码 | 调试、修复、正式结果 | 已采纳 |
| 004 | 若首次完整轮在 clean exact HEAD 上全绿且之后无相关改动，允许同一轮成为最终轮 | 不牺牲证据对应关系，也不做没有新增信息的昂贵重复 | 验收、资源 | 已采纳 |
| 005 | 只保留 wrapper 已有的轻量证据，不开发新的审计/可信设施 | 现有 JUnit、summary 和 metrics 已足以支撑正确性审查 | 证据、复杂度 | 已采纳 |
| 006 | 执行者只提交 107 分支；审查、合并、推送、发布和 target 删除分离 | 遵守用户指定的 reviewer 与 Git 停止点 | Git、验收、后续任务 | 已采纳 |
| 007 | 接受 `main@d9dc3d51` 的独立空间门结论，不为一份日志提交重建 107；执行仍以 107 的产品等价基线开展 | 新提交只含空间门日志，产品与共享设施相对 107 基线无差异；未来合回 main 时日志自然保留 | 执行基线、并行隔离 | 已采纳 |
| 008 | 正式门禁在中性环境运行：清空 shell 的代理变量与 `FORCE_COLOR`，而不是改上游测试去适配这两个条件 | 二者都是 agent shell 的环境条件；产品刻意尊重 `FORCE_COLOR`，测试也全是 offline/loopback，改测试等于让冻结的 v0.147.0 基线迁就本机 shell | 运行口径、上游一致性 | 已采纳 |
| 009 | fuzzy-file-search 的 10 秒 initialize 超时用既有 `app_server_integration`（max-threads=1）串行化解决，不放宽 timeout | 隔离实测 initialize 仅 0.2 秒，属宿主争用；相邻 zsh-fork override 对同一症状已有同样处置，复用比新建更一致 | 测试并发、稳定性 | 已采纳 |
| 010 | 不自行删除 target 内任何资产（含本任务新增的 20 GB `debug/incremental/`），由 watchdog fail-closed 兜底并请用户决定 | 授权明确排除删除 target/缓存；停机可恢复且进度保留，不值得越界 | 磁盘、授权边界 | 已采纳；用户单独授权后只删该目录 |
