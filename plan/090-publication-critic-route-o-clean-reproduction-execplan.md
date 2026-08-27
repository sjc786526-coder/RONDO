# Plan 090：Publication Critic Route O 干净复现与稳定性确认 ExecPlan

> 本计划是 Plan 090 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、研究合同、预算或完成标准，应暂停对应动作并请求审查者批示。
> 普通代码、依赖、环境、连接、存储、checkpoint、恢复和局部测试问题，应在已生效的阶段授权内自主修复并按需重跑；
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 090；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

冻结 Plan 087 Route O 后，在 exact 1.7B、冻结 v8 train/validation、同一 US-TX-3 L40S 环境类和不超过 6 USD 的新增费用内，从
exact base 独立干净运行，回答两个问题：

1. Route O 的微弱正向信号能否在原 seed、原 BF16 条件下再次出现；
2. 若能，同一信号在预先冻结的第二 seed 下是否保持基本一致。

只有两个 BF16 结果均通过预冻结判断时，才允许做一次匹配的真实 FP32 原参数更新对照，以解释更新/计算精度是否压缩或扭曲有效区间。
本任务不继续搜索 scope、学习率、objective、更新数或其它 Route，也不要求达到独立泛化、unseen 或产品 GO。

唯一正式终态为：

- `ROUTE_O_CONFIRMATION_PASS`：原 seed BF16 得到复现，第二 seed BF16 也保持一致方向；FP32 对照已完成，或按预冻结分支和剩余预算有充分理由不再运行。
- `ROUTE_O_CONFIRMATION_NO_GO`：原 seed 有效结果未复现、第二 seed 有效结果不稳定，或正式证据表明先前正向信号只是特定数值路径的无效表象。
- `INCONCLUSIVE_INFRASTRUCTURE`：在授权预算内因持续库存或无法排除的云端基础设施问题，没有形成足以判断的有效训练证据。

三个可信终态都表示 Plan 090 执行目标完成；`NO_GO` 是有效研究结论，`INCONCLUSIVE_INFRASTRUCTURE` 只表示模型问题没有得到回答，
不得改写为 Route O 失败。若终态证据本身不成立或资源未按要求收口，才属于验收不通过/任务目标失败。

### 阶段门

- **阶段 A：非付费准备与预冻结。** 在专用 worktree 中复用或补齐必要设施，核对历史资产，冻结 Route O、第二 seed、精度语义、判断口径、
  条件分支、预算准入和保留集合，并用 fixture/fake/focused test 打通轻量链路。不得创建/启动 Pod、下载或运行真实模型、上传数据、训练、
  产生费用，亦不运行本地 Cargo、Docker 或真实模型。阶段 A 完成后先提交 task branch、保持 worktree clean，并通过本计划指定的 Codex
  跨会话队列请求审查者验收。
- **阶段 B：付费云端确认序列。** 只有审查者明确回复“阶段 A 验收通过，批准进入付费阶段”后才生效。先以调试/commissioning 打通真实环境
  接缝；研究合同不变且链路稳定后，绑定最终 clean source、环境与独立 namespace，按冻结顺序执行正式序列。普通无效尝试可在预算内修复重跑，
  有效负面结果不得重跑规避。
- **阶段 C：0 Pod 本地收口。** GPU 工作结束前生成并回传必要小资产，随后立即释放全部任务 Pod并确认 compute `$0/h`。最终结果、WBS、
  完成记录和精炼日志在本地收口；不为最终文档或普通审查问题保留计费 Pod。

### 完成/验收标准

- [ ] 阶段 A 与最终交付均只在 Plan 090 worktree 完成 tracked 修改并分别提交，worktree clean；未经用户批准不合并、不推送、不归档分支、
      不删除 worktree。
- [ ] exact 模型 revision、snapshot identity、v8 train/validation、input/scalar/pair/objective 语义、Route O 九张量 scope 和 recipe 与
      Plan 087 正式结果精确一致；formal runtime 同时匹配其 container image、Python、Torch、Transformers 和 SDPA/fused AdamW 环境身份；
      unseen 全程物理不可达。
- [ ] 在任何新训练结果出现前，冻结第二 seed `20260902`、同 seed/第二 seed 判断口径、数值容差、无明显塌缩条件、FP32 触发/解释规则、
      独立 namespace 和最小保留集合；阶段 B 不得事后改口径追逐 PASS。
- [ ] 既有 exact base 与 Plan 087 Route O checkpoint 只做 no-update 统一诊断和历史比较；Plan 090 每条训练均从 exact base 和独立干净空间开始，
      不继承旧候选或前一路线的参数、optimizer、scheduler、RNG 或 cursor。
- [ ] 正式顺序为 base/旧 Route O 诊断 → 原 seed BF16 → 条件触发的第二 seed BF16 → 条件触发的 FP32；前置分支失败即停止后续训练，
      不通过临时调参、加 update、换 seed 或重选指标挽救。
- [ ] FP32 对照从 exact base 开始并实际以阶段 A 已声明的 FP32 路径执行原参数更新；不得只把 BF16 候选转型后重新评分。若实现同时改变
      forward/activation 与 update 精度，结果必须按“FP32 参数训练条件对照”解释，不冒充严格 update-only 因果证明。
- [ ] base、Plan 087 Route O 和 Plan 090 各有效结果使用同一评价实现，分别记录 train 与 validation 的 objective/component 变化、raw/projected
      Boundary 与 Within-PASS margin、pair 分布/strict wins、ROC AUC、既有 threshold/operating 指标及必要参数变化摘要，足以判断训练目标、
      validation 传递、pair 抵消和精度影响；不建设统计、审计或可信平台。
- [ ] 同 seed 与第二 seed 的 PASS 依据预冻结整体口径，而非 bitwise 相同、统一 offset、单一 threshold、单个 ordering 或任一孤立指标；
      FP32 单条不同结果本身不被夸大为已证明 BF16 偶然，结论边界与实际精度语义一致。
- [ ] 阶段 B 准入前刷新 live 余额、未结费用、库存/价格、0 Pod、卷状态/实际可用 bytes，并确认 base 诊断、原 seed BF16、可能必需的第二 seed BF16、
      小型回传和止费在安全可用额度内；6 USD 是硬上限而非消费目标。
- [ ] 同时最多一个计费 Pod，完整正式确认序列绑定同一个 exact US-TX-3 L40S Pod 与现有 `mwemzrn33y` 卷。库存紧张时使用通用创建脚本，
      创建后独立核验实际价格、
      GPU/数量、机房、镜像和卷挂载；不符、来源不明或无法确认时立即释放。
- [ ] 不新建、扩容或删除网络卷；Plan 082/087 roots 只读。空间不足时只清理本任务创建且已确认不再需要的中间工件，仍不足则暂停并请示。
- [ ] 保留 exact base 引用、最终有效候选、必要转折点、完整小型指标和可复用恢复信息；不永久保存所有中间 checkpoint。大型模型、权重、
      checkpoint 和环境留在网络卷，本地只回传验收与后续决策必需的小型结果、manifest、日志和资源终态。
- [ ] 发布 PASS 或清理其替代恢复点前，最终保留的 Plan 090 candidate 已由不同 OS 新进程完成 no-update restore/等强实际可复用性验证；
      不要求每个负面中间 checkpoint 做同等验证。
- [ ] 无论终态如何，全部任务 Pod均已 stop/delete，并通过实时查询确认 0 Pod、compute `$0/h`；57GB 网络卷继续保留且未删除。
- [ ] 相关轻量 Python 聚焦测试、必要 static/format/compile 检查、改动 shell 的 `bash -n` 与 `git diff --check` 通过；不运行本地 Cargo、Docker、
      真实模型或全 workspace 测试，fake、调试、正式结果、skip 和未运行项如实区分。
- [ ] 最终独立审查无遗留 High/Medium correctness/functionality finding，并分别报告“验收通过/不通过”和“任务目标完成/失败”；PASS 不越界为
      独立泛化、unseen、M3-C1/M3-C2、产品启用或 M3-D。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/full_model_training/` 中职责契合的训练、评价、checkpoint/恢复、bundle、handoff 与 RunPod seam，及必要的
  Plan 090 薄能力；Plan 081/082/087 的历史入口、validator 和正式结果语义保持可验证。
- `training/publication-critic-plan090/` 下体积合规、受跟踪的冻结合同、recipe、运行入口、依赖、source/data bundle 规则与 runbook；不提交模型、
  checkpoint、cache、venv 或原始训练输出。
- `eval/tests/` 中相称的 pure/fake/focused 测试；`eval/results/publication-critic/` 中体积合规的正式结果摘要。
- 本计划“当前状态”和“关键决策记录”、受影响的 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`，最终验收后的
  `doc/WBS-COMPLETED.md`，以及有意义的精炼 `agent_log/`。
- 阶段 B 生效后，通过既有安全入口只读取得 exact Hugging Face revision（卷上 exact snapshot 不可用时）；向任务自有 RunPod 上传必要的
  clean committed source 与物理无 unseen 的冻结 train+validation bundle。禁止向 HF 或其它外部目标上传/发布模型、数据、权重或结果。
- 阶段 B 生效后，只读查询 RunPod 余额、账单、库存、价格、Pod 和网络卷；在 US-TX-3 创建、启动、停止、重启、替换和删除至多一个同时计费的
  本任务 L40S Pod，挂载现有 `mwemzrn33y` 并只写新的 Plan 090 task root。
- 只清理本任务创建且已确认不再需要的远端中间 checkpoint、cache 和临时目录；不得触碰 Plan 082/087 保留资产或网络卷本身。

### 不允许修改或执行

- 冻结 v8 数据正文、label、pair、split、review、manifest、input/scalar/preferred 方向；Plan 054/060/064/066/068/071/073/075/079/081/082/087
  的冻结结果、正式 receipt、历史报告和终态。
- Route P/Q/R、其它 scope、学习率、objective 权重、optimizer、scheduler、训练数据、更新数或临时 seed 搜索；LoRA/QLoRA/PEFT、量化训练、
  换模型、新 objective 家族或改变 pair 方向。
- unseen、真实 API/Judge、M3-C1/M3-C2、selection lock、产品 threshold/default、Publication Critic 启用、M3-D 或上游基线升级。
- 新建、扩容或删除网络卷；换区、换卡、多 GPU、同时多个计费 Pod；新建 Plan 090 专用 Pod 创建器、创建 receipt、通用云编排、调参、审计或
  可信平台。
- 本地 Cargo、Docker、真实模型加载/推理、全 workspace/CI/PR；修改宿主机配置、全局工具链、系统服务、其它仓库或来源不明资产。
- 未经用户批准合并/rebase/cherry-pick main、推送 task branch、归档/重命名分支或删除 worktree。

### 不允许读取/查看

- v8 unseen-test 的正文、render、score、Judge 输入/输出，或任何需要先读 mixed 数据再过滤的路径；云端输入必须从物理无 unseen 的 canonical
  train+validation 投影产生。
- `.env.local` 内容、token、API key、secret、私钥、密码或个人配置。只可按根 `AGENTS.md` 静默检查文件存在、非符号链接、`0600` 和任务所需
  变量非空，并由严格数据 loader 向目标进程注入 allowlist；不得 source、打印、复制、上传或记录凭据。
- 与任务无关的 ignored 资产、历史 worktree 的未提交修改、真实 publication/transcript/private reasoning 和项目外个人文件。

### Git-ignored 与主物理根边界

全部 tracked 修改在
`/home/sjc/desktop/RONDO/.claude/worktrees/090-publication-critic-route-o-confirmation/` 完成并提交，主工作区不得产生 tracked 修改。

linked worktree 不共享主物理根 ignored `eval-data/`。阶段 A 如需只读核对 Plan 087 本地交接、阶段 B 的上传源、回传小型结果和运行工件，允许直接
使用主物理根以下 task-owned namespace：

`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan090/`

以及只读的：

`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan087/`

执行者须在阶段 A/最终汇报中单独列出主物理根实际创建或保留的 Plan 090 ignored 路径、用途和大致体积；不建设逐文件审计台账。主物理根
`.env.local` 仅按上述安全入口使用。规划阶段没有创建 ignored namespace，也没有直接修改主工作区。

## 3. 硬约束

以下约束只冻结研究正确性、阶段门、费用/资源安全和交付边界；不锁死类名、schema、CLI 布局、内部模块拆分、普通调试顺序或测试数量。

1. **付费审批门。** 阶段 A 可自主完成项目内实现、轻量测试、预冻结、提交和整改，但不得创建/启动云资源、上传数据、下载/运行模型、训练或
   产生费用。只有审查者明确验收阶段 A 并批准后，阶段 B 授权才生效。原则性合同、预算、GPU/region 或卷操作变化必须先请示；范围内普通修复
   无需逐项请示。
2. **Route O 精确冻结。** exact 模型为
   `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`，snapshot content SHA-256 为
   `18d9edf7132d9c5e13bb0e59e3c2c6a42f82007fa17de464e20783755a171360`。数据为物理无 unseen 的 v8 train `128/58`、validation
   `55/26`；bundle content SHA-256 为 `2247dd09c168900a47d37a50ecd6511d66d62d3f2ec8056ea3bc829c93de8b46`。formal runtime 固定为
   `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`、Python `3.12.3`、Torch `2.8.0+cu128`、Transformers `4.52.3`；不可避免的
   runtime 偏离必须在看到新正式结果前经审查者明确冻结，且最终降低结论强度，不得悄然替换。
3. **配方不搜索。** BF16 路线固定 seed `20260901` 与 `20260902`；一次 full-cohort 更新；九张量、`33,558,784` 原参数；AdamW
   `5e-6`、betas `0.9/0.999`、epsilon `1e-8`、weight decay `0`、fused；constant scheduler、clip `1.0`、microbatch `1/1`、SDPA、
   activation checkpointing；Binary/Boundary/Within-PASS 权重 `0.05/0.25/0.70`。九张量为 Layer 27 的 Q/K/V projection、Q/K norm、
   MLP gate/up projection、input/post-attention layernorm；实际训练前须按 exact inventory 解析并绑定以下完整参数名：
   `model.layers.27.self_attn.{q_proj,k_proj,v_proj}.weight`、`model.layers.27.self_attn.{q_norm,k_norm}.weight`、
   `model.layers.27.mlp.{gate_proj,up_proj}.weight`、`model.layers.27.{input_layernorm,post_attention_layernorm}.weight`。
4. **判断口径先于结果。** 阶段 A 依据 Plan 087 完整 signature 与已知 BF16 格点冻结一份小而明确的整体 rubric，至少固定 base-relative 方向、
   合理容差、pair 分布与关键伴随指标的非塌缩条件。原 seed 和第二 seed 分别对各自 matching base 判断；结果不要求 bitwise 相同，但不能只凭
   统一 offset、threshold 或一个孤立指标。rubric 经阶段 A 审查后不得因结果变化。
5. **条件分支和 clean base。** 旧 Route O 只用于 no-update 诊断。原 seed BF16 未通过即发布 NO-GO；通过后必须执行第二 seed；第二 seed
   未通过即发布 NO-GO；两次均通过才可根据预冻结分支与完整闭环预算运行 FP32。每条正式训练都重新从 exact base、独立空 namespace 开始。
6. **FP32 是真实训练对照。** FP32 默认匹配 seed `20260901`，除阶段 A 冻结的精度路径外保持 Route O 不变，并使用自身 FP32 base-relative
   delta。允许执行者选择架构契合的 update-only 或整模型 FP32 实现，但必须记录 forward、参数、梯度、optimizer state 和保存精度的实际语义；
   只做 post-hoc cast 无效。单条 FP32 不一致只支持精度依赖诊断，除非它证明 BF16 证据无效，否则不自动推翻两个 BF16 seed 的复现结论。
7. **训练与 validation 分责。** train 才进入梯度；train 与 validation 均以同一 scorer 记录必要 before/after 诊断，但 validation 仅用于预冻结
   判断和停止，unseen 不可达。新增诊断应是现有评价/训练设施上的薄层，不建立第二套 pipeline 或复杂梯度因果平台。
8. **调试完成后才 formal。** 阶段 A 尽可能打通轻量链；付费真实环境中允许保留已验证进度、从首个未打通处修复。exact 模型载入、no-update
   诊断、训练、评价、checkpoint/恢复和止费链完整打通后，再绑定 clean commit/environment/namespace 执行正式序列。若缺陷影响研究语义或
   正式证据，修复后从相称干净边界重跑，不拼接无效结果。
9. **允许修故障，不允许修结果。** 代码、依赖、连接、下载、OOM、Pod、存储、数值、checkpoint、恢复和小型回传故障可在合同、硬件和预算
   不变时自主窄修、重试或替换本任务失效 Pod，不设机械次数上限。已完成且有效的负面训练结果不得重跑、调参或换 seed 规避；无法分类时先保留
   证据、完成其它安全工作并请示。
10. **6 USD 与完整闭环。** 阶段 B 以实时状态冻结安全可用额度：`min(6 USD, live 可用余额 - 已知未结费用 - 止费/小型回传/短期卷保留余量)`。
    从基线起的 Pod、container disk、任务期间卷持有及必要回传费用均计入简单保守总账；不建设 receipt 链。每次启动下一条件分支前，必须确认
    余额足够完成该分支及保存/止费；尤其开始原 seed BF16 前须能承担它可能触发的第二 seed。余额不足时停止付费并请示，不形成半条正式结论。
11. **同一 exact Pod 的正式序列。** 只使用 US-TX-3 单张 L40S 和既有 57GB `mwemzrn33y`；commissioning 或尚未形成有效正式证据时，可在
    相同硬件/环境、独立干净边界和剩余预算内替换失效 Pod。正式确认序列须绑定同一 exact Pod；若形成有效正式结果后该 Pod 丢失，不得把
    新 Pod 的后续 seed 与旧结果拼成 PASS。预算足够时在替换 Pod 上从 exact base 重启完整 BF16 正式序列，否则诚实收口为基础设施不完备
    或请示审查者。库存紧张必须使用 `scripts/create-runpod-when-ready.py`；脚本只负责轮询/create/不确定响应 exact-name 防重，实际价格、
    GPU、机房、镜像和卷挂载由执行者通过既有 RunPod MCP/CLI 独立核验，不符立即用既有 terminal 能力释放。
12. **资产最小保留。** 旧 Route O checkpoint 固定为卷内
    `/workspace/rondo-plan087-20260826-search01/formal-search/route-o-artifacts/recovery-checkpoints/checkpoint-attempt-000-step-000001`，
    `3,591,448,949` bytes，content SHA-256 `d08ff2566d719b3aef4dd58158e86b1c374faf2021cc96a140d878b79857c923`；阶段 A 绑定 locator，
    使用前验证身份与完整性。Plan 082/087 roots 只读，Plan 090 只写独立 task root。checkpoint 清理前须有替代恢复点或已落盘的完整小型负面
    证据；PASS 时最终保留候选须经不同 OS 新进程 no-update restore/等强可复用性验证，NO-GO/INCONCLUSIVE 只留必要转折点。完整权重不下载
    本地，网络卷不得删除或扩容。
13. **秘密与外发最小化。** source bundle 必须从 Plan 090 clean commit 生成；data bundle 从 canonical train+validation 投影生成，上传前检查物理无
    unseen/secret/无关 ignored 资产。HF 只允许 exact revision 下载，不上传/发布；旧 Plan 087 source archive 只作历史证据，不作为本任务源码。
14. **终态先止费再收口。** GPU 工作一旦结束，先生成/回传必要小资产，立即 stop/delete 全部任务 Pod并实时确认 0 Pod、compute `$0/h`，再
    完成本地 tracked 结果、WBS、COMPLETED 和日志。最终审查的普通本地问题不得恢复计费；若确需重新用 GPU，必须仍在授权预算与审查批示内。
15. **提交和结论边界。** 阶段 A 与最终交付均先提交 worktree并停止等待审查；未经用户批准不得合并或推送。PASS 只说明同一 validation 上
    Route O 在两个预冻结 seed 下具有最低限度复现性，不说明独立 cohort 泛化、unseen、产品 GO 或任何下游解锁。
16. **跨会话请示与验收。** 额外授权、计划外变数、不确定事项、阶段 A 申请进入付费阶段和最终任务验收只使用下述 Codex 跨会话队列。
    执行者每条消息必须主动表明“我是 Plan 090 执行者”，发送后停止会话，不等待、不轮询、不重复发送。阶段 A 即使验收通过，审查者也必须
    通过同一队列明确回复“阶段 A 验收通过，批准进入付费阶段”；执行者未收到该明确回复前不得产生费用或外部写状态。

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

在本计划中，`<阶段性任务>` 依次用于“Plan 090 非付费准备阶段 A”和“Plan 090 最终任务”。对于阶段 A，付费审批门优先于上述通用文案中的
“如果验收通过，他不会再通知你”：审查者即使验收通过也必须通过同一队列明确回复“阶段 A 验收通过，批准进入付费阶段”；执行者未收到该
明确回复前不得产生费用或外部写状态。最终验收仍按通用文案处理。

## 4. 软性建议

以下建议用于高效起步。执行者可依据 live code、显存、数值路径与真实环境采用更简洁、优雅、架构更契合的等强方案；有实质影响的偏离记录在
关键决策中即可。

- 优先复用 Plan 087 的 exact snapshot、scope inventory、objective、Torch update、validation、checkpoint/recovery、bundle、handoff 和
  terminal 能力；Plan 090 只补确认合同、train before/after 诊断、条件分支和结果收口。不要扭曲 Plan 087 自适应 search/finalizer 来伪装兼容。
- 阶段 A 可从 Plan 087 小型 handoff 精确投影 Route O recipe、历史 raw logits、pair margins、checkpoint locator 与环境事实；Plan 090 source
  bundle 必须来自自己的 clean commit。旧 checkpoint 只读诊断，不作为训练初始化。
- 判断 rubric 宜保留少量高信息指标：raw Boundary 是主要方向，projected Boundary/Within-PASS、ROC、pair 分布、strict/operating 和 raw
  Within-PASS 共同约束塌缩；可结合 Plan 087 量级与 BF16 格点给出容差，但不必建立统计显著性体系。
- FP32 优先采用能真实提升被更新参数/optimizer 数值路径、同时尽量少改变其它条件的薄实现；若整模型 FP32 更稳妥或现有能力已足够，可直接采用，
  只需诚实降低因果表述。提前估算显存、checkpoint 与容器盘需求，避免正式序列中才暴露容量问题。
- 费用控制保持简单：实时费率 × wall clock，加明确的 container/volume 增量和停止余量即可。两个 BF16 是任务主门，FP32 只有在仍能完整完成、
  保存并止费时才运行，不为用完预算而追加工作。
- 阶段 B 先做短而完整的 no-update/单次调试闭环；确认结果 schema、small handoff 和 terminal path 都能工作后，再从 clean namespace 开始正式序列。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：从 clean `main@02fe2b42fb8b85d58d4039e93137df62d3b6d258` 创建专用 worktree
  `/home/sjc/desktop/RONDO/.claude/worktrees/090-publication-critic-route-o-confirmation`，分支
  `worktree-090-publication-critic-route-o-confirmation`。
- 2026-08-26：规划者阅读根规范、README、顶层/三期 WBS、Plan 087 ExecPlan、正式结果、最终验收、原因分析和相关训练/云端设施；
  三路只读复核分别检查模板/研究合同、历史资产/复用点和授权/预算边界。
- 2026-08-26：三路最终只读复核确认 0 High、0 Medium；runtime identity、旧候选身份/最终恢复门、可信 INCONCLUSIVE 映射和同一 exact Pod
  正式序列均已闭合。
- 2026-08-26：按用户追加要求把额外授权请示、阶段 A 付费审批、最终验收和身份声明统一绑定到指定 Codex 跨会话队列；非付费/付费阶段门
  保持不变。
- 2026-08-26：Plan 090 ExecPlan 与当前 WBS 窄同步已完成；规划阶段未访问 live RunPod/Hugging Face，未创建 Pod/卷或 ignored task
  namespace，未上传、下载或运行模型，未训练、产生费用、运行 Cargo/Docker或修改主工作区 tracked 文件。

### 当前工作

- 无。规划交付完成，等待执行者在本 worktree 开始阶段 A。

### 本任务剩余步骤

- 阶段 A：实现轻量准备、预冻结、聚焦测试和首次提交，通过指定队列申请审查者验收与付费阶段批准。
- 阶段 B：在批准后完成真实链路打通与冻结确认序列，生成小型结果并释放 Pod。
- 阶段 C：0 Pod 本地结果/WBS/完成记录/日志收口，聚焦复验、提交并申请最终审查。

### 阻塞项

- 阶段 B 付费门关闭；需阶段 A 提交通过审查者验收后才可打开。
- live 余额、未结费用、US-TX-3 L40S 库存/价格和卷可用 bytes 仅能在执行期刷新；历史快照不能当作当前准入证据。

### 当前验收状态

- `PLAN_READY / STAGE_A_NOT_STARTED / PAID_GATE_CLOSED`。

### 交接边界

- 执行者直接使用本计划创建的 Plan 090 worktree，不另建工作树，不在主工作区修改 tracked 文件。
- 因 linked-worktree/gitignore 必须使用主物理根的 Plan 090 ignored 资产时，严格限制在本计划列明 namespace，并在阶段/最终汇报单独说明。
- 阶段 A 与最终交付都只提交 task branch；合并、推送、分支归档和 worktree 删除均等待用户明确批准。
- 本任务完成后冻结本计划；独立 confirmation cohort、unseen、产品资格或 M3-D 只链接 WBS，不在此安排。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 阶段 A 提交并经审查者明确批准后才进入付费阶段 | 尽量在本地关闭可发现问题，同时保留真实环境调试冗余 | 授权与执行顺序 | 已采纳 |
| 002 | Route O recipe 原样复现，不在 Plan 090 搜索参数 | 本任务只验证复现性与最低 seed 稳定性 | 训练合同 | 已采纳 |
| 003 | 第二 seed 冻结为 `20260902`，FP32 默认匹配原 seed `20260901` | 防止见结果后选择 seed，并保持精度对照可读 | 正式分支 | 已采纳 |
| 004 | 两个 BF16 seed 是确认主门；FP32 是条件性精度诊断，不作单结果自动 veto | 单条 FP32 同时可能改变多条数值路径，不足以严格证明 BF16 偶然 | 终态解释 | 已采纳 |
| 005 | 只复用 57GB 现有卷，不授权新建、扩容或删除 | 用户授权只覆盖现有卷，且任务可通过最小保留与清理自有中间资产控容 | 云资源 | 已采纳 |
| 006 | WBS 在规划分支只窄指向 Plan 090，COMPLETED 待最终验收后更新 | 保持当前规划与历史职责分离 | 文档 | 已采纳 |
| 007 | 额外授权请示、阶段 A 付费审批和最终验收只使用用户指定的 Codex 跨会话队列 | 保证审查批示进入正确会话且不依赖文件或人工转述 | 协作与审批 | 已采纳 |
