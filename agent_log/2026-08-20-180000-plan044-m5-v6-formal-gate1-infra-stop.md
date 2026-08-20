# Plan 044 / M-5 v6 正式 Gate 1 终态

- 日期：2026-08-20
- 授权：正式 Gate 1；仅在同一 v6 Gate 1 通过且合同、代码、provider 未变化时继续 Gate 2
- 冻结身份：workflow-v6 → runtime-v4 (`0eee6dc`) → nondegradation-v6；harness `ae3fc86`

## 结果

**Gate 1 未通过，Gate 2 未启动。** 正式批次按授权停止，没有得到产品结论或 M-5 结论。

正式 `m5-g1-v6-paid-a1..a6` 六次尝试均只发出一个 Root 请求，随后以
`infra_failed / upstream_unavailable` 归档；六行均 `passed=false`、`request_count=1`、
`returncode=1`、`infra_taint.first_reason=upstream_unavailable`，没有 `agent_failed`、`completed`
或有效协议样本。代码、合同、runtime 和 provider receipt 未漂移，`harness_dirty=false`。

直接原因是正式命令运行在开发工具的 workspace sandbox 中；`www.cctq.ai` 在本机解析到
`127.0.0.1`，sandbox 按 local/private address 阻断，故请求未到达本机 relay。沙箱外无密钥
HTTPS 检查成功连接同一地址并得到 HTTP 404，TLS 校验为 0，证明阻断位于执行边界而非模型或
RONDO 产品。这里不把设施失败改写为产品失败，也不删除、覆盖或重领已归档尝试。

## 预算与资产

- v6 archive 恰好 6 行，attempt 1..6 连续；6 个 request 均 `settled`，`usage_valid=false`，
  `settlement_kind=conservative_reservation`。
- provider 可计价使用量为 `$0.000000`；账本按每次 `$2.220000` 保守结算，累计暴露 `$13.320000`，
  低于共享 `$120` 硬上限，且没有未结算 reservation。
- Gate 2 没有 run、archive 或 Docker 资产；未拉取、创建或运行镜像、容器、网络、卷。
- a1..a6 capture 与正式 receipt/ledger/archive 保留为 append-only 失败证据，不清理、不改写。

## 停止边界

本轮授权明确要求 Gate 1 未通过即停止，因此没有在沙箱外重跑，也没有启动 Gate 2。现有 v6 正式
attempt 空间已耗尽，不能把同一批次再次执行伪装成 resume。若以后重启正式评测，须另立批次身份，
先保证付费进程在已批准的沙箱外网络边界运行，再取得新的付费授权；不得复用本轮失败批次冒充通过。
