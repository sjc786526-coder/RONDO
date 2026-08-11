# Plan 014：P1 配置化 Provider 的新 Paid Pair 与 M1

> 本计划已进入离线落地阶段，是 Plan 013 完成后的下一阶段执行合同。
> 离线实现不产生 API/Docker 影响；正式 canary、paid pair 与 Docker 执行前仍须按本计划范围单独授权，不回填
> Plan 013 或模型诊断的预算与结果。

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
  terminal+valid usage，任一 403/429/5xx、缺 usage 或审批未闭环都停止，不创建/claim pair identity。
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

1. **新授权**：Plan 014 开始 paid/Docker 前一次性说明短测 profile canary 最多 4 个 upstream request、每请求
   1 USD，pair 两侧各 1 轮各 5 USD，合计最坏 14 USD，以及 Docker 与宿主影响并取得授权。Plan 013 与模型
   诊断授权不能自动扩展到本阶段。
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
7. **费用边界**：canary 每请求预留 1 USD、最多 4 USD；只有 canary 完成后才创建 pair ledger，正式 pair 的
   upstream request 按 5 USD（或 run 剩余额度）预留，pair 总额最多 10 USD、每侧最多 5 USD、并发 1。模糊
   计费按 reservation 保守结算，第一处失败立即终止后续真实请求。
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
4. **一次真实执行**
   - 获得新授权并确认候选 active profile/credential、Windows C:、Docker 基线与 build lock。
   - 先运行与 frozen CLI 完全同 shape 的 main+Guardian canary；只有 terminal+valid usage 且审批闭环才冻结
     selected profile 并创建新 pair identity。Terra 在持续 403 的访问问题解除前不作为候选。
   - RONDO slot 1；只在 completed + metadata ready + ledger settled 时运行 Codex slot 2。
   - 两侧 completed 后运行 M1，归档 result/metrics/cost；任何失败保持新 pair 终态并停止。

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

### 当前工作

- 正在离线实现 catalog/source identity 公平投影、新 pair identity 与 profile drift 门禁。正式 exact-wire canary、
  Docker 和 paid pair 尚未获得本计划自己的范围授权，也未运行；
  既有 3 轮稳定性诊断只用于选定 Sol/Sol 候选，不能回填为 pair 结果。

### 阻塞项

- paid 前必须完成 catalog/source identity、新 pair/profile drift 与 public/redacted result 的剩余 focused 门禁。
- active Sol/Sol profile 在正式 pair 前仍须通过本计划自己的 fresh exact-wire canary；Terra 的持续 403 需供应商侧
  访问能力变化后再考虑。
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
