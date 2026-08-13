# Plan 020 post-audit 收口

- 确认 Oracle proof 的共享组件摘要遗漏 `compat.py`；同时核对实际 Oracle 直达路径，将 `compat.py`、
  `freeze.py` 与 `tasksets.py` 纳入 contract SHA。真实 `build_oracle_contract()` 漂移回归证明兼容层语义变化会使旧
  proof 失效。
- campaign 在 `state.finalize()` 后、aggregate 发布前崩溃时，后继 worker 现可从只读 state、budget、public
  result 和 continuation 重放 assessment，幂等补齐 private/tracked aggregate；已有 aggregate 只接受逐字节相同
  投影。若 private 已落盘而 tracked 尚未写入，重放会严格验证并复用 private 中的 final storage snapshot，不因
  恢复时宿主计数变化产生假冲突；state、budget、results 与 assessment 仍须完整重建并匹配。v22 私有 aggregate
  到 tracked public projection 的只读重放一致。
- schema-v3+ 仍只对 task-local/global circuit breaker 豁免 `provider_response_integrity`；逐轮最多 2 项最终
  infra 的门禁恢复统计所有 infra，并在进入下一轮前停止。
- 合并路线中的 Plan 015 已由 GGUF 冻结占用，Plan 019 用于 L2a；本 B7 ExecPlan 改为 Plan 020。WBS 统一为
  “B4—B7 执行完成、B7 有效 failed 基线、E-A 未实现、M2 未达成”，只允许诊断三项 A/B 差异，不解锁方向 1
  正式优化。
- 本批只运行离线 Python focused tests 与只读 v22 projection 检查；未调用 Docker、真实 API、Cargo，也未触碰
  L2a 阶段 B 的运行进程、锁或工作树。
- 验收：focused unittest 57/57，`just eval-lock` 为 85 packages；worktree 的空 `eval/.venv` 使首次
  `just eval-test` 缺少 Harbor，未改写该环境。确认 worktree/main `uv.lock` 字节一致后，使用主工作区锁定的
  Python 3.12.3 / Harbor 0.20.0 对本 worktree 源码运行同一离线 unittest discovery，456/456 通过。
