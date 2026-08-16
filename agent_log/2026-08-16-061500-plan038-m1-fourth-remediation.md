# Plan 038 / Multi M-1 第四轮审查整改

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/039-multi-m1-team-world-state` ｜ 基线提交：`43986aa`
｜ 审查报告：`agent_log/2026-08-16-055500-plan038-m1-fourth-revalidation.md`

## 结果

第四轮报告的三项问题均已对照产品控制流确认属实，并在既有 turn/projection 接缝内完成窄修：

1. 第二次 `NeedsRoom` 不再 warning 后盲采样。一次 compaction 后仍无空间时，turn 在普通 provider sampling 前以
   `ContextWindowExceeded` 显式失败；不重复压缩，也不把活动团队伪装成空闲。
2. 团队投影触发的压缩改为当前 turn 的 `MidTurn` + `BeforeLastUserMessage` 语义。压缩后的首次普通 sampling 同时
   保留 `<team_protocol>` 稳定协议和重新生成的 Active World Index。
3. pending executed-tool metadata 在投影预算前挂载并 bound，首次 attempt 以最终输入计算余量；同一 retry cache
   传入 sampling retry loop，首轮不重复挂载，retry 重取历史时仍复用相同 metadata 与投影快照。

实现没有增加新恢复循环、审计设施或精确 tokenizer。既有近似 token 估算、4k/2k/20% 预算策略保持不变。

## 回归覆盖

- `no_room_compacts_before_sampling_instead_of_sending_a_projectionless_request`：窗口定为 18k，真实请求顺序为
  opening sampling → compaction → 同时带稳定协议和活动投影的 sampling。
- `a_request_that_cannot_carry_the_view_even_after_compaction_fails_the_turn`：9k 窗口下只允许 opening sampling 与
  compaction，请求数在 compaction 处停止并收到 context-window 错误。
- `the_measured_request_carries_attempted_tool_metadata_exactly_once` 与
  `attempted_tool_metadata_counts_against_the_request_budget`：分别固定真实请求的单次挂载和预算估算行为。

调试时 18k 用例首次失败，是测试 helper 只读取 developer message 的第一个 content；实际请求的第二个 content 已含
`<team_protocol>`。helper 改为遍历全部 content 后用例通过，产品代码无需为此调整。

领域门禁第一次运行时，`a_stale_lifecycle_change_racing_a_concurrent_one_loses_cleanly` 首轮越界、nextest retry 通过。
原因是当竞态赢家把 root state 设为 `resolved` 后，该 Event 正确退出 Root 活动视图，测试却仍用 Root view 读取
`events[0]`。改从 producer 仍为 open 的作者视图验证存储结果；复跑 46/46 干净通过。这是测试视图选择错误，未修改
领域行为。

## 验证

| 命令 | 结果 |
|---|---|
| `just test -p codex-core -E 'test(/team_world_state/) + test(only_verifiable_sessions_get_a_team_identity) + test(attempted_tool_metadata_counts_against_the_request_budget)'` | **11/11 通过**，3329 skipped |
| `just test -p codex-team-state` | 修正测试视图后 **46/46 通过**，0 skip、0 flaky |
| `just fmt` / `just fmt-check` | 使用工作树 `.codex/uv-cache` 后通过 |
| `just fix -p codex-core -p codex-team-state` | 通过，最终无 warning |
| `git diff --check` | 通过 |

所有 Rust 门禁均通过仓库共享构建锁和 cgroup 看门狗；最后一次记录 project 约 81.8 GB、target 约 53.4 GB，未触发
资源停止。全局代理变量在 wiremock 测试中按既有做法剥离。首次 `just fmt` 因默认 UV cache 为只读而失败，改用工作树
内受控缓存后通过，未修改全局配置。

## 未运行与交付边界

- 未重跑广口径 core/rmcp、全 workspace、Bazel、Docker、真实 API 或本地模型；第四轮仅修改上述接缝，定向门禁足够。
- 未修改顶层 `doc/WBS.md` / `doc/WBS-COMPLETED.md`，不覆盖 L6 并行工作；M-1 子 WBS 仍保持“待复验”。
- main 与 L6 工作树未修改；本工作树提交后不合并、不推送，等待独立复验。
