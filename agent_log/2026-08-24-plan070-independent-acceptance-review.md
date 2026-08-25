# Plan 070 / M4-C0 独立验收审查

审查目标：`f88880b9ae23a430b9e0b63816a32c478977e5ee`

对比基线：`0f3a96be217fa693a933534e8a009519dbfa973a`

结论：**验收不通过；任务目标尚未完成。** 默认关闭的独立 product gate、v2 experimental schema、只读 projection、loaded Root
owner 证明、状态分轴和聚焦测试的主体方向正确，但仍有 3 个高优先级 correctness finding、4 个中优先级 correctness/合同 finding。
修复前不能给出 `M4_C0_PROTOTYPE_PASS`，也不应合并或推送。

## Findings

### P1：真实 response-lost 会让 mutation 永久停在 pending，TUI 无法进入 result-unknown

`tui/src/app/event_dispatch.rs:23-28` 在主 App dispatcher 内直接等待 `/sessions` 命令；
`tui/src/app_server_session.rs:1011-1018,1068-1077` 又直接等待 mutation 的 `request_typed`。remote request 在
`app-server-client/src/remote.rs:637-656` 无 response deadline 地等待 oneshot。若 server 已执行 mutation，但 response frame 被故障注入
丢弃且连接仍存活，future 永远不返回，`apply_mutation_response_loss()` 无法执行，controller 保持 `Pending`，同一 TUI 也无法执行
refresh/detach。这正是 C0 要验证的“可能已提交、响应丢失”场景，不是一般网络审计要求。

现有 `app-server-client/src/experimental_session_control_tests.rs:113-127` 只直接调用状态机 transition，未经过 request 发送、server
可能提交和 response 丢失边界。修复应给 C0 mutation 一个有界、可重复的 attempt completion 语义，使 response 未能确认时进入
`stale + result-unknown`，不自动 replay，随后允许显式权威 read；无需建设通用 timeout/reconnect 平台。必须补真实 AppServerSession /
transport 接缝的故障注入回归，并证明 mutation 只发送一次、TUI 不被永久占住、迟到结果不能覆盖重读后的新状态。

### P1：archived child 被错误标为可 unarchive，可单独恢复 child 而 Root 仍 archived

`app-server/src/request_processors/experimental_session_control.rs:214-225` 已能判定 archived child 不是 canonical Root，并把 identity
provenance 置为 unavailable；但 `:328-332` 只凭 `is_archived` 就把 `unarchive` 标为 Available。TUI 在 fresh read 后只校验该
availability，再通过 `thread/unarchive` 提交 child id。

`app-server/src/request_processors/thread_processor.rs:1785-1793` 不验证 Root，底层
`thread-store/src/local/unarchive_thread.rs:13-89` 会按该 child id 单独移动 rollout 并标记 unarchived。结果是 identity 无法证明且
child-only 的对象可以成功执行 Session 冷态写操作，违反 fail-closed ownership 边界。

修复应在 canonical Root 无法证明时把 Session cold lifecycle 标为 IdentityUnavailable/ChildOnly 或等强拒绝；不修改 Team/Thread
持久介质语义。补 public JSON-RPC 回归覆盖 archived Root+child，证明 child read 不可 unarchive、Root unarchive 仍走既有权威入口。

### P1：state DB 查询失败会被伪报为 authoritative empty discovery

070 只检查 `state_db.is_some()`，随后把 state-DB-only ThreadStore page 无条件标为
`provenance=stateDbPrototype, complete=true`（`app-server/src/request_processors/experimental_session_control.rs:55-88,107-113`）。但既有
state-DB-only 路径在查询失败时于 `rollout/src/state_db.rs:442-447` 返回 `None`，并在 `rollout/src/recorder.rs:462-480` 通过
`unwrap_or_default()` 变成成功空页。因此 DB 存在但不可读时，C0 会显示完整空集合，而不是 `complete=false/unavailable`。

修复必须让 C0 自己观察到本次权威 read 是否成功，并在失败时 fail closed。优先在 C0-owned app-server/read seam 内完成，不修改
`thread-store/`、`rollout/` 或 069 所有权；若现有 seam 无法诚实区分，必须先报告所有权冲突，不能继续把空页当成功。补一个 DB query
failure 公共 JSON-RPC 回归，不能只测试 `state_db=None`。

### P2：Thread page 在过滤 child 前分页，TUI 会把非空 Session 集合显示为 `sessions: none`

`app-server/src/request_processors/experimental_session_control.rs:66-88` 先按默认 25 条分页全部 Thread，`:90-105` 才过滤 child。若一个
较旧 Root 前存在至少 25 条更新的 child，第一页会得到 `data=[]`、`nextCursor=Some(...)`、`complete=true`。TUI
`app_server_session.rs:913-923` 固定请求默认第一页且没有 cursor/follow-up 路径；`tui/src/experimental_session_control.rs:85-90`
据空 data 和 complete 直接显示 `sessions: none`。

修复可在 server root-filter 后继续有界取页，也可让 TUI 受控追页；具体策略由执行者选择。无论路线如何，只有 source 真正耗尽时才能
显示 none，且不能引入无界扫描。补“较旧 Root + 至少一个完整 child page”的 public JSON-RPC/TUI 回归。

### P2：默认关闭时仍可能展示 Session prototype 启动提示

`features/src/lib.rs:1121-1128` 虽把 feature 默认关闭，却注册了非空 Session announcement。TUI
`tui/src/tooltips.rs:35-48` 会把全部 Experimental announcement 无条件加入全局随机 tooltip 池，不查看当前 feature set；因此未 opt-in
用户也可能看到原型宣传。这违反“关闭态无用户可见变化”，现有 slash lookup/dispatch 测试没有覆盖该路径。

修复应使未启用状态不向全局 tooltip 池贡献 Session 文案，并补确定性测试；无需改造整个 tooltip 系统。

### P2：上一次 mutation certainty 会被错误归因给后来未提交的另一操作

权威 read 成功后，client 有意保留上一 mutation 的 historical certainty
（`app-server-client/src/experimental_session_control.rs:227-235`）；这本身是诚实的，因为 read 不能伪造旧 mutation receipt。但 track 和
unarchive 都可能在 `begin_mutation()` 前因 fresh/availability/id preflight 失败
（`tui/src/app_server_session.rs:987-1010,1046-1067`）。App 对任何错误都读取全局旧 certainty，并使用当前 operation 名渲染
（`tui/src/app/experimental_session_control.rs:74-105,151-183`）。

复现：track response unknown → 权威 refresh 成功 → 对未归档 Session 执行 unarchive。后一次没有发送 RPC，却会显示
“unarchive result is unknown”。修复应把本次 operation attempt 是否提交及其 certainty 与历史状态区分；可以采用 typed per-attempt
结果或其他等强方式，不要求抹掉诚实的 historical unknown。补跨操作回归，证明 preflight failure 永远显示 not submitted，不能继承旧
operation 的 rejected/unknown。

### P2：ChildOnly 拓扑随 query id 得出矛盾结论，且 v2 optional 字段违反局部 wire 规则

`app-server/src/request_processors/experimental_session_control.rs:367-380` 在 query id 直接命中 loaded child 时不检查 Root 是否仍在线，
一律返回 `LoadedNonOwner/NotOwner`；只有用 Root id 查询并在 `:383-395` 反向扫描到该 child 时才返回
`OwnerUnavailable/ChildOnly`。因此同一个“Root 已卸载、child 仍 loaded”拓扑会随 query id 得出矛盾 owner availability，child query 也会
掩盖真正的 owner unavailable。

Plan 明列 child-only 场景，但现有 8 条 public JSON-RPC 测试只覆盖 Root 与 child 同时 loaded 时查询 child
（`app-server/tests/suite/v2/experimental_session_control.rs:419-555`）。修复应使直接 child read 也核对 canonical Root current/running，
并补 Root 不在 current map、child 仍 loaded 的窄回归，确认 residency=OwnerUnavailable、reason=ChildOnly 且 online/cold Session
mutation 都 fail closed；无需新增通用恢复设施。

此外，`app-server-protocol/src/protocol/v2/experimental_session_control.rs:50` 对 `prototype_facts` 使用
`skip_serializing_if = "Option::is_none"`，直接违反 `multidev/AGENTS.md:279-293` 的 v2 payload 规则。按局部规则改正并重新生成、审查
stable/experimental schema；这不是要求新增 schema 审计设施。

## 已确认成立的部分

- 新 RPC 位于 app-server v2 experimental surface，protocol capability 与默认关闭 product gate 已分离。
- TUI 新交互继续通过 AppServerSession/app-server，无 TUI→core/store 旁路。
- loaded Root operation 通过 current ThreadManager entry 与 runtime residency lease 调用 canonical Team domain；dead resident、non-owner 与
  stale precondition 均 fail closed，core owner 实现未发现剩余 correctness finding。
- list/read 不加载 Session、不启动 Agent/model/API；historyless read 没有取得 writer 或 repair metadata。
- lifecycle、residency、operation availability、provenance、view freshness 与 mutation certainty 已分轴；lag/disconnect/EOF 显式事件会
  使 retained projection 显示 stale。
- schema、snapshot、聚焦测试和完整门禁证据均有记录，当前 worktree 在审查开始时 clean，`git diff 0f3a96b..f88880b --check`
  无错误。
- 本轮读取完整实现 diff、Plan、执行日志、相关产品调用链与测试代码；上述 finding 均可由静态路径直接复现，因此没有重复运行 Cargo、
  schema generator、14k 完整门禁、Docker 或外部服务。

## 替用户作出的决策与验证边界

- 普通 `just test` 的 V8 404 不阻断；checksum-verified `just test-with-codex-v8` 使用同一 watchdog/Nextest，已经完整执行。记录中的
  16 项失败名称均位于 070 写集外，**不要求本任务修复，也不单独否定 C0**；但它们不能覆盖本报告中的 correctness finding。
- 不要求建设通用 reconnect、notification、timeout、审计或可信平台。disconnect/EOF 后沿用现有 fatal-exit + 新进程重读边界可接受；
  C0 只需让 response-lost 的实际 mutation attempt 有界退出为 unknown，并用现有完整 read 恢复。
- 不授权为了修复 discovery 去修改 `team-state/`、`thread-store/`、`rollout/` 或吸收 069 内容。优先在 070-owned server/client/TUI seam
  内闭合；确实无法闭合时再报告所有权冲突。
- authoritative read 后保留上一 mutation 的 historical Unknown 可以继续存在；问题是 UI 不能把它冒充为当前未提交操作的结果。
- 不要求重跑 14k workspace 完整门禁。修复后只运行与 7 项 finding 直接相关的 protocol/server/client/TUI/features 聚焦测试、必要的
  schema generator、受影响 crate fix/format；只有修复意外触碰 common/core 或就近规则明确要求时，才补相称门禁。

## 修复后复验重点

1. server 已接收/可能提交而 response 被丢弃且连接存活时，TUI 有界进入 stale+unknown，不 replay，并能显式 reread。
2. archived child、真实 ChildOnly、identity unavailable 均不能执行 Session online/cold mutation；Root 路径仍可用。
3. state DB query error 返回 incomplete/unavailable；非空 Root 集合不会因 child page 被显示为空。
4. product gate 关闭时 slash、App、RPC、background 和 startup tooltip 均无原型可见变化。
5. preflight 未提交的 operation 不继承其他 operation 的 historical certainty。
6. v2 wire 规则、stable/experimental schema 与现有 snapshots 保持一致，无 `*.snap.new`。
