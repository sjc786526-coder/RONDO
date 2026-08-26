# Plan 089 / M4-W1 Writer Workspace Binding 独立终审

## 结论

- 审查对象：`a88f276338541170c415864dce8dc21acd0f62a7`，规划基线 `adbc33cc16fd1db535759ecd217549c8da54b9b8`。
- 结论：`REVIEW_NOT_ACCEPTED / TASK_TARGET_NOT_YET_COMPLETE / PENDING_REMEDIATION`。
- 主体设计方向、协议入口、exact linked-worktree 校验、默认 cwd/write-root 投影、普通 escalation 双门、cold root resume、
  replacement generation、S/C 查询控制和 fresh 进程链的大部分实现与证据有效；但下列高/中等级问题仍能绕过写边界、破坏事务式
  durability 或使 Durable Team member reload 失效。修复前不得宣告 `M4_W1_PASS / PHASE_4_COMPLETE`，不得整合或推送。

本轮以源码和提交差异静态审查为主，只执行了 `git diff --check` 和 `just --dry-run` 入口核对，没有重跑重型 Cargo、Docker、真实
模型/API、训练或云端任务。

## 阻断问题

### F1 — High：仍有代表 writer 的无约束写路径

1. `RunUserShellCommand` 没有 binding/W1 gate。`core/src/session/handlers.rs:305-329` 直接分发 `/shell`；
   `core/src/tasks/user_shell.rs:205-242` 固定使用 `PermissionProfile::Disabled` 和 `SandboxType::None`。bound writer 因而可以用
   `/shell` 直接写 main、另一 worktree 或任意绑定外路径。
2. bound writer 仅凭 MCP server 自报的 `readOnlyHint: true` 就放行工具（`core/src/tools/handlers/mcp.rs:168-180`），但本地
   stdio MCP server 由普通宿主 `Command` 启动且没有 binding sandbox（`rmcp-client/src/stdio_server_launcher.rs:277-303`）。
   语义提示不能代替写入约束，误标或实际落盘的工具会直接越界。

建议边界：可以选择最小 fail-closed 策略，例如 bound writer 禁止 `/shell`，并在没有实际文件系统约束时禁止本地 MCP 调用；也可用
更契合现有架构的等强执行约束。无需建设 MCP 可信/审计体系。应补真实入口反例，并证明 W 关闭时原行为不变。

### F2 — High：turn-only W1 授权可被长驻进程带过生命周期边界

W1 grant 只保存在 `TurnState`（`core/src/state/turn.rs:255-280`），仅在 unified-exec 启动时合入 profile
（`core/src/tools/handlers/mod.rs:295-308`、`unified_exec/exec_command.rs:269-276`）。`TurnComplete`/`TurnAborted` 清除 active turn
时没有终止该进程（`core/src/tasks/mod.rs:767-825`）；旧 process 可自主继续写，后续 turn 也可经
`unified_exec/write_stdin.rs:72-87` 驱动，而无需再次取得 W1 grant。

此外，binding 失效/replacement/terminal 的 `terminate_all_processes` 先移除记录，ExecServer terminate 又是 fire-and-forget 且丢弃
失败（`core/src/unified_exec/process_manager.rs:1429`、`unified_exec/process.rs:214`）。旧权限进程终止失败时，系统会失去重试句柄并继续
换绑或关闭，与“部分失败/结果未知不得伪报清理完成”不符。

建议边界：让使用 W1 文件权限的进程受 originating turn/generation 租约约束并确认撤销；更窄的实现也可以在 bound writer 的完成、
中断和 abort 边界确认关闭全部 unified-exec。未绑定 Session 的普通后台进程语义不应改变。

### F3 — High：关键 binding append 错误被吞掉，可能错误返回成功

`core/src/session/mod.rs:4063-4070` 的 `persist_rollout_items` 只记录 `append_items` 错误。初始 binding 随后单独 materialize/flush
（`session/mod.rs:1484-1497`、`session/session.rs:1791-1802`），replacement 也只按后续 flush 决定 `Applied`
（`session/mod.rs:2012-2025`）。append、persist、flush 是独立操作；一次 append 失败后，空 flush 可以成功，导致：

- fresh start 返回可执行但 rollout 没有 binding；
- replacement 返回 `Applied`，cold resume 却恢复旧 generation。

建议边界：仅为 durable binding identity 增加/使用可返回错误的窄 append 路径；initial start 必须传播失败，replacement 至少不得在
append 失败时返回 `Applied`。补一次性 append-failure fault test 即可，不要求重做 thread-store。

### F4 — High：replacement 与 turn admission 存在旧 context 竞态

replacement 在 `core/src/session/mod.rs:1933-1938` 只检查一次 idle，然后异步 capture 并换绑。并发 user admission 可先在
`core/src/session/handlers.rs:215-270` 构造旧 binding A 的 `TurnContext`，稍后才在 `core/src/tasks/mod.rs:324-416` 安装 active task。
replacement 可在两者之间把 live binding 换为 B。`run_turn` 的重验只验证 live B，不比较已捕获 context 的 generation/root，之后工具
仍消费旧 A context。这既不是 idle-only replacement，也允许成功换绑后继续使用旧写根。

建议边界：把 replacement idle 判定与 turn admission 放入同一现有串行边界，或在实际安装/执行前拒绝 stale generation context；无需
新增全局锁体系。补可控 barrier 的并发回归，证明换绑与 turn 只能有一个先发生且结果诚实。

### F5 — High：sibling child writer lazy reload 丢失自身 authority roots

bound parent 的 turn config 被收窄为 parent root A。followup/notice 从该 config 发起 lazy reload
（`core/src/tools/handlers/multi_agents_common.rs:188`、`multi_agents_v2/message_tool.rs:86`），
`core/src/agent/control/spawn.rs:396-495` 未把 child 持久化的 `writer_workspace_authority_roots` 恢复到 resume config。
因此 child writer B 在 `thread_manager.rs:2096` 重验时会以 A-only roots 得到 `WorkspaceRootMismatch`。现有 fresh chain 在进程替换后只
resume root，没有触发 bound child 的 lazy reload，未覆盖该合同。

建议边界：resume/member reload 应消费 child 自身已持久化的 authority roots，并继续以当前 permission/trust 重验，而不是继承 parent
的窄 execution projection。补 A-bound root + B-bound child unload/process-replacement + followup lazy reload 的聚焦回归。

### F6 — Medium：两个副作用前 TOCTOU 仍未闭合

1. W1 additional permission 有意保留逻辑 symlink（`sandboxing/src/policy_transforms.rs:19-42`），批准后再把 link 从目标 A 改指 B，
   Linux sandbox 会在启动时按新 target bind（`linux-sandbox/src/bwrap.rs:1582-1625`）。批准对象未固定，授权范围可在审批后改变。
2. tool registry 的 binding 重验发生在 reviewer 等待之前（`core/src/tools/registry.rs:602-660`）；orchestrator 在审批返回后直接运行
   （`core/src/tools/orchestrator.rs:194-281`、`388-460`），没有再次确认 worktree/Git identity、permission target 与 generation。

这两项正是 W1“写入时目标路径、symlink、Git/worktree identity 或权限发生变化时不越界写入”的明确合同。可以选择 canonical target
快照、spawn 前再次验证或其他等强方案；不要求建立通用文件身份审计设施。

### F7 — Medium：fake/offline Publication Critic 组合链未证明 Critic 实际被调用

`app-server/tests/suite/v2/durable_team_full_chain.rs:151-214` 启动了 deterministic fake scorer，但测试只断言最终 publication 结果并在
结束时关闭服务，没有 invocation counter/request 断言。如果 Critic 路径被旁路，该唯一组合回归仍可能通过。

建议为现有唯一 full-chain fake 增加轻量计数或请求记录，并断言预期调用次数；不要新增第二套重型测试。

## 审查者替用户作出的决定

- **接受 incremental 清理**：watchdog 已证明项目达到 `285,001,187,328 B` 主动停止线；执行者确认无 build lock 后只清理了用户
  预授权的 069 `target/debug/incremental/` 精确目录，并记录 `67,847,123,194 B` 前值，未扩大到 deps、其它 cache、087 或训练资产。
  原授权并未把该精确清理限定为必须先触发 Windows C: 50GB；该操作不构成验收阻断。
- **接受 canonical full workspace 的基础设施阻断归因**：冻结代码后的唯一尝试在测试前被 rusty-v8 v150.4.0 prebuilt archive HTTP
  404 阻断。它不能记为通过，但不要求机械重跑，也不要求改依赖或启用 V8 source build。
- **接受 8 项既有宽邻接失败的独立归因**：当前证据显示它们在规划基线已经存在且与 089 diff 无关；整改时不要求为其扩大范围。

## 整改与复验范围

执行者可自主选择比建议更干净、与现有架构更契合的实现；硬要求仅是关闭上述语义并避免 W-off/普通单 Agent/共享 workspace 回归。
建议先用聚焦 fault/concurrency/path/lazy-reload 测试边修边跑，打通后再冻结：

1. 跑受影响 crate 的必要测试、fmt、clippy、schema/diff 门禁；
2. 复跑唯一 Critic fake/offline 组合测试；
3. 从 fresh repository/store/worktrees 再完整运行一次正式 app-server OS 进程替换全链。

无需重跑 canonical full workspace 或全部历史矩阵。整改提交完成后，按既定 Codex 跨会话队列重新请求独立验收。
