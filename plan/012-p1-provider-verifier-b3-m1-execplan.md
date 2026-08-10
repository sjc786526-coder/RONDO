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

通过离线、Docker 和小额 provider 探针后，才冻结并执行唯一的 v8 paid pair：RONDO 一次后 Codex 一次、零重试，
最后仅在双侧 completed 时运行既有 `assess_m1`。

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
- provider 真实探针最多三个请求、依次为 authenticated endpoint、non-stream Responses、stream Responses；
  Responses `max_output_tokens <= 64`、reasoning effort low、每次 timeout <=120 秒；最多 1 USD，任一 timeout、usage
  缺失或未结算即停止后续真实请求。
- 仅当上述门禁全部通过，冻结全新 v8 pair/batch/run IDs；v8 固定 `terminal-bench/fix-git`、RONDO→Codex、零重试、
  5 USD/run、10 USD/pair，连同探针本阶段新增真实 API 总上限 11 USD，底层 ledger 20 USD hard cap 不变。
- v8 任一侧失败即保留终态并停止；不得运行 v9 或替代 pair。双侧 completed 后才可评估 M1。
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
- provider 专用类型、域名硬编码、新审计/可信体系、自动重试或第二个 pair。

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
9. **探针次数/费用**：最多三个真实 provider 请求、合计不超过 1 USD；请求严格串行。任一 request 未 settle、usage
   不合法或 timeout，立即停止剩余真实探针。
10. **v8 授权**：仅前置门禁全部通过后才可新建 v8；最多两个 Docker run，RONDO 失败不运行 Codex，零重试，
    pair 不超过 10 USD，本阶段连探针总新增费用不超过 11 USD。
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
- provider 探针已实现为通用配置驱动的三步入口，使用 1 USD 私有 ledger，响应正文和 key 不落盘。
- 本 worktree frozen eval 环境已按锁安装 83 个包；`just eval-lock` 解析 85 包，`just eval-test` 270/270 通过。

### 当前工作

- 复核差异并提交 clean provider/verifier readiness 基线，为 Docker oracle/no-API 做准备。

### 后续计划

1. 提交 provider/verifier 修复并从 clean commit 运行 focused tests。
2. 在 watchdog 内依次运行 oracle reward=1、RONDO no-API、Codex no-API，最多三个 Docker task run。
3. 运行最多三个/1 USD provider 探针；任何异常即停止真实请求。
4. 全部门禁通过后冻结 v8，提交 clean readiness，再执行唯一 v8 pair；双侧 completed 后运行 M1。
5. 更新权威状态和执行日志，提交相关 Plan 012 worktree但不合并、不推送。

### 阻塞项

- 当前无代码实施阻塞；v8 identity 尚未创建，Docker/API 尚未运行。

### 当前验收状态

- provider/verifier 代码与 pure/fake/loopback 门禁已通过；Docker oracle/no-API、真实探针、v8 与 M1 均未运行。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | proxy 上游 timeout 采用不超过 120 秒的固定上界 | 必须早于 Harbor 900 秒并让 ledger 有机会结算 | provider transport | 已采纳 |
| 002 | SSE 以合法 `response.completed` + usage 为成功终态，不等待 EOF | OpenAI-compatible 上游可能在 terminal event 后保持连接 | proxy/ledger | 已采纳 |
| 003 | verifier phase 使用 root + `HOME=/root`，Agent 保持 1000:1000 | frozen verifier 需要 apt/curl/uvx，不能把 root 权限扩给 Agent | task materialization | 已采纳 |
| 004 | Docker 三次额度按 oracle、RONDO no-API、Codex no-API 各一次计算 | 同时验证评分链与两侧执行合同且不超过授权 | Docker acceptance | 已采纳 |
| 005 | provider 探针单独使用 1 USD 总账本；v8 pair 仍为 10 USD，两者合计 11 USD | 保持授权边界清晰且不复用 v7 | budget/pair | 已采纳 |
| 006 | v8 仅在全部前置门禁通过后冻结 | 避免未就绪 identity 被消费后再次遗留不可复用失败批次 | paid readiness | 已采纳 |
