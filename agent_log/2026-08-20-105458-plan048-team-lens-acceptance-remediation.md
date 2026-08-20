# Plan 048 Team Lens 验收返修

- 逐项复现验收提交 `a3f7c20` 的 4 个阻断，确认均为真实 consumer 缺口，不需要 hook。
- SessionSource parent 提取改为只识别结构正确的 thread-spawn；turn 结束按冻结原生 reducer 语义关闭 running inference，
  late terminal 仅补 usage；invocation 缺失时从 typed Other/MCP kind 恢复工具名/namespace。
- Team Event/Version/Route/Fact 及双向关系改按 `(first_seq, stable_id)` 统一排序，schema v1 同步拒绝乱序合同，避免报告层
  重新猜测顺序。
- 新增 5 项窄回归；Team Lens 定向测试 25/25 通过。指定 24/24 个 RONDO bundle 归约成功，重复 JSON/HTML 字节一致，
  CLI help/reduce/report 与 JavaScript 语法 smoke 通过。
- 未修改 Rust/runtime/Team State/M-5 reader，未触发 hook、`eval-sync`、Cargo、Docker、API、模型或全量测试。
