# Plan 044 / M-5 v6-c2 harness 假阴与 v6-c3 收口

- 日期：2026-08-20
- 边界：workflow-v6、runtime-v4、nondegradation-v6 字节不变；未运行 Rust、Docker、真实 API smoke 或 Gate 2

## c2 终态

- c2 从批准的 sandbox 外边界运行。a1/a2 分别完成 20/25 个 usage-priced 请求，却都因
  `direct model tool call is forbidden by the workflow` 归档为 `infra_failed`；同因复现后在 a3 第 4 个请求后
  中断，a3 无 verdict/归档。
- 原始 trace 证明 a1/a2 的顶层 Direct 仅为 code-mode runtime 继续 live cell 所需的默认 namespace `wait`；
  collaboration/team dispatch 仍全部来自 code cell。旧 blanket Direct 拒绝属于 harness 假阴，不是产品失败。
- c2 账本 49/49 request 均 settled、usage_valid、usage_priced、attempt_count=1，0 held；计价合计 `$0.661683`。
  archive 两行、a3 中断 capture、ledger 与 receipt 均保留原样，不回写为通过。

## c3 修复

- collector 只豁免默认 namespace 的 runtime `wait`，并机械要求内部/模型 call-id 相同、wire raw arguments
  逐字一致、同线程且 cell 已在 wait 前创建、参数类型/键集合合法。该调用不贡献任何协作证据；Direct team
  dispatch 继续 fail-closed。
- 新建 `multi-m5-v6-c3` generation，隔离 batch/run/receipt/ledger/archive/capture，并冻结 c1/c2 摘要与终态。
  c1 conservative `$13.320000` + c2 priced `$0.661683` = prior `$13.981683`；c3 cap `$106.018317`，累计硬上限
  仍为 `$120.000000`。

## 零费用验收

- M-5 三文件完整定向套件 199/199；其中 runtime wait 覆盖正例、未知/未来/跨线程 cell、call-id、raw arguments、
  参数形状与 Direct team 反例。
- `just eval-lock`、`just eval-multi-m5-ready`、runtime-v4 loopback 通过；ready 报 c3 `not_started`，三把冻结锁与
  provider 投影未漂移。
- 独立终审未发现 P0/P1；历史 c2 trace 用新 collector 重放后 dump 22/25、log 均 7、`unattributed=0`。

当前只允许在全部文件形成 clean commit、exact-commit ready 与无密钥 connectivity 再次通过后启动 c3 Gate 1；
只有同一 c3 Gate 1 正式通过才可进入 Gate 2。
