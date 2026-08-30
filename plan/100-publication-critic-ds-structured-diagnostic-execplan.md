# Plan 100：DS-V4-Flash 五维任务合同诊断与训练路线裁决 ExecPlan

> 本计划是 Plan 100 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、阶段授权、预算或完成标准，应暂停对应动作并使用本计划指定的 Codex queue 请求审查者批示。
> 范围内的普通实现、provider 接缝、解析、恢复、费用、归档和测试问题由执行者自主修复、续跑或从相称的干净边界重跑，不因一个窄故障提前终止。
> 本计划只描述 Plan 100；后续 qualification、训练、产品启用及跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 Plan 099 `VALID_FORMAL_NO_GO` 后，使用同一个 `deepseek-v4-flash`，在 development-only
`publication-critic-v10` 同一批 27 candidates / 12 pairs 上比较三种输出任务表达：

1. **A / 单标量**：严格输出 `[0,1]` 有限总质量分，由本地 operating curve 决定候选阈值和 gate。
2. **B / 直接门判定**：严格输出 `PASS/REWRITE`，不输出标量、维度或解释。
3. **C / 五维结构化判断**：严格输出 task v2 的五项 hard decision；模型不输出总体 gate，最终 `PASS/REWRITE` 只由本地
   non-compensating AND 聚合。

三组冻结并共享相同的 provider、requested model、正式运行环境、模型可见 bounded public packet 字节、task v2 / rubric v2 语义、
validation cohort、公平性相关请求条件、数据顺序以及本地 labels/pairs/指标口径。差异只允许来自输出任务表达及其严格输出合同；schema 与确有
correctness 必要的输出 envelope 可按合同分别冻结，但不得借机改变数据、rubric、证据边界、sampling 或 supervision。

本任务判断主要问题更支持归因于单标量表达、直接离散判定、五维分解，还是任务/数据约束本身，并形成且只形成 §3 指定的一个路线终态。
无论质量结论正负，只要得到完整、有效、可解释、可独立复算的 clean formal，任务即可“验收通过 / 目标完成”；未形成完整有效 formal 时只能
以技术或预算型 `INCONCLUSIVE` 收口。

Plan 100 不属于原工作包四，不读取 qualification 或 v9 test 正文，不解锁 qualification，不启动训练，也不自动执行任何后续路线。

### 阶段门

- **阶段 A：前置本地非付费准备。** 用户已授权在 100 worktree 内完成本任务需要的项目内实现、测试、合同、结果模板、WBS/日志、普通依赖与
  只读资料查询，合法读取 v10 validation，使用 fake/provider stub/dry-run，并在范围内自主整改、重跑和提交任务分支。阶段 A 不得调用真实
  DeepSeek API，不得加载或推理真实本地模型，不使用 GPU、RunPod、Docker，不上传数据，不创建或修改外部资源，也不产生 API 费用。
  阶段 A 完成后，执行者先提交全部 tracked 变动、保持 worktree clean，再通过 §7 指定 queue 申请独立验收并停止会话。
- **阶段 B：审查者批准后的付费 API 诊断。** 用户已把阶段 B 准入决定委托给本计划指定的独立审查者。只有审查者确认阶段 A 验收通过、三种合同、
  数据范围和 formal 条件已经冻结，真实 API 只使用 `deepseek-v4-flash`，20 RMB 预算与费用口径已经生效，并通过指定 queue 明确批准后，阶段 B
  授权才生效；无需再等待用户回复。阶段 B 又严格串行为 B1 commissioning 与 B2 clean formal。
  未收到明确批准时，执行者必须停在阶段 A 终点。
- **阶段 B1：commissioning 与全链调通。** 从最小真实 synthetic 请求开始；冻结前还须用阶段 A 预指定的少量代表性 v10 public packet 验证
  A/B/C 的真实投影、长度和全链接缝，具体最小样本由执行者选择。commissioning 输出不进入正式指标，也不得用于改变任务语义。分别打通
  A/B/C 的请求、响应、严格解析、typed failure、费用、
  恢复、归档和复算。B1 不是正式结果，可以保留已验证进度并从未打通处继续；允许在既有语义和预算内自主修复实现、provider、配置、解析、
  恢复与普通依赖问题并重跑必要部分。三条完整链路都真实通过后，才冻结 clean source、prompt/schema、provider 参数、模型与环境 identity、
  validation release、解析器、指标、价卡和正式 namespace 条件。
- **阶段 B2：clean formal。** 只能在 B1 全链通过并冻结后，从新的空 formal namespace 开始。一个完整批次是 27 个 candidate × 3 组，
  共 81 个 write-once terminal observations；模型输出违反冻结合同而形成的 parse failure 是正式任务可执行性结果，不是可重试到更好输出的技术无效。
  技术中断只补未完成项；已经形成有效 observation 的项目不得因质量不满意而重复调用。若实现或基础设施问题按预冻结 taxonomy 使整轮无效，
  可修复后从新的干净 namespace 完整重跑；一旦形成一个完整有效 formal，即使结论负向也立即停止新增 API 消费，不追求更好结果。

### 完成/验收标准

- [ ] 阶段 A 形成受跟踪的小型语义与准入合同或等强身份，唯一绑定 v10 validation release、27 candidate/12 pair 字节与行序、packet projection、
      task v2 / rubric v2、A/B/C 输出语义、provider/model 边界、公平性参数、commissioning 候选配置、本地 labels/metrics、route decision、
      预算/价格规则与正式准入/namespace 条件。B1 可在不改变上述语义与公平性的前提下修复真实 prompt/schema/provider 兼容实现，三链打通后才冻结
      formal clean source/config；任何阶段都不得把密钥、私有 endpoint 或 provider 正文写入 tracked 资产。
- [ ] A 只接受严格 schema 内的单个有限 `[0,1]` scalar；B 只接受一个 `PASS/REWRITE`；C 只接受五项 hard decision，
      `conditional_continuity` 可按 task v2 使用 `N/A`，其余维度遵循 task v2 的适用枚举。缺字段、多字段、错误枚举、非有限 scalar、解释性文本、
      模型自行给出的 C 组总体 gate 或其它合同外内容均按 typed parse failure 处理。
- [ ] C 的正式 gate 只由本地程序执行 non-compensating AND：全部适用 hard dimension 为 PASS 才 PASS，任一适用维度 FAIL 即 REWRITE；
      `N/A` 的适用性按冻结 task v2 语义解释，不存在平均、权重补偿或自由 global-quality head。
- [ ] 三组对每个 candidate 使用完全相同的模型可见 packet 字节；labels、pairs、pair direction、split、defects、brief、生成/审查记录等
      supervision 只在 provider 结果落盘后由本地 join，且不会进入 prompt、请求日志或错误回显。
- [ ] 阶段 A 的相称 fixture 覆盖合法/非法输出、恢复与重复响应、timeout/429/中断、请求成功但归档前中断、归档后聚合前中断、已完成结果复用、
      只续跑未完成项、三组顺序与 packet 字节一致、supervision 隔离、预算停止、commissioning/formal 隔离以及正式结果独立复算。
- [ ] B1 从 synthetic 开始，并须再使用阶段 A 预指定的少量 v10 public packet，逐条证明 A/B/C 的完整链路；commissioning 结果与 formal
      物理隔离，不进入质量指标。正式 source/config 冻结发生在
      B1 全链通过之后，而不是在真实接缝尚未验证时提前冻结。
- [ ] B2 从空 namespace 形成 81/81 唯一 terminal observations；其中合法输出与模型/response contract typed failure 分开计数，并按阶段 A
      冻结的 fail-closed 指标/路线规则处理。只有批次不完整、实现/基础设施使 formal 无效或预算不足时才形成技术/预算型 `INCONCLUSIVE`；
      不得拼接不同正式配置、选择性覆盖负向结果或把 skip/未运行冒充结果。
- [ ] 三组统一报告 False PASS、False REWRITE、balanced accuracy、candidate 级错误切片、12 pair 结果、typed failure 与解析失败。
      A 另报告完整 scalar operating curve、ROC AUC、Boundary strict win 和是否存在可接受 operating point；C 另报告五维 confusion、
      各维 failure recall、continuity N/A recall、supported-class macro recall、预测类别覆盖、逐 pair target closure、non-target invariance
      以及本地 gate 结果。
- [ ] 阶段 A 在看见 formal 输出前冻结“基本门”“达到/明显优于/接近”的确定性操作定义和五类路线映射。C 的结构化开发门优先复用
      Plan 099 development gate 中与推理诊断相符的候选级、逐维和 pair 条件，删除 training loss 与相对 step-zero 改善等训练专属条件；
      A 的 curve/AUC/Boundary 门与 B 的直接 gate 门使用同 cohort 下可比较的既有口径。执行者可提出更清楚的等强实现，由阶段 A 审查者裁决，
      但不得在 formal 结果出现后改门。
- [ ] 正式结果和报告可从冻结 raw observation 独立复算，并完整记录 provider/requested/response model identity、不可验证的 serving 分量、
      每次 logical call / HTTP attempt、typed outcome、token/费用、正式 authority 与数据身份；不建设第二套通用费用平台、事务系统或可信证明。
- [ ] 产品 cloud scorer、local scorer、typed product wire、Publication Critic 默认状态和发布路径均不改变；不读取 qualification、v9 test
      或其它冻结 unseen 正文，不训练，不使用 GPU/RunPod/Docker/真实本地模型，不上传，不充值。
- [ ] 运行与实际 diff 相称的定向轻量测试及最终独立审查；若涉及 Rust，严格复用主物理仓库根唯一
      `.codex/cargo-target/rondo-multi` 和正式 build-lock/`just` 入口，不在 worktree、临时目录或 `multidev/codex-rs/target` 建第二套 target。
- [ ] 最终只提交 100 任务分支并保持 worktree clean；未经用户另行批准，不合并、不推送、不归档或重命名分支、不删除 worktree。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 中本任务需要的 development release、三输出合同、batch runner、strict parser、metrics、freeze、费用、恢复、
  write-once archive、recompute 与结果投影；职责合适时泛化既有 Plan 096/098/099 能力。
- `multidev/codex-rs/publication-critic/` 中仅为复用既有 DeepSeek provider 所必需的 eval/reference-only 请求、响应、usage/token 或 typed failure
  接缝；不得扩大产品 wire 或改变 default-off 产品行为。
- 与上述能力直接对应的定向 Python/Rust tests、fake/loopback fixtures、小型 tracked lock/result/template，以及本 Plan、WBS、
  `doc/WBS-COMPLETED.md`（只在最终审查接受后）和精炼 `agent_log`。
- 主物理根 task-owned ignored `eval-data/publication-critic/plan100/` 中的 commissioning/formal raw observations、费用账本、恢复状态与复算归档；
  该目录不属于 tracked worktree，执行者必须在阶段与最终汇报中单列路径、用途、大致体积和保留/清理状态。
- 普通依赖下载、官方 DeepSeek 文档/公开源码的只读查询、阶段 A/最终独立审查，以及范围内必要的项目局部重构、重生成与修复重跑。

### 不允许修改

- 冻结 task v2 / rubric v2 的语义、v9/v10/qualification 数据正文、labels/pairs、现有历史结果、已接受 review 或 Plan 099 训练终态。
- Publication Critic 产品 scorer 默认、local scorer 行为、Team State、`team_publish`、生产配置或发布语义；不得把 eval 输出 schema 变成产品协议。
- Plan 099 保留卷、Pod/RunPod、训练权重、GPU/Docker/本地模型设施、其它 worktree、宿主机配置、全局工具链或其它仓库。
- 第二套 provider、费用账本、通用测评平台、鉴权/隐私平台、审计/可信/机器证明、严格因果平台或与本任务无关的基础设施。

### 不允许读取/查看

- `publication-critic-qualification-v1` 正文、v9 test 正文，以及任何其它冻结 test/unseen 正文、旧 unseen 逐样本输出或其 label/pair 方向。
- `.env.local` 内容。只允许静默检查主仓库根该文件是否存在、非符号链接、权限为 `0600`，以及任务所需变量是否存在且非空；不得打开、搜索、
  打印、复制、记录或 shell source。
- 与本任务无关的个人文件、密钥、私有日志、训练监督或外部服务数据。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试、追求正向结论或提高局部指标而违反。

1. **唯一对照变量。** A/B/C 必须使用同一 `deepseek-v4-flash`、同一 provider/API shape、同一模型可见 packet、task/rubric 语义、cohort、
   sampling/temperature、timeout/retry 等公平性参数和本地监督口径。输出指令/schema 及确有 correctness 必要的输出 envelope 可按任务合同分别冻结，
   但差异只能服务输出表达。任何换模型、换数据、改 rubric、改 label、改变证据边界或引入其它推理差异都超出授权。
2. **五维只返回 hard decisions。** C 不返回总体 gate、scalar、置信度或解释；最终 gate 只在本地按 task v2 做非补偿合取。模型提供的额外字段
   不能覆盖 hard failure，也不能参与正式指标。
3. **外发最小化。** 只允许向 DeepSeek 外发 v10 validation 的 bounded public packet、必要的无监督 synthetic commissioning packet、冻结的
   task/rubric/output 指令。不得外发 labels、pairs/direction、split、defects、candidate brief、生成/审查记录、qualification/test、源码、密钥、
   私有日志或训练监督。
4. **预算硬上限。** Plan 100 所有真实 DeepSeek API commissioning、formal、retry、恢复和技术无效 clean rerun 共用独立 `20 RMB` 总上限，
   不继承历史余额，不授权充值。发起下一次可能计费动作前，必须满足“已 durable 结算费用 + 全部未结算 reservation + 下一动作按冻结 usage envelope、
   适用价卡和完整最坏自动 retry envelope 计算的保守预留 ≤ 20 RMB”；reservation 只有在对应 attempt durable settlement 后才能释放差额。
   余额不足以完成下一必要步骤时停止为预算型 `INCONCLUSIVE`。
5. **按 token 和时段结算。** 每次 attempt 优先使用 provider usage 与当次请求北京时间所适用的冻结官方价卡，按 cache-hit input、cache-miss input、
   output 等实际计费 token 分类复算。provider response 缺少 `usage` 本身不得直接按 `0.1 RMB` 兜底：只要能从已保存的 exact request/response、
   provider 其它 token 字段、官方 token counter 或阶段 A 冻结并经 usage-present commissioning 校准的计数方法得到各类 token 数，就必须按 token
   与当时价档计算；缓存分类无法核实时，input 按适用 cache-miss 价计算。本计划编制时的官方规则只把北京时间周一至周五
   09:00–12:00、14:00–18:00 列为高峰，其余为空闲，故周日全天适用谷价；仍须在首个真实请求前刷新并冻结
   [官方价卡](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)来源、核对时点和 live 规则，跨时段的 attempt 按各自实际档位计算。
   只有明确不计费的动作记 `0`；不确定是否计费，或已知计费但在完成上述
   计算后仍无法确定金额的实际 attempt，才按 `0.1 RMB/次` 入账。
6. **commissioning/formal 隔离。** B1 不产生正式质量证据。B2 只有全链打通后的冻结 clean source/配置和空 namespace 才有效；技术无效轮可在
   预算内修复后完整 clean rerun，模型内容或 schema 失败本身是任务结果，不得冒充技术故障重试；一个完整有效 formal 出现后立即关闭新增 API 动作。
7. **恢复而非选择性重跑。** 中断时保留已验证 write-once 结果并只补未完成项；重复响应必须幂等或明确拒绝。不得清空有效进度以挑选更好的随机
   输出，也不得拼接不同 source/config/prompt/price identity 的 rows。
8. **监督隔离。** provider 调用阶段与本地 join/metrics 阶段物理或等强逻辑隔离；普通日志、queue、tracked 结果和 provider error 不含 packet 正文、
   supervision、credential 或私有 endpoint。保留 body-free、可复算的 identity/typed outcome/usage/费用即可，不引入重型数据审计。
9. **路线终态唯一。** 有效 formal 必须按阶段 A 预冻结规则形成以下之一，不作严格因果外推：
   - `FIVE_DIMENSION_STRONGLY_SUPPORTED`：C 达到结构化开发门，且相对 B 的预冻结差异足以排除“仅直接离散判定即可解释”的路线判断；只建议未来
     另立部分解冻后层的五头训练任务。
   - `DISCRETE_SUPPORTED_FIVE_DIMENSION_INCREMENT_UNCONFIRMED`：B、C 均明显优于 A 且按预冻结定义接近；支持标量/校准是主要问题，五维额外价值未确认。
   - `CONSTRAINT_OR_DATA_ISSUE`：C 的逐维判断总体较好，但被特定维度、pair target closure 或 non-target invariance 集中阻塞；回交明确切片，
     不直接归因 backbone。
   - `TASK_EXECUTABILITY_INSUFFICIENT`：A/B/C 均未达到预冻结基本要求；默认不建议继续付费解冻训练。
   - `INCONCLUSIVE_TECHNICAL_OR_BUDGET`：未形成完整有效 formal；不得形成质量结论。
10. **资格和产品锁不变。** 任何正向结果都不读取或解锁 qualification，不授予 scorer/model 产品资格，不默认启用 Critic，不执行训练、发布或生产动作；
    后续路线必须由 WBS 和新的独立任务承接。
11. **构建与 Git。** Rust 构建/测试只走主物理根既有 `just` + `scripts/with-build-lock.sh` 入口并复用唯一
    `.codex/cargo-target/rondo-multi`；不直接 Cargo，不扩大全 workspace。tracked 变动只在 100 worktree；完成各审查批次后提交任务分支，
    合并和推送必须等待用户批准。
12. **协作入口唯一。** 阶段 A 准入、额外授权/计划外变数/不确定事项、审查整改和最终验收只通过 §7 的 Codex queue 联系指定审查者；执行者每次
    主动表明身份，发送一次后停止会话，不轮询、不重复发送相同消息。

## 4. 软性建议

以下内容用于根据现有代码给出的执行建议，但不是固定实现路线。执行者可以依据 live code、测试与 commissioning 结果采用更优的等强方案，
前提是不改变 §3 硬边界。

- 优先复用 Plan 095 的 DeepSeek provider/typed failure、Plan 096 的 eval-only usage/cost/freeze/write-once/recompute、Plan 098/099 的
  v10 development release、task v2 解析和逐维/pair metrics。若把 scalar-only runner 强行扩成大量条件分支会扭曲职责，可建立 Plan 100
  专用三任务薄层或做干净的小幅泛化，但不要复制第二套 provider、ledger 或通用 eval 平台。
- 三种输出可尽量使用同一 JSON response format、相同 max output/timeout/retry/sampling 条件，只让 schema 和输出指令表达不同，便于保持对照。
  阶段 A 固定 prompt/schema 的 commissioning 候选版本与 identity；B1 可修复真实 correctness/compatibility 问题，但不允许根据质量调
  rubric 或标签，最终 formal 版本按 §3.3 在三链打通后冻结。
- fake/stub 可先覆盖完整 81-row lifecycle；B1 从 synthetic 请求起步，再用预指定的少量 v10 public packet 验证真实投影/长度接缝。
  并发 1 通常最利于预算、恢复和次序核对；若执行者能证明其它方案同样
  安全，可自主选择。
- 费用 fallback token counter 应尽量复用[官方 tokenizer/计数能力](https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/)，并用 B1 中同时带
  usage 的响应做差异校准；只保存复算需要的 token 数、计数方法 identity 与 hash，不必保存或追踪全文到通用审计系统。
- route decision 的“明显优于/接近”宜使用 27-candidate 与 12-pair 的离散分辨率、既有 development floors 和结构化门来给出简单、可解释的
  预冻结规则，避免小样本上伪装精密统计或严格因果声明。
- 定向门禁按实际 diff 选择；纯 Python 变化不触发 Cargo。Rust 变化完成后按 `multidev/AGENTS.md` 运行 fmt 与受影响 crate 的正式入口，
  不重跑完整 workspace，也不复制 Plan 095/096 的全部历史测试矩阵。

### 建议执行步骤

1. 核对 live code、允许的 v10 development release 与主物理 ignored 边界，选择复用/专用薄层的最小清晰架构。
2. 实现三输出合同、strict parser、本地 C gate、统一 metrics、route mapping、费用 fallback、恢复/archive/recompute，并完成 fake/dry-run/focused tests。
3. 冻结阶段 A 付费申请所需的语义、候选配置、data/metrics/预算/价卡与 formal 准入条件，提交任务分支，通过 queue 申请阶段 A 验收后停止。
4. 收到明确批准后执行 B1；逐组打通真实 synthetic 全链，并用预指定的少量 v10 public packet 验证真实投影、长度和全链接缝；范围内自主修复，
   三组均通过后提交并冻结 clean formal 条件。
5. 从空 namespace 执行 B2 的 81 个 logical results；中断时只续未完成项，技术无效时按合同 clean rerun，形成首个有效 formal 后停止 API。
6. 独立复算三组指标与唯一路线终态，检查费用、外发边界、产品不变性、ignored 资产和 Git 状态；更新当前状态、WBS、结果与精炼日志并提交。
7. 通过 queue 请求最终验收并停止；若被唤醒要求窄修，修复、运行相称门禁、提交一次新变动，再发送新的完成汇报并停止。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-29：确认主工作区 clean，`main = origin/main = 027f57fdf97d4110da1c36f93c1b8a1e6b43e305`；既有
  093/095/096/097/098/099 worktree 均未复用或修改。
- 2026-08-29：从该 clean main 创建
  `.claude/worktrees/100-publication-critic-ds-structured-diagnostic` / `worktree-100-publication-critic-ds-structured-diagnostic`。
- 2026-08-29：只读核对根/`multidev` 规则、README、顶层/方向 3 WBS、ExecPlan 模板、Plan 095/096/098/099 合同与相关完成/审查记录；
  未读取 qualification、v9 test 或其它 unseen 正文。
- 2026-08-29：建立本 ExecPlan 并把 Plan 100 最小登记到根 WBS 和方向 3 子 WBS；本规划阶段未调用 API、构建/测试、GPU、RunPod、Docker、
  本地模型、训练、上传或产品动作。
- 2026-08-29：阶段 A 初始检索发生 qualification 正文意外输出；执行者立即停止并主动报告，审查提交 `387702e9` 以
  `ACCEPTED_WITH_CONTAINMENT` 允许从 clean 状态继续。后续全部读取、搜索、测试和子任务改用显式 allowlist；该上下文永久退出未来
  qualification/test 释放、阈值返调和最终资格裁决。
- 2026-08-29：完成 Plan 100 专用 A/B/C Rust 接缝、v10 validation-only loader、严格双层 parser、本地 C AND、统一 metrics/route、
  task-wide 20 RMB reservation/按 attempt 价档结算、token recount 后 0.1 RMB 末级 fallback、write-once receipt/terminal/authority、
  commissioning/formal runner、恢复和独立复算；tracked 合同冻结 27/12 身份、1 synthetic + 2 public commissioning 与 formal 准入候选。
- 2026-08-29：聚焦门禁通过：Plan 100 Python `13 passed, 9 subtests passed`；正式 build-lock/shared target 下
  `just test -p codex-publication-critic` 为 `68 passed, 0 skipped`；tracked DeepSeek descriptor + synthetic packet 在显式移除 credential 后
  离线验证到 `invalid_configuration`，确认配置/packet 校验通过且未发出请求。
- 2026-08-29：独立代码审查发现 commissioning 成功门、authority 后只读复算与 task-wide 费用证据三处实现缺口；已改为 9/9 strict success +
  usage-present recount 全量校准才生成自包含 B1 binding，formal freeze 必须与该 B1 的 source/provider/request/release/comparison/price identity
  完全一致，authority 后只允许只读重开，formal 结果与 tracked projection 绑定覆盖 commissioning/retry/技术轮的总账。定向 Python 回归增至 14 项。
- 2026-08-29：审查者批准穷尽路线：既有四个质量谓词之后的完整有效 residual 返回 `CONSTRAINT_OR_DATA_ISSUE` 并标记
  `residual_mixed_signal=true`，不修改 metrics、不伪造 concentrated blocker 或数据/backbone 归因；A-only 完整 81-row formal 与 A/B/mixed
  路由回归通过。同时修正价卡为北京时间周一至周五双峰窗、周末全天 off-peak，保留首次真实请求前 live refresh/freeze。Python 定向门禁为
  `15 passed, 24 subtests passed`。
- 2026-08-29：阶段 A 准入验收发现付费入口、task-wide authority/ledger、formal technical resume、无 response recount 与详细报告五处缺口；已
  固定主物理根唯一 `eval-data/publication-critic/plan100`，B1 只可在此创建账本，B2 运行时重新验证实际归档 B1 binding、clean HEAD 及全套
  source identity 并要求账本保留精确 B1 settlements，recompute 改为 existing/read-only 并校验 authority freeze/result hash。首个 authority
  现在封锁全部 commissioning/formal provider 入口；显式同 freeze resume 只追加 technical logical 下一 ordinal；无 response/usage 的 attempt 走
  0.1 RMB fallback；新增 body-free detailed projection。Python 定向回归增至 20 项。
- 2026-08-29：审查提交 `f0af3360` 明确验收阶段 A 并批准阶段 B。B1 请求前 live refresh 确认北京时间工作日双峰窗与费率未变，当前周日使用
  off-peak；官方 V4 tokenizer 下载到 task-owned ignored namespace 并冻结 hash。live 文档同时确认 V4 默认开启 thinking、会忽略 temperature 且
  reasoning token 无法从最终 JSON 独立复算；按 B1 provider 兼容授权对三臂统一显式关闭 thinking，并增加复用同一 Rust prompt renderer 的离线
  token recounter，不改 rubric、packet、输出 schema、labels、metrics 或路线阈值。Plan 100 Python 21 项与 Rust 69 项定向门禁通过。
- 2026-08-29：首轮 B1 为 9/9 strict success、0 retry/parse/technical failure，实际结算 `0.0069217 RMB`；binding 因 recount calibration
  fail-closed。九项只读核对均为 provider prompt 比官方 rendered tokenizer 固定多 21 tokens、completion 完全相等，故按 B1 校准职责冻结
  21-token provider chat envelope；不修改原始 usage、prompt/schema/packet 或质量语义。
- 2026-08-29：从新 clean commit 完成第二轮 B1，9/9 strict success、9/9 usage recount 精确一致，冻结实际 B1 binding；两轮 B1 共结算
  `0.0088322 RMB`。随后从空 namespace 执行 B2 clean formal，81/81 observation 完整、A/B/C parse failure 均为 0、无 retry，formal 结算
  `0.0307772 RMB`。首个完整有效 authority 形成后停止全部 API 消费。
- 2026-08-29：authority-bound tracked/detailed 独立复算通过，task-wide 99 HTTP attempts 全部按 provider usage 结算 `0.0396094 RMB`，余额
  `19.9603906 RMB`、outstanding reservation 为 0。三臂均未满足预冻结 basic/gate，唯一路线终态为
  `TASK_EXECUTABILITY_INSUFFICIENT`；这是完整有效负向质量结果，不是技术 `INCONCLUSIVE`，不解锁训练、qualification 或产品启用。
- 2026-08-29：最终独立验收复现 authority-bound tracked/detailed 结果与费用，Plan 100 Python 21/21 通过，未发现 High/Medium；任务以
  `FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED / TASK_EXECUTABILITY_INSUFFICIENT` 冻结完成，API 授权关闭且余额不转移。

### 当前工作

- `STAGE_A_ACCEPTED / STAGE_B_ACCEPTED / FINAL_REVIEW_ACCEPTED / TASK_EXECUTABILITY_INSUFFICIENT`。

### 本任务剩余步骤

- 任务内无剩余实施步骤；合并、推送、分支归档与 worktree 处置继续等待用户明确批准。

### 阻塞项

- 当前无实现或授权阻塞。

### 当前验收状态

- 规划：`COMPLETE / FROZEN`。
- 阶段 A：`ACCEPTED / COMPLETE`。
- 阶段 B：`ACCEPTED / COMPLETE`。
- 完整任务：`FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED / TASK_EXECUTABILITY_INSUFFICIENT`。

### 交接边界

- 执行者只在 100 worktree/branch 完成 tracked 实现、测试、文档、整改和提交；主物理根 ignored `plan100` 资产单列汇报。
- 阶段 A、计划外请示和最终验收使用 §7 指定 queue。阶段 A 通过后，审查者必须用同一 queue 明确通知批准阶段 B，执行者才可继续。
- 任务完成后冻结本计划；部分解冻训练、qualification 或产品启用只链接 WBS，不列入本任务剩余步骤。
- 最终验收前后都只提交任务分支。合并、推送、分支归档/重命名和 worktree 删除必须等待用户明确批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 100 是 Plan 099 后的独立 development-validation 诊断，不属于工作包四 | 区分任务表达诊断与冻结测试资格，避免负向训练结果或正向诊断越权解锁 | WBS、数据、终态 | 已采纳 |
| 002 | 同一模型/packet/task/rubric/cohort/参数只比较 scalar、direct gate、five-dimension 三种输出表达 | 把主要可观察差异集中在任务表达，而不混入换数据或换模型 | formal、解释 | 已采纳 |
| 003 | C 只输出五项 hard decision，总体 gate 由本地 non-compensating AND 决定 | 保护 task v2 的不可补偿语义，避免模型自由总分重新混入 | schema、metrics | 已采纳 |
| 004 | 阶段 A 非付费准备经独立验收后，由用户委托的审查者批准 B1/B2；阶段 B 总预算 20 RMB | 尽量在本地暴露问题，同时保留清晰付费闸门 | 阶段、授权、费用 | 已采纳 |
| 005 | 经过真实 provider 的 B1 全链通过后才冻结 B2；技术故障可修复恢复，有效 formal 质量负向不重跑 | 避免过早冻结造成整组报废，也避免结果选择 | commissioning、formal | 已采纳 |
| 006 | 缺失 provider usage 时优先按可复算 token 分类和当时价档结算，不直接按 0.1 RMB；真正无法定额才 0.1 RMB | 遵循实际 token 计费并保留硬预算安全 | 费用、归档 | 已采纳 |
| 007 | 职责契合时复用 095/096/098/099 设施；强行复用会扭曲三任务语义时允许专用薄层，不建设第二套体系 | 保持架构干净且不让历史 scalar 假设支配新目标 | 架构、测试 | 已采纳 |
| 008 | tracked 变动只在 100 worktree；ignored raw/ledger/archive 只在主物理根 `eval-data/publication-critic/plan100/` | linked worktree 不共享 ignored 资产，需保持主工作区 tracked clean | Git、资产 | 已采纳 |
| 009 | 审查、计划外批示和阶段沟通只走指定 queue；每次主动表明身份，发送后停止且不轮询 | 使用用户指定的跨会话审批通道 | 协作、交付 | 已采纳 |
| 010 | 任务结束只提交任务分支，合并/推送/归档/worktree 删除均等待用户批准 | 遵循本次明确的 Git 交付边界 | Git | 已采纳 |
| 011 | Plan 100 三臂统一显式关闭 V4 thinking，并以官方 tokenizer + 同一 Rust prompt renderer 做离线复算 | live V4 默认 thinking 会忽略冻结 temperature，reasoning token 也无法从最终 JSON 复算；关闭后保留三臂公平性和严格短 JSON 合同 | B1/B2 provider、费用 | 已采纳 |

## 7. 执行者启动提示词

> 本提示词随 Plan 100 最终验收完成而失效，仅保留为历史任务合同；不再授权任何 API、数据外发、训练、qualification、产品或集成动作。

你是 Plan 100 的执行者。请在
`/home/sjc/desktop/RONDO/.claude/worktrees/100-publication-critic-ds-structured-diagnostic/`、分支
`worktree-100-publication-critic-ds-structured-diagnostic` 内工作。开始前完整阅读根 `AGENTS.md`、`multidev/AGENTS.md`、当前 WBS 和
`plan/100-publication-critic-ds-structured-diagnostic-execplan.md`，随后直接执行阶段 A，不另写重复计划，也不要向用户复述 ExecPlan 或
AGENTS 内容。硬边界必须遵守；实现结构、复用方式和普通技术策略由你自主选择，软建议可被更优等强方案替代。

用户已经一次授权阶段 A 所需的项目内实现、测试、合同、文档、普通依赖、只读公开资料、合法 v10 validation 读取、fake/stub/dry-run、
任务专属 ignored namespace、独立审查整改和任务分支提交。阶段 A 禁止真实 API、真实模型、GPU、RunPod、Docker、训练、上传、冻结测试读取、
产品动作、合并和推送。若涉及 Rust，只能复用主物理根唯一 `.codex/cargo-target/rondo-multi` 及正式 build-lock/`just` 入口。

阶段 A 完成后先提交全部 tracked 变动并保持 worktree clean，再用下面的指定 queue 提交完整的阶段 A 完成汇报和阶段 B 准入申请，然后停止会话。
用户已委托审查者在验收通过后批准阶段 B；收到明确批准后，你可在 Plan 100 的 `20 RMB` 总上限内，仅用 `deepseek-v4-flash` 自主完成
B1 commissioning、范围内修复/恢复、B2 clean formal、分析和收口。只允许外发合同规定的 bounded public/synthetic packet 与冻结指令；
不授权充值、qualification/v9 test/unseen、训练、真实本地模型、GPU/RunPod/Docker、上传或产品启用。缺失 provider usage 时先按可复算 token
分类与请求发生时适用价档计算，不得直接记 0.1 RMB；只有完成该计算后仍无法定额的实际 attempt 才记 0.1 RMB。形成首个完整有效 formal 后，
无论结论正负都停止新增 API 消费。

最终完成后先提交所有 tracked 变动、保持 worktree clean，并在完成汇报中单列主物理根 ignored 资产的精确路径、用途、大致体积及保留/清理状态，
再通过指定 queue 申请最终验收并停止。你只能提交 100 任务分支；合并、推送、分支归档/重命名和 worktree 删除等待用户另行批准。

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a04e4c-32ac-7a30-8926-7212f2f12e85 替换。
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
`【身份：Plan 100 执行者｜阶段 A/阶段 B/整改轮次】`，随后原样粘贴上述从“执行者完成了<阶段性任务>”开始的模板，只替换两个尖括号占位符；
身份前缀不计入 `<执行者的完成汇报>`，完成汇报本身仍一模一样嵌入。普通请示也在第一行使用同样身份格式。

上述“如果验收通过，他不会再通知你”只适用于最终完整任务验收。阶段 A 通过后，审查者必须通过同一 Codex queue 明确通知执行者
“Plan 100 阶段 A 验收通过，批准进入阶段 B”，并确认三种合同/数据/formal 已冻结、真实 API 仅用 `deepseek-v4-flash`、20 RMB 与费用口径已
生效，以及 qualification、训练、GPU、产品启用和其它外部动作仍未授权；执行者收到该消息前保持停止，不自行轮询或进入阶段 B。
