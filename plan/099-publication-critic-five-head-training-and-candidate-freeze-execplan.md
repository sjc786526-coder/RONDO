# Plan 099：Publication Critic 五头主方案训练与候选冻结 ExecPlan

> 本计划是 Plan 099 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、阶段授权或完成标准，应暂停对应动作并使用本计划指定的 Codex queue 请求审查者批示。
> 普通实现、依赖、环境、checkpoint、恢复、测试和资源适配问题，应在已经生效的阶段授权内自主修复、续跑或从相称干净边界重跑，不因一次窄故障提前终止任务。
> 本计划只描述 Plan 099；工作包四及后续路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 Plan 098 已冻结的 `rondo-publication-critic-task@v2`、`rondo-publication-critic-decision@v1` 和
development-only `publication-critic-v10`，只形成一套本地可运行的五头 Publication Critic 主方案。任务先在不加载真实模型、
不使用 GPU/RunPod、也不产生训练费用的阶段 A 完成实现与冻结；阶段 A 经审查者独立验收并明确批准后，才进入阶段 B 的有界云端付费训练。

阶段 B 从唯一 exact base 和空 formal namespace 完成一条有效 clean formal 训练轨迹，按预冻结规则自动选择最佳 checkpoint，恢复并复现其
五头输出、formal decoder、pair-aware decision config 和 v10 validation 结果。达到开发准入条件时冻结候选，把工作包四实际需要的完整推理模型
权重和小型配套资产安全回传到本地 ignored 任务目录；完整训练 checkpoint 等其他大型资产留在云端网络卷。有效正式轮未达到开发准入条件时
诚实形成训练 `NO-GO`，不在同一任务或授权内搜索第二路线。

本任务不证明独立泛化或产品资格，不读取冻结资格正文，不修改 Publication Critic 默认状态、产品发布流程或生产配置。

### 阶段门

- **阶段 A：前置本地非付费准备。** 用户已经一次授权本计划第 2 节列出的项目内编辑、合法 v10 train/validation 读取、普通依赖与只读资料查询、
  定向测试、fake/dry-run、独立审查整改和提交。阶段 A 不加载、推理或训练真实模型，不使用 GPU/RunPod/Docker/付费 API，不上传资产、
  不创建或修改外部资源，也不产生训练费用。阶段 A 完成后，执行者提交 099 分支、保持 worktree clean，通过 §7 的指定队列申请验收并停止会话。
- **阶段 B：审查者批准后的云端付费训练与收口。** 用户明确授权审查者在阶段 A 验收通过后，依据阶段 A 已冻结的唯一方案和完整付费申请，
  代替用户作出本阶段准入决定。只有审查者完成独立审查、记录决定，并通过指定队列明确回复批准及最终冻结的 provider、区域/硬件、时间、
  动态预算、Pod/卷数量、资产传输、commissioning、技术恢复/重跑和收口边界后，本阶段授权才生效；不需要再等待一次用户回复。
  未收到该明确批准时，任何真实模型、RunPod、上传下载、训练、卷变更或费用动作都不得开始。阶段 B 内另设 Pod 预释放审查门：核心训练、恢复、
  候选冻结和必要回传完成后先提交并停止等待审查；正常提前释放须由审查者确认不再需要 GPU/Pod 后明确批准，执行者立即 stop/delete Pod并确认
  compute `$0/h`，随后只在本地完成文档、结果和任务收口。不可移动 absolute trigger 先到时是唯一无需 queue receipt 的自动 exact-Pod 止费例外。

### 完成/验收标准

- [ ] 全部 tracked 修改只在 099 worktree 完成并提交，交接时 clean；未经用户另行批准不合并、不推送、不归档/重命名分支、不删除 worktree。
- [ ] 阶段 A 只留下一个 exact 学生基座和一套主 recipe，无未决模型、数据、任务语义或并行待试路线；模型选择明确服务本地可运行目标与可用预算。
- [ ] 冻结并可机械加载：exact model/revision、tokenizer/input identity、五头输出身份、trainable scope、loss 组合、优化/精度、训练时长与停止规则、
      checkpoint 节奏、best-candidate 选择、恢复语义和归档规则。
- [ ] 新训练路径绑定冻结 task v2 identity、decision v1 implementation bundle、v10 manifest 及 train/validation candidate+pair bytes、formal output
      schema、formal decoder 和 release-bound pair-aware selector；身份漂移在正式动作前 fail-closed，但不扩建通用签名链或审计平台。
- [ ] train-only consumer、显式 validation 入口、五维绝对主体 loss、派生 gate loss、target-head Boundary loss、non-target/Within-PASS invariance、
      checkpoint/recovery、状态/结果归档、费用/资源门和 fake/dry-run 完整闭合。
- [ ] 在任何正式训练结果出现前，用 v10 validation 的冻结支持量和产品风险一次确定开发期数值准入规则与确定性候选排序；规则至少覆盖五头未塌缩、
      finite/schema 输出、overall gate confusion、每个 hard head failure recall、Boundary 两端绝对闭合、soft-only invariance、pair-aware decision
      config 可形成和训练无明显灾难性退化，正式结果后不得返调口径。
- [ ] 阶段 A 的 pure/fake/dry-run 与相称定向门禁通过，qualification 正文仍不可访问；独立审查无遗留 High/Medium correctness/functionality finding，
      并形成一份包含全部具体资源、预算和收口动作的阶段 B 申请。
- [ ] 阶段 B 先完成有界 commissioning，把真实环境、显存/吞吐、非零更新、保存、checkpoint 后评价、fresh-process 恢复、回传和止费链打通；
      commissioning checkpoint 与数据不得冒充正式候选。
- [ ] 从冻结 exact base 和空任务 namespace 完成一条有效 clean formal 轨迹；若因实现或基础设施正确性问题无效，可在总时间/预算和单一路线边界内
      窄修并清空 formal namespace 重跑，若轨迹有效但质量不足则停止为 `NO-GO`。
- [ ] 最佳 checkpoint 由预冻结规则确定，能由新进程完整恢复；恢复后的输出、formal decoder、decision config 和 validation 结果可复现。
- [ ] 若形成开发候选，冻结模型权重及 identity、decision config、tokenizer/input identity、训练 recipe、开发结果和 checkpoint/recovery 证据；
      若未形成候选，保留足以解释有效负向结论的同口径证据，不把 validation 表述为 qualification。
- [ ] 若形成候选，工作包四所需的完整 inference-ready 模型工件（包含全部学生/五头推理权重及必要 config/tokenizer/input identity）已下载至本地
      Plan 099 ignored namespace 并完成 exact-tree/bytes/SHA-256 校验；除验收必需小型证据外，完整训练 checkpoint 等大型资产留在网络卷。
- [ ] 阶段 B 核心任务完成后，执行者先提交 Pod 预释放审查；正常提前释放须待审查者确认权重回传、云端保留和后续资格前置充分且不再需要 Pod 后，
      明确批准释放。执行者随即 stop/delete 全部任务 compute Pod并实时确认 compute `$0/h`，之后才在本地整理最终文档与完成记录；不可移动
      absolute trigger 是唯一无需 queue receipt 的自动 exact-Pod 止费例外。
- [ ] 费用完整结算；卷、缓存和大型资产终态清楚；Pod 释放后的本地收口不为整理文档继续占用计费 compute。
- [ ] 最终独立审查分别给出“验收通过/不通过”和“任务目标完成/失败”，并明确终态是候选冻结、有效训练 `NO-GO` 或真正未闭合的 `INCONCLUSIVE`。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 中与五头训练、objective、consumer、validation、decision config、checkpoint/recovery、归档和云端运行直接
  契合的能力。职责契合时复用既有设施；旧 scalar 路线会扭曲 task v2 时，可以新增边界清楚且遵循现有生命周期、错误和观测方式的专用能力。
- `training/publication-critic-plan099/` 下体积合规、受跟踪的 exact model/recipe/resource/asset 合同、依赖、运行入口与 runbook；不得提交模型权重、
  checkpoint、cache、venv 或原始训练输出。
- `eval/tests/` 中相称的 pure/fake/focused 测试和小型 fixture；`eval/results/publication-critic/` 中体积合规的最终开发结果摘要。
- 职责相关的现有 RunPod seam 和 `scripts/create-runpod-when-ready.py` 调用接缝；不得把抢卡脚本扩成预算、卷、readiness、receipt、上传、训练或删除控制器。
- 本计划允许更新的状态/决策、受影响的 `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md`、完成后的
  `doc/WBS-COMPLETED.md`，以及有实质信息的精炼 `agent_log/`。
- 普通依赖下载、公开源码/官方模型资料的只读查询；阶段 A 可据此比较候选资料，但接受前只冻结并保留一个 exact base，不运行真实模型。
- 阶段 B 批准生效后，按审查者批准的精确清单使用 RunPod、远端容器环境、任务专属 namespace、必要模型下载、v10 train/validation 上传、
  候选 inference-ready 模型权重与小型结果回传和资源 stop/delete；所有外部动作都受批准的数量、时间、预算和资产清单约束。

### 不允许修改或执行

- `rondo-publication-critic-task@v2`、`rondo-publication-critic-decision@v1`、formal decoder、pair-aware selector、formal output schema 的语义，
  或 v9/v10/qualification 的数据、label、pair、split、review、manifest 和 identity。
- 五头身份、一次 forward、non-compensating gate 与 loss 职责；不得恢复自由 global-quality head、单标量 hard/soft 混合目标、Within-PASS
  资格排序、多基座/多 scope/多权重搜索或新的补偿性 overall threshold。
- Plan 054/060/064/066/068/071/073/075/079/081/082/087/090/094/095/096/097/098 的冻结结果、正式 receipt、历史报告和终态。
- 产品发布流程、typed `PASS/REWRITE` wire、Producer rewrite/fallback/cancel、Team State、Publication Critic 默认状态、生产配置或产品启用。
- 工作包四的 qualification 正文释放、冻结测试、正式横评、最终产品 GO/NO-GO 或 threshold 返调；本任务只交付候选和开发证据。
- 阶段 A 的真实模型加载/推理/训练、GPU/RunPod、Docker、付费 API、外部上传、远端资源变更或新增费用。
- 阶段 B 未经审查者明确批准的 provider/区域/硬件替换、预算或时间扩大、并行训练、第二路线、额外 Pod/卷、充值、外部发布、产品动作或资产传输。
- 本地 Docker。若涉及 Rust 构建/测试，绝对复用物理仓库根现有唯一 `.codex/cargo-target/rondo-multi` 和正式 build-lock/`just` 入口，
  不得在 worktree 或其他位置新建第二套 target、提高并发或绕过资源门。
- 修改宿主机配置、全局工具链、系统服务、其他仓库，或清理来源不明及非本任务创建的本地/远端资产。

### 不允许读取/查看

- `training/publication-critic-v9/splits/test/` 的 candidate/pair 正文。
- `training/publication-critic-qualification-v1/sealed/` 的 candidate/pair 正文；只允许既有严格入口所需的非正文 identity/manifest 机械边界，且不得形成训练或选择入口。
- 旧 unseen、其他历史私有测试资产，以及任何需要先打开 mixed/ignored 私有数据再过滤的路径。
- `.env.local` 内容、token、API key、secret、私钥、密码或个人配置。只能按根 `AGENTS.md` 静默检查文件状态与任务所需变量非空，
  严格按 `KEY=VALUE` 数据解析并只向目标子进程注入 allowlist；不得 source、打印、复制、上传或记录凭据。
- 与任务无关的 ignored namespace、其他 worktree 的未提交修改、真实 private transcript/reasoning 或项目外个人文件。

### Git-ignored 与主物理根边界

全部 tracked 修改在以下 worktree 完成并提交，主工作区不得产生 tracked 修改：

`/home/sjc/desktop/RONDO/.claude/worktrees/099-publication-critic-five-head-training/`

linked worktree 不共享主物理根 ignored `eval-data/`。阶段 A 的 bundle dry-run、阶段 B 的上传源、回传、receipt、日志或任务运行工件如确有需要，
只允许使用主物理根任务 namespace：

`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan099/`

执行者只访问任务需要的精确已知路径，不递归浏览其他 ignored 资产。阶段 A、Pod 预释放和最终汇报必须单独列出主物理根实际创建或修改的 ignored
路径、用途、大致体积和保留/清理状态；不建立逐文件审计台账。选中候选的完整 inference-ready 模型工件必须回传到上述 ignored 交接边界并供
工作包四直接消费；完整训练 checkpoint、optimizer state 和其他大型训练输出留在云端网络卷。两类资产都不得进入 Git。

## 3. 硬约束

以下约束只冻结任务正确性、数据隔离、阶段授权、正式训练血统、费用安全和交付边界；不锁死框架、类名、内部模块布局、平滑公式、优化器、
trainable scope、精确训练强度或普通调试顺序，这些由执行者在阶段 A 作出一次有依据的冻结选择。

1. **两阶段授权。** 阶段 A 已获本轮用户授权。阶段 B 只有在执行者完成阶段 A、提交 clean worktree、通过 §7 队列申请验收后，由审查者完成独立
   审查并通过同一队列明确批准才生效；用户已经授权审查者以该批准代替额外用户回复。审查者批准必须写明阶段 A 接受状态和最终冻结的全部外部边界，
   不能用模糊的“继续执行”代替。未获批准时安全停止，不创建 Pod/卷、不上传下载、不运行真实模型、不训练、不产生费用。
2. **唯一主方案。** 阶段 A 可以基于只读资料评估候选，但最终只能冻结一个本地可运行的 exact base/revision、一个五头实现、一个 trainable scope、
   一套 loss/optimizer/precision/时长/checkpoint/选择 recipe；不得并行保留多个待试基座或付费探索分支。阶段 A 接受后，换 base、scope、loss 职责、
   数据或 recipe 都是原则性变更，不能用 commissioning 或恢复名义绕过。
3. **冻结身份与正式判定。** 训练路径必须通过现有 strict release/identity 入口绑定 task v2 accepted implementation、decision v1 implementation
   bundle、v10 manifest 和 train/validation candidate+pair bytes、正式 output schema 和 tokenizer/input/model identity。正式 projection 唯一走
   `qualification.py#decode_with_decision_config` 的 frozen-config decoder；旧 raw argmax 只作 zero-margin diagnostic/historical reference。
4. **物理数据隔离。** 只有 v10 train 进入梯度，validation 只能经显式入口用于开发观察、停止、checkpoint 选择和 decision config；v9 test、
   qualification、旧 unseen 和其他私有测试正文不可达。正式云端 bundle 必须从物理只有 v10 train/validation 的 allowlist 构建，不能先打包再过滤。
5. **五头与 loss 职责。** 一次 backbone forward 只产生 task v2 的五个资格 heads；`L_dim` 是完整五维绝对主体，`L_gate` 只监督五头派生合取，
   `L_boundary` 只对严格 Boundary 的 target head、两端绝对 gate 和非目标不变性负责，达到有限 margin 后不再扩张，`L_invariance` 只约束
   soft-only 双端的 head/applicability/gate 不变。精确连续近似、权重和 margin 由阶段 A 冻结，但不得改变方向或增加补偿目标。
6. **开发规则先于正式结果。** 阶段 A 使用冻结 v10 validation 支持量和产品风险一次冻结数值门、不可用分母语义、聚合顺序、tie-break、停止规则和
   best-checkpoint 选择。pair-aware decision config 必须消费真实 validation candidates+pairs；所有 Boundary 与 soft-only pair 闭合后才可进入
   同一个 bounded margin grid 的确定性排序。validation 结果只叫开发结果，不叫 qualification、产品资格或独立泛化。
7. **checkpoint 与恢复。** 正式 checkpoint 至少覆盖模型、实际 trainable scope、optimizer/scheduler、精度状态、RNG、data cursor、训练进度、
   recipe/identity 和候选选择状态；只有完整原子发布并读回校验的 checkpoint 才能参与选择或恢复。至少一个正式 checkpoint 必须由不同 OS 新进程
   完整恢复并复现结果；恢复后若继续训练，不得改变 recipe。
8. **先调通、后 clean formal。** 阶段 A 先以 pure/fake/dry-run 闭合模型无关链。阶段 B commissioning 可以保留已验证进度，从首个未打通处
   边修边跑，直到环境、非零更新、完整 checkpoint、checkpoint 后评价、fresh-process 恢复、回传和止费链完整打通；随后冻结实际 source、
   environment 和 resource binding，从 exact base 与空 formal namespace 运行正式轮。commissioning 工件不能进入正式候选血统。
9. **允许修故障，不允许修结果。** 代码、依赖、环境、连接、OOM、显存适配、存储、保存、恢复和传输等正确性问题可在批准的总时间/预算/资源及
   唯一 recipe 等价适配边界内自主窄修、恢复或清空无效 formal namespace 重跑，不设“一次窄失败即停”的机械限制。正式轮有效但开发质量不足时，
   必须接受 `NO-GO`，不得改模型、loss、数据、scope、门限或开第二路线追逐正向结果。
10. **动态预算与费用门。** 阶段 B 批准时先实时冻结可用余额、已知未结/延迟费用、现有网络卷实际小时费率和资源价格。必须始终在账户中留下现有
    网络卷继续保留 6 小时所需金额；本任务动态总预算为：

    `max(实时可用余额 - 已知未结或延迟费用 - 6 × 现有网络卷实时小时费率, 0)`。

    该余额是不可突破上限，不是花费目标，也不授权充值。Pod、容器盘、任务期间卷费、模型/数据传输、commissioning、formal、恢复、回传和止费
    都计入同一总账；启动任何长步骤前必须确认剩余预算足够完成该步骤、候选权重完整回传、Pod 预释放审查等待和安全止费，否则不启动或立即止费。
    所有任务 Pod 的累计计费墙钟硬上限为 10,800 秒；对当前 Pod 必须机械满足
    `prior wall + maximum lifecycle + 60 秒 worker kill grace + 360 秒终态确认 <= 10800`。
11. **资源与抢卡。** 阶段 A 的付费申请必须冻结 RunPod 区域、单卡硬件、最长墙钟、同时/累计 Pod 与卷数量、exact image/environment、上传下载
    allowlist、现有 `mwemzrn33y` 的复用资格或新建/扩容/删除策略，以及最终保留/删除动作。历史 Plan 082/087/090/094 roots 保持只读；若复用
    `mwemzrn33y`，只写 Plan 099 独立 root。静态上传只含两份 bundle 及两份 receipt；Pod 创建核验后的 runtime host→Pod 上传只含
    live-resource、lifecycle、paid-segment 三类 canonical content-addressed JSON，不开放任意 JSON 或其他资产。库存紧张时必须使用
    `scripts/create-runpod-when-ready.py`；创建后由执行者独立核验实际价格、硬件、
    机房和卷挂载，不符则立即释放，不能让创建脚本承担这些职责。
12. **候选回传与 Pod 预释放门。** 候选模型、decision config、tokenizer/input、recipe、开发结果与恢复证据须形成校验和一致的冻结集合。
    若形成候选，必须在 Pod 预释放审查前把工作包四所需的完整 inference-ready 模型工件（全部学生/五头推理权重及必要 config/tokenizer/input）
    下载到本地 Plan 099 ignored namespace，并独立核对 exact-tree、bytes 和 SHA-256；不能只回传 manifest、adapter 或摘要后把唯一可运行权重留在云端。
    完整训练 checkpoint、optimizer/scheduler/RNG state 和其他大型资产继续留在网络卷的 Plan 099 独立 root，只回传验收必需的小型证据。
13. **先审查、再释放 Pod、后本地收口。** 阶段 B 核心训练、fresh-process 恢复、正式评价、候选/`NO-GO` 冻结、必要模型/证据回传和仍依赖 GPU
    的验证全部完成后，执行者先提交 tracked 变动、保持 worktree clean，通过 §7 队列申请 Pod 预释放审查并停止。审查者确认不再需要 Pod 后，
    通过队列明确批准释放；执行者立即 stop/delete 全部任务 compute Pod并实时确认 0 Pod / compute `$0/h`，随后在无 Pod 状态下整理最终结果、
    WBS、COMPLETED 和日志。审查未通过时只做审查者要求的必要 GPU 整改，不正常提前删除 Pod；不可移动 absolute trigger 先到时由已武装 guard
    无需 queue receipt 自动 exact stop/delete 并确认 0 Pod / compute `$0/h`，这是守住 10,800 秒硬上限的唯一例外。批准释放后不得仅为文档整理重建 Pod。
14. **测试与诚实口径。** 只运行受影响模块必要的 pure/fake/focused 门禁和相称格式/静态检查；若改 Rust，遵循共享 target/build-lock 规则，
    不默认扩大全 workspace。fake、dry-run、commissioning、formal、skip 和未运行必须分开记录，不以弱化测试、安全门或审批逻辑换取绿色结果。
15. **提交与下游边界。** 阶段 A、Pod 预释放、整改和最终交付都先提交 099 分支再向审查者报告；不合并、不推送。工作包四的冻结测试、横评、最终产品 GO/NO-GO
    和启用决策不在本计划内，Plan 099 完成后只按 WBS 交接候选或有效训练 `NO-GO`。

## 4. 软性建议

以下建议可由执行者依据现有代码、公开资料、定向测试和实际资源采用更优的等强方案替代；替代不需要逐项请示，只要不改变第 3 节硬边界。

- 先盘点 Plan 060/066/081/082/087/090/094 已有 consumer、objective、checkpoint、archive、fake 与 RunPod 生命周期能力。职责契合时复用；
  若旧单标量假设会污染五头语义，新增 Plan 099 专用薄层或干净通用化，不维护第二套重复体系。
- 基座选择综合本地可运行尺寸、license、tokenizer/input 兼容性、结构化五头支持、训练显存/时间/费用和后续维护；用公开 model card/revision
  metadata 与历史证据作初筛即可，阶段 A 不为比较而下载或运行多个真实模型。
- 以人可读、受跟踪的 model/recipe/resource/asset config 保存冻结决定，并由现有 strict loader 校验直接语义身份；不建设 registry、数据库、
  PKI、递归依赖图或通用训练平台。
- 可把 pure objective、consumer 隔离、schema/finite、selector、checkpoint/recovery、archive 和 budget/resource gate 分段打通，再从干净临时目录
  做一次完整 fake/dry-run；测试组合以能捕获本次风险为准，不重复堆叠历史套件。
- commissioning 可先用最小微批次/短序列/短更新暴露显存与吞吐问题，再采用阶段 A 预定义的等价资源适配；正式 recipe 的有效 batch、精度、
  loss、scope 和停止语义保持不变。调试进度可保留，但 formal 必须从干净起点开始。
- checkpoint 保留可围绕 `best/latest/fresh-process-recovery` 去重；选中候选的完整 inference-ready 权重回传本地，完整训练 checkpoint 留在云端卷；
  开发指标和决策证据轻量回传，不为形式完整下载所有中间大型资产。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-28：从 clean `main@01b9e7ccd11641014a6540390af7a113493330b0` 创建专用 worktree
  `/home/sjc/desktop/RONDO/.claude/worktrees/099-publication-critic-five-head-training/` 和分支
  `worktree-099-publication-critic-five-head-training`。
- 2026-08-28：完成 ExecPlan 与 WBS 当前状态窄同步；规划期间未读取 v9 test、qualification sealed 正文或旧 unseen，未运行真实模型、
  GPU/RunPod/Docker/付费 API，未上传资产或产生训练费用。
- 2026-08-29：阶段 A 冻结 exact Skywork 1.7B base、五头 linear-probe recipe、开发准入门、checkpoint-first 恢复、候选 exact-tree、动态预算与
  RunPod 生命周期设施；pure/fake/focused `6/6`、freeze CLI、Ruff、compile、shell/diff 门通过。source/data bundle 已在提交后从 exact commit
  生成并完成独立解包、合并与 freeze 复验；阶段 A 未运行真实模型、GPU/RunPod/Docker/付费 API，未上传资产或读取禁止正文。
- 2026-08-29：首轮独立验收确认五项付费前阻断；阶段 A 已整改 checkpoint 裁剪后五点评价复核、无 config 终态、step 12 续训、checkpoint/retention
  崩溃重入、isolated venv 复用 exact image Torch，并以 Plan 094 guard 的固定 Plan 099 profile 补齐 10,800 秒绝对截止自动止费。Plan 099、
  Plan 094 guard 与 Plan 087 terminal focused 合计 `22/22` 通过。
- 2026-08-29：整改复验确认 venv symlink、累计墙钟口径及 runtime control 上传边界三项剩余阻断；已改用 copied venv 并真实复用 worker 判定，
  冻结 `prior + lifecycle + 60 + 360 <= 10800` 与 absolute-trigger 唯一自动释放例外，并只开放三类 canonical/content-addressed runtime JSON。
  Plan 099 focused `14/14`、Plan 094/087 回归 `9/9`、freeze/Ruff/compile/shell/diff 门通过，等待绑定最终整改提交的四份 bundle/receipt 后申请复验。
- 2026-08-29：阶段 A 通过独立验收，阶段 B 获明确外部授权。首 Pod `z1z3m7n90nz4xr` 完成 provider、L40S、区域、镜像、价格与卷挂载核验；
  bootstrap 在模型下载前因网络卷 FUSE 将控制 JSON 呈现为 `0666` 而 fail-closed。审查者批准的 current-Pod `/run` 窄例外已由提交
  `a84fb5dd` 闭合，定向 `24 passed`，四件 bundle/receipt 已绑定新提交重建。
- 2026-08-29：进入云端恢复前发现 host guard PID 不存活，按已授权 guard safety failure 止费路径立即 exact delete 首 Pod；实时确认
  `pod_count=0`、compute `$0/h`，未下载/加载模型、未执行 commissioning 或 formal，网络卷保留。
- 2026-08-29：审查者批准最后一个 replacement Pod、从已核验 actual Pod ID 动态派生的 `/run` 控制根和前台长期 exec guard；本地已移除首 Pod
  硬编码并显式拒绝其路径，两个不同合法 ID 的实例化及错 ID/workspace/其他 `/run` 拒绝路径进入 focused 门，组合 `24 passed`。

### 当前工作

- `PHASE_B_LAST_TECHNICAL_RECOVERY_PREP / ZERO_POD`。

### 本任务剩余步骤

1. 提交动态 runtime-control 窄修，重建并验签同名四件 bundle/receipt；创建前刷新实时预算与 0 Pod 状态。
2. 创建并独立核验最后一个 replacement Pod，生成生命周期授权并以前台长期 exec 会话稳定武装 guard。
3. 在原冻结路线、剩余累计墙钟与动态预算内执行 commissioning、clean formal、恢复复现、候选或 `NO-GO` 冻结与必要回传。
4. 提交阶段 B 核心交付，使用 §7 队列申请 Pod 预释放审查并停止；审查者确认无需 Pod 并明确批准后，立即 stop/delete Pod、复核 compute `$0/h`。
5. 在无 Pod 状态下完成本地结果、WBS、COMPLETED 与日志收口；提交最终 tracked 变更，使用 §7 队列申请最终独立验收并停止。

### 阻塞项

- replacement Pod 是最后一个任务 Pod；若资源、预算或前台 guard 再失败，立即安全收口，不得创建第三 Pod。
- 阶段 B 核心任务完成后，正常 Pod 删除仍由 Pod 预释放审查门控制；安全止费与 absolute trigger 例外保持有效。

### 当前验收状态

- 规划：`COMPLETED / COMMITTED`。
- 阶段 A：`REVIEW_ACCEPTED / COMPLETE`。
- 阶段 B：`AUTHORIZED / LAST_TECHNICAL_RECOVERY_PREP / ZERO_POD`。
- 完整任务：`IN_PROGRESS / MODEL_NOT_DOWNLOADED / TRAINING_NOT_STARTED`。

### 交接边界

- 执行者和审查者只在 099 worktree/branch 完成 tracked 变动、整改和提交；阶段 A、Pod 预释放、最终验收和计划外请示均使用 §7 指定 Codex queue。
- 阶段 A 审查通过后，审查者必须通过同一队列显式批准并写明阶段 B 外部边界，执行者才可继续；最终验收通过后审查者不再唤醒执行者。
- 任何超出已生效阶段授权、目标/硬约束改变或真实高危扩权，由审查者判断是否必须转交用户；范围内普通技术决定由执行者自主处理。
- ignored 主物理根变化单列汇报；tracked 主工作区保持 clean。未经用户批准，不合并、不推送、不归档/重命名分支、不删除 worktree。
- Plan 099 完成后冻结本计划；候选或训练 `NO-GO` 的下游只链接 WBS，不在本计划重复规划工作包四。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 099 使用同一 ExecPlan 的阶段 A 本地非付费准备与阶段 B 云端付费执行；阶段 A 提交/独立审查是硬闸门 | 先尽量在本地闭合正确性，再减少付费调试成本，同时不把准备授权误作外部授权 | 阶段、授权、费用 | 已采纳 |
| 002 | ExecPlan 不替执行者预选 base、框架、scope、权重或超参数，只要求阶段 A 接受前冻结唯一 exact 主方案 | 保留实现自主性和更优架构选择空间，同时禁止重新滑回多路线搜索 | 模型、recipe、实现 | 已采纳 |
| 003 | 用户授权审查者在阶段 A 独立验收后代为批准阶段 B；批准必须通过指定 queue 明确给出完整外部边界 | 避免阶段 A 后重复等待用户，同时保留付费和外部状态的清晰授权时点 | 审批、协作 | 已采纳 |
| 004 | 阶段 B 动态预算等于实时可用余额扣除已知未结/延迟费用和现有网络卷 6 小时保留费后的非负余额 | 保证任务始终留下 6 小时网络卷金额，其他实际可用额度才属于本任务 | 预算、止费 | 已采纳 |
| 005 | 技术无效轮可在总边界内修复并从干净 namespace 重跑；有效质量失败不得借重跑换路线或改 recipe | 给窄故障合理冗余，同时保护单主方案与诚实负向结论 | commissioning、formal、终态 | 已采纳 |
| 006 | tracked 变动只在 099 worktree；必要 ignored 工件只用物理根 `eval-data/publication-critic/plan099/` 并单列汇报 | linked worktree 不共享 ignored 数据，又不能污染主工作区 tracked 状态 | Git、资产 | 已采纳 |
| 007 | 职责契合时复用已有训练设施；复用会扭曲五头语义时允许新建架构契合的专用能力，不建设重复平台 | 兼顾干净复用与任务语义，不因历史 scalar 路线强行耦合 | 架构、维护 | 已采纳 |
| 008 | 候选完整 inference-ready 权重必须回传本地 ignored namespace；完整训练 checkpoint 等其他大型资产留在云端网络卷 | 工作包四需要直接消费候选模型，同时避免无必要下载所有训练大资产 | 工件、回传、资格前置 | 已采纳 |
| 009 | 阶段 B 核心交付先做 Pod 预释放审查；审查者确认不再需要 Pod 后立即释放，再做本地文档收口 | 避免为了慢速文档整理继续支付 compute，同时防止过早删 Pod 导致必要 GPU 复验无法完成 | 审查、止费、收口 | 已采纳 |
| 010 | 唯一主方案冻结为 exact Skywork Reward V2 Qwen3 1.7B BF16 backbone，加五个独立 FP32 无 bias linear heads；只训练 22,528 个 head 参数，16 次 full-cohort update | 与既有本地运行目标、48GB L40S、v2 五头语义和有限预算直接匹配，不引入第二路线或 adapter-only 交付 | 模型、scope、recipe | 已采纳 |
| 011 | 正式点固定为 2/4/8/12/16，step 8 与最终最佳点都须新进程复现；任何进程中断只从 checkpoint-first 外部状态恢复 | 同时证明中程继续训练与最终候选本体可恢复，避免可编辑 controller state 冒充 checkpoint 证据 | checkpoint、恢复、候选 | 已采纳 |
| 012 | 开发准入固定使用 12 项 bounded margin grid、全 pair 闭合、五头非塌缩、gate FP≤3/FR≤4/BA≥0.75、逐头 failure recall 与 macro recall 下限，并要求相对 step zero 严格改善或新获准入 | 在正式结果出现前把风险门和 tie-break 固定，validation 只承担开发选择 | 开发评价、NO-GO | 已采纳 |
| 013 | 五点评价作为 write-once 小型证据全部保留，完整 checkpoint 仍只留 best/latest/step 8；候选只要求最佳完整 checkpoint 在线，并允许早期无 decision config 的点不参与排名 | 同时满足五点轨迹复核、三 checkpoint 体积上限与早期不可判定语义，不把评价证据误当完整权重 | 候选、保留、NO-GO | 已采纳 |
| 014 | 正常提前释放仍由 reviewer receipt 解锁；不可移动绝对 trigger 由 Plan 094 guard 的固定 Plan 099 profile 自动 exact stop/delete 并确认 0 Pod、compute `$0/h` | queue 等待不能突破累计墙钟和动态预算，deadline 安全终止不应依赖人工及时响应 | 生命周期、费用、审批 | 已采纳 |
| 015 | `maximum_lifecycle_seconds` 是 Pod 主体窗口；累计计费上限机械包含 60 秒 kill grace 与 360 秒确认。runtime host→Pod 只开放 resource/lifecycle/segment 三类 16 KiB canonical content-addressed JSON | 使 10,800 秒硬上限覆盖最坏收口，同时只传 worker 必需控制面，不扩大任意上传能力 | 生命周期、资产传输 | 已采纳 |

## 7. 给执行者的启动提示词

你是 Plan 099 的执行者。请在 `/home/sjc/desktop/RONDO/.claude/worktrees/099-publication-critic-five-head-training/`、分支
`worktree-099-publication-critic-five-head-training` 内工作。开始前完整阅读根 `AGENTS.md`、`multidev/AGENTS.md`、当前 WBS、
Plan 098 最终冻结交接和 `plan/099-publication-critic-five-head-training-and-candidate-freeze-execplan.md`，随后直接执行阶段 A，不另写重复计划，
也不要向用户复述 ExecPlan 或 AGENTS 内容。实现路线由你自主选择；本计划软建议可以被更优等强方案替代，硬边界必须遵守。

用户已经一次授权阶段 A：在 099 worktree 内修改本任务需要的训练、评价、测试、合同和文档，进行必要局部重构与轻量生成，合法读取
`publication-critic-v10` train/validation，下载普通依赖，只读查询公开源码/官方模型资料，使用任务专属 ignored namespace，运行相称的
pure/fake/dry-run/focused 门禁，使用子智能体辅助研究或独立审查，在范围内自主修复 findings、重生成和重跑，更新精炼日志/WBS 并提交 099 分支。
如果涉及 Rust，必须复用物理仓库根唯一 `.codex/cargo-target/rondo-multi` 和正式 build-lock/`just` 入口，绝对不得新建第二套 target。

阶段 A 授权不包含真实模型加载/推理/训练、GPU/RunPod、Docker、付费 API、外部上传下载、Pod/卷变更、qualification/v9 test/旧 unseen 正文、
产品启用/生产、宿主机或全局工具链修改、合并、推送、分支归档/重命名或删除 worktree。主物理根 ignored 变更必须在完成汇报中单列精确路径、用途、
大致体积和保留/清理状态。阶段 A 的范围内普通问题自行修复重跑，不要反复请示；目标、硬约束、授权或真实外部状态的计划外变化才通过队列请示。

完成阶段 A 后，先提交全部 tracked 变动并保持 worktree clean，再提交包含唯一 exact 主方案、开发准入数值、定向验证结果、ignored 资产、RunPod
provider/区域/硬件/时限、Pod/卷数量、动态预算、上传下载 allowlist、commissioning、技术恢复/重跑、回传和资源收口的完整阶段 B 申请，然后停止会话。
用户已授权审查者在独立验收通过后代为批准阶段 B；只有审查者通过指定队列明确回复批准和最终外部边界后，本授权才生效，无需再等待用户回复。
阶段 B 生效后，你可以在这些总边界内自主处理库存、环境、依赖、传输、中断恢复和普通代码/配置正确性问题；有效正式轮质量不足必须停止为
`NO-GO`，不得换模型、数据、scope、loss 或开启第二路线。阶段 B 预算是批准时实时可用余额扣除已知未结/延迟费用及现有网络卷 6 小时实时保留费
后的非负余额，必须覆盖 commissioning、formal、回传和止费，不授权充值。库存紧张时按根规则使用 `scripts/create-runpod-when-ready.py`，
创建后独立核验实际硬件、价格、机房和卷挂载。

阶段 B 核心训练、fresh-process 恢复、正式评价、候选/`NO-GO` 冻结、必要 GPU 验证和回传完成后，不要先花时间整理全部文档。若形成候选，必须先把
完整 inference-ready 学生/五头模型权重及必要 config/tokenizer/input identity 下载到主物理根 Plan 099 ignored namespace，完成 exact-tree、bytes、
SHA-256 校验；完整训练 checkpoint、optimizer state 和其他大型资产留在网络卷，只回传验收必需的小型证据。然后提交当前 tracked 变动、保持
worktree clean，通过同一队列以“Plan 099 阶段 B 核心任务与 Pod 预释放准备”申请审查并停止。正常提前释放只有在审查者明确确认不再需要 Pod、
批准释放后才执行；不可移动 absolute trigger 先到是唯一无需 queue receipt 的自动 exact-Pod 止费例外。释放后实时确认 0 Pod / compute `$0/h`；
之后在无 Pod 状态下慢慢整理本地结果、WBS、COMPLETED 和日志，再提交并申请
最终验收。Pod 预释放审查未通过时，只完成审查者要求的必要 GPU 整改；批准释放后不得为文档整理重建 Pod。

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a04c14-30e5-7212-8e6e-597ae12e5baa 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。

需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。

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

执行者给审查者发送消息的时候，必须主动表明身份。

为同时满足阶段验收模板原样使用和主动表明身份，实际 `XXX` 第一行先写
`【身份：Plan 099 执行者｜阶段 A/阶段 B/整改轮次】`，随后原样粘贴上述从“执行者完成了<阶段性任务>”开始的模板，只替换两个尖括号占位符；
身份前缀不计入 `<执行者的完成汇报>`，完成汇报本身仍一模一样嵌入。普通请示也在第一行使用同样身份格式。

上述原文中的“如果验收通过，他不会再通知你”只适用于最终完整任务验收。阶段 A 通过后，审查者必须通过同一 Codex queue 明确通知执行者，
写明“Plan 099 阶段 A 验收通过，批准进入阶段 B”及完整外部边界；执行者在收到该消息前保持停止，不自行轮询或进入阶段 B。
阶段 B 核心任务完成后的正常提前释放同样必须由审查者通过队列明确回复“确认不再需要 Pod，批准立即释放”；执行者收到后先释放并复核 0 Pod，
再继续无 Pod 的本地收口。不可移动 absolute trigger 先到时由 guard 自动止费，无需等待该回复。该中间审查也使用上面的阶段性任务模板，
`<阶段性任务>` 填写“Plan 099 阶段 B 核心任务与 Pod 预释放准备”。
