# Plan 015：P2 任务分层、计分预算与首次 Canary 基线

> 本计划是方向 0 的 P2 第一阶段执行合同。Plan 014 v19 及其全部历史 identity/result/ledger/artifact
> 保持只读；本计划使用新的 taskset、campaign identity、run IDs 与 200 USD 独立硬上限。除“当前状态”和
> “关键决策记录”外，其他章节默认不在执行中改写；若必须改变 provider、Sol/medium main、Sol/low Guardian、
> frozen Codex/RONDO bundle、TB 2.1 commit、10-task 清单、基础轮次或预算，暂停并请求用户确认。

## 1. 目标

### 最终目标

先闭合 Plan 014 成功 CLI 的 durable Guardian evidence 投影，再完成 B4 taskset 冻结、B5 机械计分/归因、
B6 可复算成本与 200 USD campaign 护栏，最后在相同 TB 2.1、任务顺序、profile、参数和冻结二进制下执行
RONDO A/A 两轮及 frozen Codex/RONDO A/B 各一轮，按机械规则形成 B7 基线终态。

### 完成/验收标准

- 成功 CLI 与 tracked result 复用同一 public evidence projection；CLI 路径在 work/jobs 清除后仍指向归档，且含
  `canonical_request_sha256`。
- `RunSpec` 40 USD 合同的错误信息与实现一致；方向 0 文档只把 v19 S2 称作
  `task_scoped_count_match`。
- B4 三份清单恰为 10 canary、61 validation、18 holdout；互斥、完备、稳定、可由 pinned 89 个 task ID
  机械重算。holdout 先按 ID-only 规则冻结，执行期间禁止读取其正文、验证器、日志或单任务结果。
- B5 主指标为 Task Resolution Success Rate；机械区分 `agent`、`guardian_correct_deny`、
  `guardian_false_deny`、`infra`。矛盾/未知 Guardian deny 没有 correct-deny 证明时保守归为 false deny；infra
  不进分母。holdout 只能发布整批聚合，不得持久化单任务明细。
- B6 在 API 前输出历史 usage 插值、v19-shape 压力区间、基础/全条件轮数与 200 USD 停止语义；campaign
  使用新 lock、ID 和持久 ledger。任何新请求的最大合法 reservation 无法装入剩余全局预算时不启动。
- B7 基础 40 个运行全部形成唯一终态；同一 RONDO bundle A/A 两轮得到 `sigma`，A/B 差异 `delta <= sigma`。
  `sigma > 2` 机械标为 canary unstable。每个 Codex-pass/RONDO-fail task 两侧各加跑两次；Codex 三次全过且
  RONDO 三次全败则 failed。
- 单轮 infra 比例大于 20% 时该轮无效；每轮最多一次全轮 replacement，比例不超过 20% 时每 task 最多一次
  定点 replacement。额度耗尽或仍无有效结果则 campaign failed/blocked，不把部分结果称为通过。
- fresh exact-wire canary、失败运行、replacement 与条件加跑均进入同一 200 USD 账本；所有 reservation 最终
  settled，`actual_usd=null`。
- focused unittest、`just eval-lock` 和阶段末一次 `just eval-test` 通过；正式 B7 前代码/lock 干净提交，Docker、
  Windows C:、watchdog、profile/catalog/bundle 均通过门禁。
- 最终变更与真实结果提交到当前独立审查分支；不合并、不推送。

## 2. 范围

### 允许修改

- `eval/rondo_eval/terminal_bench/` 的 evidence 投影、taskset、通用 frozen task、单任务 runner/materializer、
  scoring、campaign 状态机、结果与成本聚合。
- `eval/rondo_eval/api_budget_proxy.py` 的通用 campaign cap/run 数和 Guardian outcome 去敏观察。
- `eval/tasksets/`、一份新的 B7 tracked lock、现有 unittest、必要 `just` 入口。
- `doc/WBS.md`、`doc/WBS/eval-benchmark.md`、`doc/eval-data-layout.md`、
  `doc/WBS-COMPLETED.md`、本计划和一份精炼 `agent_log`。

### 不允许修改

- `codex-source-code/`、frozen Codex/RONDO bundle 字节、`mydev/` 产品行为、上游基线、依赖版本。
- v8—v19 lock/result/ledger/artifact，以及其他历史数据或来源不明 Docker 资源。
- 供应商远端设置、账户、API key、云资源或完整 TB 数据集运行。

### 不允许读取/查看

- `.env.local` 内容；只允许现有 strict loader 静默验证并最小注入。
- `eval/tasksets/holdout.txt` 中 ID 对应的任务正文、`task.toml` 元数据之外的文件、验证器、solution、日志、
  单任务结果或失败细节。本计划允许机器读取 holdout 清单本身以验证分区。
- 任何未纳入 canary 的 validation task 正文、验证器、solution、日志或结果；B4 只读其公开 `task.toml`
  allowlist 元数据时必须先证明该 ID 非 holdout。

## 3. 硬约束

1. 新 P2 真实 API 本地估算总费用最多 200 USD，独立于 Plan 014。200 USD 是硬停线，不是消费目标，也不是
   合法 usage 的数学全包保证；不得减任务、减基础轮次或弱化门禁迁就预算。
2. B4/B5/B6 及最后窄修复不得调用 API 或 Docker；B7 只处理 10 个 canary 所需 exact digest 镜像，pull/run
   并发为 1。不开 Cargo、不重建 bundle、不升级上游。
3. holdout 必须先仅由完整 task ID 的无盐 SHA-256 排名划出 `ceil(N/5)`；之后才能读取 visible task 的
   allowlist `task.toml` 元数据选择 canary。模型成绩、失败日志和 verifier 不得参与选题。
4. taskset 和 campaign lock 只跟踪 ID、归属、pinned digest/image/resource/profile/bundle/运行合同；不跟踪任务正文、
   raw endpoint、key env 或秘密。
5. campaign 全部串行。每个 run ID 预冻结且一次性；infra replacement/条件加跑使用独立 ID，不覆盖、重写或
   回收原结果。任一含糊 budget/usage/crash 状态按既有合同保守结算。
6. RONDO→Codex 的要求适用于 A/B 基础轮：先完成 RONDO A/B，再运行 Codex A/B。A/A 两轮先于 A/B；前序
   campaign gate 未满足时不启动后序。条件加跑按 RONDO 两次后 Codex 两次串行。
7. Task Resolution 分母只含具有有效 verifier 结果的非 infra task；correct deny 和 false deny 都是失败并进入分母。
   没有独立 correct-deny adjudication 的 deny 不得猜成正确拒绝。
8. holdout 运行未来只能整批写一条 aggregate；本计划 B7 不运行 holdout。
9. Docker 前后记录 `docker system df` 和 Windows C: 实际余量；开始及每 run 前后都相对 campaign 初始基线检查
   40/60GB 增长与 80GiB C: floor。只清理由本 campaign exact label 创建的对象。
10. 所有真实执行前必须有 clean commit、fresh profile canary、冻结 catalog/bundle/lock/taskset SHA；发生 drift
    立即停止，不创建替代 identity 继续花费。

## 4. 软性建议

- B4 用一个 `tasksets.py` 和三份文本清单，不引入数据库或额外 manifest。
- B5/B6 用纯函数计分器、成本估算器和一个轻量 campaign JSON ledger；继续复用现有 ArtifactWriter、budget
  proxy、DockerSupervisor 和单任务 runner。
- P1 `fix-git` 历史路径保持兼容；通用化通过显式 `FrozenTask` 注入，而不是删除旧常量或改历史 lock。
- 真实 campaign 若基础设施反复失败，保留终态并停止，不新增第二个 campaign 绕过结果。

## 5. 当前状态

### 已完成

- Plan 014 v19 历史 M1 cost/spend 绑定已在 `0f9c23b` 通过审查。
- B4 已先仅从 pinned `tasks/dataset.toml` 读取 89 个 task ID，并按 ID-only SHA-256 排名冻结 18 个 holdout；
  之后只读取非 holdout 候选的 `task.toml` allowlist 元数据，未读 verifier/solution/log/result。
- 已确认成功 CLI 的 evidence 手工投影仍使用 Harbor work 路径且漏 canonical digest；已完成共用 projection、
  RunSpec 错误文字和 v19 S2 文档修复；成功 CLI durable path 回归已通过。
- B4 已落 10/61/18 三份 ID-only 清单与 pinned catalog/holdout 重算门禁；B5 纯函数计分、矛盾拒绝和 holdout
  整批聚合已落；B6 可复算成本输出、200 USD/161-slot 共享 ledger 上限与 B7 聚合规则已落并通过 focused tests；
  161 包含 1 次 wire canary、40 基础、40 条件、最多 40 基础 infra replacement 与 40 条件 infra replacement。

### 当前工作

- 离线实现已完成：10-task catalog/materializer/runner、B5 计分、200 USD/161-slot 状态机、campaign public
  result、usage/cost 聚合、10-task no-API oracle 前置与正式入口均已落地；正在完成最终离线门禁与干净提交。

### 后续计划

1. 完成 focused/full unittest、taskset/cost 报告并提交。
2. 在 build lock/watchdog 下执行 10-task no-API oracle、资源门禁和 fresh exact-wire canary。
3. 串行执行 B7 状态机；聚合并提交真实结果和文档。

### 阻塞项

- 无离线阻塞；真实执行仍以干净提交、fresh canary、80 GiB C: floor 和完整 watchdog lease 为启动门。

### 当前验收状态

- Plan 014 post-audit 窄修复、B4/B5/B6 与 B7 离线执行设施已通过 focused tests。10 个 exact image 已按
  digest 串行拉取并只读解析；尚未运行 B7 oracle、fresh API canary 或正式 40-run 基线。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | holdout 为无盐 `sha256(task_id)` 排名前 `ceil(N/5)` | 只依赖 ID，无可调 salt，当前精确 18/89 | B4 | 已采纳 |
| 002 | canary 固定 10 个可见、无 GPU、资源有界且能力差异明确的任务，`fix-git` 作为 P1 锚点 | 兼顾成本、差异和既有链路证据，不看模型结果选题 | B4/B7 | 已采纳 |
| 003 | `sigma > 2` 机械判 canary unstable | 避免“接近任务总数”主观化，也不放宽 A/B 判据 | B7 | 已采纳 |
| 004 | 200 USD 用历史 usage 作合理可行性判断，但每个新 request 仍按 18.885 USD 最大合法 reservation 门禁 | 数学最坏 40/80 run 超过授权，不能伪称全包；历史压力区间远低于 200 | B6/B7 | 已采纳 |
| 005 | 未有独立 adjudication 证明的 Guardian deny 保守归 false deny | 不用 Guardian 自评循环证明“正确拒绝” | B5 | 已采纳 |
| 006 | 不扩展 M1 两槽 ledger；B7 使用独立 campaign 状态机并复用单任务 runner/budget ledger | 拓扑不同，避免把历史 pair 语义拉坏 | B6/B7 | 已采纳 |
| 007 | 在 lock 冻结前以 `build-cython-ext`、`extract-elf` 替换需要 system service/root capability 的两个候选 | 现有两侧非特权容器合同无法公平运行 system-admin 任务；不把确定性环境失败计入 σ | B4/B7 | 已采纳 |
| 008 | campaign 冻结 1 canary + 40 base + 40 conditional + 各 40 bounded infra replacement，共 161 个唯一 slot | 单轮 >20% infra 需整轮替换，条件加跑也需一次定点替换；所有可能 ID 事前冻结 | B6/B7 | 已采纳 |
