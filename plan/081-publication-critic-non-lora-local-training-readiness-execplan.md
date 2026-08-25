# Plan 081：Publication Critic 1.7B 非 LoRA 训练路线本地收敛与云端就绪 ExecPlan

> 本计划是 Plan 081 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停对应动作，按本计划指定的 Codex 跨会话队列联系审查者取得批示。
> 普通代码、fixture、依赖、接口、脚本、测试或审查问题应在授权范围内自主修复并按需重跑；只有原则性边界、授权外高危扩张或
> 资源门 fail-closed 才停止对应动作。
> 本计划只描述 Plan 081；后续云端任务、三期路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在不加载或运行真实模型、不使用 GPU、不创建云资源且不产生费用的前提下，把 Publication Critic 下一轮训练收敛为一条可执行、
可恢复、可观察的 exact 1.7B 非 LoRA 路线，并用轻量 fixture/fake 从冻结训练输入打通连续更新、同口径 validation 质量观察、候选选择、
checkpoint 恢复与结果归档闭环。

当前研究目标是让后续真实训练形成同口径优于 exact 1.7B base 的候选，不要求该候选直接达到产品 GO。Plan 081 只把这一区分落进
选择/交接语义：base 继续作为 incumbent，训练 checkpoint 只有优于 base 时才成为研究目标候选，否则诚实记录 no-improvement；
本地 fake 不产生真实质量候选。

职责契合时复用现有 Plan 060/066 的数据、训练/checkpoint 基元和 Plan 073 的质量指标；旧设施把历史 H100 全参数、FlashAdamW、
C1/C2/C3 单阶段单次更新语义写死时，应提取中性能力或建立职责明确的 Plan 081 专用薄层，不通过放松 Plan 060/066 历史合同来伪装泛化，
也不复制第二套数据、评价或训练平台。

### 完成/验收标准

- [ ] 路线合同继续绑定 exact
      `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`；冻结 pair 设计、
      packet/render/tokenization/scalar 方向、label 语义和 v8 train/validation/unseen split 不变，明确禁止 LoRA、QLoRA 与其它 PEFT 路线。
- [ ] 当前首选是从部分参数直接更新开始，并允许依据训练动态扩大可训练范围；合同能够表达和恢复实际更新范围，但不在本任务预先冻结
      具体层数/模块名、学习率、batch、更新数、优化器、scheduler 或扩大策略细节，也不把全参数更新继续写成强制路线。
- [ ] 本地控制链支持多个连续更新点和可配置观测点，不再依赖 Plan 066 的固定 C1→C2→C3、每阶段恰好一次 update 或固定 recipe；
      fixture/fake 能证明一次运行内的连续进度、停止/继续和恢复后续跑。
- [ ] 每个观测点使用既有同口径 validation 输入与质量定义，至少保留完整聚合指标、逐 pair 方向与 margin，并能相对 base/previous/best
      诚实标记改善、退化或停滞；这些开发期 validation 观察不得冒充正式 M3-C2、unseen 或产品资格证据。
- [ ] 选择状态明确区分 `base incumbent`、`better-than-base candidate` 与 `no-improvement`；一个训练 checkpoint 即使是训练序列中的
      least-bad/best，也不能在未优于 base 时冒充研究目标候选。具体同口径比较策略与容差由后续实测收敛，不在本计划预冻。
- [ ] checkpoint 生命周期区分“用于质量评价的模型快照”和“用于恢复训练的完整 checkpoint”。每个观测点永久保留小型指标与 pair margin；
      长期模型/恢复工件只需 base、best、latest 和少量有理由的关键转折点，不要求每个 update 永久保存完整权重。
- [ ] 从完整 checkpoint 恢复时，进度、实际参数更新范围、必要 optimizer/scheduler/RNG 状态、观测历史、best/latest 选择和保留策略连续；
      删除 superseded 工件不得破坏唯一可恢复点或已保留的小型观察记录。
- [ ] route/controller、checkpoint/retention、evaluation/archive 的 fake/fixture 集成测试覆盖改善、退化/停滞、关键转折点保留和中断恢复；
      既有 Plan 060/066 数据隔离、方向语义、checkpoint 与 Plan 073 指标聚焦回归通过。
- [ ] 三期 WBS 将 H100 全参数 + FlashAdamW 降为 Plan 060/066 历史事实，把 Plan 081 的 exact 1.7B 非 LoRA 路线记录为当前工作包；
      顶层 WBS 与 Plan 080 的并行改动只做三期窄同步，最终整合者基于最新 main 手工合并，不 whole-file 覆盖。
- [ ] 形成一份后续云端任务可直接消费的轻量训练/运行边界：单张 A40 48GB 首选、L40S 48GB 备选，单卡窗口不超过 12 小时，
      外部总费用不超过 15 USD；Plan 079 保留卷不是显卡、区域、容量或启动前置。本任务只准备合同，不查询库存、不创建资源、不上传或计费。
- [ ] 相关 Python 单元/集成测试、编译检查、必要格式/静态检查、改动脚本的 `bash -n` 与 `git diff --check` 通过；未运行项如实记录，
      不运行 Cargo、Docker、全 workspace、真实模型或云端门禁。
- [ ] 执行者完成范围内实现、文档、精炼日志和自检后提交 Plan 081 task branch 并保持 worktree clean；独立审查关闭所有高/中等级
      correctness/functionality finding。普通可修问题不得直接形成 `REPLAN_REQUIRED`，应先在本任务边界内修复重跑。
- [ ] 独立审查最终只给出 `LOCAL_TRAINING_READINESS_PASS` 或 `REPLAN_REQUIRED`。前者仅表示可按 WBS 进入后续真实环境 commissioning/
      训练参数开发；不表示模型质量 GO、云端授权、产品启用或 M3-D 解锁。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/full_model_training/` 内职责契合的数据、训练控制、checkpoint、恢复、工件与 receipt 基元；若历史
  Plan 060/066 适配层不宜继续承载新语义，可在 `publication_critic/` 下增加职责明确的 Plan 081/route-neutral 薄能力。
- `eval/rondo_eval/publication_critic/selection/` 中真正通用的 validation 指标/逐 pair 结果接缝；只能做中性复用或窄兼容，不改 Plan 073
  冻结结果、selection/Judge/unseen 语义。
- `training/publication-critic-plan081/` 下轻量、受跟踪的路线、云端 handoff、checkpoint/retention 或运行合同；总量继续服从
  `training/` 入库门限，不提交模型权重、adapter、checkpoint、cache 或训练输出。
- `eval/tests/` 中相称的 pure/fake/fixture/focused 测试，以及为复用既有测试设施所需的少量 test support。
- 本计划“当前状态”和“关键决策记录”、`doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、必要的精炼 `agent_log/`，以及在独立
  验收通过后由审查者按文档职责更新的 `doc/WBS-COMPLETED.md`。
- 普通依赖/公开源码与文档的只读查询；优先使用现有锁定环境，只有 live code 证明必要时才窄改依赖合同。
- 只读核对 Plan 060/066/073/075/079 的 tracked 合同、manifest、精炼结果和必要的 body-free ignored 元数据；不得据此启动旧路线。
- 通过既有 loader 只读使用主物理根
  `eval-data/publication-critic/plan066/bundles/final-01-extracted/` 的物理无 unseen train+validation 投影做必要的接口集成核对；
  不复制、不修改、不递归浏览其中的模型/checkpoint/其它工件。

### 不允许修改或执行

- `training/publication-critic-v7/`、`training/publication-critic-v8/` 的冻结正文、label、pair、split、review、manifest 或历史身份；
  Plan 054/060/064/066/068/071/073/075/079 的冻结结果、计划结论、正式 receipt 和历史报告。
- Publication Critic 产品默认、`multidev/` 产品实现、threshold、模型选择锁、M3-D、正式 M3-C2/unseen 流程或产品启用。
- 真实模型加载、推理、训练、权重/adapter/checkpoint 下载或生成、本地 GPU、RunPod/HF Jobs/其它云资源、远端上传、费用、Docker、
  Cargo、全 workspace 测试、CI/PR、发布或上游基线升级。
- LoRA、QLoRA、其它 PEFT、量化训练或另换学生底模；大规模超参搜索、论文式消融、通用训练平台、模型 registry、第二套数据/评价系统、
  复杂审计/可信/签名/机器验收平台。
- Plan 080 的 `multidev/` 实现、worktree、未提交计划改动，Plan 069 target，Plan 074/078 或其它任务的 tracked/ignored 资产；
  不清理、复制或改写现有大型 cache、target、模型和 checkpoint。
- 未经用户批准合并/rebase/cherry-pick main、推送 task branch、归档/重命名分支、删除 worktree，或修改宿主机/项目外状态。

### 不允许读取/查看

- v8 unseen-test 的正文、render、score、Judge 输入/输出，或会释放其内容的 mixed 数据路径；实现和测试使用物理不含 unseen 的既有
  train+validation 边界、body-free manifest/计数或任务自有 fixture，禁止用“读全量后过滤”实现隔离。
- `.env.local` 内容、token、API key、secret、私钥、密码、个人配置、项目外个人文件和来源不明的 ignored 资产。
- 模型权重、adapter、训练后候选和完整 checkpoint 内容；只允许核对任务必要且不泄露正文的文件存在性、大小、hash/manifest 元数据。

### Git-ignored 与主物理根边界

全部 tracked 编辑在
`/home/sjc/desktop/RONDO/.claude/worktrees/081-publication-critic-local-training-readiness/` 完成并提交，主工作区不产生 tracked 修改。

Plan 081 的本地正确性闭环应使用任务 fixture 和 `/tmp` 临时目录；测试可只读复用主物理根已有 `eval/.venv`，并以 `-B`/等强方式避免
在源码树写入 `__pycache__`，不得 sync/install 依赖或扩大共享 Python cache。必要的历史核对只读访问主物理根
`eval-data/publication-critic/` 下精确的 body-free metadata；唯一允许读取正文的既有 ignored 输入是上述物理无 unseen 的 Plan 066
train+validation 投影，并且只通过既有 loader 做接口核对。不扫描模型、checkpoint、raw score 或其它任务目录。

当前没有必须直接写主工作区 git-ignored 资产的工作。若 live 实现证明必须保留本地 dry-run 工件，只能先通过本计划指定队列报告准确路径、
用途、预计体积和清理责任并取得审查者批示；不得借此触碰/清理 Plan 069 target、Plan 079 卷镜像或既有模型资产。

## 3. 硬约束

以下约束只冻结模型/数据/评价语义、训练控制结果、资源与交付边界，不锁死模块布局、类名、配置格式、算法细节或测试数量。

1. **模型与监督路线不漂移**：exact 1.7B identity、pair/input/label 语义和 train/validation/unseen 隔离保持不变；禁止 LoRA/QLoRA/PEFT。
   部分参数直接更新是当前首选起点，可依据训练动态扩大，但本地 fake 不能替未来 GPU 实测冻结具体更新范围或 recipe。
2. **历史适配层保持历史**：Plan 060/066 的 H100 全参数、FlashAdamW、固定 C1/C2/C3 与单次更新合同继续可验证但只作历史能力来源。
   不得原地放松 plan-specific validator、改写旧 receipt 或让旧正式结果看似符合新路线；中性基元与新路线语义应有清楚职责边界。
3. **一条闭环而非第二套体系**：训练输入继续来自既有 consumer/物理无 unseen 投影，质量观察继续使用既有 scalar 方向与 validation metrics，
   checkpoint/archive 优先复用现有安全写入和恢复基元。新能力只补连续控制、参数范围、观察与保留策略缺口，不复制数据或评价体系。
4. **连续更新和观测是真实状态**：controller 必须能表达多更新、多观测、previous/best/latest 和停止/继续；改善、退化、停滞来自实际输入指标的
   明确比较，不由日志文案或固定 fixture 结论冒充。base 始终是研究 incumbent；训练序列内部 best 与优于 base 的目标候选分开表示，
   允许诚实终止为 no-improvement。具体观察频率、比较策略/容差与扩大策略可配置并留给后续实测收敛，不预建自动调参平台。
5. **checkpoint 语义分层**：模型评价快照与完整恢复 checkpoint 分责；恢复点必须覆盖继续训练真正需要的状态，观察记录不可随大工件淘汰。
   保留/清理只作用于任务拥有的工件，先验证替代恢复点再淘汰 superseded 工件，不要求每 update 完整保存，也不允许删除唯一可恢复状态。
6. **validation 不是正式资格**：validation 可用于训练中观察、best 选择、停滞/退化判断和参数范围决策；不得进入梯度、改标签/split，亦不得冒充
   unseen、正式 M3-C2、产品 GO 或严格因果证明。unseen 全程物理不可达且不读取。
7. **fake 与云端事实严格区分**：本地 fixture/fake 只证明控制流、状态、指标、归档和恢复正确，不证明 A40/L40S 显存、吞吐、数值稳定、
   优化器适配、训练质量或 12 小时/15 USD 可行性；这些留给 WBS 中另行授权的真实环境任务。
8. **允许调试、修复与重跑**：先逐段打通并保留已验证进度，范围内普通 correctness、fixture、依赖、接口、脚本或测试问题自主窄修后重跑，
   不设机械次数限制，不因一次可修失败整组报废。不得删测试、弱化断言、扩大 fallback 或改冻结语义求绿；只有任务目标/硬边界冲突、
   授权外外部动作、资源边界或无法在本任务内解决的架构原则冲突才请示或形成 `REPLAN_REQUIRED` 候选。
9. **轻量资源与并行隔离**：不运行 Cargo、Docker、真实模型/GPU或云端动作，不写/清理 069 target，不复制模型资产，不扩共享 Python cache。
   Plan 080 可并行；两者对顶层 WBS 的修改按语义窄合并，081 不读取 080 未提交内容、不覆盖其四期状态。
10. **云端边界是合同而非授权**：A40 48GB 首选、L40S 48GB 备选、单卡不超过 12 小时和总费用不超过 15 USD 只作为后续任务输入；
    Plan 081 不查询库存、不创建/上传/计费，也不把 Plan 079 卷变成前置。若本地准备发现该边界原则上不可消费，必须诚实形成重规划候选。
11. **文档与结论归位**：WBS 只维护当前路线/顺序，COMPLETED 只在独立验收后记历史，plan 只记本任务状态，agent_log 精炼记实质执行/审查。
    不改写 Plan 060/066/073/075/079 历史，不在 README、plan 或日志复制后续路线。
12. **本地提交后停止**：执行者完成实现、必要文档、测试、自检和所有范围内变动后提交 081 task branch并保持 worktree clean；不得合并、
    推送、归档或删除 worktree。随后按下述唯一队列协议发送最终验收消息并停止会话。
13. **跨会话请示、批示与验收**：需要额外授权、出现计划外变数或确需裁决的不确定事项时，只使用下述用户指定的 `codex queue` 联系审查者；
    每条消息开头主动声明“我是 Plan 081 执行者”，发送后停止会话，不等待、不轮询、不重复发送。已在本计划授权内的普通修复/重跑不重复请示。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，按照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03a93-2aee-7421-8e52-e043ae26ffa4 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。
```

```text
需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。
```

```text
执行者最终完成任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<你的执行完成的汇报>”
其中<你的执行完成的汇报>就是你本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。
```

```text
执行者给审查者发送消息的时候，必须主动表明身份。
```

## 4. 软性建议

以下建议基于 `main@0d842e0` live code，只帮助执行者高效收敛，不固定 namespace、类/API、配置 schema、参数分组算法、保留算法、
观测频率、阈值或内部路线。执行者可以采用更简洁、优雅且与现有架构契合的等强方案，并在关键决策记录中说明有实质影响的偏离。

- 现有 `full_model_training/contract.py` 与 `plan066_contract.py` 把 stage/update/全参数/optimizer 细节写死，宜保留其历史 validator，
  在其外侧抽取真正中性的 checkpoint/data/receipt 基元，或建立一个小型连续训练 controller；不要把旧字段改成大量 optional 形成含混合同。
- `plan066_data.py` 已有 train 与 validation 类型隔离，`checkpoint.py` 已有完整模型、optimizer/scheduler/RNG、progress 与新进程恢复基元，
  `selection/metrics.py` 已有完整 operating curve 和逐 pair 结果。优先复用这些职责，不复用 Plan 073 的 Judge、selection lock 或 unseen 流程。
- 参数更新范围可先抽象为可序列化的 group/scope identity 与实际 trainable inventory，fake 用小型分层 scalar model 验证“初始部分更新→扩大→恢复”。
  未来真实层名、层数和扩大触发由 GPU commissioning/训练动态决定，本任务不猜答案。
- 改善/退化/停滞可以基于 base/previous/best 的少量透明比较规则；pair margin 建议保留 signed preferred-minus-dispreferred 原值和聚合，
  避免只留 win/loss 后无法诊断排序退化。base incumbent、训练序列内部 best 与 better-than-base candidate 宜用不同字段/状态表达；
  这里是工程控制信号，不需要构建统计显著性、因果归因或自动超参搜索平台。
- retention 可先以 manifest/metadata 驱动 base、best、latest 与明确的 turning-point 标签；同一工件可同时承担 best/latest，清理算法保持幂等即可，
  不需要数据库、registry、后台 GC、签名链或通用模型生命周期服务。
- focused 测试优先覆盖：连续多 update/observation、improve→stall/regress、参数范围扩大、checkpoint 后新实例续跑、best/latest/turning-point
  重合与淘汰、逐 pair margin 永久保留、validation 不进入梯度、旧 Plan 060/066 validator 不被放松。使用 tempfile 和 fake，不生成大工件。
- 既有回归按 test class/能力面定向选择；不要机械运行会从 mixed v8 重新构建 Plan 066 export 的整套测试。需要验证真实输入接缝时，
  从主物理根 canonical no-unseen bundle 只读加载 train+validation，并继续使用 fake model，不触碰权重或 unseen。
- 实施可按“中性 seam/合同 → fake 连续控制 → 质量观测 → checkpoint/retention/resume → 云端 handoff/WBS → 聚焦回归与审查”推进；
  每段普通问题边修边跑，完整闭环打通后再从干净临时 namespace 跑一轮最终轻量集成，不把调试 attempt 冒充最终证据。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-25：确认主工作区 clean `main@0d842e0f568791765eed4eced46674b55ae0106e`，领先 `origin/main` 8 个提交；
  Plan 069/074/078 等既有 worktree 保留，Plan 080 有自己的未合入分支和任务合同现场。
- 2026-08-25：从该基线创建
  `.claude/worktrees/081-publication-critic-local-training-readiness` / `worktree-081-publication-critic-local-training-readiness`。
- 2026-08-25：只读核对根规则、README、顶层/三期 WBS、plan 模板、Plan 060/066/073/075/079、相关日志、训练合同、checkpoint、
  validation metrics、测试入口与 ignored 边界；未读取 unseen 正文、`.env.local`、模型权重或 checkpoint 内容。
- 2026-08-25：确认现有能力与缺口：Plan 066 数据隔离/checkpoint/恢复、Plan 073 metrics 可复用，但 Plan 060/066 contract 固定
  C1/C2/C3 单次更新、全参数和 FlashAdamW；Plan 081 应保持历史 validator 并补连续控制/观察/保留 seam。
- 2026-08-25：独立合同审查发现“base incumbent / better-than-base candidate / no-improvement 与无需直接产品 GO”未显式交接的 P2；
  已窄修并复审 `ACCEPT`，无剩余 P1/P2。具体同口径比较策略/容差仍留给真实训练实测，未升级为固定实现路线。
- 2026-08-25：计划编制未运行 Python 测试、模型、Cargo、Docker、云资源或付费动作，未修改主工作区和其它 worktree。
- 2026-08-25：新增 Plan 081 专用 route/cloud 合同、typed train/validation identity、连续 update/observation controller、
  observation-driven scope expansion、评价快照/完整恢复 checkpoint 分层、保留选择与 fixture/fake 归档；Plan 060/066 历史合同未修改。
- 2026-08-25：从 canonical `final-01-extracted` 物理无 unseen bundle 只读核对 train 128/58 与 validation 55/26 接缝；仅计算小型
  identity，不读取 unseen、权重或 checkpoint。
- 2026-08-25：专用测试与 Plan 060/066/073 focused 回归共 17 项通过；源码 compile 5/5。内部独立审查发现的动态 scope、data cursor、
  typed train-only、same-cohort、staging、连续重放 attempt、公开构造校验等 P2 已逐项补回归并整改，等待指定审查者最终验收。
- 2026-08-25：指定审查提交 `3f69d41` 对实现提交 `f954d30` 报告 4 个 P2、无 P1，结论为整改后复验；问题均已确认存在，
  不构成 `REPLAN_REQUIRED`。
- 2026-08-25：完成 fail-closed step/checkpoint/retention 恢复、严格 training best 与稀疏扩层转折、train/validation cohort 隔离及
  显式非 JSON state codec 整改；Plan 081 24 项与精选历史回归合计 31/31 通过，三路定点复核及一轮全 diff 独立复核均未发现
  剩余或新增 P1/P2。
- 2026-08-25：整改复验提交 `a21d290` 对整改提交 `ea023e6` 报告 2 个相邻 P2、无 P1：新 checkpoint 在 prune/marker 前缺少
  绑定 reader 资格验证，discard tree 半删后无法幂等续清；均确认存在且不构成 `REPLAN_REQUIRED`。
- 2026-08-25：新增 checkpoint 通用恢复不变量读回资格检查，以及严格 task-owned prune tombstone 原子改名/续清；Plan 081 29 项与
  精选历史回归合计 36/36 通过。内部组合复核继续发现半删 snapshot 后旧 checkpoint 可恢复、多个 discard checkpoint 升序删除会
  暴露依赖已删旧 best 的 checkpoint 两个 P2；现按数值 chronology 从新到旧隐藏 discard checkpoint，再删除 snapshot，并补
  cp2/cp4/cp6 故障恢复回归。整改后两路定点复核与全 diff 复核均未发现剩余或新增 P1/P2。
- 2026-08-25：第三轮复验提交 `d7589c5` 报告 2 个 P2 与 1 个 P3、无 P1：checkpoint 资格尚未实际 load/restore adapter，首个
  checkpoint 前失败缺少同 store fresh attempt 路径，cloud handoff 必要项未精确冻结；均确认存在且不构成 `REPLAN_REQUIRED`。
- 2026-08-25：checkpoint 资格与 resume 未完成 marker 路径现均在 retention 前执行完整 adapter load/scope/state/cursor restore；首
  checkpoint 前失败可从原失败 controller 经 fresh exact-base 断言与 base observation 精确匹配进入新 generation；cloud 输入/输出清单
  按冻结 JSON 精确验证。Plan 081 31 项与 7 项精选历史回归合计 38/38 通过；两路定点与一轮全 diff 只读复核无剩余或新增 P1/P2。

### 当前工作

- 第三轮复验的 2 个 P2 与 1 个 P3 均已整改；本地门禁与 diff/生成物检查完成后提交，等待指定审查者再次复验。

### 本任务剩余步骤

- 按用户指定队列通知审查者复验并记录最终结论。

### 阻塞项

- 无计划级阻塞。若实现要求真实模型/GPU/云端、读取 unseen、扩大共享 cache、触碰并行任务现场或改变冻结模型/数据/路线边界，
  停止对应动作并通过指定队列请示。

### 当前验收状态

- `IMPLEMENTATION_COMPLETE / THIRD_REVIEW_REMEDIATED / FOCUSED_LOCAL_GATES_PASS / REACCEPTANCE_PENDING`。

### 交接边界

- 执行者从本地轻量实现开始；不得把计划编制时的源码调查、历史 Plan 060/066/073/079 证据或 fake 闭环冒充真实训练/质量结果。
- 额外授权、计划外变数、需要批示的不确定项和最终验收交接，只使用本计划指定的
  `codex queue --thread 01a03a93-2aee-7421-8e52-e043ae26ffa4`；每条消息主动声明 Plan 081 执行者身份，发送后停止会话，
  不等待、不轮询、不重复发送。
- 本任务完成后冻结本计划；后续工作只链接 WBS，不在本计划继续规划。合并、推送、分支归档和 worktree 清理等待用户另行批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 继续 exact 1.7B 和冻结 pair/input/v8，禁止 LoRA/QLoRA；部分参数直接更新为当前首选且可按动态扩大 | Plan 079 证明 4B base 无有效收益，Plan 075 只确认训练后退化而未定位单一根因；需要保留研究变量而非重复旧 recipe | 训练路线 | 已采纳 |
| 002 | 不继承 Plan 066 的固定 C1/C2/C3 单 update、全参数和 FlashAdamW 强制合同，也不预冻层数/LR/batch/update/optimizer | 旧组合技术可行但模型质量退化；本任务应准备可观察、可调整的训练控制而非提前猜定 recipe | route contract | 已采纳 |
| 003 | 保留 Plan 060/066 历史 validator，通过中性抽取或 Plan 081 薄层补能力 | 放松旧合同会改写历史，完全重建又会复制既有数据/checkpoint/评价能力 | 架构复用 | 已采纳 |
| 004 | 训练中质量观察复用现有 validation metrics，并永久保留逐 pair signed margin；不读取 unseen | 排序退化是当前直接风险，开发期需要早观察，但不能冒充正式 M3-C2/unseen | evaluation | 已采纳 |
| 005 | 区分评价快照与完整恢复 checkpoint，长期保留 base/best/latest/少量转折点和所有小型观察记录 | 支持恢复与诊断，同时避免每 update 永久保存完整权重 | artifact lifecycle | 已采纳 |
| 006 | 云端 handoff 只冻结 A40→L40S、单卡≤12h、总费用≤15 USD，Plan 079 卷非前置；Plan 081 不运行云端 | 把后续付费任务收敛为可消费边界，同时不把当前本地准备扩大成外部动作 | cloud boundary | 已采纳 |
| 007 | 所有 tracked 变更留在 081 worktree；当前无必须写主工作区 ignored 资产的事项 | fake/fixture 与 `/tmp` 足以证明本地控制闭环，避免碰并行重型现场和大型资产 | worktree/ignored | 已采纳 |
| 008 | 顶层/三期 WBS 只做三期窄同步，最终与 Plan 080 由后整合者基于最新 main 手工合并 | 两任务并行且都触及顶层 WBS，不能用旧文件覆盖另一方向进展 | docs/integration | 已采纳 |
| 009 | 普通问题自主修复重跑；只有原则冲突才候选 `REPLAN_REQUIRED`，终审聚焦高/中 correctness | 避免窄故障导致整组报废，也不引入复杂审计/可信/机器验收体系 | failure/review | 已采纳 |
| 010 | 请示、批示和最终验收只使用指定 Codex 跨会话队列，每条消息主动声明 Plan 081 执行者身份，发送后停止且不重复 | 满足用户指定的跨会话协作与唤醒方式 | coordination/handoff | 已采纳 |
| 011 | base 保持研究 incumbent，训练内部 best 只有同口径优于 base 才成为目标候选；不要求直接产品 GO | 防止把 least-bad checkpoint 误报为研究成功，同时避免在训练开发阶段提前要求产品资格 | selection/handoff | 已采纳 |
| 012 | Plan 081 使用专用薄层：typed train/validation identity、观测后显式扩大 scope、永久小观测与分层快照/checkpoint，并以持久 reservation 分配恢复 attempt | 旧 Plan 060/066 固定 recipe 不适合连续路线；新边界需避免夹带 holdout、静态预写扩层和同一 checkpoint 多次重放冲突 | local control/recovery | 已采纳 |
| 013 | post-update 任一失败都进入 `recovery_required` 并从完整 checkpoint 新 adapter 恢复；adapter 显式声明 state codec，retention 以原子 completion artifact 收口 | 模型更新无法由 controller 安全回滚；半提交不得原地重试，非 JSON optimizer/RNG 状态和 checkpoint prune 都需可验证恢复边界 | failure/recovery | 已采纳 |
| 014 | 新 checkpoint 只有经绑定 reader 读回并核对 controller/training/data cursor 后才能替代旧恢复点；已验证 discard 先原子改名为严格 prune tombstone，checkpoint 按数值 chronology 从新到旧隐藏后再删 snapshot | byte manifest 不等于可恢复；删除意图必须先与 live artifact 分离，中途失败时仍可见的旧 checkpoint 不得依赖已删除恢复点或 snapshot | checkpoint/retention | 已采纳 |
| 015 | checkpoint 替换旧锚前执行 adapter 级完整恢复资格；首 checkpoint 前失败只允许从原失败 controller 以 fresh exact-base 新 attempt 重启；cloud handoff 必要清单精确冻结 | reader 可解码不等于 adapter 可恢复；同 store base 是 write-once，重启必须证明 exact base 且不覆盖旧工件；必要交接项不可静默删改 | recovery/handoff | 已采纳 |
