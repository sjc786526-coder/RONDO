# Plan 082：Publication Critic 1.7B 云端连续训练与候选形成 ExecPlan

> 本计划是 Plan 082 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并按本计划指定的队列请求审查者批示。
> 普通代码、依赖、环境、连接、存储、checkpoint、恢复和局部测试问题，应在已生效的阶段授权内自主修复并按需重跑；
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 082；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

消费 Plan 081 已验收的 exact 1.7B 非 PEFT fixture/fake 连续训练合同与中性 seam，在单张 RunPod A40 48GB 或 L40S 48GB 上完成：

1. 付费前把真实训练 adapter、物理无 unseen 的云端 bundle、运行入口、恢复与归档接缝准备到可审查状态；
2. 经最终审查者验收阶段 A、且用户本人明确人工批准付费后，在真实 GPU 上逐步完成模型加载、显存与更新可行性、连续 validation
   观察、完整 checkpoint 和新进程恢复；
3. 依据 commissioning 实测完成有界的训练参数开发，从部分原模型参数直接更新起步，并可按真实训练动态扩大更新范围；
4. commissioning 全链打通后，冻结结果相关源码、模型、数据、环境、实际 recipe、参数范围、观测点和 better-than-base 规则，
   从 exact base 与空 namespace 执行一轮干净正式训练；
5. 用正式轮形成一个同口径优于 exact 1.7B base 的候选，或者形成当前路线在有效正式轮中没有优于 base checkpoint 的研究结论；
6. 先以小型身份、指标、恢复和资源事实完成保留 Pod 的 GPU 阶段验收，审查者确认不再需要 GPU 后立即释放 Pod；再在本地容量安全窗口
   通过网络卷 S3-compatible API 无 Pod 回传并校验正式大型资产，完成最终验收，网络卷保留到用户本人批准删除。

任务必须诚实形成以下终态之一：

- `TRAINING_IMPROVEMENT_FOUND`：有效干净正式轮中至少一个 checkpoint 按预先冻结的同口径规则优于正式 base anchor；
- `VALID_NO_IMPROVEMENT`：有效干净正式轮完整结束，但没有 checkpoint 按该规则优于 base；
- `INCONCLUSIVE`：预算、库存、允许 GPU 的真实资源/兼容性限制或持续外部基础设施阻断，在普通可修问题已合理修复后仍使有效干净
  正式轮未能成立。

前两个终态都表示 Plan 082 目标完成，`VALID_NO_IMPROVEMENT` 不是执行失败。`INCONCLUSIVE` 是诚实的资源/基础设施终态，
但不表示训练路线失败，也不表示任务目标已经完成。Plan 082 不要求达到历史产品 GO 门限，不授予本地部署资格，不释放 unseen-test，
不启用 Publication Critic，也不解锁 M3-D。

### 阶段门

Plan 082 明确分为两个授权阶段：

- **阶段 A：付费前准备。** 执行者可完成项目内实现、轻量测试、source/data bundle 准备、runbook、静态资源预算与自审，
  然后提交 task branch 并请求最终审查者验收。阶段 A 不创建计费 Pod/卷，不下载真实模型，不上传数据，不训练。
- **阶段 B：付费 commissioning、参数开发与正式轮。** 最终审查者先基于阶段 A 的 live code、测试、bundle 身份、命令入口、预算和
  资源收口方案完成验收；验收通过只表示付费准备就绪，不能代替用户本人批准。只有用户随后明确人工批准进入付费阶段，且审查者通过
  指定队列把该人工批准传达给执行者后，本阶段授权才生效，不要求固定字面 token。执行者自己的自审、子智能体审查或审查者自行判断
  均不能替代用户人工批准；授权生效后，范围内普通修复、替换失效 Pod、续跑和重跑无需逐项重复请示。

任务有三个主要队列申请/验收点：

1. 阶段 A 提交后申请付费准备验收；审查者验收通过后仍须用户本人明确人工批准，审查者再把该批准传达给执行者。
2. 正式训练结束后保留 Pod/网络卷，只回传小型关键事实并申请 GPU 阶段验收；审查者确认无需继续操作 GPU 后，执行者立即释放 Pod。
3. 在 0 Pod 状态下完成大型资产回传和字节身份校验后申请最终任务验收；最终验收后再转请用户本人决定是否删除网络卷。

普通整改仍在相应阶段授权内自主完成。第 2 项审查要求继续 GPU 操作时，Pod 保持原状，修复后的实际训练/验证活动继续累计到训练预算；
第 3 项之前等待 Plan 083 与宿主容量安全窗口不需要重新创建 transfer Pod。

### 完成/验收标准

- [ ] 阶段 A 从 `main@90e905168039effbea796753d0f29148830a243f` 创建的 Plan 082 专用 worktree 实施；所有 tracked 改动、
      轻量测试、runbook 和小型合同均在 task branch 中完成并提交，主工作区无 tracked 修改。
- [ ] 真实训练入口消费 Plan 081 的 route、typed train/validation identity、连续 observation、checkpoint/retention/resume 等中性能力；
      Plan 081 当前 `fixture_fake` controller/候选声明不得仅靠翻转字段冒充真实训练。不得放松或改写 Plan 060/066/081 的历史 validator，
      职责不契合时可提取中性 seam 或新增小而明确的 Plan 082 controller/adapter/入口。
- [ ] source bundle 只包含必要的已提交源码与轻量合同；data bundle 从 canonical v8 投影构造并在物理上只含 train+validation，
      云端环境拿不到 unseen-test。两类 bundle 均有可复核身份和最小解包/入口测试，不包含密钥、模型权重或无关项目文件。
- [ ] exact 模型保持为
      `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`，冻结 v8、pair/input/label、
      Binary/Pair objective/loss、preferred-minus-dispreferred 方向、`logits[:,0]`、higher-is-better 和现有投影语义不漂移；禁止 LoRA、
      QLoRA、其它 PEFT、量化训练和更换模型。若实测认为必须改变 objective/loss 或其组件权重，应作为原则性扩围请示，不静默混入 recipe。
- [ ] 阶段 A 的 pure/fake/focused tests 至少覆盖真实运行能力与 Plan 081 中性 seam 的接缝、实际 trainable inventory 记录、
      validation 不进梯度、bundle 无 unseen、checkpoint 新进程恢复入口、正式 freeze/终态判定，以及 Plan 082 参数化的无 Pod S3
      inventory/manifest/续传/校验/拒绝覆盖接缝；只运行直接受影响的轻量 Python 门禁，不访问真实云资源。
- [ ] 最终审查者对阶段 A 无遗留高/中等级 correctness/functionality finding；随后取得用户本人明确人工付费批准并由审查者通过指定队列
      传达后，执行者才创建任何计费资源。阶段 A 验收通过本身不构成付费批准。
- [ ] 正式创建/启动 Pod 前，通过 RunPod 实时控制面同时刷新 A40 48GB 与 L40S 48GB 的库存状态、价格、数据中心/网络卷兼容性和账户
      费用基线；首选 A40，A40 不可及时获得或实测不适合时可切换 L40S，同时最多一个计费 GPU 实例，不扩展到第三种 GPU、多 GPU
      或多模型竞赛。
- [ ] commissioning 从最小真实链路逐步打通 exact 模型核验与加载、一次有效更新、连续 observation、完整 checkpoint、
      新 OS 进程恢复继续更新、best/latest/turning-point 归档和安全回传。调试期可保留已验证进度并从首个未打通处继续，
      其权重和指标不得冒充正式候选。
- [ ] 参数开发使用冻结 train 和 validation 语义；初始从部分原模型参数直接更新，具体范围、扩大时机、优化器、学习率、batch、
      更新数、scheduler、观测频率与停止条件由真实实测决定并完整记录，不开展无边界搜索或论文式消融。
- [ ] freeze 在观察任何正式训练结果前完成并记录：已提交 source identity、exact model/data/environment、实际 recipe、完整参数 inventory/
      scope 序列、seed、观测/checkpoint 点、同 cohort base 比较规则与容差、保留规则。任何结果相关条件改变都必须回到相称 commissioning
      后重新 freeze，不得把改变后的运行续接到旧正式结果。
- [ ] 干净正式轮使用新的空 namespace 和 exact base 从头开始；先在冻结 validation cohort 上形成正式 base anchor，再按冻结 recipe
      完整训练和观察。只有该轮的 checkpoint 可形成 `TRAINING_IMPROVEMENT_FOUND` 或 `VALID_NO_IMPROVEMENT`。
- [ ] base、previous、training-best、latest 与 better-than-base candidate 语义保持分离；所有 observation 永久保留小型聚合指标、
      逐 pair 方向和 signed margin。better-than-base 规则不得在看到正式结果后改选有利指标或容差。
- [ ] 至少一个完整 checkpoint 通过另一新进程的实际 load/restore/继续更新验证；正式 best/latest、必要关键转折点和至少一个经恢复验证的
      完整 checkpoint 在网络卷中由 manifest 精确列出。角色重合时允许同一工件承担多个角色，不要求复制权重或保留每个 observation 的完整模型。
- [ ] 全部 commissioning、参数开发、formal 和审查整改的实际训练活动累计不超过 12 小时、对应外部费用累计不超过 15 USD；从首次
      计费资源创建到第一次训练完成验收请求的非等待期全部计入，审查要求修复后恢复的活动继续累计。训练完成后的强制审查等待、0 Pod
      大型回传和等待用户批准删卷的必要保留费用不占用这两个训练上限，但必须另行持续记录和报告。账户余额不足不构成充值授权。
- [ ] 从任务费用基线起，训练与保留/回传费用合并的累计实际或保守上界首次达到 10 USD 时，只发送一次非阻断告警给用户；不停止远端
      训练、Pod 或当前有效流程。告警不扩大预算，也不替代后续资源状态报告。
- [ ] 正式训练完成后的第一次 GPU 阶段验收只回传小型关键信息：源码/recipe/freeze 身份、指标与逐 pair margin、checkpoint
      inventory/path/size/SHA-256、新进程恢复 receipt、费用和资源状态；不回传或本地复验大型 checkpoint。此时保持正式 Pod/网络卷，
      审查者明确确认无需继续操作 GPU 后立即停止/删除/释放 Pod并核对 compute 费用归零。
- [ ] 大型资产只在 0 Pod、Plan 083 不占用共享磁盘且宿主容量安全的窗口，通过 Plan 082 网络卷实时 region/endpoint 对应的 S3-compatible
      API manifest 驱动回传到 task-owned ignored namespace；支持 `.part` Range 续传、逐对象 size/SHA-256 校验、原子发布和拒绝覆盖。
      无安全窗口时保留网络卷等待，不重建 transfer Pod。全部必要资产下载并验证后申请最终任务验收；网络卷继续保留，只有用户本人
      另行明确人工批准才可删除，并如实报告其持续费率、累计费用和状态。
- [ ] 相关轻量 Python/云端专项门禁、改动 shell 的 `bash -n`、必要 compile/format 检查与 `git diff --check` 通过；不运行 Cargo、
      Docker、全 workspace、本地真实模型或 CI。fake、commissioning、formal、skip 和未运行项分别如实记录。
- [ ] 执行者依次维护 `GPU_REVIEW_PENDING / POD_RETAINED`、`GPU_REVIEW_PASS / ZERO_POD / HANDOFF_PENDING` 和
      `FINAL_REVIEW_PENDING / VOLUME_RETAINED_PENDING_USER_DELETE`，每次先提交 task branch 再发队列消息；不提前写最终完成结论。
      最终审查者关闭高/中等级 correctness/functionality finding 后收口 WBS、`doc/WBS-COMPLETED.md` 与验收日志并提交。网络卷随后按用户
      人工决定处理；资源尾项可继续窄更新本计划当前状态和日志。任何一方都不合并、不推送、不归档分支、不删除 worktree。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/full_model_training/` 中 Plan 081 连续训练能力的真实模型 adapter、云端入口、freeze/finalize、
  checkpoint/恢复和小型结果归档接缝；职责更清楚时可新建 Plan 082 专用薄模块，不固定模块名或内部 API。
- `eval/rondo_eval/publication_critic/selection/`、`base_quality/` 或其它 Publication Critic 既有能力中真正通用的 validation metrics、
  模型 snapshot 核验、source identity 或 archive 接缝；只做窄复用/泛化，不改变历史计划结果、Judge、selection lock 或 unseen 语义。
- `eval/rondo_eval/publication_critic/local_deployment/` 中 Plan 068 已验证的严格凭据 loader、S3 download core 和 manifest 解析能力；保留
  Plan 068 历史 wrapper/常量语义，抽取职责契合的中性 seam 或新增 Plan 082 薄 adapter/config，不直接调用硬编码旧卷/旧 endpoint/旧 manifest
  的 Plan 068 CLI。
- `training/publication-critic-plan082/` 下轻量、受跟踪的 route/run/freeze 合同、依赖说明、source/data bundle 工具、RunPod 入口和 runbook；
  不提交模型、checkpoint、cache、venv 或训练输出。
- `scripts/` 中确有必要且职责可复用的 RunPod 单资源查询/创建/等待/替换辅助工具；若复用旧 plan-specific 工具会扭曲语义，
  可新增 Plan 082 专用小工具，不建设通用云编排平台。
- `eval/tests/` 中相称的 pure/fake/focused 测试与小型 fixture；`eval/results/publication-critic/` 中体积合规、可读的正式结果摘要。
- 本计划“当前状态”和“关键决策记录”、`doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、最终完成历史
  `doc/WBS-COMPLETED.md` 与有意义的精炼 `agent_log/`；其中 COMPLETED 只由最终审查者在验收通过后收口。并行 WBS 修改只做语义窄更新，
  后整合者基于最新 main 手工处理。
- 普通依赖/公开源码与文档的只读查询；阶段 B 生效后，从 Hugging Face 公开下载并核验上述冻结 revision 到任务云端存储。
- 用户人工付费批准生效后，通过既有安全入口查询 RunPod 库存、价格、资源与费用；创建、启动和运行一张 A40 或 L40S Pod，
  创建并挂载满足任务所需的最小实用任务网络卷，上传必要源码和物理无 unseen 的 train+validation bundle并回传任务工件。
  commissioning 中失效/不可用 Pod 可在单实例边界内替换；正式训练 Pod 只有审查者明确确认不再需要后才可释放。网络卷删除始终需要
  用户本人另行明确人工批准。
- 审查者批准释放正式 Pod 后，通过 RunPod 控制面确认 0 Pod，并通过网络卷实时 S3-compatible endpoint 对任务 manifest 做 inventory、
  续传下载和字节身份校验；该数据面动作无需、也不得为传输重新创建 Pod。

### 不允许修改或执行

- `training/publication-critic-v8/` 及其继承数据的正文、label、pair、split、review、manifest、objective/loss 语义或冻结身份；Plan 054/060/064/066/068/
  071/073/075/079/081 的冻结结果、正式 receipt、历史报告和计划终态。
- Publication Critic 产品默认、`multidev/` 产品行为、threshold、selection lock、M3-C2/unseen 流程、M3-D、本地部署资格或产品启用。
- LoRA、QLoRA、其它 PEFT、量化训练、模型转换作为训练对象、换模型、第三种 GPU、多 GPU、并行计费 Pod、真实 API、Judge、
  unseen-test、HF 远端写入、发布、CI/PR 或上游基线升级。
- Plan 082 本地 Docker、Cargo、真实模型加载/推理、全 workspace 测试或第二个 Cargo target；除硬约束 12 明确授权的精确
  `debug/incremental` 清理外，不得写入、删除或改动 Plan 083 构建产物。
- 删除 `debug/deps`、整个共享 target、既有或非 Plan 082 任务自有模型资产、来源不明 cache/Pod/卷/工件，或在 Plan 083 重型命令
  运行时清理共享 target。正式训练 Pod 在审查者确认前不得释放；Plan 082 任务网络卷在用户本人明确人工批准前不得删除。
- 未经用户后续批准合并/rebase/cherry-pick main、推送 task branch、归档/重命名分支、删除 worktree，或修改宿主机配置、
  全局工具链、系统服务和其它仓库。

### 不允许读取/查看

- v8 unseen-test 的正文、render、score、Judge 输入/输出，或任何需要先读 mixed 数据再过滤的路径；bundle 构造必须从物理无 unseen
  的 canonical train+validation 投影开始。
- `.env.local` 内容、token、API key、secret、私钥、密码或个人配置。只可按根 `AGENTS.md` 静默检查文件存在、非符号链接、`0600`
  和任务所需变量非空；不得 source、打印、复制、上传或记录凭据。
- 与任务无关的项目外个人文件、其它仓库、真实 publication/transcript/private reasoning、来源不明 ignored 资产，以及无必要的
  历史模型/checkpoint 正文。

### Git-ignored 与主物理根边界

全部 tracked 修改在
`/home/sjc/desktop/RONDO/.claude/worktrees/082-publication-critic-cloud-continuous-training/` 完成并提交，主工作区不得产生 tracked 修改。

linked worktree 不共享主根 ignored `eval-data/`。阶段 A 如需生成 bundle dry-run、阶段 B 的上传源、回传原始 observation/checkpoint、
费用和资源终态，允许直接写主物理根的任务专用 namespace：

`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan082/`

该目录只能包含 Plan 082 输入投影、运行/回传工件和必要临时文件；逐项记录实际创建/修改的路径、体积、权限、保留/清理状态。
不得扫描或借用其它 ignored namespace。canonical 物理无 unseen 输入只读来源仍是主物理根既有 Plan 066 train+validation bundle；
执行者应通过已验收 loader/manifest 精确消费，不递归浏览无关模型、checkpoint 或其它资产。

Plan 082 计划编制阶段没有创建上述 ignored namespace，也没有必须直接在主工作区完成的修改。未来真实执行中，只有该 task-owned
`eval-data/.../plan082/` 运行资产因 gitignore/worktree 隔离必须落在主物理根；tracked 源码、测试、文档和日志不得据此绕过 worktree。

## 3. 硬约束

以下约束只冻结结果正确性、付费门、模型/数据语义、资源安全和交付边界，不锁死实现布局、类名、配置 schema、具体超参数或调试路线。

1. **付费双阶段门。** 阶段 A 可以自主实现、测试、提交和整改；任何创建计费 Pod/网络卷、上传数据、下载真实模型、云端训练或其它
   付费/外部写动作，都必须先由最终审查者验收阶段 A，再由用户本人明确人工批准进入付费阶段。审查者验收通过、自审或子智能体意见
   都不是付费批准；执行者只在审查者通过指定队列明确传达“已取得用户人工批准”后行动。批准生效后，本计划列出的阶段 B 普通修复/
   续跑无需重复请示；预算、模型、数据、GPU 集合或原则边界变化仍须停下并通过指定队列请求批示。
2. **模型、监督和 unseen 不漂移。** exact 1.7B revision、冻结 v8、pair/input/label、Binary/Pair objective/loss、
   preferred-minus-dispreferred 方向、scalar/projection 语义保持不变；只允许原参数直接更新，禁止 PEFT 与量化训练。train 进入梯度，
   validation 只作观察/选择/停止与 scope 决策，unseen 在本任务全程物理不可达。objective/loss 或其组件权重变化不属于已授权 recipe 开发。
3. **复用能力而非改写历史。** Plan 081 controller/observation/artifact 语义是当前起点，Plan 060/066/079 提供可复用云端、模型核验、
   数据、checkpoint 和恢复经验。不得放松 plan-specific 历史 validator；强行复用会产生耦合或语义扭曲时，应建立架构契合的专用能力，
   但不重复建设第二套数据、评价、checkpoint、registry、审计或可信平台。
4. **commissioning 允许探索，formal 必须冻结。** commissioning 可逐段调试、保留已验证进度、调整 recipe/参数范围并从未打通处继续；
   只有完整链路成功后才能 freeze。formal 从 clean committed source、exact base 和空 namespace 完整运行，不拼接 commissioning 权重或结果，
   不在运行中改变冻结 recipe、scope 序列、seed、比较规则或观测点。
5. **同环境 base 与预先冻结选择。** 正式 base anchor 与训练 checkpoint 使用同一模型输入、validation cohort、runtime 和指标口径；
   better-than-base 规则及容差在正式训练结果出现前冻结。training-best 未优于 base 时只能形成 `VALID_NO_IMPROVEMENT`，不得冒充候选。
6. **恢复与工件职责完整。** observation snapshot 与完整训练 checkpoint 分责；完整 checkpoint 覆盖模型、实际 trainable scope、
   optimizer/scheduler/RNG/data cursor 和连续选择状态，并由新进程实际恢复继续。只清理任务自有且已有替代恢复点的工件；小型 observation/
   pair margin 永久保留，同一权重可复用多个保留角色。
7. **修复、重试与正式结果边界。** 代码、依赖、环境、下载、网络、Pod、存储、OOM、进程、checkpoint、归档与回传问题可在阶段授权和
   双预算内自主修复、重试、续跑或换允许的 GPU，不设机械次数/slot 上限。外部中断后的 formal 只能在结果相关冻结条件不变时用新空
   namespace 重跑；一旦形成完整有效模型质量结果，不得为求正结论重跑、换 seed、改规则或事后挑指标。
8. **单 GPU、实时双候选与训练预算。** 同时最多一个计费 GPU；每次正式创建/启动前都同时刷新 A40 48GB 与 L40S 48GB 的库存、价格和
   网络卷兼容性，A40 优先，A40 不可及时获得或 commissioning 证明不适合时可换 L40S，无需为该允许切换重新申请。所有尝试累计 GPU
   实际训练活动 `<=12h`，对应外部费用累计 `<=15 USD`。活动期包括首次计费资源创建后的准备、commissioning、参数开发、formal、
   GPU 依赖验证及审查要求的 GPU 整改；队列等待期间的资源保留不伪装成训练活动，单独记时/计费。训练完成后的强制 GPU 审查等待、
   0 Pod S3 回传和等待用户删卷批准产生的必要费用不占训练上限，但持续报告；它们不授权额外训练、额外 GPU 或充值。规划时库存/价格
   不能替代创建前刷新。任务所有费用从同一 baseline 合并观察，首次达到 10 USD 时按指定队列发送一次非阻断告警；远端任务继续运行。
9. **GPU 阶段验收先闭合 Pod 依赖。** 正式训练结束后保留 Pod 与网络卷，只向审查者交付小型源码/recipe/freeze 身份、指标与 pair margin、
   checkpoint inventory/path/size/hash、新进程恢复 receipt、费用和资源状态，不回传或本地复验大型 checkpoint。该审查主要判断所有合理
   可预见且仍需 GPU/Pod 的 correctness/functionality 事项：exact 环境/模型/数据/recipe/freeze、正式轮与 base 比较有效性、训练/恢复事实、
   云端工件完整性、是否需要补跑及 Pod/卷事实。无需 GPU 的代码整理、S3 回传、本地字节校验、文档和相邻回归留到最终验收，不在此扩成总终审。
   审查者只有确认这些 GPU 事项闭合且无需继续操作 GPU 后才批准释放；执行者收到确认后立即停止/删除/释放 Pod并核对 compute 费用归零。
   释放后若意外发现原则性 P1/P2 确实必须重建 GPU，不得自行新开 Pod，按计划外变数通过队列请示。
10. **网络卷承接无 Pod 回传。** Plan 082 必须新建并挂载满足任务所需的最小实用网络卷，不使用临时本地盘代替持久任务存储，也不恢复或
    依赖 Plan 079 旧卷。Pod 释放并由控制面确认 0 Pod 后，使用网络卷实时 region/endpoint 的 S3-compatible API 读取 Plan 082 task root；
    不为 inventory/download 重建 transfer Pod。窄复用 Plan 068 严格 loader、manifest 驱动的 bounded download、`.part` Range 续传、
    size/SHA-256 校验和安全发布语义：正确既有文件可幂等跳过，任何身份不符既有文件拒绝覆盖。volume ID、region/endpoint、task root、允许
    前缀、ignored destination 与 bootstrap manifest key/bytes/hash 必须绑定 Plan 082 本轮 freeze/receipt，禁止使用 Plan 068 的
    `hi3iaz8rsr`、US-KS-2 endpoint、旧 root 或旧 artifact manifest。网络卷只有用户本人另行明确人工批准才可删除。
11. **与 Plan 083 的本地资源隔离。** Plan 082 不运行 Cargo/Docker/本地真实模型，不创建第二 target。Plan 083 的重型命令继续通过
    共享 build lock/cache，并只在获批命令进程内使用 `270000000000/285000000000/290000000000` 三个 override；不修改长期默认值。
    Plan 082 的普通文件传输不会自动受这些环境变量保护，故大型回传前后必须单独测量项目实际占用、Windows `C:` 实际余量和重型 owner：
    达 270GB 停止扩大本地工件并定位增长，达 285GB 主动停止相关写入，290GB 绝不可突破；无法取得 Windows `C:` 真实计数或其实际
    剩余空间低于 `50000000000` B 时停止大型回传。不得用 WSL 虚拟余量代替宿主计数。
12. **共享 incremental 清理是最后手段。** 只有确认无 Cargo 重型 owner，并在整个清理窗口持有 canonical build lock 或等强互斥、
    防止 Plan 083 同时启动重型命令，且目标为非符号链接并真实解析到
    `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target/debug/incremental`
    时，才可按需要精确清理其中可再生内容，并记录前后体积；清理后释放互斥。不得扩大到 `debug/deps`、整个 target 或其它缓存。
    Plan 083 正在运行或无法建立全窗口互斥时不清理，也不开始/继续大型 S3 回传；正式 Pod 在 GPU 阶段验收通过后照常立即释放，必要工件
    留在网络卷，以 0 Pod 状态等待安全窗口。
13. **秘密与上传最小化。** `.env.local` 只作静默属性/所需变量检查并由安全 loader 按 `KEY=VALUE` 数据解析，仅向目标子进程注入必要值；
    source/data archive 均在上传前检查物理成员，禁止 secret、unseen、无关源码、ignored 资产、旧模型或 checkpoint 混入。普通公开 HF 下载
    仅固定 revision，不向 HF 写入任何内容。无 Pod S3 客户端只通过现有严格 loader 从主根 `.env.local` 读取
    `RUNPOD_S3_ACCESS_KEY_ID`、`RUNPOD_S3_SECRET_ACCESS_KEY` 两个 allowlisted 非空值并直接注入目标 client；不得直接打开、source、打印、
    复制、上传或记录凭据，也不得把凭据放入 CLI 参数、config、receipt 或 stdout/stderr。
14. **结论和文档归位。** fake 不是 GPU 证据，commissioning 不是 formal，validation 不是 M3-C2/unseen/产品 GO。WBS 只记当前路线和终态，
    plan 只记任务内状态/决策，agent_log 精炼记实质批次。执行者在 GPU 阶段、小型证据验收通过并释放 Pod 后记录 0 Pod；大型资产回传验证后
    提交最终候选。最终审查者只要求无需 GPU 的修复/复验并在关闭高/中等级 correctness/functionality finding 后收口最终 WBS、
    `doc/WBS-COMPLETED.md` 与验收日志；若卷仍在则明确记 `VOLUME_RETAINED_PENDING_USER_DELETE`，不冒充资源归零。合并、推送、分支归档和
    worktree 删除等待用户批准。
15. **跨会话请示与验收。** 额外授权、计划外变数、不确定事项、阶段 A 付费申请、GPU 阶段小型证据验收、无 Pod 大型回传后的最终验收，
    只通过下述用户指定的 Codex
    跨会话队列联系审查者。执行者每条消息必须主动声明“我是 Plan 082 执行者”，发送后停止会话，不等待、不轮询、不重复发送。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03c5c-d717-7a12-a387-c70fe54f2f41 替换。
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

在本计划中，上述 `<阶段性任务>` 模板依次用于“付费前阶段 A”“保留 Pod 的 GPU 阶段小型证据验收”“0 Pod 大型资产回传后的最终验收”。
第二次消息明确请求审查者只关闭仍可能需要 GPU/Pod 的事项并决定是否释放 Pod；第三次消息才提交 S3 回传、本地字节校验和其余无需 GPU
的最终证据。对于第二次 GPU 阶段验收，用户最新要求优先于上述通用的“验收通过不再通知”约定：即使验收通过，审查者也必须通过同一
队列明确回复“无需继续操作 GPU，可以释放 Pod”，执行者未收到该明确回复前不得释放。网络卷删除批准必须由用户本人作出，不能由
审查者按一般技术决策代替；最终验收消息应同时请审查者把删卷决定交给用户，只有用户批准时才再通知执行者执行。

## 4. 软性建议

以下建议基于 `main@90e9051` live code，只帮助执行者高效起步。执行者可以采用更简洁、优雅且与现有架构契合的等强方案，
并在关键决策记录中说明有实质影响的偏离。

- 优先复用 Plan 081 的 train/validation identity、scope、observation、retention 和 fresh-adapter recovery 语义；先核对
  `ContinuousTrainingController` 的 `fixture_fake`/候选边界是否适合抽取中性 core，不得只翻转 claim 字段就挂真实 Torch adapter。
  若真实异步云进程生命周期或真实候选语义与该 controller 不契合，可建立小型 Plan 082 controller/task runner/codec adapter，
  无需复制数据、指标和 artifact store。
- Plan 066 已有 exact 1.7B 模型/数据、BF16 更新、checkpoint 和新进程恢复基元；Plan 079 已有 source archive、快照核验、RunPod launch/
  worker 和安全回传经验。优先抽取真正通用的部分；保留旧 runbook/receipt 的历史身份，Plan 082 使用自己的 namespace 和结果 schema。
- Plan 068 已真实证明在 0 Pod 状态下通过网络卷 S3-compatible API 完成交接：120/120 个对象、24,385,153,354 bytes，包含完整 checkpoint。
  Plan 082 可窄复用其 `load_allowlisted_secret_values` 与 `DownloadSpec`/安全路径/`.part` Range/SHA-256/拒绝覆盖 core，但旧
  `local_deployment.handoff_cli` 把卷 `hi3iaz8rsr`、US-KS-2 endpoint、旧 task root 和 manifest 写死，不能原样调用。宜由 Plan 082 的
  非密钥 freeze/receipt 参数化 volume、实时 region/endpoint、task root、允许前缀、ignored destination 与 bootstrap manifest
  key/bytes/hash；具体 CLI/schema 可由执行者选择更干净的等强设计。
- RunPod 的查询、观测、费用核对和适合的资源操作软性优先使用对 Agent 友好的 RunPod MCP；MCP 不擅长的网络卷挂载 Pod 创建或其它动作
  可使用现有 RunPod CLI。两者如何组合由执行者按 live 能力自主选择，只要身份、单实例、预算和删除边界一致。
- 正式开 Pod 前先通过实时控制面同时查看 A40/L40S 库存，选定一个 `gpu-id + data-center-id` 并创建/核验 Plan 082 网络卷。手动创建
  抢不到时，可直接复用 `scripts/create-runpod-plan079-initial-when-ready.py`；以下是由当前 `--help` 与脚本构造逻辑核对出的最小模板，
  占位符必须用本次 live 查询和已批准资源事实替换，不是可直接照抄的历史生产命令：

  ```bash
  python scripts/create-runpod-plan079-initial-when-ready.py \
    --pod-name 'rondo-plan082-<unique-name>' \
    --gpu-id '<live-selected-A40-or-L40S-gpu-id>' \
    --gpu-count 1 \
    --cloud-type '<live-compatible-cloud-type>' \
    --data-center-id '<live-compatible-data-center-id>' \
    --image '<approved-image>' \
    --container-disk-gb <positive-gb> \
    --network-volume-id '<plan082-network-volume-id>' \
    --volume-mount-path /workspace \
    --port 22/tcp \
    --poll-seconds 5 \
    --query-timeout-seconds 15 \
    --create-timeout-seconds 30 \
    --reconciliation-grace-seconds 30 \
    --timeout-seconds <finite-budget-aware-seconds>
  ```

  该脚本只轮询一个已选候选并执行 create/reconciliation；不同时选择 A40/L40S，不查价格/预算/卷资格，也不负责 readiness、start、
  stop 或 delete。全任务同一时刻只运行一个 monitor/creator；切换 L40S 前先停止旧 monitor 并重新刷新双候选。Pod 名必须唯一；create
  不确定或人工中断时，至少等满 `--reconciliation-grace-seconds` 并按 exact name 对账后，才能用同名再次启动 creator。显式传有限、
  预算感知的 `--timeout-seconds`，不要使用默认无限等待。成功后仍由 MCP/CLI 复核实际 Pod、GPU、网络卷和价格；停止本地脚本不会释放 Pod。
- 阶段 A 可按“真实 adapter 单元测试 → 物理无 unseen bundle → 云端 CLI/runbook → checkpoint/freeze/finalize fake 集成 → 预算/资源收口演练”推进。
  不需要预建云资源 registry、通用 scheduler、签名链、复杂账本或第二套自动验收平台。
- commissioning 可按“环境/快照核验 → 模型 load 与显存 → 单个小更新 → observation → checkpoint → 新进程 resume → 连续小段 → 参数开发”
  递进。遇到普通问题保留已验证节点并从首个未打通处修复，完整闭环后再确定 formal recipe。
- 初始 trainable scope 宜以真实参数 inventory 定义，而非依赖脆弱的字符串猜测；具体更新哪些层/模块、是否扩大到更多块以及 optimizer/
  scheduler 组合由实测决定。参数开发应围绕少量可解释观察收敛，不追求遍历所有组合。
- comparison policy 可复用既有 validation aggregate 和 signed pair margin，明确一个小而透明的主比较规则及必要容差；完整指标继续归档供诊断。
  这里不需要统计显著性平台、因果归因或把历史产品门限硬搬成训练成功条件。
- artifact retention 优先用 role manifest 表达 base/best/latest/turning-point/recovery；角色重合就复用同一对象。正式回传前先在云端淘汰已评价、
  不承担恢复或诊断职责的 task-owned checkpoint，以减少本地容量压力。
- GPU 阶段验收前，先在云端生成小型、稳定的 bootstrap artifact manifest；至少绑定每个保留对象的远端 key、bytes、SHA-256，以及
  volume/region/endpoint/task root。Pod 释放后先由控制面确认 0 Pod，再运行 Plan 082 `inventory`；本地容量安全时反复运行 `download`，
  正确既有文件幂等跳过、`.part` 续传、身份不符文件拒绝覆盖。这里的入口名只是软建议，不锁死实现。
- 10 USD 告警只发一次，消息应主动声明 Plan 082 执行者身份、当前训练/等待费用拆分、Pod/卷状态与仍在运行的远端任务，并注明“信息告警，
  无需停工或作预算决策，请确认收到后唤醒我继续监控”。按队列规则发送后停止本地会话，但不得停止 detached 远端训练或释放资源。
- 单元/集成测试聚焦新增能力和相邻 Plan 081/066/079 回归；云端专项测试聚焦真实 adapter、恢复、freeze/formal、费用与终态。
  不为了“更绿”扩大到 Cargo、Docker、本地真实模型或全仓测试。
- A40/L40S 的 cloud tier、数据中心、网络卷容量、镜像、依赖安装方式和进程 launcher 由实时兼容性、库存、稳定性和预算决定，
  但持久存储形态固定为任务网络卷。不把规划时价格快照写成长期事实；任何选择都记录实际 GPU、driver/CUDA、依赖、显存、费率和计费时间。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-25：确认主工作区 clean，`main = origin/main = 90e905168039effbea796753d0f29148830a243f`；Plan 083 已有独立
  `.claude/worktrees/083-m4-z-core-durable-team-closure`，本任务不复用或修改其现场。
- 2026-08-25：从该基线创建
  `.claude/worktrees/082-publication-critic-cloud-continuous-training` / `worktree-082-publication-critic-cloud-continuous-training`。
- 2026-08-25：只读核对根规则、README、顶层/三期 WBS、plan 模板、Plan 079/081、相关日志、Plan 081 live controller/contracts/tests、
  Plan 066/079 云端入口与 gitignore 边界；未读取 `.env.local` 内容、unseen、模型权重或 checkpoint。
- 2026-08-25：静默确认主根 `.env.local` 是普通文件且权限为 `0600`；没有检查、打印或记录其中变量和值。
- 2026-08-25：计划编制未运行测试、Cargo、Docker、真实模型、RunPod/HF 查询或任何付费/外部写动作；用户提供的库存、价格、
  项目占用、RunPod 0 active Pod 与 Plan 079 旧卷 404 均作为规划时输入，尚未由本任务实时复核。具体快照为：项目约 237.4GB；
  A40 48GB 库存 `LOW`、Secure 约 `$0.44/h`；L40S 48GB 库存 `LOW`、Community 约 `$0.79/h`、Secure 约 `$0.99/h`。
  这些价格/库存只用于规划，阶段 B 创建资源前必须刷新。
- 2026-08-25：编制时发现 WBS 仍保留“Plan 079 卷继续计费”的旧事实；本规划 diff 已按用户提供的 404 新状态窄更新顶层/三期 WBS。
  阶段 A/创建资源前仍通过既有安全入口只读复核，不把旧卷当作前置或尝试恢复。
- 2026-08-25：三路只读调查与两轮独立计划复核完成；已关闭文档收口顺序、WBS 立项状态、`INCONCLUSIVE` 资源终态、
  shared incremental 全窗口互斥、Windows `C:` 50GB 停止线、objective/loss、历史 23 USD 与 Plan 082 独立 15 USD 等 P2。
  当时版本最终复核为 `ACCEPT`，未增加复杂审计/可信/预算平台。
- 2026-08-25：按用户追加要求把阶段 A 审查与用户人工付费批准拆开；正式开 Pod 前须同时刷新 A40/L40S，持久存储固定为网络卷，
  正式 Pod 保留到审查者确认无需再用，网络卷删除另须用户人工批准；RunPod 控制软性优先 MCP、CLI 补位。
- 2026-08-25：只读核对已合并的 Plan 079 抢 Pod 脚本及当前 `--help`，确认
  `scripts/create-runpod-plan079-initial-when-ready.py` 支持单目标轮询、网络卷挂载、exact-name 去重和不确定创建后的完整对账；已写入
  Plan 082 有限时长命令模板与边界。历史材料未保存可复核的完整生产调用，因此没有把模板冒充历史命令。
- 2026-08-25：用户选择资源保留优先；12 小时/15 USD 约束实际训练活动，训练完成后的 GPU 审查等待、0 Pod 回传和卷删除等待费用分开
  持续报告；总累计费用首次达到 10 USD 时非阻断告警。GPU 阶段验收只关闭仍需 Pod 的事项，Pod 释放后其余无需 GPU 的发现留给最终验收。
- 2026-08-25：只读复核 Plan 068 无 Pod S3 成功证据和 live handoff 实现；确认历史已在 0 Pod 下交接 120/120 个对象、
  24,385,153,354 bytes（含完整 checkpoint），并确认当前 CLI 硬编码旧卷/region/root/manifest，Plan 082 只能窄复用底层严格能力后参数化。
- 2026-08-25：按资源保留优先、三次主要队列验收、GPU 专项审查分工、10 USD 非阻断告警与无 Pod S3 交接修订 ExecPlan/两份 WBS；
  最新独立复核为 `ACCEPT`，无剩余 P1/P2 correctness/functionality finding，`git diff --check` 通过。
- 2026-08-25：阶段 A 已落地 Plan 082 专用 Torch adapter、真实 controller/profile、typed run spec、source/data bundle、formal
  freeze/finalize、提前发布的进程启动 receipt、新进程 checkpoint 恢复、checkpoint-backed 候选/保留和参数化 0 Pod S3 handoff；
  Plan 081 与 Plan 068 只增加职责中性的窄 seam，历史固定 wrapper/fixture claim 保持不变。
- 2026-08-25：云端入口/runbook 已闭合显式 venv/PYTHONPATH、可重入 source/data bootstrap、有限时长单 launcher、exact source
  receipt、完整参数 inventory、冻结恢复点和 handoff bootstrap/binding 生产入口；运行位置、recipe、scope、控制点、卷/region/root 均为
  typed 参数，未建设签名链、工件台账、通用编排器或第二套数据体系。
- 2026-08-25：主物理根 `eval-data/publication-critic/plan082/stage-a-final/` 已从 canonical Plan 066 物理 train+validation bundle
  完成 prepare→archive→extract：四个文件、archive 808,960 bytes / SHA-256
  `af1d9ac744529a6366b8158549fd74a653d6596313cc9769c255fd2dcecb2fc6`，train 128/58、validation 55/26、commissioning
  6/2、unseen 0；目录总计 2,412,268 bytes，全部文件 `0600`。早期同规模 `stage-a-dry-run/` 保留为本任务临时验证资产。
- 2026-08-25：Plan 082 focused + Plan 081/068 相邻回归、shell/compile/ruff/diff 门正在最终收口；未运行 Cargo、Docker、全 workspace、
  本地真实模型，未访问 RunPod/HF、未创建 Pod/卷、未上传/下载或产生费用，未读取 `.env.local`、unseen 或模型/checkpoint 正文。
- 2026-08-26：阶段 A 首轮独立验收为 `PHASE_A_REVIEW_NOT_ACCEPTED`，确认 9 项 Medium correctness/functionality finding；付费门保持
  关闭。整改已局部闭合数值 no-op、formal exact base/真实工件、训练前输出冲突、完整实际环境、真实 retention bootstrap、固定本地
  S3 环境/入口、稳定 ready receipt、validation 参数/buffer/RNG 状态和 Plan 081 fixture profile 边界，并补直接负例。
- 2026-08-26：主物理根新增 ignored `handoff-runtime-v1` 固定 boto3 环境和 `stage-a-remediation-dry-run` 非秘密 fixture；inventory/download
  两个 preflight 均显示 exact worktree/Python prefix、`secret_access=false`、`network_access=false`。整改未访问 RunPod/HF/S3、凭据、真实模型，
  未创建 Pod/卷、未训练或产生费用。
- 2026-08-26：阶段 A 整改复验确认原 9 项失效路径已关闭，但剩余 2 项 Medium：单参数探针可在其它 scope 参数已变化后误报 no-op，
  retained bootstrap 输出可污染正式 artifact tree。两项均已局部修复并补直接负例；付费门继续关闭，正在形成新提交并申请复验。

### 当前工作

- 阶段 A 整改复验剩余的 2 项 finding 已完成局部整改与非付费验证，正在形成新提交并请求复验；阶段 B 未授权。

### 本任务剩余步骤

1. 最终审查者验收阶段 A；验收通过后等待用户本人明确人工批准付费，审查者通过指定队列传达已取得该批准后才进入下一步。
2. 阶段 B：同时刷新 A40/L40S 与网络卷兼容性/费用事实，创建单 GPU 与最小实用网络卷，完成真实环境 commissioning；总累计费用首次
   达到 10 USD 时发一次非阻断告警，远端任务继续。
3. 在 commissioning 中有界开发训练参数，完整打通后提交并冻结结果相关 source/environment/recipe/比较规则。
4. 从 exact base 和空 namespace 运行一轮干净 formal，形成 improvement 或 valid no-improvement；若外部边界始终阻断则形成 inconclusive。
5. 只回传小型关键证据，保留正式 Pod/网络卷；更新 `GPU_REVIEW_PENDING / POD_RETAINED`、WBS 候选事实与执行日志，提交 clean task branch
   并按队列请求 GPU 阶段验收。
6. 审查者只关闭所有合理可预见且仍需 GPU/Pod 的事项；执行者按审查结论修复/补跑。审查者明确确认无需再操作 GPU 后，执行者立即释放
   Pod、核对 0 Pod/compute 费用归零并提交资源状态；无需 GPU 的事项留给最终验收。
7. 等待 Plan 083 不占用共享磁盘且宿主容量安全窗口；不创建 transfer Pod，通过网络卷 S3-compatible API 完成 inventory、`.part`
   Range 续传、全部必要对象 bytes/SHA-256 校验，提交 `FINAL_REVIEW_PENDING / VOLUME_RETAINED_PENDING_USER_DELETE` 并按队列申请最终验收。
8. 最终审查者只要求无需 GPU 的修复/复验并收口最终文档；验收后转请用户本人决定是否删除网络卷。执行者仅在收到用户人工批准后删除卷，
   记录终态并通知；所有人继续等待用户决定合并/推送。

### 阻塞项

- 阶段 A 无计划级阻塞。
- 阶段 B 的计费授权尚未生效；最终审查者完成阶段 A 验收后，仍必须等待用户本人明确人工批准并由审查者通过队列传达。
- 实际 RunPod 库存、价格、旧资源终态、网络卷/S3 兼容性和本地大工件回传窗口均须在相应动作前实时复核；规划时快照不构成运行事实。

### 当前验收状态

- `PHASE_A_REVIEW_REMEDIATION_PENDING / PAID_GATE_PENDING`。

### 交接边界

- 执行者使用已创建的 Plan 082 worktree，不另建工作树，不在主工作区修改 tracked 文件。
- 阶段 A 完成时先提交并向最终审查者交付：commit、diff 摘要、聚焦测试、source/data bundle 身份与成员边界、计划运行命令、
  预算/资源收口方案、未运行项和 ignored 资产清单；按本计划指定的 Codex 队列发送阶段性验收消息后立即停止。审查通过后继续等待用户
  人工付费批准；未收到审查者明确传达的用户批准前不创建计费资源。
- 用户人工付费批准生效后，执行者可在本计划范围内自主完成普通修复与重跑；原则边界或预算变化才重新请示。
- 正式训练结束后只交付小型关键证据并保留 Pod/网络卷，提交后用同一模板请求 GPU 阶段验收。审查者批准释放即表示仍需 GPU 的事项已
  合理闭合；执行者立即释放 Pod并记录 0 Pod，不提前回传大型 checkpoint。
- 大型资产在 0 Pod 和安全容量窗口通过 S3 回传并校验后，执行者再次提交并用同一模板请求最终验收；此阶段只整改无需 GPU 的问题。
  最终验收后网络卷删除继续等待用户人工批准，资源尾项通知也通过同一队列往返。
- 本任务完成后冻结本计划；后续部署资格、是否重入 M3-C2 或路线调整只链接 WBS，不在本计划继续安排。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 阶段 A 先经最终审查者验收，随后仍须用户本人明确人工批准付费；审查者只负责传达批准 | 尽可能在计费前暴露问题，并保留用户对真实费用的最终决定权 | authorization | 已采纳 |
| 002 | 继续 exact 1.7B、冻结 v8/pair/input/objective/loss/scalar，禁止 PEFT/量化训练 | Plan 081 已冻结当前研究路线，Plan 082 只负责真实环境训练参数开发 | model/data | 已采纳 |
| 003 | 复用 Plan 081 中性连续训练 seam；不得把 `fixture_fake` controller 直接改标为真实，必要时专用新增真实 controller/adapter/runner | 既消费已验收能力，又不让历史 fake claim 冒充真实运行 | architecture | 已采纳 |
| 004 | commissioning 可探索并续跑，formal 前冻结实际 recipe/scope/seed/比较规则 | 避免过早冻结造成整组报废，同时保证正式结论不受事后选择污染 | run lifecycle | 已采纳 |
| 005 | 正式轮包含同环境、同 cohort 的 fresh base anchor | better-than-base 需要同轮可比基线，不能只沿用 commissioning 或历史硬件结果 | selection | 已采纳 |
| 006 | `VALID_NO_IMPROVEMENT` 是完成终态；有效质量结果不得为求正结论重跑 | 研究任务要允许诚实否定结论，避免把预算变成追逐正结果的搜索 | terminal semantics | 已采纳 |
| 007 | 开 Pod 前同时刷新 A40/L40S；A40 优先、L40S 备选，实际训练活动 12h/15 USD、保留/回传费分账报告、总累计到 10 USD 非阻断告警、同时单实例 | 保留用户训练预算与资源保留优先级，不把等待费伪装成训练消费 | cloud resources | 已采纳 |
| 008 | Plan 079 旧卷不依赖；Plan 082 必须新建网络卷，GPU 阶段小型证据验收关闭全部 Pod 依赖后立即释放正式 Pod，卷删除须用户人工批准 | 避免验收期抢不到 GPU，同时在批准后及时止 compute 费并保留用户的卷删除权 | resource lifecycle | 已采纳 |
| 009 | ignored 运行资产只落主物理根 `eval-data/publication-critic/plan082/` | linked worktree 不共享 ignored `eval-data`；tracked 工作仍必须留在 082 worktree | local assets | 已采纳 |
| 010 | Plan 082 传输显式执行 270/285/290GB 门，而不依赖 Plan 083 build 环境变量 | 普通回传不会经过 Cargo watchdog，必须避免容量保护的错误安全感 | capacity | 已采纳 |
| 011 | 共享 `debug/incremental` 只在无重型 owner 时作为精确、可记录的最后手段清理 | 兼顾大型工件回传和 Plan 083 共享 cache 可继续使用，不扩大到未知资产 | concurrency | 已采纳 |
| 012 | 只提交 worktree；合并、推送、分支归档和 worktree 清理等待用户批准 | 遵循本次明确交付边界 | delivery | 已采纳 |
| 013 | 额外请示、阶段 A 付费申请、GPU 阶段小型证据验收和无 Pod 大型回传后最终验收只使用指定 Codex 队列，发送后停止且主动表明身份 | 满足用户指定的三次主要申请/验收、批示与自动唤醒方式 | coordination | 已采纳 |
| 014 | RunPod 软性优先 MCP，CLI 补 MCP 不擅长的操作；手动抢不到时按计划模板复用既有单目标、唯一名称、有界超时抢 Pod 脚本 | 提高 Agent 操作可用性，同时避免重复计费 Pod 或为工具偏好锁死实现 | cloud control | 已采纳 |
| 015 | 窄复用 Plan 068 无 Pod S3 严格下载 core，以 Plan 082 实时卷/endpoint/root/manifest 参数化，不原样调用旧 CLI | 复用 120/120、24.4GB 真实成功经验，同时避免旧资源身份污染新任务 | artifact handoff | 已采纳 |
| 016 | 固定模型/数据/objective 身份，参数化 recipe、scope、控制点、路径、实时资源和 handoff；不增加签名链、registry 或通用云编排 | 保持后续 commissioning 可修且架构契合，同时把复杂度限制在正确性与功能所需范围 | maintainability | 已采纳 |
| 017 | 正式候选从完整 checkpoint-backed observation 中选择并保留其 checkpoint/snapshot；全 observation training-best 只作诊断 | 避免最好观测没有可恢复权重，也不因非 checkpoint 观测更好而错误判整轮无效 | selection/retention | 已采纳 |
| 018 | 进程 receipt 在训练 segment 前 write-once 发布，正式 freeze 显式选择末次非终 checkpoint 作为新进程恢复边界 | 中断后仍能消费已资格化 checkpoint，并保证正式轮实际走一次恢复后继续更新 | recovery | 已采纳 |
| 019 | recipe 显式参数化模型参数 dtype；每个 update 对当前 scope 全部非零梯度参数保留 CPU 前值，optimizer 后逐个精确比较，至少一个真实数值变化才接受，不做 GPU 全 scope clone 或全模型逐步哈希 | 消除单参数探针的 false no-op，同时把额外内存移到 CPU；commissioning 仍可调整 dtype/LR/scope | training correctness | 已采纳 |
| 020 | 用小型实际环境 receipt、真实 retention artifact producer 与固定项目局部 boto3 launcher 分别闭合 freeze、GPU 释放前清单和 0 Pod 回传入口；retained bootstrap 只能写入 task root 内、artifact root 外的无符号链接新路径 | 直接验证真实接缝且保持职责分离，避免 producer 污染正式工件，不引入签名链、通用环境管理器或第二套工件平台 | environment/handoff | 已采纳 |
