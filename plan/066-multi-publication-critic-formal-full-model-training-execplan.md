# Plan 066：M3-B1c Publication Critic 正式分阶段全参数训练 ExecPlan

> 本计划是 M3-B1c 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认；普通代码、依赖、数据消费、启动、恢复和工件问题应在范围内自主修复并继续。
> 本计划只描述 M3-B1c；下游 M3-C1 及跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

复用 Plan 060 已资格化且当前保持运行的唯一 RunPod H100 PCIe 80GB Pod、Standard 卷、exact 模型、venv、FlashOptim 和 cache，消费 Plan 064
冻结的 `training/publication-critic-v8/`，在同一 BF16 全参数 Skywork lineage 上完成正式 C1→C2→C3 分阶段训练，保存各阶段可用于后续资格评估的
模型候选和必要恢复状态，并在 Plan 060 与本任务共用的 23 USD 总硬上限内完成证据回收与远端资源收口。

本任务形成训练候选和同口径训练/validation 事实，不直接授予模型产品资格。模型质量、threshold、本地部署和最终产品选择属于另行规划的 M3-C1。

### 完成/验收标准

- [ ] 开始实施前，把最新本地 `main`（至少包含已验收 Plan 064 v8）合入当前 Plan 060/066 worktree，保留 Plan 060 已提交成果并解决 WBS/共享文件冲突；
      只在当前 worktree 继续、提交并保持 clean，不创建新 worktree、不合并回 main、不推送或归档。
- [ ] 对 Plan 060 final-19 正式 receipt、当前 Pod/卷实物和 Plan 064 v8 manifest 做一次有界预算适配复核；确认冻结 v8 可在剩余共享预算内完成后，记录
      `DATA_GO` 并开始正式训练。若预算事实不支持则停止在 `NO-GO/INCONCLUSIVE`，不改数据来修绿。
- [ ] 正式输入只来自 v8 的 train split：128 candidates、C2 加入 50 个 Boundary pair、C3 再加入 8 个 Within-PASS pair（累计 58 pairs）；validation 55 和 unseen-test 45
      均不进入 gradient、scheduler、训练采样或数据增强。
- [ ] exact `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` 以 BF16 全参数、单张 H100 PCIe
      80GB 和 FlashOptim/FlashAdamW 训练；无 PEFT、量化、CPU/NVMe offload、部分冻结、只训 head 或普通 AdamW fallback。
- [ ] 同一模型 lineage 连续完成 C1=Binary、C2=Binary+Boundary、C3=Binary+Boundary+Within-PASS；每阶段实际消费冻结成员、完成有限的
      forward/backward/gradient/update，并记录样本/token/step、loss component、LR、显存和耗时。
- [ ] 每阶段保存并验证一个模型候选；至少保留一个可恢复的 full checkpoint，且在任务内完成一次真实新进程恢复后继续更新或等强恢复证明。
      不要求三个阶段都长期保留完整 optimizer checkpoint；不得在验证导出与恢复之前删除唯一有效副本。
- [ ] validation 只用于阶段候选的同口径比较、异常发现和交接，不反向改写 v8 标签或 split。unseen-test 默认保持封存；若执行者认为本任务必须做一次
      最终盲评，只能在 recipe 与候选选择冻结后运行一次，且不得据其返调训练。
- [ ] 正式训练前允许短小 commissioning，打通 v8 consumer、batch、显存、保存和恢复后再从 exact base 在新 namespace 干净运行；commissioning
      不冒充正式结果，身份稳定后不因普通窄故障报废已验证下载/cache。
- [ ] receipt 绑定模型/代码/依赖/recipe/v8 manifest、训练与 holdout 隔离、阶段 lineage、候选/checkpoint hash、资源与费用；使用普通 JSON/日志/hash 即可，
      不建设签名链、数据库、审计平台或通用训练系统。
- [ ] Plan 060 与 Plan 066 从原 Plan 060 余额基线计得的全部 GPU/卷/等待/重试/清理费用合计不超过 23 USD；执行期间持续保留安全收口余量，不能把
      provider 延迟账单当成可继续消费的余额。
- [ ] 正式训练前先核实并删除 Plan 060 已停止的 legacy Pod `b0fazq4ueaii2k` 与败者卷 `bbfxl15nqr`；保持当前运行 Pod
      `oe6gbptvq5yhja`、胜者卷 `hi3iaz8rsr` 和 final-19 checkpoint 不动，直到 Plan 066 产生并验证新的恢复点。
- [ ] 成功、原则性失败或预算止损后，回收必要小型 receipt/日志/manifest/hash；下载或明确安全保留 M3-C1 所需候选后，停止并删除 task-only Pod，删除
      无需保留的临时 checkpoint/cache/卷，确认计算持续费归零并记录最终账单。只清理本任务明确创建的对象。
- [ ] focused tests、脚本语法/编译、bundle/manifest validator 和 `git diff --check` 通过；未运行或 skip 如实记录，不运行无关全仓、Docker、Cargo 或本地完整模型。
- [ ] 执行者更新本计划状态、WBS 当前事实和一份精炼执行日志并提交当前 worktree；独立验收达到 correctness/functionality
      `remaining_findings=[]`，最终结论为 `COMPLETE`、`NO-GO` 或 `INCONCLUSIVE`。

## 2. 范围

### 允许修改

- 当前 worktree 内 Plan 060 已建立的 Publication Critic full-model trainer、objective、data/collator、checkpoint、receipt/finalizer、focused tests、
  RunPod 启动脚本和训练合同；职责适配时窄扩展，若强行复用会扭曲 v8 正式训练语义，可在同一 namespace 新建专用能力。
- `training/publication-critic-plan066/` 下轻量 recipe/dependency/model/runbook 合同；不得提交模型权重、checkpoint、cache 或大体积训练输出。
- Plan 064 已冻结 v8 的 consumer 可做兼容性修复，但不得修改正式数据内容、label、pair、split、review 或 manifest 身份。若发现冻结资产自身错误，暂停并报告。
- `eval/tests/` 的相称 tiny/pure/fake/focused 回归，以及 `plan/066...`、受影响 WBS、必要 `training/README.md`/数据布局说明和一份 `agent_log`。
- 主物理根 `eval-data/publication-critic/plan066/` 下 task-only ignored bundle、receipt、日志、controller 状态和回收工件。
- 当前唯一 RunPod Pod `oe6gbptvq5yhja`、胜者 Standard 卷 `hi3iaz8rsr` 及其 Plan 060 exact 模型、venv、FlashOptim、cache 和 final-19
  checkpoint；允许上传 verified code 与 v8 train/validation（以及仅在获准最终盲评时需要的 unseen-test）数据，执行训练、保存/恢复、下载小型证据和必要候选。
- 只读确认身份后删除 Plan 060 task-only stopped legacy Pod `b0fazq4ueaii2k` 和 loser Standard 卷 `bbfxl15nqr`；不得误删当前运行 Pod 或 winner 卷。
- RunPod 只读余额、账单、价格、资源和状态查询；在本任务授权范围内监控、停止和删除上述 task-only 资源。
- Hugging Face 只作为 exact public revision 的只读来源；公开依赖/源码/文档查询和必要下载允许。

### 不允许修改或执行

- Plan 054 输入/render/tokenizer/window/raw scalar 合同、Plan 059 v7/Plan 060 smoke bundle、Plan 064 v8 冻结数据语义和历史结果。
- 更换底模/revision、GPU/云后端、训练精度或优化器主路径；多 GPU、第二/replacement Pod、LoRA/QLoRA/PEFT、4/8-bit、CPU/NVMe offload、
  部分冻结、普通 AdamW fallback 或为了通过而缩小模型。
- 数据再生成、扩池、重新 split、改 label/review/pair、用 validation/unseen-test 训练或调参、论文式消融、多 recipe 大搜索或通用训练平台。
- M3-C1 本地部署/量化/threshold/产品启用，HF Jobs/Endpoint/Space/Repo/Bucket 或任何 HF 写入，真实 API、Docker、重型 Cargo、本地完整模型训练。
- 合并回 `main`、推送、归档/重命名分支、删除当前 worktree；这些等待用户后续批准。
- 删除或修改来源不明的本地/远端对象。

### 不允许读取/查看

- `.env.local` 内容、RunPod/HF/SSH token、私钥、密码或个人配置。仅可沿既有安全入口静默检查所需凭据存在且非空；不得 source、打印、复制、记录或上传。
- 与本任务无关的个人文件、其他仓库和 ignored 资产。
- unseen-test 正文的人工浏览；若最终盲评获准，只允许受控 consumer/evaluator 机械读取并输出聚合结果。

## 3. 硬约束

1. **先整合再动远端训练。** 当前 Plan 060 worktree 基于较早 main；执行者第一步必须把最新本地 `main` 合入当前分支，使 Plan 064 v8 的受跟踪代码、
   数据和验收事实与 Plan 060 trainer 共存。不得复制一份 v8 或从另一 worktree 直接取未提交现场；冲突应按两边已验收语义合并并做 focused 回归。
2. **热资源原地交接。** 用户明确要求因 H100 难抢而保留当前 Pod/卷。只要资源身份、价格、共享预算投影和安全性仍满足，本任务不为行政分界先停 Pod；
   但不得因此跳过新的 M3-B1c 正式 namespace、数据/recipe 身份冻结或预算门。若出现需较长本地修复的问题，优先保留卷并依据剩余预算决定短停 Pod，
   不得擅自创建第二个/replacement Pod。
3. **预算是连续总账。** 共享 23 USD 从 Plan 060 原始基线连续计费，不能在 Plan 066 重新归零。开始前用 latest conservative balance delta、provider
   running rate、v8 token/pair 规模、final-19 吞吐/save/reload 实测和清理余量形成简单可复算投影；硬上限前必须自动停止工作、保存可用状态并回收资源。
4. **冻结身份闭合。** 正式 run 绑定 exact model/revision/weight、Plan 054 input identity、v8 manifest/content/contract hash、合入后的 source commit、dependency、
   FlashAdamW runtime、recipe、Pod/GPU/卷与输出 namespace。普通 hash/manifest 足够；不得以形式审计替代训练事实。
5. **train-only 梯度。** 任何产生 gradient、optimizer/scheduler 状态或训练选择的 sampler/batch 都只能从 v8 train split 构造。Binary 与 pair 共享
   `logits[:,0]` raw scalar，PASS/preferred 方向为高分；C2 累计 C1，C3 累计 C2，不在阶段间重置 base lineage。
6. **正式 recipe 有界而可调整。** 执行者依据 final-19 显存/吞吐和 v8 规模自主选择 micro-batch、accumulation、epoch/steps、LR/scheduler、gradient
   clipping、checkpointing 和 loader；先用短 commissioning 排除明显数值/内存问题，再冻结一个主 recipe。允许在 commissioning 内合理收敛参数，正式 run
   后不得依据 unseen-test 或事后结果无限搜索 recipe。
7. **候选与恢复工件实用优先。** C1/C2/C3 各保留一个明确模型候选及 manifest；full optimizer checkpoint 至少保留最新可恢复点，验证后可删除 superseded
   10GB 级 checkpoint 以控制卷空间。删除前必须确认候选导出和下一恢复点各自完整，最终至少一个候选可安全交给 M3-C1。
8. **失败语义。** 普通 bundle、依赖、consumer、collator、OOM 参数、保存/传输或启动问题可在预算内自主修复并从最近有效点继续；技术稳定后若改了正式
   source/recipe，应使用新正式 namespace 做一轮干净运行。持续非有限、全参数/FlashAdamW 路线不成立、pair 方向错误、恢复不可靠、冻结 v8 不可消费或预算
   明确不足是原则性 NO-GO，不得用禁用路线修绿。平台/网络/结算阻断形成 INCONCLUSIVE，不伪装成模型 NO-GO。
9. **验证相称。** 只跑受影响 Publication Critic Python、脚本语法/编译、manifest/bundle 和 receipt validator；H100 正式 receipt 是真实训练证据，tiny/fake
   不冒充。不得因本地缺少重型 Torch 重建大环境或重跑无关全仓测试。
10. **单一远端所有者与终态清理。** 远端 lifecycle 保持一个执行者；子智能体只做只读审查或本地独立检查。任务结束时 finally-style 回收必要证据并清理
    当前 task-only Pod/卷，记录 settled 或尽可能最终的 provider 费用；若账单延迟，明确 pending 并持续做有界只读复核，不保持 GPU 空转等结算。

## 4. 软性建议

- 优先直接扩展 Plan 060 已真实跑通的 trainer/checkpoint/receipt，而不是重写云控制或训练框架；v8 consumer 接口不匹配时做职责明确的 adapter。
- 可先在当前 Pod 上对 v8 做只读 verify/tokenize/一两个 batch commissioning，确认显存和 step 时间后立即冻结 recipe 并开始新 namespace 的正式 run。
- 数据规模远小于 1.7B 模型容量；recipe 应以避免过拟合和灾难性漂移为先，不必为了“用满预算”增加 epoch。validation 曲线、有限性和阶段候选比机械耗尽
  GPU 时间更重要。
- validation 可在每阶段结束按 Plan 054/现有同口径 evaluator 聚合报告；具体主指标、early stop 和候选排序在正式训练前写入 recipe。若现有评价合同不适合
  直接充当训练选择，不要强行扭曲，可只记录稳定的 loss/ranking 聚合，把产品资格留给 M3-C1。
- 模型候选宜用标准可加载的 model-only safetensors/config/tokenizer 工件；full checkpoint 用于恢复，不要求长期下载三份 10GB optimizer 状态。
- 保留 Plan 060 cache 和已校验依赖能显著节省费用；只清理 superseded checkpoint、旧 bundle 和明确无用 cache，不为整洁重下模型或重建 venv。
- 预算记录保持简单：基线余额、当前余额/费率、累计保守费用、工作停止线、清理余量和最终 provider 事实即可。

## 5. 当前状态

### 已完成

- Plan 060 final-19 已在当前唯一 H100 PCIe 80GB 上证明 BF16 全参数、FlashAdamW、C1→C2→C3、约 10.56GB full checkpoint 和新进程
  step 3→4 恢复继续；训练路径技术证据经初步独立核对无 correctness/functionality finding。
- Plan 064 已独立验收并冻结 v8：123 scenarios、228 candidates、104 pairs，train/validation/unseen-test 为 128/55/45，exact tokens
  178,646；数据覆盖、质量和消费合同通过，待 Plan 060 正式事实做有界预算适配。
- 用户明确决定暂不释放难以重新获取的当前 Pod/卷，允许在同一热资源上优先衔接下一阶段；这不扩大共享 23 USD 总硬上限。

### 当前工作

- `READY_FOR_EXECUTION`：等待执行者先把最新 main/Plan 064 合入当前 worktree，完成 v8 预算适配和 M3-B1c 本地/远端准备后直接开始有界正式训练。

### 本任务剩余步骤

- 合入最新 main 并跑窄回归；形成 v8 budget-adaptation `DATA_GO/NO-GO/INCONCLUSIVE`。
- 清理已停止 legacy Pod 与败者卷，同时保留热 Pod、winner 卷和 final-19 恢复点。
- 准备并验证 Plan 066 source/data/recipe bundle，在当前 Pod commissioning 后冻结正式身份。
- 从 exact base 干净执行 C1→C2→C3，保存阶段候选、validation 聚合和恢复状态。
- 回收工件与费用证据，清理 task-only 远端资源，提交当前 worktree并交独立验收。

### 阻塞项

- 当前无已知原则性阻塞。若启动时连续总账投影已不能为正式训练和清理留出可信余量，则预算适配必须停止为 NO-GO/INCONCLUSIVE。

### 当前验收状态

- `PLANNED / NOT YET EXECUTED`。Plan 060 技术资格证据和 Plan 064 冻结数据均已到位；M3-B1c 尚未产生正式训练候选。

### 交接边界

- 本任务完成后冻结本计划并把候选与事实交回 WBS；不在此规划 M3-C1 的部署、量化、threshold 或产品资格。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 继续使用当前 Plan 060 worktree，先合入最新 main/Plan 064，不新建 worktree | 用户要求节省热资源等待和 Git 切换成本，同时保留两项已验收成果 | Git、实施起点 | 已采纳 |
| 002 | 当前唯一 Pod/卷直接交接给 Plan 066，不为 Plan 边界先释放 | H100 难以重新获取，当前环境和 exact 资产已验证 | RunPod、费用 | 已采纳 |
| 003 | Plan 060+066 从原基线按 23 USD 连续总账，不等待 Plan 060 单独 settled billing | 资源不释放时无法形成独立终账，连续计费更保守且可复算 | 预算、验收 | 已采纳 |
| 004 | v8 冻结实物不重做，只做一次有界预算适配 | Plan 064 覆盖、质量、consumer 已验收，唯一缺口是训练预算事实 | 数据、范围 | 已采纳 |
| 005 | 各阶段保留模型候选，但只强制至少一个最新 full recovery checkpoint | 满足后续资格与故障恢复，同时避免三个 10GB optimizer checkpoint 挤占卷 | 工件、恢复 | 已采纳 |
| 006 | validation 可做阶段同口径比较；unseen-test 默认封存，最多在 recipe/选择冻结后一次盲评 | 支持候选交接并防止 holdout 反向调参 | 评价、数据隔离 | 已采纳 |
