# Plan 055 / M3-B2a 整改最终验收

日期：2026-08-22

审查对象：`worktree-055-publication-critic-service@3be09927e0435a85ad987d00a1fa774b003c5434`

结论：**PASS；验收通过，任务目标完成。** 上轮 `d216bfb` 报告的三项 correctness/functionality finding 均已关闭，未发现局部
修复造成的新回归。

## Findings 关闭情况

1. **极小 frame cap：关闭。** protocol v1 统一拒绝 request/response 小于 8 KiB 或大于 1 MiB 的配置；公开构造器、client
   构造和 `serve()` 最终消费点均通过同一 descriptor 校验复验。最大长度、最大 JSON 转义 identity 的正式 wire 序列化回归覆盖
   liveness/readiness/shutdown 请求和全部控制响应；大合法 review 仍可按设计得到 typed `RequestTooLarge`，且后续调用不受污染。
2. **terminal backend status：关闭。** scorer status 由单次快照分类为 Loading、精确 Ready 或 typed terminal failure；liveness
   报 `Failed` phase，readiness/review 立即返回 backend/model/scoring failure，Loading 仍可等待并恢复，draining 继续优先。
3. **release barrier 丢唤醒：关闭。** 受控 scorer 改用不可逆、可预取消且广播的一次性 `CancellationToken` latch；release 早于
   waiter 注册也可见，显式请求取消仍优先。资源进程测试覆盖一次 release 同时放行 active 与四个 queued affected calls。

## 回归与边界

- `3be09927` 只修改 Publication Critic crate 的 source/tests 与 Plan 055 状态文档；相对规划基线，`team_publish`、Team State、
  Team Lens、`eval/`、`training/` 和 `mydev/` 仍为零差异。未新增依赖、锁文件或构建接线变化。
- 静态复核确认 exact expected identity、有限 queue/concurrency/deadline、queued/in-flight 取消、grace/force shutdown、body-free
  日志和请求失败后隔离语义没有被本轮局部修复削弱。
- 采用执行者经共享构建锁报告的最终 29/29 定向测试、Clippy、argument-comment lint、fix/fmt 证据；本轮按用户要求没有重复运行
  重型 Cargo。轻量直接运行现有整改 binary，`--request-bytes 1 --response-bytes 1` 现以
  `InvalidResourceConfiguration`/exit 1 拒绝，不再公告启动。
- 未运行全 workspace、全 Bazel、CI、PR、Docker、真实 API、训练、云资源或真实模型；这些不属于本次复验完成门，未运行不表述
  为通过。证据仍只覆盖受控 backend 的正式服务进程与 typed client，不代表真实 threshold、模型质量、B2b packet 构造或产品
  端到端。

## 决策与当前状态

- 维持上轮裁决：**不新增生产进程 supervisor、复杂鉴权、可信证明、审计设施或第二套 trace。** 可执行服务、startup
  announcement、typed client 与实际子进程测试已经满足 B2a 边界；部署监督留给调用方/后续部署层。
- 执行摘要没有提出新的用户决策项，本轮无需代用户新增产品或架构决策。
- **验收状态：通过。任务目标：完成。** 055 工作树仅本地提交，尚未合并、推送或归档；M3-B2b 仍须另行立项授权。
