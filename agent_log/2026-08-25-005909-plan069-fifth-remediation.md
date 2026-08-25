# Plan 069 第五轮 correctness 修复

第五轮独立复验的唯一中等级 finding 确认存在，并在现有 thread-store final close validator 内关闭：recorder shutdown/materialization
后，close 现在同时比较 canonical outer `SessionMeta.session_id`、outer Root `SessionMeta.id` 与 exact inner durable Team marker。任一字段
不匹配均返回 conflict、保留同一 Root owner 且不报告成功；恢复 canonical metadata 后可由同一 owner 完成重试。

邻近回归分别破坏 outer Session ID 与 outer Root ID，同时保持 inner marker 不变；两次 close 均失败并可继续取得 write permit，恢复原
SessionMeta 后 final close 成功。该修复复用现有 close generation/prepared retry 状态，没有修改 Team 状态机、wait、rollout reader，也没有
新增 registry、审计或通用事务设施。

验证：

- `UV_CACHE_DIR=/home/sjc/desktop/RONDO/eval-data/uv-cache just fmt`、`git diff --check`：通过。
- thread-store outer-lineage 与现有 marker close 回归：2/2 通过；watchdog
  `.codex/build-watchdog/20260825-005758-1000-1700963`，`complete`、退出码 0、`stop_reason=none`，JUnit SHA-256
  `81a11db9209238acb41cb4369b02ba8740c559c9d768287c7f5297484251f0f7`。
- core `durable_team_close_revalidates_marker_before_shutdown_complete`：1/1 通过；watchdog
  `.codex/build-watchdog/20260825-005819-1000-1703109`，`complete`、退出码 0、`stop_reason=none`，JUnit SHA-256
  `f645c29ed51e608456c7a7ab4e42e56a685d6715b9badda339697ce8e95d88d8`。
- 按复验边界未运行完整 workspace、clippy、Docker、真实模型或 GPU；测试结束后 Cargo/rustc/nextest、Docker 容器和 GPU compute 均为 0，
  canonical heavy lock 已释放。

状态：`IMPLEMENTATION_COMPLETE / PREACCEPTANCE_REVIEW_PENDING / FINAL_PASS_BLOCKED_BY_#37198`。未进入阶段 E、未同步 main、未处理
`#37198`、未合并或推送。
