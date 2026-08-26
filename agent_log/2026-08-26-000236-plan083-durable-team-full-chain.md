# Plan 083 / M4-Z(core) Durable Team 全链执行记录

时间：2026-08-26 ｜ 分支：`worktree-083-m4-z-core-durable-team-closure` ｜ 基线：`75fb51b4b3ea`

## 实质修改

- Durable child spawn/resume 现在先持久化 Open AgentGraph edge，再发布 registry/residency；graph store 缺失或写入失败时 fail-closed，
  并精确关闭、移除尚未发布的 runtime。Durable metadata restore 和 child close 的 graph 读取/写入失败也不再被吞掉。
- Root close barrier 同时检查 persisted Open descendants 与 loaded running descendants。公开 `session/control` 将该可重试阻塞映射为
  typed `ActiveWriter`，卸载但仍可恢复的 child 不再被误当作已关闭。
- 为 V2 collaboration 增加正式 `close_agent`，复用既有 AgentControl subtree shutdown、exact owner retirement 和 Closed edge；没有新增
  第二套生命周期或状态源。
- 修正 Durable Session enum payload 的 JSON schema camelCase，保持 schema 与既有 serde/TypeScript wire 一致，并同步 stable、
  experimental JSON schema 及 precomputed exports。
- 新增公开 app-server v2 全链回归：fresh store 创建 Root/child，child 通过 Team 工具提交事件，非 owner query 读取，真实旧 OS 进程退出，
  新进程恢复同一 Session/Root/TeamInstance 和 committed state，继续 mutation，经历 descendant barrier、显式 child close、owner close、
  archive/unarchive/delete，且 cold query/control 不启动模型请求。

## 调试中关闭的问题

- 初始全链确认 durable graph persistence 原为 best-effort，Root close 只检查内存 registry，恢复后的 unloaded Open child 可绕过关闭证明；
  同时公共 Control 把 busy barrier 归入通用错误，V2 工具面没有终态 child close。这些均按既有 graph、AgentControl 和 Control seam 窄修。
- 既有恢复测试把 manager shutdown 当作正式 Root close；新 barrier 正确拒绝仍有 Open edge 的 Root。测试改为保留 TempDir、精确丢弃旧
  runtime owner，并等待旧 ThreadStore 析构释放 writer，真实区分进程替换与领域关闭。干净退出测试则显式 close child edge。
- schema 生成器现有 `just write-app-server-schema` 指向不存在的 Rust bin；本任务没有扩张修复该配方，而是在同一 canonical watchdog 下运行
  仓库既有 ignored schema fixture generator tests，分别写出 stable/experimental 生成物并用 fixture/precomputed 回归校验。
- scoped clippy 发现 resume watcher 最后一次使用的 `agent_path` 多余 clone；改为等价 move 后重跑通过。

## 验证证据

- graph/close 职责层新回归：Nextest `0f10b2f2-19ef-45ba-8034-0cd68fdaa5f5`，`4/4`；S/C 相邻既有回归：
  `0767d48e-d206-425d-9c91-5986829d85db`，`4/4`。
- schema stable 生成轮 `6033f8f7-9a02-4850-b2dc-ac290fefbfb7`、experimental 生成轮
  `22c4676d-e069-45b9-a3cb-3941936e2ef1` 均通过；最终宽聚焦轮 `99a78c43-ab72-4b33-abff-45d46411e3df` 为 `30/30`，覆盖
  core、app-server、protocol、client、TUI、schema/precomputed、fork/crash/query/control/no-replay 邻接面。
- 实际修改的 `codex-core`、`codex-app-server`、`codex-app-server-protocol` scoped clippy 在窄修后通过；watchdog
  `20260825-234928-1000-2065466`。最终 `just fmt`、`git diff --check` 和生成物自审通过，无 `*.snap.new`、`.rej`、`.orig`。
- 候选冻结后，从全新 TempDir、Session/store 完成正式产品全链：Nextest
  `b0d0eadc-5c49-46d8-9e97-310cf35691ea`，`1/1`；watchdog `20260825-235546-1000-2079406`，
  `stop=none / cleanup=none`。该轮使用 fake localhost model server，但 app-server replacement 是真实 OS 子进程；没有真实 API/模型。

## 资源与边界

- 首轮宽门禁前项目/069 target/deps/incremental 为
  `254,311,297,024 / 191,586,164,736 / 137,939,984,384 / 53,007,081,472 B`；Windows `C:` 可用
  `75,166,531,584 B`。按已授权边界仅删除 069 `debug/incremental`，保留 `debug/deps`；清理后为
  `202,245,156,864 / 139,520,024,576 / 137,939,984,384 / 4,096 B`，`C:` 可用 `75,166,420,992 B`。
- 最终项目/069 target/deps/incremental 为
  `241,870,729,216 / 179,236,501,019 / 153,116,631,496 / 24,742,818,339 B`；Windows `C:` 可用
  `75,187,970,048 B`。所有批次均使用共享 target、进程级 270/285/290GB 门限、`CARGO_BUILD_JOBS=1` 和 canonical lock/watchdog；
  未创建第二个大型 target，未清理 deps 或来源不明资产。
- 未运行 full workspace、Docker、真实 API/模型、训练、benchmark、Plan 082、M4-W0/W1、CI/PR、merge、push、发布或其它远端写；
  未读取 `.env.local` 或其它 worktree 的未提交内容。

## 当前结论

执行者候选实现、相称门禁、fresh 正式轮和自审均已完成，当前为 `AWAITING_REVIEW`。`M4_Z_CORE_PASS` 尚未成立，
`doc/WBS-COMPLETED.md` 未更新；最终结论与验收收口由指定审查者负责。
