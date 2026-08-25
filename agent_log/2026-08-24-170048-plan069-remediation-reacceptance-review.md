# Plan 069 修复轮复验

## 结论

- 审查对象：`0b9f6f8daedf792fc34bf7758c60f6929e8d6047`（`fix(multidev): harden durable team recovery`）。
- 结论：`REJECTED`。上轮 H-1、M-3、M-4、M-5、M-7 及 initial CAS Unknown owner 保留均已正确关闭；M-1 的单边缺失处理和 M-2 的正常成功顺序也已落地。但完整产品边界仍有 3 项中等级 correctness finding，当前不能接受 `PREACCEPTANCE_COMPLETE`。
- 当前准确状态：`IMPLEMENTATION_INCOMPLETE / PREACCEPTANCE_REJECTED / FINAL_PASS_BLOCKED_BY_CORRECTNESS_AND_#37198`。
- 本轮没有重跑完整 workspace、Docker 或其他重型流程。审查采用提交 diff、产品路径、回归源码和已有 watchdog/JUnit 原始证据；已有记录真实支持 team-state 153/153、thread-store 188/188、core 3/3 + 7/7、产品 cold-resume 2/2 通过，但这些切片没有覆盖下列边界。

## 阻断 finding

### M-1：durable intent 与 snapshot 共置；整个 Team backend 丢失时，关闭态仍以空 Team 冒充恢复

新增 `.team-lineage` 与 `.team-state` 都位于同一个 `codex_home/team-sessions/v1` 后端（`core/src/team/durable.rs:31-42,144-154`）。
`durable_team_artifacts_exist` 也只检查这两个共置文件（`:68-80`）。因此一个已经成功提交 Team state 的 Session 在进程退出后，若整个
`team-sessions/v1` backend/目录丢失而 canonical rollout 仍在，两项读取都会得到 `None`。

随后以默认 durable-off 配置恢复时，`session/session.rs:856-866` 的 guard 为 false，初始化会继续进入 `:1480-1484` 的 non-durable Root
注册，创建新的空内存 Team。durable-on 路径会因缺 lineage 拒绝，但默认关闭路径仍违反计划对“backend/lineage/state 缺失时不得创建空 Team”
的明确要求，也没有真正把 durable intent 锚定到既有 Session/root lineage。

修复不需要 registry、审计或可信平台。只需让最小 typed durable intent 成为 existing Session/root lineage 中独立于 Team backend 的持久事实
（或采用等强的独立锚点），再与 snapshot backend 交叉验证；补“成功 durable Session 保留 rollout、整体移走 Team backend、durable-off
resume 必须拒绝且不注册空 Team”的聚焦回归。

### M-2：`SessionSource::Unknown` 可让 durable Root 假成功，却没有 generation-1 snapshot

产品 app-server 接受 `--session-source unknown`（`app-server/src/main.rs:38-45`；`protocol/src/protocol.rs:2879-2893`）。`Unknown` 不属于
`is_non_root_agent`，因此被 `session/session.rs:788-805` 当作 Root 进入 durable activation；但
`team_participant_identity(Unknown)` 明确返回 `None`（`agent/control.rs:900-921`）。

fresh 路径仍先物化 rollout 并写 `.team-lineage`（`session.rs:1419-1433`），随后 `try_register_team_participant` 对 `None` 直接返回成功而不做
mutation（`agent/control.rs:205-217`），最终 `session.rs:1435-1487` 返回成功 Session。结果是：没有 Root participant、没有 generation-1
snapshot，Team capability 只会得到 `UnknownParticipant`；进程退出后 cold resume 又因 lineage-only 缺 snapshot 被拒绝。

这是正常产品入口可达的 durable activation 假成功。应在任何持久副作用前要求 durable Root 具备可证明的 participant identity，或采用与现有身份
策略等强的处理；无论具体路线，成功 activation 必须证明 generation-1 Root snapshot 已提交。补一条 fresh Unknown durable activation 必须明确
失败且不留下半激活 artifact 的聚焦回归即可。

### M-3：lineage 发布结果不确定时仍释放唯一 owner，并留下不可继续的半激活 Session

`write_lineage` 在 atomic persist 后执行父目录 `sync_all`；若文件已经到位但目录同步失败，它返回 `Unknown`（`core/src/team/durable.rs:328-341`）。
`initialize_durable_team_lineage` 原样传播该错误，Session 初始化在 `session/session.rs:1427-1433` 使用 `?` 直接退出，随后 `:1488-1496`
discard live persistence/Root owner。

此时 matching lineage 可能已经可见，但 generation-1 snapshot 尚未尝试。之后 fresh activation 因 artifact 冲突而拒绝，resume 又因 snapshot 缺失
而拒绝；没有可到达的产品重试对象。当前 degraded-owner 逻辑只覆盖首次 snapshot CAS 的 Unknown/Unavailable，没有覆盖此前的 lineage publish
Unknown，因而“初始 unknown 保留 owner”的结论还不完整。

可在同一 Root owner 内有界读回并验证 lineage 后继续，或保留能重试 lineage 初始化的 degraded owner；实现路线由执行者选择。只需加入
“lineage rename/persist 已发生、目录 durability 返回 Unknown”这一条故障回归，不必建设通用恢复日志。

## 已确认关闭的原 finding

- H-1：`same_durable_state` 对全部持久字段做领域等价，随机序 `HashMap` 不再参与 JSON 字节比较；多成员/wake/retry 跨进程路径已有覆盖。
- M-1 的单边场景：lineage-only、snapshot-only、identity/version/corruption 均会 fail-closed；本轮 M-1 指向的是两项共置 artifact 同时随 backend 丢失。
- M-2 的正常成功顺序：fresh Root 已先 materialize rollout，再写 lineage，最后提交 generation 1；立即非优雅退出的产品回归成立。
- M-3：retire retry 已绑定历史 Retire change，不再冻结后续合法 Root state。
- M-4：跨 generation reconcile 会去掉已成为 Fact 的 observation，并保留其余同进程 pending 项；同 generation 不覆盖 live pending。
- M-5：单删/批删均在任何副作用前整批拒绝同 store live writer，shutdown 后才允许删除。
- M-6/新增 Unknown 窗口：snapshot CAS Unknown 的读回、同 owner reconcile 与连续 Unavailable 已保留 `N/N+1` 窗口。
- M-7：lineage/snapshot 的产品读取入口在分配前检查 regular-file 与大小，并最多读取上限加一字节。

## 代用户作出的决策与复验边界

- 当前不接受 069 预验收，不进入阶段 E，不合并、不推送，也不提前处理 `#37198`。
- 三项修复继续留在 Plan 069 原边界。允许为独立 durable intent 做必要的 existing Session/root lineage 或 protocol/core 接缝窄改；不得借此建设
  Session registry、审计/可信平台、S2 生命周期矩阵或 Plan 070 控制面。
- 普通编译、测试或 snapshot 问题由执行者自主修复重跑。修复后只需运行直接受影响的 core/Session 产品回归，以及实际改到的 team-state、
  thread-store 或 protocol 聚焦门禁；已有未受影响的完整 workspace 证据无需重跑。
- 继续只形成 069 工作树内的干净本地提交；未经用户批准不 merge/rebase/push/删除 worktree。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败（当前修复提交仍未完整实现预期；允许在原授权与 Plan 069 边界内继续窄修后复验）**。
