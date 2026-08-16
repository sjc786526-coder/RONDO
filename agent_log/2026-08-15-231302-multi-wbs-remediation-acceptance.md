# RONDO Multi WBS 整改验收审查

日期：2026-08-15 ｜ 验收对象：`worktree-038-multi-wbs-restructure@ba23a8f`

## 验收结论

**验收不通过；任务目标尚未完成。**

`ba23a8f` 已实质修复上一轮最重要的问题，架构和 M-1 → M-5 主顺序不需要重做。但复验仍发现两项会让阶段
在核心功能未正确成立时通过的缺口，以及四项会把实现引向错误行为或留下可空过验收的语义缺口。它们都能通过
小范围修改 WBS 关闭，不需要增加数据库、复杂 ACL、审计平台、额外调度器或其他重设施。

本轮只读核对两份 WBS、整改日志与相关 `multidev` 源码，并新增本报告；没有修改 WBS 或源码，没有构建、测试、
网络、Docker、API、合并或推送。

## 已通过并应保留

- 活动视图已经改为三类理由的并集，Root 也按 producer 身份参与判断；结束 route 不再让 Agent 遗忘自己的 open Version。
- 增量 mutation、stale lifecycle 拒绝、幂等重试、终态不重开和历史查询已进入权威合同与 M-1 验收。
- request-only projection 已覆盖 provider retry，同一次逻辑采样复用同一不可变快照；投影自身有硬预算和显式 overflow。
- route 已固定 canonical visibility/assignment 先提交、短通知后发送，通知失败不回滚 canonical 状态。
- 无权威 Session 身份 fail-closed；Fact locator 不再成为任意读取 sibling 上下文的通道。
- M-3 已禁止以“全部 Unavailable”代替正常 Fact 下钻；M-4 已区分作者关闭、`RetiredByRoot` 和可恢复成员；
  M-5 已拆分功能门与相对 Codex 退化门。
- 撤回 producer 可见 Root attention、把批量结束注意力降到候选池，都是合理减法。

## 合并前必须修正

### 1. M-1 只限制了 projection 自身，没有保证整次模型请求不超窗

WBS `doc/WBS/multi-agent-trusted-evidence.md:66-67,147-149` 已要求 projection 有 hard cap，但没有要求它计入
`history + instructions + projection` 的整次请求预算。源码
`multidev/codex-rs/core/src/context_manager/history.rs:163-187` 的估算只统计 base instructions 与 history items；
request-only projection 不在 history 中。于是 history 已接近 context 上限时，即使 projection 自身低于 10K，
追加后仍可能直接把请求顶到 `ContextWindowExceeded`。

Claude 自己也在 `agent_log/2026-08-15-225058-multi-wbs-restructure.md:157-161` 正确认定“M-1 必须把投影预算并进估算”，
但该必要条件没有进入唯一权威 WBS。

**应改**：M-1 明确 projection 必须计入整次请求剩余 token/context 预算，或预留等价 headroom；接近窗口时先做
显式 overflow/已有 compaction，不能由 projection 把请求顶爆，并覆盖一个 near-limit 用例。无需在 WBS 指定估算算法。

### 2. M-5 仍可能在真实产品工作流失败时通过

WBS `:194-201` 的第一道门只要求 Event、wake、route、多作者、Fact 与收尾“确实被触发”且无状态不变量失败，
没有要求冻结的真实 Multi 工作流达到自身任务完成标准。系统可以完整触发这些机制、最后任务仍失败，却通过第一门；
第二道门又可以在另一组同题运行上通过，因此两门相加仍不能证明目标中的“真实任务上跑通完整协作语义”。

**应改**：第一门同时要求冻结工作流本身达到预冻结的任务完成标准。正常工作流必须覆盖正常 attention 收尾；
不应为了过门而强制造 orphan，orphan 的定向正确性留在 M-4 验收，真实运行自然发生时再附带验证。

### 3. 最小生命周期状态与默认值仍未冻结

WBS 已写终态不重开和 Root-authored 默认 tracking（`:34-57`），但没有定义 producer 的 `open/closed`
（以及可选 `superseded`）和 Root 的 `pending/tracking/resolved` 分别表达什么，也没有明确非 Root 新 Version 的
Root attention 默认是 `pending`。用户接受“Root 自建默认 tracking 而非统一 pending”的前提，正是普通 producer
发布默认 pending；遗漏后实现者仍可把 child 新 Version 默认 tracking，并声称符合 WBS。

**本轮代为裁决**：第一版 producer 最小状态为 `open/closed`，`RetiredByRoot` 是不同于作者关闭的独立终态；
`superseded` 只有在首阶段确有需要时作为更精确终态加入。Root 状态为 `pending/tracking/resolved`：普通参与者新建
Version 默认 `pending`，Root 自建默认 `tracking`；状态意义沿用原设计的“未消费 / 已判断但继续关注 / 已完成当前协调”。
WBS 只需一段精炼定义，不需要 transition table。

### 4. “永久历史”和“会话恢复”必须按团队实例边界表述

合同 `:38-41` 称历史永久保留，并把“进程或会话恢复”笼统写成旧引用只作历史；但 `:102,219` 又允许第一版
TeamState 仅为 session 内存态，跨进程持久化后置，字面互相矛盾。

源码还存在两种不同恢复：根 thread 恢复会新建 `AgentControl`；同一存活根树中的 V2 成员则可能被 residency 卸载后，
使用同一个 `AgentControl` 重新加载（`agent/control/residency.rs:117-148`、`agent/control/spawn.rs:250-283,354-363`）。
后一种不能被判为新 epoch、stale 引用或真正 unavailable，否则会误丢仍有效团队状态并触发错误 orphan 处理。

**本轮代为裁决**：历史在**当前团队实例存续期内** append-only、不因退出活动视图而删除；有匹配 TeamState/epoch
的成员 reload 继续使用原身份、权限和状态。只有根团队恢复时无对应 TeamState，或引用的 epoch 不匹配，才开启新实例，
把旧通知/引用标为 historical/reset 且不得解析到新对象。第一版仍不要求跨进程持久化。

### 5. M-2 还缺 assignment 结束的反向验收，投递规则需覆盖运行中目标

M-2 `:161-165` 只验“assignment 结束后，目标仍有自己未终态 Version 时继续 active”，没有验另一半：目标没有
自己的 open Version、没有其他 active assignment 时，应退出 active 视图但保持历史可见。若 `end_assignment`
实现为 no-op、Event 永久常驻，现标准仍可能通过。

同段把 queue-only 描述成“仅补充信息”，遗漏了目标正在运行但 route 要求工作的情况。运行中的 Agent 应在安全边界
接收排队输入，而不是再触发一个新 turn。

**本轮代为裁决**：目标正在运行时使用 queue；目标 idle 且 assignment 要求开始/继续工作时 trigger；目标 idle
且只是信息通知时 queue。M-2 增加成对验收：有其他 active 理由则保留，没有任何理由则退出 active、历史可读。

### 6. M-3 的非空正常路径与权限拒绝没有成为完成标准

M-3 `:172-178` 已要求“每个首版支持类别有代表性引用成功”，但没有要求首版支持类别集合非空；也没有验合同
`:84-87` 的关键拒绝路径。理论上把支持集声明为空，或正常下钻成功但 sibling 仍可绕过 visibility 读取私有 observation，
都可能按当前文字通过。

**应改**：M-3 plan 冻结一个非空的首版 observation 类别集合，至少一条真实 Version 关联 Fact 并正常下钻；同时验证
不可见 sibling Fact 读取 fail-closed、route 后只开放目标引用而不连带开放其 thread/rollout 周边内容。这里只需定向测试，
不建设复杂 ACL。

## 非阻断清理

- 候选池 `:210-211` 的“原先排在 M-4……故移出”属于修订历史，应只留在 agent log；从实时 WBS 删除即可。

## 最终状态

- **验收：不通过。** 两个完成门仍能在核心目标未成立时通过，另有四处会影响实现行为或验收闭环的语义缺口。
- **任务目标：尚未完成。** 不是架构失败；保留现有 29 条合同和 M-1 → M-5 主结构，完成上述小范围修订后即可复验。
- **交付边界：** 本报告是本轮唯一新增文件；执行者分支仍未合并、未推送。
