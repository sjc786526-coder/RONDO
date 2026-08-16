# RONDO Multi 修正方案意见稿（工程落地版）

## 一、意见稿的定位

本意见稿以《RONDO Multi 当前最新完整设计》为基准，不重新讨论该方案是否值得实施，也不把第一版的性能、成功率或成本表现作为否定架构的理由。当前方案的核心方向——复用 Codex execution/control plane、保持 Agent 私有推理、由 Harness 维护 Event-centric Team World State、以 Fact reference 连接客观 observation、由 Root 负责选择性协调——总体上已经成立。

以下内容主要集中于尚未完全闭合、容易在实现中产生歧义、竞态、重复状态或不可恢复行为的部分。第一版允许不够智能、不够节省 token，也允许部分机制采取临时实现；但状态提交、权限边界、唤醒语义、事件身份、Fact 可解析性和错误恢复必须明确。本文提出的修正应尽量作为对现有设计的补充约束，而不是推翻或重写其核心结构。

---

# 二、必须首先明确的总体分层

当前设计中的“Team World State”和 Codex 源码中已有的 `WorldState` 容易在命名和职责上发生混淆。Codex `v0.147.0` 已经存在 World State section、snapshot、diff、rollout persistence、compaction reinjection 和 extension contribution 等基础设施。 

因此应当明确分为两层：

```text
TeamStateStore
    RONDO Multi 的团队级 canonical state
    保存 Event、Version、FactRef、visibility、route、生命周期和 revision
    由同一个 AgentControl tree 共享
    不直接等同于任何一个 Agent 的模型上下文

TeamProjection
    TeamStateStore 面向某个 Agent、某次 sampling 的模型可见投影
    Root 和 child 获得不同的 projection
    可以借助 Codex WorldState 或直接在请求边界注入
```

建议在源码中避免直接把 canonical store 命名为 `WorldState`，可采用：

```rust
team_state::TeamStateStore
team_state::TeamEvent
team_state::EventVersion
team_state::TeamProjectionSnapshot
```

Codex 原有结构则继续保留：

```rust
context::world_state::WorldState
```

这样可以防止后续把“canonical 团队事实”与“模型上下文差异投影”混成同一个可变对象。

---

# 三、Active World Index 的注入路径尚未最终确定

## 1. 当前问题

现有设计要求 Active World Index：

- 每个 sampling boundary 根据最新 Team World State 重新生成；
- 不作为普通历史消息持续追加；
- 不受 conversation compaction 影响；
- 类似系统上下文，但又不是固定系统提示词。

这一目标与 Codex 现有 extension WorldState 的默认行为并不完全一致。现有 WorldState 会生成模型可见的 context fragment，并把这些 fragment 记录进 conversation history；它能够处理 diff 和 compaction，但并不是纯 request-only projection。

如果不提前选定实现路线，开发过程中很容易出现两套平行机制：一套是 Codex WorldState，一套是 RONDO 临时 prompt 注入逻辑，最终难以维护。

## 2. 可选路线

### 路线 A：第一版复用现有 extension WorldState section

做法是把当前 Agent 可见的 Team Projection 实现成一个 extension-owned WorldState section。

**优点：**

- 对 Codex 内核侵入最小；
- 自动获得 snapshot、diff、rollout persistence 和 compaction reinjection；
- 容易先跑通状态变化和模型可见性；
- 适合第一条端到端纵向切片。

**缺点：**

- Team Projection 会以 contextual message 的方式进入 history；
- 旧 projection 可能暂时保留在历史中；
- 与“每次请求重新生成、完全不累积”的目标语义不完全一致；
- 必须用明确标记告诉模型新 projection 替代旧 projection。

建议投影至少包含：

```xml
<team_state_projection
    team_epoch="..."
    revision="42"
    replaces_all_prior_team_state_projections="true">
...
</team_state_projection>
```

### 路线 B：直接在 sampling request 边界追加 request-only projection

Codex 在构造本轮 `Prompt.input` 前，会从当前 history 生成请求输入。可以在这一边界追加 Team Projection，而不调用 `record_conversation_items`。

**优点：**

- 最符合现有设计的语义；
- 不污染 conversation history；
- 不会因旧 projection 累积产生歧义；
- compaction 后下一次请求仍可重新生成。

**缺点：**

- 需要修改核心 request assembly；
- 必须处理 stream retry、token estimation、context limit 和 prompt cache 稳定性；
- 必须保证一次 sampling 使用的是一个确定的 projection snapshot；
- 容易形成 RONDO 专用的内核特殊路径。

### 路线 C：扩展 Codex WorldState，使其支持 `request_only` 或 `volatile` section

即保留 Codex WorldState 的 section、snapshot、diff 和 extension 接口，但允许某些 section 只在每次模型请求中渲染，不进入普通 history。

**优点：**

- 长期架构最干净；
- 不为 RONDO 单独复制一套上下文状态系统；
- 未来其他动态状态也可以复用；
- request-only projection 与 canonical snapshot 可以统一管理。

**缺点：**

- 第一版工程量最大；
- 需要仔细修改 WorldState、ContextManager、compaction 和 token estimation 的交界；
- 容易在纵向切片尚未跑通之前扩大开发范围。

## 3. 推荐顺序

以“先跑起来”为目标：

```text
路线 A > 路线 B > 路线 C
```

以长期目标架构为标准：

```text
路线 C > 路线 B > 路线 A
```

实际建议是：第一条纵向切片先采用路线 A，并把这一点明确记录为 MVP 偏差；核心状态机稳定后，再决定升级为路线 C。不要在第一版同时实现 A 和 B。

---

# 四、“调用 Event 工具时先展示 Active Events”在单次工具调用中无法成立

## 1. 当前问题

现有设计描述为：

```text
Agent 调用 Event/Handoff 工具
→ Harness 先展示该 Agent 当前 active Events
→ 模型决定本次更新内容
→ Harness 提交修改
```

但在标准 function tool 语义中，模型必须先生成工具名称和参数，Harness 才能执行工具并返回结果。因此 Harness 无法在同一次工具调用中先展示状态，再让模型修改已经生成的参数。

如果不修正，实际实现可能退化为：

- 工具先返回 active Events；
- 模型再调用第二次工具；
- 或者模型在完全不知道最新 revision 的情况下直接提交 mutation。

## 2. 可选路线

### 路线 A：每次 sampling 前注入 Agent 自己的 Active Event Index

Root 获得 Root Projection，child 获得自己的 Child Projection。模型在决定是否调用 Event 工具之前，就已经知道当前状态。

mutation tool 同时携带：

```json
{
  "observed_revision": 42,
  "operation_id": "...",
  "action": "append_version"
}
```

**优点：**

- 符合模型决策顺序；
- 不增加额外工具轮次；
- 可以检测 stale view；
- Active Event 不再依赖模型记忆。

**缺点：**

- 每次 sampling 都会占用一定上下文；
- 必须实现可靠、紧凑、角色相关的 projection。

### 路线 B：拆成 `inspect_team_state` 和 mutation 两步

```text
inspect_team_state
publish_event / update_event_state
```

**优点：**

- 实现直观；
- 不需要修改每次 sampling 的 prompt；
- 模型可以主动选择什么时候读取。

**缺点：**

- 每次更新至少增加一轮工具调用；
- 模型仍然可能忘记先读取；
- 对高召回、频繁阶段汇报不友好。

### 路线 C：允许 mutation 因 stale revision 失败，并返回最新状态

模型先盲目提交；若状态已经变化，Harness 拒绝并返回最新 projection，要求模型重试。

**优点：**

- 实现最简单；
- 可以保证强一致 mutation。

**缺点：**

- 容易产生反复重试；
- 模型对 active Events 的持续认知仍然较弱；
- 不符合“重要状态主动回到模型注意力”的设计目标。

## 3. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

因此，Active Event Index 应当从“Event 工具调用时显示”修正为“在模型决定是否调用 Event 工具之前，作为本次 sampling 的动态团队上下文提供”。

---

# 五、正式 route 不应把完整 Event chain 复制进普通通信正文

## 1. 当前问题

现有设计提出 Root 正式 route Team Event 时，将 Event identity、完整 Version chain 和 Fact refs 一起通过 `send_message` 或 `followup_task` 投递。

Codex 的 `InterAgentCommunication` 会被转换成目标 Agent 的模型输入，并进入其 history/rollout。

如果每次 route 都复制完整 chain，会形成两个事实来源：

```text
TeamStateStore 中的 canonical Event chain
目标 Agent history 中的一份 route-time Event chain 副本
```

后续新增 Version 后，history 中的副本立即过时，并会造成：

- 同一 Event 多份陈旧副本；
- route 多次后重复 token；
- 模型无法确定哪份 chain 是最新的；
- TeamStateStore 与 transcript 的职责重新混合。

## 2. 建议修正

正式 route 应拆成两个动作：

```text
Canonical state change：
    授予目标 Agent 对 Event 的 visibility
    创建 RouteAssignment
    记录 route purpose、mode 和 revision

Transport notification：
    通过 send_message / followup_task 发送紧凑 route envelope
```

通信正文只需包含：

```json
{
  "type": "team_event_routed",
  "team_epoch": "...",
  "event_id": "E17",
  "team_revision": 43,
  "route_mode": "contribute",
  "route_purpose": "检查 Windows 路径兼容性"
}
```

完整 Version chain 由目标 Agent 下一次 Team Projection 或 `read_event(E17)` 从 canonical store 获取。

## 3. 可选路线

### 路线 A：compact envelope + canonical visibility

**优点：**

- 不复制 canonical state；
- 后续 Version 自动可见；
- 消息内容短；
- route 和 Event identity 保持稳定。

**缺点：**

- 目标 Agent 必须具备 Team Projection 或 `read_event`；
- route delivery 与 visibility commit 需要定义顺序。

### 路线 B：继续发送完整 chain

**优点：**

- 第一版最容易看见效果；
- 不需要额外读取工具。

**缺点：**

- 状态重复；
- chain 很快陈旧；
- route 次数增加后 context 成本不可控；
- 与 Harness-owned canonical reality 的核心目标冲突。

### 路线 C：新建特殊 Agent-to-Agent 协议

**优点：**

- 可以为 Event route 定制结构化传输。

**缺点：**

- 重新实现 mailbox、delivery 和 turn triggering；
- 与“复用 Codex communication plane”的原则冲突；
- 第一版没有必要。

## 4. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

路线 B 可以用于最早的临时 smoke test，但不宜成为正式结构。

---

# 六、route 的 canonical commit 顺序必须固定

## 1. 当前问题

如果 route notification 先发送，visibility 后写入，则目标 Agent 可能在收到消息后立即开始 sampling，却无法从 TeamStateStore 读取 Event。

如果 visibility 先写入、通信失败，则目标 Agent 已经有读取权限，但可能没有获得及时通知。

这必须明确为一种有意识的失败语义，而不能让实现顺序随机决定。

## 2. 建议顺序

推荐固定为：

```text
1. 校验 Root 权限、目标 Agent 和 Event
2. 在 TeamStateStore 中提交 visibility grant
3. 创建或更新 RouteAssignment
4. 增加 state_revision
5. 释放 TeamStateStore lock
6. 调用 send_message 或 followup_task
7. 在 RouteRecord 中记录 delivered / failed
```

通信失败时，不回滚 visibility，而记录：

```rust
RouteDeliveryState::Failed {
    reason: String,
    failed_at_revision: u64,
}
```

Root 可以显式重试。

## 3. 可选路线

### 路线 A：visibility first，失败后保留 visibility 并记录 failed

**优点：**

- 不存在“收到通知但读不到 Event”的竞态；
- 不需要跨 TeamStateStore 和 mailbox 做事务；
- 重试简单。

**缺点：**

- 通信失败时，目标可能已经获得但暂未察觉该 Event。

### 路线 B：message first，成功后授予 visibility

**优点：**

- visibility 与成功通知看似一致。

**缺点：**

- 存在目标先被唤醒、后获得权限的真实竞态；
- 不推荐。

### 路线 C：失败时回滚 visibility

**优点：**

- route 看起来具有事务性。

**缺点：**

- 并发情况下回滚复杂；
- 目标可能已经在其他 sampling 中看见 Event；
- 容易制造“知识被撤回”的不自然语义。

## 4. 推荐顺序

```text
路线 A > 路线 C > 路线 B
```

---

# 七、visibility、route assignment 和贡献权限目前被混成了一个概念

## 1. 当前问题

现有设计规定 Root route Event 后，目标 Agent：

- 获得 Event 可见性；
- Event 可以继续出现在 active list；
- 可以为同一 Event 发布 Version。

但尚未明确：

- visibility 是否永久；
- Root 结束任务后是否撤销可见性；
- 仅用于告知的信息是否也允许目标 Agent append Version；
- route 何时不再使 Event 出现在 child active list。

如果直接使用一个 `visible_to` 集合承担所有语义，会出现两个问题：

1. 一旦 Agent 看过 Event，理论上不应假装它从未看过；
2. 但如果可见性永久等于 active assignment，Event 可能永远占据其 active list。

## 2. 建议修正

拆成三个维度：

```rust
VisibilityGrant
    目标 Agent 是否有权读取该 Event 历史
    一般应当是永久的、不可逆的知识可见性

RouteAssignment
    Root 当前是否仍要求目标 Agent 关注或处理该 Event
    active / completed / cancelled

ContributionCapability
    observe_only / contribute
    目标 Agent 是否有权为该 Event append Version
```

Child Active Event Index 的纳入规则可修正为：

```text
Agent 自己仍有 open Version
或
该 Event 存在面向该 Agent 的 active RouteAssignment
```

仅仅拥有历史 visibility，不应让 Event 永久出现在 active list。

## 3. 可选路线

### 路线 A：永久 visibility + 独立 assignment lifecycle

**优点：**

- 符合“知道过的信息不能被撤销”的认知语义；
- active list 可以正常退出；
- route 任务状态可审计。

**缺点：**

- 比单一 `visible_to` 多一个状态结构。

### 路线 B：可撤销 visibility

**优点：**

- 数据结构简单。

**缺点：**

- Agent history 中可能已经存在 route notification；
- 撤销可见性只是 Harness 假装 Agent 不知道；
- 历史查询和权限语义不自然。

### 路线 C：不维护 assignment，只依赖普通任务消息

**优点：**

- 第一版代码较少。

**缺点：**

- 无法机械决定 route Event 何时退出 child active list；
- Root 对 route 是否完成没有 canonical 状态。

## 4. 推荐顺序

```text
路线 A > 路线 C > 路线 B
```

第一版即使不实现复杂 assignment，也至少应区分：

```text
historical visibility
current active assignment
```

---

# 八、`send_message` 与 `followup_task` 的选择策略需要显式化

## 1. 当前问题

Codex V2 中：

- `send_message` 是 queue-only；
- `followup_task` 使用 `trigger_turn`；
- 两者共享同一主要投递路径；
- `followup_task` 不要求目标 Agent 当前一定 idle；
- `followup_task` 不能以 Root 为目标。

当前设计虽然确认可以复用两者，但没有明确由谁决定具体 delivery mode。若 Root model 每次都自行判断，可能频繁把普通信息作为新任务触发；若 Harness 完全自动判断，又可能替代 Root 的语义决策。

## 2. 建议修正

route 工具提供：

```rust
enum DeliveryMode {
    Auto,
    QueueOnly,
    TriggerTurn,
}
```

`Auto` 的默认规则：

```text
目标 Agent 正在运行：
    默认 QueueOnly

目标 Agent idle，且 RouteAssignment 要求继续工作：
    TriggerTurn

目标 Agent idle，但只是补充信息：
    QueueOnly

目标为 Root：
    不使用 followup_task，由 Team wake 机制处理
```

Root 可以显式覆盖 `Auto`，但 Harness 应记录最终实际使用的 delivery mode。

## 3. 推荐顺序

```text
默认 Auto + Root 可覆盖
>
完全由 Root 每次选择
>
完全由 Harness 隐式决定且不暴露
```

---

# 九、Root wake 必须使用持久 generation，不能只依赖瞬时通知

## 1. 当前问题

现有 `wait_agent` 使用 input queue activity 和 timeout 等条件等待。

若 RONDO 只在新 Event 发布时调用一次 `notify()` 或发送一次瞬时 channel message，会出现漏唤醒：

```text
Child 发布 E17/V2
→ wake notification 已经发生
→ Root 随后才调用 wait_agent
→ 没有后续通知
→ Root 一直等到 timeout
```

因此“发生过 Team State 变化”必须有持久状态，而不能只存在于一个瞬时信号中。

## 2. 建议数据

至少区分：

```rust
state_revision: u64
wake_generation: u64
```

含义：

```text
state_revision
    任何 canonical TeamStateStore 变化都递增

wake_generation
    只有需要 Root 重新获得协调机会的变化才递增
```

Root 还应保存：

```rust
root_last_observed_wake_generation: u64
```

等待流程应采用：

```text
1. 先订阅 watch receiver
2. 再读取当前 wake_generation
3. 与 last observed generation 比较
4. 若已经有未观察变化，立即返回
5. 否则 select mailbox / team wake / timeout
```

## 3. 可选实现

### 路线 A：`watch::Sender<u64>`

**优点：**

- 保存最新 generation；
- 天然支持事件合并；
- 新订阅者可以比较当前值；
- 与现有 Tokio 架构一致。

**缺点：**

- 不保存每个 wake 的完整事件序列；
- 但 Root 本来就应读取最新 Active World Index，而不是消费 FIFO。

### 路线 B：broadcast channel

**优点：**

- 可传递每次变化记录。

**缺点：**

- 订阅晚了仍可能漏历史；
- 有 lag 和容量问题；
- 与“只关心最新世界状态”的语义不匹配。

### 路线 C：`Notify`

**优点：**

- 实现最简单。

**缺点：**

- 最容易产生 lost wake；
- 不推荐。

## 4. 推荐顺序

```text
watch generation > broadcast > Notify
```

---

# 十、哪些变化会唤醒 Root，需要形成明确规则

当前“新的 Event 或 Version 可以唤醒 Root”仍不够具体。生命周期状态变化是否唤醒、Root 自己发布是否自唤醒，都需要固定。

建议规则如下：

```text
非 Root Agent 创建新 Event：
    root_state = pending
    wake_generation += 1

非 Root Agent append 新 Version：
    root_state = pending
    wake_generation += 1

producer 将一个 Root 当前 pending/tracking 的 Version
从 open 改为 closed/superseded：
    wake_generation += 1
    但不创建新的 root_state

producer 修改一个 Root 已 resolved 的旧 Version：
    不唤醒 Root
    不重新进入 Active World Index

Root 修改 root_state：
    不自唤醒

Root 创建新 Event 或 Version：
    不自唤醒
    initial_root_state 由 Root 显式指定
    默认建议为 tracking

route 给 sibling：
    可能唤醒目标 sibling
    不因此唤醒 Root 自己
```

这里建议把“producer 对 Root-active Version 的关闭”视为值得唤醒 Root 的状态变化。否则 Root 正在 tracking 一个问题，而 producer 已经结束调查，Root 可能只能等到 timeout 后才知道。

---

# 十一、Root 自己发布 Event 时不应机械进入 pending 并自我唤醒

## 1. 当前问题

现有统一规则是新 Version 默认对 Root 进入 pending。但 Root 自己创建 Event 时，它显然已经知道该 Event，若仍然：

```text
Root 创建 E20/V1
→ E20/V1 root_state=pending
→ wake Root
```

就会产生没有意义的 self-wake 和“Root 尚未消费自己刚创建内容”的状态。

## 2. 可选路线

### 路线 A：Root-authored Version 默认 `tracking`

**优点：**

- 符合 Root 创建事项通常是为了继续跟踪或 route；
- 不需要额外消费自己的内容。

**缺点：**

- Root 创建纯历史记录时还要再改为 resolved。

### 路线 B：Root 必须显式提供 initial root state

```text
pending / tracking / resolved
```

**优点：**

- 语义最明确。

**缺点：**

- 增加工具参数；
- 模型可能选择错误。

### 路线 C：仍设为 pending，但禁止 self-wake

**优点：**

- 状态规则统一。

**缺点：**

- Root active list 会出现自己尚未“处理”的新 Version；
- 语义不自然。

## 3. 推荐顺序

```text
路线 B，默认值 tracking
>
路线 A
>
路线 C
```

---

# 十二、Version 追加顺序不是因果顺序，但仍需记录作者当时看见了什么

## 1. 当前问题

当前设计明确：

```text
V1 → V2 → V3 只是 Harness 登记顺序
不代表后一个作者看过全部前序 Version
```

这一原则正确，但如果完全不记录作者提交时的可见状态，之后无法回答：

```text
B 发布 V3 时是否已经看到 A 的 V2？
V3 是在什么团队状态下产生的？
冲突是信息不同步，还是语义判断不同？
```

## 2. 可选路线

### 路线 A：只记录 `observed_team_revision`

```rust
observed_team_revision: u64
```

**优点：**

- 成本很低；
- 可以判断 Version 是否基于陈旧视图；
- 不把 Event 变成复杂 DAG。

**缺点：**

- 无法精确知道作者看过哪些具体 Version。

### 路线 B：增加可选 `based_on_versions`

```rust
based_on_versions: Vec<VersionId>
```

**优点：**

- 可以表达“这个更新明确基于 V1 和 V2”；
- 有利于解释修正、反驳或综合。

**缺点：**

- 需要模型显式填写；
- 不能保证完整。

### 路线 C：完整向量时钟或 Version DAG

**优点：**

- 因果表达最严格。

**缺点：**

- 对 2–8 Agent 的第一版过度复杂；
- 会把工程重点转向分布式因果系统。

## 3. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

第一版建议强制记录 `observed_team_revision`，将 `based_on_versions` 作为可选字段。

---

# 十三、canonical mutation 需要 stale-view 和幂等语义

## 1. 当前问题

多个 Agent 可能并发：

- append Version；
- 修改自己的 producer state；
- Root route；
- Root 修改 root state。

如果工具只提交“我要把 E17/V2 设为 closed”，却不说明模型基于哪个 revision 作出决定，就无法检测它是否在使用陈旧 projection。

模型 API、tool runtime 或 stream retry 还可能导致同一工具调用被重复提交，从而创建重复 Version。

## 2. 建议机制

所有 mutation 至少携带：

```rust
operation_id: String
observed_revision: u64
```

Harness 根据 mutation 类型采用不同策略：

```text
append_version：
    即使 observed_revision 旧，也通常允许 append
    但返回 stale_view warning
    Version 记录实际 observed_revision

producer/root lifecycle update：
    使用 expected current state 或 expected updated_revision
    不匹配时拒绝并返回最新状态

route：
    使用幂等语义
    同一 operation_id 不重复创建 assignment

create_event：
    同一 operation_id 只创建一次
```

## 3. 可选并发架构

### 路线 A：单一 `tokio::sync::Mutex<TeamStateInner>`

**优点：**

- 适合 2–8 Agent；
- 最容易保证原子提交和单调 ID；
- 易测试。

**缺点：**

- 所有 mutation 串行；
- 但当前规模完全可接受。

### 路线 B：Actor mailbox

**优点：**

- 所有命令天然串行；
- 方便生成 mutation log。

**缺点：**

- 请求/响应、关闭和错误传播更复杂；
- 第一版收益有限。

### 路线 C：数据库事务

**优点：**

- 为后续持久化和多进程准备。

**缺点：**

- 第一版明显过重；
- 会延缓纵向切片。

## 4. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

TeamStateStore 的锁绝不能跨以下操作持有：

```text
模型调用
send_message / followup_task
rollout I/O
read_fact I/O
工具执行
```

应在锁内生成不可变 commit result 或 projection snapshot，释放锁后再执行外部操作。

---

# 十四、Version authored payload 与生命周期投影应在类型上物理分离

## 1. 当前问题

设计已经说明 authored payload 不可变，而 producer/root state 可以更新。但如果实现仍将它们放在一个可整体覆盖、可序列化回写的结构里，后续很容易无意修改旧 Handoff 或 Fact refs。

## 2. 建议结构

```rust
struct EventVersion {
    authored: AuthoredVersion,
    producer: ProducerProjection,
    root: RootProjection,
    transitions: Vec<LifecycleTransition>,
}

struct AuthoredVersion {
    id: VersionId,
    author: AgentId,
    handoff: String,
    fact_refs: Vec<FactId>,
    created_revision: u64,
    observed_team_revision: u64,
}

struct ProducerProjection {
    state: ProducerState,
    updated_revision: u64,
}

struct RootProjection {
    state: RootState,
    note: Option<String>,
    updated_revision: u64,
}
```

同时，生命周期变化不应只覆盖当前状态，建议保留精简 transition log：

```rust
struct LifecycleTransition {
    actor: AgentId,
    side: LifecycleSide,
    from: String,
    to: String,
    reason: Option<String>,
    committed_revision: u64,
}
```

## 3. 可选路线

### 路线 A：只保存当前 producer/root state

**优点：**

- 最简单。

**缺点：**

- 无法审计谁在何时改变状态；
- Root override 和 producer 自己关闭容易混淆。

### 路线 B：当前 projection + append-only transition log

**优点：**

- 查询高效；
- 历史可审计；
- 工程量适中。

**缺点：**

- 多保存一份精简日志。

### 路线 C：所有 TeamState 完全 event-sourced

**优点：**

- 理论上最统一。

**缺点：**

- 读取和恢复复杂；
- 第一版没有必要。

## 4. 推荐顺序

```text
路线 B > 路线 A > 路线 C
```

---

# 十五、producer/root 状态需要正式 transition table

状态不能只依靠提示词解释。至少应在代码和测试中定义允许的转换。

建议第一版状态：

```rust
enum ProducerState {
    Open,
    Closed,
    Superseded { by: VersionId },
    RetiredByRoot { reason: String },
}

enum RootState {
    Pending,
    Tracking { reason: Option<String> },
    Resolved { reason: Option<String> },
}
```

建议 transition 规则：

```text
Producer：
    Open → Closed
    Open → Superseded
    Open → RetiredByRoot
    Closed/Superseded/RetiredByRoot 默认不可重新打开
    问题重新相关时 append 新 Version

Root：
    Pending → Tracking
    Pending → Resolved
    Tracking → Resolved
    Tracking → Pending 可选，但应有明确原因
    Resolved 不原地重新打开
    新 Version 负责重新获得 Root attention
```

“旧 Version 重新打开”会破坏 append-oriented 历史语义，因此不建议支持。若旧问题再次出现，应创建新 Version。

---

# 十六、orphan Version 不应被 Root 伪装成 producer 自己关闭

## 1. 当前问题

现有设计已经要求 Root override 必须记录原因，但仍保留“第一版可以由 Root 显式关闭”的表述。如果实现直接把 producer state 改为 `closed`，会失去最重要的区别：

```text
作者认为事项结束
与
作者不可用，Root 为了结束悬挂状态而退休该 Version
```

## 2. 可选路线

### 路线 A：从第一版就加入 `RetiredByRoot`

**优点：**

- 类型层面不会伪造作者意图；
- active predicate 简单；
- 审计明确。

**缺点：**

- producer state 多一个终态。

### 路线 B：producer state 保持 open，另加 root override metadata

**优点：**

- producer 原始状态完全不变。

**缺点：**

- active 判断需要额外排除 override；
- 查询和投影更复杂。

### 路线 C：仍写成 closed，但附加 override flag

**优点：**

- 数据结构最少。

**缺点：**

- 状态名称本身误导；
- 容易在后续代码中丢失 override 区别。

## 3. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

producer availability 建议作为从 AgentControl lifecycle 派生的 metadata：

```text
Running
Idle
Completed
Interrupted
Errored
Unavailable
```

它不应修改 authored Version。Agent 若在同一进程内重新恢复，可用性可以重新变化；一旦 Root 已明确 `RetiredByRoot`，该旧 Version 仍保持终态，需要继续调查时创建新 Version。

---

# 十七、Fact Index 的捕获位置尚未具体化

## 1. 当前问题

设计提出 Harness 为“值得引用的原始 observation”分配 Fact ID，但尚未明确 Fact 在 Codex 哪个边界创建。

不能简单假设 extension 的 ToolLifecycle hook 能获得所有 canonical payload。Codex extension API 对 ToolLifecycleContributor 的定位主要是观察工具生命周期，而不是读取或重写完整工具输入输出。

如果捕获点选错，可能发生：

- Fact 在输出最终截断前创建；
- Fact locator 指向尚未持久化的对象；
- 某些工具有 Fact，另一些工具没有；
- call ID、ResponseItem ID 和 rollout ordinal 不一致。

## 2. 可选路线

### 路线 A：在 finalized tool output 转为 `ResponseItem`、进入 history/rollout 前捕获

即在工具结果已经完成、call ID 和最终保留 payload 已确定，但尚未写入 conversation history的统一边界创建 Fact。

**优点：**

- 捕获的是 Codex 实际保留的 observation；
- 可以使用稳定 item ID 和 call ID；
- 集中实现；
- 与 Fact locator 语义一致。

**缺点：**

- 需要修改 Codex core 的工具结果记录路径；
- 不一定能获得工具产生但被 Codex 丢弃的完整原始字节。

### 路线 B：在每个工具 handler 中创建 Fact

**优点：**

- 可以获得最接近工具原始输出的数据；
- 可按工具定制。

**缺点：**

- 侵入性高；
- 工具种类多；
- 容易出现覆盖不一致。

### 路线 C：事后解析 rollout 创建 Fact

**优点：**

- 对核心执行路径侵入较低。

**缺点：**

- 延迟；
- locator 更脆弱；
- 需要重新关联 call/output；
- rollout 变化会影响解析。

## 3. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

第一版只需要支持高价值 observation：

```text
shell/exec completion
测试命令结果
patch/apply result
MCP tool result
关键文件读取结果
```

Team Event 工具、read_event、read_fact 等 RONDO 内部工具应默认排除，避免形成递归 Fact。

---

# 十八、Fact 不应承诺所有工具的完整原始 payload 永远可恢复

## 1. 当前问题

当前设计中的“原始 payload 继续保存在 rollout/thread/tool state”容易被理解为：

```text
所有 stdout/stderr、所有工具内容、未经截断的原始字节
都能永久通过 FactRef 找回
```

但 Codex 可能对进入模型 history 的大工具输出执行截断，compaction 也会改变部分上下文。除非 RONDO 额外保存 artifact，否则不能对所有工具做这一承诺。

## 2. 建议重新定义

第一版 Fact 应定义为：

> Harness 能稳定定位到的、由 Codex 实际保留的历史 observation。

Fact 只承诺 observation identity 和 locator，不承诺未被 Codex 保留的完整原始数据。

建议结构：

```rust
struct FactLocator {
    fact_id: FactId,
    producer_thread_id: ThreadId,
    turn_id: String,
    response_item_id: Option<ResponseItemId>,
    call_id: Option<String>,
    observation_kind: ObservationKind,
    rollout_ordinal: Option<u64>,
    payload_digest: Option<String>,
    bounded_preview: Option<String>,
    payload_availability: PayloadAvailability,
    workspace_revision: Option<u64>,
}
```

其中：

```rust
enum PayloadAvailability {
    Retained,
    RetainedButTruncated,
    ExternalArtifact,
    Unavailable,
}
```

`Unavailable` 只表示 payload 目前不能解析，不表示历史 observation 是假的。

## 3. 可选路线

### 路线 A：locator-only，引用 Codex 实际保留内容

**优点：**

- 最轻量；
- 不复制大输出；
- 符合第一版目标。

**缺点：**

- 某些原始内容可能已经截断。

### 路线 B：只为高价值或大输出增加 content-addressed artifact store

**优点：**

- 关键证据可以完整保存；
- 可按需启用。

**缺点：**

- 增加磁盘管理、清理和生命周期问题。

### 路线 C：复制所有工具原始输出

**优点：**

- 理论上最完整。

**缺点：**

- 存储和隐私成本高；
- 重复 Codex rollout；
- 第一版明显过度。

## 4. 推荐顺序

```text
路线 A → 按真实需要补充路线 B
```

路线 C 不建议采用。

---

# 十九、“本发布周期新增 Fact refs”的游标语义必须确定

## 1. 当前问题

当前设计中的“从上一个 Event 之后新产生的 Fact refs”在以下场景中存在歧义：

```text
Agent 产生 F1、F2、F3
随后连续发布 E17/V2 和 E18/V1
```

此时：

- F1–F3 是只属于第一次 publication？
- 两个 Event 都应获得？
- 第二个 Event 是否获得空窗口？
- “上一个 Event”是同 Event 上一 Version，还是该 Agent 的任意上次 publication？

如果不规定，回放同一条执行轨迹可能得到不同 Fact refs。

## 2. 最低必需修正

即使第一版不正式引入 `FactWindow` 类型，也必须有：

```rust
per_agent_fact_seq: u64
per_agent_last_publication_seq: u64
```

一次 publication 对应机械区间：

```text
(last_publication_seq, current_fact_seq]
```

提交成功后推进 cursor。

## 3. 可选路线

### 路线 A：candidate Fact Window + 模型可选直接相关 refs

Harness 提供本周期候选窗口，模型可以：

- 选择直接相关 Fact；
- 保留完整 window boundary 作为 provenance；
- 不要求对每项 claim 做精确映射。

**优点：**

- 比全部自动附加更精确；
- 仍然不要求模型扫描全部历史；
- 后续容易扩展 claim-to-evidence。

**缺点：**

- Event 工具参数更复杂；
- 模型可能遗漏相关 Fact。

### 路线 B：每个 Agent 一个全局 publication cursor，自动附加窗口全部 Fact

**优点：**

- 最简单；
- 完全机械；
- 高召回。

**缺点：**

- 可能把不相关 Fact 附到第一个 Event；
- 紧接着的第二个 Event 可能没有 Fact。

### 路线 C：每个 Event 独立 cursor

**优点：**

- 同一 Event 的证据窗口更连续。

**缺点：**

- 同一个 Fact 可能被许多 Event 重复附加；
- 新 Event 初始 cursor 如何确定仍有歧义。

### 路线 D：要求模型从全部 Fact 历史中手工选择

**优点：**

- 理论上语义最精确。

**缺点：**

- 模型必须重新读取大量历史；
- 与轻量化目标冲突。

## 4. 推荐顺序

长期语义质量：

```text
路线 A > 路线 B > 路线 C > 路线 D
```

最小纵向切片：

```text
先采用路线 B
```

但必须把 cursor 规则写死，不能继续使用模糊的“从上一个 Event 以后”。

---

# 二十、Fact 的时间相关性需要一个轻量 workspace chronology

## 1. 当前问题

当前设计正确地区分：

```text
某次测试曾经 FAIL
≠
当前 workspace 仍然 FAIL
```

但如果 Fact 只记录时间和 producer，模型仍可能难以判断 Fact 之后是否发生过相关写入。

不建议建立严格 snapshot，但可以提供低成本 chronology。

## 2. 可选路线

### 路线 A：维护 best-effort `workspace_revision`

每次 RONDO 能观察到的写入、patch、文件创建或删除后递增：

```rust
workspace_revision: u64
```

Fact 记录产生时的 revision。若能识别修改路径，再记录：

```rust
touched_paths: Vec<PathBuf>
```

**优点：**

- 实现轻量；
- 可以告诉模型“此 Fact 产生后 workspace 已修改 7 次”；
- 不宣称严格 snapshot。

**缺点：**

- 外部编辑器或未被 Harness 观察的写入可能绕过 revision；
- 必须明确它是 best-effort chronology。

### 路线 B：记录 git HEAD、dirty diff hash 或 tree fingerprint

**优点：**

- 对 Git workspace 更精确。

**缺点：**

- dirty workspace 计算成本更高；
- 多 writer 并发时 hash 频繁变化；
- 非 Git workspace 不适用。

### 路线 C：完全不记录 workspace chronology

**优点：**

- 最简单。

**缺点：**

- Root 下钻 Fact 后更难判断 freshness；
- 可能频繁重新验证。

## 3. 推荐顺序

```text
路线 A > 路线 B > 路线 C
```

建议第一版仅实现 monotonic revision，并明确它不是隔离机制、不是 snapshot，也不用于自动判定 Fact valid/invalid。

---

# 二十一、Active World Index 保留完整 chain 可以接受，但必须有硬安全边界

## 1. 当前问题

现有设计明确第一版保留完整 Version chain，不提前做 materialized head 或 history folding。这一取舍可以保留。

但“完整 chain”不能等同于“没有任何长度上限”。一个长期 Event 即使只有少数 Agent，也可能积累大量 Version。若 projection 超出模型上下文，系统将从性能问题升级为无法继续 sampling 的正确性问题。

## 2. 建议修正

第一版仍默认完整 chain，但增加机械安全阀：

```text
max_handoff_bytes_per_version
max_fact_refs_per_version
max_versions_per_projection
max_total_projection_tokens
```

达到预算时不能静默截断。应显式输出：

```text
Event E17 has 34 versions.
18 versions are included in this projection.
16 historical versions remain available through read_event(E17).
Projection overflow is explicit; no version was silently discarded.
```

建议投影包含：

```text
team_epoch
state_revision
projection_revision
projection_hash
included Event IDs
overflow manifest
```

展示顺序必须 deterministic，例如：

```text
Root pending Events
→ Root tracking Events
→ 最近 committed revision
→ Event ID
```

这只是显示顺序，不是 FIFO 调度。

## 3. 可选路线

### 路线 A：完整 chain + 硬预算 + 显式 overflow manifest

**优点：**

- 保留第一版完整性目标；
- 避免 context hard failure；
- 不需要提前设计复杂摘要。

**缺点：**

- 极端情况下仍需 `read_event` 下钻。

### 路线 B：完全无上限的完整 chain

**优点：**

- 代码最简单。

**缺点：**

- 迟早可能超过上下文；
- 不推荐。

### 路线 C：立即实现 materialized head/history folding

**优点：**

- context 最紧凑。

**缺点：**

- 需要定义摘要正确性和证据保留；
- 违背当前先保证 canonical projection 完整的优先级。

## 4. 推荐顺序

第一版：

```text
路线 A > 路线 B > 路线 C
```

真实运行证明 chain 成为主要瓶颈后，再把路线 C 作为独立优化任务。

---

# 二十二、in-memory 第一版必须引入 `team_epoch`

## 1. 当前问题

第一版使用 session/team-scoped 内存状态是合理的，但进程重启后可能出现：

```text
Codex thread rollout 恢复
→ 旧 history 中仍有 Team Projection 或 route envelope
→ 新 TeamStateStore 是空的
→ 模型误把旧 projection 当作当前团队状态
```

## 2. 建议修正

每个 TeamStateStore 创建时生成：

```rust
team_epoch: Uuid
```

所有下列对象都携带它：

```text
Event 外部引用
FactRef
Team Projection
route envelope
mutation result
state dump
```

`E17` 只在一个 epoch 内唯一，完整身份应视为：

```text
(team_epoch, E17)
```

若恢复 thread 时没有对应 canonical TeamStateStore，应显式注入：

```text
The previous Team State epoch is unavailable.
Prior team projections and route envelopes are historical only.
A new Team State epoch has started.
```

不能静默把旧 projection 当成当前状态。

## 3. 可选路线

### 路线 A：in-memory + team_epoch + reset marker

**优点：**

- 最适合 MVP；
- 不需要立即实现持久化；
- 避免旧状态冒充当前状态。

**缺点：**

- 完整进程重启后 Team Event 不恢复。

### 路线 B：将 TeamState 持久化到 sidecar 或独立 append log

**优点：**

- 可恢复；
- 便于调试和离线分析。

**缺点：**

- 需要 schema migration、flush 和损坏恢复；
- 不应阻塞第一条纵向切片。

### 路线 C：从 Agent 消息和 history 重建 TeamState

**优点：**

- 不增加独立持久化。

**缺点：**

- history 不是 canonical store；
- route message 可能陈旧或缺失；
- 与设计原则冲突。

## 4. 推荐顺序

```text
路线 A → 路线 B
```

路线 C 不建议采用。

---

# 二十三、工具权限不能相信模型提供的 author、producer 或 Root 标志

## 1. 当前问题

设计已经规定：

- 只有 Version author 能修改自己的 producer state；
- 只有 Root 能修改 root state 和 route；
- 获得 Event visibility 的 Agent 才能读取或 append。

但这些权限必须在 Harness 中由当前 Session 身份推导，不能让工具参数包含并相信：

```json
{
  "author": "root",
  "producer": "agent-a",
  "is_root": true
}
```

## 2. 建议规则

```text
actor thread ID：
    从当前 ToolInvocation / Session 推导

actor AgentPath：
    从 SessionSource 推导

Root 权限：
    根据 AgentPath::is_root 判断

Version author：
    Harness 自动填写

Fact producer：
    从实际产生 observation 的 thread/turn 推导

Event append 权限：
    根据 VisibilityGrant 和 ContributionCapability 判断

producer state update：
    只能修改 author == current actor 的 Version

root state update / route / orphan retirement：
    仅 Root
```

任何 model-supplied actor metadata 只能作为说明文字，不能作为权限依据。

---

# 二十四、Event 工具表面不宜过度拆分，也不宜全部塞进一个工具

## 1. 可选路线

### 路线 A：单一 `team_state` 工具，所有 action 用 union 参数

**优点：**

- 工具数量少。

**缺点：**

- schema 很大；
- Root-only 和 child action 混在一起；
- 模型容易选择错误 action；
- 测试和错误信息复杂。

### 路线 B：每个动作一个工具

例如：

```text
create_event
append_event_version
update_producer_state
update_root_state
route_event
read_event
read_fact
```

**优点：**

- 权限和语义清晰；
- 容易测试。

**缺点：**

- 工具表面较大；
- 增加模型工具选择负担。

### 路线 C：读操作分离，mutation 使用有限 union，Root route 独立

建议：

```text
read_team_state
read_event
read_fact

publish_team_update
    create_event
    append_version
    update_own_producer_state

root_manage_event
    update_root_state
    retire_orphan
    batch_resolve_current_versions

route_team_event
```

**优点：**

- 工具数量适中；
- 权限边界明确；
- child 和 Root 不会看到过多无权调用的动作；
- mutation schema 仍然可控。

**缺点：**

- 仍需要几个工具。

## 2. 推荐顺序

```text
路线 C > 路线 B > 路线 A
```

所有 mutation 工具结果应保持紧凑，只返回：

```json
{
  "team_epoch": "...",
  "committed_revision": 43,
  "event_id": "E17",
  "version_id": "E17/V3",
  "stale_view": false
}
```

不要在 mutation result 中再次回显完整 Event chain。

---

# 二十五、Event duplicate 和 Event relation 需要最小支持

## 1. 当前问题

当前设计允许两个互不可见 Agent 为同一现实问题创建两个独立 Event，并由 Root 后续判断是否收敛。但如果完全没有 Event relation，Root 只能在自然语言 note 中记住：

```text
E17 和 E24 实际上是同一问题
```

compaction 后可能再次丢失这一协调判断。

Harness 不应自动做语义 merge，但可以保存 Root 显式建立的关系。

## 2. 建议结构

```rust
enum EventRelationKind {
    RelatedTo,
    DuplicateOf,
    SupersedesEvent,
    Blocks,
}

struct EventRelation {
    from: EventId,
    to: EventId,
    kind: EventRelationKind,
    created_by: AgentId,
    reason: Option<String>,
    committed_revision: u64,
}
```

`DuplicateOf` 不自动删除或合并旧 Event，只影响 projection 和 Root 判断。

## 3. 可选路线

### 路线 A：Root 显式创建 relation edge

**优点：**

- 轻量；
- 不依赖自动语义聚类；
- 可跨 compaction 保存协调判断。

**缺点：**

- 多一个 Root action。

### 路线 B：Harness 自动聚类、合并 Event

**优点：**

- 理论上减少重复。

**缺点：**

- 高度依赖语义；
- 误合并比重复 Event 更危险；
- 不适合第一版。

### 路线 C：完全不支持 relation

**优点：**

- 最简单。

**缺点：**

- 重复 Event 只能靠 Root 记忆。

## 4. 推荐顺序

```text
路线 A > 路线 C > 路线 B
```

该功能可以放在第一条纵向切片之后，不必阻塞核心状态机。

---

# 二十六、高召回 publication 仍需要机械 payload guardrail

高召回原则可以保留，Harness 不应自动判定某条语义是否值得发布。但工具层仍应防止无效或失控 payload。

建议第一版加入：

```text
Event title 非空
Handoff 非空
拒绝完全相同的重复 Version payload
限制单个 Handoff 最大长度
限制单 Version FactRef 数量
限制 Root note 长度
限制 route purpose 长度
记录每个 Agent 的 publication 频率和平均长度
```

这些限制用于保护运行时和可观测性，不用于自动压制“看起来不重要”的 Event。

不建议第一版引入：

```text
自动 semantic importance classifier
自动拒绝低价值 Event
基于固定时间或工具次数的强制 publication
自动 Event 聚类
```

这些都应在获得真实轨迹以后再评估。

---

# 二十七、Root 批量 resolved 需要防止误覆盖并发新 Version

Root 可能希望一次将一个 Event 的当前 Version 全部设为 resolved。如果只提供逐 Version 操作，工具调用较多；如果提供简单 `resolve_event(E17)`，又可能在 Root 读取后、提交前有新 Version 出现，从而被误一起 resolved。

建议 batch action 携带 Root 当时看到的 Version 集：

```json
{
  "event_id": "E17",
  "resolve_versions": ["E17/V1", "E17/V2", "E17/V3"],
  "observed_revision": 42
}
```

Harness 只 resolved 明确列出的 Version。并发新增的 V4 保持 pending。

不要实现：

```text
把 E17 当前和未来所有 Version 都设为 resolved
```

Event 的 Root attention 生命周期仍应由 Version 驱动。

---

# 二十八、Team Projection 必须是一次原子快照

每次 sampling 前，Harness 应在 TeamStateStore 锁内生成：

```rust
TeamProjectionSnapshot {
    team_epoch,
    state_revision,
    wake_generation,
    events,
    assignments,
    overflow_manifest,
}
```

然后立即释放锁。

模型请求使用这一不可变 snapshot。若在模型 sampling 期间 TeamStateStore 又变化：

- 不修改当前请求；
- 不中断当前 sampling；
- 下一 sampling boundary 使用新 revision；
- 若 Root 正在 wait，则通过 wake generation 唤醒。

这样可以避免一个 projection 中一半是 revision 42、一半是 revision 43。

---

# 二十九、第一版应增加最低限度的可观测性，而不是先做复杂 UI

至少需要一个确定性调试入口：

```text
team_state dump --json
```

或等价内部命令，输出：

```text
team_epoch
state_revision
wake_generation
Events
Versions
authored payload
producer/root projections
lifecycle transitions
visibility grants
route assignments
route delivery states
Fact locators
operation dedup records
projection overflow information
```

同时建议保存精简 mutation log：

```text
revision
operation_id
actor
action
affected Event/Version
before state
after state
wake_generation change
```

可观测性的目标不是产品展示，而是让任何一次错误协调都能回答：

```text
哪一个 Agent 在什么 revision 下做了什么修改？
Root 为什么没有被唤醒？
目标 Agent 为什么看不到某个 Event？
这个 FactRef 为什么无法解析？
某个 Version 为什么退出了 active list？
```

---

# 三十、第一版必须验证的状态不变量

以下规则应成为纯 Rust 单元测试和并发测试，而不是只写在提示词中：

1. `AuthoredVersion` 创建后永不修改。

2. Event ID、Version ID 和 Fact ID 在一个 `team_epoch` 内唯一。

3. 同一 Event 的 Version 追加顺序在并发下仍然单调。

4. 非 Root Agent 创建新 Version 时，Root projection 原子进入 pending。

5. Root resolved 不修改 producer state。

6. producer closed/superseded 不修改 root state。

7. Root 已 resolved 的旧 Version仅发生 producer state 更新时，不重新进入 Root active list。

8. Root tracking/pending 的 Version发生 producer 终态变化时，Root 可以被唤醒。

9. 新 Version 总能重新获得 Root attention。

10. Root-authored Version 不产生 self-wake。

11. 只有 Version author 能修改自己的 producer state。

12. 只有 Root 能修改 root state、route 和 retire orphan。

13. 没有 visibility 的 Agent 不能读取 Event chain。

14. 没有 contribution capability 的 Agent 不能 append Version。

15. route 先提交 visibility，再发送 notification。

16. route delivery 失败不会产生半写入或丢失 RouteRecord。

17. mutation retry 不会重复创建 Event 或 Version。

18. stale lifecycle mutation 不会静默覆盖新状态。

19. FactRef 创建成功时必须处于可解析或明确 `Unavailable` 状态，不能无标记悬空。

20. Team wake 在 publication-before-wait 和 publication-during-wait 两种时序下都不会丢失。

21. projection 构造期间不持有锁进行 I/O。

22. projection 超过预算时必须显式报告 overflow，不能静默删除 Version。

23. 进程重启后旧 `team_epoch` 不会被误认为当前 TeamState。

---

# 三十一、建议的第一版实现顺序

## 阶段 1：纯 TeamStateStore 和状态机

暂时不接模型、不接 Fact、不接 route。

实现：

```text
TeamEpoch
Event / Version ID
AuthoredVersion
producer/root projection
lifecycle transition log
visibility
state_revision
wake_generation
operation_id dedup
deterministic projection renderer
```

完成全部状态不变量测试。

## 阶段 2：接入共享宿主

将：

```rust
Arc<TeamStateStore>
```

放到同一 Root AgentControl tree 共享的位置，不在每个 Session 内各自复制。

验证：

```text
Root
Child A
Child B
```

访问的是同一个 canonical store。

## 阶段 3：接入最小 mutation/read 工具

先实现：

```text
publish_team_update
read_event
root_manage_event
```

Fact refs 暂时允许为空。

所有 mutation 带：

```text
operation_id
observed_revision
```

## 阶段 4：接入 Team Projection

第一版可先复用 extension WorldState section。

实现：

```text
Root Projection
Child Projection
team_epoch/revision markers
deterministic ordering
硬 projection budget
```

此时修正“工具调用时显示 active Events”为“sampling 前提供 projection”。

## 阶段 5：扩展 `wait_agent`

加入：

```text
Team wake generation
Root last observed generation
publication-before-wait 测试
publication-during-wait 测试
```

wait result 只需返回：

```json
{
  "reason": "team_state_changed",
  "previous_generation": 11,
  "current_generation": 12,
  "current_revision": 43
}
```

不在 wait result 中复制 Event 正文。

## 阶段 6：接入 route

实现：

```text
VisibilityGrant
RouteAssignment
ContributionCapability
compact route envelope
send_message / followup_task auto policy
delivery success/failure
```

## 阶段 7：接入有限 Fact Index

在 finalized tool output 记录边界捕获高价值 observation。

实现：

```text
Fact ID
locator
payload availability
bounded preview
workspace revision
read_fact
```

不立即实现全量 artifact store。

## 阶段 8：加入 orphan、relation 和调试设施

实现：

```text
RetiredByRoot
Event relation
team_state dump --json
mutation log
```

## 阶段 9：根据真实轨迹决定是否升级 projection 路线

只有在状态机和纵向切片稳定后，再决定：

```text
继续使用 extension WorldState
直接 request-only injection
扩展 Codex WorldState 支持 volatile section
```

---

# 三十二、建议的第一条端到端纵向切片

第一条 smoke path 不应包含所有功能，只验证核心语义：

```text
1. Root spawn Child A

2. Root 进入 wait_agent
   记录 last observed wake generation

3. Child A 创建 E1/V1
   producer_state = open
   root_state = pending

4. TeamStateStore 原子提交
   state_revision 增加
   wake_generation 增加

5. Root wait 被唤醒

6. Root 下一次 sampling 获得最新 Team Projection
   看见 E1/V1

7. Root 将 E1/V1 标记为 resolved

8. Child A 的 producer_state 仍然 open
   E1/V1 仍出现在 Child A 自己的 active projection

9. Child A 后来 append E1/V2

10. E1/V2 默认 root_state = pending
    wake_generation 再次增加

11. Root 再次看到 E1
    projection 中包含 V1 → V2 完整 chain

12. Root resolved V2
    旧 V1 authored payload、Fact refs 和 transition history仍然保留
```

这条链跑通，即证明了最核心的设计价值：

```text
团队状态不依赖某个模型记住
Root attention 与 producer lifecycle 解耦
新 Version 可以重新获得 Root attention
Root wait 不漏 Event
Event chain 跨模型轮次保持稳定
```

随后再增加：

```text
route 给 Child B
Child B append V3
FactRef
orphan retirement
并发 append
进程 epoch reset
```

---

# 三十三、修正后的优先级结论

第一版最重要的不是继续扩充概念，而是把以下边界变成真实代码约束：

```text
TeamStateStore 是唯一 canonical 团队状态
Team Projection 只是每次 sampling 的角色相关视图
InterAgentCommunication 只负责通知，不复制 canonical Event chain
visibility、assignment 和 contribution permission 相互分离
wake 使用持久 generation，不使用瞬时 Notify
authored payload 与 lifecycle projection 物理分离
所有 mutation 都有 observed revision 和 idempotency key
FactRef 只承诺可定位到 Harness 实际保留的 observation
in-memory 模式必须有 team_epoch
所有权限从当前 Session 身份推导
```

在这些边界成立后，即使第一版存在以下问题，也仍然可以视为成功的工程落地：

```text
Event 发布过多
Handoff 不够稳定
Fact refs 偶尔噪声较大
Root 路由不够聪明
任务成功率没有提高
token 成本暂时上升
```

这些问题都可以通过真实运行轨迹继续调整。

相反，以下问题不能以“第一版先跑起来”为理由保留：

```text
Event mutation 可能重复提交
Root wait 可能漏 wake
同一 Event 有多份相互矛盾的 canonical 副本
旧 route message 被模型误认为最新 chain
Root 可以伪装成 producer 修改状态
FactRef 指向不存在内容却无明确标记
进程恢复后旧 Team Projection 冒充当前世界状态
并发 mutation 静默覆盖彼此
projection 超长时静默丢失历史
```

因此，RONDO Multi 的修正重点不应是进一步追求理论完整性，而应是把 canonical state、projection、transport、authority、revision、wake 和 provenance 之间的边界彻底固定。只要第一条纵向切片能够稳定证明这些边界，架构就已经具备继续演化和真实测量的基础。