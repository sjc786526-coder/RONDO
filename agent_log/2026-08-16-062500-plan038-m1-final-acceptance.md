# Plan 038 / Multi M-1 最终验收

## 结论

- 验收对象：`worktree-039-multi-m1-team-world-state` 提交
  `5f7268d3a5e13435ab08970fcca0d280b0bfd17d`，第四轮复验报告提交为 `43986aa`。
- **验收状态：通过。**
- **任务目标：完成。** M-1 的 canonical 团队状态、Event/Version 与双生命周期、Root 唤醒、request-only
  活动投影、有界历史、身份/并发/retry/compaction 边界以及真实 Root/child 产品纵切均已实现并由定向测试固化。
- 成果仍只在任务工作树；未合并、未推送。按任务授权，这不影响实现与验收完成，集成需另行批准。

## 第四轮三项整改复验

1. **二次 `NeedsRoom` 已 fail-closed。** `core/src/session/turn.rs:392-410` 在一次 compaction 后仍无法容纳
   活动投影时，于普通 `run_sampling_request` 之前返回 `ContextWindowExceeded`。真实产品测试断言请求止于
   compaction，没有第三次无投影 sampling。
2. **压缩后稳定协议得到保留。** 投影触发的 current-turn compaction 使用
   `MidTurn + BeforeLastUserMessage { world_state, step_context }`；随后从 replacement history 重取输入并重新渲染。
   产品测试断言压缩后的普通请求同时带 `<team_protocol>` 与 Active World Index。
3. **预算基于附加 metadata 后的请求输入。** pending executed-tool metadata 在捕获投影前完成 attach 与 bound；
   首次 provider attempt 使用这份已计量输入，retry 用同一 cache 从 history 重放且不重复附加。局部单测确认 metadata
   会增加 input token 估算，产品测试确认最终请求只挂载一次。

未发现上述修复引入新的 M-1 功能回归。既有 provider retry 测试仍证明同一逻辑 sampling 复用字节一致的投影。

## 额外核对

- 并发测试 `a_stale_lifecycle_change_racing_a_concurrent_one_loses_cleanly` 改从 producer/worker 活动视图读取结果是
  正确修正：winner 若把 Root 状态置为 `resolved`，该项应退出 Root 活动视图；producer 仍 open，因此作者视图仍能
  验证最终存储状态。该修改没有弱化领域语义。
- 新增 compaction 测试使用本地 summarization 分支；remote/token-budget 变体共享同一
  `InitialContextInjection` 接缝，本轮不要求为每个 backend 复制产品测试。
- 近似 token 估算、24-token framing 与 4k/2k/20% 常量是已知工程取舍；当前实现已覆盖全部已知模型可见组成，
  不要求引入 provider tokenizer 或预算审计体系。

## 独立验证

- `just test -p codex-team-state`：**46/46 通过**，0 skipped、0 flaky。
- `just test -p codex-core -E 'test(/team_world_state/) + test(only_verifiable_sessions_get_a_team_identity) +
  test(attempted_tool_metadata_counts_against_the_request_budget)'`：**11/11 通过**，3329 skipped。
- 两组仅各运行一次，均通过仓库共享构建锁与 cgroup 看门狗；最终 project 约 83.0 GB、target 约 53.2 GB，未触发停止。
- `git diff --check`：通过；worktree 在写入本报告前干净。
- 未重复执行广口径 core/rmcp、全 workspace、Bazel、Docker、真实 API 或本地模型。执行者报告的 fmt/fmt-check/scoped
  fix 已通过；历史 85 项宽门禁失败仍只作为前轮“无新增失败”证据，不在本轮重新归因。

## 替用户作出的决策

1. 接受一次 compaction 后仍无空间即 `ContextWindowExceeded` 的 fail-closed 行为；不增加重复压缩循环或新恢复设施。
2. 接受 current-turn compaction 复用既有 mid-turn initial-context 接缝；不为 remote/token-budget backend 增加重复测试。
3. 接受仓库现有近似 token 估算与预算常量；不建设精确 tokenizer、预算审计或可信体系。
4. 接受并发测试改从作者活动视图读取；这是修正错误视图假设，不是降低断言强度。
5. 保持 `team_state_enabled` 默认关闭、Root 全队/member 已授权 Event 的最小权限、独立 `wait_agent_enabled` 等既有决定。
6. Bazel 与上一轮未复现 flaky 继续作为非阻断未验证/观察项；不补跑重型宽门禁。

没有遗留事项需要用户在 M-1 实现层面作决策。下一步仅是经用户批准后把已验收工作树集成到 main；本报告不执行
合并或推送。

## 交付状态

- 本次只新增验收报告并同步 M-1 专用 WBS 当前状态；未修改实现、ExecPlan、顶层 `doc/WBS.md`、
  `doc/WBS-COMPLETED.md`、main 或 L6 工作树。
- 验收提交 `5f7268d` 未合并、未推送；工作树将在提交本报告后停止，等待用户决定集成。
