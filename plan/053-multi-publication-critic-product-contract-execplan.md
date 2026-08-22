# Plan 053：M3-A1 Publication Critic 产品合同与质量边界 ExecPlan

> 本计划是 M3-A1 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通文档矛盾、边界例缺口、链接或格式问题可在范围内自主窄修并有界复核。
> 本计划只描述 M3-A1；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 `main@ea03202ba838f3d6ba4a2061b76b9f3fdbf73c66` 的现行 RONDO Multi 产品事实之上，形成一份精炼、稳定、可由
训练链和产品链共同消费的 Publication Critic 产品合同。合同只冻结 M3-A1 必须关闭的产品语义：被审 publication、最小公共
输入及禁入边界、统一 qualification 原则、`PASS/REWRITE` 与软偏好的分界、两次重写和最终发布语义、服务故障/取消语义，
以及 Producer、Critic、Harness、Root 的职责。

本任务不实现 Critic，不设计数据设施或本地服务，也不重新评价 Plan 050。研究材料只作为候选与事实索引；只有与现行源码、
WBS 和完成证据一致且在本任务中明确采纳的内容，才进入稳定产品合同。

### 完成/验收标准

- [ ] 新增 `doc/rondo-multi-publication-critic-product-contract.md`，开头明确其权威范围、适用版本、与 WBS/研究材料的关系，
      并把“现行已实现事实”“M3-A1 新冻结语义”“仍留给后续任务的工程选择”清楚分开。
- [ ] 合同明确 Critic 审查的是与最终提交语义一致的**完整 publication candidate**，不是只审 `handoff`；新 Event 与已有
      Event 都包含完成 qualification 所需的最小公共语义，同时不把私有上下文或无界历史带入。
- [ ] 最小公共输入按语义字段和缺失/省略边界定义清楚。至少关闭：新/已有 Event 的局部 scope、candidate 的
      title/summary/handoff 语义、已有 Event 所需的有界公共上下文语义（若不需要历史也须明确）、上下文省略或陈旧时如何
      诚实表达，以及 Evidence V1 到底允许何种非正文语义。精确 API、JSON schema、序列化形态、历史条数、token/字符上限
      留给后续任务。
- [ ] 合同明确禁止 Producer/sibling 私有 transcript、隐藏推理、全 Team State、整个仓库、无界 Event history、原始 trace、
      原始 evidence/Fact observation 正文及监督标签或生成/审查元数据进入 Critic 输入；V1 不验证 Fact 真伪、时效或
      claim→Fact 语义蕴含。
- [ ] 同一组最低质量原则适用于新 Event、已有 Event、已完成事项和未完成事项：能传递有用状态、诚实保留不确定性、在确有
      未完成工作时可接续、不过度被过程噪声淹没、packet 内部不矛盾。已完成事项不因没有 handoff/下一步而被错误拒绝。
- [ ] 决定 `PASS/REWRITE` 的最低质量要求与只在合格内容之间优化的软偏好明确分层。稍长但完整可靠的 candidate 可 PASS；
      更短或更“漂亮”不能弥补状态缺失、确定性越级、不可接续或关键内部冲突。
- [ ] 重写状态机语义无歧义：原稿和第一次改稿若 `REWRITE`，各提供一次 Producer 自主重写机会；第二次改稿接受最终非阻断
      审查，随后无论 `PASS/REWRITE` 都只发布最终稿。反馈由 Harness 提供有界、不同的固定提示并只回显最近一次被拒绝的
      candidate；Critic 不自动改写或生成长篇自由文本理由。
- [ ] 服务超时、不可用或输出无效时继续发布并诚实区分“审核未完成”；重写机会耗尽且最终仍 `REWRITE` 时继续发布并区分
      “审核完成但未通过”；Producer/turn 取消则不提交、不推进 canonical 状态且不留下重写 cycle 残留。
- [ ] Producer、Critic、Harness、Root 的职责边界明确，Critic 不决定是否值得发布、事实真伪、route、spawn、分工、
      Root resolve/retire 或最终任务结论，Harness 也不代替 Producer 写 publication。
- [ ] 新 Event/已有 Event × 已完成/未完成四类 publication 各有至少一组紧凑边界例，例子能说明临界 `PASS/REWRITE`
      差异及所依据的 hard requirement；例子不是训练集、性能证据或固定文风模板。
- [ ] 合同逐项说明现行 Team State 不变量不被改变：被阻断的 draft 不创建 Event/Version，不推进 revision/wake 或消费
      evidence window；最终实际发布仍只提交一个不可变 Version，并继续遵守现有权限、stale、retry/dedup、生命周期与
      Root attention 语义。这里冻结结果语义，不指定未来 hook 或缓存实现。
- [ ] M3-A2 与 M3-B2a 的交接分别明确：两者可以依赖同一产品合同独立开始，不需重新讨论 Publication Critic 的基本产品
      语义；仍需各自在自身计划中冻结的 schema、数据/评价细节、服务协议和数值参数没有被 M3-A1 越俎代庖。
- [ ] Plan 050 只作为三任务条件性历史事实和现行资产边界使用；不重新评价其结果，也不把三任务案例外推为 Publication
      Critic 效果、一般协作质量或性能收益证据。
- [ ] `doc/WBS/multi-agent-trusted-evidence.md` 精炼链接产品合同并把 M3-A1 状态与交接写成当前事实；不复制整份合同或执行
      历史。并行期间不修改顶层 `doc/WBS.md` 或 `doc/WBS-COMPLETED.md`。
- [ ] 完成精炼 `agent_log/2026-08-22-014140-plan053-m3-a1-product-contract.md`，只记录事实收口、主要取舍、验证与未运行项。
- [ ] 至少一次由独立审查者完成的聚焦复核，覆盖合同内部一致性、四类边界例、现行 Team State 不变量和两条下游交接。
      范围内 finding 可由执行者自主窄修并复核，不因第一次普通文档问题立即停工。
- [ ] 文档链接、引用、格式、禁入词/范围与 diff 检查通过；不需要 Cargo、Docker、模型、API 或全量测试。
- [ ] 执行者审查工作树、主工作区和其他 worktree 状态后，只提交 053 本地工作树分支并保持干净；不合并、不推送、不归档
      或重命名分支。合并与推送必须等待用户批准。

## 2. 范围

### 允许修改

- `doc/rondo-multi-publication-critic-product-contract.md`：M3-A1 的稳定产品合同和少量代表性边界例。
- `doc/WBS/multi-agent-trusted-evidence.md`：只做方向 3 内 M3-A1 状态、合同链接和下游交接的精炼同步。
- 本计划的“当前状态”和“关键决策记录”。
- `agent_log/2026-08-22-014140-plan053-m3-a1-product-contract.md`；执行阶段在同一精炼日志中补充实质结果和必要整改，不堆叠多份流水账。

如果执行者判断另一份同样精炼、职责更清晰的方向 3 合同路径明显更优，可在不落入 `doc/research/`、`doc/WBS/` 或
`plan/` 的前提下自主选择，并同步本计划当前状态和 WBS 链接；不得把产品合同拆成多套互相竞争的权威文件。

### 允许只读核对

- 根/`multidev/` 规则、README、当前 WBS、Plan 047—050、完成证据、两份 2026-08-21 Publication Critic 研究材料，
  以及与 `team_publish`、Team State、history/evidence、Team Lens/Plan 050 边界直接相关的现行源码和测试。
- 为复核引用准确性，可只读使用 Git 历史和现有 tracked fixture；不得借此重新评价旧任务或扩大成新研究。

### 不允许修改

- `multidev/`、`mydev/`、`eval/`、`training/`、`justfile`、`scripts/`、锁文件、产品配置或任何产品/测试行为。
- `doc/WBS.md`、`doc/WBS-COMPLETED.md`、方向 0/1/2 子 WBS、README、两份冻结研究材料、Plan 047—052、历史日志/审计快照。
- Plan 052 工作树、分支、未提交内容或其涉及的 Local、共享 `eval/`、Team Lens 和顶层 WBS 写集。
- 数据集、评价设施、模型服务、`team_publish` 接入、训练/部署工件、runtime trace 扩展或新的审计/可信设施。

### 不允许读取/查看

- `.env.local` 的内容，以及任何项目外个人文件、凭据、密钥或私有数据。
- Plan 050 ignored 原始 trace/payload、任务 workspace、publication 正文、Fact observation 正文或其他 ignored 私密运行资产。
- 其他工作树未提交内容。只允许用 `git status`/`git worktree list` 等元数据保护并行状态，不进入其文件读取设计。

### Git-ignored 与主工作区边界

M3-A1 的合同可以只依据 tracked 源码、测试、WBS、完成证据和研究材料完成，**没有必须直接在主工作区写入的工作**。
worktree 不复制的 Plan 050 ignored 原始资产既不需要也不得展开。本任务预计不物化共享 `eval/.venv`、`eval-data/uv-cache`
或其他 common-root ignored 状态；如果执行者发现确有必要，说明任务范围判断已变化，应先停止该动作并向用户说明，而不是
直接写主工作区。

## 3. 硬约束

以下约束具有强制性。不得为了缩短文档、迎合研究稿或快速完成而违反。

1. **事实、历史与候选分层**：现行源码/WBS/完成证据优先于研究材料。研究中的实现、训练和部署建议只能标为候选或下游待定；
   Plan 048/050 的 tracked body-free 产物只证明既有边界，不能还原正文、转成训练/benchmark，Plan 050 三任务也不得外推为
   一般性能或 Critic 效果证据。
2. **只冻结完整产品语义**：Critic 审查与最终拟提交 authored publication 语义一致的完整 candidate，不得只看 handoff 或
   “审 A 写 B”。本任务不得冻结 API/JSON schema、模块布局、wire shape、历史条数、token/字符上限、队列/超时数值、
   score/threshold、训练参数、依赖、模型 revision、工件或部署格式。
3. **公共且有界**：最小输入只能来自权威身份和 permission-scoped 公共 Team State；禁止私有 transcript/reasoning、sibling
   内容、无界 history、raw evidence/trace/repository。上下文缺失、省略或陈旧必须诚实显式，不能补造完整性。
4. **统一质量门槛**：四类 publication 使用同一 hard requirements；只有 continuation 随“工作确实未完成”条件化。篇幅、
   文风、是否含 handoff/evidence 等软偏好或表面特征不得成为隐藏门槛。
5. **质量 gate 与角色不越界**：Producer 拥有 publication 语义和重写，Harness 只执行有界协议，Critic 只判 qualification，
   Root 保持协调职责。前两次 `REWRITE` 可阻断 draft，最终审查非阻断；服务/合同故障继续发布且不能冒充业务判定，取消不发布。
   不得引入自动改写、事实验证、调度/route 决策或第二套 Team State/trace。
6. **保持现行 Team State 合同**：不得静默改变 Event/Version 身份、不可变 authored entry、双生命周期、权限/可见性、
   revision/stale、retry/dedup、wake、evidence window 或 Root attention 语义。若合同确实要求改变产品语义，应停止并请求用户决策。
7. **Plan 052 与 Git 隔离**：053 不进入、rebase、merge、修改或依赖 Plan 052 分支，不争写其共享写集。完成并通过独立复核后
   只提交 053 本地分支；不得合并 `main`、推送、关闭 worktree 或重命名分支，后续整合等待用户批准。
8. **适度验证与自主修复**：只做轻量文档、引用、边界例与一致性检查。普通矛盾、链接、格式或例子缺口由执行者窄修并重跑；
   不因一次可修失败停工，也不得删减验收或改变语义凑绿。只有原则性冲突、越界需求或合理窄修后仍无法收口时才暂停。
9. **外部与资源禁区**：本任务不授权 Cargo、Docker、真实 API、本地模型、模型/package 下载、RunPod、训练、数据外发、付费、
   全 workspace、CI/PR、宿主机/全局配置或远端状态变更。

## 4. 软性建议

以下建议基于 `main@ea03202` 的现行材料，不固定执行者的写作结构或产品判断。执行者可以采用更简洁、更一致的等强方案，
并在关键决策记录中说明有实质影响的偏离。

- 产品合同宜控制为一份可直接阅读的短文，采用“适用范围 → 被审对象与最小输入 → hard/soft rubric → 重写/失败语义 →
  角色与 Team State 不变量 → 四类例子 → 下游交接”的顺序；无需复制长程 WBS、研究报告或源码取证表。
- 优先复用职责和边界相符的现有设施；如果强行复用会造成语义扭曲、跨层耦合或长期维护负担，可以新建必要的专用模块、
  接口或设施。新增设计应与现有 Team State、产品分层和生命周期契合，避免形成重复的平行体系；不以改动最少为目标，
  也不预建没有现实需求的重型能力。
- 最小输入可优先选择真正共同且稳定的语义。已有 Event 若需要历史，应描述“有界、event-local、permission-scoped、显式
  omission/stale”的公共 projection 责任；不要在 M3-A1 猜具体 N、token cap 或序列化结构。Evidence V1 优先保持
  body-free，避免把 Fact ID/数量误写成 claim 获证。
- 边界例宜按四类各给一个 `PASS` 与一个只改变关键缺陷的 `REWRITE`，并用一句话指出 hard requirement；内容使用明显合成的
  短例，不模仿 Plan 050 原始正文，也不扩张成数据集。
- 软偏好保持很少：直接、少重复、信息密度较高即可。不要把固定长度、正式文风、必须 handoff、必须 evidence、必须行动项或
  “越短越好”变成 qualification 门槛。
- 独立审查可交给一个干净上下文的子智能体，输入本计划、合同、方向 3 WBS 和必要源码/测试事实，要求只报可复现的内部矛盾、
  四类覆盖、Team State 不变量和下游共同语义遗漏。执行者核实 finding 后自主窄修；通常一次修后复核即可，必要时再做一次，
  不建立多评审委员会或审计流水线。
- 建议的轻量检查包括：`git diff --check`、Markdown 链接/路径存在性、关键术语与禁区 `rg`、四类例子和下游交接的人工清单
  对照。M3-A1 没有代码变更，不为文档任务运行 Cargo 或扩大测试。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已从 `main@ea03202ba838f3d6ba4a2061b76b9f3fdbf73c66` 创建
  `.claude/worktrees/053-multi-publication-critic-contract` / `worktree-053-multi-publication-critic-contract`。
- 规划时主工作区 tracked clean，`main@ea03202` 比 `origin/main@607cba0` 超前一个提交；Plan 052 工作树独立存在并仍在整改。
- 已核对根/`multidev/` 规则、README、当前 WBS、Plan 047—050 与完成证据、两份 Publication Critic 研究材料，以及
  `team_publish`、Team State publish/history/evidence 和相关测试的现行实现。
- 已确认 M3-A1 可只用 tracked 事实完成；不需要读取 Plan 050 ignored 原始 trace，也没有必须直接写主工作区的事项。
- 已冻结本执行合同并初始化精炼任务日志。
- 执行阶段已重新核对 Plan 047—050 完成证据、两份 Publication Critic 研究材料，以及现行 `team_publish`、history、
  evidence、retry/dedup、revision/wake、权限与生命周期源码和定向测试。
- 已形成 `doc/rondo-multi-publication-critic-product-contract.md` 初稿，覆盖完整 canonical candidate、最小公共输入、
  Evidence V1、hard/soft qualification、两次重写/故障/取消、角色职责、Team State 不变量和四类边界例。
- 已精炼同步方向 3 子 WBS 的 M3-A1 状态、合同链接和 M3-A2/M3-B2a 交接；未修改顶层 WBS 或其他并行写集。
- 聚焦独立审查确认主体 Team State 不变量与下游交接成立，并提出 4 项真实 finding：两个边界例的隐性 evidence/handoff
  门槛、fallback 的 commit outcome 表述，以及执行期 Plan/WBS 状态同步。四项均已窄修；同一审查者终验全部 staged
  交付为 `PASS`，确认四项全部关闭且没有新的 correctness/functionality finding。
- 已完成相对链接存在性、四类例子计数、关键术语、允许写集、`git diff --cached --check`、主工作区/Plan 052 元数据和
  worktree 状态检查；暂存区只含本计划允许的四个路径。

### 当前工作

- M3-A1 产品合同、WBS/Plan/日志同步、轻量检查和独立验收均已完成；本计划随 053 本地提交冻结。

### 本任务剩余步骤

- 本任务内无剩余实现或验证步骤；完成 053 本地提交并确认工作树干净后停止。

### 阻塞项

- 当前无阻塞。Plan 052 并行进行不是内容工作的阻塞项；它只阻止 053 争写共享顶层 WBS或自行进入主线整合。

### 当前验收状态

- 验收通过，任务目标完成。唯一的干净上下文独立审查者确认 4 项 finding 全部关闭，合同、四类例子、Team State 不变量、
  两条下游交接及允许写集均无剩余 correctness/functionality 问题。

### 交接边界

- M3-A1 完成后冻结本计划。下游顺序与当前状态只链接 `doc/WBS.md` 与
  `doc/WBS/multi-agent-trusted-evidence.md`，不在产品合同、计划或日志中复制后续路线。
- 053 工作树通过审查并本地提交后即停止。Plan 052 先完成整改与主线整合；随后顶层 WBS 的并行工作包表述、053 合并、推送
  与完成分支归档由用户批准的整合批次处理，不能由本次执行授权推定。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | M3-A1 只冻结产品语义，不冻结 API/schema、模块布局或数值参数 | 让训练链与产品链共享稳定含义，同时保留下游按实测选择实现的空间 | 产品合同与交接 | 已采纳 |
| 002 | 产品合同作为独立精炼文档，研究材料保持日期冻结的候选/证据 | 研究稿混有模型、训练和实现候选，不能直接冒充稳定产品合同 | 文档权威边界 | 已采纳 |
| 003 | 四类 publication 共用一套 hard requirements，只对未完成事项条件化 continuation | 避免 Event 类型、终态或 handoff 形态形成隐性不同门槛 | qualification | 已采纳 |
| 004 | Plan 050 原始 ignored trace 不进入 M3-A1 | tracked 事实足以冻结产品语义；展开原始正文会越过本任务数据边界 | 读取边界 | 已采纳 |
| 005 | Plan 052 并行期间 053 不写共享顶层 WBS；工作树完成后只本地提交 | 避免两任务争写权威文档，并遵守用户对合并/推送另行批准的要求 | 并行与 Git 交付 | 已采纳 |
| 006 | 普通文档 finding 允许范围内自主窄修并有界复核 | 一次可修的矛盾或例子缺口不应中断任务，原则语义边界仍需用户决定 | 审查流程 | 已采纳 |
| 007 | 复用以职责边界相符为前提；必要时允许新建架构契合的专用能力 | 避免“为了轻而轻”或为复用扭曲设计，同时不建设重复、无现实需求的重型体系 | 下游设计与验收取向 | 已采纳 |
| 008 | 已有 Event 必须带有界 continuity envelope，但 prior authored text 可诚实为空或省略 | 同时给增量 publication 局部语境并避免冻结历史条数、无界抓取或把缺失上下文冒充完整 | 最小公共输入 | 已采纳 |
| 009 | Evidence V1 只给 policy marker 和 prior public Version 的 body-free 引用存在/省略语义，不给 Fact ID、locator、类别或正文 | 当前 candidate 的最终 evidence window 只在 commit 时确定；最小语义足以约束确定性用词且避免伪 grounding | Evidence V1 | 已采纳 |
| 010 | 任一审查点发生服务/合同故障都停止继续审核并把当前稿送入现行发布路径；审核状态与最终 commit outcome 正交 | Critic 是质量优化而非安全门，且故障不能伪装成业务 verdict 或 store 已提交 | fallback | 已采纳 |
| 011 | 用户指定的同一名干净上下文聚焦审查者同时承担合同复核和全部工作终验，不再启动第二名审查者 | 满足一次独立上下文审查与修复后复验闭环，避免重复评审 | 审查流程 | 已采纳 |
