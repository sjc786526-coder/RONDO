# Plan 069 第四轮预验收复验

## 结论

- 审查对象：`534cfca7720e0a9fa0e662d0b7eba62b6a6b56b5`（`fix(multidev): enforce durable team read boundaries`）。
- 结论：`REJECTED`。上一轮 marker 持续复核、projection 错误传播和 wait 入口错误传播已按正确方向落地，现有聚焦证据也成立；但仍有 4 项中等级 correctness finding，当前不能接受 `PREACCEPTANCE_COMPLETE`。
- 当前准确状态：`IMPLEMENTATION_INCOMPLETE / PREACCEPTANCE_REJECTED / FINAL_PASS_BLOCKED_BY_CORRECTNESS_AND_#37198`。
- 本轮未重跑 Cargo、clippy 或完整 workspace。两组 watchdog/JUnit 已核对为 `complete`、退出码 0、`stop_reason=none`，分别 3/3 与 26/26 零失败；源码级确定性路径足以判定下列未覆盖问题。`git diff --check 249a788..534cfca` 通过。

## 阻断 finding

### M-1：close 只在开始前验证 marker，随后仍可能在不可恢复时报告 `ShutdownComplete`

`TeamStateHandle::begin_close` 只在取得 close barrier 前调用一次 `ensure_readable_or_reconcile`（`team-state/src/handle.rs:449-460`）。之后
`core/src/session/handlers.rs:660-718` 会执行可能较长的 runtime/hooks shutdown、rollout shutdown 和 close complete；
`LocalTeamClosePermit::complete` / `RootClosePermit::complete` 只封闭 authority，不再读取 typed SessionMeta（`core/src/team/durable.rs:231-253`、
`thread-store/src/authority.rs:129-136`）。

若 canonical rollout 在初检后被删除、替换或损坏，已打开的 recorder fd 仍可能成功 flush，且 live-writer shutdown 会把 materialized path 缺失视为
成功。最终 owner/OS authority 被释放并发出 `ShutdownComplete`，新进程却无法定位或恢复该 Team。应在 recorder/owner 仍可重试的最终 close 成功边界
复核同一 typed marker；失败时不得报告完成或丢失 owner。具体顺序与 API 由执行者选择，无需建设新 lifecycle 平台。

### M-2：post-CAS typed marker mismatch 会丢失 `Unknown(N)` 的 N/N+1 恢复窗口

snapshot replacement 成功但第二次 marker 校验失败时，`LocalTeamWritePermit::compare_and_swap` 正确返回 `Unknown`（`core/src/team/durable.rs:181-198`）。
但下一次 reconcile 若 marker 仍为 IdentityMismatch、Conflict 或 UnsupportedVersion，`mark_durability_failure` 会把现有 `Unknown(N)` 改成
`Unavailable(N)`（`team-state/src/handle.rs:280-345,471-501`）。marker 后续恢复后，Unavailable 分支只允许 generation N，磁盘若实际已是 N+1 就永久
conflict，唯一 live owner 无法继续重试。

在尚未成功读取并判定 committed snapshot 前，typed marker 错误同样不能消除 post-CAS uncertainty；恢复后仍须允许精确的 N/N+1 reconcile。
只需收紧既有状态转换并补一条 post-CAS mismatch → 一次失败 retry → marker 恢复的领域回归，不需要新 journal 或补偿系统。

### M-3：wait 建立成功后发生 durable 故障，仍会正常 timeout/completed

wait 入口现在会正确传播 activation/resolve 错误；但 `TeamWakeWaiter::wait` 只在进入循环或收到 `change_tx` 通知后检查 durable wake
（`team-state/src/handle.rs:1167-1177`）。没有 Team 通知时，外层 activity/timeout 分支胜出后直接构造正常结果并发出 Completed
（`core/src/tools/handlers/multi_agents_v2/wait.rs:113-144`），没有最终 marker/snapshot/status 校验。

因此健康 Team 开始 wait、首次检查通过、随后 marker 持续不可用且无 Team change 时，会返回 `Wait timed out`。现有产品回归在 wait 调用进入 handler
之前隐藏 marker，只覆盖入口失败。正常返回前需要一次可线性化的最终 durable read/status 复核；不要求轮询 marker，也不要求严格审计所有瞬时故障。

### M-4：blocking SessionMeta head reader 对损坏或压缩膨胀输入无读取上限

新增 blocking reader 对 plain/zstd 都返回无界 `BufRead::lines()`（`rollout/src/compression.rs:1076-1088`），调用方持续扫描到 SessionMeta 或 EOF
（`rollout/src/list.rs:1295-1302`）。超长无换行首记录或压缩膨胀输入会在每次 committed read/CAS marker 复核时无界分配或长时间阻塞，而不是按
Plan 069 已采纳的 lineage 有界读取边界 fail-closed。新增测试只覆盖合法首行后的 invalid UTF-8 tail，会在坏 tail 前提前成功。

给解压后的 head/record 设置明确上限并覆盖 plain/zstd oversized 或 no-newline head 即可；可复用现有 rollout line-size 惯例，不建设新的
介质审计设施。

## 已确认关闭与成立的部分

- live owner 的 committed read 与 mutation 已复核 canonical SessionMeta；pre-CAS marker 丢失不推进 generation，CAS 后 marker 失败不再返回 durable success。
- projection 的 activation/reconcile/snapshot 错误会在 sampling 前终止；feature-off、健康非 participant 与健康 idle 仍保留合法空语义。
- wait 在进入 handler 时已存在的 durable unavailable 会明确报错，不再通过 `.is_ok()` / `.ok()` 降级。
- blocking reader 的正常 plain 优先、compressed fallback 与异步 reader 表示语义一致；Root write permit 连续持有既有 writer/OS authority。
- JUnit SHA 与 summary 匹配：core marker-loss/projection/wait 3/3，rollout/thread-store/team-state 26/26，均零失败。它们证明已覆盖路径，但未覆盖 M-1 至 M-4 的场景。
- 069 工作树提交边界未触碰共享 WBS、Plan 070 控制面或 `#37198`。审查期间本地 `main` 已由其他任务推进至 `d941d0a`，但 `#37198` 仍未进入 main；本轮未同步、合并或改写任何并行现场。

## 代用户作出的决策与复验边界

- 当前不接受 069 预验收，不进入阶段 E，不同步最新 main，不合并、不推送，也不处理 `#37198`。
- 4 项修复继续留在 Plan 069 原边界；允许必要的 core/team-state/thread-store/rollout 窄接缝。不得扩建 registry、审计/可信平台、通用事务设施、S2 生命周期或 Plan 070 控制面。
- 普通编译、fixture 和测试问题由执行者自主修复、重跑。修复后只需运行：close 期间 marker-loss、post-CAS typed mismatch 恢复、wait 阻塞后 marker-loss、plain/zstd bounded head，以及直接受影响 crate 的聚焦门禁；无需完整 workspace 或 clippy，除非改动本身产生新的编译/lint 问题。
- 继续只形成 069 工作树内的干净本地提交；未经用户批准不 merge/rebase/push/删除 worktree。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败（当前提交仍未完整实现预期；允许在原授权和 Plan 069 边界内继续窄修后复验）**。
