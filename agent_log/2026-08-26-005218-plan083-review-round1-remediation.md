# Plan 083 / M4-Z(core) 首轮审查整改记录

时间：2026-08-26 ｜ 审查基线：`3dd8d190db150a09b92b163901be874e66153b73`

## 整改

- 确认两项 finding 均存在。V2 `close_agent` 现在沿既有 V2 handler 语义，在 teardown 前用当前 `AgentControl` registry 证明 target
  membership，并拒绝 Root/self；V1 显式 ID 行为未改变。
- Durable child Session 的 participant activation 改为 owner-controlled defer：fresh/fork/显式 resume 先成功持久化 Open AgentGraph
  edge，再提交 canonical Team participant，最后发布 agent registry/residency。graph 缺失或写失败只清理 unpublished runtime，因而不会产生
  participant commit；后续确定性 participant activation 失败复用 Closed edge 与 exact runtime cleanup，不建设第二套事务或状态源。
- graph-failure fixture 使用真实命名 V2 member，直接比较失败前后的 committed participants、Team projection/revision 和 residency，另断言
  runtime/registry 均无泄漏；V2 close 回归覆盖 foreign loaded Root/child、当前 Root/self 以及本 Team task name/UUID。

## 验证

- 直接回归：graph/participant `2/2`，Nextest `d52f492b-4baf-4a52-9295-7abdd9ed3ce0`；V2 close `1/1`，Nextest
  `dad2c092-693f-4d23-bc6a-51a496c4d474`。
- fork/resume/crash 与 V1 close 邻接面 `7/7`，Nextest `57ec0395-9fe0-40ed-a54f-126f571ce003`。冻结后的 `codex-core` scoped clippy
  通过，watchdog `20260826-004831-1000-2189464`；`just fmt-check` 与 `git diff --check` 通过。
- 新冻结候选从新的 TempDir、Session/store 运行正式产品全链：Nextest `8a93166f-a605-40c5-965d-d69ffa3fa999`，`1/1`；watchdog
  `20260826-004938-1000-2191687` 为 `stop=none / cleanup=none`，退出后无残留任务进程。该轮继续使用 fake localhost model server，
  app-server replacement 为真实 OS 子进程，没有真实 API/模型。
- 正式轮前后项目/069 target 为 `246,593,462,272 / 183,807,692,800 B` →
  `248,552,226,816 / 185,766,424,576 B`；最终 deps/incremental 为 `152,793,542,656 / 32,157,921,280 B`，Windows `C:`
  可用 `75,189,628,928 B`。所有重型批次均复用 069 target、进程级 270/285/290GB 门限和 canonical lock/watchdog。

## 当前状态

首轮 finding 整改、新正式证据与自审已完成，候选恢复为 `AWAITING_REVIEW`。未运行 full workspace、Docker、真实 API/模型、训练、
benchmark、Plan 082 或 M4-W0/W1；未写 `M4_Z_CORE_PASS` 或 `doc/WBS-COMPLETED.md`，未 merge、push 或归档。
