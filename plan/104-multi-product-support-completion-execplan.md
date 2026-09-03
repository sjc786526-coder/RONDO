# Plan 104：Multi 产品配套补齐 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

对应 WBS：`doc/WBS.md` 的“产品线配套补齐与逐条收口”阶段一 M-1 / M-2 / M-3。
执行基线：`main@3f22453cb0027d2f5d2b46f97a2e8a2618bdb877`，Codex CLI 基线仍为冻结的 `v0.147.0`。

## 1. 目标

### 最终目标

补齐 RONDO Multi 在最终全量测试前已经确认的三项配套缺口：让轻量 CI 持续运行
`codex-team-state` 测试，让 `/status` 如实呈现已加载的 Guardian override 配置，并在仓库根提供公共
Guardian 与 Multi 的 RONDO 配置指南及清楚入口。本任务不新增产品能力，不改变任何默认行为。

### 完成/验收标准

- Multi 的 CI `TEST_PACKAGES` 包含 `codex-team-state`；`doc/ci-pipeline.md` 的 package 表、说明和
  Multi 本地复现命令与 workflow 一致，Local 的 CI 范围不因本任务改变。
- 推送后的 Multi 轻量 CI 通过；日志明确显示 `codex-team-state` 实际运行了非零测试，不能只以命令退出码为证。
  首次实跑后复核现有耗时说明是否仍合理，只有证据表明需要时才修订实测数据。
- Multi `/status` 对四类显式 Guardian override（model、provider、reasoning effort、evidence directory）
  中实际已加载的项目给出有界摘要，并满足：
  - reviewer 为 `AutoReview` 且存在 override 时，说明配置已加载；
  - reviewer 为 `User` 且存在 override 时，说明配置已加载但当前 reviewer 未选用它；
  - 不存在 override 时不新增状态行，既有无配置界面和相应快照保持稳定。
- `/status` 的措辞只陈述当前配置和 reviewer 选择，不声称某次审批已经运行或实际使用了某个模型、provider、
  effort 或 evidence 路径。配置摘要不得改变 Guardian 的模型解析、审批路由或运行时行为。
- 新增根 `doc/rondo-config.md`，清楚说明 RONDO 相对上游新增的公共 Guardian 配置和 Multi 配置、默认关闭/选择
  关系及必要依赖，并指向上游通用配置文档；README 提供清楚入口。指南不写 Local 专属配置，不与产品树继承文档
  重复建设第二份通用 Codex 配置手册。
- 与最终差异直接相关的格式检查、`codex-team-state` 测试、Multi TUI 状态测试及快照验证通过；所有快照改动均经
  人工阅读确认。未运行、skip 或 CI 尚未触发的项目必须如实标注。
- 工作树差异只包含本任务必要内容，完成实现、验证和自检后提交到工作树分支。合并、推送和推送后 CI 验收须在
  审查通过并取得用户另行明确批准后执行；在此之前不得把任务整体标记为完成。

## 2. 范围

### 允许修改

- `.github/workflows/ci.yml` 与 `doc/ci-pipeline.md`：仅补 Multi 的 `codex-team-state` 轻量测试覆盖及对应说明。
- `multidev/codex-rs/tui/src/status/` 中 `/status` 实现、相邻测试和必要快照；若职责更清楚，可使用同模块下的
  小型专用文件，而不强制把逻辑继续堆入既有大文件。
- 新增 `doc/rondo-config.md`，并修改根 `README.md` 提供入口。
- 本 ExecPlan 的当前状态、必要的精炼 `agent_log/`，以及在任务达到对应状态后受影响的 WBS / 完成记录。
- 因上述改动直接需要的窄幅测试修订、注释和文档链接修订。

### 不允许修改

- `mydev/` 下任何 Local 产品代码、测试、快照或 Local `/status`。
- 两棵产品树继承的 `docs/`、`codex-rs/config.md`，以及只读上游/参考源码。
- Guardian、Team State、Durable Team、Publication Critic、Team Lens 或其他产品能力与运行时语义；reviewer、模型选择、
  provider、reasoning effort、证据捕获、feature gate 及其默认值。
- 把 `codex-tui` 整体加入 CI，或把本任务扩成全 workspace CI。
- Cargo 依赖、lockfile、配置 schema 或发布产物；本任务没有新增配置字段或依赖的理由。
- 方向 3 后续研究、训练、测评、资格结论、产品冻结、tag、发布、空间整理、缓存清理或任何删除动作。

### 不允许读取/查看

- `.env.local` 内容、任何凭据/API Key、真实私有配置或项目范围外的个人文件。
- 冻结测试集、私有测评样本、模型权重或与本任务无关的其他 worktree 未提交内容。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. `/status` 必须基于当前有效 `Config` 中的显式 Guardian override 摘要配置状态；不得把“已加载”升级为“已生效于
   某次 review”，也不得从配置值推断运行时实际模型身份。
2. 无任何 Guardian override 时不新增行，不为展示能力而制造空值、默认值或重复 reviewer 信息。存在部分 override 时
   只报告确实加载的部分，不补写推测值。
3. 本任务只增加状态呈现、用户文档和持续测试覆盖。关闭态、默认 reviewer、feature gate、审批路由、模型/provider
   解析优先级、Team State 行为与发布路径必须保持不变。
4. CI 必须在 Multi 既有轻量 package gate 中真正选择 `codex-team-state`；最终验收必须查看 Actions 日志中的非零测试数。
   不得用零测试成功、过滤失配、skip 或仅编译成功替代测试通过。
5. 根配置指南以当前配置类型、schema 与解析代码为事实源，只记录 RONDO 用户需要的增量内容。不得把实验性能力写成
   默认启用、已获质量资格或生产可用；Publication Critic 的现行负向资格结论不得被配置示例淡化。
6. 所有本地重型 Cargo 构建、lint 和测试必须使用根共享构建锁/看门狗的既有 `just` 入口，并继续使用物理仓库根下唯一的
   `.codex/cargo-target/rondo-multi`。不得直接运行正式重型 Cargo 命令、不得覆盖 `CARGO_TARGET_DIR`、不得在工作树或
   其他位置新建第二套 target，也不得提高既有并发上限。最终全 workspace 测试不属于本任务。
7. 执行期间可以自主修复任务范围内的普通编译、测试、快照、CI 或瞬时故障并合理重跑，不因一次可窄修的问题中止；
   但不得通过弱化测试、断言或安全边界换取绿色。只有解决问题必须突破本计划范围、使用未授权外部资源或执行不可逆
   操作时才暂停并请求用户决定。
8. 本地实现和本地验证只在本工作树进行，保护主工作区及其他任务现有修改。完成后只提交工作树分支；未经用户后续明确批准，
   不合并 `main`、不推送、不打 tag、不发布。
9. 本任务不使用真实 API、真实本地模型、Docker、GPU、付费资源或真实数据外发，也不读取密钥。

## 4. 软性建议

以下内容用于根据现有代码给出的执行建议，但不是固定约束，也不代表代码变化之后的精准效果预测。AI 可以依据代码、
实际测试和运行结果采用更优方案。

- `/status` 可先形成一个可选的展示值，再沿用现有 `FieldFormatter` 与快照设施渲染。辅助逻辑放在 `card.rs` 还是同模块
  专用文件，以最终职责和可读性为准，不必为一行摘要建设新的通用状态框架。
- 优先复用 `test_config`、现有 auto-review snapshot 和状态渲染测试；三态既可以用少量聚焦断言加代表性快照覆盖，
  也可以采用同等清晰、维护成本更低的测试组合。
- CI 继续沿用现有 `TEST_PACKAGES` 机制即可。同步检查 workflow 注释、文档 package 表、本地 Multi 复现命令和首次
  Actions 日志；除非实测明显改变，不必为了“更新”而改写已有历史耗时。
- `doc/rondo-config.md` 宜用短例子和字段/关系说明覆盖公共 Guardian 与 Multi 的 RONDO 增量，并链接两条产品线已有
  `docs/config.md` 获取上游通用配置。具体结构由执行者按可读性决定。
- 验证范围应与实际差异相称，通常包括最终格式检查、`codex-team-state` package、`codex-tui` package 的相关状态测试与
  snapshot pending 检查、文档链接/CI 配置自检及 `git diff --check`。若发现真实相邻影响，可增加必要的窄门禁；不要
  自动扩大为最终全 workspace 测试。
- 在耗时流程中保留已验证进度，从首次未打通处边修边跑；最终以干净工作树差异上的一次完整定向门禁作为交付证据。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根/`multidev` 开发规则、当前 WBS、Multi 现行约束、CI workflow 与权威 CI 文档、Guardian 配置结构、
  Multi 配置结构、`/status` 现有实现与相邻测试。
- 已从干净 `main@3f22453c` 建立专用工作树
  `.claude/worktrees/106-multi-product-support` 和分支 `worktree-106-multi-product-support`。
- 已冻结本 ExecPlan。
- **M-1**：`.github/workflows/ci.yml` 的 Multi `TEST_PACKAGES` 加入 `-p codex-team-state`；
  `doc/ci-pipeline.md` 同步不变量 1 的措辞、package 表、Multi 本地复现命令块，并标注既有耗时数据
  形成于该 crate 入 CI 之前；首次纳入后的热缓存实测已补记。
- **M-2**：新增 `multidev/codex-rs/tui/src/status/guardian.rs`（`card.rs` 已 945 行，超过
  `multidev/AGENTS.md` 的 800 行门槛，故新开模块而非继续堆入），`card.rs` 增加
  `guardian_config: Option<String>` 字段、标签与渲染行。三态断言与一份代表性快照落在既有
  `status/tests.rs`，复用 `test_config`。
- **M-3**：新增 `doc/rondo-config.md`（公共 Guardian 增量 + Multi 增量，链接上游通用配置文档）；
  `README.md` 在"从源码构建"与仓库结构树两处提供入口。
- 本地最终门禁 `3602/3602` 通过，其中 `codex-team-state` 实跑 159 个测试；独立审查又以
  `codex-team-state` 全包加 4 个新增 status 测试完成 `163/163` 窄复验。
- 首次独立审查发现的配置回退解释、默认状态措辞、Local 范围和任务状态记录问题均已完成窄文档修订并复核；
  产品代码无需整改。
- 已以非快进 merge `8a8a14ff` 合入 `main` 并推送 `origin/main`；工作分支已归档为
  `zz-done/worktree-106-multi-product-support`。
- 推送触发的 GitHub Actions `ci` run `33710767703` 全部通过：Multi check 10m38s、Local check 10m52s；
  Multi Gate 3a 明确选择 `-p codex-team-state`，该 crate 发现 160 个测试并得到 159 passed、1 ignored、0 failed。

### 当前工作

- 本任务已完成并冻结；后续工作只按 WBS 另行立项，不在本计划继续展开。

### 本任务剩余步骤

- 无。

### 阻塞项

- 无。

### 当前验收状态

- `COMPLETED / FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED / INTEGRATED / PUSHED / CI_PASS`。

### 交接边界

- 本任务完成后冻结此计划；后续空间门、最终全量测试、冻结、发布与 Local 阶段只链接 WBS，不在本计划展开。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 用一个 ExecPlan 共同交付 M-1 / M-2 / M-3，任务内顺序由执行者决定 | 三项共同形成 Multi 全量前的同一配套收口，WBS 明确阶段内无技术顺序依赖 | 本任务 | 已采纳 |
| 002 | 根配置指南只写 RONDO 增量，并链接上游通用配置文档 | 避免重复、冲突和产品树继承文档漂移 | `doc/rondo-config.md`、README | 已采纳 |
| 003 | `/status` 只展示显式已加载 override 与 reviewer 选择，不展示推断的实际运行身份 | 配置加载不等于某次审批实际使用 | Multi TUI | 已采纳 |
| 004 | 工作树提交与 `main` 合并/推送分开授权，推送后 CI 仍是任务最终验收的一部分 | 遵守本次用户指定的审查流程，同时保留完整宏观验收 | Git 流程、CI | 已采纳 |
| 005 | 本任务没有必须在主工作区直接编辑的 git-ignored 交付物；本地构建只复用根共享 target 与锁 | 所有产品、CI 和文档变更均为受跟踪文件，共享 target 只是既有执行设施 | 工作树、构建设施 | 已采纳 |
| 006 | Guardian 摘要逻辑放新模块 `status/guardian.rs`，而非继续写进 `card.rs` | `card.rs` 已 945 行，超过 `multidev/AGENTS.md` 的 800 行门槛；本计划 §2 也允许同模块下的小型专用文件 | Multi TUI | 已采纳 |
| 007 | 状态行措辞定为 `loaded for reviewer auto_review (...)` / `loaded, unused by reviewer user (...)`，用 config 里的字面值指代 reviewer | 两态对称且都点名 reviewer，满足 WBS "显示 reviewer 与已加载 override"；显式 model 是最高优先级 slug，但 `loaded` 只陈述加载事实，不声称某次 review 已发生或 provider 已实际处理它 | Multi TUI、`doc/rondo-config.md` | 已采纳 |
| 008 | 每项 override 值按 48 列上限截断 | 值来自自由文本配置，而 transcript 渲染宽度是 `u16::MAX`，不截断会让一条长路径撑爆整块记录 | Multi TUI | 已采纳 |
| 009 | 保留 CI 文档中的既有冷/热历史表，并补记首次纳入 team-state 后的热缓存实测 | 新 Multi run 为 10m38s，未超原 13m50s 参考值；没有新的冷缓存数据，故不虚构或覆盖冷跑基线 | `doc/ci-pipeline.md` | 已采纳 |
