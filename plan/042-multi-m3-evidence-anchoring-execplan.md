# Multi M-3 证据锚定 ExecPlan

> 本计划是本任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述 Multi M-3；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在已经合入 `main` 的 M-1 团队世界状态和 M-2 选择性路由之上，完成 RONDO Multi 的证据锚定真实产品纵切，
让 Agent 发布的 Event/Version 可以机械回溯到 Codex Harness 当时真正观察并正式保留的工具结果：

> Agent 完成工具调用并留下受支持的文本结果 → Harness 建立稳定 Fact 引用 → Agent 成功发布 Version 时，
> 自动关联本发布周期新增的 Fact → Root 或获得该 Event 可见性的 Agent 按权限下钻到那一个 observation。

Fact 只证明“当时观察到了什么”，不证明结果现在仍然成立。Harness 不替 Agent 判断 observation 是否值得发布，
也不把 Fact 自动升级成 Event。

本计划固定产品行为、权限与失败语义，不预先固定捕获接缝、Fact ID/locator 编码、索引内部类型、工具名、模块边界、
锁或事务表示。执行者应根据实时源码选择最小完整实现，并可采用比软建议更清晰的等强方案。

### 完成/验收标准

- [ ] 首版 observation 支持集非空，并准确限定为：**已经完成、由 Codex 正式保留、结果内容为文本的工具结果**；
      成功和失败结果都能形成 Fact。未完成/仅流式增量、模型普通回复与推理、Agent 间自由消息、团队工具与证据读取
      工具自身结果、图片/音频及其他非文本结果均不形成 Fact。
- [ ] 当前团队实例存续期内存在轻量 Fact Index。每个 Fact 有稳定身份、权威 producer、确定顺序、类别、指向正式
      retained observation 的 locator 和明确可用状态；Fact ref 写入 Version 前这些定位事实已经确定。Fact 的完整身份
      属于当前团队实例，旧实例引用不能解析到新实例，未确认保留成功的结果不能标成 Available。
- [ ] 每次成功发布 Version，都自动且只关联该权威 Agent 自上一次成功团队发布以来新增的受支持 Fact；首次发布从其
      加入当前团队实例起算。同一参与者卸载后重载不重置窗口，其他 Agent 的 Fact 不进入其发布窗口。
- [ ] canonical commit 前的发布失败不推进成功游标，同一逻辑重试沿用已经绑定的 Fact 集；commit 已成功但响应/传递
      失败时，重试返回原 Version 和原 refs。两者都不得重复创建 Fact/Version，也不因重试期间出现新 observation
      而漂移。并发完成的工具结果与发布边界有唯一、可测试的机械顺序，不丢失、不重复关联。
- [ ] Fact refs 写入 Version 的 authored 内容后不可变；团队投影或有界历史能让有权参与者取得该 Version 明确引用的
      Fact refs。TeamState 只保存引用和必要元数据，不复制全量工具输出。
- [ ] 证据下钻按权威 Session 身份 fail-closed：Root 可读当前团队 Fact；子 Agent 可读自己产生的 Fact；子 Agent
      还可读其可见 Event 的任一 Version 明确引用的 Fact。仅猜中 Fact ID、同团队 sibling 关系或看见别的 Event ID
      都不授予读取权限；跨团队、未知或畸形引用显式拒绝。
- [ ] 下钻只返回目标 observation 的有界文本和必要元数据，不附带相邻 rollout、调用参数、其他工具结果、完整
      transcript 或 producer 私有上下文。原始 observation 已不可取得时返回 `Unavailable` 或等价显式状态，
      Version 中的不可变引用仍可诚实解释，不出现无标记悬空引用；超出读取上限时显式截断或省略。
- [ ] 至少一条真实无 API RONDO Multi 产品链通过 Agent/session/tool execution/retention/team tool 接缝跑通：
      成功文本工具结果 → FactRef → Version → Root 下钻。纯领域状态机测试只能补充，不能代替这条纵切。
- [ ] 成功与失败文本工具结果各至少有一条正常可用的 Fact 下钻；`Unavailable` 只验证原始结果确实不可再取得时的
      诚实退化，不能代替首版支持类别的正常链路。
- [ ] M-2 route 纵切扩展跑通：目标 Agent 只能下钻该可见 Event 明确引用的他人证据，并在同一 Event 下追加自动携带
      自己新 Fact 的 Version；Root 随后能读取新的多作者 chain 及两侧获授权证据。未 route 的 sibling 证据保持拒绝。
- [ ] 确定性与拒绝路径有代表性覆盖：同一执行轨迹重放产生相同的 observation-to-publication 关联；成功/失败工具结果、
      发布失败后重试、精确重放、并发边界、Unavailable、有界返回、猜测 ID 越权、跨实例、非文本/未完成结果、
      团队工具及证据读取不递归产 Fact 均被验证。
- [ ] M-1/M-2 已验收行为与默认关闭状态不退化；功能关闭时不注册新增团队能力、不改变普通工具结果与 rollout 行为。
      运行 `codex-team-state`、新增 M-3 产品纵切、M-1/M-2 产品回归及实际受影响 core 模块的定向门禁，不扩大为
      全 workspace 测试。
- [ ] `just fmt`、`just fmt-check`、受影响 package 的 scoped lint/fix 与定向 Rust 测试通过；diff、生成文件、资源与
      worktree 现场检查完成。本计划状态、精炼 `agent_log/`、Multi 子 WBS、顶层 WBS 和完成历史按职责同步，完整成果
      提交在 042 工作树分支后停止，未合并、未推送。

## 2. 范围

### 允许修改

- `multidev/` 中实现 M-3 所需的团队领域状态、Session/AgentControl 生命周期组件、正式工具结果保留接缝、团队工具、
  投影/历史表示、构建清单、生成文件和定向测试。
- 为把 Fact 定位到 Codex 已保留 observation 所需的最小局部重构；具体落点由实时源码决定，不要求把新概念都塞入
  `codex-core` 或 `codex-team-state`。
- 本文件的“当前状态”和“关键决策记录”、一份或少量真正有意义的 M-3 精炼 `agent_log/`，以及完成时
  `doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS.md`、`doc/WBS-COMPLETED.md` 中各自职责内的当前事实/历史。
- 任务需要的普通依赖处理、生成文件/锁文件更新和只读源码/官方文档查询；生成差异必须用仓库既有工具产生并审查。

### 不允许修改

- `mydev/`、RONDO Local、`training/`、Local 私有数据、模型工件、测评结果与无关 eval 设施。
- `codex-source-code/` 上游只读快照、冻结 `codex-doc/`、既有历史 plan/log/audit snapshot 的形成时点结论。
- M-4 的 orphan 退休、团队状态转储、变更日志与发布频率统计；M-5 的 runtime bundle、Docker、真实 API、付费运行
  或退化测评。
- Artifact store、全量工具输出副本、完整 transcript、完整 provenance graph、自动 freshness 验证/重跑、claim 与
  Fact 的逐句映射、相关性判断、证据评分、复杂 ACL/签名/审计/可信体系或跨进程 Fact 持久化。
- UI、CI、PR、上游基线升级、系统/全局工具链配置、远端资源和无关功能/重构。

### 不允许读取/查看

- `.env.local` 的任何内容；本任务不需要密钥，不得打开、搜索、打印、复制、记录或 source 该文件。
- 与本任务无关的私有运行数据、模型权重、个人配置、其他 worktree 的未提交内容和项目外文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **隔离执行**：所有受跟踪编辑、格式化、构建、测试和提交只在
   `.claude/worktrees/042-multi-m3-evidence-anchoring`（分支 `worktree-042-multi-m3-evidence-anchoring`）进行。
   不回退、覆盖、stash、移动或清理来源不明的修改，不进入其他 worktree 开发。
2. **支持集与事实边界**：Fact 只能来自已经到达 Codex 正式 retained boundary 的受支持文本工具结果；流式 delta、
   调用参数、模型/Agent 自述和仅发出但未保留的结果都不是 Fact。Fact 是 point-in-time observation，不得被表述成
   当前真理，Harness 不做自动语义升级、相关性判断或新鲜度验证。
3. **稳定身份而非 payload 副本**：Fact 身份、producer、顺序和 locator 由 Harness 权威事实生成，不信任模型传入。
   Fact Index 与 TeamState 不复制全量输出；Version 只持不可变引用。locator 必须只解析到目标 observation；丢失原始
   结果时保留索引身份并显式 Unavailable，不能转而返回相邻上下文凑数。
4. **发布窗口与幂等**：窗口按权威 producer 隔离，并以 Codex 的正式保留顺序而非墙钟时间判定。Fact 集合的选择、
   Version 提交与成功游标推进必须形成不会丢失/重复的统一语义；失败不消费窗口，稳定重试不漂移引用。新事实若落在
   已成功提交或已绑定重试的边界之后，留给后续成功发布。
5. **Event 可达权限**：证据读取权限只从当前团队实例的权威身份、Fact producer 和 canonical Event 可见性/引用关系
   推导。route 只开放该 Event chain 明确引用的目标 Fact，不开放 producer 的其他 Fact、工具调用参数、上下文或
   sibling rollout；团队工具和证据读取结果不得递归成为新 Fact。
6. **真实纵切与既有语义**：M-3 必须接入实际 RONDO Multi Agent/session/tool retention/team tool 运行面，并保持
   M-1 单一 canonical TeamState、不可变 Version、实例身份、投影/历史和 M-2 route/可见性/多作者链语义，以及现有
   `team_state_enabled` 默认关闭行为。不能只在测试 helper 中伪造关联。
7. **资源与外部边界**：不得直接运行 Cargo。Rust test/fix/clippy 等重型入口必须使用仓库已有、接入根
   `scripts/with-build-lock.sh` 的 `just` 配方，使用项目根内受监控 target，遵守全局单构建与 Windows `C:`/cgroup/
   项目容量门禁；拿不到必要计数或门禁持续拒绝时 fail-closed。禁止 Docker、真实 API、付费测评、本地模型、训练、
   数据外发、远端写入和系统配置变更。
8. **允许自修复重跑**：普通编译、格式、fixture、时序、权限或 locator 的窄问题可以自行分析、修复并有界重跑，
   不因首次小失败停止。只有触及原则性边界、需要未授权高危能力、计划合同必须改变、资源门禁持续不可满足，或多次
   合理尝试后仍有实质阻塞时才暂停汇报；不得用重试绕过门禁、挑选结果或把 skip/未运行写成通过。
9. **文档与交付**：只按各文档职责同步当前状态和完成证据，不把 M-4/M-5 路线复制进 plan/log。完成后只读检查
   主工作区与各 worktree 的 Git 状态/意外生成物概况，不读取其他 worktree 的未提交内容；同时审查本分支 diff 和
   受保护文件。可分阶段提交，但最终完整纵切必须在 042 分支形成清晰提交并停止；不合并 `main`、不推送、不删除/
   重命名 worktree 或分支，等待独立审查。

## 4. 软性建议

以下是基于 `main@0c1a5e4` 实时源码的高性价比候选，不是固定路线。执行者可根据代码、测试和复杂度采用更小、
更清晰或更可靠的等强方案，并在关键决策记录中简要说明重要取舍。

- 当前所有工具终态最终归一为 `ResponseInputItem` 并经 `Session::record_conversation_items` 进入 session history，再尝试
  持久化到 rollout；现有落盘失败路径可能只记日志，若 locator 依赖 rollout，执行者需要选择能诚实确认可用性的局部
  接缝，不能把未确认落盘的目标永久标成 Available。
  `FunctionCallOutput` / `CustomToolCallOutput` 的文本 body 是首版支持集的自然判定候选。捕获层需要在仍能可靠知道
  tool identity 的位置排除 `team_*` 与证据读取工具，并在正式保留成功后建立索引；若另一接缝更能同时满足两点，
  应选择更优落点。
- `AgentControl` 已由同一 Root 树的 Session 共享 `TeamStateHandle`，适合作为 session-scoped Fact Index 的所有权候选；
  也可以使用职责更清楚的独立组件。建议 `codex-team-state` 只拥有 typed Fact refs、发布窗口和授权所需元数据，避免
  为方便而把 rollout 读取或输出 payload 搬进领域 crate。
- Fact ID 可以复用团队实例 tag 加确定序号或等价稳定表示；locator 可由 producer thread、正式 response item/call
  身份和必要序号组成。重点是同实例内稳定、跨实例拒绝、重放可比较，不要求使用特定字符串格式；现有本地 response
  item ID 也不能未经论证就当成跨重放稳定 ID，不建议用墙钟或全量输出 hash 代替正式顺序。
- 发布路径可先按 retry identity 固定候选 Fact 区间，再一次性提交 Version refs 与成功游标；或者采用能直接证明同样
  不变量的其他事务边界。不要要求模型列 Fact，也不要因为当前窗口为空而拒绝合法 Version。
- 证据下钻可以新增一个窄 team tool，也可以扩展合适的既有读取面；建议复用 `TeamAccess` 的权威 actor 与既有 Event
  可见性判定。返回结构只需 reference、producer、category、availability、截断信息和目标文本等必要字段，不做通用
  rollout 浏览器。
- 产品测试可新增聚焦 M-3 的 integration suite，并复用 `core_test_support::responses`、实际 `Session`、真实团队工具
  与 M-2 route fixture。领域测试优先覆盖游标/重试/并发/权限矩阵；产品纵切覆盖真正的 retention locator 和泄漏边界。
- 下钻测试可在目标 observation、相邻工具结果和相邻消息中放置互不相同的 marker，断言返回只包含目标 marker；
  这比只检查“返回里出现了目标文本”更能证明没有顺带泄漏上下文。
- 并发排序、非文本/未完成分类和细粒度幂等拒绝可在最贴近捕获/领域边界的单元测试验证；不要求每条负向场景都另建
  昂贵产品纵切。真实产品链重点覆盖成功、失败、route 后权限、不可见 sibling 拒绝和目标 observation 无泄漏。
- 实施可按“Fact 捕获与下钻基础 → Version 自动关联与 route 权限纵切”串行形成两个 reviewable 提交，也可在依赖关系
  更简单时用一个提交；只有完整纵切通过才宣称 M-3 完成。
- 定向门禁优先包括 `just test -p codex-team-state`、新 M-3 suite、既有 `suite::team_world_state` 与
  `suite::team_routing`、实际受影响的 `tools::`/history/rollout 测试和 scoped fix。只有确实改到 projection/context
  时再补对应 `context::` 门禁，不机械扩大到全 workspace。
- 保持现有团队 feature gate 通常最省兼容成本；除非真实接缝要求，不新增配置项、公开 app-server API、TUI 或复杂
  数据迁移。Cargo/Bazel/config schema 只在实际依赖或 schema 改动时用既有生成器同步。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已核对根 `AGENTS.md`、`README.md`、顶层 WBS、Multi 子 WBS、计划模板、M-1/M-2 ExecPlan 与实时源码/测试接缝。
- 用户提示中的旧现场已被后续交付取代：当前 `main` 与 `origin/main` 均为 `0c1a5e4`，主工作区干净；M-2 已合入，
  Plan 041 已完成、人判、独立验收、合并和推送，其分支已归档，M-3 前置条件全部满足。
- 已从 `main@0c1a5e4` 创建本专用 worktree 和本地分支；没有在主工作区修改任何受跟踪文件。
- **M-3 实现完成**，提交 `db39e28`（捕获、定位、发布窗口、权限、`team_evidence`）、
  `8360bbf`（失败结果捕获与真实产品纵切）、`ce32394`（收敛解析入口）、`cfe3dc1`（第一轮独立审查整改）、
  `35356ab`（验收审查整改：窗口完整锚定、一对一 locator、按 producer 暂存、PostToolUse 拦截结果入集）。
- 捕获拆成两步落在 `ToolRegistry::dispatch_any_with_terminal_outcome` 的两个终态分支（记下观察，此处才知道
  tool identity 与"是否真的跑完"）和 `Session::record_conversation_items`（确认保留后铸造 Fact 并按 retention
  顺序分配序号）。领域侧新增 `FactId` 与 `codex-team-state` 的 `evidence` / `store::evidence` 模块。
- 定向门禁全部通过（验收整改后重跑）：`codex-team-state` 101/101、`suite::team_evidence` 3/3、
  M-1/M-2 回归 12/12、`core` 的 `team::evidence` 6/6、合并 `tools::`+`context::` 共 541/541；
  clippy/fix/fmt/fmt-check 通过。
- 文档已同步：精炼日志 `agent_log/2026-08-17-040656-plan042-multi-m3-evidence-anchoring.md`、
  Multi 子 WBS、顶层 WBS 与 `doc/WBS-COMPLETED.md`。

### 当前工作

- 已交付并完成两轮审查整改，等待复验。

### 本任务剩余步骤

1. 等待独立复验结论；如再提出实质缺陷，在本分支窄修并只重跑受影响门禁。

### 阻塞项

- 无。Docker、真实 API、本地模型、付费测评和全 workspace 测试均不是本任务所需证据。
- 环境注意事项：本机 shell 存在环境代理且 `no_proxy` 使用 reqwest 不支持的 glob 形式，core 集成测试必须显式
  清空代理变量（`env -u HTTP_PROXY … NO_PROXY=127.0.0.1,localhost`），否则打向 loopback wiremock 的请求会被
  送去代理，表现为"expected 1 request, got 0"。这与本次改动无关。

### 当前验收状态

- ExecPlan 与现场核对：已完成。
- M-3 实现、格式化、lint、定向测试：已完成并通过，结果见上引门禁。
- 审查：两轮。第一轮（执行期自查）与第二轮（独立验收，报告见
  `agent_log/2026-08-17-045506-...-independent-acceptance-review.md`，结论为不通过）提出的全部缺陷已整改
  并重跑门禁。**复验尚未进行，不能表述为已验收**；合并与推送未执行。
- 主工作区 git-ignored 现场：仅 Git 创建了 `.claude/worktrees/042-multi-m3-evidence-anchoring` 目录及关联元数据；
  本任务没有在主工作区直接生成私有/ignored 产品数据。

### 交接边界

- 执行者在目标和硬边界内自主选择最小完整实现，不把软建议中的文件、类型、工具名或提交拆分当成固定要求。
- 完成后只提交 042 工作树并停止；独立审查者将对照本计划、实时 WBS、live code、定向测试和 Git/资源现场验收。
- 本任务完成后冻结本计划；M-4 及以后只链接 `doc/WBS/multi-agent-trusted-evidence.md`，不在此继续规划。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 固定 M-3 产品行为、权限与失败语义，不预先锁死捕获接缝、ID/locator、工具名或模块布局 | 用户要求保留执行者自主权，实时源码存在多个可行接缝 | M-3 实现 | 已采纳 |
| 002 | 首版只支持 Codex 正式保留的已完成文本工具结果，并同时覆盖成功和失败 | 得到最小非空纵切，同时避免提前建设图片/音频/资产存储 | Fact 支持集 | 已采纳 |
| 003 | Version 自动关联 producer 自上次成功发布以来的新增 Fact，模型不逐个选择 | 保证低负担、机械确定且可重放 | 发布窗口 | 已采纳 |
| 004 | 发布失败不消费窗口；稳定重试绑定同一 Fact 集，新到 Fact 留给后续发布 | 同时满足可恢复重试、无重复和窗口不丢证据 | 幂等与并发 | 已采纳 |
| 005 | TeamState 只保留 Fact refs/必要元数据，原始输出继续由 Codex retained observation 承载 | 防止团队状态变成 transcript/artifact store | 存储边界 | 已采纳 |
| 006 | 子 Agent 的跨 Agent 读取只沿其可见 Event 中的显式引用开放，猜测 ID 不授予权限 | 保留选择性传播和私有上下文边界 | 权限 | 已采纳 |
| 007 | 同一团队实例内要求引用与稳定重试精确稳定；新团队实例的重放比较 observation-to-window 关联而非复用旧实例 ID | 团队实例身份本来就必须隔离，确定性不能破坏 reset 语义 | 重放与身份 | 已采纳 |
| 008 | 普通窄失败允许执行者自行修复并定向重跑，原则边界或持续实质阻塞才暂停 | 给实现和测试恢复留合理冗余，不放松安全/资源门禁 | 执行流程 | 已采纳 |
| 009 | 042 只提交工作树分支；合并、推送和分支/worktree 归档等待用户另行批准 | 遵守本次明确交付边界 | Git 交付 | 已采纳 |
| 010 | 当前无需在主工作区直接生成 M-3 ignored 数据；`.claude/worktrees` 与 Git 元数据是唯一主工作区侧效果 | M-3 是 session 内存态与受跟踪代码/测试任务，无私有数据资产 | 工作区 | 已采纳 |
| 011 | locator 解析目标是 producer session 的 conversation history，按 Codex 为每个已保留 item 分配的身份一对一定位 | rollout 失败路径只记日志，依赖它无法诚实确认可用性；call_id 来自模型请求、可复用，据此匹配会串线或在 compaction 后把旧 Fact 重定向到新文本 | 定位与可用性 | 已实现（首版按 call_id 匹配，验收审查后改为 item 身份） |
| 012 | 捕获落在 tool dispatch 的终态分支 + retention 边界两处，序号在第二处分配 | 第一处才知道 tool identity 与"是否真的跑完"，第二处才知道真的被保留；一处做不到两件事 | 捕获接缝 | 已实现 |
| 013 | 失败结果也捕获：dispatch 的 `Err(RespondToModel)` 同样是终态 | 退出码非零的 shell 走该分支，只收 `Ok` 会让"失败"这半个支持集几乎为空 | 支持集 | 已实现 |
| 014 | dispatch 中更早的拒绝（未知工具、PreToolUse 拦截、PostToolUse 拒绝结果）不捕获 | 要么工具没跑，要么跑出来的结果被替换，都不是对工作的观察 | 支持集 | 已实现 |
| 015 | `ContentItems` body 整类排除，不抢救其中的文本片段 | 该形状是图片/媒体的载体，逐片段抢救会让 Fact 描述模型没真正看到的东西 | 支持集 | 已实现 |
| 016 | 不在 Fact 上缓存可用状态，改为每次读取现场回答；两种读不到的原因分别命名，都不写死引用 | “不在 producer 当前 history 里”正是普通 compaction 的结果，而 rollout 仍持有该项，据此永久降级会误判“真正不可用” | Unavailable 语义 | 已实现（首版曾单向降级，独立审查后移除） |
| 017 | 投影按上限命名引用并计数余量，完整清单走 `team_history` | 发布窗口无固定大小，逐条全列会让投影随运行时长无界增长 | 投影预算 | 已实现 |
| 018 | host 用 filler 顶替被丢弃的工具结果时，先撤销该次 note | 等待 runtime 清理的工具会在 abort 抢到终态后才返回，filler 用同一 call id 落盘，否则被打断的调用会变成证据 | 支持集 | 已实现 |
| 019 | locator 用 Codex 为每个已保留 item 分配的身份，call_id 只作元数据；重复 call_id 的 pending 槽位仍先到先得 | 一对一定位是唯一能保证“只解析到目标 observation”的做法，而 item 身份只需在本实例内唯一，不需要跨重放稳定 | 定位诚实性 | 已实现（首版靠“保留第一条 note”缓解，不足） |
| 020 | canonical Version 保留发布窗口的全部引用；上限只加在打印列表的surface（投影 4 条、工具结果 32 条）并报告省略数 | 消费了却不锚定等于永久丢失该 observation（游标已越过它），上下文预算不能改变不可变 authored 关联 | 上下文预算 | 已实现（首版在 authored 侧截断，验收审查否决） |
| 021 | pending 暂存上限改为按 producer 计，逐出时记 warn | 共享上限会让一个成员的突发把另一个成员即将保留的结果静默挤掉 | 捕获边界 | 已实现 |
| 022 | PostToolUse 拦截后的模型可见失败文本纳入支持集；执行前的拒绝（未知工具、PreToolUse）仍排除 | 拦截发生在 handler 已执行之后，它改变的是模型得到的答案，而那个答案会被正式保留 | 支持集 | 已实现 |
