# Plan 083 / M4-Z(core) 独立验收审查（Round 1）

时间：2026-08-26 ｜ 审查候选：`962469c77f3dbbfd43d6af9ea36ffa8bdf1dcd05`

## 结论

`REVIEW_NOT_PASSED` / `M4_Z_CORE_PASS` 尚未成立。

候选的 fresh 真实进程替换全链、30 项宽聚焦门禁、schema/precomputed、scoped clippy 与资源退出证据均有效；主线和工作树状态也符合交付边界。但独立代码审查确认两个中等级 correctness finding，均位于本任务新增/修改的正式链职责内，必须窄修并复验后再验收。

## Findings

### Medium 1：V2 `close_agent` 可用 foreign UUID 越过 Team 边界关闭其它 Session 的 thread

- `core/src/agent/agent_resolver.rs` 对可解析 UUID 直接返回 `ThreadId`；新增 V2 handler 随后复用 `multi_agents/close_agent.rs`，没有像 V2 `interrupt_agent` 和消息工具一样调用 `ensure_agent_known`，也没有在工具边界拒绝 Root。
- `AgentControl::close_agent` 只特殊拒绝“当前调用者 Team 的 durable Root”，之后通过共享 `ThreadManagerState` 查询和关闭目标。因此，同一 app-server/manager 内另一个 Root tree 的 loaded child UUID 会被当前 Team 的 `close_agent` 实际关闭；foreign Root 也会进入 shutdown，不能依赖后续 graph status 写失败来恢复已发生的 teardown。
- 现有正式全链只覆盖本 Team 的 task name，未覆盖 foreign UUID，绿测不能排除该路径。

期望修复：在 V2 close 的职责边界证明 target 属于当前 `AgentControl`/Root tree，并拒绝 Root（以及当前 agent 自身等不合法目标），保持与现有 V2 工具语义一致。优先局部修复 V2 路径，避免无意改变仍允许显式 ID 操作的 V1 合同；若执行者有证据表明更合适的等强 owner seam，可采用更优实现。至少补一项回归，证明 foreign loaded child/Root 在拒绝后仍运行，同时本 Team child 的 task name/UUID close 仍成功。

### Medium 2：durable graph persist 失败会留下已提交但不可恢复的 phantom participant

- durable child 的 `Session::new` 在 `core/src/session/session.rs` 完成前会调用 `try_register_team_participant`，这是 canonical Team 的 durable commit。
- `spawn_agent_internal` 只有在该 Session/runtime 已创建并返回后才写 Open AgentGraph edge。新增 fail-closed 路径在 graph 缺失或写失败时会 shutdown 并精确移除 runtime，但不会、也没有现成动作撤销之前的 Team participant commit。
- 结果是 spawn 返回确定失败、registry/runtime/graph 均没有 child，但正式 query 仍可能看到一个已提交 participant。当前新增回归只断言 manager 和 registry 清洁，没有比较失败前后的 committed Team projection/generation，因此漏掉了这个不一致。

期望修复：调整 durable child 的发布顺序或使用现有架构内的等强 seam，使 participant commit、Open graph 和 runtime 发布不会在确定失败结果下分裂；不要为此新增第二套事务、状态源或审计设施。确定 graph 失败后，权威 Team query 不应留下 phantom member；若某一步的提交结果确实不可证明，则必须按现有 unknown/reconcile 语义诚实处理，不能伪装成无副作用失败。回归应直接比较失败前后的 committed Team participant/projection，并继续断言无 graph edge、runtime、registry/residency 泄漏。

## 证据复核与复验边界

- fresh 正式轮 `.codex/build-watchdog/20260825-235546-1000-2079406`：Nextest `b0d0eadc-5c49-46d8-9e97-310cf35691ea`，`1/1`，`stop=none / cleanup=none`；证据有效。
- 宽聚焦轮 `.codex/build-watchdog/20260825-234512-1000-2049971`：Nextest `99a78c43-ab72-4b33-abff-45d46411e3df`，`30/30`；覆盖矩阵与声明一致。
- 未发现 schema wire、公开 query/control 映射、真实旧/新 app-server 进程替换或资源门证据造假。正式全链对 archive/delete `affectedThreadIds` 的断言可更强，但已有职责层 subtree 回归，因此不作为本轮阻断项，也不要求扩建测试设施。
- 本轮审查未重跑重型 Cargo。整改后只需运行新增聚焦回归、受影响 crate 的相称 lint/format，并在冻结新候选后从 fresh store 重跑正式全链；不要求 full workspace、Docker、真实 API/模型或额外审计。

## 替用户作出的决策

- 两个 finding 都属于 Plan 083 已授权的 correctness 窄修，不需要追加用户授权；执行者直接整改、提交并按既定队列重新通知。
- 不要求引入通用鉴权层、跨 Team capability 平台或第二套事务设施。V2 target membership 校验与 durable child 发布顺序应优先落在现有 owner seam；具体实现由执行者基于 live 架构自主选择。
- 将当前候选同步为 `REVIEW_CHANGES_REQUESTED`/未完成状态，不写 `M4_Z_CORE_PASS`，不更新 `doc/WBS-COMPLETED.md`，不 merge、不 push、不归档。

## 当前项目状态

- 验收：不通过（候选存在两个未关闭的 Medium correctness finding）。
- 任务目标：尚未完成（正式证据有效，但独立终审门尚未关闭）。
