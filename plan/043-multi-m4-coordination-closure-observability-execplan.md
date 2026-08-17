# Multi M-4 协调闭合与可观测性 ExecPlan

> 本计划是本任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述 Multi M-4；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在已经合入 `main` 的 M-1 团队世界状态、M-2 选择性路由和 M-3 证据锚定之上，完成 RONDO Multi 离线内核的
协调闭合与可观测性纵切：

> Harness 从 AgentControl、registry、residency 与恢复能力等权威事实派生 producer 可用性；只有 Root 能在
> producer 被确认真正不可用后，显式把其未终态 Version 退休为独立终态；同时 Root 可通过有界、确定性的状态转储、
> 精简变更日志和发布统计解释团队为何处于当前状态。

本阶段只解决“如何诚实结束遗留 producer 注意力”和“如何定位错误协调”。它不自动替 Root 作判断，不把协调元数据
扩张成完整审计系统，也不开始 M-5 的真实运行。

本计划固定产品行为、失败语义和验收证据，不预先固定可用性探针的内部表示、缓存方式、工具名、模块边界、分页编码或
提交拆分。执行者应依据实时源码选择最小完整实现，并可采用比软建议更清晰的等强方案。

### 完成/验收标准

- [ ] producer 可用性至少稳定区分四类等价语义：**当前可用**（正在运行或仍可接收任务）、**可恢复但未加载**
      （当前不驻留，但可在同一 Root 树恢复）、**真正不可用**（权威控制面确认当前团队实例内已不可恢复）和
      **状态无法确认**。`Completed`、`Interrupted`、`Errored`、`Shutdown`、`NotFound`、registry 缺项或 residency
      卸载等任一表面事实均不得单独机械等同于真正不可用。
- [ ] 可用性由 Harness 权威事实派生，不信任模型或工具参数自报。读取存储/控制面失败、创建/卸载/恢复竞态、来源矛盾
      或缺少足够事实时必须落入“状态无法确认”并 fail-closed；Root 的活动视图对已展示 Version 标明 producer 的派生
      可用性，完整状态转储还应覆盖已退出活动视图的参与者与 Version。
- [ ] 只有 Root 可以退休 Version；目标必须仍处于 producer 未终态，且其作者在提交时仍被权威事实确认为真正不可用。
      可恢复未加载、状态不明或当前可用的 producer 均明确拒绝。退休记录是与 producer 自己 `closed` 不同的独立终态，
      至少保留目标、Root 操作者、非空有界原因、提交 revision 和当时验证的可用性状态版本/等价证明。
- [ ] Root 退休只移除目标 Version 的 producer-open 活动理由：不得替 Root 改成 `resolved`，不得结束或改写 route、
      assignment、delivery、同 Event 其他作者 Version、同作者其他 Version、Fact 引用或不可变 authored 内容。若还有
      root attention、进行中 assignment 或其他自己的未终态 Version，Event 继续按原活动谓词保留。
- [ ] 不自动退休、不自动清理 orphan、不自动改 root attention，也不自动 escalation。Root 不操作时开放 Version 持续
      悬挂且历史保留；可用性变化本身是否产生 wake 必须有明确、可测试且不冒充 escalation 的规则。Root 自己提交退休
      不得产生自唤醒，任何实际 mutation 的日志都能说明唤醒目标，或说明没有唤醒时适用的规则。
- [ ] 退休是终态。即使成员之后重新出现，旧 Version 也不得原地重开或改写为 producer closed；继续调查只能在仍有权限
      的同一 Event 下追加新 Version。新 Version 使用当时的新生命周期，不继承旧退休状态。
- [ ] 退休提交具备目标状态前置条件、可用性状态版本/等价并发保护和稳定重试身份：陈旧请求被拒绝并返回足够的当前状态，
      并发请求最多一个提交；精确重试返回原结果但不增加 revision、wake generation、变更记录或统计；同一重试身份换
      目标/原因必须拒绝，第二次独立退休同一终态也不得覆盖原操作者和原因。
- [ ] 提供 Root 可用的状态转储入口。一次结果或一页必须有硬上限，并能分页到其余条目；同一 revision/可用性快照下重复
      读取使用稳定排序并得到等价内容。分页不得把不同 revision 的页面静默拼接；可以通过冻结快照、带版本 cursor、
      陈旧 cursor 拒绝或其他等强方式保证一致性。
- [ ] 状态转储至少包含：团队实例、当前 revision 与 wake generation；参与者及其派生可用性与状态版本；Event/Version、
      producer/Root 双生命周期和 Root 退休元数据；visibility grant、route/assignment/delivery；Fact 引用、producer、
      类别和 locator 等定位元数据；每个参与者对 Event 的可见/不可见理由及活动视图纳入/排除理由；每个 Agent 的发布
      统计。允许展示 TeamState 已持有且受既有上限约束的 Event/Version 字段，但不得读取或复制原始工具输出、完整
      transcript、rollout 周边、私有上下文或证据正文。
- [ ] 当前团队实例生命周期内保留按 revision 排序的轻量变更日志。每条实际变更至少说明 actor、revision、mutation
      类别、目标对象 ID、必要的前后状态 delta、wake 决策/规则；能够结合当前转储回答“谁在什么 revision 改了什么”、
      “Root 为什么被或未被唤醒”、“某 Agent 为什么能/不能看见 Event”和“Version 为什么仍活动、退出活动或被退休”。
- [ ] 变更日志只保存协调元数据，不复制 title/summary/handoff/route note、工具输出、Fact 正文、transcript 或私有上下文；
      拒绝操作和稳定重试不伪造新 revision 或新日志。日志是 TeamState 的轻量解释面，不成为第二份 canonical 状态，
      也不要求跨进程持久化、签名或防篡改链。
- [ ] 发布统计按参与者覆盖当前团队实例，至少包含：成功且唯一的 Version 发布次数、authored 内容总体量和这些 Version
      持有的 Fact 引用总数。内容体量必须在输出/代码中明确单位与纳入字段，并只从 TeamState canonical 写入后的有界
      authored 字段计算；被拒绝发布和稳定重试均不计数。统计与全量 canonical Event/Version 可机械重算一致，零发布
      参与者也有明确结果。实现可以查询时派生或在 commit 时维护，但不得漂移。
- [ ] 至少一条真实、无 API 的 RONDO Multi 产品纵切通过实际 Agent/session/control/team tool 接缝跑通：成员发布开放
      Version；成员被卸载但仍可恢复时 Root 能看见该分类且退休被拒绝；权威控制面随后确认其真正不可恢复，Root 显式
      退休成功；转储、日志和统计能解释前后状态。纯 TeamStore 单测只能补充，不能代替该产品纵切。
- [ ] 代表性负向与并发路径被固化：状态未知拒绝、非 Root 拒绝、错误目标/错误实例引用、已 closed/已退休目标、陈旧可用性
      快照、退休与 producer close/成员再现竞态、并发退休、精确重试、重试身份复用、成员重新出现后旧 Version 不重开、
      未操作 orphan 持续悬挂、退休不误伤 Root attention/其他作者 Version/route assignment，均有贴近所属边界的测试。
- [ ] 确定性和解释能力有直接断言：打乱 HashMap/注册/查询来源的自然遍历顺序不改变规范输出排序；无状态变化的重复 dump
      等价；有界/page 边界可达；visibility 与 active-reason 的正反两面成对覆盖；每条 canonical revision 与变更记录、
      wake 决策相符；精确重试不会使 wake generation 虚增。
- [ ] M-1 世界状态、M-2 route/assignment/notification、M-3 Fact 捕获/发布窗口/权限下钻与现有
      `team_state_enabled` 默认关闭行为不退化。运行 `codex-team-state`、新增 M-4 团队产品纵切、既有 M-1—M-3 产品
      定向回归及实际受影响 core/Agent 生命周期模块门禁，不扩大为全 workspace 测试。
- [ ] `just fmt`、`just fmt-check`、受影响 package 的 scoped lint/fix 与定向 Rust 测试通过；diff、生成文件、资源和
      worktree 现场检查完成。本计划状态、精炼 `agent_log/`、Multi 子 WBS、顶层 WBS和完成历史按职责同步，完整成果
      提交在 043 工作树分支后停止，未合并、未推送。

## 2. 范围

### 允许修改

- `multidev/` 中实现 M-4 所需的 `codex-team-state` 领域状态、AgentControl/registry/residency/恢复能力接缝、团队投影、
  团队工具、构建清单、生成文件和定向测试。
- 为形成一致的可用性快照、wake generation、Root 退休原子提交和有界诊断读取所需的最小局部重构；具体落点由实时
  源码决定，不要求把所有概念都塞入 `codex-core` 或 `codex-team-state`。
- 本文件的“当前状态”和“关键决策记录”、一份或少量真正有意义的 M-4 精炼 `agent_log/`，以及完成时
  `doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS.md`、`doc/WBS-COMPLETED.md` 中各自职责内的当前事实/历史。
- 任务需要的普通依赖处理、生成文件/锁文件更新和只读源码/官方文档查询；生成差异必须用仓库既有工具产生并审查。

### 不允许修改

- `mydev/`、RONDO Local、`training/`、Local 私有数据、模型工件、测评结果与无关 eval 设施。
- `codex-source-code/` 上游只读快照、冻结 `codex-doc/`、既有历史 plan/log/audit snapshot 的形成时点结论。
- M-5 runtime bundle、真实协作工作流、Docker、真实 API、付费运行、退化比较、训练、测评结果或生产启用。
- Event 关系图、自动合并、重要性分类、批量结束注意力、自动 orphan 清理、自动 escalation、自动语义判断或证据新鲜度。
- 产品级 UI、数据库、跨进程团队状态/日志持久化、外部日志平台、完整审计系统、签名/防篡改链、复杂 ACL、原始证据归档、
  artifact store、全量工具输出/rollout/transcript 副本或通用诊断浏览器。
- CI、PR、上游基线升级、系统/全局工具链配置、远端资源和无关功能/重构。

### 不允许读取/查看

- `.env.local` 的任何内容；本任务不需要密钥，不得打开、搜索、打印、复制、记录或 source 该文件。
- 与本任务无关的私有运行数据、模型权重、个人配置、其他 worktree 的未提交内容和项目外文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **隔离执行**：所有受跟踪编辑、格式化、构建、测试和提交只在
   `.claude/worktrees/043-multi-m4-coordination-closure`（分支
   `worktree-043-multi-m4-coordination-closure`）进行。不回退、覆盖、stash、移动或清理来源不明的修改，不进入
   其他 worktree 开发。
2. **权威可用性与 fail-closed**：可用性必须综合当前加载/可接收任务事实、Agent registry、residency、同一 Root 树
   恢复资格及其权威状态；具体证据不足或相互矛盾时归为未知。不得把单个 `AgentStatus`、一次发送失败、当前 session
   未加载、registry 查询 miss 或模型自述直接当成真正不可用，也不得为了让退休测试通过而削弱现有恢复能力。
3. **退休独立且原子**：退休只能由权威 Root 身份对显式 Version 执行；提交时再次验证 producer 未终态、作者身份、
   真正不可用及其状态版本，记录有界原因和操作者后原子进入独立终态。它只改变 producer-open 这一轴，不改 authored
   内容、Root 轴、route、其他 Version 或证据；终态不可覆盖、不可重开。
4. **并发、重试与 generation**：退休和既有 mutation 一样先完整验证再一次提交；陈旧或冲突不部分写入。稳定重试、
   no-op delivery/route replay 等没有 canonical 变化的路径不得新增 revision、变更日志、发布统计、wake ledger 信号或
   对外 wake generation；任何 generation 的含义必须明确并由真实变化驱动。
5. **轻量、确定、有界的解释面**：dump、日志、统计必须从同一 canonical TeamState 与明确的权威可用性快照得到，排序
   不依赖 HashMap 或异步完成顺序；每个入口有硬上限且超出部分可分页或显式计数。不得以“调试方便”为由复制原始
   evidence、工具输出、transcript/rollout 周边或私有上下文，也不得创建第二套可写团队状态。
6. **真实纵切与既有语义**：M-4 必须接入实际 RONDO Multi Agent/session/control/team tool 运行面，保持 M-1 单一
   TeamState、实例身份、不可变 Version、请求级投影与活动谓词，M-2 可见性/route/通知失败恢复，M-3 Fact 定位/权限/
   发布窗口，以及 feature 默认关闭语义。不能只在测试 helper 中直接注入“unavailable”绕过真实派生接缝。
7. **资源与外部边界**：不得直接运行 Cargo。Rust test/fix/clippy 等重型入口必须使用仓库已有、接入根
   `scripts/with-build-lock.sh` 的 `just` 配方，使用项目根内受监控 target，遵守全局单构建与 Windows `C:`/cgroup/
   项目容量门禁；拿不到必要计数或门禁持续拒绝时 fail-closed。禁止 Docker、真实 API、付费测评、本地模型、训练、
   数据外发、远端写入和系统配置变更。
8. **允许自修复重跑**：普通编译、格式、fixture、生命周期竞态、分页、排序或窄实现问题可以自行分析、修复并有界
   重跑，不因首次小失败停止。只有触及原则性边界、需要未授权高危能力、计划合同必须改变、资源门禁持续不可满足，
   或多次合理尝试后仍有实质阻塞时才暂停汇报；不得用重试绕过门禁、挑选结果或把 skip/未运行写成通过。
9. **文档与交付**：只按各文档职责同步当前状态和完成证据，不在 plan/log 复制 M-5 路线。完成后只读检查主工作区与
   各 worktree 的 Git 状态/意外生成物概况，不读取其他 worktree 的未提交内容；同时审查本分支 diff 和受保护文件。
   可按两个串行批次形成多个清晰提交，但只有联合产品纵切通过才算完成；最终只提交 043 分支并停止，不合并 `main`、
   不推送、不删除/重命名 worktree 或分支，等待独立审查。

## 4. 软性建议

以下是基于 `main@af1063d` 实时源码的高性价比候选，不是固定路线。执行者可根据代码、测试和复杂度采用更小、
更清晰或更可靠的等强方案，并在关键决策记录中简要说明重要取舍。

- 当前 `AgentControl` 同时拥有 `AgentRegistry`、`V2Residency`、`ThreadManagerState` 弱引用和共享
  `TeamStateHandle`；`resume_agent_from_rollout` 与 thread/agent-graph store 已表达“同一树内可恢复”。可考虑在此处
  形成一次 typed availability snapshot，再交给投影/退休/诊断消费；也可以选择职责更清楚的窄组件。重点是不要让
  `codex-team-state` 自己猜异步 Agent 生命周期事实。
- `Completed`/`Interrupted`/`Errored` 的空闲 session 仍可能接收下一轮；residency 卸载也会保留 registry 与 rollout
  恢复能力。现有 `close_agent` 之后同样可能被 `resume_agent` 恢复，不能未经真实恢复资格检查就把 close 当成永久
  unavailable。测试可复用现有 residency 容量、close/resume 和 test thread store fixture 来造四类状态。
- producer 独立终态可以扩展现有生命周期表示，也可以使用与 `ProducerState` 并列、但由活动谓词统一消费的退休记录；
  不要求特定 enum/字段布局。建议让退休结果直接带回提交时的 availability proof/version，便于并发冲突说明。
- 活动投影可以只为 Root 渲染必要的 producer availability 标签，并保持 M-1 的 request-only、同一逻辑采样重试复用
  同一快照和上下文硬预算。完整参与者矩阵、排除理由、locator 与统计更适合放在 Root-only 的有界诊断入口，避免把
  Active World Index 变成常驻调试面。
- 诊断入口可以新增一个窄 Root-only team tool，也可以扩展职责合适的现有读取面；退休可扩展 `team_update` 或使用独立
  工具。名称和 wire 结构由执行者决定，但普通成员必须 fail-closed，工具应继续受现有 `team_state_enabled` 总开关
  约束，且不要无必要扩展 app-server、TUI 或公开配置。
- 可考虑让 domain dump 先生成 stable typed snapshot，再由工具层做分页/序列化；IDs/ordinal/revision 是自然稳定排序键。
  availability 属于控制面 overlay 时，应与 TeamState revision 一起冻结或携带版本，避免一页之内前后不一致。
- 变更日志适合在每个 canonical commit 点追加小型 typed delta，wake decision 与 rule code 同步记录；visibility 和
  active-reason 可以从 canonical Event/Version/route 状态按现有谓词现场推导，不必为每个 Agent×Event 复制一份日志。
  拒绝、纯读取和 deduplicated outcome 不需要留下“尝试审计”。
- 发布统计从 canonical Event/Version 查询时重算通常最不容易漂移；如果为性能选择增量计数，应在同一次 publish commit
  更新并用全量重算测试对账。内容体量可采用 canonical 新 Event title + Version summary/handoff 的 Rust
  `chars().count()` 等价值，与现有按字符截断保持一致；也可选择更合适且同样明确、可重算的单位/字段集合。
- 建议按“producer availability + Root retirement 纵切”→“dump + change log + publication stats”两个串行批次推进；
  每批可有一个或多个 reviewable commit，但第二批必须覆盖第一批产生的新状态，最后再跑联合产品纵切。
- 领域测试优先覆盖四类 availability 输入、退休 CAS/终态/活动谓词、日志 revision/wake 与统计重算；产品 integration
  suite 覆盖真实 AgentControl/residency/resume/team tools。无须把每个纯排序或错误码都复制成昂贵产品纵切。
- 定向门禁优先包括 `just test -p codex-team-state`、新增 M-4 suite、既有 `suite::team_world_state`、
  `suite::team_routing`、`suite::team_evidence`，以及实际受影响的 `agent::control`、`tools::`、`team::`、`context::`
  子集；只跑真正受影响的包/模块，不机械跑完整 workspace。loopback core 测试继续显式清空环境代理并设置
  `NO_PROXY=127.0.0.1,localhost`，避免把代理噪声误判为实现失败。
- 若 Rust 依赖、config 或 schema 确实变化，按 `multidev/AGENTS.md` 使用既有生成器同步 Cargo/Bazel/config/schema；
  没有真实需要则不要新增依赖、配置开关、数据库 migration 或生成文件。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已核对根 `AGENTS.md`、`README.md`、顶层 WBS、Multi 子 WBS、`multidev/AGENTS.md`、计划模板、M-1—M-3
  ExecPlan/日志与实时源码/测试接缝。
- 现场与用户给出的前置一致：`main` 与 `origin/main` 均为 `af1063d`，主工作区干净；M-3 已验收并合入，Local 已正式
  收口；已逐一只读复核 037—042 历史 worktree，均干净且位于 `zz-done/*` 归档分支，M-4 不需要并行避让。
- 已从 `main@af1063d` 创建 `.claude/worktrees/043-multi-m4-coordination-closure` 和本地分支
  `worktree-043-multi-m4-coordination-closure`；没有在主工作区修改任何受跟踪文件。
- 已确认实时架构：`TeamStore` 集中拥有 revision、幂等提交、双生命周期、route、wake ledger 与 Fact refs；
  `AgentControl` 掌握 registry、当前加载状态、V2 residency 和 rollout 恢复路径。可用性必须在两者接缝处诚实派生，
  不能只读 `AgentStatus`。
- 已完成一次只读独立计划审查；审查确认四类 availability、Root retirement、dump/log/stats 的最小接缝与本计划一致，
  并特别指出现有 `TeamStateHandle` 对 deduplicated/no-op 的 `notify_change` 也会推进 change generation，已纳入 M-4 硬约束。
- 本 ExecPlan 已按模板形成；此轮仅规划和交付执行者提示词，尚未实现或运行 Rust 构建/测试。

### 当前工作

- 独立复验认定 `8f73572` 仍未完整实现本计划。第二轮审查缺口已在 043 工作树窄修；未合并、未推送，等待再次独立审查。

### 本任务剩余步骤

1. 再次独立审查对照本计划、live code 与定向测试验收。
2. 审查通过后由用户授权合并与推送。

### 阻塞项

- 无。Docker、真实 API、本地模型、付费资源、全 workspace 测试、合并和推送均不是本任务所需或已授权范围。

### 当前验收状态

- 规划现场核对、worktree 创建和 ExecPlan：已完成。
- 首次实现提交 `e03eef1`：独立验收不通过（报告 `e2105aa`）。
- 第一轮整改 `8f73572`：独立复验不通过（报告 `035977c`）。
- 第二轮审查缺口整改、格式化、lint、定向测试、文档同步：本轮已完成并提交 043 分支。
- 再次独立审查：待进行；不由执行者自判替代。

### 交接边界

- 执行者在目标和硬边界内自主选择最小完整实现，不把软建议中的文件、类型、工具名、状态编码、分页方案或提交拆分
  当成固定要求；发现更优等强路线可自行采用并在关键决策记录中简述。
- 普通编译、fixture、竞态或窄实现问题应自主修复并有界重跑；原则边界、未授权高危扩展、合同变化、持续资源门禁或
  多次合理尝试仍无法收敛的实质阻塞才暂停汇报。
- 完成后只提交 043 工作树并停止；独立审查者将对照本计划、实时 WBS、live code、定向测试和 Git/资源现场验收。
- 本任务完成后冻结本计划；M-5 及以后只链接 `doc/WBS/multi-agent-trusted-evidence.md`，不在此继续规划。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 固定 M-4 行为、失败语义和验收证据，不预先锁死工具名、模块、缓存、分页或提交拆分 | 用户要求保留执行者自主权，实时源码存在多个等强接缝 | M-4 实现 | 已采纳 |
| 002 | 可用性固定为当前可用、可恢复未加载、真正不可用、状态未知四类；任何单一 AgentStatus 都不足以证明真正不可用 | Completed/Interrupted 等状态仍可接收下一轮，close/unload 后也可能同树恢复 | availability | 已采纳 |
| 003 | Root 退休是 producer closed 之外的独立终态，并记录操作者、原因、revision 与 availability state version | 不能伪造作者结论，也要拒绝陈旧/并发覆盖 | Version 生命周期 | 已采纳 |
| 004 | 不自动退休、清理、改 root attention 或 escalation；Root 不操作时 orphan 持续悬挂 | Harness 不替 Root 作语义判断，且与 WBS 当前设计一致 | 协调策略 | 已采纳 |
| 005 | 退休只撤销 producer-open 活动理由，Root attention、route、其他 Version 与 Fact refs 均独立保留 | 维持 M-1/M-2 的统一活动谓词和双生命周期 | 活动视图 | 已采纳 |
| 006 | Root 获得有界、确定、可分页的完整诊断面；常驻活动投影只增加必要 availability 信息 | 兼顾可诊断性与模型上下文预算，不把投影变成 UI/审计 dump | 状态转储 | 已采纳 |
| 007 | 变更日志只记录 canonical mutation delta 与 wake rule，不记录拒绝尝试或正文 | 足以解释协调，又避免第二份状态、transcript 副本和复杂审计设施 | change log | 已采纳 |
| 008 | 发布统计按唯一 committed Version 计次；内容单位与纳入字段须明确并基于 canonical authored 字段，Fact 数计 Version refs | 保证可从当前 TeamState 精确重算，又不给实现者锁死唯一体量口径 | publication stats | 已采纳 |
| 009 | 无 canonical 变化的重试/no-op 不得推进 revision、wake generation、日志或统计 | 相同状态重复 dump 必须等价，不能产生虚假可观测变化 | 幂等与可观测性 | 已采纳 |
| 010 | 实施分两个串行批次，但不规定每批的 commit 数和具体内部路线 | 便于审查同时不给执行者施加不必要结构约束 | 实施顺序 | 已采纳 |
| 011 | 普通窄失败允许自主修复并有界重跑，原则边界或持续实质阻塞才暂停 | 给实现与测试恢复合理冗余，不放松安全和资源门禁 | 执行流程 | 已采纳 |
| 012 | 043 只提交工作树分支；合并、推送和分支/worktree 归档等待用户另行批准 | 遵守本次明确交付边界 | Git 交付 | 已采纳 |
| 013 | 当前无需在主工作区直接生成 ignored 产品数据；主工作区侧仅保留 Git 管理 043 worktree 所需目录与元数据 | M-4 是 session 内存态代码/测试任务，不涉及私有数据资产 | 工作区 | 已采纳 |
| 014 | 产品可用性按显式 `resume_agent` 恢复能力派生，与自动 V2 load（`probe_v2_restore`）拆开：Loaded→available；store+history 可重建→recoverable_unloaded（registry 缺失不算真正不可用）；store/history 明确缺失→unavailable；其余读失败→unknown。epoch 是 ThreadManager 单调 generation | `shutdown_live_agent` 会丢掉 registry 但保留 rollout，既有 `resume_agent` 测试证明仍可恢复并接收输入 | availability | 已采纳 |
| 015 | 退休是 `Option<RetirementRecord>` 覆盖层，producer 保持 `open`；只撤销 producer-open 活动理由 | 不能伪装成作者 closed，也不能改 root attention / route / 其他 Version | Version 生命周期 | 已采纳 |
| 016 | dump/log 用 offset 分页；dump cursor 为 `revision:epoch:observe_generation:offset`；对外 ID 用 Display 字符串。`observe_generation` 在新建 participant 和 `confirm_observation` 时递增 | 同 revision 下 dump 排列变化（插页 Fact）不能静默拼接旧 cursor | 可观测性 | 已采纳 |
| 017 | `TeamStateHandle::notify_change` 只在真实 canonical mutation 上 bump；稳定重试/no-op 不写 changelog、不改统计 | 修掉 deduplicated 也会推进 wake generation 的既有问题 | 幂等 | 已采纳 |
| 018 | Root-only 工具 `team_retire` / `team_inspect`（dump/log/stats）；协议片段升到 v4 | 与现有 team 工具同一 namespace，不另做诊断浏览器 | 工具面 | 已采纳 |
| 019 | `authored_chars` 计 Unicode 标量值，纳入开 Event 的 title、每 Version 的 summary 与可选 handoff，查询时从 canonical 重算 | 拒绝发布和稳定重试本来就不会入库，统计不会漂 | publication stats | 已采纳 |
| 020 | 同状态 lifecycle（`pending→pending` / `tracking→tracking`）是无 canonical 变化的 no-op：不推进 revision、changelog 或 wake generation | 与硬约束 4 一致；成功提交不等于状态变了 | 幂等 | 已采纳 |
| 021 | 发布统计按 `thread_id` 聚合并尊重 limit/offset；dump Version 只带 `fact_ref_count`，Version→Fact 用独立 `VersionFact` 行分页；Fact 带 `call_id`；Agent 关系行同时保留 label 与 `thread_id` | 单条 dump 不得随 Fact 数无界增长；重复 label 必须能指出具体 Agent | 可观测性 | 已采纳 |
| 022 | 产品纵切仍覆盖 unload→recoverable 拒绝→delete→unavailable 退休。`resume_agent` 可恢复性与陈旧 epoch 分别落在控制面 shutdown/resume 测试和领域 live_epoch/ABA 测试 | 审查反例的权威接缝在控制面/领域层；产品 suite 继续验证真实工具纵切 | 测试分层 | 已采纳 |
| 023 | 退休最终检查与 loaded-map insert/remove、store delete、registry release 共用一把同步 availability gate；gate 内不再 await | 只线性化最终 epoch 重验与恢复/删除，不建事务或审计设施；避免跨 await 持锁 | 并发 | 已采纳 |
| 024 | dump 续页只接受带 revision/epoch/observe_generation 的 cursor；裸 offset 拒绝 | 防止 mutation 后用 offset 拼接不同快照 | 可观测性 | 已采纳 |
