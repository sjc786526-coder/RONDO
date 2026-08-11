# P1 测评链阶段总结与新会话交接

## 1. 交接结论

本批从 P1 Terminal-Bench / 本地审批前置设施开工，经过独立审查、轻量化和多次真实链路验证，当前已经形成以下稳定边界：

- **B1 完成**：Terminal-Bench 2.1、`fix-git`、任务镜像、两侧 runtime bundle 与基础结果合同已冻结。
- **B2 完成**：Plan 009 已在真实 Docker 中按 RONDO→Codex 串行完成双侧 no-API 链路；两侧各 2 次 fake 请求、真实 code-mode tool round-trip、严格容器有效态和精确 cleanup 均通过。
- **L1 完成**：Standard/Lite `E_final` 规范化、静态审批 payload 和最终去工具边界已有统一合同与测试；只声明三组协议/fixture 投影，不冒充三套生产消费者。
- **L2 仅完成前置**：llama.cpp CPU x64 frontend/动态运行闭包、launcher/client/doctor/fake 已就绪；GPU、权重、model-backed 启动和真实推理均未验收。
- **B3/M1 未完成**：Plan 012 已证明 Sol 主 Agent 的真实 Responses 链、可信 verifier/oracle 和完整 Docker 运行链可用，但 v8 在自然触发 Luna Guardian 后收到上游 HTTP 503，RONDO slot 1 失败，Codex slot 2 与 M1 未运行。

截至本日志，Plan 012 readiness HEAD 为 `919a4790eb38770d1a394a8ce59b8734e504e97f`，append-only results HEAD 为
`bb3cd1e813f2b622e22bbc312f3625f0a064f530`；合并前主线为
`7bb03d0e23bcbc27dd49e66485652a502e44b0d5`。交付后的最终 `main`/远端 SHA 以本次交付结果为准。

## 2. 历程概览

### 2.1 Plan 008：共享地基、B1/B2 初版和 L1/L2 前置

初版完成了共享 eval 合同、ArtifactWriter、付费预算代理、Terminal-Bench 双适配器、二进制/镜像冻结、L1 payload 和 L2 llama.cpp 前端设施。真实 Docker 很快暴露 builtin seccomp 下 nested user namespace 无法创建，B2 因而没有被误写为完成。

独立审查随后发现配对公平门禁未接生产路径、归档崩溃窗口、Docker 有效态证据不足、结果语义矛盾和运行身份漂移等问题。整改补齐了 custom seccomp、container image/UID/cgroup/limits/metrics/VHDX、watchdog 与结果合同，但实现一度演变得过重；真实 v4 又暴露 `cap_drop=ALL` 下运行时 `chown` 失败和 root-owned Git 仓库的 `safe.directory` 问题。

### 2.2 Plan 009：做减法并完成 B2

Plan 009 删除了 no-API 永久账本、retirement、崩溃恢复状态机、一次性 migration 和 Harbor 全依赖文件闭包，保留单进程 RONDO→Codex 入口、一个当前 receipt 和必要的 Docker 安全监督。marker 改为只接受结构化 `exec_command` 成功结果，UID 1000 下增加真实 Git probe。

真实 canonical r5 在 clean commit 上完成双侧 no-API Docker 验收：

- RONDO、Codex 均 `completed`；
- 每侧 2 次 fake 请求，tool round-trip 成功；
- pinned image、UID 1000、`cap_drop=ALL`、private cgroup、custom seccomp、2/3 GiB memory/swap 与 256 pids 均由 daemon facts 验证；
- cleanup 为 `verified_empty`，容器、网络、卷归零，VHDX 与 `docker system df` 无增长；
- 官方 API 0 次、费用 0 USD。

Plan 009 已以主线 merge `b0b8b70` 交付，B2 自此冻结，不再扩张低收益审计合同。

### 2.3 Plan 010/011：第一次 paid 尝试与通用 provider

Plan 010 v6 首次执行 paid RONDO slot 1，但配置仍指向错误的官方 endpoint，宿主代理又被 canonical shell 清除，最终 `AgentTimeoutError`；Codex/M1 未运行，v6 保持失败终态。

Plan 011 将 provider 改为通用、配置驱动的 OpenAI-compatible HTTPS endpoint：受跟踪源码不含供应商域名，实际 base URL 只来自 ignored `rondo.local.toml`；密钥仍只由严格 loader 从 `.env.local` 注入宿主 proxy，容器只看到 loopback bearer。同期 watchdog 改为以 Windows `C:` 实际容量而非 WSL 虚拟 1TB 余量做 fail-closed 门禁。

v7 仍因上游真实响应无终态而超时，RONDO slot 1 失败，Codex/M1 未运行。v6/v7 的 pair、budget、artifact 和 append-only result 均保留，不复用、不改写。

### 2.4 Plan 012：修通 verifier、transport 和 Sol 主链

Plan 012 只处理直接业务阻塞：

- proxy 上游 deadline 固定为 90 秒，早于 Harbor Agent timeout；
- SSE 收到合法 `response.completed + usage` 后立即收束，不等待上游 EOF；
- non-stream 完整 completed JSON + usage 同样可在上游保持连接时提前结束；
- 严格转发受限的 Codex `User-Agent` 与 `originator`，保留宿主 HTTP(S) proxy，只为 loopback 设置 `NO_PROXY`；
- verifier phase 使用 root + `HOME=/root`，Agent、RONDO/Codex 和工具仍为 UID/GID 1000；
- frozen solution 在真实受监督 Docker 中通过可信 root verifier，得到 `reward=1`，证明评分链有效。

真实 provider 现状：

- **Sol 可用**：frozen-Codex wire 在宿主代理下得到 terminal response、合法 usage 和 settled ledger；v8 的 5 个 Sol main 请求也全部 HTTP 200。
- **Luna 当前渠道不可用**：同配置的 Guardian 请求返回 HTTP 503、usage invalid；用户已在供应商侧确认该渠道暂不可用。
- **Terra 当前组合不可用**：最新非流探针约 6 秒返回 HTTP 403，未发送流式第二请求；这只描述当前 base URL、credential、Codex UA 和模型组合，不外推为 Terra 全局不可用。ignored 本地配置已经恢复 Sol。

## 3. v8 真实结果

v8 固定：

- pair：`p1-fix-git-pair-v8`；batch：`p1-fix-git-b3-m1-v3`；
- task：`terminal-bench/fix-git`；
- 顺序：RONDO slot 1 → Codex slot 2；各一轮、零重试；
- main：`gpt-5.6-sol`；Guardian：`gpt-5.6-luna` / low；
- 5 USD/run，10 USD/pair。

实际执行：

- RONDO main 共 5 次 Sol 请求，HTTP 200、usage valid、角色声明/推断一致；官方价格本地计算合计 `$0.163456`。
- 自然 Guardian 请求为 Luna/low，HTTP 503、usage invalid。预算代理按 fail-closed 合同用当时剩余的 `$4.836544` reservation 结算该失败，run 本地 `spent_usd=5.000000`、reservation 为 0。
- 这里的 `$5.000000` 是**保守本地预算计价**，不是供应商实扣证明；结果保持 `actual_usd=null`。
- RONDO 以 `infra_failed` 终止；v8 pair 为 `failed/blocked`，只有 slot 1。Codex slot 2、M1、自然完成的 Guardian `E_final`/S2 均不存在。
- watchdog `rondo-build-1000-20260811085847-50122.scope` 正常收束，`stop_reason=none`、`cleanup_reason=none`；Windows C: 从 `195236925440` 到 `195236298752` bytes，swap peak 0。精确容器、网络、卷为空，scope inactive。

append-only 结果保存在 results 分支，raw 去敏 API metadata、budget、pair、work 和 watchdog evidence 保存在 common-root ignored `eval-data/`。v8 历史结果行不改写。

## 4. 预算与结果语义

- Plan 012 当前所有 provider probe 与 v8 ledger 均已 settled，没有 active reservation。
- Terra 两个 one-shot 各按 `$0.25` 保守结算；其中第一次在开发沙箱外联前中断，第二次得到 HTTP 403。
- Plan 012 本地保守累计为 `$13.070095`，低于本阶段 20 USD 授权；供应商实际账单未查询，不能把本地保守值当实扣。
- Sol 计价采用 `$5/$0.50/$30`，Luna 采用降价后的 `$0.20/$0.02/$1.20`，Terra 采用 `$2/$0.20/$12`，单位均为每百万 input/cached/output token。
- exceptional publication 的角色汇总已做最小修复：未来会把合法声明的失败请求计入 `api_request_roles`，但只要任一 usage invalid，`metadata_ready` 仍为 false。v8 旧行保持 `0/0` 不变，真实 5 main + 1 Guardian 可从其归档 `api-metadata.json` 复核。

## 5. 当前代码与安全边界

已保持：

- 通用 provider/base URL 配置，不硬编码供应商；redirect、凭据 URL、非法 URL、错误 role/model/usage 均拒绝。
- `.env.local` 不被打开、搜索、打印、复制或提交；严格 loader 只向目标宿主 proxy 注入所需 key。
- 容器不接触真实 key 或宿主代理，只使用 loopback base URL 与随机临时 bearer。
- Docker 仍受 watchdog、Windows C:、40/60GB Docker 增长、80GiB 余量、内存/cgroup/串行锁和 exact cleanup 约束。
- paid pair 保持零重试、RONDO 失败即停 Codex；失败 pair 与 append-only 结果不复用、不覆盖。

未完成：

- B3/M1 没有双侧 completed 证据；不能推进依赖 M1 的性能基线。
- frozen Codex v0.147 的 configured-provider API-key Guardian 默认候选仍是 Luna，不能读取 RONDO 新增的 `auto_review.model`。下一会话若要实际使用 Sol Guardian，必须建立一个**新的、两侧实际上游条件一致**的公平合同和新 pair，不能只改 RONDO，也不能冒充 v8 重试。
- L2 GPU、权重、model-backed server、真实推理、延迟/显存和 L2a/L3/L4 均未验收。

## 6. 下一会话建议

1. 先读取本日志、`doc/WBS.md`、Plan 012 和 v8 append-only result，不重做已经通过的 B1/B2、oracle 或 Sol wire 探针。
2. 不再探测已确认不可用的 Luna/Terra 当前渠道。若用户决定 Sol Guardian，先用最小代码明确两侧 requested/effective Guardian 模型与计价，保持 provider 通用配置；补必要的 focused fake/loopback 回归即可。
3. 冻结新 pair/batch/run IDs，v8 保持 failed/blocked。任何新真实 paid pair都要重新明确模型、轮数和预算授权。
4. 新 pair 仍严格 RONDO→Codex、零重试、首侧失败即停；双侧 completed 后才运行 `assess_m1`。
5. 不借机扩建新的审计/资产体系；只修会阻塞真实业务链、造成假成功、泄密/超费或资源失控的问题。

## 7. 本批验证与工作树状态

- v8 readiness 前：`just eval-test` 273/273，`just eval-lock` 85 packages。
- 最新 Terra/角色修复：focused pure/fake/loopback 63/63，`py_compile`、`git diff --check` 通过。
- 当前测试源码静态计数为 275 项；本次交接只改文档，不重复运行全量测试。
- readiness 与 results worktree 均 tracked clean；主工作区在合并前 clean。
- 既有 `0809-remaining-test-failures` worktree 的用户未跟踪日志保持未改动。
- 本批未运行 Cargo、本地模型或权重下载；Terra/角色修复提交后未运行 Docker。
