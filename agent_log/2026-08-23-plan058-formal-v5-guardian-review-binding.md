# Plan 058 formal-v5 Guardian review binding

从 clean detached source `62387ad1f3e8cdde1eb17fdc95b37ccdd7c36070` 经共享 lock/watchdog 重建
formal-v5 runtime。首次 companion publication 误用 attached source，被 BinaryFreeze 正确拒绝；第一次 legacy
构建虽成功，但其 source gate root 与 detached companion 不同，未用于最终 runtime。随后 legacy/companion 均从同一
detached root 重建，prepare/verify legacy、companion、bwrap 与 runtime 全部通过。CLI/host/bwrap SHA-256 分别为
`d88a225b82fcd0bb00e990cea02b55b78417aac371aed5c39bbbaba31e4f3437`、
`75d684e6c568cc224af74f7075deffef13765ec8ef07f264e21c8d124b63224d`、
`77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`，runtime manifest SHA-256 为
`39dfc87701a36b1275819bc89bf20432ce5fa15f1f0245ecb75a871d90d56c8e`。失败/弃用 proof 均保留且发生在
Docker/API 前，没有混入冻结 runtime。

`plan058-direction1-c2-formal-v5` 按 `8 → 18 → 1–7 → 9–17 → 19–20` 冻结，零 API preflight `10/10`。
第 6 个执行位置（绝对槽 4，`fix-git`）实际 agent exit `0`、verifier reward `1`，但本地 validator 把连续的
Guardian API turns 逐个要求终态证据，因而在结果投影阶段 fail-closed。真实序列含 3 个 Guardian 请求、2 个 logical
review 和 2 份终态证据：同一 review 的中间工具 turn 不产生独立 terminal evidence。formal-v5 按本地设施故障永久
作废，公共正式结果 `0/20`；77 个可靠 attempts、0 transport retry、费用 `1.758825 USD`。Plan 058 累计费用
`15.158073 USD`、reserved `0`、剩余 `34.841927 USD`。Docker/VHDX 增长 `0`，Windows C: 最终余量
`201226924032` bytes。

修复保持原始 Guardian 请求计数用于预算和三次硬上限，只将连续 Guardian turns 分组为 logical review，并把每份
终态 evidence 绑定到该组末次请求。Guardian、审批、sandbox、安全策略和历史结果身份均未改变。相关结果、pair 与
Plan 058 回归 `105/105` 通过；用 formal-v5 第 4 槽真实私有工件离线重验证得到 `completed`/reward `1`、
3 requests、2 reviews、2 evidence、binding valid。按正式故障合同不复活或拼接 v5，修复后只以新 diagnostic
复验受影响的绝对槽 4，再重新冻结全新 formal。
