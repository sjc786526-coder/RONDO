# Plan 014：P1 配置化 Provider 的新 Paid Pair 与 M1

> 本计划处于待落地状态，是 Plan 013 完成后的下一阶段执行合同。
> 执行前必须重新核对代码/环境，并取得新的真实 API 与 Docker 授权；不得沿用 Plan 013 的 10 USD 授权。

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
- frozen Codex 不能读取 RONDO `auto_review.model` 的差异必须显式建模；两侧 effective Guardian 条件相同，
  requested/effective 不同则如实记录，不得伪装成相同配置。
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

1. **新授权**：Plan 014 开始 paid/Docker 前一次性说明目标 profile、两侧各 1 轮、最坏 10 USD、Docker 与宿主
   影响并取得授权。Plan 013 探针授权不能自动扩展到本阶段。
2. **有效条件公平**：main/Guardian effective model、effort、provider endpoint、请求能力和 rate card 必须双侧一致。
   frozen Codex requested Guardian 若不同，lock/result 同时记录 requested 与 effective，不把改写隐藏为原生能力。
3. **改写边界**：如需把 frozen Codex 的固定 Guardian model 改为 selected effective model，只允许 proxy 对
   `side=codex + verified Guardian schema + exact frozen requested model` 做单字段改写；持久化改写前后 body hash、
   requested/effective model 与原因，其他 body/header 漂移全部拒绝。RONDO 不走该兼容分支。
4. **已计费解析重放**：先用源码与 loopback trace 确认 Guardian retry 的稳定关联字段。门禁必须能区分“同一
   review 的 charged parse retry”和“后续独立审批”；不能可靠区分时不得用全局次数猜测，也不得 paid。
5. **未计费 retry**：继续沿用 Plan 013 proxy 内 `max_attempts<=5`、单 reservation、共享 90 秒 transport budget 与
   operator-confirmed-unbilled 门禁。task/run/pair 仍为零重试。
6. **配置绑定**：sequence ledger 绑定 canonical selected profile，不绑定整个 `rondo.local.toml`；无关 local-model
   编辑不阻断 pair，但 provider/endpoint/model/rate/retry 任何字段漂移必须阻断 slot 2。
7. **费用边界**：新 ledger 总额最多 10 USD、每侧最多 5 USD、并发 1。模糊计费按 reservation 保守结算，
   第一处失败立即终止后续真实请求。
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
   - 从 frozen/RONDO Guardian 请求中提取 requested/effective model 与 stable review correlation evidence。
   - 选定 charged parse retry 的可靠门禁；若证据不足，记录 blocker 并停止本计划。
   - 补 main/Guardian、双侧、模型改写允许/拒绝、charged replay 拒绝的 loopback 回归。
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
   - 获得新授权并确认 active profile/credential、Windows C:、Docker 基线与 build lock。
   - RONDO slot 1；只在 completed + metadata ready + ledger settled 时运行 Codex slot 2。
   - 两侧 completed 后运行 M1，归档 result/metrics/cost；任何失败保持新 pair 终态并停止。

## 5. 当前状态

### 已完成

- Plan 013 已定义动态 provider/model/rate 与 proxy 内未计费 retry 合同。
- 已确认 frozen Codex v0.147.0 不读取 RONDO `auto_review.model`；旧 v8 的 Luna 503 不能作为重试复用。
- 已确认产品层 completed Guardian parse failure 可发起新的 paid request，必须在本阶段 paid 前处理。

### 当前工作

- 待 Plan 013 完成交付后启动。本计划尚未获得真实 API/Docker 授权，未创建新 pair lock/ledger，未运行付费请求。

### 阻塞项

- 必须先证明 charged parse retry 的跨 frozen/RONDO 可靠关联门禁；无法证明时属于真实阻塞，不以次数上限替代。
- official profile 若无独立 credential，只能选择已验证可用的 active relay profile，不挪用中转 key。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 状态 |
|---|---|---|---|
| 001 | 新 pair/lock/ledger，不复用 v8 | v8 identity 已消费且有效 Guardian 条件改变 | 已采纳 |
| 002 | requested/effective Guardian 分开冻结 | frozen Codex 配置能力与 RONDO 不同，实际公平条件仍须一致 | 已采纳 |
| 003 | charged parse retry 未闭合前禁止 paid | 用户只允许未计费失败重试，5 USD cap 不能替代语义门禁 | 已采纳 |
| 004 | sequence 绑定 selected profile SHA | 防止 slot 间 provider/model/rate 漂移，又不受无关本地配置影响 | 已采纳 |
| 005 | raw endpoint 不进 tracked result | 保留本机供应商切换边界，公平比较使用 endpoint/profile hash | 已采纳 |
| 006 | 新 lock/result 使用专门的 public/redacted projection | 通用运行时 `to_dict()` 含本机 endpoint/display/key env，不可直接持久化 | 已采纳 |
