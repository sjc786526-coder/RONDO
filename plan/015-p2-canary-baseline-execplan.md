# Plan 015：P2 任务分层、计分预算与首次 Canary 基线

> 本计划是方向 0 的 P2 第一阶段执行合同。Plan 014 v19 及其全部历史 identity/result/ledger/artifact
> 保持只读；本计划使用新的 taskset、campaign identity、run IDs 与累计 700 USD 独立硬上限。除“当前状态”和
> “关键决策记录”外，其他章节默认不在执行中改写；若必须改变 provider、Sol/medium main、Sol/low Guardian、
> frozen Codex/RONDO bundle、TB 2.1 commit、10-task 清单、基础轮次或预算，暂停并请求用户确认。

## 1. 目标

### 最终目标

先闭合 Plan 014 成功 CLI 的 durable Guardian evidence 投影，再完成 B4 taskset 冻结、B5 机械计分/归因、
B6 可复算成本与 700 USD campaign 护栏，最后在相同 TB 2.1、任务顺序、profile、参数和冻结二进制下执行
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
- B6 在 API 前输出历史 usage 插值、v19-shape 压力区间、基础/全条件轮数与 700 USD 停止语义；campaign
  使用新 lock、ID 和持久 ledger。任何新请求的最大合法 reservation 无法装入剩余全局预算时不启动。
- B7 基础 40 个运行全部形成唯一终态；同一 RONDO bundle A/A 两轮得到 `sigma`，A/B 差异 `delta <= sigma`。
  `sigma > 2` 机械标为 canary unstable。每个 Codex-pass/RONDO-fail task 两侧各加跑两次；Codex 三次全过且
  RONDO 三次全败则 failed。
- 后继 identity 的每条 task/round/side/repeat 运行链只对 infra 激活后续 attempt，最多 `a1`—`a4`；首个
  pass 或正常 reward 0 等有效结果立即跳过余下 attempt。`a1` infra 后紧接同题 `a2`；同一结构化类别第二次
  出现时先落 durable diagnosis hold，未经结构化 RCA resolution 不得 claim 下一 attempt。本地实现或共享基础设施
  缺陷使当前 identity blocked；仅结论为外部瞬态时允许继续。任一类别第三次出现标为
  `task_local_reproducible_infra` 并停止该题，不运行 `a4`；类别不同才可在总上限内继续。
- 单轮最终 infra 最多 2 项，超过时在下一轮前立即 blocked；基础与条件链使用同一 attempt 合同。
- 同一结构化机械故障类别累计命中 3 个不同 task 时立即熔断，未启动 slot 不再 claim；预算停止导致的 publication
  拒绝继承预算代理的结构化上游根因。`sigma`/`delta` 只在四轮共同有效的同一 task 集合上计算并公开分母，少于
  8 项只发布部分技术事实并把 M2 标为 blocked。
- fresh exact-wire canary、失败运行、replacement 与条件加跑均进入同一 700 USD 账本；所有 reservation 最终
  settled，`actual_usd=null`。
- Oracle 以单题 proof 增量落盘并由十题 manifest 聚合；proof 不绑定 paid campaign 或整个 Git commit，只绑定
  task/source/image、taskset/catalog entry、共享执行组件、verifier、seccomp、Harbor/TB 和必要宿主兼容事实。
  仅 task-local 或共享组件变化时按精确依赖失效，进程中断不丢失已完成单题。
- wire canary 独立绑定 provider/profile/proxy/model effort/catalog/bundle；新 paid identity 或供应商故障后仍 fresh，
  但其成功/失败不改变 Oracle proof 有效性。
- Oracle task 与 paid task 各自独占一次重型 lock/watchdog；取得锁后重验全部运行事实，执行、精确清理、最终资源
  计数和 durable state 写入完成后释放。campaign 另用轻量 lease 串行推进，一次只 claim 一个 slot。
- crash/restart 不重复发送已结算请求、不覆盖结果或复用 run ID：已发布且账本完整的 running slot 可机械收敛；
  其他含糊 running slot 保守结算并阻断。identity 由轻量生成入口派生，版本、ID、SHA、prior debit 与 cap 自动校验。
- focused unittest、`just eval-lock` 和阶段末一次 `just eval-test` 通过；正式 B7 前代码/lock 干净提交，Docker、
  Windows C:、watchdog、profile/catalog/bundle 均通过门禁。
- 最终变更与真实结果提交到当前独立审查分支；不合并、不推送。

## 2. 范围

### 允许修改

- `eval/rondo_eval/terminal_bench/` 的 evidence 投影、taskset、通用 frozen task、单任务 runner/materializer、
  scoring、campaign 状态机、结果与成本聚合。
- `eval/rondo_eval/api_budget_proxy.py` 的通用 campaign cap/run 数和 Guardian outcome 去敏观察。
- `eval/tasksets/`、B7 active pointer/历史 lock、Oracle proof/manifest、现有 unittest、必要 `just` 入口。
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

1. 新 P2 真实 API 本地估算总费用最多 700 USD，独立于 Plan 014。700 USD 是硬停线，不是消费目标，也不是
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
11. v1—v10 lock/ledger/result/artifact/receipt 只读；旧 Oracle 只有新 validator 能从已有字段机械证明完整匹配时
    才可复用，证据不足不回填。700 USD 授权不因 identity、进程或 proof 变化而重置。
12. coordinator 不持有重型 lock；它只持有 campaign lease 并逐个调用 locked worker。worker 等锁前不得 claim，
    锁内必须先完成 profile/identity/task/image/Docker/C:/budget/watchdog 重验，结束时先落 durable slot/proof 再释放。

## 4. 软性建议

- B4 用一个 `tasksets.py` 和三份文本清单，不引入数据库或额外 manifest。
- B5/B6 用纯函数计分器、成本估算器和一个轻量 campaign JSON ledger；继续复用现有 ArtifactWriter、budget
  proxy、DockerSupervisor、单任务 runner 与 build-lock wrapper。Oracle proof 只增加一个小型 JSON store，
  不引入数据库、签名或额外审计层。
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
  整批聚合已落；B6 可复算成本输出、600 USD/161-slot 共享 ledger 上限与 B7 聚合规则已落并通过 focused tests；
  161 包含 1 次 wire canary、40 基础、40 条件、最多 40 基础 infra replacement 与 40 条件 infra replacement。

### 当前工作

- v2 完整十题 Oracle 均 reward 1，替换后的 `openssl-selfsigned-cert` 已通过；fresh exact-wire canary completed，
  本地估算 `0.180523 USD`。
- v2 正式首轮暴露通用非 Git adapter、Guardian E_final digest 与 campaign 中断恢复缺陷；第 8 个 RONDO run
  执行中主动停止，v2 已收口为 blocked 且全部 reservation settled。v2 累计本地估算 `39.269328 USD`，
  `actual_usd=null`；其 identity、slot、ledger、result 与 artifact 不复用。
- v3 十题 Oracle 与 fresh canary 均通过；首个 RONDO 任务实际 reward 1，但结果合同把“未自然触发 Guardian”
  错判为 infra。第 2 个任务运行中主动停止并保守结算；v3 blocked、reservation 为 0，P2 累计估算
  `58.689250 USD`，`actual_usd=null`。
- B7 campaign 允许零 Guardian 的普通完成；一旦触发仍强制 `main → guardian → main` 与 E_final digest 逐项绑定。
  P1 pair 的强制审批闭环保持不变。
- v4 Oracle 与 wire canary 通过；首轮和旧全轮 replacement 后仍有 4 项 infra。旧状态机错误地在轮门禁前启动
  下一轮，已人工停止并保守结算。v4 blocked、reservation 为 0，budget ledger `99.580057 USD`；含此前尝试和
  v4 canary 的 P2 累计为 `158.468137 USD`，全部 v4 identity/state/result/artifact 只读保留。
- 经追加授权，P2 总硬上限为 `400 USD`。v5 使用新 campaign/batch/run IDs，精确冻结 prior debit
  `158.468137 USD`，采用 infra-only 定点补跑、逐轮即时门禁、结构化三 task 熔断和至少 8 项共同分母。
- v5 完整 Oracle 10/10 reward 1；fresh wire canary 的 4 个请求均 attempt 1、usage valid、角色与审批命令正确，
  但 frozen Codex 在 tool call 前额外输出一条普通 assistant 消息，唯一最终消息门禁拒绝。v5 blocked，canary
  估算 `0.226591 USD`，无正式 budget/运行。
- canary parser 不放宽；synthetic prompt 明确禁止 tool call 前 assistant/commentary。v6 使用新 identity，并把 v5
  canary 纳入 prior，精确冻结 `158.694728 USD`。
- v6 Oracle 10/10 与 fresh canary 均通过；第一轮 10 个首跑后，`filter-js-from-html`、`polyglot-c-py` 的唯一
  补跑仍为 `docker_runtime`，`vulnerable-secret` 的唯一补跑仍为 `provider_response_integrity`。逐轮门禁在第二轮
  前将 campaign 收口为 blocked，formal `41.414652 USD`、canary `0.225196 USD`，累计 `200.334576 USD`，
  reservation 为 0；v6 identity/state/result/artifact 保持只读。
- Docker 失败诊断现保留 bounded supervisor reason、结构化 probe 名和耗时。两个受影响镜像各 5 轮无 API
  counter/stats/exec 与各一次官方 Oracle 均通过，未复现持续故障；不升级或重启 Docker。v7 使用全新
  campaign/batch/run IDs，精确带入 `200.334576 USD` prior，其他冻结合同不变。
- v7 Oracle 10/10 与 canary 通过；第一轮中三个不同 task 的 `docker_container_metrics` 在约 1.2—1.7s 内
  失败，结构化 circuit breaker 在 `polyglot-c-py` 后停止，formal `21.212471 USD`、canary `0.225266 USD`，
  累计 `221.772313 USD`、reservation 为 0。根因是 inspect 后、metrics exec 前容器自然移除的 teardown race，
  不是 30s 控制面卡死。修复仅在 fresh exact-label re-list 证明旧容器已消失时接受空 final observation；容器仍在或
  identity 改变继续硬失败。两项故障镜像的官方 no-API Oracle 均由正式 parser 复核为 completed/reward 1。
- v8 Oracle 10/10 与 fresh canary 通过；第一轮在三个不同 task 出现真实 `provider_response_integrity` 后按冻结
  circuit breaker 收口为 blocked。三个无 terminal/usage 的 stream 均按 `18.885000 USD` 保守结算，v8 formal
  `59.734158 USD`、canary `0.211082 USD`，P2 累计 `281.718702 USD`，reservation 为 0；全部 v8 identity、
  state、result、artifact 保持只读。
- v8 同时证明两个独立执行缺口：task image 缺少 Python 时 adapter 无法写 auth，以及 metrics 失败发生在容器
  stopped-but-not-removed 窗口。auth 现由宿主严格编码为只读 Compose secret；Docker 只对 identity 完全一致且
  `State.Running=false` 的对象作同一 deadline 内 bounded teardown poll。SSE read error 另保留原 HTTP status 与
  `stream_end_kind`，计费和失败分类不放宽。
- 用户追加 `200 USD` 机动授权；v9 使用新 campaign/batch/161 个 run IDs，精确冻结 prior `281.718702 USD`、
  P2 总硬上限 `600 USD`。taskset、profile、bundle、TB commit、四轮与停止规则均不变。
- v9 完整 Oracle 10/10 与 fresh canary (`0.143029 USD`) 通过，首个正式 `db-wal-recovery` 以 reward 0 自然完成，
  12 个请求全部 usage-priced settled (`0.425953 USD`)。wrapper 从结果 worktree 启动，首题发布后自身变脏并被
  harness drift 门禁拒绝；进程自然退出后 v9 收口为 blocked，159 个未启动 slot 均 skipped、reservation 为 0。
  v9 总后继 prior 为 `282.287684 USD`，全部事实只读保留。
- campaign-independent Oracle store 已按单题 contract SHA 原子保存 proof，并以十题 manifest 聚合；task/image、
  verifier、共享执行组件、Harbor/TB、seccomp 或稳定 Docker 合同变化会精确失效，campaign/profile/wire 变化不会。
- paid coordinator 现只持有轻量 lease；每个 worker 经 build lock/watchdog 独立推进一个 Oracle 或 paid slot，锁内重验
  profile、identity、task/image、Docker/C:、预算和 checkout。published+settled 的中断 slot 机械收敛，其他中断阻断。
- v9 收口时的 161 slot 由代码派生，v1—v9 进入只读 registry；后继生成器从 terminal state、wire receipt 与
  settled budget 重算 prior，拒绝版本/ID/profile/bundle/cap 漂移或 debit 缺失。
- focused 185/185、`just eval-lock` 85 packages、完整 pure/fake/loopback eval 420/420 通过；本轮离线改进未调用
  API、Docker 或 Cargo，未读取 `.env.local`。
- v10 由生成器冻结为 campaign/batch `p2-b7-canary-baseline-v10`/`p2-b7-canary-sol-sol-v10`，161 个 run ID
  从 `20260812-300000000` 派生，lock SHA `3e51aa222cc222890627036221a8a235e0ff6d95b0c5491b84eb9a2cb48d5d32`，
  prior `282.287684 USD`。Oracle compatibility receipt 缺口在 0 API/0 USD 时闭合后才继续正式执行。
- v10 随后自然执行并保持原 161-slot/600 USD 合同：增量 Oracle 10/10 与 fresh wire canary (`0.225026 USD`)
  均完成；第一轮 13 个 paid run 完整结算 `61.383485 USD`，第三个不同 task 的
  `provider_response_integrity` 触发全局熔断，147 个未启动 slot 均 skipped，reservation 为 0。累计 debit 为
  `343.896195 USD`，`actual_usd=null`；结果已提交到独立 results 分支，v10 全部事实只读。
- v10 RCA 确认 provider-integrity 是 started stream 缺 terminal/usage，保守结算正确；sanitize a2 是冻结的
  Guardian 三逻辑请求上限拒绝第 4 次请求；filter 的两次 `docker_container_metrics` 失败发生在仍可见容器，不能
  按 teardown race 放行。counter 现额外保留 bounded/redacted stderr、SHA、exit/timeout，不放宽门禁。
- 用户追加 `100 USD`，后继总硬上限为 `700 USD`，精确 prior 必须为 `343.896195 USD`；后继使用 schema-v2、
  机械派生 1 wire + 80 条逻辑链 × 4 attempts = 321 个唯一 slot。v1—v10 loader 继续按各自 schema/cap/slot
  只读验证，不能因新合同失效。
- schema-v2 a1—a4、durable diagnosis hold/resolution、第三次 task-local 熔断与 321-run 预算上限已离线落地；
  focused 170/170、完整 eval 430/430、`eval-lock` 85 packages 与 diff 门禁通过，未调用 API、Docker 或 Cargo。

### 后续计划

1. 提交已通过离线门禁的 schema-v2 实现，再由生成器创建唯一后继 identity，cap 700、prior
   `343.896195 USD`，不得手写复制 active 常量。
2. 新 identity 重新执行受共享组件变化影响的 Oracle proof 与 fresh wire canary，再逐 slot 推进；第二次同类 task
   infra 必须先离线 RCA，第三次同类终止该题。最终聚合 `sigma`/`delta`、共同分母、费用与资源事实。

### 阻塞项

- 无离线阻塞；Docker counter 共享组件变化会使十题 proof 精确失效，后继需重新生成，不回填 v10 proof。若任何
  官方 Oracle reward 0 则停止并报告，不自动换题。diagnosis hold 是可恢复暂停而非 campaign 通过或费用重置。

### 当前验收状态

- v1 是 API 前失败终态；v2—v10 是保留全部费用事实的 blocked 终态。v10 累计 debit `343.896195 USD`、
  reservation 0；后继规则与 700 USD cap 已离线验收，尚未创建新 identity。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | holdout 为无盐 `sha256(task_id)` 排名前 `ceil(N/5)` | 只依赖 ID，无可调 salt，当前精确 18/89 | B4 | 已采纳 |
| 002 | canary 固定 10 个可见、无 GPU、资源有界且能力差异明确的任务，`fix-git` 作为 P1 锚点 | 兼顾成本、差异和既有链路证据，不看模型结果选题 | B4/B7 | 已采纳 |
| 003 | `sigma > 2` 机械判 canary unstable | 避免“接近任务总数”主观化，也不放宽 A/B 判据 | B7 | 已采纳 |
| 004 | v1—v10 的阶段上限用历史 usage 作合理可行性判断，但每个新 request 仍按 18.885 USD 最大合法 reservation 门禁 | 数学最坏批次超过授权，不能伪称全包；额度是硬停线而非消费目标 | B6/B7 | 已采纳 |
| 005 | 未有独立 adjudication 证明的 Guardian deny 保守归 false deny | 不用 Guardian 自评循环证明“正确拒绝” | B5 | 已采纳 |
| 006 | 不扩展 M1 两槽 ledger；B7 使用独立 campaign 状态机并复用单任务 runner/budget ledger | 拓扑不同，避免把历史 pair 语义拉坏 | B6/B7 | 已采纳 |
| 007 | 在 lock 冻结前以 `build-cython-ext`、`extract-elf` 替换需要 system service/root capability 的两个候选 | 现有两侧非特权容器合同无法公平运行 system-admin 任务；不把确定性环境失败计入 σ | B4/B7 | 已采纳 |
| 008 | campaign 冻结 1 canary + 40 base + 40 conditional + 各 40 bounded infra replacement，共 161 个唯一 slot | replacement 只按 task 首次 infra 定点激活；所有可能 ID 仍事前冻结 | B6/B7 | 已采纳 |
| 009 | 经用户批准以 `openssl-selfsigned-cert` 替换官方 verifier reward 0 的 `build-cython-ext`，重冻 v2 identity 并退役 v1 | Oracle 在任何 API 前证明原题自身不可用；不是按模型成绩择题，holdout/预算/profile/bundle/轮次均不变 | B4/B7 | 已采纳 |
| 010 | v2 在系统性 infra 后主动停止并退役；修复通用执行合同后重冻 v3，lock 扣除 v2 的 `39.269328 USD` | 避免未修复的整轮 replacement 盲目消费，并确保换 identity 不重置 P2 的 200 USD 总硬上限 | B6/B7 | 已采纳 |
| 011 | B7 的零 Guardian 自然完成合法；触发 Guardian 时仍逐项绑定；P1 强制审批合同不变。v3 退役并重冻 v4 | 多任务性能基线不能把“未需审批”伪装成 infra，同时不能弱化真实审批证据 | B5/B7 | 已采纳 |
| 012 | v4 退役并重冻 v5；取消全轮 replacement，每轮即时门禁，同类结构化故障命中 3 个 task 熔断，`sigma`/`delta` 使用至少 8 项共同集合 | 避免成功任务重复暴露于随机上游故障，也防止无效轮继续消费 | B6/B7 | 已采纳 |
| 013 | 用户追加 200 USD，P2 总硬上限改为 400 USD；v5 带入 prior `158.468137 USD` | 新授权不重置历史 debit，任何下一 request 仍须容纳最大合法 reservation | B6/B7 | 已采纳 |
| 014 | v5 canary 因 tool 前额外 assistant 消息失败；保持唯一消息 parser，收紧 synthetic prompt 并重冻 v6，prior `158.694728 USD` | 线缆/审批成功不等于精确 CLI 行为成功，不能为继续执行弱化 canary | B6/B7 | 已采纳 |
| 015 | v6 第一轮补跑后仍有 3 项 infra，逐轮门禁退役 v6；在受影响镜像无 API 稳定性与 Oracle 通过后重冻 v7，prior `200.334576 USD` | 不盲目重跑、不在 campaign 中途升级 Docker；诊断未复现持续故障且剩余预算仍能容纳最大 reservation | B6/B7 | 已采纳 |
| 016 | v7 熔断后修复已证明的 metrics teardown race 并重冻 v8，prior `221.772313 USD` | 三个 task 的结构化失败探针完全相同；只接受 fresh exact-label 证明的自然消失，不放宽真正的 exec/identity 故障 | B6/B7 | 已采纳 |
| 017 | v8 因三个 task 的真实 provider response integrity 熔断后退役；修复 task-image-independent auth 与 stopped-container teardown 窗口，用户追加 200 USD 后重冻 v9，prior `281.718702 USD`、cap `600 USD` | 保留三个含糊 stream 的完整保守费用，不把执行缺口或新授权当作重置历史 debit | B6/B7 | 已采纳 |
| 018 | v9 因从结果 worktree 启动导致首题发布后 harness dirty 而 blocked；后继执行先改为 campaign-independent Oracle proof、独立 wire canary、per-slot heavy lock + campaign lease、机械 identity generator | 避免重复十题 Oracle 和整段独占重型锁，同时保持每 slot 重验、一次性 ID、预算与 fail-closed 标准 | B6/B7 | 已采纳 |
| 019 | active pointer 只允许最新 identity；后继 prior 从 terminal state、wire receipt 和完整 settled budget 机械重算，coordinator lease 与每步 heavy lock 分层 | 允许安全恢复和增量执行，同时防止历史 identity、丢失 debit 或并发 worker 被重新执行 | B6/B7 | 已采纳 |
| 020 | v10 保持原 161-slot/600 USD 合同自然熔断；其 Oracle/wire/13 run/费用全部只读，结果提交但不回填为通过 | 第三个不同 task 的真实 provider-integrity 满足冻结 circuit breaker，不能为继续执行改写 identity | B6/B7 | 已采纳 |
| 021 | 后继 schema-v2 机械派生 321 slot，并采用 infra-only a1—a4、第二次同类诊断暂停、第三次同类 task-local 熔断；用户追加 100 USD 后总 cap 700，prior 精确继承 v10 | 允许少量任务形态复现，同时禁止盲目连续付费；历史 schema-v1 仍按原字节只读加载 | B6/B7 | 已采纳 |
