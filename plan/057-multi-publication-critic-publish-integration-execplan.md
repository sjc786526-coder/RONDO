# Plan 057：M3-B2b Publication Critic 接入 Multi 发布流程 ExecPlan

> 本计划是 M3-B2b 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通实现、编译、测试、格式和局部设计问题应在范围内
> 自主修复并有界重跑。
> 本计划只描述 M3-B2b；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

依据 [`Publication Critic 产品合同`](../doc/rondo-multi-publication-critic-product-contract.md)，把 Plan 055 已交付的版本化 packet、
可信 expected identity、typed client、`PASS/REWRITE` 与 typed failure 接到 RONDO Multi 的 `team_publish` canonical mutation 之前，
实现默认关闭、可取消、有界且不改变 Team State 权威语义的 publication review cycle。

启用后，Harness 使用权威 Producer 身份、canonical target/candidate 和有权限的有界 Event continuity context 调用受控 Critic 服务；
前两次 `REWRITE` 只向 Producer 返回固定反馈而不提交，第二次改稿接受最终非阻断审核，typed failure 则停止继续审核并尝试发布当前稿。
最终 commit 仍且只由现行 Team State 路径完成。关闭时保持当前 `team_publish` 行为，不构造 packet、不调用 Critic，也不建立 cycle 状态。

### 完成/验收标准

- [ ] Publication Critic 配置默认关闭；关闭态下 `team_publish` 继续暴露现有 model-visible 输入/输出合同，调用者无需提供 Critic 续接信息，既有
      成功/失败结果、权限、canonical 内容、dedup/replay、stale、revision、wake、Root attention 和 evidence window 行为保持不变，并有现有回归
      与新增聚焦回归证明没有 Critic 调用或 cycle 副作用。启用态若需要 additive continuation 表达，只能按配置出现在启用合同中。
- [ ] 启用态在 store mutation 前构造 Plan 055 `PublicationPacket`：角色来自权威 session，target/title/candidate 与最终拟提交的 canonical
      authored 字段逐字段语义一致；已有 Event 只读取 actor 原本有权读取的 event-local、单页有界公共 history projection。
- [ ] packet 遵守 M3-A1 与 Plan 055 allowlist：最多使用合同允许的 prior publication 数量和 body-free evidence summary；不读取 Fact observation
      正文，不把 Fact ID 值传入或暴露给 Critic，也不读取私有 transcript、隐藏 reasoning、全 Team State、无界历史、监督元数据、凭据或其他禁入
      内容。省略、不可得与 freshness 状态诚实表达。
- [ ] 原稿或第一次改稿得到 `PASS` 时，该稿只走一次现行 publish mutation；前两次 `REWRITE` 均不调用 mutation，并分别返回两个版本化、
      固定、有界且不同的反馈，反馈只回显最近一次被拒绝的 canonical title/summary/optional handoff。
- [ ] 第二次改稿仍调用 Critic，但无论 `PASS/REWRITE` 都只尝试提交该稿一次；有效最终 `REWRITE` 与“审核未完成”保持不同的 typed
      开发者状态。任何一次 typed contract/infrastructure failure 都停止本 cycle 后续审核并只尝试提交当前稿一次，且不能冒充业务 verdict。
- [ ] Harness 明确定义 publication cycle 身份和最多三次审核的计数/续接/清理语义；不同 actor、team instance、cycle 或并发调用不能串线。
      同一 cycle 不得在续接时切换 target kind，已有 Event 的 `event_id` 必须保持不变；被拒稿不进入 Team State committed map，最终成功 commit
      继续使用最终成功 tool attempt 自身的现行 request identity 语义，cycle identity 不替代它。续接不匹配时拒绝还是在无歧义条件下开启新 cycle，
      由实现冻结并测试。
- [ ] 未提交 attempt 的 exact replay 幂等：不重复调用 Critic、不增加 rewrite 次数，并返回与首次相同的固定反馈/结果；同 attempt identity 携带不同
      原始内容必须拒绝。另一个独立 publish 不能被误认成当前改稿，新 Event 的可改写 title 不能被单独当作 cycle identity。
- [ ] 已提交请求的精确 replay 在 Critic 之前返回原 committed outcome，不重新审核、不消费后来 Fact；同一 request identity 携带不同原始
      publish 内容仍按现行语义拒绝。并发重复最多产生一个 canonical commit，不能产生幽灵 Event/Version 或重复 evidence 消费。
- [ ] commit 前收到调用/turn 取消时，取消正在等待的 Critic 调用、零提交并清理 cycle；commit 已原子成功后的取消不回滚 Version。timeout、
      queue failure、取消和 store refusal 不遗留 cycle、容量占用或部分 Team State 写入。
- [ ] 最终提交继续由现行 store 重新检查参与者/权限、target、stale、request identity、validation、dedup 和 evidence window；Critic 等待期间
      不持有 Team State mutex，不 peek、预留或消费 publish evidence window。审核活动、前两次拒稿、取消和 store refusal 本身不推进 revision、
      wake、Root attention 或 evidence cursor；typed failure fallback 若由 store 成功 commit，则只由该次 commit 按现行语义正常推进和消费。
- [ ] 启用态的 review/cycle 通过现有开发者观测方式提供有界、body-free 的 typed 结果，至少能区分最终 `PASS`、最终 `REWRITE`、typed failure
      fallback、取消、store commit/refusal 与阻断式 rewrite 次数；配置/测试可确认关闭态，但关闭时不要求为每次 publish 新增 review event。状态不写入
      authored publication，不建立第二套 Team State、第二套 trace 或正文审计存储。模型可见的固定 rewrite tool response 是唯一允许由新增接入层回显
      最近 candidate 的位置；内部 error chain、developer log preview/metadata 不泄漏 candidate/context sentinel，不因该响应采用成功或可恢复错误编码而混淆。
- [ ] 使用 Plan 055 的受控 scorer 启动真实服务进程并经过正式 transport、协议、expected identity、typed client 和产品 handler，至少覆盖代表性的
      `PASS`、阻断式到最终非阻断 `REWRITE`、typed failure fallback 与取消产品路径；关闭态证明零请求。replay/different-content、权限/stale、
      并发和清理等完整矩阵可使用同一生产边界上的确定性 seam 分层验证，但不能取代正式进程产品 E2E。测试不依赖真实模型、Docker、外部 API 或
      脆弱的长 `sleep` 竞速。
- [ ] 只运行受影响 crate 的格式、lint、配置/生成物检查和定向测试；重型 Rust/Bazel 入口经共享构建锁与看门狗。结果明确区分受控服务产品
      流程、fake/单元检查和未运行的真实模型/性能证据，不运行全 workspace。
- [ ] 完成 diff/允许写集检查和一次独立验收；普通 finding 由执行者自主窄修并重跑相关门禁。最终只提交 Plan 057 worktree 本地分支并保持
      worktree 干净；不合并、不推送、不归档或重命名分支。

## 2. 范围

### 允许修改

- `multidev/` 内与 Publication Critic 产品接入直接相关的配置、packet projection/canonicalization、client 生命周期或注入边界、
  `team_publish` 前置 cycle、固定反馈、body-free 开发者观测和定向测试。
- 为保持职责清晰所需的 `multidev/` 小范围重构、新模块或专用能力；若 Plan 055 的 public client/packet API 暴露出真实接入缺陷，可做
  范围内窄修并补回归。
- 因实际依赖或配置变化必须同步的 `multidev/` Cargo/Bazel 清单、锁文件、配置 schema 和其他已有生成物。
- 本计划的“当前状态”和“关键决策记录”，以及完成实现与验收时的一份精炼 Plan 057 `agent_log`。
- 任务完成时精炼同步 `doc/WBS/multi-agent-trusted-evidence.md` 中 M3-B2b 的当前事实；只写当前状态和 WBS 交接，不堆叠执行流水。

本任务不预设 cycle state 必须位于 handler、session service、AgentControl 或独立 crate，也不预设工具输出采用 tagged union 还是现有可恢复
反馈机制、continuity builder 的具体模块、配置字段名或观测事件形状。执行者可结合 live code 选择更优方案，只需满足本计划冻结的产品行为、
边界与验收。

### 允许只读核对

- 根/`multidev/` 规则、README、当前 WBS、Plan 053/055、Publication Critic 产品合同、相关冻结研究/审计材料、Git 历史，以及本任务引用的
  tracked 源码和测试。
- 主工作区与其他 worktree 只用于 Git 状态、资源占用和冲突保护核对；Plan 056 的任务状态只读，不读取或复制其 ignored 私有运行资产。

### 不允许修改

- `mydev/`、`eval/`、`training/`、Plan 056 的 tracked/ignored 代码、身份、预算、结果、Docker/Harbor 资产或其他现场。
- M3-A2 数据/样本/评价/输入规模，M3-B1 训练链，真实 threshold/model identity，M3-C1 部署资格或 M3-C2 横评。
- Producer 自动改写、Root 职责、新 Agent-to-Agent 协议/调度、Team State 生命周期语义、第二套 Team State、第二套 trace、通用 supervisor、
  复杂鉴权、审计/可信体系或与接入无关的重构。为实现冻结 rewrite cycle 而对现有 `team_publish` 增加必要的反馈/续接表达不属于新 Agent 协议。
- 顶层 `doc/WBS.md`、`doc/WBS-COMPLETED.md` 及 056 文件。方向 3 子 WBS 只在 057 任务完成时精炼同步自身当前事实；顶层完成历史由用户批准的
  串行主线整合根据届时已闭合的 056 状态更新，本任务 worktree 不抢写并行共享状态。
- Docker、真实 API、真实本地模型、模型下载、训练/量化/转换、云资源、上传/发布、付费操作、宿主机或全局工具链配置、CI/PR、全 workspace
  门禁、合并、推送或分支归档。
- 其他工作树、来源不明的修改、历史结果/日志/审计快照和无关 README/WBS 内容。

### 不允许读取/查看

- `.env.local` 内容，以及项目外个人文件、凭据、密钥或私有数据。
- ignored 原始 trace/payload、真实 publication/transcript/reasoning 正文、Fact observation 正文、Plan 056 私有运行数据或任何模型权重。
- 其他 worktree 的未提交文件内容；仅可查看 Git 元数据和公开已提交文件以保护并行工作。

### Git-ignored 与主工作区边界

本任务正式交付物均应是 tracked 文件，**当前没有必须直接在主工作区完成的工作**。`.claude/worktrees/057-publication-critic-integration`
目录本身按仓库设计被 ignore，但其内部交付文件由 057 分支正常跟踪和提交。受控服务测试使用临时 loopback 端点和系统临时目录或 057
worktree 内的任务专用临时位置；构建输出留在 RONDO 项目根内受监控的 worktree target，不需要在主物理根物化业务资产。

若实施中发现必须写主工作区 ignored 区、读取 Plan 056 运行资产、修改项目外位置或依赖未授权真实服务，应先停止该动作并报告，不得自行扩张
授权。普通共享 Cargo 缓存不属于本任务清理对象；只回收本任务精确创建的临时服务进程、端点和临时文件，worktree target 由仓库既有资源入口管理。

## 3. 硬约束

以下约束具有强制性。它们只冻结必要产品与安全边界，不固定可替换的实现路线。

1. **上游产品合同不改写。** M3-A1 合同和 Plan 055 typed contract 是本任务的语义上游；完整 canonical candidate、公共/禁入输入、
   Evidence V1、两次重写、最终非阻断审核、typed failure fallback 和取消语义不得在接入层重新解释。发现真实冲突时请求产品决策。
2. **关闭态是真正旁路。** Critic 默认关闭；关闭时保留现有 model-visible `team_publish` schema/output，从当前解析直接进入现行 store 路径，不依赖
   服务可用性，不创建 packet、client call、cycle 或 review 状态，也不改变既有结果。启用必须使用显式 typed 有效配置；缺失或无效配置不能静默连接
   任意端点/identity。必要续接字段若存在，只能由启用态的工具合同暴露。
3. **先 canonical、后审核、最后仍由 store 提交。** packet 与拟提交字段必须共享同一 canonicalization 语义，不能审长原稿后让 store 写入
   不同截断稿；canonical 副本只供 packet/preparation，现行 store ledger 比较和最终提交仍接收原始 `PublishRequest`，不能把两个不同但 clamp 后相同的
   原始请求误判为 exact replay。Critic 等待在 store mutex 外，最终只调用一次现有 publish mutation，并接受其权限、stale、dedup、validation 与
   evidence 结果。实现可共享纯函数、typed prepared view 或采用其他等强方式，但不能另建第二个写路径。
4. **公共且有界的 packet。** 只从权威 session 和 permission-scoped event-local public read 构造 Plan 055 packet；不分页拼接全历史，
   不读取 Fact observation body，不把 Fact ID 值送入 Critic，也不读取任何私有/监督字段。context 的 revision、coverage、freshness 和 unavailable
   状态必须来自真实读取结果；不能仅凭 global revision 与 `based_on_revision` 的差值猜某个 Event 已 stale。
5. **cycle、attempt 与 request identity 正确。** Harness 自己约束原稿加两次改稿的上限，并把续接限制在同一 team instance/actor/cycle 和 logical
   target；target kind 不能切换，已有 Event 的 `event_id` 不能变化。cycle identity 不能替代最终成功 tool attempt 的现行 request identity；未提交
   attempt 的 exact replay 不复审、不增加次数，同 attempt identity 不同原始内容拒绝，且不污染 store dedup。已 committed identity 的 exact replay
   或 different-content conflict 均在 Critic 之前返回现行 outcome/error。具体 token、key、cache、状态所有者与续接不匹配的无歧义处理由执行者决定并测试。
6. **verdict、failure 与 commit 正交。** 只有 Plan 055 合法 `PASS/REWRITE` 是业务 verdict。只有 typed Critic client/service contract 或
   infrastructure failure 触发一次当前稿 fallback publish；Event 不存在/不可见、原生权限或 preparation/read 失败等 Team State error 保持原生拒绝，
   不能伪装成 Critic failure 后 fail-open。`Cancelled` 在 commit 前不 fallback，且在进入同步 commit 前重查。最终审核结果、此前阻断 rewrite 次数和
   store outcome 分开记录，不能用一个大枚举混淆。
7. **取消、并发与生命周期不留幽灵。** 调用/turn 取消必须传播到 typed client；commit 前取消零 mutation，commit 后不回滚。cycle 状态的生命周期
   必须绑定 turn/team instance，在成功、拒绝、failure、取消、turn/session 结束或 instance reset 后不可再被看见或复用；自然析构或显式清理由实现
   选择。并发不得越过 attempt 上限、重复 commit 或泄漏跨 actor 状态。
8. **Team State 不变量不让位。** 审核活动、被拒稿、等待、取消和 store refusal 本身不推进 revision、wake、Root attention 或 evidence cursor；
   Critic 不 peek/预留 evidence。审核故障只选择 fallback，不直接 mutation；fallback 或正常路径最终成功 commit 时，恰由该一次现行 store commit
   保持并产生 Event/Version 不可变性、revision、stale/wake/权限/生命周期和全部 evidence refs 语义。
9. **观测轻量且正文隔离。** 复用已有开发者观测面，只记录有界 typed metadata；cycle 状态、普通 log preview、错误链和新增测试输出不持久化或
   打印 candidate/context。固定 rewrite 反馈只能在 Producer 必须接收的模型可见响应中回显最近被拒 canonical candidate，不形成第二套 trace/storage。
10. **受控端到端证据。** 代表性的 `PASS`、完整 rewrite、failure fallback 与取消产品路径必须启动 Plan 055 实际服务进程并走正式 typed client；
    受控 scorer 只替换 backend。完整状态/竞态矩阵允许在同一生产接入边界使用确定性 seam 做更窄测试，但不得只靠 mock handler、直接构造 verdict
    或 service crate 测试冒充产品闭环；所有测试同时验证 packet 或 Team State 前后状态，且不宣称真实模型质量、threshold 或性能。
11. **并行资源与 Git 隔离。** Plan 056 Docker/Harbor 预检、正式 Docker run 或其他重型任务占用共享槽时，057 不运行 Cargo、Clippy、Bazel 或
    其他重型门禁；等待期间可继续只读、编辑和轻量检查。不得修改/清理 056 或来源不明现场。最终只提交 057 worktree，合并/推送/归档等待用户批准。
12. **普通问题自主收敛，原则边界才停。** 执行者应自行诊断并窄修普通编译、测试、lint、race、fixture、配置和局部 API 问题，按需要有界重跑；
    不因一次可修失败停工。只有产品合同冲突、必须越界、触发预期外高危/外部状态操作，或合理修复后仍无法满足原则性完成门时才暂停报告。

## 4. 软性建议

以下建议基于 `main@9c002bd` 的实时代码与 Plan 055 接口，不固定执行者的实现路线。执行者可依据 live code、测试和维护成本采用更优的等强方案，
并在关键决策记录中简要说明有实质影响的选择。

- `multidev/codex-rs/core/src/tools/handlers/team_tools/publish.rs` 已在 store 前拥有 async 边界、权威 session、target、submission 和 draft，适合保留为
  薄编排点；packet projection/cycle/observability 若有成组逻辑，优先放入职责清楚的小模块或专用 crate，避免继续膨胀 handler 或 `codex-core`。
- 可以在 `codex-team-state` 暴露最小的 canonicalization/只读 committed preflight/event projection 能力，也可以在不复制规则的前提下采用其他布局。
  读侧应保持 permission-scoped；写侧仍由 `publish()` 单一负责。若新增 API，只公开 B2b 真正需要的最小表面。
- continuity context 可从现有 event-specific `history()` 取最近的、确定性且不超过 Plan 055 `MAX_PRIOR_PUBLICATIONS` 的单页 window，再把 evidence refs
  投影为数量/省略状态而非 ID。具体取序、freshness 判定和 unavailable 映射应写成小而直接的合同测试，不必建设通用查询 DSL。
- 配置可作为 Multi/team-state 下的 typed 默认关闭子配置，并在 session/root-tree 生命周期中注入可替换的 Critic client/provider。生产接入不必拥有
  通用 daemon supervisor；受控测试可以复用 Plan 055 子进程启动方式，未来 M3-C1 只替换 backend/descriptor 即可。
- 本任务只要求清楚的 `off` 与启用审核行为，不需要增加 `shadow` 或其他研究模式。rewrite 的模型可见结果可以采用配置相关的 output/schema、现有可恢复
  反馈机制或其他与消费链兼容的方案；计划不偏好某种 wire。cycle 可使用 Harness mint 的 opaque continuation identity，也可采用其他不会靠 title/正文
  猜关联的机制。
- 已提交 replay 可由 Team State 提供只读 committed preflight，也可用能保持 store 单一权威的等强方式。并发相同未提交请求是否合并 Critic 调用属于实现选择；
  无论是否合并，最终最多一个 commit，且已 committed replay 必须零审核。
- 开发者观测优先使用现有 structured tracing/trace hook 或同职责 body-free 面，字段只需表达 mode、attempt/rewrite count、verdict/failure kind、取消和 commit
  outcome；不需要数据库、审计日志、签名链、长期 cycle 账本或 Team Lens 新状态模型。
- 测试宜分层：纯 projection/cycle 测试覆盖 packet 与状态机，Team State 回归覆盖 canonical/preflight/invariants，core 产品集成测试启动受控服务进程并检查
  handler 输出和最终 store。使用 barrier/channel 驱动取消和竞态，避免长 `sleep`。
- 若 core 集成测试需要启动 sibling `codex-publication-critic-service` binary，应明确补齐 Cargo 与 Bazel/runfiles 的测试接线，不能依赖 Plan 055 遗留的
  `target/debug` 产物；packet allowlist 用 builder/序列化或专用测试 peer 检查，不要求正式 service 记录 request body。
- 门禁按实际改动收敛。通常包括相关配置/schema 测试、`codex-team-state`、`codex-publication-critic`（若有修改）和新增 `codex-core` 产品接入测试，随后对
  受影响 crate 执行 Clippy/fix、argument-comment lint 与 `just fmt`。若改变 Cargo/Bazel 接线或 config schema，使用仓库既有生成命令更新并审查；不为
  “更放心”运行全 workspace。
- 独立验收聚焦 off 旁路、packet allowlist/canonical equality、三次审核状态机、replay/cancel/concurrency、Team State 零副作用、body-free 观测和允许写集。
  普通 finding 窄修后只复验相关门禁，不建设额外审查平台。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已确认规划基线为 clean `main@9c002bd898e0f62fcdae521c5ba9b8cddd760a08`，与 `origin/main` 一致；Plan 055 已在该基线完成主线整合。
- 已从该基线创建 `.claude/worktrees/057-publication-critic-integration`，分支 `worktree-057-publication-critic-integration`。
- 已核对根/`multidev/` AGENTS、README、顶层/方向 3 WBS、plan 模板、Plan 053/055、M3-A1 产品合同、Plan 055 实现与最终验收日志、冻结研究材料，
  以及现行 `team_publish`、Team State canonical mutation/history/evidence 和 Plan 055 packet/client 接口。
- 已确认 Plan 056 worktree 当前 clean 于 `da68b34`，且 057 的 tracked 交付不需要读取或修改其现场；重型门禁仍须等待 056 Docker/Harbor campaign 释放
  共享资源。
- 已确认本任务可完全在 057 worktree 用 tracked 代码、临时 loopback 受控服务和定向 Rust 测试完成；当前没有必须直接写主工作区 ignored 区的事项。
- 已由两个只读子智能体分别按 live source/Team State 调用链和模板/产品合同独立复核草稿；已据此修正 failure fallback 副作用、raw request replay、
  attempt 幂等、native error/freshness、测试分层和并行文档边界。该复核只验收规划，不替代实现后的独立验收。
- 已冻结本 ExecPlan；模块布局、cycle owner、输出 wire、配置字段和观测事件的具体形状留给执行者结合实时实现自主选择。
- 已落地默认关闭的 typed Publication Critic 配置；关闭态注册原 `team_publish` schema/output 和同步发布路径，启用态才暴露 opaque
  `review_cycle_id`、构造 client/packet 并建立 turn-local review state。
- `codex-team-state` 已把原 publish validation/canonicalization 提取为共享只读 preparation，并提供同一 store view 下的
  `prepare_publish_with_history()`；packet 审核 canonical 副本，ledger 与最终 commit 仍接收原始 `PublishRequest`。
- 已实现最多三次审核、两个固定反馈版本、未提交 attempt replay、committed replay 前置、typed failure fallback、取消清理及同步 commit
  前重查；cycle 由 turn extension owner 串行化并绑定 team instance、actor 与 target。
- continuity 只投影 actor 可读的 event-local 单页 history，Evidence V1 只保留数量/省略状态；通用 tool runtime 增加 body-redaction 能力，
  reviewed publish 的 initial/completion trace、hook 和 log 不持久化 candidate/context body。
- 已建立 7 条启动 Plan 055 正式服务二进制的产品进程测试，覆盖 off、PASS/committed replay、并发 exact replay、完整 rewrite、failure
  fallback、rewrite 后 failure 与取消；另有 Team State、packet、配置、注册表、trace 和路由分层回归。
- 已在本地提交实现 `f5d538a744507c3f80391f0094389bb8b0a8e192`，并由一个干净上下文独立审查者核对规划基线至该提交的全部
  diff、生产调用链、测试和允许写集；审查结论为 PASS，无普通 finding 或阻断问题。

### 当前工作

Plan 057 实现、定向门禁、清理、本地提交和干净上下文独立验收均已完成；本节与方向 3 子 WBS 已写入最终状态。没有剩余产品实现工作，
后续只等待用户另行批准主线整合。

### 本任务剩余步骤

无。Plan 057 已完成；真实 backend/model/threshold 资格、联合横评及主线整合只交接到方向 3 WBS 或等待用户另行批准，不在本计划继续维护。

### 阻塞项

无阻塞。参数注释 lint 的 Cargo 入口在进入源码检查前因仓库固定 `nightly-2025-09-18`（Rust 1.92）不满足现锁定
`sqlx 0.9.0` 的 Rust 1.94 要求而失败；Bazel 替代入口经共享看门狗分析 3 个受影响 target 10 分钟后仍未完成，已受控中断并精确回收。
该未完成门禁不冒充通过；其余定向测试、`-D warnings` Clippy、fix、格式、schema 与 Bazel lock 均已闭合。

### 当前验收状态

- 实施：产品代码和测试已落地；关闭旁路、canonical packet、cycle/replay/fallback/cancel、body-free 观测及正式服务进程接入均已覆盖。
- 测试：`codex-team-state --lib` 133 passed、1 既有 ignored；Publication Critic core 组 11/11 passed（其中正式服务进程 7/7）；
  配置/注册表/trace 聚焦组 7/7、Team route 8/8、`codex-features --lib` 34/34。服务进程均由测试回收。
- 静态/生成物：受影响 3 crate 的 Clippy `-D warnings` 与 `just fix` 通过；`just fmt`、`just fmt-check`、config schema 生成/fixture、
  Bazel module lock update/check 和 `git diff --check` 通过，module lock 无差异。argument-comment lint 未完成，原因见“阻塞项”。
- 未运行：Docker、真实 API、真实模型、本地推理、训练、量化/转换、云资源、全 workspace、CI、PR；没有真实模型质量、threshold 或性能结论。
- 独立验收：干净上下文审查者已审查 `9c002bd..f5d538a` 并 PASS，明确覆盖 off、canonical/raw、replay、三次审核、fallback、
  Team State fail-closed、取消/并发、continuity/body 隔离、开发者观测、正式服务产品测试、接线、文档和允许写集；无 finding。
- Git：实现提交为 `f5d538a744507c3f80391f0094389bb8b0a8e192`；最终状态文档另作本地收口提交，057 worktree 保持 clean。
  未合并、推送、rebase、归档或重命名；主工作区保持 clean，其他 worktree 未修改。

### 交接边界

- 本任务完成并通过独立验收后冻结本计划；真实 backend 部署与资格、最终 threshold/model identity、联合横评及更后工作只交接到方向 3 WBS，
  不在本计划继续规划。
- Plan 057 完成后只提交本地 worktree 分支。主线整合默认等待 Plan 056 campaign、资源、最终验收和文档状态闭合；rebase、权威 WBS/COMPLETED
  同步、合并、推送与分支归档必须等用户明确批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Critic 默认关闭；关闭态完全旁路 packet/client/cycle | 保持现行 `team_publish` 产品行为与零服务依赖 | 配置、handler、测试 | 已采纳 |
| 002 | M3-A1 产品合同与 Plan 055 typed contract 是接入语义上游 | 防止在 runtime 重谈 qualification、packet 或 failure 含义 | packet、cycle、client | 已采纳 |
| 003 | Critic 审核 canonical candidate，最终 store 仍是唯一 mutation 权威 | 避免审写语义漂移及第二条 Team State 写路径 | canonicalization、store、handler | 已采纳 |
| 004 | 最多两次阻断式重写；第二次改稿审核非阻断，typed failure fail-open，取消 fail-closed | 落实已冻结产品 cycle 且避免无限重试 | cycle、反馈、取消 | 已采纳 |
| 005 | 已 committed replay 在 Critic 前返回，同 identity 不同原始内容仍拒绝 | 保持现有幂等与冲突语义，避免重放重复推理 | request identity、Team State | 已采纳 |
| 006 | continuity 只来自 actor 可读的 event-local 单页有界公共投影，Evidence V1 不读 observation 正文、不向 Critic 传 Fact ID | 保持权限、隐私和输入上限 | projection、packet、测试 | 已采纳 |
| 007 | review/cycle 开发者状态 body-free 并复用现有观测面 | 满足诊断需要而不建立第二套状态或 trace | logging、trace、测试 | 已采纳 |
| 008 | 实现布局、cycle owner、反馈 wire 和具体观测字段由执行者自主选择 | 计划只冻结外部行为，保留更优架构选择空间 | 全实现 | 已采纳 |
| 009 | 只用受控 scorer 的真实服务进程验收产品流程，不运行或宣称真实模型能力 | B2b 验证接入正确性，模型资格属于后续工作包 | 测试、结论 | 已采纳 |
| 010 | 057 与 056 隔离并共享重型槽串行；只提交 worktree | 保护并行 campaign 与用户的最终集成批准权 | 资源、Git、文档 | 已采纳 |
| 011 | Team State 提供共享 canonical preparation，并在同一只读 store view 返回目标 Event 的有界 history | 避免复制 clamp/权限/stale 规则及 preparation/history 竞态，同时保持最终 `publish()` 唯一写路径 | team-state、packet、replay | 已采纳 |
| 012 | cycle state 由 turn extension owner 持有，使用 owned async mutex 串行审核 attempt | 绑定 turn 生命周期并阻止并发复审/重复 commit；不跨 await 持有 Team State 锁 | cycle、并发、取消 | 已采纳 |
| 013 | reviewed runtime 显式声明 body redaction，通用 dispatch/trace/hook 只记录 handler 提供的安全 metadata | 复用现有观测面且避免 candidate/context 进入普通日志或第二套 trace | registry、trace、观测 | 已采纳 |
| 014 | 配置关闭注册原始工具合同，配置开启才注册 reviewed schema/output | 使关闭态 model-visible 行为和解析严格保持原样，同时只在启用态提供必要 continuation | 配置、spec、handler | 已采纳 |
