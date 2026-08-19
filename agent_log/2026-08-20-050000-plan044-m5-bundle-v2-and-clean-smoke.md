# Plan 044 / Multi M-5：重建 bundle、冻结 v3、两次 clean smoke

日期：2026-08-20 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`

## 结论

产品缺陷的修复**在真实模型上确认成立**：成员现在能收到明文任务、完成回合并调用团队工具。
但 **clean smoke 未达成**，剩 1 次额度未用。**M-5 未通过，门 1 未通过，门 2 未启动。**

## 改动

- **重建并冻结 `multi-m5-runtime-v2`**（源码 `6fe1379`，含 code-mode 明文修复）。
  需要**两次**重型构建而不是一次：`prepare_companion()` 拷进 bundle 的 `codex` 字节取自 legacy artifact
  目录，因此必须先补 legacy 单 bin 构建 + `prepare`，再做两 bin `v8-build` + `prepare-companion`。
  两次均走本 worktree 的 `scripts/with-build-lock.sh`、`CARGO_BUILD_JOBS=2`，`status=0 stop=none`，
  39m08s / 32m41s，未放宽任何门禁。旧 bundle、旧锁、旧归档未动。
- **冻结 `multi-m5-workflow-v3` / `multi-m5-nondegradation-v3`**，均显式写 `runtime_lock_id`。
  v3 新增：门 1 `infra_taint_effect`、`provider_contract`；门 2 `provider_retry_backoff_seconds="2"`、
  `unpriced_settlement`（`unpriced_stop_threshold=1` + `any_unpriced_invalidates_observation=true`）。
- **退避统一从锁读**：门 1 原硬编码 `2.0`，门 2 原读宿主 `paid_eval.retry_backoff_seconds`（本机 `1.0`），
  两门实际不一致且都不在冻结合同里。按决策 043 的隔离方式处理，宿主全局量不动（决策 044）。
- **新增 `member_message_delivery`**（`plaintext`/`encrypted`/`absent`），写进门 1 结果与 smoke 摘要。
  这是冒烟五项验收里唯一原本只靠人看抓包的一项（决策 046）。
- **clean smoke 独立批次** `multi-m5-clean-smoke`：旧 `$40` 批次已用尽，且账本 cap 与磁盘文件绑定、
  不能就地扩容。上限由 `3 次 × 单次 run cap $23.10 = $69.30` 机械推导并强制小于 `$120`（决策 045）。

## 疑难点

- 交接文档的构建命令模板有三处与代码不符，逐条以代码为准：`CARGO_TARGET_DIR` 必须恰好是
  `eval-data/build/rondo-multi-<commit>-x86_64-unknown-linux-musl`（`_expected_target()`），
  `RONDO_BUILD_METRICS_DIR` 必须落在 `eval-data/build-metrics/` 下且每次构建一个全新目录
  （`_validate_watchdog_summary()` 要求恰好一份 `summary.env`），gate-root 与 cwd 必须是实现 worktree。
  上一轮编在 measurement 树 `multidev/codex-rs/target` 下的产物即使编完也会被 `prepare` 拒收。
- 上一轮 OOM 的直接原因是没设 `CARGO_BUILD_JOBS`，32 核并发把 21G cgroup 打爆；恢复决策 016 的 `2` 即可。

## 真实 API 结果（clean smoke，2/3 次）

| run | 请求 | 结果 | 说明 |
|---|---|---|---|
| `cs1` | 1 | `infra_failed` | 第 1 个请求即被上游终止，产品侧零信息 |
| `cs2` | 35 | `infra_failed` | 成员真实跑起来了；4 次上游终止 |

**成立的部分（cs2）**：两个线程 —— Root 20 个请求、成员 15 个请求。成员从 code cell 派发 8 次工具调用
（`team_publish`×2、`team_evidence`×2、`team_history`、`team_route_update`、`send_message`、`exec_command`）。
`member_message_delivery=plaintext`，**82 明文块 / 0 encrypted**；同一路径在旧 bundle 的 cm4 抓包里是
37 个伪 encrypted、成员 8/8 推理失败、从未完成一个回合。**产品缺陷的修复到此确认成立。**

**未成立的部分，两个独立原因**：

1. **上游终止**：形态是 HTTP `200` 之后在流内发 `error`/`server_error`。重试白名单是 HTTP **状态码**
   （429/500/502/503/504），状态码为 200 时退避梯子完全不触发，一次抖动即打 taint。
   cs1 1/1、cs2 4/35。`conservative_exposure_usd=$11.10 ≠ 0`，按验收口径直接 `infra_failed`。
2. **模型未调用 `team_inspect`**：判据只接受 `team_inspect` 的输出作为 dump/log 证据源。
   因此 cs2 的七个谓词**全部无法验证**，不是"判为假"。
   **不得**据此对 `team_evidence` / Direct fact 风险或 terra 的指令遵循下任何结论。

**旧观测的勘误**：cm1–cm4 的 49 个请求里终止错误**全部**是 `invalid_encrypted_content`、零个
`server_error`。代码注释里"中转站约三分之一掉流"的说法是被产品缺陷污染的观测，不是中转站的基线故障率。
`server_error` 是本轮才出现的形态。

**费用**：clean smoke 批次共扣 `$11.52`，其中真实 token 计价 `$0.42`，其余为保守预留；剩余 `$57.78`。
**正式两道门的 `$120` 账本仍不存在、零消费。** 未跑 Docker、未启动正式门 1/门 2。

## 验收

- 全量 `python -m unittest discover -s tests`：**952 通过 / 0 失败**，另 2 条既有加载错误
  （`test_l6_b10333_pair`、`test_local_m4_holdout_anchor`，干净树上同样存在）。
- 定向门禁 216/216；`just eval-lock` 通过；`ready=true`。
- 彩排：七谓词全真、`member_message_delivery=plaintext`、`counts_as_effective=false`。
- loopback：通过，`lock_id=multi-m5-runtime-v2`。
- 未合并、未推送。剩余 1 次 clean smoke 额度**未使用**，等待方向决定（见 WBS）。
