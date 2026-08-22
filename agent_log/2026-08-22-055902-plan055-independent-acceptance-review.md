# Plan 055 / M3-B2a 独立验收审查

日期：2026-08-22

审查对象：`worktree-055-publication-critic-service@c4c3e497eb752f762fa099bcf8c515992b4b4651`

结论：**不通过；当前提交尚未完成 Plan 055 任务目标。**

## 审查范围与证据

- 核对根目录与 `multidev/` 规则、Plan 055、M3-A1/方向 3 WBS、执行日志、提交序列和相对基线 `2bdd1f9` 的完整差异。
- 静态审查新增 crate 的 packet/identity/resource/failure、typed client、wire、service、受控 scorer binary 与 27 项定向测试。
- 允许写集符合任务边界；`team_publish`、Team State、Team Lens、`eval/`、`training/` 和 `mydev/` 无差异，未发现发布流程或
  Team State 行为被接入或改变。
- 复用执行者报告的 27/27、Clippy、fix/fmt 与 Bazel lock 证据。本轮未重复运行重型 Cargo；发现的问题不在现有测试覆盖内，
  仅以现有已构建 binary 做了一次轻量复现。

## 必须修复的 findings

### 1. 有效配置可启动一个无法健康检查、调用或正式关闭的服务（P1）

`RuntimeLimits::validate()` 只要求 request/response cap 非零且不超过 1 MiB，因此 `request_bytes=1`、`response_bytes=1` 会通过
`RuntimeLimits`、`ServiceConfig` 和 `serve()` 的复验。服务仍会打印 startup announcement 并进入监听/ready；但 typed client
连最小 liveness 或 shutdown envelope 都无法发送，会在连接前返回 `RequestTooLarge`。raw peer 即使送入请求，服务的任何正式
response envelope 也超过 1 byte，`write_response()` 会静默放弃写出并断连。

轻量复现：

```text
timeout 0.5s ./multidev/codex-rs/target/debug/codex-publication-critic-service \
  --request-bytes 1 --response-bytes 1
```

进程打印 `publication_critic_service_listening` 和包含上述 cap 的 startup announcement，随后持续运行至外部 timeout，证明该配置被
当作可启动配置接受。

这使公开的 typed “有效配置”与最基本的 lifecycle/协议可用性矛盾，也会让 B2b 把启动配置错误误判成运行时请求超限或断连。
修复应在单一资源/descriptor 校验边界拒绝不能容纳基本正式协议 envelope 的 cap，并由 client/service 最终消费点继续复验。
具体最小值或计算方式由执行者选择；不要求建设通用策略系统。现有 client request-cap 测试可改用“可容纳控制请求、但容纳不下
较大合法 review”的上限。

### 2. `ScorerStatus::Failed` 被误报为仍在启动（P1）

`ServerState::backend_ready()` 只返回 bool，`status()` 随后把 `ScorerStatus::Loading`、identity 不匹配和显式
`ScorerStatus::Failed` 全部折叠成 `ServicePhase::Starting`。review 返回 `NotReady`，`wait_until_ready()` 最终只能等到
`StartupTimeout`。终态 backend 初始化失败因此不能及时形成已有的 typed backend failure，且该公开状态分支没有回归测试。

应让 readiness/review 对 `Failed` 及时返回 typed backend/lifecycle failure；是否新增 wire phase、复用现有 `BackendFailed`，或采用
其他等强且更小的实现由执行者决定。需要一条确定性回归证明 `Loading` 仍可等待，而 `Failed` 不会被伪装成启动中或等满 startup
deadline。

### 3. 受控 scorer 的 release barrier 存在丢唤醒竞态（P2）

阻塞 scorer 先读取 `released == false`，再创建/轮询 `Notify::notified()`；控制线程使用 `notify_waiters()`。若 release 恰好发生在
这两步之间，`notify_waiters()` 不为未来 waiter 保存 permit，而 `released` 虽已变为 true，score future 却没有机会重新进入循环，
只能等 job timeout 或 cancellation。资源、取消和关闭测试因此存在偶发错判风险，不能作为确定性的正式生命周期证据。

应改成不会丢唤醒的轻量同步原语或正确注册/复查顺序，并保留现有 barrier 驱动测试。实现者可自主选择 `watch`、semaphore、
oneshot 或正确使用 `Notified` 等更合适的窄修方案。

## 审查取舍与替用户作出的决定

- **不要求新增生产进程 supervisor/常驻服务管理器。** 本次宏观目标可由可执行服务、startup announcement、正式 typed client 与
  实际子进程测试共同满足；进程所有权和部署监督可保持在调用方/后续部署层。测试 helper 中的 spawn/wait/reap 不必上移成新平台。
- `UnexpectedExit`、`ShutdownTimeout`、`IoTimeout` 当前没有生产映射，不作为独立阻断项；但修复时不得把这些未实际产生的 variant
  写成已经验证的精确能力。异常退出后得到 typed `Connect` 仍属于可接受的基础设施失败。
- 不增加复杂鉴权、可信证明、审计设施、第二套 trace、全 workspace/Bazel 测试或真实模型证据。修复后只需通过共享构建锁运行
  新 crate 的相关测试和必要 lint/fmt，并检查局部修复没有破坏现有 27 项闭环。

## 当前状态与复验门

- **验收状态：不通过（实现存在上述 correctness/functionality 缺口）。**
- **任务目标：失败（当前 HEAD 尚未完整实现预期；属于可局部修复的问题，不代表路线失败）。**
- 执行者应修复三项 finding、补对应定向回归、更新 Plan/WBS/COMPLETED/执行日志中当前过早的 `PASS/已完成` 声明，并提交工作树。
- 复验重点仅为上述三项、原有进程闭环/取消/资源回归、允许写集和文档事实；无需扩大测试或设施范围。
