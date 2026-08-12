# Plan 015 增量编排与安全恢复

- v9 未被中止或改写；自然收口为 blocked。其 Oracle 10/10、wire canary `$0.143029`、首个正式任务
  `$0.425953` 与后继累计 debit `$282.287684` 均从既有 state/receipt/budget 复核，reservation 为 0。
- 新 Oracle store 逐题原子保存 proof，再由十题 manifest 聚合。proof 绑定 task/source/image、verifier、共享执行
  组件、Harbor/TB、seccomp 和稳定 Docker 事实，不绑定 campaign、provider profile、wire canary 或整个 Git commit。
- B7 coordinator 改为轻量 campaign lease；每个 Oracle/paid task 单独进入 build lock/watchdog，锁内执行实时门禁、
  单 slot、Docker 清理、最终资源计数和 durable state。恢复只接受 public result 与 settled budget 完整一致的 running
  slot，其他含糊状态 fail-closed。
- 161 个 slot 继续机械派生；active pointer 当前关闭，v1—v9 只读。identity generator 从 predecessor terminal state、
  wire receipt 与完整 budget 重算 prior，并拒绝版本、run-ID、profile/bundle、cap 或 debit 漂移。
- 验收：focused 185/185、完整 pure/fake/loopback eval 420/420、`just eval-lock` 85 packages、`git diff --check`
  通过。本批未调用真实 API、Docker 或 Cargo，未读取 `.env.local`，未修改任何 v1—v9 历史资产。
- 生成器随后冻结 v10：`p2-b7-canary-baseline-v10`、`p2-b7-canary-sol-sol-v10`、run ID base
  `20260812-300000000`、lock SHA `3e51aa222cc222890627036221a8a235e0ff6d95b0c5491b84eb9a2cb48d5d32`，
  prior `282.287684 USD`。首题 Oracle 官方任务与 Docker 清理完成，但 proof 发布调用了强制 paid metrics 的 B2
  receipt 而在落盘前停止；无 state/slot/API/费用。新增 Oracle 专用 compatibility receipt，保持 paid receipt 门禁，
  focused 108/108 与 lock 通过。
