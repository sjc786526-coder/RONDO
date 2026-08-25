# Plan 077 提交级独立审查

## 结论

审查对象为 `3642b04405bfad5daff3462f9a9f9ef7edd86a9a` 相对 Plan 提交
`9f1e7ed03bf5dabe3e670de219379cf4def1f0f8` 的完整差异。

当前结论为：`ACCEPTANCE_FAILED / TASK_GOAL_INCOMPLETE`。主查询链已经形成，server/protocol、canonical local read、分页、冷态读取、
default-off 和无激活边界总体正确，但仍有 4 个未关闭的中等级 correctness/compatibility finding。Plan 规定独立终审不得遗留
高/中等级问题，因此当前不能给出 `M4_C1_QUERY_PASS`。

- 高等级：0
- 中等级：4
- 低等级：0

## Findings

### M1：In-memory store 被错误接入 canonical persisted SessionMeta read seam

`multidev/codex-rs/thread-store/src/in_memory.rs:760` 从易失的 `histories` / `archived_threads` 返回 `SessionMeta`，并在同文件
`:1044` 覆盖正式 `ThreadStore::read_session_meta`。但 `thread-store/src/store.rs:141` 明确要求该 seam 读取 canonical persisted
`SessionMeta`；不能证明该语义的 store 应保留默认 `Unsupported`。

因此 direct `session/read` 在 debug/in-memory 配置下可以把易失内存内容投影为已认证 identity/storage；如果同一 `codex_home` 恰好
存在相同 lineage 的磁盘 snapshot，还会把易失 metadata 与持久 snapshot 拼成 `Available` view。locator list 已正确 fail-closed 为
`Unsupported`，direct read 却绕开了同一边界。

处理要求：in-memory store 对 formal direct metadata read 同样 fail-closed；删除该 override 或明确返回
`ReadSessionMetaError::Unsupported`，并把相邻测试改成验证 direct read 不会认证易失状态。无需新增 store registry 或可信设施。

### M2：客户端会把非法 Team projection 组合安装为 fresh 并推进 high-water

`multidev/codex-rs/app-server-client/src/durable_session_query.rs:624-658` 的 list validation 只拒绝
`Available + team=None` 和 `team=Some + root=None`；同文件 `:692-718` 的 read validation 也只有单向检查。两条路径均未拒绝：

- `Incomplete`、`Unavailable` 或 `Unsupported` 却携带 `team=Some`；
- `team.viewer.thread_id` 与 top-level canonical Root 不同；
- `team.viewer.role` 不是 Root。

随后 `:421-425` 和 `:475-485` 会推进 generation/fingerprint high-water、安装整份 projection 并标为 `Fresh`。当前合法 server
在 `app-server/src/request_processors/durable_session_query.rs:398-418` 确实不会产生这些组合，但 formal client 已承担 response/Root/
whole-view validation，不能把可直接检测的矛盾状态变成当前事实。

处理要求：在 list/read staged apply 前 fail-closed 校验 `team` 与 `Available` 的对称一致性，并校验 viewer 是同一 canonical Root 且角色
为 Root；拒绝时不得部分推进 Root/high-water/projection，保留 stale/absent 语义。补 list/read 两侧的聚焦回归即可，不需要通用
attestation。

### M3：两个独立 feature 同时启用时，formal query 会整体遮蔽 C0 control

`multidev/codex-rs/tui/src/chatwidget/slash_dispatch.rs:387-398` 和 `:697-710` 只要 `DurableSessionQuery` 为 true 就无条件发送 formal
query event。两 gate 同开时，原 C0 `track`、`unarchive`、`detach` 等命令都会进入 formal parser 并失败，C0 control event 不再可达；
`tui/src/chatwidget/tests/slash_commands.rs:149-155` 还固化了全量 query precedence。

这违反 Plan 硬约束 6：C0 可以保留在原独立 experimental gate 下，但 query 拆分不得改变其产品语义。只启用 query 时隔离 control
是正确的；问题只在用户明确同时启用两个独立 gate 时出现。

处理要求：两项能力同时显式启用时都必须可达，不能用全局优先级静默遮蔽其中一个。可以按无歧义命令形状路由、增加清晰的 query/
prototype 子命名空间或采用更好的等强设计；具体命令语法由执行者决定。补双 gate 共存和 query-only 不暴露 control 的聚焦回归。

### M4：Team authored 文本可以伪造结构化 TUI 状态行

Team summary/label 只做长度 clamp，不移除换行或控制字符：`multidev/codex-rs/team-state/src/model.rs:40-55`、
`team-state/src/store.rs:244-265`。正式 renderer 在 `tui/src/durable_session_query.rs:200-220` 将 participant label、author label 和 summary
原样嵌入结构化状态文本，随后 `tui/src/app/durable_session_query.rs:242-248` 对整体 `.lines()` 拆分为独立 history lines。

例如 summary 中的换行加 `operations: ...` 会显示成新的无字段前缀状态行；其他控制字符也没有展示边界。这样不会修改后端事实，但会让
正式查询 UI 对事实边界产生误导，且现有 snapshot 只覆盖单行 authored 文本。

处理要求：仅在结构化 query renderer 的 authored scalar 展示边界做小而明确的单行/control normalization，并补 multiline/control
渲染回归。不要修改 canonical Team State，也不要建设通用内容审计或可信体系。

## 已核对且通过的部分

- 104 路径 write set 与执行日志一致；没有 WBS、Cargo/Bazel manifest/lock、根 README、其他 Plan/日志或删除项。
- stable v2 `session/list` / `session/read`、默认关闭 feature、schema、app-server README 与生成导出一致。
- state DB 只作为 bounded locator；local ThreadStore 路径会读取 canonical `SessionMeta`，再与 marker 和同一完整 checksummed snapshot
  交叉验证。snapshot generation、完整 payload fingerprint 与 Team revision 分轴保留。
- server list/read 没有 writer authority、repair、resume/load、Team mutation、Agent/model/tool/API 或 control 调用；cold restart、归档、
  child/mismatch、损坏/缺失和无外部请求有公共 RPC 覆盖。
- cursor 绑定 active/archive source；无 source generation 时保守 `SourceChanged`，预算和错误不会冒充 complete。
- 客户端 ticket/connection/attachment、Root 绑定、list/read high-water 原子 staging、迟到响应、disconnect/lag/stale、TUI 后台 timeout、
  分页和 archived 可达性在上述 M2 之外未发现问题。
- `git diff --check` 通过；没有 `*.snap.new`、`*.rej`、备份残留。8 个相关 JSON/schema 可解析，两个 precomputed zstd export 完整。
- 执行日志中的最终 JUnit 18/18 与 46/46、哈希、资源值、285GB stop 和 13 个 incremental hash 清理记录可复核；失败与未运行项没有
  冒充通过。

## 替用户作出的决策

1. 不要求为本轮审查重跑 workspace `just test`，也不以替换 V8 archive、关闭 sandbox、源码构建 V8 或升级依赖规避既有 404；这些
   都超出 077，且不能提高当前四项 finding 的判断质量。
2. core/protocol 宽轮的代理/mock 环境失败不记为通过，但不作为 077 的新增 blocker；已有聚焦证据足以支持未受 finding 影响的主链。
   不要求重跑该宽轮。
3. 修复后只需要覆盖直接因果面的聚焦回归，不要求 app-server/client/TUI workspace 全量或新建 E2E/审计平台。任何会读写 Rust target
   的命令仍须由执行者按 Plan 提交精确批次，等待用户额外明确批准和人工调度；本次审查没有授予重型命令权限。
4. 077 与 078 的 shared-file 收敛和 query/lifecycle 兼容验收继续留给后整合者，不作为当前独立分支提交级 blocker；但四项 finding
   必须先在 077 分支关闭。
5. 双 feature 共存的产品原则确定为“两个显式 opt-in 都可达且无静默遮蔽”；具体无歧义路由可由执行者选择更优方案。TUI authored
   文本处理只放在结构化展示边界，不上升为全局存储清洗或可信系统。

## 验证边界与下一步

本审查只执行源码/测试/生成物静态核对、`git diff --check`、JSON parse、zstd integrity 和 worktree 状态检查；没有运行 Cargo、测试、
clippy、fix 或 schema generator，也没有写共享 target。

执行者应在原 077 worktree 内窄修四项 finding、补直接回归、按重型审批门取得必要验证授权并本地提交，再通知本会话审查者复验。
在四项中等级问题关闭前：验收不通过，任务目标未完成。
