# Plan 089 / M4-W1 首轮整改复验

## 结论

- 复验对象：`e191a958a38bb0310ae66f5e2ee887b53bbd1a7d`，首轮审查提交 `cec193c`。
- 结论：`REVIEW_NOT_ACCEPTED / TASK_TARGET_NOT_YET_COMPLETE / PENDING_NARROW_REMEDIATION`。
- F1、F4、F5、F6、F7 已关闭；F2、F3 仍有直接可达缺口，并发现一项与本轮 confirmed revoke 接线相关的 durable close 顺序回归。
  下列问题均可在现有 PTY/unified-exec、Session settings、rollout persistence 和 shutdown 接缝内窄修，不要求新增审计、可信或并行状态体系。

本轮静态复验整改 diff，并直接核验了正式 watchdog/JUnit：`20260826-135046-1000-190891` 为 `final_rc=0 / stop=none /
cleanup=none / 1 passed`，JUnit SHA-256 确为 `3c62f83387ccfd3c5eac668e15962d3c6527735d74240b21b224ead35a42b1a8`。
因 Windows C: 只比 50GB 门高约 30MB，审查者没有启动 Cargo，只执行了 `git diff --check` 和只读证据核对。

## 仍需整改

### R2-F1 — High：local unified-exec 的 confirmed revoke 仍会伪报成功

turn completion/abort、replacement、binding invalidation 和 shutdown 已接入 `terminate_all_processes_confirmed`，ExecServer terminate 返回错误时
也会保留 handle；但 W1 binding 只接受 local environment，实际 writer 会使用 local PTY 路径：

- `core/src/unified_exec/process.rs:227-239` 的 local `terminate_confirmed` 只调用无返回值的 `ExecCommandSession::terminate()`，随后无条件
  `signal_exit` 并返回 `Ok`；
- `utils/pty/src/process.rs:219-269` 的 `request_terminate()` 丢弃 `killer.kill()` 错误并取走 killer，`terminate()` 随即 abort wait/output
  tasks；
- `core/src/unified_exec/process_manager.rs:1451-1485` 因此会删除唯一 handle。

kill 失败时，持有 W1 外写能力的本地进程仍可继续运行，而 turn/replacement/terminal 被错误报告为已撤销。现有 fault test 只覆盖 remote
`ExecProcess`，没有覆盖真实 local PTY。

最窄边界：为 PTY local terminate 提供可传播的 kill 结果；失败时不得人工标记退出或移除 manager handle，并保留可重试终止能力。
是否等待退出可按现有 PTY/ExecServer 语义选择等强方案，不要求建设新进程监管体系。补一个 local killer failure/success 聚焦测试。

### R2-F2 — High：Forked binding identity 仍非严格持久，None tombstone 会被冷恢复穿透

1. `core/src/session/session.rs:1791` 的 strict initial 条件只包含 `New | Cleared`。`Forked` 生成的 child
   `ThreadSettingsApplied` 仍在 `core/src/session/mod.rs:1538-1562` 经吞错的 `persist_rollout_items` 写入。显式绑定 B 的 full-history fork
   遇到 append failure 时仍会返回 executable child，但 B identity 没有 durable commit。
2. `protocol/src/protocol.rs:2619` 用 `find_map` 扫描 binding；最新 child settings 若为 `binding=None`，扫描会继续向前找到复制/引用前缀中的
   parent binding A。于是 live 时正确 unbound 的 fork，cold resume 后会错误继承 A。

这直接违反 fork/new/clear 不继承来源 binding，以及首次动作前 durable identity 的合同。

最窄边界：Forked 当前 settings 也必须在返回 executable 前具有可传播错误的持久屏障；resume extractor 必须以最新一条
`ThreadSettingsApplied` 为边界，最新 binding 为 `None` 时立即作为 tombstone 返回无 binding，不能继续回溯。补 bound fork append fault
和 unbound fork cold resume 两个聚焦反例即可。

### R2-F3 — Medium：turn 内 authority/profile 更新不会撤销旧进程和旧 TurnContext 权限

`core/src/session/handlers.rs:104-128` 允许独立 thread-settings update；`core/src/session/mod.rs:1685-1732` 应用新的 permission/profile/
environment 后只刷新 network proxy/MCP。已启动的 W1 进程仍保留旧 OS sandbox，当前 turn 的后续工具也仍持有旧 `TurnContext` profile。
因此权限在 turn 内收窄后，实际写入不一定同时满足当前 permission/sandbox。

可以选择在 bound active turn 期间拒绝 authority-relevant settings 变化，或在同一既有 mutation boundary 内先 confirmed revoke、再应用并让旧
context 失效；只需覆盖 permission/profile/environment/workspace authority 的真实变化，不要把纯 model/personality 设置复杂化。补一条权限
收窄后旧进程/旧 context 不可继续写的回归。

### R2-F4 — Medium：durable close 的 RetainedError 发生在 canonical persistence 已关闭之后

durable Root 在 `core/src/session/handlers.rs:681` 先执行 `live_thread.shutdown()`，随后在 `:712` 才进入可能失败的 bound process confirmed
revoke。revoke 失败时 `:713` abort Team/lifecycle close 并报告 `RetainedError`，但 canonical rollout writer 已关闭，runtime 已不是可以继续
持久 mutation 的完整 retained owner。

最窄边界：在不可逆的 `live_thread.shutdown()` 之前完成 bound process confirmed revoke；失败时 abort close 并保留完整 runtime。成功后再
进入原有 persistence shutdown 与 terminal commit 顺序。补 revoke failure 时 persistence 仍可用、Root authority 未释放的聚焦测试。

## 已接受的整改与证据

- F1：bound `/shell` 已在 unmanaged 执行前拒绝；binding active 时 local/executor stdio MCP 不再启动，W-off 行为保留。
- F4：replacement 与 turn admission 共用 binding mutation 串行边界，stale binding context 在安装/执行前拒绝。
- F5：bound child lazy reload 从同一 settings event 读取自身 binding/roots，并与当前 authority 取交集；撤销时诚实 unavailable。
- F6：W1 target 在 reviewer 前 canonicalize，review 后及每次实际 attempt 前重验 binding 和 physical target。
- F7：唯一 offline Critic 记录真实 packet，正式链断言恰好一次，并核对 actor、target、title、summary、handoff。
- strict New/Cleared append、replacement `Unknown`、remote terminate 失败句柄保留等本轮已完成部分均予以保留，不要求重做。

## 审查者替用户作出的决定

- 接受第二次精确清理 069 `target/debug/incremental/`：执行者是在 watchdog project proactive stop 后、取得指定 queue 批准并确认无
  active build 后执行，记录 `61,233,204,668 B -> 0 B`，未扩大到 deps、其它 cache、087、训练或来源不明资产。
- 接受当前 fresh 正式链和 scoped 验证证据；四 crate clippy 被项目主动停止的批次不记为通过，但最终 core scoped clippy 已通过，
  不要求机械重跑完整 clippy/full workspace/历史矩阵。
- 对剩余窄修，先完成源码与轻量静态检查。若 monitored Cargo 首次实际触发 Windows 50GB 门，必须先停止该命令；之后可按用户原始明确
  指令启用仅本任务的 35GB 临时例外继续必要聚焦测试和一次 fresh 正式链，但必须持续记录 C:，若余量快速下降或达到 35GB 立即停止。
  清理仍只限经 watchdog 证明需要、确认无 active build 后的同一 069 `target/debug/incremental/`；不得扩大删除范围。

## 复验范围

整改完成后只需：上述四组聚焦回归、受影响 core/protocol 的必要 fmt/clippy/diff 门禁、唯一 Critic + fresh app-server OS 正式全链一轮。
无需重跑 canonical full workspace、全部 changed-crate 历史矩阵或建立额外审计设施。完成并提交后按既定 Codex queue 再请求复验。
