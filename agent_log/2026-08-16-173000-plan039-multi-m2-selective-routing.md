# Plan 039 / Multi M-2 选择性路由纵切

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/040-multi-m2-selective-routing`
｜ 分支：`worktree-040-multi-m2-selective-routing` ｜ 起点：`531297c`

## 本次改动

在 M-1 团队世界状态之上落地选择性路由：Root 以 Event 为单位授予不可撤销可见性并可建立工作指派，
canonical 提交完成后才投递紧凑通知。

**领域层（`multidev/codex-rs/team-state/`）**

- 新增 `RouteId`（`rte-{event}.{n}-{instance}`）、`TeamRoute`、`RouteDuty`（`notice`/`assigned`/`ended`）、
  `DeliveryState`（`pending`/`delivered`/`failed{reason}`）。route 挂在 `TeamEvent` 上，不复制 Event。
- route 提交、投递记录、结束指派单列 `store/route.rs`，沿用 store 既有"先全量校验再一次提交"的结构；
  `store.rs` 只保留 publish 与 lifecycle 不变量。
- 第 13 条活动谓词补齐第三个纳入理由（面向自己的进行中指派）；`is_visible_to` 增加 route 授权分支，
  该授权不随指派结束而撤销。
- retry 账本 `committed` 从 `PublishRequest` 泛化为 `CommittedRequest`/`CommittedOutcome` 枚举，
  publish 与 route 共享同一 `(actor, request_id)` 命名空间。
- 投影新增 route 行，并按可见性收敛：Root 见全部 route，成员只见发给自己的。

**产品层（`multidev/codex-rs/core/`）**

- 新增 `team_route`（`intent=assign|notify`）与 `team_route_update`（`action=end|retry_notice`）两个工具，
  注册在既有 `features.multi_agent_v2.team_state_enabled` 门内，默认关闭不变。
- 通知构造、投递与失败记录集中在 `team_tools/notice.rs`：复用既有 `ensure_agent_known` →
  `build_agent_resume_config` → `ensure_v2_agent_loaded` → `send_inter_agent_communication` 链路，
  未新建调度器、Agent-to-Agent 协议或全局订阅。
- 通知正文只含团队实例、route/Event 定位、动作提示与 Root 的短备注，不含标题、summary、handoff 或 chain。
- 稳定团队协议前缀升版 v1→v2，说明 route 语义与"通知不带内容、去 canonical 状态读"。

## 疑难问题

1. **三种投递意图不能靠读 Agent status 区分**。`AgentStatus` 是最后事件的派生值，`NotFound` 还混淆了
   "已卸载"与"已消失"；权威判据是 `active_turn` 锁。最终只由 `duty` 推导 `trigger_turn`，运行中排队与
   空闲唤起交给既有执行面在锁内裁决——这也正是上游 `maybe_start_turn_for_pending_work` 已有的语义。
2. **重复 route 有两种，只挡一种不够**。retry identity 只覆盖同一次逻辑提交的重放；Root 在两个不同轮次
   再次 route 同一 Event 给同一目标不是重放，但会叠加第二份指派，结束其中之一后活动视图里会留下无法
   解释的残留。因此额外按"同一目标在同一 Event 上已有进行中指派"去重。
3. **retry identity 跨操作类型复用**。若 publish 与 route 各用一套命名空间，同一 identity 会在两类操作上
   分别生效，等于放弃"重试不产生重复对象"。改为共享命名空间并显式拒绝跨类型复用。
4. **集成测试的 mock 计数语义**。`core_test_support` 的 `ResponseMock` 在 wiremock **匹配阶段**就记录请求
   （包括它随后拒绝的那些），所以 `single_request()` 的含义是"这个 mock 被询问过一次"而不是"应答过一次"，
   多 Agent 场景下必然误报。断言全部改为对 mock server 完整请求日志跑显式谓词。
5. **跨 Agent 断言的时序**。`submit_turn` 只等 Root 的轮次结束，目标 Agent 的后续请求可能更晚到达。
   涉及目标轮次的断言改用有上限的轮询等待；断言"不该发生"的用例保留固定 settle 时间。

## 验收结果

全部经仓库根共享构建锁执行，未跑全 workspace。

| 门禁 | 结果 |
|---|---|
| `just fmt` / `just fmt-check` | 通过 |
| `just fix -p codex-team-state` / `-p codex-core` | 无告警 |
| `just test -p codex-team-state` | 75/75（M-1 原 46 + M-2 新增 29） |
| `just test -p codex-core --test all -- suite::team_world_state suite::team_routing` | 12/12（M-1 纵切 9 项无退化 + M-2 新增 3 项） |
| `just test -p codex-core --lib -- tools::` | 415/415 |
| `just test -p codex-core --lib -- context::` | 99/99 |
| `just test -p codex-core --lib -- team` | 9/9（含 7 项 route 工具用例） |

M-2 产品纵切在真实 Agent/session/communication/wait 接缝上跑通：Root 发布一个 worker 看不到的 Event →
route 为 assign → worker 被唤起、读到完整 chain、在同一 Event 追加自己的 Version → Root 被唤醒并看到
双作者 chain → Root 结束指派。三种投递意图各有独立产品用例，其中"运行中目标"用例以 `turn_id` 相等
证明通知并入既有轮次而非另起一轮。

未运行：Docker、真实 API、本地模型、付费测评、全 workspace 测试（均不在本次授权内）。

## 环境说明

本机 shell 预置 `HTTP(S)_PROXY` / `ALL_PROXY`，会使被测进程连不上 wiremock 起的本地 mock server；
该现象对 M-1 既有 suite 同样复现，与本次改动无关。集成测试均在显式清除这些变量后执行，
未修改宿主机或仓库配置。
