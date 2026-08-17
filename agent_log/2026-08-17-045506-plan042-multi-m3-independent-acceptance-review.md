# Plan 042 / Multi M-3 独立验收审查

日期：2026-08-17 ｜ 审查对象：`worktree-042-multi-m3-evidence-anchoring@f939ded` ｜ 基线：`main@0c1a5e4`

## 结论

- **验收不通过**：普通证据链、M-2 route 后下钻和权限主路径已经真实跑通，但存在两项直接破坏证据锚定正确性的阻断缺陷。
- **任务目标失败（当前提交尚未完整实现预期）**：部分已保留 observation 会永久失去 Version 锚点，且 Fact locator 在合法的
  `call_id` 复用下可能返回另一条 observation。M-3 不能按当前提交宣称完成、合并或推送。
- 本轮只做独立审查与最小定向复验，没有修改产品代码、扩大设施或运行全 workspace 门禁。

## 阻断项

### P1：单次发布窗口超过 32 条时，较早 Fact 被永久消费但未写入任何 Version

`MAX_VERSION_EVIDENCE_REFS = 32`（`team-state/src/evidence.rs:24-29`）。`take_publish_window` 先把 producer 游标推进到
完整窗口的最后一条 Fact，再计算省略数、删除较早 refs，只把最新 32 条交给 `publish` 写入 Version
（`team-state/src/store/evidence.rs:105-126`、`team-state/src/store.rs:338-355`）。

例如一个发布周期有 37 条新 Fact，前 5 条既不属于本次 Version，后续发布也不会再取得。`evidence_refs_omitted` 只是即时
发布返回值，不是可下钻引用；Event 获得者永远无法沿该 Version 读取这 5 条证据。这违反 ExecPlan
`33-39`、`102-104` 的“关联本周期新增 Fact”及“不丢失、不重复”合同。

处理要求：canonical Version 应保留本窗口的全部轻量 Fact refs；上下文预算应在投影或有界读取面解决。实现者可自主选择
最小方案，不要求引入新存储、审计或可信设施。

### P1：`producer + call_id + output_kind` 不是 observation 的稳定唯一 locator

重复 `call_id` 只在 pending 队列内被拒绝；第一次 Fact 确认后，同一 producer 可以再次 note/confirm 相同 ID
（`team-state/src/store/evidence.rs:46-53`、`79-92`）。读取则始终返回 history 中第一个同 ID、同 output kind 的结果
（`core/src/team/evidence.rs:284-297`）。源码没有建立或验证 call ID 在线程历史内全局唯一。

后果包括：

- 后一个 Fact 的 tool/category 可以描述第二次调用，下钻文本却来自第一次调用；
- 并行调用时 first-completed note 与 `FuturesOrdered` 的 first-retained 顺序还可能不同；
- 旧结果被 compaction 移除后若出现同 ID 新结果，旧 Fact 会从应有的 `Unavailable` 重定向到新文本；
- 若第一次结果来自被排除的团队/证据工具，后续普通工具复用 ID 可把该排除结果错误锚定并随 Event 开放。

这违反 ExecPlan `30-32`、`99-101` 的稳定身份与“只解析目标 observation”合同。处理要求是让 locator 一对一标识 retained
item，或提供能证明 Fact 永不重定向的等强方案；不限定具体编码或模块路线。

## 需要一并收口的正确性缺口

### P2：全团队 256 条 pending 上限会静默漏掉随后正式保留的结果

pending observations 共用一个 256 条队列，满后直接 `pop_front`
（`team-state/src/evidence.rs:17-22`、`team-state/src/store/evidence.rs:54-56`）。产品执行层没有“单批最多 256 条”的硬保证：
tool future 会持续进入 `FuturesOrdered`，response 完成后才按序 drain/retain；源码里的其他 256 上限只约束 analytics 或
metadata。因而极端但可达的批次会让最旧 note（甚至属于另一 producer）在结果正式保留前被静默逐出，之后无法形成 Fact。

整改不需要扩大系统：只需保证已支持且正式保留的结果不会因共享暂存上限无标记消失，并补一条小型边界回归。

### P2：PostToolUse 拦截后的最终失败文本落入支持形状，却不会形成 Fact

工具 handler 已完成后，`PostToolUse` 的 `should_block` 会把模型最终看到的结果替换成 `RespondToModel` 失败
（`core/src/tools/registry.rs:675-712`）；宿主随后生成 `success=false` 的文本 Function/CustomToolCallOutput 并正式写入 history。
该分支在 evidence note 前直接返回，所以 retention 无 pending 可确认。

本轮决定：未知工具和 PreToolUse 拦截因工具未执行，可以继续排除；PostToolUse 拦截发生在执行完成之后，其最终保留的文本
失败结果属于首版支持集，应形成 failure Fact。只需在现有捕获/分类层补窄回归，不要求新增产品纵切。

## 已核对且接受的行为与代用户决策

- 接受以 producer conversation history 为读取来源、每次读取现场判断 availability；不要求 rollout/artifact store，也不把
  暂时读不到永久写死。locator 本身仍须按上项修到一对一。
- 接受 `spawn_agent` / `wait_agent` 等非团队工具结果按发布周期机械进入作者 Fact 集；这符合“模型不逐条挑选”。
- 接受 code-mode 内部调用 `team_evidence` 的文本折入外层 cell 结果后，外层结果按普通 observation 处理；没有新增读取权限，
  不需为此建立特殊防泄漏设施。
- 接受被打断调用用领域撤销 + 明确宿主调用点覆盖，不要求再建昂贵的产品级 interrupt 纵切。
- 否决 ExecPlan 决策 020 的 canonical 32-ref 截断；保留投影的显示上限是合理的，但不能用上下文预算改变不可变 authored
  关联。部分否决决策 014：PostToolUse 已执行完成后的模型可见失败结果应捕获，未知工具/PreToolUse 仍可排除。
- 不要求签名链、provenance graph、复杂 ACL、输出副本、跨进程持久化或额外审计设施；以上问题均可局部修正。

执行者交付中没有必须由用户选择的其他产品决策；上述取舍由本轮审查直接作出。

## 定向复验与现场

本轮通过共享构建锁仅运行两组窄门禁：

| 门禁 | 结果 | 说明 |
|---|---|---|
| `just test -p codex-core suite::team_evidence` | 2/2 通过 | 普通成功/失败、Version、Root 下钻、route 后授权和 sibling 拒绝主链可运行 |
| `just test -p codex-team-state a_version_carries_a_bounded_number_of_references_and_reports_the_rest` | 1/1 通过 | 该测试明确固化“37 条只保留最新 32 条并消费全部窗口”，因此同时复现 P1 合同偏差 |

第一次在受限 sandbox 内启动领域测试时，资源看门狗因无法连接宿主 cgroup bus fail-closed（exit 81）；随后按仓库门禁在获准
环境中用同一命令重跑并通过，不是代码测试失败。core 产品测试按执行日志说明清除了 loopback 代理变量。未重跑执行者已经
通过的 M-1/M-2 12 条回归、539 条合并门禁、clippy/fmt，也未运行全 workspace、Docker、真实 API、本地模型或测评。

审查前 042 工作树干净，`git diff --check 0c1a5e4...f939ded` 通过；主工作区 `main = origin/main = 0c1a5e4` 且干净。
本报告是本轮唯一受跟踪改动。未合并、未推送、未归档分支；现有 plan/WBS 中的 M-3 完成声明不构成已验收事实，整改时应按
最终结果同步。

## 复验入口

整改后只需围绕四个缺口补小型定向回归并重跑原 M-3 suite、`codex-team-state` 与 M-1/M-2 产品回归：发布窗口超过 32 条
仍完整锚定、跨确认周期/并行重复 call ID 不串线且旧 Fact 不重定向、pending 达边界不静默漏掉已保留结果、PostToolUse
拦截后的失败文本进入支持集。无须扩大到全 workspace 测试。
