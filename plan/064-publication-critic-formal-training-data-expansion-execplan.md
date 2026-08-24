# Plan 064：Publication Critic 正式训练数据扩充与冻结 ExecPlan

> 本计划是 Publication Critic 正式训练数据扩充任务的稳定合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通生成、格式、schema、复核、split、重复、token、manifest、consumer
> 和轻量测试问题应在范围内自主修复并按需重跑。
> 本计划只描述 Plan 064；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在不改变 Plan 059 `publication-critic-v7`、Plan 054 冻结输入合同或 Plan 060 smoke 输入的前提下，依据 v7 的真实覆盖缺口、正式训练用途、
可接受的数据质量和可获得的 Plan 060 吞吐/预算事实，扩充 Publication Critic 的场景、难度、表达与判定边界，形成一个具有新版本身份、可由
现有训练消费路径直接读取的正式数据版本。

任务不预先硬编码样本总数。执行者先把规模判断、覆盖目标和停止条件冻结为本任务的 data-design lock，再分批生成、复核和返修；达到覆盖、
质量、消费和预算适配条件即停止，不为数量本身继续扩充。最终结论为数据 `GO`、`NO-GO` 或“证据不足”。只有本任务经独立验收的数据 `GO`
与 Plan 060 经独立验收的训练资格 `GO` 同时成立后，WBS 才能把 M3-B1c 标为具备另行规划条件；本任务不启动训练。

任务按四个阶段推进：

1. **阶段 A——规模与覆盖基线。** 只读核对 v7 和可用的已提交/已交接 Plan 060 事实，形成覆盖缺口、保留集、规模判断方式、停止/NO-GO/
   证据不足条件及受限数据来源；不改 v7，也不等待 Plan 060 才开始能够独立完成的覆盖设计。
2. **阶段 B——分批扩充与复核。** 先用小批次打通生成、复核、finalize、split、token census 和 consumer，再按覆盖缺口分批扩大。普通窄问题
   自主修复和重跑；保留已经验证且未受语义变化影响的进度，不机械整批报废。
3. **阶段 C——冻结前审查与正式冻结。** 完成 freeze-ready 候选全集和必要机械门禁后，执行者必须先停下，以 clean checkpoint commit、候选资产
   和汇总报告申请计划制定者审查；未获明确批准不得生成或提交最终 freeze。批准后才进入本阶段的正式冻结子阶段，从已审集合和干净状态完整运行
   finalization/freeze。
4. **阶段 D——数据资格决策与交接。** 对最终新版本运行相称门禁，给出数据 `GO`、`NO-GO` 或“证据不足”的 provisional 建议，同步任务记录并
   提交 clean worktree，再交计划制定者独立验收并作出最终数据资格结论。

### 完成/验收标准

- [x] Plan 059 `training/publication-critic-v7/` 全目录及其已冻结标签/配对/split/manifest/身份保持逐字节不变，其中包括 Plan 060 使用的 tracked
      `train-only-smoke-bundle.json`；新资产使用独立版本和目录，不覆盖旧版本。Plan 060 worktree/ignored 中的 bundle 或 upload 资产零读取、零写入、
      零替换，不把它们列为 Plan 064 必须直接比对的对象。
- [x] 阶段 A 形成版本化 data-design lock：说明 v7 已覆盖与缺口、正式训练用途、数据来源、覆盖矩阵、训练/validation/unseen-test 保留策略、规模
      判断输入、目标区间或等强有界表达、停止/NO-GO/证据不足条件及复核策略。规模依据必须能关联覆盖、质量、可用 Plan 060 吞吐和正式训练预算，
      不能只写一个想当然的总数或为了填满上限继续生成。
- [x] 新数据扩大四类 publication、五项 hard qualification、明显/边界/mixed 难度、角色、长度、continuity/Evidence、文风、Unicode 与自然表达覆盖；
      采用稀疏而有意义的组合，不要求维度笛卡尔积或人为制造均匀外观。
- [x] 所有正式数据通过 schema、packet/render/input allowlist、split/group、引用、hash、重复、明显捷径和 exact-tokenizer 可消费性校验；candidate 不被
      静默截断，continuity 只沿用 Plan 054 的整条省略语义。
- [x] 语义质量采用与数据用途和风险相称的复核：holdout、Boundary/Within-PASS、近边界/混合/高风险切片得到充分直接检查；大规模清晰训练样本可按
      覆盖分层抽样，不要求每一条都达到手工精品水准。抽样暴露的系统性问题须回到受影响集合修复、替换、降级或排除，不能用总体数量掩盖。
- [x] 若采用抽样语义复核，新版本使用诚实的版本化 review/finalize 合同区分直接复核、风险全审和按已声明抽样策略接纳的训练行，并绑定抽样范围、
      结果与处置；不得修改 v7 合同，也不得给未被直接复核的行伪造“独立 reviewer accept”。简单字段或紧凑 sidecar 即可，不建设审计平台。
- [x] v7 原有 validation 与 unseen-test 成员没有迁入训练集；若新版本纳入任何 v7 成员，其正文、监督、group 和 split 身份保持不变。所有新增关系按
      source/scenario/pair/template/near-duplicate 组闭包切分，train、validation 与 unseen-test 不存在已知泄漏或悬空引用。
- [x] 无论新版本完整物化还是采用 base+delta，group/split、exact/near-duplicate、shortcut、token、manifest 和 consumer 门禁都针对组合后的完整逻辑
      release；与 v7 holdout 形成同组或明显近重复关系的新增行不得进入 train，只能留在同一 holdout 或排除，不能靠 delta 边界绕过。
- [x] 扩充后的 validation 与 unseen-test 对正式训练后的评价仍有明确用途和足够覆盖；训练入口、membership 和任何 train-only bundle 默认不能触达
      holdout。调试集合、被淘汰/返修的旧行和中间 freeze 不得拼入正式版本。
- [x] 新版本直接继承 Plan 054 的 packet、render、tokenizer、16,384-token window 和 scalar 语义，并能通过现有或职责清楚的窄扩展 consumer 物化
      M3-B1c 所需的 Binary、Boundary 与 Within-PASS 输入；不在本任务设计 loss、optimizer、batch recipe 或模型质量判定。
- [x] freeze-ready 候选全集在最终冻结前形成可恢复、可检查的 checkpoint；执行者提交范围内 tracked 实现/合同后保持 worktree clean，向计划制定者
      提交规模依据、覆盖/质量汇总、抽样与 finding、split/泄漏、重复/捷径、token/consumer、Plan 060 事实引用及拟冻结文件清单，等待明确批准。
- [x] 获得冻结批准后，从固定候选集合和干净状态完整运行一轮 finalization、review 终态核对、group/split、dedup/shortcut、exact-token census、
      consumer 和 freeze；最终 manifest 绑定新版本的输入/设计/实现/数据身份，正式目录与该轮输出一致。
- [x] pure/focused tests 覆盖实际改变的 schema、继承/版本、split/group、重复/捷径、freeze/hash、consumer/bundle 与旧 v7 不变性；全量新数据完成
      tokenizer-only 和 consumer smoke。只跑相关轻量门禁，不运行 Cargo、Docker 或完整模型。
- [x] 执行者最终报告明确冻结规模、主要覆盖、已知限制、正式训练可消费边界和数据 `GO`/`NO-GO`/“证据不足”的 provisional 建议；计划制定者在
      独立验收中作出最终结论。没有可用且足够的 Plan 060 吞吐/预算事实时，可以完成扩充与冻结，但不得仅凭数据量宣称规模已被正式训练预算证明；
      应如实建议“证据不足”或带条件的上限结论。
- [x] 执行者只窄更新本计划状态/决策、职责相关说明和一份精炼 `agent_log`，并给出建议的 WBS delta；规划时的共享 WBS 已滞后，执行分支不得用它
      覆盖 Plan 060/062 并行成果。最终 WBS 同步留到独立验收通过、用户批准主线整合后，基于届时最新 clean `main` 窄完成。worktree 形成少量清晰
      提交并保持 clean，不合并、不推送、不归档、不删除 worktree或重命名分支。
- [x] 计划制定者对最终代码、数据、测试、ignored 交接和结论完成独立验收；数据 `GO` 要求无剩余 correctness/functionality 阻断 finding。普通非阻断
      限制可以诚实保留，不为凑 GO 建设复杂审计/可信体系或弱化已有门禁。

## 2. 范围

### 允许修改

- 本计划的“当前状态”和“关键决策记录”；若稳定正文必须变化，先请求用户确认。
- `eval/rondo_eval/publication_critic/training_data/`、`eval/tools/`、`eval/templates/publication-critic/`、
  `eval/manifests/publication-critic/`、`eval/tests/` 及相应小型 fixture/配置中，为 Plan 064 覆盖分析、批量生成/复核、版本继承、切分、检查、
  freeze 和 consumer 所需的能力。
- `training/` 下一个独立于 `publication-critic-v7` 的新版本目录、数据卡、manifest、正式 train/validation/unseen-test、membership 和训练消费包；
  具体版本号、文件拆分及采用完整物化还是经验证的 base+delta 组合由执行者依据维护和消费成本决定。
- 与上述职责直接相关的现有 Python 入口、依赖定义和轻量说明。职责契合时复用 Plan 059 设施；强行复用会造成语义扭曲时，可以新增专用能力，
  但仍沿用现有配置、生命周期、错误、测试和观测方式，不另起第二套数据平台。
- 完成时一份精炼 Plan 064 `agent_log`，以及必要的 `training/README.md` / `doc/eval-data-layout.md` 稳定事实。执行者在交接中给出建议的 WBS
  delta，但不从当前滞后分支修改共享 WBS；独立验收通过且用户批准主线整合后，再由整合者基于最新 main 窄同步。没有事实变化的文档不改。
- 主物理仓库根 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan064/` 内的 raw generation/review、返修/排除、抽样复核、临时 split/
  finalize/token/consumer、freeze-ready checkpoint 和报告。目录/文件默认分别为 `0700`/`0600`，不得使用 symlink。

本计划不固定样本总数、split 比例、生成批数、teacher prompt 文案、抽样率、near-duplicate 算法、具体 Python 模块、最终文件布局或 consumer CLI。
执行者应在阶段 A 的 data-design lock 中做出有据、可复算且有上界的选择；live code 或数据证明有更干净的等强路线时，可以自主采用并在关键决策
记录中简要说明。

### 允许只读核对

- 根/局部规则、README、当前 WBS、Plan 054/059、Publication Critic 产品合同、v7 数据/验收证据、相关 tracked 源码/测试/Git 历史及现有数据布局。
- 主物理根既有 Plan 054 exact tokenizer/cache 与 Plan 059 自有保留资产中职责相关的生成/复核/冻结证据；不得修改、移动或清理这些上游资产。
- Plan 060 已提交的规划合同可只读用于理解范围，但不算正式吞吐/费用证据；规模判断只接受已经合入 main 的结果，或用户/审查者明确交接的正式
  吞吐、费用和预算汇总。其他 worktree 只读 Git 元数据用于并行保护。
- 普通公开网络文档和源码；不得借此调用项目真实 API、登录服务、上传数据或改变远端状态。

### 不允许修改或执行

- `training/publication-critic-v7/`、Plan 059 v7 绑定的 frozen schema/prompt/identity/manifest 与历史日志/结果，Plan 054 v4 的 packet/render/
  tokenizer/window/scalar 身份，以及 Plan 060 的 smoke bundle、recipe、训练实现和冻结运行资产。
- Plan 060/062 的 worktree、branch、未提交内容、ignored 资产、预算或结果；也不修改 `mydev/`、`multidev/` 产品源码及其他任务现场。
- 正式模型训练、model forward、模型质量/threshold/部署判定、M3-B1c 启动，或为了数据任务改变训练 recipe、optimizer、checkpoint 或运行平台。
- Docker、RunPod/HF Jobs/其他云计算、重型 Cargo/Bazel、本地完整模型下载/加载/推理、项目真实 API 批量调用、批量测评、模型或数据上传、远端写入、
  产生费用的服务、CI/PR、上游升级、宿主机/全局工具链配置。
- 通用数据/标注/审核平台、teacher committee、签名/可信链、复杂权限/鉴权、严格因果或语义审计体系、embedding 服务，以及与本任务无关的重构。
- 当前共享 `doc/WBS.md` 与 `doc/WBS/*.md`；该快照已落后于 Plan 060/062 并行事实，执行者只提供建议 delta，不自行 merge/rebase main 争写共享 WBS。
  最终独立验收通过且用户批准主线整合后，才基于届时最新 main 窄同步 Plan 064 事实。
- 合并或 rebase `main`、推送任意分支、归档/重命名任务分支或删除 worktree；这些动作等待用户另行批准。

### 不允许读取/查看

- `.env.local` 内容、项目外个人文件、密钥、凭据、账号 token、私有配置或无关数据；本任务不需要读取或加载任何秘密。
- Plan 060/062 和其他 worktree 的未提交内容或 ignored 运行资产。Plan 060 的规模事实只接受已提交文件、正式交接或用户/审查者明确提供的汇总，
  不通过窥探并行现场推断。
- 与 Publication Critic 数据职责无关的完整 transcript、private/hidden reasoning、raw trace、Fact observation 或工具结果正文；真实锚点仍只使用
  已授权、可可靠恢复的 event-local 公共投影。
- 任何模型权重内容。exact-tokenizer-only 工作只打开身份允许的 tokenizer/template/special-token 文件，不加载模型 backend。

### Git-ignored 与主工作区边界

tracked 代码、合同、测试、正式数据、文档和日志全部在
`/home/sjc/desktop/RONDO/.claude/worktrees/064-publication-critic-data-expansion/` 修改并提交；主工作区不得产生 tracked 修改。

linked worktree 不共享主根 ignored `eval-data/`，因此执行阶段预计必须直接在主物理仓库根创建并使用
`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan064/`。这里仅存 Plan 064 自有的 raw/临时/prefreeze 资产，不创建第二份 tracked 树。
Plan 054 tokenizer/cache 与 Plan 059 retained namespace 只读，Plan 060/062 namespace 零读取、零写入、零清理。任务内清理只针对 Plan 064 明确创建且
确认不再需要的临时资产；freeze-ready 输入、复核记录与正式 freeze 对账所需证据至少保留到最终独立验收完成，并在交接时单列路径、大小和保留状态。

## 3. 硬约束

以下约束只冻结不可变上游、数据正确性、并行安全、冻结关口与诚实结论，不固定可替换实现路线。

1. **v7 与 Plan 060 输入不可变。** 不修改、再冻结、重命名或覆盖 v7，也不把 Plan 064 数据替换进 Plan 060。新版本若包含 v7 成员，必须验证内容和
   split 身份保持一致；v7 validation/unseen-test 永不迁入训练。Plan 060 worktree/ignored 现场零读取、零写入，v7 内已有 tracked smoke bundle 的
   不变性由 v7 全目录回归覆盖，不要求读取 Plan 060 自有 bundle/upload 资产。
2. **规模先有依据，停止不看数量表演。** 阶段 A 在扩大生成前冻结覆盖缺口、规模输入、目标区间/硬上界或等强有界表达及停止条件。Plan 060 尚无
   正式吞吐/费用时可以继续本地扩充，但最终规模结论必须标出所用假设；事实到达后只允许按预先定义的方法更新规模判断，不能为已有数据倒推门槛。
3. **Plan 054 是唯一输入语义。** 正式 candidate 必须经现有 `PublicationPacket v1`、qualification rubric、两条 message render、exact tokenizer、
   16,384 window 与 whole-continuity omission 合同；不得复制第二份近似 packet/renderer 或改变 scalar 方向。发现上游核心合同错误时停止并返回上游。
4. **组级 split 与 holdout 隔离。** source/scenario/pair/template/near-duplicate 关系闭包必须位于同一 split；训练消费默认只持有 train。新增 holdout
   必须在冻结时固定身份，冻结后不因训练便利迁移、补标签或改写。
5. **质量复核与风险匹配。** 所有行做机械全检；语义复核覆盖所有 holdout、pair、近边界/混合/高风险切片，并对其余训练主体按覆盖分层抽样或采用
   等强策略。无需追求每条训练样本都完美，但已发现的系统性 label/prompt/template/shortcut 问题必须处理受影响集合，不能只删抽中的个例。
   采用抽样时必须新增版本化 review/finalize 表达，诚实区分直接审查行与按抽样策略接纳的训练行；不得修改 v7 schema/freeze，也不得为未逐条审查的
   数据填写具有“独立 reviewer 已接受”含义的旧状态。该表达只需支持正确消费和复核，不扩张成通用审核系统。
6. **复核可以收敛，不能制造一致。** 执行者可在范围内返修、替换、重新生成、重新复核、降级或排除，不设一次失败即停或机械次数上限；有效淘汰
   不要求按原样本补回。不得反复追问 reviewer 直到得到预定标签，也不得为凑规模降低 qualification 或 pair 语义。
7. **检查相称且可复算。** exact/near-duplicate、跨 split group、label/split/role/length/style/Unicode/Evidence/模板等明显捷径和 token census 必须
   覆盖完整候选集并报告聚合；base+delta 时“完整候选集”指组合后的逻辑 release，检查不能只在 delta 内运行。新增行若与 v7 holdout 同组或明显
   近重复，不得进入 train；关系跨越两个既有 holdout 且无法在不改变 v7 的前提下闭合时应排除或返修。自动检查只用于发现明显问题，不承诺消除
   所有统计相关，也不升级成通用语义审计或因果证明。
8. **先调试打通，再冻结正式结果。** 阶段 B 保留身份未变且已验证的生成/复核进度，从未打通处边修边跑；设施和语义稳定后才形成 freeze-ready
   候选全集。不得过早生成正式 manifest，再在正式目录中反复修补或把 commissioning/中间集合拼接成 release。
9. **冻结前必须停下审查。** 执行者在 prefreeze checkpoint 提交后停止，不运行正式 freeze、不创建最终 `training/` 版本、不把草稿写成 GO。
   计划制定者可以直接读取 Plan 064 ignored 候选与报告做审查；普通 finding 修复后可再次提交 checkpoint。只有计划制定者明确批准，才进入阶段 C
   的正式冻结子阶段。任何后续整改只要改变候选语义、label、pair、group/split、规模集合或输入身份，原冻结批准即失效，必须形成新的 prefreeze
   checkpoint 并再次停下审查；仅候选内容/身份完全不变的 runner/环境修复可直接重跑正式机械链。
10. **正式 freeze 是一轮干净全量运行。** 获批后固定候选/复核/设计/实现身份，用新输出目录从干净状态完整跑 finalization、split、检查、token census、
    consumer 和 manifest。任何语义、label、pair、group/split、规模集合或输入身份变化都须更新新版本身份、回到 prefreeze 重新审查，并在再获批准后
    重新运行完整终态链，不能只改 hash。
11. **训练可直接消费，但不替训练做决定。** 新 release 必须由严格 consumer 验证 Binary/Boundary/Within-PASS、membership、输入身份与 holdout 排除；
    可以复用或窄扩展现有 consumer，不实现正式 loss/recipe/训练平台。数据 GO 只代表数据资格，不代表模型质量或训练预算 GO。
12. **并行与资源隔离。** 不读写 Plan 060/062 未提交或 ignored 现场，不占用其 RunPod/预算/构建槽；本任务不运行 Docker、重型构建或完整模型。
    缺少 Plan 060 正式事实不构成继续本地数据工作的阻塞，但不得伪造汇合结论。
13. **证据诚实、文档按职责同步。** pure/focused、开发用 Codex 生成/复核、tokenizer-only、consumer 和未运行的模型/训练证据分开表述。执行者
    只提供建议 WBS delta；最终 WBS 在独立验收和用户批准主线整合后基于届时最新 clean main 窄同步。plan/日志不复制下游路线，
    WBS-COMPLETED 只在最终独立验收通过后更新。
14. **Git 交付止于任务分支提交。** 只 stage 范围内文件，检查 diff、体积、敏感/ignored 边界和并行 worktree 状态，形成少量本地提交并保持 clean。
    执行者不得合并、推送、归档、删 worktree 或触碰来源不明修改；最终独立验收与主线整合等待用户决定。

## 4. 软性建议

以下建议基于 `main@eeeddf6f532c4f116ddc72595196034c20953ad3` 的 live 设施，不是验收门。执行者可依据实际数据、Plan 060 正式事实和维护成本采用更优
等强方案，审查者不得把本节偏好升级为硬约束。

- 先从 v7 `manifest.json`、`reports.json`、design lock 和 supervision metadata 生成覆盖透视，再有界抽看正文确认语义缺口；矩阵关注薄弱交叉和
  真实失败模式，不需要把全部维度做成笛卡尔积。
- 现有 `training_data` 子包已经覆盖 contract、grouping、dedup/shortcut、input identity、token census、freeze 和 factory consumer。职责相同的
  部分直接复用；规模分析、分层抽样或版本组合确属新职责时，宜新增小而清楚的专用模块，而不是继续把 Plan 059 脚本硬编码扩张。
- 新版本可完整物化，也可采用 v7 base + additive delta 后由 manifest/consumer 直接组合。数据体积仍很小时完整物化通常更简单；若组合路线更干净，
  必须让使用者一次加载即可得到闭合版本，不能要求训练端手工拼文件或绕过 holdout 验证；所有跨 base/delta 的 group、重复、捷径、token 与消费门禁
  仍对完整组合运行。
- 可按 scenario pack 分批生成清晰 Binary、Boundary、Within-PASS 和 mixed case；先验证小批的解析、pair 语义、token 与消费，再扩大。开发用 Codex
  多智能体会话可以分担生成和独立复核，实际 model/effort/session 能记录多少就诚实记录多少，不建设 teacher committee。
- 语义检查宜前置到每批和 prefreeze：对 holdout/pair/边界做直接复核，对清晰训练主体做按 publication class、hard focus、难度、风格、长度和来源
  分层抽样；抽样失败率、主要 finding 和受影响范围比逐条“全接受”标记更有信息量。若执行者有更高性价比的等强策略，可以自主采用。
- data-design lock 可以把规模表达为覆盖下限、预期训练步骤/token 需求、质量淘汰余量和训练预算上界共同形成的区间；Plan 060 只提供真实吞吐/费用
  参数，不替 Plan 064 选择数据语义或 split。
- prefreeze 交接包保持人工可读即可：checkpoint commit、候选目录、设计锁、生成/复核身份、规模计算、覆盖表、抽样结果、known findings、split/group、
  duplicate/shortcut、token/consumer 汇总和拟冻结文件清单；不需要签名、数据库或专用审计服务。
- 测试按受影响面收敛：先 pure schema/version/group/sampling，再跑 Publication Critic focused Python tests，最后对 freeze-ready/正式全集各做相称
  validator、tokenizer-only 与 consumer smoke。不要运行全 workspace、Cargo、Docker 或模型 forward。
- 交接时给出一段精确、短小的建议 WBS delta；不在 064 执行分支合并 main 或修改当前滞后 WBS。最终整合者在用户批准后对最新 main 做窄编辑，
  保留已进入主线的 Plan 060/062 事实。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 阶段 A 已完成。物理 v7 身份保持 `tree=435c06fba3196bee21d59d88b9e6d6b1a1e1999a`、manifest content
  `07666936706786c456e83a7130c211013ff95cfb3e494154e62fca1e3bc528eb`；基线为 36 scenario、72 candidate、36 pair、42/16/14 split、
  50,073 exact tokens。Plan 060 仅有已提交规划合同，没有可接受的真实吞吐、费用或训练预算汇总，因此数据规模预算适配仍为证据不足。
- data-design lock、batch/review/finalize、完整逻辑 release 门禁、risk-stratified quality audit、exact v7 membership projection、consumer 和 focused tests
  已落地。v7 物理目录未修改；v8 仅显式退休 `HONEST-V3-001B` 的六条歧义 honesty qminus 和六条 Boundary relation，保留 66 个 canonically
  unchanged v7 candidates、36 scenarios 和 30 pairs。
- 阶段 B 的稳定 delta 为 87 scenarios、162 candidates、74 pairs，所有新 candidate/pair 均有 direct review binding。修复按小块完成并锁定：
  scope 三块与 honesty train/validation/unseen 三块均由独立 reviewer 只做本块 blind regression；未通过的 honesty train/unseen 只返修本块，
  未删除样本或重开已通过区域。
- 完整逻辑候选为 123 scenarios、228 candidates、104 pairs，最终 preliminary split 为 train/validation/unseen-test `128/55/45`；37 条
  near-duplicate edges 均闭合，无 reference match、coverage failure、visible/conditioned/length shortcut finding，exact token 为 178,646、
  单项 553--2,094，whole-continuity omission 为 0。
- `candidate-v11-reviewed` 是当前权威候选。首次 clean-HEAD prefreeze 试跑在写 release 前发现一条 `known_stale` packet 缺少对应的派生
  freshness slice；只修正该 scenario/supervision metadata，并把 slice projection 校验前移到 generation contract。packet 正文、label、defect、pair、
  候选身份和抽样集合均未改变；旧失败输出保留为诊断证据。
- release-audit-v6 覆盖 97 个风险分层、123 candidates 和 33 pairs。它与 v5 的 blind candidate/pair packets、三个 shard、抽样 ID、strata、reveal
  均逐字节一致，仅 reviewed content binding 因上述 metadata 修正而更新，故机械精确重绑定而未重做语义审查。三路有效盲审中唯一系统性 finding 精确命中既有 `HC-001` 六个 v7
  continuity pairs，并由终态 adjudication 维持 `false_positive`；未解决系统性 finding 为 0。一个 reviewer 主动披露旧会话暴露，其 shard C 输出被
  保留但排除，另启零上下文 reviewer 重审同一 shard C 并得到 0 finding。单条 label/defect/soft-direction 分歧原样记录；按 design lock，附加 audit
  只发现系统性问题，不替代所有新行的 direct admission review。
- 12 个 Publication Critic focused Python 模块共 136 tests 全部通过；compileall 与 `git diff --check` 通过。全模型、Cargo、Docker、云任务、
  真实 API、上传、训练和 Plan 060/062 live 资产均未运行或读取。

### 当前工作

- `COMPLETE`：最终独立验收通过。`training/publication-critic-v8/` 已冻结并绑定获批 universe
  `3fdfc0ada4a67451e4f1fc7e66302067119172fea809802ff1d01576b3be40d9`；最终数据资格为“证据不足（训练预算适配未决）”，不是数据 GO。

### 本任务剩余步骤

- 本任务内无剩余实施或验收步骤。WBS 窄同步与主线整合仍按用户边界留给后续整合者；本分支不修改 WBS、不合并、不推送、不归档。

### 阻塞项

- Plan 064 无剩余阻塞。Plan 060 尚无可接受的正式吞吐、最终费用或训练预算事实，因此下游数据 GO 与 M3-B1c 仍被阻断；该外部条件不影响
  Plan 064 以“证据不足”终态完成。

### 当前验收状态

- `FROZEN / ACCEPTED / EVIDENCE_INSUFFICIENT`：阶段 A--D 与最终独立验收全部完成，正式 v8、manifest、DATA_CARD、tokenizer-only、consumer 和
  137 项 focused tests 通过。没有数据 GO，也未启动训练；后续预算适配复核与主线交付由 WBS 另行承接。

### 交接边界

- 第一次强制交接发生在 freeze-ready checkpoint：执行者保持 worktree clean，提交 tracked checkpoint 与主物理根候选/报告清单，明确写出“尚未
  freeze”，等待计划制定者批准或给出 finding。
- 冻结获批后，执行者在同一 worktree 和 Plan 064 ignored namespace 继续，完成正式 freeze、自检与提交；随后再次停止，交计划制定者做最终独立验收。
- 每次交接都单列主物理根 `eval-data/publication-critic/plan064/` 实际创建/修改的路径、大小、保留/可清理状态，并确认未触碰 Plan 054/059/060/062
  或来源不明 ignored 资产。任务完成后冻结本计划，后续只交回 WBS。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | v7 作为不可变基线；Plan 064 创建独立版本，v7 成员若被继承则内容和 split 不变 | 同时保护 Plan 060 smoke 输入和既有 holdout 身份 | 数据版本、split | 已采纳 |
| 002 | 样本数不在 ExecPlan 固定，阶段 A 以覆盖、质量、Plan 060 事实和正式训练预算冻结有界规模方法 | 避免机械扩量，也避免事后为已有数据倒推门槛 | 规模、停止条件 | 已采纳 |
| 003 | 所有正式行机械全检；语义复核按风险分层，不要求全部训练行逐条精品化；抽样接纳使用新版本化合同且不伪造逐行 accept | 扩大量级下优先保证高风险监督和发现系统性问题，同时保持 review 证据诚实 | review、质量 | 已采纳 |
| 004 | 普通失败允许返修、替换和重跑，不设置机械槽位/次数上限；原则冲突才暂停 | 保留已验证进度，避免窄问题导致整批报废 | 生成、恢复 | 已采纳 |
| 005 | freeze-ready 后强制停下，由计划制定者先审候选全集；明确批准后才正式 freeze | 让语义和规模问题在低修改成本阶段暴露 | 阶段、验收 | 已采纳 |
| 006 | 新版本可完整物化或采用可直接消费的 base+delta，布局由执行者依据 live 设施选择 | 保留干净实现空间，不强迫扭曲旧设施 | freeze、consumer | 已采纳 |
| 007 | Plan 060 规划合同可只读；真实吞吐/费用只接受已进 main、正式交接或用户提供的汇总，不读取其并行现场 | 保持并行隔离，避免把瞬时状态当正式吞吐与费用 | 依赖、并行 | 已采纳 |
| 008 | tracked 交付仅在 064 worktree；raw/prefreeze 资产统一放主物理根 Plan 064 ignored namespace | linked worktree 不共享 ignored 资产，同时避免主工作区 tracked 修改 | Git、数据布局 | 已采纳 |
| 009 | 执行者不修改当前滞后 WBS，只提供建议 delta；最终编辑在独立验收和用户批准整合后基于最新 clean main 窄完成 | 保护 Plan 060/062 并行成果，保留用户批准主线交付的边界 | 文档、Git | 已采纳 |
| 010 | v8 对物理 v7 使用 exact membership projection，显式退休 `HONEST-V3-001B` 六条歧义 qminus 及其 relations，不改写 v7 | 保留上游 release 与 Plan 060 smoke 身份，同时避免把已确认歧义监督继承进 v8 | lineage、release | 已采纳 |
| 011 | 采用完整物化 release；同一 lineage helper 同时约束 commissioning、prefreeze、freeze 和 consumer，不在各入口重复过滤 | 数据规模小，完整物化更易直接消费和完整验证 | freeze、consumer | 已采纳 |
| 012 | direct review 是新行准入；release audit 只作为系统性风险监控，保留单条分歧但只由未解决系统性 finding 阻断 | 符合 design lock 与风险相称复核，避免反复追问 reviewer 制造一致 | review、质量 | 已采纳 |
| 013 | grouped split 的确定性搜索预算由 20,000 调为 30,000，算法、seed、ratio、coverage 和 group 规则不变 | 固定候选首次可行分配在 attempt 23,429；这是有界机械搜索预算问题，不是数据语义问题 | split、配置 | 已采纳 |
| 014 | 只冻结计划制定者批准的 `3fdfc0...40d9` universe；Plan 060 正式预算事实缺失时，阶段 D 结论固定为“证据不足” | 保持冻结身份精确，同时不把覆盖规模冒充训练预算资格 | freeze、结论 | 已采纳 |
| 015 | 最终独立验收接受 v8 冻结并以“证据不足”完成 Plan 064；Plan 060 正式事实到达后仅做一次有界预算适配复核 | 合同允许证据不足终态，避免为取得 GO 机械扩量或重做已冻结数据 | 验收、交接 | 已采纳 |
