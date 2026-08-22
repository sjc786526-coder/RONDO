# Plan 057 / M3-B2b Publication Critic 发布接入

工作树：`.claude/worktrees/057-publication-critic-integration`

分支：`worktree-057-publication-critic-integration`

## 实质修改

- 新增默认关闭且绑定 loopback endpoint、expected service descriptor 与 timeout 的 typed 配置；off 注册原 `team_publish`
  schema/output 和同步 store 路径，on 才暴露 review continuation。
- 从 Team State 现行 publish 提取共享只读 canonical preparation，并以同一 store view 返回 permission-scoped、event-local、单页
  history；Critic packet 使用 canonical 副本，raw request ledger 与最终 mutation 仍走原 `publish()`。
- 新增 turn-local 最多三次审核 cycle、两个固定 rewrite 反馈、attempt/committed replay、typed failure fallback、取消清理与同步
  commit 前重查；并发 attempt 由 owned async mutex 串行，但 Critic 等待不持有 Team State mutex。
- continuity 只携带有界公共 publication 与 body-free evidence 数量，不读取 observation 正文、不传 Fact ID；reviewed runtime 的
  dispatch、hook、trace 与普通 log 只记录 typed metadata，candidate 只出现在必要的模型可见 rewrite response。
- 新增正式 Plan 055 服务进程产品测试及 Team State、packet、配置、注册表、replay/race/cancel、trace redaction 定向回归；同步
  Cargo/Bazel 接线、config schema 与 Unix 共享 build/watchdog just 入口。

## 验收结果

- `codex-team-state --lib`：133 passed、1 既有 ignored。
- `codex-core --lib -E 'test(publication_review)'`：11/11 passed；其中 7 条启动
  `codex-publication-critic-service` 正式二进制，覆盖 off/PASS/并发 exact replay/完整 rewrite/failure fallback/取消，所有子进程回收。
- 配置、注册表与 body-redaction 聚焦组：7/7 passed；Team route：8/8 passed；`codex-features --lib`：34/34 passed。
- 受影响 3 crate 的 Clippy `-D warnings` 与 `just fix` 通过；`just fmt`、`just fmt-check`、schema 生成/fixture、Bazel module
  lock update/check、`git diff --check` 通过，module lock 无差异。
- argument-comment Cargo wrapper 在源码检查前因固定 Rust 1.92 nightly 不满足现锁定 `sqlx 0.9.0` 的 Rust 1.94 要求失败；
  Bazel 三目标替代入口经共享看门狗分析 10 分钟后仍未完成，已受控中断且无残留，不记为通过。

## 边界

- 未运行 Docker、真实 API、真实模型、本地推理、训练、量化/转换、云资源、全 workspace、CI 或 PR；没有真实模型质量、
  threshold 或性能结论。
- 未修改 `mydev/`、`eval/`、`training/`、Plan 056、顶层 WBS/COMPLETED 或其他 worktree；未合并、推送、rebase 或归档。
- 本日志创建时实现后的独立验收尚待执行；最终结论在同一任务收口后补充。
