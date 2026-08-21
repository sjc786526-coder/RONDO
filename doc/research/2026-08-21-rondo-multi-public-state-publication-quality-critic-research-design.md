# RONDO Multi 公共状态发布质量 Critic：研究设计与工程可行性

> 文档性质：形成于 2026-08-21 的候选研究设计，用于把公共状态发布质量 Critic 讨论收敛为可落地的 ML 与工程问题；它不是 ExecPlan，也不宣告任务已经排期或实施。
> 代码基线：主工作区 `main@94999835d36428ca37ad0a0962301faa07f962e1`；Plan 050 已合入 `main` 并通过修复后独立复验。本文中的 publication 源码事实已在该基线上重新核对。
> 规划边界：用户计划在 Plan 050 收口后考虑本项目，该时间前提现已满足；当前 WBS 仍写明“无已排期工作包”。正式顺序、任务编号和授权门只能由 `doc/WBS.md`、`doc/WBS/*.md` 与后续 ExecPlan 冻结。
> 重写关系：本文吸收原始 AI 设计稿中的有效内容和用户批注，并用当前源码、训练资产与工具环境修正不可落地或互相冲突的部分；原始散点稿在完成合并审阅后删除，本文是保留的研究设计。
> 模型边界：学生底模、教师/复核/终审模型的精确版本、上下文、训练框架、导出格式和本地推理栈均未冻结，选型完成后再写入任务合同。

## 1. 执行摘要

本项目研究的不是“让小模型成为第二个 Agent”，而是在 Producer 调用 `team_publish`、内容进入 canonical Team State 之前，判断这份**完整 publication packet**是否达到最低协作质量。因此正式名称采用**公共状态发布质量 Critic**，下文简称 **Publication Critic**；被审对象包括必填 `summary` 和可选 `handoff`，而不是只审可为空的 `handoff` 字段。

| 议题 | 收敛结论 | 状态 |
|---|---|---|
| 产品职责 | Producer 决定公开什么；Critic 只判断已拟定内容能否作为公共 checkpoint；Root 仍负责协调与最终判断 | 设计原则 |
| 运行时结果 | 核心业务判定保持 `PASS` / `REWRITE`；不输出长篇自由文本，不自动重写 | 设计原则 |
| Evidence | V1 不引入显式 claim→Fact grounding，不验证 Fact 真伪、时效或 evidence→claim 语义蕴含；只学习文字中的事实/推测/未知纪律 | 用户决定 + 源码约束 |
| 数据监督 | 每条样本都有 Binary 标签；额外只构造可靠的 Boundary/Q± pair 和少量 Within-PASS pair；不同维度的 trade-off 不强排 | 设计原则 |
| 训练标量 | Binary 与 Pair 共用单样本 publication desirability score；qualification 是主体，少量 Within-PASS 只做低权重的局部偏好塑形，不把该标量解释为客观、完整的总体质量 | 用户确认 |
| Q± | 只允许一个导致跨过门槛的原子差异，其他 hard rubric 维度必须都合格 | 用户决定 |
| 训练路线 | 保存同一 lineage 的 `C0 未训练 → C1 Binary → C2 Boundary/Q± → C3 Within-PASS` 四个 checkpoint；后续阶段混入前序样本，避免能力遗忘 | 用户决定 |
| 数据切分 | 同一具体 scenario、pair、模板近改写和真实来源组不得跨 split；同类题型可以跨 split，并在各 split 保持类别覆盖 | 用户决定 |
| 数据质检 | 教师会话生成、同能力的独立教师会话复核、不同模型家族只做最终盲横评；精确模型稍后冻结 | 角色顺序已决定；模型待选 |
| 学生模型 | 不绑定上一项目的 Ministral、8B、12K、Q4_K_M 或 llama.cpp；先完成 packet token census 和小规模未训练基线 | 待调研 |
| 云与 Hub | RunPod MCP 可承担控制面，现有 SSH/SCP 合同承担数据面；HF CLI 用于 exact-revision 调研/下载/校验。HF Jobs 和私有 Hub 镜像不进入首版主路径 | 设计候选 |
| 重写与故障 | 最多提供两次重写机会；最终稿非阻断发布。服务故障记为未审核，重写耗尽后仍未 PASS 记为未审核通过；状态至少对开发者可观测，不要求暴露给 Root/团队 | 用户决定 |
| 重写反馈 | 两次使用不同的 Harness 固定提示，并回显最近一次被拒绝的 canonical publication；不依赖 Producer transcript，也不让 Critic 生成自由文本理由 | 用户决定 |
| Event context | existing Event 是否携带历史、采用何种 projection 及其条数/token 上限必须先做实际调研；本文不冻结 | 待调研 |
| 结论上限 | 第一版最多证明离线 qualification 改善、本地服务可用、runtime 分支功能正确；不据此声称整体任务成功率或协作质量已经提高 | 硬边界 |

这项工作可行，但不应直接从“选一个模型开始训练”。最先需要关闭的是三个代码前置缺口：定义真实 publication packet、冻结 V1 Evidence 边界、规定 `REWRITE` 与本地服务故障的产品语义。数据与训练合同应随后围绕真实 packet 建立。

## 2. 证据口径与当前项目实况

本文区分四种表述：

- **已验证事实**：可由当前源码、受跟踪合同、已完成日志或本轮工具清单机械确认。
- **源码推论**：由当前控制流和数据流推出，但尚未以新 Critic 代码或测试验证。
- **设计候选**：本文推荐的实现方向，后续 ExecPlan 可在不改变研究目标的前提下修订。
- **待实测/待决策**：必须由 packet census、模型实验或用户选择关闭，本文不伪装为既定事实。

本轮没有读取 `.env.local`、ignored 原始 Plan 050 trace、任务 workspace 或任何密钥；没有调用真实 API、运行 Docker/Cargo、本地模型、训练或付费资源，也没有创建、启停或删除 RunPod/HF 资源。

### 2.1 当前 RONDO Multi publication 事实

| 当前事实 | 对 Critic 设计的直接影响 | 证据 |
|---|---|---|
| `team_publish` 输入为 `event_id/title/summary/handoff/based_on_revision`，仅 `summary` 必填 | Publication Critic 必须审完整 publication candidate；只审 `handoff` 会漏掉主要共享语义 | `multidev/codex-rs/core/src/tools/handlers/team_tools/spec.rs:11-59`、`publish.rs:102-114` |
| Event 下的 Version 是不可变 authored entry，`summary` 与 `handoff` 一经提交不原地改写 | Gate 应位于提交前；REWRITE 不应先落一个坏 Version 再补另一个 | `multidev/codex-rs/team-state/src/model.rs:152-187` |
| title、summary、handoff 写入时分别按 200、2,000、1,000 Unicode scalar values 截断并显示 marker | Critic 必须审 canonicalized 文本，不能审通过一个随后被截断成不同内容的原文 | `multidev/codex-rs/team-state/src/model.rs:20-58` |
| 成功 publish 在同一 store mutation 内完成目标解析、revision、Version append、wake、retry 记录和 evidence cursor 推进 | 网络/模型调用必须在 store 锁外；`team-state` domain crate 不承载异步 HTTP 推理 | `multidev/codex-rs/team-state/src/store.rs:278-428` |
| Fact 是 retained tool observation 的 locator，不复制 payload，也不声明 observation 仍为真 | Critic 不能把 Fact ID 当真理或把“有 Fact”当“claim 已被证明” | `multidev/codex-rs/team-state/src/evidence.rs:1-10,98-159` |
| Producer 不挑选 Fact；每次成功 publish 自动附上自上次成功发布后该 Producer 的全部新 Fact，并推进 cursor | 当前草稿无法显式声明 claim→Fact；pre-commit 也没有最终 window 的冻结 token | `multidev/codex-rs/core/src/context/team_protocol_instructions.rs:30-33`、`team-state/src/store/evidence.rs:97-127` |
| `team_evidence` 只在权限通过后按需读取单条 observation，正文最多 4,000 字符且可能已不可用 | 将 evidence body 全量塞给 Critic 既不是当前 publication 接口，也会扩大上下文与时效问题 | `multidev/codex-rs/core/src/tools/handlers/team_tools/evidence.rs:29-60`、`core/src/team/evidence.rs:34-38` |
| `team_history` 可读取一个可见 Event 的有界 Version chain | 对 existing Event 可构造有限上下文，但必须先做 token census，不能默认喂完整历史 | `multidev/codex-rs/core/src/tools/handlers/team_tools/history.rs`、`team-state/src/store.rs:691-761` |
| Active World Index 每次请求从 canonical state 重建，不写入普通 history；空间不足显式拒绝采样 | Critic packet 应是独立、版本化、可计数的投影，不能偷用 Producer transcript 或复制整个 world index | `multidev/codex-rs/core/src/team/projection.rs:1-16,47-125` |
| Team Lens 当前是 body-free 离线消费者，主要保留数量、关系与状态而非 handoff 正文 | `team_view.json` 可做来源索引/统计，不能直接当训练正文 | `eval/rondo_eval/team_lens/`、`doc/WBS/multi-agent-trusted-evidence.md:142-180` |

### 2.2 与 Plan 050 的关系

用户希望在 050 收口后考虑本项目。当前 `main`、WBS 与完成记录均表明 050 已完成并通过修复后独立复验，但 WBS 尚未排定新的工作包；因此本文只收敛研究与工程候选，不自行把本项目登记成后续任务。050 证据只按以下边界使用：

- 050 的真实 collaboration trace 可在未来作为少量 real-world sanity anchor 和 scenario 来源；
- tracked Team Lens 输出是 body-free 的，不能还原训练所需 publication 正文；
- 如需从 ignored 原生 trace 提取正文，必须在正式任务内新增明确、最小的 body-bearing projection 和数据边界；
- 三道任务样本量不足以承担主体训练集，也不能把它们包装成统计性 Critic benchmark；
- 不为本研究稿查看原始 trace，也不把 050 的三题条件性结果外推成 Critic 的训练或产品效果证据。

## 3. 问题定义、职责与非目标

### 3.1 研究问题

ML 问题：在最终 runtime 仍只需要 `PASS/REWRITE` 时，单条 Binary supervision 之后依次加入原子 Boundary/Q± pair 和少量可靠 Within-PASS pair，能否让同一个本地小模型更好地判断 publication qualification？

工程问题：一个 bounded、可本地推理的 Critic，能否在不接管 Producer semantics、不改变 Root 职责和 Team State canonical 不变量的前提下，作为 `team_publish` 的可关闭前置 gate 工作？

### 3.2 角色边界

| 角色 | 负责 | 不负责 |
|---|---|---|
| Producer | 选择公开内容，撰写 title/summary/handoff，收到反馈后自行重写 | 向 Critic 暴露完整私有上下文；服从 Critic 对全局任务的规划 |
| Critic | 判断候选 packet 是否达到最低公共状态质量；在合格区学习少量稳定表达偏好 | 决定 Event 是否值得存在、routing、spawn、任务拆分、根因、Fact 真伪或遗漏的私有发现 |
| Harness | canonicalize packet，调用/校验本地服务，执行 PASS/REWRITE 分支和 attempt 上限 | 代替模型做高层语义总结；建立第二份 Team State 或第二套 trace |
| Root | 阅读公共状态，route/resolve/retire，协调团队并承担最终任务结果 | 被 Critic 取代；把 Critic 判定当成世界真相 |

核心原则保持为：

> Producer owns semantics；Critic evaluates publication qualification；Harness enforces the bounded protocol；Root owns coordination.

### 3.3 第一版明确非目标

- 不读取完整 Producer/sibling transcript、隐藏 reasoning、整个仓库或全量工具历史；
- 不把内部训练标量声称为跨任务、客观且完整的“总体质量”；不对缺少可靠对应关系的 PASS 强行排序，不训练 `REWRITE > REWRITE`；
- 不自动改写 handoff，不让 Critic 生成新事实或下一步计划；
- 不做 evidence 真伪、跨 Version 逻辑链、时效性或因果蕴含验证；
- 不决定是否发布、发布给谁、是否委派或如何分工；
- 不建立多教师委员会、人工标注团队、重型 reward-model 平台或多底模排行榜；
- 不把第一版扩张成真实任务成功率的因果实验；
- 不把 Local approval 的模型、schema、GGUF 路径和 launcher 默认带入 Multi 产品。

## 4. Runtime 合同候选

### 4.1 推荐数据流

```text
Producer 调用 team_publish
        ↓
解析身份、目标与 based_on_revision
        ↓
用 Team State 公共纯函数 canonicalize title/summary/handoff
        ↓
构造 bounded、versioned Critic packet（store 锁外）
        ↓
Local Publication Critic
   ├─ PASS ─────→ 调用现有 TeamStore::publish 原子提交
   ├─ REWRITE ──→ 不提交、不推进 evidence cursor；把固定反馈交回 Producer
   └─ INFRA ────→ 按冻结 fallback 处理，绝不伪装成业务 REWRITE
```

最自然的 hook 是 `multidev/codex-rs/core/src/tools/handlers/team_tools/publish.rs:34-77`：该 handler 已是 async，并且调用 store 前已经拿到权威 actor、target、submission 与 draft。模型客户端应在 `core` 的独立模块或小 crate 中；`team-state` 只保留同步 domain invariants、canonicalization 纯函数和必要的只读 packet projection。

### 4.2 Packet schema 的最小语义

精确 JSON schema 要在实现任务中生成并冻结；目前先冻结字段职责，不冻结 token 数和 Event 历史条数。

| 字段组 | 来源 | V1 语义 | 上限/缺失处理 |
|---|---|---|---|
| `schema_version`、`rubric_version` | Harness 常量 | 绑定输入与判据，拒绝未知版本 | 必填 |
| actor role 与 target kind | 权威 session + parsed request | `root/member`、`new_event/existing_event`；不接受模型自报身份 | 必填 |
| `title` | 新 Event request 或 canonical Event | 定义局部事项；existing Event 不让 Producer重复写标题 | canonical 200-char 合同 |
| bounded Event context（候选） | 待调研的 canonical projection | 若实测需要，可帮助 existing Event 理解“本次是增量 checkpoint”；是否包含历史以及采用原文、摘要或其他投影均未冻结 | 先做真实样本调研、token census 与小型消融；省略必须显式 |
| `summary` | canonicalized request | 必填，描述本次结论或状态变化；是主要被审内容 | canonical 2,000-char 合同 |
| `handoff` | canonicalized request | 可选；仅在确有后续动作时描述接手位置，不要求终态样本硬写下一步 | canonical 1,000-char 合同；缺失是合法值 |
| evidence policy marker | Harness | V1 固定声明 `semantic_entailment_not_evaluated`；可选提供新 Fact 数量/类别等非正文 metadata，但不能推断支持关系 | 是否提供 metadata 待小样本实验 |
| overflow/stale metadata | Harness | 告诉 Critic context 是否省略、读自哪个 revision；不把旧视图伪装成完整状态 | 必填显式状态 |

禁止进入 packet：完整 transcript、hidden reasoning、sibling 私有内容、全 Team State、未筛选工具正文、密钥、原始 trace、整个 repository 或无界 Event history。

Event context 仍是研究问题，不是本文已经决定的 V1 必填输入。new Event 至少有 canonical title；existing Event 可以比较“不带历史”“最近 N 条有界 Version”“更窄的确定性投影”等候选，再根据真实 publication 样本、C0 表现、token 分布和错误切片决定。本文不预先冻结具体内容、条数或 token 上限。

实现前必须解决 canonicalization 的单一来源。推荐把当前 `clamp_title/clamp_summary/clamp_handoff` 变成 store 与 packet builder 共用的纯函数；另一可接受路线是显式拒绝超长 draft。Critic 直接审未截断原文、store 再静默写入截断文本不可接受。

### 4.3 Evidence V1 边界

原稿在“只做形式检查”和“判断 evidence 是否足以支持 claim”之间来回切换；当前代码证明后者不能直接落地：

1. Fact 由 Harness 在 retained tool result 边界 mint；
2. Producer 调用 `team_publish` 时不选择、也不知道本次最终附上的全部 Fact；
3. store 只有在成功 commit 时才取走当前 window 并推进 cursor；
4. Critic 网络调用期间可能产生新 Fact，因此简单 `peek` 不能保证它看到的就是最终 Version 附带的列表；
5. Event 结论可能依赖旧 Version 的 Fact，本次增量 window 本身不是完整逻辑依据。

所以 V1 采用以下保守定义：

- V1 明确不引入 authored claim→Fact 显式 grounding；
- Critic 判断文字是否诚实区分 `observed / inferred / suspected / unknown`；
- 没有 evidence 不自动触发 REWRITE，明确标注的 hypothesis 完全可以 PASS；
- 有 Fact 数量或 ID 也不自动让强 claim PASS；
- Critic 不读取 observation body，不判断 Fact 可靠性、是否仍适用或能否蕴含结论；
- 不要求“强 observation claim 必须显式绑定某个 Fact”；如果未来另立产品协议增加 authored claim→Fact 合同，再由确定性代码检查引用存在性，不能倒推为 V1 已有能力。

如果未来确实要做 semantic evidence checking，应单独设计 `prepare_publish/reservation/token → critic → commit exact packet`，同时定义跨 Version 引用与 bounded evidence body；不能在 handler 中临时 peek 后声称原子一致。

### 4.4 输出、模式与失败语义

模型侧 V1 只生成严格枚举 `PASS` 或 `REWRITE`，本地 adapter 负责拒绝多余文本、未知 token、空响应和 schema 漂移。离线评测可以读取内部 `desirability_score` 进行阈值选择；该标量同时承载以 qualification 为主体的门槛和少量稳定软偏好，但产品公开合同仍只有离散判定，不公开或宣称一个客观总体质量分。

推荐按三种模式落地：

| 模式 | 行为 | 用途 |
|---|---|---|
| `off` | 完全沿用当前 `team_publish` | 默认值与零行为回归 |
| `shadow` | 调 Critic并记录 typed verdict/latency/infra，始终执行原 publish | 先观察输入、错误与时延，不影响任务 |
| `enforce` | PASS 提交；前两次 REWRITE 阻止当前 draft 并允许重写；最终稿只审核和记录、不再阻止发布 | 模型与 runtime 验收后启用 |

当前成功 tool output 只有已提交的 event/version/revision/evidence 等字段，尚无“未提交但需要重写”的合法 union。后续实现必须在以下两条路线中明确选择：

- **Tagged output union（语义更干净）**：`published` 分支保留现有结果，`rewrite_required` 分支携带 attempt-specific 固定提示、剩余次数与最近一次被拒绝的 canonical publication；代价是 tool schema 和 Team Lens 消费者需要同步更新。
- **RespondToModel error（改动更窄）**：把 REWRITE 作为可恢复工具反馈；代价是 expected policy outcome 会被记为 tool failure，观测和指标容易混淆。

本文倾向 tagged union，但把 wire shape 留给 ExecPlan 根据实时消费者冻结。

Rewrite 必须有 Harness-owned 硬上限，不能依赖模型自觉。V1 每个 publication cycle 最多提供 **两次重写机会**：原稿和第一次改稿若得到 REWRITE，可分别触发一次重写；第二次改稿作为最终稿仍做一次非阻断检查，但无论结果如何都发布。cycle identity、跨 call 计数和 turn 结束清理必须由 Harness 定义，因为未提交调用不会进入 TeamStore 的 committed retry map。

两次重写反馈由 Harness 选择不同的版本化固定模板，而不是让 Critic 自由生成理由：

- 第一次提示聚焦最低 publication qualification，要求在保留已知事实的前提下补足状态、区分确定性并清理无价值过程；
- 第二次提示明确这是最后一次重写机会，要求对照最近一次被拒绝的 publication 做定点修正，不删除已经合格的信息，也不为了通过而引入新事实；
- 两次反馈都回显**最近一次**被拒绝的 canonical `title/summary/handoff`，不依赖 Producer 是否仍保留先前 transcript；不累积更早候选或整段会话，避免上下文无界增长。

这仍然保持模型业务输出只有 `PASS/REWRITE`。固定提示、attempt index、剩余额度和 rejected candidate 都由 Harness 生成或回显，不是 Critic 的自由文本解释。将来只有实测证明这套反馈不足时，才研究受限 reason enum。

| 条件 | 已决定行为 | 必须避免 |
|---|---|---|
| 最终非阻断检查 PASS | 发布最终稿并记 `passed_after_rewrite` | 因曾经 REWRITE 而伪称最终仍未通过 |
| 最终非阻断检查仍 REWRITE | 发布最终稿并记 `exhausted_unapproved` | 无限循环；伪称最终 PASS |
| timeout/连接失败/服务未加载 | 发布并记 `infra_bypassed`，含义是未完成审核 | 把未审核伪装成 REWRITE、PASS 或“审核未通过” |
| malformed/未知 schema | 发布并记 `infra_bypassed`，另带 typed contract failure subtype | 静默猜标签 |
| Producer/turn 取消 | 不提交、不推进 cursor，清理 cycle state | 留下幽灵 attempt |

上述 fail-open 与重写上限已经由用户确认：该 gate 是协作质量优化，不是安全审批边界。`infra_bypassed` 表示没有完成审核，`exhausted_unapproved` 表示完成了审核但未通过，两者不得合并。状态至少进入开发者可观测的原生 trace、Team Lens 或指标；V1 不要求把它写入 canonical Team State、tool 正文或主动暴露给 Root/团队。

### 4.5 并发与 stale 语义

Critic 调用必须在 TeamStore mutex 外 await。调用期间 Event revision、可见性或新 Fact 可能变化；现有 append 语义会对旧 `based_on_revision` 标记 stale，而不是拒绝。最小 V1 应：

- 若最终采用 Event context，packet 记录该 projection 读取时的 revision；
- Critic 主要审 candidate 自身和有限上下文，不声称 gate 与 commit 是原子事务；
- PASS 后仍由现有 store 重新执行权限、目标、retry 与 stale 判断；
- 并发变化导致 store 拒绝时返回原生 TeamError，不能绕过；
- 只有实测证明 stale context 使判定失真，才增加一次有限 recheck，不能无限重评。

Critic 还必须保留现有 publish 的幂等语义。当前 dedup 只在 `TeamStore::publish` 内按 `(actor, request_id)` 检查；如果把 Critic 直接前插，同一已提交请求的稳定重放会重复推理，甚至因本次模型输出 REWRITE 而挡住原本应返回的 committed outcome。实现需要在不产生副作用的前提下选择一种路径：

- 在 store/handle 增加只读 committed-outcome fast path，先返回完全匹配的既有结果；或
- 在 session service 以 `team instance + actor + request_id + canonical request fingerprint` 绑定 Critic 与 commit outcome，重放只返回原结果；
- request identity 相同但 canonical fingerprint 不同仍必须拒绝，不能让缓存掩盖现有冲突语义。

多个 Agent 可以同时 publish，而本地 GPU 服务目标仍是单请求/低并发。Critic client 必须显式配置有界并发、有限队列和独立 timeout；排队/取消/超时不得持有 TeamStore mutex、创建 Version 或消费 evidence。不能依赖 llama server 的隐式队列作为 Harness 资源合同。

## 5. Qualification rubric

### 5.1 Hard requirements：决定 PASS / REWRITE

| 维度 | PASS 最低条件 | REWRITE 条件 | Critic 不负责什么 |
|---|---|---|---|
| State transfer | 相对当前 Event/local scope，能说清本次发现、结论或状态变化；允许很短 | 只有“发现一些问题”“还需调查”等几乎无状态内容 | 判断 Producer 是否遗漏私有上下文中的发现 |
| Uncertainty preservation | observed、inferred、suspected、unknown 的语气与 packet 所呈现状态一致 | 把未验证猜测写成已证实结论，或混淆未知与事实 | 独立调查世界真相 |
| Continuation | 当工作确实未完成时，接手者知道已排除什么、卡在哪里或接下来应从哪里继续 | 明显未完成却没有可接续状态 | 判断下一步是否全局最优；要求已完成事项编造下一步 |
| Scope discipline | 保留公共 checkpoint 所需信息，少量冗余不影响 PASS | transcript dump 或过程流水严重淹没核心状态 | 追求固定长度或某种文风 |
| Internal coherence | summary、handoff 以及实际采用的 Event context（如有）不自相矛盾；handoff 与当前状态相容 | 同一 packet 内出现关键冲突或无从执行的交接 | 解决 Event 历史中的全部争议 |
| Evidence/epistemic V1 | 没有 evidence 时仍诚实保留不确定性；不借 Fact 外观夸大确定性 | packet 本身暴露明显的确定性越级 | 验证 Fact 内容、时效、蕴含链或 claim→Fact 绑定 |

两个最小边界例子：

- `测试稳定复现 reload 后仍为旧值；缓存路径尚未验证。` 可以 PASS，因为 observation 与 hypothesis 分开。
- `测试已经证明缓存就是根因。` 在 packet 只呈现“旧值仍存在”时应 REWRITE，因为文字把未知机制升级成事实；这不是 Critic 对真实缓存逻辑的独立判决。

### 5.2 Soft preferences：只塑造 PASS 区

在 hard requirements 都满足且核心语义等价时，RONDO 稳定偏好：更直接、更少重复、更高信息密度、更少无价值过程叙述。软偏好不形成隐藏门槛：稍长但完整可靠的 packet 仍然 PASS，更短但丢失必要状态的 packet 必须 REWRITE。

Handoff quality 是多维偏序，不是一条绝对轴。以下情况不建立 pair：

- A 更短，B 对 uncertainty 更清楚；
- A continuation 更强，B 状态描述更完整；
- 两者都有不同但不越过门槛的弱点；
- 两个 REWRITE 只是“谁没那么差”。

## 6. 数据合同与生成

### 6.1 三层监督

| 数据类型 | 标签/方向 | 作用 | 是否覆盖全部样本 |
|---|---|---|---|
| Binary qualification | 每条 `PASS` 或 `REWRITE` | 学 publication threshold | 是 |
| Boundary pair | `PASS > REWRITE` | 强化门槛两侧差异 | 否 |
| Q+ / Q− | near-boundary `Q+ PASS > Q− REWRITE` | 学最小跨阈值变化 | 少量高质量核心 |
| Within-PASS pair | `PASS preferred > PASS` | 在合格区塑造稳定软偏好 | 少量、克制 |
| REWRITE pair | `REWRITE > REWRITE` | 首版无明确产品价值 | 不做 |

Q± 采用用户提出的硬约束：同一 scenario、task state、Event context variant（包括双方都不带）和 evidence policy，只改变一个 target dimension；除该差异外，其他 hard dimensions 必须分别能 PASS，长度和文风尽量接近。做不到时保留为单条 Binary 或自然 mixed case，不进入 Q pair。

自然 mixed cases 仍然必要，例如“结构简洁但有关键 certainty 越级”或“略显冗余但状态完整”。它们用于防止模型只识别教师模板；多维 trade-off 通常只给 Binary 标签，不强造比较方向。

### 6.2 建议的逻辑 schema

不直接复用 Local approval 的 allow/deny schema，只复用其版本化、哈希、分组和 manifest 模式。Publication Critic 专用合同至少分三种对象：

| 对象 | 关键字段 |
|---|---|
| Scenario | `scenario_id`、`scenario_group_id`、`template_family`、`source_kind`、Event context variant 与 optional bounded projection、evidence policy、rubric version、source trace identity（如有） |
| Candidate | `candidate_id`、canonical title/summary/handoff、Binary label、defect tags、controlled dimension、generator/reviewer identity、split |
| Pair | `pair_id`、kind、preferred/rejected candidate IDs、changed dimension、non-target hard dimensions pass、pair reviewer decision |

建议 defect metadata：`vague_state`、`uncertainty_collapse`、`missing_continuation`、`scope_bloat`、`redundancy`、`low_information_density`、`internal_conflict`、`evidence_overclaim_v1`。它们用于数据校验和 error slice，不要求 runtime 模型输出。

### 6.3 数据来源与质量控制

数据来源按以下比例关系组织，但不在模型与 token census 前写死样本数：

1. **少量真实 anchors**：经授权从 050 或后续真实协作 trace 做受控 projection；只作为 scenario 参考、holdout/sanity 和集成案例，不直接导出完整 transcript。
2. **教师合成主体**：覆盖新/旧 Event、终态/未完成态、无 evidence、有 metadata、受控单缺陷与自然 mixed case。
3. **对抗捷径样本**：短但好、长但空、有 Fact 外观但过度断言、无 Fact但 uncertainty 正确、正式文风但不合格、口语化但状态有效。

当前用户倾向的质检链为：

```text
teacher generator session
        ↓
independent teacher-review session（不读取生成意图）
        ↓
validator / dedup / grouped split / freeze
        ↓
final blind judge（不同模型家族，只用于最终横评）
```

精确模型稍后冻结；这里冻结的是**角色分离**。独立同模型会话可以降低自我确认，但仍不是人类 ground truth，最终报告必须把它称为 teacher reference。

### 6.4 Grouped + stratified split

- 同一 `scenario_group_id`、同一 pair/Q 组、同模板近改写、同一真实 trace source group 只能进入一个 split；
- 用规范化文本的 exact hash 与近重复连通组防止改几个词后跨 split；具体算法/阈值沿用既有模式但由新数据合同重新冻结；
- 同一题型或 defect category 可以跨 split，且 train/validation/test 都应覆盖核心训练方向；
- 不追求“测试题与训练题类型完全不同”，只阻止具体内容和模板泄漏；
- test 在生成与调参阶段冻结隔离，threshold 只在 validation 选择；
- pair 两端绝不能跨 split。

## 7. 分阶段训练实验

### 7.1 单一 lineage 与 checkpoint 比较

| Checkpoint | 初始化 | 新增监督 | 必须保留的旧监督 | 主要比较 |
|---|---|---|---|---|
| C0 | 选定底模 | 无微调 | 无 | 未训练基线 |
| C1 | C0 | Binary qualification | — | C1 vs C0：普通二分类是否有效 |
| C2 | C1 | Boundary pair，重点 Q± | Binary replay/anchor | C2 vs C1：边界监督是否增益且不破坏门槛 |
| C3 | C2 | 少量 Within-PASS pair | Binary + Boundary replay/anchor | C3 vs C2：软偏好是否增益且不损害 qualification |

每个 checkpoint 都保存模型/adapter、数据 manifest、recipe、dependency identity、训练 receipt 和同一 held-out 输出。C3 变差时可以保留 C2 为产品候选；“最后训练的”不等于“必须部署的”。

连续训练的代价必须诚实记录：C1/C2/C3 的总训练量不同，且 C2/C3 存在灾难性遗忘与顺序效应，因此增量比较适合回答工程问题，但不是严格隔离数据类型的因果论文实验。首版不要求再从 C0 独立训练三套模型；如果结果难解释，再补一个小型 compute-matched ablation，而不是预先扩大训练矩阵。

### 7.2 Pair objective 的可实现定义

标准 DPO 通常比较**同一 prompt 下两个 completion**；本项目的 pair 是两个不同 publication input，因此不能只把 JSONL 塞进普通 DPO trainer 就声称学会了 qualification 排序。

推荐让 Binary 与 Pair 共享一个单样本 **publication desirability score**：

```text
s(x) = log P(PASS | x) - log P(REWRITE | x)

L = L_binary
  + λ_boundary · -log sigmoid(s(x_pass) - s(x_rewrite))
  + λ_within   · -log sigmoid(s(x_preferred_pass) - s(x_other_pass))
```

这可以由 causal LM 的受限标签 log-prob、或带分类头的 encoder/decoder 实现；具体框架取决于学生模型及本地部署路线。这个 `s(x)` 并非纯粹的 threshold distance：Binary 与 Boundary 让 qualification 成为主体，少量 Within-PASS 则让它在合格区内部带有较弱、局部的 RONDO 稳定偏好方向。因此 V1 确实使用了一个训练方便的一维标量，但不声称所有 publication 存在客观、完整、可跨任务比较的总体质量顺序。

Within-PASS 必须数量少、`λ_within` 较低、偏好明确，且两端继续接受强 Binary PASS anchor；这样可以要求 `s(preferred PASS) > s(other PASS)`，同时避免把较弱一侧推过 REWRITE 门槛。`λ`、replay 比例、学习率、步数和正则化在 one-step smoke 与 validation 前冻结，不在本文猜数值。

### 7.3 模型选择保持开放

选型顺序应是：先冻结 packet schema并对 synthetic/real anchors 做 exact token census，再比较少量候选的 C0 能力、训练兼容性和本地运行成本。筛选条件包括：

- 能可靠区分事实、推测、未知和状态可接续性；
- 对短结构化输出或 PASS/REWRITE log-prob 支持良好；
- 训练框架能实现共享 Binary + pair desirability score，而非只有 completion preference；
- context 覆盖真实 packet 分布，不靠截断关键状态；
- 可在 RTX 4060 Laptop 8GB 的本地目标下达到可接受显存、延迟和稳定性；
- tokenizer/template、量化/导出与许可路线可冻结复现。

上一项目已经验证 exact b10333 llama.cpp + 8B 级 Q4_K_M + 12,288 context 的一个特定 Local approval 路线能在本机工作；这只是部署经验，不是本项目的模型、context 或 runtime 决定。3B/4B、7B/8B 及其他规模都应由 C0 与 packet census 决定。

## 8. 离线评价与最终横评

### 8.1 统一评价矩阵

C0、C1、C2、C3 使用同一冻结 test 和相同 decode/timeout 合同，至少报告：

- Binary：balanced accuracy、PASS/REWRITE 分区准确率、macro F1、malformed/timeout/infra 比例；
- 错误成本：False PASS（低质状态进入 Team State）与 False REWRITE（额外调用、延迟和重写风险）；
- Boundary：普通 boundary pair accuracy、Q± pair accuracy、margin 分布；
- Within-PASS：只在冻结、双 PASS、单软偏好样本上计算 pair accuracy；
- slices：按 defect、source、new/existing Event、终态/未完成、长度区间、evidence policy 分组；
- 工程：input/output tokens、P50/P95 latency、峰值显存、服务可用率。

若模型暴露 `desirability_score`，qualification threshold 只在 validation 按预先定义的错误代价选择并冻结；test 不回调阈值。不能通过把所有样本判 REWRITE 来制造“安全”的表面结果，也不能只看 overall accuracy 掩盖某一侧错误。

### 8.2 最终盲横评

终审输入至少包含 teacher reference、C0、C1、C2、C3；隐藏来源并平衡展示顺序。终审模型只按同一 rubric 对回答与 pair 方向判定，不读取训练 checkpoint 名、生成意图或原始私有 trace。教师 reference 与终审都可能有偏差，因此需要同时保留机械标签指标、模型 judge 结果和少量人工 spot check，而不是把单个裁判写成绝对 ground truth。

### 8.3 能得出与不能得出的结论

第一版在证据充分时可以说：

- 某 checkpoint 在冻结 test 上相对 C0/C1 改善了哪些 qualification 或 pair slices；
- 本地服务在冻结硬件、packet 与并发合同下可运行；
- shadow/enforce 的 PASS、REWRITE、上限与 fallback 分支满足功能合同；
- feature off 时原 `team_publish` 行为没有回归。

第一版不能仅据此说：

- Critic 已提升 RONDO Multi 的总体任务成功率、协作质量或成本；
- teacher/judge 标签等于客观真理；
- Evidence semantic correctness 已经解决；
- 050 三题或少量真实 anchors 代表一般多智能体任务分布；
- 最后一个 checkpoint 必然优于前面 checkpoint 或适合默认启用。

## 9. 现有工程资产、RunPod 与 Hugging Face

### 9.1 复用的是机制，不是上一任务的模型合同

| 现有资产/工具 | 已有能力 | 本项目建议 | 不能直接继承 |
|---|---|---|---|
| `training/` + `eval-data/` 分层 | tracked 轻量数据/合同与 ignored 私有正文/权重分离 | 新建 Publication Critic 专用 dataset/schema/data card/manifest；大正文按现有体积门限分流 | Local approval 的 allow/deny payload |
| `eval/rondo_eval/local_approval/synthetic_training.py` 模式 | schema/hash、group split、近重复、exclusive publish、recompute manifest | 抽取/复用通用机制，建立 Candidate/Pair validator | 原 600 条审批样本与类别 |
| Local L6 bundle | train-only allowlist、token census、mock、smoke/formal、resume、receipt、artifact verify | 为新任务做独立 bundle 和多 checkpoint receipt | Ministral revision、4K、LoRA regex、旧 recipe |
| conversion contracts | converter/quantizer identity、逐文件 hash、artifact allowlist、paired route | 等模型确定后复用模式 | b10333/Ministral 专用 closure 与 GGUF 必选结论 |
| 本地 launcher/client | loopback-only、no redirect、response cap、零自动重试、schema 复验、launcher identity | 实现 Publication Critic 专用 Rust client/adapter 与配置；可复用这些安全/稳定模式 | Python approval-v3 client、`[auto_review]`、现有模板和 12K 参数 |
| Team Lens | 复用原生 trace，确定性 body-free reducer/viewer | 解析 typed critic outcome/latency/count；不新建 trace writer | 训练正文 |
| RunPod MCP | 当前会话可见 capacity/billing、Pod create/get/start/stop/delete、bounded logs 等控制面 | 授权后作为单 Pod 控制面；状态与账单复核自动化 | 已认证、已有余额、实时容量/价格已经验收的说法 |
| SSH/SCP runbook | verified tar、远端 bundle verify、日志、回收、删除闭环 | 继续承担 RunPod 数据面；MCP 不替代文件传输/远程 shell | 旧任务的固定 GPU、镜像和目录 |
| HF CLI | 本机入口存在；历史 runbook 已使用 exact revision/file download 后切 offline | 模型调研、dry-run/下载、cache verify、tokenizer/base exact revision | 当前登录、私有 repo、上传链已可用的说法 |

本机可见 `/home/sjc/.local/bin/hf` 和 eval venv 的 `hf`；本轮未检查 token、账号或远端权限。RunPod MCP 工具面也只证明当前开发会话存在相应能力，不证明认证、余额、容量和实时价格。它们都应在正式任务的授权前门做只读 preflight。

### 9.2 建议的云端训练闭环

1. 本地完成 packet schema、validator、split、C0 基线和 train-only bundle；test/holdout 不进入训练 bundle。
2. 用 HF CLI/官方 metadata 冻结学生 base/tokenizer exact revision，并把下载文件与大小纳入 model contract；下载后训练/转换尽量 offline。
3. 在 ExecPlan 中冻结数据量、C1/C2/C3 最大步数、单一 GPU 候选、预计费用和硬上限。用户当前预算意向约为 RunPod **30 USD 以内**，它不是本研究稿赋予的执行授权。
4. 获得明确授权后，由 RunPod MCP 只创建一个 Pod并持续读取状态/账单；verified tar + SSH/SCP 传输数据和脚本。
5. 先 one-step optimizer smoke 与独立 reload；通过后才顺序训练 C1、C2、C3并保存各阶段 checkpoint。失败不得盲重跑或另起并发 Pod。
6. 回收 allowlisted adapter/checkpoint/recipe/metrics/receipt，逐文件 hash 验证；训练数据、validation/test、逐样本输出、凭据不随模型工件回传或上传。
7. 只有模型选型证明需要时才做 GGUF/其他格式转换和本地 smoke；先结束云端计费，再跑 C0–C3 串行离线评价。

HF 私有 repo 可作为可选的工件镜像，但现有仓库尚没有 Publication Critic 的 upload allowlist/staging verifier；默认仍是本地 SCP 回收。HF Jobs 虽可由 CLI 使用，但当前仓库没有对应训练状态机，而且同时维护 RunPod/HF 两套云后端收益很低，首版不纳入。

### 9.3 数据落点

建议命名空间（仅设计候选，实际创建由后续 plan 冻结）：

- `eval/rondo_eval/publication_critic/`：validator、split、census、offline runner、judge import；
- `eval/templates/publication-critic/`：versioned packet/rubric/generation/review/judge schemas 与 prompts；
- `training/multi-publication-critic-v1/`：体积合规的 train/validation、manifest、data card；
- `eval-data/publication-critic/`：真实 projection、raw candidates、test/holdout、RunPod bundle、权重和逐样本输出；
- `eval-data/models/`：最终本地模型/adapter，永不入库。

不在 `mydev/` 放 Multi 数据，也不把 `training/` 接入 Rust build。

## 10. 工程接入与验证范围

### 10.1 推荐模块边界

- `multidev/codex-rs/core/.../team_tools/publish.rs`：只负责 hook 编排和把 typed outcome 转成工具结果；
- 新的 `core` 模块或小 crate：packet schema、client、response parser、mode/timeout/attempt state；
- `team-state`：仅在必要时公开 canonicalization 纯函数和 bounded read projection，不引入网络、模型或 async；
- 现有 rollout trace：记录 typed critic outcome，不建第二套 critic trace；
- Team Lens：从原生 trace 归约 verdict/infra/latency/count，不保存 packet 正文；
- 独立 `[publication_critic]` 非密钥配置与 `.env.local` 所需变量检查；不复用 `[auto_review]` 的模型身份。

### 10.2 最小实施切分

| 阶段 | 交付物 | 退出条件 |
|---|---|---|
| A 数据与 packet | schema、rubric、canonical builder、token census、validator、少量真实/合成 anchors | packet 与 Evidence V1 不再依赖假接口；C0 可评 |
| B 数据集与 C0/C1 | generator→independent review、group split、C0、Binary C1 | test 冻结；Binary 有区分度且无明显 shortcut |
| C Pair 训练 | C2 Boundary/Q±、C3 Within-PASS、前序 replay、全 checkpoint receipts | 同一矩阵完成；是否保留 C2/C3由结果决定 |
| D 本地服务资格 | 模型特定导出、loopback client、identity、schema/latency/显存 smoke | 本地单并发 bounded packet 可稳定判定 |
| E Runtime | off→shadow→enforce、attempt cap、fallback、Team Lens 指标 | 相关测试通过；off 零回归；无无限 loop |

这是候选技术切分，不是 WBS 路线；正式任务可以把 A–E 合并或拆分，但不得在数据合同未闭合前直接跳到付费训练。

### 10.3 关键回归

实现阶段至少覆盖：

- canonical packet 与最终持久化文本逐字一致，超长输入没有“审 A 写 B”；
- feature off 不增加请求、不改变 tool schema 行为、revision、wake、evidence、retry 或 latency 路径；
- shadow 的 PASS/REWRITE/infra 都仍只提交一次原 Version；
- enforce PASS 保留现有 event/version/revision/stale/dedup/evidence window 语义；
- enforce 中额度内的 REWRITE 不创建 Event/Version、不推进 revision/wake/evidence cursor，下一次成功 publish 仍关联完整未消费 window；
- 两次重写机会、最终非阻断检查及 cycle 清理严格命中冻结状态机；最终 REWRITE 仍只提交一次并记 `exhausted_unapproved`；
- 第一次、第二次 REWRITE 返回不同的版本化固定提示，均逐字回显最近一次被拒绝的 canonical publication；不累积旧稿或泄露其他上下文；
- timeout、连接失败和 malformed 均发布并记 `infra_bypassed`，取消则不提交；两类状态不会混淆；
- Critic await 不持 TeamStore mutex；并发 append/新 Fact/stale view 不绕过 store 原生校验；
- 已提交 request replay 命中 committed fast path，不重复推理；同 request identity + 不同 canonical fingerprint 仍按原合同拒绝；
- 多 Agent 并发请求服从有界队列/并发/timeout，排队取消不串 cycle、不产生 mutation；
- fake server 覆盖严格 schema、body 上限、no redirect、零自动重试和身份漂移；
- Team Lens 只归约 typed outcome，不泄露 publication/evidence 正文；
- 本地真实模型 smoke 与训练/转换另行授权，不能用 fake 结果冒充。

若改 Rust，只通过仓库共享 build lock 运行受影响 crate 的必要测试；第一版不因本项目重跑全 workspace。

## 11. 决策与待决策登记

| 决策 | 用户选择/问题 | 本文判断 | 状态 |
|---|---|---|---|
| Evidence grounding | V1 不需要显式 grounding，也不让小模型验证逻辑链 | V1 只检查 uncertainty/epistemic wording，不读 body、不做 claim→Fact 绑定；以后如另立形式绑定协议，由确定性代码检查引用 | **已关闭（V1）** |
| 是否带历史 evidence | 增量 evidence 可能依赖旧证据，不能只看本次 window | V1 不携带 evidence body、不做 semantic evidence；如果 Event context 调研最终选择 authored history，它也不等于历史 evidence。未来 semantic 路线单独设计 exact reservation | V1 后评估 |
| Q± 非目标维度 | 其他维度全部 PASS | 采纳为 pair validator 硬约束 | **已关闭（V1）** |
| 训练方式 | C1→C2→C3 顺序续训并保留全部权重 | 采纳；加入前序 replay 与统一 test，并诚实记录顺序/总训练量混杂 | **已关闭（V1）** |
| Split 泛化强度 | 防具体/字面近重复即可，同类题可跨 split | 采纳 grouped + stratified，不做题型整体隔离 | **已关闭（V1）** |
| 生成/审查/终审 | 独立教师会话复核，异构强模型只做最终横评 | 角色顺序已采纳；精确模型版本仍待选 | 角色已关闭；模型待选 |
| 学生模型/context | 继续调研，不固定 | 先 packet census + C0，小候选集后冻结 | 训练授权前 |
| Pair loss 与标量语义 | 接受共享 score，但不能声称完全没有一维尺度或把它说成客观总体质量 | 使用 single-input publication desirability score；qualification 为主体，Within-PASS 以少量、低权重、强 Binary PASS anchor 做局部塑形；普通 completion-DPO 不能直接替代 | **已关闭（V1）** |
| Internal coherence | 同一 publication packet 内不能自相矛盾 | summary、handoff 以及最终选定的 Event context projection 之间存在关键冲突时 REWRITE；不扩张为外部事实调查 | **已关闭（V1）** |
| Event context | 仍需结合真实数据调研，不在研究稿定死 | new Event 至少使用 title；existing Event 对“不带历史/最近 N 条 Version/更窄投影”做 token census 与小型消融后再冻结 | **待调研** |
| REWRITE wire result | 原稿只写 PASS/REWRITE | 倾向 tagged published/rewrite union，需检查现有消费者 | Runtime ExecPlan |
| 最大重写次数 | 最多允许 Producer 重写两次 | 前两次 REWRITE 可阻断当前 draft；第二次改稿做最终非阻断检查并照常发布 | **已关闭（V1）** |
| 耗尽/infra fallback | 都继续发布，但开发者必须能区分“未审核”和“审核未通过”；不要求暴露给 Root/团队 | 最终 REWRITE 记 `exhausted_unapproved`；服务/contract 故障记 `infra_bypassed`；进入原生 trace/Team Lens/指标，不污染 canonical authored state | **已关闭（V1）** |
| runtime rewrite feedback | V1 不需要 Critic 自由文本理由；两次重写提示应不同，并带回最近一次 Producer 输出 | Harness 使用两个版本化固定模板，回显最近一次被拒绝的 canonical publication，不累积历史；受限 reason enum 仅在实测不足时再研究 | **已关闭（V1）** |
| 部署格式 | 倾向本地量化，但模型未定 | GGUF/llama.cpp 是已验证经验而非必选；模型确定后再选 | 本地资格计划 |

## 12. 主要风险与控制

| 风险 | 表现 | 首版控制 |
|---|---|---|
| 合成 shortcut | 长度、Fact ID、正式文风或教师模板代替真正理解 | 对抗反例、来源切片、近重复分组、真实 anchors |
| Pair 伪偏好 | 多维 trade-off 被强排，模型学风格而非门槛 | Q 原子差异 validator；mixed case 仅 Binary；Within-PASS 双方先独立 PASS |
| 连续训练遗忘 | C2/C3 qualification 下降 | 前序 replay、每阶段 checkpoint、同一 test；允许部署 C1/C2而非 C3 |
| Pair 目标错配 | 用普通 DPO 比较不同输入，runtime Binary 没共享 score | 显式 desirability `s(x)` + Binary/rank loss；qualification 为主体；one-step gradient/overfit smoke |
| Evidence 过度承诺 | 增量 Fact 被误当完整证明，小模型猜逻辑链 | V1 不读 body、不做 entailment，能力声明明确 |
| 审写不一致 | Critic 通过未截断文本，store 写入截断文本 | 共用 canonicalization 纯函数或拒绝超长 |
| 并发漂移 | 若采用 Event context，Critic 审查时的 projection 与 commit 时不同 | revision metadata + 原生 stale 语义；必要时一次有限 recheck |
| 幂等回放破坏 | 已提交 request 重放再次推理，甚至被新 verdict 阻断 | committed fast path 或精确 request/fingerprint outcome cache |
| 本地服务拥塞 | 多 Agent publish 把单 GPU 隐式队列拖到无界 | Harness 侧有界并发、队列和 timeout；取消无副作用 |
| 无限 rewrite | Producer 与 Critic 循环 | Harness-owned cycle；最多两次重写机会；最终检查非阻断 |
| 第二次重写失焦 | Producer 看不到上一稿或只收到同一泛化提示 | 两个 attempt-specific 固定模板；回显最近一次 canonical rejected candidate；不累积完整历史 |
| Critic 单点故障 | 本地服务 OOM/timeout 阻断团队状态 | off/shadow/enforce；故障继续发布并记 `infra_bypassed` |
| 离线外推 | test 变好被写成真实协作提升 | 只主张离线判断与功能接入；真实闭环另立项 |
| 双产品污染 | Local approval 配置/模型默认渗入 Multi | 独立 namespace/client/identity；只复用通用模式 |
| 云端费用/数据外发 | Pod、下载、上传或训练超出当前授权 | 精确预算与数据 allowlist；授权前只读 preflight；单 Pod 串行 |

## 13. 证据索引与收束判断

主要项目证据：

- 产品定位与规划边界：`README.md:16-23`、`doc/WBS.md:5-7,93-100`、`doc/WBS/multi-agent-trusted-evidence.md:21-88`；
- publication/tool surface：`multidev/codex-rs/core/src/tools/handlers/team_tools/spec.rs`、`publish.rs`；
- canonical Version 与字段上限：`multidev/codex-rs/team-state/src/model.rs`；
- publish 原子提交与 evidence window：`multidev/codex-rs/team-state/src/store.rs`、`store/evidence.rs`；
- evidence locator/read：`multidev/codex-rs/team-state/src/evidence.rs`、`multidev/codex-rs/core/src/team/evidence.rs`；
- request-only Team projection：`multidev/codex-rs/core/src/team/projection.rs`；
- 训练数据与资产分层：`training/README.md`、`doc/eval-data-layout.md`、`training/local-approval-synthetic-v1/DATA_CARD.md`；
- RunPod 训练/回收模式：`training/local-approval-l6/README.md`、`stage2-runbook.md`、`eval/rondo_eval/local_approval/l6_training.py`；
- 本地推理历史边界：`doc/WBS/local-approval-model.md`、`eval/rondo_eval/local_approval/client.py`、`launcher.py`；

收束判断：公共状态发布质量 Critic 是一个适合 RONDO 的小型 ML 工程问题，但当前最有价值的第一步不是扩大模型与训练矩阵，而是把真实 `team_publish` packet、V1 Evidence 边界、Binary/Pair 共享 desirability score 和 runtime fallback 写成一致合同。完成这些之后，现有 synthetic 数据管线、RunPod 单 Pod 状态机、HF exact-revision 下载、训练 receipt、转换验真、本地 launcher 经验和 Team Lens 都能提供高复用价值；复用时应保留机制，不能把上一项 Local approval 的任务专用模型、schema 和部署参数原样搬进 RONDO Multi。
