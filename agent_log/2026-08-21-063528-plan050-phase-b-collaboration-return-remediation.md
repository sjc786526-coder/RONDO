# Plan 050 阶段 B 协作返回漏报窄修

## 结论

C01 RONDO 的协作漏报真实存在，已完成本地窄修、正反回归和既有付费资产重归约；未重跑 API 或替换任何有效结果。
当前候选等待独立复验。更正后 C01 RONDO 为 `collaboration_observed / not_observed`，C03 RONDO 保持
`collaboration_observed / observed`；总览为 2 个 `collaboration_observed`、4 个 `policy_noncompliance`，影响链为
1 `observed`、5 `not_observed`。

## 修复与证据

- 原聚合只把 completed member-to-Root `agent_result` 计为贡献交回，遗漏同方向、同样 typed 的 completed
  `send_message`。C01 RONDO 的 Team View 机械字段显示 1 个 accepted member、7 次完成推理、7 次完成的非协作工具、
  1 次 completed member-to-Root `send_message`，Root 在消息后仍有一次完成推理。
- `member_result_returned` 现在接受 completed member-to-Root `agent_result` 或 `send_message`；实质成员活动仍是独立必需
  条件，纯 spawn/message 不会被判为合规协作。回归同时覆盖“实质活动 + message、无 agent_result”为正例，
  “有活动但无任何返回”和“只有 message、无实质活动”为反例。
- 从冻结的 13 条 records 与六份既有 Team View 重建 aggregate；未展开正文 trace。旧的错误 C01/overview 派生文件按已知
  digest 精确替换，其余 cases、run、Team View、账本和 verifier 结果保持不变。

## 验证与边界

- `tests.test_explicit_eval tests.test_proactive_eval tests.test_team_lens` 共 75 项：73 通过、2 个既有可选 Plan 049 真实样本
  skip，无失败。
- aggregate 仍为 13 attempts、6 个有效终态、4 成功、2 有效任务失败、7 infra invalid、无缺槽/半对。37 个正式
  aggregate/record/run/Team View/case/overview 值通过 body-free 与对应 schema 校验；finalizer 同输入重入 digest 不变。
- aggregate digest 为 `50502a6ba68b47b9cf0a4502ce211c094e8c9aafba051dec44645c126971814a`；C01/C02/C03 为
  `7729a9361edc13a442e06477706ee322244b7b946757433b597eca53a69d1111`、
  `bcd2697e931d967f52db42339d60f29f52a0163dafc160d3727085e71da27ca4`、
  `0d373519342dcf922986977f9afdf6790c8248943bf78ee86dfb30590a51931d`；overview 为
  `b02ad9424139ddeda75a83bede08a42db623a11e2d078872f6e8ddb80b4178f9`。
- 本轮 ignored 写入仅更新 `eval-data/plan-050/paid/plan-050-paid-v1/aggregate.json`、`cases/C01.json` 与
  `overview.json`。未读取 secret、未运行真实 API、Docker、Cargo、本地模型、全量测试、CI 或 PR；费用、资源状态和
  165/165 请求结算均未改变。
