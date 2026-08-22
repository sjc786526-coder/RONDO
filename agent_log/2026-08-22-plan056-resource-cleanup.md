# Plan 056 大型资源清理

日期：2026-08-22

Plan 056 验收完成后，按用户授权清理其明确归属且可重新生成的大型构建资源：

- 删除 formal-v6 Cargo target
  `eval-data/build/rondo-4965d7483d9e2812ec8e39debdb5988107e8101a-x86_64-unknown-linux-musl`，
  清理前占用 13,593,186,304 bytes。
- 通过 `git worktree remove` 正常注销并删除三份干净的 detached source：`2765ff8f`、`c2be21d0` 和
  `4965d74`，合计占用 534,536,192 bytes。
- 上述明确目标合计 14,127,722,496 bytes（约 13.16 GiB）；清理前后文件系统可用空间实测增加
  14,132,051,968 bytes。

没有删除 formal-v6 runtime bundle、正式 campaign、trace/API metadata、Terminal-Bench 结果、预算账本、
公共结果或 Docker 镜像。旧代和重复发布 bundle 因仍属于发布/复验证据而保留，没有把它们当作普通中间产物
删除。清理后 `just eval-plan056 status` 仍返回 `finalized`、20 个 published slot、候选 C2、费用
`4.677962 USD` 和零 reservation。

删除内容不可直接恢复，但均可从仓库提交重新检出或构建；本次未修改任何受跟踪产品代码。
