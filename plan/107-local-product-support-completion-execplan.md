# Plan 107：Local 产品配套补齐 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

对应 WBS：`doc/WBS.md` 的“产品线配套补齐与逐条收口”阶段二 L-1 / L-2。
执行基线：`main@58ed2f0385aa1e8d9466a79f9c2944714ca61315`，Codex CLI 基线仍为冻结的 `v0.147.0`。

## 1. 目标

### 最终目标

一次补齐 RONDO Local 在最终全 workspace 测试前已经确认的配套缺口：让 Local `/status` 如实呈现
Guardian override 的加载状态，在根 `doc/rondo-config.md` 增加与当前源码、受跟踪示例和产品结论一致的
Local 专属配置说明，并同步 README 入口与必要的当前规划记录。本任务只完善呈现和文档，不新增产品能力，
不改变默认值，也不提前形成 Local 全量、冻结或发布结论。

### 完成/验收标准

- Local `/status` 对当前有效配置中存在的四类标识性 Guardian override（model、provider、reasoning effort、
  evidence directory）提供有界摘要，并满足三态语义：
  - reviewer 为 `AutoReview` 且存在 override 时，说明配置已加载；
  - reviewer 为 `User` 且存在 override 时，说明配置存在但当前 reviewer 未选用；
  - 不存在 override 时不新增状态行，既有无配置界面和相关快照不发生无理由漂移。
- 状态行只陈述当前加载的配置与 reviewer 选择，不声称某次审批已发生、请求已到达 provider，或某个模型、
  provider、effort、证据路径已经在运行时被实际使用；不改变 Guardian 的配置解析或审批路由。
- 根配置指南新增精炼的 Local 专属章节。章节依据当前 Local 源码、配置解析与受跟踪示例核实字段和生命周期，
  说明配置入口、运行前提和现有边界；清楚区分“字段可以配置”“工程接缝已经存在”“特定模型或用途已经获得资格”。
- Local 本地审批模型继续如实标为“保留为实验、未采用”。文档不得暗示下载任意权重后即可使用，也不得把历史上
  某一窄合同的工程或模型证据外推为真实审批放行资格、默认启用或生产可用。
- 配置指南继续只写 RONDO 相对冻结上游的增量，并指向上游通用配置文档；不得复制出第二套 Codex 通用配置手册。
  README 的概述和入口能让读者清楚找到公共 Guardian、Multi 与 Local 的增量说明。
- 与最终差异直接相关的 Local 格式检查、TUI 状态测试和快照检查通过；测试日志证明相关测试非零执行，所有有意
  变更的快照均经阅读确认，且没有遗留 `*.snap.new` 或其他意外产物。未运行或 skip 的项目如实标注。
- 必要的 WBS、完成记录、Plan 动态状态和精炼实施日志按各自职责同步。最终 WBS 只能写“Local 配套完成、下一步为
  独立空间盘点任务”，不得提前写成 Local 全量通过、功能冻结或发布就绪。
- 实现完成并通过本地验证后只提交专用工作树分支，交由计划制定者独立审查；任务内审查问题全部闭合后，仍须获得
  用户明确批准才可合并和推送。本地证据须确认定向 TUI 测试非零执行；获批合入后，推送触发的 Local 轻量 CI
  必须全绿，并按现有选包核对其中测试非零执行，不以轻量 CI 代替 TUI 证据。
- 最终差异不实质性修改 `multidev/` 或既有 Multi 文档语义；Multi 的冻结状态、全量基线和 `multi-v0.1.1` 保持有效。

## 2. 范围

### 允许修改

- `mydev/codex-rs/tui/src/status/` 内 Local `/status` 的实现、相邻测试和必要快照；可按职责选择在既有文件中窄改或
  增加同模块专用文件。
- 根 `doc/rondo-config.md` 的 Local 增量章节，以及根 `README.md` 中与配置说明直接相关的概述和入口。
- 本 ExecPlan 的当前状态、必要的精炼 `agent_log/`，以及任务达到相应阶段后受影响的 `doc/WBS.md` 和
  `doc/WBS-COMPLETED.md`。
- 为上述改动直接需要的窄幅测试修订、注释、链接或文档结构调整。

### 不允许修改

- `multidev/` 下任何代码、功能、测试、配置或快照；根文档中既有 Multi 行为、资格与发布语义也不得实质改变。
- Guardian、本地推理、审批或 provider 的运行能力、配置字段、解析优先级、默认 reviewer、feature gate 或默认值。
- 上游继承的两棵产品树 `docs/`、`codex-rs/config.md`，以及 `codex-source-code/`、`reference-agent-harness/`。
- 根轻量 CI 的 crate 范围和 workflow；尤其不得把整个 `codex-tui` 加入 CI。
- Cargo 依赖、lockfile、配置 schema、评测/训练设施或发布产物，除非执行中发现完成既定目标所必需的真实缺口并先获
  用户批准扩围。
- 空间盘点或清理、删除、最终全 workspace 测试、Local 冻结、版本号、tag、Release 或任何发布动作。

### 不允许读取/查看

- `.env.local` 内容、任何凭据/API Key、私有模型权重、私有测评数据或项目范围外个人文件。
- 其他 worktree 的未提交内容；已提交的 Plan 104 / 106 历史与 Multi 实现只可作为只读参考，不可在原工作树继续开发。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **状态语义来自有效配置。** `/status` 必须基于 Local 当前有效 `Config` 中实际加载的 model、provider、reasoning
   effort、evidence directory 四类显式 Guardian override；无 override 不增加行，部分 override 只报告实际存在项，
   不补写默认值或推测值，也不把 `policy` 长文本放入摘要。
2. **配置不等于运行事实。** 显式 Guardian model override 是最高优先级的 review model slug；界面保持保守措辞，
   是因为它不知道 review 是否发生、请求是否到达 provider，而不是因为该显式值会被 catalog 或默认值覆盖。
3. **文档必须先核实再列字段。** Local 专属字段和入口不得从历史计划或 Multi 机械推定；须对照当前 Local 配置类型、
   加载/运行代码、受跟踪示例和现行 WBS 后再记录。`config.toml`、根 `rondo.local.example.toml` 所代表的
   project-local 机器/测评配置，以及密钥环境示例若属于不同生命周期，必须明确区分，不得写成同一配置面。
4. **能力边界不升级。** 文档可说明已有配置和工程接缝，但不得由“可配置”推导“可运行”，不得由窄模型/运行合同的
   历史资格推导真实审批用途已获采用，更不得改变方向 2“保留为实验、未采用”的最终结论。
5. **只补 Local 增量。** 公共 Guardian 与已冻结 Multi 章节只允许为加入 Local 入口所必需的非语义性衔接；不得借本任务
   重写 Multi、修正 Multi 实现或扩展其他方向。若发现 Multi 问题，只在交付中记录并留待另行立项。
6. **使用唯一 Local target。** 格式检查使用受跟踪的 Local `just` 入口；所有本地重型 Cargo lint、构建和测试必须经
   根共享锁/资源看门狗的既有 `just` 入口，继续使用物理仓库根下唯一的 `.codex/cargo-target/rondo-local`。不得覆盖
   `CARGO_TARGET_DIR`，不得在工作树、`mydev/codex-rs/target` 或其他位置新建第二套 target，也不得提高并发。
   最终全 workspace 测试不属于本任务。
7. **快照与非零测试必须可核对。** UI 改动必须有相称的 `insta` 覆盖；接受前阅读实际 snapshot diff，确认无 override
   的既有状态稳定，并检查无待接受快照。退出码成功但过滤到零测试、全部 skip 或仅完成编译不能算通过。根轻量 CI
   不包含整个 `codex-tui`，因此 Local TUI 正确性必须由本地相关测试证明；推送后 CI 只验收既有 Local 轻量选包。
8. **允许任务内迭代。** 执行者可自主定位并修复范围内普通的编译、测试、快照、代理环境或瞬时 CI 问题并合理重跑，
   不因一次可窄修问题停止；不得以弱化测试、断言、安全边界或文档事实口径换取绿色。必须越界、使用未授权外部资源或
   执行不可逆操作时才暂停请示。
9. **Git 授权门分开。** 实现、验证和提交只在本专用工作树进行，保护主工作区与其他 worktree。执行者完成后只提交
   工作树分支并交给计划制定者审查；未经用户后续明确批准，不得合并 `main`、推送、打 tag 或发布。审查整改仍在同一
   工作树完成并提交；合并和每次推送均服从用户授权。
10. **外部与资源边界。** 本任务不读取 `.env.local` 内容或任何真实密钥，不调用真实 API，不加载真实本地模型，
    不运行 Docker、训练、测评或付费操作，不清理任何空间，也不修改宿主机或项目外状态。普通只读源码核查和已授权的
    项目内定向验证除外。根 `rondo.local.toml` 按仓库规则只含可读的非密钥机器参数，本任务文档不依赖其本机取值；
    若普通诊断确有必要可读取，但不得把本机值复制进受跟踪文档或日志。
11. **记录职责清楚。** WBS 只维护当前阶段与下一工作包，WBS-COMPLETED 只在形成相应完成事实后记录成果，Plan 动态段
    只保存恢复任务所需状态，`agent_log/` 只记实质修改、疑难点和验证结果；不得在多处复制执行历史或下游路线。

## 4. 软性建议

以下内容用于根据现有代码给出的执行建议，但不是固定约束，也不代表代码变化之后的精准效果预测。AI 可以依据代码、
实际测试和运行结果采用更优方案。

- 可把 Plan 104 的 Multi `/status` 三态措辞、摘要上限和测试思路作为参考，但应以 Local 当前代码为准。若 Local 模块结构
  仍与 Multi 相近，复用同样的小型 helper 可能最清楚；若已有更合适的本地抽象，可采用更契合现状的实现。
- 优先复用既有 `FieldFormatter`、目录显示、`test_config` 和状态快照设施。三态可以由聚焦断言与少量代表性快照组合
  覆盖；不必为一行摘要建立新的通用面板、状态框架或审计设施。
- 写 Local 配置章节前，可从当前解析/调用点反向核对受跟踪示例中每组配置的所有者、消费者和运行前提，再决定章节
  结构。适合用短示例、表格和明确链接表达的内容无需展开成操作手册；历史研究细节链接权威结论即可。
- 验证范围按实际差异决定，通常包括 Local Rust 格式检查、`codex-tui` 的相关状态测试或相称包级测试、snapshot pending
  检查、文档链接/措辞自检和 `git diff --check`。若真实相邻影响需要更宽的定向门禁，可以增加，但不要自动扩大为最终
  全 workspace 测试。
- 对耗时测试先保留已通过的有效进度，从未打通处边修边跑；代码与快照稳定后，再在最终差异上完成一轮相称的定向门禁。
- 设计上优先复用职责契合的现有设施；若强行复用会造成耦合或语义扭曲，可以增加任务所需的专用小能力，但应继续遵循
  现有配置、生命周期、错误、测试和观测习惯，不重复建设第二套体系。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根与 `mydev/` 开发规则、计划模板、当前 WBS、Plan 104 / 106 相关合同与验收记录、根配置指南、README、
  Local/Multi `/status` 差异、受跟踪配置示例及相关 Local 历史结论。
- 已确认规划基线 `main == origin/main == 58ed2f03`，主工作区干净；Plan 106 的旧 worktree 保持挂载且未被使用。
- 已从该基线建立专用工作树 `.claude/worktrees/110-local-product-support` 和分支
  `worktree-110-local-product-support`。
- ExecPlan 初稿已完成一次独立只读审查；格式/构建入口、非密钥本机配置读取边界以及本地 TUI 与轻量 CI 的证据职责
  已按当前仓库事实修正，无遗留阻断项。
- 已冻结本 ExecPlan。规划阶段没有改产品代码或持续规划文档，没有运行构建/测试，也没有读取 ignored 配置。
- L-1 已完成：新增 `mydev/codex-rs/tui/src/status/guardian.rs`，`card.rs` 四处窄改动，
  `status/tests.rs` 增加三态断言与一份代表性快照，`permissions_text_for` 提成 `status_field_text_for`。
- L-2 已完成：`doc/rondo-config.md` 新增 §3 Local 节（原 §3 顺延为 §4），§1.4 改为两条线通用，
  README 配置入口同步为三节结构。章节事实以 `codex-source-code/` 上游只读快照逐文件核实。
- 验证已完成：`just fmt` 无改动产出；`just test -p codex-tui status::` 最终 60 tests run / 60 passed /
  0 failed，非零执行成立。新快照逐行阅读后按单文件精确接受，其余 20 份既有 status 快照零漂移，
  全仓库无遗留 `*.snap.new`。构建经根共享锁与看门狗，复用唯一 `.codex/cargo-target/rondo-local`。
- WBS、WBS-COMPLETED 与实施日志 `agent_log/2026-09-03-plan107-local-product-support.md` 已按职责同步。

### 当前工作

- 审查发现一（文档）已整改：开头的配置层绝对表述收窄为"只有一处例外"，写明 RONDO 新增的
  `auto_review.model_provider` 项目层剥离与实际告警文案；§3.2 示例块标注必须写在用户级
  `~/.codex/config.toml`，并把该前提列为四条运行前提之首。仅改 `doc/rondo-config.md` 与实施日志，
  Rust、快照与测试代码零改动。轻量复核：`just fmt-check` 退出 0、`git diff --check` 干净、无 `*.snap.new`。
- 审查发现二（自产 target）已闭合：用户对 `mydev/codex-rs/target/` 这一精确路径单独授权后执行删除。
  删除前复核非符号链接、内容仅 `.rustc_info.json`（1718 B）与空 `nextest/local/`；只对该完整字面路径操作。
  删除后该路径不存在，`.codex/cargo-target/rondo-local` 前后同为 `31,499,597,846` bytes 且仍存在，
  工作树内再无其他 `target` 目录。

### 本任务剩余步骤

- 由计划制定者窄复验整改提交，确认文档、范围、快照与意外产物问题闭合。
- 审查通过后等待用户明确批准合并与推送；获批后完成主线合入、推送与 Local 轻量 CI 终验，再据实关闭任务。

### 阻塞项

- 无技术阻塞；两项审查发现均已闭合。
- 合并和推送尚未授权，属于整改复验完成后的预定用户门。

### 当前验收状态

- `IMPLEMENTED / TARGETED_GATE_PASS / REVIEW_FINDINGS_REMEDIATED / RE_REVIEW_PENDING /
  MERGE_PUSH_NOT_AUTHORIZED`。

### 交付中记录、留待另行立项的事项

- 首次独立审查裁决：`[auto_review].model_provider` 的 project-local 限制直接影响新 Local provider 示例，
  必须在本任务窄修；`check_for_update_on_startup` 默认改 `false` 的公共说明继续延期，不阻断本任务。
- 首次独立审查报告：`agent_log/2026-09-03-plan107-independent-review.md`。

### 交接边界

- Plan 107 完成后冻结本计划；下游工作只链接 `doc/WBS.md` 的当前条目，不在本计划展开或提前执行。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 用一个 ExecPlan 共同交付 L-1 / L-2，任务内顺序由执行者决定 | 两项共同构成 Local 全量测试前的配套收口，彼此无必须固定的技术顺序 | 本任务 | 已采纳 |
| 002 | Local 配置字段不在规划阶段预先穷举，由执行者按当前源码和受跟踪示例核实 | 避免把历史设施、上游字段或不同生命周期配置误写成当前产品用户接口 | 配置指南 | 已采纳 |
| 003 | `/status` 与 Multi 保持同一用户语义，但 Local 实现按自身代码结构决定 | 复用已验收语义，同时避免机械复制或反向触碰冻结 Multi | Local TUI | 已采纳 |
| 004 | 配置、工程接缝和用途资格分层表述，保留“本地审批模型保留为实验、未采用” | 防止从配置可达性或历史窄证据外推产品资格 | 文档、README | 已采纳 |
| 005 | 执行者只提交工作树，计划制定者独立审查；合并和推送另等用户批准 | 遵守本次指定的审查与 Git 授权流程，同时保留推送后 CI 作为任务终验 | Git、审查、CI | 已采纳 |
| 006 | 本任务没有必须直接在主工作区完成的 git-ignored 交付；构建只复用根唯一 Local target | 全部交付文件受跟踪，不需修改 ignored 配置且 `.env.local` 内容不得读取；共享 target 是既有构建设施而非任务交付物 | 工作树、构建 | 已采纳 |
