# Plan 097 最终独立验收

日期：2026-08-28 00:44 PDT ｜ 返修基线：`worktree-097-m3-d-dual-backend-engineering@161be6d` ｜ 初审：
`agent_log/2026-08-28-001531-plan097-independent-review.md`

## 结论

**验收通过 / 任务目标完成。** 最终复验未发现新的 High、Medium 或 Low correctness/functionality finding；初审 4 Medium / 1 Low 均已窄修并
形成相称回归。Plan 097 正式终态接受为
`M3_D_DUAL_BACKEND_ENGINEERING_PASS / FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED`。

该结论只表示工程链与双 backend 可替换性 GO，不改变模型和产品锁：本地模型质量 `NO-GO / 待替换`、cloud scorer `NOT QUALIFIED`、M3-D
产品价值未验收、Publication Critic 默认 `OFF`、生产启用 `NO`。

## 返修复核

- cloud scorer ledger 现在于每次 reserve、settle、snapshot 时取得 OS 文件锁并 fresh reload、校验和原子落盘；代码审查确认 reservation 在
  provider 请求前持久化，进程中断仍按 1 RMB 保守占位。除执行者两实例回归外，本审查以 16 个独立实例并发 reserve，得到 1–16 唯一 attempt，
  snapshot 保留完整 16 RMB 保守额度。
- finalizer 从当前非密钥 runtime config 投影 Producer provider identity，要求 local/cloud receipt 的 profile SHA-256、model、effort 彼此相等且
  等于该投影，并写入 final summary。历史两份 formal receipt 与当前配置均为
  `29e0cded5a50f3f4666a6b915ac883f825c479ccadcd8a50bfcd25f9ffc8df98 / gpt-5.6-terra / low`。
- scorer service 仍执行有界清理，但 shutdown probe 失败/未接受、提前或非零退出、graceful timeout、SIGTERM/SIGKILL 或未 reap 均不能生成成功
  receipt；只有 accepted、graceful、zero-exit 才投影 `shutdown_outcome=graceful`。聚焦反例覆盖 probe failure、提前退出和强制回收。
- local contract/descriptor threshold 已恢复权威 `0.9350569011196121`，测试直接绑定权威常量；tracked archive 诚实保留
  `formal-5` 历史低 1 ULP 值，并明确旧 service receipt 只证明 process reaped，没有伪造或改写 raw receipt。
- 初审点名的两个私有临时目录与一个 ledger temp 已精确删除；Plan 097 根下同类 producer/packet/temp 前缀复核为零。正式/commissioning
  receipts、预算 ledger、共享 target/cache 和其他任务资产均保留。

## 证据与验证边界

- `8dc768e..161be6d` 只包含上述设施窄修、回归和职责内文档更新；`git diff --check` 通过，097、main、093、095、096 tracked worktree 均 clean。
- 本审查独立运行全部 Plan 097 Python 单元测试 `51/51`，并运行上述 16 路 ledger 并发检查；未重跑 Cargo、Rust process tests、全 workspace、真实
  API、Producer、真实本地模型、Docker 或 RunPod。接受执行批次已有 13/13 Rust process evidence 和本次 39/39 受影响回归。
- 物理根 formal-5 的 result/local/cloud SHA-256 仍分别为 `91a191f0...9b57`、`50106108...d52`、`6e418b60...9ec5`；两份 Producer identity
  一致，费用总账仍为 `21.4197186 RMB / 30 RMB`。当前 local descriptor SHA-256 为 `78aa4d94...8c90`，与归档声明一致。
- 历史 formal service receipt 没有 graceful outcome 字段。按初审已作出的裁定，本次以“历史真实进程已 reap + 既有 process tests + 修正后的
  lifecycle fail-closed 回归”接受，无需为验收设施修复重新产生模型/API费用；归档不得把旧 receipt 改写为 graceful 证明。

## 代用户作出的决策

1. 接受保留 `plan097-formal-5` 作为真实工程正式轮，不要求重新付费或重新加载本地模型；其 threshold 与 shutdown 证据局限已在结果中显式降格，
   不影响已观察到的 OFF/local/cloud、rewrite/commit/fallback/cancel 工程事实。
2. Plan 097 的一次性本地模型、真实 API 与 Producer 授权随本次验收关闭，未用余额不向未来任务转移。未来模型替换、质量资格、产品价值验证或生产启用
   必须另立任务与授权。
3. 当前只提交 097 本地分支；未经用户批准不合并、不推送、不归档/重命名分支，也不删除 worktree。执行者没有遗留其他需要用户确认的技术决策。

## 最终状态

- 验收：**通过**。
- 任务目标：**完成**。
- 工程链：**GO**；双 backend 可替换：**GO**。
- 本地模型质量：**NO-GO / 待替换**；云端 scorer：**NOT QUALIFIED**；M3-D 产品价值：**未验收**；默认：**OFF**；生产：**NO**。
