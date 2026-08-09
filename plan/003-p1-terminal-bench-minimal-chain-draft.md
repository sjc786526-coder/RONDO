# P1 草稿：Terminal-Bench 2.1 最小真实链路（B1～B3）

> **草稿状态**：本文件用于下一阶段讨论，不代表已授权实施。
> 执行前须先完成本轮 P0 改动审查，并由用户明确授权 B1 的 Docker 操作；B3 还需单独给出
> 真实 API 的任务数、轮数、模型与预算上限。
> 本计划采用 `plan/plan-example.md` 的稳定约束格式；实现开始后，除“当前状态”和“关键决策记录”外，
> 目标、范围、硬约束或完成标准若需变化，应暂停并请求用户确认。

对应 WBS：`doc/WBS.md` 的 P1、`doc/WBS/eval-benchmark.md` 的 E-B1～B3。

## 1. 目标

### 最终目标

用同一套轻量 runner 和同一 Terminal-Bench 2.1 任务环境，把冻结 Codex CLI `v0.147.0` 与 RONDO
分别接入，完成 1～2 个任务的最小真实 API 链路，并自动留下可复核的运行配置、结果、外部资源指标、
任务镜像 digest 和 Guardian `E_final`。P1 只证明链路可用和两侧条件可核对，不产出成功率基线，也不
据一两个任务评价优化效果。

### 完成/验收标准

- B1 完成后，仓库内冻结 Terminal-Bench harness 的精确版本和依赖锁；记录所用官方示例任务 id、
  task/image digest、Docker/uv 版本与实际 agent 适配接口，不继续使用浮动 `2.1.x`。
- B2 提供一个 runner、两个薄适配器；两侧的任务选择、顺序、镜像、主模型、Guardian 模型/effort、
  approval/sandbox、超时、重试和 websocket 设置来自同一份运行规范，不能各自手配。
- 冻结 Codex 基线从只读 `codex-source-code/` 复制到项目内 ignored scratch 后构建；只允许对副本中的
  135 个 workspace lock 条目做 `0.0.0 -> 0.147.0` 机械规范化。原快照保持 detached、clean、精确
  指向 `rust-v0.147.0` / `be6e8eac029b183056b7e4402879f15d2c85f61b`。
- 两侧二进制各构建一次并固化，记录 SHA-256、源码 commit/dirty、Rust 工具链和构建命令；一次 run
  不得隐式重编。
- 不调用真实模型的 adapter/归档测试先通过；若 harness 自带测试入口则复用，否则只用项目已有
  Rust/Nextest 或 Python 标准/现有 uv 测试方式，不增加第二个重型框架。
- B3 在单独授权的预算内，先跑 1 个任务、健康后最多再跑 1 个；两侧各至少有一条 completed run，
  或留下明确的 `infra_failed` 结果和可恢复现场。skip、网络失败和容器失败不算通过。
- 每条 run 原子落盘到 `eval-data/runs/<run_id>/`，并追加符合 `doc/eval-data-layout.md` 的
  `eval/results/runs.jsonl`；记录 task outcome 与 `agent|guardian_correct_deny|guardian_false_deny|infra`
  归因、wall/CPU/peak RSS、token/cost（能取得时）及产物相对路径。
- RONDO 侧启用 S2 后产生 `E_final.json` + `meta.json`；消费者保留
  `guardian_source_baseline` 与 `guardian_source_commit`，并从 standard/Lite 两种逻辑形态中提取有效 policy，写入
  `guardian_effective_policy_sha256`。不得用源码版本冒充实际 policy 身份。
- 运行结束自动输出一页摘要；命令退出码能区分配置错误、环境错误、预算停止、agent 失败和成功。
- P1 验收不要求历史 workspace 全绿；但不得把本轮已知的 Clash fake-IP、宿主代理、浏览器副作用或
  `/tmp` marker 污染带入 runner，再把环境偶然性当作 agent 成绩。

建议形成以下稳定入口；若 B1 发现官方接口要求不同，可在实现前更新本草稿：

```text
just eval-tb-doctor
just eval-tb-build codex|rondo
just eval-tb-smoke --side codex|rondo --task <task_id> --no-api
just eval-tb-run --side codex|rondo --task <task_id> --budget-usd <amount>
```

## 2. 范围

### 允许修改

- 新建轻量 `eval/`：版本锁、runner、官方 adapter、配置 schema、结果归档与小型 fixture。
- `mydev/justfile`：增加统一的 doctor/build/smoke/run 入口；任何会触发 Cargo、镜像构建或较大
  Python 工作负载的入口必须再经项目看门狗。
- `doc/WBS.md`、`doc/WBS/eval-benchmark.md`、`doc/eval-data-layout.md`：只同步 B1 实测后才能确定的
  当前版本、接口、产物和里程碑状态。
- `agent_log/`：记录 B1/B2/B3 的实测命令、授权范围、预算和结果。
- `.gitignore`：仅补充由 B1 实测确认的本地缓存/产物路径；大产物继续落既有 `/eval-data/`。

### 不允许修改

- `codex-source-code/` 只读快照及其 Git 状态；禁止就地改 `Cargo.lock`、打补丁或加入探针。
- RONDO/Codex 核心行为、Guardian policy、审批/沙箱安全语义和 Terminal-Bench task/verifier。
- 任务 4 中已调查的上游失败测试；它们应另立维护批次，不混入 P1。
- P2 的 10-task canary、A/A+A/B 基线、隐藏集、离线回放、曲线和批量归因器。
- 宿主 Clash、DNS、代理、Docker Desktop 配置和全局 Python/Rust 环境；需要调整时先停下给出证据。
- 发布、上传、远端写入、模型训练或任何未单独授权的真实 API 调用。

### 不允许读取/查看

- API key 明文、个人配置、真实会话记录和项目外私有文件。
- P2 未来隐藏集的任务正文、verifier、单任务日志与单任务结果。
- 非本任务所需的其他仓库和 worktree 修改。

## 3. 硬约束

1. **授权拆分**：B1 的 Docker 拉取/运行先授权；B3 再按“任务、轮数、模型、预算上限”单独授权。
   B1/B2 不得借环境勘察偷偷发真实模型请求。
2. **资源监督**：全部重型 Cargo、Docker build/run、harness 安装/执行只能通过
   `mydev/scripts/with-build-lock.sh` 或明确接入它的 `just` 入口；一次只能有一组重型工作，
   `CARGO_TARGET_DIR` 位于 RONDO 项目根内。Docker Desktop daemon/容器并不天然属于调用端的 user
   cgroup；B1 必须另验证 container 的 memory/swap/pids/timeout 与 Docker 存储计数，拿不到可靠计数
   就 fail-closed，不能把“docker 客户端经过 wrapper”冒充容器已受完整监督。
3. **公平条件**：同一任务两侧使用同一个 digest、输入、顺序、网络策略、超时和 retry；主模型固定为
   `gpt-5.6-luna`，Guardian 显式固定 `gpt-5.6-luna + low`，`supports_websockets=false`，
   `approvals_reviewer=auto_review`，`approval_policy=on-request`，`sandbox_mode=workspace-write`。
4. **冻结基线**：baseline 只允许 lock 机械规范化；二进制构建后记录哈希并复用。任何额外源码差异都
   使该产物失去“冻结 Codex”资格。
5. **事实分层**：Docker/task smoke、fake/no-API adapter test、真实 API run 分开记录；
   `infra_failed` 不计 agent 成败，部分结果不得伪装成完成。
6. **安全不降级**：Clash TUN 返回 `198.18/15` 时仍保留本地/私网 fail-closed 判定，不为跑通而放行
   fake-IP 网段。优先让 runner 使用可控 resolver/direct client；必须改宿主 DNS 时重新征求授权。
7. **秘密最小化**：凭据只经运行时环境传入，不落 config、命令行、日志或 artifact；输出前做键名与
   URL/header 脱敏扫描。原始 `E_final` 按私有会话记录处理，保持 ignored 和最小权限。
8. **原子与可恢复**：每次运行先写临时目录/临时记录，终态再 rename/append；预算、信号或基础设施
   中止也必须留下状态与已花费估计，不产生半条 JSONL。
9. **不凑绿**：不得更新 task verifier、弱化审批/沙箱、无限增大超时或删除失败明细来换取通过。
10. **精确版本优先于猜测**：Terminal-Bench 包名、CLI、adapter API、示例任务和 digest 以 B1 的官方
    安装产物/文档实测为准；本草稿不预先伪造接口。

## 4. 软性建议

### 阶段与串并行

1. **P1-0 串行前置**：用户/Claude 审查本轮 P0 diff；确认 S2 定向门禁和看门狗改动可接受。
2. **B1 串行勘察**（Docker 授权后）：doctor → 官方 harness 安装到项目局部 uv 环境 → 冻结版本/lock
   → 验证 Docker daemon/容器资源与存储计数 → 拉取单一示例任务镜像并记录 digest → 用 no-op/fake
   adapter 验证容器生命周期。发现接口后先更新本计划的待核实项，不立即扩范围。
3. **B2 可并行的轻工作**：
   - runner/config/result schema 与 adapter fixture 测试；
   - 两侧二进制身份、构建 manifest 与 source-integrity 检查；
   - 结果归档、秘密扫描和 effective-policy 提取器。
   两个 Cargo 二进制构建仍必须串行，不能因分工而并发。
4. **B2 串行集成**：先 RONDO no-API smoke，再冻结 Codex no-API smoke；比较 manifest 中全部公平字段，
   不一致即 fail-closed。
5. **B3 串行真实链路**（真实 API 授权后）：先 1 task × 1 side 的设施探针，再同任务另一 side；两侧
   都健康才考虑第二个任务。预算或基础设施红线触发后立即停，不自动扩大重跑。
6. **收口**：只跑受影响设施的必要测试；更新 WBS/日志并输出 M1 证据。完整 workspace 和 P2 canary
   不属于本阶段默认门禁。

### 建议模块边界

- `RunSpec`：唯一运行输入，含 side、binary manifest、task/image、模型/审批/网络、timeout/retry、预算。
- `PreparedRun`：doctor 和镜像解析后的不可变输入；缺 digest 或公平字段不一致时不允许启动。
- `RunOutcome`：`completed | agent_failed | infra_failed | budget_stopped | cancelled`，退出码与 JSON 一致。
- `ArtifactWriter`：负责原子目录、JSONL append、脱敏扫描和最终摘要；adapter 不直接散写文件。
- `PolicyIdentity`：从 standard `instructions` 或 Lite developer item 提取有效 policy，输出结构版本和
  SHA-256；解析不明时标 `unknown` 并阻止跨 policy 聚合，而不是退化到 source baseline。

### 失败处置

- Docker daemon/拉取失败：记 `infra_failed`，保留 daemon/镜像摘要；不自动修改 Docker/Clash。
- DNS 解析到 `198.18/15`：区分“任务容器网络”与“Codex managed proxy”；先证明具体失败链路，
  再决定 runner resolver 还是请求用户为相关域名提供 real-IP DNS。
- API 401/403/429/配额不足：停止真实 run，记录去敏错误与已花费；不循环重试消耗预算。
- task/verifier 非零：保持原始结果，按 agent/guardian/infra 证据归因；无法确定时写 `unknown`，不猜。
- `E_final` 缺失：如果审批轮未到 send point，允许 `meta:evidence=none`；已观测到 Guardian 出站却缺失
  则判设施失败。发送点之后的网络失败仍可能有 `E_final`。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息。

### 已完成

- P0 已具备显式 Guardian model/effort 和 S2 证据落盘；2026-08-09 定向复验修复了 WS 建连前过早
  捕获、业务同名 `call_id` 被递归改写和结构 `turn_id` 漂移。
- 基线迁移已做树级验收；官方 tag commit、lock 规范化和二进制来源边界已明确。
- `doc/eval-data-layout.md` 已定义 ignored/raw 与 tracked/summary 的基本目录和 run schema。
- 历史上游/RONDO 全量失败已归因；没有证据显示这些失败来自 P0，但测试环境仍非完全 hermetic。

### 当前工作

- 仅形成草稿；未安装 Terminal-Bench，未拉镜像，未运行 Docker，未调用真实 API。

### 后续计划

- 用户/Claude 审查并决定是否接收 P0 和看门狗小修。
- 用户确认 P1 草稿后，先单独授权 B1 Docker 勘察；以实测接口更新版本、文件布局和稳定命令。
- B2 完成且 no-API smoke 通过后，再提交 B3 的精确任务/轮数/模型/费用预算申请。

### 阻塞项

- Terminal-Bench 2.1 的当前精确发行版本、包名、adapter API、示例任务和 task image digest 尚未实测。
- Docker Desktop 容器是否能被当前 wrapper 的 cgroup/磁盘计数完整覆盖尚未验证；B1 必须先补显式
  container limits 和 Docker 存储计数，不能沿用 Cargo 监督结论。
- B1 Docker 操作与 B3 真实 API 均未授权。
- 本轮 P0/watchdog diff 尚待用户指定的 Claude 审查，且未提交、未合并。
- 最新严格全量原始 stdout/JUnit 未保留；这不阻塞 P1 最小链路，但阻塞对该轮 81 项的更细时序复盘。

### 当前验收状态

- 草稿完成不等于 P1 通过。M1 仍为未开始。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | P1 只做 B1～B3 和 1～2 个任务，不提前做 canary/基线 | 先证明链路和公平条件，控制成本与变量 | P1/P2 边界 | 提议 |
| 002 | 一个 runner + 两个薄 adapter，共享不可变 `RunSpec` | 公平条件由机器检查，不靠人工记忆 | 架构 | 提议 |
| 003 | baseline 复制到 ignored scratch 后只改 lock 版本 | 保持官方快照只读，同时满足 `--locked` 构建 | 基线构建 | 提议 |
| 004 | 二进制一次构建、记录哈希、运行期禁止隐式编译 | 降低磁盘/时间波动并保证可复核 | 构建与归档 | 提议 |
| 005 | source baseline 与 effective policy hash 分开记录 | 同一源码版本可加载不同 config/catalog policy | S2 消费 | 提议 |
| 006 | Clash fake-IP 不加入私网 allowlist | `198.18/15` fail-closed 是正确安全行为 | 网络 | 提议 |
| 007 | 真实 API 先单任务双侧串行，再决定第二任务 | 最小化费用并尽早暴露设施错误 | B3 | 提议 |
| 008 | 历史全量失败另立维护批次，不混入 P1 | 绝大多数是上游 fixture/环境问题，混修会扩大阶段 | 范围 | 提议 |
