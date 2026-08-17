# Plan 043 / Multi M-4 整改后独立复验

日期：2026-08-17 ｜ 审查对象：`worktree-043-multi-m4-coordination-closure@8f73572` ｜ 前次审查：`e2105aa` ｜ 基线：`main@af1063d`

## 结论

- **验收不通过**：`8f73572` 已有效修复同状态 lifecycle 虚假变更、Fact 插页 cursor、退休解释元数据、按 ThreadId
  聚合并分页的发布统计，但 producer availability 仍与产品真实恢复能力矛盾，退休提交也没有和成员恢复形成原子边界；dump
  仍存在无界单条记录、绕过冻结 cursor 和重复 label 身份歧义。
- **任务目标失败（当前提交尚未完整实现预期）**：M-4 的主体实现可以保留，但现在还不能宣称完成、合并或推送。剩余问题都能在
  现有 AgentControl / ThreadManager / TeamState / inspect 接缝内窄修，不需要增加复杂审计、可信链、外部日志平台或跨进程设施。
- 本轮没有修改产品代码，只做源码与测试审查、两项轻量定向复验并提交本报告；没有重跑 M-1—M-4 产品套件、全 workspace、
  Docker、真实 API 或本地模型。

## 已确认整改有效

- availability 分类已复用 `probe_v2_restore` 的 loaded / restorable / failed 判定；Interrupted 驱逐后“stored thread 仍在但
  `ensure_v2_agent_loaded` 失败”的原反例已被覆盖。
- availability epoch 已从内容哈希改为单调 generation，消除了同一分类集合哈希导致的直接 ABA；snapshot 分类过程也会在前后
  generation 不一致时重试。
- dump 已补 retirement reason、retirement availability / epoch、Version→Fact ID 和 Fact `call_id`；`observe_generation`
  会让 participant / Fact 插页后的旧 cursor 失效，wake generation 也和 TeamStore 状态在同一锁内读取。
- `pending→pending` / `tracking→tracking` 已成为稳定 no-op，不再推进 revision、change log 或 wake generation。
- publication stats 已按稳定 ThreadId 重算并服从 `limit/offset`；重复 label 不再串账。既定 Unicode scalar values 内容体量口径
  清楚且可重算。

这些修复方向正确，不应在下一轮推倒重做。现有绿色测试没有覆盖下面的真实反例，因此不能替代产品合同审查。

## 验收阻断

### P1：registry miss 被误判为真正不可用，实际仍可在同一 Root 树恢复

`core/src/agent/control/spawn.rs:276-281` 在 live thread miss 后，只因 registry metadata 缺失便返回
`V2RestoreProbe::Unrecoverable`。但 `shutdown_live_agent` 会移除 live thread 和 registry，而保留 rollout
（`core/src/agent/control/legacy.rs:7-29`）；显式 `resume_agent` 随后能从 stored rollout 重建 runtime 与 registry
（`core/src/agent/control/spawn.rs:985-1069`）。

仓库既有测试 `core/src/tools/handlers/multi_agents_tests.rs:2739-2809` 已直接证明：agent shutdown 后状态是 `NotFound`，仍可
成功 resume 并继续 `send_input`。本轮精确重跑该测试也通过。当前 classifier 对同一状态会报告 `unavailable`，Root 因而可以
退休一个实际仍可恢复的 producer，违反“可恢复未加载不得退休”和 unknown fail-closed。

处理要求：availability 必须覆盖同一 Root 树内所有真实恢复入口，包括显式 rollout resume；registry 缺失本身不能证明真正
不可用。具体是扩展 probe、拆分内部 fast-resume 与产品 recoverability probe，还是使用等强方案，由执行者自主选择。

### P1：退休提交与成员恢复仍非原子，generation 也没有覆盖全部分类变化

`team_retire` 先异步取得 snapshot（`core/src/tools/handlers/team_tools/retire.rs:45-73`），随后
`TeamStateHandle::retire` 只在 TeamStore mutex 内读取一次 `availability_epoch()`
（`team-state/src/handle.rs:181-195`）。TeamStore 锁不约束 ThreadManager；在这次 atomic load 之后、
`team-state/src/store/retire.rs:89-130` 写入 retirement 之前，producer 仍可恢复并变为 available，旧 unavailable snapshot
仍会提交。

ThreadManager 的 loaded map 变化还是“先 insert/remove、后 bump”
（`core/src/thread_manager.rs:1357-1363,1823-1835`），不是与退休共享的线性化边界。新增
`a_live_epoch_that_moved_during_commit_is_refused` 只手工传入不同 epoch，没有制造“final read 后恢复、commit 前写入”的真实竞态。

generation 也没有覆盖所有输入：`release_spawned_thread` 改变 registry 却不 bump
（`core/src/agent/registry.rs:102-119`）；app-server 正式 `thread/delete` 直接删 store
（`app-server/src/request_processors/thread_delete.rs:47-55`），没有通知 ThreadManager generation。现有产品纵切只走新增的
`ThreadManager::delete_stored_thread`（`core/tests/suite/team_coordination.rs:397-400`），没有覆盖正式删除接缝。因此同一个 epoch
仍可能对应不同 availability 内容，既不能可靠充当退休 CAS，也不能完整冻结 dump availability。

处理要求：所有会影响派生分类的正式入口都要进入同一单调状态版本，并让最终 availability 检查与 retirement commit 对恢复/
删除状态变化呈线性化。可以用窄共享 guard、真正的 versioned transition/CAS 或其他等强轻量方案；不要求新的服务或审计系统。

### P1：dump 仍不满足“每页有硬上限且续页不混状态”

`DumpEntry::Version.fact_ids` 是无界 `Vec`（`team-state/src/observe.rs:51-64`），构造时会全量复制一个 Version 的全部
`evidence_refs`（`team-state/src/store/observe.rs:170-190`）。M-3 明确保留所有 canonical refs，
`team-state/src/store/evidence_tests.rs:712-740` 也证明单 Version 可以超过展示上限。因此即使 `limit=1`，一条 dump 记录仍可随
Fact 数量无界增长；“最多 50 条 entry”不是输出体量硬上限。

此外，`team_inspect` 对 dump 仍接受通用 `offset`（`core/src/tools/handlers/team_tools/inspect.rs:36-60`），TeamStore 在没有
cursor 时直接采用该 offset（`team-state/src/store/observe.rs:44-52`）。调用者可以在第一页后发生 mutation，再用裸 offset 读取
下一页，从而绕过 revision / availability epoch / observe generation 校验，静默拼接不同状态。schema 虽说明 offset 供 log/stats，
运行时没有落实。

处理要求：Version→Fact 关联需要有界且能继续分页或等强枚举，不复制证据正文；dump 续页必须只接受受版本约束的 cursor，不能
用裸 offset 绕过。具体采用独立 FactRef entry、子分页或其他轻量表示由执行者选择。

### P2：重复 label 时 dump / change log 不能唯一回答“哪个 Agent”

本次 stats 测试已固化两个 ThreadId 可以共享同一 label（`team-state/src/store/observe_tests.rs:443-509`），但 Version author、
Route target、Fact producer、Visibility/Activity participant 以及 ChangeLog actor / wake target 仍只输出 label。例如
`team-state/src/store/observe.rs:87-103,203-229` 中，同 label 的两个 Agent 对同 Event 可形成一真一假的 visibility 行，Root
却无法分辨各自身份。这直接影响“某 Agent 为什么能或不能看到 Event”和“谁在 revision 修改对象”，不是额外审计需求。

处理要求：在保留人类可读 label 的同时，为这些 Agent 关系补稳定 ThreadId（或等强唯一身份）；不需要 ACL、签名或身份可信体系。

## 替用户作出的决策

1. 接受并保留 `8f73572` 中已生效的 shared probe、单调 generation 方向、`observe_generation`、lifecycle no-op、退休元数据和
   ThreadId stats 分页，不要求回滚或改成大型设施。
2. 将“同一 Root 树可恢复”解释为包含现有显式 `resume_agent`；shutdown / NotFound / registry miss 但 rollout 仍可恢复的成员属于
   `recoverable_unloaded`（无法可靠确认时为 `unknown`），不得退休。
3. 不接受“在 TeamStore 锁内单读一次 atomic generation”作为原子退休证明。下一轮只需最小的共享 transition guard 或等强
   线性化方案，并让正式 registry/store 变化入口统一推进状态版本；不建设通用事务或审计框架。
4. dump 必须同时满足单条输出有界、剩余关联可继续读取、续页不混状态；裸 offset 不作为 dump 续页入口。所有回答 Agent 身份的
   行保留 label 并补稳定 ID，不引入复杂身份体系。
5. 继续在 043 工作树窄修并补代表性反例；不进入 M-5，不合并、不推送。修复后只重跑 `codex-team-state`、精确 control 恢复/
   并发测试、M-4 产品纵切和必要的 M-1—M-3 定向回归，不扩大为全 workspace。

执行者没有留下必须由用户另选的产品决策；上述取舍由本轮审查直接作出。

## 独立验证与现场

| 项目 | 结果 | 说明 |
|---|---|---|
| `git diff --check e2105aa..8f73572` | 通过 | 整改差异无 whitespace error |
| `just test -p codex-team-state --lib` | 121/121 通过 | 共享构建锁与资源看门狗；run `97af1961-7da3-4b63-8e37-d89171cc48f8` |
| `just test -p codex-core --lib -- resume_agent_restores_closed_agent_and_accepts_send_input` | 1/1 通过 | 2207 skipped；run `9ec909f1-2549-4b94-9a0f-e7c09e6af8ad`，确认 shutdown/NotFound 后真实可恢复 |
| M-1—M-4 产品测试 | 本轮未重跑 | 采用整改日志的定向结果；本轮只补最小证据，不重复较重门禁 |

第一次在受限 sandbox 内启动领域测试时，资源看门狗因无法连接宿主 cgroup bus 按规范 fail-closed（exit 81）；随后在获准环境中
通过同一共享构建锁命令重跑并通过，不是代码测试失败。未运行全 workspace、Docker、真实 API、本地模型、付费资源或测评。

复验前 043 工作树干净，`main = origin/main = af1063d` 且主工作区干净。本报告是本轮唯一产品仓库受跟踪改动；未修改实现、
Plan/WBS，未合并、未推送、未归档分支。当前 WBS/Plan 中“整改待复验”记录不构成验收通过；M-5 在 M-4 真正验收合入前保持
未开始。
