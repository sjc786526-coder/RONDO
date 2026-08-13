# P1 B3/M1 provider and verifier recovery ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 若真实 provider、Docker 或预算证据未满足门禁，停止在对应阶段，不以重试绕过失败。

## 1. 目标

### 最终目标

保留 Plan 011 v7 的失败终态，在不放宽既有 Docker、watchdog、密钥和预算边界的前提下，修复两个直接业务阻塞：

1. OpenAI-compatible 上游请求在 Harbor 900 秒前有界结束，SSE 在合法 `response.completed` 与 usage 到达后即可结算，
   timeout/usage 缺失也必须落明确的已结算失败；
2. frozen `terminal-bench/fix-git` verifier 通过 Harbor 的 verifier user/env 以 root + `HOME=/root` 执行，
   RONDO/Codex Agent 继续固定 UID/GID 1000:1000。

通过离线、Docker 和小额 provider 探针后，才冻结并执行新的 paid pair：每个 pair 为 RONDO 一次后 Codex 一次、
零重试，最后仅在双侧 completed 时运行既有 `assess_m1`。只有明确基础设施故障修复后才允许第二个 pair。

### 完成/验收标准

- v7 readiness/results 已合并推送，`main == origin/main`，v7 ledger、artifact 和 append-only result 不改写、不复用。
- proxy 上游 timeout 固定为 60～120 秒且小于 Agent 的 900 秒；timeout、断连、非法或缺失 usage 均结算 reservation，
  不留下新的永久 reserved request。
- SSE relay 在收到合法 `response.completed` 和 usage 后主动结束，不依赖上游 EOF；fake hold-open 回归通过。
- materialized task 明确 `verifier.user=root`、`verifier.env.HOME=/root`，同时保持 service 与 Agent 为 1000:1000；
  source/staged metadata 和 drift 回归 fail-closed。
- focused pure/fake/loopback tests 通过。
- Docker 诊断最多三个 task run，严格串行且均在项目 watchdog 内：先 oracle/solution reward=1，再 RONDO、Codex
  no-API；使用既有 pinned image，禁止 pull/build，精确清理并保留 Windows C:、Docker df、receipt 与 watchdog evidence。
- provider 真实探针使用极小 Responses 请求，`max_output_tokens <= 64`、reasoning effort low、每次 timeout
  `<=120` 秒；任一 usage 缺失或未结算即停止同一诊断序列。探针与正式 benchmark 的本阶段新增费用合计不得超过
  20 USD（主 Agent 按官方 Sol 价格、Guardian 按官方 Luna 价格核算）。
- 仅当上述门禁全部通过，冻结全新 pair/batch/run IDs；固定 `terminal-bench/fix-git`、RONDO→Codex、零重试、
  5 USD/run、10 USD/pair。本阶段探针与最多两个 pair 的新增真实 API 总上限为 20 USD。
- 每个新 pair 任一侧失败即保留终态并停止；只有明确的 provider/proxy/verifier/Docker/eval harness 基础设施故障
  修复后才可冻结第二个 pair，最多两个新 pair。双侧 completed 后才可评估 M1。
- 更新实时 WBS、Plan 012 和一份精炼执行日志；Plan 012 提交不合并、不推送。

## 2. 范围

### 允许修改

- `eval/rondo_eval/api_budget_proxy.py` 及其 focused tests：有界 transport、SSE terminal 结算。
- `eval/rondo_eval/terminal_bench/` 及其 focused tests：verifier 投影、oracle/no-API 入口、必要的轻量 provider probe。
- `eval/locks/p1-terminal-bench-pair-v1.json`：只在全部前置门禁通过后冻结 v8。
- `justfile`：只增加或调整 Plan 012 的 canonical 轻量入口。
- `plan/012-*`、受影响的实时 WBS 和一份 `agent_log/`。
- Git common root 下 ignored `eval-data/` 中本批 ledger、receipt、work、artifact 与 metrics。

### 不允许修改

- v7 ledger、run IDs、artifact、append-only result 及其历史证据。
- Docker seccomp/capability/private-cgroup/UID/resource/cleanup 边界、预算上限与角色公平合同的放宽。
- RONDO 产品 Rust 源码、上游基线、Cargo lock、模型设施或 L2。
- provider 专用类型、域名硬编码、新审计/可信体系或自动重试；不得以产品失败、认证/额度/usage 错误或不明确的
  供应商错误为理由创建第二个 pair。

### 不允许读取/查看

- `.env.local` 内容；只允许既有严格 loader 静默校验和读取目标变量。
- API 请求/响应正文、真实 key 或其他凭据；探针只输出去敏状态、usage/settlement 和费用信息。

## 3. 硬约束

1. **执行身份**：从 clean main `7bb03d0e23bcbc27dd49e66485652a502e44b0d5` 创建 Plan 012 worktree；
   所有正式 Docker/API 入口从 clean Plan 012 commit 执行。
2. **串行重型任务**：Docker 全生命周期必须在 `mydev/scripts/with-build-lock.sh` 下；本任务禁止 Cargo、Docker
   pull/build 和本地模型。Docker 与任何重型任务严格互斥。
3. **容量证据**：仅 Windows C: 实际余量有效；无法读取或低于 80 GiB 时 Docker fail-closed。WSL 虚拟余量无效。
4. **密钥边界**：provider 仅由 ignored `rondo.local.toml` 决定，Key 仅由严格 loader 从 common-root
   `.env.local` 静默加载到宿主代理；不得注入容器、argv、日志或受跟踪文件。
5. **上游时限**：proxy 的单次上游 HTTP/SSE timeout 必须小于 900 秒且不超过 120 秒。到期必须分类失败、结算
   reservation 并关闭本地请求。
6. **SSE 终态**：只有成功解析 `response.completed` 且其中含合法 usage 才按 usage 结算并提前结束；其他终态、
   EOF 或格式错误不得冒充完成。
7. **Verifier 权限分离**：只允许 Harbor verifier phase 使用 root + `HOME=/root`；容器默认 user、Agent、
   RONDO/Codex 和工具调用保持 1000:1000，禁止 privileged、SYS_ADMIN、seccomp unconfined。
8. **Docker 次数**：最多三个 no-API task run；oracle 失败即停止，RONDO no-API 失败即不运行 Codex。
9. **探针次数/费用**：真实 provider 请求严格串行、保持极小输入；任一 request 未 settle 或 usage 不合法即停止同一
   诊断序列。本阶段探针与正式 benchmark 新增费用合计不超过 20 USD。
10. **paid 授权**：仅前置门禁全部通过后才可新建 paid pair；每 pair 最多两个 Docker run，RONDO 失败不运行
    Codex，零重试，5 USD/run、10 USD/pair；最多两个新 pair，第二个仅用于修复后重验明确的基础设施故障。
11. **结果诚实性**：`actual_usd` 只有结算事实支持时才写数值；未结算 reservation 保持 null。fake、Docker、
    真实 API、未运行项分开报告。
12. **停止条件**：redirect、配置漂移、预算/usage/settlement 异常、watchdog/Windows C:/Docker counter 不可用、
    pinned image 缺失或 cleanup 未确认均立即停止，不用重复调用碰运气。

## 4. 软性建议

- 先用 fake hold-open SSE 和短 timeout fixture 固化代理行为，再碰 Docker/API。
- verifier 改动只投影 Harbor 已有 `verifier.user` / `verifier.env`，不改 frozen task 原始内容或镜像。
- oracle 和现有双侧 no-API 尽量复用相同 materializer、Docker supervisor 与 cleanup 路径。
- provider 探针保持为轻量 CLI：只保存 HTTP status、terminal/usage 合法性、ledger settlement 与计算费用。
- v8 readiness 与 results 可分独立 worktree；results 仅追加结果和实时文档。

## 5. 当前状态

### 已完成

- Plan 011 v7 readiness/results 已分别合并到 main 并推送；`main == origin/main == 7bb03d0e23bcbc27dd49e66485652a502e44b0d5`。
- v7 失败证据保持原样；旧分支已重命名至 `zz-done/*`。
- 已从 clean main 创建本 Plan 012 独立 worktree；严格 loader 已静默确认任务所需 provider credential 可用，
  未输出或查看 `.env.local` 内容。
- proxy 上游 deadline 已与 Agent timeout 解耦为 90 秒；SSE 在完整 `response.completed + usage` 后主动收束，
  header timeout 和 hold-open 回归均证明 reservation 会结算。
- staged verifier 已投影为 root + `HOME=/root`，service/Agent 仍为 1000:1000；新增受监督、无模型、无真实 key
  的 Harbor oracle 入口。
- provider 探针为通用配置驱动入口，响应正文和 key 不落盘；代理保留冻结 Codex 的 User-Agent，并继续拒绝
  redirect、非法 usage 和超预算请求。
- 本 worktree frozen eval 环境已按锁安装 83 个包；`just eval-lock` 解析 85 包，最终 `just eval-test`
  271/271 通过。
- watchdog 内的第六次 oracle 诊断已完成 frozen solution，root verifier 通过 pytest，`reward=1`；Agent/oracle
  保持 UID/GID 1000，隔离和 cleanup 有效态均通过。
- 真实 provider 已执行两个 non-stream Responses one-shot：首个 90 秒无 HTTP status，第二个在 Codex User-Agent
  转发后明确返回 HTTP 503；两个 ledger 均 settled/无 reservation，各按最大 reservation 保守计价 `$0.755400`。
  两次 `/models` 状态检查均在 90 秒内无 HTTP status，不生成 token 或 ledger 费用。

### 当前工作

- v8 已从 clean readiness commit 执行 RONDO slot 1，并在自然触发 Guardian 后按零重试合同停止；Codex slot 2
  与 M1 均未运行。当前只保留终态、结果和执行日志，不创建替代 pair。

### 历史交接（不是当前规划）

> 以下记录只反映 v8 结束时的交接判断；当前路线以 `doc/WBS.md` 为准。

1. 保留全部 stopped probe/v8 ledger、去敏 metadata、Docker evidence、watchdog summary 与 append-only result，
   不复用或改写。
2. 冻结 Codex API-key Guardian 的有效默认仍是 `gpt-5.6-luna`；v8 已证明 Sol 主 Agent 可完成真实请求，但
   Luna Guardian 返回 HTTP 503。不得把 Guardian 改写为 Sol 后冒充同一公平 pair。
3. B3/M1 保持未通过；后续若改变 Guardian/provider 合同或供应商模型能力，作为新的独立计划与授权处理。

### 阻塞项

- Sol 主链路可用，但 frozen Codex v0.147 的公平 Guardian 合同仍要求 Luna。v8 的 5 个 Sol main 请求均为
  HTTP 200 且 usage 合法；唯一 Guardian Luna 请求为 HTTP 503/usage invalid，因而不能完成 RONDO slot 1。
  容器只接触 loopback proxy，不接收宿主代理变量或真实 key。

### 当前验收状态

- provider/verifier 的 pure/fake/loopback 门禁已通过；真实 oracle/verifier `reward=1`，Sol frozen-Codex wire
  terminal/usage/settlement 通过。v8 RONDO 运行的本地预算已完整结算为 `$5.000000`、reservation 为 0；连同
  既有探针与两个 Terra one-shot，本阶段本地保守计价累计 `$13.070095`，`actual_usd` 保持未知。Terra 在当前
  provider/credential/UA 组合下返回 HTTP 403，本地配置已恢复 Sol。Codex/M1 未运行，也没有可归档的 `E_final`。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | proxy 上游 timeout 采用不超过 120 秒的固定上界 | 必须早于 Harbor 900 秒并让 ledger 有机会结算 | provider transport | 已采纳 |
| 002 | SSE 以合法 `response.completed` + usage 为成功终态，不等待 EOF | OpenAI-compatible 上游可能在 terminal event 后保持连接 | proxy/ledger | 已采纳 |
| 003 | verifier phase 使用 root + `HOME=/root`，Agent 保持 1000:1000 | frozen verifier 需要 apt/curl/uvx，不能把 root 权限扩给 Agent | task materialization | 已采纳 |
| 004 | Docker 三次额度按 oracle、RONDO no-API、Codex no-API 各一次计算 | 同时验证评分链与两侧执行合同且不超过授权 | Docker acceptance | 已采纳 |
| 005 | provider 探针单独使用 1 USD 总账本；v8 pair 仍为 10 USD，两者合计 11 USD | 早期授权边界 | budget/pair | 已由 008 取代 |
| 006 | v8 仅在全部前置门禁通过后冻结 | 避免未就绪 identity 被消费后再次遗留不可复用失败批次 | paid readiness | 已采纳 |
| 007 | 代理逐字转发一个经语法校验的下游 User-Agent | OpenAI-compatible 中转可能以 Codex User-Agent 路由；代理身份覆盖会破坏兼容 | provider transport | 已采纳 |
| 008 | 探针与最多两个新 paid pair 共用 20 USD 总授权 | 用户扩大诊断次数但收紧本阶段总费用；第二 pair 仅限基础设施修复后重验 | provider/budget/pair | 已采纳 |
| 009 | v8 主 Agent 使用 Sol；两侧 Guardian 保持 Luna/low | Codex v0.147 的 API-key Guardian 默认固定 Luna，不能虚构 Sol override；主 Sol 已由真实 wire 验证 | pair/model/budget | 已采纳 |
| 010 | authenticated provider 传输保留宿主代理，容器仍只使用 loopback proxy | 当前区域直连只证明短 401 可达，真实长响应直连无终态；宿主代理下真实 Sol wire 成功 | canonical shell/network | 已采纳 |
