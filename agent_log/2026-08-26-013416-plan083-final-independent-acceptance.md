# Plan 083 / M4-Z(core) 最终独立验收

时间：2026-08-26 01:34 PDT ｜ 最终产品候选：`0a68f37667188bb7886ce51d4f79436b54bb9faa`

## 结论

**验收通过，任务目标完成，结论为 `M4_Z_CORE_PASS`。** 第二轮整改已关闭 participant activation cleanup 的失败时序 finding；
本次限定正确性、功能性与局部回归的终审没有发现新的高、中等级 correctness finding。

## 正确性复核

- activation definitive failure 后，cleanup 先 shutdown captured owner，再取得 exact thread-map lease；只有持有该 lease 时才把 Open edge
  写为 Closed，并在写成功后 exact-retire。teardown、missing/replaced owner、graph store 缺失或 graph 写失败均不会提前退休 owner；
  Open edge 或 store unavailable 继续阻塞 Root close，受跟踪 owner 则保留 exact retry/inspection 资格。
- lease 跨越 Closed 写与 runtime retirement，阻止 same-ID replacement 插入到两者之间。成功路径同时得到 Closed edge 与 exact runtime
  retirement；失败路径返回错误且 Root close 仍 fail-closed，符合既有 explicit close 与 lifecycle authority 语义。
- 定向 fault seam 只在单元测试编译中存在，不增加产品状态、通用 fault scheduler、事务、锁服务或审计设施。整改未改变协议、schema、
  client/TUI 或 non-durable/shared workspace 路径。

## 证据

- failure-ordering JUnit `2/2`：Nextest `2bbfc5e1-3596-4132-8126-a8a17ad809b3`；graph/Root-close 邻接 `6/6`：
  `17586187-cf86-4b4b-b02b-bf884e8e8dcb`。两轮均为 0 failure/error，watchdog `stop=none / cleanup=none`。
- `codex-core` scoped clippy watchdog `20260826-012104-1000-2249681` 为 rc 0；执行者记录的 `fmt-check` 与 live
  `git diff --check` 通过，无 `*.snap.new`。
- 冻结候选的 fresh 正式产品全链 Nextest `fc6e8c7d-ff74-4af0-9147-a91580541ef8` 为 `1/1`；watchdog
  `20260826-012504-1000-2261794` 为 `stop=none / cleanup=none`。该轮使用 fresh TempDir、Session/store，并以真实旧/新 app-server
  OS 进程替换覆盖恢复、继续 mutation、query/control 与最终 lifecycle。
- 首轮已认可的宽聚焦 `30/30`、stable/experimental schema、precomputed exports 与 client/TUI 证据未被本次 core-only 修复推翻。
  本轮不重复运行这些重型门禁，也不运行 full workspace、Docker、真实 API/模型、训练或 benchmark。

## 替用户作出的决定

1. 接受 `0a68f37` 为 Plan 083 最终产品候选，无需第三轮整改。
2. 接受现有仅测试编译的定向 fault seam 与保存的相称/fresh 证据；不为本任务扩建通用故障或审计平台，也不重跑已认可的 `30/30`。
3. 写入 `M4_Z_CORE_PASS`、冻结 Plan 083 并追加完成历史；083 分支仍只保留本地 clean 提交，不 merge、不 push、不归档。
4. M4-W0/W1 与 Plan 082 的路线和授权保持不变；Plan 083 的一次性构建授权不向后续任务转移。

## 最终状态

- 验收：**通过**。
- 任务目标：**完成**。
- 结论：`M4_Z_CORE_PASS`。
- 未决高/中等级 correctness/functionality finding：无。
