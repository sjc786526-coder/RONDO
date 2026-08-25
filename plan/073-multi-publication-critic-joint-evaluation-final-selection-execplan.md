# Plan 073：M3-C2 Publication Critic 联合横评与最终选择 ExecPlan

> 本计划是 M3-C2 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、候选范围、冻结数据、原则边界或完成标准，应暂停并请求用户确认；普通环境、依赖、连接、进程、
> launcher、测试和局部实现问题应在范围内自主修复、续跑或重跑。
> 本计划只描述 M3-C2；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

对 Plan 071 已确认具备本地部署资格的 exact base、C1、C3 使用相同的冻结评价资产和评价规则完成联合横评；在
GPT-5.6-sol 冻结参考标签、Opus 5 独立质量判断、False PASS/False REWRITE、边界表现、延迟和本地资源开销之间作出可解释的
综合选择，冻结最终模型、产品判定 threshold 和目标本地运行配置。

若 validation 阶段形成可接受的暂定选择，则在选择规则和“模型 + threshold + 运行配置”锁定后，才释放 unseen-test，执行一次
逻辑上的最终盲验。任务必须形成以下一种诚实终态：

- `GO`：锁定组合通过 validation 选择门与 unseen-test 确认，可解锁 M3-D；
- `NO-GO`：有效评价证明没有候选达到发布要求，或锁定组合被 unseen-test 否决；
- `INCONCLUSIVE`：基础设施、异构判断或必要证据不足，无法作出有效选择或盲验结论。

exact base、C1、C3 地位相同，允许 exact base 获胜；最后 checkpoint 或微调模型没有默认优先权。本任务以得到可靠决策为成功，
不以必须得到 `GO` 为成功。

### 完成/验收标准

- [ ] exact base、C1、C3 的权重、tokenizer、输入/scalar identity 与 Plan 071 资格身份复核一致；C2 不进入加载、评价、修复或选择。
- [ ] 在正式 validation 输出产生前冻结联合评价与选择协议，至少明确：主要质量维度、False PASS/False REWRITE 的处理、边界指标、
      threshold 选择方法、必要质量底线、延迟/资源的使用方式、异构判断的作用和无法区分时的处理。协议可以在 commissioning 期间完善，
      但不得按正式赢家结果倒推。
- [ ] 三个候选使用同一 validation cohort、输入/render/tokenizer/window/scalar 语义、目标 deployment runtime 类别、指标定义和
      threshold 选择方法，得到完整、有效、可比较的正式结果。相同方法可以为不同候选得到不同数值 threshold；不得为单个候选另开优惠规则。
- [ ] 每个候选至少报告 confusion、False PASS、False REWRITE、总体质量、适用的 slice/pair/boundary 指标、typed failure，以及足够支持
      选择的逐项或聚合结果；不得用单一总分掩盖错误类型或边界退化。
- [ ] 在同一目标本地运行口径下取得 load/cold、warm latency、吞吐或有界压力、RSS、VRAM、失败与清理事实；已有资格证据可以复用，
      但最终配置发生变化或比较口径需要时应补测，不把不同 runtime/config 的数字直接混排。
- [ ] 暂定胜者的最终 model/scoring identity、精确 threshold 和运行配置进入现有 Plan 055 service descriptor，并以同输入确认 offline/service
      verdict parity、有界调用和 clean shutdown；服务接缝未变时无需机械重跑 Plan 068/071 的完整故障矩阵。
- [ ] Opus 5 通过 Claude Code 订阅入口完成必要的独立质量判断。Judge 只接收产品合同所需 rubric 与去除 GPT 标签、pair direction、split、
      模型身份、模型 score/verdict 的盲化评价内容；其结果记录实际模型标识、日期及 prompt/package 身份，以预先说明的方式补充
      确定性指标，不单独替代冻结参考和本地实测。
- [ ] GPT 冻结参考与 Opus 判断各自保留身份、分母和分歧说明；不得把 Opus 结果写回监督资产，也不得用投票或合并新标签制造新的“真值”。
- [ ] Judge 的覆盖/抽样、批次、结构化输出和聚合方式足以解释其对选择的影响；执行者与 Judge 使用上下文隔离的子智能体或等强组织，
      不建设多模型委员会、长期人工评审平台或通用 Judge 服务。
- [ ] 调试阶段允许保留已验证进度，从未打通处自主修复、续跑和重跑；全链路打通后再冻结 source、资产、协议、候选运行配置和程序身份，
      从 clean tracked source 与新的空正式 namespace 完整运行一轮作为唯一有效 validation 正式结果。
- [ ] validation 后用冻结协议作出暂定选择并写出不可歧义的 selection lock；若没有候选达到门限，直接形成 `NO-GO`，unseen-test 保持封存。
- [ ] 只有 selection lock 有效时才允许读取、render、score 或 Judge unseen-test；同一锁定组合完成一次逻辑盲验。基础设施中断可在同一身份和
      namespace 内安全续跑，不能借续跑改候选、threshold、配置、协议或已见结论，也不能把 unseen-test 用于返调或改选 runner-up。
- [ ] unseen-test 通过则形成 `GO`；锁定组合被有效 unseen 证据否决则形成 `NO-GO`；盲验在已释放数据后因不可恢复的设施/正确性问题失效则
      形成 `INCONCLUSIVE`，不得再开第二轮 unseen-test 搜索有利结果。
- [ ] 结果由项目内轻量入口复测和归档：ignored 目录保存必要 raw/Judge/运行证据，tracked 结果只保存足够复算和理解决策的小型聚合、身份与结论，
      可以保存复测所需的任务专用 rubric/prompt/schema，但不提交模型权重、Judge 原始响应、评价正文、私有映射或敏感内容。
- [ ] 运行受影响的 Publication Critic pure/fake/focused tests、必要的真实模型横评、仅在 Rust 接缝实际变化时运行相应定向 Cargo 门禁，
      并执行格式/生成物检查和 `git diff --check`；未运行、skip、fake、订阅 Judge、真实本地模型和 Docker 证据分别表述。
- [ ] Plan 069 的工作树、未提交修改和运行现场未受干扰；重型 Cargo、Docker、真实本地模型/GPU 与 Plan 069 及其它重型任务按全局资源门串行。
- [ ] 更新本计划当前状态和一份精炼 `agent_log`，提交 clean Plan 073 task branch，交计划制定者独立验收；没有已知阻塞性的
      correctness/functionality 问题。执行者不把任务分支合并进 `main`，不推送、不归档分支或删除 worktree。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 内与 M3-C2 直接相关的数据消费、候选运行、联合指标、threshold/selection、Judge 交换、
  unseen release、结果归档和 launcher 能力。职责契合时复用现有模块；若继续挤入 Plan 054/068/071 schema 会扭曲历史，可新增架构契合的
  M3-C2 专用模块或 namespace。
- `eval/tests/test_publication_critic_*`、必要的小型 template/config/schema/fixture、`eval/results/publication-critic/` 下的小型正式聚合结果
  及相应说明；新增测试只覆盖本任务真实新增或改变的行为。
- 仅当现有真实服务接缝无法表达最终运行配置或取得必要测量时，窄改 `multidev/codex-rs/publication-critic/` 及直接相关测试/构建定义；
  没有真实需要时不修改 Team State、`core`、thread-store、app-server 或 TUI。
- 仅随真实依赖或 schema 变化机械更新并审查相应 lock/生成物；不为本任务预装通用评价框架或无关依赖。
- 本计划“当前状态/关键决策记录”和一份精炼 Plan 073 `agent_log`。共享 WBS/WBS-COMPLETED 的最终状态同步留到独立验收和用户批准
  主线整合时基于最新 `main` 窄完成，执行分支只提供准确建议 delta，避免覆盖 Plan 069 的并行文档变化。
- 主物理仓库根的 ignored `eval-data/publication-critic/plan073/`，用于 commissioning、formal validation、selection lock、Judge 与 unseen
  原始结果；确有需要时可创建 `eval-data/envs/publication-critic-plan073/` 或任务专用 cache/target。
- 只读复用主物理仓库根现存的 Plan 068/071 exact base、C1、C3、checkpoint/manifest、环境、正式资格和服务二进制；优先复用并验证现有
  工件，不复制整套模型，不改写旧 namespace、env、target 或已验收结果。
- 只读消费 tracked `training/publication-critic-v8/` 的 validation；selection lock 生效后，只向唯一逻辑盲验 campaign 释放 unseen-test。
  同一冻结 campaign 内允许必要的完整性读取和无 terminal 项续跑，但不得开启第二个选择/确认 campaign。可以复用 Plan 054/068/071 的
  非 unseen 结果与现有本地资源测量事实，但不能用历史异口径数字替代本轮缺失的可比较证据。
- 通过现有 Claude Code 订阅使用 Opus 5 做本任务必要的盲化异构质量判断；只发送 Judge 完成判断所必需的冻结、非密钥评价内容。
  这不授权直接 API 调用、文件上传、远端资产创建或向模型发送权重、私有运行正文、凭据和无关仓库内容。
- 普通项目依赖、公开只读源码/文档查询；获得重型资源窗口后，在当前本地 WSL/GPU 上进行有界真实模型加载、推理和资源测量。
- 只有现有正式路径确有必要时，使用一个明确的 task-owned Docker image/container；Docker 不是默认要求，且只可清理本任务创建的对象。
- 范围内 commissioning、修复、续跑、重跑、独立审查 finding 整改和本地 task-branch 提交。若 Plan 069 先进入 `main` 且相关共享事实变化，
  可在正式冻结前把必要的最新主线变化安全、窄地同步到 Plan 073 分支，但不得把 Plan 073 合并进 `main`。

### 不允许修改或执行

- 修改、覆盖或重新生成 exact base/C1/C3、tokenizer、Plan 064/v8 candidate、label、pair、split、review/manifest，或重新训练、继续训练、
  合并 adapter、量化、探索新底模/候选/部署路线。C2 保持 `NOT_QUALIFIED`，不恢复、不修复、不评价。
- 改变 Plan 054 输入/render/tokenizer/window/scalar 语义、Plan 055 服务协议/identity/typed failure 信任边界、Plan 057 默认关闭与
  rewrite/fallback/cancel/store 语义；如确需改变稳定产品语义，应停止并请求上游决定。
- 把 unseen-test 用于 commissioning、threshold 调整、候选替换、配置优化、Judge 规则修改、训练或第二次确认；不得提前输出其正文、标签、
  pair direction 或逐项结果给执行/选择上下文。
- 默认启用 Publication Critic、修改产品默认配置、执行 M3-D、开展端到端协作收益研究或把离线结果外推为普遍产品收益。
- 建设通用模型评价平台、数据平台、Judge/评审委员会、长期 registry/database、复杂审计/可信/签名链、第二套模型服务或第二套 Team State/trace。
- 直接付费 API、真实 API 批量测评、云 GPU、RunPod/HF Job/Endpoint/Space/Repo/Bucket、远端训练/存储、数据或权重上传、发布、产生新费用、
  上游升级或其他远端状态修改。
- 读取、修改、stash、清理或依赖 Plan 069 工作树的未提交/ignored 内容；修改其 Durable Session、thread-store、app-server/TUI 语义或运行现场。
- 无关全 workspace 测试、CI/PR、推送任务分支、把任务分支合并/rebase 到 `main`、分支归档/重命名或 worktree 删除。

### 不允许读取/查看

- `.env.local` 内容、任何 token、API key、access key、secret、私钥、密码或个人配置；本任务不需要这些凭据。
- selection lock 生效前的 unseen-test 正文、标签、pair direction、模型输入投影或 Judge 材料。
- 与任务无关的真实 publication/transcript/private reasoning、Fact observation/raw evidence、其它 worktree 未提交内容、项目外个人文件或其他仓库。

### Git-ignored 与物理根边界

tracked 代码、测试、计划、轻量结果和日志全部在
`/home/sjc/desktop/RONDO/.claude/worktrees/073-m3-c2-publication-critic-selection/` 修改并提交；主工作区不得产生 tracked 修改。

linked worktree 不共享主根 ignored `eval-data/`。因此 Plan 073 的模型运行、Judge 原始交换、validation/unseen 原始结果、可能的新 env/cache/target
必须直接落在主物理仓库根的 task-owned ignored namespace。这些是后续执行中预计必须直接在主工作区产生的内容，不是本次规划提交的一部分。
执行者交接时应列出实际创建/修改的 ignored 路径、大小、权限与保留状态；只清理能精确确认由 Plan 073 创建且不再需要的临时对象。

## 3. 硬约束

以下约束只冻结选择公平性、盲验边界、稳定产品语义、资源安全与诚实证据，不预先锁死指标权重、Judge 批次、模块布局、阈值优化算法或
进程组织。

1. **候选和数据固定。** 正式候选只有 exact base、C1、C3；validation 和 unseen-test 只来自冻结 v8，正文、label、pair、split 不修改。
   三者继续消费同一个 PublicationPacket/render/tokenizer/window/scalar 产品语义；C2 和新候选不进入任何补位或返修路线。
2. **先打通，再冻结正式口径。** commission 阶段可以有界试跑、保存进度、修复设施并重新组织实现，不设机械失败/重试次数；正式 validation 前才
   冻结具体协议、source、候选/config、Judge 方案和程序身份。从新 namespace 完整运行后，只有同一 freeze 下的完整轮可以成为正式结果。
3. **选择规则先于正式赢家。** 正式 candidate 输出产生前必须明确质量底线、比较维度、threshold 选择方法、冲突/并列处理和 Judge 的作用。
   可比较要求是同一规则与搜索空间，不是强迫不同模型共用同一个数值 threshold；最终锁定的是一个不可拆分的模型/threshold/config 组合。
4. **错误类型不能被平均。** False PASS、False REWRITE、边界/Within-PASS 或等强难例必须分别可见，发布质量是首要选择依据；延迟与资源用于
   可用性门和有依据的取舍，不得让更快模型掩盖不可接受的质量，也不得用一个加权总分替代关键明细和最低门。
5. **Opus 判断保持独立。** Judge 上下文不得暴露 GPT 标签、pair 方向、split 名、模型身份/阶段、模型 score/verdict 或先验赢家叙事。
   执行与 Judge 至少以不同子智能体/上下文组织；Judge 输出怎样进入最终选择应在正式前说明。GPT/Opus 结果分别报告分歧，不投票生成新标签；
   Opus 是异构质量视角，不是新的唯一真值源。会话中断、传输截断或 schema 无效时可用同一冻结 rubric/package 和 Opus 5 补齐或重试
   受影响批次，但不得因判断内容不满意而重判。Judge commissioning 优先使用非正式、非 unseen fixture 或 fake 结果；正式 validation 包只在
   rubric/schema/package identity 冻结后发送，全部批次通过身份、完整性、唯一性校验前不向 selection 暴露部分聚合，已有有效 terminal 不重问。
   每批记录订阅界面显示的模型标识和日期；不同模型身份不得混入同一正式 aggregate，无法确认或继续使用 Opus 5 时为 `INCONCLUSIVE`，
   除非用户另行改变异构模型边界。
6. **本地运行口径一致。** 三候选按同一目标 runtime 类别、输入批处理语义和资源测量边界运行；一次只加载一个模型。若最终配置与 Plan 071
   资格配置相同，可复用未漂移的资格事实；任何会影响 latency、资源或产品 verdict 的变化都须在本轮相称复测。
7. **unseen 只确认锁定选择。** selection lock 之前，代码、测试、commissioning、Judge 和人工分析都不得访问 unseen 内容。
   锁定后只有一个逻辑盲验 namespace；可以在 freeze 不变且未借助结果调参的前提下恢复技术中断，但不能重选模型、改 threshold/config、换协议、
   追加 Judge 规则或开启第二轮 unseen。锁定组合失败后不得自动切换 runner-up。
8. **三态结论诚实。** 有效 validation 无候选达标或有效 unseen 否决锁定组合时为 `NO-GO`；设施/订阅/资源不足以判断时为 `INCONCLUSIVE`；
   只有锁定组合满足全部必需门且 unseen 未否决时才为 `GO`。只有 `GO` 解锁 M3-D，但仍不在本任务启动或默认启用产品。
9. **稳定产品边界不动。** 本任务只选择现有 Critic 的模型、threshold 和运行配置，不改变 hard/soft qualification、两次 rewrite 后非阻断发布、
   infra fallback、取消、唯一 store commit、Team State 或角色职责。模型质量问题不能伪装成服务/threshold bug。
10. **证据保持轻量。** 复用现有普通 JSON、hash、write-once archive、结果模板与测试结构即可；只保留复测和理解结论需要的身份、逐项投影和聚合。
    不要求密码学证明、数据库、普适 schema、严格因果证明或额外审计平台。
11. **重型资源全局串行。** 轻量开发与订阅 Judge 可与 Plan 069 并行；真实本地模型/GPU、Docker、重型 Cargo 必须等待全局重型窗口，使用
    canonical shared wrapper/lock/watchdog，并遵守 Windows C:、内存、swap、磁盘和 Docker 增量门。拿不到必要事实时 fail-closed，不触碰 069 现场。
12. **范围内问题自主闭合。** 依赖、launcher、进程、连接、OOM、测试和局部兼容问题可修复、续跑和重跑；有效模型/Judge 输出不能因不满意而
    定向重问或筛掉。只有需要越过候选/数据/付费/产品/远端/宿主原则边界，或 unseen 已释放后出现不可恢复的有效性问题时才暂停。
13. **交付止于 task branch。** 执行者更新计划状态、精炼日志和必要小型结果，审查 tracked/ignored 资产与所有 worktree 状态，形成 clean 提交；
    独立验收由计划制定者完成，普通 finding 可在本 worktree 修复复验。未经用户批准不得把 Plan 073 合并进 `main`、推送或归档。

## 4. 软性建议

以下内容是基于当前 live code 的高性价比起点，不是固定路线。执行者可以依据实现、Judge 组织和真实结果采用更优方案，审查者不得把本节偏好
升级为验收门。

- 可优先组合 `DatasetConsumer(..., allow_evaluation=True)`、既有 render/scoring、Plan 068/071 inference/worker/service 与
  `summarize_measurement()`，再增加职责清晰的 M3-C2 selection 层；若这些接口强行拼接会使历史 schema 或 unseen 边界含混，建立小型专用模块更干净。
- validation 正式阶段可优先消费 Plan 066 已导出的 train+validation-only bundle 和现有 `ValidationDataset`，让运行进程物理上拿不到 unseen；
  selection lock 生效后再由完整冻结 release 的显式 evaluation consumer 打开 unseen，通常比预加载全部 split 后依赖调用纪律更简单。
- validation 为 55 candidate、unseen-test 为 45 candidate；规模足够小，可一次只加载一个候选并缓存 score row，避免重复模型加载。
  具体 batch、顺序、并行度和中间格式由本地显存与已有 worker 事实决定。
- threshold 可比较完整 operating curve、先满足 False PASS/关键 slice 底线再优化 False REWRITE/综合质量，或采用其它预先冻结且解释清楚的方法；
  不强制某个加权公式。对样本较少的 slice 明示分母和不确定性通常比构造复杂统计框架更有价值。
- Opus Judge 可覆盖全部 validation，或采用在正式前冻结的分层盲化子集；可以优先确保 hard qualification、boundary、Within-PASS、模型分歧
  和接近 threshold 的情形得到足够覆盖，但不得在看到 GPT 标签后只挑有利案例。Judge 原始正文留 ignored，tracked 只保留结构化聚合和必要短理由。
- 让一个子智能体负责盲化材料与 Judge 批次，另一个负责本地执行/确定性聚合，父执行者最后只按冻结协议合并两类证据，通常足以获得干净的
  上下文隔离；无需模拟评审委员会或多轮辩论。
- Plan 071 已证明三对象在原始 safetensors + CUDA BF16 路径下合格，并留有 load/RSS/VRAM/warm/stress/service 事实。若最终运行配置不变，
  可复用稳定事实并只补 validation 质量/threshold 所需运行；若 timeout/queue/batch 等最终值改变，再定向补相应测量。
- 可用一个小型 split-release/selection-lock 检查阻止误开 unseen，并用 pure tests 覆盖锁前拒绝、锁后固定组合、不可改选和同一 namespace 续跑；
  不需要把它扩张成安全系统或资产审计器。
- 测试按影响面递进：selection/threshold/Judge parser/unseen gate 的 pure tests；进程/worker 变化再加 focused integration；Rust scorer/service
  实际变化才运行 `just fmt`、`just fix -p codex-publication-critic` 和 `just test -p codex-publication-critic`。不改 Rust 就不机械触发 Cargo。
- 正式结果可采用每候选一页核心质量/threshold/资源摘要、一个横向比较表、一个 Judge 补充表和一个最终 decision；避免复制 Plan 054/068/071
  的全部历史或把 raw dataset 正文写入 WBS/日志。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- Plan 071 唯一有效正式轮已确认 exact base、C1、C3 均为 `QUALIFIED`，C2 保持历史 `NOT_QUALIFIED`；M3-C2 前置满足。
- 已从 clean `main@d72d109f7a3c4cb5d8a57d585e9efcc834542802` 创建
  `.claude/worktrees/073-m3-c2-publication-critic-selection` / `worktree-073-m3-c2-publication-critic-selection`。
- 已只读核对根规则、README、当前 WBS/方向 3 WBS、Plan 054/068/071/072、产品合同、v8 数据卡与现有评价/部署实现。
- 新增 `eval/rondo_eval/publication_critic/selection/`（protocol/release/metrics/judge/decision/lock/archive/runner）与 44 项 focused
  测试；复用 Plan 054 packet→scalar 路径、stable sigmoid、Plan 064 consumer，未改动 Plan 054/055/057 产品语义，未改 Rust。
- 正式轮 `plan073-formal-20260825T084317Z-selection-v1` 已从 clean `65932d69fcdfe9cdb6099f5b0478667f0ca72cfc` 与空 namespace 完整执行：
  三候选同口径 validation 运行 + `claude-opus-5` 全量 55 条盲化横评。结论 **`NO-GO`**，无候选达到冻结发布质量底线。
- 因无有效 selection lock，unseen-test 全程未释放、未 render、未打分、未送 Judge。
- 结果与身份见 `eval/results/publication-critic/m3-c2-joint-selection-v1.{json,md}`；正式 archive 在
  `eval-data/publication-critic/plan073/formal/runs/plan073-formal-20260825T084317Z-selection-v1/`。

### 当前工作

- `REMEDIATED_R3_AWAITING_RE_REVIEW`：中断交接复验（`fca9033`）的三项阻塞均已窄修并完成轻量复验；正式
  `NO-GO`、指标与冻结底线不变。

### 本任务剩余步骤

- 无代码剩余。validation bundle 同时通过既有 canonical Plan 066 verifier 与正式导出摘要绑定，containment 测试不再读取
  mixed v8；unseen confirmation/report 必须重建锁下真实 release，并从 raw score 与成对 Judge package/aggregate 重算后
  canonical 相等，report 还要求 lock 精确绑定其 validation result。
- 仅待计划制定者独立复验；无需重跑模型、Opus、Cargo、Docker 或 unseen campaign。

### 阻塞项

- 无已知阻塞项。本轮未加载模型、未运行 Cargo/Docker/Opus、未释放或读取 unseen body。

### 当前验收状态

- `EXECUTED / NO-GO RESULT RETAINED / R3 REMEDIATED / PENDING RE_REVIEW`

### 交接边界

- 执行者只在 Plan 073 本地 task branch 完成上述窄整改和复验；计划制定者随后复审，不重开模型或 Judge 正式轮。
- 只有独立接受的 `GO` 才由 WBS 解锁 M3-D。`NO-GO` 或 `INCONCLUSIVE` 只交付结论和返回边界，不在本计划扩写训练、C2 修复、新候选或下游任务。
- 任务完成后冻结本计划；共享 WBS、WBS-COMPLETED、合并、推送和分支归档由用户后续单独批准并基于届时最新 `main` 完成。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 候选固定为 exact base、C1、C3，允许 base 获胜；C2 不恢复 | Plan 071 已建立三者同口径资格，C2 的能力失败不属于本任务 | 候选、运行范围 | 已采纳 |
| 002 | 公平性要求同一 threshold 选择方法，不要求三模型共用同一数值 threshold | 微调可改变 score calibration；强制同数值可能把 calibration 差异误作质量差异 | threshold、横评 | 已采纳 |
| 003 | Opus 5 通过订阅入口提供盲化独立视角，并与执行/确定性聚合做子智能体上下文隔离 | 降低 GPT 教师标签单一偏好，同时避免 Judge 看到答案或赢家叙事 | Judge、证据合并 | 已采纳 |
| 004 | unseen-test 在 selection lock 后只执行一个逻辑盲验；冻结身份不变时可恢复技术中断 | 既保护最终盲验，又不给普通可恢复故障设置一次进程失败即报废的机械限制 | unseen、恢复 | 已采纳 |
| 005 | tracked 实现在 073 worktree，模型与 raw/Judge/运行资产在主物理根 Plan 073 ignored namespace | linked worktree 不共享 ignored `eval-data/`，且无需复制约 24GB 既有工件 | Git、资产 | 已采纳 |
| 006 | WBS 最终同步留给独立验收后的主线整合 | Plan 069 并行推进且 WBS 是共享权威文件，执行分支不应以旧基线覆盖并行状态 | 文档、交付 | 已采纳 |
| 007 | M3-C2 新建 `selection/` 子包，而不是扩写 Plan 054/068/071 schema | 历史 schema 描述 24 样本固定 cohort 的部署身份；M3-C2 比较的是 v8 评价 split 上的模型质量，强行合并会扭曲两者语义 | 模块布局 | 已采纳 |
| 008 | 质量底线取 False PASS ≤`0.25`、False REWRITE ≤`0.35`、balanced ≥`0.75`、AUC ≥`0.80`、boundary ≥`0.70` | False PASS 让不合格发布进入 Team State，是 Critic 存在的理由；False REWRITE 只多一轮有界重写。数值取自产品语义与 Plan 054 基座事实，正式输出前冻结 | 选择门 | 已采纳 |
| 009 | 延迟/资源只作可用性门，不参与排名 | 三候选同架构同尺寸，实测 load/warm/RSS/VRAM 几乎一致，用它排名是伪精度 | 排名规则 | 已采纳 |
| 010 | Judge 覆盖全部 55 条而非分层抽样 | 规模足够小，全覆盖直接消除抽样偏置与"看到标签后挑案例"的质疑 | Judge | 已采纳 |
| 011 | 正式 `evaluate` 在冻结 commit 运行；tracked 报告投影在其后的 commit 生成 | 报告是对已归档证据的纯投影，不含判定逻辑；正式证据仍绑定冻结 source，并已用归档 raw 逐字节重算复核 | 证据、交付 | 已采纳 |
| 012 | validation 只读物理不含 unseen 的 Plan 066 train+validation bundle，并绑定 canonical bundle 身份与正式导出摘要 | 避免 lock 前读取 mixed v8；固定投影摘要阻止以自洽重哈希替换数据，既有 consumer 继续承担跨行语义校验 | unseen 边界 | 已采纳（复验整改） |
| 013 | selection lock 与 unseen confirmation 都从冻结数据重建 release，并用 raw score 与成对 Judge package/aggregate 重算后要求 canonical 相等；report 再绑定 validation result | result/confirmation 自带 rows 只能证明内部自洽，不能证明来自正式输入；复用既有 evaluator 即可闭合，无需新建可信设施 | lock、confirmation、report | 已采纳（复验整改） |
