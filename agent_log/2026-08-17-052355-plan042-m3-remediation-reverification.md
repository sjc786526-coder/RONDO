# Plan 042 / Multi M-3 验收整改独立复验

日期：2026-08-17 ｜ 复验对象：`worktree-042-multi-m3-evidence-anchoring@74a6843` ｜ 基线：`main@0c1a5e4`

## 结论

- **验收不通过**。
- **任务目标失败（当前提交仍未完整实现预期）**。
- 上轮四项中，canonical 发布窗口丢 refs 与 PostToolUse 失败不入集已经正确修复；item identity 也解决了已铸造 Fact
  的静默重定向。但 locator 修复只覆盖顺序复用，pending 上限只消除了跨 producer 相互挤占，且新增的 32-ref 输出上限
  没有可继续读取的 refs 分页。当前仍有两项阻断和一项边缘正确性缺口，不应合并或推送。

本轮未要求任何新审计、可信、资产存储或重型测试设施，只核对真实产品语义并运行最小定向门禁。

## 已确认修复正确

1. **canonical Version 不再截断发布窗口**：`take_publish_window` 返回并消费完整窗口，`publish` 把全部 refs 写入不可变
   authored 内容。原先“游标推进但旧 refs 丢失”的 P1 已关闭。
2. **已铸造 Fact 按 retained item identity 读取**：本地工具输出进入 history 前由 Harness 分配 `ResponseItemId`，Fact locator
   按该 ID 解析。顺序复用 `call_id` 时两条已铸造 Fact 可分别读取；旧 item 被 compaction 移除后也不会重定向到同 call ID
   的新文本。这个选择无需跨重放复用 locator ID；重放合同仍由 Fact retention 序号与发布窗口关联承担，因此接受。
3. **PostToolUse 拦截结果已纳入**：handler 已执行后的 `should_block` 在返回模型失败文本前 note，真实产品回归证明 retained
   failure result 能形成 Fact、写入 Version 并读回。未知工具与 PreToolUse 因执行前拒绝继续排除，接受。
4. **pending 上限改为 per-producer**：一个 producer 的突发不再逐出 sibling 的 note；这一部分修复成立。

## 阻断项

### P1：并行重复 `call_id` 仍会漏 Fact或把 metadata 配给错误 item

`note_observation` 仍按 `producer + call_id` 判断 pending 重复并直接丢弃后一个 note
（`team-state/src/store/evidence.rs:40-47`）；retention 时也仍按这个组合取 pending，再把当下 item ID 填入 locator
（同文件 `93-118`）。`ResponseItemId` 只让最终读取一对一，没有给 note 与 retained item 建立一对一配对。

现有测试 `a_reused_call_id_produces_separate_facts_pointing_at_separate_items` 实际先断言第二个同时 pending 的 note 没有槽位，
等第一个确认后才重新 note 第二次调用（`store/evidence_tests.rs:669-705`）；它覆盖的是顺序复用，不是上轮报告要求的并行复用。

可达后果：

- 两个并行普通工具复用同 ID 时只生成一个 Fact，另一个正式保留结果无 Fact；
- completion 顺序与 `FuturesOrdered` retention 顺序不同时，Fact 的 tool/category 来自一个调用，item locator 却指向另一个；
- 若 provider 顺序中的第一项是被排除的团队工具、第二项是同 ID 普通工具，而普通工具先完成并留下 pending note，第一项 retention
  可消费这条 note，使被排除的团队工具文本错误成为普通 Fact。

这仍违反 ExecPlan `30-37`、`52-54` 的权威 metadata、并发不丢失和非递归支持集。处理要求是让 dispatch note 带有可一路
关联到 retained item 的 Harness 身份，或采用等强机制；不限定具体 token、ID 或模块路线。

### P1：第 33 条以后的 canonical Fact refs 没有模型可达的有界读取路径

canonical Version 现在保存全部 refs，这一步正确；但 `team_publish` 与 `team_history` 都调用同一个
`reported_evidence_refs`，永远只返回列表前 32 条和 omitted 数
（`core/src/tools/handlers/team_tools/publish.rs:79-88`、`history.rs:77-86`）。`team_history` 的参数只有 Event/Version
分页，没有 evidence-ref offset/cursor，因此再次读取仍得到相同 32 条。

这意味着 Root 或 route 目标虽然在 canonical 权限上可以读取隐藏 Fact，却无法取得它的 ID，只能猜测。代码注释“read the rest
with team_history”以及 ExecPlan 决策 017 的“完整清单走 team_history”目前都不成立，也违反验收标准 `38-42`。

本轮决定：`team_publish` 保持 32 条预览可以接受；至少一个权限受控的读取面必须以游标/分页或等强的有界方式让 Agent 逐步
取得该 Version 的全部 refs。不得恢复无界输出，也不需要新建通用审计/浏览系统。

## 需要一并收口的边缘正确性缺口

### P2：per-producer 256 上限仍会丢同一 producer 随后正式保留的 observation

整改只把共享上限拆成 per-producer。达到 256 后仍删除该 producer 最旧 note，再写一条 tracing warning
（`team-state/src/store/evidence.rs:49-73`）；产品执行层仍没有每 producer/response 最多 256 个工具 future 的硬限制。
被逐出的结果随后进入 history 时不会形成 Fact。warning 是诊断日志，不是 Fact、Version 引用或模型可见的显式退化状态，
所以没有关闭原 P2 的“支持集结果静默漏铸”部分。

处理要求仍是：已完成且正式保留的受支持结果不能只因暂存上限消失。可以调整捕获配对或在明确生命周期边界清理真正遗留的
pending；无需真实启动 257 个 shell，也不要求取消所有资源边界。

## 代用户作出的决策

- 接受 `ResponseItemId` 作为当前 session 内的 observation locator；本任务不要求 locator 跨重放同值。
- 接受 canonical Version 保留全部轻量 refs，同时对模型输出设硬上限；但省略部分必须可通过有界分页取得。
- 不接受“per-producer + warn”作为丢 Fact 问题的完整修复；跨 producer 隔离正确，但同 producer 正式保留结果仍不能漏铸。
- 不接受并行重复 `call_id` 继续先到先得；`call_id` 来自模型请求，不能承担 Harness 的配对身份。
- 接受 PostToolUse 已执行后的失败文本纳入，未知工具/PreToolUse 继续排除。
- ExecPlan 决策 014 仍写着 PostToolUse 排除，与新决策 022 冲突；决策 017 仍声称 history 可取完整 refs。整改时应精炼为
  一套当前事实，不新增历史堆叠。
- 以上只需局部实现与小型回归，不增加 artifact store、签名链、provenance graph、复杂 ACL 或额外审计设施。

执行者没有留下其他必须由用户选择的产品问题；上述方向由本轮复验直接确定。

## 最小定向复验

所有 Rust 测试均经共享构建锁和资源看门狗运行；core 产品测试按已知环境要求清空 loopback 代理变量。

| 门禁 | 结果 | 说明 |
|---|---|---|
| `just test -p codex-team-state evidence` | 23/23 通过 | 确认完整 canonical 窗口、顺序 call ID 复用、权限与现有 per-producer 行为；现有测试也明确固化了同时 pending 只留一个及同 producer 保持 256 条 |
| `just test -p codex-core suite::team_evidence` | 3/3 通过 | 成功/失败、route 权限与新增真实 PostToolUse 拦截纵切通过 |

未重跑执行者已报告的 541 条合并门禁、fix/fmt，也未运行全 workspace、Docker、真实 API、本地模型或付费测评。

复验前 `74a6843` 工作树干净，`git diff --check a3ecfea...74a6843` 通过；主工作区
`main = origin/main = 0c1a5e4` 且干净。本报告是本轮唯一受跟踪改动；未合并、未推送、未归档分支。

## 下次复验入口

整改后只需新增三类小型回归：同时 pending/完成顺序相反的重复 call ID 仍各自准确铸造；超过 32 条 refs 可从模型工具按页
完整取得；到达 pending 边界不丢随后正式保留的结果。随后重跑 `codex-team-state evidence`、`core team::evidence`、
`suite::team_evidence` 与 M-1/M-2 12 条产品回归即可，无需全 workspace 测试。
