# Plan 069 独立预验收审查

## 结论

- 审查对象：`42600466fe349639b1bfcfc76b8fe15884a7c472`（`feat(multidev): persist durable team sessions`）。
- 结论：`REJECTED`。发现 1 项高等级、7 项中等级 correctness finding；当前不能认定 `IMPLEMENTATION_COMPLETE / PREACCEPTANCE_COMPLETE`。
- 当前准确状态：`IMPLEMENTATION_INCOMPLETE / PREACCEPTANCE_REJECTED / FINAL_PASS_BLOCKED_BY_CORRECTNESS_AND_#37198`。
- 本轮没有重新运行完整 workspace 或其他重型测试。已核对提交边界、现有 JUnit/执行日志、关键产品路径与测试覆盖；`git diff --check 8535caa..HEAD` 通过，069/main 均无既有未提交改动。

## 阻断 finding

### H-1：非规范化 JSON 字节比较会让正常多成员 Team 的 cold resume/reconcile 随机失败

`TeamStore` 的 `participants`、`published_facts_through` 和 `WakeLedger` 等包含普通随机序 `HashMap`，但
`team-state/src/handle.rs:309-326` 与 `:435-468` 把独立反序列化后的 store 再次 `serde_json::to_vec`，按原始字节判断同 generation
是否相同。语义相同的 map 可以输出不同键序。

可达路径是：Root 与 child 已提交 → 新进程 `resume_durable` 首次 decode → Session 末尾幂等注册 Root → no-op verify 再次 decode →
键序不同被误报为 `state changed without advancing its generation`。同 generation reconcile 也有相同问题。现有 cold-resume 测试只有
单个 Root participant，没有覆盖真实多成员状态。

修复应采用完整领域等价或确定性 canonical representation；不能继续比较含随机序 map 的 JSON 字节。至少补 root + child，并带 wake/
retry 状态的 no-op cold resume 与 reconcile 回归。

### M-1：snapshot 同时充当唯一 durable marker；状态缺失时关闭态会把 durable Session 当成新空 Team

`core/src/team/durable.rs:52-61` 的 durable 探测只是 snapshot path `try_exists()`；`core/src/session/session.rs:838-848` 在 durability 关闭时
也只在 snapshot 仍存在时拒绝恢复。若 snapshot 被删除、丢失或 backend 不完整，原 durable rollout 没有独立、可交叉验证的 durable intent，
恢复会继续使用默认 in-memory Team，并在 `session.rs:1404-1408` 注册出新空 Team。

这直接违反“marker/backend/lineage/state 缺失 fail-closed，不以空 Team 冒充恢复”。修复不要求建设 registry 或可信平台；只需让既有
Session/root lineage 持久记录最小 durable intent/identity，并与 canonical snapshot 相互验证。具体介质和表示由执行者选择。

### M-2：fresh durable Team 的首次成功提交早于可定位 Session/root lineage

`rollout/src/recorder.rs:787-792` 明确延迟新 rollout 文件创建；`InitialHistory::New` 不会在初始化中 materialize rollout。
`core/src/session/session.rs:1396-1403` 却先以 Root participant registration 提交 generation 1 并允许 Session 启动成功。

因此 Session 成功创建后、首个 turn 或 graceful shutdown 之前若进程退出，Team snapshot 已 durable success，但 rollout/`SessionMeta` 尚未落地，
新进程无法通过现有 ThreadStore 定位或证明该 Session/root lineage。现有产品 cold-resume 测试先完成完整 turn，漏掉了这个窗口。

首次 Team success 前必须先建立足以定位和证明 lineage 的持久 Session/root 边界；补“创建成功后立即非优雅退出，再定位、恢复并继续 mutation”
的产品回归。该接缝可与 M-1 的最小 durable intent 一并干净解决。

### M-3：退休重试账本的校验错误冻结了后续合法 Root attention mutation

`team-state/src/store.rs:367-383` 只禁止退休版本再次 `CloseProducer`，仍允许 Root 对退休版本执行 `SetRootState`；`:475-480` 会合法更新
该轴。但 `store.rs:1086-1089` 在每次 durable validation 时要求退休请求当时的 `expected_root_state` 永远等于版本当前状态。

确定性路径是：worker publish（Pending）→ Root retire（账本记录 expected Pending）→ Root 将同一退休版本设为 Resolved。领域 mutation 已合法
构造 candidate，`encode_snapshot/validate_durable` 却报 corrupt，导致该协调无法持久完成。

退休请求的 expected lifecycle 是提交时前置条件，不能与以后允许变化的当前轴比较。应校验不会随合法后续 mutation 改变的退休事实，或保存并
校验提交时快照；补这一条领域 + durable 回归即可。

### M-4：reconcile 会丢失同一进程内仍待确认的 evidence notes

`pending_observations` 按设计不跨进程持久化，但 `team-state/src/handle.rs:337` 在 reconcile 时以 hydrated store 整体覆盖 live store，没有保留
仍有效的短生命周期 pending notes。

确定性路径是：note A、B → 确认 A 时注入 before-write unavailable → `ensure_readable_or_reconcile` → 再确认 A/B 均返回 `None`。after-write
unknown 时 A 可能已成为 committed fact，同时无关的 pending B 仍会丢失。`core/src/team/evidence.rs:379` 的产品路径遇错后直接停止本批，
不会自行补回这些候选。

不要求把 pending notes 持久化。可以在同进程 reconcile 时安全保留并按已提交 fact 去重，或让 retention 路径 reconcile 后安全重试当前批次；
应覆盖 before-write unavailable、after-write unknown 与无关 pending 项。

### M-5：同一 LocalThreadStore 的 delete 可绕过仍在执行的 Root write permit

`thread-store/src/local/mod.rs:284-295` 发现 live recorder 时跳过另取 OS writer lock；`local/delete_thread.rs:157-171` 随后直接移除 recorder并
`detach_owner`。`detach_owner` 只拒绝新 permit，不等待已有 `active_writes` 清零，所以已取得的 Root write permit 仍能在 rollout/lineage 删除后
完成 Team CAS 并返回成功。

这是 authority 扩展引入的可达全局回归，不要求在 069 实现 S2 的 delete 生命周期矩阵。窄修可以让 live recorder 存在时 delete fail-closed；
若选择等待，则必须复用现有 close barrier。补“持有 Root write permit 时同进程 delete 失败且 rollout 保留”的轻量回归。

### M-6：首次 Team commit 返回 after-write unknown 时，初始化清理会释放唯一 Root authority

Root participant registration 是首次 durable commit。若 `compare_and_swap` 已写入但返回 unknown，错误从 `session.rs:1399-1403` 传播到
`:1418-1420`，随后 `LiveThreadInitGuard::discard` 调用 `discard_thread`；`thread-store/src/local/live_writer.rs:204-219` 会 close/remove recorder
并释放 writer authority。此时可能已有 committed snapshot，但启动失败、Team handle 被丢弃，第二进程可以取得 authority。

这与“commit 失败不移除唯一可重试 owner、不提前交接 authority”矛盾，也使计划中“初始化失败清理不会留下 orphan”的结论在 after-write
unknown 情况下不成立。执行者可选择在激活边界内完成可证明的 reconcile/retry，或在仍不确定时保留一个真实可重试 owner；不能把普通 discard
当成该失败的正常关闭。补首次注册的 before-write failure 与 after-write unknown 产品/集成回归。

### M-7：64 MiB snapshot 上限在整文件读入之后才检查

`core/src/team/durable.rs:66-72` 和 `:125-133` 先用 `std::fs::read` 读取整个 snapshot；`team-state/src/durable.rs` 的 64 MiB 上限直到 decode
后才生效。损坏的超大或稀疏 marker 可以先触发巨大分配/OOM，而不是诚实返回 corrupt/unavailable。

这是已有显式 size contract 的失效，不需要额外审计设施。读取前检查 metadata，并用有界读取（上限加一字节）后拒绝即可；补一个稀疏/超限
snapshot 的轻量回归。

## 已确认成立的部分

- 写集未越过 Publication Critic、Plan 070 控制面或四份共享 WBS；未夹带 `#37198`。
- snapshot framing/checksum/version、Root/Session identity 校验、read-only 拒写、Root/child 共用 authority、跨进程 OS writer 排他、write/close
  permit 的主要 RAII 路径和 failed-close 无伪 `ShutdownComplete` 设计总体方向正确。
- 现有记录支持 Team State 146 passed、Thread Store 187 passed、069 聚焦 core/Session 门禁通过；完整 workspace 的 10 项失败归因与执行摘要一致。
  这些证据证明了已覆盖路径，但不能覆盖上述未建模交错和多成员状态。

## 代用户作出的决策与修复验收边界

- 当前不接受 069 预验收，不进入阶段 E，不合并、不推送，也不提前处理 `#37198`。
- 修复应保持 069 原边界：不建设通用审计/可信/registry 平台，不实现 S2 全生命周期或 C0 控制面；具体数据表示和 API 由执行者自主选择。
- 本轮修复后只需运行受影响的 `codex-team-state`、`codex-thread-store`、`codex-core` 聚焦门禁及新增回归，并做一次相称的跨进程/产品 cold-resume
  复验；无需再次运行完整 workspace。若修复改变 common/protocol/schema，再按就近规则做必要生成与聚焦兼容检查。
- 继续保持分支内本地提交；未经用户批准不得 merge/rebase/push/删除 worktree。`#37198` 仍仅阻塞最终 M4-S1 PASS，但当前先由 correctness findings
  阻塞预验收。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败（当前提交尚未实现预期；允许在原授权和 Plan 069 边界内修复后复验）**。
