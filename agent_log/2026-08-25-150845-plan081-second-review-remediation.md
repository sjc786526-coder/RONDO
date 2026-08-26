# Plan 081 整改复验二次整改

## 结论

- 已分别复现并确认整改复验报告的 2 个 P2；均属 Plan 081 范围内 correctness 问题，不需要重规划或扩大设施。
- checkpoint 读回资格与 retention 半删幂等恢复均已整改；内部组合复核继续发现并关闭 2 个相邻 P2，整改后未发现剩余或新增 P1/P2。
- 当前仅等待指定审查者再次复验；`LOCAL_TRAINING_READINESS_PASS` 尚未成立。

## 实质修改

- 新 checkpoint 在更新 controller state、淘汰旧恢复点和发布 completion marker 前，必须由当前绑定 reader 读回；读回 controller state
  需与待提交状态一致，training state 必须保有 optimizer/scheduler/RNG/data 四块 Mapping，data cursor 必须与 update receipt 一致。
- postpublish 异常 reconciliation 复用同一资格检查；只有已通过资格验证的新 checkpoint 可成为恢复锚点，资格失败明确回退旧 committed state。
- 已验证且明确 discard 的 snapshot/checkpoint 先在同一父目录原子改名为严格 `.<artifact-id>.prune-<32hex>` tombstone，再删除树；
  resume 和直接 prune 重试只续清这两个 namespace 的精确 tombstone，近似 hidden 名称继续 fail closed。
- retention 按解析后的 `(generation, step)` 从新到旧隐藏 superseded checkpoint，再删除 snapshot；任一中途失败时仍可见的旧
  checkpoint 不会依赖已先删除的旧 best 恢复点，snapshot 半删时对应旧 checkpoint 也已不可恢复。

## 验证

- Plan 081 fixture/fake 29/29 通过；连同 7 项 Plan 060/066/073 精选历史回归共 36/36 通过。
- 新回归覆盖 writer 产物不可解码、training state 结构非法、data cursor 错误，均不得 prune/marker 且可从旧 checkpoint 恢复；
  覆盖 discard tree 在 tombstone 内丢失 manifest 后删除失败、旧 checkpoint 拒绝、fresh 新 checkpoint resume 与直接 prune 幂等续清，
  near-miss hidden 拒绝，以及 cp2/cp4/cp6 多 checkpoint 中断后从安全旧点继续且保留旧 best。
- 3 个变更 Python 文件无落盘编译检查、100 字符行检查与 `git diff --check` 通过。

## 边界

未运行真实模型、推理或训练，未使用 GPU、云端、Docker、Cargo、全 workspace 或外部写操作；未读取 unseen 正文、`.env.local`、
模型权重或 checkpoint，未修改其它任务 worktree 或 ignored 大型资产。
