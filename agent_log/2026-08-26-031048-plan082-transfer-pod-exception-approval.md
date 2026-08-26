# Plan 082 一次性 transfer Pod 例外批准

时间：2026-08-26 ｜ 状态：`TRANSFER_POD_EXCEPTION_GRANTED`

## 核对

- RunPod 控制面只读确认当前账户 0 Pod；网络卷 `mwemzrn33y` 仍为 US-TX-3 40GB Standard。当前 L40S 库存为 `LOW`，费用为
  Community 0.79 USD/h、Secure 0.99 USD/h；创建前仍须实时刷新 CPU/单卡 GPU 兼容性、库存、费率和费用基线。
- provider 已入账 Plan 082 原训练 Pod `91e9o2l0im1ay2` 两个小时桶，共约 0.594 USD；卷的当前已入账小时桶约 0.00389 USD。
  账单仍可能延迟，但远低于 10 USD 告警线。
- RunPod 官方 [S3-compatible API 文档](https://docs.runpod.io/storage/s3-api)当前支持数据中心列表不含 US-TX-3，并要求网络卷位于受支持
  数据中心；[network-volume update 接口](https://docs.runpod.io/api-reference/network-volumes/POST/networkvolumes/networkVolumeId/update)
  只允许 name/size，不能迁移 data center。执行者的 TLS 阻断判断成立，继续猜 endpoint 或关闭 TLS 不合理。

## 用户人工授权与审查者决定

用户本人明确批准 `TRANSFER_POD_EXCEPTION_GRANTED`，审查者采纳并通过指定队列传达。执行边界如下：

- 同时至多一个能挂载现有卷 `mwemzrn33y` 的临时 transfer Pod；实时兼容且可用时优先最低费用 CPU，否则可选费用合理的任意单卡 GPU，
  不受训练阶段 A40/L40S 型号限制。
- Pod 只读取现有卷并回传、续传、校验 bootstrap 冻结的 39 个正式对象及必要小型证据；不得训练、加载模型到 GPU、改变正式结果、
  创建第二卷、删除或修改远端 checkpoint、原始数据及其它工件。
- 普通连接、依赖和续传问题可自主修复；实例失效时须先确认旧 Pod 已不存在，才能替换一个兼容实例。不得并行保留多个 transfer Pod。
- 创建前记录实例类型、费率、费用基线；继续合并记录任务费用，累计实际或保守上界首次达到 10 USD 时按合同非阻断告警。
- 完成后逐对象核验 bytes/SHA-256，立即删除 transfer Pod并确认 0 Pod、持续 compute 费率为 0。网络卷继续保留，未经用户本人另行人工
  批准不得删除。
- 无法挂载现有卷、需要第二卷/并行 Pod，或预计突破既有费用边界时必须重新请示。本例外不恢复训练授权、不允许改变正式结果或扩大
  工件集合。

当前研究结论仍为 `VALID_NO_IMPROVEMENT`；大型资产交接和最终验收尚未完成，不合并、不推送、不归档分支。
