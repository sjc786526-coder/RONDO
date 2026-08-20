# Plan 044 / M-5 v6-c2 纯执行环境整改

- 日期：2026-08-20
- 边界：不修改 workflow-v6、runtime-v4、nondegradation-v6；未运行 Rust、Docker、真实 API smoke 或付费推理
- 原因：v6-c1 六次均在模型输出前被开发工具 sandbox 的 local/private-address 策略阻断

## 实现

- 新增 `multi-m5-v6-c2` campaign generation，不是行为合同 v7。c2 独占 receipt、ledger、archive、capture 与
  run-id；formal identity 绑定 generation、provider、三把 v6 锁、clean harness commit 和跨代预算字段。
- generation manifest 固定 c1 ledger/receipt/archive 三摘要及终态语义。用户确认 c1 中转站实际账单 `$0`；
  本地仍保留 `$13.32` conservative exposure，c2 ledger cap 为 `$106.68`，两代共享上限仍为 `$120`。
- 正式 Gate 1/2 在 secret、receipt/ledger/claim/capture/Docker 前运行同进程无密钥 GET：精确冻结 endpoint、
  单次 15 秒、无 Authorization/body、禁环境 proxy 与 redirect；任意 HTTP status 仅证明可达，网络/TLS/timeout/
  sandbox 错误 rc78 且不消耗 attempt。
- Gate 2 在 secret、heavy lease、Docker counter 和 ledger open 前只读证明 c2 receipt、连续 Gate 1 pass 前缀及
  已存在 ledger；runner 内仍二次核 archive/ledger，防 TOCTOU。
- clean harness 检查包含全部未跟踪文件，避免漏提交 campaign lock/loader 仍被标作 clean；ignored eval-data 不计脏。

## 零费用验证

- M-5 执行设施 112 项；判据与 trace 81 项；合计 193 项定向门禁。
- `just eval-lock`、`just eval-multi-m5-ready`、runtime-v4 loopback 通过；ready 为 c2 `not_started`，并证明
  `$13.32 + $106.68 = $120` 且 c2 cap 覆盖 `$67.80` 最坏调度形状预测。
- 同一 `provider-connectivity` CLI：sandbox 内 rc78，随后核对 c2 receipt/ledger/archive/capture 全部不存在且 c1
  三摘要未变；批准的 sandbox 外运行得到 unauthenticated HTTP 301、rc0。
- 完整 193 项串行重跑 `OK`；测试内 `just` 子进程使用测试专属可写 runtime 目录，不再依赖宿主
  `/run/user/1000` 可写。独立终审未发现剩余 P0/P1，代码面 GO；正式执行仍要求先提交全部文件并得到 clean identity。

## 当前边界

零费用设施验证已完成。正式 c2 尚未创建任何资产或发出模型请求；待本次改动形成 clean harness commit 后，
按用户授权从 sandbox 外启动 c2 Gate 1，仅在同一 v6 通过且身份未漂移时继续 Gate 2。
