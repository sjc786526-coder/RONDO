# Plan 013：P1 本地 Provider/Model Profile 与未计费重试

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

把 P1 真实 API 测评链的供应商、Responses base URL、主模型、Guardian 模型及对应官方计价从生产代码中的
固定值改为 common-root ignored `rondo.local.toml` 中的可切换 profile；同时在预算代理内提供最多 5 次的
“明确未计费失败”重试，让中转站的临时非 2xx 故障不再必然中止主模型或审批模型请求。

本任务只打通配置、预算代理、轻量 provider probe 和相关测试。旧 v8 pair/result/ledger 保持历史事实；新的
Terminal-Bench paid pair、B3/M1 和 Docker 运行属于下一阶段，不在本计划内执行。

### 完成/验收标准

- active provider、provider base URL、API key 环境变量名、main/Guardian model 和模型 Standard 计价的配置源
  均为 `rondo.local.toml`；生产 eval 代码不再以 Sol/Terra/Luna 名称或供应商域名分支。真实运行选中的 effective
  model、价卡快照及 profile/endpoint hash 可作为测评事实进入 tracked result/lock，但 raw endpoint 与本机变量名不进入。
- `rondo.local.example.toml` 提供不含真实供应商域名的 provider/model profile 合同；ignored 本地配置可通过
  `active_provider`、`main_model`、`guardian_model` 三个短字段切换中转/官方与 Sol/Terra/Luna。
- ProviderProjection/RunSpec、预算代理、provider probe 和 RONDO adapter 接受配置投影并 fail-closed 校验；
  v8 pair lock 因冻结旧 identity 继续拒绝不同配置，不被静默复用。
- 预算代理收到的每个 main/Guardian downstream Responses 请求最多 5 个 upstream attempts；Harbor、task、
  run 和 pair 仍保持零重试，proxy 继续拒绝下游 retry header，任何 SDK/Guardian 内建 retry 不得绕过它增加
  同一请求的 upstream attempts。
- 只有 provider profile 明确允许的非 2xx，且完整有界错误响应不含 terminal/usage 证据时，才记为未计费并
  重试；2xx 缺 usage、流中断、timeout、disconnect、无法完整分类的响应均不重试并保守结算。
- 全部 attempts 共用一个 request id、一个 reservation 和一个 90 秒 transport budget；成功只按一次合法 usage 结算，未计费重试耗尽以
  `0 USD`、`usage_valid=false`、明确 stop reason 收束，任何模糊失败仍最多扣除原 reservation。
- focused pure/fake/loopback 测试覆盖动态 provider/model/price、main/Guardian、1~5 attempts、成功收束、
  未计费耗尽、模糊失败禁止重试、预算/metadata 持久化和 secret redaction；`just eval-lock` 通过。
- 复用现有 `.env.local` 密钥做最小真实 provider probe；总授权上限 10 USD，串行执行，实际成功后不为了用满
  额度继续请求。结果只记录去敏 status/attempt/usage/本地计价，供应商实际账单未知时 `actual_usd` 保持 null。
- tracked result 不保存 raw provider base URL/供应商 display name，改存 selected profile/endpoint hash；更新一份
  精炼 `agent_log`、受影响的实时 WBS/示例配置，并新增下一阶段 execplan，明确新 pair、冻结 Codex Guardian
  requested/effective 公平合同、B3/M1、Docker 门禁和新的付费授权边界。

## 2. 范围

### 允许修改

- `eval/rondo_eval/config.py`、`contracts.py`、`api_budget_proxy.py`、`provider_probe.py`。
- P1 Terminal-Bench adapter/runner/pair/result 中仅与动态 provider/model projection 直接相关的窄改动。
- `eval/tests/` 中对应的 focused 测试；必要时调整旧测试 fixture，不新增重型测试体系。
- `rondo.local.example.toml`、`rondo.secrets.example.env`、ignored common-root `rondo.local.toml`。
- `plan/013-*`、下一阶段 execplan、`doc/WBS.md`、必要的 `doc/WBS-COMPLETED.md` 与一份 `agent_log`。

### 不允许修改

- `mydev/` 产品 Rust 代码、`codex-source-code/` 冻结上游、现有二进制/runtime bundle、Cargo 依赖和锁。
- v6/v7/v8 的 pair identity、append-only result、ledger、artifact 或历史日志。
- B1/B2、oracle/verifier、Docker supervisor、local llama.cpp/L2 实现及无关 eval 轨道。
- 远端资源、供应商账户/额度设置、API key、宿主机配置或项目外文件。

### 不允许读取/查看

- `.env.local` 内容、密钥明文、供应商后台账单或任何项目外个人配置。
- `eval-data/` 中与本任务 provider probe/既有状态核对无关的原始内容。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **密钥边界**：复用 common-root `.env.local` 的现有 key；只允许严格 loader 静默读取 active provider 所需
   变量并注入宿主 loopback proxy。不得创建、改写、打印、搜索、复制或记录 key。
2. **本地配置边界**：真实供应商 display name、域名/base URL、API key 环境变量选择，以及模型/价卡的配置源
   只在 ignored `rondo.local.toml`。tracked example 只给占位 profile；运行后允许 tracked result/lock 保存 effective
   model、官方价卡快照与 profile/endpoint hash 作为测评事实，但不保存 raw endpoint/display/key env；历史事实不改写。
3. **动态但严格**：provider/model profile 名、模型 ID、URL、Decimal 价格、日期、官方 source URL、reasoning
   effort、attempt 上限、重试状态码均有界校验；未知字段、缺字段、重复语义、credential URL、redirect 均拒绝。
4. **重试层级**：`max_attempts` 表示包括首次调用在内的总 upstream attempts，范围 1~5。不得打开 Codex SDK、
   Harbor、Terminal-Bench task、run 或 pair 的 retry；不得重新执行已经成功的逻辑请求或工具调用。
5. **未计费判定**：仅 provider profile 列出的非 2xx 状态可进入判定；响应必须在大小上限内完整读取，且不得
   出现 completed/terminal response 或任何 usage。HTTP 2xx、SSE 已开始、读取不完整、timeout/disconnect、
   解析不明、invalid usage 都属于计费不确定，禁止重试。该结论是 operator/provider profile 提供的操作性
   billing contract 加响应证据，不是仅凭状态码推断，也不冒充供应商发票证明。
6. **预算单调性**：一个 downstream request 只 reserve 一次；reservation 在所有 attempts 完成前保持 active。
   成功按配置价格向上取整结算一次；明确未计费耗尽结算 0 并停止 run；进程中断仍按全 reservation 恢复。
7. **费用上限**：本计划新真实 API 总账本上限为 10 USD，任何单 request reservation 不超过 5 USD，串行、
   并发 1。已有历史本地估算不挪入或抵扣本计划 ledger；不声称本地估算等于供应商实扣。
8. **共享时限**：同一 logical downstream request 的全部 1~5 attempts 与 backoff 共用一个 90 秒 transport
   budget，不给每个 attempt 重置 90 秒。body read 会按 monotonic 剩余量收紧 socket timeout；Python `urllib`
   的 DNS/connect/header 阶段只能得到剩余量作为单次操作 timeout，无法宣称可强制取消的端到端绝对 deadline。
9. **真实测试停止条件**：配置/key/price 漂移、redirect、active reservation、usage 无效、预算异常或非预期
   计费证据立即停止。一次请求成功后不重复；重试只消费该请求剩余的未计费 attempt 数。
10. **资源边界**：本计划不运行 Docker、Cargo、本地模型、训练、批量数据集或发布；Python eval 测试只走现有
   `just eval-test`/focused 入口，使用项目内 `eval-data/uv-cache`。
11. **历史与公平**：旧 v8 继续 failed/blocked。当前任务不通过 proxy 偷换 frozen Codex Guardian 后冒充 v8；
    requested/effective Guardian 差异和新双侧公平 identity 必须留给下一阶段的新 pair。
12. **已计费 parse retry 边界**：RONDO/frozen Codex Guardian 产品层可能在已完成但解析失败后发起新的 review
    request；本计划不修改两侧产品代码，也不把它误写成已解决。本计划只保证 proxy 对其收到的每个 downstream
    请求内部，非 2xx upstream attempts 遵守未计费门禁；下一阶段必须在双侧公平合同中统一处理 charged parse retry。

## 4. 软性建议

- 把 paid eval profile 与现有 DeepSeek/Qwen/local-model 配置分区，减少无关 schema 迁移。
- 价格使用字符串 Decimal，模型 profile 同时保存 snapshot date/source URL；预算 reservation 继续以 5 USD
  上界保护，不根据低报价缩小安全余量。
- retry metadata 只保留 attempt count、最终状态和有界分类，不保存上游错误正文。
- 真实 probe 优先使用极小 non-stream 请求，再验证一个 Guardian 形状；只在确有必要时验证 streaming。
- 下一阶段先解决 frozen Codex Guardian 的 requested/effective 公平合同，再冻结新 pair，避免重复制造失败 ID。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已读取 P1 交接日志、README、当前 WBS、Plan 012、配置/合同/预算代理/provider probe/adapter 与相关测试。
- main 干净且与 `origin/main` 同步；已从 `c893322` 创建独立 worktree/分支
  `0810-p1-provider-model-config`。
- 已按凭据技能静默确认 common-root `.env.local` 为普通文件、权限 `0600` 且现有 `OPENAI_API_KEY` 非空；
  用户明确选择复用，不创建新 key。
- OpenAI Docs 已核对 2026-08-11 当前 Sol/Terra/Luna Standard token 价格、272k 长上下文倍率、缓存写入倍率及
  Responses endpoint 支持；实际配置把基础价格和非线性计价规则一起放入 ignored 本地 model profile。
- paid eval 动态 provider/model/price profile 已接通 config、RunSpec、预算代理、probe 与 Terminal-Bench adapter/result；
  active provider/main/Guardian 三个短字段可独立切换，tracked success result 不落 raw endpoint/display/key env。
- proxy 已实现 main/Guardian 共用的 1~5 operator-confirmed-unbilled attempts、单 reservation、保守未知结算、
  crash recovery 和去敏 attempt/settlement metadata；产品层 charged Guardian parse retry 明确保留给 Plan 014。
- 已完成纯/fake/loopback 定向回归；最新完整 eval 门禁结果见本批 `agent_log`。
- 真实 v1 在开发沙箱内得到 `upstream_status=0` 并保守结算 `$5.000000`；沙箱 DNS 阻断来自执行环境观测，ledger
  本身只证明未取得 HTTP status/usage，不能证明上游是否收到字节。随后经授权的 v2 中，Sol main 首次完成并按
  usage 本地估算 `$0.022105`；Sol Guardian 首次返回无法明确未计费的 HTTP 502，未重试并保守结算余额
  `$4.977895`。两份本地 ledger 合计上限 10 USD，`actual_usd=null`，没有继续发真实请求。

### 当前工作

- 代码、测试、真实 probe 与文档收口完成；保留在独立 worktree，未改写 v8 或启动 Plan 014 paid pair。

### 后续计划

1. 用户验收本 worktree 交付后，再决定是否提交、合并和推送；本任务未获授权时不自行改变 main/远端。
2. 下一阶段按 Plan 014 先闭合 charged Guardian parse retry 与双侧 effective 条件，再申请新的 paid/Docker 授权。

### 阻塞项

- Plan 013 无阻塞。OpenAI official profile 若缺少独立 credential，会在被选择时 fail-closed；本批只复用 active
  relay key。Plan 014 的 charged parse retry 公平门禁仍是下一阶段 blocker。

### 当前验收状态

- 动态配置、价卡、未计费 retry、失败回执与相关 Terminal-Bench 投影已落地；定向与完整 eval 门禁通过。
- 真实 API 只执行 v1/v2 两个有界 ledger：v2 main completed，Guardian 502 后 fail-closed；B3、Codex slot 2、M1、
  Docker、Cargo 和本地模型均未运行。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 新增独立 paid eval provider/model profile，而不是继续扩张固定 `[providers.openai]` | 保留 DeepSeek/Qwen/local-model 现状，同时移除 P1 production 硬编码 | config/contracts/probe | 已采纳 |
| 002 | RunSpec `max_retries=0` 保持不变，新增 proxy 内 `max_attempts<=5` | 避免 task/tool/pair 重放，只重发同一尚未计费的 API 请求 | proxy/ledger | 已采纳 |
| 003 | 配置声明的非 2xx + 无 terminal/usage 才可视为未计费；transport 模糊失败不重试 | 官方文档没有给出可把 timeout/断连普遍视为未计费的保证 | retry/budget | 已采纳 |
| 004 | 一个 reservation 覆盖所有 attempts，未计费耗尽以 0 USD 显式停止 | 保持预算单调、进程恢复保守，同时记录无计费证据 | ledger/metadata | 已采纳 |
| 005 | 本计划只做轻量真实 provider probe，B3/M1 新 pair 留给下一计划 | 当前 v8 identity 已消费且 frozen Codex Guardian 需要新的公平合同 | scope/WBS | 已采纳 |
| 006 | tracked result 不保存 raw base URL/display/key env；允许保存 effective model、价卡快照与 profile/endpoint hash | 配置源保持本地，运行后的可复核条件仍是测评事实 | results/pair | 已采纳 |
| 007 | 全部 upstream attempts 共用 90 秒 transport budget，并披露 urllib DNS/header 限制 | 防止主动把旧时限放大五倍，同时不夸大标准库可取消能力 | proxy/retry | 已采纳 |
| 008 | 长上下文 threshold/multiplier 与 cache-write multiplier 纳入 ModelPricing/profile SHA | 不把当前三模型的非线性价规误套到未来模型 | config/contracts/proxy | 已采纳 |
