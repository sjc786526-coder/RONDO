# Plan 033：L3/L4 未微调 Local-static baseline

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 L3/L4 未微调 baseline；跨任务路线、优先级、顺序和依赖以
> `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

严格导入 Plan 032 已冻结并标记 `ready_for_l3=true` 的 40 条 Sol 教师标签，在现有已资格化的
Ministral 12k 本地服务上，对完全对应的 canonical static payload v3 做一次程序化 Local-static 批量回放。
在看到真实模型结果前冻结 L4 指标定义，随后按同一口径发布 seed 24 条与 holdout 16 条的教师导入记录、
本地自动运行记录和未微调聚合 baseline，为后续 L5b/L6 与 Local M4 提供固定对照起点。

本任务测量的是未微调 Local 相对时点 Sol 蒸馏目标的表现；不把 Sol 称为人工 ground truth，也不据本轮分数
决定模型采用或淘汰。

### 完成/验收标准

- 严格复核 tracked 教师锁与私有批次的 manifest、outbound、prepare receipt、labels 和 import metadata；
  40 条标签与 40 条 canonical payload 在语义身份、代表 `E_final` SHA、payload SHA、分区和用途上逐条唯一对应，
  无缺失、额外、重复或跨分区。
- 不运行 Plan 032 `prepare`，不重新生成、补问、改写或“优化”任何 Sol 标签；教师输入只来自现有冻结批次。
- 指标 schema、终态分类、分母、百分位算法和公共/私有投影在真实模型运行前写入 tracked 代码或模板、通过 focused
  tests 并提交；真实运行后只按冻结口径填数。
- 40 条样本全部进入唯一明确终态。合规 allow/deny、结构化输出失败、超时和最终基础设施失败均为可归档结果；
  不能为追求 40/40 结构化成功而弱化 schema、超时或 fail-closed。
- seed 与 holdout 各发布一对匹配的 shadow 记录：教师侧为 `sol-static/source=imported`，本地侧为
  `local-static/source=auto`。两对记录绑定同一教师批次、分区和样本集合身份。
- seed 公共记录可以保留不含正文的必要逐条诊断；holdout 公共记录只能含整批摘要且 `tasks=null`，不得通过
  baseline、日志、计划、测试输出或其他 tracked 文件泄漏逐条身份、标签、模型输出、耗时、token 或失败明细。
- 按 §3.2 的冻结定义分别计算 seed、holdout 和 40 条总体的教师一致率、教师不一致数量、allow/deny 分布、
  结构化输出失败、超时、fail-closed、基础设施失败、P50/P95 延迟与 token，以及本地运行显存峰值。
- 教师导入记录明确不冒充自动运行：`binary_sha256=null`、`metrics=null`、`cost.actual_usd=null`、
  `cost.estimated_usd=0.0`；本地记录明确绑定当前 `rondo-local`、未微调 GGUF、b10333 CUDA runtime、12k/512
  服务合同和运行时指标。
- baseline 能由冻结教师输入、私有本地终态和同版本聚合代码重算；公共结果不含真实正文、模型 rationale 或
  holdout 明细，不把相对教师标签的差异称为“漏放/误拦”。
- focused pure/fake/loopback 测试、真实 40 条回放、结果重算/发布校验和必要的 eval lock 检查均通过且无 skip；
  模型进程、端口、launcher receipt、临时文件与 GPU 现场完成定点清理。
- 全部合同通过后才更新 WBS，关闭方向 2 的 P2 剩余项并把下一工作包指向 P3 的 L5b/L6；同步一份精炼日志和
  `doc/WBS-COMPLETED.md` 历史记录。
- 所有 tracked 改动只在 `033-l3-l4-unfinetuned-baseline` worktree/分支自审并提交；不合并、不推送、
  不删除 worktree、不重命名分支。

## 2. 范围

### 允许修改

- 本计划的“当前状态”和“关键决策记录”。
- `eval/rondo_eval/local_approval/` 下实现严格教师导入、Local-static 批量回放、终态分类、指标聚合与结果构造所需的
  轻量代码；执行者可按现有架构选择文件和局部抽象。
- `eval/rondo_eval/artifacts.py` 或现有统一结果发布链中支持 WBS 已定义的 shadow `source=imported|auto`、
  imported null 字段和 holdout `tasks=null` 所必需的窄改动；不得借机重写 Terminal-Bench 发布体系。
- `eval/tests/` 下直接相关的 pure/fake/loopback 回归和不含真实正文的合成 fixture；必要时在
  `eval/templates/local-approval/` 或等价 tracked 小文件中冻结本轮指标 schema/版本。
- `eval/results/runs.jsonl` 中本轮四条匹配 shadow 记录，以及 `eval/results/baselines/` 下一个不含逐条 holdout
  信息的未微调聚合 baseline。具体文件名与内部代码结构由执行者结合现有惯例决定。
- 若 live schema 需要同步，精炼更新 `doc/eval-data-layout.md`；完成后更新 `doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 和一份 `agent_log/`。
- 只读使用主工作区 ignored `eval-data/teacher-labels/20260815-sol-teacher-labels-v1/` 中的冻结批次、其中选中项对应的
  真实归档，以及主工作区已存在的 runtime、GGUF、共享 eval venv/cache 和非密钥本机配置。
- 在 Git common root 的 ignored `eval-data/` 下创建本任务独占的 0700/0600 私有运行目录，保存原始本地输出、
  逐条终态、attempt、holdout 明细、模型私有日志和发布所需私有摘要；只清理本任务明确创建的临时对象。

### 不允许修改

- Plan 032 冻结私有批次及 `eval/locks/local-approval-sol-teacher-labels-v1.json` 的任何内容；不得重新 prepare、
  重新调用 Sol、补标签、换代表样本、重分区或改教师判定。
- canonical static payload v3、`STATIC_INSTRUCTIONS`、`rondo_static_approval_v1`、12,288/512 服务合同、现有
  runtime/GGUF/tokenizer/template、资格 evidence、launcher 身份或 `rondo.local.toml`。
- `mydev/`、`multidev/` 产品代码或正式 Guardian bridge 链；L3 只直接消费 canonical static 合同。
- 16k、5 条超窗证据、L5b 合成数据、L6/LoRA/训练、微调后模型、云 GPU、Local M4 或 Opus 裁判。
- Docker、Cargo、云 API、数据外发、模型/权重/依赖下载、上游基线升级、CI、PR 或远端资源。
- 历史 run、baseline、计划、日志、审计快照或已发布结果的改写；本轮结果只追加。
- 主工作区任何 tracked 文件。主工作区只承载 Git common root 下既有或本任务新增的 ignored 私有数据。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash 或 source；本任务预期不需要 API key。
- 与冻结 40 条无关的私有正文、其他任务私有数据或个人文件。
- 允许程序按严格 reader 在内存中读取获授权的 40 条 canonical payload、教师标签及对应真实 `E_final`，但不得把
  正文、模型原始输出、rationale、risk tags、逐条 holdout 身份或逐条 holdout 指标输出到终端、普通日志或 Git。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

### 3.1 冻结输入与逐条对应

1. 唯一教师来源是批次 `20260815-sol-teacher-labels-v1`。入口先用现有 Plan 032 verifier 或等强复用重新验证
   `ready_for_l3=true`、40 条完整集合和 tracked lock 绑定；已知最终计数为 seed 24、holdout 16，labels SHA-256 为
   `7eaafa25aa99de804559ee77f034f4e69f8ff4227f5cf5d8d70c66f0a7b82a40`。现场任一身份、文件哈希或计数漂移即不得运行。
2. Local 输入必须使用冻结 outbound/manifest 所绑定的同一份 canonical static payload v3 bytes；不得从当前源码重新
   prepare 一批“等价输入”，不得用 Guardian bridge 请求、摘要、裁剪、重排消息或 provider-specific 变体替代。
3. 每条本地 attempt 必须绑定 batch、semantic id、代表 `E_final` SHA、payload SHA、partition 和同一条教师标签。
   导入和运行两侧的样本集合摘要必须相同；未知、重复、额外或跨分区条目使整批不可发布。
4. 教师标签只表达特定时点 Sol 蒸馏目标。公共文案只能使用“教师一致/教师不一致”；“漏放/误拦”字段在本轮不存在
   或保持 `null`，不能根据 Sol 分歧推导。

### 3.2 真实运行前冻结的 L4 指标口径

1. 指标合同必须在第一次正式本地回放前成为 clean committed tracked 内容，并由合成结果测试证明。真实结果出现后
   不得改分母、百分位算法、失败分类或字段含义；若发现合同实现 bug 导致批次无效，只能按 §3.3 保留失败事实、修复并重跑。
2. 每个样本最终且仅属于一个终态：`decided_allow`、`decided_deny`、`structured_output_failed`、`timed_out`、
   `infra_failed`。前两类必须经过完整 `rondo_static_approval_v1` 校验；不得把解析失败、超时或 infra 默认值伪造成模型 deny。
3. `fail_closed` 是设施行为，不是教师或模型判定：后三类不能向下游释放 allow/deny，均计一次 fail-closed；合规模型 deny
   不计 fail-closed。分别发布结构化输出失败数、超时数、最终 infra 失败数和 fail-closed 总数。
4. 教师一致数量只统计终态为合规 allow/deny 且与对应 Sol 标签相同的样本；教师不一致数量只统计合规 allow/deny 中
   与教师相反的样本。主教师一致率固定为 `teacher_agreement_count / comparable_decision_count`；分母为 0 时写 `null`，
   不伪造 0%。同时强制报告 numerator、denominator、`comparable_decision_count / partition_total` 的有效判定覆盖率和
   各失败计数，使判断质量与工程可用性分开、失败也不能从 baseline 消失。
5. 教师与本地 allow/deny 分布分别报告；本地分布只统计合规模型判定，失败类别另列，不以 fail-closed 行为补成 deny。
6. 每条样本延迟从该样本进入实际请求阶段前的 monotonic 时钟起，到其最终终态止；若发生获准的定向 infra 重试，包含该
   样本实际等待与重试开销。seed、holdout 与总体均按升序 nearest-rank
   `index = ceil(p / 100 * n)`（1-based）计算 P50/P95，并记录样本数和单位。
7. input token 使用冻结 census/manifest 中与 payload 绑定的精确计数；output/total token 只使用服务返回且经严格校验的 usage。
   对缺失 usage 不填 0，必须报告可用样本数与缺失数；P50/P95 只在相应已观测集合上计算。最终 tracked schema 应明确
   input/output/total 的名称、单位和 percentile method，不用估算值冒充实测值。
8. 显存指标使用 GPU 独占窗口内的设备级 `nvidia-smi memory.used` 连续采样，至少记录 baseline、peak、delta、采样方法和
   采样是否完整；公共核心指标为整次本地批量生命周期的 peak bytes。采样中断或出现其他 compute process 时不得发布正式 baseline。
9. 上述指标分别形成 seed、holdout 摘要，并由同一纯函数重算 40 条总体摘要。教师 imported 行 `metrics=null`；
   Local auto 行承载冻结的工程/质量 metrics。不得设置“一致率至少 X%”或基于结果决定通过的机械阈值。

### 3.3 运行、失败与重试语义

1. tracked 实现、指标合同及直接测试先在本 worktree 提交。正式运行必须从该 clean committed harness 启动并记录 commit；
   ignored 私有输出不构成 dirty，tracked 结果只在整个批次取得 40 个终态后发布。
2. 真实运行只使用已资格化的唯一未微调 Ministral GGUF、冻结 b10333 CUDA runtime、12,288/512、static payload v3 和
   `rondo_static_approval_v1`。不得换模型、参数、prompt、标签或样本，也不得做额外 warm-up 判定后挑选结果。
3. 不限制为完成本任务所需的受监管本地模型生命周期数量；实现/测试中的小问题、启动前检查问题和可明确窄修的设施问题可在
   授权范围内自主修复验证，不需因一次失败立即停下汇报。但每次真实生命周期仍须留下有界事实并完成现场清理，不能盲目重复同一失败。
4. 对明确且不含模型判定信息的本地 transport/infra 失败项，允许使用完全相同输入定向重试一次，并保留首次 attempt 与原因。
   已收到模型响应后的结构化输出失败、推理超时和任何“不满意”的 allow/deny 都是 baseline 结果，不得重试。
5. 若 runner 自身实现缺陷使完整批次不可解释，允许保留首次失败批次、修复和补回归后再完整运行一次；不能覆盖旧 run id、
   私有 attempts 或失败原因。再次需要改变冻结输入/指标/原则边界，或只能靠内容选择性重跑才能继续时，才停止并请求用户决定。
6. 一批 `outcome=completed` 表示 40 条均已得到上述终态，不表示 40 条均有合规判定。若仍有未尝试、身份不明或未分类条目，
   整批不得以 completed 或 baseline 发布。

### 3.4 shadow 发布与私有数据边界

1. 正式公共结果固定为四条新记录：seed 的 `sol-static/imported` 与 `local-static/auto`，holdout 的同一对记录。
   每对共享 batch、partition、sample count 和集合摘要；run id 唯一且只追加，不覆盖历史。
2. imported 行遵循 `doc/eval-data-layout.md`：不写 `product`，必须写 teacher model/date/prompt version/SHA，
   `binary_sha256=null`、`metrics=null`、`cost.actual_usd=null`、`cost.estimated_usd=0.0`，`git_commit` 记录导入时
   eval harness commit，`artifacts` 指向冻结教师目录。统一结果校验必须显式理解此合同，不能用假 binary/metrics 绕过。
3. Local auto 行必须写 `product=rondo-local` 且 `config.product=config.binary_product=rondo-local`，绑定未微调 GGUF、
   runtime、qualification/serve/request identity、metric contract、教师批次和输入集合；不得携带 Terminal-Bench
   `auto_review_config` 或把本地 loopback 记成云 API 成本。
4. seed `tasks` 若发布，只能含重算所需的 body-free identity、终态、判定、教师匹配、延迟/token 可用性等最小字段；
   rationale、risk tags、payload、`E_final` 和模型原始 envelope 只留私有区。
5. holdout 两条记录、聚合 baseline、WBS、日志和测试输出都只能含整批计数/分布/百分位/集合摘要，`tasks=null`；
   不得出现逐条 semantic/task/review id、文件路径、判定、匹配关系、错误、延迟、token 或模型输出。
6. 私有逐条记录必须区分原始 envelope、严格解析后的 decision、attempt、终态与聚合输入，使用 0700 目录、0600 普通文件，
   不跟踪、不经 symlink 导入 worktree、不回显正文。聚合 baseline 和四条公共记录由程序从该冻结私有批次生成，不能手工填数。
7. 结果发布应复用现有 append-only index、锁与私有 artifact 约定；只做支持本轮 shadow 合同所需的窄扩展，不新增数据库、
   签名、可信链、访问控制、复杂多记录事务或第二套结果库。

### 3.5 本地资源与安全边界

1. 真实模型生命周期必须走仓库现有共享 lock/watchdog，独占 GPU，并与 Docker、重型 Cargo 和其他真实本地模型任务互斥。
   拿不到锁、watchdog、GPU/显存计数或发现未知 CUDA compute process 时 fail-closed，不绕过设施。
2. 仅允许 loopback 访问本地服务；不得调用云 API、外发数据、下载模型/权重/依赖或产生费用。正式 Guardian bridge 不参与。
3. 启动前验证 exact runtime/model/config/qualification identity 和空闲端口；结束后只定点停止本任务已验证的进程，并确认端口释放、
   launcher receipt 清除、无本任务 GPU process、临时工件处理完成。不得终止或删除来源不明对象。
4. 现有 `rondo.local.toml` 与 12k 资格 evidence 只读使用，不做“顺手修正”。`.env.local` 不读取；若现有严格 loader
   因配置要求检查 secret，只允许按根规则静默检查文件安全属性和所需变量非空，不能打印值。

### 3.6 测试、文档与 Git 交付

1. focused tests 至少覆盖：40 条严格集合匹配、imported/auto 字段差异、五类终态、允许/禁止重试、教师一致率分母、
   nearest-rank P50/P95、token missing 语义、allow/deny 分布、seed/holdout 投影、holdout `tasks=null` 与无逐条泄漏、
   指标幂等重算、结果 schema 和中断后不覆盖历史。使用合成 fixture/fake/loopback，不把真实正文写进测试。
2. 运行直接受影响的既有 `teacher_labels`、local approval、artifact/result 测试与 `just eval-lock`（或现场等价门禁）；
   不扩大为全量 eval、Rust、Docker 或 Cargo。真实 40 条运行是测评证据，不替代设施正确性测试。
3. 只有四条记录、聚合 baseline、私有工件和重算结果互相一致，且敏感/holdout 扫描、清理与 Git diff 检查通过后，才能把
   WBS 中 P2 改为完成。WBS 只保留当前状态与下一工作包；详细结果写 baseline/完成历史，执行细节写一份精炼日志。
4. 最终检查主工作区与所有 worktree 状态，只提交本任务 tracked 文件到 `033-l3-l4-unfinetuned-baseline`。
   不 `git add -f eval-data`，不合并、不推送；等待用户交给本审查者独立验收。

## 4. 软性建议

以下内容依据当前代码给出，但不是固定实现路线。执行者可以根据 live code 和 focused tests 采用更窄、更清楚的等强方案。

- 优先在现有 `eval/rondo_eval/local_approval/` 增加一个小型 shadow/baseline 模块，复用 Plan 032 的严格 verifier、
  `LocalApprovalClient`、正式 launcher identity 和 `ArtifactWriter`；如现有职责边界更适合其他局部布局，可自主调整。
- 可把流程保持为少量阶段：只读 `verify/plan`、真实 `run`、离线 `summarize/publish`。阶段命名、CLI 参数、类和函数由执行者决定，
  关键是运行前指标合同已提交、运行中不写 tracked 结果、运行后可从私有终态幂等重算。
- 优先一次启动已资格化服务完成 40 条顺序请求，以减少加载开销并保持 GPU 采样窗口清楚；如果 live launcher 更适合其他同等安全的
  生命周期组织，执行者可选择更优方案，但不能并发请求或改变样本合同。
- 对现有 `artifacts.py` 只补 shadow source-aware 的字段校验和 imported 特例。四条记录不要求新建跨记录审计协议；可在完整批次
  已冻结后依次使用既有 journal 发布，并用唯一 run id 的恢复语义处理普通中断。
- 指标合同可用一个紧凑版本化 JSON/schema/template，也可由版本化代码常量与序列化测试表达；不为一个 baseline 引入插件系统、
  schema registry、数据库或通用统计框架。
- token usage 可在不放宽现有 response 校验的前提下从原始 envelope 旁路提取并严格校验；若某终态没有可信 usage，按缺失计数，
  不为填满表格估算或伪造。
- seed 的逐条公共任务信息不是强制交付；如果整批摘要已足够重算公共结论，可以选择更小的 body-free 投影。holdout 则始终只能摘要。
- focused 测试优先落在新模块测试及受影响的 `test_teacher_labels.py`、`test_local_approval.py`、
  `test_config_and_artifacts.py`；依据实际改动选择最小充分集合，不机械跑全套历史测试。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-15：核对主工作区实际为 `main@1c5f704`，与 `origin/main` 一致且 clean；用户提示中的 `4d61d7b`
  之后已有一条 Plan 032 状态收口提交。
- 已从 `main@1c5f704` 创建分支/worktree
  `/home/sjc/desktop/RONDO/.claude/worktrees/033-l3-l4-unfinetuned-baseline`。
- 已阅读根规则、README、两份 WBS、数据布局、Plan 模板、Plan 030/032、最终独立验收日志，以及当前 teacher-label、
  local client/launcher/qualification、artifact/result 实现和直接测试。
- 已确认冻结教师批次仍在主工作区 ignored 私有区，目录 0700、文件 0600；只读取聚合字段/row keys 复核为 40 条、
  seed 24 / holdout 16、`ready_for_l3=true`，未输出正文或逐条 holdout 信息。
- 已确认当前结果文档合同已定义 `source=imported|auto` 与 imported null 字段，但 live `artifacts.py` 尚未完整支持
  imported 的 `binary_sha256=null`、`metrics=null` 和教师目录 artifact 引用；这是本任务必要的窄实现缺口。
- 用户已一次性授权本计划范围内的 tracked eval-side 实现/测试/文档/提交、只读使用 Plan 032 私有批次与对应真实
  `E_final`、不限模型生命周期数量的现有未微调 Ministral 12k 本地批量推理、明确 transport/infra 项定向重试一次、
  runner 缺陷修复后完整重跑一次、ignored 私有工件与 tracked 聚合结果写入，以及运行期间 GPU/资源独占。
- 规划阶段未修改主工作区 tracked/ignored 文件，未启动模型、GPU 服务、Docker、Cargo 或 API，未运行测试；真实模型运行次数为 0。

### 当前工作

- 已完成。实现、focused tests、真实 40 条回放、结果发布与文档收口均已落地并提交在本 worktree 分支；
  等待审查者独立验收。

### 本任务剩余步骤

- 无。已完成：严格 importer + Local-static runner + 冻结指标合同 + shadow/publication 窄扩展；
  运行前 clean harness 提交（`bbb572d`）；真实 40 条回放；四条 shadow 记录与聚合 baseline 发布（`94492c5`）；
  WBS / 子 WBS / WBS-COMPLETED / 数据布局与一份精炼日志更新。不合并、不推送。

### 阻塞项

- 无。

### 当前验收状态

- focused `test_shadow_replay` 44 项与直接受影响的既有 teacher-label / local-approval /
  artifact-result 测试合计 **326 项通过、0 skip**；`uv lock --check` 85 packages 通过。
- 真实运行：1 个模型生命周期，40/40 首次尝试进入唯一终态（allow 16、deny 19、结构化输出失败 5、
  超时 0、基础设施失败 0、重试 0）；峰值显存 8,048,869,376 B（基线 1,629,487,104 B、1,351 次采样、窗口完整）；
  服务 input token 与冻结 census 40/40 一致；四项现场清理全 true。
- 指标：教师一致 16/35（seed 9/21、holdout 7/14），教师不一致 19，有效判定覆盖 35/40 = 87.5%，
  fail-closed 5，P50/P95 延迟 8,335.01 / 25,758.68 ms。**该批教师标签全部为 `allow`**，
  故本轮一致率不构成有区分度的质量信号，只作固定对照起点。
- 发布：四条 shadow 记录 `20260815-082704844/845/846/847` 与
  `eval/results/baselines/local-approval-unfinetuned-static-baseline-v1.json`
  （SHA-256 `ca0bbc21a24b23b607a1308462fcac16447d4577d779819e6c8f683bb09d4dcd`）。
  在最终交付 HEAD 上重跑 publish 为幂等空操作（exit 0、0 条新记录、baseline SHA 不变）；
  公开 seed 逐条投影可独立重算出 9/21。
- 独立验收（`agent_log/2026-08-15-084543-plan033-independent-acceptance.md`）确认 baseline 数据有效，
  并指出两处窄缺口：统一结果校验未强制 shadow 的 source/side 映射与 `holdout ⇒ tasks=null`；
  发布对 harness commit 采用等值绑定，导致最终 HEAD 无法完成所称的幂等重算。两项均已在本分支窄修并补回归，
  未改动模型结果、指标口径或冻结输入。
- 一次运行前失败：首次用相对路径调用 `with-build-lock.sh`，lease 校验要求 wrapper cmdline 含解析后的
  绝对脚本路径，故被拒（`watchdog_unavailable`）；该次未启动模型、未创建私有目录、未动 GPU。
- 现场限制（如实记录，未改动）：本机 WSL 的 `nvidia-smi --query-compute-apps` 始终返回空行，
  因此"无外来 CUDA compute 进程"子检查实际空转；设备级 `memory.used` 采样正常。

### 交接边界

- 执行者对模块划分、CLI、内部类型和测试组织保留自主权；审查者按冻结输入、指标先后顺序、结果/隐私合同、真实运行证据、
  清理和 Git 边界验收，不把软性建议或个人实现偏好升级为门槛。
- 本任务完成后冻结此计划；下游只链接 WBS 的 L5b/L6，不在本计划扩写 P3 或 Local M4 路线。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | seed 与 holdout 各发布一对 imported/auto shadow 记录，共四条 | 既能逐分区匹配，又能让 holdout 强制 `tasks=null`，避免在一条混合记录里泄漏 | 结果布局 | 已采纳 |
| 002 | 主教师一致率只在有效判定间计算，同时强制发布有效判定覆盖率与失败分类 | WBS 要求判断质量与工程可用性分开；解析失败/超时不能伪装成相反判定，也不能从 baseline 消失 | L4 指标 | 已采纳 |
| 003 | 指标合同必须先以 clean commit 冻结，再运行真实模型 | 用简单 Git 时序满足“看结果前冻结”，不增加签名或审计设施 | 执行顺序 | 已采纳 |
| 004 | tracked 开发留在 worktree，教师输入与逐条本地输出使用 Git common root 的 ignored 私有区 | linked worktree 不共享 ignored 数据；公共代码和私有正文仍保持边界清楚 | 数据落点 | 已采纳 |
| 005 | transport/infra 可定向重试一次，模型判定、解析失败和推理超时不得按内容重跑；runner 缺陷可保留失败后完整重跑一次 | 给普通工程窄修留出余量，同时防止按结果挑选 baseline | 重试语义 | 已采纳 |
| 006 | 复用并窄扩展统一结果库，不为四条 shadow 记录新建第二套发布或可信体系 | 当前缺口是 schema/runner 支持，不需要扩大基础设施 | 实现范围 | 已采纳 |
