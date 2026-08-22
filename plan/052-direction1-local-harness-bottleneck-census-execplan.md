# Plan 052：方向 1 RONDO Local Harness 聚合观测与瓶颈普查

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/*.md` 为唯一来源。
>
> 本任务只建立观测、普查和候选决策，不实施任何 C1—C13 行为优化。执行者收到用户明确引用本计划的
> 一次性执行授权后，才进入实现阶段；执行结束只提交任务 worktree，合并、推送和分支归档均需用户另行批准。

## 1. 目标

### 最终目标

1. 正式重启仅面向 RONDO Local 的方向 1，以轻量、默认关闭的任务级聚合观测补齐当前 eval 归因缺口。
2. 只读分析已有已交付 Local 运行资产，对 C1、C11、C7、C2 及辅助的 C4/C5 做首轮瓶颈普查，区分真实观察、
   未观察到和当前不可测，不因教师 Harness 已有某项机制就推定 RONDO 存在对应瓶颈。
3. 任务结束时只形成一个清楚交接：证据充分则在 WBS 中选定一个首个优化候选；证据不足则在 WBS 中定义一轮
   有界测量任务。同时决定方向 1 后续是否需要恢复 E-A 的最小子集，默认不恢复完整 A1—A7。

### 完成/验收标准

- [x] 顶层 WBS 与方向 1 子 WBS 表述一致：方向 1 已进入 Plan 052 推进状态，本任务不实现性能优化，当前唯一
      工作包与任务结束后的二选一交接清楚；README 不堆叠阶段状态。
- [x] 形成一个版本化、可校验的 RONDO Local 任务级聚合观测 schema。它明确适用范围、采集开关、样本/字段覆盖、
      缺失值语义和来源，不改写历史结果，也不把 Local 内部指标用于和未注入同等探针的冻结 Codex 做公平横比。
- [x] 观测关闭时不建立额外采集状态、不产生额外文件或网络行为，也不改变请求、prompt、工具、compact、审批、
      重试、停止或调度语义；开启时只产生有界的安全聚合值。
- [x] tracked/public 输出只允许计数、时长、token、比例、枚举、布尔值和必要的版本/覆盖身份；不得包含 prompt、
      命令正文、工具输出、原始参数、任务正文、最终回答正文、密钥、私有路径或逐条私有样本身份。若内部为去重
      临时计算摘要，摘要本身也不得进入 tracked/public 结果。
- [x] 历史资产读取器或等价工具能对当前已交付资产做只读、可重复普查；缺文件、旧 schema、部分运行失败和字段
      不可用均有明确分类，不能用 0、空字符串或推测值伪装成已测量。
- [x] 日期冻结的普查证据说明样本来源、选择规则、覆盖范围、可测/不可测字段、局限及 C1/C11/C7/C2/C4/C5 的
      结论。每个重点候选只能落入“已观察且影响明显 / 已观察但影响较弱 / 当前样本未观察到 / 当前资产无法测量”
      之一，并给出分母、发生率或不能给出发生率的原因；“未观察到”不得写成“绝对不存在”。
- [x] 候选排序综合发生率、影响范围、预期收益、实现成本和行为风险，不按教师实现数量、新颖度或既有候选顺序
      机械决定；C4/C5 只作归因辅助，不单独包装成成功率优化。
- [x] 证据充分时，WBS 只留下一个首个优化候选；证据不足时，WBS 只留下一个测量工作包，并明确任务数、轮数、
      模型、预算上限、停止条件和需另行取得的真实执行授权。本计划内不启动该测量运行。
- [x] E-A 决策有明确依据：现有资产和最小观测足够则继续不恢复；确需低成本反复实验时，只在 WBS 中列出必要的
      最小能力与依赖，不在本任务建设录制器、回放服务器、故障注入、曲线和统一入口全套设施。
- [x] 相关格式化、静态检查、Python 定向测试、受影响 Rust crate/模块的定向门禁和必要轻量集成测试通过；所有
      Cargo 构建/测试经过根共享构建锁与资源看门狗。全 workspace、CI、PR、Docker、真实 API、本地模型、训练、
      validation、holdout 均不运行。
- [x] 安排一次聚焦的只读独立复核，确认观测未改变 Local 行为、结论能被实际资产支持、四类结论没有混淆且候选
      选择不是主观指定。完成后同步 WBS、WBS-COMPLETED、计划当前状态、日期冻结证据和一份精炼 agent log。
- [x] 任务分支已提交且 worktree 干净；主工作区和其他 worktree 未受干扰。未经用户另行批准不合并、不推送、
      不归档分支。

## 2. 范围

### 允许修改

- `mydev/` 中与 RONDO Local 任务级安全聚合观测直接相关的最小代码，以及对应 Rust 测试。若现有边界允许从
  `codex exec`/app-server/rollout 的稳定事件接线，执行者可选对当前架构更小的方案。
- `eval/rondo_eval/` 中必要的 schema、读取、聚合、比较和历史资产普查逻辑；`eval/tests/` 中对应定向测试；必要时
  在根 `justfile` 增加一个轻量、默认无外部执行的入口。
- 与本任务直接相关的 `doc/WBS.md`、`doc/WBS/teacher-harness-study.md`、
  `doc/WBS/eval-benchmark.md`、`doc/audit-snapshots/`、`doc/WBS-COMPLETED.md`、本计划和一份精炼日志。
- 主仓库物理根下与本任务相关的 ignored `eval-data/` 已交付 Local 运行资产，只读分析；如工具需要中间输出，
  只允许在任务专用 ignored 路径写入有界、可删除的安全聚合或临时文件。
- 普通项目依赖下载和项目局部缓存；不得安装或修改全局工具链。

### 不允许修改

- C1—C13 任一行为优化，以及 prompt、工具输出内容/预算、compact 策略、请求恢复、重试、停止条件、工具调度、
  Guardian/审批、sandbox、安全策略或生产默认行为。
- RONDO Multi、Publication Critic、本地审批模型、训练资产、冻结上游 `codex-source-code/`、上游版本或依赖基线。
- 历史 `eval/results/runs.jsonl` 行、已发布 baseline、既有 ignored 原始运行资产、预算/结算账本或来源不明的缓存。
- E-A A1—A7 全套设施、第二套 telemetry、数据库、常驻服务、通用数据平台、签名链或复杂审计/可信/鉴权系统。
- 真实 API、付费 Terminal-Bench、Docker、本地模型、训练、云端任务、数据上传、validation、holdout、完整数据集、
  全 workspace 测试、CI、PR 或上游升级。

### 不允许读取/查看

- `.env.local` 内容；本任务没有读取其变量的需要，也不得搜索、打印、复制或记录。
- validation/holdout 正文、solution、verifier、逐条结果，以及与本任务无关的 ignored 资产正文。
- 项目外个人文件、其他仓库、密钥/凭据或来源不明的本地资产内容。
- 已选样本中的 prompt、命令、工具输出、原始参数、私有字段和任务正文可以由任务内分析器按最小需要在内存中读取，
  但执行者不得把这些正文复制到终端汇报、Git、WBS、日志、日期冻结证据或公共结果中。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或得到某个候选结论而违反。

1. **只观测，不优化。** 本任务不得改变模型可见内容或 agent 决策路径。任何需要修改 C1—C13 产品行为的发现只
   进入 WBS 的后续单候选工作包，不在 Plan 052 顺手实现。
2. **默认关闭且行为保持。** 新观测必须有明确 opt-in，关闭路径不初始化聚合器、不写文件、不增加网络调用；开启
   路径不得改变请求字节、工具调用/结果、审批、compact、重试、停止、调度或退出码。对无法证明行为保持的方案，
   应缩小接线面或换更小实现，不以“只是 telemetry”放宽要求。
3. **输出严格 body-free。** 持久 schema 采用显式 allowlist 和版本；只保存聚合数值、有限枚举和覆盖身份。正文、
   原始值、逐条摘要、私有路径、可逆编码或可用于恢复正文的句柄均不得进入 tracked/public 输出。输入坏损时拒绝或
   标记 unavailable，不把私有异常文本透传到错误消息。
4. **证据语义不能混淆。** `observed_material`、`observed_weak`、`not_observed`、`unmeasurable`（名称可等价）必须
   是互斥终态；每项绑定样本分母、覆盖和证据质量。缺少可测字段时只能是不可测，不能默认 0；样本中没出现只能是
   未观察到，不能证明全局不存在。
5. **样本选择可复核但不泄露。** 使用 tracked 结果身份和安全元数据确定已交付 RONDO Local 样本，不从目录名、
   成绩或候选结论反向挑样本。优先覆盖 v28 及可用的代表性长轨迹、失败、compact、多工具样本；实际纳入、排除、
   缺失和重复数量以聚合方式报告，不公开私有 task/run 对应关系。
6. **决策只有一个下一包。** 只有可复核证据足以支持时才选择一个优化候选；否则唯一下一包必须是有界测量任务。
   不得同时排定多个优化实现，也不得把“补更多观测”和一个未经证据支持的行为优化捆绑立项。
7. **E-A 按最小必要性决定。** 当前仍未恢复 E-A。Plan 052 可以建议后续恢复最小子集，但不能因历史 A1—A7 已有
   设计就整套恢复，也不能把正确性测试重新包装成测评设施。
8. **资源与验证守门。** Rust 格式化、静态检查、构建和测试按 `mydev/AGENTS.md` 执行，所有重型 Cargo 入口经过
   根共享锁、cgroup、项目容量和 Windows `C:` 实际余量门禁，`CARGO_TARGET_DIR` 位于受监控项目根内；拿不到
   这些资源事实时 fail-closed。只跑受影响 crate/模块和 eval 的必要门禁，不扩大到全 workspace。
9. **普通小故障自主收敛。** 首次编译/测试失败、fixture 或 schema 接线问题、短时构建锁占用、可窄修的兼容问题
   不构成用户阻塞；执行者应在范围内诊断、窄修、等待或有界重跑。不得为追求绿灯弱化测试、隐私或行为保持边界。
10. **只有原则性扩展才暂停。** 需要真实 API/Docker/本地模型/训练/云资源/数据外发、完整 workspace 测试、上游升级、
    大范围架构重构、读取 `.env.local`、改变产品行为/方向目标、触碰项目外或来源不明修改，或资源门不可用时停止并
    重新申请授权。
11. **Git 与工作树隔离。** 实现、测试和 tracked 文档只在 Plan 052 worktree；主物理根只承担 §5 声明的 ignored
    资产 I/O。不 stash、回退、覆盖或删除未知修改。任务完成只提交 `worktree-052-direction1-bottleneck-census`；
    不合并 `main`、不推送、不重命名或归档分支。

## 4. 软性建议

以下内容基于 `main@9f32f22` 的实时代码和资产结构给出，不是固定实现路线。执行者可以根据测试和实际复杂度采用
更小或更优方案，只要满足目标、硬约束和验收标准。

- 优先复用现有 `TurnTimingState`/turn profile、token/cache usage、`CompactionAnalyticsAttempt`、Guardian metrics、
  direct tool timing、`codex exec --json` 与 Terminal-Bench 结果发布链。可以新增一个小型 task-local collector，
  也可以从已有稳定事件边界形成等价聚合；不要为此建设新的 telemetry 传输平台。
- schema 可按“身份与版本 / coverage 与 availability / token 与 turn profile / compact / tool 与 approval 聚合 /
  候选信号”分组。具体字段和模块归属由执行者决定；重要的是旧字段兼容、缺失值明确、整数溢出有界、输出只含
  allowlist 类型，且读取方能比较同版本任务。
- 历史资产普查可先用当前 `codex exec --json` 的事件类型、usage、command/file-change/terminal 状态做确定性统计；
  需要读取正文才能判断重复、截断标记或完成声明时，只在内存中生成临时 fingerprint/分类，持久化只写聚合计数。
  无法从旧工件回答的 compact、完整请求终止原因或 timing 项应直接标为不可测。
- C1 可关注截断/遗漏标记、模型可见输出规模和后续重复执行；C11 可关注 typed 或 body-free 终止原因；C7 可关注
  最终声明与最后相关测试/错误/diff 状态；C2 可关注精确重复、同类错误、无文件变化和连续 compact。这里是观测
  方向，不要求执行者采用某一具体启发式；规则不够可靠时宁可缩小口径或判不可测。
- 可以把实现分为互不冲突的两条线：先完成历史资产的只读 inventory/census，再补最小观测接线和测试，最后统一
  用同一 schema 汇合。共享 schema、产品代码和 WBS 仍由主执行者单写者维护。
- 独立复核应聚焦行为保持、隐私投影、样本/分母和候选决策，不要求再建审计工具；审查发现窄问题后由执行者修复、
  重跑相关门禁并再次复核即可。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已确认规划基线为 clean `main@9f32f22`，与本地跟踪的 `origin/main` 一致，创建时只有主工作树。
- 已从该基线创建 `.claude/worktrees/052-direction1-bottleneck-census`，分支
  `worktree-052-direction1-bottleneck-census`；主工作区 tracked 文件未修改。
- 规划收尾复核时，主工作区曾新增来源不明且不重叠的 untracked
  `doc/research/2026-08-21-rondo-multi-publication-critic-local-engineering-facts.md`；本任务始终未打开、移动或纳入它。
  任务收尾时外部流程已将它提交到更新后的 clean `main@607cba0`；本任务没有合并该更新，也没有触碰其内容。
- 已核对根/`mydev` AGENTS、README、顶层/方向 0/方向 1 WBS、候选研究、数据布局、Plan 051 及实时源码。
- 安全结构盘点确认主物理根现有 290 个 ignored run 目录、209 份 `codex exec --json` 工件和 27 个 campaign
  目录；这些只是资产结构，不等于 Plan 052 的合格 Local 样本分母，执行时必须按 tracked 产品/结果身份筛选。
- 原生 rollout trace 已有 turn/inference/tool 生命周期、usage、调用源和 tool runtime；API metadata 已有请求角色、
  终态、错误类别与 usage。compact 原因、Guardian 细节和完成声明—验证关系仍不足以可靠归因，保持不可测。
- 已确认 `RepoPaths.discover()` 从 worktree 解析 Git common root；ignored `eval-data/` 不复制进普通 worktree，
  因而其只读普查必须从任务 worktree 发起、实际访问主仓库物理根。
- 已删除重复的 `codex exec --json --rondo-local-observation` collector。下一轮只对目标 RONDO Local 请求显式启用
  既有 `CODEX_ROLLOUT_TRACE_ROOT`；Terminal-Bench 在发布前把原生 trace 与 API metadata 投影成固定名称的
  schema-v1 body-free 任务结果，缺失、残缺、重复、字段漂移或来源不一致均停止发布，原始 trace 不归档。
- rollout trace 增加最小完整性终态与原生输出 render 事实：精确区分 model-visible 与 code-mode runtime 表面，
  只记录字节数、截断/collection omission、预算和有限枚举，不记录正文；现有 Team Lens 严格 reader/reducer 同时
  支持 Local 单智能体 bundle，不另建 telemetry 平台。
- 已实现严格 Local 选样、common-root 锚定的 `O_NOFOLLOW` 私有工件读取、exact-schema 校验、聚合/比较与根
  `just eval-plan052-census` 入口；日期冻结机器结果和证据均已形成。
- v28 最终 cohort 为 10 个任务 × 3 次 Local 观测。API metadata 为 30/30 run、10/10 任务；exec JSONL 为
  24/30 run、8/10 任务，另外 6 个 redacted 集中在 2 个任务。C1/C2 为弱信号、C11 仅在当前样本未观察到、
  C7 不可测；没有选择行为优化。
- WBS 已只留下一个后续包：同一 10 题、2 个 Local round、Terra medium/Guardian low、20 USD 硬上限和明确停止
  条件的真实观测复测，本任务不运行；E-A 继续不恢复。
- 首轮独立验收发现重复 collector、正式结果接线缺口及残缺历史工件误计为零；均已按现有原生事实链窄修并补回归。

### 当前工作

实现、普查、文档同步、定向门禁和最终独立只读复核均已完成；本提交冻结任务合同并交接 WBS 的唯一后续测量包。

### 本任务剩余步骤

无。后续只按 WBS 的唯一有界测量包另立授权和 ExecPlan，本任务不运行真实复测。

### 阻塞项

当前无计划层阻塞。普通编译、fixture、schema 或临时锁问题按 §3.9 自主处理；只有 §3.10 的原则性扩展才请求用户。

### 当前验收状态

- 实现：默认关闭的 Local trace opt-in、严格离线投影/schema/compare、只读 census、根 just 入口及日期冻结结果均完成；未改变
  prompt、请求、工具、compact、审批、重试、停止、调度、退出码或生产默认。
- 普查：tracked index 288 行完成纯 tracked 校验；最终只验证 30 个 Local private summary。公共结果通过 exact schema
  与 body-free allowlist，实时重建和 tracked JSON 一致。
- 门禁：最终相关 Python 集合 277/277 通过；`codex-rollout-trace` 62/62，受影响 `codex-core` output context
  3/3、code-mode 5/5、tool-dispatch trace 4/4 通过；受影响 crate 的 `just fix` 与项目缓存下 `just fmt` 通过。
  独立复核为 PASS。一次误触发的宽 `codex-core` crate 测试因环境代理相关失败且范围过宽而中止，不冒充通过。
- 未运行：Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI、PR、Bazel。
- Git：只提交当前专用分支；不合并、不推送、不归档。修复阶段曾存在的主工作区来源不明 WBS 修改保持原样；
  交付复核时外部流程已将其提交，主工作区为 clean `main@ea03202` 且 ahead `origin/main` 1，本任务不触碰。

### 主工作区 ignored 资产

以下工作因根 `.gitignore` 与 `RepoPaths.common_root` 设计，只能在主仓库物理根
`/home/sjc/desktop/RONDO` 的 ignored 区完成；命令仍从 Plan 052 worktree 发起，所有 tracked 修改仍落任务树：

- `eval-data/runs/`、`eval-data/campaigns/` 及必要的既有 Local 运行资产：只读 inventory、筛选和聚合分析；不改写、
  移动或删除原件，不在终端/文档复制正文。
- 如分析器必须写中间状态，只能使用 `eval-data/` 下 Plan 052 独占的有界 ignored 临时目录，最终只保留任务需要的
  私有中间物或精确清理本任务自建临时物；tracked 日期冻结证据只接收 body-free 聚合。
- `eval/.venv` 与 `eval-data/uv-cache` 可按既有入口作为共享项目局部 Python 环境/缓存使用；不修改全局 Python。
- `.env.local` 与 `rondo.local.toml` 本任务均不需要读取或修改。若实现意外依赖其中任一内容，应视为路线不够小；
  `.env.local` 仍绝对禁止打开。

实际执行中，主物理根只发生以下 ignored I/O：重复只读 v28 campaign identity，以及合格 30 个 Local run 的
private summary、API metadata、24 份 exec JSONL 与 6 份 redaction marker；修复后复跑又按同一 tracked 身份只读
这些 v28 Local 工件并保持冻结结果逐字节一致。使用既有共享 `eval/.venv` 和
`eval-data/uv-cache` 运行冻结 Python 环境。初版 census 在 Local 筛选前误用了全索引 reader，因此额外只读打开了
10 份 v28 Codex private summary；独立复核后已改为 tracked-only 预筛选，最终实现和后续复跑不再打开它们。该误读
没有输出正文、写入或改变任何资产。修复期间建立并完整删除 `eval-data/plan052-temp/`，未改写、移动、删除任何既有
ignored 资产；另在 `/tmp` 创建的运行时临时目录也已删除。

主工作区没有任何 tracked 文件必须直接修改；若执行者发现 tracked 写入只能在主工作区完成，应停止并先说明原因，
不得绕过 worktree 纪律。

### 交接边界

- 本任务完成并通过独立复核后冻结本计划；后续唯一工作包只在 WBS 中维护。
- 执行结束只提交 Plan 052 分支；合并本地 `main`、推送 `origin/main` 和分支归档均等待用户另行批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 方向 1 以“聚合观测 + 历史资产普查”重启，不直接实施候选 | 当前研究只证明机制值得实验，尚无 RONDO Local 发生率和影响证据 | WBS、产品、eval | 已采纳 |
| 002 | 候选结论使用四类互斥状态，缺字段不得当作 0 | 旧资产覆盖不齐，强行代理会把不可测伪装成阴性证据 | schema、普查 | 已采纳 |
| 003 | E-A 当前仍不恢复，只在任务末按实际证据决定最小后续能力 | 避免因历史设计恢复整套低频设施 | WBS、eval | 已采纳 |
| 004 | 规划期资产目录数只作结构事实，eligible cohort 由 tracked 产品/结果身份重新筛选 | ignored 目录同时含不同产品、侧别和执行代次，目录计数不是样本分母 | 普查 | 已采纳 |
| 005 | 执行和审查阶段只提交 Plan 052 worktree，不合并、不推送、不归档 | 用户明确要求每次完成后先只提交工作树 | Git 交付 | 已采纳 |
| 006 | 复用原生 rollout trace/API metadata，在其真实输出边界只补决策必需的 body-free render 与完整性事实；删除重复 `codex-exec` collector | 现有事实源与 Terminal-Bench 发布链已合适，重复聚合会形成第二事实源；原生边界才能精确回答模型可见截断 | rollout trace、core、eval | 已采纳 |
| 007 | v28 Local 使用 30-run/10-task 固定 cohort；exec 的 6 个 redacted 按任务级非随机缺失，不计为 0 | tracked campaign/slot 身份完整，但正文覆盖只有 24-run/8-task | census、证据 | 已采纳 |
| 008 | 当前证据不足以选择 C1 或 C2，唯一下一包为 10 题 × 2 round、20 USD 上限的 Local 观测复测；E-A 不恢复 | C1/C2 仅有低频弱代理，C11 为窄样本阴性，C7 不可测；现有观测足以补覆盖 | WBS、方向 1 | 已采纳 |
| 009 | 私有读取先做纯 tracked 筛选，再以 common-root `dir_fd`/`O_NOFOLLOW` 逐级打开 30 个 Local 槽；缺失覆盖时 compare 全部 delta 为 null | 关闭独立复核发现的越界读取、symlink 逃逸和“缺失当 0”问题 | eval reader、compare | 已采纳 |
| 010 | 下一轮的唯一变量是开启 Local 安全观测，不改变产品行为；任一 trace/API 缺失、完整性终态非零、schema 或交叉核对失败即停止 | 当前证据只够验证观测覆盖，尚不足以承诺某个行为优化收益 | WBS、Terminal-Bench、结果发布 | 已采纳 |
