# 0.147.0 基线、P0、测试体系与看门狗验收执行计划

> 本文件是本轮审查的可恢复执行记忆，按用户授权直接建立并在执行中持续更新。
> 它不替代 P0 的稳定技术方案，也不是下一阶段 P1 的交付方案。

## 1. 目标

### 最终目标

在独立 worktree 中，以实时源码、Git 历史、已有原始日志和受看门狗保护的必要测试为证据：

1. 验收 Codex CLI `v0.147.0` 基线迁移及权威文档表述；
2. 独立复核 P0 在新基线上的实现与验收，发现并小范围修复真实问题；
3. 审查 RONDO 测试是否复用上游体系，并判断构建资源看门狗是否可靠、是否真正覆盖主要入口；
4. 调查纯上游与 RONDO 全量测试失败/跳过的根因、处置建议和需要用户配合的宿主环境事项；
5. 在上述结论基础上形成下一阶段 P1 的技术方案草稿。

### 完成/验收标准

- 基线身份、导入范围、lock 规范化和文档事实均有可复核证据；`codex-source-code/` 如有问题只报告。
- P0 逐条对照 `plan/001-p0-guardian-override-and-evidence.md`，区分已满足、合理偏离、缺口和新隐患。
- 测试设施审查覆盖测试归属、重复/重型风险、统一入口与看门狗绕过面。
- 失败调查至少给出“需修产品 / 需修测试或 fixture / 需隔离环境 / 可接受跳过或未支持 / 需用户配合”的清单；任务 4 不改测试、不改网络、不凑绿。
- 必要测试全部经 `mydev/scripts/with-build-lock.sh` 或已接入该脚本的 `just` 入口，且一次只运行一组重型任务。
- P1 草稿符合 `plan/plan-example.md`，显式标出本轮未闭合和后续需核实事项。
- 所有改动只留在 `.claude/worktrees/0809-baseline-p0-acceptance`；不合并、不提交、不推送。

## 2. 范围

### 允许修改

- 本 worktree 中与已证实问题直接相关的 RONDO 源码、现有测试、看门狗与统一入口。
- `README.md`、`doc/WBS.md`、`doc/WBS-COMPLETED.md`、`doc/development-environment.md` 中受影响的权威事实。
- `plan/` 中本 exec plan 与 P1 草稿；`agent_log/` 中本轮精炼执行日志。

### 不允许修改

- `codex-source-code/`、`codex-doc/`、`reference-agent-harness/`。
- 主工作区和其他 worktree 的任何内容。
- 任务 4 涉及的失败测试、网络配置和宿主机配置；不得通过弱化断言或改快照凑绿。
- P1 产品实现、真实 API 跑批、Docker 运行、发布、上传或其他远端状态。

### 不允许读取/查看

- 项目外个人文件、凭据、API Key 与真实会话数据。
- 与本轮任务无关的其他仓库。

## 3. 硬约束

1. 所有重型 Cargo 构建/测试必须受 `with-build-lock.sh` 完整保护；优先使用已接入的 `just` 配方。
2. 同时最多运行一组重型构建/测试；子智能体不得自行启动 Cargo/Nextest/Bazel/Docker。
3. 不使用 `RONDO_BUILD_WATCHDOG=0`、`RONDO_BUILD_LOCK=0`、外置 `CARGO_TARGET_DIR` 或其他绕过方式。
4. 先复现、后修复；只修任务 0/1/2/3/6 中证实且范围小的缺陷。任务 4 只调查。
5. 测试、跳过、未运行、离线、真实网络、Docker 和真实模型证据必须明确区分。
6. 不回退、覆盖、stash 或删除来源不明的修改；不清理其他 worktree/target。
7. 不安装 Bazel，不修改宿主机网络。若判断必须由用户改变 Clash/TUN/DNS 或宿主配置，只给出最小配合步骤。
8. 上游基线升级不在本轮；只验收已经完成的 `0.147.0` 迁移。

## 4. 软性建议与执行顺序

1. 串行建立事实底座：Git/worktree 状态 → 规则/计划/日志 → exec plan。
2. 并行只读审查：
   - A：上游快照、导入提交、lock 规范化与文档一致性；
   - B：P0 实现、测试与方案逐项对照；
   - C：测试体系复用与看门狗入口/脚本可靠性；
   - D：全量失败的 fixture/cwd/skill/V8 类归因；
   - E：代理/网络/realtime/shell/migration 类归因与宿主配合边界。
3. 主智能体交叉核对代码与子审查结论，先做纯静态/轻量脚本验证，再按证据缺口排定向重型测试。
4. 小修完成后只跑受影响模块的必要测试；除非静态证据明确表明必须重跑，不重复一次 120GB 级冷全量。
5. 最后更新权威文档、执行日志和 P1 草稿，再做一次独立复核与 worktree 污染检查。

## 5. 当前状态

### 已完成

- 确认主工作区 `main...origin/main` 干净；保留三个既有 worktree 不动。
- 创建本 worktree 与分支 `audit/0809-baseline-p0-acceptance`，起点 `e43697d`。
- 完整阅读仓库级与 `mydev/` 规则、README、当前/已完成 WBS、P0 方案、开发环境、P1/E-B 路线及本轮相关日志。
- 确认历史记录声称：纯上游全量 14,065 run / 83 failed / 1 timed out / 23 skipped；最新 RONDO 全量 14,077 run / 81 failed / 23 skipped；二者均不声称全绿。
- 远端 tag、本地快照与迁移三方核对确认真实 commit 为 `be6e8eac029b183056b7e4402879f15d2c85f61b`；七处文档中的不存在 SHA 已做最小事实纠错。
- 五条并行只读审查全部完成，并由主智能体交叉核对源码、历史 raw log 和 Git 树证据。
- 基线迁移通过树级/三方合并验收；确认 `.vscode` 3 文件为迁移前既有 allowlist，未改 ignored 上游快照。
- P0 修复三个实质缺口：捕获移到 HTTP/WS transport send point、`call_id` 只改结构位置、
  passthrough `turn_id` 定点规范化；source baseline 与有效 policy 身份分开。
- P0 精确回归首轮 15/16（唯一为新 Lite 测试错误期待空字符串）；修正字段缺席断言后 16/16 通过。
- 看门狗补足 signal/EXIT trap、终止确认、活跃期计数器 fail-closed、rustc throttle fail-closed，并把
  Unix benchmark 与三个 schema generator 纳入统一入口；schema/fmt/clippy/测试全部经看门狗串行执行。
- 全量失败与 23 个 skip 已形成逐类根因、修法和用户配合矩阵；任务 4 未改任何测试或网络。
- 写入本轮精炼日志 `agent_log/2026-08-09-020200-baseline-p0-test-audit.md` 与 P1 草稿
  `plan/003-p1-terminal-bench-minimal-chain-draft.md`。
- 最终 `git diff --check` 通过；无活跃 watchdog scope 或 Cargo/rustc/nextest；主工作区保持干净，
  review worktree 保留约 23GB 受监控构建产物供 Claude 复核/增量测试。

### 当前工作

- 本轮执行完成，等待外部审查。

### 历史交接（不是当前规划）

> 以下记录只反映本计划结束时的交接判断；当前路线以 `doc/WBS.md` 为准。

- 交给 Claude 审查本 worktree；不提交、不合并、不推送。
- 用户决定是否另立全量失败测试维护批次，以及是否授权 P1 B1 Docker 勘察。

### 阻塞项

- 无本轮阻塞。Bazel 未安装、最新严格轮 raw stdout/JUnit 缺失均作为未运行/证据边界保留。

### 当前验收状态

- 基线验收通过；P0 定向功能复验 16/16 通过；测试复用验收通过；看门狗高风险可靠性小修通过
  syntax/signal/真实受控构建验证，但不宣称所有直接 Cargo 入口都被机制封堵；任务 4 调查完成；
  P1 草稿完成。完整 workspace 未重跑，历史 81 项失败未修。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 五条静态审查并行，重型测试统一串行 | 提高审查覆盖面，同时严格满足 OOM/磁盘与单构建约束 | 本轮全部任务 | 已采纳 |
| 002 | 不默认重跑两个完整 workspace 全量 | 历史冷构建约占 126GB；本轮应先根据原始证据与定向复现确认缺口，避免把重复重型运行当验收本身 | 测试策略 | 已采纳 |
| 003 | 任务 4 的真实问题也只形成修复建议，不在本轮改测试/网络 | 用户明确限定只调查，避免调查与处置混杂 | 全量失败调查 | 已采纳 |
| 004 | `E_final` 定义为 send point 的完整逻辑请求，不是“模型已收到”或 WS delta | delta 无法独立离线复用；builder 候选又可能从未连接 | P0 证据语义 | 已采纳 |
| 005 | meta 记录 `guardian_source_baseline`，有效 policy hash 留给 P1 消费器 | 同一源码版本可加载 requirements/config/catalog policy | P0/P1 数据契约 | 已采纳 |
| 006 | 看门狗只做高价值窄修，不实现通用 Cargo/PATH 拦截层 | 主测试入口已保护；全入口机制封堵影响面大，超出本轮调研边界 | 构建设施 | 已采纳 |
| 007 | P0 以精确定向回归收口，不重复完整 workspace | 改动边界窄，历史 raw 已证明失败主体非 P0；冷全量成本高且任务 4 禁止修测试 | 验收 | 已采纳 |
