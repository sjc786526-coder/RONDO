# Plan 083 / M4-Z(core) 独立验收审查（Round 2）

时间：2026-08-26 ｜ 审查候选：`a7f0802387bd53eeef12e743475307298cbb33c3`

## 结论

`REVIEW_NOT_PASSED` / `M4_Z_CORE_PASS` 尚未成立。

首轮两项 Medium 的主要问题已经关闭：V2 `close_agent` 在 teardown 前验证当前 Team membership 并拒绝 foreign Root/child、Root 和 self；durable child 的 participant commit 也已延后到 Open graph edge 成功之后。保存的 `2/2`、`1/1`、`7/7` 聚焦/邻接回归、scoped clippy 和新 fresh 正式全链证据均有效。

但整改新增的 participant activation 失败 cleanup 仍有一项中等级失败时序缺口，必须窄修后再验收。

## Finding

### Medium：cleanup 先关闭 graph edge，teardown 失败时会隐藏仍被跟踪或已替换的 runtime owner

- `core/src/agent/control.rs` 的 `discard_persisted_unpublished_thread` 当前先把 child Open edge 写为 `Closed`，随后才调用 `discard_unpublished_thread` 执行 `shutdown_and_wait` 与 exact runtime removal。
- 该 child 尚未提交 agent registry/residency。若 shutdown 失败，或 exact removal 返回 `Missing`/`Replaced`，函数虽返回错误，但 graph edge 已经 Closed，registry 也没有 child metadata。
- Root close barrier 只合并 persisted Open descendants 与 registry 中 loaded/running descendants。上述状态因此可能让仍 loaded/running、或同 ID replacement 的 child 从 barrier 中消失；spawn admission guard 释放后，Root 可错误地跨过 close barrier。这违反本任务“teardown 失败不伪报完成、不隐藏唯一 owner、不允许 Root authority 提前释放”的硬约束。
- 现有新增测试覆盖 graph 写失败前不提交 participant，以及正常 cleanup；没有覆盖“edge 已成功 Open、participant activation 失败、runtime teardown/exact removal 又失败”的组合，因此 fresh happy-path 也不能排除该时序。

期望修复：在现有 exact-owner/graph seam 内保证 runtime teardown 失败时 Open edge 仍可阻塞 Root close；同时避免先移除 map owner、再关闭 edge造成 same-ID replacement 竞态。可优先复用 `close_agent` 已有的“shutdown captured owner → exact map lease → durable edge transition → exact retirement”模式，或采用证据充分的等强方案。不要新增第二套事务、锁服务或审计设施。

回归只需证明两个关键结果：teardown/exact-owner 失败时 target 仍通过 Open edge或等强权威事实阻塞 Root close；成功路径才同时得到 Closed edge与 exact runtime retirement。具体故障注入方式由执行者选择，不要求通用 fault scheduler。

## 证据复核与复验边界

- graph/participant `2/2`：Nextest `d52f492b-4baf-4a52-9295-7abdd9ed3ce0`；V2 close `1/1`：`dad2c092-693f-4d23-bc6a-51a496c4d474`；邻接面 `7/7`：`57ec0395-9fe0-40ed-a54f-126f571ce003`。JUnit 与 watchdog 均为零失败、正常退出。
- fresh 正式轮：Nextest `8a93166f-a605-40c5-965d-d69ffa3fa999`，`1/1`；watchdog `20260826-004938-1000-2191687` 为 `stop=none / cleanup=none`，资源门有效。
- watchdog 不保存完整 argv，`fmt-check` 只有执行日志声明；这是非阻断的低风险可追溯限制，不要求扩建审计设施或为此重跑重型门禁。
- 本轮审查未运行重型 Cargo。整改后运行新增聚焦回归、实际受影响 crate 的相称 lint/format，并在冻结新候选后从 fresh store 重跑正式全链即可；不重跑首轮已认可的 30/30，不要求 full workspace、Docker 或真实 API/模型。

## 替用户作出的决策

- 该 finding 属于 Plan 083 已授权的 correctness 窄修，不需要追加用户授权；执行者直接整改、提交并按既定队列重新通知。
- 不要求重新设计 participant/graph 体系。修复应收敛在现有 cleanup、exact-owner lease 与 lifecycle barrier seam；执行者可采用比建议更优的等强实现并给出证据。
- 当前状态同步为 `REVIEW_CHANGES_REQUESTED`；不写 `M4_Z_CORE_PASS`，不更新 `doc/WBS-COMPLETED.md`，不 merge、不 push、不归档。

## 当前项目状态

- 验收：不通过（候选仍有一项未关闭的 Medium correctness finding）。
- 任务目标：尚未完成（两项首轮 finding 的主体已关闭，但失败 teardown 终审门尚未关闭）。
