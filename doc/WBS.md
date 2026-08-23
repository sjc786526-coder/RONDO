# RONDO 长程规划（WBS）

最后更新：2026-08-23（Plan 058 正在独立 worktree 推进 C2；Plan 054 / M3-A2 已主线整合，Plan 059 / M3-B1a 正在执行数据 revision v3）

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
| 1：Harness 优化 | **Plan 058 正在独立 worktree 推进 C2** | 正式 campaign 的冻结身份、账本、资产与最终结论仍由 Plan 058 独立负责，尚未主线整合 |
| 2：本地审批模型 | **已收口，今后不再开启** | 最终结论为“保留为实验”；不改生产默认，不再规划后续工作包 |
| 3：RONDO Multi | 第一、二期及其收口案例、**三期 M3-A1、M3-A2、M3-B2a、M3-B2b 已完成** | Plan 059 / M3-B1a 的 v2 candidate-length shortcut 已判定数据 NO-GO；revision v3 rehearsal 已通过，正式冻结待执行；M3-B1b 尚未解锁 |

### 方向命名口径

- 后续规划、任务与汇报统一使用“方向 1”和“方向 3”，不再使用“Local 方向”指代方向 1。
- `mydev/` 是方向 1 当前产品源码位置；`multidev/` 是方向 3 产品源码位置。目录名称不等于方向名称。
- `RONDO Local` / `rondo-local` 仅在必须区分现有产品或运行身份时使用，不代表方向 2。方向 2 专指已经收口的
  本地审批模型研究。

最近一次有记录的 `v0.147.0` RONDO 全 workspace 实际执行为 14,092 项：14,060 通过、31 失败、
1 超时，Nextest 另列 23 项 ignored。此后未重跑全 workspace，因此这只是历史测试快照，不代表当前全绿，
也不代表旧失败已在当前提交复现。

## 2. 下一工作包与顺序

方向 1 与方向 3 是两套产品源码上的独立推进面，不互为默认前置。

### 方向 1：C2 候选交接

Plan 056 已完成。首个可信正式 campaign `formal-v6` 使用 v28 同一冻结 10 题、两个完整 round 和固定
Terra medium/low 条件形成有效 20/20；20 个 slot 均有完整 API usage、原生 trace 投影、Terminal-Bench 终态和
Docker receipt，8 pass/12 fail。formal-v6 为 219 attempts、`4.677962 USD`；连同 v1、三次 rehearsal 和
formal-v5，Plan 056 累计 483 attempts、`10.329028 USD`，reservation 0，随后停止付费运行。

冻结门槛只选出 **C2**：9 次 occurrence，影响 6 个 slot/4 个任务，其中 3 个失败 slot，两轮均观察到，影响值
10108；C1 和 C11 未达门槛，C7 继续不可测。公共 body-free 结果见
`eval/results/observations/plan056-direction1-bounded-observation-formal-v6-2026-08-22.json`，详细历史和验收证据见
`doc/WBS-COMPLETED.md` 与 `plan/056-direction1-bounded-observation-execplan.md`。

方向 1 当前由 Plan 058 在独立 worktree 推进 C2 行为优化与正式 campaign；其冻结身份、预算/账本、运行资产、结算、资源释放和最终结论
以 Plan 058 自身合同与后续主线整合为准。本页不根据并行工作树的中间状态预写结果，也不授权其他任务读取、修改或清理其现场。

### 方向 3：Publication Critic 三期

- M3-A1 产品合同、M3-B2a / Plan 055 本地 Critic 服务与 M3-B2b / Plan 057 发布流程接入均已完成并进入主线。三期分为
  `M3-A2 → M3-B1a → M3-B1b → M3-B1c` 数据/训练链与 `M3-B2a → M3-B2b` 产品链，两链在
  `M3-C1 → M3-C2` 汇合，最后由 M3-D 收口。
- M3-A2 / Plan 054 已完成并进入主线。M3-B1a / Plan 059 的 v1 因跨 split 固定文本 shortcut 判定数据 NO-GO；revision v2
  又在最终干净审查中发现 6 个 scope Q- 是唯一超过 80 candidate tokens 的样本，形成跨 split 完美长度捷径，故同样判定数据 NO-GO。
  revision v3 已让 scope Q+/Q- 长度交错，并新增 exact-token at-most/at-least threshold 门禁；rehearsal 全链路通过，正式生成、复核与冻结待执行。
  M3-B1b 未解锁，不能提前启动。
- Plan 059 的当前授权只覆盖其轻量数据工作，不授权训练、完整模型、项目真实 API、Docker 或启用真实 Critic；每个后续包仍须按自身范围取得授权。

方向 1 与方向 3 的只读研究、轻量代码和数据工作可以并行；本地重型 Cargo、Docker、真实本地模型加载/推理继续
全局串行，并由实际进入实施的工作包协调共享资源。

- 方向 0 的设施保持可用，但不自行创建新 campaign；任何真实 API、Docker 或新预算均需针对新任务重新授权。
- 方向 2 永久收口，不作为方向 1 或方向 3 的前置、旁支或待恢复项目。
- 上游 Codex 基线升级继续保留为独立、不排期任务；只有用户明确启动时才进入规划。

## 3. 方向关系

- 方向 1 在 `mydev/` 推进 Harness 优化；方向 3 在 `multidev/` 推进多智能体与 Publication Critic，不互相夹带实现。
- 方向 0 是可复用设施，不再作为解锁其他方向的总闸门；只在具体任务需要时提供相称测评。
- 方向 2 已永久收口，不参与后续路线，也不阻塞其他方向。
- 所有方向只共享排期、API 预算、Docker、构建和本地模型等全局资源约束，重型操作保持串行。

## 4. 仓库与产品线结构

### 4.1 布局

```text
RONDO/
├── mydev/        # 方向 1 当前产品源码（目录名沿用现状）
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

- `doc/WBS/eval-benchmark.md` —— 方向 0：现行测评设施与方向 1 观测投影边界
- `doc/WBS/teacher-harness-study.md` —— 方向 1：Plan 052/056 观测结论与 C2 下一边界
- `doc/WBS/local-approval-model.md` —— 方向 2：已永久收口
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：现行产品语义与三期 Publication Critic 长程路线
