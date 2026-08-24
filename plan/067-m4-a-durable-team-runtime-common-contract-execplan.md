# Plan 067：M4-A Durable Team Runtime 共同合同与实施决策 ExecPlan

> 本计划是 M4-A 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通引用、文档矛盾、边界例或审查 finding
> 可以在范围内自主窄修并有界复核。
> 本计划只描述 M4-A；后续工作包、顺序与条件依赖以 `doc/WBS.md`、
> `doc/WBS/multi-agent-trusted-evidence.md` 和 `doc/WBS/durable-team-runtime.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 `main@273042f3f26d8f9a22d774fa72858ebf413c122e` 的 RONDO Multi、冻结 Codex CLI `v0.147.0` 与现行
`doc/WBS/durable-team-runtime.md`，在该第四期 WBS 内收敛一份 S/C/W 子线可共同消费的 M4-A 产品合同。合同必须关闭身份、生命周期、单一写
authority、耐久成功、自洽读取、失败责任、在线/冷态控制、启用组合、现有设施责任级复用判断及四项上游候选增量的决策；同时把
存储、锁、API、模块和测试实现细节留给对应下游工作包。

任务结束只允许以下结论之一：

- `M4_A_GO`：共同边界已经闭合，至少存在一条与当前架构契合的合理路线；M4-S1、M4-C0、M4-W0 按合同注明的条件依赖解锁。
- `REPLAN_REQUIRED`：即使允许合理的架构内扩展或专用能力，当前第四期宏观边界仍不存在满足共同合同的合理路线；必须明确冲突和
  需要调整的 WBS 边界，不能以未调查或普通实现困难代替该结论。

### 完成/验收标准

- [ ] 在 `doc/WBS/durable-team-runtime.md` 内形成单一、精炼的共同产品合同，并让它继续作为第四期当前合同、路线与依赖的唯一
      权威；不得另建一份长期 product-contract 文档与其竞争。
- [ ] 对关键 WBS 条目建立“已有保证 / 真实缺口 / 下游内部选择”事实矩阵，并给出可复核的现行源码、测试或冻结上游依据。
      详细事实、设施分级和上游对照写入一份日期冻结的
      `doc/audit-snapshots/2026-08-24-plan067-m4-a-durable-team-contract.md`；WBS 只保留决定与必要依据，不建设机器校验、可信或审计设施。
- [ ] 冻结 `SessionId`、canonical Root `ThreadId` 与 `TeamInstanceId` 的产品职责、V1 归属关系和生命周期；明确 Root/child、旧
      Session、顶层 fork 与 child spawn 分别如何关联三类身份。当前是否同值、转换方式和源码证据只作为冻结快照中的表示事实，
      WBS 不承诺永久同值、具体类型或字段布局。
- [ ] 用一张生命周期表关闭 resume/member reload、顶层 `thread/fork`、`spawn_agent fork_turns=none/all/N`、`/new`、slash
      `/clear`、纯 UI 清屏、detach/unsubscribe/断连、正常关闭、存活进程内 task/shutdown 失败、完整进程退出、archive、unarchive、
      delete 及缺失/损坏/不兼容旧状态的产品结果。表中不得留下由 S1/C0/W0 各自裁决的跨子线 TBD。
- [ ] 明确 canonical Root lineage 的单一 Team 写 authority 如何成为所有 Root/child Team mutation 的共同资格，且必须持续覆盖
      成功提交边界；child Thread 自身 writer、一次性资格检查、只读控制端或第二个进程均不能绕过 Root 归属成功写入。
- [ ] 明确 canonical mutation 的耐久成功、自洽已提交读取、允许的 stale/unknown/unavailable、关闭完成、关闭失败、部分失败与
      结果未知的责任边界。对不推进 Team revision 的独立状态轴也要给出等价产品结果，但不预定 read token、snapshot、事务或提交
      顺序。
- [ ] 明确在线 Team mutation 由已加载 owner runtime 的领域能力负责；archive/unarchive/delete 等冷态 Root 生命周期由原生权威
      生命周期路径负责。活跃 authority 冲突、owner 未连接、部分成功或无法确认结果时必须有诚实结果，不建设跨进程 mutation
      relay、queue、强制接管或补偿事务平台。
- [ ] 对 lineage/authority 无法证明、持久标记与后端不一致、数据缺失/损坏/版本不兼容、旧 Team 引用跨实例等情况形成明确的
      fail-closed、只读降级或 unavailable/unsupported 语义；不得静默创建空 Team、重铸旧 ID 或退回另一份状态源。
- [ ] 给出 Durable Session、Session 控制面、MultiAgentV2、Team State 与可选 W 线的有效启用矩阵：说明依赖、合法独立关闭态、
      默认关闭行为、非法组合及已有 durable 数据的只读可见性。具体配置 key、解析顺序和内部子开关留给下游。
- [ ] 对至少 ThreadStore active-writer、Session/thread lineage、V2 Agent graph/residency、Team State、app-server v2/TUI 生命周期能力、
      配置/feature gate、Git/worktree 观察原语逐项给出“直接复用 / 架构内扩展 / 新建专用能力 / 当前不可行”的责任级结论；不得为
      追求复用扭曲语义，也不得形成第二套 Team State、writer authority、生命周期或控制体系。
- [ ] 对上游 `#37847`、`#37198`、`#39616`、`#39153` 分别记录实际增量、RONDO 缺口、采用/适配/条件延期/不采用结论、消费工作包
      与进入主线条件。任何选中项仍只是后续独立回移任务的输入，未进入主线不得冒充已满足前置；W 专属项不得阻塞 S/C。
- [ ] 若结论为 `M4_A_GO`，分别形成 M4-S1、M4-C0、M4-W0 可直接建立 ExecPlan 的交接：列出已冻结共同输入、各自 owner 的目标
      与失败边界，以及仍可自主选择的内部问题。C0 只接收可原型验证的实验语义，不提前承诺正式 RPC/TUI；W0 只接收价值原型
      输入，不提前给出 binding/handoff GO。
- [ ] 若结论为 `REPLAN_REQUIRED`，分别形成 S1/C0/W0 的阻塞交接：明确哪个共同合同无法满足、为何合理扩展或专用能力仍不足、
      需要调整哪项第四期宏观 WBS 边界；不得声称三个下游已解锁或可按当前边界建立 ExecPlan。
- [ ] `doc/WBS/durable-team-runtime.md` 直接承载稳定共同决定、M4-A 结论与下游交接，但不堆叠源码调查流水或执行历史；日期冻结快照
      只承载形成决定时的证据，不冒充当前规划。Plan 068 并行期间不修改 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`
      或 `doc/WBS-COMPLETED.md`。
- [ ] 完成一份精炼 `agent_log/2026-08-24-plan067-m4-a-common-contract.md`，只记录主要决定、必要源码依据、验证、审查整改及未运行项。
- [ ] 至少一次由未参与合同写作的独立审查者复核：共同合同与源码事实、WBS 一致性、S1/C0/W0 可实施性及是否存在跨子线 TBD。
      高/中等级 correctness finding 必须在范围内修复并由审查者复核关闭；普通问题允许自主修复和重跑，不因第一次可修失败停工。
- [ ] 文档链接、引用、关键术语、允许写集、`git diff --check` 和最终工作树状态检查通过；若未运行 Cargo 或其他验证，如实记录为
      未运行，不能表述为通过。
- [ ] 最终差异不包含产品/测试实现、上游回移、Plan 068 内容或其他下游产物；执行者只提交 067 本地分支并保持工作树干净，不
      合并、不推送、不关闭 worktree、不重命名分支。

## 2. 范围

### 允许修改

- `doc/WBS/durable-team-runtime.md`：第四期共同产品合同、M4-A 最终结论和 S1/C0/W0 交接的唯一当前权威。
- 本计划的“当前状态”和“关键决策记录”。
- `agent_log/2026-08-24-plan067-m4-a-common-contract.md`。
- `doc/audit-snapshots/2026-08-24-plan067-m4-a-durable-team-contract.md`：一份紧凑、日期冻结的源码事实、设施责任分级、上游
  对照与验证边界；不是新的规划或产品合同来源。

普通调研笔记和可丢弃验证放 `/tmp`，不提交临时产物。独立审查结果通常收敛进同一精炼日志；只有审查者需要保留不可合并的独立
日期冻结结论时，才允许在 `agent_log/` 增加一份终审日志，这是已预授权的唯一额外 tracked 路径。除此之外新增 tracked 文件或
扩大写集必须请求用户确认，不为每轮整改创建流水账。

### 允许只读核对

- 根/`multidev/` `AGENTS.md`、README、当前 WBS、Plan 038/043/047/048、Plan 065 日志与完成证据，以及与 Session/thread、
  MultiAgentV2、Team State、ThreadStore、app-server v2/TUI、feature/config、Git/worktree 直接相关的现行源码与测试。
- 主物理仓库 `/home/sjc/desktop/RONDO/codex-source-code/` 中冻结 `v0.147.0` 源码。该目录 git-ignored，不存在于 linked worktree，
  本任务只可从主仓路径读取、检索或执行只读 Git 查询，不在其中 checkout、fetch、编辑或生成文件。
- 仓库内冻结 Codex 文档、Git 历史，以及四项候选 PR 的上游 primary source；普通只读源码查询和网络访问已在本任务授权内。
- Plan 068 仅可通过 `git worktree list`、`git status --short`、分支/HEAD、进程/锁/资源计数等元数据确认 worktree、当前变更路径、
  用户已声明的预期写集和资源冲突；不得进入其文件读取未提交设计或把其结果作为 067 前置。

### 不允许修改

- `multidev/`、`mydev/`、`eval/`、`training/`、`codex-source-code/`、`codex-doc/`、`scripts/`、`justfile`、锁文件、生成 schema、
  产品配置、产品源码、测试或 fixture。
- `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md`、README、其他方向 WBS、冻结研究/审计快照、
  既有 plan 和历史日志。
- Plan 068 worktree/分支、其未提交内容及其 Publication Critic 模型、服务、部署、权重、测评或运行资产。
- S1、S2、C0、后续 C*、W0、W1、M4-Z 的生产代码、测试设施、正式 API/TUI、binding/handoff 原型，或任何实际上游回移。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、ignored 私有模型/测评正文、训练输出、权重，以及项目外个人文件或私有数据。
- Plan 068 或其他 worktree 的未提交文件内容；元数据检查不得扩展成 diff、show、文件读取或设计复用。

### Git-ignored 与主工作区边界

本任务所有 tracked 编辑都在 067 worktree 内完成。唯一预计需要直接访问主物理仓库的 ignored 资产是
`/home/sjc/desktop/RONDO/codex-source-code/`，用途仅为只读核对冻结上游源码；不需要直接修改主工作区或创建 ignored 运行资产。
共享 `.codex/` 构建锁状态只有在确需聚焦 Rust 验证时才通过仓库既有入口使用，不手工改锁或看门狗状态。若执行者发现必须在主
工作区写文件、修改 ignored 资产或读取私密运行数据才能闭合合同，说明范围判断已经变化，应停止该动作并向用户说明。

## 3. 硬约束

以下约束具有强制性。不得为了快速收口、迎合既有文档或通过审查而违反。

1. **指定基线与并行隔离**：所有产品判断以 `main@273042f3...` 和冻结 `v0.147.0` 为基线。Plan 068 只做元数据核对，不读取、
   修改、合并、rebase 或依赖其未提交内容；067 不争写其当前共享整合面。若其元数据写集意外扩展到 067 的合同或第四期 WBS，
   先停止冲突文件的编辑并请求用户协调，不凭内容猜测合并方案。
2. **共同产品结果必须闭合**：身份、生命周期、authority、耐久/读取/关闭、在线与冷态责任、失败/降级及启用组合不得作为跨子线
   TBD 下放。若证据支持多个等强机制，可冻结共同结果与 owner，把机制选择留给下游；不能用“实现时再看”替代产品决定。
3. **不越俎代庖**：M4-A 不冻结 crate/module、Rust API、wire schema、数据库/文件格式、字段、锁/permit/guard、read token、
   snapshot、事务、重试/调用顺序、分页、通知或测试 fixture。只有为说明职责所必需的接口形状可作为非约束性示意。
4. **单一权威与诚实结果**：Team State 仍是 canonical coordination 状态；Root lineage 写 authority 必须覆盖成功 Team commit，
   child 不得绕过。成功、关闭完成、部分失败、结果未知、自洽读取和降级不得被后台假设、UI 投影或第二份数据源伪造。
5. **优雅复用而不强行复用**：职责契合时直接复用；接近但不足时可架构内扩展；强行复用会扭曲语义时可新建专用能力。新增能力
   继续遵循现有配置、生命周期、错误、测试与观测方式，不建设相互竞争的第二套 Team State、writer authority、Session 生命周期、
   控制面状态源、trace 或通用平台。
6. **上游只决策不回移**：保持 `v0.147.0` 产品基线，`v0.149.1` 仅作对照。不得 checkout/升级/回移候选 PR 或把未合并实现写成
   当前保证；必要回移另建 ExecPlan，并按本合同注明的消费边进入主线。
7. **文档职责不漂移**：第四期 WBS 写稳定共同产品语义、当前状态、路线与依赖，日期冻结快照写形成决定时的证据，plan 只写本
   任务合同/状态，日志只记历史。不得在非 WBS 文档复制后续路线，也不得把日期冻结 evidence 冒充当前规划。
8. **适度验证与自主修复**：先做只读源码/测试对照和可丢弃窄验证。普通命令、引用、文档、边界例或审查问题由执行者修复后重跑；
   不因一次窄修可解决的问题停工，也不得删减验收或弱化语义凑绿。只有原则性边界冲突、授权外扩张或合理窄修后仍无法形成两种
   允许结论时才暂停。
9. **资源与外部禁区**：默认不运行 Cargo。确有必要的少量聚焦 Rust 验证必须经仓库共享 `scripts/with-build-lock.sh` 或接入它的
   `just` 配方，并服从根 `AGENTS.md` 的锁、cgroup、Windows `C:` 和与 Docker/真实本地模型互斥门禁；拿不到计数即 fail-closed。
   不授权 Docker、真实 API/模型、训练、性能测评、全 workspace、CI/PR、发布、上传、付费或其他远端状态变更。
10. **本地提交即停止**：提交前检查允许写集、diff、主工作区及 worktree 元数据。只提交
    `worktree-067-m4-a-durable-team-contract`，不合并 main、不推送、不关闭 worktree、不归档或重命名分支；main 若在并行期间
    前进，也不自行 rebase，后续由获批整合者基于最新 main 窄同步。

## 4. 软性建议

以下建议基于指定基线，只帮助执行者高效收敛，不固定写作结构或实现判断。执行者可采用更简洁、更契合现行架构的等强策略，并在
关键决策记录中说明有实质影响的偏离。

- 阶段 A 先把 WBS 条目映射到当前源码：三类身份与转换、AgentControl/registry/residency、TeamStateHandle/TeamStore、
  ThreadStore writer、thread manager、app-server lifecycle、feature gate。每条只标“保证/缺口/下游选择”，不要制作全仓 census。
- 阶段 B 可由三个有界只读子智能体分别调查身份/authority、生命周期/控制、上游增量/启用组合；只返回证据和候选判断，由一个
  集成者统一写合同。避免多个 Agent 并发改同一文档，也不需要评审委员会。
- WBS 中的共同合同可采用“身份关系 → 生命周期矩阵 → authority 与 durable/read/close 结果 → 在线/冷态责任 → 启用矩阵 →
  上游决策 → S1/C0/W0 交接”的紧凑结构；设施分级、较细源码位置和 PR 对照留在冻结快照，不逐行复制实现。
- 对现有 ThreadStore active-writer，重点判断它能否作为 canonical Root authority 的基础并持续覆盖 Team commit，而不是预先决定
  复用某个 guard 类型。对 SessionId/ThreadId 的同值转换，也要区分当前表示事实与稳定产品职责，避免把偶然类型布局升级为未来承诺。
- 启用矩阵优先表达用户可观察能力和关闭态，配置名字与内部拆分保持开放。控制面可否独立只读历史 durable Session、W 是否依赖
  控制面等问题必须作决定，但无需为此先设计 RPC，也无需机械枚举五类能力的完整笛卡尔积。
- 上游 PR 优先阅读 primary source 的 diff、测试与依赖链，再对照 `v0.147.0` 和 RONDO 现状。采用结论应解释由哪个工作包消费、
  何时必须进入 main，以及不用它时的当前路线；不要把“上游较新”当成采用理由。
- 独立审查只聚焦可复现的高/中等级 correctness：合同内部矛盾、源码误读、WBS 冲突、非法 feature 组合、跨子线 TBD 和无法实施的
  交接。审查后保留一次或少量窄修/复核余量，不建设审计清单、签名、可信证明或机器门禁。
- 静态源码、现有测试和上游 diff 足以支持结论时，不运行 Rust 构建。确需临时验证时从最小未证实接缝开始，保留已确认进度；合同
  全部打通后再从干净文档状态完成一次最终链接、引用、diff 和工作树复核，以该轮作为正式结果。

### 建议的阶段编排与退出条件

以下编排用于避免并行调研各自发明共同语义；它不限制每个阶段内部的检索顺序或文档表达。

**A. 基线与缺口确认**

- 核对 067 的指定 HEAD、主工作区与全部 worktree 元数据；Plan 068 只看 branch/HEAD/status 路径等元数据。
- 把 WBS 共同问题逐项标为“已有保证 / 真实共同缺口 / 明确下游 owner 的内部选择”。
- 退出条件：每项判断都有当前主线或冻结上游来源，不依赖任何未合并 worktree 内容；共享写集边界已确认。

**B. 三路有界只读调研**

- B1 关闭三类身份、Root/child lineage 与写 authority；B2 关闭生命周期、耐久/读取/关闭结果及在线/冷态 owner；B3 关闭启用组合、
  设施责任分级与四项上游候选。
- 退出条件：每路交付证据和候选决定，但不写共享文档；共同结果没有被机制细节替代，四项 PR 均有消费者和进入主线条件。

**C. 单一集成者收敛**

- 由一个集成者把稳定决定写入第四期 WBS，把源码事实、设施分级与 PR 对照写入日期冻结快照，并为每个保留开放项指定唯一
  下游 owner。
- 退出条件：没有 S1/C0/W0 需要重新共同裁决的 TBD；存在至少一条不扭曲架构且不重复建设权威体系的合理路线，否则已形成有
  证据的 `REPLAN_REQUIRED`。

**D. 交接、独立审查与冻结**

- GO 路径完成 S1/C0/W0 可开工交接；REPLAN 路径完成三者的阻塞交接和需调整的宏观边界。由未参与写作的审查者核对源码事实、
  共同合同、WBS 一致性和相应终局是否成立；普通 finding 自主修复并复核。
- 退出条件：高/中 correctness finding 已关闭，链接、引用、允许写集、diff 与工作树复核通过；最终结论、未运行项和本地提交均
  诚实记录。低等级非阻断建议可以如实保留，不要求零建议或多审查者共识。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已确认主工作区 tracked clean，`main` 与 `origin/main` 同在 `273042f3f26d8f9a22d774fa72858ebf413c122e`。
- 已从该提交创建 `.claude/worktrees/067-m4-a-durable-team-contract` / `worktree-067-m4-a-durable-team-contract`。
- 已完整阅读根 `AGENTS.md`、README、当前 WBS、`doc/WBS/durable-team-runtime.md`、`multidev/AGENTS.md`、Plan 模板与 Plan 065
  相关验收日志，并核对关键身份、Team State、ThreadStore、生命周期和 feature 源码入口。
- 已通过元数据确认 Plan 068 独立 worktree 起于同一提交；规划终检时其 status 路径元数据包含 `doc/WBS.md`、
  `doc/WBS/multi-agent-trusted-evidence.md`、`rondo.secrets.example.env` 与自身 plan。067 执行期不写这些路径；其中两个共享 WBS
  面留给后续获批整合批次基于最新 main 窄同步。
- 已确认 git-ignored `codex-source-code/` 不随 linked worktree 出现；冻结 `v0.147.0` 快照可从主物理仓库根只读核对，本任务不需要
  直接修改主工作区或创建 ignored 资产。
- 已冻结本 ExecPlan，并复核 Plan 038/043/047/048、Plan 065 验收记录、当前 Session/ThreadStore/V2/Team State/app-server/TUI/
  config/Git 源码与现有测试；冻结 `v0.147.0` 快照保持只读 clean。
- 已由四个只读子智能体分别完成 identity/authority、lifecycle/control、upstream candidates、history/enablement 调研；共享文档仅由
  主集成者编辑。
- 已核对四项官方上游 PR、exact head、diff、测试、依赖与 `rust-v0.149.1` 最终形状；未 fetch、checkout、回移或升级基线。
- 已在 `doc/WBS/durable-team-runtime.md` 形成三类身份、Root authority、durable/read/close、完整生命周期、启用组合、设施责任、
  四项上游决定及 S1/C0/W0 交接的最终 `M4_A_GO` 合同，并形成日期冻结证据快照。
- 干净上下文独立终审发现并关闭 1 个中等级 lifecycle finding：即时 detach 与零订阅 deferred idle unload 已分离，后者统一服从
  durable close barrier；复核者最终返回 `PASS`。
- 链接/术语/允许写集检查及完整 staged `git diff --cached --check` 已通过；差异精确限于四个授权路径。
- 外部独立验收报告对首个提交提出 M1 Root-close/live-child authority 缺口、M2 三期状态过期和 L1 当前工作停留在提交前；三项均已
  依据现行源码及已提交 `main` 确认为真实，并在本轮后续提交中完成最小整改。

### 当前工作

- 执行者侧合同整改、静态复核和本地提交均已完成；独立复审状态由后续审查报告拥有，本计划不复制维护其最终结论。

### 本任务剩余步骤

- 无执行者侧内容步骤；若独立复审提出新的真实 finding，再按同一窄修流程恢复任务。

### 阻塞项

- 当前无阻塞。Plan 068 的并行工作只限制 067 的共享 WBS 写集，不构成产品调研前置。

### 当前验收状态

- 首个提交未获外部独立验收；M1/M2/L1 已在本日志所在后续提交中修复，执行者侧轻量门禁通过。当前仍为 `M4_A_GO` 路线且不存在
  `REPLAN_REQUIRED` 阻塞；最终接受状态以独立复审报告为准。

### 交接边界

- M4-A 完成后冻结本计划。S1/C0/W0 的后续路线和条件依赖只链接 `doc/WBS/durable-team-runtime.md`，不在共同合同、plan 或日志中
  继续维护。
- 067 本地提交并独立验收后停止。合并、推送、共享 WBS/COMPLETED 的最新主线同步及完成分支归档必须等待用户批准的整合批次。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | M4-A 的稳定共同决定直接收敛进 `doc/WBS/durable-team-runtime.md`，证据另放一份日期冻结快照 | 该 WBS 已拥有第四期合同、路线与依赖；另建长期 product contract 会制造两份权威 | 文档权威 | 已采纳 |
| 002 | Plan 068 并行期间不修改顶层 WBS、方向 3 总 WBS或 COMPLETED | 元数据已确认 068 正在写前两者；避免共享整合面并发争写，完成历史留给获批整合批次 | 并行与 Git | 已采纳 |
| 003 | git-ignored `codex-source-code/` 只从主物理仓库根只读核对，所有 tracked 编辑留在 067 worktree | linked worktree 不复制该冻结快照，但本任务无需在主工作区产生任何写入 | 工作区边界 | 已采纳 |
| 004 | M4-A 只冻结职责与产品结果，不选择或实现下游机制 | 共同边界必须足以开工，同时存储、锁、API、模块和测试细节应由真实消费包决定 | 任务切分 | 已采纳 |
| 005 | 复用按职责契合判断；必要时允许架构内专用能力，但禁止重复体系 | 保持设计干净，避免为了改动少而扭曲语义，也避免预建平台 | 架构取向 | 已采纳 |
| 006 | 普通调研/文档/审查失败允许自主窄修和有界重跑，原则冲突才暂停 | 给执行者合理排错余量，不弱化产品和授权边界 | 执行流程 | 已采纳 |
| 007 | 默认只做静态与轻量验证；确需 Rust 验证时使用共享锁和资源看门狗 | M4-A 是合同任务，重型验证不是默认必要条件，但真实源码疑点可被窄验证 | 验证与资源 | 已采纳 |
| 008 | 067 只本地提交，不因 main 并行前进而自行 rebase、合并或推送 | 用户要求本地验收后再批准整合，且后整合者应基于最新 main 窄同步 | Git 交付 | 已采纳 |
| 009 | `SessionId`、canonical Root `ThreadId`、`TeamInstanceId` 分别拥有 lineage、生命周期/authority anchor、Team generation 职责；当前同值表示不升级为永久合同 | 现有身份足以复用，另建 Session 身份会重复体系；顶层 fork/new/clear 与 child spawn 的边界因此可无映射闭合 | 身份与 lifecycle | 已采纳 |
| 010 | 以现有 Root Thread active-writer 为唯一排他基础并做架构内扩展，使 authority 连续覆盖 Team durable commit；child writer 和一次性资格检查均不足 | 当前 Team 仅检查 participant 与进程内 mutex，直接复用不能证明跨进程 durable single writer，另建 Team lock 又会产生竞争权威 | authority 与 persistence | 已采纳 |
| 011 | Team State canonical 语义直接复用；新增与其集成的专用 durability/read 能力，并冻结 durable success、自洽 committed read、close barrier、partial/unknown/fail-closed 结果 | 当前 cold resume 会创建 fresh Team handle，且 shutdown/archive/delete 存在表面成功或部分结果，必须闭合但无需建设通用事务平台 | 耐久、读取与关闭 | 已采纳 |
| 012 | Durable writable 依赖有效 V2 + Team State + durable backend + Root authority；Control 可独立只读历史 durable 数据；W1 依赖 W0 GO + Durable/S1；全部新能力默认关闭 | 保留现有关闭态并允许有价值的 headless/read-only 组合，同时防止内存 Team 或孤立 binding 冒充 durable | 启用组合 | 已采纳 |
| 013 | `#37198`→S1 PASS、`#37847`→S2 PASS；`#39616` 仅在 W0 GO 且 W1 消费 trust 时于 W1 开始前适配；`#39153` 仅在 W0 GO 后按 fail-closed 权限语义适配并于采用它的 W1 PASS 前进入主线 | 四项都对应真实缺口，但消费者和产品语义不同；W-only 增量不得阻塞 S/C，permission fallback 不能破坏 durable binding | 上游候选与消费边 | 已采纳 |
| 014 | `M4_A_GO`，分别解锁 M4-S1、M4-C0、M4-W0 建立 ExecPlan；正式 W1 仍等待价值门与 S1 | 当前架构可通过窄专用能力和既有设施扩展闭合，不需要修改第四期宏观边界；验收状态以后续独立报告为准 | 最终方向 | 已采纳 |
| 015 | 任何 mutation-capable descendant 存活时，Root/Team close 不得完成或释放 authority；下游可阻止 close，或在同一 barrier 内安全 quiesce/close descendants | Team capability 由 root tree 共享，而 idle unload 按 ThreadId 独立发生；不闭合该边界会允许旧 child 与新 owner 重叠写入 | close 与 authority | 已采纳 |
| 016 | 第四期 WBS 只按已提交 main 同步三期当前事实：M3-B1c 已完成、计算 Pod 已删除且无活跃云训练；不读取 Plan 068 未提交内容 | 持续维护 WBS 不得保留已失效前置，也不能以并行 worktree 作为权威 | 当前路线与资源 | 已采纳 |
