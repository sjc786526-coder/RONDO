# Plan 008 第四轮独立审查整改日志

日期：2026-08-10

工作树：`.claude/worktrees/0810-plan008-review-remediation`

整改前提交：`5f584273297cac3ec91799d8cf53904c748357f7`

审查输入：`agent_log/2026-08-10-172258-plan008-fourth-independent-review.md`

## 1. 范围与边界

本批只处理第四轮审查提出的三个 B2 重跑前问题：退休失败的 v4 identity、把 no-API 崩溃恢复绑定到本次请求 side、为 failed no-API 槽持久保存并由 pair ledger 绑定去敏结构化摘要。同步更新受影响的 Plan/WBS/数据布局文档，不扩展 B3、M1 或 L2 model-backed 能力。

本批未运行 Docker、Cargo、真实 API 或模型，未读取 `.env.local`，未改写或删除保留的 v4 ledger、trial、watchdog 与既有审查日志证据。paid 模式继续 hard-disabled。

## 2. 问题核实

三项审查结论均成立：

1. 受跟踪 pair lock 在整改前仍启用 v4；v4 的 failed/blocked 终态只存在于 ignored 本机 ledger，新 clone 可以从同一受跟踪源码重新创建 v4。
2. no-API durable summary 的恢复入口没有核对调用者的 `--side`，Codex 命令可错误消费 RONDO summary。
3. v4 failed slot 没有机器绑定的结构化失败摘要；有效镜像、seccomp、private cgroup、VHDX 与 container metrics 仅有运行时采样和人工日志，无法从 failed ledger 独立重算。

核对保留现场时还发现第四轮审查日志最初转录的 harness commit 有一处笔误。机器 source-of-truth 是保留 v4 ledger 与 Git 对象共同指向的：

- v4 ledger SHA-256：`23ceecfebfb058fe6dd814df09a217674f62374740d3e2282b90f4aff069edef`
- eval harness commit：`07d0a487f8c498032a6da7ce4fd37a91c607bdac`
- run：`tb-no-api-rondo-e2cd95f5bc72`，side：`rondo`

不存在的转录值已在审查日志中订正；保留 ledger 本身未改写。

## 3. 实现

### 3.1 v4 退休与 v5 冻结

- 受跟踪 lock 的当前唯一 identity 改为 `p1-fix-git-pair-v5`，no-API batch 改为 `p1-no-api-smoke-v5`；paid 仍明确 disabled。
- lock 新增精确 `retired_pairs` 条目，绑定 v4 pair id、失败终态、ledger SHA、真实 harness commit、run、side 和审查日志相对路径。
- loader 拒绝当前 identity 与 retired identity 重复，也拒绝 retirement 字段缺失或漂移。生产 ledger/summary 路径只从当前 v5 lock 派生，不接受 CLI 自选 pair id。
- 当前 v5 lock SHA-256 为 `7e6b69c60987cca55565cfa1e2414d7b1840b098048875b496003cee97105252`。本批结束前，主仓 ignored `p1-fix-git-pair-v5-no-api.json` 不存在；没有把轻量测试冒充 v5 实跑。

### 3.2 side-bound 恢复

- `reconcile_no_api_summary()` 强制接收 `requested_side`，并在读取 summary 或修改 ledger 前，同时核对 active run side、拓扑 slot side 与请求 side。
- 错侧恢复返回配置错误且不修改 ledger/summary；正确 side 之后仍可恢复。
- 恢复输出显式包含 `requested_side`、`recovered_side` 与 `terminal_status`。只有 recovered `completed` 返回 0；recovered `failed` 返回 infra 非零，防止只看退出码的串行编排误触下一侧。
- 回归证明 RONDO durable summary 不能被 Codex 命令消费，failed RONDO 恢复不会触发配置、密钥、watchdog、Docker 或 backend 前置。

### 3.3 failed no-API 原子摘要与去敏诊断

- no-API ledger 升为 schema v4；completed 与 failed 统一绑定固定 `no_api_summary_path` 和 SHA-256，terminal ledger 每次打开都重读 canonical summary、重算 hash 并核对终态。
- 事务顺序为：持久 active claim → 执行与 cleanup → 原子写入并 fsync summary → ledger 在锁内从固定路径重读/校验 → 原子收敛为 completed 或 failed/blocked。
- summary schema v2 对 completed/failed 共用身份字段；失败额外保存闭集 failure stage、安全 command id 和受限诊断分类。adapter 不再把原始 argv、stdout/stderr、异常 cause、密钥或宿主绝对路径带入错误或摘要。
- Docker 证据按实际可用性记录 `observed`、`observed_partial` 或 `not_observed`。可用时保存 daemon image ref/id、有效 seccomp、private cgroup、capability/NNP、资源限额、去路径 mount/network digest、VHDX/df、container CPU/peak memory 与 cleanup；不可用字段保持 `null` 和固定原因，不补造 0。
- trial result/exception 只以受限相对 artifact role 和 SHA-256 关联。父 watchdog summary 在子 CLI 退出后才生成，子进程诚实记录 `parent_finalize_pending`，不伪造其 digest。
- summary 已耐久而 ledger 仍 active 时，同侧重启可收敛。若进程在 summary 耐久前死亡，ledger 保持 active 并拒绝新 claim；因为无法证明 Docker 是否启动，不伪造 `not_observed` 终态。

## 4. 文档同步

- `plan/008-p1-terminal-bench-and-local-approval-execplan.md`：记录 v4 退休、v5 当前状态、failed summary 事务与 side 恢复边界。
- `doc/WBS.md`、`doc/WBS/eval-benchmark.md`：当前状态改为 v4 RONDO 设施失败并退休、v5 未跑 Docker、B2 未完整验收。
- `doc/eval-data-layout.md`：冻结 no-API ledger schema v4、completed/failed summary、崩溃前后语义和去敏字段边界。
- `doc/WBS/local-approval-model.md`：保持 L2 仅 CPU x64 前端/运行闭包，明确 receipt 仍不证明进程实际加载字节或 launcher 退出后 server 必然退出。

## 5. 验证证据

- 聚焦 no-API smoke + pair：30/30 通过。
- 四模块聚焦回归（adapter/pair/docker-smoke/results）：79/79 通过。
- `just eval-test`：285/285 通过，无 skip；该入口显式清除环境代理，只保留 loopback `NO_PROXY`。
- `just eval-lock`：85 packages，lock check 通过。
- 三个生产 Python 模块 `py_compile` 通过。
- `git diff --check` 通过。
- 独立聚焦复核确认三项整改范围内未发现剩余提交阻断；其结论不扩张为 Plan 008 整体闭环或无缺陷声明。

全部验证均为 pure/fake/loopback 轻量测试；没有 Docker、Cargo、真实 API 或模型证据。

## 6. 明确保留的未验边界

- v5 尚未运行真实 Docker；RONDO→Codex 双侧 B2 仍未验收。
- 修复后的 compose upload ownership、secret 只读挂载、固定 workdir chmod、日志目录 ownership 和生产 partial Docker 投影仍须由下一次严格串行 v5 Docker 验证。
- B3 继续被逐请求 declared role 发送链和 pre-journal `publishing` 收敛问题阻断；paid/M1 hard-disabled，真实 API 另需批次、轮数、模型与预算授权。
- L2 model-backed 继续被 launcher/server 生命周期与进程实际加载字节身份约束阻断；权重/GPU 推理另需授权。

因此本提交只交付第四轮审查的第一阶段整改，不宣告 Plan 008、B2、B3/M1 或 L2 完成。
