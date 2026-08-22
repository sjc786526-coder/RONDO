# Plan 055 独立验收整改

日期：2026-08-22

来源：独立验收提交 `d216bfb` / `agent_log/2026-08-22-055902-plan055-independent-acceptance-review.md`

## 实质修改

- `RuntimeLimits` 统一拒绝低于 8 KiB 的 request/response cap；该固定下限只保证任意有效 identity 下 liveness、readiness、shutdown
  和 response 控制 envelope 可完成，合法的大 review 仍返回 typed `RequestTooLarge`。最大转义 identity 的 wire 序列化回归守住该边界。
- 将 scorer status 统一分类为 `Loading`、精确 `Ready` 和 terminal typed failure。terminal 状态的 liveness 使用 `Failed` phase，
  readiness/review 立即返回既有 backend/model/scoring failure code；`Loading` 仍保持可等待并可恢复。
- 受控 scorer 的 `Notify + AtomicBool` release barrier 改为一次性 `CancellationToken` latch，消除 waiter 注册前 release 的丢唤醒；
  资源测试让一次 release 覆盖 active 与后续四个 queued affected calls，同时保留 timeout、显式取消和 force shutdown 回归。

## 验证

- `just test -p codex-publication-critic`：29/29 passed，0 skipped。
- `just clippy -p codex-publication-critic`：通过。
- `../scripts/with-build-lock.sh just argument-comment-lint -p codex-publication-critic`：通过；仅有既有
  `codex-utils-cargo-bin` 的两个 unknown-lint warning。
- `just fix -p codex-publication-critic`：通过；最终 `UV_CACHE_DIR=/home/sjc/desktop/RONDO/eval-data/uv-cache just fmt`：通过。
- 所有 Cargo 门禁均经过共享构建锁与资源看门狗，最终均为 `stop=none`；按 `multidev/AGENTS.md`，最终 fix/fmt 后未重复测试。

## 边界与状态

- 未新增依赖或生成文件变化，不需重跑 Bazel lock；未运行全 workspace、全 Bazel、CI、PR、Docker、真实 API、训练或真实模型。
- 相对基线允许写集仍只涉及 Publication Critic crate、workspace/BUILD 接线与 Plan 055 文档；`team_publish`、Team State、Team Lens、
  `eval/`、`training/`、`mydev/` 零修改。
- 证据仍只覆盖受控 scorer 经真实服务进程、正式 transport、typed client 和资源门的闭环，不代表真实模型或最终 threshold。
- 本轮整改本地门禁已完成，等待同一独立审查者重新验收；尚未合并、推送或归档分支。
