# Plan 071：M3-C1 基座对照可比性修正与有界资格重验 ExecPlan

> 本计划是 Plan 068 之后的独立修正任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认；普通环境、数值、进程、依赖、测试和局部兼容问题
> 应在范围内自主修复并按需重跑。
> 本计划只处理 base 本地部署可比性；M3-C2 的联合横评、最终模型/threshold/运行配置选择和后续顺序，以
> `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在不改变 exact base、训练候选、数据、输入/scalar 合同或产品语义的前提下，解释 Plan 068 正式 v3 中 base 的
CPU FP32 reference 与本地 CUDA deployment 之间为何出现 projected drift 和一次临时 verdict mismatch；只修正经证据确认的
部署或资格可比性问题，并在正式重验前冻结一套对 base 与训练候选锚点一致适用的资格口径。

从干净 tracked source 和新的 Plan 071 正式 namespace 完成 base 与至少一个既有合格训练候选的同口径资格重验，形成以下
唯一一种任务终态：

- `BASE_COMPARABILITY_GO`：base `QUALIFIED`，且至少一个训练候选锚点在同一规则下仍 `QUALIFIED`；
- `BASE_NOT_COMPARABLE`：有效环境和合理修正下 base 仍无法取得本地可比资格；
- `INCONCLUSIVE`：基础设施、宿主资源或必要观察不足，无法作出有效资格判断。

本任务以得到可靠结论为成功，不以强行让 base 通过为成功。它不修复 C2 的模型能力，不排名候选，不冻结最终产品 threshold，
也不启动 M3-C2。

### 完成/验收标准

- [ ] 只读复核 Plan 068 唯一有效正式轮 `plan068-formal-20260824T222852Z-qualification-v3` 的输入、freeze、raw reference/
      deployment、service 和 result，明确区分候选身份、cross-dtype 数值差异、同 runtime 重复性、offline/service parity 与临时 verdict。
- [ ] 对 base 失败给出有证据的分类：真实且不可接受的部署漂移、参考/数值域/运行口径不等价、scorer/runtime 局部兼容问题，或
      临时 verdict 对近边界差异的放大；允许多因一果，但不能只凭最终 PASS/FAIL 倒推原因。
- [ ] 在正式模型重验前固定资格规则的选择依据；完成必要 commissioning 后，再冻结 source、原始工件、实际 deployment artifact、
      runtime identity、既有非 unseen cohort、训练候选锚点和具体数值/方向/verdict/service 门。规则不得按 base 已知差值贴线。
- [ ] exact base 与锚点使用同一输入、tokenizer、窗口、projection、runtime 类别和资格判断规则；如果对象身份导致规则输入不同，差异必须是
      规则本身预先定义的显式输入，而不是 candidate-specific relaxation。
- [ ] base 从空正式 namespace 完成完整资格运行；至少一个 Plan 068 `QUALIFIED` 的 C1/C3 候选完成同口径正式锚点运行。若修改影响
      共享 qualification/scorer/projection/service 逻辑，则正式覆盖所有受影响的 C1/C3 门，不能静默沿用旧结论。
- [ ] base 取得 `QUALIFIED`，或在有效基础设施下形成可复现的 `BASE_NOT_COMPARABLE`；无法满足有效运行条件时形成 `INCONCLUSIVE`，
      不把基础设施失败写成模型失败。
- [ ] base 正式轮覆盖 24 条既有 cohort 的 identity/load/offline score、资源与延迟，以及真实 service 的 ready、同输入 parity、有界压力和
      clean shutdown；既有 failure/cancel/restart 合同未受影响时不机械重做完整故障矩阵，相关接缝改变时才补齐受影响项。
- [ ] offline deployment runner 与正式 Plan 055 service runtime 对同一输入保持合法、有限 scalar 和 verdict 一致；若改动触及 service seam，
      定向复核 descriptor、typed failure、取消、重启和关闭，不机械重复无关全生命周期测评。
- [ ] C1/C3 既有资格未因本轮规则或共享实现变化被静默破坏；C2 保持 Plan 068 的 `NOT_QUALIFIED` 历史结论，不进行模型重验、调参或能力修复。
- [ ] Plan 054 输入/render/tokenizer/window/scalar 语义、Plan 055 服务协议、Plan 057 默认关闭与发布/fallback/cancel/store 语义均保持不变；
      unseen-test 未导出、未读取、未运行或用于口径选择。
- [ ] 调试阶段先以小范围从未打通处自主修复、续跑和重跑，直至目标链路完整打通；随后冻结身份和配置，从 clean tracked source 与全新正式
      namespace 完整运行一轮。不得拼接 Plan 068 结果、调试轮或不同 freeze 的零散输出冒充 Plan 071 正式结果。
- [ ] 只运行受影响的 Publication Critic Python/Rust 定向门禁、必要格式/生成物检查、真实模型重验与 `git diff --check`；skip、未运行、
      pure/fake、真实模型和 Docker 证据分别表述，不机械运行无关全 workspace。
- [ ] 使用普通 JSON、SHA-256、现有日志和必要测试证据即可闭合身份与结果；不建设签名链、数据库、registry、通用审计/可信平台或第二套模型服务。
- [ ] 不干扰 Plan 069/070 的文件与运行现场；真实本地模型、Docker 或重型 Cargo 只在二者释放重型资源后按根资源门串行执行。
- [ ] 更新本计划当前状态和一份精炼 `agent_log`，形成 clean Plan 071 分支提交并接受独立验收；不合并、推送、归档分支或删除 worktree。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/local_deployment/` 内职责明确的资格比较、inference/worker、service runner、结果聚合和窄 launcher
  能力；优先扩展现有设施，若继续把 Plan 071 语义塞入 Plan 068 schema 会扭曲历史，可增加版本化的 Plan 071 专用模块或 schema。
- `eval/tests/test_publication_critic_*` 中与本任务直接相关的 pure/fake/focused 回归，以及必要的小型 tracked freeze/template/说明。
- 仅在真实证据表明 Python qualification/backend 不能闭合问题时，窄改 `multidev/codex-rs/publication-critic/` 的 real scorer、
  service/probe 接缝及其测试；没有证据时不改 `core`、Team State、app-server 或 TUI。
- 仅当 `codex-publication-critic` 的真实依赖发生必要变化时，机械更新并审查 workspace `Cargo.lock` / `MODULE.bazel.lock`；不得为本任务
  预先引入无关依赖或改锁文件。
- 本计划“当前状态/关键决策记录”、一份精炼 Plan 071 `agent_log`，以及独立审查报告。当前路线 WBS 只在任务独立验收后由后续主线同步
  基于最新 `main` 窄更新，不在执行提交中抢写并行任务状态。
- 主物理仓库根的 ignored `eval-data/publication-critic/plan071/`，用于 commissioning、freeze、调试和正式结果；确有必要时可创建
  `eval-data/envs/publication-critic-plan071/` 或 Plan 071 专用 cache。任务输出不得写回 Plan 068 namespace。
- 只读使用主物理仓库根现存的 Plan 068 exact base、C1/C2/C3、完整 checkpoint、handoff evidence、commissioning、正式 v3 证据和
  `eval-data/envs/publication-critic-plan068/`；运行既有 env 可以复用，但不得在其中安装、升级或改写依赖。
- 只读使用旧 Plan 068 worktree 的已验收 service/probe 二进制作为历史复现参照；Plan 071 若需构建，输出到 Plan 071 自己的受监控
  target，不覆盖旧 target。
- 若现有 exact base 或公开 tokenizer 文件经身份验证确实缺失/损坏，可只读下载
  `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` 到 Plan 071 专用 cache；
  优先复用本地完整工件，不登录、不写 Hugging Face Hub。
- 普通项目局部依赖和公开只读源码/文档下载；资源释放后在当前 RTX 4060 Laptop / WSL 上进行必要的有界本地模型加载和推理。
- 只有现有正式路径确有必要时，使用一个明确的 task-owned Docker image/container；它不是默认要求，且只能清理本任务创建的对象。

### 不允许修改或执行

- 修改或覆盖 exact base、C1/C2/C3、Plan 066 checkpoint、tokenizer、任何冻结权重/manifest，或重新训练、继续训练、合并 adapter、
  生成/改写训练数据、label、pair、split。
- 改写 Plan 068 v3 的 freeze、raw evidence、result、summary、历史 plan/log 或旧 target/env；Plan 071 只能引用并产生新结论，不能把
  历史 `NOT_QUALIFIED` 重标为错误结果。
- 改变 Plan 054 两消息 render、完整 candidate、exact tokenizer、16,384 window、whole-continuity omission、right padding、
  `logits[:,0]` higher-is-better、stable sigmoid `[0,1]` 或有限单 scalar 语义。
- 改变 Plan 055 protocol/descriptor/identity/verdict/typed failure 信任边界，或 Plan 057 默认关闭、rewrite/fallback/cancel/唯一 store commit
  产品语义；如确需改变这些稳定语义，应停止并请求上游决定。
- 为使 base 通过而修改临时 threshold、最终 threshold、标签或产品 verdict 映射；资格层的 cross-runtime 容差或 near-boundary 规则不得
  静默改变 service descriptor 中精确的 `projected_score >= threshold` 行为。
- 修复或重跑 C2 的 ranking/direction 模型能力，开展候选排名/最终选择、M3-C2、M3-D、端到端协作收益或默认启用 Critic。
- 新建任何 RunPod/HF Job/Endpoint/Space/Repo/Bucket、云 GPU、远端存储或其他付费资源；真实 API、远端上传/发布、训练、上游升级。
- 删除 Plan 068 本地交接资产、C1/C2/C3、exact base、完整 checkpoint、正式/commissioning/handoff evidence、旧 serving env 或旧 target；
  不清理来源不明的本地/Docker对象。
- 读取或修改 Plan 069/070 工作树、未提交实现、plan/log 或其 Durable Session/app-server/TUI 语义；不依赖其尚未进入 `main` 的代码。
- 无关全 workspace、CI/PR、任务分支 push、合并/rebase `main`、分支归档/重命名或 worktree 删除。

### 不允许读取/查看

- `.env.local` 内容、任何 token、API key、access key、secret、私钥、密码或个人配置；本任务正常路径不需要这些凭据。
- v8 unseen-test 正文或投影，以及与本任务无关的真实 publication/transcript/private reasoning、Fact observation、raw evidence 或训练监督正文。
- 与任务无关的项目外个人文件、其他仓库和来源不明 ignored 资产。

### Git-ignored 与物理根边界

tracked 代码、测试、计划和日志全部在
`/home/sjc/desktop/RONDO/.claude/worktrees/071-m3-c1-base-comparability/` 修改并提交，主工作区不得产生 tracked 修改。

linked worktree 不共享主根 ignored `eval-data/`。因此 Plan 071 的调试/正式原始结果、可能的新 env/cache 必须直接落在主物理仓库根的
`eval-data/` 对应 Plan 071 namespace；这些是授权内必须在主物理工作区直接产生的 ignored 内容。每次交接单独报告实际创建/修改的 ignored
路径、大小、权限与保留状态，但不建立额外资产管理系统。

Plan 068 的核心模型、checkpoint、证据、serving env 与旧 target 只读保留。Plan 071 不复制整套 24GB 工件；运行时从既有绝对路径读取，
只把新产生的小型结果和确有必要的派生工件写入 Plan 071 namespace。

## 3. 硬约束

以下约束只冻结任务边界、公平比较、产品语义、正式运行身份和并行安全，不预先锁死 executor 采用的数值方法、deployment dtype、模块布局
或调试策略。

1. **历史与资产不可变。** Plan 068 v3 是通过独立验收的历史事实：base/C2 `NOT_QUALIFIED`、C1/C3 `QUALIFIED`。
   Plan 071 从相同冻结权重和既有非 unseen cohort 出发建立新运行，不编辑旧证据、旧二进制、旧 env 或模型文件，也不把重验结果回填成
   Plan 068 当时的结论。
2. **先归因，后修正。** 阶段 A 先用现有 raw evidence 和纯逻辑检查区分：same-artifact CPU FP32↔CUDA 数值差异、同 runtime 重复性、
   scalar→sigmoid 投影、临时 threshold 边界、offline↔service parity 和实际产品 verdict。不得先改 gate 再为其寻找理由。
3. **输入和 scalar 只有一个定义。** 继续消费现有 typed `PublicationPacket` 并复用 Plan 054 的 renderer/tokenizer/window/pooling/direction/
   projection。可以修正不同数值 runtime 之间如何判断“可比”，不能为 base 创建第二种模型可见输入、scalar 或产品 verdict。
4. **比较层必须分清。** 资格证据分别报告原始工件身份、reference runtime、deployment runtime、cross-runtime 数值差异、deployment
   offline/service 一致性和临时 verdict 行为。BF16 不能冒充 FP32；同一 artifact 也不能把不同 runtime 的结果称为同身份重跑。
5. **口径不能按结果贴线。** 阶段 A 先冻结判断维度和具体门限的选择方法；阶段 B 可用有界 commissioning 验证合理数值模型并自主迭代。
   正式轮之前必须冻结具体规则。门限应来自 dtype/runtime 的工程依据、独立重复性或预先声明的方法，不能由“base 差多少”或候选当前结论加 epsilon 得出。
6. **同口径对待 base 与锚点。** 同一冻结规则必须应用于 base 与正式锚点；若规则考虑 reference score 区域、数值精度或 threshold 距离，
   这些只能作为预先定义、对所有对象同样计算的输入。若一项 shared gate 被改变，所有受影响的 C1/C3 都应重验。
7. **资格容差不是产品 threshold。** Plan 054 calibration threshold 只保留为部署资格的临时判定参照，不得调整它来让 base 通过，也不冻结
   最终产品 threshold。若采用 guard band、raw-domain 比较或 reference→deployment 映射，它们只属于资格判断并对锚点同样适用；正式 service
   仍按 descriptor 中的精确 threshold 和 `>=` 规则输出 verdict。
8. **只修部署可比性。** 允许修复资格比较、dtype/runtime 适配、worker/scorer 或 service parity 的局部问题；不得把 base 自身质量、C2
   ranking/direction、最终候选选择或产品语义问题重新定义成部署 bug。若合理路线仍不能闭合，诚实输出 `BASE_NOT_COMPARABLE`。
9. **复用唯一服务边界。** 真实模型仍只替换 Plan 055 的 `PublicationScorer` backend，继续经过现有 loopback、trusted expected descriptor、
   bounded queue/deadline、typed verdict/failure、取消和关闭。raw/projected score只留在权限合适的资格结果，不进入产品 wire、Team State 或普通日志。
10. **先打通，后正式。** 阶段 B 可保留已验证的轻量进度并从失败处边修边跑，不设机械重试次数；先完整打通 base 与锚点的目标路径，
    再冻结 tracked source、原始/部署工件、runtime、cohort、规则和程序身份，从 clean source 与空正式 namespace 完整运行。正式身份改变后重跑受影响正式轮。
11. **三态诚实。** 有效运行中的数值、方向、verdict、service 或资源门失败应保留，不能反复搜索配置掩盖；依赖、OOM、进程、driver、锁、
    暂时资源竞争等基础设施问题可自主修复/重跑，仍不足以判断时为 `INCONCLUSIVE`，不能写成 `BASE_NOT_COMPARABLE`。
12. **数据隔离。** 正式 offline 资格继续覆盖 Plan 068 已用的 24 个 Plan 054 representative/boundary 样本，不得新增/改写样本、
    用 v8 validation/unseen-test 调门、排名或选择。commissioning 和 service parity 可以使用其中有界子集，但不能冒充正式 offline 结果。
13. **重型资源严格错峰。** 阶段 A 和纯逻辑/轻量测试可立即与 069/070 并行；在 069/070 释放重型槽之前，不运行 Cargo、Docker 或真实模型。
    获得资源窗口后，重型 Cargo 必须经根共享 lock/watchdog，真实模型与 Docker/任何重型 Cargo 互斥，一次只加载一个模型，不绕过资源计数器或容量门。
14. **简单证据与窄测试。** 复用现有普通 JSON/hash/archive 和测试结构，新增测试只覆盖改变的资格/数值/服务行为。Python-only 资格逻辑
    不触发 Cargo；只有 real scorer/Rust 接缝实际变化才运行 `codex-publication-critic` 定向门禁；只有产品公开接缝实际变化才扩到 Plan 057 回归。
15. **工作树隔离。** Plan 071 只拥有 Publication Critic base 可比性代码、Plan 071 ignored 输出与相应测试/log。069/070 不进入本任务；
    最终只提交 Plan 071 分支并保持 clean，合并、推送、分支归档和 worktree 清理由用户另行批准。

## 4. 软性建议

以下内容用于提供高性价比起点，不是固定实现路线。执行者可依据代码和真实证据采用更优策略，并在日志中说明理由。

- 先对 Plan 068 v3 做纯计算复盘：base 的 max raw-logit drift `0.165081...` 仍低于当时 `0.25` raw gate，ranking concordance
  `0.97826...`、pair-direction preservation `1.0`，但 max projected drift 为 `0.034041...`；唯一 verdict flip 的 FP32 reference score
  `0.935057118...` 与临时 threshold `0.935056901...` 极近。最大 projected drift 则发生在远离 threshold 的 rewrite 样本；这提示
  “cross-dtype 系统差异、sigmoid 区域敏感度和 near-threshold 判定”都值得分别验证，不能把全部失败归因于单次边界翻转，也不是预定结论。
- 先分开验证“CPU FP32 与目标 CUDA dtype 的合理近似误差”和“同一 deployment runtime 的 runner/service parity”，避免用一个 absolute
  projected gate 同时回答两个问题。raw-logit/ULP-aware、score-sensitive tolerance、near-threshold guard band 或更合适的目标 runtime 都可比较，
  但必须在正式轮前给出统一、非 candidate-fitted 的选择依据。
- 若资格逻辑是唯一问题，优先只改 Python qualification/runner 并沿用现有 real scorer；若确有 worker/runtime 差异，再窄改现有 scorer seam。
  不要求为了“完整”修改 Rust 或 Docker。
- 锚点可以优先选择最能覆盖本轮改变的既有合格候选；若规则改变影响 C1/C3，则一起重验通常比论证“未受影响”更直接。C1 的完整生命周期
  和 C3 的非饱和 projected drift 可作为不同侧面的参考，但执行者可以依据阶段 A 证据选择更优组合。
- 直接复用现有 24GB 模型/checkpoint、Plan 068 env 和 v3 evidence，避免复制。旧 target/env 保留为历史复现基线；若依赖或 Rust 源码需改变，
  新建 Plan 071 专用 env/target，避免污染已验收身份。
- 测试按影响面递进：资格逻辑与 stable sigmoid 的 Python focused tests；worker/service runner 变化再加进程定向测试；Rust real scorer 变化后
  等资源窗口运行 `just test -p codex-publication-critic`。没有公共产品接缝变化时不跑 core/workspace。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已只读闭合 Plan 068 v3 的 artifact/runtime/raw/service/result 身份。base 的 CPU FP32→CUDA BF16 max raw drift 为
  `0.1650810242`，低于 v3 在 base 结果前已冻结的 `0.25` raw cap；max projected drift `0.03404159195` 是 sigmoid
  在具体 score 区域的放大。唯一 verdict flip 的 reference raw logit 位于临时 threshold raw logit 的 `0.25` 半径内；
  无半径外 stable flip。C1/C3 是同规则锚点，C2 保持历史 `NOT_QUALIFIED` 且未重验。
- 新增版本化 Plan 071 comparability/offline/observations/worker-parity 能力；Plan 068 schema 与结果保持只读。cross-runtime
  raw/envelope/near-threshold、同 CUDA BF16 fresh-worker parity、精确产品 service verdict 分层判定；service runner 通过显式
  contract 选择复用既有唯一服务体系，没有改变 Plan 054/055/057 稳定语义。
- 源码与定向测试提交 `c72edde0f6f7cdd3b944b38fc2a47dbb7ceae65e` 后保持 clean；8 条 calibration commissioning
  `plan071-commissioning-20260825T055253Z-qualification-v1` 打通 base/C1/C3 完整链路，三对象均 `QUALIFIED`。具体门限
  未按 commissioning 结果调整。
- 从新的空 namespace 完成预审 formal `plan071-formal-20260825T060132Z-qualification-v1`，绑定 clean source `c72edde...`、
  freeze canonical SHA-256 `15ff83bedc107e1004140a3fee0d9e6dd2869186910e96e130a0ba831bd141d9`、exact base/C1/C2/C3
  artifact、旧验收 service/probe/Python 程序、Plan 054 threshold/reference 与 24 条非 unseen cohort。
- 预审 formal 数值结论为 base/C1/C3 均 `QUALIFIED`、任务终态 `BASE_COMPARABILITY_GO`；C2 未重验并保持历史
  `NOT_QUALIFIED`。独立审查随后发现两个异常分支，逻辑修复与 40/40 回归已闭合；由于 source/result schema 身份改变，
  该轮降为 superseded 预审证据，不能作为最终唯一 formal，须从新的空 namespace 完整重跑。
- 三个正式对象各完成 24 条 CPU FP32 reference、CUDA BF16 deployment、fresh-worker parity、18 次真实 service verdict
  调用、15/15 stress 和 clean shutdown；C1 另完成 cancel/post-cancel ready/review。所有正式 watchdog 均
  `stop=none / cleanup=none / swap=0`，最终 GPU compute process 为 0。
- 受影响 Python 定向测试 40/40、compileall 与 `git diff --check` 通过。没有 Rust 源码变化，故未运行 Cargo；Docker、HF 下载、
  真实 API、远端操作和 unseen-test 均未运行。

### 当前工作

- 修复后的 clean source checkpoint 为 `90ce6ba5eb3ba3faa3ffa4db41934c1147e18653`。唯一有效正式轮
  `plan071-formal-20260825T064600Z-qualification-v5` 从新的空 namespace 完整运行，freeze canonical SHA-256 为
  `02fbb85d9eb3c76a6761fd86b495d46a01720e13ced4fbac0b74e3cd8e831616`；base/C1/C3 均为 `QUALIFIED`，任务终态为
  `BASE_COMPARABILITY_GO`（`base_and_anchor_qualified`）。C2 未重验并保持 Plan 068 历史 `NOT_QUALIFIED`。
- v2 因更新后的 069 资源交接要求在首个对象结果产生前主动中止；v3/v4 分别因非 canonical watchdog override 和相对 wrapper
  路径被 production proof 在模型加载前 fail-closed。三轮均有 `abort.json`、不属于正式证据，且未被 v5 聚合引用。
- v5 三对象各覆盖 24 条 offline reference/deployment、fresh-worker parity、18 次真实 service 调用、15/15 stress 与 clean
  shutdown；C1 cancel/post-cancel recheck 通过。三个 canonical watchdog 均 `status=0 / stop=none / cleanup=none`，模型、GPU
  compute 与 scope 已全部退出，Plan 071 后续不再占用重型资源。

### 本任务剩余步骤

1. 更新本计划与精炼执行日志，完成轻量定向门禁并提交 clean 分支。
2. 通过既有 queue 机制交最终独立验收；范围内 finding 自主修复并重新交接。

### 阻塞项

- 无实现或资源阻塞。用户明确把重型资源所有权切换给 071 后，v5 才进入真实模型；069 等待且 072 未占用 canonical heavy lock。
  v5 终态核验已确认 Cargo/rustc/nextest、Docker task、模型 service/worker、GPU compute 与 `rondo-build` scope 均不存在，重型资源槽已释放。

### 当前验收状态

- `FORMAL_COMPLETE_REVIEW_HANDOFF_PENDING`

### 交接边界

- `BASE_COMPARABILITY_GO` 经独立验收后，只允许后续基于最新 main 更新 WBS 中的 M3-C2 规划前置；不自动启动、授权、合并或启用 M3-C2。
- `BASE_NOT_COMPARABLE` 或 `INCONCLUSIVE` 经独立验收后，按证据把三期继续锁定并指出返回的部署/基础设施能力；不在本计划安排新训练、C2 修复或替代模型。
- 本任务完成后冻结此计划；跨任务后续只链接 WBS，不在本计划继续维护。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 071 使用全新工作树，不复用 068 工作树作为可写实现现场 | Plan 068 正式 manifest 绑定旧路径下已验收 service/probe 二进制；保留旧 worktree/target 可避免新构建覆盖历史复现基线，同时根 `eval-data/` 重资产仍可直接复用 | Git/worktree、历史复现、磁盘 | 已采纳 |
| 002 | Plan 068 模型、checkpoint、v3 evidence、serving env 与旧 target 全部只读保留 | 远端副本已永久删除，且 base 修正、候选锚点与未来恢复仍依赖这些唯一/有价值资产；复制整套资产没有收益 | ignored 资产、复现与恢复 | 已采纳 |
| 003 | Plan 071 把 cross-runtime 数值可比性、deployment 内部 parity 与产品 verdict 分层判断 | v3 已显示 raw drift、sigmoid 后 drift 和 near-threshold flip 可能回答不同问题；混成单门会妨碍正确归因 | 资格 schema、runner、正式 freeze | 已采纳 |
| 004 | C2 不进入本任务重验；C1/C3 只按共享影响承担锚点/回归 | C2 的 Plan 068 失败是 ranking/direction 模型能力，不是 base 部署可比性缺口 | 正式运行范围、资源 | 已采纳 |
| 005 | cross-runtime 沿用 Plan 068 在 base 结果前已冻结的 `0.25` raw-logit cap；projected 层用该 cap 经 stable sigmoid 导出的逐行 envelope，并把同一 raw 半径作为临时 threshold guard | 该方法不从 Plan 071 base 结果贴线；它把 dtype raw 误差、sigmoid 区域敏感度和近阈值放大分开，同时对 base/C1/C3 一致应用 | Plan 071 freeze、比较与三态结论 | 已执行 |
| 006 | 同 CUDA BF16 offline→fresh worker 继续使用独立 `0.005` projected / `0.25` raw 门，产品 service 仍按 descriptor exact threshold 判 verdict | Plan 068 fresh-worker commissioning 给出独立部署重复性依据；资格 guard 不得改变产品 verdict | worker parity、service parity | 已执行 |
| 007 | 共享资格逻辑变化后正式覆盖 base、C1、C3 全部受影响门；C1 承担 cancel recheck，Plan 068 v3 完整 failure/restart matrix 不机械重跑 | C1/C3 分别覆盖饱和与非饱和 score 区域；既有 failure matrix 与 Rust 服务边界未变化 | 正式对象与生命周期范围 | 已执行 |
| 008 | 继续只读复用 Plan 068 已验收 env、service/probe 二进制和 24GB 工件，不修改 Rust、不建新 env、不使用 Docker | commissioning 与正式链路均证明 Python-only 资格修正足以闭合，扩大构建或复制没有功能收益 | 依赖、磁盘、门禁范围 | 已执行 |
| 009 | `plan071-formal-20260825T060132Z-qualification-v1` 仅保留为 superseded 预审证据；修复异常分支并把 result schema 升为 v2 后，从新 clean source 和空 namespace 完整重跑 | 独立审查发现失败 warm review 计数和无合格锚点终态两个异常分支；数值 GO 未被推翻，但正式 program/result 身份已改变，不能沿用旧 archive 改算 | 正式证据、schema、重跑 | 已执行 |
| 010 | v2/v3/v4 作为有原因、不可续用的 aborted namespace 保留；仅 v5 是最终 formal | v2 遵守更新后的跨任务终态门主动中止；v3/v4 由 production proof 在模型加载前拒绝。用新 namespace 重跑可避免把基础设施失败或零散进度混入正式身份 | 资源交接、正式证据、运行身份 | 已执行 |
