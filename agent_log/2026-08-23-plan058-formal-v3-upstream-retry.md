# Plan 058 formal-v3 upstream retry gap

从 clean `ad0d81ad68c16c7d8a90d94d744b9b3eb1bdad4c` 重建并复验 legacy、companion、bwrap 与 runtime
bundle 后，`plan058-direction1-c2-formal-v3` 按冻结顺序完成十题零 API preflight `10/10`。恢复构建期间有三次
Docker/API 前的 fail-closed：开发沙箱禁止 systemd user bus、attached source 被 companion 冻结门拒绝、同一
metrics parent 含失败与成功 summary 后被单 proof 门拒绝。旧 metrics 全部保留，最终 manifest 只绑定全新
identity 下各自唯一的成功 watchdog proof；CLI/host/bwrap SHA-256 为 `ff6273bb34ea8749747d0499abc173bb0686dee4553dd10def684795998455fa`、
`b642f82b0346f19c4d19b1b27ddb440f153c6ff70ea24a1c6de5bfc9c3484f97`、
`77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`。

首个正式槽 8 的前 6 次 main 请求均为可靠 `response.completed`，第 7 次由上游返回 HTTP 200 的终态
`response.failed / status=failed / code=upstream_error`，没有可靠 usage，按冻结规则结算 `1 USD` fallback。
agent 随后非零退出，但 Harbor 继续 verifier 并得到 reward `0`。现有 Plan 058 classifier 只把 open/read/clean-EOF
和瞬态 HTTP 识别为 pure transport，漏掉该明确上游终态，因此 runner 以
`terminal_bench_infrastructure_failed` 作废 campaign。formal-v3 已永久发布为 invalid、正式结果 `0/20`；7 个
main attempts 共 `1.074850 USD`，累计 task budget `9.851674 USD`、reserved `0`。Docker/VHDX 增长 `0`，
Windows C: 最终余量 `201641660416` bytes。

修复只接受 `status=200`、`stream_end_kind=terminal`、`response.failed`、响应 status `failed` 且错误码精确为
`upstream_error` 的组合，生成 body-free `upstream_terminal_failed` retry evidence；`model_failed`、context、鉴权、
配额、配置和未知错误仍拒绝重试。相关 unittest `33/33`、compile 与 diff check 通过；formal-v3 的真实 body-free
metadata/账本可只读重投影为 7 attempts、`1.074850 USD` 的 typed pure transport。下一步只以新 diagnostic-v6
复验槽 8，再从新 clean source 重建 runtime 与全新 20/20 formal；不复活或拼接 v3。
