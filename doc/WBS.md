# RONDO 长程规划（WBS）

最后更新：2026-08-25（Plan 072 共享重型任务启动前冲突观察门已完成并通过独立验收）

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段指针、跨方向关系、
稳定工程边界和授权门；已完成成果与验收见 `doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，执行细节见
`agent_log/`，研究与审计材料只代表其形成时点。

## 1. 当前状态

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。上游升级仍是未排期待办，启动时再冻结目标版本，
不得混入普通功能任务。

项目包含两套并列产品源码：`mydev/` 与 `multidev/`。当前方向状态如下：

| 方向 | 当前状态 | 当前规划边界 |
|---|---|---|
| 0：量化测评基准 | 既有设施与首次 schema v7 正式 canary 已完成，当前无 active campaign | 保留设施；历史结果见 COMPLETED，新 campaign 须重新立项与授权 |
| 1：Harness 优化 | **正式收口；当前无 active 工作包** | 当前不继续新增观测或内核/热路径优化；既有实现、设施与历史结果保留。未来可由用户另行决定是否重新立项，本次收口不作永久禁止 |
| 2：本地审批模型 | **已收口，今后不再开启** | 最终结论为“保留为实验”；不改生产默认，不再规划后续工作包 |
| 3：RONDO Multi | 第一、二期及其收口案例、**三期 M3-A1、M3-A2、M3-B1a、M3-B1b、M3-B1c、M3-B2a、M3-B2b、M3-C1、Plan 064 与四期 M4-A、M4-C0 已完成** | M3-C1 结论为 base/C2 `NOT_QUALIFIED`、C1/C3 `QUALIFIED`；因 base 对照未通过同口径资格，M3-C2 前置为 false，三期下一包须先修正并重验 base 本地部署可比性，不得直接启动 M3-C2。RunPod 已为 0 Pod/0 volume、持续费用为 0；M4-C0 结论为 `M4_C0_PROTOTYPE_PASS`，正式 Session query 等待 M4-S1，正式 control/TUI 再等待 M4-S2 |

### 方向命名口径

- 后续规划、任务与汇报统一使用“方向 1”和“方向 3”，不再使用“Local 方向”指代方向 1。
- `mydev/` 是方向 1 当前产品源码位置；`multidev/` 是方向 3 产品源码位置。目录名称不等于方向名称。
- `RONDO Local` / `rondo-local` 仅在必须区分现有产品或运行身份时使用，不代表方向 2。方向 2 专指已经收口的
  本地审批模型研究。

最近一次有记录的 `v0.147.0` RONDO 全 workspace 实际执行来自 Plan 070：14,380 项中 14,364 通过、
16 失败，Nextest 另列 24 项 skipped；其中 1 项通过发生在自动重试。16 项均被该任务验收判定为其写集外失败。
此后未在当前合并提交重跑全 workspace，因此这只是历史测试快照，不代表当前全绿，也不代表旧失败已在当前提交复现。

## 2. 下一工作包与顺序

方向 3 是当前唯一已经明确下一工作包的产品推进面。方向 1 已正式收口，不作为方向 3 的前置或旁支。

### 方向 3：Publication Critic 三期

- M3-A1 产品合同、M3-B2a / Plan 055 本地 Critic 服务与 M3-B2b / Plan 057 发布流程接入均已完成并进入主线。Plan 060 训练资格
  `TECHNICAL_GO`、冻结 v8 `DATA_GO` 与 Plan 066 正式训练授权已经同时成立；M3-B1c 已完成正式训练、候选保存、恢复验证、计算终态与
  独立验收。产品链与模型链在
  `M3-C1 → M3-C2` 汇合，最后由 M3-D 收口。
- M3-A2 / Plan 054 与 M3-B1a / Plan 059 均已完成并进入主线。Plan 059 revision v7 冻结 72 candidate、30 Boundary 与
  6 Within-PASS，三 split 为 42/16/14；独立最终验收确认输入隔离、group/split、review、50,073-token census、manifest、
  factory-only consumer 与 train-only smoke bundle 闭环，`remaining_findings=[]`，数据结论 GO。详细历史见
  `doc/WBS-COMPLETED.md` 与 Plan 059 最终验收日志。
- Plan 064 已独立验收完成并冻结 `publication-critic-v8`：228 candidate、104 pair、三 split 为 128/55/45，训练 consumer 默认
  只暴露 train。覆盖、质量与消费合同通过；冻结时的预算适配证据不足已由 Plan 060 正式吞吐、费用和 23 USD 连续总账的有界复核闭合，
  当前结论为 `DATA_GO`。v7 与 Plan 060 smoke 输入保持不变，Plan 066 只消费 v8 train，validation 不进梯度，unseen-test 默认封存。
- M3-B1b / Plan 060 已在 Secure 单卡 H100 PCIe 80GB 上完成 BF16 全参数 FlashAdamW commissioning 与 final-19
  干净 formal start/resume，C1→C2→C3、完整 checkpoint、新进程恢复和继续更新均形成有效证据；独立代码/archive 复核
  `remaining_findings=[]`，最终验收通过，结论为 `TECHNICAL_GO`。Plan 060 与 Plan 066 从原 Plan 060 基线连续计入 23 USD 总账；
  Plan 066 已统一收口计算资源终态；final-01 terminal receipt 因延迟追账 superseded，final-02 保留生成时的控制台费用快照，最终费用口径见下项。
- M3-B1c / Plan 066 已在当前唯一 H100 PCIe 80GB 上从 exact base 干净执行 C1→C2→C3，实际消费 128 Binary、50 Boundary 与 8
  Within-PASS，保存并复验三个阶段候选、固定 validation 与完整恢复点，新进程 step 3→4 继续更新通过。计算 Pod 已永久删除；Plan 068
  随后把 formal checkpoint、三个候选、exact 模型与必要环境安全交接到本地并删除 winner 卷。独立验收按用户指定冻结终审最新 provider 快照总费用 `$10.9647715263`，距 `$23`
  硬上限 `$12.0352284737`；correctness/functionality `remaining_findings=[]`，结论为 `GO`。该训练结论解除 M3-C1 前置，
  但本身不授予模型质量、threshold、部署或产品资格；资格已由 Plan 068 独立判断，见下项。
- M3-C1 / Plan 068 已完成本地工件交接、真实 scorer/service 接入、四对象正式资格运行、独立验收与远端止费。正式 v3 结论为
  base `NOT_QUALIFIED`、C1 `QUALIFIED`、C2 `NOT_QUALIFIED`、C3 `QUALIFIED`：base 未过 projected drift 与临时 verdict parity，
  C2 未过 ranking/direction，C1/C3 的 runner/service 一致性、稳定性和有界资源门通过；unseen-test 未用于适配或选择。
  本地保留 120/120 个必要对象与正式 checkpoint；RunPod exact winner 卷已删除，当前 0 Pod、0 volume、持续费用为 0。
- Plan 068 的技术实现与任务流程验收通过，但约定要求 base 对照和至少一个训练候选同口径可比，因此
  `m3_c2_prerequisite_satisfied=false`。三期下一包应先在不改冻结权重、数据、产品语义或最终 threshold 的前提下，修正并重验
  base 本地部署可比性；具体路线另建 ExecPlan。该包的本地重型步骤继续复用 canonical shared wrapper：wrapper 在取得 flock 后、
  payload 前会对既存 populated RONDO heavy scope 或不可可靠观察的 scope 事实 fail-closed，无需另建人工观察门或第二套互斥设施。
  M3-C2 与 M3-D 均未启动，也未获实施授权。

### 方向 3：Durable Team Runtime 四期

- 四期必成主线是 Team Session 跨进程持久化/恢复及其 app-server v2 / TUI 控制面；Writer Workspace Binding 降为可选增强，
  只绑定调用者已准备且授权的 worktree，价值门证明需要时才附加 minimal handoff，不建设 workspace registry、ChangeSet
  生命周期或 Git 资产平台。
- 四期详细 WBS 见 [`doc/WBS/durable-team-runtime.md`](WBS/durable-team-runtime.md)。Plan 067 已完成共同合同并经独立验收接受
  `M4_A_GO`；Plan 070 / M4-C0 已完成默认关闭的 experimental app-server v2→client→TUI 纵向原型并取得
  `M4_C0_PROTOTYPE_PASS`。原型只提供正式拆包输入，不冒充 S1 durable read model 或正式公共控制面；正式 Session query 等待
  M4-S1，正式 control/TUI 再等待 M4-S2。M4-W0 仍是独立价值原型，正式 W 实现须先获得 binding GO。
- 四期不依赖 Publication Critic 训练、真实模型、真实 API 或性能测评，可以与三期模型链并行；它保持 shared workspace
  为默认，不建设通用 scheduler、自动路由、自动 merge/push、第二套 Team State/trace 或审计/可信平台。
- 三期未来另行授权的云计算不占本地 Cargo build lock，可与四期有界并行开发；bundle/checkpoint/结果传输仍竞争本地网络与磁盘，
  四期重型 Cargo 与三期本地模型、Docker 等重型任务按根 `AGENTS.md` 串行错峰。详细资源关系见四期子 WBS。

如果未来重新启动方向 1，它仍与方向 3 保持产品源码和任务合同独立；本地重型 Cargo、Docker、真实本地模型
加载/推理继续全局串行，并由实际进入实施的工作包协调共享资源。

- 方向 0 的设施保持可用，但不自行创建新 campaign；任何真实 API、Docker 或新预算均需针对新任务重新授权。
- 方向 1 当前正式收口，不排期观测或内核/Harness 优化；未来是否重新启动由用户另行决定。
- 方向 2 永久收口，不作为方向 1 或方向 3 的前置、旁支或待恢复项目。
- 上游 Codex 基线升级继续保留为独立、不排期任务；只有用户明确启动时才进入规划。

## 3. 方向关系

- 方向 1 的既有产品源码位于 `mydev/`，当前正式收口；方向 3 在 `multidev/` 推进多智能体与 Publication Critic。
  如果方向 1 未来重新启动，两者仍不互相夹带实现。
- 方向 0 是可复用设施，不再作为解锁其他方向的总闸门；只在具体任务需要时提供相称测评。
- 方向 2 已永久收口，不参与后续路线，也不阻塞其他方向。
- 所有方向只共享排期、API 预算、Docker、构建和本地模型等全局资源约束，重型操作保持串行。

## 4. 仓库与产品线结构

### 4.1 布局

```text
RONDO/
├── mydev/        # 方向 1 产品源码（当前收口，目录名沿用现状）
├── multidev/     # 方向 3 产品源码
├── eval/         # 两套产品可复用的通用测评设施
├── scripts/      # 共享构建锁与资源看门狗入口
├── eval-data/    # 本地重资产与私有运行数据，内部按产品分命名空间
├── test-data/    # 历史测试结果和数据
├── training/     # 轻量、受跟踪的训练合同与门限内数据集
├── doc/
└── plan/
```

### 4.2 产品与分支边界

- 两套产品地位相同，但核心源码独立；公共修复和外围设施按需复用，不追求提交级长期同步。
- 单仓库、单长期 `main`；不为方向 3 维护永久产品分支。具体开发任务仍按 `AGENTS.md` 使用短期 worktree，
  除非用户明确要求直接在主工作区工作。
- 方向 1 任务原则上修改 `mydev/` 及必要共享文件；方向 3 任务原则上修改 `multidev/` 及必要共享文件。
- `eval/`、WBS 和其他共享权威文件尽量在同一时段由一个任务负责，避免并行任务互相覆盖。

### 4.3 磁盘与重型资源

- 重型 Cargo 构建与测试必须经仓库根共享 `scripts/with-build-lock.sh` 或已接入它的 `just` 配方；
  `CARGO_TARGET_DIR` 必须位于项目根内并受看门狗监督。
- canonical wrapper 在取得 flock 后、任何 payload 启动前枚举当前用户的 canonical RONDO heavy scope，并以 cgroup
  `populated` 事实判定冲突；仍 populated 或事实不可可靠取得时稳定拒绝，不等待、不清理、不接管旧 scope。历史 inactive/failed
  unit 只有在无 ControlGroup、明确 unpopulated，或 cgroup 已消失且终态复读一致时才放行。
- 两套产品的重型构建、Docker、真实本地模型加载/推理全局串行；同一时刻只保留一个产品的热 target。
- 具体磁盘、Windows `C:`、内存、swap、Docker 增量和 fail-closed 阈值以根 `AGENTS.md` 为准，不使用 WSL
  虚拟容量代替宿主容量。

### 4.4 共享外围设施

两套产品可复用构建锁与看门狗、Docker/Terminal-Bench runner、API 预算与结算、BinaryManifest、结果归档、
本地模型外围运行设施以及 fake/loopback/replay 测试，但不因此共享核心产品语义。

### 4.5 产品身份与历史资产

- `product`（`rondo-local` / `rondo-multi`）表示既有运行产品身份，`side`（`rondo` / `codex`）表示比较侧；
  两者正交，且都不替代方向 1/2/3 的规划名称。
- 方向 3 身份必须贯通源码、构建、冻结 binary、manifest、adapter/RunSpec 与结果归档；唯一布局映射为
  `eval/rondo_eval/contracts.py` 的 `product_layout()`。
- 历史结果、receipt、trace、冻结 plan 和审计材料保持原身份，只作为历史证据，不回填新字段、不冒充新任务基线。
- crate 名与二进制名沿用上游（`codex-cli` / `codex`），便于与 `codex-source-code/` 直接比较。
- 数据资产边界见 `doc/eval-data-layout.md`。

## 5. 持续工程约束

- 测试用于正确性保障，随有效代码维护，只跑受影响模块所需门禁；较大阶段收口时再运行相称的扩大门禁。
- 测评用于量化性能与行为，默认关闭、轻量、自动记录归档；fake、离线、真实 API、真实模型与 Docker 证据严格区分。
- 冻结 Codex 与 RONDO 的公平比较只使用同口径外部指标；内部探针只用于同一产品自身诊断。
- skip、未运行、无效比较和基础设施失败不得表述为通过，也不得为凑绿弱化测试、安全或审批逻辑。

## 6. 授权门

以下动作每次执行前都需要针对具体任务单独授权，历史授权不自动延续：

- Docker 拉取、构建或运行；
- 按量付费真实 API 批量测评，包括任务、轮数、模型与预算上限；
- 真实本地模型加载或推理；
- 真实数据外发，包括上传项目生成的数据；
- 云 GPU 训练、上传或下载权重及其他会产生费用或外部状态的操作；
- 上游基线升级。

普通依赖下载、源码查询和只读网络访问可随已授权任务执行。具体资源阈值、密钥边界和操作纪律以根
`AGENTS.md` 为准。

## 7. 子 WBS 索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：现行测评设施与新任务授权边界
- `doc/WBS/teacher-harness-study.md` —— 方向 1：正式收口状态与历史归档入口
- `doc/WBS/local-approval-model.md` —— 方向 2：已永久收口
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：现行产品语义与三期 Publication Critic 长程路线
- `doc/WBS/durable-team-runtime.md` —— 方向 3 四期：Durable Team Session、Session 控制面与可选 Writer Workspace Binding/Minimal Handoff
