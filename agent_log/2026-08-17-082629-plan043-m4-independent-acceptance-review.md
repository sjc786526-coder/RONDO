# Plan 043 / Multi M-4 独立验收审查

日期：2026-08-17 ｜ 审查对象：`worktree-043-multi-m4-coordination-closure@e03eef1` ｜ 基线：`main@af1063d`

## 结论

- **验收不通过**：Root-only 独立退休、无自动清理、route / Root attention 隔离、轻量日志与真实无 API 纵切的主体方向正确，
  但 producer 可用性仍会与真实恢复结果矛盾，退休提交也不能可靠拒绝成员恢复竞态；解释面和 no-op 语义还有直接违反合同的缺口。
- **任务目标失败（当前提交尚未完整实现预期）**：M-4 不能按 `e03eef1` 宣称完成、合并或推送。这里的“失败”表示当前提交未达到
  既定完成标准，不否定已经落地的主体实现；以下问题均可在现有控制面、TeamState 与 inspect 工具内窄修，不需要增加复杂审计、
  可信链、外部日志平台或跨进程持久化。
- 本轮只做独立审查与一次轻量领域包复验，没有修改产品代码，没有重跑 core 产品纵切、全 workspace、Docker、真实 API 或本地模型。

## 已确认正确的主体能力

- Root 权限由权威 session 身份进入 TeamStore 后再次校验；普通成员不能退休或读取诊断面。
- 退休以独立 `RetirementRecord` 覆盖层保存，producer 仍为 `open`；已实现“不伪装 producer closed、只撤销该 Version 的
  producer-open 活动理由”，不会自动改 Root attention、route、assignment、其他 Version、Fact refs 或 authored 内容。
- 没有自动退休、orphan 清理或 escalation；Root 不操作时事项继续悬挂。精确 retire / publish / route 重试和 unchanged delivery
  已避免重复 revision、日志与 generation。
- dump / log 一页上限、稳定遍历顺序、Root 活动视图 availability 标签、查询时重算发布统计和真实 Session / AgentControl /
  team tool 产品纵切均已接通；`team_retire` / `team_inspect` 仍受 `team_state_enabled` 总开关控制。
- 执行者报告的 M-1—M-3 回归、受影响 core 测试与格式/lint 结果和现场实现没有发现相反证据；本轮轻量重跑的
  `codex-team-state` 114 项也全部通过。现有绿色测试没有覆盖下列反例，因此不能替代合同审查。

## 验收阻断

### P1：availability 没有复用真实恢复门禁，且退休检查存在 TOCTOU / ABA

`core/src/agent/control/availability.rs:42-66` 只检查当前 loaded thread 与 `read_stored_thread`；有 stored thread 就报告
`recoverable_unloaded`。真实 V2 恢复还要求 registry metadata、可加载的 model context 与 V2 marker，见
`core/src/agent/control/spawn.rs:250-285`。

仓库已有一个直接反例：`core/src/agent/control/residency_tests.rs:70-123` 证明 Interrupted V2 agent 经 residency 驱逐后，
stored thread 仍在，但 `ensure_v2_agent_loaded` 权威返回 `ThreadNotFound`。新分类器会把同一 producer 报为
`recoverable_unloaded`，从而让一个实际已不能恢复的 orphan 永远无法退休。这也说明当前实现没有像计划和源码注释所称那样
综合 registry、residency 与恢复能力。

反方向还有错误退休风险：`core/src/tools/handlers/team_tools/retire.rs:45-71` 先异步派生 snapshot，之后才进入 TeamStore；
`team-state/src/store/retire.rs:87-104` 只比较调用方传入的这份 snapshot。producer 在两步之间恢复时，旧 `unavailable`
仍可被提交。`team-state/src/availability.rs:64-80` 的 epoch 又只是当前分类集合的内容哈希，不是状态版本：
`unavailable → available → unavailable` 会回到同一 epoch，无法拒绝 ABA 式陈旧请求。

处理要求：分类结果应与实际“同一 Root 树能否恢复/接收任务”的控制门禁一致；退休提交要在可用性状态版本或等强原子重验下
确认作者在提交时仍真正不可用。具体采用单调 generation、控制面 CAS、窄锁或其他等强方案由执行者选择，不要求引入新服务。

### P1：dump 不是完整、可连续分页的协调快照

当前 Version dump（`team-state/src/store/observe.rs:146-157`）只输出 `retired/by/at` 和 Fact 数量，遗漏 canonical
`RetirementRecord` 已保存的 reason、availability 与 availability epoch；变更日志也只写 `retired`。即时
`team_retire` 返回消失后，Root 无法回答“为什么、依据哪一状态版本退休”。

同一 dump 只给 Version 的 `fact_ref_count`，全局 Fact 行又没有 Version→FactId 关联，且遗漏
`ObservationLocator.call_id`（`team-state/src/evidence.rs:58-72`）。所以它也不能回答“这个 Version 引用了哪些 Fact，以及这些
Fact 的完整定位元数据是什么”。补轻量 ID / metadata 关联即可，不应复制证据正文或工具输出。

分页一致性同样有实际缺口：`confirm_observation` 会向 `facts` 追加条目，但不推进 Team revision
（`team-state/src/store/evidence.rs:72-94`）；dump cursor 却只校验 Team revision 和 availability epoch
（`team-state/src/store/observe.rs:31-39`）。第一页后确认一个 Fact，旧 cursor 仍被接受，offset 后续页可能漏项或重复。
此外 `TeamStateHandle::dump/change_log` 在取得 store 锁前读取 wake generation（`team-state/src/handle.rs:177-195`），
并发 mutation 可能返回新 revision 搭配旧 generation，随后无 revision 变化而 generation 再变化。

处理要求：让 cursor 覆盖所有会改变 dump 排列的 canonical 状态，并让 revision / generation / entries 来自同一一致读取；无需冻结
transcript 或复制第二份 TeamState。

### P1：同状态 lifecycle 更新仍制造虚假变更

`team-state/src/store.rs:491-579` 允许 Root 对 `pending → pending` 或 `tracking → tracking` 成功提交，随后无条件推进 revision、
写入 `before == after` 的日志；`team-state/src/handle.rs:118-125` 对任意成功 lifecycle 调用推进 wake generation。
这与 M-4“没有 canonical 变化就不产生 revision / log / generation”和实现日志“只在真实 mutation 上推进”的声明直接矛盾。

处理要求：同状态更新应成为稳定 no-op 或明确拒绝，但不能伪造 canonical mutation；补一条领域层小回归即可。

### P2：发布统计既不按稳定 Agent 身份聚合，也没有有界读取

TeamState 以 `ThreadId` 注册参与者且允许 label 重复（`team-state/src/store.rs:184-207`），但
`publication_stats_rows` 用 label 查找并聚合（`team-state/src/store/observe.rs:209-240`）。旧 Agent 释放 path 后，新 thread
可复用同一 `/root/task` label；两者各发布一次会得到两条同名行，一条错误计 2、另一条为 0，而不是“每个 Agent”的真实统计。
诊断输出也没有稳定 ID，无法消除歧义。

同时 stats 分支忽略 `limit/offset`，直接返回全部历史参与者（`core/src/tools/handlers/team_tools/inspect.rs:97-111`、
`team-state/src/store/observe.rs:112-115`）。团队生命周期内参与者可以顺序增长，因此该入口不满足“每个解释入口有硬上限，超出
可分页或显式计数”的合同。

处理要求：以稳定 Agent 身份计数并保留 label 供人读；给 stats 增加与现有 observe 风格一致的页或明确硬上限/省略计数。
不引入限流、质量评价或长期指标平台。

## 测试覆盖缺口与窄复验范围

现有 M-4 产品纵切只串行覆盖 Completed worker 的 unload → delete → retire。领域测试只人工构造 snapshot；没有固化计划要求的
真实恢复门禁矛盾、snapshot 后恢复、ABA、retire / producer-close 竞态、并发 retire、成员重现后旧 Version 终态、orphan
不操作持续悬挂、同状态 lifecycle no-op、Fact 插页 cursor、重复 label stats 与 stats 上限。部分行为从 mutex / 终态实现看
方向正确，但验收合同要求的关键竞态不能只靠推断。

整改后优先补上述反例的领域/控制面小测试；产品层只需在现有 M-4 suite 增加一条真实恢复资格与退休竞态的代表性覆盖。
随后重跑 `codex-team-state`、M-4 产品 suite、M-1—M-3 定向回归和真正受影响的 control/team tool 子集即可；不需要全 workspace。

## 替用户作出的决策

1. 保留当前 `RetirementRecord` 覆盖层、Root-only `team_retire` / `team_inspect`、无自动清理及查询时重算 stats 的轻量架构；
   不要求改成大型状态机或新增审计/可信设施。
2. 接受 `authored_chars = Event title（opening Version）+ summary + optional handoff` 的 Unicode 标量值口径；只修稳定 Agent
   身份和有界输出，不引入 token 估算、质量评价或限流。
3. 不接受内容哈希充当 availability 状态版本，也不接受仅“store 可读”代表可恢复；执行者可自主选择最小的等强并发方案，
   但结果必须与真实恢复门禁一致并拒绝提交窗口和 ABA 陈旧退休。
4. dump / log 只补回答 M-4 问题所必需的 retirement metadata、Version→Fact 引用和 locator metadata；明确不复制
   summary/handoff、工具输出、证据正文、transcript 或私有上下文。
5. 当前继续使用 043 工作树整改并形成后续 reviewable commit；不新开 M-5，不合并、不推送。整改完成后做同工作树窄复验，
   再独立验收。

执行者没有留下必须由用户另选的产品问题；以上取舍由本轮审查直接作出。

## 独立验证与现场

| 项目 | 结果 | 说明 |
|---|---|---|
| `git diff --check c78afc3..e03eef1` | 通过 | 实现差异无 whitespace error |
| `just test -p codex-team-state --lib` | 114/114 通过 | 共享构建锁与资源看门狗；run `b2a3b6a5-bbe5-4ade-9e0f-2051f0ffbee6` |
| core / M-1—M-4 产品测试 | 本轮未重跑 | 采用执行日志的定向结果，静态复核产品接缝；避免重复重型门禁 |

第一次在受限 sandbox 内启动领域测试时，资源看门狗因无法连接宿主 cgroup bus 按规范 fail-closed（exit 81）；随后在获准环境中
用同一命令重跑并通过，不是代码测试失败。未运行全 workspace、Docker、真实 API、本地模型、付费资源或测评。

审查前 043 工作树干净，`main = origin/main = af1063d` 且主工作区干净。本报告是本轮唯一产品仓库受跟踪改动；未修改实现、
Plan/WBS、未合并、未推送、未归档分支。现有 WBS 与 WBS-COMPLETED 中“实现完成、待审查”的记录不构成验收通过；整改时应
按最终结果同步，M-5 在 M-4 真正验收合入前保持未开始。
