# RONDO Multi Publication Critic 产品合同

本文是 RONDO Multi M3-A1 对 **Publication Critic 产品语义和最低质量边界**的权威合同，适用于
`main@ea03202ba838f3d6ba4a2061b76b9f3fdbf73c66` 所承载的现行 Team State 语义及其后续三期实现。
本文只冻结稳定产品含义，不承载实现进度或训练任务细节。现行实现与路线以 WBS 为准；后继五头训练任务的
唯一权威语义合同是
[`rondo-multi-publication-critic-task-contract-v2.md`](rondo-multi-publication-critic-task-contract-v2.md)。

当前阶段与任务顺序仍以 [`doc/WBS.md`](WBS.md) 和
[`doc/WBS/multi-agent-trusted-evidence.md`](WBS/multi-agent-trusted-evidence.md) 为准。两份
2026-08-21 Publication Critic 研究材料是日期冻结的事实与候选来源，不与本文并列成为产品合同；研究建议只有在本文明确
采纳后才构成稳定语义。

## 1. 权威范围

### 1.1 现行已实现事实

- `team_publish` 打开新 Event 或给可见的已有 Event 追加一个不可变 Version；新 Event 使用 authored `title`，每个
  Version 使用 authored `summary` 和可选 `handoff`。
- 权威 session 决定 Producer 身份和权限。成功提交由 Team State 原子完成 Event/Version、revision、wake、stale、
  retry/dedup 和 evidence window 变更；Fact 是 retained observation 的引用，不是事实真值或永久可恢复正文。
- Event history 是 event-local、permission-scoped 且单页有界的公共读取面；整个 Event chain 仍可分页而无全局长度上界。
- Producer 与 Root 的生命周期轴相互独立；Root route/resolve/retire 和 attention 语义不属于 publication 文本判定。

### 1.2 M3-A1 新冻结的产品语义

- Critic 审查与最终拟提交内容语义一致的**完整 canonical publication candidate**，不是只审 `handoff`。
- 新 Event、已有 Event、已完成事项和未完成事项共用同一组 hard qualification requirements；只有 continuation 要求随
  “工作确实未完成”而条件化。
- 产品判定只有 `PASS/REWRITE`。前两次 `REWRITE` 可以退回当前稿给 Producer 自主重写；第二次改稿接受最终非阻断审查，
  随后发布。服务或合同故障也继续发布，取消则不提交。
- Critic 只消费本文定义的有界公共输入；它不验证事实、不自动改写、不调度团队，也不接管 Producer 或 Root。

### 1.3 留给后续任务的工程选择

本文不冻结 API、JSON schema、wire shape、模块或 crate 布局、序列化格式、Event 历史条数、token/字符上限、队列和超时数值、
score/threshold、样本数、训练参数、模型 revision、工件格式或部署方式。后续实现可以复用职责相符的现有机制，也可以新增
架构契合的专用能力；不得为复用而扭曲本合同，也不得建设重复或没有现实需求的重型体系。

## 2. 被审对象与最小公共输入

### 2.1 完整 publication candidate

Critic 看到的 candidate 必须与通过 gate 后交给现行 Team State 提交的 authored publication 逐字段语义一致：

- **新 Event**：canonical `title`、canonical `summary` 和 canonical optional `handoff`；
- **已有 Event**：现有 canonical Event `title`、本次 canonical `summary` 和本次 canonical optional `handoff`。

已有 Event 的 title 虽不是本次 Producer 重写的字段，仍是完整 candidate 的局部事项边界。`handoff` 缺失是合法值，尤其是
事项已经完成时；Critic 不得把“必须有下一步”当作隐藏门槛。

Critic 不得审原始长稿、而让 store 写入语义不同的截断稿。canonicalization 必须有单一语义来源；采用共享纯函数、提前拒绝
超长稿或其他等强实现由后续任务决定。

### 2.2 必需语义字段

每次审查的最小公共 packet 必须表达下列语义；字段名与编码留待后续冻结。

| 语义 | 来源与要求 |
|---|---|
| 合同身份 | 明确输入合同和 qualification rubric 的版本；未知版本不能被猜测解释。 |
| 权威角色 | 由 session 提供 Producer 是 Root 或普通成员；不得相信模型自报身份。 |
| target kind | 明确是新 Event 或已有 Event。 |
| local scope | 新 Event 使用 canonical authored title；已有 Event 使用 canonical Event title。只描述本事项，不复制整个 Team State。 |
| candidate | 本次 canonical summary 与可选 canonical handoff，连同 local scope 构成完整 publication candidate。 |
| continuity context | 新 Event 明确为 `not_applicable`。已有 Event 使用只读、event-local、permission-scoped、确定性且有界的公共 projection；它可以为空，但必须诚实表达提供、遗漏或不可得。 |
| context freshness | 标明 continuity context 所依据的 Team revision，以及审查时是否已知 stale、部分省略或不可得；不得把旧或不完整视图伪装成完整历史。 |
| Evidence V1 policy | 明确 semantic entailment 未被评价，并按 §2.3 表达允许的 body-free 状态。 |

已有 Event 的 continuity context 只用于判断本次增量 checkpoint 在局部事项内是否可理解、是否与所给公共状态关键冲突。
它最多包含由确定性有界策略选出的 prior canonical authored publication 语义及其 omission/freshness 状态；不得分页抓取整个
Event chain 后拼成 packet。没有 prior text、context 被省略或 context 已陈旧时，Critic 只能按实际提供内容判定，不得补造历史，
也不得仅因 Harness 诚实标记了省略而拒绝一个自身已合格的 candidate。具体 projection、条数和预算由下游实测选择。

### 2.3 Evidence V1

Evidence V1 只允许以下非正文语义进入 Critic 输入：

- 固定 policy 含义：`semantic_entailment_not_evaluated`；
- 对 continuity context 中已经提交的公共 Version，可有界表达“是否带 Fact 引用”、引用数量是否被省略，以及 observation
  可用性是否未知；
- 对本次未提交 candidate，明确表示最终 publish window 在 commit 前不可作为已冻结证据提供。

V1 不向 Critic 提供 Fact ID、producer/locator、tool 名、category、observation 正文或由这些信息推测出的“已获证”标签。
Fact 存在、数量更多或外观更正式都不能让强断言自动 PASS；没有 Fact 也不能让诚实的 hypothesis 自动 REWRITE。
Critic 只判断 publication 用词是否诚实保留 `observed/inferred/suspected/unknown` 等确定性差异，不判断 Fact 真伪、时效、
适用性或 claim→Fact 蕴含。

### 2.4 禁入边界

以下内容不得进入 Critic packet：

- Producer 或 sibling 的私有 transcript、隐藏 reasoning、未发布发现或完整工具历史；
- 全 Team State、整个 Active World Index、整个 Event history、整个仓库或 workspace；
- 原始 trace、raw evidence、Fact observation 正文或未筛选工具正文；
- 密钥、凭据或其他私有运行数据；
- Binary label、defect tag、pair direction、split、generator/reviewer/source identity 等监督、生成或审查元数据。

## 3. Qualification 边界

### 3.1 Hard requirements：决定 `PASS/REWRITE`

四类 publication 使用同一组最低要求。任一适用 hard requirement 失败即 `REWRITE`；全部适用要求满足即 `PASS`，不能再用
篇幅、文风或表面特征提高门槛。

| 要求 | `PASS` 最低条件 | `REWRITE` 边界 |
|---|---|---|
| 有用状态传递 | 在 local scope 内说清本次发现、结论或状态变化；允许很短。 | 只有“处理了一些问题”“仍需研究”等几乎没有可用状态的文字。 |
| 诚实保留不确定性 | packet 所呈现的 observation、推断、怀疑和未知不发生确定性越级。 | 把未验证机制、猜测或缺失上下文写成已经证实。 |
| 条件化可接续 | **只有工作确实未完成时**，接手者能知道已到哪里、卡点或下一步起点。 | 明显未完成却没有可接续状态；已完成事项不因没有 handoff 而失败。 |
| 范围与信号 | 核心公共状态没有被 transcript dump、无价值过程或重复严重淹没；少量有用背景合法。 | 过程噪声使关键状态难以识别。 |
| packet 内部一致 | title、summary、handoff 和实际提供的 continuity context 在关键状态上相容。 | 同一 packet 对是否完成、已验证内容或接手动作给出关键冲突。 |

这些要求只评价 packet 呈现的内容。Critic 不因无法看到 Producer 私有上下文而猜测“还有遗漏发现”，也不独立调查世界真相。

### 3.2 Soft preferences：只优化 `PASS` 区

当 hard requirements 已全部满足且核心语义等价时，可以偏好更直接、少重复、信息密度更高的表达。这些偏好不改变
qualification：稍长但完整可靠的 candidate 仍须 `PASS`；更短、更正式或更漂亮不能弥补状态缺失、确定性越级、不可接续或
关键内部冲突。

固定长度、正式文风、必须有 handoff、必须有 evidence、必须列行动项和“越短越好”都不是 hard requirement。

## 4. 重写、故障与取消语义

一个 publication cycle 最多包含原稿和两份 Producer 改稿：

1. Harness 审查原稿。`PASS` 时提交该稿；`REWRITE` 时不提交，并给 Producer 第一次自主重写机会。
2. Harness 审查第一次改稿。`PASS` 时提交该稿；`REWRITE` 时仍不提交，并给 Producer第二次、也是最后一次重写机会。
3. Harness 审查第二次改稿。该次审查是最终非阻断审查：无论 `PASS` 或 `REWRITE`，都只把第二次改稿提交一次。

前两次反馈由 Harness 提供两个不同、版本化且有界的固定提示，只回显**最近一次**被拒绝的 canonical publication candidate。
第一次提示聚焦补足最低 qualification；第二次提示明确最后机会并要求定点修正。反馈不累积更早草稿或 transcript，Critic 不生成
自由文本理由，Harness 和 Critic 都不替 Producer 改写或删除内容。

服务 timeout、不可用、排队失败、未知合同、无效输出或其他无法形成有效 verdict 的情况，在任何审查点都停止本 cycle 的继续
审核，并尝试提交当时的 candidate：

- 审核状态记为“审核未完成”，不得冒充 `PASS`、`REWRITE` 或“审核完成但未通过”；
- 若最终非阻断审查有效返回 `REWRITE`，审核状态记为“审核完成但未通过、重写机会已耗尽”；
- 此前发生过的阻断式 `REWRITE` 次数与最终审核状态正交保留，不能因最后一次 infra failure 丢失或改写；
- 这些状态只要求进入有界的开发者可观测面，不写进 authored publication，也不成为第二份 Team State；具体 trace/指标形态
  留给后续任务。

Critic verdict 或 infra fallback 只允许进入现行 publish 提交路径，不能绕过原生权限、目标、stale、retry 或 store validation。
审核状态与 canonical commit outcome 必须正交记录：只有 store 成功 commit 才能附加“已发布”；store 合法拒绝时记为
“未提交/发布失败”，保留相应审核状态且不留下部分写入。这种拒绝不是 Critic verdict。

Producer/turn 在 cycle 尚未完成 canonical commit 时取消，则不提交、不推进任何 Team State 状态并清理本 cycle 的重写状态。
一旦现行 store 已完成原子 commit，后来的取消不能回滚已提交 Version。

## 5. 职责边界

| 角色 | 负责 | 不负责 |
|---|---|---|
| Producer | 判断是否值得形成 publication、撰写完整 candidate、接收固定反馈后自主决定如何重写。 | 暴露私有 transcript/reasoning；接受 Critic 自动代写；把通过当作事实真值证明。 |
| Critic | 只依据有界 packet 判断本文的 publication qualification，返回严格的 `PASS/REWRITE` 产品判定。 | 是否值得发布、事实真伪、route、spawn、分工、Root resolve/retire、最终任务结论或自由文本改写。 |
| Harness | 解析权威身份和 target，构造与提交语义一致的 canonical packet，执行有界调用/重写/fallback/cancel 协议并给出固定反馈。 | 代替 Producer 总结、补事实或写 publication；建立第二套 Team State、调度器或 Agent 间协议。 |
| Root | 消费正常 canonical Team State，继续负责 route、协调、resolve/retire 和最终任务结果。 | 把 Critic 当第二个 Agent、事实裁判或协调者；承担 Critic 的模型服务职责。 |

## 6. Team State 不变量

Publication Critic 只改变提交前的有界交互，不能改变下列结果语义：

1. 前两次被 `REWRITE` 的 draft 不创建 Event 或 Version，不推进 Team revision、wake generation 或 Root attention，
   不消费 evidence window，也不产生可见性、route 或生命周期变化。
2. 最终实际发布仍只调用现行 canonical publish mutation 一次：新 Event 创建一个 Event 和一个不可变 Version；已有 Event
   只追加一个不可变 Version。Critic、Harness 或后续生命周期更新都不原地重写 authored 内容。
3. Critic 所审 canonical candidate 与最终交给 store 的 authored 字段语义一致；store 仍负责最终 clamp/validation 的单一
   权威结果。若 store 拒绝，失败不得留下部分写入。
4. 每个新的成功 canonical coordination mutation 仍恰好推进一次 revision。`REWRITE`、infra 审核、取消、rejected、
   deduplicated 和稳定 no-op 均不推进 revision。
5. wake 只由最终实际 canonical 变化产生；Root 自建 Version 不自唤醒，成员发布与 producer close 的现行 wake/消费规则不变。
6. 已提交 request 的稳定 replay 返回原 committed outcome，不重复创建对象或消费后来 Fact，也不应重新进入 Critic；同一
   request identity 携带不同内容仍按现行合同拒绝。未提交 cycle 的身份和清理实现不得污染 committed dedup map。
7. Evidence 仍由 Harness 按现行 publish window 规则在成功 commit 时关联并推进 cursor。Critic 不 peek、预留或消费 window；
   前两次拒稿、infra、取消和 store refusal 都不得使 Fact 丢失。最终 Version 保留 store 在实际 commit 时选择的全部引用。
8. Critic packet 只能读取 actor 原本有权读取的 event-local public projection。现行权威身份、可见性、contribution、Fact
   read permission、instance reset 和 fail-closed 规则不放宽。
9. stale append 仍按现行合同标记后提交；stale lifecycle 仍拒绝。Critic 不能把读取时 revision 变成新的覆盖权限，也不能
   绕过 commit 时的重新校验。
10. Producer `open/closed` 与 Root `pending/tracking/resolved` 双生命周期、retire、assignment、活动视图和 Root attention
    终态不变；被拒 draft 和审核状态都不成为新的 canonical 生命周期轴。

这里冻结的是结果语义，不指定未来 hook、cycle cache、committed fast path 或开发者观测字段的模块位置。

## 7. 四类代表性边界例

以下均为合成、紧凑的产品边界例，不是训练集、性能证据或固定文风模板。每组使用 §3.1 的同一 hard requirements；
`REWRITE` 只展示该组关键缺陷。

### 7.1 新 Event × 已完成事项

```text
PASS
title: 配置解析空路径崩溃
summary: path 为空时会触发 panic；已改为返回配置错误，定向解析测试通过。
handoff: <缺失>

REWRITE
title: 配置解析空路径崩溃
summary: 配置解析问题已处理。
handoff: <缺失>
```

差异：`REWRITE` 没有传递具体故障、变化或验证状态，违反“有用状态传递”。已完成的 `PASS` 没有 handoff 仍然合格。

### 7.2 新 Event × 未完成事项

```text
PASS
title: Windows UNC 路径仍无法加载
summary: Linux 路径用例通过；UNC 用例在前缀解析后失败，分隔符处理是否为根因仍未验证。
handoff: 从 UNC 前缀后的解析分支验证具体根因；不必重查 Linux 用例。

REWRITE
title: Windows UNC 路径仍无法加载
summary: Linux 路径用例通过；分隔符处理是否为根因仍未验证，但已确认它就是根因。
handoff: 从 UNC 前缀后的解析分支验证具体根因；不必重查 Linux 用例。
```

差异：`REWRITE` 在同一 packet 内一面承认机制未验证、一面宣称已确认，违反“诚实保留不确定性”和内部一致性；Critic
不需要外部 evidence 才能看见这个缺陷。

### 7.3 已有 Event × 已完成事项

```text
provided continuity context:
  title: reload 后仍读取旧缓存键
  prior summary: 已复现旧值；缓存键构造尚未检查。

PASS candidate:
  summary: 修正缓存键构造后，reload 定向测试稳定读取新值；该事项已完成。
  handoff: <缺失>

REWRITE candidate:
  summary: 修正缓存键构造后，reload 定向测试稳定读取新值；该事项已完成。
  handoff: 继续定位为什么 reload 仍读取旧值。
```

差异：`REWRITE` 的 handoff 与 summary 的完成状态及验证结果关键冲突，违反“packet 内部一致”。`PASS` 不需要编造下一步。

### 7.4 已有 Event × 未完成事项

```text
provided continuity context:
  title: schema migration 回滚失败
  prior summary: 正向迁移已通过；回滚尚未验证。

PASS candidate:
  summary: 回滚仍在重复索引处失败；正向迁移保持通过，事项未完成。
  handoff: 从回滚的索引清理继续；无需重跑已通过的正向迁移。

REWRITE candidate:
  summary: 正向迁移保持通过；回滚事项尚未完成。
  handoff: <缺失>
```

差异：`REWRITE` 保留了“正向迁移已通过”的有用状态，却没有说明回滚进展、卡点或继续起点，违反条件化“可接续”；判定
依据不是 handoff 字段缺失，同样的缺失在已完成事项中合法。

## 8. 下游共同交接

本文的五项 hard requirement、公共输入、Evidence V1 与 typed `PASS/REWRITE` 产品边界由
`rondo-publication-critic-task@v2` 投影成一次 backbone forward 的五头训练与评价语义。task contract 可以增加内部
结构化诊断和派生 scalar，但不得改写本文的发布、重写、fallback、取消、canonical commit 或 Team State 不变量。
冻结 v8 与旧 scalar 路径保留历史身份，不与后继 task contract 并列成为当前训练语义。

M3-A2 与 M3-B2a 可以独立依赖本文，不需重新讨论被审对象、最小公共输入语义、hard/soft 分层、四类一致门槛、Evidence V1、
职责边界或重写/故障/取消语义。

- **M3-A2 数据/评价设施**可以把本文的 packet 语义、qualification 和四类切面转换为自己的版本化 schema、少量样本与评价；
  它仍须自行冻结 serialization、projection 选择与预算、数据规模/split、指标、threshold 和评价参数。本文例子不能直接冒充
  数据集或模型效果证据。
- **M3-B2a 本地 Critic 服务**可以围绕同一 packet 语义和严格 verdict/failure 边界建立可替换服务；它仍须自行冻结服务
  协议、模型/scoring identity、健康检查、超时、并发/队列、输入输出上限和错误类型。它不在该工作包修改 `team_publish`
  或实现 Producer 重写状态机。

后续 Multi 发布接入必须继续保持 §6 的 Team State 不变量。两条链的当前顺序、授权门和更后工作包只见方向 3 WBS；
本文不复制路线。

Plan 050 仅提供三个冻结任务的条件性历史事实和 body-free 资产边界。它不证明一般性能、自然协作率、成员贡献质量、
Publication Critic 效果或 Team State 的因果收益；本文没有查看或还原其 ignored 原始正文。
