# Plan 087：Publication Critic 1.7B 云端自适应原参数路线搜索 ExecPlan

> 本计划是 Plan 087 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并按本计划指定的队列请求审查者批示。
> 普通代码、依赖、环境、连接、存储、checkpoint、恢复和局部测试问题，应在已生效的阶段授权内自主修复并按需重跑；
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 087；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 exact 1.7B、冻结 v8 输入与 pair 语义、不使用 LoRA/QLoRA/PEFT 或量化训练的前提下，使用单张 48GB RunPod GPU 和不超过
9 USD 的任务新增外部费用，启发式搜索比 Plan 082 score-head-only 更有能力的原参数更新路线，直到：

- 找到并在网络卷保留一个同口径有潜力优于 exact base 的研究候选；或
- 剩余预算已不足以完成下一次有意义的“更新—validation—保存—止费”循环；或
- 持续库存/云端基础设施条件使任务无法形成足够训练证据。

本任务允许执行者依据同 cohort validation 的完整观测，自主改变原参数更新范围、优化动态、既有 Binary/Pair objective 家族内部的
权重或组合，以及更新、观察和 checkpoint 节奏。它不要求严格拆分单个超参数的因果贡献，也不要求候选达到产品 GO。

Plan 087 的有效研究终态只有：

- `PROMISING_CANDIDATE_RETAINED`：出现明确排序或 pair 质量改善、关键伴随指标未明显塌缩，并已保留可复用候选；
- `BUDGET_EXHAUSTED_NO_CANDIDATE`：搜索流程有效，但在 9 USD 窗口内没有有潜力候选；
- `INCONCLUSIVE_INFRASTRUCTURE`：长期无适用 GPU、不可恢复云端故障或其它外部条件导致训练证据不足。

前两个终态都完成本研究任务；第三个终态可以完成合规收口与验收，但研究目标未达成，且不得解释为模型路线失败。

### 阶段门

Plan 087 分为两个授权阶段：

- **阶段 A：非付费准备。** 在专用 worktree 内复用或补齐训练、validation、checkpoint/恢复、保留、预算和云端生命周期能力，准备少量
  有实际区别的初始路线、任务输入、运行入口、停止/终态与资产语义，并以 fixture/fake/focused test 验证。不得创建/启动 Pod 或网络卷，
  不得下载/运行真实模型，不得上传数据、训练或产生新的外部费用，也不运行本地 Cargo、Docker 或真实模型。
- **阶段 B：付费自适应搜索。** 执行者完成阶段 A、提交 task branch，并通过本计划指定队列请求审查者验收。只有审查者明确回复
  阶段 A 验收通过并批准进入付费阶段后，阶段 B 授权才生效。用户对本计划列明外部动作与 9 USD 上限的一次性授权已经随执行提示词给出，
  不再需要第二次用户批准；审查者批准是实际付费开关。阶段 B 生效后，范围内普通修复、重试、续跑和允许资源替换无需逐项请示。

阶段 A 不设置额外“诊断任务”。审查通过后直接进入同一 Plan 087 的真实环境打通与预算搜索；付费环境中先保留已验证进度、从首个未打通处
边修边跑，真实链路足够稳定后从 exact base 和干净任务 namespace 启动一轮正式搜索窗口。该窗口按定义允许观测驱动的路线调整，不要求把
每次调整拆成独立 formal run。

### 完成/验收标准

- [ ] 全部 tracked 实现、测试、合同、结果摘要和文档修改只在 Plan 087 worktree 完成；阶段 A 与最终交付均先提交 task branch，
      worktree clean，不合并、不推送、不归档分支、不删除 worktree。
- [ ] 阶段 A 复用 Plan 081/082 职责契合的 train/validation identity、真实 Torch 更新、checkpoint/新进程恢复、retention、bundle、
      launcher 和小型 manifest 能力；Plan 082 的固定等权 objective、预声明单调 scope、formal 与旧终态 validator 保持历史合同，
      不靠放松旧 validator 伪装兼容。职责不契合时只补 Plan 087 专用或 route-neutral 的薄能力。
- [ ] 云端输入物理上只含冻结 v8 train+validation；exact 模型固定为
      `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`，unseen-test 全程不可达。
- [ ] 初始路线数量保持少量且彼此在原参数范围、优化动态或既有 objective 组合上有实际区别；具体路线数、超参数和切换条件不由本计划锁死，
      实际路线及每次变化在作用于后续更新前后有足够记录，能重建候选 lineage 和预算消费。
- [ ] 同一 validation cohort 提供 base anchor、完整聚合指标、逐 pair 方向/margin 与必要伴随指标；validation 不进入梯度，只用于路线调整、
      停止和候选判断。unseen、M3-C1、M3-C2、产品 threshold/启用均未进入本任务。
- [ ] 候选判断基于明确排序或 pair 质量改善与关键伴随指标的整体表现，并留下执行者理由；浮点噪声、统一 logit offset、仅阈值变化或单一指标
      偶然抖动不能单独支持 `PROMISING_CANDIDATE_RETAINED`。不预先冻结细粒度公式或把启发式判断扩成严格因果/可信平台。
- [ ] 训练与恢复链能记录并恢复实际参数范围、optimizer/scheduler、RNG、数据进度、路线历史、观测和选择状态；至少对最终候选或任务结束时
      的必要恢复点完成相称完整性/可复用性验证。大型权重和 checkpoint 保留在网络卷，不下载到本地项目空间。
- [ ] 一旦形成有潜力候选，立即停止继续搜索；本任务不利用余额追求更高分，也不做候选的干净正式复现、M3-C1、M3-C2、unseen 或产品启用。
- [ ] 若没有候选，在剩余授权预算不足以完成下一次有意义闭环时主动结束；保留完整路线历史、指标和有限诊断资产，不为求正结论超预算，
      也不永久保留每个无效 checkpoint。
- [ ] 阶段 B 开始前记录 provider 费用/余额与资源基线；用户当前说明余额为 9.14 USD，其中 Plan 087 任务消费硬上限为 9 USD，另保留
      0.14 USD 给任务终态后按需扩至最高 60GB 的网络卷。阶段 B 初始可用总额固定为
      `min(9 USD, 阶段 B 基线余额 - 0.14 USD)`；任务期 Pod、container disk、网络卷持有/增容/新建和必要小型回传的累计保守费用不得超过
      该总额。每个新动作的预计增量还必须同时不超过“初始可用总额减累计保守费用”和“当前余额减 0.14 USD”。终态后的卷持有费不计入
      Plan 087 总账，也不要求在 9 USD 内另行预留；对账与停止须为账单延迟留余量。
- [ ] 同时最多一个计费 Pod。任务结束前释放全部 Pod并实时确认 `0 Pod`、持续 compute 费率为 0；保留卷的 ID、区域、容量、内容角色、
      持续费率与是否新建/扩容如实记录。任何现有或新建网络卷均未删除。
- [ ] `PROMISING_CANDIDATE_RETAINED` 时保存候选 checkpoint、实际路线、必要恢复状态、完整 validation 指标和 pair margin，并确认后续任务可复用；
      其它终态保存足够支持结论的小型结果、路线历史和必要诊断。无论终态如何，本地只回传验收与后续工作必须保留的小型结果、manifest、
      日志和资源终态；完整 checkpoint、权重、训练环境及其它大工件只留网络卷。
- [ ] 阶段 A 和最终阶段的相关轻量 Python 测试、必要 compile/format/static 检查、改动 shell 的 `bash -n` 与 `git diff --check` 通过；
      不运行 Cargo、Docker、全 workspace、本地真实模型或 CI，fake、调试、正式搜索、skip 和未运行项分别如实记录。
- [ ] 最终独立审查关闭所有高/中等级 correctness/functionality finding，并分别给出“验收通过/不通过”和“任务目标完成/失败”；
      `INCONCLUSIVE_INFRASTRUCTURE` 不得被改写为路线 no-candidate。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/full_model_training/` 中职责契合的中性训练/评价/checkpoint/恢复/retention/bundle/cloud seam，及明确的
  Plan 087 自适应搜索能力；保留 Plan 081/082 历史入口和 validator 的既有语义。
- `eval/rondo_eval/publication_critic/selection/`、`base_quality/`、`local_deployment/` 中真正通用的 validation 指标、模型身份、严格安全加载、
  小型 manifest 或回传接缝；只做窄复用/泛化，不改变历史计划结果、Judge、selection lock、unseen 或产品语义。
- `training/publication-critic-plan087/` 下体积合规、受跟踪的初始路线候选、预算/停止/终态、运行入口、依赖、source/data bundle 与 runbook；
  不提交模型、checkpoint、cache、venv 或原始训练输出。
- `scripts/create-runpod-when-ready.py` 作为仓库唯一通用抢卡入口，只负责库存轮询、自动创建和不确定响应的 exact-name 防重复对账；
  Plan 087 不建立专用 Pod 创建器、确认器或创建 receipt，不建设通用调参或云编排平台。
- `eval/tests/` 中相称的 pure/fake/focused 测试和小型 fixture；`eval/results/publication-critic/` 中体积合规的正式搜索摘要。
- 本计划“当前状态”和“关键决策记录”、`doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、最终验收后由审查者更新的
  `doc/WBS-COMPLETED.md`，以及有意义的精炼 `agent_log/`。并行 WBS 只做语义窄整合。
- 普通依赖、公开源码和文档只读查询；阶段 B 生效后，按 exact revision 从 Hugging Face 下载模型到任务云端资源，禁止向 HF 上传/发布。
- 阶段 B 生效后，通过既有安全入口查询 RunPod 库存、价格、余额、资源和费用；向任务自有 RunPod 资源上传必要的已提交源码与物理无 unseen
  train+validation bundle；创建、启动、重启、替换、停止和删除一张 A40 48GB 或 L40S 48GB Pod并执行真实 1.7B 训练。
- 阶段 B 可挂载并复用现有 US-TX-3 40GB 卷 `mwemzrn33y`；Plan 082 既有 roots/对象全部视为只读，唯一允许写入的范围是新的 Plan 087
  task root。容量不足时按需渐进扩容、最高 60GB。若该区域长期没有适用 GPU，可在选定兼容区域新建一个当下够用的最小实用任务卷，并仅在需要时
  继续扩容、最高 60GB。
- 只清理本任务新建且已确认不需保留的远端工件；不得修改、覆盖或清理 Plan 082 的历史资产。任何网络卷本身都不得删除。

### 不允许修改或执行

- `training/publication-critic-v8/` 及其继承数据的正文、label、pair、split、review、manifest、输入/scalar 方向或冻结身份；Plan 054/060/064/
  066/068/071/073/075/079/081/082 的冻结结果、正式 receipt、历史报告和计划终态。
- Publication Critic 产品默认、`multidev/` 产品行为、threshold、selection lock、M3-C1/M3-C2/unseen 流程、M3-D、本地部署资格或产品启用。
- LoRA、QLoRA、其它 PEFT、量化训练、换模型、新 objective 家族或改变 pair/preferred 方向；第三种 GPU、多 GPU、同时多个计费 Pod、
  真实 API/Judge、HF 远端写入、发布、CI/PR 或上游基线升级。
- Plan 087 本地 Docker、Cargo、真实模型加载/推理、全 workspace 测试或创建 Cargo target；不得读写或清理 Plan 086/069 的构建资产、
  worktree、未提交修改和任务专属 ignored 资产。
- 删除任何现有或新建 RunPod 网络卷；删除/覆盖来源不明 Pod、卷、cache、模型、checkpoint 或非 Plan 087 工件；修改宿主机配置、全局工具链、
  系统服务、其它仓库或项目外个人文件。
- 未经用户后续批准合并/rebase/cherry-pick main、推送 task branch、归档/重命名分支或删除 worktree。

### 不允许读取/查看

- v8 unseen-test 的正文、render、score、Judge 输入/输出，或任何需要先读 mixed 数据再过滤的路径；云端 bundle 必须从物理无 unseen 的
  canonical train+validation 投影开始。
- `.env.local` 内容、token、API key、secret、私钥、密码或个人配置。只可按根 `AGENTS.md` 静默检查文件存在、非符号链接、`0600`
  和任务所需变量非空；不得 source、打印、复制、上传或记录凭据。
- 与任务无关的 ignored 资产、Plan 086/069 构建资产正文、真实 publication/transcript/private reasoning 和项目外个人文件。

### Git-ignored 与主物理根边界

全部 tracked 修改在
`/home/sjc/desktop/RONDO/.claude/worktrees/087-publication-critic-adaptive-search/` 完成并提交，主工作区不得产生 tracked 修改。

linked worktree 不共享主物理根 ignored `eval-data/`。阶段 A 的 bundle dry-run、阶段 B 的上传源、回传小型结果、receipt、日志和临时运行工件
允许直接写入主物理根任务专属 namespace：

`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan087/`

该目录只允许 Plan 087 输入投影与运行/回传工件；执行者在阶段/最终汇报中列出实际创建或保留的主要路径、用途和体积，不建设逐文件审计台账。
Plan 082 ignored 资产仅在确有复用需要时通过精确 manifest/既有 loader 只读访问，不扫描、复制或改写整个历史目录。

主物理根 `.env.local` 仅通过严格数据 loader 静默校验并向目标进程注入 allowlist 变量。可在兼容时只读复用主根 `eval/.venv`；不得任意升级
共享环境。规划阶段没有创建上述 ignored namespace，也没有直接修改主工作区；执行阶段只有这些 task-owned ignored 运行资产和安全入口因
gitignore/linked-worktree 隔离必须使用主物理根，tracked 源码、测试、文档和日志仍必须留在 worktree。

## 3. 硬约束

以下约束只冻结研究正确性、阶段门、模型/数据语义、费用/资源安全和交付边界，不锁死实现布局、类名、配置 schema、路线数量、超参数、
搜索策略或调试次序。

1. **非付费与付费两阶段门。** 阶段 A 可自主完成项目内实现、轻量测试、输入/运行准备、提交和整改，但不得产生费用或外部状态变化。
   阶段 A 提交后必须通过指定队列请求审查；只有审查者明确验收通过并批准阶段 B，执行者才可创建/启动云资源、上传数据、下载/运行模型或
   训练。执行提示词已经承载用户一次性授权，不要求再向用户申请第二次批准；审查者批准前付费门保持关闭。
2. **模型、监督和 unseen 不漂移。** exact 1.7B revision、冻结 v8 input/label/pair、preferred-minus-dispreferred、`logits[:,0]` 与
   higher-is-better 语义保持不变；只允许原模型参数直接更新，禁止 PEFT 与量化训练。train 可进入梯度，validation 只作观察/路线调整/
   停止/候选判断，unseen 全程物理不可达。
3. **自适应变量有边界但不机械冻结。** 执行者可调整原参数 scope（包括扩大、缩小或重选职责明确的范围）、优化器及其动态、batch/累积、
   scheduler、裁剪、更新/观测/checkpoint 节奏，以及既有 Binary/Pair objective 家族内部权重或组合；不得换新监督任务、改 pair 方向、标签或
   输入含义。路线变化必须记录实际值、理由、起始状态和后续观测，足以复现候选 lineage，但不要求单变量实验或严格因果证明。
4. **复用能力而非改写历史。** Plan 081/082 提供中性训练、bundle、模型核验、validation 隔离、checkpoint/恢复、launcher 与 handoff 基元；
   Plan 082 的 fixed recipe、单调预声明 scope、formal finalizer 与旧终态继续可验证。强行复用会造成耦合或语义扭曲时，应建立架构契合的
   Plan 087 专用能力，不复制第二套数据、评价、checkpoint、registry、审计或可信体系。
5. **调试闭环后开始正式搜索窗口。** 阶段 A 尽可能打通轻量全链；真实环境中的可修接缝允许保留已验证进度、从未打通处修复重跑。
   exact 模型更新、同 cohort validation、checkpoint/恢复和止费链足够稳定后，从 exact base 与干净 task namespace 启动预算搜索窗口。
   该窗口本身允许按观测自适应，不把调试权重冒充候选；发现影响证据有效性的缺陷时，修复后从相称干净边界重新开始，不拼接无效结果。
6. **候选是启发式研究候选。** base anchor 与训练观测使用同一 validation cohort、输入、scalar 方向和指标口径。候选需有明确排序或 pair
   质量改善，且关键伴随指标无明显塌缩；浮点噪声、统一 offset 或单一 threshold 变化不足以成立。具体判断由执行者结合完整指标作出并说明，
   不为追求机器裁决预建细粒度公式、审计链或可信平台。
7. **找到即停、无候选也可完成。** 一旦候选成立，停止新的训练搜索并进入保存/止费；不消耗余额追求更好分数。没有候选时，以剩余预算能否
   完成下一个有意义闭环决定停止，不以固定路线数、尝试数或机械 slot 限制探索，也不超预算求正结论。
8. **恢复与资产可用。** checkpoint 必须覆盖继续训练/后续复用真正需要的模型、实际 scope、optimizer/scheduler、RNG、data cursor、
   路线/观测/选择状态。`PROMISING_CANDIDATE_RETAINED` 必须验证所选候选 checkpoint 本身完整且可恢复/复用，不能用另一个 latest 或 recovery
   checkpoint 代替。任务自有工件只有在替代恢复点或终态保留集合已验证后才能清理；Plan 082 历史资产只读。候选大权重留在网络卷，本地只回传
   必要小型结果、manifest、日志和资源终态。
9. **修复、重试和继续。** 代码、依赖、环境、下载、网络、Pod、存储、OOM、数值、进程、checkpoint、恢复、归档和小型回传问题可在阶段授权、
   GPU 集合、单实例和预算内自主窄修、重试、续跑或替换失效资源，不设机械次数上限。不得删测试、弱化断言、扩大 fallback、伪造结果或改变
   原则边界求绿；需要预算/模型/数据/GPU 集合扩张、卷删除或其它授权外动作时才通过队列请示。
10. **单 GPU、实时选择与 9 USD 总账。** 付费启动前刷新 A40/L40S 库存、价格、region/volume 兼容性、0 Pod 状态、账户余额和费用基线。
    优先选择可直接挂载现有 US-TX-3 卷并复用 Plan 082 环境的 L40S；同区长期无库存时可选择其它区域 A40并权衡 bootstrap/新卷成本。
    同时最多一个计费 Pod；失效实例只有在确认旧实例已不再计费后才能替换。阶段 B 启动时把初始可用总额固定为
    `min(9 USD, 基线余额 - 0.14 USD)`；任务开始基线后的 Pod、container disk、既有/新卷持有与增容、必要小型回传累计保守费用不得超过
    该总额。每个新动作的预计增量还须同时不超过总额剩余和当前余额减 0.14 USD，并为延迟账单留下停止余量。用户说明的 0.14 USD 专供
    终态后最高 60GB 网络卷继续持有；终态后的卷费不计入 Plan 087 任务总账，也不因它缩减已授权的 9 USD 任务上限。
11. **网络卷只增不删。** 可挂载现有 `mwemzrn33y` 并在新 task root 写 Plan 087 资产；确有容量需要时从 40GB 以最小实用增量渐进扩容、
    最高 60GB。
    若该区域长期没有适用 GPU，可在选定区域创建至多一个当下够用的最小实用任务卷；新卷和现有卷都只按实际需要渐进扩容，任务内最高
    60GB，不要求创建时直接达到 60GB。不得删除任何现有或新卷；任务结束报告全部卷的实时状态和持续费率。候选卷保留给后续干净正式复现，
    无候选时也不因止费擅自删卷。
12. **与 Plan 086/069 并行隔离。** Plan 087 不运行本地 Cargo、Docker或真实模型，不创建 Cargo target，不下载大型 checkpoint 到项目空间，
    不读写/清理 Plan 086/069 构建资产。RunPod 远端工作可与 Plan 086 重型 Rust 构建并行；共享 WBS 只作语义窄整合，后完成者基于届时
    main 保留另一方向进展，不 whole-file 覆盖。
13. **秘密与外发最小化。** `.env.local` 只由严格 loader 当 `KEY=VALUE` 数据解析并注入目标子进程所需 allowlist；source/data archive
    上传前检查物理成员，禁止 secret、unseen、无关源码、ignored 历史资产、旧模型/checkpoint 混入。唯一的数据外发例外是向任务自有
    RunPod 资源上传必要的窄 source archive 与物理无 unseen train+validation bundle；除此之外，不向 HF 或其它外部目标上传/发布模型、
    数据、权重或结果。HF 只下载 exact revision。
14. **资源终态优先。** 无论成功、预算耗尽还是基础设施失败，终态判断形成后都只取回验收与后续本地必须保留的小型资产，完整 checkpoint、
    权重、训练环境和其它大工件留在网络卷；随后立即停止/删除所有 Pod，实时确认 0 Pod 和
    compute 费率为 0，再完成本地 tracked 文档/结果提交。普通最终审查发现可在本地修复的问题不得恢复计费；若确有 correctness 问题必须
    再用 GPU，仍须处于阶段 B、预算有余且由审查者通过队列明确指示，否则形成诚实的相应终态。
15. **结论和文档归位。** fake、云端调试和正式搜索分别记录；validation 不冒充 unseen、M3-C2 或产品 GO。WBS 只维护当前路线和交接，
    plan 只维护任务状态/决策，agent_log 精炼记录实质批次，COMPLETED 只在最终验收后追加。后续正式复现或产品工作只链接 WBS，不写进本计划。
16. **本地提交后停止。** 执行者在阶段 A 与最终交付时都先提交所有范围内 tracked 变动并保持 worktree clean，再通过指定队列通知审查者并
    停止会话。未经用户批准不得合并、推送、归档分支或删除 worktree。
17. **跨会话请示与验收。** 额外授权、计划外变数、不确定事项、阶段 A 申请进入付费阶段和最终任务验收只使用下述 Codex 跨会话队列。
    执行者每条消息必须主动表明“我是 Plan 087 执行者”，发送后停止会话，不等待、不轮询、不重复发送。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03e03-9920-7171-882d-948775b2aea4 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。
```

```text
需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。
```

```text
执行者完成非付费的准备阶段，申请进入付费阶段，以及最终完成任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了<阶段性任务>，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<执行者的完成汇报>”
其中
<阶段性任务>就是执行者想申请验收的部分，一般情况下主要是付费前准备工作的验收和最终整个任务完成的验收。
<执行者的完成汇报>就是执行者本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）执行者你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。
```

```text
执行者给审查者发送消息的时候，必须主动表明身份。
```

在本计划中，`<阶段性任务>` 依次用于“Plan 087 非付费准备阶段 A”和“Plan 087 最终任务”。对于阶段 A，用户最新指定的付费门优先于上述
通用文案中的“如果验收通过，他不会再通知你”：审查者即使验收通过也必须通过同一队列明确回复“阶段 A 验收通过，批准进入付费阶段”；
执行者未收到该明确回复前不得产生费用或外部写状态。最终验收仍按通用文案处理。

## 4. 软性建议

以下建议只帮助执行者高效起步。执行者可依据 live code、真实显存/训练动态和完整指标采用更简洁、优雅、与现有架构更契合的等强方案，
不需要为了遵循建议而扭曲实现；有实质影响的偏离记录在关键决策中即可。

- 优先保留 Plan 082 的历史实现不动，在其真实 Torch adapter、bundle、model lock、validation、checkpoint codec、fresh-process recovery、
  launcher 和 handoff core 之上增加 Plan 087 route/search seam。Plan 082 source bundle 的成员集不含 Plan 087 合同，准备新 source bundle 时
  应显式解决这一点，而不是临时复制文件。
- 初始路线可优先考虑 score head 加末端 backbone block、较宽末端范围或更广原参数范围，并用与 score-head-only 明显不同的优化动态；
  objective 可在既有 Binary/Boundary/Within-PASS 或 Binary/Pair 组合内重新权衡。这里只是起点示例，不限定模块名、顺序、数量或必须全参数。
- 先用短更新和较密观察判断是否只是统一 offset、排序是否开始变化、pair margin 与 binary/calibration 是否共同健康，再决定扩大/重选 scope、
  调整优化动态或换下一路线。路线继续 checkpoint 还是从 exact base 新开，由 lineage 可解释性、恢复成本和剩余预算共同决定。
- 复用现有卷时在独立 Plan 087 task root 工作，避免触碰 Plan 082 正式/commissioning 工件；先估算候选 checkpoint、环境与日志空间，确有需要
  再按需扩容、最高 60GB。跨区新卷也从最小实用容量起步；bootstrap、扩容和持续费用由实时库存与完整下一闭环成本决定，不因 L40S 偏好无限等待。
- 成本控制宜维护简单的 wall-clock × 实时费率加已知 container/volume 费用保守估计，并在每次路线启动前判断是否还有完整闭环余量；
  不必建设账单预测、通用 quota 或复杂可信核算系统。
- 找到候选后，在释放 Pod 前完成 checkpoint manifest、完整性/恢复资格、小型 metrics/pair margin、实际路线和资源终态所需的远端生成与回传。
  大 checkpoint 留卷即可，不重复下载或本地验证全部 payload。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：从 clean `main@39fe9a87814c035baff734448bf206300ea0a9b7` 创建专用 worktree
  `/home/sjc/desktop/RONDO/.claude/worktrees/087-publication-critic-adaptive-search/` 与分支
  `worktree-087-publication-critic-adaptive-search`。
- 2026-08-26：规划者阅读根规范、README、顶层/三期 WBS、Plan 081/082 合同与训练设施、Plan 082 正式结果/最终审查/卷保留事实，
  按模板形成 Plan 087 合同并窄同步当前 WBS；未创建 ignored 任务资产、未访问 RunPod/HF、未产生费用。
- 2026-08-26：两路只读独立复核检查 prior art、WBS/Git 边界与计划全文；发现的预算累计公式、卷读写范围和 RunPod 上传例外三项 Medium
  合同歧义已修订，复验无剩余 High/Medium correctness/functionality finding。
- 2026-08-26：执行者完成阶段 A 实现：在 Plan 081/082 中性核心之上增加 Plan 087 adaptive recipe/scope/search/finalize 薄层，
  闭合路线 lineage、hash-linked 累计保守预算、decimal GB 与实际可用 bytes 容量门、独立进程精确恢复后入选、三终态、窄 source/data
  bundle、任务根写入边界、小型回传 allowlist与歧义 stop/delete 后核对；Plan 082 fixed recipe/formal validator
  保持历史语义。
- 2026-08-26：两条初始路线、云端 runbook 与 exact Hugging Face revision bootstrap 已准备；新增测试与 Plan 081/082 相关历史回归共
  84 项通过（另有 34 个 subtests），shell syntax、Python AST、定向 Ruff 与 diff 检查通过。Stage A 本地数据投影只含
  train+validation，物理 unseen rows/body 为 0；未查询或修改 RunPod/HF、未运行本地真实模型/Cargo/Docker、未产生费用。
- 2026-08-26：两路独立只读实现审查提出的容量口径/实际余量、费用快照链、恢复 receipt 绑定、路线 evidence lineage、远端任务根写入、
  stop/delete API 歧义回查与小型 handoff 边界已窄修；focused tests 与 runbook 操作序列随整改同步，两路最终复验均无剩余 High/Medium finding。
- 2026-08-26：阶段 A 对当时的专用创建原型经历多轮审查，并同步关闭路线收口、恢复分责和动态 scope 问题；细节保留在形成时点的
  `agent_log/`。用户最终仓库收口决定已移除该创建原型，现行创建流程由下方决策 017/023 定义。
- 2026-08-26：整改后 Plan 081/082/087 相邻聚焦回归 90 项通过（另有 44 个 subtests），定向 Ruff/format、15 文件 AST、shell syntax
  与 diff check 通过。云端生命周期与训练/搜索两路只读复验均无剩余 High/Medium correctness/functionality finding；未访问任何 live 外部状态。
- 2026-08-26：阶段 A 最终聚焦回归 93 项通过（另有 59 个 subtests）；定向 Ruff/format、15 文件 AST、shell/CLI syntax、diff check 与
  WBS untouched 门禁通过。
- 2026-08-26：审查者以 High 0、Medium 0 验收阶段 A，并明确回复“阶段 A 验收通过，批准进入付费阶段”。执行者随后刷新 live 基线：
  账户 0 Pod、余额 9.1252646939 USD，固定任务总额 8.9852646939 USD；既有卷 `mwemzrn33y` 在 US-TX-3 可挂载 L40S。
- 2026-08-26：阶段 B 以已提交 `6dd27d8` source archive、物理无 unseen 的 v8 train+validation bundle 和 exact
  `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` 打通真实 L40S 链路。
  根据 live FUSE mount 语义窄修容量观测说明，并在 debug 全链闭合后从 clean exact base 启动正式搜索。
- 2026-08-26：正式搜索完成 A–O 共 15 条 hash-linked 路线。A–N 在完整观测后诚实收口；Route O 的末块内部输入变换/归一化九张量范围
  以一次 full-cohort 更新取得 raw boundary margin +0.00390625、projected boundary +0.00086113、projected within-PASS +0.00013894
  和 ROC AUC +0.00140056，严格胜数、阈值错误和 best operating balanced accuracy 未退化，形成分布式而非统一 offset 的研究候选。
- 2026-08-26：Route O 精确候选 checkpoint 已由新 OS 进程执行 no-update 恢复验证，模型/优化器/调度器/RNG/数据/路线状态一致。
  18 个小型回传文件共 573701 bytes 通过 exact-tree 校验；完整 checkpoint、model snapshot 与训练环境仅留在网络卷。
- 2026-08-26：终态为 `PROMISING_CANDIDATE_RETAINED`。任务 Pod 已精确 stop/delete，并复核账户 0 Pod、compute 费率 0；
  `mwemzrn33y` 保留且未删除，容量 57GB、持续卷费 0.006 USD/h。终态余额 6.2192572691 USD，保守任务费用 3.009 USD，
  剩余任务授权 5.9762646939 USD。终态 receipt 观察到的累计 task-window Pod billing 1.9811751181 USD 已由追加成本快照 40 纠正记录。
- 2026-08-26：最终七个相邻聚焦 unittest 93 项通过；15 文件 AST、三个 shell syntax、CLI help、source/data/handoff exact-tree、
  terminal/result JSON 不变量、diff check 与 WBS untouched 门禁通过。获批后未修改 Python 实现，阶段 A 已验收的 Ruff 结果保持有效。
- 2026-08-26：最终审查确认研究终态 High 0、Medium 0，但按用户最终仓库决定要求三项收口：通用化抢卡脚本、删除 Plan 087 专用
  创建/确认/receipt 路线，以及在根 AGENTS/CLAUDE 工作流程写明“先创建、后独立核验、不符立即释放”。研究运行、6dd27d8 历史输入、
  41 张费用快照、handoff、终态结果和远端资产不改写，也不恢复任何 Pod。
- 2026-08-26：仓库收口已完成：通用入口/测试均移除 Plan 079 标识，Plan 087 专用创建器、创建测试、current bundle member 和 active
  receipt 语义已删除，根 AGENTS/CLAUDE 第 7 条逐字一致；历史 `agent_log` 与 6dd27d8 输入证据保持原样。最终聚焦回归 91 项通过，
  其中通用抢卡 6 项、Plan 087 terminal/source-bundle 定向 8 项；定向 Ruff/format、5 文件 AST、两个 CLI help、三个 shell syntax、
  非历史旧引用、diff、结果 untouched 与 WBS untouched 门禁通过。

### 当前工作

- 研究执行与云端归零保持完成；用户指定的三项仓库收口和聚焦门禁均已完成，等待最终复验。

### 本任务剩余步骤

1. 执行者提交 Plan 087 worktree 后用指定队列请求最终复验；审查者完成相称独立复核与必要整改。
2. 整体验收通过后按审查者既定决定统一更新 WBS/WBS-COMPLETED；此前保持两份权威 WBS untouched。

### 阻塞项

- 当前无计划级或基础设施阻塞；仓库收口等待最终复验。
- 网络卷持续费用为终态后的保留成本，不属于 Plan 087 已关闭的任务总账；卷不得删除。

### 当前验收状态

- `PROMISING_CANDIDATE_RETAINED / FINAL_REVIEW_PENDING / ZERO_POD`；研究证据已通过，仓库收口已实现并待复验，不含 unseen/product GO。

### 交接边界

- 执行者直接使用本计划已创建的 Plan 087 worktree，不另建工作树，不在主工作区修改 tracked 文件。
- 阶段 A 和最终交付都必须先提交 worktree，再按指定队列发送一次相应消息并停止会话；普通可修问题在阶段授权内自主修复重跑。
- 本任务完成后冻结本计划；候选干净正式复现、部署/资格、M3-C2、unseen 或产品启用只链接 WBS，不在本计划继续安排。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 087 是预算内自适应搜索，不继承 Plan 082 单一路线 formal freeze 和有效结果后禁止再搜 | Plan 082 已证明 score-head-only 无改善，本任务目标就是在同一固定语义下探索更大原参数路线 | research lifecycle | 已采纳 |
| 002 | 明确阶段 A 非付费准备与阶段 B 付费搜索；用户授权预置，但阶段 B 只有审查者验收并明确批准后才生效 | 在产生费用前完成正确性门，同时避免再次向用户逐项申请 | authorization | 已采纳 |
| 003 | 保留 Plan 082 历史 validator，Plan 087 用专用薄层承载可变 scope/objective、搜索历史和新终态 | 旧实现把等权、单调 scope、单指标 formal 与旧终态写死，直接放松会改写历史合同 | architecture | 已采纳 |
| 004 | 候选采用完整同 cohort 指标的启发式判断，不冻结细粒度公式 | 目标是找到有潜力候选而非证明单因果，统一 offset/噪声仍需排除 | selection | 已采纳 |
| 005 | 一旦找到候选立即停止；本任务不做候选干净正式复现 | 节省有限预算，并把适应性搜索与后续确认分责 | stopping | 已采纳 |
| 006 | A40/L40S、同时单 Pod、任务消费至多 9 USD；实时余额另留 0.14 USD 给终态后最高 60GB 卷，不把终态后卷费计入任务 | 与用户给定的 9.14 USD 余额分配一致，并为延迟账单留余量 | cloud budget | 已采纳 |
| 007 | 优先现有 `mwemzrn33y`；现有/跨区新卷从当下容量起步并按需渐扩、最高 60GB，任何卷都不删除 | 不预付无用容量，60GB 仍足以承载探索并可由任务外预留余额继续持有 | storage | 已采纳 |
| 008 | tracked 全留 worktree，Plan 087 ignored 运行资产只落主物理根 task namespace | linked worktree 不共享根 `eval-data/`，秘密入口也只存在主物理根 | workspace | 已采纳 |
| 009 | Plan 087 不占本地重型资源，可与 Plan 086 并行；共享 WBS 由后完成者基于届时 main 窄整合 | 避免 Cargo/Docker/本地模型与共享文档互相覆盖 | concurrency | 已采纳 |
| 010 | 阶段 A、额外请示和最终验收只走用户指定 Codex queue，每条消息主动声明执行者身份 | 满足跨会话审批和自动唤醒边界 | coordination | 已采纳 |
| 011 | worktree 只提交，合并、推送、分支归档和 worktree 清理等待用户批准 | 遵循本次明确交付边界 | delivery | 已采纳 |
| 012 | 候选判断保留完整指标与执行者四项整体判断，不冻结细粒度数值门；promising 必须绑定同一个由新 OS 进程精确恢复的 checkpoint | 既排除仅噪声/offset/threshold 的伪改善，又不把启发式研究候选误写成产品资格公式 | selection/recovery | 已采纳 |
| 013 | 真实 parameter inventory 动态解析 score/final、任意末端深度、显式模块前缀或全参数；新 exact-base 路线可重选，同一路线后续 phase 只允许实际参数集严格扩展 | 兼容 exact 模型命名和自适应职责切换，同时保持单条 checkpoint/optimizer scope 历史可复现 | training scope | 已采纳 |
| 014 | 费用采用不可改写的 hash-linked 累计快照链；路线与终态必须按序绑定全部新增快照 | 同时覆盖延迟账单、Pod 替换和多段训练，避免只交末张快照丢失累计费用 | cost lineage | 已采纳 |
| 015 | 候选 checkpoint 必须由不同 OS 进程的 verify-only 恢复 receipt 绑定 source/recovery process、route context、runtime 与 payload identity | 让“可恢复”成为实际执行证据，并阻止用其它 checkpoint 或同进程状态替代 | recovery | 已采纳 |
| 016 | 所有云端写路径约束在显式 Plan 087 task root；通用抢卡脚本只在 create 响应不确定时按 exact name 防重复对账，terminal 对 stop/delete 不确定响应按 exact identity 收口；本地回传只接受显式小文件 allowlist | 避免污染 Plan 082 roots、重复计费实例或回传大权重树，同时保持创建与资格核验分责 | cloud lifecycle | 已采纳 |
| 017 | Pod 先由通用 `scripts/create-runpod-when-ready.py` 抢卡，再由执行者通过既有 RunPod MCP/CLI 独立核验实际价格、GPU、机房和网络卷挂载；脚本状态不是资格 receipt，任何不符或无法确认都立即由 terminal 能力释放 | 用户要求缩短抢卡关键路径并删除 Plan 087 专用创建/确认体系；独立后验核验仍保护实际资源正确性 | cloud lifecycle | 已采纳 |
| 018 | 路线收口与 checkpoint 恢复分责：完整观测/checkpoint 可提前 `not_promising`，无恢复时明确记录 `none`；只有 promising 或明确必要恢复点承担 fresh-process 恢复 | 避免弱路线机械跑满和重复候选级恢复，同时保留候选可复用证据 | search/recovery | 已采纳 |
| 019 | live FUSE mount 的 `df` 报共享后端容量时，以 provider decimal GB 配额减 task-root `du` 作为门禁余量，并保留原始观测 | 真实挂载不暴露任务卷 quota；该窄口径继续满足 60GB 上限和 checkpoint atomic staging 约束 | capacity | 已采纳 |
| 020 | 成本终态采用余额差、provider task-window billing 与累计 wall-clock ledger 三者最大值；发现终态 billing receipt 晚于快照投影时，只追加 hash-linked 快照 40，不改写历史 | 覆盖延迟计费并保持累计账本不可改写；本次最大值仍为 ledger 3.009 USD | cost lineage | 已采纳 |
| 021 | Route O 出现分布式 boundary 改善、projected within-PASS/ROC 伴随改善且关键 operating 指标未退化后立即停搜，不使用剩余预算做冗余 clean replay | ExecPlan 的终点是恢复合格的研究候选；正式复现属于后续独立工作，继续付费不会提高本任务结论必要性 | research terminal | 已采纳 |
| 022 | 只保留 Route O recovery-qualified checkpoint/model snapshot；清理已确认非候选的大型路线工件，保留 57GB 既有卷且删除全部 Pod | 满足后续复用、小型本地交接、Plan 082 只读和终态零 compute 边界 | retention | 已采纳 |
| 023 | 完整删除 Plan 087 专用 Pod 创建器、创建/确认测试、current bundle member 与 receipt 文档；已执行的 `6dd27d8` archive/receipt 作为历史输入证据不重建不改写 | 最终仓库只保留一个职责固定的通用抢卡入口，且历史研究证据身份不被纯收口伪装更新 | repository closure | 已采纳 |
