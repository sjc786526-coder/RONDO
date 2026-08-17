# Plan 042 / Multi M-3 验收审查整改

日期：2026-08-17 ｜ 分支：`worktree-042-multi-m3-evidence-anchoring` ｜ 提交：`35356ab`
对应审查：`agent_log/2026-08-17-045506-plan042-multi-m3-independent-acceptance-review.md`（结论：不通过）

四项缺陷全部复核确认存在，全部整改。

## 发布窗口超过上限时丢失锚点（P1）

我原本让 `take_publish_window` 把游标推进到完整窗口末尾，再只把最新 32 条写进 Version。游标已经越过更早那几条，
所以它们既不在本次 Version 里、也不可能被后续发布取得 —— 永久失去锚点。这是我自己在决策 020 里做的取舍，
**取舍本身是错的**：上下文预算不能改变不可变 authored 关联。

现在 Version 保留窗口的全部引用；上限只加在**打印列表的地方**：投影仍是 4 条 + 计数，
`team_publish` 与 `team_history` 改为 32 条 + `evidence_refs_omitted`，不再输出无界列表。
领域测试从"固化截断行为"改成断言"窗口消费的每一条都被锚定，且 canonical 记录能全部交回"。

## locator 不是一对一（P1）

原 locator 是 `producer + call_id + output_kind`，而 call_id 来自模型请求。四种后果都成立：
后一次调用的 Fact 描述第二次调用却解析到第一次的文本；并行时 note 顺序与保留顺序可能不同；
compaction 移除旧结果后同 ID 新结果会让旧 Fact **静默重定向**（本该报读不回来）；
若第一条来自被排除的团队工具，普通工具复用 ID 能把它错误锚定并随 Event 开放。

改为用 **Codex 为每个已保留 item 分配的身份**（`ResponseItemId`）定位，一对一。call_id 降为元数据。
关键论证：这个身份不需要跨重放稳定 —— 重放要复现的是 Fact 序号与每次发布携带的窗口，
那由序号机制保证并已有测试；locator 只需在本实例内唯一。捕获层能拿到它是因为 retention hook 收到的正是
即将写入的那批 item，身份此时已经分配好。

## 共享 pending 上限静默逐出（P2）

256 条队列全团队共用，满了 `pop_front`，可能把**另一个 producer** 即将保留的结果挤掉。
改为**按 producer 计**上限，逐出时记 `warn`。测试断言 worker 无论排多少都不会挤掉 root 的 note。

## PostToolUse 拦截后的失败文本不入集（P2）

`should_block` 分支在我的 note 之前提前 return。但拦截发生在 handler **已执行完成之后**，
它改变的只是模型得到的答案，而那个答案会作为该次调用的 `success=false` 文本被正式保留 ——
于是出现"调用完成、结果已保留、却没有任何东西能指向它"。现已纳入支持集；执行前的拒绝
（未知工具、PreToolUse 拦截）继续排除，因为工具没跑。补了一条带真实阻断 hook 的产品回归。

## 门禁（整改后重跑）

| 门禁 | 结果 |
|---|---|
| `just test -p codex-team-state` | 101/101 |
| `just test -p codex-core suite::team_evidence` | 3/3（新增 PostToolUse 拦截回归） |
| 合并 `suite::team_evidence`+`team_world_state`+`team_routing`+`team::evidence`+`tools::`+`context::` | 541/541 |
| `just fix -p codex-team-state -p codex-core`、`just fmt`、`just fmt-check` | 通过 |

新增/改写的定向回归：窗口消费的每条都被锚定且 canonical 记录全部交回；同一 call_id 的两次调用各自成 Fact
并各自解析到自己的 item（领域 + 真实 session 两级）；一个 producer 的暂存突发不影响另一个；
被 PostToolUse 拦截的结果仍可被 Version 引用并读回，类别为 failure、正文是模型实际看到的拒绝理由。

未运行：全 workspace、Docker、真实 API、本地模型、付费测评。功能仍默认关闭。
