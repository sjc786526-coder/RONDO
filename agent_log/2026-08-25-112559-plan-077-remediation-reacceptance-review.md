# Plan 077 整改复验

## 结论

复验对象为整改提交 `c14d66143433acc887e7bce1ef6747ccd6574ba5` 相对前次审查提交
`5454c440d3c62fa4714b89bac10a5afee0156095` 的完整差异，并回看 Plan 基线 `9f1e7ed03bf5dabe3e670de219379cf4def1f0f8`
至当前提交的整体边界。

结论：`ACCEPTANCE_PASS / TASK_GOAL_COMPLETE`。前次 4 个中等级 finding 均已关闭，未发现整改引入的新高、中或低等级正确性问题；
可以给出 `M4_C1_QUERY_PASS`。该结论只覆盖 077 独立分支的正式 Session Query 任务，不代表已经完成与 078 的主线整合、merge 或 push。

- 高等级：0
- 中等级：0
- 低等级：0

## Finding 关闭情况

1. `InMemoryThreadStore` 已删除 formal `read_session_meta` override，重新继承 trait 默认 `Unsupported`。已有 volatile thread 的单测和
   app-server list/direct-read 公共场景组合证明：易失 metadata 不再认证为 persisted SessionMeta，也不能与磁盘 snapshot 拼成
   `Available`。
2. app-server client 在 list/read 两侧对称校验 `Available <=> Team`，并要求 Team viewer 等于外层 canonical Root 且 role 为 Root。
   校验发生在 projection、high-water 与 canonical Root map 提交前；新增回归证明非法页不会部分提交前序 Session，旧 projection 保留并
   降为 stale。
3. 双 gate 路由已改为无歧义入口：`/sessions` 在 query gate 开启时固定走正式只读查询，`/session-control` 固定走 C0；仅开启 C0 时
   `/sessions` 继续作为兼容 alias。popup、无参/带参 dispatch、usage 和 refresh 提示保持一致，query-only 不暴露 control。
4. 正式 query renderer 对当前实际展示的 participant label、version author label 与 summary 做单行 whitespace/control 折叠；canonical
   Team snapshot、fingerprint 和存储值不变。恶意换行、ESC/BEL 和 Unicode separator snapshot 不再能伪造独立结构化状态行。

## 证据与相邻回归

- 整改提交精确 23 路径；分支相对 Plan 基线 109 路径。没有新增 WBS、Cargo/Bazel manifest/lock 或根 README 变更，也没有删除项。
- `git diff --check` 对整改差异和完整分支差异均通过；worktree 无 `*.snap.new`、`*.rej`、备份或未知修改。
- 正式整改 JUnit
  `.codex/build-watchdog/20260825-110652-1000-280129/junit-local.xml` 的 SHA-256 实测为
  `80d41f5afe70128ae9c3ae3855d2e975bb7e1b4c17c27ec53fe9f81db3543096`，内容为 8 tests、0 failure、0 error，覆盖四项 finding 的
  thread-store、app-server、client 与 TUI 直接因果面。watchdog summary 为 `run_rc=0`、`final_rc=0`、`stop_reason=none`。
- 三路独立只读复核分别检查 persisted seam、client 原子拒绝、TUI 路由与 renderer，均无 finding。本次审查未编辑实现，也未运行 Cargo、
  测试、clippy、fix 或 schema generator。
- workspace `just test` 的既有 V8 404、core/protocol 宽轮 proxy/mock 阻断和未运行的 Docker/真实 API/模型/CI 不冒充通过；它们不改变
  现有 077 聚焦证据对任务目标的支持。

## 替用户作出的决策

1. 接受现有聚焦整改轮，不重跑 workspace 或 crate 全量，也不为 V8 404、proxy/mock 环境问题引入 077 范围外绕行。
2. 当前 renderer 已覆盖正式查询实际展示的 authored label/summary 字段；不扩展为 canonical 存储清洗、通用 Unicode 内容审计或可信
   展示平台。
3. 077 任务目标在本地分支已完成。078 合入后的 shared-file 收敛与 query/lifecycle 聚焦兼容验收继续由后整合者在最新 main 上执行，
   不把尚未发生的整合当作当前 077 提交级 blocker。
4. 审查报告只提交到 077 工作树；未授权也不执行 merge、push、worktree 关闭或分支重命名。验收通过后不再向执行者发送 queue 消息。

## 当前状态

- 验收：通过。
- 任务目标：完成。
- 交付形态：077 本地分支提交完成，等待用户决定后续整合。
