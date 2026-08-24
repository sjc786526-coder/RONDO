# Plan 068：M3-C1 Publication Critic 本地部署资格与候选交接 ExecPlan

> 本计划是 M3-C1 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认；普通下载续传、依赖、格式、转换、加载、显存、
> launcher、服务、测试和局部兼容问题应在范围内自主修复并按需重跑。
> 本计划只描述 M3-C1；M3-C2 的横评、最终选择与正式 threshold，以及跨任务路线、顺序和依赖，以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

安全接收并核验 Plan 066 交付的 exact base、C1、C2、C3、正式 C3 full checkpoint 和必要运行身份，在当前
RTX 4060 Laptop 8GB / WSL 目标环境中形成真实可运行的 Publication Critic 部署工件；把真实模型 scorer 接入 Plan 055
已经冻结的服务边界，并保持 Plan 057 的默认关闭、rewrite、fallback、取消和唯一 store commit 语义不变。

本任务分别判断 base、C1、C2、C3 是否具备本地部署资格，验证原始候选到实际部署工件之间的 score/direction/verdict
漂移、离线 runner 与正式服务 runtime 的一致性，以及 2–8 Agent 小团队场景所需的有界资源、延迟、稳定性和 typed failure。
本任务只给资格结论，不排名候选、不选择最终模型、不冻结正式产品 threshold 或最终运行配置。

完成本地回收、真实加载、正式资格运行和独立删除前复核后，删除唯一 Plan 060/066 task-only winner 卷，确认相应 RunPod
Pod 与卷持续费用归零。不可逆删除只有这一处强制中途复核门，不扩张成通用资产审计流程。

### 完成/验收标准

- [ ] 从当前 Plan 068 worktree 实施，只提交该任务分支并保持 clean；不合并、推送、归档分支或删除 worktree。
- [ ] 现场核对 RunPod 当前为 0 Pod，winner Standard 60GB 卷精确为 `hi3iaz8rsr`、位于 `US-KS-2`、仍只承载
      Plan 060/066 工件；历史 receipt 不能代替当前 provider 事实。
- [ ] 通过不创建 Pod 的既有只读传输面回收卷内独特工件；若已有 RunPod S3 凭据或同等已授权入口不可用，则保留卷并把任务标为
      `INCONCLUSIVE`，不得创建 transfer Pod、Endpoint、Job、S3 key 或其他云资源绕过边界。
- [ ] 本地安全保存并逐文件验证 C1/C2/C3 三个完整 model-only candidate、正式 `checkpoint-c3` 完整树、exact base 九文件、
      source bundle/recipe/model contract、candidate/checkpoint manifests、dependency identity/freeze、FlashOptim wheel、winner lock、
      provider facts 与必要小型 receipt/log。可复建环境身份是硬要求，整棵远端 venv/cache 仅在确有必要时保留。
- [ ] base、C1、C2、C3 的原始候选身份、实际部署工件身份、tokenizer/input/scalar identity 和转换关系均明确；四者都完成真实
      结构核验与目标环境加载尝试，不能把最后 checkpoint、文件名或服务自报身份当作候选身份。成功加载是 `QUALIFIED` 的必要条件；
      在有效环境中可复现的候选自身加载失败可以形成 `NOT_QUALIFIED`，不得伪造成成功加载。
- [ ] 阶段 A 先冻结资格维度、原始参考方法、cohort 选择规则、临时 threshold 来源、三态定义和禁止为候选倒推口径的规则；代表性
      commissioning 完整打通后、四对象正式资格轮之前，再冻结具体 cohort、candidate/deployment artifact、runtime 配置以及数值漂移、
      方向/排序、verdict、资源/延迟/稳定性门。所有数值可复算并有工程理由，但不冒充 M3-C2 的最终评价或产品配置。
- [ ] Plan 054 的完整 candidate、两消息 render、exact tokenizer、16,384 window、whole-continuity omission、`logits[:,0]`
      higher-is-better 与 stable sigmoid `[0,1]` 语义保持不变；raw scalar 单值且有限。
- [ ] 对每个发生格式转换、量化、dtype 或其他部署适配的候选，以其未适配原始工件为参考，在同一冻结 cohort 上验证 raw/projected
      score、方向、必要 pair 排序和临时 verdict 漂移满足正式轮前冻结口径。若原始工件本身即部署工件，则明确记录无转换并验证同身份重跑一致性，
      不伪造“量化已验证”。
- [ ] base/C1/C2/C3 中每个拟判 `QUALIFIED` 的对象，至少用一组同输入完成离线 runner 与真实 scorer/service runtime 的
      verdict parity 和 bounded call；数值一致性在内部 scorer/资格 runner 层验证，raw score 不新增到产品 wire、Team State 或普通日志。
- [ ] 至少一个训练候选通过真实 Plan 055 服务路径完成完整的启动、liveness/ready、代表性并发/排队、取消、typed backend failure、
      graceful/forced cleanup 与关闭矩阵；共享 backend 的完整矩阵无需对四对象机械重复，但无孤儿 worker、残留监听、失效容量或正文泄漏。
- [ ] base、C1、C2、C3 分别得到 `QUALIFIED`、`NOT_QUALIFIED` 或 `INCONCLUSIVE`，并记录 load time、warm latency（至少
      P50/P95/max 或等强小样本汇总）、RSS、显存、稳定性、失败/取消和采用的有界并发配置。各指标按对象实际到达阶段记录；无法加载或
      未到相应阶段的指标标为 `N/A` 并绑定原因，完整运行指标只对 `QUALIFIED` 必需。有效候选失败不通过反复调参掩盖。
- [ ] base 对照和至少一个训练候选在同一资格口径下 `QUALIFIED`，且至少一个训练候选能稳定处理有界 publication，才可解除
      M3-C2 前置；若不满足，则停止模型选择链并指出需要返回的上游能力，不在本任务中改权重、数据或产品语义。
- [ ] unseen-test 未导出、未读取、未运行，也未用于格式、量化、threshold、资格或候选决策；资格 cohort 不冒充最终模型质量横评。
- [ ] 调试链完整打通后，冻结 candidate/deployment artifact、代码、依赖、资格配置与 cohort，从 clean tracked source 和新的正式输出
      namespace 对 base/C1/C2/C3 完整运行一轮；调试结果、不同配置或零散重跑不得拼接成正式资格结果。
- [ ] 运行相称的 Publication Critic Python pure/fake tests、受影响 Rust crate 的 format/fix/定向 tests、配置/lock/生成物检查、真实模型
      资格 runner 和 `git diff --check`；未运行、skip、受控 scorer、真实模型和 Docker 证据分别表述，不运行无关全 workspace。
- [ ] 删除卷前，执行者形成 clean 本地提交并交计划制定者做一次独立只读复核；只有收到 `LOCAL_HANDOFF_ACCEPTED` 后才可在用户转交
      执行提示词后生效的一次性授权内删除精确卷 `hi3iaz8rsr`。finding 可自主窄修、重跑并重新交接，不需要另行申请删除授权。
- [ ] 删除后立即确认目标卷不存在、Pod 仍为 0，Plan 060/066 的 compute 与 volume 持续费用均为 0；若出现无关资源，只报告而不删除。
      更新本计划状态和一份精炼日志，提交最终 task branch，接受最终独立验收。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 内职责清晰的 Plan 068 部署、真实 inference worker/backend、资格 runner、转换/工件验证、
  归档与 launcher 能力；职责契合时复用 Plan 054 实现，不把冻结 Plan 054 runner 强行改成多任务框架。
- `eval/environments/publication-critic-plan068/` 等任务局部 inference-only 依赖合同、必要 lock，以及
  `eval/tests/test_publication_critic_*` 的 pure/fake/focused 回归。
- `multidev/codex-rs/publication-critic/` 内真实 `PublicationScorer` adapter、专用 real-service binary/launcher、最小 failure
  适配和定向测试；可复用现有 `serve()`、typed client、descriptor、资源与生命周期合同。
- 只有 live 接缝确实不足时，窄改 `multidev/` 的 Publication Critic 配置/产品接缝及相应 tests/schema；不得以“方便”为由改写
  Plan 057 产品状态机。Cargo/Bazel/config 生成物和锁文件仅随真实依赖或 schema 变化机械更新。
- 小型 tracked 的资格配置、manifest schema、正式聚合结果、使用说明、`rondo.secrets.example.env` /
  `rondo.local.example.toml` 示例接口（仅当真实实现需要）、本计划状态、一份精炼 `agent_log` 和必要稳定资产布局说明。
- 主物理仓库根的 ignored `eval-data/publication-critic/plan068/`、`eval-data/models/publication-critic/` 与任务专用 env/cache
  namespace，用于下载、原件、转换工件、运行环境、调试/正式结果和本地交接；具体子布局可由执行者按职责调整，但必须与既有资产隔离。
- 当前 ignored `rondo.local.toml` 中非密钥的 Plan 068 本机参数（若实现采用该入口）；更适合任务专用 ignored 配置时可自主选择，
  不强迫复用 RONDO Local approval 的模型语义。
- 对 RunPod 进行当前资源/费用/卷 identity 的只读查询；使用已有凭据通过官方 S3-compatible API 或其他无需新计算资源的既有安全入口，
  只读列举并下载 `hi3iaz8rsr` 的必要对象；删除前复核通过后删除该 exact task-only 卷，并复查资源终态。
- Hugging Face 只允许 `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`
  的公开、只读、exact-revision 下载/校验，用于补齐或验证 exact base；优先复用并校验现有本地 cache，不登录、不写 Hub。
- 必要时使用一个明确的 task-only Docker image/container；它只是本地部署手段，不是默认路线，必须遵守根资源门并只清理本任务创建对象。
- 普通依赖和公开只读源码/文档下载；当前 RTX 4060 Laptop / WSL 环境中的模型转换、量化、加载、真实本地推理与有界资格运行。

### 不允许修改或执行

- Plan 054 输入/render/tokenizer/window/raw scalar 语义，Plan 064 v8 内容/label/pair/split/review/manifest，Plan 066 训练权重、
  checkpoint 内容或训练事实；不得重新训练、继续训练、改权重、生成数据或用 validation/unseen-test 做梯度更新。
- Plan 055 服务协议的 verdict/identity/typed failure 信任边界，或 Plan 057 的默认关闭、rewrite/fallback/cancel/store commit 语义；
  如确需改变这些稳定产品语义，应停止并返回上游决策，不能在部署层静默改变。
- 最终候选排名、最终产品 threshold、最终运行配置选择、默认启用 Critic、M3-C2 横评、M3-D 端到端收益或 M4-A Durable Runtime 能力。
- 新建/启动/恢复任何 RunPod Pod、Job、Endpoint、Serverless worker、网络卷或其他云计算/存储资源；创建或轮换 RunPod/S3 凭据；
  HF Jobs/Endpoint/Space/Repo/Bucket、任何远端上传/发布、真实 API、付费模型调用、上游 Codex 基线升级。
- 删除 `hi3iaz8rsr` 以外的本地或远端对象；删除唯一卷前不得远程改写、移动或“试清理”其内容。
- 修改、读取或依赖 Plan 067/M4-A worktree 的未提交或 ignored 现场，修改其 plan/log 或 Durable Team Session、控制面、writer binding 语义。
- 无关全 workspace 测试、CI/PR、合并、rebase/push `main`、推送任务分支、归档/重命名分支或删除 worktree。

### 不允许读取/查看

- `.env.local` 内容、RunPod/S3/HF token、access key、secret key、私钥、密码或个人配置。只可通过项目安全入口静默检查任务所需变量
  是否存在且非空；不得 source、打印、复制、哈希、写入命令行/日志/receipt 或转交子智能体。
- 与任务无关的项目外个人文件、其他仓库和来源不明 ignored 资产。
- unseen-test 正文或其投影；与部署资格无关的真实 publication/transcript/private reasoning、Fact observation、raw evidence 或训练监督正文。

### Git-ignored 与主工作区边界

tracked 代码、合同、测试、文档和日志全部在
`/home/sjc/desktop/RONDO/.claude/worktrees/068-m3-c1-publication-critic-local-qualification/` 修改并提交；主工作区不得产生 tracked 修改。

linked worktree 不共享主根 ignored `eval-data/`、`.env.local` 和 `rondo.local.toml`。因此候选/checkpoint 下载、转换工件、任务环境、
cache、调试和正式运行原始结果必须直接落在主物理仓库根的 Plan 068 ignored namespace；若需机器配置，也直接使用主根 ignored 配置。
执行者每次交接必须列出本任务实际创建/修改的 ignored 路径、大小、权限与保留状态，不进入其他 Plan namespace，不清理来源不明资产。

## 3. 硬约束

以下约束只冻结上游语义、资格结论、不可逆交接、并行安全与诚实证据，不预先锁死部署格式、量化方案、runtime、worker IPC 或模块布局。

1. **四个固定资格对象。** 资格集合固定为 exact base 和 Plan 066 正式 C1/C2/C3；base revision/九文件 hash、三个 candidate manifest、
   正式 checkpoint manifest 与 Plan 066 final facts 是交接依据。不得替换底模、合并候选、修改权重或把 C3/checkpoint 自动称为 winner。
2. **Plan 054 是唯一输入和 scalar 语义。** 正式 scorer 接收 Plan 055 typed `PublicationPacket`，必须复用或等强调用现有两消息 render、
   exact tokenizer、candidate 不截断、16,384 window 与 whole-prior omission；raw `logits[:,0]` 无界 higher-is-better，经同一 stable sigmoid
   投影到 `[0,1]`。格式改变不能成为重新解释 pooling、方向或 projection 的理由。
3. **资格不是选择。** 阶段 A 先固定判断维度、参考方法、cohort 选择规则、临时 threshold 来源、三态定义和禁止倒推口径的规则；允许用
   代表性候选完成 commissioning 并据实际目标环境制定有工程依据的数值。具体 cohort、runtime 和漂移/资源/延迟/稳定性门必须在四对象正式轮前
   冻结且同口径，之后不得为某候选取得通过而放宽；全程不依据 unseen-test。Plan 054 calibration threshold 可作有来源的临时起点，
   但不是强制实现，也不是最终产品 threshold。
4. **三态结论可操作。** `QUALIFIED` 表示候选在有效基础设施下满足已冻结的身份、漂移、服务、资源和稳定性门；
   `NOT_QUALIFIED` 表示候选本身在有效运行中不满足门；`INCONCLUSIVE` 表示凭据/传输/依赖/宿主资源/计数器等基础设施不足以判断。
   四个对象均须有结论；不得把 infra failure 写成模型不合格，也不得把 skip 写成通过。
5. **转换前后要有真实参考。** 发生转换/量化/精度变化时，必须先用未适配候选在同一输入合同上取得可比较参考，再评部署工件；
   口径至少覆盖单值有限性、higher-is-better、projected drift、稳定排序/明显 margin 和临时 verdict。具体统计与数值在代表性
   commissioning 后、四对象正式资格轮前冻结，
   不机械继承 Plan 054 同 FP32 parity 的 `1e-4` 为量化总门。无法取得可信参考时结论是 `INCONCLUSIVE`。
6. **复用唯一产品服务边界。** 真实模型只替换 Plan 055 的 scorer backend；正式产品调用仍经过现有 loopback transport、expected descriptor、
   identity 校验、有限 queue/deadline、typed verdict/failure、取消和关闭。可以增加 Publication Critic 专用 worker/launcher，不能另建第二套通用模型
   服务或让部署 backend 自己解释 raw `team_publish`。
7. **runner/runtime 一致但不扩产品协议。** 离线资格 runner 与正式 scorer 应尽量共享 render/tokenizer/projection/inference core；同输入 verdict
   必须一致，数值偏差服从正式轮前冻结门。raw/projected score 只留在权限合适的 0600 资格结果，不进入产品 wire、Producer/Root、Team State 或普通日志。
8. **先打通，后正式。** 阶段 B 可保留已验证下载、原始候选、转换 cache 和局部进度，从未打通处自主修复/续传/重跑；先用小 cohort 和单候选
   打通 load→offline score→real service→typed client→cancel/shutdown 全链。四对象都覆盖身份、转换、加载尝试与 offline 资格；每个拟判
   `QUALIFIED` 的对象至少完成一次 bounded service parity，完整 failure/cancel/shutdown 矩阵只需一个代表性训练候选承担。只有全链稳定后才固定
   source、依赖、工件、资格配置和 cohort，从 clean tracked source 与新正式目录运行完整阶段 C。正式配置或工件改变后，应重跑受影响的完整正式资格轮。
9. **有效失败保留，窄故障可恢复。** 普通网络中断、S3 502/timeout、依赖、转换、OOM 参数、launcher、worker、服务和测试问题可在身份不变时
   续传、自主修复并合理重跑，不设置机械次数上限；候选在有效口径下的真实漂移、方向、资源或稳定性失败必须如实保留，不能通过反复搜索实现/门槛掩盖。
10. **资源适合小团队且始终有界。** 所有真实本地模型加载/推理和可能的 Docker、重型 Cargo 共用根 heavy lock/watchdog 并全局串行；一次只加载
    一个 candidate，真实 scorer 默认单 GPU 有界执行。记录当前硬件、load/RSS/VRAM/latency/failure；用代表性的 1/2/4/8 调用压力或等强有界场景判断
    2–8 Agent 适用，不扩张成大型 benchmark，也不为通过无界放大 timeout/queue。
11. **数据隔离。** 可使用 Plan 054 已冻结且明确 `future_unseen_test=false` 的 representative/boundary fixtures，以及阶段 A 明确允许的机械边界输入；
    不使用 v8 unseen-test。validation 若确需作为无标签部署输入，必须在阶段 A 明示且不得据其调权重、排名候选或冻结最终 threshold；更简单的等强 cohort
    应优先，避免把 M3-C1 变成 M3-C2。
12. **远端只读交接与最小凭据。** RunPod MCP 只负责现有 Pod/卷等资源状态与最终精确删卷，S3-compatible API 负责卷内文件列举和下载；普通
    `RUNPOD_API_KEY` 不是项目本地交接硬依赖。下载只针对 exact 卷 `hi3iaz8rsr`，不做无界递归列举、不记录 credential，不把 S3 access
    扩张为远端重组或清理。既有安全入口失效、卷 identity/路径无法闭合或出现其他使用方时停止，保留卷并请求用户决定。
13. **唯一卷的删除门。** 删除前须完成本地逐文件 bytes/hash/结构校验、base+C1+C2+C3 的真实加载尝试与有效三态结论、完整 checkpoint
    tree/metadata/state 验证、依赖/recipe/receipt/winner lock 交叉绑定、正式资格结果以及独立 `LOCAL_HANDOFF_ACCEPTED`。成功加载只对
    `QUALIFIED` 对象是硬要求；若某对象在有效目标环境中可复现地加载失败并据此得到 `NOT_QUALIFIED`，不单独阻止卷删除。若失败可能来自
    本地副本缺失、损坏或身份未闭合，则必须保留卷。删除只针对已解析 exact ID，不使用名称模糊匹配；删除后只读确认卷消失、0 Pod 和 task 持续费为零。
14. **M4-A 与 Git 隔离。** Plan 068 拥有真实 Critic scorer、本地部署/资格、ignored 工件和 winner 卷交接；Plan 067/M4-A 拥有 Durable Session、
    生命周期、控制面共同边界及其 plan/log。两者不读写对方现场；真实模型/Docker 与 M4-A 重型 Cargo/Docker 串行错峰。共享 WBS、锁文件或外围配置最终由
    后整合者基于最新 main 窄合并，不用旧文件覆盖另一任务事实。
15. **相称测试和简单证据。** 只扩展既有正确性测试与轻量资格归档，普通 manifest/hash/JSON/Markdown 足够；不建设签名链、数据库、PKI、
    数据资产审计、可信平台、模型 registry 或通用 supervisor。真实权重测试不进入默认无权重 test suite；fake/受控与真实模型证据分开。
16. **安全配置与外部边界。** `.env.local` 只按根合同静默检查，严格数据解析并只向目标子进程注入所需变量；非密钥参数放任务 ignored config
    或 `rondo.local.toml`。HF 只读命令必须指定 exact revision 与项目局部 cache，禁止 upload/login。若使用 Docker，完整遵守根 Docker 容量计数、串行、
    单镜像/容器和 task-only cleanup；若不需要则不为形式引入 Docker。
17. **任务交付止于本地分支。** 执行者更新本计划状态/关键决策与一份精炼日志，审查 tracked/ignored diff、权限、体积、敏感边界和所有 worktree 状态，
    形成少量 clean 提交。WBS 最终状态与 WBS-COMPLETED 历史只在独立验收及用户批准主线整合时基于最新 main 窄同步；执行者提供精确建议 delta，
    不争写并行 M4-A 的共享文档。

## 4. 软性建议

以下建议基于 `main@273042f3f26d8f9a22d774fa72858ebf413c122e` 的 live 设施，不是验收门；执行者可依据实测、维护成本和更优架构采用
等强方案，审查者不得把本节偏好升级为硬约束。

- 优先复用 Python `eval/rondo_eval/publication_critic/` 的 contract/render/tokenization/scoring/Transformers backend，以及 Rust
  `codex-publication-critic` crate 的 `PublicationScorer`、`serve()`、client、descriptor 和生命周期。最自然的新增能力是 Critic 专用长驻
  inference worker + 现有 Rust service adapter；若同进程 Rust runtime 或其他方案更干净，也可自主选择。
- Plan 057 已把服务视为 externally managed loopback service，通常无需修改 core/team-state。任务 launcher 可以拥有真实服务/worker 生命周期，
  不必建设 daemon manager、服务发现、TLS 或鉴权平台。
- Plan 054 CPU env 和 Plan 066 H100 training env 都不应冒充 RTX 4060 serving env。可建立小型 inference-only 项目局部 env；远端 venv/cache
  只作重建线索，保留 dependency freeze 和独特 wheel 通常比整棵复制更有价值。
- 原始 BF16 safetensors 若能直接满足 8GB 资源和延迟门，可作为部署工件，不强迫量化；若必须转换/量化，格式由 scalar parity、显存、延迟、
  lifecycle 与维护成本共同决定。不要因为 RONDO Local 曾用 GGUF/llama.cpp 就默认 Skywork sequence-classification 也必须走同一路线。
- 可先使用 Plan 054 的 24 条 representative/boundary fixtures 与两个 product-cap mechanical cases，并在正式前冻结一个小而足够的 cohort。
  漂移判断可结合绝对/分位 score 差、相关/方向、明显 margin pair 和 threshold 邻域；阈值邻域样本应单列，不必把合理的边界翻转等同大幅语义漂移。
- 当前 Plan 055 production defaults 是 scorer concurrency 1、queue 4、job 25s、client 30s、startup 60s。Plan 068 可以基于 4060 冷启动/16k
  实测选择任务资格用的有界值并写入 descriptor；最终值仍留给 M3-C2。
- 三候选约 3.46GB/个，checkpoint 约 10.56GB，加 exact base、临时下载与转换预计至少需要约 24.4GB 原始资产空间。下载前先以真实目标路径和
  Windows `C:` 实际余量做容量预检，允许内容寻址/硬链接等安全去重，但不能因此破坏各 manifest 的逻辑完整性。
- US-KS-2 exact endpoint 的 `HeadBucket` 与两层有界、非递归 `ListObjectsV2` 已在不启动 Pod 的情况下真实通过；后续可用项目范围内的
  boto3、AWS CLI 或更合适的兼容客户端按已验证 manifest 下载，路线不锁死。大文件允许续传或合理重试，但不得把已通过的可达性探测冒充下载完成。
- Hugging Face exact base 兜底可使用 `hf download ... --revision e51ea3... --cache-dir <project-local>`，随后用 tracked 九文件 hash 和
  `hf cache verify` 或现有 verifier 复核；现有本地 exact snapshot 若完整则不重复下载。
- 不要求四个候选重复整个 Plan 055/057 故障矩阵。候选差异由资格 runner 全覆盖；共用 backend/协议的生命周期与 failure 矩阵可由既有受控测试加
  一条真实候选闭环承担。真实取消若底层 CUDA forward 不可中断，可通过有界 worker 终止/重建或等强策略保证不留下脱管工作。
- 资格结果保持简明：每候选一份身份、部署适配、漂移、资源、服务事实和三态结论，加一个总表即可。不要把 Plan 054 的完整 calibration/slice
  历史系统复制到本任务，也不要把运行细节堆到 WBS。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 规划基线已核对：`main = origin/main = 273042f3f26d8f9a22d774fa72858ebf413c122e`，主工作区 clean；Plan 060
  `TECHNICAL_GO`、Plan 064 `DATA_GO`、Plan 066 `COMPLETE / ACCEPTED / GO`。
- Plan 066 仓库证据记录 0 Pod；winner 卷 `hi3iaz8rsr` 保留 exact base、C1/C2/C3、正式 `checkpoint-c3`、可复建依赖/环境。
  这是历史交接事实，实施时仍须现场复核。
- 已核对 Plan 054 输入/scalar、Plan 055 service/scorer/typed failure/lifecycle、Plan 057 产品接入和 Plan 066 candidate/checkpoint manifests；
  当前真实缺口是 real scorer/backend、RTX 4060 部署工件、资格 runner/launcher 与本地回收，不是重写产品协议。
- 阶段 A 的 RunPod/S3 可达性已真实验证：已鉴权 RunPod MCP 只读确认 0 Pod、唯一 Standard 60GB 卷 `hi3iaz8rsr`
  (`rondo-plan060-pcie-assets-20260824`, `US-KS-2`)；未创建、启动、修改或删除任何资源。
- 用户已在主仓库根 ignored `.env.local` 安全提供 `RUNPOD_S3_ACCESS_KEY_ID` 与 `RUNPOD_S3_SECRET_ACCESS_KEY`。分支线程只经严格解析器静默确认
  普通文件/非 symlink、`0600`、合法 `KEY=VALUE` 及两值非空；未 source、打印、复制或记录凭据。tracked 示例只声明这两个变量名。
- 使用 exact endpoint `https://s3api-us-ks-2.runpod.io/`、卷 ID bucket、SigV4 与 path-style，真实 `HeadBucket` 通过；随后只做两层有界、
  非递归 `ListObjectsV2`，确认交接根 `rondo-plan060-publication-critic-20260824t040742z/` 及预期 bundle/model/runs/venv/wheels 等入口可见。
  未递归扫描、下载、校验、上传或删除对象；详情见 `agent_log/2026-08-24-105210-plan068-s3-reachability.md`。
- 已明确控制面/数据面分工：现有 RunPod MCP 负责资源查询和最终删卷，项目内 S3 client 负责文件交接；普通 `RUNPOD_API_KEY` 不作为本任务
  `.env.local` 硬依赖，执行者不得为此读取 MCP 的 OAuth/API credential 或创建新 key。
- 专用 worktree 已建立：
  `/home/sjc/desktop/RONDO/.claude/worktrees/068-m3-c1-publication-critic-local-qualification/`，分支
  `worktree-068-m3-c1-publication-critic-local-qualification`。

### 当前工作

- `IN_PROGRESS / STAGE_A_REACHABILITY_VERIFIED`：一次性授权已用于完成最小只读可达性探测和凭据变量示例；候选下载、本地身份验证、
  真实模型部署/资格和卷删除均未开始。用户转交本计划的更新提示词后，执行者从剩余阶段 A 工作继续。

### 本任务剩余步骤

1. 阶段 A：保留已验证的 0 Pod/winner 卷/S3 可达性事实；核对本地硬件与真实 Windows `C:` 容量，从 Plan 060/066 identity、manifest 和
   receipt 闭合必须下载的精确路径/文件，先做有界试下载与恢复验证；冻结资格维度、参考方法、cohort 选择规则、临时 threshold 来源、
   三态定义和禁止倒推口径的规则。
2. 阶段 B：下载并验证必要原始资产，建立或复用干净的本地部署能力；先打通一个候选，再覆盖 base/C1/C2/C3 的身份、转换、加载尝试、
   offline 资格与定向 tests，每个拟 `QUALIFIED` 对象完成 bounded service parity，完整 failure/cancel/shutdown 矩阵只由代表性训练候选承担。
   普通问题在范围内修复重跑；代表性 commissioning 稳定后、四对象正式轮前冻结具体 cohort、artifact、runtime 配置和数值
   漂移/资源/延迟/稳定性门，此后不得按候选放宽。
3. 阶段 C：固定代码、依赖、候选/部署工件和资格口径，从 clean source/新 namespace 完整运行四对象正式资格轮，生成三态决策和精炼资源/漂移/服务结果。
4. 阶段 D1：提交 clean 的本地交接 checkpoint，列出 tracked/ignored 工件、测试、正式结果与当前 provider 事实，停止在卷删除前，交计划制定者独立复核。
5. 阶段 D2：收到 `LOCAL_HANDOFF_ACCEPTED` 后删除 exact winner 卷，复核 0 Pod、目标卷不存在和任务持续费归零，更新 plan/log、提交 clean final checkpoint，
   交最终独立验收。

### 阻塞项

- 当前没有 RunPod S3 凭据、网络或无 Pod 可达性阻塞；若既有安全入口后续失效，仍须保留卷并诚实转为基础设施阻塞，不得创建 key 或 Pod 绕过。
- winner 卷交接根已通过有界列表定位，但必须下载的精确文件集合尚未由 Plan 060/066 manifest/receipt 闭合；不得仅凭目录名猜测或无界递归下载。

### 当前验收状态

- `STAGE_A_PARTIAL_PASS`：资源 identity、S3 凭据安全入口、`HeadBucket` 和有界目录可见性已通过；这不是候选交接或阶段 C 正式资格证据。
  尚未下载/校验候选，未运行真实模型/Docker/Cargo，未形成任何候选资格结论；winner 卷仍保留并持续计费。

### 交接边界

- 阶段 D1 是唯一不可逆操作前停点：执行者提交并保持 clean，计划制定者只读检查本地副本、正式资格和删除门。普通 finding 修复后可重复交接；
  `LOCAL_HANDOFF_ACCEPTED` 只批准按既有用户授权删除 exact 卷，不是 M3-C2 或产品启用授权。
- 任务完成后冻结本计划。只有 base 与至少一个训练候选在同一口径下 `QUALIFIED` 才解除 M3-C2 前置；M3-C2 仍须按 WBS 另行规划和授权，
  不自动启动。若不满足，则只交回失败能力和事实，不在本计划继续安排返工路线。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 固定资格集合为 exact base、C1、C2、C3，并逐一给三态结论 | 训练已交付三个阶段候选，M3-C1 需要部署资格而非默认最后 checkpoint 胜出 | 候选、结论 | 已采纳 |
| 002 | 阶段 A 冻结判断维度、参考方法与口径推导规则；代表性 commissioning 后、四对象正式轮前冻结具体 cohort、runtime 和数值门 | 允许先打通真实目标环境再制定有工程依据的门，同时防止按候选倒推或把 M3-C2 最终选择过早固化 | 资格口径 | 已采纳 |
| 003 | 真实模型只替换 Plan 055 scorer backend；Plan 057 产品状态机和 wire 不承载 raw score | 现有服务/产品边界已完整，新增缺口是模型计算和部署而非第二套协议 | 架构、产品 | 已采纳 |
| 004 | 调试可保留有效进度并自主修复，正式证据只接受全链打通后的 clean 完整轮 | 避免过早冻结造成整组返工，也避免拼接不同身份的调试结果 | 执行、验收 | 已采纳 |
| 005 | 转换/量化不是强制路线；原始工件若满足 8GB 资格可直接部署，否则由执行者选择更优适配 | 资格目标是可运行且语义保持，不是预设某种格式 | 部署格式 | 已采纳 |
| 006 | 重资产只落主物理根 ignored Plan 068/model/env namespace，tracked 工作只在 068 worktree | linked worktree 不共享 ignored 资产，且权重/checkpoint 永不入库 | 数据、Git | 已采纳 |
| 007 | winner 卷删除前必须由计划制定者做一次独立本地交接复核；通过后无需再次申请用户删除授权 | 删除唯一远端副本不可逆，而用户要求执行提示词一次性覆盖验收后的任务内止费 | 远端生命周期 | 已采纳 |
| 008 | 现有 RunPod MCP 负责资源状态/最终删卷，既有 S3 credential 和无 Pod S3 API 负责文件交接；普通 `RUNPOD_API_KEY` 不作为项目本地交接硬依赖 | 真实 HeadBucket/有界 list 已验证两条能力边界，无需创建 transfer Pod、S3 key 或其他云资源 | RunPod、凭据 | 已验证 |
| 009 | M4-A 只共享资源互斥与主线整合边界，不成为 Plan 068 产品依赖或组合回归 | 三、四期正交，避免互相污染 plan、代码和重型资源 | 并行、WBS | 已采纳 |
| 010 | WBS 完成状态留到独立验收和用户批准主线整合时基于最新 main 窄同步；执行者只提供 delta | 并行 Plan 067 可能修改共享 WBS，任务分支不应用旧文件覆盖 | 文档、交付 | 已采纳 |
