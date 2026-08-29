# RONDO 长程规划（WBS）

最后更新：2026-08-29（方向 3 Publication Critic 三期在 Plan 097 双 backend 工程闭环后正式进入质量重构路线；后续固定串行为
“任务合同重构 → v8 后继数据改造与有限扩充 → 一次主方案训练 → 模型资格验收与横评”。Plan 098 已为前两个工作包建立同一两阶段
ExecPlan；Plan 098 的任务合同、v9/v10/qualification、formal decoder、pair-aware margin selection 与 direct-dependency identity 已全部
通过最终复验并冻结完成。工作包三 Plan 099 阶段 A 已通过独立验收且阶段 B 已获授权；首个 exact Pod 在模型下载前暴露 FUSE
runtime-control seam，随后因 host guard 核验失败按安全止费授权删除。当前等待审查者批示 replacement Pod 的 exact 控制路径和稳定 guard 启动方式。
Plan 097 的 `M3_D_DUAL_BACKEND_ENGINEERING_PASS / FINAL_REVIEW_ACCEPTED / INTEGRATED / PUSHED`、Plan 096 的
`CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`、Plan 095 最终验收、Plan 094 有效负向研究终态和 Plan 093 Linux 全 workspace 正确性基线
均保持有效；新路线不自动解锁产品质量、默认启用或生产）

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段指针、跨方向关系、
稳定工程边界和授权门；已完成成果与验收见 `doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，执行细节见
`agent_log/`，研究与审计材料只代表其形成时点。

## 1. 当前状态

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。上游升级仍是未排期待办，启动时再冻结目标版本，
不得混入普通功能任务。

项目包含两套并列产品源码：`mydev/` 与 `multidev/`。当前方向状态如下：

| 方向 | 当前状态 | 当前规划边界 |
|---|---|---|
| 0：量化测评基准 | 既有设施与首次 schema v7 正式 canary 已完成，当前无 active campaign | 保留设施；历史结果见 COMPLETED，新 campaign 须重新立项与授权 |
| 1：Harness 优化 | **正式收口；当前无 active 工作包** | 当前不继续新增观测或内核/热路径优化；既有实现、设施与历史结果保留。未来可由用户另行决定是否重新立项，本次收口不作永久禁止 |
| 2：本地审批模型 | **已收口，今后不再开启** | 最终结论为“保留为实验”；不改生产默认，不再规划后续工作包 |
| 3：RONDO Multi | 第一、二期、第四期已完成；三期 Plan 099 阶段 B 技术恢复待审查者批示 | 工程链与双 backend 可替换性 GO；v2/v9/v10/qualification、formal decoder、pair-aware selector 与 direct-dependency identity 已冻结。Plan 099 只训练一套主方案；首 Pod 已安全释放为 0 compute，尚未下载模型或训练，replacement Pod 的 exact 控制路径与 guard 启动方式待批示；新四包串行路线未完成前不读冻结测试、不改产品默认、不授予质量、产品价值或生产资格 |

方向 3 当前 Linux 正确性基线由 Plan 093 建立：default features、standard local Nextest、checksum-verified V8 的完整 workspace
为 `14660/14660` passed、0 failure/error/timeout，另有 1/1 setup passed；24 个 skip 不计 passed。正式证据和精确边界见
`doc/WBS/multi-agent-trusted-evidence.md` 与 `doc/WBS-COMPLETED.md`。

### 方向命名口径

- 后续规划、任务与汇报统一使用“方向 1”和“方向 3”，不再使用“Local 方向”指代方向 1。
- `mydev/` 是方向 1 当前产品源码位置；`multidev/` 是方向 3 产品源码位置。目录名称不等于方向名称。
- `RONDO Local` / `rondo-local` 仅在必须区分现有产品或运行身份时使用，不代表方向 2。方向 2 专指已经收口的
  本地审批模型研究。

## 2. 下一工作包与顺序

方向 3 三期的现行后续路线如下，四个工作包严格串行；前一包的冻结交付物与宏观验收是后一包的前置，不并行修改任务语义、数据合同或训练候选：

```text
工作包一：任务合同重构
        ↓
工作包二：v8 后继数据改造与有限扩充
        ↓
工作包三：一次主方案训练（Plan 099 阶段 A → 审查者按用户委托批准后的阶段 B）
        ↓
工作包四：模型资格验收与横评
```

- **工作包一 / Plan 098 阶段一已完成并冻结**：既有 `rondo-publication-critic-task@v2` 五头、non-compensating gate 与
  implementation `55342bdb11b09c11b589fd398717f7712fca012c` 保持不变；下游 `rondo-publication-critic-decision@v1` 已定义逐头 margin、
  validation-only 冻结配置及固定逐维 confusion/failure recall，并把 config 绑定到 decoder/metrics implementation bundle；directional design
  另绑定 implementation commit 与 bundle。continuity 现仅在 N/A 决定性胜出时排除，弱 N/A 最高和 margin 边界均 fail-closed；标准 selector
  通过 `DevelopmentRelease` 机械绑定真实 v10 manifest、validation candidate bytes、labels、行序和 batch size。不恢复 global scalar threshold
  或 hard/soft 混合排序。版本化 formal projection 现保持旧 schema 字节和 v9 历史 identity 不变，同时把旧 raw argmax 限定为
  zero-margin diagnostic/historical reference；训练候选、validation、资格与未来产品正式 projection 只能使用绑定 frozen decision config 的
  decision v1 decoder。frozen decision bundle 现另绑定该 decoder 直接调用的 `successor_task.py` 与历史 raw output schema 精确字节；任一
  漂移都会在正式 decode 前 fail-closed。该绑定没有扩到 accepted-task 的其他非直接组件，不重开 v2 任务语义或 v9 历史 identity。
- **工作包二 / Plan 098 阶段二已完成并冻结**：`publication-critic-v9` 已按冻结 v2 合同形成 216 candidates / 96 pairs，物理
  train/validation/test 为 162/27/27 candidates；三个独立负责人模块均经一一对应的干净盲审以 0 finding 接受。正式 manifest、完整五维监督、
  Boundary/invariance、覆盖、重复/捷径门、train-only smoke 与只暴露 train/显式 validation 的 consumer 已闭合；v8 保持不变，安全投影不足以
  无歧义提供五头标签，故正式直接复用为零。finalizer 已在写出前核对 13 个必要语义组件及组合 SHA，并把 accepted implementation
  绑定进 design、generation config 与 release identity；权威 Markdown 不变而任一其他核心组件漂移的回归已闭合。方向性整改另冻结
  development-only `publication-critic-v10`，只含 162 train / 27 validation candidates；42 个原负责人定向 replacements 已获一一对应盲审接受，
  scope 长度 AUC、honest cue 反例、旁白和重复诊断闭合。v9 test 不读取、不改写并降格为 metadata-only 同分布辅助 holdout。全新 test-only
  负责人和独立盲审员已以 0 finding 接受 50-group / 200-candidate / 100-pair 的 family-isolated
  `publication-critic-qualification-v1`；其读取仍封存到工作包四。v9 原 `continuity-context` 盲审员已对同一 11 个 replacements 窄复验为
  0 finding 并绑定新 review SHA；release-bound selector 现同时绑定并消费实际 validation pairs，pair bytes SHA 进入 frozen config，12 个 pair
  的 Boundary Q+/Q-、非目标不变性与 soft invariance 报告必须全部闭合才可进入原单一 bounded margin grid 的确定性排序。v10/qualification
  只更新必要 identity 后从空目录机械重建并逐字节复现，数据正文和已接受 review 未重做。本轮 dependency identity 窄修同样只机械更新
  design/config/manifest/release identity 并完成独立字节复现。
- **工作包三 / Plan 099 阶段 B 技术恢复待批示**：唯一方案为 exact Skywork Reward V2 Qwen3 1.7B 冻结 BF16 backbone 加五个
  FP32 linear heads，只训练 22,528 个参数；本地已闭合消费、objective、checkpoint-first 控制、崩溃/续训恢复、裁剪后候选导出、有效 `NO-GO`
  与绝对截止资源门。copied venv、累计 `prior + lifecycle + kill grace + confirmation <= 10800` 和三类 content-addressed runtime control JSON
  上传边界已机械闭合。阶段 A 已通过审查且阶段 B 外部边界已生效；首个 exact Pod 在模型下载前因网络卷 FUSE `0666` 控制文件 fail-closed，
  获批的 current-Pod `/run` 窄修已本地闭合，但随后发现宿主 guard 不存活，遂按安全止费授权删除 Pod 并确认 0 Pod / compute `$0/h`。
  当前不继续计费；replacement Pod 的新 exact `/run` 路径和可持续 guard 启动方式须经指定队列批示后再执行。
- **工作包四待候选冻结后启动**：使用未参与训练和方案选择的冻结集合完成资格与横评，给出最终模型、判定配置和 GO/NO-GO；不得用
  测试集返调任务、数据或 threshold，也不因通过而自动默认启用或进入生产。

各工作包的详细目标、边界、宏观验收与授权门以 `doc/WBS/multi-agent-trusted-evidence.md` 为准。工作包一与二由
`plan/098-publication-critic-contract-and-v8-successor-execplan.md` 冻结完成；工作包三由
`plan/099-publication-critic-five-head-training-and-candidate-freeze-execplan.md` 规划为严格串行的非付费/付费阶段；工作包四仍在候选冻结后另立任务级
ExecPlan 与授权。

方向 3 是当前唯一仍在推进的产品线。Plan 081 已取得 `LOCAL_TRAINING_READINESS_PASS`；三期 Plan 082 已获用户付费批准并完成
真实 commissioning、正式 freeze、干净 formal 和新进程恢复，终态为 `VALID_NO_IMPROVEMENT`。保留 Pod 的 GPU 专项验收已经通过，
唯一训练 Pod 已释放并确认持续 compute 费率为 0；保留卷所在 `US-TX-3` 不提供 S3 API，故按用户一次性授权使用单个 transfer Pod
只读回传冻结 39 对象。全部对象完成本地 bytes/SHA-256 校验后 transfer Pod 已删除；最终验收通过。用户本人随后明确决定继续保留
网络卷 `mwemzrn33y`，该卷当前仍未删除，状态为 `FINAL_REVIEW_ACCEPTED / ZERO_POD / VOLUME_RETAINED_BY_USER_DECISION`。
Plan 087 已完成 exact BF16 1.7B 的 A–O 15 条自适应路线并保留 Route O。Plan 090 随后冻结该九张量/`33,558,784` 原参数配方，
从 exact base 在独立空间完成两次 clean BF16 execution；两次均通过整体 rubric，取得相同的 raw Boundary `+0.00390625`、projected
Boundary `+0.00086113`、projected Within-PASS `+0.00013894` 与 ROC AUC `+0.00140056`，第二候选经不同进程恢复。正式路径没有
shuffle、有效 dropout 或其它 seed-sensitive consumer，因此该结果只确认同一冻结 validation 上的执行/数值重复性，
`seed_sensitive_stability_tested=false`，不证明随机 seed 稳定或独立 cohort 泛化。条件性完整 FP32 参数训练对照已执行，raw Boundary
`-0.00659415`、projected Boundary `+0.00620638`，只支持精度路径敏感性诊断，不构成严格 update-only 因果反证。
Plan 090 保守费用 `$0.71`，低于 `$6` 硬上限；任务 Pod 已删除并实时复核 0 Pod、compute `$0/h`。只保留恢复合格的第二 BF16
checkpoint 于既有 57GB 卷 `mwemzrn33y`，卷未扩容或删除并继续按 `$0.006/h` 计费。Plan 087/090 的剩余预算与外部授权均不向后续转移。
Plan 090 最终独立验收已通过，其授权已经关闭。Plan 094 阶段 B 已在唯一 Secure US-TX-3 L40S 上完成 commissioning 和 clean formal；
Plan 090 guarded import 因历史 cursor 不兼容按合同拒绝，正式轮使用预冻结 exact-base fallback 干净重建。四个 checkpoint-first 观察点均无
material/strict/operating event，step 4 按预冻结平台规则形成 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT`；step 2/3 均由新进程恢复并继续。
三份保留 checkpoint 已在挂载卷上深读资格化，小型证据已回传，大型权重保留在 70GB 既有卷。预释放审查通过后，唯一 Pod 已精确 stop/delete；
账户 0 Pod、compute `$0/h` 与本地 finalizer 均完成，账户只剩卷费 `$0.007/h`。该任务仍只使用开发 validation，不回答独立 cohort 或产品资格；
M3-D 的质量/产品价值门继续锁定。
Plan 095 已完成并进入主线：复用 Plan 055/057/068 服务、typed verdict 与发布接缝，增加显式选择、default-off 的云端 reference scorer，
合成 packet 的真实 API commissioning/clean smoke、全部窄修与最终验收均通过。Plan 096 已在保持产品默认、local worker、Team State 与
发布行为不变的前提下，对冻结 validation 55 条完成 DeepSeek V4 Flash 正式 curve 与独立复算。正式 55/55、零最终 typed failure；
ROC AUC `0.8403` 与 Boundary strict win `15/19` 均过线，但 fallback threshold `0.9` 的 False PASS `8/21` 超过 `5/21` 上限，故终态为
`CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`。唯一 authority preflight finding 已离线窄修，首次独立验收复验以 0 High / 0 Medium /
0 Low 接受；该结论不授予 scorer 质量资格。不读取 unseen，不延续训练或继承 Plan 094 云资源。

用户随后另行启动 Plan 097，把 M3-D 当前工作包改为工程前置闭环：以 exact 1.7B base 与 DeepSeek V4 Flash 作为未获产品质量资格的真实 fixture，
验证同一 `PublicationScorer → service → typed client → team_publish` 链在 OFF/local/cloud 三态下的 Producer rewrite、canonical commit、
failure/cancel、Root/Team State 不变量及 backend 可替换性。任务通过只表示工程链与替换接缝 GO；本地模型质量、云端 scorer 资格、产品价值、
Publication Critic 默认与生产启用继续锁定。实现与 clean `plan097-formal-5` 已形成
`M3_D_DUAL_BACKEND_ENGINEERING_PASS`：local/cloud 均 3/3 fixture 覆盖 `PASS + REWRITE`，正常 Producer 均完成两次重写与唯一提交，
OFF/fallback/cancel 和资源终态闭合；累计保守费用 `21.4197186 RMB / 30 RMB`。首次独立验收指出费用账本跨进程互斥、Producer identity
收口、service shutdown 失败传播、临时残留和 reference threshold 精度问题；执行者已按保留 `formal-5` 且不重跑付费 API/真实模型的决定完成窄修，
最终独立复验以 0 High / 0 Medium / 0 Low 接受。当前项目口径为工程链 GO、双 backend 可替换 GO；本地模型质量
`NO-GO / 待替换`、云 scorer `NOT QUALIFIED`、M3-D 产品价值未验收、Publication Critic 默认 `OFF`、生产启用 `NO`。合同与最终状态见
`plan/097-m3-d-dual-backend-engineering-execplan.md`，正式摘要见
`eval/results/publication-critic/m3-d-dual-backend-engineering-v1.md`。
方向 1 已正式收口，不作为方向 3 的前置或旁支。

### 方向 3：Publication Critic 三期

- M3-A1 产品合同、M3-B2a / Plan 055 本地 Critic 服务与 M3-B2b / Plan 057 发布流程接入均已完成并进入主线。Plan 060 训练资格
  `TECHNICAL_GO`、冻结 v8 `DATA_GO` 与 Plan 066 正式训练授权已经同时成立；M3-B1c 已完成正式训练、候选保存、恢复验证、计算终态与
  独立验收。产品链与模型链已在 `M3-C1 → M3-C2` 汇合；Plan 073 的 `NO-GO` 未解锁原路线最后的 M3-D。
- M3-A2 / Plan 054 与 M3-B1a / Plan 059 均已完成并进入主线。Plan 059 revision v7 冻结 72 candidate、30 Boundary 与
  6 Within-PASS，三 split 为 42/16/14；独立最终验收确认输入隔离、group/split、review、50,073-token census、manifest、
  factory-only consumer 与 train-only smoke bundle 闭环，`remaining_findings=[]`，数据结论 GO。详细历史见
  `doc/WBS-COMPLETED.md` 与 Plan 059 最终验收日志。
- Plan 064 已独立验收完成并冻结 `publication-critic-v8`：228 candidate、104 pair、三 split 为 128/55/45，训练 consumer 默认
  只暴露 train。覆盖、质量与消费合同通过；冻结时的预算适配证据不足已由 Plan 060 正式吞吐、费用和 23 USD 连续总账的有界复核闭合，
  当前结论为 `DATA_GO`。v7 与 Plan 060 smoke 输入保持不变，Plan 066 只消费 v8 train，validation 不进梯度，unseen-test 默认封存。
- M3-B1b / Plan 060 已在 Secure 单卡 H100 PCIe 80GB 上完成 BF16 全参数 FlashAdamW commissioning 与 final-19
  干净 formal start/resume，C1→C2→C3、完整 checkpoint、新进程恢复和继续更新均形成有效证据；独立代码/archive 复核
  `remaining_findings=[]`，最终验收通过，结论为 `TECHNICAL_GO`。Plan 060 与 Plan 066 从原 Plan 060 基线连续计入 23 USD 总账；
  Plan 066 已统一收口计算资源终态；final-01 terminal receipt 因延迟追账 superseded，final-02 保留生成时的控制台费用快照，最终费用口径见下项。
- M3-B1c / Plan 066 已在当前唯一 H100 PCIe 80GB 上从 exact base 干净执行 C1→C2→C3，实际消费 128 Binary、50 Boundary 与 8
  Within-PASS，保存并复验三个阶段候选、固定 validation 与完整恢复点，新进程 step 3→4 继续更新通过。计算 Pod 已永久删除；Plan 068
  随后把 formal checkpoint、三个候选、exact 模型与必要环境安全交接到本地并删除 winner 卷。独立验收按用户指定冻结终审最新 provider 快照总费用 `$10.9647715263`，距 `$23`
  硬上限 `$12.0352284737`；correctness/functionality `remaining_findings=[]`，结论为 `GO`。该训练结论解除 M3-C1 前置，
  但本身不授予模型质量、threshold、部署或产品资格；资格已由 Plan 068 独立判断，见下项。
- M3-C1 / Plan 068 已完成本地工件交接、真实 scorer/service 接入、四对象正式资格运行、独立验收与远端止费。正式 v3 结论为
  base `NOT_QUALIFIED`、C1 `QUALIFIED`、C2 `NOT_QUALIFIED`、C3 `QUALIFIED`：base 未过 projected drift 与临时 verdict parity，
  C2 未过 ranking/direction，C1/C3 的 runner/service 一致性、稳定性和有界资源门通过；unseen-test 未用于适配或选择。
  本地保留 110/120 个必要对象（正式 checkpoint 载荷已释放，manifest/metadata 与验收收据保留）；RunPod exact winner 卷已删除，当前 0 Pod、0 volume、持续费用为 0。
- Plan 071 在不改冻结权重、数据、Plan 054/055/057 产品语义或最终 threshold 的前提下，将 cross-runtime raw/envelope、
  同 deployment worker parity 与精确 service verdict 分层判断，并以同一规则从干净状态重验 exact base、C1、C3。唯一有效正式轮
  `plan071-formal-20260825T064600Z-qualification-v5` 给出 base/C1/C3 均 `QUALIFIED`，C2 未重验并保持 Plan 068 历史
  `NOT_QUALIFIED`；最终独立验收接受 `BASE_COMPARABILITY_GO`，因此 `m3_c2_prerequisite_satisfied=true`。
  Plan 073 / M3-C2 随后以同一冻结协议正式比较 exact base、C1、C3，三者均未达到发布质量底线，终态为 `NO-GO`；没有
  selection lock 或 unseen-test 释放，也没有最终模型、threshold 或运行配置。Publication Critic 保持 default-off，M3-D 的质量/产品价值门保持锁定；
  Plan 075 已完成证据链重建：直接失败层是模型质量；部署、runtime 和 threshold 不是原因；Plan 066 训练后的 C1/C3 有输出/排序
  退化，但现有单 recipe/seed/run 不能把 LR、裁剪、objective、optimizer、数据或底模之一确定为单一根因。Plan 079 随后对 exact
  `Skywork/Skywork-Reward-V2-Qwen3-4B@fd958fef475f323f4e6b195930e3dd918485c668` 原始 BF16 base 完成冻结 validation 正式测评：
  55/55、零 typed failure，但完整 operating curve 不存在满足全部质量门的点，终态为 `4B_BASE_QUALITY_NO_GO`。该结果未产生训练、
  量化、本地部署或产品资格。Plan 081 随后完成 exact 1.7B、冻结 pair/input/v8、禁止 LoRA/QLoRA 的本地路线准备，
  以可按训练动态扩大的部分参数直接更新为当前首选，并在不运行真实模型/GPU/云端的前提下闭合连续质量观察、checkpoint、恢复与归档；
  它不预先冻结具体层数、学习率、batch、更新数或优化器。后续真实训练以形成同口径优于 exact 1.7B base 的候选为研究目标，
  不要求直接取得产品 GO；未优于 base 时保留 no-improvement 结论。Plan 079 任务 Pod 已删除；用户提供的最新查询显示原 20 GB
  Standard 网络卷 `v1us0nmk0p` 返回 404、已不存在，Plan 082 在创建资源前仍通过既有安全入口复核且不依赖或恢复该卷；
  Plan 082 已从 exact base 完成冻结的 score-head 四步正式训练；boundary pair mean margin 从 `0.8252560622` 逐步轻微回落至
  `0.8252007961`，而 ROC AUC、strict win rate 与 balanced accuracy 不变，故诚实形成 `VALID_NO_IMPROVEMENT`。step 2 已由新进程
  恢复并继续更新，step 2 与 step 4 两份完整 checkpoint、正式/commissioning 原始 observations、输入和日志在 Plan 082 完成时保留于
  40GB 任务卷，任务根实际占用约 31.21GB；Plan 087 后续将同一卷扩至 57GB 并保留候选。当前卷按用户决定继续保留，不删除大 checkpoint；
  任何再次扩容须由新任务重新授权。
  冻结 bootstrap 的 39 个正式对象也已完整回传到项目 ignored 目录并逐对象验证；正式对象共 `13,797,142,360` bytes，加 bootstrap 后
  `13,797,156,884` bytes。最终验收确认 formal/retention/receipt 与本地 exact-tree 闭合；transfer Pod 已删除并确认 0 Pod，网络卷继续
  保留；用户本人已经明确决定继续保留，卷 `mwemzrn33y` 当前仍未删除。
  Plan 082 训练活动受 12 小时/15 USD 上限约束，训练与后续资源保留/无 Pod 回传费用分账报告，总累计达到 10 USD 时非阻断告警；
  详细结果与后续边界见三期子 WBS。
- Plan 087 接续 Plan 082 的 `VALID_NO_IMPROVEMENT`，保持 exact 1.7B、冻结 v8/pair/input、unseen 隔离和非 PEFT/非量化边界，
  在单张 L40S 与 9 USD 授权内完成 A–O 15 条 exact-base 路线。Route O 的 `33,558,784` 个末块内部输入变换/归一化原参数经一次
  full-cohort 更新取得 raw boundary margin `+0.00390625`、projected boundary `+0.00086113`、projected within-PASS
  `+0.00013894` 与 ROC AUC `+0.00140056`，关键 operating 指标未退化；checkpoint 已由不同 OS 进程 no-update 恢复，终态为
  `PROMISING_CANDIDATE_RETAINED / FINAL_REVIEW_ACCEPTED / ZERO_POD`。由于 15 条路线共用 validation 且没有干净重跑，效果可靠性、
  重复性与独立泛化未确认；后续只允许另行立项和授权的冻结 recipe 正式复现，不解锁 unseen、M3-C1/M3-C2、产品启用或 M3-D 产品价值。
- Plan 090 已按冻结顺序完成 Route O 两次 clean BF16 execution、第二候选不同进程恢复与真实整模型 FP32 参数训练条件对照，终态为
  `ROUTE_O_CONFIRMATION_PASS / ZERO_POD`。两个 BF16 结果在同一 validation 上完整重复 Plan 087 信号；FP32 的 raw/projected 方向分歧
  作为精度路径诊断保留。该结果不测试随机 seed 敏感性、独立 cohort 或 unseen，不授予产品 GO、M3-C1/M3-C2 或 M3-D 产品价值资格；后续若继续，
  必须另立任务而不是沿用 Plan 090 授权。
- Plan 094 已在单张 US-TX-3 Secure L40S 上完成 clean Route O 连续正式轨迹。step 1 只重复 Plan 090 微弱信号，step 2--4 raw Boundary
  转负，projected margin 小幅上移但始终没有 material/strict/operating event；预冻结 step-4 平台规则形成有效负向终态
  `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT`。fresh-process 恢复并继续与卷上 checkpoint 深读资格化均完成，大型权重保留在按需从 57GB
  扩到 70GB 的既有卷，小型结果已回传。预释放审查通过后，唯一 Pod 已删除并独立复核账户 0 Pod / compute `$0/h`；本地 finalizer
  保持同一有效负向终态，并已通过整体最终验收。不读取 unseen、不授予产品资格或 M3-D 产品价值资格。任务合同见
  `plan/094-publication-critic-route-o-continuous-training-execplan.md`。
- Plan 095 已完成并进入主线：在不改变 `PublicationScorer`/service/packet/render/`team_publish`/本地 worker 语义的前提下，新增
  default-off 的云端参考 scorer backend `codex-publication-critic-cloud-service` 与显式选择路径。离线以 loopback provider 覆盖
  ready/PASS/REWRITE、malformed/out-of-domain、model drift、有界 retry、慢 provider 与取消、并发/队列与 fail-closed 启动；随后以合成
  packet 完成真实 API commissioning 与 clean smoke，两个正反 packet 得到 `PASS` 与 `REWRITE`，并由 400 负向对照证明请求确实到达选定
  provider。云端 identity 对 provider 无法验证的 tokenizer/serving 分量显式标为 `provider-managed-tokenizer@unverifiable`，scoring
  definition 强制带 `rondo-cloud-reference-` 前缀，threshold 为显式非最终参考值。首次 finding 已全部窄修并通过 Sol 最终复验，任务不做
  批量测评、最终 threshold、v8/unseen、GPU、真实本地模型或项目数据上传；合同见
  `plan/095-publication-critic-cloud-reference-scorer-backend-execplan.md`。
- Plan 096 已完成实现、真实 synthetic commissioning、clean freeze、空 namespace 正式 55 条与独立复算，通过最终独立验收并进入已推送
  主线。唯一 authority preflight finding 已窄修，复验为 0 High / 0 Medium / 0 Low correctness finding。正式模型
  `deepseek-v4-flash` 的结果为 `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`：False PASS `8/21`、False REWRITE `0/34`、balanced
  accuracy `0.8095`、ROC AUC `0.8403`、Boundary strict win `15/19`，完整 curve 无 admissible operating point。正式轮 55/55、零最终
  typed failure、56 attempts，其中一次冻结 policy 允许的 transient retry；正式费用 `1.3855704 RMB`，含两轮 commissioning 的任务总费用
  `2.1391799 RMB`。该终态不授予质量或产品价值资格；Plan 097 由用户另行以工程 fixture 目标启动。任务未修改标签/pair/rubric/quality floor，
  未读取 unseen，未训练或使用 GPU/RunPod/Docker，
  也未改变 Publication Critic 默认和产品发布语义；合同与完成状态见
  `plan/096-validation-cloud-scorer-qualification-and-headroom-execplan.md`。

如果未来重新启动方向 1，它仍与方向 3 保持产品源码和任务合同独立；本地重型 Cargo、Docker、真实本地模型
加载/推理继续全局串行，并由实际进入实施的工作包协调共享资源。

- 方向 0 的设施保持可用，但不自行创建新 campaign；任何真实 API、Docker 或新预算均需针对新任务重新授权。
- 方向 1 当前正式收口，不排期观测或内核/Harness 优化；未来是否重新启动由用户另行决定。
- 方向 2 永久收口，不作为方向 1 或方向 3 的前置、旁支或待恢复项目。
- 上游 Codex 基线升级继续保留为独立、不排期任务；只有用户明确启动时才进入规划。

## 3. 方向关系

- 方向 1 的既有产品源码位于 `mydev/`，当前正式收口；方向 3 在 `multidev/` 推进多智能体与 Publication Critic。
  如果方向 1 未来重新启动，两者仍不互相夹带实现。
- 方向 0 是可复用设施，不再作为解锁其他方向的总闸门；只在具体任务需要时提供相称测评。
- 方向 2 已永久收口，不参与后续路线，也不阻塞其他方向。
- 所有方向只共享排期、API 预算、Docker、构建和本地模型等全局资源约束，重型操作保持串行。

## 4. 仓库与产品线结构

### 4.1 布局

```text
RONDO/
├── mydev/        # 方向 1 产品源码（当前收口，目录名沿用现状）
├── multidev/     # 方向 3 产品源码
├── eval/         # 两套产品可复用的通用测评设施
├── scripts/      # 共享构建锁与资源看门狗入口
├── eval-data/    # 本地重资产与私有运行数据，内部按产品分命名空间
├── test-data/    # 历史测试结果和数据
├── training/     # 轻量、受跟踪的训练合同与门限内数据集
├── doc/
└── plan/
```

### 4.2 产品与分支边界

- 两套产品地位相同，但核心源码独立；公共修复和外围设施按需复用，不追求提交级长期同步。
- 单仓库、单长期 `main`；不为方向 3 维护永久产品分支。具体开发任务仍按 `AGENTS.md` 使用短期 worktree，
  除非用户明确要求直接在主工作区工作。
- 方向 1 任务原则上修改 `mydev/` 及必要共享文件；方向 3 任务原则上修改 `multidev/` 及必要共享文件。
- `eval/`、WBS 和其他共享权威文件尽量在同一时段由一个任务负责，避免并行任务互相覆盖。

### 4.3 磁盘与重型资源

- 重型 Cargo 构建与测试必须经仓库根共享 `scripts/with-build-lock.sh` 或已接入它的 `just` 配方。受支持 Unix 入口按产品把
  主工作区和 linked worktree 路由到物理仓库根的 `.codex/cargo-target/rondo-local` 或 `rondo-multi`；两产品叶子隔离，
  `CARGO_TARGET_DIR` 必须位于项目根内并受看门狗监督。当前只保留已建立基线的 `rondo-multi`，`rondo-local` 当前不存在。
- 日常 Cargo 默认 `jobs=2`、GNU/Linux LLD 单线程、机器级 rustc 槽为 2；要求尽量一次跑完的完整 workspace 使用产品 Justfile 的
  `test-with-codex-v8-conservative`（`jobs=1`、LLD 单线程）。两套产品的重型构建、Docker、真实本地模型加载/推理仍全局串行。
  除具体 ExecPlan 已获得一次性授权外，后续重型批次不自动排队，须由用户逐批明确批准并人工决定运行时机；历史授权不转移。
- 具体磁盘、Windows `C:`、内存、swap、Docker 增量和 fail-closed 阈值以根 `AGENTS.md` 为准，不使用 WSL
  虚拟容量代替宿主容量。

### 4.4 共享外围设施

两套产品可复用构建锁与看门狗、Docker/Terminal-Bench runner、API 预算与结算、BinaryManifest、结果归档、
本地模型外围运行设施以及 fake/loopback/replay 测试，但不因此共享核心产品语义。

### 4.5 产品身份与历史资产

- `product`（`rondo-local` / `rondo-multi`）表示既有运行产品身份，`side`（`rondo` / `codex`）表示比较侧；
  两者正交，且都不替代方向 1/2/3 的规划名称。
- 方向 3 身份必须贯通源码、构建、冻结 binary、manifest、adapter/RunSpec 与结果归档；唯一布局映射为
  `eval/rondo_eval/contracts.py` 的 `product_layout()`。
- 历史结果、receipt、trace、冻结 plan 和审计材料保持原身份，只作为历史证据，不回填新字段、不冒充新任务基线。
- crate 名与二进制名沿用上游（`codex-cli` / `codex`），便于与 `codex-source-code/` 直接比较。
- 数据资产边界见 `doc/eval-data-layout.md`。

## 5. 持续工程约束

- 测试用于正确性保障，随有效代码维护，只跑受影响模块所需门禁；较大阶段收口时再运行相称的扩大门禁。
- 测评用于量化性能与行为，默认关闭、轻量、自动记录归档；fake、离线、真实 API、真实模型与 Docker 证据严格区分。
- 冻结 Codex 与 RONDO 的公平比较只使用同口径外部指标；内部探针只用于同一产品自身诊断。
- skip、未运行、无效比较和基础设施失败不得表述为通过，也不得为凑绿弱化测试、安全或审批逻辑。

## 6. 授权门

以下动作每次执行前都需要针对具体任务单独授权，历史授权不自动延续：

- Docker 拉取、构建或运行；
- 按量付费真实 API 批量测评，包括任务、轮数、模型与预算上限；
- 真实本地模型加载或推理；
- 真实数据外发，包括上传项目生成的数据；
- 云 GPU 训练、上传或下载权重及其他会产生费用或外部状态的操作；
- 上游基线升级。

普通依赖下载、源码查询和只读网络访问可随已授权任务执行。具体资源阈值、密钥边界和操作纪律以根
`AGENTS.md` 为准。

Plan 097 的一次性本地模型、DeepSeek scorer、正常 Producer 与 30 RMB 真实 API 授权已随最终验收关闭，余额不转移。用户已批准并完成本地
main 合并和随 Plan 098 主线更新推送；分支归档或 worktree 删除继续等待用户批准。任何后续真实模型/API、质量测量、产品价值验证或生产动作都须
服从对应新任务授权。
Plan 099 阶段 A 已通过独立验收，阶段 B 已按指定队列冻结主方案、资源、时间、动态预算、技术恢复、资产传输和收口范围。首 Pod 已因 guard
核验失败按安全止费授权删除并确认 0 compute；在 replacement Pod 的新 exact 控制路径与稳定 guard 启动方式获批前保持无 Pod。
工作包四的真实推理、冻结测试和付费横评仍需再次独立授权。

## 7. 子 WBS 索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：现行测评设施与新任务授权边界
- `doc/WBS/teacher-harness-study.md` —— 方向 1：正式收口状态与历史归档入口
- `doc/WBS/local-approval-model.md` —— 方向 2：已永久收口
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：现行产品语义与三期 Publication Critic 长程路线
- `doc/WBS/durable-team-runtime.md` —— 方向 3 四期：正式收口状态与历史归档入口
