# Plan 067 M4-A Durable Team Contract evidence snapshot

日期：2026-08-24
性质：形成 M4-A 共同合同时的冻结证据；当前路线与依赖只以
[`doc/WBS/durable-team-runtime.md`](../WBS/durable-team-runtime.md) 为准。

## 1. 基线与调查边界

- RONDO 基线：`main@273042f3f26d8f9a22d774fa72858ebf413c122e`；Plan 067 调查提交：
  `cf568b6c290c99f010350ce8fefb81818d71540b`。
- 主物理仓库 git-ignored 冻结上游快照：`rust-v0.147.0@be6e8eac029b183056b7e4402879f15d2c85f61b`，只读且 clean。
- 官方 `rust-v0.149.1` 对照提交：`ff29a44391deccde0aba0f8390337d7f3c319ea4`。只比较四项指定 PR 的官方
  diff、测试与 tag 中最终形状，不执行 fetch、checkout、回移或完整基线升级。
- Plan 068 仅核对 worktree、branch、HEAD、status 路径及进程/资源元数据；未读取其文件、diff 或设计。

## 2. 当前保证、真实缺口与责任分级

| 设施 | 当前源码事实 | M4-A 责任分级与真实缺口 |
|---|---|---|
| Session/root/child identity | `SessionId` 与 `ThreadId` 当前可无损转换；root/children 共用同一 AgentControl SessionId，新建/清空/顶层 fork 分配新 root，resume 保留原 conversation ID（`protocol/src/session_id.rs:13-31,55-64`；`core/src/session/session.rs:493-502,569-606`） | **直接复用** lineage；同值只是表示事实。缺口是 durable load 时须交叉验证 canonical root，不能用缺失/退化 metadata remint lineage |
| Team identity/state | `TeamInstanceId` 独立标记全部引用；一个 live root tree 共享 `TeamStateHandle`，participant 身份由当前 session 注册（`team-state/src/ids.rs:1-31`；`core/src/agent/control.rs:93-127,153-169`；`core/src/team/mod.rs:35-60`） | canonical 语义**直接复用**，durability **架构内扩展/专用能力**；`TeamStateHandle::default()` 总是新 store，cold root resume 又新建 AgentControl，故当前不能跨进程恢复原 Team（`team-state/src/handle.rs:45-75`；`core/src/thread_manager.rs:993-1025`） |
| V2 graph/residency | graph 只持久 parent/child topology 与 open metadata；cold root resume 恢复身份但不加载 child runtime，residency 是进程内 LRU（`agent-graph-store/src/store.rs:13-59`；`core/src/agent/control/spawn.rs:159-230`；`core/src/agent/control/residency.rs:17-45,80-150,217-231`） | graph/residency **直接复用并窄扩展 reload**；不能替代 Team State、durable backend 或 authority |
| Root active-writer | Local ThreadStore create/resume 对单个 ThreadId 持有跨进程 writer lock；竞争者 conflict，成功 shutdown 最后释放，read path 不取 writer（`thread-store/src/local/writer_lock.rs:17-87,168-189`；`live_writer.rs:25-47,145-188`；`read_thread.rs:32-97`） | **架构内扩展**；当前 guard 是 per-thread 且 Team mutation 完全不检查它。S1 必须让 canonical Root authority 连续覆盖 Team durable commit，不能另建 Team lock/lease/registry |
| Team mutation | participant check 后，进程内 mutex 同步检查不变量并立即返回（`team-state/src/store.rs:230-250,275-328,385-458`；`core/src/tools/handlers/team_tools/update.rs:33-87`） | 当前只证明 live-process atomicity，不证明 durable success、跨进程 single writer 或 owner-loss result；须由 S1 闭合 |
| app-server v2/TUI lifecycle | 已有 resume/fork/archive/unarchive/delete、subscription、TUI clear/switch 入口 | **架构内扩展**投影权威领域结果；不能直接写 durable medium，也不能成为第三份状态源 |
| feature/config | V2 默认关，Team State 默认关；有效 Team 还要求 V2 与 collab tools；已有依赖缺失时拒绝配置的先例（`features/src/lib.rs:1106-1117`；`core/src/team/mod.rs:23-33`；`core/src/config/mod.rs:1364-1391,2922-2926`） | **架构内扩展** opt-in/fail-closed 组合；具体 key、解析顺序和内部子开关未冻结 |
| Git/worktree | 当前提供 cwd/workspace roots、Git repo/worktree 与 status/diff 观察；`.git` linked-worktree 推断不做双向注册/trust 验证（`git-utils/src/info.rs:771-821`） | W0 **直接复用**系统 Git 作价值原型；正式 W1 若获 GO，再按条件扩展 trust/binding。没有现成 managed-workspace runtime |

Local ThreadStore 的真实子进程回归还证明第二 writer conflict、原 owner shutdown 后可接管：
`app-server/tests/suite/v2/thread_resume.rs:261-341`。这支持复用方向，但不证明 Team commit 已被该 authority 覆盖。

## 3. 生命周期与失败证据

- 顶层 fork 新建 AgentControl/root identity，保留原生 `forked_from`；V2 child spawn 的 `none/all/N` 都沿用同一 AgentControl，
  只改变 conversation context（`core/src/thread_manager.rs:1245-1299`；
  `core/src/tools/handlers/multi_agents_v2/spawn.rs:99-139,189-236`）。
- Team 实例 tag mismatch 走 `InstanceReset`，可作为旧引用跨新空 Team fail-closed 基础（`team-state/src/store.rs:243-272`）。
- TUI slash `/clear` 走新 thread，而纯 UI clear、switch、unsubscribe/客户端断开的即时结果只改变展示或附着；零订阅且空闲达到
  延迟阈值后，现行 app-server 会独立尝试 SessionEnd/shutdown、移除 thread 并发出 `thread/closed`
  （`app-server/src/request_processors/thread_lifecycle.rs:349-380,394-449`）。当前实现会在 shutdown 成功前撤掉 bookkeeping，失败/超时
  也可能留下“仍 loaded”与已移除状态的矛盾；第四期必须让该 deferred idle unload 走同一 member unload 或 owner/Team close
  barrier。`AgentControl` 与 Team handle 由 root tree 共享，而 idle unload 按具体 ThreadId 触发；running child 又不满足普通 residency
  unload 条件（`core/src/agent/control.rs:93-116`；`core/src/agent/control/residency.rs:217-232`）。因此只要仍有 descendant 具备
  Team mutation 能力，Root close 就不能完成或释放 authority；实现可以阻止 close，或在同一 barrier 内先安全 quiesce/close
  descendants，但不能先让新 owner 接管。
- 原生 archive 会尝试 subtree，但 descendant 失败可形成部分结果；unarchive 只处理指定 root；delete 顺序执行 store/state 删除，
  均不提供整棵树原子事务（`app-server/src/request_processors/thread_processor.rs:1465-1542,1772-1805`；
  `thread-store/src/local/archive_thread.rs:12-51`；`app-server/src/request_processors/thread_delete.rs:31-76`；
  `thread-store/src/local/delete_thread.rs:42-94,113-175`）。共同合同因此要求诚实 partial/unknown，而不新增补偿平台。
- 当前 session shutdown handler 即使 live-thread shutdown 失败仍可发送 `ShutdownComplete`（`core/src/session/handlers.rs:622-666`）；
  archive/delete 路径也可能在 shutdown 失败后继续。它们是 S2/消费包必须修复的 correctness gap，不能提升为 durable close 保证。
- 完整进程退出由 OS 释放 writer，不等于存活进程内 session task/shutdown 失败；后者必须保留 closing/failed 和唯一可重试对象。
- durable marker/backend 缺失、损坏、版本不兼容、lineage/instance mismatch 均没有可接受的空 Team fallback；只有可独立验证的
  兼容部分可显式只读降级。

## 4. 四项官方上游候选

| PR 与 exact head | 官方实际增量与当前 RONDO 缺口 | 2026-08-24 决定 |
|---|---|---|
| [#37847](https://github.com/openai/codex/pull/37847) `4996cf05af6e96e03d0d997681e7db85bce04deb` | V2 residency reload 把 inherited environment 带回 StartThreadOptions，并有 eviction/reload 回归；当前 `core/src/thread_manager.rs:1706-1733` 已携 snapshot 却未传入 options | 独立窄适配，M4-S2 消费并在其 PASS 前进入主线；不承担 durability 或 W binding |
| [#37198](https://github.com/openai/codex/pull/37198) `547080e4d690cdeea12f427a8d9c5165928821ed` | local read 以非空 persisted cwd 覆盖 legacy rollout cwd、校验 rollout path 并重算 permission profile；当前 `thread-store/src/local/read_thread.rs:64-76,129-154` 无 overlay，既有 `:1028-1116` 测试反而固定 rollout cwd | 独立窄适配，M4-S1 消费并在其 PASS 前进入主线；read/list cwd 不替代 live execution/binding 验证 |
| [#39616](https://github.com/openai/codex/pull/39616) `bc3545b805de6e91a11b88114fe1673b678633ca` | 验证 `.git` 类型/大小、gitdir/backlink、commondir、registered checkout 与 main ownership；当前 RONDO 只做单向文本推断，且缺新增 trust/path-native helpers | 条件延期，不阻塞 W0。仅在 W0 binding GO 且 W1 消费 linked-worktree project trust 时按 RONDO 边界适配，并在 W1 开始前进入主线 |
| [#39153](https://github.com/openai/codex/pull/39153) `539a09cb28ca1ded4278c6d54716abbacab42428` | resume/fork 恢复 approval/reviewer/active permission profile，显式 override 优先；当前 app-server 仅恢复 reviewer（`app-server/src/request_processors/thread_processor.rs:176-194,3455-3476`） | W0 binding GO 后条件适配；不得照搬 invalid profile 静默回退 default，durable binding 应 unavailable/replacement。若 W1 消费，须在其 PASS 前进入主线 |

官方 `rust-v0.149.1` tag 中可见四项语义的后续形状；这只证明候选已进入对照版本，不构成整体升级或可直接 cherry-pick 证明。
两项 W-only 候选不阻塞 S/C。

## 5. 证据边界

- 结论由当前源码、现有测试定义、Plans 038/043/047/048、Plan 065 验收记录、冻结 v0.147.0 快照和四项官方 PR
  primary source 交叉形成。
- 静态证据已足以确定共同边界；未运行 Cargo/Rust、Docker、真实 API/模型、训练、测评、全 workspace、CI 或 PR。
- 未进行 PR ancestry/cherry-pick 测试，未实施任何上游回移。具体介质、schema、crate/module、API/wire、锁/permit、read token、
  snapshot、调用顺序和 fixture 均未选择。
