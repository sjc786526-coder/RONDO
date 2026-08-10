# 方向 0：量化测评基准

最后更新：2026-08-10 ｜ 依赖：P0（S1/S2）｜ 当前 Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

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
  `completed`/reward 1.0。受跟踪 lock 同时绑定 Harbor console entry bytes、package files、
  marker-active 传递运行依赖版本与文件闭包。
- **B2 新门禁真实重验失败**：统一 runner、双 adapter、结果解析/归档、费用代理与
  Docker 监督已接线。旧 pair lock/schema 下的 `fix-git` no-API v3 保留 RONDO→Codex 正常路径
  completed 的历史证据，但它不包含第二轮新增的持久化契约。新契约使用 stable
  sidecar lock + temp/fsync/atomic replace/parent fsync 保存 pair ledger，绑定两槽共用的 clean
  eval harness commit，并对 no-API 原子保留去敏 safe summary；summary 与 ledger 通过固定路径、持续
  重读和 active 崩溃恢复收敛。watchdog lease 另绑定 wrapper PID/start-ticks 和新鲜 heartbeat，production
  overlay/inspect 强制 `cap_drop=ALL`。Docker 有效态另绑定 daemon
  actual image ID、Desktop VHDX 增长、private cgroup namespace、容器 cgroup v2 CPU/峰值内存、
  daemon 回显的有效 seccomp、规范 watchdog 阈值与安全 override；这些字段必须存在于去敏 safe
  summary，缺失不能完成 pair。新 identity 为 `p1-fix-git-pair-v4`，不复用保留的 v3 ledger。
  首次真实 Docker 重验在 RONDO slot 1 的 adapter 安装阶段 `infra_failed`：有效镜像、VHDX、
  private cgroup、容器 metrics、custom seccomp 与 `cap_drop=ALL` 已由 daemon 事实校验，但安装上传后的
  ownership/permission 复合命令失败；trace 定位到含 `chown` 的命令，原始 stderr 未保留，因此不冒充
  独立 syscall 证明。0 fake/API 请求。ledger 已写 failed/blocked，Codex slot 2 按合同未运行。
  adapter 后续已移除 install/run 的所有 `chown`，上传物必须实际 root-owned，agent 私有文件由
  1000:1000 自建，任务递归写权限只允许固定 `/app/personal-site`；该修复尚未用 Docker 重验。
  这不是双侧 B2 完整验收。
- **B3/M1 未完成**：三条旧 Codex 诊断均在首个官方 API 请求前 fail-closed，现已一次性迁移为
  `infra_failed` 永久结果并保留不可重用预算槽。实际 API 调用 0 次、费用 0 USD；旧付费批次不能形成
  公平 pair，paid 入口 hard-disabled。后续除新 pair/batch/轮次/预算和新授权外，还须在真实
  Docker 中验证 custom seccomp、container metrics 与 image/VHDX 契约。paid publication 先将 ledger 置为
  `publishing`，持久结果后回读 record digest 再收敛为 `completed`；M1 必须同时核对两条
  record 与 durable paid pair ledger、harness commit、publication digest、declared request role 和容器
  metrics。任一不一致都不能通过 M1。

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
  - Guardian 覆盖为 `gpt-5.6-luna` + `low`（依赖 S1）
  - 相同主模型 GPT-5.6-luna、相同超时与重试策略
- `v0.147.0` 的 Guardian 默认模型会随 provider/auth 改变，所以测评配置和结果元数据必须记录
  **显式** model/effort，不得以当前 API-key 路径恰好默认 Luna 为由省略配置。
- 验收：同一任务两侧各跑一次，运行条件在结果元数据里可核对。

### B3 最小真实链路跑通（规模 S，授权门：小额真实 API）—— **M1**

- 1~2 个任务的端到端，结果落盘归档。
- 同步开启 S2，确认真实审批过程能产出 `E_final`。

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

### B5 计分与失败归因（规模 M）

- 主指标：Task Resolution Success Rate。
- 归因分类必须区分：主 Agent/Harness 失败、Guardian 正确拒绝导致的失败、Guardian 误拒、基础设施失败（超时/网络/容器）。
- Guardian 对危险或未授权动作的**正确**拒绝计入主 Agent 应承担的失败代价，但在报表中单列，避免掩盖 harness 真实能力变化。

### B6 成本与预算护栏（规模 S）

- 跑批前输出预估：任务数 × 轮数 × 模型 × 预估 token → 成本区间。
- 硬上限：超过预算即中止并保留已完成结果。
- 每次跑批需单独授权。

### B7 首次基线（规模 S，授权门：canary 跑批）—— **M2 的一半**

- 按 `doc/WBS.md` §4「M2 的可执行判据」执行：先用同一 RONDO 二进制跑 2 轮 A/A 得出波动带宽 `σ`，再跑 codex 与 RONDO 各 1 轮 A/B，要求跨侧差异任务数 `≤ σ` 且无单向失败模式。
- 基础 10 任务 × 4 轮 = 40 次运行，外加条件触发的定点加跑（每个出现 codex-pass/RONDO-fail 的任务两侧各加 2 轮）。按 B6 出预估并单独授权。
- 不通过则先停下修测评设施，不得先行推进优化。

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
    门禁。当前只有 pure/fake 验证，真实 Docker 口径待 B2 重验；冻结 codex 不加补丁，
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
