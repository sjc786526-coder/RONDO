# Plan 059：M3-B1a Publication Critic 分层训练数据生成、复核与冻结 ExecPlan

> 本计划是 M3-B1a 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通 schema、生成、复核解析、split、dedup、tokenizer、
> manifest、fixture、consumer 和测试问题应在范围内自主修复并按需重跑。
> 本计划只描述 M3-B1a；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

继承 Plan 054 v4 已验收的 `PublicationPacket v1`、两条有序 message、control-token-safe render、exact
tokenizer/template/special-token identity、16,384-token window 及 overflow 语义，把 Publication Critic 的产品 qualification 转换为一套
可直接交给 M3-B1b 的正式训练数据资产。

数据以少量可可靠恢复的真实 RONDO Multi 公共场景为锚点、执行本任务的 GPT-5.6-sol 开发用 Codex 直接合成为主体，并经过隔离子会话的
GPT-5.6-sol 独立教师复核；不设计“执行者再把合成工作交给外部 Sol”的交接。最终冻结互相隔离的
train、validation、unseen-test split，以及三类监督：每个正式 candidate 的 Binary `PASS/REWRITE`、可靠的 Boundary/Q± 原子边界对和少量
Within-PASS 软偏好对。任务同时交付轻量 consumer 与不含 validation/unseen-test 的 train-only smoke bundle，使 M3-B1b 无需在付费环境中
重新解释输入、标签、pair 或 split。

本任务只判断“数据是否具备进入训练资格 smoke 的条件”。不运行模型 forward、optimizer step 或训练，不证明模型性能提升、训练成功、
本地部署资格或产品上线资格；诚实的数据 NO-GO 也属于有效完成。

### 完成/验收标准

- [x] 在任何数据合成前先形成版本化 coverage/stop lock，冻结来源 allowlist、最低覆盖矩阵、目标量/硬上限/停止条件、split 目标、teacher 角色、
      分歧处理、dedup/near-duplicate/group 规则以及 C1/C2/C3 数据成员关系。具体数量由执行者依据 live 合同和合理工作量确定，但不得先看
      完整生成结果再反推最低门槛；exact prompt/实现/配置身份在小批 rehearsal 打通后、扩大生成前再冻结。
- [x] Scenario、Candidate、Pair 与监督 metadata 的职责清楚：Scenario 表达可合成或可恢复的公共场景蓝图；Candidate 复用并通过
      `PublicationPacket v1` 验证；Pair 只引用正式 candidate；label、split、defect、pair direction、generator/reviewer/source 等监督和
      生成信息物理隔离，不进入现有 renderer。
- [x] 冻结 train、validation、unseen-test 三个非空 split；每个正式 candidate 恰有一个 Binary `PASS/REWRITE`，三个 split 均有两类标签及
      data-design lock 声明的最低覆盖。Plan 054 calibration/measurement cohort 只作历史基线、语义锚点或去重参照，不改名、复制为或冒充
      Plan 059 unseen test。
- [x] 覆盖矩阵以稀疏而有意义的组合覆盖 new/existing Event × completed/incomplete、五项 hard qualification、明显 PASS/REWRITE、
      near-boundary 与自然 mixed case，并重点补足 `internal_consistency` 精致 hard negative、new/completed 的 useful-state/process-dump/
      scope 边界、threshold-near handoff、continuity 与 Evidence V1 的可用/缺失/陈旧/明确省略对照。
- [x] 数据在长度、Root/普通成员角色、正式/口语文风、Unicode 和模板表达上有受控变化；这些变化不改写产品 qualification。完成按 split/label/
      slice 的轻量聚合检查，没有已知的明显标签、长度、角色、模板或 Evidence 外观捷径；不要求建立因果审计或通用数据质量平台。
- [x] Boundary/Q± 的每对端点都先有独立 Binary 判定，`Q+` 为 `PASS`、`Q-` 为 `REWRITE`，只改变一个有声明且经 reviewer 确认的 hard
      qualification 目标维度；两端最终 continuity omission 和非目标 model-visible context 保持相同。无法可信保持单维差异的候选可保留为
      普通 Binary/mixed case，但不能强行进入原子 pair。
- [x] Within-PASS 的两端都先独立满足全部适用 hard qualification，pair 只表达核心语义等价时的克制软偏好及明确方向；不产生
      `REWRITE > REWRITE` 排序，两端最终 continuity omission 和非 candidate 公共 context 保持相同，也不让 Within-PASS 数量或训练成员关系
      压过 Binary/Boundary 主体。
- [x] 少量真实锚点只取自已完成任务中可可靠恢复的公共场景/公共状态；不把无关完整 transcript、隐藏/private reasoning、raw trace、Fact
      observation 正文或私有工具正文直接放入 Scenario、Candidate 或 teacher prompt。所有从同一真实来源派生的变体共享 source group。
- [x] teacher generator 与 independent teacher reviewer 保持角色和上下文分离，实际模型/effort/角色和可用的 session/run identity 被记录；
      generator 是直接执行本任务的 GPT-5.6-sol 主会话，reviewer 是未继承其隐藏生成对话的独立 GPT-5.6-sol 子会话。分歧按
      预先冻结规则接受、返修、重生成、降级为 Binary/mixed 或排除，不通过反复询问 reviewer 强行制造一致。
- [x] 在大批量合成前，以覆盖主要 schema、pair 和长输入边界的小批次打通 generation → review → finalize/split → exact-tokenizer census →
      consumer/bundle 全链路，并在后续批次间做有代表性的抽样复核。发现系统性 prompt/schema/pair 问题时先停该批次、修复并复验，不等全部合成
      结束后整版报废。
- [x] 全链路 rehearsal 打通后才冻结正式实现、prompt 与配置；随后从 clean 状态对全部拟入选 raw candidate 完整运行一次 finalizer、review
      终态检查、group/split、dedup、token census、freeze 和 consumer，并以该轮作为正式冻结证据。早期有效合成可在最终合同下重校验后保留，
      只有受语义/prompt 变化影响的部分才重生成，不为形式上的“从头跑”浪费已验证教师产物。
- [x] grouped + stratified split 在 candidate 接受后按冻结规则完成；同一 scenario/source group、任一 pair、声明的模板近改写和检测出的
      near-duplicate component 全部落在同一 split。split 算法、seed/identity、分组输入与结果可复算，train/validation/unseen-test 的 candidate
      和 pair 引用均无交集、无悬空引用。
- [x] exact duplicate 和版本化 near-duplicate 检查覆盖三个正式 split、真实 anchor 变体、模板近改写以及 Plan 054 cohort；规则与阈值由
      data-design lock 冻结并报告聚合结果。自动相似度只作候选筛查，明显语义重复或可疑跨 split 关系仍须处理，不冒充严格语义证明。
- [x] 每个正式 packet 通过 Plan 054 v4 的产品机械约束、model-visible allowlist、control-token guard、两条 message render 和 exact tokenizer；
      全量 token census 使用冻结 tokenizer/template/special-token identity，逐行记录最终 `input_ids` 数量与整条 continuity omission，bucket 与
      总数严格对账。candidate 不静默截断，无法在仅整条省略 continuity 后完整落入 16,384 token 的 candidate 不得进入正式数据。
- [x] 冻结资产含版本化 schema/contract、三 split 数据、pair 数据、manifest、数据卡、设计锁、prompt/identity 摘要、完整文件 hash、覆盖/
      review/split/dedup/token 聚合和必要的可复算命令；最终正文满足 `training/` 的总量与单文件门限。原始生成/复核/返修明细留在任务专用
      ignored 区，不把权重、模型运行产物或私有上下文提交到 Git。
- [x] 轻量 consumer 能严格读取 Candidate/Binary/Pair 与 frozen input identity，拒绝 schema/identity/hash/引用/split 漂移，并验证：C1 只消费
      train Binary；C2 在完整保留 C1 成员的基础上增加 train Boundary/Q±；C3 在完整保留 C2 的基础上增加 train Within-PASS。这里仅定义
      数据成员关系，不定义 loss、batch、optimizer 或训练 recipe。
- [x] 生成确定性的 train-only smoke bundle；bundle 只来自 train split，包含足以机械覆盖 C1/C2/C3 输入类型的成员与来源 hash，不包含
      validation 或 unseen-test candidate/packet/pair/label/metadata。轻量消费 smoke 能从 bundle 物化现有两-message 模型输入，但不加载完整模型。
- [x] pure/focused tests 覆盖 schema、监督隔离、review 状态、pair 不变量、分组切分、重复/近重复、freeze/hash、C1/C2/C3 成员和 bundle 排除；
      exact-tokenizer-only 门禁覆盖全部正式 candidate。只运行受影响模块的必要测试，结果明确区分 pure、teacher reference、真实 tokenizer 和
      未运行的模型/训练证据。
- [x] 完成一次与 generator/reviewer 均分离的聚焦独立验收，审查数据正确性、split 泄漏、输入隔离、token census、冻结身份和 consumer 合同。
      普通 finding 在 059 范围内修复并重新冻结受影响完整集合；最终给出 M3-B1b 数据 GO/NO-GO，且没有剩余 correctness/functionality finding。
- [x] 完成后只精炼更新顶层 WBS 的方向 3 指针、方向 3 子 WBS、本计划状态/决策和一份有实质内容的 Plan 059 `agent_log`。检查 diff、文件体积、敏感/ignored 边界、
      主工作区与所有 worktree 状态后，只提交 059 worktree 本地分支并保持 clean；不合并、不推送、不归档、不删除 worktree或重命名分支。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 内与 Plan 059 直接相关的数据合同、teacher 输入/输出解析、验证、分组切分、重复检查、token census、
  freeze/finalize 与轻量 consumer 能力；职责成组时可新增专用子包/模块，职责吻合时复用 Plan 054 的 packet/render/tokenizer/identity/archive
  原语，不复制第二套输入或评价 runner。Plan 054 v4 implementation manifest 已绑定的既有输入/评价文件保持只读，059 新职责默认以并列新增
  模块消费其现行 API/合同；不能为方便训练而让 v4 identity 漂移。
- `eval/templates/publication-critic/`、`eval/manifests/publication-critic/`、`eval/fixtures/`、`eval/tests/` 及相应小型配置/依赖锁中本任务需要的
  schema、data-design lock、teacher prompt、fixture、manifest 和 focused tests。最终正式训练正文优先归 `training/`，不把同一数据重复维护在
  `eval/fixtures/`。
- `training/` 下职责明确的 Publication Critic 版本化训练数据目录、数据卡、manifest、三 split、pair、C1/C2/C3 membership 和 train-only smoke
  bundle；目录名和文件拆分由执行者结合体积、消费方式和现有惯例决定。
- 与上述能力直接相关的已有生成物、Python 依赖定义、任务局部命令入口和必要小型说明；公共职责确有需要时可窄调已有原语，但不得为本任务建立
  通用训练/数据平台。
- 本计划的“当前状态”和“关键决策记录”、任务完成时一份精炼 Plan 059 `agent_log`，以及
  `doc/WBS.md` 中仅方向 3 的当前指针、`doc/WBS/multi-agent-trusted-evidence.md` 中 M3-B1a 的当前事实、结论和 M3-B1b 交接。
- 主物理仓库根的 git-ignored `eval-data/publication-critic/plan059/` 任务命名空间，用于 source projection、raw candidates、generator/reviewer
  结构化输出、返修记录、逐条过滤/重复明细、临时 finalization 和本地 smoke 产物。目录/文件默认分别为 `0700`/`0600`，不得使用 symlink。

本计划不固定 Python 模块名、JSONL 文件拆分、样本总数、各 split 精确比例、near-duplicate 算法、teacher prompt 文案、生成批次数、模板数量或
consumer CLI 形状。执行者应先在 data-design lock 中做出有依据且可机检的选择；若 live code 显示有更干净的等强路线，可以自主采用并在关键决策中
简要记录。

本次规划提交另可依据用户已明确事实，一次性把顶层 WBS 的 Plan 058 active 边界与 Plan 054/059 方向指针同步到当前状态；进入 059 实施后，
执行者只更新方向 3 指针，不替 Plan 058 写结果、结算或释放事实。

### 允许只读核对与普通网络读取

- 根/局部规则、README、当前 WBS、Plan 050/053/054/055/057、Publication Critic 产品合同、Plan 054 v4 冻结身份/结果/fixtures、相关 tracked
  源码、测试、Git 历史和现有训练数据范式。
- 主物理仓库根中 Plan 054 已保留的 exact tokenizer、任务环境和必要 cache；只使用 tokenizer/template/special-token 文件，不加载或复制完整
  模型权重，不重新运行 Plan 054 scalar measurement。
- Plan 050、057 等已完成 Multi 任务中任务明确选中的少量运行资产，仅为提取可可靠恢复的 event-local 公共状态或合成场景锚点。优先使用 tracked
  public/body-free 投影；确需读取 ignored 完成资产时，只对事先列明的任务/文件通过已有公共状态投影做有界提取，不浏览或复制完整 transcript、
  hidden reasoning、raw tool/evidence body。
- Hugging Face 公共 metadata 和 Plan 054 已冻结 revision 的 tokenizer 文件。只有 exact tokenizer 文件确实缺失时，才允许补取该冻结 revision
  的必要 tokenizer/template 文件；不下载完整模型权重，不登录、上传或修改 Hugging Face 远端资源。
- 主工作区和其他 worktree 的 Git/资源元数据只用于并行保护。Plan 058 是否释放全局运行槽只接受其正式 campaign/账本/reservation/资源后置
  记录和用户明确交接，不通过检查瞬时 Docker/进程状态自行推断。

### 不允许修改或执行

- Plan 054 v4 的 `PublicationPacket v1` 产品语义、qualification、render、exact tokenizer/template/special-token identity、16,384-token
  window、candidate/continuity overflow 语义、scalar 历史结果，或 Plan 055/057 的服务和发布产品行为。若发现上游核心合同缺陷，停止并返回
  上游修正，不在数据中兼容两套语义。
- Plan 058 的任何 worktree、branch 内容、formal/commissioning campaign、预算/账本/reservation、trace、binary、Docker 对象、ignored 运行资产
  或资源记录；也不修改 `mydev/`、方向 1 WBS/结果及其他任务现场。
- `multidev/` 产品源码、配置与测试。本任务现有 Python 严格输入合同足以建立训练数据层；若执行中证明确需新增 Rust validator/export seam，
  应先暂停并取得范围及重型门禁授权，而不是在 059 内暗自扩张。
- Plan 054 calibration/measurement 样本的身份或角色；不得把它们复制或改名为 Plan 059 unseen test，也不得修改历史结果、日志或冻结研究快照。
- M3-B1b/M3-B1c/M3-C1/M3-C2：模型 forward、optimizer、训练 recipe 探索、量化/转换、checkpoint、部署、阈值选择或产品启用。
- Docker/Harbor、重型 Cargo/Bazel、完整本地模型加载/推理、GPU/大内存推理、项目真实 API 批量生成/判别、模型权重大规模下载、RunPod/H100、
  训练、上传、发布、远端写入或其他付费操作。Plan 058 正式释放不会自动扩大本授权；059 如确需其中任一项，须先取得新增授权。
- 第二套 renderer、packet validator、eval runner、产品状态/trace、通用数据平台、teacher committee、人工标注平台、复杂审计/签名/可信链、严格
  因果去重系统、通用训练平台或与 Publication Critic 数据冻结无关的重构。
- 除本次规划提交按用户事实同步 Plan 058 active 边界外，顶层 `doc/WBS.md` 中方向 3 当前指针以外的后续修改、`doc/WBS-COMPLETED.md`、共享
  结果索引和 Plan 058 的方向 1 结果/结算/释放事实；进入实施后 059 只窄同步自身方向。
- CI/PR、上游基线升级、宿主机/全局工具链配置、合并、推送、worktree/分支归档或清理其他任务资产。

### 不允许读取/查看

- `.env.local` 内容、项目外个人文件、密钥、凭据、账号 token、私有配置或无关数据；不得运行会打印 Hugging Face token 或环境密钥的命令。
- Plan 058 的 tracked/ignored worktree 与运行资产，以及其他 worktree 的未提交内容。
- 与所选真实锚点无关的 raw trace、完整 transcript、private/hidden reasoning、Fact observation、工具参数/结果正文或其他 ignored 历史运行正文；
  teacher 生成与 reviewer 不需要这些内容。
- Plan 054 完整模型权重内容或任何其他模型权重。tokenizer-only 工作应明确只打开冻结 tokenizer/template/special-token 文件。

### Git-ignored 与主工作区边界

所有 tracked 合同、代码、测试、冻结数据、manifest、数据卡和 bundle 都在
`.claude/worktrees/059-publication-critic-training-data` 完成并提交，主工作区不产生 tracked 修改。

linked worktree 不共享主根的 ignored `eval-data/`，因此下列执行期资产必须直接写入主物理仓库根的
`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan059/` 或等强、明确的 Plan 059 子命名空间，并在交付中单独汇报：

- 从明确完成任务中有界提取的公共 source projection；
- raw Scenario/Candidate、generator/reviewer 结构化输出、返修/排除和逐条 dedup 明细；
- split/finalize 的临时产物、token census 明细和 consumer smoke 临时输出。

现有 Plan 054 tokenizer/环境只读复用，不移动、不清理；Plan 058 和来源不明 ignored 资产零读取、零写入、零清理。任务内清理只针对 059 自己明确
创建且确认不再需要的临时对象；必要 raw generation/review/finalization 证据至少保留到 Plan 059 独立验收与用户交付完成，并在交付时列明继续
保留供 B1b 使用或可安全清理的 059 自有资产。

## 3. 硬约束

以下约束只冻结数据正确性、输入语义、安全与交付边界，不固定执行者可替换的实现路线。

1. **Plan 054 v4 是唯一模型输入上游。** 正式 Candidate 必须消费同一 `PublicationPacket v1` 机械约束、qualification rubric、两条有序
   message、control-token-safe render、exact tokenizer/template/special-token identity、16,384-token window 和 whole-continuity omission
   语义。Plan 054 v4 implementation manifest 已绑定的输入/评价实现不得修改，数据设施不得近似复刻 packet/render/validator；若这些冻结合同
   本身有 correctness 缺陷，停止生成并返回上游修正。
2. **先冻结覆盖和停止条件，再冻结正式运行身份。** 合成前的 coverage/stop lock 至少绑定 schema/版本、来源 allowlist、teacher 角色、稀疏最低
   覆盖矩阵及逐格最小值、目标量/硬上限/停止与 NO-GO 条件、split 比例或容差、真实/合成策略、pair 数量边界、review/disagreement 状态机、
   group/dedup/near-duplicate 规则、输入 identity 和 C1/C2/C3 membership。先用代表性小批次暴露 prompt、解析和全链路问题；确认后在扩大生成前
   再以 clean commit 或等强内容 hash 冻结实际 teacher identity、prompt hashes、实现与配置。后续语义性变化须升级版本并使受影响集合重新生成/
   复核/切分/冻结。达到最低覆盖、review 质量和合理冗余后按停止条件收口，不为扩大数量本身继续生成。
3. **输入与监督物理隔离。** renderer 和 tokenizer API 只接收现行 packet 与固定 rubric；Scenario、Binary/defect/rationale、split、pair direction、
   source/generator/reviewer、review 状态和设计标签不能通过自由 metadata bag、模板注释或隐藏前缀进入模型输入。Candidate/Pair 可以采用专用数据
   schema，但不能成为第二份 packet schema或第二 renderer。
4. **监督语义不可混淆。** 每个正式 candidate 恰有一个 reviewer 接受的 Binary label。Boundary/Q± 必须为同 scenario/group 内的
   `PASS > REWRITE` 单一 hard-dimension 原子差异；Within-PASS 必须为同核心语义下 `PASS > PASS` 的软偏好。pair 两端都保留自己的 Binary
   监督且同 split；所有 pair 两端的最终 continuity omission 数量与非 candidate 公共 context 必须相同，Q± 的 candidate 部分还只能改变声明的
   单一 hard dimension。不收录方向含糊 pair、
   `REWRITE > REWRITE` 或用表面简短/正式/evidence 外观替代 qualification 的偏好。
5. **teacher 角色分离但无额外交接。** 直接执行本任务的 GPT-5.6-sol 可以承担 generator，不再等待另一教师批次；reviewer 必须使用未继承
   generator 隐藏对话的独立 GPT-5.6-sol 子会话。记录实际 model、reasoning effort、日期、角色、prompt hash 及工具可提供的 session/run
   identity；不建设委员会、严格盲测或人工平台。teacher reference 不是人类真值，最终数据卡必须保留这一限制。
6. **真实锚点只提供公共场景。** 只提取任务已明确选择、可可靠恢复、与 Publication Critic 相关的 event-local 公共状态，不复制无关完整运行
   正文。相同真实 source、同一 Scenario、其改写/模板变体和所有 pair 端点必须共享可追踪 group；source identity 留在监督 metadata，不进入
   packet。Plan 054 cohort 可以作 anchor/dedup 参照，但没有任何样本自动继承正式 split 身份。
7. **先分组、后分层切分。** split 的原子单位是 source/scenario/pair/template/near-duplicate 关系闭包，而不是单行 candidate。算法必须在组级
   满足 data-design lock 的标签、四类 publication、hard slice 与监督覆盖，无法同时满足时补足/返修候选或给出数据 NO-GO，不能拆组换取比例。
   unseen-test 身份一旦正式冻结，后续训练/bundle 生产入口必须默认拒绝读取或混入它。
8. **复核分歧允许收敛，不允许造一致。** schema/格式错误、覆盖不足、非原子 pair、错误标签和 reviewer 退回可自主返修、重生成、重新复核或
   排除；不设一次失败即停止或人为 retry 上限。若合理修复仍无法形成可信单维 pair，则降级为普通 Binary/mixed 或排除；不得重复询问 reviewer
   直到获得预定结论。所有正式样本必须有一个终态 review decision，排除项不混入冻结集合。
9. **全量 exact-input 验证。** finalizer 必须对全部正式 candidate 重新执行产品 packet validation、allowlist render、registered control-token
   guard、`truncation=False` exact tokenization、16k fitting 和 token bucket 对账；pair 只引用这些已验证 candidate。任何 candidate semantic 字段
   均不得 token 级截断，continuity 只能整条省略并显式记录；仍 overflow、identity 漂移或 validator/render 不一致时 fail closed。
10. **重复与捷径检查相称而非形式主义。** exact/near-duplicate group、source/template 关系、label/split/role/length/style/Unicode/Evidence 聚合
    必须可复算并进入 manifest/data card；发现明显跨 split 泄漏或简单外观即可稳定猜标签时应补样本、重分组或排除。无需承诺消除所有潜在统计
    相关，也不为此建设 embedding 服务、复杂语义审计或因果证明。
11. **冻结是内容身份，不是只改 manifest。** 正式 freeze 绑定设计锁、schemas、prompts、teacher identities、所有数据/pair/bundle 文件、
    exact input identity、split/group/dedup/token 统计和生成代码 commit。冻结后若改变 candidate 语义、label、pair、group、split 或 input identity，
    必须升级数据版本并重新冻结完整受影响集合；不得原地只修 manifest/hash 或无痕覆盖旧 freeze。
12. **消费合同在本地关闭。** C1/C2/C3 的累计成员关系和 train-only smoke bundle 必须由同一严格 consumer 验证；bundle 只从 train 派生且默认
    训练入口不可触达 validation/unseen-test，显式评价模式仍可读取相应 split。consumer 验证输入与监督即可，不实现训练 loss、dataloader 性能
    优化、模型 forward 或 recipe 探索；M3-B1b 不得成为重新切 split、补标签或改 pair 语义的场所。
13. **Plan 058 与外部资源边界不让位。** 059 的开发用 Codex teacher 子会话、纯 Python/逻辑测试、exact-tokenizer-only census、文档和审查
    可以与 058 并行；Docker、重型 Cargo/Bazel、完整模型或模型权重下载/加载、本地 GPU/大内存推理、项目真实 API 批量任务、训练和上传不在
    本次授权内，058 正式释放也不会自动解锁。缺失时补取冻结 revision 的明确 tokenizer/template 文件仍按 §2 的窄授权执行。即使没有活动容器
    也不能自行认定 058 已释放；059 不借用 058 的预算或资源身份。本任务新增项目付费预算为 `0 USD`。
14. **普通失败自主修复，原则冲突才停。** 执行者可在范围内修 schema、解析、生成、复核、split、dedup、tokenizer、manifest、fixture、consumer
    和测试问题，补足覆盖并重跑；不因一次窄失败停工。只有上游冻结语义缺陷、必须越权触碰 058/外部状态/付费资源、未知高危动作，或合理修复后
    仍无法满足覆盖、split、输入或消费原则时才暂停并报告。最终数据不足时给出 NO-GO，不为凑 GO 弱化门禁。
15. **证据分层且不夸大。** 开发用 Codex teacher output、独立 reviewer、pure/focused test、exact tokenizer census 和 consumer smoke 分开
    表述；skip/未运行不写成通过。M3-B1b 数据 GO 只表示冻结数据可进入付费资格 smoke，且必须等待本分支经用户批准合入 main；不表示训练、
    模型质量、部署或产品资格。
16. **Git 交付止于 worktree commit。** 执行前后检查 main、059 和其他 worktree 的 Git 状态，保护未知修改；只 stage 059 允许文件，检查
    staged diff/大文件/敏感边界并本地提交，保持 059 clean。`doc/WBS-COMPLETED.md`、顶层 WBS 中已授权方向指针以外的同步、合并、推送、
    分支归档和 worktree 删除必须等待用户批准。

## 4. 软性建议

以下建议基于 `main@2ac4e8501a7a186e0c9ff3f560acefc6a9feb802` 的 live 设施，不固定执行者的实现路线。执行者可依据代码、实际数据和
维护成本采用更优的等强方案，并在关键决策记录中简要说明有实质影响的选择。

- Plan 054 的 `eval/rondo_eval/publication_critic/contract.py`、`render.py`、`tokenization.py` 与 `identity.py` 已负责 packet、render、exact
  token 和内容 identity，且已进入 v4 implementation identity；保持这些文件不变并从新增能力直接调用。数据职责可以放在新的
  `training_data/` 子包或若干小模块，避免继续扩张已经较大的 evaluation runner/contract 文件，也不要求这一特定布局。
- 现有任意 packet 的严格校验实现位于冻结模块的内部 seam；新增模块可以用很薄的 adapter 调用现行严格校验，也可以采用不修改冻结文件且不复制
  校验规则的其他方式。不要强行扩展固定 24 条 Plan 054 cohort 的 `load_sample_corpus()`。
- 可以采用“设计草案与小批 rehearsal → 设计锁 → 分批 raw generation/review/抽样 → clean full finalization → freeze/consumer”的简单批处理，
  JSONL 与小型 JSON manifest 已足够。原始候选和逐条返修留 ignored 区，Git 只保留最终正式数据与紧凑聚合；无需数据库、队列平台或审计服务。
- data-design lock 的覆盖矩阵不必穷举所有维度笛卡尔积。优先给产品四类、五项 hard requirement、Plan 054 弱项和三类监督设置可解释的
  最小格，再用 mixed/style/Unicode/长度变化补捷径；同时设置目标量、硬上限和停止条件，达到覆盖与质量门后停止，避免无意义扩大。
- GPT-5.6-sol 执行者可先产 Scenario 蓝图，再生成同 group 的 Binary/原子 pair 候选；每完成一个小批次就先验证解析、覆盖和 pair 抽样，必要时
  修 prompt/合同后再继续。reviewer 使用同一冻结产品合同输出结构化
  `accept/revise/downgrade/exclude` 及简短公开 rationale。若更适合分批并行生成或采用不同结构化状态，执行者可以自主选择。
- near-duplicate 可以从规范化 model-visible packet/render 的简单 n-gram/Jaccard/containment 或其他轻量、可复算方法起步，并先 union 明确的
  source/scenario/pair/template 关系；相似度主体应排除所有样本共享的固定 rubric/framing，并分别关注 candidate 与带 local context 的可变内容。
  阈值用小型人工 spot-check 冻结即可，不需要 embedding 模型或严格语义等价证明。
- grouped stratification 可以用确定 seed 的搜索/启发式分配，只要结果稳定、约束可检查且无法满足时 fail closed；不需要引入通用优化器。
- Pair 只存 endpoint candidate ID、kind、preferred/dispreferred direction 和原子/软偏好说明，避免复制 packet 正文。最终三 split 可以按维护成本
  选择“一份 candidate registry + split/group 字段”或分文件布局，只要 train-only bundle 的物理排除和 consumer 默认拒绝成立。
- 可以参考 `training/local-approval-synthetic-v1/` 的 tracked data card、manifest、hash、group split 与 ignored raw batch 分层，但不要复用它的
  approval schema、label 语义或把其审计细节机械搬入 Publication Critic。
- 优先复用主物理根中 Plan 054 已保留的 exact tokenizer 和环境。若环境复用造成依赖漂移，可在 Plan 059 ignored namespace 建轻量 tokenizer-only
  环境并冻结依赖；不要复制模型权重，也不要为 tokenizer census 启动模型 backend。
- 测试按改动分层收敛：先 pure schema/group/split/bundle，再跑现有及新增 Publication Critic focused Python tests，最后对全量正式数据执行一次
  exact-tokenizer census。本任务不运行 Rust/Bazel 或全 workspace 门禁。
- 独立验收重点抽查数据语义与 group closure，复算 manifest/hash/split/token aggregates，并确认 train-only bundle 入口与默认训练路径无法触达
  validation/unseen-test；正式 consumer 可以在显式评价模式读取对应 split。普通 finding 修复后重验相关集合即可；语义或 split 变化则按硬约束
  重新冻结完整受影响集合。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已核实规划基线为 clean `main@2ac4e8501a7a186e0c9ff3f560acefc6a9feb802`，与 `origin/main` 一致；Plan 054 已非快进合并并推送，
  054 worktree 已移除且分支已归档。
- 已从该 clean main 创建 `.claude/worktrees/059-publication-critic-training-data`，分支
  `worktree-059-publication-critic-training-data`；创建时 Plan 058 的正式/commissioning worktree 保持独立，未读取其内容。
- 已阅读根/`multidev/` AGENTS、README、顶层/方向 3 WBS、plan 模板、Plan 050/054/057、Publication Critic 产品合同、Plan 054 v4 最终验收、
  eval-data/training 分层规范和现有 Publication Critic 数据/输入设施。
- 已确认主物理根中 Plan 054 的 exact tokenizer、Plan 054 raw namespace 与任务环境目录仍存在，Plan 059 ignored namespace 尚未创建；本轮未打开
  模型权重或 ignored 运行正文。
- 已把用户给出的 Plan 059 宏观目标收敛为本 ExecPlan；样本数量、split 数值、teacher 实际身份、prompt 和内部实现路线留给执行者先在
  data-design lock 中依据 live 设施冻结。
- 已按用户补充决定：实际执行会话为 GPT-5.6-sol 并直接负责合成；通过代表性小批次与批间抽样先暴露问题，打通全流程后才冻结实现/配置并运行
  clean full finalization；规模由目标、硬上限和停止条件约束，不以扩大样本量本身为目标。
- 已由三个只读子智能体分别检查 Plan 054 设施复用边界、真实锚点/group split 边界和 plan/WBS 合同，并由规划者按 live 文件复核；据此明确
  v4 identity-bound 文件只读、Q± 的最终 context/omission 同一性、group closure 和主根 ignored 资产边界。该复核只验收规划，不替代实现后验收。

### 当前工作

- revision v3 正式数据、完整冻结门禁、最终干净上下文聚焦审查及 staged/敏感/体积/状态检查均已完成；本计划随 059 本地提交冻结，
  等待用户与计划制定者验收。执行者 provisional 建议不升级为计划制定者最终数据 GO。

### 本任务剩余步骤

- 任务内无剩余实现步骤；计划制定者最终验收、获批主线整合与任何 M3-B1b 授权均在本任务外。

### 阻塞项

- 当前无阻塞。Plan 058 尚未以正式 campaign/账本/reservation/资源后置记录和用户交接明确释放全局运行槽；这不阻塞本任务获授权的开发用
  Codex teacher、纯逻辑、tokenizer-only、文档与审查工作。本计划本身也不授权重型 Cargo/Docker/完整模型/项目真实 API/训练，058 后续释放
  不会自动扩大 059 范围。

### 当前验收状态

- v1 `formal-v3` 的结构、review、token 与 consumer 门禁通过，但干净上下文审查复算出固定 Q-/Within-PASS marker 在多个 split 中标签独占；
  该结论推翻 v1 provisional GO，失败冻结只保留为 ignored 修复证据，不提交训练正文。
- revision v2 formal-v6 的 teacher、split、dedup、token 与 consumer 门禁虽通过，但最终干净审查复算出 `candidate_tokens >= 80`
  对 6 个 scope Q- 形成 6/6 REWRITE、0 false positive 的跨 split 捷径；v2 tracked 候选未提交，失败冻结保留为 ignored 修复证据。
- revision v3 rehearsal-v9 已完成 17/17 candidate、9/9 pair 独立 accept，scope Q+/Q- 字符长度分别为 121/127 与 142/146，
  scope-04 的 Boundary 与 Within-PASS 方向均成立；10,941-token census、text/length shortcut、manifest 和 consumer 门禁通过。
- revision v3 `formal-v8` 已从 clean implementation freeze 生成，独立 GPT-5.6-sol reviewer 对 72/72 candidate 与 36/36 pair 全部
  accept，remaining finding 为 0；正式冻结为 36 scenario group、42/16/14 split、39 PASS / 33 REWRITE、30 Boundary / 6 Within-PASS。
- 11 条 near-duplicate edge 全部同 scenario，Plan 054 reference match、跨 split label-exclusive 文本 shortcut 与双向 exact-token 长度
  threshold shortcut 均为 0；72 条 exact-token census 共 53,294 tokens，单条 553–2,753，continuity omission 为 0。
- 严格 manifest/frozen consumer、C1/C2/C3（42 Binary / +18 Boundary / +3 Within-PASS）、默认 holdout 拒绝、train-only smoke bundle
  和 44 项 focused Python tests 通过。最终干净上下文预审复算上述数据、语义、输入隔离、split/dedup/token/freeze/consumer 与文档事实后
  PASS，remaining finding 为 0。执行者 provisional 数据 GO；计划制定者最终验收、主线整合与 M3-B1b 解锁均不在本任务内。

### 交接边界

- 执行者对模块布局、数据文件拆分、合理规模、split 数值、teacher prompt、生成批次、近重复算法和 consumer CLI 保留自主权；审查者只按
  硬约束、冻结产物和完成标准验收，不把软建议或个人实现偏好升级为门槛。
- 本任务完成后冻结此计划；M3-B1b 只有在 Plan 059 数据 GO、独立验收通过且经用户批准合入 main 后才解锁。B1b/B1c 的训练路线、预算和
  实施细节继续只由 WBS 和各自新 ExecPlan 决定。
- 执行者本地提交 059 worktree 后停止，向用户与本计划制定者交付 commit、测试/数据证据、ignored 主根资产清单和 GO/NO-GO；不得自行合并、
  推送、归档、删除 worktree 或重命名分支。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 059 直接继承 Plan 054 v4 输入/render/tokenizer/window 合同，不建设第二套模型输入 | 训练、评价与未来 runtime 必须审同一个 publication | packet、render、tokenizer、consumer | 已采纳 |
| 002 | 合成前先冻结 coverage/stop lock，小批打通后再冻结 exact prompt/实现/配置；ExecPlan 不拍死具体数值 | 既让规模由覆盖和停止条件决定，又避免过早冻结正式运行身份 | 规模、split、teacher、停止条件 | 已采纳 |
| 003 | 每个 candidate 都有 Binary；Q± 为 `PASS > REWRITE` 原子 hard pair；Within-PASS 为少量 `PASS > PASS` soft pair | 保持 hard qualification 与软偏好层次，避免 pair 语义扭曲 | schema、review、C1/C2/C3 | 已采纳 |
| 004 | C1=全部 train Binary，C2=C1+train Boundary/Q±，C3=C2+train Within-PASS | 同一 lineage 累计加入监督并保留前序样本，且不提前定义训练 recipe | consumer、bundle、B1b handoff | 已采纳 |
| 005 | 真实场景只作少量公共锚点，teacher synthesis 为主体；generator/reviewer 用独立开发用 Codex 会话 | 提高覆盖与可控性，同时保持必要角色分离而不建设委员会 | source、generation、review | 已采纳 |
| 006 | split 原子单位是 source/scenario/pair/template/near-duplicate 关系闭包 | 防止同源、pair 端点和近改写跨 split 泄漏 | split、dedup、manifest | 已采纳 |
| 007 | 最终数据与合同按体积门限进入 `training/`，raw generation/review/finalize 资产进入主物理根 Plan 059 ignored namespace | linked worktree 不共享 ignored 数据，且最终训练资产需要随 commit 交付 | 数据分层、Git、主工作区 | 已采纳 |
| 008 | Plan 059 只执行开发用 Codex teacher、纯逻辑、tokenizer-only 和文档审查；Plan 058 释放不自动扩权 | 保持全局重型资源与预算身份隔离，也让本任务授权边界无歧义 | 并行、资源、授权 | 已采纳 |
| 009 | 普通数据/设施问题允许返修和重跑；上游语义冲突或最终数据不足才停/NO-GO | 给 AI 执行充分收敛余量，同时不跨原则边界 | 失败恢复、验收 | 已采纳 |
| 010 | 本次规划提交一次性同步用户确认的 Plan 058 active 边界；059 实施只更新方向 3 指针，方向 1 结果和 COMPLETED 留给对应任务/主线整合 | 让权威入口一致，同时不替 Plan 058 写未验收结论 | 文档、并行合并 | 已采纳 |
| 011 | GPT-5.6-sol 执行者直接合成，独立 GPT-5.6-sol 子会话复核；先小批打通和抽样，再冻结并 clean full finalization | 减少交接与整版返工，保留已验证进度并控制无意义的数据合成成本 | generation、review、freeze | 已采纳 |
| 012 | coverage/stop lock 冻结正式目标为 72 candidate、30 Boundary、6 Within-PASS，达到全部稀疏覆盖后立即停止 | 在覆盖四类 publication、五项 hard requirement、三 split 和关键薄弱切片的同时避免无意义扩量 | scale、coverage、stop | 已执行 |
| 013 | rehearsal 与正式分批 review 的真实 finding 只重生成受影响 endpoint，并以逐行内容相等门禁复用未变化 review | 保留有效生成进度，同时确保任何 Scenario/packet/supervision/pair 漂移都触发局部重审 | review、repair、freeze | 已执行 |
| 014 | v1 的固定 Q-/Within-PASS 文本 shortcut 判定数据 NO-GO；revision v2 用逐场景显式文本和跨 split label-exclusive char-4-gram 门禁替代 | 防止未来 validation/unseen 指标只复现标签模板 | 数据 revision、shortcut、split | 已执行 |
| 015 | formal-v5 teacher finding 的 6 个 continuity 与 5 个 scope Q- 只做局部语义返修；rehearsal-v6 验证目标维度后，formal-v6 对 72/36 全量重审 | 保持 hard negative 与 pair 原子性，不把软质量差异冒充 qualification failure | teacher review、pair、freeze | 已执行 |
| 016 | v2 的 scope Q- 超长捷径判定数据 NO-GO；revision v3 使 scope Q+/Q- exact-token 长度相近且交错，并新增双向 exact-token threshold 门禁；scope-04 soft endpoint 保留相关重复以恢复可信软方向 | 长度不是 qualification，正式 split 不能让极端长度完美预测标签，Within-PASS 方向必须真实 | 数据 revision、token census、shortcut、pair | 已执行 |
| 017 | revision v3 以 formal-v8 全量独立复核和同内容双物化作为正式冻结证据；失败 v1/v2 只保留 ignored 修复证据，不进入 tracked training release | 正式版本必须绑定已修复语义、clean generation identity、全量 teacher 终态与 exact-token/consumer 门禁 | review、freeze、training handoff | 已执行 |
| 018 | 最终干净上下文预审独立复算 v2 finding closure 与 v3 全链路后 PASS，remaining finding 为 0；仍只给执行者 provisional 数据 GO | 提前关闭普通 correctness finding，同时保留计划制定者最终验收和 M3-B1b 解锁边界 | final review、handoff | 已执行 |
