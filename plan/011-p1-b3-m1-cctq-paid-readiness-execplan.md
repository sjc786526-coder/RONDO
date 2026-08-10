# P1 B3/M1 configurable provider paid readiness ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

保留已失败且不可复用的 Plan 010 v6 pair，在新的 v7 pair 中恢复供应商无关、配置驱动的 OpenAI-compatible
上游：ignored `rondo.local.toml` 决定 credential-free HTTPS `base_url`，budget proxy 通用拼接 `/responses`。
保留既有 role 投影、预算、Docker/watchdog、公平与 publication 边界；完成相关 pure/fake/loopback 门禁后停止，
不运行 Docker、真实 API、Cargo 或模型，并申请新的真实 API 批量授权。

### 完成/验收标准

- ignored `rondo.local.toml` 保存用户当前选择的 OpenAI-compatible provider；受跟踪 example 只提供保留域名的通用
  HTTPS 示例。配置内不写 key，源码/lock/template 不识别任何具体中转供应商。
- budget proxy 接受任意合法的 credential-free HTTPS base URL，去掉尾斜杠后通用拼接 `/responses`；HTTP、query、
  fragment、userinfo、非法端口/控制字符一律在请求/费用发生前拒绝，redirect 仍不跟随。
- main/Guardian declared role、host-only real key、ephemeral downstream key、redirect/retry/hosted-tool 拒绝和 usage
  预算行为不倒退。
- Luna 计价继续使用 OpenAI 官方 Standard rates：input 0.20、cached input 0.02、output 1.20 USD/百万 token；
  5 USD/run、v7 两槽最多 10 USD、底层 ledger 20 USD hard cap 与最大 reservation 0.755400 USD 不变。
- 未来结果只在 `spent_usd == 0` 且不存在未结算 reservation 时写 `actual_usd=0.0`；存在 reservation 或非零
  本地计价时写 `actual_usd=null`。已有 v6 JSONL、pair/budget ledger 和私有 artifact 不改写。
- 新 pair `p1-fix-git-pair-v7` / batch `p1-fix-git-b3-m1-v2` 固定 `terminal-bench/fix-git`、RONDO slot 1 →
  Codex slot 2、各一轮、零重试；模型均为 `gpt-5.6-luna`，Guardian effort `low`。tracked lock 不冻结域名，M1
  使用两侧结果中既有的 `provider_base_url` 与 `provider_config_sha256` 拒绝配置漂移。
- 只运行 base URL、role、预算、费用口径和 v7 identity 的相关 pure/fake/loopback 测试；最终输出唯一 canonical
  命令与预算后停在新的真实 API 授权门。不得把 readiness 表述为 B3/M1 通过。

## 2. 范围

### 允许修改

- ignored common-root `rondo.local.toml` 的非密钥 provider base URL。
- `rondo.local.example.toml`、`eval/locks/p1-terminal-bench-pair-v1.json`。
- `eval/rondo_eval/api_budget_proxy.py`、`eval/rondo_eval/terminal_bench/{__main__,pair,results}.py` 中与通用 HTTPS
  endpoint、v7 identity、future `actual_usd` 直接相关的最小代码。
- 上述行为的现有 focused tests；Plan 010 当前状态纠正、实时 WBS、Plan 011、精炼实施日志。

### 不允许修改

- v6 的 tracked JSONL 行、ignored pair/budget ledger、run artifact、watchdog/metrics 或 results commit。
- `mydev/`、冻结二进制、task/image、Harbor、Docker/watchdog、ArtifactWriter/ledger schema、证据体系、L1/L2。
- 新 provider 框架、审计层、数据库、重试机制或与本次 readiness 无关的重构。

### 不允许读取/查看

- `.env.local` 内容；只允许严格 loader 静默确认目标变量存在且非空，不得打印、复制或记录值。
- 项目外个人文件、模型权重、来源不明 Docker 对象内容或其他仓库。

## 3. 硬约束

1. **先计划后实现**：本文件落地后才修改生产代码和配置。
2. **配置驱动上游**：生产 proxy 只从 `rondo.local.toml` 接受无凭据 HTTPS base URL 并拼接 `/responses`；不在
   Python、tracked template 或 pair lock 中识别供应商域名。loopback override 仅供既有 fake 测试。
3. **代理环境**：未来 canonical shell 继续清除大小写 HTTP(S)/ALL proxy，只设置
   `NO_PROXY/no_proxy=127.0.0.1,localhost`；当前配置的 provider 已由用户提供的无认证探测验证可直连。
4. **费用边界**：沿用官方 Luna 价格和 5/10/20 USD 上限；usage 缺失/非法及未结算 reservation 保持
   fail-closed，不把本地 estimate 冒充账单实扣。
5. **v6 append-only**：不得修改或复用 v6；v7 使用全新 pair/batch/run IDs。当前 v7 readiness 不能创建真实
   pair/budget/run/metrics/results 数据。
6. **严格串行**：未来真实命令固定 RONDO→Codex，首侧失败立即停止，零重试；M1 仅在双侧 completed 后运行。
7. **无外部执行**：本阶段禁止 Docker、真实 API、Cargo、本地模型、pull/build、发布或产生费用。
8. **轻量验证**：只跑直接相关门禁，不扩 schema、账本、审计或理论性边界。

## 4. 软性建议

- 把原 `_official_responses_endpoint` 改为小型通用 HTTPS validator，不引入 provider 类型或 allowlist。
- provider 配置表名继续使用现有 `openai` 协议适配标识；真实上游只来自 ignored 配置，结果中的 base URL 与
  config SHA 用于两侧公平比较。
- `actual_usd` 只调整 record producer 的派生条件和一条 focused regression，不迁移历史记录。
- v7 尽量只替换 v6 identity/base URL，其余公平字段逐字节保持。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- Plan 010 readiness 和 append-only v6 result 已 no-ff 合并并推送；local/origin/remote main 均为
  `2e16e90e01539667310f79a6f15ef7c277ff8377`，主工作区 clean；完成分支已转入 `zz-done/`。
- 新 worktree/branch `0810-plan011-cctq-b3-paid-readiness` 从上述 clean main 创建。
- 已重读根 `AGENTS.md`、plan example、Plan 010 与当前 WBS；严格 loader 无输出确认现有 key 可用。
- 当前用户选择的 provider 已在 ignored `rondo.local.toml` 配置；受跟踪源码、template 与 pair lock 不记录其域名。
  OpenAI 官方 Luna 页面确认价格仍为 0.20/0.02/1.20 USD/百万 token。
- v6 根因已复核为 ignored config、tracked pair lock 和 proxy validator 均错误固定官方 OpenAI endpoint；清除
  ambient proxy 只让该错误配置表现为超时，不是未来命令应保留宿主 proxy 的理由。
- proxy、v7 identity、通用 template 与 future `actual_usd` 已完成最小修改；最终 focused
  pure/fake/loopback 87/87。pair lock SHA-256 为
  `b9e38f51de548d2787ca80114b8df8eaaadc3138b05b3928a508eb5434bda29b`。

### 当前工作

- 无；readiness 实现、focused 门禁、实时文档、实施日志和唯一 canonical 命令均已完成。

### 后续计划

1. 停在授权门；只有取得新的单独真实 API 批量授权后才执行日志中的 canonical 命令。

### 阻塞项

- 无实现阻塞；真实 v7 B3/M1 受新的单独 API 批量授权门阻断。

### 当前验收状态

- v6：failed/blocked，完整保留，不可复用。
- v7：readiness 已完成，未创建 ledger/run，Docker/API/Cargo/model 均未运行，等待新的单独 API 批量授权。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | provider 由 ignored 配置决定；源码只实现通用 OpenAI-compatible HTTPS endpoint | 可切换官方或中转站，不新建 provider 架构 | config、proxy、pair | 已采纳 |
| 002 | canonical shell 继续清除 ambient proxy | 当前配置的 provider 可直连，减少不必要网络变量 | future command | 已采纳 |
| 003 | v6 原样保留，v7 使用新 identity | 遵守 append-only 与零重试，不把配置修正冒充同一次 run | pair/results | 已采纳 |
| 004 | reservation 存在时 future `actual_usd=null` | 本地未结算预留不是已确认 0 账单 | results | 已采纳 |
| 005 | tracked pair 不冻结域名，M1 比较两侧 base URL 与 config SHA | 复用已有公平字段，避免供应商审计体系 | pair、M1 | 已采纳 |
