# Plan 044 / M-5 v6 整改独立验收

- 日期：2026-08-20
- 验收对象：`17a5205358a446620b12e6299cc03ba5874ad67a`
- 范围：正式大规模付费测评前的 workflow-v6 / nondegradation-v6、Gate 1/2 判据、capture 隔离、provider 前置冻结与断点续跑
- 边界：只读审查有效代码；未调用真实 API，未运行 Docker、重型 Cargo 或正式测评；仅新增本报告

## 结论

**NO-GO。验收不通过；本轮“完成正式付费前整改”的任务目标失败。**

整改已经关闭上一轮的大部分真实问题，但仍有 3 组 P1 阻断：Gate 1 的冻结协作协议仍可假通过；恢复逻辑会把已持久化的终止型预算停止误当作可重试 infra；正常的首请求前中断会因 runner 自己留下的局部产物而永久失去恢复出口。因此目前不能开始正式 Gate 1，更不能开始 Gate 2。

当前正式 v6 archive、ledger、隐藏锁、identity receipt 和 `m5-g1-v6-paid-a1..a6` capture 均不存在；本轮没有产生费用，也没有污染正式历史。M-5 仍为未通过，Gate 1 / Gate 2 均未启动。

## 阻断项

### P1-1：Gate 1 判据仍未完整约束冻结协作协议

`eval/rondo_eval/multi_m5/predicates.py` 已补强成员证据下钻和第二次发布，但仍缺少三个互相关联的约束：

1. Root 的 `wait_agent` 只检查调用线程、完成状态和返回文本，没有和首次成员发布、Root 发布建立完成时序。当前正向 fixture 中 wait 的 trace 序号甚至晚于第二次成员发布，仍被判绿。
2. 第二次成员 `team_publish` 的返回对象没有被要求使用不同于首次发布的 `version_id`；只要 dump 中另有一条无关成员版本，第二次调用复用首次版本仍能通过。
3. `team_route` 只核对 event/target，不核对调用者是否是 manifest Root；成员自己 route 也会被计为 `root_routed=true`。

独立内存反例结果：

```text
late_wait_passed True wait_seq 6 second_publish_seq 5
reused_version_id_passed True predicates {...全部为 true...}
member_routed_passed True team_route True
```

这意味着正式付费样本可以在没有真实执行“成员首次发布唤醒 Root → Root 协调/route → 成员证据下钻并追加不同版本”的情况下被计为通过，直接影响 Gate 1 正确性。

最小整改要求：

- trace 为嵌套工具调用保存完成序号，而不只保存开始序号；按完成/开始边界验证首次成员发布完成后 Root wait 才完成，随后才允许 Root publish/route。
- 将 Root publish 和 route 的调用线程绑定到 manifest Root。
- 要求第二次成员发布返回的 `version_id` 与首次不同，并与同 event、同成员、同 thread 的 dump Version 对应。
- 增加“wait 完成过早/过晚、复用首次 version_id、成员代替 Root route”三个负例；不得靠放宽模板规避。

### P1-2：requested-but-unarchived 恢复忽略终止型预算停止

`eval/rondo_eval/multi_m5/resume.py` 的 `claimed_run_disposition` 对任何已有请求但未归档的 run 都返回 `abandon`，Gate 1/2 随后将其归为可重试 infra 并继续下一 attempt。它没有先读取 ledger 已持久化的 `stop_reason`。

独立隔离复现：

```text
stop_reason budget_capacity_exhausted disposition abandon
```

因此，如果进程在预算代理已经持久化 `budget_capacity_exhausted`、但 archive 尚未 fsync 的窗口退出，恢复会把本应终止批次的预算停止改写成 infra，然后继续产生请求。这违反 nondegradation-v6 的 `budget_and_capacity_stops_remain_terminal` 合同。虽然用户的中转余额固定，这仍是运行控制语义错误，并可能让归档错误地声称是普通设施重试。

最小整改要求：

- disposition 先读取并分类 ledger stop；budget/capacity 类必须幂等归档为 `budget_stopped` 并终止，不得领取下一 attempt。
- 只有合同明确允许的 request-cap、interrupted request、taint/infra 类才转为 abandoned infra；未知 stop fail-closed。
- Gate 1/2 各补“已有请求 + 无 archive + terminal budget stop”的恢复回归，并验证执行器零调用、第二次恢复不重复追加。

### P1-3：首请求前的正常中断无法恢复

v6 允许 pristine claim 安全重领，但当前实现只要发现 conflict path 就拒绝。问题在于这些 path 会由 runner 在正常流程中、首请求之前创建：

- Gate 1 在 claim 后、启动被测进程和首请求前创建 capture/`rollout-trace`。
- Gate 2 在 claim 后、首请求前创建 meta/staging 等 run-owned 产物。

若此窗口进程被终止，ledger 仍是零请求、零费用的 pristine 状态，但下一次启动会因为这些由自己创建的局部产物永久报 `ResumeError`。这正是本轮新增断点续跑要解决的高概率窗口，不能仅以“发现冲突所以安全拒绝”视为完成。

最小整改要求：

- 明确定义“pristine ledger + 精确属于该 run_id 的已知局部产物”为可恢复状态。
- Gate 1 可校验后安全退役该 capture 并重领，或落一条 zero-request abandoned infra 后转下一 attempt。
- Gate 2 可校验并清理/退役该 run 的 staging 与本轮创建对象后重领，或同样记录 zero-request abandoned infra 后前进。
- 未知产物、符号链接、身份不符及非 run-owned 冲突继续 fail-closed。
- Gate 1/2 各补一次“claim 后、首请求前中断”的回归。

## 已确认正确的部分

- workflow-v6 / nondegradation-v6 已冻结为 6 次 Gate 1、每槽 5 次 infra、全批 40 次 infra、116 槽、60 个有效样本、80 请求/run、HTTP retry 5、共享硬上限 `$120`；点估计 `$10.40`、放宽后保守预测 `$67.80`，主线一致。
- v6 继续引用未变化的 runtime-v4；v5 两个锁和 runtime-v4 的 blob 未被改写。
- 正式 capture 已改用 v6 namespace；测试使用临时 capture，`persist=False` 不再静默写正式路径；非空目录和符号链接在消费前拒绝。
- provider 冻结校验已经移动到账本打开和 run claim 之前；同一 v6 Gate 1 pass 才能进入 Gate 2 的主线已接通。
- v6 rehearsal 的 archive 与 raw verdict event_id 一致；旧 v5 archive 未被覆盖。但由于 P1-1，当前 rehearsal 只能证明线路运行，不能证明判据已经完整。
- 独立轻量复跑：`MultiM5PredicateTests` 14/14、`MultiM5ResumeTests` 11/11，共 25/25 通过。绿色结果没有覆盖上述反例，所以不能抵消阻断发现。执行者报告的 162/162 未在本轮重复全跑。
- 工作树在写入本报告前为 clean；主工作区 `main=origin/main=45efac6` 干净，measurement-v4 tree 也干净。未合并、未推送。

## 替用户作出的决策

1. **暂不授权正式付费 Gate 1/2。** 这不是账本保守程度问题，而是有效样本判定和恢复功能仍可能做错；修复后仍须按项目安全边界由用户明确授权真实 API。Gate 2 继续只在同一 v6 Gate 1 通过后单独进入。
2. **保留 workflow-v6 / nondegradation-v6，不为本轮窄修另起 v7。** 现有 v6 文本合同已经要求正确协议与 terminal stop；当前问题是实现未满足合同，且尚无正式 v6 付费证据，直接做兼容性修正更干净。
3. **修复后使用新的 append-only rehearsal run identity（例如 v6-r2），保留现有 rehearsal 记录，不覆盖历史 raw/archive。**
4. **保持测试串行，不扩建设施以追求并行安全。** 修复后只需串行运行三个 M-5 Python 模块（计数应为 162 或随新增负例合理增加）、eval-lock、ready、loopback 和一次新 rehearsal；无需重跑 Rust 146、Docker 或真实 API。
5. 授权表中补写精确 endpoint、Harbor 已有 Docker evidence 在后续 parse 失败时仍应保留，均列为低成本 P2；不单独扩大成新设施，也不掩盖上述 P1。

## 再验收条件

1. 关闭 P1-1 的顺序、actor、不同 version_id 三类假通过，并补对应负例。
2. 关闭 P1-2 的 terminal stop 误分类，Gate 1/2 恢复均保持终止语义。
3. 关闭 P1-3 的首请求前中断死路，同时保持未知/非本 run 冲突 fail-closed。
4. 串行通过上述轻量门禁，生成新的可下钻 rehearsal，复核正式 v6 ledger/archive/receipt/capture 仍未启动。

达到这些条件后再做一次窄范围独立复验；通过后才可向用户申请正式 Gate 1 付费授权。
