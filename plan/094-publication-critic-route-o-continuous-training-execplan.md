# Plan 094：Publication Critic Route O 连续训练与实质增益候选形成 ExecPlan

> 本计划是 Plan 094 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并按本计划指定的队列请求审查者批示。
> 普通代码、依赖、环境、连接、存储、checkpoint、恢复、测评和局部测试问题，应在已生效的阶段授权内自主修复、续跑或按需重跑；
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 094；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

保持 exact 1.7B、冻结 v8 train/validation、既有 pair/input/objective 家族、unseen 物理隔离和 Route O 九张量原参数范围不变，
复用 Plan 081/082 已有连续训练、checkpoint、恢复、观察和保留能力以及 Plan 087/090 的 Route O 资产，形成一条可持续推进和观察的
Route O 正式训练轨迹：

1. 在非付费阶段把 Route O 连续训练、完整 checkpoint、checkpoint 后测评、独立恢复、停止规则和资产保留接合到可审查状态；
2. 经审查者明确批准进入付费阶段后，在单张 US-TX-3 L40S 上先调通真实完整链路，再从冻结的可比较起点运行正式轨迹；
3. 每个观察点只有在完整 checkpoint 落盘并资格化后才进入测评，训练和测评故障可以分别恢复，不报废此前有效进度；
4. 持续比较同轮 exact base、previous、best、latest 和必要转折点，判断 Plan 090 的微弱信号能否扩大为有实际意义的
   better-than-base 候选；
5. 找到候选或形成有效无实质改善结论后，保留必要可恢复资产并立即释放计算资源。

任务必须诚实形成以下终态之一：

- `ROUTE_O_MATERIAL_CANDIDATE_RETAINED`：至少一个完整、可恢复 checkpoint 达到正式结果前冻结的实质改善标准；改善明显超出
  Plan 090 已知微弱包络，在有意义的 ranking、strict 或 operating 指标上产生变化，且没有造成另一 pair family 的明显退化。
- `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT`：一条有效、可恢复的正式连续训练轨迹按预冻结停止规则完整结束，但 checkpoint 只表现为
  微小变化、平台期、相互抵消或随后反转，没有形成实质 better-than-base 候选。
- `INCONCLUSIVE`：预算或持续外部基础设施问题在普通可修问题已合理修复后，仍使有效正式轨迹无法成立或无法完成必要恢复闭环。

前两个终态都表示 Plan 094 目标完成；负向终态不是执行失败，也不表示 Route O、exact 1.7B 或 objective 家族普遍失败。
`INCONCLUSIVE` 不得由普通代码、依赖、OOM、连接、存储、checkpoint、Pod 或短时网络问题冒充。本任务不要求产品 GO，不释放
unseen，不授予 M3-C1/M3-C2 资格，也不解锁 M3-D。

### 阶段门

Plan 094 只有两个授权阶段：

- **阶段 A：前置非付费准备。** 执行者在既有 Plan 094 worktree 中完成项目内实现、轻量 fixture/fake/focused 门禁、历史资产与只读
  live 状态核对、运行入口、正式判断/停止/保留规则预冻结和自审。阶段 A 不创建、启动或修改 Pod/网络卷，不上传数据，不下载或运行真实模型，
  不训练，不产生新增费用；不运行本地 Cargo、Docker 或真实本地模型。完成全部变动后提交 task branch，保持 worktree clean，并通过指定
  `codex queue` 请求审查者验收和付费准入。
- **阶段 B：经审查批准后的付费执行与资源收口。** 只有审查者通过指定队列明确回复“Plan 094 阶段 A 验收通过，批准进入付费阶段”后，
  本阶段的一次性用户授权才生效。先在真实环境保留已验证进度、从未打通处边修边跑；训练、完整 checkpoint、checkpoint 后测评、新进程恢复、
  小型结果回传和止费链完整打通后，再冻结正式条件并从干净、可比较的起点运行正式轨迹。形成合法终态后完成仍依赖 GPU 的验证、回传必要
  小型结果、释放全部任务 Pod并确认 compute `$0/h`；随后在本地收口结果和权威文档，提交 task branch并请求最终审查。用户于
  2026-08-26 暂停本阶段；该暂停已于 2026-08-27 由用户明确解除，审查者随后给出本节要求的明确阶段 B 批准。

### 完成/验收标准

- [ ] 阶段 A 与最终交付都只在 Plan 094 worktree 完成 tracked 修改并分别提交，worktree clean；未经用户批准不合并、不推送、不归档分支、
      不删除 worktree。
- [ ] 阶段 A 经审查者验收且审查者通过指定队列明确批准进入付费阶段；此前没有付费或外部写动作。
- [ ] exact 模型 revision/snapshot、v8 train/validation、pair/input/label、preferred-minus-dispreferred、scalar/projection、objective 家族、
      Route O 九张量范围和 unseen 隔离保持不变；没有回退到多路线或参数范围搜索。
- [ ] 在看到本任务正式 checkpoint 结果前，冻结正式起点与连续语义、同轮 base、实质改善 rubric、停止规则、观察/checkpoint 策略和资产
      保留原则；正式执行不事后改口径追逐正向结论。
- [ ] 实质改善 rubric 明确越过 Plan 090 微弱信号包络，并要求有意义的 ranking、strict 或 operating 变化；单个 BF16 格点、统一 offset、
      单一 ordering、仅 projected 微动、仅 train loss 改善或单纯无退化均不足以形成候选。
- [ ] 正式 base 与各 checkpoint 使用相同运行环境、模型输入、train/validation 和评价口径；只使用同轮 matching exact base delta，
      不混用 Plan 082 FP32 base 或其它历史绝对值冒充可比基线。
- [ ] checkpoint 覆盖模型、实际 trainable scope、optimizer/scheduler、RNG、data cursor 和连续选择状态；只有完整、原子发布并经读回资格化的
      checkpoint 才能进入测评或作为恢复点。
- [ ] 训练进度和测评进度可分别恢复；测评或连接故障不报废已资格化 checkpoint，也不要求建设通用队列、registry 或第二套云编排平台。
- [ ] 至少一个正式 checkpoint 经过另一新 OS 进程的实际恢复并继续训练或完成审查者接受的等强恢复验证。
- [ ] 每个正式观察点永久保留 train/validation 聚合指标、raw/projected pair margin 与逐 pair 方向，以及足以判断 ranking、strict、
      operating、pair 抵消和输出塌缩的既有指标。
- [ ] base、previous、training-best、checkpoint-backed best、latest、material candidate 与必要 turning point 角色明确；角色重合时复用同一
      checkpoint，不为形式完整复制权重或永久保存每个中间 checkpoint。
- [ ] 调试/commissioning 与正式结果清楚分开；真实链路调通后才冻结正式条件，从干净 namespace 运行正式轨迹，不把调试权重或拼接结果
      冒充正式证据。
- [ ] 阶段 B 创建资源前刷新 RunPod 余额、未结费用、库存、实际价格、Pod 和 `mwemzrn33y` 状态/可用空间；同时最多一个计费 L40S Pod，
      本任务新增外部费用硬上限为 5 USD，且留有 checkpoint、结果回传和止费余量。
- [ ] 只使用既有 `mwemzrn33y`；Plan 082/087/090 既有根保持只读，Plan 094 使用独立远端根。确需扩容时只可把该卷从 57GB 有界扩至
      最多 80GB；不创建第二卷，不删除现有卷。
- [ ] 完整权重只保留最终候选、latest、必要转折点和至少一个恢复合格 checkpoint；小型训练/测评指标永久保留。大型 checkpoint 保持在卷上，
      本地只回传验收和决策所需的小型结果。
- [ ] 无论合法终态为何，全部本任务 Pod均已停止/删除，并经实时查询确认 0 Pod、compute `$0/h`；网络卷继续保留，状态、容量、费率和必要
      资产位置明确。
- [ ] 相关轻量 Python 聚焦测试、必要 static/format/compile、改动 shell 的 `bash -n` 与 `git diff --check` 通过；不运行 Cargo、Docker、
      全 workspace、本地真实模型或 CI，fake、调试、正式、skip 和未运行项如实区分。
- [ ] 最终独立审查没有遗留 High/Medium correctness 或 functionality finding，并分别报告“验收通过/不通过”和“任务目标完成/失败”；
      正向候选不越界为随机 seed 稳定、独立 cohort、unseen、产品资格或 M3-D。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/full_model_training/` 中职责契合的连续训练、checkpoint、恢复、测评、保留、bundle、handoff 与 RunPod seam；
  可增加职责明确的 Plan 094 薄能力，但不得放松 Plan 081/082/087/090 历史 validator 或改写历史结果语义。
- Publication Critic 既有评价能力中真正通用的 aggregate、pair margin、ranking、strict、operating 和结果归档接缝；只做窄复用/泛化。
- `training/publication-critic-plan094/` 下体积合规、受跟踪的冻结合同、运行入口、依赖说明、source/data bundle 规则和 runbook；不提交模型、
  checkpoint、cache、venv 或原始训练输出。
- `eval/tests/` 中相称的 pure/fake/focused 测试与小型 fixture；`eval/results/publication-critic/` 中体积合规的正式结果摘要。
- 本计划“当前状态”和“关键决策记录”、受影响的 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`，最终验收后的
  `doc/WBS-COMPLETED.md`，以及有意义的精炼 `agent_log/`。
- 职责直接相关的既有 RunPod 脚本/接缝；库存紧张时必须使用根规则指定的 `scripts/create-runpod-when-ready.py`，不得扩大其职责。
- 普通依赖下载、公开源码/文档的只读查询，以及阶段 A 的 RunPod 只读状态核对。
- 阶段 B 生效后，通过既有安全入口查询 RunPod live 状态；在 US-TX-3 创建、启动、停止、重启、替换和删除至多一个同时计费的本任务 L40S
  Pod，挂载并写入既有卷的 Plan 094 独立 root；上传必要 clean source 与物理无 unseen 的冻结 train+validation bundle。
- 阶段 B 生效后，卷上确实缺失 exact 模型 snapshot 时，只读下载冻结 Hugging Face revision；不向 Hugging Face 上传或发布任何资产。
- 阶段 B 生效后，现有 57GB 卷实际不足时扩容至不超过 80GB；只清理本任务创建、已确认不再需要且已有替代恢复点或完整小型结果的临时资产
  与中间 checkpoint。

### 不允许修改或执行

- 冻结 v8 数据正文、label、pair、split、review、manifest、input/scalar/preferred 方向或 objective 家族；Plan 054/060/064/066/068/071/
  073/075/079/081/082/087/090 的冻结结果、正式 receipt、历史报告和终态。
- Route P/Q/R、其它参数更新范围、换模型、换数据集、改变 pair 方向、LoRA/QLoRA/其它 PEFT、量化训练、FP32 路线研究或无边界超参数搜索。
- unseen 的读取/render/score/释放、真实 API/Judge、产品 threshold、selection lock、Publication Critic 默认启用、M3-C1/M3-C2、M3-D 或
  上游基线升级。
- 换区、换卡、多 GPU、同时多个计费 Pod、新建第二卷、删除现有卷，或建设第二套训练、评价、checkpoint、云编排、审计、可信或费用平台。
- Plan 094 本地 Cargo、Docker、真实模型加载/推理、全 workspace、CI/PR，或修改 Plan 093 的构建锁、共享 target、资源门和开发环境文档。
- 修改宿主机配置、全局工具链、系统服务、其它仓库或来源不明资产；清理非本任务创建的 Pod、卷、模型、cache、checkpoint 或临时目录。
- 未经用户后续批准合并/rebase/cherry-pick main、推送 task branch、归档/重命名分支或删除 worktree。

### 不允许读取/查看

- v8 unseen-test 的正文、render、score、Judge 输入/输出，或任何需要先读 mixed 数据再过滤的路径；云端输入必须从物理无 unseen 的
  canonical train+validation 投影产生。
- `.env.local` 内容、token、API key、secret、私钥、密码或个人配置。只可按根 `AGENTS.md` 静默检查文件存在、非符号链接、`0600`
  和任务所需变量非空，并由严格数据 loader 向目标子进程注入 allowlist；不得 source、打印、复制、上传或记录凭据。
- 与任务无关的 ignored 资产、其它 worktree 的未提交修改、真实 publication/transcript/private reasoning 和项目外个人文件。
- Plan 093 的共享 target、正式全 workspace 证据正文或其它独占运行资产；只允许必要的 status/owner 元数据保护检查。

### Git-ignored 与主物理根边界

全部 tracked 修改在：

`/home/sjc/desktop/RONDO/.claude/worktrees/094-publication-critic-route-o-continuous-training/`

完成并提交，主工作区不得产生 tracked 修改。

linked worktree 不共享主物理根 ignored `eval-data/`。阶段 A 的 bundle dry-run、阶段 B 的上传源、回传小型结果、receipt、日志和任务运行工件，
如确有需要，允许直接使用主物理根 task-owned namespace：

`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan094/`

只读历史输入应通过已知 manifest/loader 精确消费 Plan 082/087/090 及 canonical train+validation 的任务相关对象，不递归浏览其它 ignored
namespace。执行者在阶段 A 和最终汇报中分别列出主物理根实际创建/保留的 Plan 094 ignored 路径、用途和大致体积；不建设逐文件审计台账。
主物理根 `.env.local` 只按上述安全入口使用。规划阶段没有创建该 ignored namespace，也没有直接修改主工作区。

## 3. 硬约束

以下约束只冻结研究正确性、付费门、费用/资源安全和交付边界；不锁死类名、schema、CLI 布局、内部模块拆分、训练强度、checkpoint 密度、
训练/测评调度或普通调试顺序。

1. **审查者付费门与一次性用户授权。** 用户已为本计划一次性授权第 2 节列出的项目内工作，以及阶段 B 的单 L40S、既有卷使用/有界扩容、
   exact snapshot 必要只读下载和不超过 5 USD 的新增外部费用；但阶段 B 在阶段 A 审查通过前不生效。只有审查者通过指定队列明确批准后才可
   创建/修改云资源、上传数据、下载或运行真实模型、训练和产生新增费用。范围内普通修复无需逐项请示；模型、数据、Route O 范围、预算、
   unseen、外部发布或产品动作变化必须先请示。
2. **exact 身份与 Route O 唯一范围。** exact 模型固定为
   `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`，snapshot content SHA-256 为
   `18d9edf7132d9c5e13bb0e59e3c2c6a42f82007fa17de464e20783755a171360`；数据固定为物理无 unseen 的 v8 train `128/58`、validation
   `55/26`。Route O 只更新 Layer 27 的 Q/K/V projection、Q/K norm、MLP gate/up projection、input/post-attention layernorm 九张量、
   `33,558,784` 个原参数。训练强度、更新/观察节奏和调度由执行者依真实动态决定，但不得扩大或切换参数范围、改变 objective 家族或回到路线搜索。
3. **判断口径先于正式结果。** 阶段 A 必须用 Plan 090 完整 signature 冻结小而透明的 material rubric、停止规则和保留规则。Plan 090 的
   已知微弱包络为 raw Boundary `+0.00390625`、projected Boundary `+0.00086113`、raw Within-PASS `-0.00334821`、projected
   Within-PASS `+0.00013894`、ROC AUC `+0.00140056`，balanced/strict/operating 没有改善。Plan 094 候选必须整体越过该弱信号，
   至少出现一项预先量化的有意义 ranking、strict 或 operating 改善，pair 改善不是统一 offset，且另一 family 不明显退化。具体等强数值门
   由执行者在阶段 A 提议并经审查，不在本计划锁死；rubric 不得在看到正式 checkpoint 后更改。
4. **连续起点和 matching base 冻结。** 阶段 A 核验 Plan 090 保留 checkpoint 的完整恢复语义后，选择从该恢复点继续，或从 exact base 在
   新 namespace 精确重建 Route O 首步再继续；不得把只有权重的部分恢复冒充 optimizer/RNG/data cursor 连续。正式前冻结起点、update 编号、
   optimizer/scheduler/RNG/data cursor 和 matching exact base 身份；所有质量判断只使用本轮同环境 delta。
5. **checkpoint 先于测评。** 正式顺序必须是训练推进 → 完整 checkpoint 原子落盘/manifest 资格化 → 从该 checkpoint 进入测评 → 继续训练。
   不得把先测内存态、后补 checkpoint 的 observation 冒充合格观察点。训练和测评可串行交错或适度流水，但 pending checkpoint 在测评完成前
   不得被 retention 清理；失败恢复只需轻薄状态接缝，不建设通用调度平台。
6. **同口径观察与 validation 分责。** train 才进入梯度；validation 只用于连续观察、停止和候选选择，unseen 不可达。base 和每个观察点
   使用同一 scorer/runtime，记录 train/validation objective/component、raw/projected Boundary 与 Within-PASS margin、逐 pair 方向、
   ranking/ROC、strict、balanced/best-balanced、冻结 operating 指标和必要输出跨度。validation 已用于选择，不能冒充独立 cohort。
7. **恢复必须证明可继续。** checkpoint 包含继续训练所需完整状态；至少一个正式 checkpoint 由不同 OS 新进程恢复并继续产生有效更新。
   若终止点使继续更新不合适，执行者可提出等强验证并由审查者判断，但单纯目录存在、模型 load 或 no-update score 默认不等强。
8. **先调通再冻结 formal。** 阶段 A 尽可能闭合轻量链；付费 commissioning 中保留已验证进度，从首个未打通处修复。真实模型核验/载入、
   非零且实际生效的 Route O 更新、完整 checkpoint、checkpoint 后测评、fresh-process resume、结果回传和止费链全部打通后，再冻结 clean
   source/environment/namespace 执行正式轨迹。影响研究语义的缺陷修复后，从相称干净边界重跑，不拼接无效结果。
9. **允许修故障，不允许修结果。** 代码、依赖、网络、下载、OOM、连接、Pod、存储、数值、checkpoint、恢复、测评和小型回传问题可在
   范围、硬件和预算不变时自主窄修、重试、续跑或替换本任务失效 Pod，不设机械次数上限。已形成的有效负面训练轨迹不得通过重跑、换路线、
   改标准或事后挑指标规避；无法分类时保留证据、完成其它安全工作并用队列请示。
10. **5 USD、单 Pod 与抢卡。** 阶段 B 安全可用额度为
    `min(5 USD, live 可用余额 - 已知未结费用 - checkpoint/回传/止费和短期存储余量)`；不授权充值。Pod、container disk、任务期间卷费用
    和本任务导致的扩容费用计入简单保守总账，5 USD 是硬上限而非消费目标。只使用 US-TX-3 单张 L40S，同时最多一个计费 Pod；库存紧张时
    必须使用 `scripts/create-runpod-when-ready.py`。该脚本只负责轮询、create 与不确定响应 exact-name 对账；创建后由执行者独立核验实际
    硬件、价格、机房和卷挂载，不符立即释放。
11. **卷和资产边界。** 复用 `mwemzrn33y`，Plan 082/087/090 roots 只读，Plan 094 写独立 root。空间确实不足时可有界扩容至 80GB，
    不得创建第二卷或删除现有卷。只清理本任务自有且已完成测评、不承担 candidate/latest/turning/recovery 角色的中间 checkpoint；完整小指标
    永久保留，不要求回传大型权重或重建 Plan 082 的 transfer/S3 设施。
12. **秘密和外发最小化。** source bundle 必须来自 Plan 094 clean commit；data bundle 从 canonical train+validation 投影产生并在上传前
    检查物理无 unseen/secret/无关 ignored 资产。`.env.local` 只由严格 loader 按 `KEY=VALUE` 数据解析并向目标进程注入必要变量；HF 只允许
    exact revision 下载，不上传或发布模型、数据、权重和结果。
13. **终态先止费再文档收口。** 一旦形成合法终态，先完成所有仍依赖 GPU 的恢复/工件核验，生成并回传必要小资产，然后立即 stop/delete
    全部任务 Pod并实时确认 0 Pod、compute `$0/h`。最终本地文档或普通审查问题不得保留/重启计费 Pod；卷继续保留并明确容量、费率、
    task root 与保留角色。
14. **Plan 093 并行隔离。** 本地只运行轻量 Python、static 和 fake/focused 门禁；不得读取/写入/清理 Plan 093 的
    `.codex/cargo-target/rondo-multi/`、`test-data/_retained-test-evidence/plan093-clean-full-workspace-baseline/runs/`、共享构建脚本、资源门或
    `doc/development-environment.md`。云端 L40S 可独立推进；若意外需要本地 Cargo、Docker 或真实模型，等待 Plan 093 完成并先请示。
15. **提交和结论边界。** 阶段 A 与最终交付均先提交 Plan 094 branch、保持 worktree clean，再发送队列消息并停止。未经用户批准不合并、
    推送、归档或删除 worktree。正向终态只表示同一冻结 validation 上的连续训练轨迹形成 material better-than-base 研究候选；不证明随机
    seed 稳定、独立 cohort 泛化、unseen、产品 GO 或下游解锁。负向终态只覆盖本次冻结轨迹。
16. **跨会话请示与验收。** 额外授权、计划外变数、不确定事项、阶段 A 技术验收和最终任务验收只使用下述 Codex 跨会话队列。执行者每条
    消息必须主动声明“我是 Plan 094 执行者”，发送后停止会话，不等待、不轮询、不重复发送。阶段 A 即使验收通过，审查者也必须通过同一
    队列明确批准进入付费阶段；当前用户暂停决定优先，执行者即使收到技术验收也不得申请或接受付费批准，不得产生费用或外部写状态。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a04183-c0c1-7f22-a100-e03b611be70c 替换。
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

在本计划中，`<阶段性任务>` 依次用于“Plan 094 非付费准备阶段 A”和“Plan 094 最终任务”。当前阶段 A 队列消息只申请技术验收，并须明确
`PAID_STAGE_PAUSED_BY_USER / PAID_GATE_CLOSED`；不得请求或接受“批准进入付费阶段”。如果用户以后明确恢复付费阶段，仍须通过同一队列取得
原计划规定的明确付费批准，才可产生费用或外部写状态。最终验收仍按通用文案处理。

## 4. 软性建议

以下建议用于帮助执行者高效起步，不是固定路线。执行者可依据 live code、显存、吞吐和训练动态采用更简洁、优雅、架构更契合的等强或更优
方案，并在关键决策记录中说明有实质影响的偏离。

- 优先复用 Plan 081/082 的原子 checkpoint、全树 manifest/读回资格化、optimizer/scheduler/RNG/data cursor 恢复、分段续跑和
  base/previous/best/latest/turning-point 角色；Plan 094 只补 Route O 续训起点、checkpoint-first 测评、material rubric 和终态收口。
  不要为复用而放松 Plan 082 的 fresh-base 历史 validator；语义不契合时增加 Plan 094 薄 adapter/controller 更干净。
- Plan 081/082 现有 controller 是 update 后先观察再存 checkpoint，Plan 094 可在既有职责边界上做小型顺序适配，让测评明确消费已资格化
  checkpoint。训练/测评独立恢复可以是一份简单的 pending/evaluated 状态或幂等 receipt，不需要通用作业队列。
- Plan 082 的单 `comparison_value` finalizer 不足以表达实质改善；可复用 freeze、checkpoint-backed selection 和 retention 结构，新增一份
  Plan 094 小型整体判定，不需要规则引擎或统计显著性平台。
- 正式起点优先根据卷上 Plan 090 checkpoint 的真实完整性决定。若其 optimizer/RNG/data cursor 足以连续恢复，可直接续训；否则从 exact
  base 在新 namespace 重建冻结 Route O 起步状态更诚实。两者均须保留同轮 exact base anchor，不沿用 Plan 082 FP32 base 绝对值。
- commissioning 可按“环境/资产核验 → 模型 load → Route O 有效更新 → checkpoint 原子发布/读回 → 从 checkpoint 测评 → 新进程恢复续训
  → 小型结果与止费”递进。遇到普通问题保留已验证节点，从未打通处继续；全链稳定后才冻结正式轨迹。
- 训练强度、LR、batch、scheduler、观察/checkpoint 密度、串行或适度流水调度由实测决定。围绕少量高信息观察点收敛，不为耗尽预算而继续
  无信息训练，也不预建大规模超参数搜索或并行训练设施。
- material rubric 宜综合 raw Boundary、projected Boundary/Within-PASS、raw Within-PASS、ROC/ranking、strict、balanced/operating、
  pair 分布和输出跨度。可以基于 Plan 090 格点/ordering 量级冻结简明阈值，但不必建设统计因果或可信证明体系。
- checkpoint retention 宜延迟到对应测评完成；使用 role manifest 让 candidate/latest/turning/recovery 重合时复用同一对象。空间不足先清理
  已测且无角色的本任务中间 checkpoint，再在确有必要时有界扩容，不预先扩容。
- RunPod 查询、观测和资源操作可使用现有最可靠入口；库存紧张时按根规则使用通用抢卡脚本。创建后独立核验，停止本地脚本不等于释放 Pod。
- 聚焦测试优先覆盖：checkpoint-first 顺序、pending checkpoint 不被清理、测评幂等恢复、完整状态 fresh-process 续训、validation 不进梯度且
  不漂移训练状态、BF16 非零梯度但参数无实际变化、material/negative/terminal 分支和 Plan 082/090 相邻合同。只跑受影响的轻量门禁。
- 可以用少量子智能体做只读 census、局部实现或最终独立审查；共享状态机、云端资源和提交由单一执行者负责，避免并行写冲突。

### 建议执行步骤

**阶段 A：非付费准备**

1. 核对 live code、Plan 090 freeze/result/checkpoint locator、Plan 082 连续训练能力、exact 模型/数据 identity 和当前只读 RunPod/卷状态。
2. 落地必要薄能力、Plan 094 合同/入口和 focused tests；在看到正式结果前冻结 material/stop/retention 与正式连续语义。
3. 检查 diff、测试、未运行项和主物理 ignored 资产，更新计划动态状态与精炼日志，提交 Plan 094 分支并通过队列申请阶段 A 验收/付费准入。

**阶段 B：付费调通、正式轨迹与收口**

1. 收到审查者明确批准后，刷新 live 预算、Pod、库存、价格、卷容量和资产；创建至多一个 L40S Pod并独立核验。
2. 逐段调通完整真实链，修复普通接缝；稳定后冻结 clean source/environment/namespace 和正式条件。
3. 运行正式连续轨迹并持续观察；找到 material candidate、达到预冻结有效无改善停止规则或触及闭环预算边界时停止。
4. 保留必要 checkpoint/小指标并完成恢复验证，回传必要小结果，释放全部 Pod并确认 compute `$0/h`，卷继续保留。
5. 收口正式结果、当前 WBS、计划动态状态和精炼实施日志，运行相称轻量门禁并提交；通过队列请求最终独立验收。验收通过后再由审查者
   收口 `doc/WBS-COMPLETED.md` 和审查日志，不提前冒充最终接受。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 clean，`main = origin/main = e30c8a3d4ed5148aeb93c95d15b2285c49c0bac3`；Plan 093 worktree
  正在执行冷全 workspace，动态状态为 `FULL_WORKSPACE_PENDING`。
- 2026-08-26：从上述 clean main 创建
  `.claude/worktrees/094-publication-critic-route-o-continuous-training` / `worktree-094-publication-critic-route-o-continuous-training`。
- 2026-08-26：只读核对根规则、README、顶层/三期 WBS、plan 模板、Plan 081/082/087/090 合同、关键日志/结果、连续训练源码与测试入口，
  并完成三路并行只读复核；未读取 `.env.local`、unseen、模型权重、checkpoint 正文或无关 ignored 资产。
- 2026-08-26：编制 Plan 094 ExecPlan，并窄同步顶层/三期 WBS 的当前任务、付费门和与 Plan 093 并行边界。规划阶段未运行测试、Cargo、
  Docker、真实模型或云端查询，未创建/修改 Pod/卷、上传/下载或产生新增费用；用户提供的 0 Pod、57GB 卷和价格/余额相关事实仍须执行前
  live 刷新。
- 2026-08-26：两路最终只读复核分别检查训练/checkpoint 技术合同与授权/文档职责，均为 `ACCEPT`，无 High/Medium
  correctness/functionality finding；未增加额外 GPU 审查门、审计或可信设施。
- 2026-08-26：本次规划没有在主工作区直接创建 tracked 或 ignored 文件；后续执行若需要 worktree 不共享的运行资产，只使用并单独汇报
  主物理根 `eval-data/publication-critic/plan094/`。
- 2026-08-26：阶段 A 已实现 Plan 094 专用薄控制层：每次 update 后先原子发布并深读回完整 checkpoint，再以永久小 overlay 完成
  train/validation 测评；pending checkpoint 不参与清理，overlay 可在不重复 update 的情况下幂等补做。完整状态包含模型、实际 Route O
  scope、optimizer/scheduler、RNG、data cursor、连续选择与恢复角色。
- 2026-08-26：冻结 primary 起点为 Plan 090 第二 BF16 的精确完整 checkpoint 导入；导入门核对 ID、3,591,369,941 bytes、content
  SHA-256、历史 controller/runtime、optimizer/scheduler/RNG/data cursor、同轮 exact base 和恢复后分数。若 commissioning 未打通该导入，
  只允许从 exact base 在新 namespace 重建 Route O step 1，不拼接部分状态；Plan 090 历史 checkpoint 只作 previous、不能成为 Plan 094 候选。
- 2026-08-26：在正式结果前冻结 material/停止/保留合同：候选须 raw Boundary 至少 `+0.005859375`、projected Boundary 越过
  Plan 090 弱包络、pair 改变非统一 offset 且 Boundary 改善数比恶化数至少多 4，同时满足另一 family/strict/FPR/输出跨度 companion
  和至少一个两-ordering、strict 或 operating 离散事件；首个 material 停止，否则 step 4 三点无信号平台或 step 6 有效负向停止。
  永久保留小结果，完整 checkpoint 最多六个角色去重对象；六是本轨迹的理论总观察点上限，并优先保护 material/latest/recovery/turning。
- 2026-08-26：轻量 fake/focused 门禁已覆盖 checkpoint-first 顺序、评测失败幂等恢复、Plan 090 完整导入 identity drift、新进程恢复后继续
  update、material 终止延迟到恢复闭环、有效负向终态、5 USD 单调预算、0 Pod finalizer、Stage B fail-closed、task-root 写边界和 clean
  source archive exact-tree/secret-free round trip；Plan 094 15/15、相邻 Plan 090 16/16 和独立复核的 Plan 081/082/090 fake training
  64/64 通过，独立复核无遗留 High/Medium finding。未运行 Cargo、Docker、真实模型、训练或云写。
- 2026-08-26：阶段 A 只读 RunPod 快照为余额 `$5.4443864251`、账户费率 `$0.006/h`、0 Pod、`mwemzrn33y` 位于 US-TX-3 且 57GB、
  Secure L40S `$0.99/h` 且当时无库存。该快照只用于准备，阶段 B 创建资源前必须重新刷新。阶段 A 未创建主物理根 Plan 094 ignored namespace。
- 2026-08-26：首轮独立审查以 1 High / 3 Medium 拒绝阶段 A；整改已将 bootstrap 与后续 paid launch 绑定五分钟内 task-owned budget
  snapshot、核验费率和有限 timeout，Plan 090 外部点只保留 previous 语义，本任务训练 claim 只认自有 checkpoint，并把 Hub token 清除移到
  snapshot 分支之前。未改变模型、数据、Route O、material rubric、停止或保留规则。
- 2026-08-27：整改复审确认上述三个 Medium 已闭合，但指出 Pod 内 timeout 不会释放仍计费的 Pod。第二轮窄整改新增 Plan 094 host-only
  absolute lifecycle guard：从 provider start 固定唯一终止 trigger，脱离操作者会话等待，到点复用 Plan 087 exact terminal helper
  stop/delete 并确认 0 Pod；创建时总预算和每个 paid segment 都计入 60 秒 worker kill grace 与 360 秒终止确认余量，后续 launch 不得延长
  trigger。Plan 094 focused 17/17、相邻 Plan 090 与 Plan 087 terminal 20/20 及 compile/static 门禁通过；未修改根抢卡脚本，也未建设通用预算或
  云编排设施。用户同时暂停付费阶段。
- 2026-08-27：第二轮整改复审确认 lifecycle High 已闭合，仅余 0 High / 1 Medium：最终 receipt 误用 terminal helper 调用前时刻作为
  `confirmed_at`。窄修在 exact 0 Pod 校验成功后重取完成时刻，超过 360 秒 confirmation deadline 则拒绝发布成功结果；推进 250 秒及越界
  361 秒的 fake-clock 回归分别覆盖真实确认时刻与 fail-closed，Plan 094 delivery 加 Plan 087 terminal 定向测试 9/9 通过。Plan 087 历史 helper
  保持不变。
- 2026-08-27：最终技术复审确认上述 Medium 已闭合，无遗留 High/Medium correctness 或 functionality finding；阶段 A 技术验收通过。
  用户暂停阶段 B 的决定保持有效，付费门未开启，尚未运行真实模型或形成研究终态。
- 2026-08-27：用户明确解除付费暂停，审查者按指定队列确认“Plan 094 阶段 A 验收通过，批准进入付费阶段”。创建资源前的 live 刷新确认
  余额 `$5.4333030917`、0 Pod、57GB 卷 `mwemzrn33y` 位于 US-TX-3、账户卷费率 `$0.006/h`、Secure L40S `$0.99/h`，当时 L40S 无库存。
- 2026-08-27：通过根抢卡入口创建并独立核验唯一 Pod `0bsry5tbei7p4o`：Secure US-TX-3 NVIDIA L40S、`$0.99/h`、冻结 image、单 GPU
  与既有卷挂载均符合合同；宿主 lifecycle guard 固定最晚 `2026-08-27T11:17:42.117Z` 止费。空间上界确有需要时仅把卷从 57GB 扩至
  70GB；用户后续放宽到 120GB 未使用，`$0.82` closure reserve 含完成后至少 6 小时卷保留的 `$0.06` 保守余量。
- 2026-08-27：commissioning 已证明真实 Route O update、完整 checkpoint、checkpoint 后测评、fresh-process 恢复继续和小型回传。
  guarded Plan 090 import 因历史 controller cursor 不兼容按合同拒绝，formal 使用预冻结 exact-base fallback 在 clean namespace 重建 step 1，
  未拼接部分历史状态。
- 2026-08-27：正式 step 1--4 均完成 checkpoint-first train/validation overlay；step 1 只重复 Plan 090 微弱信号，step 2--4 raw Boundary
  转负且所有 meaningful event 均为 false。step 4 按预冻结规则形成 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT` /
  `prefrozen_three_checkpoint_no_material_plateau`。这是有效负向研究终态，不重跑规避。
- 2026-08-27：steps 1/3/4 三份保留 checkpoint 已在挂载卷上完成 terminal deep qualification；step 3 为 fresh-process recovery，step 4
  为 latest。2,017,280-byte / 181-member 小型包 SHA-256 `a0b227bdc606e76c0e17b1500e9770665631f576b9d409d66e30a2f9b32e9ea4`
  已回传并复核不含权重或 source/data tar；大型资产留在约 13.22GB 的远端 Plan 094 root。

### 当前工作

- 正式研究轨迹与全部 Pod 依赖验证已完成。按用户最新顺序，唯一 Pod 保留等待预释放审查；绝对 lifecycle guard 不取消。

### 本任务剩余步骤

- 预释放审查接受后立即释放唯一 Pod，实时确认 exact 0 Pod / compute `$0/h`，随后仅用已回传小包与 qualification receipt 在本地运行
  terminal finalizer；大型 checkpoint/权重继续留卷。
- 收口最终结果、当前 WBS、完成历史和实施日志，运行相称轻量门禁并提交，再申请最终独立验收。
- 本任务完成后冻结本计划；不在此安排独立 cohort、unseen、产品资格或 M3-D。

### 阻塞项

- 无实现阻塞。Plan 093 正在冷全 workspace；本任务只运行轻量本地门禁，不与其竞争重型资源。
- 正常资源释放等待预释放审查；若审查未在绝对 guard trigger 前返回，guard 按 5 USD 硬边界优先自动释放 Pod，不等待人工操作。

### 当前验收状态

- `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT / POD_RETAINED_PENDING_PRE_RELEASE_REVIEW / PAID_GUARD_ARMED`。

### 交接边界

- 执行者继续使用已创建的 Plan 094 worktree，不另建工作树，不在主工作区修改 tracked 文件。
- 阶段 A 完成全部变动和相称轻量门禁后，先提交并保持 clean，再按指定队列交付 commit、diff/实现摘要、聚焦测试、正式规则、运行入口、
  预算/资源收口方案、ignored 路径和未运行项；发送后立即停止会话。
- 用户与审查者已共同打开阶段 B；执行者可在一次性授权内自主修复、续跑和必要重跑，原则边界变化才通过队列请示。
- 用户要求先完成全部 Pod 依赖工作并经预释放审查，再释放 Pod。执行者先提交当前小型结果/资格收据投影并保持 clean，通过队列申请预释放审查；
  接受后完成 zero-Pod finalizer、最终 tracked 收口和第二次最终验收。
- 本任务任何阶段都不自行合并、推送、归档分支或删除 worktree；等待用户后续批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 用户一次性授权阶段 A 与条件性阶段 B，但阶段 B 只有审查者明确批准后才生效 | 在付费前完成独立 correctness/functionality 审查，同时避免重复逐项授权 | authorization | 已采纳 |
| 002 | exact 1.7B、v8/pair/input/objective 家族与 Route O 九张量范围冻结；训练强度和调度由执行者决定 | 任务研究变量是 Route O 连续轨迹，不是重新搜索参数范围；避免过度约束实现 | research contract | 已采纳 |
| 003 | material 标准在阶段 A 冻结，必须越过 Plan 090 弱包络并产生有意义离散/排序/operating 变化 | 防止把已知微小格点和单 ordering 再次包装成实质候选 | candidate semantics | 已采纳 |
| 004 | 正式观察只消费已完整落盘和资格化的 checkpoint，训练/测评进度可分别恢复 | 让一次测评或连接故障不报废连续训练轨迹，并保证候选可恢复 | pipeline | 已采纳 |
| 005 | 复用 Plan 081/082 底层能力，语义不契合时增加 Plan 094 薄适配，不放松历史 validator | 兼顾架构复用与 Route O 续训/checkpoint-first/material rubric 新语义 | architecture | 已采纳 |
| 006 | 正式起点由阶段 A 基于 Plan 090 checkpoint 完整性选择：完整续训或 exact-base 重建 Route O 起步 | 不把部分恢复冒充连续状态，也不给实现路线不必要的预设 | recovery | 已采纳 |
| 007 | `VALID_NO_MATERIAL_IMPROVEMENT` 是完成终态；普通问题可修复重跑，有效负面结果不可重跑规避 | 允许诚实研究结论，又不给窄故障过早终止任务 | terminal semantics | 已采纳 |
| 008 | 单张 US-TX-3 L40S、同时最多一个计费 Pod、5 USD 硬上限；用户后续允许卷按需至 120GB，实际只扩到 70GB | 在当前资产和预算内控制费用/重复资源风险，不把上限当扩容目标 | cloud resources | 已采纳 |
| 009 | 只回传必要小结果，大权重留在既有卷；先完成 Pod 依赖工作和预释放审查，再释放 Pod并本地 finalizer | 适配用户指定验收顺序，同时由绝对 guard 保留硬止费上界 | retention/handoff | 已采纳 |
| 010 | 本地阶段不碰 Plan 093 的 Cargo/shared target/证据/资源门写集 | 允许云端训练准备与冷全 workspace 并行且不争用重型资源 | concurrency | 已采纳 |
| 011 | tracked 工作只在 094 worktree；ignored 运行资产只落主物理根 Plan 094 namespace并单独汇报 | linked worktree 不共享 `eval-data`，同时保护主工作区 tracked 状态 | workspace | 已采纳 |
| 012 | 额外请示、阶段 A 付费申请和最终验收只走指定 Codex 队列，消息主动表明身份并发送后停止 | 满足用户指定的批示、自动唤醒和独立验收方式 | coordination | 已采纳 |
| 013 | 每个阶段只提交工作树；合并、推送、分支归档和 worktree 删除等待用户批准 | 遵循本次明确 Git 停止点 | delivery | 已采纳 |
| 014 | 使用 Plan 094 两阶段 controller：完整 checkpoint 先资格化，测评结果再以 checkpoint hash 绑定的小型原子 overlay 发布 | 复用 Plan 081 原子 checkpoint/深恢复，同时让测评失败不报废训练进度或重复 update | architecture | 已采纳 |
| 015 | primary 从精确 Plan 090 完整 checkpoint 接续；历史点只作 previous，导入失败则 commissioning 从 exact base 重建 step 1 | 保留真实 optimizer/RNG/data 连续性，同时避免把旧结果包装成新候选或拼接部分恢复 | continuation | 已采纳 |
| 016 | 正式 model 终态必须已有本任务 checkpoint 被不同 OS 进程恢复并继续一次有效 update；若先出现 material，终止状态延迟到该闭环完成 | 满足“可恢复且可继续”而不因早停丢失恢复证据 | recovery | 已采纳 |
| 017 | resume 只接受 artifact store 当前最新保留 checkpoint；terminal-deferred 立即停下且同一 controller 不得继续 update | 防止从旧 best/recovery 分叉重训规避已形成的有效正向或负向轨迹，并节省紧预算 | recovery | 已采纳 |
| 018 | 新进程恢复要求完整 runtime core 精确一致，但允许任务自有 replacement Pod 的 provider ID/name 与 hostname 改变，并同时记录旧/新绑定 | 支持授权范围内替换失效 Pod，同时不放松模型、环境、recipe、precision 或数据连续性 | runtime | 已采纳 |
| 019 | 完整 checkpoint 保留上限为全轨迹理论最大六个，material/latest/recovery/turning 先于 best 角色 | 消除四个槽位与最多两个 turning point 的硬保护冲突，仍保持严格有界且不建设第二套资产体系 | retention | 已采纳 |
| 020 | 每个真实 Pod 在创建时冻结绝对 lifecycle trigger，并由宿主侧脱离会话的 Plan 094 guard 复用 Plan 087 helper 到点精确止费 | 覆盖 launch 间隙、会话中断和 worker 结束后的持续计费，不把职责塞进根抢卡脚本 | cloud safety | 已采纳 |
| 021 | 用户暂停 Plan 094 付费阶段；阶段 A 技术复审不得转化为付费批准 | 遵循最新用户决定并保持所有外部写与新增费用关闭 | authorization | 已采纳 |
| 022 | 用户解除付费暂停且审查者明确批准阶段 B；创建前 live 刷新后仅按冻结资源与 5 USD 上限执行 | 阶段 B 双门已满足，同时保留创建时的易变状态和硬预算重新核验 | authorization | 已采纳 |
| 023 | guarded Plan 090 import 失败后按预冻结 exact-base fallback 重建 formal step 1，不修补历史 cursor 或拼接状态 | commissioning 证明历史 cursor 不满足精确续训门；fallback 保持模型、数据、Route O 与正式比较口径不变 | continuation | 已采纳 |
| 024 | Pod 释放前生成绑定 controller state 和全部现存 checkpoint 哈希的 qualification receipt；zero-Pod finalizer 消费小型 receipt | 满足先做完挂载卷深读、权重留卷和审查后释放的顺序，不建设第二套 handoff/审计体系 | terminal handoff | 已采纳 |
| 025 | closure reserve 提高到 `$0.82`，其中保守预留 `$0.06` 覆盖完成后至少 6 小时 70GB 卷保留 | 服从用户新增存储余量要求，同时仍使生命周期总上界低于 5 USD | budget | 已采纳 |
