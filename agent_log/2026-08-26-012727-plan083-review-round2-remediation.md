# Plan 083 / M4-Z(core) 第二轮审查整改

时间：2026-08-26 ｜ 审查状态基线：`9059a8ac4843a762cbdc9784305fcb9fc99db7cf`

## 整改

- 确认 finding 存在。participant activation cleanup 原先先持久化 Closed edge，再 teardown 与 exact-remove runtime；后两步失败时，
  unpublished owner 会同时脱离 graph 与 registry 两类 Root close barrier。
- cleanup 改为复用 explicit close 的 owner 顺序：先 shutdown captured owner，再取得 exact thread-map lease；持 lease 写 Closed edge，写成功后
  exact-retire。teardown、missing/replaced owner、graph store 缺失或写失败均不会提前关闭 edge；lease 覆盖 Closed 写与 retirement，阻止
  same-ID replacement 插入竞态。
- 增加仅在单元测试编译中存在的定向 fault seam，以真实 participant activation definitive failure 驱动 teardown 与 exact-owner gap；
  不新增产品状态、通用 fault scheduler、事务或审计设施。

## 验证

- failure-ordering 聚焦 `2/2`：Nextest `2bbfc5e1-3596-4132-8126-a8a17ad809b3`；graph/Root-close 邻接 `6/6`：
  Nextest `17586187-cf86-4b4b-b02b-bf884e8e8dcb`。失败时 Open edge继续阻塞 Root close，成功重试才得到 Closed edge与 exact retirement。
- `codex-core` scoped clippy 通过，watchdog `20260826-012104-1000-2249681`；`just fmt-check` 与 `git diff --check` 通过。
- 冻结候选从 fresh TempDir、Session/store 完成正式产品全链：Nextest `fc6e8c7d-ff74-4af0-9147-a91580541ef8`，`1/1`；watchdog
  `20260826-012504-1000-2261794` 为 `stop=none / cleanup=none`，退出后无残留任务进程。
- 正式轮前后项目/069 target 为 `251,268,050,944 / 188,469,571,584 B` → `251,103,621,120 / 188,302,737,408 B`；最终
  deps/incremental 为 `152,793,751,552 / 34,694,021,120 B`，Windows `C:` 可用 `75,571,384,320 B`。

## 当前状态

第二轮 finding 整改、fresh 正式证据与自审完成，候选恢复 `AWAITING_REVIEW`。未重跑已认可的 30/30，未运行 full workspace、Docker、
真实 API/模型、训练或 benchmark；未写 `M4_Z_CORE_PASS` 或 `doc/WBS-COMPLETED.md`，未 merge、push 或归档。
