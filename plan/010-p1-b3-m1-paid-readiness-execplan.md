# P1 B3/M1 最小 paid 就绪 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

在已通过真实 no-API Docker 验收的 Plan 009 基础上，只补齐一次最小 B3/M1 真实 API 批次启动所必需的代码和冻结配置：
由本地预算代理为每个主 Agent/Guardian 请求投影并验证 declared eval role；让 publication journal 创建前的确定性失败
收敛为既有明确失败终态；冻结同一 `fix-git` 任务、RONDO/Codex 各一轮、零重试及明确预算。完成轻量门禁后停止，
不运行真实 API，向用户申请单独的真实批次授权。

### 完成/验收标准

- 主 Agent 与 Guardian 请求在离开本地预算代理前都带有正确的 `X-RONDO-Eval-Role`；代理必须按已验证的请求形状
  推导角色，并拒绝调用方声明与推导结果不一致的请求。元数据只把实际投影成功且一致的角色计为 declared。
- publication 已进入 paid `publishing`，但 `ArtifactWriter` 尚未创建 journal 时，如发生确定性校验失败，必须使用现有
  failure publication/ledger 终态收敛，不永久停留在 `publishing`；journal 创建后继续使用既有恢复语义。
- paid pair 唯一冻结为 `terminal-bench/fix-git`，RONDO slot 1、Codex slot 2，各一轮，零重试；两侧使用现有固定
  image、bundle、公平参数、Docker/watchdog 和 append-only publication。
- 模型固定为主 Agent `gpt-5.6-luna`，Guardian `gpt-5.6-luna`、reasoning effort `low`。每 run 上限 5 USD，
  批次总硬上限 20 USD；两槽拓扑最大实际授权额为 10 USD，最多 2 个 benchmark run。
- 已有 Luna 预算价格快照与当前官方模型页一致，并由 focused loopback 测试覆盖；不更改 ledger schema 和上限。
- 只运行相关 pure/fake/loopback 测试；不得运行 Docker、Cargo、本地模型或真实 API。
- 最终给出准确的模型、两侧运行数、每 run/批次预算、零重试和 canonical 执行命令，然后停止并申请单独真实 API
  批量授权。pure/fake 通过不得表述为 B3/M1 通过。

## 2. 范围

### 允许修改

- `eval/rondo_eval/api_budget_proxy.py` 及其 focused loopback 测试：角色投影/验证和现有 Luna 价格常量。
- `eval/rondo_eval/artifacts.py`：只允许增加判断 publication journal/target 是否已开始的轻量查询，不改归档 schema。
- `eval/rondo_eval/terminal_bench/__main__.py`：只允许收敛 journal 前确定性 publication 失败，并显式指定 frozen
  detached measurement worktree，避免把当前 harness checkout 误当产品源码身份；不改变 measurement 校验本身。
- `eval/rondo_eval/terminal_bench/pair.py`、`eval/locks/p1-terminal-bench-pair-v1.json` 及直接测试：冻结 paid 两槽批次。
- 与上述行为直接相关的 `eval/tests/`；以 focused 行为回归为主，不扩测试体系。
- 本计划“当前状态/关键决策记录”、受影响的实时 WBS、eval benchmark 状态和一份精炼实施日志。

### 不允许修改

- `mydev/` 产品源码、冻结 Codex/RONDO 二进制、Terminal-Bench task/image、Harbor 或 bwrap 资产。
- Docker/watchdog、ArtifactWriter schema、预算 ledger schema、证据 schema、M1 指标体系、L1/L2、本地模型或训练。
- 已发布结果、历史 no-API receipt、历史 budget/pair ledger 或 Plan 009 证据。
- 新增数据库、可信锚、审计字段、通用 workflow、复杂状态机或与真实 paid 启动无关的重构。

### 不允许读取/查看

- `.env.local` 内容。只允许既有严格 loader 静默校验文件/变量并把目标 key 注入目标进程；不得打开、搜索、打印、
  复制或记录密钥。
- 项目外个人文件、模型权重、来源不明 Docker 对象内容或其他仓库。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **先计划后实施**：本 ExecPlan 落地后才修改生产代码；若需要扩大目标/范围或真实外部操作，暂停并重新授权。
2. **最小角色投影**：不修改冻结两侧产品。角色由受控 loopback budget proxy 根据已有严格 body 识别结果投影；
   调用方已有声明时必须一致。不得把未经验证的任意 header 当真。
3. **不改 schema**：复用现有 role provenance、ledger、publication 和 failure record 字段；不新增审计层。
4. **崩溃边界不倒退**：只有 journal 尚不存在的确定性校验失败进入 failure publication；一旦 journal/target 已出现，
   必须保持 existing publishing recovery，禁止同时写第二终态。
5. **费用 fail-closed**：官方价格、每请求 reservation、每 run 5 USD、批次 20 USD、最多 4 个底层 ledger run 的硬门
   保持；本 pair 拓扑进一步限制为两个 run。usage 缺失/非法继续按最大预留扣减并停止。
6. **固定公平拓扑**：同一任务、image、timeout、模型、Guardian effort、retry 和 bundle 身份；RONDO 成功后才允许
   Codex，任一失败停止，不创建替代 pair、不自动重试。
7. **真实 API 不执行**：本批可以启用唯一受跟踪 paid pair，以便授权后无需再改代码；但不得读取 key 内容、调用 API、
   运行 Docker/Cargo/模型或产生费用。实际执行必须等待用户再次明确授权。
8. **轻量门禁**：只跑 role proxy、publication failure 和 paid pair 直接相关 pure/fake/loopback。普通诊断或低风险边角
   只记入日志，不扩 schema、账本或审计设施。
9. **诚实交付**：区分 fake/loopback 与未运行真实 API/Docker；B3/M1 只有未来双侧真实 completed 且聚合通过才可验收。

## 4. 软性建议

- 角色投影优先复用 `_inspect_request` 已有的 body 形状校验结果，在单一转发点写 header 与 metadata，避免两套判断。
- `ArtifactWriter` 只暴露一个无副作用的 publication-started 查询；CLI 在异常分支据此选择既有 failure publisher 或
  publishing recovery，不新增状态。
- paid lock 直接从 Plan 009 已验证的 B2 lock 改出当前唯一 pair，只更新 paid identity/topology/enablement 和官方价格
  所需事实，不触碰 Docker/Harbor identity。
- 最终执行说明给出两个严格串行命令或一个已有 canonical 包装入口；不为展示命令另建通用编排层。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- Plan 009 分支已 no-ff 合并到本地 `main` 并推送；`main == origin/main ==
  b0b8b702a46d7db3113763142ea92d9c254061fb`，主工作区干净。
- 完成分支已按规范保留为 `zz-done/0810-plan008-review-remediation`。
- 当前独立 worktree/分支 `0810-plan010-b3-m1-paid-readiness` 从上述 clean commit 创建。
- 已重读根与就近 `AGENTS.md`、`plan/plan-example.md`、Plan 009 和 paid 相关源码/测试。
- 严格 loader 已在不输出内容的前提下确认当前 OpenAI provider secret 可用；未读取或打印 `.env.local`，未调用 API。
- 候选 pair/run identity 在 tracked 结果和 common `eval-data` 中不存在：
  `p1-fix-git-pair-v6`、`p1-fix-git-b3-m1-v1`、`20260810-230000000-tb-rondo-r1`、
  `20260810-230000001-tb-codex-r1`。
- loopback budget proxy 会按已验证 request shape 为缺失声明的请求投影 main/guardian declared role，并把该
  header 转发；已有 header 与推导不一致仍在上游调用前拒绝。
- Luna Standard 价格已按 2026-08-10 官方模型页同步为 input 0.20、cached input 0.02、output 1.20
  USD/百万 token；最大单请求 reservation 为 0.7554 USD。20/5 USD 硬上限未改。
- `ArtifactWriter.publication_started()` 只区分 journal/target 是否已出现；paid CLI 对 journal 前确定性
  validation failure 复用已有 failure publication，journal 后恢复语义不变。
- paid lock 已冻结 v6 两槽并启用：同一 `fix-git`，RONDO/Codex 各一轮、零重试；lock SHA-256 为
  `c63ec54e881ec123a451e5bb5136bc4b90306d7531ff56a97daef8f435545b3f`。
- paid CLI 已显式接收 detached measurement worktree；watchdog/harness/结果 worktree 仍各自按原合同校验。
- focused pure/fake/loopback：proxy + artifacts/config + pair + results 81/81，Terminal runner/adapter 18/18，
  合计 99/99；`py_compile`、CLI help 与 `git diff --check` 通过。
- 用户随后授权执行唯一 v6 paid pair。clean harness `1d36eab9bf2b5462347cb304116656f47ef9c2af` 上的
  RONDO slot 1 在约 975 秒后以 `AgentTimeoutError` / `infra_failed` 收敛；pair ledger 已
  `failed/blocked`，零重试合同生效，Codex slot 2 与 M1 均未运行。
- 该 run 启动了一个 main 请求，但没有收到上游响应或 usage；预算 ledger 保留 0.755400 USD reservation，
  `charged_usd=null`、`spent_usd=0`。未查询账单，因此真实计费不作 0 USD 断言。
- 直接原因是本计划原 canonical shell 清除了宿主 HTTP(S) proxy。无认证对照中，清除 proxy 后访问官方 endpoint
  15.010 秒超时；保留宿主网络环境时 0.494 秒返回预期 401。未来 paid 命令必须保留宿主 proxy，只设置
  loopback `NO_PROXY=127.0.0.1,localhost`。
- watchdog 正常收尾，132 个 Docker samples 无 warning；运行后 Docker 为 0 容器、0 卷，image/build-cache
  与运行前相同，项目盘仍有 846GB 可用空间。

### 当前工作

- 无；v6 首槽已失败并完成结果归档、费用保留和直接原因诊断。

### 后续计划

1. 不复用 v6，不运行 Codex；若继续 B3，须另行冻结新 pair，并再次取得明确真实 API 批量授权。
2. 新 pair 的 canonical 命令保留宿主 HTTP(S) proxy，仅让 loopback 地址绕过 proxy；仍严格 RONDO→Codex、
   零重试、首侧失败停止。

### 阻塞项

- v6 已按授权执行一次并因首槽 infra failure 永久阻断；继续 B3/M1 需要新 pair 与新的单独 API 批量授权。

### 当前验收状态

- Plan 009 B2：已通过并已合并推送。
- Plan 010 paid readiness：代码、focused 门禁、文档与日志完成。
- B3/M1：RONDO slot 1 已尝试但未完成；Codex 与 M1 未运行。一个上游请求未返回，ledger 保留
  0.755400 USD reservation，实际账单费用未知。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 角色由本地预算代理按已验证请求形状投影，不修改冻结产品 | 同时适用于 RONDO/Codex，避免重建二进制并保证公平 | proxy、metadata | 已采纳 |
| 002 | journal 前失败复用现有 failure publication；journal 后维持 publishing recovery | 修复永久卡死且不引入第二归档事务 | ArtifactWriter、paid CLI | 已采纳 |
| 003 | paid pair 固定为 v6：fix-git、RONDO→Codex、各一轮、零重试 | 满足最小 B3/M1，避免扩大运行数和证据体系 | pair lock、命令 | 已采纳 |
| 004 | 保留 20 USD 批次硬上限和 5 USD/run；两槽拓扑最多使用 10 USD | 延续既有授权上限，同时给本次最小批次更窄的自然上界 | budget、交付说明 | 已采纳 |
| 005 | 本批只做 readiness 并提交 worktree，真实 API 必须下一次单独授权 | 用户明确要求先给参数/命令再停止 | 执行边界 | 已采纳 |
| 006 | paid CLI 显式接收 detached measurement worktree，harness/watchdog 仍在当前 clean checkout | 当前 eval harness 与冻结 RONDO 产品提交不同，单一 cwd 无法同时证明两种身份 | CLI 启动命令 | 已采纳 |
| 007 | 真实执行时使用同 readiness commit 的独立 results worktree | 首侧 append-only result 会弄脏 results checkout，不能同时弄脏第二槽所需的 clean harness | paid 执行拓扑 | 已采纳 |
| 008 | paid host 进程保留宿主 HTTP(S) proxy，只对 loopback 设置 `NO_PROXY` | 当前机器直连官方 endpoint 超时，预算代理需要宿主网络路径；Harbor 子进程环境仍由 runner 最小化 | canonical shell | 已采纳 |
