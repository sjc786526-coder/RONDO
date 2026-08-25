# Plan 069 第五轮预验收复验

## 结论

- 审查对象：`5884b141945725091b5c323a6191ded42c7849a4`（`fix(multidev): close durable team failure gaps`）。
- 结论：`REJECTED`。第四轮的 Unknown N/N+1、阻塞 wait 最终复核、bounded marker head 及 close prepare/retry 状态机主体均已正确关闭；但 final close 的 lineage 交叉验证仍漏掉外层 Session/Root identity，剩余 1 项中等级 correctness finding。
- 当前准确状态：`IMPLEMENTATION_INCOMPLETE / PREACCEPTANCE_REJECTED / FINAL_PASS_BLOCKED_BY_CORRECTNESS_AND_#37198`。
- 本轮未重跑 Cargo、clippy 或完整 workspace。两组 watchdog/JUnit 已核对为 `complete`、退出码 0、`stop_reason=none`，分别 2/2 与 29/29 零失败，SHA 与摘要匹配；`git diff --check e5edc4c..5884b141` 通过。

## 阻断 finding

### M-1：final close 只比较嵌套 marker，外层 Session/Root lineage 损坏时仍可报告成功

`RootWriterAuthorityState::validate_close_session_meta` 在 recorder shutdown 后正确重读 canonical metadata，但仅检查
`session_meta.durable_team == Some(expected)`（`thread-store/src/authority.rs:382-404`）。正常 committed read/cold resume 的合同还会同时要求
`SessionMeta.session_id == expected.session_id` 与 `SessionMeta.id == expected.root_thread_id`（`core/src/team/durable.rs:88-103`），因为外层
SessionMeta 才拥有 canonical Session/root lineage。

可达故障是：close 初检通过 → rollout 首行在 final validation 前被替换为 outer `session_id` 或 Root `id` 不匹配、但保留原
`durable_team` 的合法 JSON → final validation 通过并移除 live owner → handler 发出 `ShutdownComplete` → 新进程恢复时必然
`IdentityMismatch`。这仍会把不可恢复的 close 伪报为成功。

修复只需让现有 final validator 同时比较 outer Session/Root 与 exact inner marker，并补一条 outer mismatch 的 thread-store 或产品聚焦回归；
无需新增状态、事务、registry 或审计设施。

## 已确认关闭与成立的部分

- recorder shutdown/materialization 后、live entry detach 前会执行 final marker read；缺失 marker 使 close 失败、不发 `ShutdownComplete`，abort 后同一 owner 可在 marker 恢复时跳过第二次 recorder Shutdown 并完成 retry。
- close generation、active-write drain、required marker 注册、abort/drop 清理和 complete 状态转换未发现新的高/中等级问题。
- post-CAS `Unknown(N)` 现在在失败 read/reconcile 期间保留 N/N+1 窗口，typed mismatch 恢复后可接受 generation N+1。
- wait 的 Team/timeout/mailbox 任一正常分支都会在 Completed 前最终复核 durable state；feature-off、合法非 participant 与未消费 wake 语义无回归。
- blocking SessionMeta reader 对解压后的 plain/zstd head 累计限制 16 MiB 与 10 条非空记录；oversized/no-newline、invalid UTF-8 和合法 marker 后坏 tail 均诚实、有界处理。
- JUnit 原始记录准确支持 core close/blocked-wait 2/2，以及 team-state/thread-store/rollout 29/29；现有 close 回归覆盖整文件缺失，但没有覆盖 M-1 的 cross-field mismatch。

## 代用户作出的决策与复验边界

- 当前不接受 069 预验收，不进入阶段 E，不同步最新 main，不合并、不推送，也不处理 `#37198`。
- 只修 M-1：允许在现有 thread-store close validator 与邻近测试内补齐三字段等价验证；无需再次修改 Team 状态机、wait 或 rollout 上限，除非编译直接要求。
- 修复后只需运行新增 outer-lineage mismatch 与直接受影响 thread-store/core close 聚焦门禁，再执行 `just fmt` / diff check；无需完整 workspace 或 clippy。
- 审查中另评估了 recorder Shutdown future 在命令发送后被强制取消的 prepared-flag 窗口。当前 normal Session 产品关闭由独立 submission loop 持续执行，调用方 timeout 不会取消该 close handler；完整 task-cancellation/异常终止矩阵属于 S2，因此本轮不把没有 S1 产品可达证据的该场景升级为新阻断。若以后暴露可取消的直接 shutdown 控制面，再按实际入口收口。
- 本地 `main` 当前为 `d72d109` 且与 origin 同步，`#37198` 仍未进入 main；继续仅形成 069 工作树内的干净本地提交，未经用户批准不 merge/rebase/push/删除 worktree。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败（当前提交仍未完整实现预期；允许在原授权和 Plan 069 边界内继续最后一处窄修后复验）**。
