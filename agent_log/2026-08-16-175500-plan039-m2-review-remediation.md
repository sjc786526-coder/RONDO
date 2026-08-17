# Plan 039 / Multi M-2 首轮审查整改

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/040-multi-m2-selective-routing`
｜ 针对审查报告：`agent_log/2026-08-16-173945-plan039-m2-independent-acceptance-review.md`（提交 `b2a9fe6`）

## 三项阻断的确认与修复

三项均复现属实，且都是恢复路径而非主链问题。修复全部落在既有 store 与 handler 内，未新增审计、
可靠投递或调度设施。

### 1. 活动指派去重没有占用新的 retry identity

确认：`store/route.rs` 的"已有进行中指派"分支直接返回，从不写 `committed`。因此该 identity 仍是空闲的——
指派结束后原样重放会再造一个指派，且它还能被另一类提交取用，等于在共享 retry namespace 上开了个洞。

修复：该分支现在把本次 `(actor, request_id)` 绑定到它所答复的那个指派再返回。同时补上审查指出的另一半——
**note 不同不再静默复用旧指派**。沿用旧指派会丢掉 Root 刚下达的新指令，再开一个又让目标为同一 Event 持有
两个理由；因此新增 `TeamError::AssignmentInProgress`，明确告诉 Root 可以改为发布 Version，或先结束当前指派。
比较时对新 note 施以与写入相同的 clamp，避免长文本被截断后误判为"不同"。

### 2. 精确重放返回过期的 `pending`

确认：`CommittedOutcome::Route` 缓存了整个 `RouteOutcome`，其中 `delivery` 是**提交时**的值，而提交必然发生在
通知之前，所以缓存里永远是 `pending`；`record_delivery` 只改 canonical route。于是 canonical 已经是 `failed`
的 route，重放时被报成 `pending`，恰好掩盖了合同要求"明确可见且可幂等重试"的那个状态。

修复：账本不再缓存可变快照，只记 `RouteId`；重放时经 `deduplicated_outcome()` 从 canonical route 现取 dispatch。
这样任何后续新增的可变字段都不会重蹈覆辙，而不只是修好 delivery 这一个。publish 侧仍缓存 outcome——它的字段
在提交时就已全部固定。

### 3. 目标可先产生未授权重发副作用

确认：`route_dispatch` 允许发起者或目标取用，`record_delivery` 只允许发起者。`retry_notice` 先取 dispatch、
再执行加载与发送、最后才记账，于是目标可以给自己真实重发通知，然后记账才报 `NotPermitted`——通知已经发出去了。

修复：把 `route_dispatch` 收紧为仅发起者可取，与 `record_delivery` 同一权威。这样鉴权发生在取 dispatch 这一步，
即在任何加载或发送之前，两处权限不可能再漂移。目标仍可读 Event、仍可结束自己的指派。

### 顺带收紧的两项低风险问题

- 信息型通知不再无条件指示目标 `team_publish`；改为说明"没有要求你做什么"，可选贡献。指示追加 Version 会把
  通知悄悄变成工作，正是两种 intent 要区分的东西。
- `team_route` / `team_route_update` 返回的 `revision` 现在与同一次返回的 `delivery` 取自同一 canonical 快照
  （`deliver_and_record` 改为返回整个 `DeliveryOutcome`），不再是"提交 revision + 提交后状态"的混搭。

## 复验结果

均经仓库根共享构建锁执行，未跑全 workspace。

| 门禁 | 结果 |
|---|---|
| `just fmt` / `just fmt-check` | 通过 |
| `just fix -p codex-team-state` / `-p codex-core` | 无告警 |
| `just test -p codex-team-state` | 78/78（整改新增 3 项） |
| `just test -p codex-core --test all -- suite::team_world_state suite::team_routing` | 12/12（M-1 九项无退化） |
| `just test -p codex-core --lib -- tools::` | 416/416（整改新增 1 项） |
| `just test -p codex-core --lib -- context::` | 99/99 |

新增的四组聚焦回归，每一组都对应一项阻断：

- `a_replayed_route_reports_the_delivery_state_the_route_has_now`：记录投递失败后重放，断言拿到 `failed`
  而非 `pending`，且 revision 与之同快照。
- `an_alias_identity_is_bound_to_the_assignment_it_was_answered_with`：别名 identity 在指派结束后重放仍返回原
  route（`ended`）且不新增对象，并断言该 identity 已被占用、无法再被 publish 取用。
- `a_hand_over_with_a_different_instruction_is_refused_rather_than_dropped`：note 不同时拒绝，原指令不受影响。
- `only_the_router_may_take_a_dispatch_to_resend`（领域）与
  `a_target_cannot_resend_its_own_notice_and_nothing_is_sent`（产品）：后者直接断言拒绝发生在发送之前——
  目标线程上的通知条数在被拒后没有变化——并确认目标仍能结束自己的指派。

## 未变更

主链设计未动：canonical 先于通知、按 duty 推导 `trigger_turn`、publish 与 route 共享 retry namespace、
同一 Event/target 至多一个进行中指派，均按审查确认的决定保留。顶层 `doc/WBS.md`、`doc/WBS-COMPLETED.md`、
`mydev/`、L6 工作树未触碰。未运行 Docker、真实 API、本地模型与全 workspace 测试。
