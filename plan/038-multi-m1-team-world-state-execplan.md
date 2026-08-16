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
  集成测试接缝。
- 已从干净 `main@53fbb58b` 创建本专用 worktree 和短期本地分支；未进入或读取 L6 工作树内容。
- 已建立本 ExecPlan。
- **M-1 实现已完成**：新增领域 crate `codex-team-state`（canonical store、双生命周期、活动视图、
  增量/幂等/陈旧 mutation、唤醒账本、有界历史、request-only 投影渲染与预算），并接入真实产品运行面
  —— `AgentControl` 持有团队实例、`Session::new` 从权威身份注册参与者、`team_publish`/`team_update`/
  `team_history` 三个模型可见工具、`session/turn.rs` 的 per-sampling 快照与尾部挂载、
  `wait_agent` 的团队唤醒、`TeamProtocolState` 稳定指令前缀。
- 已加 `features.multi_agent_v2.team_state_enabled`（默认关闭）并重新生成 `config.schema.json`。
- 已完成领域单测 36 项、`codex-core` 集成用例 5 项，以及格式化、定向 lint 与受影响 package 测试。
- 已写入精炼 `agent_log/2026-08-16-034500-plan038-multi-m1-team-world-state.md`。

### 当前工作

首轮独立审查判定不通过，其 5 个阻断项与 3 个窄修项经逐条核对**全部属实**，已在本工作树完成整改并提交，
等待复验。整改记录见 `agent_log/2026-08-16-043500-plan038-m1-review-remediation.md`。

### 本任务剩余步骤

无。后续动作（合并、推送、顶层 WBS 同步）不在本任务授权内，交给复验与最终集成。

### 阻塞项

无产品阻塞。两项环境限制已如实记录、未绕过：

1. `codex-code-mode-host` 依赖的 V8 预编译包在本机下载 404，因此 code-mode 相关测试无法在此环境运行。
2. 本机全局 `HTTP(S)_PROXY`/`ALL_PROXY` 会拦截 wiremock 的 loopback 请求；所有测试在剥离代理变量的
   环境下运行，与仓库既有 `eval-*` 配方做法一致。

L6 仍有 12 个未合并提交且改动了 `doc/WBS.md` 与 `doc/WBS-COMPLETED.md`，因此顶层同步按计划延后。

### 当前验收状态

- ExecPlan：已建立并完成自审。
- M-1 实现与测试：已完成并已按首轮审查整改。`codex-team-state` + `codex-features` 76/76、
  M-1 集成用例 6/6 加身份单测 1/1 全部通过；`just test -p codex-core -p codex-rmcp-client`
  3456/3541 通过，85 项失败与整改前**失败集合逐条一致**（无新增回归），仍为 code-mode host/
  工作区二进制/真实网络三类环境限制，按审查口径记为"环境归因、未独立确认"。
- 格式化与 lint：`just fmt`、`just fmt-check`、`just fix -p codex-core -p codex-team-state` 均通过。
- 文档：M-1 精炼 log 与本计划已更新；`doc/WBS/multi-agent-trusted-evidence.md` 已按实际状态同步。
- 顶层 `doc/WBS.md` / `doc/WBS-COMPLETED.md`：按决策 005 明确延后。
- Bazel（`BUILD.bazel` / `MODULE.bazel.lock`）：本机未安装 Bazel，按用户指示不为 M-1 安装，标记为
  **当前环境未验证的非阻断项**；两个 Bazel 文件均无变化，依赖正确性由 Cargo lock、定向测试与 diff 兜底。
- 全 workspace 测试、Docker、真实 API、本地模型：未运行，不属于本任务。

### 交接边界

- 执行者已在本工作树完成、提交并停止；独立审查者将对照本计划、实时 WBS、代码 diff、定向测试和现场状态验收。
- 本计划自此冻结；M-2 及以后路线只链接 `doc/WBS/multi-agent-trusted-evidence.md`，不在此继续规划。

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
| 007 | 团队领域独立为 `codex-team-state` crate，只依赖 `codex-protocol`，不进 `codex-core` | 不变量与并发语义可单独测试，也不给已经臃肿的 core 增重 | `multidev/` 架构 | 已采纳 |
| 008 | 团队状态挂在 `AgentControl` 上 | 它本来就是每个 Root 树创建一次、被全部子 Agent clone，天然给出"一个存活 Root 树一份 canonical 状态" | 团队实例生命周期 | 已采纳 |
| 009 | 参与者身份在 `Session::new` 从 thread id + session source 派生并幂等注册 | 权威身份唯一来源；幂等注册同时实现"卸载重载仍属原实例、权限与状态不变" | 身份与重载 | 已采纳 |
| 010 | 唤醒实现为每参与者可消费计数 + watch 通道，先订阅再检查 | V2 wait 等的是自己的 mailbox，团队变化没有投递通道；计数关掉"先检查后订阅"竞态，也让已消费变化不重复唤醒 | Root wait | 已采纳 |
| 011 | 幂等身份默认取 harness 的 tool `call_id`，模型只能可选覆盖 | 重试身份由 harness 而不是模型记忆保证，模型漏传也不会产生重复对象 | 工具面 | 已采纳 |
| 012 | 新增 `features.multi_agent_v2.team_state_enabled`，默认关闭 | 避免改动既有 multi-agent 测试的工具面与 prompt；M-1 集成测试显式打开跑真实链路 | 配置与测试范围 | 已采纳 |
| 013 | 稳定团队协议走 world-state section 进 initial context，动态投影只走 request-only 尾部 | 稳定前缀保住前缀缓存并随 compaction 自动重注入；易变数据不进 history/rollout | 投影与缓存 | 已采纳 |
| 014 | authored 内容在写入时即有界，投影与历史因此构造性有界 | 比让每个消费方各自记得裁剪更可靠，也让 store 里不存在无界字段 | 领域与投影 | 审查整改后采纳 |
| 015 | 极小预算下投影退化为不可再缩的省略通告，允许它略超预算，而不是输出空块或消失 | 空块等于谎称"团队无事发生"且模型无从分辨；通告只有几十 token，真正的空间回收交给已有 compaction | 投影预算 | 审查整改后采纳（与审查建议的硬 clamp 不同） |
| 016 | 可见性同时决定可读与可贡献，append 前校验可见性 | 引用可猜，靠引用保密等于没有边界；与设计合同第 21 条一致，M-2 再由 route 扩展 | 权限 | 审查整改后采纳 |
| 017 | Root 的 `resolved` 为终态，不可原地重开 | 重新相关只能由新 Version 表达，否则破坏追加式历史语义 | 生命周期 | 审查整改后采纳 |
| 018 | 只承认可核验的会话身份（用户面 root 线程、带 agent path 的 V2 spawn），其余不登记 | 把"缺省当 Root"改成"证明不了就没有能力"，这才是 fail-closed | 身份 | 审查整改后采纳 |
| 019 | 对外引用携带完整 UUID 实例身份 | 实例归属必须是可精确校验的事实，不是概率判断；代价是引用变长 | 引用与重置 | 审查整改后采纳 |
