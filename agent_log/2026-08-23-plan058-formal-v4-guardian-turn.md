# Plan 058 formal-v4 Guardian intermediate-turn gap

从 clean `8f2f0838cf1b755067f2ffea47866a1942baa933` 重建并复验 runtime 后，
`plan058-direction1-c2-formal-v4` 按冻结顺序完成零 API preflight `10/10`。首个正式槽 8 的 attempt 1 在
7 次 main 请求后发生 `upstream_clean_eof`；runner 正确保留 7 次 attempts、`1.187595 USD` 和 transport receipt，
并以同一逻辑槽的全新 physical attempt 自动重试。

attempt 2 完成 18 main、3 Guardian 请求。Guardian 前两个 review 形成 approval；第三个已付费请求进入 review
内部 code-mode/tool 中间轮次，尚未产生 terminal decision，第 4 次请求随后被冻结的本地上限以
`guardian_logical_request_limit_exceeded` 拒绝。agent exit `1`，但 Harbor verifier 完整运行并给出 reward `1`。
旧 Plan 058 matcher 错误要求 3 个已发送 Guardian 请求各有 terminal evidence，再额外有一个 failed-closed；真实
形状只有 2 个 terminal approval 和 1 个未发送的上限请求 failed-closed，故有效 task pass 被误判为
`terminal_bench_infrastructure_failed`。formal-v4 已永久作废、body-free 发布为 `0/20`，不得复活或拼接；共
28 upstream attempts、1 transport retry、`1.924235 USD`，累计 task budget `12.499077 USD`、reserved `0`。
Docker/VHDX 增长 `0`，Windows C: 最终余量 `202307883008` bytes。

修复不改变 Guardian、审批或安全策略，只校正本地结果分类：仍要求精确 agent exit `1`/tee `0`、预算停因、3 个
唯一 Guardian API metadata、verifier 结果，以及唯一额外 failed-closed/session-error；所有已有 terminal evidence
必须是已发送 metadata 的子集，从而允许预算内请求用于 Guardian 自身的中间工具轮次。formal-v4 真实工件离线
复验为有效 `agent_failed`/reward `1`；C2、预算代理和 Terminal-Bench 结果相关回归 `159/159` 通过。按局部
commissioning 合同，下一步只用新 diagnostic 复验槽 8，再从新 clean source 重建并启动全新完整 formal。
