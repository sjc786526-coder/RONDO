# Plan 079：Publication Critic Skywork 4B 云端基座质量测评 ExecPlan

> 本计划是 Plan 079 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、模型或数据身份、评价语义、质量门、预算或原则边界，应暂停执行并请求用户确认；普通环境、依赖、下载、连接、
> OOM、进程、归档、launcher、测试与局部兼容问题由执行者在范围和预算内自主修复、续跑或重跑。
> 本计划只描述 Plan 079；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

在保持 Publication Critic 已冻结产品输入、validation、pair 与评价思想不变的前提下，于单张 24GB RunPod RTX 4090、RTX 3090
或末位备选 RTX A5000 上，
对原始 BF16
`Skywork/Skywork-Reward-V2-Qwen3-4B@fd958fef475f323f4e6b195930e3dd918485c668`
完成一次有界、可复算的正式基座质量测评，判断更大同家族基座是否达到既有发布质量门。

任务必须形成以下一种诚实终态：

- `4B_BASE_QUALITY_GO`：完整有效正式轮在同一 operating point 满足全部既有发布质量门；
- `4B_BASE_QUALITY_NO_GO`：完整有效正式轮证明不存在满足全部门限的 operating point；
- `INCONCLUSIVE`：在 15 USD 总预算内，基础设施或无法闭合的兼容问题使正式结果无效或不完整。

取得可靠终态就是任务成功，不要求结果必须为 GO。`4B_BASE_QUALITY_GO` 只产生后续任务可评估的云端 BF16 候选，
不直接解锁 M3-D，不释放 unseen-test，也不授予量化、本地部署或产品启用资格。

### 完成/验收标准

- [ ] 冻结并记录 exact Hugging Face repo/revision、该 revision 的完整官方快照文件集合、两份 safetensors shard 与 index、
      config/tokenizer/chat template/README、逐文件身份、Apache-2.0 license、Transformers 类别和实际运行身份；不跟随浮动 revision，
      不把单分片 1.7B 身份冒充 4B 身份。
- [ ] 评价后端能正确加载、核验并消费官方两分片快照，输出一列有限 scalar；职责契合时扩展既有模型制品能力，强行复用会扭曲
      三候选或单文件语义时可增加架构契合的 4B base 专用入口，但不得复制第二套 render、scoring、数据或评价体系。
- [ ] 继续使用现有 typed `PublicationPacket`、canonical render、16,384 context 与既有溢出规则、scalar head、`logits[:,0]`、
      higher-is-better 方向和既有投影；不得改变产品可见输入或评价含义。
- [ ] 正式数据只来自物理不含 unseen-test 的既有冻结 v8 train+validation bundle；validation 精确覆盖 55 条 candidate、
      19 个 boundary pair 和 7 个 within-PASS pair，不重新生成、修改、重标或重新切分数据。
- [ ] 不重新调用任何 Judge；只把 Plan 073 已验收的冻结标签与异构 Judge 结论作为历史解释背景，不把历史 Judge 输出改写成新标签。
- [ ] 在正式冻结前，commissioning 完整打通一次 exact 模型下载与核验、加载、render、55 条打分、聚合、归档和安全回传。
      commissioning 可保留已验证进度并从未打通处自主修复，但其输出不得拼接或升格为正式结果。
- [ ] commissioning 完整成功后，冻结 tracked source、模型、输入 bundle、依赖、评价程序、dtype、GPU 型号与其它结果相关运行配置；
      从 clean source 与新的空正式 namespace 完整运行一轮，只有该轮可形成正式质量结论。每个 attempt 的 Pod ID/attempt ID 如实记录，
      但不冒充跨重跑必须相同的结果身份；纯云平台/网络中断时可在同数据中心、同网络卷、同 GPU 型号和同冻结配置的新 Pod 上，从另一个
      空正式 namespace 重跑。GPU 型号或其它结果相关身份改变后，先重做受影响 commissioning 再重新冻结。
- [ ] 唯一正式轮保存并可独立重算：55 条有效 raw/projected score 与 typed failure、raw score 分布、完整 operating curve、
      False PASS、False REWRITE、balanced accuracy、ROC AUC、boundary/within-PASS pair 结果、延迟、显存和实际费用。
- [ ] `4B_BASE_QUALITY_GO` 只在 typed failure 为 0，且同一 operating point 同时满足 False PASS ≤ `0.25`、
      False REWRITE ≤ `0.35`、balanced accuracy ≥ `0.75`、ROC AUC ≥ `0.80`、boundary strict win ≥ `0.70` 时成立；
      within-PASS 如实报告但不追加事后门限。完整有效的质量失败不得因结果不理想而重跑、调门或换口径。
- [ ] 与 Plan 073 的历史 exact 1.7B base 做同口径差异说明，引用已验收历史结果而不重新加载或运行 1.7B；不同硬件的延迟/显存只作
      清楚标注的背景，不作伪精确优劣推断。
- [ ] 执行者完成直接受影响的 pure/fake/focused tests、真实云端 commissioning、唯一正式轮复算、自检和 clean task branch 提交；
      随后由计划制定者完成一次独立验收，普通 finding 可退回执行者窄修并复验。Plan 079 不修改 Rust，因而不运行 Cargo；
      也不运行 Docker、真实本地模型或全仓测试。未运行、skip、fake 与真实云端证据分别表述。
- [ ] 正式结果安全回传项目专用 ignored namespace 后停止计算并删除/释放任务 Pod，确认 GPU 持续费用为 0。任务专属网络卷按用户补充要求
      保留在同一数据中心，不得由执行者删除；交付时报告卷 ID、数据中心、容量/占用、费率、累计费用与持续计费状态，等待用户另行批准释放。
- [ ] 更新本计划当前状态、一份精炼 `agent_log` 和三期子 WBS 的准确建议 delta；提交 clean Plan 079 task branch并交计划制定者独立验收。
      执行者不合并 `main`、不推送、不归档分支、不删除 worktree，也不以旧基线改写顶层 WBS 或 COMPLETED。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 中与多分片快照身份、4B backend、冻结 validation 消费、质量聚合、归档、运行入口和结果投影直接相关的能力。
  可以复用或窄扩 Plan 054/073 设施，也可在职责更清晰时新增 Plan 079 专用模块或 namespace。
- `eval/tests/test_publication_critic_*` 及必要的小型 fixture；新增测试只覆盖本任务新增或改变的模型身份、加载、评价与归档行为。
- `eval/model-locks/`、`eval/environments/` 或 `training/publication-critic-plan079/` 下确有必要的轻量 model/dependency/run 配置与云端入口，
  以及职责相符的既有 RunPod 辅助设施；由现有目录职责决定落点，不提交权重、环境、缓存、raw score、私有输入副本或大体积结果。
- `eval/results/publication-critic/` 下可复算且体积合规的正式聚合结果/说明、本计划“当前状态/关键决策记录”、一份精炼 Plan 079 日志，
  以及执行完成后提供给整合者的三期子 WBS 窄更新建议。
- 主物理仓库根 ignored `eval-data/publication-critic/plan079/` 及确有必要的任务专用 env/cache，用于 bundle、commissioning、formal、
  回传、费用与资源终态。工作树不共享该目录，因此这些内容可以按本节直接在主物理根产生并只归本任务所有。
- 只读使用 Plan 054/066/071/073 的 tracked 实现、冻结 train+validation bundle、历史 1.7B 正式结果和必要 ignored 证据；
  上传运行所需的项目代码与物理不含 unseen 的 bundle。
- 公开只读下载上述 exact Hugging Face revision；在 RunPod 创建、运行、重建、停止和删除单张 4090/3090/A5000 Pod，创建并挂载一个
  与 Pod 同数据中心的任务专属网络卷，在 15 USD 总账内自主修复基础设施并重跑。

### 不允许修改

- 冻结 v8 数据正文、label、pair、split、review、manifest 或 Plan 073 的历史结果、Judge 结论和质量门。
- Publication Critic 产品输入模板、typed packet、产品默认、Plan 055/057 稳定产品语义、selection lock、unseen release、M3-D 或产品启用状态。
- 任何模型权重；不训练、继续训练、量化、转换、蒸馏或生成新候选，不重新运行 1.7B/C1/C2/C3。
- `multidev/` 全部文件，以及 Plan 077/078 worktree、未提交文件、运行 namespace、Durable Session、app-server、TUI 或其任务资源。
  若真实证据显示必须改变 Rust/产品接缝才能完成任务，这属于原则性扩围，应暂停并请求用户协调，不在当前授权内自行进入。
- 顶层 `doc/WBS.md`、`doc/WBS-COMPLETED.md`、README 或并行任务共享文档；最终整合者在用户批准后基于最新 main 处理。
- 其它云平台、付费 API、HF 远端写入、发布、训练、CI/PR、任务分支 push、合并/rebase main、分支归档或 worktree 删除。
- 未经用户单独批准删除 Plan 079 网络卷；也不得删除或清理来源不明的 Pod、卷、镜像、缓存、工件或既有 ignored 资产。

### 不允许读取/查看

- v8 unseen-test 的正文、render、score、Judge 输入/输出或任何能释放其内容的混合资产；正式输入应让云端进程物理上拿不到 unseen。
- `.env.local` 内容、token、API key、access key、secret、私钥、密码或个人配置。只可按根 `AGENTS.md` 静默检查文件与所需变量，
  通过既有安全入口只向目标子进程注入必要值，不得 source、打印、复制、上传或记录凭据。
- 与任务无关的项目外个人文件、其他仓库、私有数据、真实 publication/transcript/private reasoning 或来源不明 ignored 资产。

### Git-ignored 与物理根边界

tracked 代码、测试、计划、配置和日志只在
`/home/sjc/desktop/RONDO/.claude/worktrees/079-publication-critic-skywork-4b-base-quality/` 修改并提交，主工作区不产生 tracked 修改。

linked worktree 不共享主根 ignored `eval-data/`。因此运行输入投影、回传原始结果、费用/资源记录和必要 env/cache 可直接落在主物理根
`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan079/`。交接时逐项报告实际创建/修改的 ignored 路径、大小、权限与保留状态；
不复制旧大型模型资产，不把目录存在本身当作正式结果，也不建设额外资产 registry、签名链或审计平台。

## 3. 硬约束

以下约束只冻结结果可信所必需的模型/输入/评价身份、预算、正式轮和并行安全，不锁死模块布局、batch、依赖安装、launcher 或调试策略。

1. **唯一模型身份。** 正式对象只能是指定 repo 的 exact commit 和原始 BF16 官方快照；完整文件集合、分片 index、实际 shard、
   tokenizer/config/license 与依赖身份必须核验并归档。不能改用浮动 main、镜像模型、单文件重打包、量化或转换件。
2. **输入与分数语义不变。** 只复用冻结 packet→render、exact 模型 tokenizer 下的既有 tokenization/window/overflow 合同、
   scalar→projection 和 higher-is-better 方向；模型尺寸、分片加载或云端 runtime 差异不得改变 16,384 window、padding、
   `logits[:,0]` 或标签/pair/指标定义。若 4B tokenizer 资产并非与 1.7B byte-identical，应按同一规则重算 Plan 079 token/omission 事实，
   不得沿用不相符的旧 census，也不得借此改变 packet/render/overflow 语义。
3. **unseen 与 Judge 封闭。** Plan 079 全程只消费物理无 unseen 的 train+validation bundle，不读取混合 v8 来“过滤 validation”；
   不调用 Judge、不释放 unseen，也不因 GO 提前进入 selection、本地资格或 M3-D。
4. **先完整打通，再正式冻结。** commissioning 可保留进度、局部续跑并自由更换调试 namespace；只有完整 55 条端到端成功后才能冻结。
   formal 必须来自 clean tracked source 和空 namespace，不能拼接 commissioning、旧 Plan 073 raw 或多个 formal attempt。
5. **修复与重跑按原因处理。** 环境、下载、网络、Pod、OOM、依赖、进程、归档和局部兼容问题可在预算内自主修复并重试，不设机械次数；
   纯基础设施中断可在同数据中心/卷、同 GPU 型号和同冻结配置的新 Pod 上，用新空 formal namespace 重跑。有效完整质量失败不得重跑求绿；
   源码、模型、输入、dtype/GPU 型号、其它结果相关配置或评价语义实质改变后，原 formal 失效并重做受影响 commissioning。
6. **15 USD 总账与保留卷。** 从 Plan 079 云资源创建到执行者交付期间，Pod、GPU、网络卷、存储与其它全部实际费用累计不得超过 15 USD；
   不要求花完，接近上限应留出回传和 Pod 止费余量，达到上限立即停止 Pod 与新增计算并形成 `INCONCLUSIVE`（若尚无有效正式结果）。交付时
   必须报告累计额、卷费率、剩余 headroom 和按当前费率触及 15 USD 的预计时间。用户又明确要求卷在交付后继续保留且删除须单独批准，
   因而执行者不得为守 lifetime 预算自行删除卷，也不得声称可同时无限保留卷并永久保证总账不越线；交付后的持续卷费是用户保留指令产生的
   外部持续费用，后续由用户在触线前另行决定删除或调整预算。
7. **单资源、GPU 顺序与可迁移性。** 同时最多运行一张 24GB GPU；优先 RTX 4090，4090 当时不可用或价格不合适时改选 RTX 3090，
   只有两者都没有可用卡时才使用 RTX A5000。网络卷绑定数据中心，因此选址先依据 RunPod 的硬件支持关系构造候选集，而不是把某一时刻的
   `HIGH/MEDIUM/LOW/NONE` 库存当作中心支持关系：网络卷候选限定为支持 Secure Cloud、Standard 网络卷、RTX 4090 与 RTX 6000 Ada 的
   共同中心，当前已确认 `US-IL-1`；使用 3090/A5000 备选时还须确认候选中心支持该卡。创建网络卷前再用 RunPod MCP 更新该支持交集，并仅以
   实时库存、价格和可用 CUDA 主机版本决定候选集内的实际落点。模型、环境、输入与进度落在同一卷，使 Pod 不足或故障时可在该数据中心
   重建/切换 Pod；不得借此并行开多 Pod 或复制多份计费卷。
8. **本地重型资源零占用。** 本任务不运行本地重型 Cargo、Docker 或真实本地模型，不占 Plan 077/078 的资源槽；意外需要时先等待资源窗口，
   仍须遵守根级门禁且不得触碰它们的 worktree/现场。本任务云 GPU 可与其非冲突开发并行，但大文件传输注意本地网络和磁盘压力。
9. **正式结果完整且可复算。** typed failure 或缺分数使正式质量结论无效；完整 operating curve 和门限判断必须从正式 55 行及冻结 pair 重建，
   tracked 摘要与 ignored raw 明确绑定。`NO_GO` 不是基础设施失败，`INCONCLUSIVE` 也不能冒充模型质量失败。
10. **秘密与外部状态最小化。** 只使用任务已授权的 RunPod/HF 入口，凭据不进入云端 bundle、命令输出、日志或 Git；不上传 unseen、密钥、
    旧模型工件或无关项目文件。只删除任务明确创建的 Pod；网络卷删除权保留给用户。
11. **工作树隔离与本地交付。** Plan 079 只拥有本计划范围内的 tracked/ignored 资产。完成后只提交 task branch 并保持 worktree clean；
    合并、推送、主线文档整合、分支归档和 worktree 清理由用户后续批准。

## 4. 软性建议

以下是基于当前代码的高性价比起点，不是固定路线。执行者可依据代码、云端实测和测试结果采用更优策略，并记录关键取舍。

- 优先复用 Plan 073 `selection/dataset_source.py` 的无 unseen validation 来源、`selection/metrics.py` 的完整 operating curve/质量指标，
  以及现有 render/tokenization/backend/archive 基元；Plan 073 的三候选 freeze、Judge、selection lock 与 unseen confirmation 不属于本任务。
- 现有 `SkyworkBackend` 的模型加载/finite scalar 逻辑已通过 `AutoModelForSequenceClassification.from_pretrained(local snapshot)` 工作，
  Transformers 原生支持 index+shard；其本地 watchdog lease 生命周期不适合原样搬到 RunPod。真正需要调整的可能主要是云端 lifecycle、
  快照 identity、硬编码单 `model.safetensors` 的 runner/artifact 假设和 4B 运行投影。若泛化旧入口会扭曲历史，建立小型
  `base_quality`/Plan 079 专用入口通常更干净。
- commissioning 可按“元数据/下载核验 → load 与单条 → 小 batch → 55 条完整 scoring → metrics/archive/recompute → 回传”递进，
  每阶段在网络卷保留已验证进度；在看过完整链路的运行时间和显存后再确定 formal batch 与 GPU，避免过早冻结。
- 数据中心选择软性优先满足：Secure Cloud、支持 Standard 网络卷，并在硬件目录/主机支持关系中同时支持 RTX 4090 与 RTX 6000 Ada 48GB；
  该支持交集不随某一时刻的卡库存而定义。
  4090 与 RTX 6000 Ada 分别归入 RunPod `ADA_24` / `ADA_48_PRO` pool、同属 Ada 架构；这能让未来另行授权的微调任务继续挂同一卷并
  减少环境差异。这只是选址偏好，
  不把 RTX 6000 Ada、微调、费用或训练动作带入 Plan 079。当前已确认的共同支持候选为 `US-IL-1`：支持 Standard 网络卷以及两种 Ada GPU，
  两者当前共同可用的 CUDA 主机版本为 13.0。执行者在创建卷前应重新查询支持交集，允许发现并采用其它满足条件的中心；随后才在这些候选中
  查询实时库存和价格。若交集候选暂时无卡，可在预算允许范围内重查或按本计划 base GPU 顺序评估候选中心支持的备选卡，不把瞬时无库存误判为
  中心不支持，也不为等待理想库存无限消耗预算。
- 网络卷选择满足 exact 8.04GB BF16 权重、HF cache、Python/Transformers 环境、冻结 bundle/code、commissioning/formal、base raw 结果
  与回传余量的最小实用容量即可；记录实际规格和费率，不在 Plan 079 预分配未来 checkpoint 容量。后续获批任务可在保留同一卷 ID 的前提下
  扩容并写入训练 checkpoint/恢复状态。Pod 重建时复用同一数据中心、同一卷和已核验文件，避免重复下载。
- 云端运行入口可按职责复用 Plan 060/066 的 runbook、readiness、传输和费用记录方式，但不必继承 H100、训练候选、optimizer、双候选或旧卷清理语义。
- pure tests 优先覆盖两分片文件集合/index 核验、单分片缺失/漂移拒绝、55 行完整性、门限边界、typed failure、commissioning/formal namespace
  隔离与结果重算；mock shard 内容即可，不把多 GB 权重或真实 GPU变成普通单测 fixture。
- 正式 tracked 报告保持精炼：模型/源码/输入/依赖/运行身份、完整指标与 curve 摘要、1.7B 历史同口径表、成本/资源终态和三态结论；
  逐行 raw 与大日志留在 ignored Plan 079 namespace，不复制历史 Plan 073 长报告。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-25：确认主工作区 `main@b077462f03a36c9c57c67db08b69b59f26cdd904` clean，领先 `origin/main@4a9fb17` 9 个提交；
  Plan 077/078 worktree 存在且保持不可触碰。
- 2026-08-25：从该 clean main 创建
  `.claude/worktrees/079-publication-critic-skywork-4b-base-quality` / `worktree-079-publication-critic-skywork-4b-base-quality`。
- 2026-08-25：只读核对根规范、README、顶层/三期 WBS、plan 模板、Plan 054/066/071/073/075、相关最终日志、现有 Publication Critic
  Python 设施、冻结 v8 与主物理根 ignored 资产边界。
- 2026-08-25：用 Hugging Face 公共只读元数据确认指定 revision 精确解析为同一 commit，模型为
  `Qwen3ForSequenceClassification`/text-classification、4,022,470,656 个 BF16 参数，官方权重为两 shard + index、index 声明总权重
  `8,044,941,312` bytes，license 为 Apache-2.0；未下载权重、未登录或写入 HF。
- 2026-08-25：计划已吸收用户补充的网络卷要求：Pod 交付时释放，网络卷保留并等待用户另行批准删除。
- 2026-08-25：独立成稿审查发现并闭合预算/保留卷口径、formal 重跑身份、`multidev/` 范围和独立验收职责四项问题；
  复审结论 `ACCEPT`，无剩余 P1/P2/P3 correctness、scope 或可执行性 finding。
- 2026-08-25：RunPod 支持交集核对确认 `US-IL-1` 同时支持 RTX 4090、RTX 6000 Ada 与 Standard 网络卷；当时两种卡均为 LOW，
  共同 CUDA 主机版本为 13.0，Secure Cloud 参考价分别为 `$0.74/h`、`$0.84/h`。计划据此将“数据中心支持交集”和“创建时实时库存”分层：
  前者定义卷的候选落点，后者只决定候选中的实际部署，执行前仍须重查两者。
- 2026-08-25：A5000 末位备选和 4090/RTX 6000 Ada 同中心软偏好未引入下游训练授权、多卡运行或库存保证。
- 2026-08-25：实现并验证 Plan 079 专用 `base_quality` 入口、两分片 snapshot/model lock、exact source tree、Plan 066 bundle 派生
  validation release、runtime receipt、commissioning/formal gate、write-once archive、独立复算和首个完整正式结果 authority；吸收
  `3bb1253` 独立审查的三项 P1，commissioning 不再形成正式结论、freeze/run 均重建并比对 release、新 source tar 不再执行旧 source root。
- 2026-08-25：在 `US-IL-1` 创建 20 GB Standard 卷 `v1us0nmk0p` 和单张 Secure Cloud RTX 4090 Pod
  `iocp8k8w6zvh4s`（`$0.74/h`、CUDA host 12.8），下载并逐文件核验 exact 官方两分片 BF16 snapshot。镜像遗留
  `HF_HUB_ENABLE_HF_TRANSFER=1` 与冻结依赖不匹配时，专用 bootstrap 显式隔离该开关并从保留缓存续跑成功。
- 2026-08-25：commissioning `plan079-commissioning-20260825T175440Z-610d880-r1` 从 55/55、零 typed failure 的完整链路形成
  `COMMISSIONING_COMPLETE`，本地独立复算与云端结果逐字节一致；随后从 clean `610d880312c8ee9c98c28740f8b0b62c4fafb65f`
  和新空 namespace 运行唯一正式轮 `plan079-formal-20260825T175912Z-610d880-r1`。
- 2026-08-25：唯一正式轮 55/55、零 typed failure，形成有效 `4B_BASE_QUALITY_NO_GO`：无 admissible operating point，ROC AUC
  `0.6218487395 < 0.80`，boundary strict win `13/19 = 0.6842105263 < 0.70`；selected point 的 False PASS 为
  `12/21 = 0.5714285714`、False REWRITE `4/34 = 0.1176470588`、balanced accuracy `0.6554621849`。formal raw/result 已安全
  回传，第二次本地复算与正式 `result.json` 逐字节一致，未因 NO-GO 重跑。
- 2026-08-25：Pod 已删除并按 exact name 复核为零，持续 GPU 费用为 0；卷 `v1us0nmk0p` 按授权保留，容量 20 GB，删除前
  Plan 079 task root 用量 8,242,665,809 bytes。`2026-08-25T18:14:05Z` 平台已结算卷费 `$0.00194444449`，Pod 账单明细仍延迟；按
  1,535 秒 Pod 上界、两小时卷费和容器盘费保守计总额不超过 `$0.3207`，至少剩 `$14.6793`，卷单独持续计费约 7,549 小时 / 314.5 天
  后触及上限。正式摘要已投影到 `eval/results/publication-critic/`，完整 raw 与运行 receipts 保留在物理根 ignored
  `eval-data/publication-critic/plan079/`。
- 2026-08-25：把审查者提供的库存监控器及 focused test 纳入本任务；它只处理运行时参数化的 stock poll/create 与 exact-name
  uncertain-create reconciliation，不接管预算、价格、卷验收、readiness 或资源启停删除。
- 2026-08-25：正式结果已完整落盘且 authority 已存在后，执行者最终只读复核发现“final evidence 已写、authority 尚未写”崩溃窗口；
  窄化修复为：其它 formal namespace 遇到待协调 evidence 时 fail-closed，同一 run 可验证恢复并幂等补 claim，既有 authority 允许同 run
  只读恢复但继续拒绝不同 run。该修复只改变归档崩溃恢复，不改变冻结评分、输入、指标或既有正式结果，因而未重跑有效 NO-GO。
- 2026-08-25：首次独立验收在 `c705777` 发现合法但不完整的 formal `INCONCLUSIVE` 也被待认领 gate 阻断新空 namespace；执行者确认并
  窄修为由 archive 发现候选、runner 使用候选自带 run-spec/release/scores/runtime/result 做完整既有合同验证，仅对合法
  `INCONCLUSIVE / valid_full_quality_run=false` 放行重跑，缺失、漂移或语义含混的 evidence 继续 fail-closed。修复不改变正式评分，未重跑云端。
- 2026-08-25：执行期间一次过宽的只读检索机械遍历到禁止的 mixed v8 路径并输出普通行；未筛选、使用、评分或上传任何该内容，
  随即停止触碰该路径。正式输入和云端资产始终只来自物理不含 unseen-test 的 Plan 066 train+validation bundle。

### 当前工作

- `ACCEPTED / 4B_BASE_QUALITY_NO_GO / COMPLETE`：首次独立验收唯一 P2 已在 `d29e857` 窄修并通过复验；实现、真实运行、
  正式 NO-GO、独立复算、止费、记录和 task branch 提交均已完成。

### 本任务剩余步骤

- 无。分支合并、主线 WBS/WBS-COMPLETED 整合、推送、分支归档、worktree 清理和网络卷删除等待用户批准后基于届时干净 `main`
  处理；后续模型、训练、量化、本地部署或 M3-D 不属于本计划。

### 阻塞项

- 当前无任务内阻塞。保留卷继续按 Standard 费率计费，删除须用户另行批准。

### 当前验收状态

- `ACCEPTED / 4B_BASE_QUALITY_NO_GO / TASK COMPLETE`：正式结果有效且已独立复算，首次验收 finding 已通过复验；Pod 已删除，卷按用户
  指令保留。本状态不冒充 main 整合、后继任务授权或网络卷删除许可。

### 交接边界

- 执行者按本计划与一次性授权完成实现、云端运行、结果、自检和 task branch 提交；计划制定者已完成独立验收与整改复验。
- 三种终态都在本任务内收口；量化、本地资格、训练、换模型、产品启用与 M3-D 均由 WBS 后续另行立项，本计划不安排。
- 任务完成后冻结本计划；主线 WBS/WBS-COMPLETED、合并、推送、分支归档、worktree 清理和网络卷删除均等待用户后续批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 用户以 Plan 079 的 exact 4B base 云端质量测评取代 Plan 076 作为三期当前入口 | 先验证同家族更大基座是否具备质量信号，比在已失败 1.7B 底模上立即诊断训练动态更直接 | 三期当前工作包、WBS | 已采纳 |
| 002 | 冻结输入/评价核心，不冻结具体模块布局；职责扭曲时允许 Plan 079 专用入口 | 复用 render/metrics 有益，强行继承三候选、Judge、unseen 和单文件假设会增加耦合 | 实现架构 | 已采纳 |
| 003 | 正式对象只使用 exact 4B 官方 BF16 两分片快照 | 任务要回答基座质量，量化、转换或重打包会混入额外变量 | 模型与运行身份 | 已采纳 |
| 004 | validation 继续由 Plan 066 物理无 unseen 的 train+validation bundle 提供 | 该边界已经 Plan 073 独立验收，可复用而无需新建数据体系 | 输入与 unseen 隔离 | 已采纳 |
| 005 | commissioning 必须先完整覆盖 55 条端到端链路，之后才冻结并从空 namespace 做正式轮 | 避免在正式阶段才暴露可修复问题、反复报废整组结果 | 运行阶段、正式证据 | 已采纳 |
| 006 | Pod 交付时释放；同数据中心任务网络卷保留，删除须用户另行批准；15 USD 统计到执行者交付并报告保留卷预计触线时间 | 用户要求利用持久卷支持同数据中心 Pod 灵活切换并保留删除决定权；无限保留与 lifetime 硬上限不能由执行者同时保证 | RunPod 生命周期、预算与费用回执 | 已采纳 |
| 007 | Plan 079 分支只窄更新三期子 WBS；顶层 WBS、COMPLETED 与最终整合留给届时最新 main | Plan 077/078 并行推进，共享文档不能由旧基线覆盖 | 文档与交付 | 已采纳 |
| 008 | base GPU 顺序为 4090 → 3090 → A5000；数据中心候选先按 4090、RTX 6000 Ada 与 Standard 卷的支持交集确定，再以实时库存选实际落点；当前确认 `US-IL-1` | 4090 足够完成 base，A5000 只作末位兜底；支持关系决定长期卷落点，瞬时库存只决定何时能部署；Ada 同代和同卷可降低未来另立微调任务的迁移成本 | RunPod 选卡、数据中心与卷 | 已采纳 |
| 009 | 采用 Plan 079 专用薄入口复用既有 packet/render/scoring/metrics/bundle 基元，并对 exact source、release、runtime、commissioning 和首个完整 formal 结果增加任务内 fail-closed gate | 旧三候选、Judge、单分片与本地 watchdog 生命周期不适合直接继承；专用入口避免语义扭曲且不复制评价体系 | 评价架构、云端生命周期与正式证据 | 已实施 |
| 010 | 唯一有效正式结果为 `4B_BASE_QUALITY_NO_GO`，不因结果不理想重跑；4B 不获得训练、量化、本地部署、产品启用或 M3-D 资格 | 55 行完整正式证据没有可同时满足冻结门限的 operating point，属于模型质量失败而非基础设施失败 | Plan 079 终态与三期交接 | 已采纳 |
| 011 | 库存 monitor 作为可选、参数化的 poll/create 辅助设施纳入任务，但预算/价格/卷/readiness/启停删除仍由执行 controller 管理 | 抢卡需要低延迟自动化，资源资格和生命周期门禁职责不同，不应耦合进同一脚本 | 后续 RunPod 抢卡复用 | 已实施 |
