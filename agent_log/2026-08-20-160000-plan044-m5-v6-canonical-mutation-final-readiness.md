# Plan 044 / M-5 v6 canonical mutation 再整改

- 日期：2026-08-20
- 边界：只修改 Gate 1 判据、workflow-v6 语义、定向测试与当前文档；未运行 Docker、Rust、真实 API 或正式 Gate
- 产品身份：workflow-v6 → 未变化的 runtime-v4 (`0eee6dc`) → nondegradation-v6

## 改动

- first member publish、Root publish、second member publish 与 Root route 只有在 completed、结果完整且
  `deduplicated is False` 时才可进入协议；旧 Version 的幂等重试不能冒充 evidence 后的新 Version。
- canonical mutation 的跨线程提交顺序改由精确 inspect-log actor/thread/target/revision 证明；wrapper end 不作
  跨线程提交时钟，同 actor 仍用 end/start。Root wait 与首次成员 publish 以调用区间重叠、精确 member-publish
  wake log 和 TeamActivity 返回绑定；route start 必须先于 evidence start，second publish/update 依赖 revision。
- `team_update` 批量结果允许其它目标及同一 Version 的独立 producer 轴更新，但协议中只能唯一匹配一个成功
  resolve 的成员 Version。
- rehearsal identity 前进到 append-only `m5-g1-rehearsal-v6-r3`；v6/v6-r2 archive 与 raw 未覆盖。

## 验证

- Gate 1/恢复/trace/Docker fake 精确窄回归 105/105；M-5 三模块串行 183/183。
- `just eval-lock`、`just eval-multi-m5-ready`（`ready=true`、formal identity=`not_started`）和 loopback 通过。
- v6-r3 rehearsal：23 requests，20/20 nested dispatch 均来自 code cell，0 Direct/failed；dump 7 页、log 2 页
  到 null；七谓词全真，明文 9、加密/未知 0，trace_error/taint/stop 均为空。新判据本身机械证明计入的
  publish/route 均为 non-deduplicated mutation。
- 独立复核未发现剩余 P0/P1；`git diff --check` 通过。

## 决策与停止边界

沿用审查建议的最小修法，没有修改 trace 采集结构，也没有建设 Docker 自动清理。原因是 TeamStore mutation、
log/wake 在 handler 返回前已经提交，而跨线程 `ToolCallEnded` 只是 wrapper 观测，不能当提交时钟；Harbor-started
资源仍需持锁的受监督精确处理。

正式 v6 archive、ledger、identity receipt 与 paid capture 均不存在，本轮无费用。Gate 1/Gate 2 未启动，
M-5 仍未通过；当前停在正式大规模付费测评之前。
