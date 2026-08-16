# Multi M-1 团队世界状态纵切 ExecPlan

> 本计划是本任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述 Multi M-1；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 `multidev/` 内完成 Multi M-1 的真实产品纵切，证明同一 Root 团队的重要协作状态由 Harness
持有和维护：它不依赖任何模型复述或记忆，不进入可压缩 history/rollout，并能跨采样重试、compaction、
等待时序与同一 Root 树内的成员卸载/重新加载保持正确。

任务必须使用现有 RONDO Multi 的 Agent、session、V2 wait/mailbox 与 sampling 接缝跑通以下链路：

> Root 派生子 Agent 并等待 → 子 Agent 发布 Event → Root 被唤醒并在下一次采样看到团队状态 →
> Root 更新注意力状态 → 子 Agent 保留自己的未完成事项 → 子 Agent 追加新 Version →
> Root 再次获得协调机会并看到完整 Version chain。

具体模块、类型、store 所属位置、mutation API、revision/幂等/锁/wake generation 表示、投影渲染类型和
必要内核重构由执行者结合实时源码自主决定。计划固定的是产品行为和边界，不固定实现路线。

### 完成/验收标准

- [ ] 上述 Root/child 链路通过真实 RONDO Multi 产品接缝的无 API 集成测试可复现；不能只用脱离
      Agent/session/wait/sampling 的纯状态机测试代替。
- [ ] 同一 Root 树共享一份 canonical 团队状态；Event 是团队级对象，Version 是不可变 authored 条目，
      authored 内容与可变生命周期状态边界由代码保证。
- [ ] producer 的 `open`/`closed` 与 Root 的 `pending`/`tracking`/`resolved` 相互独立；普通参与者新建
      Version 对 Root 默认 pending，Root 自建默认 tracking 且不自唤醒。Root resolved 不关闭 producer
      事项，producer 关闭也不替 Root 消费注意力；已关闭 Version 不原地重开，事项再次相关时追加新 Version。
- [ ] 第 13 条活动视图谓词在 M-1 已具备的纳入理由上成立：Root resolved 后，子 Agent 自己仍未终态的
      Version 继续留在其活动视图；新 Version 使 Event 重新进入 Root 活动视图。M-2 route 理由本轮不实现。
- [ ] 历史在当前团队实例存续期内追加式保留；退出活动视图不删除对象，有权限的参与者可通过有界查询
      取回历史，越权或身份不明时 fail-closed。
- [ ] mutation 是增量的：未显式列出的对象不变；稳定重试身份不会产生重复 Event/Version；陈旧视图上的
      追加可提交但显式标记陈旧；前置状态已变化的生命周期 mutation 被拒绝并返回最新状态，不静默覆盖。
- [ ] 并发测试覆盖至少同一 Event 的并发追加、重复请求和与生命周期变更竞争的陈旧请求；没有丢更新、
      重复对象或批量误伤。
- [ ] Root wait 与团队变更可靠衔接：发布先于等待和等待期间发布都不丢；消费后的变化不虚假重复唤醒；
      Root 自建 Version 不自唤醒；producer 关闭 Root 仍 pending/tracking 的 Version 会再给 Root 协调机会，
      仅关闭 Root 已 resolved 的旧 Version 不会。
- [ ] 面向参与者的 Active World Index 在每次模型 sampling 前由 canonical 状态生成；同一逻辑 sampling 的
      provider retry 复用同一不可变 snapshot，下一次 sampling 才获取新 snapshot。
- [ ] 稳定、版本化团队规则位于稳定指令前缀；动态投影在已接纳输入、history 规范化及 tool call/result 配对
      完成后的最后一个协议安全位置追加，不进入 conversation history/rollout，不重排或拆开协议项。
- [ ] compaction 后投影从 canonical 状态正确重建；测试能够证明历史/rollout 中没有投影残留，也不依赖模型
      在摘要或回复中复述状态。
- [ ] 投影有整次请求级硬预算。接近上下文窗口时先显式省略部分内容或走已有 compaction，省略清单可见且
      可通过有界历史查询下钻；请求不能被投影顶爆，也不得静默截断。
- [ ] 团队实例身份贯穿 Event/Version/查询与 mutation 引用；同一存活 Root 树内成员卸载后重载继续使用
      原实例、身份、权限和状态。找不到对应 TeamState 或实例不匹配时开启/识别新实例，旧引用不解析到
      当前对象，并向调用者显式报告 reset/mismatch。
- [ ] 参与者身份和能力只从当前 Session/AgentControl 的权威注册信息推导；缺失、矛盾、跨团队实例或未登记
      身份均拒绝，不能信任模型传入的 author/root/producer 自报字段。
- [ ] 行为由必要的领域单测、并发/重试测试、sampling/compaction 集成测试和真实多 Agent 纵切测试共同固化；
      复用既有 fake/loopback/test support，未运行项和证据等级如实记录。
- [ ] `just fmt`、受影响 package 的定向 lint/fix 与定向 Rust 测试通过；不为本任务扩大为全 workspace 重型测试。
- [ ] diff、资源门禁现场和意外生成物检查完成；精炼 `agent_log/`、本计划状态及可安全更新的 M-1 权威 WBS
      已同步；完整实现提交在本工作树分支，未合并、未推送。

## 2. 范围

### 允许修改

- `multidev/` 中实现 M-1 所必需的 Rust 源码、协议/工具接缝、构建清单和定向测试。
- M-1 需要的少量共享构建/测试接缝，但仅限无法在 `multidev/` 内干净完成的部分，且不得改变 Local/L6 语义。
- 本文件、M-1 精炼 `agent_log/`，以及完成时受影响的 `doc/WBS/multi-agent-trusted-evidence.md` 条目。
- 仅当 L6 已合并且共享文件现场无并行修改时，按文档职责同步 `doc/WBS.md`、
  `doc/WBS-COMPLETED.md`；否则保留 M-1 专用记录，把顶层同步明确留给最终集成。
- 任务所需的普通依赖下载和只读源码/文档查询；不包含真实外部服务写入或付费调用。

### 不允许修改

- `mydev/`、`training/`、L6 的 plan/测试/模型工件/云端训练配置，以及
  `.claude/worktrees/037-l6-first-lora-paired-artifacts` 内任何内容。
- RONDO Local、Guardian、本地审批模型或 L6 行为。
- `codex-source-code/` 上游只读快照、冻结 `codex-doc/`、历史审计快照与既有历史 plan/log 的结论。
- M-2 的 route/assignment/紧凑通知，M-3 的 Fact/证据 locator/observation 下钻，M-4 的 orphan 退休、
  审计转储/发布频率观测，M-5 的真实 API、付费比较或 runtime bundle。
- Event 关系图、自动合并/升级/escalation、重要性分类、跨进程 TeamState 持久化、新调度器、
  新 Agent-to-Agent 协议、全局订阅、shared workspace 锁/worktree 协调或多 writer 重构。
- 正式 eval campaign、结果账本、付费预算记录或无关测评设施。

### 不允许读取/查看

- `.env.local` 的内容；只可在任务确实需要时静默检查其存在、非符号链接、权限 `0600` 和指定变量非空。
  预计本任务不需要该文件。
- `rondo.local.toml` 的内容；本任务不依赖本机模型或 provider 配置。
- L6 未提交文件、生成物、训练数据正文、模型权重、adapter、私有评测原件、密钥或其他项目外个人文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **隔离执行**：所有受跟踪编辑、格式化、构建、测试和提交只在
   `.claude/worktrees/039-multi-m1-team-world-state`（分支 `worktree-039-multi-m1-team-world-state`）进行。
   不进入或修改 L6 工作树；不回退、覆盖、stash、移动或清理来源不明的现有修改。
2. **语义来源**：M-1 行为以 `doc/WBS/multi-agent-trusted-evidence.md` 的设计语义合同和 §M-1 完成标准为准。
   本计划不另造一套状态语义；若实现发现两者无法同时满足，先记录事实并请求用户裁决。
3. **真实纵切**：团队能力必须接入现有 RONDO Multi Agent/session/wait/sampling 运行面，并能由实际模型工具面
   发起所需发布、追加、生命周期更新和历史查询。纯领域 API 可用于单测，但不能冒充端到端完成。
4. **canonical 与身份**：一个存活 Root 树只能有一份团队状态和一个团队实例身份；状态归 Harness 所有，
   不以 prompt、history、rollout、模型回复或成员当前是否驻留作为事实来源。模型自报身份不授予能力。
5. **不可变内容与双生命周期**：Event/Version authored 内容写入后不可改写；生命周期 mutation 必须显式、
   可并发检查且不跨边界联动。历史退出活动视图后仍保留，第一版仅需当前团队实例内存续。
6. **并发与幂等**：mutation 必须原子地检查并提交，稳定重试身份只能对应同一结果；陈旧追加与陈旧生命周期
   变更按 WBS 的不同语义处理，任何批量 mutation 只触及显式列出的目标。
7. **不丢唤醒**：Root 等待的订阅/检查顺序必须关闭“先检查、后订阅”竞态，并以可消费的团队变化为依据；
   不能只发送一条可能丢失的瞬时通知，也不能让已消费 generation 永久造成重复唤醒。
8. **request-only 投影**：每次逻辑 sampling 捕获一次不可变团队 snapshot，并在全部 provider retry 中复用；
   动态投影不落入 history/rollout。正确性优先于 WebSocket `previous_response_id` 增量复用，不得为缓存旧投影、
   累积 patch 或把 team revision 编入 prompt cache key。
9. **预算与协议完整性**：投影必须计入整次请求的剩余上下文，显式处理 overflow；挂载不得越过未接纳输入、
   拆散 tool call/result 或改变现有历史顺序。任何省略必须可见，并保留有界、按权限的下钻路径。
10. **并行隔离**：M-1 与 L6 产品上并行、资源上服从全局互斥。共享 WBS/eval 文件若仍有 L6 并行修改，
    不覆盖、不强行解决；M-1 专用源码、plan 和 log 可独立提交，顶层状态同步可延后到集成阶段。
11. **资源与测试门禁**：不得直接运行 Cargo。Rust 构建、test、fix/clippy 等重型入口必须走根
    `scripts/with-build-lock.sh` 或已经接入它的 `just` 配方，使用项目根内受监控 target，保持既有并发上限。
    执行前确认没有受门禁保护的 Cargo/Docker/本地模型任务；拿不到锁、cgroup、Windows `C:` 实际余量或
    资源计数器时 fail-closed。只跑受影响 package/集成用例，不跑全 workspace。
12. **外部与秘密边界**：禁止 Docker、真实 API/付费测评、真实本地模型加载/推理、云 GPU、训练、数据外发、
    模型上传/权重下载、上游升级、远端状态修改和系统/全局工具链变更。测试必须清楚区分 unit、fake/loopback、
    实际多 Agent 产品链路与未运行能力；skip 不算通过。
13. **允许自修复重跑**：普通编译、格式、测试 fixture、窄实现错误或临时锁占用不要求首次失败就停下；可以分析、
    做范围内修复并定向重跑。只有触及原则性边界、需要未授权高危能力、资源门禁持续不可满足、计划合同需要变更，
    或多次尝试后仍是实质性阻塞时才暂停汇报；不得用重试绕过安全门禁或弱化测试。
14. **提交交接**：完成后审查 diff、受保护路径、资源使用和意外生成物，在工作树分支提交完整成果并停止。
    不合并 `main`、不推送、不删除 worktree；等待独立审查者验收。

## 4. 软性建议

以下是基于当前源码的高性价比落点，不是固定约束。执行者可依据实现复杂度、测试反馈和代码演进选择更小、
更清晰或更可靠的等价方案，并在关键决策记录中简要说明。

- `AgentControl` 已按 Root 树创建一次并由所有子 Agent clone，共享 registry、residency 和 rollout budget；它或其拥有的
  独立组件是 TeamState 生命周期的自然候选。若新 crate 或 ThreadManager 侧所有权更清晰，可以采用更优结构。
- 将领域状态/不变量、身份授权与 mutation、投影渲染、sampling/wake 接缝分开，避免继续膨胀中央 session/turn 文件；
  API 保持最小，测试 helper 不进入生产公开面。
- revision、幂等 key、wake generation 和锁可选择能直接表达不变量的简单表示；第一版是 2–8 个 Agent 的
  session 内存态，不需要事件溯源数据库、复杂 ACL、全局订阅或持久化框架。
- 可复用现有 V2 `wait_agent` 对 input queue activity 的订阅方式，但团队变化应有自己的可靠消费语义；无需改变
  Codex 的宏观 Agent 生命周期或发明第二套 mailbox。
- sampling 当前在 retry 循环内先取得/规范化 prompt history，再附加 pending tool metadata，最后 `build_prompt`；
  动态投影可在这条链上的最后协议安全位置接入。快照应在 retry 循环外按逻辑 sampling 捕获一次。
- model-visible 稳定规则优先复用 `core/context` 的 typed fragment 约定；动态数据可使用独立 request-only 渲染类型，
  不要借用会写回 history 的既有 world-state diff 通道。
- 测试优先扩展现有 `core_test_support::responses`、V2 multi-agent handler/residency 测试、prompt/compaction 测试和
  `test_codex` 集成设施。真实纵切可由受控 fake/loopback provider 驱动实际工具调用和多个 session，无需真实 API。
- 先用窄领域/并发测试站稳不变量，再接 wait 与 sampling，最后固化整条产品链；若实际依赖关系更适合另一顺序，
  执行者可调整。
- 除非 M-1 产品入口确实需要，避免扩展 app-server/TUI/公开 wire API；若确实修改公开 API 或用户可见 UI，遵循
  就近 AGENTS 的 schema、文档、跨平台与 snapshot 要求。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根 `AGENTS.md`、`README.md`、顶层 WBS、方向 3 子 WBS、计划模板、M-0 计划与相关验收日志。
- 已只读核对 `AgentControl`/registry/residency、V2 `wait_agent`、session sampling/retry、history/compaction 与现有
  集成测试接缝；未替执行者锁定具体实现。
- 已从干净 `main@53fbb58b` 创建本专用 worktree 和短期本地分支；未进入或读取 L6 工作树内容。
- 已建立本 ExecPlan；尚未修改产品源码或运行 Rust 构建/测试。

### 当前工作

计划已就绪，等待执行者在本工作树内实施 M-1。

### 本任务剩余步骤

1. 基于实时调用链确定最小架构与身份/能力边界，先用定向测试表达核心领域不变量、并发、幂等和陈旧 mutation。
2. 实现 canonical TeamState、Event/Version、双生命周期、活动视图及有界历史查询，并接入实际 model-visible mutation
   工具/内部 API。
3. 把团队变化接入 Root wait 的无丢失唤醒，把团队实例和成员身份接入 spawn/residency reload 生命周期。
4. 把稳定协议和 request-only Active World Index 接入 sampling；完成 retry snapshot、budget/overflow、compaction
   与 history/rollout 不持久化验证。
5. 固化完整 Root/child 产品纵切及发布先/后等待、重试、并发、陈旧视图、近窗口和 reload 等定向用例。
6. 运行格式化、受影响 package 的 lint/fix 和定向测试；审查 diff、资源和生成物，更新精炼 log/plan/WBS，
   提交工作树并停止。

### 阻塞项

无产品或外部前置阻塞。L6 是受保护的并行任务：遇到共享构建锁时等待；遇到共享 WBS 并行修改时延后顶层同步，
均不构成修改 L6 或扩大权限的理由。

### 当前验收状态

- ExecPlan：已建立并完成自审。
- M-1 实现与测试：未开始。
- Docker、真实 API、本地模型、全 workspace 测试：未授权且不属于本任务。

### 交接边界

- 执行者只在本工作树完成、提交并停止；独立审查者将对照本计划、实时 WBS、代码 diff、定向测试和现场状态验收。
- 本任务完成后冻结本计划；M-2 及以后路线只链接 `doc/WBS/multi-agent-trusted-evidence.md`，不在此继续规划。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | M-1 固定产品行为与验收，不预先写死 store、锁、revision、工具 schema 或模块布局 | 用户要求保留执行自主权，且实时源码已有多种可行接缝 | `multidev/` M-1 | 已采纳 |
| 002 | 第一版 TeamState 仅在当前 Root 团队实例内存续，不做跨进程持久化 | 与 WBS 阶段边界一致，避免提前建设恢复/存储体系 | TeamState 生命周期 | 已采纳 |
| 003 | request-only 投影正确性优先，接受当前 WebSocket 增量复用通常失效 | 持久化旧投影会破坏新鲜度、retry 一致性和 compaction 独立性 | sampling/cache | 已采纳 |
| 004 | 使用真实 Multi 运行面加无 API fake/loopback provider 作为 M-1 产品链证据 | 能验证 Agent/session/wait/sampling 接缝，又不需要未授权真实 API | 集成验收 | 已采纳 |
| 005 | L6 未合并或共享文件有并行修改时，不强行同步顶层 WBS/WBS-COMPLETED | 保护并行任务；M-1 专用源码、plan、log 和子 WBS 可独立审查 | 文档交付 | 已采纳 |
| 006 | 普通窄失败允许执行者自行修复和定向重跑，原则性边界与持续资源阻塞才停下汇报 | 避免把可恢复的小问题误当阻塞，同时保留安全和授权边界 | 执行流程 | 已采纳 |
