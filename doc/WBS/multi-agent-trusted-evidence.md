# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-08-18 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md` ｜ M-5 阶段 B 第五轮整改完成：门 1 判据改读 code-mode rollout trace（冻结 workflow v2），门 2 模型全链贯通，$120 成为数学上限；真实付费未执行

## 定位

RONDO Multi 不重做 Agent 执行面。Codex 原生继续负责 thread、spawn/fork、并行执行、shared workspace、mailbox、
wait/resume/interrupt、工具执行、sandbox 与审批。本产品线只解决一个问题：**多个拥有私有上下文和独立推理过程的
Agent，如何把真正值得团队持续知道的信息，变成一份 Harness 拥有、可追溯、不会因模型遗忘或上下文压缩而静默消失的
团队世界状态**，同时不互相广播 transcript 与推理过程。

设计原文见 `doc/research/RONDO Multi 当前最新完整设计（补充修订版）.md`，工程风险清单见同目录
《RONDO Multi 修正方案意见稿（工程落地版）》；两者都是形成时点的冻结证据，不随本页更新改写。
**本页是当前语义、阶段顺序与验收边界的唯一规划来源**：两份研究文档与本页不一致时，以本页为准。

第一版定位是工程实践、Harness 创新与技术训练，不以"跑赢原生 Codex Multi-Agent"作为存在前提。
成功率、成本、重复工具调用与发布负担都要测量并驱动迭代，但都不是准入门。

第一版预期团队规模 2–8 个 Agent，实际通常更少。不为几十上百 Agent 提前引入层级 coordinator、
topic subscription 或 learned routing。

**内核形态不受 Local 约束**：允许内核级重构，不要求与 `mydev/` 长期保持提交级一致。

## 设计语义合同

以下语义已定，后续每个阶段都受其约束。要改只在这里改，不在 plan、代码注释或提示词里另立一套。

### 状态与身份

1. 团队状态是**团队协作状态**（Event、Version、生命周期、可见性、指派）的唯一 canonical 来源。
   原始 observation 仍由 Codex 实际保留的 rollout / 工具结果承载，证据引用只是指针，不把 payload 复制进来；
   Event 与 Handoff 是 Agent 的语义判断，不是客观事实，也不是当前真理。模型看到的只是面向某个角色、
   某次采样的投影，投影不是事实来源。
2. Event 是团队级身份，Version 是这件事演化过程中不可变的阶段性条目。创建者只是 `created_by`，不拥有该 Event。
3. Version 的追加顺序只是登记顺序，不隐含因果继承，也不隐含后者替代前者；替代关系由显式状态表达。
4. Version 的 authored 内容（作者、Handoff、证据引用）写入后永不改写；生命周期状态是附着其上、可更新的投影。
   已进入终态的 Version 不原地重开；旧问题重新相关时追加新 Version。
5. 历史在**当前团队实例存续期内**追加式保留且可查询：已退出活动视图的 Event/Version 不删除，
   参与者可按权限调取自己有权访问的历史。这是"追加式历史"的意义所在，不是可选的调试功能。
   （跨进程持久化见候选池，第一版不要求。）
6. 一个 Event/Version/证据引用的完整身份包含它所属的**团队实例**。同一存活 Root 树内的成员被卸载后重新加载，
   仍属于原实例，继续沿用原有身份、权限与状态，**不得判为新实例、陈旧引用或 producer 真正不可用**。
   只有 Root 团队恢复时找不到对应团队状态、或引用的实例与当前不匹配，才开启新实例；此时旧投影、
   旧 route 通知及其中的引用一律只作历史，不得解析到新对象，并显式提示已重置。

### 双生命周期与注意力

这套生命周期的最小词汇如下，后续阶段按此实现：**producer 侧**第一版为 `open` / `closed`
（作者认为该 Version 所述事项是否仍需继续注意），第 11 条的 Root 退休是与作者关闭不同的独立终态，
`superseded` 只在第一阶段确有需要时作为更精确的终态加入；**Root 侧**为 `pending`（尚未显式处理）/
`tracking`（已判断但要求它继续占据注意力）/ `resolved`（当前协调已完成）。
**普通参与者新建的 Version 对 Root 默认 `pending`，Root 自建默认 `tracking`。**
Root 的 `resolved` 是协调注意力的结束，不等于 producer 认为问题已解决。

7. producer 侧与 Root 侧状态相互独立：Root resolved 不改 producer 状态，producer 关闭也不替 Root 完成消费。
8. 任何有资格的 Agent 追加新 Version，都使该 Event 重新进入 Root 的活动视图。
9. Root 自己创建的 Event/Version 默认进入 tracking 而非 pending，且不自我唤醒。
10. producer 关闭一个 Root 仍在 pending/tracking 的 Version 时，应使 Root 重新获得一次协调机会；
    Root 已 resolved 的旧 Version 仅发生 producer 侧变化时，不重新进入 Root 活动视图。
11. producer 已不可用而 Version 仍未终结时，由 Root 显式退休该 Version。它是**与作者关闭不同的独立终态**，
    记录操作者与理由，不冒充 producer 自己关闭。producer 可用性是派生元数据，
    "可恢复但当前未加载"与"真正不可用"必须区分。
12. 不做自动 escalation：Harness 不判断 Root 是否判断错误；持续异议通过发布新 Version 表达，不靠系统覆盖 Root。
13. **活动视图谓词**（统一适用于 Root 与子 Agent）：一个 Event 出现在某参与者的活动视图，当且仅当
    ——该参与者自己仍有未终态 Version，**或**存在面向它的进行中 route 指派，**或**（仅 Root）
    该 Event 仍有 root_state 未 resolved 的 Version。仅有历史可见性不使 Event 常驻活动视图；
    结束一个指派只撤掉其中一个纳入理由，不影响其余理由，尤其不得让参与者看不见自己仍未结束的事项。

### 投影与上下文

14. 参与者的活动视图必须在模型决定是否调用团队工具**之前**就已进入本次采样上下文，而不是工具调用之后才展示。
15. 团队投影与可压缩的消息上下文并列：不进入 conversation history 与 rollout，不被 compaction 改写，
    每次采样从当前团队状态重新生成。**同一次逻辑采样的全部 provider 重试必须复用同一份不可变快照**，
    只有下一次采样才取新快照。
    （因此 Codex 既有那条"渲染成 diff 片段并写回历史"的 world-state 通道不适合作为它的载体。）
16. 语义上默认投影完整 Version chain，但注入模型的内容必须有硬预算，**并且必须计入整次请求的上下文余量**
    —— 投影不进 history，所以 history 侧的估算不会替它兜底。超预算或逼近窗口时显式报告被省略的部分，
    并保留有界、按权限的历史下钻；不得静默截断，也不得由投影把请求顶爆。历史长度不直接转化为上下文长度。
17. **稳定规则放前缀，易变数据靠尾部。** 团队协议中不随轮次变化的部分（Event/Version 含义、生命周期状态的
    语义、工具契约与使用规则）属于参与者稳定且版本化的指令前缀；每轮变化的部分（当前活动视图、
    团队实例与版本号、省略清单）保持 request-only，附加在本轮完整正常输入之后的**最后一个协议安全位置**。
    投影不得越过尚未接纳的输入，不得插入或重排工具调用与其结果的配对。
    这条是缓存与正确性的共同要求：前缀缓存依赖从头完全一致的前缀，把易变内容放在前面会让其后的整段历史
    每轮失效。**原设计里"类似系统提示词那样的存在"指的是它不受消息累加与压缩影响，不是指把它放在请求开头。**

**这里有一处已接受的取舍**：request-only 投影会让当前 WebSocket 传输那条"本次输入必须是上次输入加上次响应的
严格扩展"的增量复用基本失效——上一轮的投影在这一轮已从原位置消失。它与服务端前缀缓存是两套机制，
把投影放在尾部仍然保住了指令与历史这段共享前缀。第一版按正确性优先：不为保住增量复用而把旧投影持久化、
重复携带或改成累积补丁，也不把团队版本号编进缓存键。缓存命中率与相关成本只作真实运行后的观测指标，
不作为任何阶段的门；若真实数据证明损失显著再单独立项，且不得反向破坏 request-only、快照新鲜度、
重试一致性与整次请求预算这四条语义。

### 变更提交

18. **增量提交**：模型只提交本轮真正发生变化的 Event/Version；未提及的活动项保持原状态，不要求机械复述。
    团队状态不是每轮 replace-all 快照 —— 模型某轮少说一句，不能让一个事项静默死亡。
19. 每次提交要能说明它基于哪一份团队视图，并具备稳定的重试身份。由此固定四条行为：重试不重复创建
    Event / Version / 指派；基于陈旧视图的追加可以保留作者判断，但必须显式标记为陈旧；生命周期变更若前置状态
    已被他人改变，必须拒绝并返回最新状态，不得静默覆盖；任何批量操作只作用于提交时显式列出的对象，
    不波及并发新增项。

### 传播与权限

20. Root 以 Event 为单位选择性 route：先完成可见性与指派的 canonical 提交，再发送紧凑通知。
    通知是提交之外的副作用，正文不复制 Event chain，完整内容始终从团队状态获取。
21. 可见性与任务指派分离：可见性不可撤销，决定可读性与（第一版）贡献资格；是否活动由第 13 条的谓词决定。
    只读贡献档位后置。
22. 权限从当前 Session 的权威身份推导；**取不到权威身份时一律 fail-closed**，不默认按 Root 处理，
    也不信任模型自报的 author / producer / root 标志。只有登记在册的团队参与者获得团队能力。
23. 证据读取范围随可见性收敛：Root 可读本团队证据；子 Agent 只能读自己产生的、或从其可见 Event 可达的引用。
    引用只开放目标 observation，不连带开放 sibling 的其他上下文 —— 这是私有上下文与选择性传播的底线。
24. 复用 Codex 执行面：不新建 Agent-to-Agent 传输协议、不另建调度器、不建全局订阅机制。
    Agent 的运行、等待、结束等宏观生命周期直接沿用现有机制，不作为特殊 Event 类型。

### 证据

25. Fact 是"Harness 能稳定定位到的、Codex 实际保留的历史 observation"。它只承诺身份与定位，
    **不承诺完整原始字节永久可恢复**；不可得时必须显式标注，不允许悬空引用。
26. Fact 永远是历史 observation，不是当前真理。Harness 不自动判定它是否仍然适用。
27. 一次发布周期携带哪些新增证据，必须由确定性规则决定：同一条执行轨迹重放应得到相同关联。

### 边界

28. Harness 不做语义判断：不把证据自动升级成 Event、不自动聚类合并 Event、不按固定时间或工具次数强制发布。
    是否已形成值得外部化的语义检查点由实际工作的 Agent 判断；全局相关性、优先级与传播由 Root 判断。
29. 团队状态第一版可以是 session 内存态（跨进程持久化见候选池），但必须满足第 6 条的实例身份要求。
30. Shared workspace 沿用 Codex 原有多 writer 语义，第一版不引入 worktree、写入锁或新的 workspace 协调。

## 持续约束（M-0 产品基线，已完成）

`multidev/` 由 `mydev/` 的 Git 跟踪文件精确复制而成。落地证据见 `doc/WBS-COMPLETED.md`，
取舍论证见 `agent_log/2026-08-13-strategy-consensus-landing.md`。下列三条对每个后续阶段继续生效：

1. **默认关闭可断言**：`[auto_review]` 的 `model`、`model_provider`、`reasoning_effort`、`evidence_dir`
   在空配置下经真实配置加载后全为 `None`。
2. **基线在关闭态取得**：Multi 的基线测试与退化验收在该关闭态下运行；eval 不为 Multi 注入这四项，
   结果工件用版本化 `auto_review_config` 记录该状态。
3. **不携带本地模型依赖**：`multidev/` 的配置与测试不引用任何 GGUF 路径或本地推理 runtime。

**产品身份**贯通源码/构建路径、Cargo target、binary freeze、manifest、共享 catalog、adapter/RunSpec、
campaign 与结果归档，唯一映射是 `eval/rondo_eval/contracts.py` 的 `product_layout()`；
Multi 的工件命名空间是 `eval-data/bin/rondo-multi/`。规则见 `doc/eval-data-layout.md`。
Multi 目前**没有冻结的 runtime bundle**，首次 Docker 或付费验收前必须先冻结一套。

**继承代码的处置**：evidence capture 与 Guardian provider 覆盖默认关闭、不影响 Multi 开发，本质是预留接口。
不预设删除，处置原则只有一条：**不为保住它而对 Multi 内核做设计妥协**。

## 阶段

每个阶段只定义目标、交付能力、完成标准与边界；具体做法由该阶段的 plan 决定。
阶段顺序是硬依赖顺序，不并行。

### M-1 团队世界状态纵切（已验收并合入 main）

已验收实现由工作树提交 `5f7268d` 落地，并通过 merge commit `bcad5b22` 合入 `main`。团队领域是独立 crate
`codex-team-state`，canonical 状态挂在 `AgentControl` 上（每个存活 Root 树一份），模型可见工具为
`team_publish` / `team_update` / `team_history`。整套能力由
`features.multi_agent_v2.team_state_enabled` 控制，**默认关闭**；开启后才注册团队工具、注入稳定团队
协议前缀与每次采样的 Active World Index。

领域门禁 46/46、真实产品接缝定向门禁 11/11 通过；最终验收结论与未验证边界见
`agent_log/2026-08-16-062500-plan038-m1-final-acceptance.md`。

这是五个阶段里最重的一个，因为它要一次性把状态、投影与唤醒三者的正确性条件全部立住；后面四个阶段都是在
已经站稳的地基上做增量。

- **目标**：证明"团队状态不依赖任何模型记住"这一核心命题在真实多 Agent 运行中成立。
- **交付能力**：Event / Version 身份与不可变 authored 内容；producer 与 Root 双生命周期；
  按第 13 条谓词生成的参与者活动视图在采样前进入上下文；Root 在协调等待期间不遗漏团队状态变化；
  同一 Root 树内所有参与者共享同一份 canonical 团队状态；增量提交与历史查询。
- **完成标准**：
  - 一条端到端链路真实跑通并可复现 —— Root 派生子 Agent 并进入等待；子 Agent 发布首个 Event；
    Root 被唤醒并在下一次采样中看到它；Root 标记 resolved 后该事项仍留在子 Agent 自己的活动视图；
    子 Agent 追加新 Version 后该 Event 重新获得 Root 注意力，且完整 chain 可见。
  - 唤醒规则：发布先于等待、发布发生在等待期间两种时序都不丢；已消费过的变化不产生重复唤醒；
    Root 自建 Version 不自唤醒；producer 关闭 Root 仍活动的 Version 会唤醒 Root，而 Root 已 resolved 的
    旧 Version 只改 producer 状态时不会。
  - 提交规则：一次提交只改变显式指明的目标，未提及的活动项保持原状；重试不产生重复对象；
    陈旧视图上的追加被标记而非拒绝；陈旧的生命周期变更被拒绝并返回最新状态。
  - 投影规则：不出现在 conversation history 与 rollout 中，compaction 后仍能正确重建；
    同一次逻辑采样的所有 provider 重试使用同一份快照；注入内容有硬预算，超出时显式报告省略部分，
    且可通过有界的历史查询取回。**投影计入整次请求的上下文余量，并覆盖一个逼近窗口的用例：
    该用例下先做显式省略或已有的上下文压缩，请求不得被投影顶爆。**
    挂载位置按第 17 条验收：稳定规则在指令前缀、易变数据在请求尾部，且在历史规范化与工具调用/结果配对
    完成之后才追加，不插入配对中间、不重排历史、不越过尚未接纳的输入。
  - 身份规则：团队实例标识贯通对外引用；同一存活 Root 树内成员卸载后重新加载仍属原实例、状态与权限不变；
    只有找不到对应团队状态或实例不匹配才开新实例，此时旧投影/旧引用不解析到当前状态并显式提示重置；
    取不到权威身份时团队能力 fail-closed。
  - 上述规则以测试固化，而不是只写在提示词里。
- **边界**：不含 route、不含证据索引、不含 orphan 退休与 Event 关系；不改动 Codex 的 spawn/fork/lifecycle；
  证据引用在此阶段可以为空 —— 这是阶段边界，不是产品终态。

### M-2 选择性路由（已验收并合入 main）

实现由工作树分支 `worktree-040-multi-m2-selective-routing` 落地，并通过 merge commit `dbeba041` 合入
`main`。模型可见工具新增
`team_route`（`intent=assign|notify`）与 `team_route_update`（`action=end|retry_notice`），与 M-1 三个工具
同受 `features.multi_agent_v2.team_state_enabled` 控制，**默认仍关闭**。领域侧新增 `TeamRoute`
（`RouteDuty` = notice/assigned/ended，`DeliveryState` = pending/delivered/failed），可见性一经授予不可撤销，
指派有独立身份与终态；通知复用既有 inter-agent communication，未新增调度器或第二套协议。

首轮独立审查发现的三项通知恢复路径缺陷（去重未占用 retry identity、精确重放报过期 `pending`、目标可先重发
通知后记账失败）已整改并通过最终独立复验。

定向门禁（整改后）：`codex-team-state` 78/78，团队产品纵切 `suite::team_world_state` + `suite::team_routing`
12/12（M-1 九项无退化），`codex-core` 的 `tools::` 416/416、`context::` 99/99。
执行细节见 `agent_log/2026-08-16-173000-plan039-multi-m2-selective-routing.md`，
审查、整改与最终验收见同目录 `...-173945-...-independent-acceptance-review.md`、
`...-175500-...-review-remediation.md` 与 `...-180544-...-final-acceptance.md`，
任务合同见 `plan/039-multi-m2-selective-routing-execplan.md`。

- **目标**：让团队信息按 Root 的判断在 Agent 之间流动，且不产生第二份 canonical 副本。
- **交付能力**：Root 以 Event 为单位授予可见性并建立指派，再投递紧凑通知；被 route 的 Agent 能读到完整 chain
  并在同一 Event 下贡献自己的 Version；指派有可结束的生命周期；通知失败可见、可幂等重试。
- **完成标准**：同一 Event 下的多作者 Version 链跨 Agent 跑通；通信正文不含 Event chain 正文。
  失败语义明确为：可见性与指派的 canonical 提交先完成且**不因通知失败而回滚**，通知失败被记录为可重试状态；
  必须排除的只有"通知已到但目标读不到 Event"这一种时序，而不是"授权已生效、通知暂时失败"这一显式状态。
  指派结束的验收必须**成对**：目标若仍有自己未终态的 Version 或其他进行中指派，该 Event 仍在其活动视图中；
  若已无任何纳入理由，则退出活动视图、但历史仍可按权限读取（第 13 条）。只验前一半的话，
  结束指派实现成空操作也能通过。
  投递意图需在本阶段冻结为三分支，不可互换：目标正在运行时排队投递，在既有安全边界进入其上下文，不另起一轮；
  目标空闲且指派要求它开始或继续工作时，触发其下一轮；目标空闲但只是信息通知时排队投递。
- **边界**：不引入新的 Agent-to-Agent 传输协议；不实现只读贡献档位；不实现 Event 关系图。

### M-3 证据锚定（已验收并合入 main）

实现由工作树分支 `worktree-042-multi-m3-evidence-anchoring` 落地（提交 `db39e28`、`8360bbf`、`ce32394`、
`cfe3dc1`、`35356ab`、`eb53218`），并通过 merge commit `5783ac0` 合入 `main`。第三轮独立复验指出的
并行重复 call ID 配对、
refs 第 33 条后不可达与同 producer 暂存截断均已补修并通过最终独立复验。模型可见工具新增
`team_evidence`，与 M-1/M-2 五个工具同受
`features.multi_agent_v2.team_state_enabled` 控制，**默认仍关闭**。

首版 observation 支持集为**已完成、由 Codex 正式保留、body 为纯文本的工具结果**，成功与失败都形成 Fact。
捕获拆成两步：Harness 在 dispatch 前为结果预留唯一 item identity，工具处理器产出终态时按该身份记下观察
（宿主要自己顶替回答时再精确撤销），同一 retained item 进入 conversation history 时才铸造 Fact 并按 retention
顺序分配序号，所以并行重复 call ID 不会串配，也不存在"尚未保留就当成存在"的引用。可用状态不缓存在 Fact 上，
每次读取现场判定并区分"producer 未加载"与"当前 history 不携带该项"，两者都不写死引用。领域侧
`codex-team-state` 只持 typed Fact refs、每 producer 的发布窗口和授权元数据；`publish` 在同一次 mutation
内取走该作者上次成功发布之后的新 Fact 并推进游标。读取沿 Event 图收敛，`team_evidence` 只返回目标
observation 的有界文本与必要元数据。

locator 是 Codex 为每个已保留 item 分配的身份（一对一，call_id 只作元数据）；Version 保留发布窗口的全部引用，
上下文预算只作用于打印列表的 surface 并报告省略数。

实现期定向门禁：`codex-team-state` 101/101；产品纵切 `suite::team_evidence` 3/3；M-1/M-2 回归
12/12；`core` 的 `team::evidence` 6/6；合并 `tools::`/`context::` 共 541/541。补充整改后另通过
`codex-team-state evidence` 23/23、新边界产品纵切 1/1 与其余定向回归 19/19；最终独立复验再次确认
23/23 与 1/1。执行与验收细节见
`agent_log/2026-08-17-040656-plan042-multi-m3-evidence-anchoring.md`，验收审查与整改见同目录
`...-045506-...-independent-acceptance-review.md`、`...-052355-...-remediation-reverification.md` 与
`...-055152-...-supplemental-remediation-reverification.md`，
任务合同见 `plan/042-multi-m3-evidence-anchoring-execplan.md`。

M-3 已完成并合入 `main`。M-4 已验收并经 merge commit `601de62` 合入 `main`。M-5 阶段 A 已通过；阶段 B 仍在进行，真实付费运行未开始，不能表述为 M-5 通过。

- **目标**：让 Event 里的语义判断可以回溯到 Harness 实际观察到的执行结果，使团队状态成为 evidence-backed，
  而不只是结构化便签。
- **交付能力**：为高价值 observation 分配稳定引用与定位信息；发布周期内新增的证据机械关联到 Version；
  参与者可按第 23 条的读取范围下钻到 Codex 实际保留的 observation 或其可用表示。
- **完成标准**：同一条执行轨迹重放得到相同的证据关联。
  本阶段 plan 必须冻结一个**非空**的首版 observation 类别集合，其中每一类都要有代表性引用在正常生命周期内
  真实下钻成功，且至少有一条真实 Version 关联到证据并成功下钻 —— 把支持集声明为空不算通过。
  "不可得"是诚实的退化标注，不能作为正常路径的替代成功 —— 全部引用都不可解析同样不算通过。
  引用只在定位信息与可用性都确定后才提交，持久化失败不得标成可用。
  **拒绝路径同为完成标准**：不可见的 sibling 证据读取 fail-closed；route 之后只开放目标引用，
  不连带开放其 thread/rollout 周边内容（第 23 条）。这里只需定向测试，不建设复杂 ACL。
  团队工具自身与证据读取动作默认不递归产生新证据。
- **边界**：不复制全量工具输出，不建 artifact store，不自动判定证据是否仍然有效。

### M-4 协调闭合与可观测性（已验收并合入 main）

实现由工作树分支 `worktree-043-multi-m4-coordination-closure` 落地，并通过 merge commit `601de62`
合入 `main`。模型可见工具新增 `team_retire` 与 `team_inspect`（dump/log/stats），协议片段升到 v4，
与既有团队工具同受 `features.multi_agent_v2.team_state_enabled` 控制，**默认仍关闭**。

producer 可用性由 Harness 权威控制面派生四类：loaded 且 `is_running()` 为 available；同一 Root 树
可通过显式 `resume_agent` 恢复为 recoverable_unloaded；store/history 明确缺失为 unavailable；读失败或
store transition 期间为 unknown。Root 退休是独立终态覆盖层，只撤销目标 Version 的 producer-open
活动理由。dump cursor 绑定 team instance、revision、availability epoch 与 observe generation。

最终独立验收见 `agent_log/2026-08-17-105030-plan043-m4-final-independent-acceptance.md`，
任务合同见 `plan/043-multi-m4-coordination-closure-observability-execplan.md`，完整执行与审查链见
`doc/WBS-COMPLETED.md`。

- **目标**：让长时间运行中的团队状态能干净收尾，并让一次错误协调可被事后解释。
- **交付能力**：producer 不可用时 Root 显式退休其未终结 Version；确定性的团队状态转储与精简变更日志；
  每个 Agent 的发布频率与体量可观测。
- **完成标准**：producer 的不可用状态在 Root 视图中明确可见，且区分"可恢复但未加载"与"真正不可用"；
  Root 可显式退休，退休后该 Version 退出对应的活动理由，并保留操作者与理由。
  （Root 不操作时事项继续悬挂是设计意图 —— 无自动 escalation，所以完成标准不是"orphan 自动消失"。）
  从转储与变更日志可以回答"谁在哪个版本号下做了什么改动""Root 为什么没被唤醒""某 Agent 为什么看不到某个 Event"。
- **边界**：不做产品级 UI，不做自动重要性分类，不做自动 Event 合并，不做批量结束注意力（见候选池）。

### M-5 真实运行与不退化验收

阶段 A（Plan 044，无费用）已通过：冻结 bundle、两份运行合同与接线核验通过，门 1 判据的三处缺陷
（同 Event 合取、Root 唤醒、证据按产出工具绑定）已关闭并各有反例回归。

**阶段 B 经五轮独立审查整改，当前事实如下。**

**门 1 判据已重建（第五轮）。** 冻结模型 `gpt-5.6-terra` 是 `tool_mode=code_mode_only`，配合
`features.code_mode_host=true` 时，模型只发一个 `custom_tool_call(name=exec)`，团队工具全部由其中的
JavaScript 调用；Responses 线上顶层 `function_call` 数为 0。原 v1 判据只认
`responses_function_call_outputs`，**在真实配置下结构上不可能通过** —— 阶段 A 那次"实测确认 wire 形状"
用的是直接注入 function_call，结论对但不是模型的真实行为。现改为读冻结二进制自身的 rollout trace
（`CODEX_ROLLOUT_TRACE_ROOT`，产品既有能力，非新增代码）：判据只认 Rust dispatch 侧写下的
`ToolCallStarted/Ended`（工具名、namespace、注册表收到的参数、handler 返回值），并要求每条 dispatch 能绑定回
抓包里模型真实发出的 code cell（`model_visible_call_id` + `source_js`），否则 fail-closed。这样
"模型自己打印一段像 dump 的文本"不构成证据。已冻结 `multi-m5-workflow-v2`，v1 归档不得充当 v2 证据；
彩排 stub 同步改为真实 code-mode 形状（这是关键：只改采集不改 stub 等于把同一个错误再犯一遍）。

**门 2 模型已全链贯通（第五轮）。** 预算代理取锁里的 terra，但 `make_run_spec` 仍走宿主
`paid_eval.main_model` 别名，实际 adapter 拿到 sol，真跑会被代理本地拒掉并记成"产品失败"。现在锁里的
root/member 模型与 effort 贯通 `TerminalBenchRequest → make_run_spec → adapter argv → proxy`，
就绪自检离线构造 Codex/Multi 两侧 prepared run 并逐字段比对；全局 `AGENT_DEFAULT_SUBAGENT_MODEL` 恢复为
sol（此前被整体翻成 terra，会静默改写本机每个 Multi campaign 的成员身份），M-5 从自己的锁显式传入。

**$120 已是数学上限（第五轮）。** 此前每请求预留 $4/$2，而通用 Usage 合同允许的 terra 单请求最大合法费用
约 $7.554，settle 时按实际计价可越过 cap。现在冻结 token 信封（输入 272k = terra 上下文窗口，输出 128k =
通用合同上界），预留由信封 × 价目表机械推导（$2.22），信封在账本 settle 处强制，因此
`charged ≤ reserved` 恒成立，reserve 时的批次校验即为真上限。每 run 上限由最大并发推导
（Root + 3 成员 + Guardian = 5 × 预留），并发上限改为经校验的整数而非布尔。停止原因区分 budget 与 infra
（上游失败、缺 usage、超时不再被贴成"预算停止"），未知原因 fail-closed；预留扣款与已计价消费分开记账。
正式付费槽位改用 `claim_run`，重跑 CLI 无法二次消费同一 run id。

**已知风险，尚未验证。** 团队证据 fact 只在 `ToolCallSource::Direct` 时留存，code cell 内的嵌套调用不留
（`multidev/codex-rs/core/src/team/evidence.rs`，产品的明确设计）。若真实模型把所有工具调用都放进 cell，
则冻结的 `team_evidence` 谓词无法成立。彩排中 shell 走直接调用即可满足（两种暴露面都开着，是合法模型行为），
但真实模型是否如此**只能由付费冒烟回答**，不得预先假定。

彩排由 stub 驱动协议，**证明的是产品与判据这条链路能走通，不是真实模型会遵守协议**，因此
**不是**门 1 通过、更不是 M-5 通过。下一步：用已授权的 $40 独立冒烟账本（独立 batch/lock_id/归档，
每次运行必须带全新 `--label`）验证真实模型下 trace 判据能否看见协作，确认后才进正式门 1；
门 1 通过后才进门 2。授权清单见 `plan/044-multi-m5-real-workflow-and-nondegradation-execplan.md`。

- **目标**：在真实任务上跑通完整协作语义，并确认相对冻结 Codex 未出现稳定单向退化。
  **口径边界**：这句话由门 1 与门 2 **合起来**满足 —— 门 1 的载体是协议演示级 fixture（答案写在
  fixture 里、指令规定工具顺序），只回答「真实模型下团队机制是否端到端真的发生」，不证明 Multi 在
  有分析负载的任务上更强；真实任务由门 2 的十个 TB 任务提供。任一门单独都不得引用为满足本目标。
  详见 `eval/locks/multi-m5-workflow-v2.json` 的 `scope_limits` 与 Plan 044 决策 032。
- **前置**：冻结一个真实的 Multi 产品工作流作为验收样例（具体选哪个由本阶段 plan 决定，不预先写死角色分工）；
  按产品身份冻结一套 Multi runtime bundle；按 `doc/WBS.md` §6 单独取得真实 API 授权。
  阶段 A 前两项（工作流合同、runtime bundle）已冻结；独立验收要求先修好门 1 判据再谈第三项授权。
  第三项所需的两个付费部件已落地并通过独立验收，仍待用户单独授权，本轮不进入真实运行。
- **完成标准**：两个相互独立的门，缺一不可。
  1. **工作流成立且功能实际发生**：在功能开启的真实运行中，冻结的工作流达到它自己预冻结的任务完成标准，
     且 Event/Version 发布、Root 唤醒、route、多作者追加与证据下钻确实被触发、注意力按正常路径收尾，
     没有状态不变量失败。**功能关闭、模型从未调用团队工具、或工作流本身没完成，都不算通过。**
     （orphan 退休不在本门的必触发清单里：正常工作流不应为了过门人为制造 orphan，
     它的定向正确性由 M-4 负责，真实运行中自然发生时附带验证即可。）
  2. **不退化**：再做下节的小样本稳定单向失败检查。
  内部的 Event/route/证据计数只作为"功能确实激活"的证据与诊断，不混进跨二进制的任务完成率。
- **边界**：不主张质量优势，不做大规模统计证明。

## 候选池（不排期，由真实运行证据触发）

每项都写触发条件，不预先锁定实现路线；候选方案的具体形态见两份研究稿。

- **投影成本压缩**：当完整 chain 的上下文成本被真实运行证明是主要瓶颈时立项。M-1 的硬预算与显式省略
  已经保证正确性，这里解决的是效率，不提前优化。
- **批量结束注意力**：当逐项消费被真实运行证明确实成为 Root 的负担时立项。若实现，必须只作用于提交时
  显式列出的 Version 并遵守第 19 条。
- **Event 关系**：当重复 Event 频繁出现、Root 靠自然语言备忘跨 compaction 记不住关联时立项。
- **证据新鲜度线索**：当模型频繁重复验证同一件事时立项。立项前须先确认它对 Harness 观察不到的写入天然不完整，
  不会给模型虚假的精确感。
- **Root 注意力状态对 producer 可见**：当真实轨迹证明"Root 在等、producer 已收工"的信息不对称确实造成损失时
  再立项，且只暴露状态本身、不暴露 Root 自己的协调理由（那会污染独立调查）。
  第 10 条的唤醒规则已经从 Root 侧覆盖了这个协调风险，所以第一版不做。
- **只读贡献档位**：当确实出现"只告知、不允许追加"的需求时再加，是向后兼容的扩展。
- **团队状态跨进程持久化与恢复**：当会话中断导致的团队状态丢失被证明是真实痛点时立项。
- **多 writer 隔离与集成**：当共享 workspace 的真实写冲突频率被证明不可接受时立项。
- **朴素自然语言转述对照模式**：只作为测评期的临时开关按需实现，**不作为设计约束长期维护**。
- **远期**：通用 DAG、嵌套团队、跨 session 复用、多进程或远程 worker。每项都必须由真实使用证据触发。

## 退化验收口径

这是 M-5 的第二道门，只回答"有没有退化"，**不回答"协作功能是否真的在工作"** —— 后者由 M-5 第一道门负责，
两者不可互相替代。

"相对冻结 Codex 不明显退化"的判定方式：**固定一小组 TB 2.1 任务，Multi 与冻结 Codex 跑同题，
只记录任务是否完成。**

- **不计算 `σ` / `delta`，不做统计显著性，不继承旧 M2 的机械判据** —— 那套与"不要求昂贵统计证明"的定位冲突，
  且小样本下 `σ` 极不稳定。
- 只在 Multi 出现**稳定的单向失败**（Codex 完成、Multi 不完成，且重复出现）时判定为退化并回头修；
  没有观察到这种失败时，只表述为"该小样本下未观察到稳定单向退化"，不扩大成统计意义或全面能力上的通过。
- **任务集：直接复用 P2/B7 的同一个金丝雀集**（`eval/tasksets/p2-b7-canary-catalog-v*.json`），不另选任务。
- **频次：只在 M-5 以及后续重大改动时跑。** 平时回归完全依赖测试体系（单测、fake/loopback/replay），
  不做周期性付费跑。
- 这是跨二进制对比，v22 暴露的那批设施缺陷会原样适用（catalog 非对称、harness/deadline 混杂、非交错执行
  都可能把设施伪影伪装成"Multi 单向失败"）。公平比较设施已闭合；运行时仍须冻结范围、轮数与预算并单独授权。

轻量指标（token 数、工具调用次数、发布频率与体量）随各阶段低成本记录归档，不依赖大规模付费测评。

## 稳定非目标

- 合规/取证平台、完整 provenance graph、PKI/签名链、区块链或平行 ACL。
- trust score、长期 agent 排名、在线学习路由器、judge 集群或一智能体一票。
- 全量 transcript/CoT 广播、自由群聊、无限反思、固定大 swarm。
- 通用副作用缓存、任意工具透明重放。
- 复杂鉴权、数据资产审计或可信度评分体系。
- 为证明全面优于单体而建设庞大 benchmark；只测目标工作流的正确性与轻量开销。
