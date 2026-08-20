# Plan 049：Multi 二期 C 主动委派收益对比 ExecPlan

> 本计划是 Multi 二期 C 的稳定任务合同，同时覆盖阶段 A 与阶段 B。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、公平合同、范围、硬约束、费用上限或完成标准，应暂停执行并请求用户确认；普通实现选择、
> 配置/fixture 窄修、基础设施修复、从可信状态 resume 和合同内有界重跑不属于合同变更。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在冻结 Codex CLI `v0.147.0` 与 RONDO Multi 使用相同自然任务、主动委派 developer instruction、主/成员模型、
reasoning effort、并发、deadline、工具面和外部判定的条件下，分别回答：

1. RONDO Multi 是否比冻结 Codex 更容易在自然任务中自主决定并实际发起委派。
2. 在实际发生委派的运行中，两侧的外部任务结果、耗时、token、推理/工具/命令/文件工具活动与团队协调成本有何差异。

两项结论必须分开。Team Lens 用于描述原生 trace 中的真实团队行为，不单独证明任务质量、因果收益或 Team State
归因；小样本只作描述性成对比较，不宣称统计显著性或全面优越。

本任务是一个 plan、一个分支、一个工作树，严格按顺序分为：

- **阶段 A：无费用准备。** 当前已授权。冻结合同、完成最小设施、离线测试和彩排，最后只给 `paid-ready` 或
  `blocked` 结论；不得产生真实 provider/API 请求或费用。
- **阶段 B：真实 API activation pilot 与正式成对测评。** 当前未授权。只有用户另行明确“开始阶段 B”并确认本计划的
  总费用边界与当前可用余额后才可启动。

### 完成/验收标准

#### 阶段 A：无费用准备

- [ ] 用受跟踪的机器可读合同冻结本计划 §3.2—§3.5 的任务、prompt/policy 摘要、产品与二进制身份、模型/effort、
      工具面、并发、deadline、成对顺序、有效运行/infra 分类、恢复规则、Team Lens 产物、activation 门与费用上限。
- [ ] 复用现有 Multi M-5、Terminal-Bench、预算账本、归档、原生 rollout trace 和 Team Lens，完成一条最小的共同编排、
      成对调度、身份绑定、body-free 结果聚合与幂等 resume 路径；不建立第二套 runner、trace writer、在线服务或大型
      benchmark 平台。
- [ ] dry-run 能确定性给出 pilot/正式槽位、稳定 run/pair 身份、执行顺序、账本命名空间和每侧预期 trace、Team View、
      HTML 与聚合输出位置；dry-run 身份必须显式标为 rehearsal，不得占用或伪装正式 paid identity。
- [ ] 两侧命令投影明确证明都启用 Multi-Agent V2、相同成员模型/effort 与相同并发；现有 M-5 的 Codex V1 / RONDO V2
      非对称入口不得原样继承。
- [ ] pure/fake/loopback/replay 与 body-free 合成 fixture 覆盖：两侧成功与任务有效失败、provider/network 模拟失败、
      配置/产品身份漂移、部分配对、缺失/部分 trace、归档或报告失败、重复执行、进程中断和从最后可信状态恢复。
- [ ] resume 对已归档有效运行、已生成 Team Lens 产物和已结算请求均幂等；一个配对只补尚未形成可信终态的一侧，
      不因恢复重复创建有效运行、重复归档或重复记账。
- [ ] 同一固定归档重复生成的 `team_view.json`、`team_report.html` 与聚合结果保持字节确定；Codex Team State 为
      `not_applicable`/`null`，不得伪造成“可用但为空”。
- [ ] tracked 合同、结果与 fixture 均为 body-free：不得包含 raw prompt/response、reasoning、agent message、命令/stdout/
      stderr、工具参数/结果正文、Fact 正文、隐藏推理、密钥或 raw trace。原始 trace 与运行产物只留在 ignored
      `eval-data/`，不得提交。
- [ ] 阶段 A 的普通入口不接触真实 provider；阶段 B 付费入口在缺少独立显式启动动作与本地 activation 条件时，必须在
      读取密钥、创建正式 receipt/ledger/run、发起网络请求或启动 Docker 之前拒绝。允许用临时 fake marker 测试，
      不得在阶段 A 创建正式付费 activation receipt。
- [ ] 相关定向测试通过。若实现未改 Rust，不要求 Cargo；若确需窄改 Rust，只运行受影响 crate 的必要门禁并遵守共享
      build-lock/watchdog，不扩大到全 workspace。
- [ ] 阶段 A 退出材料明确列出：`paid-ready`/`blocked`、阶段 B 启动清单、冻结合同摘要、pilot 通过条件、100 USD 总硬
      上限及余额确认项、允许自主修复/重跑的情况、fail-closed 条件，以及只能由首次真实连接确认的事项。
- [ ] 没有真实 API 请求、费用、正式 paid receipt、正式结果身份、正式运行归档或“付费已开始”的表述。
- [ ] 执行者完成本地提交并保持 049 工作树干净；独立审查者确认 `paid-ready` 或给出具体 `blocked` 原因。阶段 A 后仍保留
      同一工作树/分支等待阶段 B，不合并、不推送、不关闭。

付费 provider 连通性若无法零费用验证，诚实留给阶段 B activation pilot，不因此伪造绿色，也不单独把其余阶段 A
判为失败。

#### 阶段 B：付费测评与观测（当前未授权）

- [ ] 用户另行明确授权“开始阶段 B”，确认 **100 USD 本任务累计硬上限**，并确认中转站可用余额不少于该上限；授权前
      不得运行任何真实 provider/API 或正式样本。若用户选择其他金额，属于费用合同变更，必须先更新计划并重新审查。
- [ ] 先完成 §3.4 的固定 activation pilot；只有 policy 注入、两侧原生 trace、Team Lens 和主动委派 activation 门均满足，
      才进入正式十个成对任务。
- [ ] 按 §3.3 的固定顺序得到十个有效配对；基础设施无效尝试不替换为别的任务，模型正常完成但 verifier 失败属于有效
      测评结果，不因分数不好而重跑。
- [ ] 每个有效运行均有 body-free Team View 与离线 HTML；字段不可得时使用 Team Lens 既有四态与 reason code，
      不以零值伪造可观测事实。
- [ ] 聚合分别报告：外部 verifier 结果；wall time；input/cached/cache-write/output/reasoning/total token；inference、
      tool、terminal command 与可机械识别的 file-tool 活动；spawn、峰值并发、message/followup/wait；RONDO Team State
      的 Event/Version/route/Fact/attention 指标及两侧 availability。
- [ ] 最终报告将 `有效成功/有效失败`、`infra 无效`、`未激活`、`样本不足`、`观测降级` 分开，并分别给出“委派倾向”
      与“委派后结果/成本”的结论。只有一侧委派时可报告倾向与整包结果，但不得把差异单独归因为 Team State；双方均未
      委派时只能结论为本策略/任务集未激活。
- [ ] 阶段 B 实现、结果与精炼历史记录提交在同一 049 分支；独立审查后仍须用户批准才可合并、推送或关闭工作树。

## 2. 范围

### 允许修改

- `plan/049-multi-proactive-delegation-eval-execplan.md`：只更新允许变化的当前状态与关键决策记录。
- `eval/rondo_eval/` 中直接相关的共享测评代码；优先复用 `multi_m5/`、`terminal_bench/`、`team_lens/` 与公共账本/归档
  组件，可按现有架构新增一个窄的 Plan 049 模块。
- `eval/tests/` 中直接相关的定向测试，以及 `eval/fixtures/` 中小型、合成、body-free fixture。
- `eval/locks/`、`eval/tasksets/`、`eval/templates/` 中本任务的新冻结合同；不改写历史 M-5/P2 锁和结果。
- 必要的 `justfile` 或 `scripts/` 窄入口；不得绕过现有资源门禁。
- `multidev/` 中仅限无法由共同 eval 配置完成、且不改变产品语义的窄测评适配。任何只改变 RONDO 行为、破坏双方工具面
  或需要重新定义公平合同的修改都不在此授权内。
- 阶段状态实际变化时，精炼更新 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`；完整任务结束前不向
  `doc/WBS-COMPLETED.md` 提前写“已完成”。
- 本任务有实质进展时新增精炼 `agent_log/`；阶段 B 完成后可新增 body-free 聚合结果，不堆叠 raw 运行正文。

### 允许的 ignored 共用根产物

下列内容因 Git worktree 不复制 ignored 机器状态，必须由 049 工作树通过 `RepoPaths.common_root` 使用主仓库共同根；它们
不是受跟踪的 main 修改，但执行者必须在交付中单独列明：

- `eval-data/` 下已有 runtime bundle、Terminal-Bench source、运行 scratch、模拟账本/归档、trace 和 Team Lens 生成物；
  本任务新产物须使用独立的 Plan 049 命名空间，不覆盖或清理来源不明的既有资产。
- 如确需同步普通依赖，`eval/.venv/` 与 `eval-data/uv-cache/` 由现有 `just eval-sync` 共用；无依赖变化时优先复用现状。
- 阶段 A 只可静默检查共同根 `.env.local` 的存在性、普通文件/非符号链接、`0600` 权限及所需变量非空；不得打开、
  搜索、打印、复制、source 或记录其内容。`rondo.local.toml` 只作非密钥机器配置输入，不得写入 API Key。

所有受跟踪编辑仍只在 049 工作树中完成。若发现除上述清单外必须直接修改主工作区的事项，先停止该动作并向用户单独说明。

### 不允许修改

- `codex-source-code/` 与冻结 Codex 源码/二进制；上游基线升级不属于本任务。
- `mydev/`、Local 方向计划/结果、现有 P2/M-5 正式锁、账本与历史结果。
- 为本任务改变 RONDO Multi 产品语义、Team State 语义或默认启用状态。
- CI/PR、宿主机配置、全局工具链、系统服务、其他仓库或远端资源。
- 为追求绿色而弱化 scorer、trace、Team Lens、费用、隐私、身份或阶段授权门。

### 不允许读取/查看

- `.env.local` 的内容以及任何项目外个人文件、凭据或私有数据。
- raw trace、prompt、response、命令输出或 Fact 正文不得人工展开、复制进日志/对话/受跟踪文件。允许本地自动化消费者在
  任务范围内机械读取原始运行资产并只产出 body-free 结果。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试、提高激活率或获得更好分数而违反。

### 3.1 基线、阶段与交付

- 共同开发基线为干净 `main@e192a58f5aef0f26291d9798a7fedc493aa62979`；工作树为
  `.claude/worktrees/049-multi-proactive-delegation-eval`，分支为 `worktree-049-multi-proactive-delegation-eval`。
- 阶段 A 与 B 使用同一计划、分支和工作树并严格串行。阶段 A 当前授权不因代码已经具备付费能力而扩大为阶段 B 授权。
- 阶段 A 结束只提交本地分支并保持工作树干净；不合并、不推送、不关闭。阶段 B 及最终验收后也须用户另行批准这些动作。
- 普通配置、fixture、调度、归档、resume、报告与定向测试问题由执行者自主修复并重跑；只有改变公平合同/产品语义、
  需要真实 API、越过费用/数据/资源边界或状态已无法安全判断时才暂停。

### 3.2 公平合同

**产品与任务身份**

- 冻结 Codex 使用 `eval/locks/multi-m5-runtime-v4.json` 中 `codex_baseline`：源码
  `be6e8eac029b183056b7e4402879f15d2c85f61b` 及其冻结 bundle/manifest/hash。
- RONDO Multi 默认复用同一 runtime lock 的 `rondo-multi` bundle：源码
  `0eee6dc5ee69f0eca9e1db350148c423a2b2bf67` 及冻结 manifest/hash。该源码是当前 main 的祖先；047 只增加测试，048
  只增加 eval consumer。若阶段 A 证明该 bundle 不能承载共同 proactive policy，应作为公平合同 blocker 汇报，不得
  单边修改产品后继续冒充同条件比较。
- 自然任务冻结为 `eval/tasksets/p2-b7-canary-catalog-v4.json`，SHA-256
  `00b83e4435218de730c25fcbc8fd69cebc0cee36db433a4b305076cb1e157ddf` 中的十个 Terminal-Bench 2.1 任务；任务正文、
  source digest、镜像 digest、workdir、agent/verifier/build timeout 与 task-native verifier 均沿用该 catalog。
- 用户任务只使用原生 Terminal-Bench task instruction；不得追加要求 spawn、指定工具顺序、规定成员数量、教授 RONDO
  协作协议或暗示哪一侧应委派的内容。

**共同主动委派 developer instruction**

两侧 Root 必须收到字节一致的下列英文 developer instruction；受跟踪模板及其 SHA-256 进入 Plan 049 lock，运行时以
hash 绑定并在 raw trace 内机械核验，body-free 结果只记录 hash 与 matched 布尔值：

```text
Proactively consider whether independent, substantial subtasks would benefit from teammates. Delegate when doing so is likely to improve the task result or reduce wall-clock time. Decide autonomously whether, what, when, and how to delegate. Coordinate and integrate any delegated work, and remain responsible for the final answer. Do not delegate merely to demonstrate collaboration, and do not use teammates when the task is better handled directly.
```

该 policy 不按任务特化，不点名 spawn 工具、工具顺序或 Team State 协议。若 CLI 的 custom developer instruction 会替换而
非追加默认协作说明，两侧仍使用同一替换语义；不得一侧保留额外默认 proactive 文本而另一侧没有。

**共同运行条件**

- provider/API/base URL 沿用冻结 M-5 合同：`relay` / `responses` / `https://www.cctq.ai/v1`；Root 与成员模型均为
  `gpt-5.6-terra`，reasoning effort 均为 `medium`。阶段 B 前必须把实际 provider/model/effort 投影与价格快照绑定进
  新锁；机器配置漂移必须拒绝。
- 两侧都启用同一 Multi-Agent V2 工具面、成员模型/effort 覆盖、approval/sandbox、任务环境和原生 rollout trace；冻结
  Codex 不修改源码。只有 RONDO Multi 额外启用 Team State，这一差异必须在身份和报告中显式记录。
- 现有 M-5 adapter 会把 Codex 作为 V1、RONDO 作为 V2，且未给 Terminal-Bench run 接入 Plan 049 所需 trace root；
  阶段 A 必须窄改共同 eval 接线并用命令投影/loopback 证明上述对称合同，不能把旧 M-5 gate 2 直接改名复用。
- 每次只运行一个 Terminal-Bench 槽位；槽位内部 `max_concurrent_threads_per_session=4`（Root 加最多三个同时活跃成员），
  provider 主请求并发上限同为 4。不得为激活临时提高某一侧并发或指定必须生成的成员数。
- 每个 run 的请求上限为 80；provider 内部尝试沿用最多 5 次、2 秒 backoff，以及仅对 429/500/502/503/504 的既有
  无账单重试口径。任务 deadline 使用 catalog 固定值，不因某一侧进展慢而临时延长。
- 主结论必须表述为“`medium` + 同一 proactive policy 下的对比”，不得冒充两侧默认行为；`ultra` 或其他模型/effort
  不属于本任务诊断或结果。

### 3.3 正式任务、轮数与顺序

阶段 B 正式部分固定为每任务一个有效配对、共十个任务/二十个有效 run，不因分数或是否委派追加观察轮。为平衡镜像预热
与固定先后，采用 task-major 的交替 side-first 顺序：

| Pair | Task | 第一个槽位 | 第二个槽位 |
|---|---|---|---|
| F01 | `terminal-bench/db-wal-recovery` | Codex | RONDO Multi |
| F02 | `terminal-bench/extract-elf` | RONDO Multi | Codex |
| F03 | `terminal-bench/filter-js-from-html` | Codex | RONDO Multi |
| F04 | `terminal-bench/fix-git` | RONDO Multi | Codex |
| F05 | `terminal-bench/headless-terminal` | Codex | RONDO Multi |
| F06 | `terminal-bench/openssl-selfsigned-cert` | RONDO Multi | Codex |
| F07 | `terminal-bench/polyglot-c-py` | Codex | RONDO Multi |
| F08 | `terminal-bench/sanitize-git-repo` | RONDO Multi | Codex |
| F09 | `terminal-bench/sqlite-db-truncate` | Codex | RONDO Multi |
| F10 | `terminal-bench/vulnerable-secret` | RONDO Multi | Codex |

有效运行的外部完成判定只来自 Terminal-Bench task-native verifier：reward/pass 为成功，任务未通过为有效失败。模型正常结束但
任务失败、选择不委派或委派后结果较差都属于有效测评结果，不得作为 infra 重跑。运行过程必须同时形成可读原生 trace 与
Team Lens；部分产品失败只要仍有可机械归约的 partial trace，按有效失败保留并降级报告。完全缺失 trace 时必须先判断是
collector/归档基础设施故障还是产品本身终止，保留原始分类证据，不得用选择性重跑美化产品结果。

### 3.4 Activation pilot

正式任务前固定执行三个自然任务的六个有效 pilot run；pilot 与正式结果身份、账本槽位和聚合分区分开，不进入正式十题
结论：

1. `terminal-bench/filter-js-from-html`：Codex → RONDO Multi。
2. `terminal-bench/sanitize-git-repo`：RONDO Multi → Codex。
3. `terminal-bench/db-wal-recovery`：Codex → RONDO Multi。

pilot 通过需同时满足：

- 六个有效 pilot run 均机械确认产品/binary/config、自然任务、共同 policy hash、Root/成员模型和 effort、并发/deadline；
- 六个原生 trace 均可由 Team Lens 处理并产出 body-free JSON/HTML；
- 至少一侧至少一次出现由 Root 自主发起、trace-backed 且成功接受的 spawn，能与对应 Agent 生命周期关联。

若只有一侧出现 spawn，activation 仍可通过并进入正式样本，但最终只能报告委派倾向与整包产品结果，不能归因 Team State
收益；若双方都没有 spawn，则结论为当前 policy/任务集未激活，停止在 pilot，不得临时改 prompt、强制 spawn、换题或把
pilot 重跑成“直到激活”。infra 无效 pilot 可按 §3.5 恢复，不属于追求激活的选择性重跑。

### 3.5 分类、恢复与费用

- 每个计划槽位使用稳定 pair/task/side/run/attempt 身份。已归档的有效终态只读复用；同一有效槽位不得出现两个被纳入
  聚合的 run。中断后只补未形成可信终态的一侧，不重跑已有效完成的对侧。
- provider/network、Docker/Harbor、runner、账本、collector、归档或 Team Lens 设施故障按证据归为 infra 无效；模型正常
  完成但任务失败是有效失败。产品自身崩溃/协议失败不能自动伪装成 infra，原因不清时 fail-closed 并独立报告。
- 在不改变公平合同的前提下，执行者可自主修复设施、从最后可信状态 resume，并重跑受影响槽位。每槽最多 5 个已发起的
  infra 无效 paid attempt，全任务 pilot + 正式阶段共用最多 40 个 infra 无效 paid attempt；离线修复/测试重跑不计入。
  这些上限提供足够恢复空间，但防止无边界消耗；不能把有效失败改标 infra 来换取新样本。
- 本任务阶段 B 的累计费用硬上限为 **100.00 USD**，覆盖 pilot、正式 run、provider 请求与 infra 重试；历史 M-5 费用不
  计入本任务，但 Plan 049 自己所有付费尝试均计入。账本必须按实际 usage 保守结算，未知 usage 保留足额 exposure，
  不得把 reservation 当已发生费用或把未定费用记为零。
- 阶段 B 启动前必须由用户确认 100 USD 授权和不低于 100 USD 的当前可用余额。达到硬上限、余额耗尽、实际用量不能保守
  记账、身份/公平合同漂移、正文/密钥泄漏风险或运行状态无法安全判断时立即停止；不因单个可修复的 5xx、fixture、归档
  或 resume 问题停止整个任务。
- paid entry 必须在任何密钥读取、网络、Docker、正式 receipt/ledger/run 创建之前完成阶段授权门、干净 harness commit、
  frozen lock、余额/上限与 resume-prefix 检查。正式 activation receipt 只可在阶段 B 明确授权后创建。

### 3.6 Team Lens、聚合与数据边界

- 两侧均开启原生 rollout trace，并用现有 Team Lens 同一消费者处理。不得修改冻结 Codex、建立新 writer、旁路 telemetry、
  在线观测服务或把 Team Lens 接入运行时调度。
- 每个有效 run 的 ignored 产物至少包括 raw bundle、`team_view.json` 和 `team_report.html`；tracked 聚合只保存允许字段、
  availability/reason code、计数/时长/usage、稳定运行身份、合同 hash 与外部结果，不保存正文或 raw 路径。
- `file activity` 只报告 trace 能机械识别的文件类工具调用计数，并明确 coverage；shell 命令可能修改文件时不得解析命令正文
  或把 `0` 冒充完整文件系统差异。若现有 trace 无法支持完整指标，使用 `partial`/`unsupported`，不为该指标新增重型
  文件系统审计。
- `message`、`followup`、`wait` 按冻结产品的原生 interaction/tool kind 归一化；某一产品/版本没有对应 typed 事件时
  显式降级，不通过文本、ID 外观、时间邻近或命令内容猜测。
- 委派倾向的主观测为“有效 run 是否出现 Root 发起且成功接受的 spawn”与两侧频率；补充报告 spawn 尝试数、成员数、
  首次 spawn 时间和峰值并发。委派后结果只在实际发生委派的运行/配对中描述，并同时给出完整十题整包结果，避免把
  自选择出来的成功轨迹当作因果证明。

### 3.7 资源与测试

- 阶段 A 默认不用 Docker；若正式设施确实依赖 Docker，可从冻结 catalog 选择一个明确 digest，做至多一个串行、零 API
  的最小端到端彩排，不运行完整任务集。执行前后记录 `docker system df` 与 Windows `C:` 实际余量；新增占用 40 GB
  告警、60 GB 主动停止，`C:` 低于 80 GiB 立即停止，只清理本任务明确创建的对象。
- Docker、重型 Cargo 与真实本地模型互斥且并发为 1。本任务不授权真实本地模型加载或训练。
- 任何重型 Cargo 构建/测试必须通过仓库共享 `scripts/with-build-lock.sh` 或已接入的 `just` 入口；拿不到锁、cgroup、
  Windows `C:` 实际余量或资源计数器时 fail-closed。`CARGO_TARGET_DIR` 必须位于受监控项目根内。
- 只运行受影响模块的必要门禁；不要求全 workspace、CI 或 PR，不用扩大测试来替代针对性验收。

## 4. 软性建议

以下建议基于 `main@e192a58` 的现有结构，不固定内部实现。执行者可依据实时代码、测试和更小的设计采用更优方案，并在
关键决策记录中简述实质偏离。

- 优先给 Plan 049 建一个薄的 campaign/contract/aggregate 层，把 M-5 的 runner、budget、archive、resume 与 Team Lens
  作为组件调用；不要复制整个 `multi_m5` 包，也不要把历史 v6 常量硬改成 049。
- developer instruction 优先走两侧已有的 config/CLI developer-instruction 入口，并在 fake request 与原生 trace 中验证
  hash；如果共同入口成立，就不要改产品源码。
- 现有 Terminal-Bench adapter 的 V1/V2 分支可以做窄泛化或由 Plan 049 薄层组合；选择哪种由执行者决定，但应让 Codex
  也获得 V2、成员覆盖与 trace root，同时保留历史 M-5 行为和测试。
- 先写小型合同 loader、schedule 与 resume 状态机测试，再接 loopback 和 Team Lens；故障矩阵可用少量参数化 fixture，
  不必为每个历史故障再建一套 runner。
- 聚合器优先消费 Terminal-Bench 的外部结果与现有 `team_view.json`，只在确有 body-free 指标缺口时窄扩 Team Lens；
  report HTML 保持生成物，不把静态页面批量提交到仓库。
- dry-run、fake、replay 与正式付费命令使用显眼的不同子命令/命名空间，降低误触风险；具体 CLI 名称和模块拆分由执行者决定。
- 使用 `RepoPaths.discover()` 的 worktree/common-root 语义访问共享 ignored 资产，避免在代码里写死主工作区绝对路径。
- 阶段 A 调试和定向测试可以多次自主重跑；只在同类问题反复证明合同本身不可行时给 `blocked`，不要因一次可窄修错误
  过早停工。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- [x] 已核对根 `AGENTS.md`、README、当前 WBS、Multi 子 WBS、Plan 044/047/048、047/048 整合日志、数据布局与相关
      M-5/Terminal-Bench/Team Lens 源码。
- [x] 已确认共同基线 `main == origin/main == e192a58f5aef0f26291d9798a7fedc493aa62979`，主工作区干净且进入时
      只有主工作树；047/048 历史分支均保留为 `zz-done/...`。
- [x] 已从该基线创建 049 专用工作树与分支，并冻结本计划的 A/B 边界、公平合同、任务/顺序、activation、恢复与费用语义。
- [x] 已确认现有 M-5 runtime-v4 bundles、十题 catalog、Terminal-Bench runner、预算/归档/resume、原生 rollout trace 与
      Team Lens 是阶段 A 的首选复用面；没有发现需要第二套平台的理由。
- [x] 已识别现有 M-5 不能原样作为公平入口：其 Codex 使用 V1、RONDO 使用 V2，且 Terminal-Bench runner 尚未接入
      Plan 049 的 rollout trace root；这两点属于阶段 A 的窄 eval 接线工作，不需要修改冻结 Codex。

### 当前工作

- ExecPlan 已制定，阶段 A 实现尚未开始，等待交给执行者。

### 本任务剩余步骤

1. 阶段 A：落地冻结 lock/template、最小编排/聚合/resume 与付费入口隔离。
2. 阶段 A：完成 pure/fake/loopback/replay、Team Lens 确定性、故障恢复和必要的零 API 彩排。
3. 阶段 A：更新计划状态与精炼日志，提交 049 分支，独立审查给出 `paid-ready` 或 `blocked`。
4. 等待用户另行授权阶段 B；未授权期间保持工作树、分支和正式付费入口不动。
5. 阶段 B 获授权后：创建正式 activation identity，执行 pilot；通过后按固定顺序完成十个有效配对、聚合与独立审查。
6. 最终仍只提交 049 分支；合并、推送和关闭工作树等待用户批准。

### 阻塞项

- 阶段 A 无已知 blocker。
- 阶段 B 当前因缺少明确开始授权、100 USD 上限确认和余额确认而有意阻塞；provider 真连通性也只可在该阶段 pilot 确认。

### 当前验收状态

- 规划完成，尚未实施或运行测试。
- 未运行 Docker、Cargo、API、本地模型、付费测评或全量测试；未创建正式 receipt/ledger/run/result identity。

### 交接边界

- 阶段 A 完成后计划不冻结为整个任务完成，而是保持同一合同等待阶段 B；只有“当前状态”和必要决策记录继续更新。
- 整个 Plan 049 完成后冻结本计划；后续路线只链接 `doc/WBS.md` 与 Multi 子 WBS，不在本计划追加下游任务。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | A/B 使用一个 plan、一个分支、一个工作树，B 另行授权 | 保持合同连续，同时隔离真实费用边界 | 全任务 | 已采纳 |
| 002 | 复用 M-5 runtime-v4 与十题 catalog，新增薄编排层 | 现有身份、runner、预算、trace 与恢复设施已足够，避免第二套平台 | 阶段 A/B | 已采纳 |
| 003 | Root/成员统一 `gpt-5.6-terra` + `medium`，两侧同一非任务特化 policy | 隔离主要产品差异，并延续已验证配置 | 公平合同 | 已采纳 |
| 004 | 正式十题各一对，side-first 交替；有效失败不按分数重跑 | 平衡固定先后/镜像预热并避免选择性取样 | 调度与判读 | 已采纳 |
| 005 | pilot 固定三题；至少一侧一次 trace-backed Root spawn 才激活 | 先小规模证明 policy、trace 与观测链生效，不强制双方表现相同 | 阶段 B 门 | 已采纳 |
| 006 | 100 USD 累计硬上限，5 次/槽与 40 次全局 infra 恢复池 | 给可修复故障充分冗余，同时保持明确停止边界 | 费用与恢复 | 已采纳 |
| 007 | 文件活动只报机械可见 file-tool coverage，不建文件系统审计 | 满足诚实可观测性并保持测评轻量 | Team Lens/聚合 | 已采纳 |
| 008 | 受跟踪编辑只在 049；共享 ignored 资产经 common root 使用并单独汇报 | worktree 不复制机器资产，且必须保护 main 与既有数据 | 工作区边界 | 已采纳 |
| 009 | 不继承 M-5 的 Codex V1 / RONDO V2 非对称，阶段 A 为两侧建立共同 V2 + trace 接线 | Plan 049 比较主动委派，工具面与观测链必须公平一致 | eval adapter/runner | 已采纳 |
