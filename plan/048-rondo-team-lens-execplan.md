# RONDO Team Lens ExecPlan

> 本计划是任务 B 的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。普通实现选择、窄修和有界重跑不属于合同变更。
> 本计划只描述 Team Lens；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在不建立第二套 tracing、不参与 runtime 调度、也不保存正文的前提下，完成一个本地离线 Team Lens：同一个消费者读取
冻结 Codex 与 RONDO Multi 的原生 rollout trace bundle，先归约成确定性、规范化、body-free 的 `team_view.json`，
再只从该数据合同生成可离线打开的单文件 `team_report.html`。

本任务按顺序完成两个阶段，但作为一个任务一次收口：

1. **数据 MVP**：读取原生 bundle、明确字段可用性与缺口、输出 `team_view.json`。
2. **静态可视化**：只读取 `team_view.json`，输出 `team_report.html`。

本计划冻结数据边界、降级语义与完成证据，不预先固定编程语言内部结构、图形布局、CSS 风格、模块拆分或是否复用某个
现有 helper。执行者可依据实时代码选择更小、更清晰的实现。

### 完成/验收标准

#### 阶段 1：数据 MVP

- [ ] 用同一个公开入口读取冻结 Codex 与 RONDO Multi 的代表性原生 rollout bundle；产品身份由调用者显式给出为
      `codex` 或 `rondo-multi`，不得通过“是否看见 team tool”猜测产品。
- [ ] 每个输出至少包含下方“最小数据合同”的顶层语义，并为字段类别给出
      `available`、`partial`、`unsupported`、`not_applicable` 四态之一和简短 reason code。
- [ ] 共有数据覆盖可机械取得的 Agent/thread、Codex turn、inference、模型/provider、工具与 terminal 活动、
      Agent interaction、writer sequence/时序、生命周期状态与用量；某项取不到时显式降级，不补默认值冒充事实。
- [ ] RONDO 专有数据覆盖可机械取得的 Team revision、per-inference projection、Event/Version、route、Fact 身份和关系。
      无法完整机械还原的类别可以是 `partial` 或 `unsupported`，但不能靠文本含义、ID 外观或时序邻近猜关系。
- [ ] Codex 的 Team State 类别必须是 `not_applicable` 且数据为 `null`，不得用空 Event/Version/Fact 数组伪装成
      “RONDO Team State 存在但本轮为空”。真正可用且计数为零的普通类别仍可使用空数组。
- [ ] `team_view.json` 采用允许字段白名单，不含 prompt、response、reasoning、agent message、工具参数/结果正文、
      code cell 源码、命令/stdin/stdout/stderr/cwd/path、Fact 正文、title/summary/handoff/note、preview、raw payload
      reference 或原始 trace 文件路径。模型名、工具名、状态、计数、稳定对象 ID、数值 usage 与时序元数据可以保留。
- [ ] 同一固定 bundle 在相同 product 参数下重复归约，输出 JSON 字节一致；数组排序、对象引用和并列毫秒内顺序以
      原生 stable ID / writer sequence 等机械事实决定，不依赖目录遍历、HashMap 顺序、当前时间或随机数。
- [ ] 缺少可选字段或产品确实不支持某类别时生成诚实的部分结果；原生 reader/reducer 已拒绝的 manifest/schema、
      必需身份或引用错误继续拒绝，不能静默拼接另一 bundle 或输出看似完整的报告。本任务不另建通用完整性、可信或
      对抗审计层。
- [ ] 使用离线、合成、body-free fixture 覆盖两侧原生布局、确定性、四态降级、Codex `not_applicable`、RONDO 关系、
      原生 reader 必需错误和正文不出站；测试不得提交真实 raw trace。
- [ ] 定向 fixture 至少证明：没有预生成 `state.json` 仍能消费原生 bundle；direct 与 code-mode 两种 Team tool result
      都按同一语义归约；`evidence_refs_omitted > 0` 会把 Fact flow 标为 `partial`；`wait_agent` 只记为工具/等待活动，
      不伪造成原生 interaction edge。

#### 条件 hook 门

- [ ] **先完成零 hook 验证**：先在不改 `multidev/` runtime/trace writer 的状态下实现并测试共有归约，并用代表性
      RONDO bundle 形成一份精炼的字段矩阵。源码可见但 bundle 未证实的字段不能算 `available`。
- [ ] 只有当机械证据证明 Team Attention Map、Event/Version 关系或 Fact flow 中至少一项核心 RONDO 视图无法在
      不猜测的情况下形成，才允许启用条件 hook；“实现方便”“希望字段更漂亮”或解析代码略复杂不构成触发理由。
- [ ] projection 的零 hook 路径必须覆盖自由 title/summary/handoff/note 含换行并伪装成结构行的合成回归。若现行文本
      语法不能在这些输入下无歧义地区分身份/关系，projection 只能标为 `partial`/`unsupported`，或按本门触发最小 hook；
      不能把“当前样本恰好可解析”升级成通用可用。
- [ ] 若不触发 hook，在 plan 当前状态记录“零 hook 足够”及验证依据；若触发，在任何 runtime 编辑前先在 plan 当前状态
      和一份精炼 agent log 中记录：缺失字段、受阻视图、现有 trace 为什么不足、拟补的最小结构化 metadata 和对应测试。
- [ ] hook 只补上述核心视图所需的最小 RONDO metadata，复用原生 `TraceWriter`、原生 sequence/thread/turn context、
      raw event/reducer 与现有 Team State 事实来源；不得修改冻结 Codex，不得建立新 writer、独立序号/线程身份、
      mailbox 记录、Team Trace JSONL、旁路状态或常开 telemetry。
- [ ] 如触发 hook，零 hook 缺口证据和先失败后通过的定向测试保留在提交中；hook 仍不得把任何正文写进
      `team_view.json` 或新增的结构化 metadata。
- [ ] 如触发 hook，同一消费者仍须读取未带新 metadata 的旧 Codex/旧 RONDO bundle，并按四态诚实降级；不能把 hook
      变成所有历史 bundle 的强制前置。

#### 阶段 2：静态可视化

- [ ] 报告生成器只接收 `team_view.json`；其代码路径不读取、定位或重新解析 raw bundle/payload。
- [ ] 生成确定性、无需网络即可打开的单文件 `team_report.html`，CSS、脚本和所需规范化数据全部内嵌，不引用 CDN、
      字体、图片、source map 或其他外部资源，也不要求本地服务端。
- [ ] 共有视图覆盖 Agent swimlane/timeline、模型与工具活动、通信/等待和摘要信息；RONDO 专有视图覆盖 Team
      Attention Map、Event/Version 关系和 Fact flow。具体布局、交互和视觉风格由执行者自主选择。
- [ ] `available`、`partial`、`unsupported`、`not_applicable` 在相关视图中清楚可见；各视图对同一 Agent、Event、
      Version、Fact 和时间顺序使用同一规范化身份与排序，不各自重新推断。
- [ ] 内嵌数据与 DOM 渲染安全处理 `<`、`&`、引号、`</script>` 等输入；不得因模型名、工具名或 ID 中的字符生成
      新脚本/HTML。报告中不出现被归约器排除的正文或 raw 路径。
- [ ] Codex 与 RONDO 两侧 fixture 均能生成报告；同一 `team_view.json` 重复生成的 HTML 字节一致，并有定向测试证明
      关键视图、降级标记、自包含与“renderer 不读 raw trace”边界。

#### 最小数据合同

`team_view.json` 的稳定顶层语义冻结为下列骨架；执行者可在不改变这些语义和 body-free 边界的前提下细化嵌套字段：

```json
{
  "schema_version": 1,
  "source": {
    "product": "codex | rondo-multi",
    "trace_schema": {
      "manifest_version": 1,
      "raw_event_versions": [1],
      "reduced_state_version": null
    },
    "trace_id": "...",
    "rollout_id": "...",
    "root_thread_id": "..."
  },
  "availability": {
    "agents": {"status": "available", "reason_codes": []},
    "turns": {"status": "available", "reason_codes": []},
    "inferences": {"status": "available", "reason_codes": []},
    "usage": {"status": "partial", "reason_codes": ["example_reason"]},
    "tools": {"status": "available", "reason_codes": []},
    "terminal": {"status": "available", "reason_codes": []},
    "interactions": {"status": "available", "reason_codes": []},
    "timing": {"status": "available", "reason_codes": []},
    "team_revisions": {"status": "not_applicable", "reason_codes": ["codex_has_no_team_state"]},
    "team_projections": {"status": "not_applicable", "reason_codes": ["codex_has_no_team_state"]},
    "team_events_versions": {"status": "not_applicable", "reason_codes": ["codex_has_no_team_state"]},
    "team_routes": {"status": "not_applicable", "reason_codes": ["codex_has_no_team_state"]},
    "team_facts": {"status": "not_applicable", "reason_codes": ["codex_has_no_team_state"]}
  },
  "agents": [],
  "turns": [],
  "inferences": [],
  "tools": [],
  "terminal": [],
  "interactions": [],
  "team": null,
  "summary": {}
}
```

没有预生成/消费 reduced state 时，`reduced_state_version` 为 `null`；实际消费 reduced state 时才记录其独立数字版本。
`raw_event_versions` 记录本 bundle 实际出现的版本集合，不用 manifest version 代替。

约束重点是字段类别、身份引用、四态降级和正文白名单，不要求 executor 机械照搬示例 reason code、记录拆分或内部类名。
若 nested schema 的更优调整不会破坏验收，可在“关键决策记录”中说明后实施；不需要为普通 schema 窄修重新请示。

## 2. 范围

### 允许修改

#### 首批固定写集

- `eval/rondo_eval/team_lens/**`：消费者、规范化 schema/serializer、静态报告生成器和离线入口。
- `eval/tests/test_team_lens*.py`：Team Lens 定向测试。
- `eval/fixtures/team-lens/**`：仅限小型、合成、body-free fixture 或 fixture 描述；真实 raw trace 不得进入。
- `eval/rondo_eval/multi_m5/trace.py` 及其现有定向测试：只有提取真正共用的 bundle reader 能净减少重复且不改变 M-5
  判据时才可窄改；否则保持不动。
- `eval/pyproject.toml`、`eval/uv.lock`：只有一个小型离线依赖明显降低总体复杂度时才可同步修改；优先使用标准库和现有
  依赖，不为了图表建立前端 toolchain。
- 本计划的“当前状态”和“关键决策记录”，以及一份或少量有实质信息的 `agent_log/`。

#### 条件写集

- 仅在条件 hook 门通过后，允许窄改 `multidev/codex-rs/rollout-trace/**` 和将最小 metadata 接入原生 trace 所必需的
  RONDO 调用点、相邻定向测试/生成文件。条件写集不包含 `codex-team-state` canonical 状态实现，也不自动授权依赖锁。
- 若 hook 必须改 Rust 依赖、共享 Cargo/Bazel 锁或 A 独占测试入口，不得抢改；记录需求并交给最终整合者，或选择无需
  改共享写集的等强实现。

### 不允许修改

- `.claude/worktrees/047-team-state-sequence-properties` 及任务 A 的任何内容；任务 A 独占
  `multidev/codex-rs/team-state/**`、Rust 测试依赖/锁和主动性质测试入口。
- `codex-source-code/`、`mydev/`、冻结 `codex-doc/`、既有历史 plan/log/audit snapshot、训练/模型资产和无关 eval 设施。
- `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md` 等共享规划文档；由 A/B 均验收后
  的最终整合批次统一同步。
- runtime 调度、Team State canonical 状态、Agent 协议、模型上下文语义、在线服务、数据库、遥测后台、独立前端工程、
  benchmark/评分、主动委派收益对比、CI/PR、上游基线升级和无关重构。
- 真实 trace、prompt/response、命令输出、Fact 正文、个人数据、密钥、模型权重或执行生成的
  `team_view.json`/`team_report.html` 成品提交；合成测试素材除外。

### 读取/查看边界

- 不得打开、搜索、打印、复制、记录或 source `.env.local`；本任务不需要密钥。
- 可以只读检查主工作区中指定的 `codex-source-code/` 源码和指定的冻结 Codex/RONDO bundle，因为这些 git-ignored
  资产不会出现在工作树。检查 raw bundle 时优先用程序做 schema/metadata 统计，不用 shell/日志打印 payload 正文。
- 若现有 eval 环境不可用或本任务确实修改依赖，可使用仓库既有 `just eval-sync`；它会从 worktree 写入 common-root 的
  ignored `eval/.venv` 与 `eval-data/uv-cache`。这是唯一预期的主工作区 ignored 写例外，只能用于本任务普通依赖物化，
  执行日志与交付必须单独说明是否发生；不得借此写主工作区受跟踪文件或其他 ignored 数据。
- 不查看与本任务无关的 `eval-data/`、`test-data/`、其他 worktree 未提交内容、个人配置或项目外文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或改善视觉效果而违反。

1. **并行隔离**：所有受跟踪编辑、任务输出和提交只在
   `.claude/worktrees/048-team-lens`（分支 `worktree-048-team-lens`）进行。明确知晓任务 A 并行存在；不切换、
   清理、stash、覆盖、格式化或提交 A/主工作区的内容。测试临时文件使用临时目录；只有上节明确的共享 ignored Python
   环境/缓存可以按需物化。发现其他共享写集需求时留给最终整合，不抢改。
2. **单一原生事实链**：消费者读取现有 Codex rollout bundle/reducer 语义；不得通过 Team Lens 写入 runtime、补造事件、
   重放工具或建立第二套 trace/状态。产品身份由调用者声明，关系只来自 typed 字段或经正文伪装回归证明无歧义的确定
   语法，不从正文语义、ID 形状、时间邻近或缺失值推断。
3. **body-free 白名单**：规范化层按允许字段构造新对象，不能先复制 raw/reduced graph 再靠少数黑名单删除。报告只消费
   该规范化对象；错误消息、日志、fixture 和测试失败 diff 同样不得泄露 raw 正文。
4. **显式降级与确定性**：四态的语义在两侧一致；`partial` 必须说明缺什么，`unsupported` 表示该 trace schema 无此能力，
   `not_applicable` 只表示产品概念不适用。确定性以固定输入的字节输出为验收，不把当前时间、绝对路径或随机 ID 写入结果。
5. **条件 hook**：阶段 1 的零 hook 缺口验证通过前不得编辑 RONDO trace runtime。触发后也只能补最小结构化 metadata，
   复用现有 writer/context/reducer；不得修改冻结 Codex、Team State canonical 状态或为了 viewer 改变产品行为。
6. **阶段单向依赖**：可视化只依赖 `team_view.json`，不能为画图方便回读 raw trace，也不能要求 runtime 保留正文。
   `team_view.json` 是 reducer 与报告之间唯一合同。
7. **外部与资源边界**：本轮禁止 Docker、真实 API、真实本地模型、训练、完整数据集、workspace 全量测试、数据外发、
   远端写入和系统/全局配置变更。普通依赖下载可以进行；如触发 Rust hook，所有重型 Cargo format/fix/test 必须走
   仓库共享 build-lock/既有 `just` 入口并与 A 排队，拿不到资源门禁时停止该重型动作，不直接运行 Cargo 绕过。
8. **验证适度**：首批只跑 Team Lens 定向 Python 测试和真正受影响的既有 M-5 trace 测试；未改共享 eval 逻辑时不跑
   全部 eval suite。只有触发 hook 才增加受影响的 `rollout-trace`/core 定向 Rust 门禁，仍不扩大到 workspace 全量。
9. **允许自修复重跑**：普通解析、schema、fixture、转义、确定性、测试或窄 hook 编译问题可自行分析、修复并有界重跑，
   不因第一次小失败停下。只有触及原则性边界、需要未授权高危能力、必须改变计划目标/范围、共享写集无法避开、资源门禁
   持续不可满足，或多次合理尝试后仍有实质阻塞时才暂停汇报；不得靠重试挑选结果、绕过门禁或把 skip 当通过。
10. **提交边界**：完成两个阶段并审查 diff、敏感内容、意外生成物与工作树状态后，提交本地 048 分支并停止。不得合并
    `main`、不得推送工作树分支、不得删除/重命名 worktree 或分支；共享 WBS 与完成历史留给最终整合批次。

## 4. 软性建议

以下建议基于 `main@7ba7eb6` 的实时源码，不是固定路线。执行者可根据实现和测试采用更优的等强方案。

- 当前两侧 `codex-rs/rollout-trace` 逐文件一致，原生 reducer 已提供 threads、turns、inference、tool、terminal、
  interaction、sequence/time 等图结构。优先利用它或兼容其 schema，不必重造完整 reducer。
- `eval/rondo_eval/multi_m5/trace.py` 与 `eval/tests/test_multi_m5_trace_evidence.py` 已有 bundle 边界检查和小型合成 builder
  经验。可借鉴或抽取窄共用 reader，但 Team Lens 不应继承 M-5 的工作流判据和复杂归因规则。
- 当前通用 tool dispatch 能看到成功 team tool 的结构化 invocation/result；注意 publish 的 summary/title/handoff、route
  note 与 evidence drill-down observation 都是正文，必须在归约前剔除。只保留 ID、revision、状态和 typed relation。
- 当前 request-only Team projection 位于 inference request，而 Fact 确认没有独立 typed Team trace event。可以先验证现有
  canonical tag/typed tool result 是否足以机械提取；renderer 当前允许自由正文包含换行，测试应主动放入与结构行同形的
  title/summary/handoff/note。若仍只能猜测，可评估原生 raw event/reducer 的最小扩展；`RawTraceEventPayload::Other`
  当前并不是免接入的插件点，reducer 仍会拒绝它。具体 hook 位置、事件形态与字段应由零 hook 证据决定。
- 用量在 reduced model 中有 `TokenUsage` 形状，但当前 replay 路径是否从实际 response payload 填充必须用代表性 bundle
  验证；不能因类型存在就报告 `available`。必要时可从原生 response 的结构化 usage 区域提取数值，但不保留 response。
- 单文件 HTML 可用原生 HTML/CSS/JavaScript 和一份转义后的规范化 JSON 完成。没有明确净收益时不要引入 Node、bundler、
  图数据库或大型图表依赖；若小依赖更简单，仍可按允许写集自主选择。
- fixture 可由测试 builder 在临时目录生成原生 bundle，避免把 bundle 形态误当真实 raw trace 提交。可用明显虚构 ID、
  模型名和占位正文验证正文绝不会出现在 JSON/HTML 中。当前 ignored 现场有 RONDO M-5 原生 bundle，但未发现冻结
  Codex 的现成 bundle；Codex 侧可复用冻结源码的原生 fixture/builder，或用无 API、无模型的离线路径生成结构忠实的
  fixture。合成 fixture 必须如实标记，不能冒充真实运行证据。
- 建议先完成 schema/四态和共有 reducer，再补 RONDO 关系与零 hook 报告；阶段 1 固定后再做 HTML。每阶段可形成一个
  清晰提交，也可在实现更适合时使用其他少量提交；最终以联合验收为准。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根 `AGENTS.md`、`README.md`、顶层 WBS、Multi 子 WBS、计划模板、`multidev/AGENTS.md` 和相关 rollout trace/
  Team State 源码；未读取真实 trace 正文。
- 已确认主工作区干净且基线为 `main@7ba7eb6`，并创建干净的
  `.claude/worktrees/048-team-lens` / `worktree-048-team-lens`。并行 A 分支/工作树已存在，不触碰。
- 已确认冻结 Codex 与 RONDO Multi 的 `codex-rs/rollout-trace` 当前逐文件一致，manifest/raw event/reduced state schema
  兼容；bundle 自身没有产品字段，所以调用者必须显式声明 product。
- 已确认共有 trace 有 thread/turn/inference/tool/terminal/interaction/time 的结构化入口；RONDO Team 目前没有专用
  typed trace event，部分关系只间接存在于通用 tool invocation/result 与 request-only projection 中。该源码侦察只用于
  设计零 hook 验证，不等同于代表性 bundle 已通过缺口门，也不预先授权 hook。
- 已只看路径/manifest 存在性核对 ignored 现场：`eval-data/` 下有 24 个 RONDO M-5 rollout trace manifest，未发现冻结
  Codex 的现成 rollout trace bundle；没有打开 payload。Codex 侧的代表性 native fixture 需由执行者用上述离线方式补齐。
- 已确认仓库 `just eval-sync` 会把 ignored Python 环境与 uv cache 物化到 common-root；只有执行者确实需要同步依赖时才
  允许这一主工作区 ignored 写例外，并须在交付中单独说明。
- 已冻结 A/B 写集、共享文档归属、条件 hook、body-free 数据合同和本次执行授权边界。
- 已在固定 `eval/` 写集内完成 Team Lens：同一 `reduce_bundle()` 入口按显式 product 消费原生 v1 bundle，白名单生成
  `team_view.json`；报告器只消费该合同并输出内嵌 CSS/JS/数据的确定性单文件 HTML；未修改 M-5 reader、依赖或 Rust。
- 零 hook 验证已完成：冻结 Codex 与 RONDO `rollout-trace` 源码逐文件一致；同一消费者成功读取 24/24 个指定 RONDO
  M-5 原生 bundle（均无预生成 `state.json`）。独立审查纠正 Fact 动态 observation 语义后，其中 1 个五类 Team 视图全
  `available`，其余按缺少完整 dump/Team/evidence observation 显式 `partial`；所有 bundle 的 JSON/HTML 重复生成均字节
  一致。Codex 侧使用与冻结源码一致的原生 v1 合成
  fixture，明确标记为合成证据。现有 typed tool result、projection 外壳和 dump 关系足够，不触发 hook。
- 已加入临时目录原生 fixture 与 25 项定向测试，覆盖两侧布局、direct/code-mode 等义、四态降级、无 `state.json`、
  Fact omission、wait 非 interaction、严格 reader 错误、正文不出站、renderer 单向依赖、确定性与 HTML 转义/自包含；
  `PYTHONPATH=eval python3 -m unittest -v eval/tests/test_team_lens.py` 为 25/25 通过。
- 前轮独立审查已修复 Fact/retire、原生 variant、ownership、四态、attention stale、interaction endpoint 和可选 parent
  降级等问题。后续验收提交 `a3f7c20` 又复现 4 个真实缺口：合法结构化 SessionSource、turn-end inference 收口、缺失
  invocation 时 typed ToolCallKind 回退及十进制 ordinal 超过 9 后的 Event/Version 顺序；现均已补先失败后通过的窄回归。
- 修复后 24/24 指定 bundle 仍可归约，JSON/HTML 重复生成字节一致，五类 Team capability 全 `available` 的样本仍为 1；
  CLI help/reduce/report 与内嵌 JavaScript 语法 smoke 通过。
- 修复提交 `78736a7` 已由新的干净上下文独立审查者复验为 `PASS`：四项原阻断、额外 late-terminal 状态组合、全部 Team
  实体/双向关系排序与 schema 乱序反例均关闭，25/25 定向测试和 24/24 现场 bundle 确定性继续通过。
- 未执行 `just eval-sync`，未产生 common-root ignored 环境/缓存写入；未运行 Docker、API、模型、Cargo 或全量测试。

### 当前工作

验收提交 `a3f7c20` 的 4 个阻断已在 Python consumer/schema 内窄修，保持零 hook；修复提交 `78736a7` 的定向、现场和
干净上下文独立复验及用户最终验收均通过。任务已统一合入 `main`，本计划冻结。

### 本任务剩余步骤

- 无。

### 阻塞项

- 无。条件 hook 是否需要是阶段 1 的预期判定，不是当前阻塞。

### 当前验收状态

- 验收通过，任务目标完成；两阶段实现与 `a3f7c20` 指出的 4 个阻断均已闭合，最终复验未发现新的可复现正确性或
  功能问题。统一整合不改变本任务合同与验收结论。

### 交接边界

- 本任务完成后冻结此计划。后置主动委派收益对比和 A/B 最终整合只链接
  `doc/WBS.md` / `doc/WBS/multi-agent-trusted-evidence.md`，不在本计划展开或提前执行。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 数据 MVP 与静态可视化在同一 048 任务内顺序完成 | `team_view.json` 必须先成为唯一数据合同，两个阶段都完成才形成可用 Lens | 任务拆分 | 已采纳 |
| 002 | 调用者显式声明 `codex` / `rondo-multi`，bundle 内容不决定产品身份 | 两侧 trace schema 相同，RONDO 运行也可能未调用 Team 工具；内容推断会把缺失误判成产品身份 | 输入合同 | 已采纳 |
| 003 | 规范化输出采用字段白名单和四态 capability matrix；Codex Team State 为 `not_applicable` + `null` | 同时满足 body-free、诚实降级和跨产品统一解释 | 数据合同 | 已采纳 |
| 004 | 零 hook bundle 验证先行，源码侦察不自动触发 hook | 只有真实缺口才能证明 runtime 改动必要，避免为了 viewer 建第二套 tracing | hook 门 | 已采纳 |
| 005 | B 首批固定写集不含 Team State crate、Rust 锁、主动测试入口和共享 WBS | 支持 A/B 并行并把共享冲突留给最终整合批次 | 并行开发 | 已采纳 |
| 006 | 普通窄失败允许自主修复和有界重跑；原则边界、未授权扩展和持续资源门禁才暂停 | 给执行者合理冗余，不让一次可修小失败中断完整任务 | 执行流程 | 已采纳 |
| 007 | 048 完成后只提交本地工作树分支，不合并、不推送 | 符合本轮交付授权，保留独立审查与最终整合门 | Git 交付 | 已采纳 |
| 008 | projection 文本必须通过正文结构行伪装回归，否则降级或触发最小 hook | 当前 renderer 的自由正文可含换行，仅凭固定前缀解析会猜错 Team 关系 | 零 hook 判定 | 已采纳 |
| 009 | schema identity 分开记录 manifest/raw event/reduced state 版本 | 三者在原生 trace 中是独立版本，混成一个值会误报兼容性 | 输入合同 | 已采纳 |
| 010 | 依赖同步可按需写 common-root ignored eval 环境/缓存，其他主工作区写入仍禁止 | 现有 `just eval-sync` 的真实路径语义如此，需诚实列为例外 | ignored 现场 | 已采纳 |
| 011 | 零 hook 足够，不编辑 RONDO trace runtime | 24/24 指定 RONDO 原生 bundle 可由 typed tool result、projection 外壳与 dump 机械归约；缺少动态 evidence observation 的样本可诚实降级 | hook 门 | 已采纳 |
| 012 | projection 只解析请求尾部 developer item 的 canonical 外壳/header，不解析后续 Event/Version 文本 | 自由 title/summary/handoff/note 可换行伪装结构行；关系统一来自 typed tool result/dump | 归约边界 | 已采纳 |
| 013 | 报告使用标准库 HTML/CSS/JS，内嵌转义后的严格 Team View，并以 DOM `textContent` 渲染数据 | 无需新增依赖或前端工程即可满足离线、自包含、确定性和注入安全 | 静态报告 | 已采纳 |
| 014 | canonical Fact dump 不代表动态 evidence observation；只有 `team_evidence` 结果填写 availability | Fact 身份/元数据与调用时 observation 是不同事实，不能用静态存在性冒充可用性 | Fact 降级 | 已采纳 |
| 015 | consumer 对声明支持的原生 v1 variant 执行必需字段、envelope 和生命周期关联校验 | 避免自建 reader 接受冻结 Rust serde/reducer 已拒绝的 bundle，同时不另建通用审计层 | 输入合同 | 已采纳 |
| 016 | attention snapshot 新鲜度比较 Team result revision 与 dump revision，并排除 deduplicated result | tool-end sequence 是观测完成顺序，不等于 canonical Team State 变更顺序 | Team Attention | 已采纳 |
| 017 | schema v1 用 Agent parent 校验 spawn/result 方向，并限制 capability 的产品合法状态 | 这些关系已在规范化数据中可机械判定，允许矛盾会让报告展示反向 interaction 或错误四态 | 规范化 schema | 已采纳 |
| 018 | child parent 缺失时保留 spawned 角色/interaction 方向并降级，不拒绝 bundle | 原生 thread metadata 是 best-effort Option；parent 等式只有在字段存在时才能机械断言 | Agent 降级 | 已采纳 |
| 019 | SessionSource 只在结构正确的 `subagent.thread_spawn.parent_thread_id` 存在时提取 parent，其他形态返回未知 | 冻结原生 reducer 将 SessionSource 作为 best-effort Value，Custom/Internal/Review 等对象形态不代表 spawn | Agent 身份 | 已采纳 |
| 020 | turn terminal 关闭同 turn 的 running inference；late terminal 只补 usage，不覆盖 turn-end 状态与时间 | 与冻结原生 reducer 的 completed/cancelled→cancelled、failed→failed、aborted→aborted 收口语义一致 | inference 生命周期 | 已采纳 |
| 021 | invocation 缺失时从 typed `Other.name` 或 `Mcp.server/tool` 恢复工具身份 | 这些字段是同一原生事件内已有的 body-free 机械事实，不能降级为 variant tag | 工具归约 | 已采纳 |
| 022 | Team 实体与关系统一按 `(first_seq, stable_id)` 排序，并由 schema v1 拒绝乱序合同 | ID 词典序不是原生时序；renderer 只消费规范化合同，排序必须在 consumer/schema 边界统一保证 | Team 时序 | 已采纳 |
