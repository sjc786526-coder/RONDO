# Plan 069 预验收 finding 修复

## 结果

- 复核 `2026-08-24-154516-plan069-independent-preacceptance-review.md` 的 H-1、M-1 至 M-7，八项均真实存在并已在 069 原边界内修复。
- 未改四份共享 WBS、Plan 068/070 资产、protocol/schema/manifest/lock；未实现 S2 delete 矩阵或 070 控制面。
- 当前实现完成、聚焦门禁和本轮全新上下文独立复验均通过；最终 PASS 仍只受 `#37198` 与后续获批 main 同步阻塞。

## 实质修改

- Team snapshot 同 generation/no-op 改为完整领域结构等价；reconcile 按 committed Fact 去重并保留同进程未提交 observation；退休重试绑定历史 Retire change，不冻结后续合法 Root state。
- Root rollout 先物化，再写最小 typed Session/Root lineage intent，最后提交 generation 1；缺 lineage/state 任一半边均拒绝 cold resume。初始 unknown/unavailable 在原 owner 内读回/reconcile/retry，仍不确定时保留 degraded Session owner，由产品 Team capability 入口继续恢复。
- snapshot/lineage 所有 core 读取均在分配前做 regular-file 与长度检查，并以上限加一字节读取；unknown CAS 的同 permit 读回补目录持久化屏障。
- LocalThreadStore 单删/批删在同 store 存在 live writer 时预检拒绝，不再移除 recorder 或 detach authority；关闭 writer 后维持既有删除行为。

## 验证

- `just fmt`：通过。
- `just clippy -p codex-team-state -p codex-thread-store -p codex-core`：通过；watchdog `20260824-163232-1000-3944404`。
- `just test -p codex-team-state --lib`：153/153 passed，1 skipped；watchdog `20260824-163014-1000-3937377`。
- `just test -p codex-thread-store --lib`：188/188 passed；watchdog `20260824-160606-1000-3868752`。
- core 本地介质与真实子进程：3/3 passed；watchdog `20260824-162240-1000-3894135`。
- core close/config/跨进程聚焦：7/7 passed；watchdog `20260824-163050-1000-3939346`。
- 产品 Session cold resume 与“创建成功后立即非优雅退出、再定位恢复并 mutation”：2/2 passed；watchdog `20260824-162913-1000-3935257`。
- 产品回归首次执行因环境代理把 loopback mock 请求返回 502 而 0/2；保持原测试切片，仅设置 `NO_PROXY=127.0.0.1,localhost` 后上述 2/2 通过。该失败未修改产品或断言。
- 按审查修复边界未重跑完整 workspace；未运行 Docker、真实 API、模型、训练、eval、CI 或远端动作。

## 独立复验

- 全新上下文审查者首轮发现 1 项中等级 finding：initial CAS Unknown 后连续存储 Unavailable 会丢失 `N+1` 仍可能已提交的信息。
- 已让 `mark_durability_failure` 在该转换中保留 `Unknown { expected_generation: N }`，新增连续两次读取失败后恢复并接受 `N+1` 的回归。
- 修复后目标回归 1/1、team-state 完整 153/153（1 skipped）和 `just clippy -p codex-team-state` 均通过；最终 watchdog 分别为
  `20260824-164626-1000-3986381`、`20260824-164709-1000-3988460`、`20260824-164722-1000-3989433`。
- 同一独立审查者最终结论：`ACCEPT`，无剩余高/中 correctness finding。
