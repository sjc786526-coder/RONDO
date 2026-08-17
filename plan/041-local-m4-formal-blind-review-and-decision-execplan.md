# Plan 041：正式 Local M4 三方盲评、真实 holdout 锚点与人判收口

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理本轮正式 Local M4；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

消费 Plan 032、036、037 已冻结的正式工件，完成 RONDO Local 首轮正式 M4：对全部 130 条 synthetic
validation 上的 `sol-static`、同源未微调 `local-static`、微调后 `local-ft-static` 做两批三方盲评；另用
Plan 032 的真实 holdout 与 Plan 037 的同一 paired-GGUF 形成独立 sanity anchor。两组分别裁判、解盲和聚合，
最后把事实结果交给用户，由用户作出且仅作出“采用 / 保留为实验 / 停止”之一的正式决定。

本任务不再训练、调参、量化、调用 Sol 或改变样本，也不把“采用”扩展为生产启用。质量不理想不是执行失败；只要
冻结横评合同有效、结果完整且用户决定已记录，M4 即可按实际结论完成。

### 完成/验收标准

- [x] synthetic 正式主体精确覆盖冻结 validation 全部 130 条，两批各 65 条；直接消费 Plan 037 已验真的
      390 行三方输入，不重新运行两种 Local 的 130 条推理，也不重新调用 Sol。
- [x] synthetic 两个裁判包均通过匿名性、位置平衡、完整集合和 prompt/package 身份校验；不存在 side、模型、
      工件、路径、seed 或 mapping 泄漏。
- [x] 真实 holdout 从 Plan 032 冻结 manifest/标签严格重验后物化，当前预期 16 条，正式数量以重验通过的冻结
      manifest 为准；不增删、不抽样、不按标签或输出选择样本。
- [x] holdout 的 Sol 侧只导入既有 point-in-time 标签；两种 Local 使用 Plan 037 同一 canonical pair、同一
      runtime/template/request/sampling/output 合同串行运行，每个 sample-side 只留下一个诚实终态。
- [x] holdout 裁判包与 synthetic 分开，且同样通过匿名性、位置平衡、完整集合和身份校验；两组不共享 aggregate、
      不合并分母，tracked holdout 投影不泄漏逐条正文、身份、输出、理由或映射。
- [x] 所有正式裁判结果都来自人在场的 Claude Code 订阅入口与 WBS 指定的 Opus 5，使用仓库内既有冻结
      prompt/schema；逐批记录实际模型标识、判定日期、prompt 和 package 身份，并注明只能代表判定时点。
- [x] 只有在 synthetic 和 holdout 的全部正式批次结果都完整、唯一且验证通过后，才进行最终解盲和聚合；任何无效
      结果不会混入部分 aggregate。
- [x] 正式结果清楚报告：两种 Local 各自相对 Sol 的教师一致情况；相对 Opus 的漏放、误拦、偏好/理由质量与结构化
      可用性；微调前后直接差值；synthetic 主体结论；真实 holdout sanity anchor 的独立结论与限制。
- [x] 用户已明确选择“采用 / 保留为实验 / 停止”之一，决定和依据已精炼记录；即使选择“采用”，也未改变生产默认、
      provider、launcher 或部署配置。
- [x] 直接相关 pure/local 测试与必要真实运行检查通过，未运行项和真实终态如实记录；服务进程、监听端口和 GPU 显存
      已清理，040/M-2 与其他 worktree 未受干扰。
- [x] tracked 结果、Plan 状态、Local 专项 WBS、顶层 WBS、完成历史和精炼日志按职责同步；独立审查通过，真实问题已
      整改复验。041 worktree 形成清晰提交，但未合并、未推送、未重命名或删除分支/worktree。

## 2. 范围

### 允许修改

- `plan/041-local-m4-formal-blind-review-and-decision-execplan.md` 的“当前状态”和“关键决策记录”。
- `eval/rondo_eval/local_approval/` 内为正式 holdout 物化、同 pair 运行、正式打包/导入/解盲/聚合与结果投影所需的
  最小实现或局部修复。
- `eval/tests/` 内直接相关的 pure/local 回归与合成 fixture；必要时可窄改既有相关测试，避免重复建设测试套件。
- `eval/locks/` 或 `eval/reports/` 下不含正文和逐条 holdout 信息的正式 M4 身份/结果摘要；具体落点按现有职责选择，
  不把 M4 会话内裁判伪装成自动运行的 shadow/TB 结果。
- 若真实数据落点或固定产物合同确需补充，可精炼更新 `doc/eval-data-layout.md`。
- 任务真正收口后更新 `doc/WBS.md`、`doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 与必要的精炼
  `agent_log/`；只写各自职责内的当前事实或历史证据。
- 主工作区 ignored `eval-data/` 内本任务专用、持久化的 holdout 输入/本地输出、synthetic 与 holdout 裁判包、
  原始裁判结果、私有映射、解盲和 aggregate；目录保持 `0700`、普通文件保持 `0600`。

### 不允许修改

- `training/local-approval-synthetic-v1/` 的冻结 train/validation、Plan 032 教师标签、Plan 037 的模型、adapter、
  GGUF、recipe、训练/转换 receipt、390 行三方输入及 canonical pair evidence。
- `eval/templates/cross-eval-judge/` 内既有冻结裁判 prompt/schema/blinding 语义；如果现场事实证明必须变更这些合同，
  先暂停并请求用户确认，不在本任务中静默升版或改判据。
- `eval/results/runs.jsonl`、既有 L3/L4 shadow 行和 baseline；Local M4 是会话内人判定，不冒充自动测评运行。
- `mydev/` 的生产默认、Guardian/launcher/provider 配置和正式部署开关；本任务不因“采用”决定顺带启用模型。
- `multidev/`、`doc/WBS/multi-agent-trusted-evidence.md`、Plan 040、040/M-2 日志、分支或 worktree。
- Plan 032/036/037 的冻结计划和历史日志、README 稳定事实、CI/PR、上游基线及无关文件。

### 不允许读取/查看

- `.env.local` 的任何内容；不得打开、搜索、打印、复制或 source。任务不需要 API key。
- 与本任务无关的私有运行数据、密钥、个人配置和其他 worktree 内容。
- 进入正式 Opus 裁判阶段后，不得读取该批私有 blinding seed、mapping、side 原始输入或模型身份材料；裁判只读取
  冻结 prompt/schema、judge request 与匿名 package。文件工具只承担这些正式输入与结果的运输。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、得到更好结果或凑齐绿色状态而违反。

### 3.1 冻结输入与成对归因

1. synthetic 只认 Plan 036 cohort 与 Plan 037 正式导入通过的 390 行、pair receipt 和 private evidence；执行前
   重新验证 `ready_for_blind_packaging`。不得重跑 synthetic Local、重问 Sol、替换失败/不理想输出或从中抽样。
2. holdout 只认 Plan 032 已冻结的 `holdout` 分区、对应 point-in-time Sol 标签及其身份/哈希。物化时从真实私有
   manifest 重算 sample、canonical payload、partition、教师 prompt/model/date 与集合完整性；若来源之间无法一致
   重建正式集合，停止并报告，不人工补项、猜测或重划 cohort。
3. holdout 两种 Local 必须使用 Plan 037 同一 canonical paired-GGUF 及 formal pair evidence。除 side/工件身份与
   training receipt 外，两侧共享 base lineage、runtime、chat template、request、sampling 与 output contract；
   Plan 033 baseline 或其他模型不能替代。
4. 每个 Local sample-side 只留下一个诚实 terminal。allow/deny、结构化失败、拒绝、超时和 fail-closed 都是结果事实；
   不补造 deny，不因内容不满意而重跑。只有在尚未形成样本终态的基础设施/运输故障下，才可按同一冻结输入做可恢复
   的局部续跑，并保留足以区分 attempt 与最终 terminal 的轻量记录。

### 3.2 本地模型与资源现场

1. 仅为正式 holdout 串行加载两枚 Plan 037 GGUF；两侧不得同时驻留 GPU，也不与 040 的重型 Cargo、Docker 或其他
   真实本地模型任务并发。若共享重型锁或相应进程正在占用资源，041 只等待，不中断、不清理、不绕过门禁。
2. 加载前确认 Windows `C:` 盘实际余量、项目占用、GPU/进程/端口和共享重型资源状态可读且满足现有门禁；拿不到
   必要计数或容量不足时 fail-closed。不得用 WSL 虚拟余量代替宿主容量，也不得删除来源不明资产腾空间。
3. 两侧完成或异常退出后都必须停止本任务服务，确认任务进程和监听端口消失、GPU 显存回落；只清理本任务明确创建的
   临时对象，不触碰 040 或其他任务资源。
4. 本任务不运行 Docker、重型 Cargo、训练、转换或量化，不使用 RunPod、Hugging Face、云 GPU、付费 API，不创建、
   修改或删除远端资产；也不新增 Sol/Opus 程序化 provider。

### 3.3 正式 Opus 裁判与重试

1. 用户已授权将 synthetic 与真实 holdout 的正式匿名裁判包通过 Claude Code 订阅入口外发给 WBS 指定的 Opus 5，
   首次外发前不再要求用户抽查样本。外发前仍须做一次轻量敏感内容检查；若发现明显不应外发的敏感内容，暂停并询问，
   不自行删改样本或正文。
2. 裁判必须使用仓库内既有冻结 prompt/schema，同一 partition 的所有批次共享同一判据。裁判看不到 side、模型、路径、
   pair、seed 或 mapping，不从措辞/位置猜模型身份，也不调用工具调查仓库、网络或额外证据。
3. 会话中断、输出截断、传输失败或 schema/格式无效时，允许在同一冻结 prompt、package、judge model 和日期身份下
   有界续传或重试受影响部分，并重新做完整集合校验。不得因裁判结论、偏好或质量不满意而重判；若 Opus 5 不可用或
   必须换模型，暂停并请求用户确认。
4. 每批结果必须记录订阅界面当时实际显示的 Opus 模型标识与实际判定日期。订阅侧模型版本不由仓库冻结，结论只能
   表述为 point-in-time 判定，不宣称完全可复现。
5. synthetic 与 holdout 的所有正式裁判批次都必须先完成身份、schema、完整性、唯一性和 side 泄漏检查；全体通过后
   才允许最终解盲和各自聚合。失败批次不得被跳过，已验证批次也不得先形成会影响后续裁判的正式结果结论。

### 3.4 聚合、结论与人工决定

1. synthetic 与 holdout 使用独立 cohort、private package、结果、解盲文件、aggregate 和分母；任何聚合入口都必须
   拒绝混合 partition。holdout 只作真实分布 sanity anchor，不据此另做三方强弱排名。
2. 相对 Sol 只称“教师一致/不一致”；漏放（Opus 判 deny 而 Local allow）与误拦（Opus 判 allow 而 Local deny）只按
   Opus 独立判断计算。结构化失败、超时和 fail-closed 与判断质量分开报告，微调前后使用同口径直接作差。
3. 结果只陈述完整数据事实、已知限制和可理解的比较，不设置新的机械质量阈值。Opus 同时参与项目开发的独立性瑕疵和
   订阅模型不可完全复现限制必须注明，但不为此建设额外审计、签名、多模型共识或隔离系统。
4. aggregate 完成后向用户呈现足够作决策的摘要并等待用户本人选择“采用 / 保留为实验 / 停止”。执行者不得代替用户
   作正式选择；取得决定前不得把 M4 标为完成。无论选择哪项，只记录决定，不改生产默认或开展部署。

### 3.5 工作区、并行协调与交付

1. tracked 实现、测试和文档只在 041 worktree 编辑。linked worktree 不共享 ignored 数据，任务所需 Plan 032/037
   私有来源以及新生成的正式 M4 私有产物必须留在主工作区 `/home/sjc/desktop/RONDO/eval-data/` 的明确任务目录；
   这不授权修改主工作区 tracked 文件，也不得用 symlink 或 `git add -f` 把私有数据带入 Git。
2. 041 不进入或修改 040 worktree。普通编辑/Python/Opus 会话可与 040 并行；本地模型阶段按 §3.2 串行。同步顶层
   `doc/WBS.md` 和 `doc/WBS-COMPLETED.md` 前重新读取届时最新 `main`，只叠加 Local M4 事实，保留真实 M-2 状态。
3. 私有目录/文件保持 0700/0600，写入不覆盖未知既有执行目录；真实正文、逐条 holdout 身份、原始模型输出、mapping、
   密钥和模型路径不得进入 Git、普通终端、公开摘要或日志。
4. 修复真实 bug 时先补相应回归，只跑直接相关 Python/pure 测试、必要 holdout 模型运行和正式导入/打包/结果校验；
   不扩大为全量 eval、Cargo、Docker、CI 或 PR。skip/未运行不能表述为通过。
5. 执行者完成后自查 diff、私有落点、敏感信息和所有 worktree 状态，只提交 041 worktree 分支并交给独立审查；根据
   审查中的真实问题自行整改、复验并追加提交。未经用户后续明确批准，不合并 main、不推送、不重命名/删除分支或
   worktree。

## 4. 软性建议

以下内容是基于当前 live code 的执行建议，不是固定路线。执行者可依据实际代码、测试和运行结果采用更简单或更稳妥
的等强方案，并在关键决策记录中简要说明。

- 优先复用 `rondo_eval.local_approval.cross_eval` 已有的 synthetic 正式 CLI、private holdout bundle、匿名位置平衡、
  strict judge import、unblind/aggregate 和 batch-only holdout projection；只把现有库级 holdout 合同接成正式可操作
  闭环，不另建测评框架、数据库或通用审计系统。
- 优先复用 Plan 037 的 `l6_b10333_pair` / `paired_outputs` 正式来源重验、串行服务和 terminal journal 语义，把输入
  参数化为 private holdout bundle；若局部抽取比扩展原 CLI 更干净，可自主选择。
- synthetic 可使用一个新的正式 execution 目录并复制/导入 Plan 037 的已验真三方工件；holdout 使用独立 execution
  目录或同一任务命名空间下明确分隔的目录。重点是两组合同、文件与 aggregate 不混，不强制具体文件拆分。
- 在进入裁判阶段前一次性生成并验证所有匿名 package；裁判阶段只让 Opus 读取 prompt/schema/request/package，生成
  对应 JSONL。长包可按既有 batch 或上下文容量安全续传，但不要把同一冻结 batch 改成不同判据。
- tracked 正式结果优先只保存可公开的聚合计数、直接差值、模型/日期/prompt/package 身份和 private artifact 哈希；
  holdout 使用既有 batch-only 白名单投影。人可读结论保持简洁，详细逐条结果永久留在 ignored 私有目录。
- focused 门禁优先覆盖 holdout 正式物化、同 pair 归因、mixed terminal、全批验证后才解盲、partition 隔离、结果投影
  与用户决定记录；不为已经由 Plan 036 覆盖的通用盲化负向场景重复堆测试。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 全部完成。synthetic 130 条与真实 holdout 16 条分别完成物化/导入、盲化打包、正式裁判、解盲与聚合，
  用户已作出唯一人判：**保留为实验**（`keep_as_experiment`，2026-08-16）。
- synthetic 直接消费 Plan 037 已验真的 390 行，未重跑 130×2 推理、未重新调用 Sol；holdout 从 Plan 032 冻结
  批次严格重验后物化 16 条，两种 Local 使用与 Plan 037 逐字节相同的 pair receipt（`1d57def1…129c`）串行运行。
- 结果：synthetic 未微调教师一致 104/130、误拦 26，微调 130/130、误拦 0；holdout 未微调 14/16 合规、
  教师一致 8/14、误拦 6，微调 16/16 合规、教师一致 15/16、误拦 1；两分区漏放均为 0，从不合并分母。
- tracked body-free 结论锁 `eval/locks/local-approval-m4-formal-review-v1.json`（`4e27d06a…1d89`，
  独立审查后按准确分项结果重述 rationale 并重新发布）；未改动生产默认、provider、launcher 或部署。
- focused unittest 253/253 通过；本地模型阶段持共享重型锁串行运行，进程/端口/显存已清理。

### 当前工作

- 已收口。两轮独立审查发现均已窄修并复验，最终独立验收于 2026-08-17 通过；验收报告为
  `agent_log/2026-08-17-001729-plan041-final-independent-acceptance.md`（验收提交 `545fc77`）。

### 本任务剩余步骤

- 无。用户已授权本轮合并 main、推送 origin/main 和归档本地任务分支，交付后本计划冻结。

### 独立审查整改（2026-08-16）

1. 顶层权威文档已按 main 当前状态吸收 Multi M-2 完成历史与 M-3 下一阶段，并补记 Local M4 里程碑行；
   `doc/WBS.md` 与 `doc/WBS-COMPLETED.md` 的全部 Multi 内容现与 main 逐字一致（含里程碑表的
   `Multi M-2` 行）。与 main 的三方合并冲突只剩两类，且每处本分支都是更新的事实：`doc/WBS.md` 的四处
   Local 状态区
   （抬头行、方向 2 行、3b 工作包段、方向表第 2 行，其中抬头行是 main 抬头的超集）和 `doc/WBS-COMPLETED.md`
   末尾的 append/append。
2. 匿名扫描补上直接身份措辞：`local` 名词表增加 decision/judgment 等，并覆盖 tuned / untuned /
   (un)fine-tuned 后接明确 side noun 的情形；
   同时把大写 `Local` 的连字符复合词（真实 Guardian policy 的 `Local-vs-prod note`）排除，避免新的误报。
   四个正式 package 的候选侧扫描仍为 0 命中，四份 judge result 也为 0，**无需重判**。
3. `doc/WBS.md` 与结论锁的“每一项指标都改善”改为准确分项：明确列出改善项，并记录漏放两分区维持 0、
   synthetic 结构化可用性两侧同为 130/130、`sole_preferred` 由 5 降为 0。结论锁因此重发布，
   引用其 SHA-256 的文档同步更新。`keep_as_experiment` 及其依据不变。

### 阻塞项

- 无。

### 当前验收状态

- **通过。** 正式结果完整、用户决定已记录、tracked 结论锁已发布，focused unittest 253/253 通过；最终独立验收
  确认任务目标完成，无剩余整改项。生产启用不在本任务范围内。

### 交接边界

- 执行者在目标与硬边界内自主选择最小完整实现，不把软建议当成固定文件/CLI 设计。
- 审查者按冻结输入、同 pair、盲评完整性、partition 隔离、真实结果、用户决定、测试和 Git/资源现场验收，不以软建议
  的具体实现路线作为额外门槛。
- 本任务完成后冻结本计划；若有后续生产启用或部署工作，只由 WBS 另行安排，不在本计划延伸。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | synthetic 直接消费 Plan 037 现有 390 行，禁止重新调用 Sol 或重跑 130×2 Local | 正式输入已完整验真，重复生成会引入挑样与时点漂移 | synthetic 输入 | 已采纳 |
| 002 | 真实 holdout 使用 Plan 032 冻结集合和标签，Local 两侧复用 Plan 037 同一 paired-GGUF，独立于 synthetic | 提供真实分布 sanity anchor，同时保持训练隔离与成对归因 | holdout | 已采纳 |
| 003 | 用户取消首次外发前样本抽查，但保留明显敏感内容的暂停门 | 用户已明确授权正式匿名包外发，原则性隐私边界仍不可绕过 | 数据外发 | 已采纳 |
| 004 | 中断、截断、传输或 schema 无效允许同冻结合同有界恢复；不允许按结论重判 | 给可恢复的小问题合理冗余，不让结果偏好影响裁判 | 裁判执行 | 已采纳 |
| 005 | 不设质量阈值，质量好坏不决定执行成功；唯一正式产品决定由用户作出 | M4 是人判里程碑，不是自动晋级门 | 完成语义 | 已采纳 |
| 006 | tracked 工作留在 041 worktree，ignored 私有来源/结果留在主工作区 `eval-data/` | linked worktree 不共享 ignored 数据，且正式会话产物需持久保留 | 工作区 | 已采纳 |
| 007 | 041 只提交 worktree 分支；合并、推送、归档等待用户另行批准 | 遵循本次明确交付要求 | Git 交付 | 已采纳 |
| 008 | 订阅侧 Opus 结果记录实际模型标识与日期，只声明 point-in-time 判定 | 订阅模型版本无法由仓库冻结，不能宣称完全复现 | 结果限制 | 已采纳 |
| 009 | 顶层权威文档末尾串行同步并基于届时最新 main 保留 Multi 状态 | 040/M-2 正在并行推进，旧分支文档不能覆盖新事实 | 并行协调 | 已采纳 |
| 010 | 真实 holdout 出现两个既有 terminal failure（未微调侧结构化输出失败），经用户现场授权新增 **holdout-only** terminal-carrying v2 裁判合同 | 冻结 v1 包每条只能装三个 decision，无法表达已经产生的真实结果；这是完整表达既有结果的格式兼容，**不得**用于重跑、挑样或改变裁判标准 | 裁判合同 | 已采纳 |
| 011 | v2 只作用于 holdout：synthetic 两批继续用冻结 v1 prompt/package/schema，v1 文件保持冻结不修改；无判定候选记为 `no_decision`/`not_applicable`，禁止进入 `preferred_candidates`，也不得当作隐含 deny | 保持合成主体判据不漂移，同时让 16/16 完整集合可判 | 裁判合同 | 已采纳 |
| 012 | 漏放/误拦与裁判一致率只在该侧产生有效 decision 时计算；结构化失败单独进入可用性口径，教师一致率同时报有效判定分母与完整覆盖率 | 判断质量与工程可用性不混算 | 指标口径 | 已采纳 |
