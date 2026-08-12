# 方向 0：量化测评基准

最后更新：2026-08-11 ｜ 依赖：P0（S1/S2）｜ 当前 Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 目标

为 RONDO 建立可重复、可归档、可出曲线的性能判据，使后续优化"有效与否"有据可依，并保证与冻结 codex 的对比公平。

两条子轨：

- **E-A 轻量离线冻结回放**：测行为保持型优化（运行时、数据结构、工具执行）与故障注入，成本近零，可高频跑。建设原则是**轻量化，合理复用现有测试/诊断/测评设施**，不大规模另起炉灶。
- **E-B 真实 API + Terminal-Bench 2.1**：测行为改变型优化，是最终可信指标，成本高、低频跑。

按已定排序，**E-B 的最小真实链路先行**，它同时产出 E-A 需要的高保真录制素材和方向 2 需要的证据包模板。

## P1 当前状态

- **B1 完成**：Harbor 固定为 `0.20.0`，TB 2.1 数据集固定为 commit
  `ffccbe05ee73a9d59518217f294ad711bda39304`；`terminal-bench/fix-git` 的 task archive 和
  `linux/amd64` 镜像均以 SHA-256 锁定。受监督 Docker 下官方 hello-world oracle 为
  `completed`/reward 1.0。受跟踪 lock 绑定 `uv.lock`、Harbor 版本、console/interpreter 和三个关键模块；
  不再遍历 site-packages 或维护传递依赖文件闭包。
- **B2 完成**：统一 runner、双 adapter 与 Docker/watchdog 监督保持。no-API 不再使用
  permanent pair ledger、retirement、失败摘要恢复或一次性 migration；失败可在修复后由用户重新启动。
  canonical `just eval-b2-no-api` 在一个进程中按 RONDO→Codex 严格串行，首侧失败立即停止。成功时只替换
  `eval-data/b2/current.json`，其中 Docker 字段直接来自 supervisor 的唯一 receipt。
  adapter 仍要求 bundle 目录 root-owned、三个固定文件为 agent UID/GID 1000 且 mode 0555、
  精确 `/app/personal-site` Git probe、
  custom seccomp、`cap_drop=ALL`、private cgroup、容器 metrics、VHDX 与 cleanup；marker 还必须来自
  冻结 code-mode 两项 structured output 的第二项，且其中投影后的 `exit_code=0`、stdout 精确等于固定值。
  Plan 009 在 commit `b47a7b4` 上以已存在的 pinned image 严格串行运行 RONDO→Codex：两侧均
  completed，各 2 次 fake 请求、tool round-trip 成功、cleanup verified empty；官方 API 0 次、
  费用 0 USD。`reward=0` 是 no-API marker 诊断不解真实 task 的预期结果，不冒充 B3 成绩。
- **B3/M1 完成**：Plan 014 v19 冻结唯一 pair/batch/run IDs、Sol/medium main、Sol/low Guardian、source-bound
  frozen Codex catalog、价卡/retry、profile/endpoint SHA 与 20 USD pair cap。fresh exact-wire canary 4/4 请求
  attempt 1、usage valid 后，正式运行严格按 RONDO→frozen Codex 串行完成同一 `fix-git` task：RONDO 17/17、
  Codex 18/18 upstream request 均 attempt 1、usage-priced，双侧 `completed`/reward 1、reservation 0。
  RONDO 两份自然 Guardian `E_final/meta` 均 Sol/low、approved；不可改写的 v19 public record 只证明
  task-scoped request/evidence count match，后续新记录才要求 canonical digest 一一绑定后标为 verified。
  durable public result、pair lock、sequence ledger、profile/endpoint 和 container metrics 经既有 `assess_m1`
  得到 `m1=passed`、`reasons=[]`、`s2=task_scoped_count_match`。v19 正式费用 `$0.870787`；Plan 014 含历史 canary/失败终态
  的累计本地估算 `$6.988825 < $280`，全部 reservation settled，`actual_usd=null`。旧失败 pair 均保持不可复用，
  详见 Plan 014 与执行日志。

## E-B 真实 Terminal-Bench 2.1 测评

### B1 环境与接口勘察（规模 S，授权门：Docker）

- 沙箱外验证 Docker Desktop daemon 与镜像拉取可用（`doc/development-environment.md` 第 7 节已确认握手成功，未拉过镜像）。
- 用 uv 安装 TB 2.1 官方 harness，勘察其 agent 适配接口的**实际**形态（版本以安装后为准，不预设）。
- **勘察完立即冻结版本**：把 harness 的精确版本号与依赖锁文件写入仓库（uv lock / 明确 pin），任务镜像记录 digest。"以安装后为准"只适用于第一次勘察，之后基线必须可复现，不能随上游漂移。
- 产出：接口勘察笔记 + 版本冻结记录 + 最小可跑通的官方示例任务一条。

### B2 双侧 agent 适配器（规模 M）

- 把**冻结 codex**（`codex-source-code/` 构建产物）与 **RONDO**（`mydev/`）都接入同一 agent 适配接口。
- **基线二进制的构建方式**：`codex-source-code/` 是纯净只读快照，官方 0.147 `Cargo.lock` 的
  135 个 workspace package 仍写作 `0.0.0`。构建必须复制到隔离 scratch source，只在副本中把这
  135 项机械规范化为 `0.147.0`，并指定项目专用 scratch `CARGO_TARGET_DIR`；不得改写只读快照或
  把 scratch lock 冒充官方文件。基线二进制**构建一次后固化**，记录上游 tag/commit、规范化规则、
  二进制 SHA256 与工具链版本；后续跑批直接复用，不每轮重编。所有重型构建仍走项目看门狗。
- 统一运行条件，写死在适配器里而不是靠人工记忆：
  - 关闭 websocket（provider `supports_websockets = false`）
  - `approvals_reviewer = "auto_review"`
  - `approval_policy = "on-request"`
  - `sandbox_mode = "workspace-write"`（三项合起来才等价于 0.147 的 `--approve-for-me`）
  - Guardian model/effort 由本地 paid profile 选择并由每批 pair lock 冻结（依赖 S1）
  - 相同主模型、reasoning effort、provider profile、价卡与重试策略
- `v0.147.0` 的 Guardian 默认模型会随 provider/auth 改变，所以测评配置和结果元数据必须记录
  **显式** model/effort，不得以当前 API-key 路径恰好默认 Luna 为由省略配置。
- 验收：同一任务两侧各跑一次，运行条件在结果元数据里可核对。

### B3 最小真实链路跑通（规模 S，授权门：小额真实 API）—— **M1**

- 1~2 个任务的端到端，结果落盘归档。
- 同步开启 S2，确认真实审批过程能产出 `E_final`。
- **已完成**：v19 在 `terminal-bench/fix-git` 上完成双侧真实运行，M1 passed、S2 task-scoped count match；后续运行不复用该
  identity，B7 仍需按 B6 单独预算和授权。

### B4 任务分层与冻结清单（规模 S）

- **canary 子集**：10 个任务，要求彼此差异大、覆盖典型能力、单任务成本可控。作为阶段性日常测评。
- **验证集**：其余可见任务，低频使用，用于检查是否过拟合 canary。
- **隐藏集**：预先划出并冻结，**不查看任务内容、失败日志、验证器与单任务结果**，只在重大阶段验收时看总分。
- **隐藏集的实际隔离方法**（光把清单写进仓库不构成隐藏）：
  - 用**确定性哈希划分**决定归属（如 `sha256(task_id)` 落桶），划分过程只读任务 id，不需要查看任务内容。
  - 仓库内只存"分区归属"，不存任务正文、验证器或失败日志。
  - 隐藏集的**单任务结果不写入结果库明细**，只写聚合分数——否则隐藏集会通过结果库慢慢泄漏。
  - 后续每个任务计划的"不允许读取/查看"一节必须显式列出隐藏分区。
- 分层清单一经冻结即写入仓库，改动需记录理由。
- **当前实现**：TB 2.1 pinned 89 个 ID 已按无盐 `sha256(task_id)` 冻结为 10 canary / 61 validation /
  18 holdout；执行 catalog 另绑定 10 个 source/image/workdir/resource/timeout identity。holdout 划分前未读正文，
  B7 不运行 holdout。

### B5 计分与失败归因（规模 M）

- 主指标：Task Resolution Success Rate。
- 归因分类必须区分：主 Agent/Harness 失败、Guardian 正确拒绝导致的失败、Guardian 误拒、基础设施失败（超时/网络/容器）。
- Guardian 对危险或未授权动作的**正确**拒绝计入主 Agent 应承担的失败代价，但在报表中单列，避免掩盖 harness 真实能力变化。
- **当前实现**：纯函数计分器保守拒绝矛盾证据；无独立 adjudication 的 semantic deny 归 `guardian_false_deny`，
  Guardian technical failure 归 infra 并排除分母；holdout producer 只接受整批聚合。

### B6 成本与预算护栏（规模 S）

- 跑批前输出预估：任务数 × 轮数 × 模型 × 预估 token → 成本区间。
- 硬上限：超过预算即中止并保留已完成结果。
- 每次跑批需单独授权。
- **当前实现**：Plan 015 独立 campaign cap 为 400 USD，v6 精确扣除既有 `158.694728 USD` debit；161 个
  一次性 slot 和 18.885 USD 最大合法 request reservation 均预冻结。B6 历史插值与 v19-shape 压力上界可复算，
  预算不足时在下一 request 前停止。

### B7 首次基线（规模 S，授权门：canary 跑批）—— **M2 的一半**

- 按 `doc/WBS.md` §4「M2 的可执行判据」执行：先用同一 RONDO 二进制跑 2 轮 A/A 得出波动带宽 `σ`，再跑 codex 与 RONDO 各 1 轮 A/B，要求跨侧差异任务数 `≤ σ` 且无单向失败模式。
- 基础 10 任务 × 4 轮 = 40 次运行，外加条件触发的定点加跑（每个出现 codex-pass/RONDO-fail 的任务两侧各加 2 轮）。按 B6 出预估并单独授权。
- 不通过则先停下修测评设施，不得先行推进优化。
- **当前状态**：Plan 015 已获累计 400 USD 与串行 Docker 授权；v1—v5 保持只读。v6 只对首跑 infra 做一次
  定点补跑，每轮结束立即检查最多 2 项剩余 infra；同一结构化故障命中 3 个 task 时熔断。四轮比较使用至少
  8 项共同有效 task 的同一分母。代码提交后依次执行 no-API oracle、fresh exact-wire canary、A/A 与
  RONDO→Codex A/B，再按机械条件激活条件加跑。

## E-A 轻量离线冻结回放

### A1 录制器（规模 M）

- 在 HTTP 层录制，不侵入核心代码路径：provider `base_url` 指向本地录制代理。
- 复用 `codex-rs/responses-api-proxy/src/dump.rs` 的 `ExchangeDumper`（已带 authorization 脱敏与序号），按需扩展 SSE 流的完整留存。
- 录制元数据必须标记 Guardian 请求是标准 Responses 还是 Responses Lite。`v0.147.0` 的 Luna
  使用 Lite，policy 和工具声明的 JSON 位置与标准 Responses 不同；request drift 只能在同一
  完整逻辑请求形态或先规范化为统一逻辑 payload 后比较。
- 录制元数据还必须写入上游 baseline tag/commit、Guardian source tag/peeled commit 与有效 policy 内容哈希；
  Guardian两字段取自 `mydev/codex-rs/core/upstream-source-baseline.toml`。
  0.147 的 policy/template 和 approval/retry reason 输入与 0.146.1 不同；同一源码版本也可能使用
  requirements/config/catalog policy，不能在没有两层标记时合并统计。
- 录制可以重、可以慢、低频执行，**不作为基线**，只作素材来源。

### A2 回放服务器（规模 M）

- 读取录制包，按**轮次序号**返回对应 SSE 响应，不做请求体严格匹配。
- 但要计算并报告 **request drift**：本轮实际请求与录制时请求的结构化差异。drift 为零表示这是纯行为保持型改动，回放结论可信；drift 非零要在报告里显式标红，说明该用例已不适用于回放判据。
- 验收：同一录制包连续两次回放，指标波动在阈值内且 drift 为零。

### A3 冻结用例集（规模 S）

- 从 B3/B7 的真实运行中挑选，覆盖：长轨迹、多工具调用、含审批、含压缩/compact、含失败重试。
- 用例集冻结并写入仓库（体积受控，必要时只存规范化后的精简包）。

### A4 探针与指标（规模 M）

- **两类指标必须分开，不能混谈**：
  - **外部指标**（wall time、CPU time、峰值内存、退出码）由 runner/supervisor 在**进程外**统一采集。
    `getrusage(self+children)` 只覆盖宿主 runner/CLI，仍仅作设施诊断。supervisor 已对 exact
    container 读取 cgroup v2 `cpu.stat usage_usec` 与 `memory.peak`，生成
    `container_id/cpu_usage_seconds/peak_memory_bytes`，并作为 paid publication/pair/M1 的强制机器
    门禁。Plan 009 已在双侧真实 no-API Docker 中采集 container CPU/峰值内存，并核对
    pinned image、VHDX、custom seccomp 与 cleanup；冻结 codex 不加补丁，
    两侧使用完全相同的采集方式。
  - **内部探针**（轮次数、工具调用次数与耗时、序列化耗时、审批往返耗时）只存在于 RONDO 内部，用于 **RONDO 自身版本间**的对比与找瓶颈，**不用于与冻结 codex 横比**。
  - 原先"baseline 同样加载探针"的说法含糊：往冻结 codex 里打探针就破坏了"冻结"的意义，因此明确改为上面的分工。
- 实现要求：原子累加、内存累积、**轮末统一输出**，运行中不持续写盘。
- 默认关闭，关闭时零开销；关闭状态下的外部指标即为公平对比基准。

### A5 故障注入（规模 S）

- 确定性注入：请求超时、SSE 中途断流、工具执行失败、沙箱拒绝、审批超时。
- 用途是测健壮性路径的行为与耗时，不是压力测试。

### A6 结果归档与曲线（规模 S）

- 目录布局、命名、结果库 schema、保留策略与 git 跟踪边界统一遵循 **`doc/eval-data-layout.md`**，本文不重复定义。
- 绘图脚本用 `mydev/scripts/.venv`（uv 管理）出趋势曲线，按需运行，不常驻。

### A7 一键入口（规模 S）—— **M2 的另一半**

- `just` 任务一键跑离线回放并输出与上次的对比表。

## E-C 测评设施自测

测评设施说了假话比没有测评更糟，因此设施本身要有测试：

- 回放服务器、规范化器、计分器、归因分类器的单元测试。
- **注入已知退化能被检出**：人为在回放路径插入固定延迟或多余轮次，验证报告确实标出退化。
- 这些测试并入既有 Nextest 体系，不另起框架。

## 硬约束

- 测评设施对功能代码的性能影响必须可忽略，且默认关闭。
- 冻结 codex 与 RONDO 的运行条件由适配器统一写死，不依赖人工保证。
- 隐藏集信息不得进入日常开发循环。
- 任何真实 API 跑批前须单独授权并给出预算。
- skip、未运行、fake 结果不得表述为通过；离线回放结论不得冒充真实任务成绩。
