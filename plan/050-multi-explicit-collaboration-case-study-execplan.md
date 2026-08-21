# Plan 050：明确委派三任务比较案例 ExecPlan

> 本计划是 Plan 050 的稳定任务合同，同时覆盖阶段 A 与阶段 B。
> 当前用户只授权制定并提交本计划，**尚未授权阶段 A 或阶段 B**。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、三道任务、共同 policy、公平合同、范围、硬约束、最高预算或完成标准，应暂停执行并请求用户确认；
> 普通实现选择、离线 fixture/配置窄修、基础设施修复、从可信状态 resume 和合同内重跑不属于合同变更。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在明确要求真实多智能体协作、且委派应当发生的条件下，对冻结 Codex CLI `v0.147.0` 与 RONDO Multi 完成三道
Terminal-Bench 2.1 任务的同条件比较案例。两侧使用同一任务、主/成员/Guardian 模型、`high` reasoning effort、
developer policy、Multi-Agent V2 工具面、并发、deadline、Docker 环境和 task-native verifier；唯一产品侧差异是
RONDO Multi 启用 Team State。

本任务回答：当上述明确 collaboration policy 已正确注入时，两侧的外部任务结果、成本和可观察协作过程分别是什么样子。
它不重新估计自然委派率，不从三题推导统计显著性、总体成功率提升、普遍性能优势或 Team State 的单因素因果收益。

任务按同一计划、分支和工作树严格分成两个阶段：

1. **阶段 A：无费用准备。** 复用 Plan 049 设施，冻结 Plan 050 独立合同并完成离线/必要轻量彩排；不得调用真实付费 API。
2. **阶段 B：付费执行与观测。** 只在阶段 A 独立验收为 `paid-ready` 且用户再次给出单独、明确的开始授权后，串行完成
   六个基础逻辑槽位、结算、Team Lens 归约和三份并列案例。

### 完成/验收标准

#### 阶段 A：无费用准备

- [ ] 新建并冻结 `multi-explicit-collaboration-v1` 机器合同、任务集和 policy 模板；使用独立的 Plan 050 lock、run/pair/
      attempt identity、账本 batch、rehearsal/paid namespace 与 `eval-data/plan-050/` ignored 根，不改写 Plan 049 的合同、
      结果或 ignored paid 状态。
- [ ] 合同冻结 §3.2—§3.5 的三题 source/image/verifier 身份、policy 精确字节及 hash、二进制、provider、主/成员/Guardian
      模型与 `high` effort、六槽顺序、deadline、并发、判定维度、恢复语义、价格快照、最高可授权预算和数据边界。
- [ ] 最大限度复用 Plan 049 的 Terminal-Bench runner、persistent budget ledger、reservation/settlement、resume、
      Root/Guardian selector、原生 rollout trace、Team Lens 和报告组件；只增加 Plan 050 合同所需的薄编排或窄泛化，
      不复制成第二套 runner、trace writer、账本、Team Lens 或展示前端。
- [ ] dry-run 能确定性列出六个基础槽位、顺序、稳定身份、预期 ignored/tracked 产物与恢复决策；rehearsal/fake 身份不得
      占用或伪装正式 paid identity。
- [ ] 两侧命令投影与零 API loopback 证明：共同 policy hash 确实进入 Root、共同 Multi-Agent V2 工具面一致、
      主/成员/Guardian 模型与 effort 均为冻结值、并发/deadline 一致，唯一允许的工具差异是 RONDO 的 Team State。
- [ ] pure/fake/loopback/replay 与小型合成 fixture 覆盖六槽编排、成功/有效失败、`policy_noncompliance`、infra 无效、
      请求前/请求后中断、settled 后本地归约失败、部分配对、幂等 resume、合同漂移、未知请求/usage 和原则性停止。
- [ ] trace 选择器对两侧都只能选择唯一 `SessionSource::Exec` Root，并允许身份精确匹配的 Guardian bundle；双 Root、
      未知来源、身份不明或无法核清的逻辑槽位必须拒绝，Guardian 不进入产品团队行为指标。
- [ ] 同一固定归档重复生成的 `team_view.json`、`team_report.html`、三题并列案例数据和总览保持字节确定；Codex Team State
      为 `not_applicable`/`null`，字段缺失使用 Team Lens 既有四态与 reason code，不用零值冒充事实。
- [ ] tracked lock、fixture、聚合和案例产物保持 body-free：不含 raw prompt/response、reasoning、agent message、命令或
      stdout/stderr、工具参数/结果正文、Fact 正文、密钥、隐藏推理或 raw trace。原始 trace、任务 workspace 与完整运行
      产物只留在 ignored `eval-data/plan-050/`。
- [ ] 阶段 A 的普通入口不接触真实 provider。阶段 B 入口在缺少独立授权、精确预算、paid-ready 审查提交与本地启动条件时，
      必须在读取密钥、创建正式 receipt/ledger/run、发起网络请求或启动正式 Docker 任务前拒绝。
- [ ] 只运行相关模块的必要测试。若未改 Rust，不运行 Cargo；若确需窄改 Rust，只通过共享 build-lock/watchdog 运行受影响
      crate 的必要门禁，不扩大到全 workspace。
- [ ] 执行者在 050 分支完成本地提交并保持工作树干净；独立审查者复核合同、离线证据、付费入口和 body-free 边界，给出
      明确 `paid-ready` 或具体 `blocked` 结论，并列出阶段 B 的精炼启动清单。
- [ ] 阶段 A 全程没有真实付费请求、费用、正式 paid receipt、正式结果身份或“阶段 B 已开始”的表述。

付费 provider 的真实连通性若无法零费用证明，诚实留给阶段 B 第一组成对运行，不因此伪造绿色，也不额外增加 pilot。

#### 阶段 B：付费执行与观测

- [ ] 用户在阶段 A `paid-ready` 后另行明确授权“开始 Plan 050 阶段 B”，确认本次实际累计费用上限；该上限不得超过
      `min(100.00 USD, 启动时确认的中转站可用余额)`。当前计划制定和未来阶段 A 授权都不能替代这次开始授权。
- [ ] 按 §3.3 固定顺序全局串行推进六个基础逻辑槽位。第一组成对结果同时承担真实 provider、trace、Root/Guardian
      选择与结算链路的早期确认，属于正式案例且不得另加 pilot 或事后替换。
- [ ] 每个逻辑槽位最终恰有一个可解释的有效终态，或整个 campaign 以明确原则性/预算停止收口；已形成有效终态的槽位
      不因 verifier 失败、委派结果不好、轨迹不漂亮或 `policy_noncompliance` 重跑。
- [ ] 每个有效槽位的外部结果、usage、费用、唯一 Root trace、Team Lens 与同一 run/slot identity 对齐；不存在未知请求
      提交状态、未结算 reservation、未保守计价 usage 或悬空 Docker/runner。
- [ ] 每题生成一份 Codex/RONDO 并列案例，并生成三题总览。至少展示外部 verifier 结果、wall time、token/费用、
      共同工具与交互指标、协作合规状态、Team Lens 轨迹及 Team State availability；只在证据支持时标记
      “成员发现 → 团队传播 → Root/其他成员调整 → 最终整合”，否则明确标为 `not_observed` 或 `unknown`。
- [ ] 有 accepted Root spawn 且成员承担实质、独立可行动工作时才能称为委派后的协作案例；policy hash 匹配但 Root 未委派，
      或只产生仪式性成员活动，标为 `policy_noncompliance`。真实委派但 verifier 失败仍是有效案例。
- [ ] 最终报告只作三题条件性案例解释；外部 verifier 是主要结果，Team Lens 是过程解释。Event/Fact/route/wake 数量、
      participant 数量或漂亮调用顺序都不能替代任务结果或证明因果收益。
- [ ] 独立最终验收确认六槽/停止状态、结算、报告和 body-free 边界一致；按实际状态精炼更新 WBS、WBS-COMPLETED、
      本计划与 agent log。执行者只提交 050 工作树；合并、推送、关闭或分支重命名均等待用户另行批准。

## 2. 范围

### 允许修改

- `plan/050-multi-explicit-collaboration-case-study-execplan.md`：执行期只更新允许变化的当前状态与关键决策记录。
- `eval/rondo_eval/` 中直接相关的共享测评代码；优先复用/窄泛化 `proactive_eval/`、`terminal_bench/`、`team_lens/`、
  `multi_m5/` 和公共预算/归档组件，内部模块形态由执行者依据实时代码决定。
- `eval/tests/` 中直接相关的定向测试，以及 `eval/fixtures/` 中小型、合成、body-free fixture。
- `eval/locks/`、`eval/tasksets/`、`eval/templates/` 中 Plan 050 独立冻结合同；不得改写历史 Plan 049/M-5/P2 锁。
- 必要的 `justfile` 或 `scripts/` 窄入口；不得绕过现有付费授权、Docker 或 build-lock/watchdog 门禁。
- `multidev/` 仅限共同 eval 接线无法完成时的窄测评适配；不得改变 Team State 或产品协作语义。冻结 Codex 不修改。
- 阶段状态实际变化时，精炼更新 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`；仅在阶段 B 最终完成后更新
  `doc/WBS-COMPLETED.md`。本任务有实质进展时新增精炼 `agent_log/`。
- 阶段 B 可新增紧凑、body-free、可确定性重建的总览/案例结果；展示的具体文件组合由执行者选择，不为此建立新前端工程。

### 允许的 ignored 共用根产物

Git worktree 不复制下列本地机器状态。050 工作树可通过 `RepoPaths.common_root` 使用主仓库共同根，并须在每阶段交付中
单独列明实际读写；这不授权修改主工作区受跟踪文件：

- `eval-data/` 中已有冻结 runtime bundle、Terminal-Bench source、scratch、trace 与 Team Lens 生成物；Plan 050 新状态
  只能写入独立 `eval-data/plan-050/`，不得覆盖、迁移或清理 Plan 049 及其他任务资产。
- 如确需依赖同步，`eval/.venv/` 与 `eval-data/uv-cache/` 可由仓库既有 `just eval-sync` 共用；无依赖变化时优先复用现状。
- `.env.local` 只能由既有安全检查/加载器静默检查：存在、普通文件、非符号链接、权限 `0600`、任务所需变量存在且非空；
  不得打开、搜索、打印、复制、source 或记录内容。
- `rondo.local.toml` 只允许作为非密钥机器配置输入。若现有共同入口确实要求 Plan 050 的非密钥模型/effort 投影落在该文件，
  阶段 A 可做保持其他配置不变的最小修改并单独汇报；优先使用 Plan 050 独立合同/入口，文件中不得写入任何 API Key。

若发现除上述清单外必须直接修改主工作区或其他 git-ignored 共享状态，先停止该动作并向用户说明。

### 不允许修改

- `codex-source-code/`、冻结 Codex 源码/二进制或上游基线；不得为本任务重新构建、修补冻结 Codex。
- `mydev/`、Local 路线、Plan 049 历史合同/结果/paid namespace，或其他工作树/分支的贡献。
- RONDO Multi/Team State 产品语义、默认语义或专门提高第一次 spawn 率的产品机制；不得新增 delegation scheduler。
- 任务 prompt、task-native verifier、镜像内容，或为三道题之一编写特化协作脚本/角色剧本。
- CI/PR、全 workspace 测试、本地模型、训练、完整 benchmark、宿主机/全局工具链/系统服务、其他仓库或远端资源。
- 为得到更好展示而规定或优化 Event、Fact、route、wake、telemetry、participant 或工具调用的数量/顺序。
- 为追求绿色而弱化 verifier、trace identity、费用、resume、body-free、资源或阶段授权边界。

### 不允许读取/查看

- `.env.local` 内容，以及任何项目外个人文件、凭据或私有数据。
- 与 Plan 050 无关的 raw trace、任务 workspace、账本、运行正文或其他 worktree 未提交内容。
- Plan 050 原始运行资产只允许任务内消费者按既有白名单机械归约；不得把 prompt/response、message、命令/结果或 Fact 正文
  打印到终端、日志、对话或受跟踪文件。协作影响链不能从正文关键词、ID 外观、时间邻近或数量阈值猜测。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试、提高委派率或获得更漂亮的案例而违反。

### 3.1 基线、阶段与 Git 交付

- 计划基线为 `main@38e922e736f236e922c114d81a205d2d9f65b10f`；专用工作树为
  `.claude/worktrees/050-multi-explicit-collaboration-case-study`，分支为
  `worktree-050-multi-explicit-collaboration-case-study`。执行前仍须检查主工作区、050 与其他 worktree 状态，保护并行贡献。
- 阶段 A 与 B 使用同一计划、分支和工作树并严格串行。当前规划授权、阶段 A 授权和阶段 B 付费开始授权三者相互独立，
  不得互相推定。
- 阶段 A/B 各自完成后，执行者只提交 050 本地分支并保持工作树干净；不合并、不推送、不关闭、不重命名分支。
- 普通 fixture、配置、编排、归档、报告、Docker/网络/provider 可恢复故障由执行者在合同内自主定位、窄修、测试、resume
  和重跑；只有触及原则边界、外部状态无法核清、总预算/资源硬门、或必须扩大授权时才暂停。

### 3.2 冻结公平合同

**产品与二进制**

- 共同 runtime identity 复用 `eval/locks/multi-m5-runtime-v4.json`：
  - 冻结 Codex：源码 `be6e8eac029b183056b7e4402879f15d2c85f61b`，二进制 SHA-256
    `8bd5f096af8302c0d5bf272a15a563d243fe77e8b704b749321a437c815f1a80`；
  - RONDO Multi：源码 `0eee6dc5ee69f0eca9e1db350148c423a2b2bf67`，二进制 SHA-256
    `c64ff001fe7bec20c84a6bbea84f077ffffdcddc8b796b2f663513d5d7a6c631`。
- 两侧都启用相同 Multi-Agent V2 共同工具、approval/sandbox、成员覆盖、原生 rollout trace 和任务环境；只有 RONDO 额外
  启用 Team State。产品或 bundle 不具备该合同则阶段 A 为 `blocked`，不得单边改产品后继续冒充公平比较。

**任务、镜像与 verifier**

- 任务来自 `eval/tasksets/p2-b7-canary-catalog-v4.json`，文件 SHA-256
  `00b83e4435218de730c25fcbc8fd69cebc0cee36db433a4b305076cb1e157ddf`，内部 taskset SHA-256
  `2a9f9e3400f38606bacd71a220d8abb595a108ef3622556e8684dadbeb03a61b`，Terminal-Bench commit
  `ffccbe05ee73a9d59518217f294ad711bda39304`。每题的 source digest 同时绑定原生 task instruction 与 task-native verifier：

| Task | Source digest | Docker image（digest-pinned） |
|---|---|---|
| `terminal-bench/sqlite-db-truncate` | `sha256:956f038b479cc3b9b493553b57a60a8ff4154526386c3914c0b99e93e1ab6e87` | `alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4` |
| `terminal-bench/headless-terminal` | `sha256:203953871ebdae4efbf163af9499849368dab5e219b70d447e5ee9701ad382d9` | `alexgshaw/headless-terminal@sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa` |
| `terminal-bench/extract-elf` | `sha256:1ef31d566be4fe3459d5368621ae7ef7a31b23ef675737e473bbc43c8c7b3fce` | `alexgshaw/extract-elf@sha256:6932e4cb318464307eacd497ef8dc617eaf551b6a90231f815ec0b911895cfed` |

- 三题共同使用 `/app` workdir、2048 MiB、PID limit 256、task timeout 1800 s、agent timeout 900 s、verifier timeout
  900 s、build timeout 600 s。两侧只接收同一原生 task instruction；collaboration 要求只来自下述共同 developer policy。
- 外部完成判定只来自 task-native verifier。通过为 `completed`，verifier 未通过为 `task_failed`；可归因的产品/协议终止为
  `product_failed`。这些都是有效外部结果，不因分数不好或案例不漂亮重跑。

**共同明确 collaboration policy**

两侧 Root 的 developer instruction 必须是下列单行 UTF-8 文本加一个尾随 LF；任何换行、空格、标点或大小写变化都视为
漂移。冻结 SHA-256 为 `a4d90e09a9c0ff69816a6da4153a6fb78c3ad8695dd4076c9884a33eb3b90b49`：

```text
You must use teammates to carry out genuine multi-agent collaboration on this task. Delegate substantial and independently actionable work to teammates. When new evidence could affect another line of work, communicate it and adapt the approach or work division as warranted. Integrate and verify teammate contributions before finishing. Choose the team shape, timing, communication pattern, and tool sequence autonomously. Do not fabricate activity for observability or target Team State events, routes, facts, wakes, telemetry counts, participant counts, or call ordering. The Root remains responsible for the final solution and verifier outcome.
```

- policy 不按任务特化，不规定任务拆分、成员角色/数量、工具顺序或 Team State 调用。Root 自主决定团队形态、时机、通信与
  具体实现，但必须承担委派、整合和最终 verifier 责任。
- 运行时若 custom developer instruction 是替换而非追加，两侧保持同一替换语义；不得让一侧额外保留另一侧没有的默认
  collaboration 文本。成员线程如何继承同一 session policy 按冻结产品原生语义处理，不做单侧特化。

**共同 provider 与运行条件**

- provider/API/base URL 复用 Plan 049 的 `relay` / `responses` / `https://www.cctq.ai/v1`；Root、普通成员与 Guardian
  都使用 `gpt-5.6-terra`，reasoning effort 都为 `high`。`medium`、`ultra` 或异构成员不属于 Plan 050。
- 阶段 A 用只读官方来源与本地 provider 投影冻结当时价格快照和保守 reservation 计算。Plan 049 的 2026-08-18 快照
  （input 2、cached input 0.2、output 12 USD/百万 token 及既有长上下文/cache-write 乘数）只能作为起点；若事实已漂移，
  应更新 Plan 050 新锁和费用预测，不改写 Plan 049。阶段 B 的价格投影与锁不符时停止，不猜测计价。
- 每次只运行一个 Terminal-Bench 逻辑槽位；槽位内部 `max_concurrent_threads_per_session=4`（Root 加最多三个同时活跃成员），
  provider 主请求并发上限为 4。不得为某题或某侧临时提高并发或指定成员数。
- 每个 run 的请求上限为 80；provider 内部无账单重试沿用最多 5 次、2 s backoff，仅限 429/500/502/503/504。
  这些是单请求 transport 语义，不是整个逻辑槽位的 infra 重跑次数上限。
- approval policy 为 `on-request`、sandbox 为 `workspace-write`，两侧网络与 Docker 条件一致。主报告必须表述为
  “`gpt-5.6-terra` + `high` + 同一明确 collaboration policy 下的三任务案例”，不得冒充产品默认行为。

### 3.3 六槽顺序与第一对早期确认

六个基础逻辑槽位全局串行、task-major 执行；pair-first 交替以降低固定 side-first 偏差。稳定 anchor 先行，用正式第一对
同时确认真实 provider/trace/结算链，不另建 pilot：

| 顺序 | Pair | Task | Side | Product |
|---|---|---|---|---|
| S01 | C01 | `terminal-bench/sqlite-db-truncate` | `codex` | 冻结 Codex |
| S02 | C01 | `terminal-bench/sqlite-db-truncate` | `rondo` | RONDO Multi |
| S03 | C02 | `terminal-bench/headless-terminal` | `rondo` | RONDO Multi |
| S04 | C02 | `terminal-bench/headless-terminal` | `codex` | 冻结 Codex |
| S05 | C03 | `terminal-bench/extract-elf` | `codex` | 冻结 Codex |
| S06 | C03 | `terminal-bench/extract-elf` | `rondo` | RONDO Multi |

- 第一对形成的有效结果必须保留在正式案例中。若其暴露可恢复设施问题，先修复并从可信状态恢复；若暴露任务/policy/model/
  身份漂移、无法选择唯一 Root 或未知请求/费用状态，则按 §3.4 原则性停止，不用额外 pilot 绕过。
- `policy_noncompliance` 不是 activation stop。只要公平合同和证据链成立，仍按固定顺序完成剩余槽位并如实报告；不得追加
  第七个有效槽位把 noncompliance 采成阳性。

### 3.4 结果维度、恢复与停止语义

- 每个稳定 slot/run/attempt identity 分别记录三个正交维度：
  1. 外部结果：`completed` / `task_failed` / `product_failed`；
  2. 协作合规：`collaboration_observed` / `policy_noncompliance`；
  3. 观测状态：Team Lens 既有 `available` / `partial` / `unsupported` / `not_applicable` 及 reason code。
  不得用其中一个维度覆盖或美化另一个维度。
- `collaboration_observed` 至少要求 accepted Root spawn，且成员确实推进一项实质、独立可行动的工作并把贡献交回团队；
  只 spawn 后立即结束、空转或为了 telemetry 造活动不满足。这里不设置消息数、工具数、token 或 participant 数量阈值。
- policy hash 已匹配且 Root trace 可解释，但没有 accepted Root spawn 或只有仪式性成员活动，记为 `policy_noncompliance`；
  无论 verifier 成败都不补跑。policy 未注入/漂移则不是 noncompliance 样本，而是公平合同原则性停止。
- “成员发现 → 团队传播 → Root/其他成员调整 → 最终整合”只在 typed identity/interaction/Team State 关系与时序足以支持时
  标为 `observed`；调用数量或先后相邻本身不证明影响。证据不足标为 `not_observed` 或 `unknown`，不要求导演出完整链。
- provider/network、Docker/Harbor、runner、账本、collector、归档或报告的可归因设施故障可记为 `infra_failed` 无效尝试。
  执行者可在不改变公平合同的前提下自主窄修、测试、resume 和重跑；本计划不设置容易把可修问题提前变成失败的逐槽/
  逐错误小次数上限，所有已提交 paid attempt 仍受同一总预算约束并保留 attempt lineage。
- 已归档的有效外部终态只读复用；中断后只补尚无可信终态的一侧。若 provider 已结算而 Team Lens/报告失败，只恢复本地
  归约/发布，不重复请求。不能把有效任务失败或产品失败改标 infra 来购买新样本。
- 若产品已形成有效外部终态但唯一 Root/trace 身份无法核清，不得购买替代样本，应持久原则性停止并独立报告；若请求是否
  已提交、usage/费用、slot identity 或 reservation 状态无法保守判断，同样停止而不猜测。
- 任务、policy、模型/effort、公平合同漂移，logical slot 或 Root 无法唯一确定，预算/费用/请求状态无法核清，正文/密钥
  泄漏风险，或 Docker/Windows 磁盘/其他资源硬门触发时，立即持久停止。普通可修的 5xx、fixture、归档或 resume 问题
  本身不构成原则性停止。

### 3.5 费用、Team Lens 与数据产物

- 阶段 A 冻结 `maximum_authorizable_cap_usd=100.00`。阶段 B 启动 receipt 再冻结用户本次明确授权的实际硬上限，必须为
  正数且不高于 `min(100.00 USD, 已确认可用余额)`；降低实际上限不改变任务公平合同，提高到 100 USD 以上必须重新授权
  并修改稳定合同。Plan 049 历史费用不计入 Plan 050。
- 实际上限覆盖六槽、provider 请求和所有 infra 重试；不设逐题、逐错误的小预算。账本按冻结价格保守 reservation/settle，
  未知 usage 保留足额 exposure，不把 reservation 当实际费用，也不把未定费用记为零。达到实际上限立即停止。
- 每个有效 run 的 ignored 产物至少包含 raw bundle、settled/execution/API metadata、task result、`team_view.json`、
  `team_report.html` 与 body-free run record；tracked 聚合只保存允许字段、稳定 identity/hash、外部结果、usage/cost、
  availability/reason code 和计数/时序指标。
- 三份并列案例与总览复用现有 Team Lens/报告数据合同。每题的两侧指标和轨迹必须对齐到各自 slot；Codex 的 Team State
  明确 `not_applicable`，RONDO 只展示自然产生的 Team State。可直接展示的具体 HTML/JSON/Markdown 组合由执行者自主选择，
  但必须确定性、离线、body-free，并且不建立服务端、数据库、在线 UI 或第二套前端构建系统。
- file activity、message/followup/wait 与 Team State 字段沿用 Team Lens 既有机械 coverage 和四态语义；取不到就降级，
  不通过 shell 文本、正文关键词、ID 外观或时间邻近猜测。

### 3.6 资源与测试

- 阶段 A 默认不用 Docker。若正式接线确实需要，可选择上述一个明确 digest 做至多一个串行、零 API 的轻量端到端彩排，
  不运行三题全集。阶段 B 只运行固定六槽及可归因 infra 恢复，不扩到完整数据集。
- 任何 Docker 操作前后记录 `docker system df` 与 Windows `C:` 实际余量；以任务开始为基线，新增占用 40 GB 告警、
  60 GB 主动停止，`C:` 低于 80 GiB 立即停止。只清理本任务明确创建的对象，不清理来源不明的镜像、容器、卷或缓存。
- Docker、重型 Cargo、真实本地模型和付费 API 全局串行并互斥。本任务不授权本地模型加载、训练或批量真实 API 测评。
- 任何重型 Cargo 构建/测试必须经共享 `scripts/with-build-lock.sh` 或已接入的 `just` 入口；拿不到锁、cgroup、Windows `C:`
  实际余量或其他资源计数器时 fail-closed，`CARGO_TARGET_DIR` 必须位于受监控的 RONDO 项目根内。
- 只跑受影响模块的必要门禁；不要求全 workspace、CI 或 PR。测试、fake、loopback、replay、轻量 Docker 与真实付费结果
  必须明确区分，skip 或未运行不能表述为通过。

## 4. 软性建议

以下建议基于 `main@38e922e` 的现有结构，不固定内部实现。执行者可依据实时代码、测试与更小的设计采用更优方案，并在
关键决策记录中简述实质偏离。

- 优先把 Plan 049 的薄 campaign/contract/aggregate 层参数化为可承载 Plan 050 新 lock/taskset/namespace 的共享组件；
  若更小的适配层更清晰也可以采用，但不要复制 `proactive_eval` 整包。
- 先落地机器合同、policy 模板和六槽 schedule，再用现有 fake/loopback/replay 验证；只有真实缺口才扩 loader、runner、
  Team Lens 或报告 schema。
- 第一对选择稳定 `sqlite-db-truncate` 是为了尽早暴露真实链路问题；它仍是正式结果，不应增加与第一对重复的 pilot。
- 展示层可采用“紧凑成对摘要 + 两侧现有 Team Lens 报告”的组合；如果现有 renderer/aggregate 已能满足，就不要重做视觉前端。
- `policy_noncompliance`、外部结果和轨迹链使用独立字段，避免把 task pass 自动包装成协作成功，或把 verifier fail 自动包装成
  协作失败。
- 使用 `RepoPaths.discover()` 的 worktree/common-root 语义访问共享 ignored 资产，避免写死主工作区绝对路径。
- 阶段 A 调试、定向测试与可归因 infra 恢复可以自主多次进行；不要因一次可窄修错误过早停工，也不要为了避免停工越过
  合同、费用、身份、正文或资源边界。
- 阶段 A 完成后先由执行者自检并提交，再交给独立审查者；真实 finding 由执行者在同一工作树窄修并重跑相关门禁，直到
  `paid-ready` 或确认存在原则 blocker。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- [x] 已阅读根 `AGENTS.md`、README、当前 WBS、Multi 子 WBS、计划模板、Plan 048/049 的相关合同、Plan 049 实现入口、
      runtime/catalog lock、Team Lens schema 与 050 前置规划日志。
- [x] 已确认主工作区进入时干净；用户随后明确授权把 050 既有两笔前置规划提交 fast-forward 合并到本地 `main`。
      合并后 `main` 与 050 分支共同基线为 `38e922e736f236e922c114d81a205d2d9f65b10f`，未推送。
- [x] 已冻结本计划的研究问题、三题身份、明确 collaboration policy 及 hash、`high` effort、公平运行条件、六槽顺序、
      分类/恢复/费用语义、A/B 授权门、资源边界和轻量复用原则。
- [x] 用户已明确授权阶段 A；已冻结 `multi-explicit-collaboration-v1` lock/taskset/policy/replay fixture，建立独立
      `plan050-*` run/attempt/batch、`plan-050-rehearsal-v1` / `plan-050-paid-v1` namespace 和
      `eval-data/plan-050/` ignored 根，Plan 049 的合同与既有 paid 状态未改写。
- [x] 已完成六槽 dry-run、fake/replay、确定性三题案例/总览和两侧冻结二进制零 API loopback；共同 policy、共同
      Multi-Agent V2 工具面、Root `terra/high` 请求、成员 `terra/high` CLI 投影与 Guardian `terra/high` 共同
      model-catalog 投影均已机械核对。loopback 只观察到 Root 请求，成员/Guardian 如实标为配置投影。
- [x] 已完成实际预算 receipt 绑定、正式入口负门禁、共享 runner/账本/resume 的临时离线注入测试；阶段 A 未读取密钥
      正文，未创建正式 paid receipt/ledger/run，未调用真实 provider、Docker、Cargo 或本地模型，费用为 0。

### 当前工作

- 阶段 A 实现、定向自检和 ignored rehearsal/loopback 证据已完成，当前等待本轮上下文独立的审查者复核；在该复核
  明确通过前只称 `paid-ready-candidate`，不称最终 `paid-ready`。

### 本任务剩余步骤

- 提交阶段 A 候选，由上下文独立审查者复核合同、测试、离线证据、付费负门禁和 body-free 边界；真实 finding 窄修并
  重跑，直至 `paid-ready` 或确认原则 blocker。
- 仅在用户另行明确授权阶段 B 和实际费用上限后，串行运行六槽并完成结算、三份案例、总览和最终独立验收。
- 阶段 B 最终完成后更新权威文档与历史记录，提交 050 分支；合并、推送和关闭继续等待用户授权。

### 阻塞项

- 无已知阶段 A 技术 blocker；阶段 B 的独立开始授权与实际总预算尚未提供，这是预期授权门。

### 当前验收状态

- `paid-ready-candidate`：六槽 fake rehearsal 为 4 成功、2 有效失败、0 infra，确定性案例/总览完整；最终 loopback
  namespace 为 `phase-a-final-v3`，两侧各 1 个本地回环 Root 请求，policy/tool/model 投影一致。
- 定向回归共 216 项：214 通过、2 项因未提供既有真实 Plan 049 样本路径按预期跳过；无失败。范围覆盖 Plan 050、
  Plan 049 共享编排、预算代理、Terminal-Bench、Team Lens 与 Multi 工具面，未运行全量测试。
- readiness 复算得到 6/6 terminal、无缺槽/半对，且 `eval-data/plan-050/paid/` 不存在。阶段 A 未运行真实 API、Docker、
  Cargo、模型或全 workspace 测试，没有产生费用；最终结论仍待独立审查。

### 交接边界

- 阶段 A 完成后本计划仍保持为同一 A/B 合同，只更新当前状态与必要决策；阶段 B 必须再次获得用户授权。
- Plan 050 最终完成后冻结本计划；后续路线只链接 WBS，不在本计划继续规划。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | A/B 使用同一 plan、分支和工作树，A/B 分别授权 | 保持合同与恢复连续，同时隔离无费用准备和真实费用边界 | 全任务 | 已采纳 |
| 002 | 复用 Plan 049 全链路，只建 Plan 050 独立 identity/namespace | 现有 runner、账本、selector、trace、Team Lens 已验证，避免重复系统 | 阶段 A/B | 已采纳 |
| 003 | Root/成员/Guardian 统一 `gpt-5.6-terra` + `high` | 响应用户把 effort 从 `medium` 升级为 `high`，并保持两侧唯一产品差异 | 公平合同 | 已采纳 |
| 004 | 精确 policy 强制真实委派与整合，但不规定团队形态或 Team State 活动 | 建立 post-delegation 条件，同时避免导演 telemetry 与实现路线 | policy | 已采纳 |
| 005 | 三题为 sqlite anchor、headless 主案例、extract-elf 高难挑战；每题每侧一次 | 同时覆盖稳定链路、动态整合和困难泛化，不为展示补样本 | 任务集 | 已采纳 |
| 006 | 第一对使用 sqlite 正式结果确认 provider/trace/结算，不设额外 pilot | 复用稳定 anchor 尽早暴露链路问题，并避免增加第七/第八个样本 | 调度 | 已采纳 |
| 007 | 外部结果、协作合规和观测四态正交记录 | 保留 task pass + noncompliance、真实协作 + task fail 等真实组合 | 判读 | 已采纳 |
| 008 | 不设逐槽/逐错误小重跑上限，只受公平状态、总预算和资源硬门约束 | 给可修设施问题充分冗余，同时禁止选择性重采有效结果 | 恢复/费用 | 已采纳 |
| 009 | 阶段 A 冻结 100 USD 最高可授权上限，B 再冻结不高于余额的实际上限 | 既给 campaign 足够空间，又确保费用不超过用户当次授权和可用余额 | 费用 | 已采纳 |
| 010 | 三份案例复用 Team Lens 数据合同并保持 body-free，不新建前端 | 满足产品展示与轨迹解释，同时保持设施轻量 | 报告 | 已采纳 |
| 011 | 工作树完成只提交本地分支；合并和推送均需用户另行批准 | 符合本任务明确 Git 交付边界 | 交付 | 已采纳 |
