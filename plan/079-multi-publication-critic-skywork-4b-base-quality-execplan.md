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
   只有两者都没有可用卡时才使用 RTX A5000。创建网络卷前必须用 RunPod MCP 重查 Secure Cloud 的 GPU、数据中心、卷类型、价格与库存，
   数据中心不受地域限制，但必须支持任务网络卷与所选 base GPU，不能因随意选址把卷锁在明显不合适的位置。模型、环境、输入与进度落在同一卷，
   使 Pod 不足或故障时可在该数据中心重建/切换 Pod；不得借此并行开多 Pod 或复制多份计费卷。
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
- 数据中心选择软性优先满足：Secure Cloud、支持网络卷、当时有 RTX 4090，且同中心也有或近期可见 RTX 6000 Ada 48GB。
  4090 与 RTX 6000 Ada 分别归入 RunPod `ADA_24` / `ADA_48_PRO` pool、同属 Ada 架构；这能让未来另行授权的微调任务继续挂同一卷并
  减少环境差异。这只是选址偏好，
  不把 RTX 6000 Ada、微调、费用或训练动作带入 Plan 079。若执行时没有双卡交集，按本计划 base GPU 顺序选择可用中心并记录取舍，
  不为等待理想中心无限消耗预算。
- 当前 MCP 候选只作执行前参考：`US-WA-1` 支持 Standard 卷且当前见 RTX 6000 Ada；`EU-RO-1`、`EUR-IS-1`、`US-IL-1`、
  `US-TX-3` 支持 Standard 卷且当前见 RTX 4090。规划快照没有同时显示两种 Ada GPU 的中心，执行者必须重查，不能把该列表当库存锁。
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
- 2026-08-25T16:20:09Z：RunPod MCP Secure Cloud/POD 实时快照显示：RTX 4090 24GB 为 LOW、参考价 `$0.74/h`，支持卷的可用中心为
  `EU-RO-1`、`EUR-IS-1`、`US-IL-1`、`US-TX-3`；RTX 6000 Ada 48GB 的 detail 为 LOW、参考价 `$0.84/h`，只返回
  `US-WA-1`（Standard 卷），但紧邻的 catalog 查询曾返回 NONE，说明库存高度易变。RTX 3090 24GB 聚合为 LOW、`$0.50/h`，当时未返回
  具体中心；RTX A5000 24GB 为 NONE、`$0.27/h`。规划时没有 4090 与 RTX 6000 Ada 的实时中心交集，执行前必须通过 MCP 重新选择。
- 2026-08-25：A5000 末位备选、实时候选中心和 4090/RTX 6000 Ada 同中心软偏好经独立复审 `ACCEPT`；未引入下游训练授权、
  多卡运行、库存保证或新的 P1/P2/P3 finding。

### 当前工作

- `PLANNED / REVIEWED / NOT EXECUTED`：execplan 与三期子 WBS 当前入口已完成并通过成稿复审，待本分支提交后交给执行者实施。

### 本任务剩余步骤

- 兼容与复用闭合：确定两分片模型身份、backend、validation、metrics、archive 的最小适配，完成直接相关测试。
- 云端 commissioning：实时复核数据中心候选，创建同数据中心网络卷与单张 4090/3090/A5000 Pod，完整打通下载、核验、55 条评价、
  聚合、归档和回传。
- 冻结与正式运行：冻结全部身份，从 clean source 和空 namespace 完整运行唯一正式轮并独立复算。
- 判定、自检与止费：形成三态结论和精炼证据，释放 Pod，保留并报告网络卷，提交 clean task branch并交计划制定者独立验收。

### 阻塞项

- 当前无代码或路线阻塞。真实执行需要执行者收到随本计划提供的一次性 RunPod/HF/上传/预算授权，并使用项目既有安全凭据入口。

### 当前验收状态

- `PLANNED / IMPLEMENTATION NOT STARTED`：未修改实现、未运行测试、未创建云资源、未产生费用、未下载/加载真实模型。

### 交接边界

- 执行者按本计划与一次性授权完成实现、云端运行、结果、自检和 task branch 提交；计划制定者随后执行唯一一次独立验收。
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
| 008 | base GPU 顺序为 4090 → 3090 → A5000；选址软性优先同中心可用 4090 与 RTX 6000 Ada，但执行时按 MCP 实时库存决定 | 4090 足够完成 base，A5000 只作末位兜底；Ada 同代和同卷可降低未来另立微调任务的迁移成本，但当前无实时双卡中心交集 | RunPod 选卡、数据中心与卷 | 已采纳 |
