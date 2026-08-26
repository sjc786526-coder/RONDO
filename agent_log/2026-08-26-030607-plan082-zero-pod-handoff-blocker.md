# Plan 082 Pod 释放与 0 Pod handoff 外部阻断

时间：2026-08-26 ｜ 状态：`GPU_REVIEW_PASS / ZERO_POD / HANDOFF_EXTERNAL_BLOCKED`

## Pod 与费用终态

- 最终审查者明确回复“无需继续操作 GPU，可以立即释放 Pod”后，精确核对账户唯一 Pod/卷身份并删除
  `91e9o2l0im1ay2`。2026-08-26T10:00:29Z 控制面确认 `pod_count=0`、持续 compute 费率为 0；唯一网络卷
  `mwemzrn33y` 仍为 US-TX-3 40GB，未删除、改名、迁移或扩容。
- provider 当时只返回两个延迟部分账单桶，共 `$0.4285083329`；按从创建到删除的完整 elapsed L40S 时间、`0.99 USD/h` 和存储留量，
  累计保守上界 `< $1.60`，远低于 10 USD 告警线。网络卷按 provider 当前 `$0.07/GB/month` 继续产生约 `$0.00384/h` 存储费。

## 0 Pod handoff 尝试与诊断

- Plan 083 已完成且 worktree clean；共享构建锁可用、0 个重型 scope/Cargo 进程。传输前 RONDO 项目实占
  `254,426,943,488` bytes，Windows C: 真实可用 `75,188,027,392` bytes；39 对象共 `13,797,142,360` bytes，预计落盘后仍低于
  270GB 门，不需要清理任何 Cargo 工件。
- 生成本轮参数化 binding：卷 `mwemzrn33y`、region `us-tx-3`、endpoint `https://s3api-us-tx-3.runpod.io/`、task root
  `rondo-plan082-20260826-stageb01/`、正式 prefix、ignored destination 与 bootstrap 14,524 bytes /
  `e658b7f71aee1bb356d964f787eabcfe74f61482c40913ab9f8d89acb127714f`；binding SHA-256
  `8ee44ad692963b3eeb81ff7dc355cbd94c75553441698bb6f7dd1d19275b0257`。inventory/download 双 dry-run 均绑定 exact worktree、固定 7 包
  venv，并返回 `secret_access=false`、`network_access=false`。
- 真实 inventory 使用既有严格 loader 静默注入两个 allowlisted S3 凭据，在 bootstrap `HEAD` 阶段返回 `handoff_head_failed`，未创建大型
  本地文件。相同 loader 的最小 HEAD/LIST 诊断均在请求前产生 `SSLError`；无凭据 curl 也在公开 endpoint TLS 建连时返回
  `SSL_ERROR_SYSCALL`，因此不是 bootstrap key/bytes/hash 或本地凭据输出路径问题。
- RunPod 当前官方 S3 API 文档的支持数据中心列表不含 US-TX-3，并明确卷必须创建在支持的数据中心；network-volume update API 仅允许
  name/size，不能迁移 data center。这与 TLS 诊断一致。没有关闭 TLS、猜测其它 region endpoint、读取/打印凭据、创建 Pod/卷或下载
  checkpoint。

## 需要的新授权

现有合同禁止为传输重建 Pod，而 provider 也没有已授权的 0 Pod 路径。最小可执行替代是：若 reviewer 取得用户扩围批准，仅创建一个
US-TX-3、挂载现有卷的临时单卡 L40S Pod，不训练、不加载模型、不建第二卷，只用 resumable SSH 传回 bootstrap 精确列出的 39 对象，
逐对象校验 bytes/SHA-256 后立即删除并再次确认 0 Pod；预计仍远低于 15 USD。未获明确批准前保持 0 Pod、保留卷并继续记录卷费。
