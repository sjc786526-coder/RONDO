# Plan 014：P1 配置化 Provider 的新 Paid Pair 与 M1

> 本计划是 Plan 013 完成后的 B3/M1 执行合同。离线 identity/profile 门禁已完成；v9 已作为不可复用的失败终态
> 保留。用户授权在本计划内对已定位故障执行“离线修复 → fresh exact-wire canary → 新 identity paid pair”的
> 有界迭代，canary 与正式 pair 的累计本地估算费用硬上限为 280 USD。Plan 013 或既有模型诊断的预算与结果不得
> 回填；Plan 014 已发生的 canary 与 v9 费用 `$0.386904` 必须计入该上限。

## 1. 目标

### 最终目标

在不复用旧 v8 identity/result/ledger 的前提下，为配置化 provider profile 建立一套新的双侧 paid pair：先运行
RONDO，再运行 frozen Codex v0.147.0；两侧实际发往上游的 main/Guardian 模型、reasoning effort、价格合同和
失败语义可核验地一致，两个 slot 均 completed 后才计算 M1。

### 完成/验收标准

- 新建唯一 pair/batch/run identity 与新 lock schema；旧 v8 继续保持 failed/blocked，不改写、不复用。
- pair lock 冻结 selected provider profile SHA、endpoint SHA、main/Guardian requested/effective model、effort、价格
  快照、proxy attempt 合同、单侧 5 USD 与双侧 10 USD 上限，不写 raw provider URL 或密钥变量名。
- 新增明确的 public/redacted projection；tracked lock/result 禁止直接序列化 `ProviderProjection.to_dict()` 或
  `RunSpec.to_dict()`，因为通用运行时投影仍含 raw endpoint/display/key env。
- frozen Codex 使用与 bundle source commit 精确一致的最小 `model_catalog_json`，通过主模型条目的
  `auto_review_model_override` 选择 Guardian；RONDO 使用自身 `[auto_review]`。lock/result 同时记录两侧
  requested/effective model，且两者都必须等于 selected profile。
- pair 前先用相同 frozen CLI/request shape 做一次短测 profile canary；每个 upstream request 预留 1 USD、
  main+approval 最多 4 个请求/4 USD，main 与 Guardian 均须
  terminal+valid usage，任一 403/429/5xx、缺 usage 或审批未闭环都停止，不创建/claim pair ledger；预留的 tracked
  identity 保持未消费，若 selected profile 变化则必须新建 lock/IDs，不能改写 v9。
- 任何 completed+usage 的 Guardian 响应之后，产品层 parse failure 不得再产生第二个付费 upstream request；
  无法为 frozen Codex 建立可靠门禁时，本阶段 fail-closed，不运行 paid pair。
- sequence ledger 在 slot 1 claim 时绑定 selected profile canonical SHA；slot 1 启动前、slot 1 结束时、slot 2 claim
  前均重新投影并比较，发生本地配置漂移立即停止。
- paid 执行严格 RONDO -> Codex；slot 1 未 completed、metadata 非 ready、预算停止或 Docker 证据不合格时不运行
  slot 2；只有两侧 completed 才执行 `assess_m1`。
- focused pure/fake/loopback 测试和现有 eval 全套通过；真实执行遵守 build lock、Docker/Windows C: 容量与单任务
  互斥门禁，最终记录本地 estimated cost，并保持 `actual_usd=null`，除非人工提供供应商账单事实。

## 2. 范围

### 允许修改

- `eval/rondo_eval/terminal_bench/` 的 pair identity、sequence ledger、adapter/proxy 投影与结果聚合窄改动。
- `eval/rondo_eval/api_budget_proxy.py` 中 requested/effective Guardian 与 charged-parse-replay 门禁。
- 新 lock、新的 focused tests、必要的实时 WBS/完成记录与一份执行日志。
- 若实现所需，可对 `mydev/` 增加 RONDO 侧稳定 review-id/header 投影；不得改变审批结论语义。

### 不允许修改

- frozen `codex-source-code/`、Codex v0.147.0 bundle、旧 v8 lock/result/ledger/artifact。
- B1/B2 已通过的 oracle/verifier、无关任务、local-model/L2、上游基线和依赖版本。
- 供应商账户、key、远端资源或任何历史测评记录。

## 3. 硬约束

1. **本阶段授权**：Plan 014 canary 与正式 pair 的累计本地估算费用不得超过 280 USD，起始已发生
   `$0.386904`；每轮 canary 仍最多 4 个 upstream request、每请求预留 1 USD，每个正式 pair 两侧各 1 轮、
   每侧最多 5 USD。只有离线分析与修复已经完成并形成干净提交，才可启动下一轮真实执行；不得把项目其余
   600 USD 预算当成本阶段消费目标。
2. **有效条件公平**：main/Guardian requested/effective model、effort、provider endpoint、请求能力和 rate card
   必须双侧一致；模型 catalog 必须绑定 frozen bundle 的 source commit 与投影 SHA，不能读取在线或用户 catalog。
3. **catalog 边界**：只从 git-ignored、只读且 HEAD 等于 frozen bundle manifest `source_commit` 的上游
   `models.json` 选择精确 main/Guardian 条目，输出最小私有 catalog；只允许修改主条目的
   `auto_review_model_override`。原 catalog、冻结源码/二进制、其他模型元数据均不修改，catalog SHA 进入 receipt。
4. **已计费解析重放**：本次固定 Terminal-Bench task 的 pair contract 只允许一个 Guardian logical request。
   proxy 在任何第二个 Guardian downstream request 转发前本地拒绝并停止 run；第一个 logical request 内仍只允许
   operator-confirmed-unbilled transport retry。这样不需要猜测 frozen review id，也不会把第二次独立审批误发上游；
   若任务实际需要第二次审批，本 pair 直接 fail-closed，另行设计通用 correlation contract。
5. **未计费 retry**：继续沿用 Plan 013 proxy 内 `max_attempts<=5`、单 reservation、共享 90 秒 transport budget 与
   operator-confirmed-unbilled 门禁。task/run/pair 仍为零重试。
6. **配置绑定**：sequence ledger 绑定 canonical selected profile，不绑定整个 `rondo.local.toml`；无关 local-model
   编辑不阻断 pair，但 provider/endpoint/model/rate/retry 任何字段漂移必须阻断 slot 2。
7. **费用边界**：canary 每请求预留 1 USD、最多 4 USD；只有 canary 完成后才创建本轮 pair ledger，正式 pair
   的 upstream request 按 5 USD（或 run 剩余额度）预留，单 pair 总额最多 10 USD、每侧最多 5 USD、并发 1。
   每轮启动前必须从所有 Plan 014 durable receipt/ledger 重新计算累计本地估算费用，并确认剩余金额足以覆盖本轮
   最坏 reservation；模糊计费按 reservation 保守结算。第一处失败立即终止该 pair，保留唯一终态，完成根因
   分析与离线修复后才能以新的 lock/pair/batch/run IDs 继续。
8. **历史边界**：新 pair schema/IDs 不兼容 v8；加载旧 lock 或旧 run id 必须明确拒绝，不能自动迁移。
9. **资源门禁**：重型构建只走 `mydev/scripts/with-build-lock.sh`/既有 just 配方；Docker 前后记录 `docker system
   df` 与 Windows C: 实际余量，遵守仓库 40/60GB 增量和 80GiB 余量阈值。
10. **结果语义**：raw provider URL/display name/key env 不进 tracked result；profile/endpoint hash 与 effective model
    是聚合事实。success/failure 两条 tracked result 路径均须保存相同的 profile/endpoint hash；两侧未 completed 时
    M1 只能是 failed/not-run，不能由局部 reward 推成成功。
11. **时限口径**：沿用 Plan 013 monotonic 剩余预算和 body-read timeout；若本阶段要求可强制取消的端到端绝对
    deadline，必须替换或包裹当前 `urllib` transport，不能把 DNS/connect/header 的单次 timeout 夸写成硬取消证明。

## 4. 实施顺序

1. **先闭合公平合同（纯测试）**
   - 将已验证的 frozen catalog override 投影抽成可复用的私有启动合同，记录 source commit、catalog SHA、
     requested/effective model；RONDO 保持显式 `[auto_review]`。
   - 给本 pair 增加 declared `max_guardian_logical_requests=1`，第二个 Guardian request 在 reserve/forward 前停止；
     补两侧一次审批允许、同 logical request 未计费 retry 允许、charged parse replay/第二次审批拒绝的回归。
   - 补 main/Guardian、双侧、catalog source identity/选择/篡改拒绝和 public/redacted projection 回归。
2. **新 identity 与漂移门禁**
   - 新建 lock schema 和唯一 pair/batch/run IDs。
   - 新增 public/redacted provider projection；success/failure 统一携带 profile/endpoint hash，禁止把通用
     `ProviderProjection`/`RunSpec` 原样持久化。
   - sequence ledger 在 slot 1 bind selected profile SHA，slot 2 claim 前重验。
   - M1 改用 profile/endpoint hash、requested/effective 字段比较；保留旧 v8 只读兼容。
3. **离线验收**
   - 跑 focused tests、`just eval-lock`、`just eval-test`；不重复 B1/B2 paid/no-api 已完成证据。
   - 独立审查 secret redaction、预算恢复、旧 ID 拒绝与 pair 顺序。
4. **有界真实执行循环**
   - 确认 active profile/credential、Windows C:、Docker 基线与 build lock；先把 canary 的四个 logical request
     和 4 USD 保守预算做成运行时硬门禁并完成干净提交。
   - 用 source-bound frozen Codex 运行 fresh `main` + `approval` exact-wire canary：只允许
     `main` 与 `main → guardian → main`，每 request 预留 1 USD、总 logical request 上限 4、所有 upstream
     attempt 必须为 1。只有 terminal+valid usage、审批闭环且 fresh profile 精确匹配 v9 lock 才创建 sequence
     ledger 并 claim slot 1；profile、catalog 或 identity 变化时停止，不改写 v9。
   - RONDO slot 1；只在 completed + metadata ready + ledger settled 时运行 Codex slot 2。
   - 两侧 completed 后运行 M1，归档 result/metrics/cost；任何失败保持新 pair 终态并停止。
   - canary 或 pair 失败时，不复用或改写该轮 identity/ledger/result/artifact；先离线定位、补回归、形成干净提交，
     再冻结新的唯一 identity 并从 fresh canary 重新开始。剩余预算不足以覆盖下一轮最坏暴露时暂停。
5. **交付收口**
   - 检查 RONDO 结果中唯一自然 Guardian evidence 的 `E_final/meta` 绑定、两侧预算 settled、pair ledger completed、
     M1 `passed` 且 S2 `verified`；Plan 014 全部 canary + pair 累计本地估算费用不得超过 280 USD，`actual_usd`
     无账单事实时保持 null。
   - 合并真实 public result，更新 Plan 当前状态、WBS 当前事实和一份精炼执行日志；运行受影响测试和结构门禁。
   - 提交后合并本地 main 并推送；保留历史数据，不重写失败终态，不为失败创建第二个 pair。

## 5. 当前状态

### 已完成

- Plan 013 已定义动态 provider/model/rate 与 proxy 内未计费 retry 合同。
- 已确认 frozen Codex v0.147.0 不读取 RONDO `auto_review.model`，但支持
  `model_catalog_json.models[].auto_review_model_override`；无需 proxy 改写或修改冻结源码即可显式选择 Sol Guardian。
- 已确认产品层 completed Guardian parse failure 可发起新的 paid request，必须在本阶段 paid 前处理。
- 真实冻结 CLI 已确认 configured API-key provider 的默认 Guardian 为 Luna/low；注入最小 catalog 后，冻结 Codex
  requested/effective Guardian 均为 Sol/low，RONDO 通过 `[auto_review]` 投影同一条件。
- frozen Codex 与 RONDO 已连续完成 3 轮 Sol/Sol 零重试短测：24/24 个 upstream request 一次成功且 usage valid，
  两侧审批链均为 `main → guardian → main`，本地价卡估算合计 1.234473 USD。早期 Luna 503、Sol 429/缺 usage、
  Terra 26/26 HTTP 403 仍作为波动边界保留；短测不是 paid pair。
- declared single-Guardian gate 已落到 proxy、短测入口和正式 live 路径：首个 Guardian logical request 内可继续
  operator-confirmed-unbilled attempts，第二个 Guardian request 在 reservation/forward 前以本地 409 停止 run。
  focused loopback 覆盖正常 `main → guardian → main`、首请求两次 upstream attempts 和 charged parse replay；
  相关 proxy/diagnostic/provider/live 58/58 通过。
- frozen Codex catalog 已从诊断逻辑提取为正式 source-bound 投影：从 manifest 指定 commit 的 git object 取
  `models.json`，输出最小 `0400` catalog，并由 runner/adapter 绑定 source commit、SHA256、owner、只读性和
  `model_catalog_json` 启动参数。实际 active Sol/Sol profile 投影只含 Sol 且 override 为 Sol；相关 focused
  tests 25/25 通过。
- provider 已有专门的 public result 投影；success 与 claimed failure 统一保存 profile/endpoint hash、模型、
  价卡和 retry 合同，且回归证明不会持久化 raw endpoint、display name、key env 或整份 local config SHA。
- 正式链路审查发现的七项缺陷已完成窄修复：proxy close 会等待所有 handler 收口且关闭后不再开始新 forward；
  public producer 可直接通过 M1；completed 与 M1 都要求精确 `main → guardian → main`；main effort 已进入
  local profile、canonical SHA、adapter、proxy 和 public result；CLI 诊断改为精确消息/命令/请求状态合同、
  显式环境白名单及剩余 retry 配额，并要求 ledger run 未停止、命令先于最终消息、唯一 `turn.completed` 且无
  `turn.failed`。真实 public producer→pair ledger→M1 集成回归和完整 eval 323/323 通过。
- 新 schema-v2 lock 已冻结唯一 `p1-fix-git-pair-v9` / `p1-fix-git-b4-m1-v1` 与两侧 run ID、Sol/medium
  main、Sol/low Guardian、价卡/retry、5 USD 单侧/10 USD pair 上限和 source-bound frozen catalog SHA；lock
  不包含 raw endpoint、display name 或 key env。v8 只能通过显式 legacy 入口只读加载，不能创建或 claim 新账本。
- pair sequence ledger schema v5 在 slot 1 claim 绑定 selected profile/endpoint SHA；正式入口在首次 claim、completed
  发布前、durable publication 收口及 slot 2 新进程 claim 时重投影本地 profile。public success/failure 直接使用 lock
  的同一 redacted profile，M1 对两侧 result、lock 与 ledger 做精确三方比较；focused tests 与完整 eval 325/325 通过。
- canary 的总 logical-request 门禁已落地并提交为 `f7c21f8`：source-bound frozen Codex 只允许
  `main` 与 `main → guardian → main`，分阶段硬 cap 为 1+3 USD，内部与外层 retry 均为 0；完整 eval
  328/328 通过。fresh Sol/Sol canary 随后 4/4 请求均一次成功、usage valid，审批命令和终态精确闭环，
  本地估算 `$0.225706`。
- 唯一 v9 pair 已执行 RONDO slot 1 并收敛为 `infra_failed/blocked`：6 个 Sol/medium main 请求均一次成功、
  usage valid，本地估算 `$0.161198`、无 reservation；自然 Guardian `E_final` 已生成且为 Sol/low、schema/source
  正确，但 review session 在请求进入 budget proxy 前以 HTTP 429 `session_error` fail-closed。Codex slot 2 与 M1
  按计划未运行，这份未绑定真实 Guardian usage 的 evidence 不算可用 S2。

### 当前工作

- 已从 `29cfab6` 创建独立 `0811-plan014-b3m1-closure` 工作树。v9 identity/result/ledger 保持唯一失败终态，
  不重跑、不改写。
- 已定位 v9 根因：SSE relay 先向 RONDO 暴露 `response.completed`、后结算主请求，Guardian 在该窗口因主请求仍占用
  全部保守 reservation 而得到本地 `budget_stopped` 429；上游未收到 Guardian 请求。proxy 现按完整 SSE event
  缓冲，先结算与写 metadata，再暴露终态。结算顺序及即时 `main → guardian` 回环回归均通过，proxy 46/46、
  `eval-lock` 85 packages 通过。
- 当前先提交根因修复，再冻结新 identity；随后通过当前 Sol/medium + Sol/low profile 的 fresh exact-wire canary 和
  Docker/Windows C:/build-lock 门禁，按 RONDO → frozen Codex 执行。Plan 014 累计费用从 `$0.386904` 起算。
- 根因修复已提交为 `22ddcdc`。新 schema-v2 v3 lock 冻结 `p1-fix-git-pair-v10`、
  `p1-fix-git-b4-m1-v2`、RONDO run `20260811-140000000-tb-rondo-r1` 与 frozen Codex run
  `20260811-140000001-tb-codex-r1`；v9 v2 lock 保持原文件，并新增显式只读隔离回归。identity/profile focused
  tests 59/59 与 `eval-lock` 85 packages 通过，待完整 eval 门禁和 identity 提交。

### 阻塞项

- v9 已消费并 blocked；任何后续正式执行都必须新建 lock/IDs，并重新通过 fresh canary 与资源/预算门。
- official profile 若无独立 credential，只能保持未选择状态，不挪用中转 key。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 状态 |
|---|---|---|---|
| 001 | 新 pair/lock/ledger，不复用 v8 | v8 identity 已消费且有效 Guardian 条件改变 | 已采纳 |
| 002 | requested/effective Guardian 分开冻结 | frozen Codex 配置能力与 RONDO 不同，实际公平条件仍须一致 | 已采纳 |
| 003 | charged parse retry 未闭合前禁止 paid | 用户只允许未计费失败重试，5 USD cap 不能替代语义门禁 | 已采纳 |
| 004 | sequence 绑定 selected profile SHA | 防止 slot 间 provider/model/rate 漂移，又不受无关本地配置影响 | 已采纳 |
| 005 | raw endpoint 不进 tracked result | 保留本机供应商切换边界，公平比较使用 endpoint/profile hash | 已采纳 |
| 006 | 新 lock/result 使用专门的 public/redacted projection | 通用运行时 `to_dict()` 含本机 endpoint/display/key env，不可直接持久化 | 已采纳 |
| 007 | paid pair 前增加最多 4 USD exact-wire short canary | 早期 relay 同时出现成功与 403/429/503，先验证当下稳定性可避免消费 pair identity | 已采纳 |
| 008 | frozen Codex 用 source-bound 最小 model catalog 选择 Guardian | 这是冻结源码已有启动能力，可让 requested/effective 都为 Sol，无需请求改写 | 已采纳 |
| 009 | 固定单审批 task 声明 Guardian logical request 上限为 1 | 在不知道 frozen review id 的情况下，仍可在任何 charged parse replay 上游发送前可靠停止 | 已采纳 |
| 010 | 短测每 upstream request 预留 1 USD，正式/大请求按 5 USD | 兼顾高频小探针与正式任务 fail-closed 暴露上限 | 已采纳 |
| 011 | completed/M1 必须消费精确审批序列，main effort 与 Guardian effort 同级冻结 | 防止主请求或 effort 漂移产生可发布的假成功 | 已采纳 |
| 012 | CLI 诊断只接受未停止 ledger、单一最终消息、成对且先于消息的固定审批命令和成功 turn 终态 | 历史 `expected_command=false` 收据只能保留为稳定性事实，不能充当新门禁证据 | 已采纳 |
| 013 | Plan 014 canary 使用 source-bound frozen Codex 且硬限制四个 logical request、零 retry、4 USD | 仅靠事后序列检查不能证明 14 USD 总预算不会先超限再失败 | 已采纳 |
| 014 | v9 任一正式侧失败后保留唯一终态并停止，不创建替代 pair | 防止为追求绿结果连续消费预算或破坏 identity 一次性语义 | 已采纳 |
| 015 | v9 RONDO Guardian 失败后不把已生成但未绑定 usage 的 `E_final` 计为 S2 | 请求未进入预算 metadata，不能证明审批模型真实完成 | 已采纳 |
| 016 | v9 后允许在 280 USD 累计硬上限内按“修复后新 identity”有界迭代 | 普通运行失败不应盲重跑，也不应阻止已定位修复后的 B3/M1 闭环 | 已采纳 |
| 017 | v10 使用新的 v3 lock、batch 与两条 run ID，v9 v2 lock 只读保留 | 运行失败身份不可复用，profile/bundle 未变化时无需重建二进制 | 已采纳 |
