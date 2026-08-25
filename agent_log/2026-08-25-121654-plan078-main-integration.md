# Plan 078 主线整合

- 用户授权把已验收的 Plan 078 合入本地主工作区并更新文档；本批不含 push，也没有额外重型 Cargo 授权。
- 078 吸收最新 `main@305f904`。三个直接文本冲突按既定符号所有权做加法收敛：`core/src/team/durable.rs` 同时保留 Plan 077
  query read seam 与 Plan 078 统一 snapshot path；`thread-store/src/lib.rs` 同时导出 query errors 与 path helper；
  `thread-store/src/store.rs` 同时保留 query futures 与 ordered archive partial-failure。app-server 路由自动合并。
- 更新 `doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、`doc/WBS-COMPLETED.md` 与 Plan 078 动态状态：记录
  `M4_S2_PASS`，把正式 Session Control/TUI 设为下一项可另行立项的四期必成主线，并保留 M4-W0 条件边。
- 轻量验收：项目内 UV cache 下 `just fmt-check` PASS，staged `git diff --check` PASS；未运行 Cargo build/test/clippy、Docker、
  真实 API/模型、训练、测评或远端操作。合并树 query×lifecycle 聚焦回归因没有追加重型授权而未重跑，转交后续正式 C* 的首批
  获批门禁，不冒充已执行。
- 未改动、stash、覆盖、清理或提交其他工作树；不删除 worktree，不归档分支，不推送。
