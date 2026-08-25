# Plan 081 第五轮复验整改

## 结论

- 第五轮复验的 2 个 P2 均确认存在，并在 Plan 081 原范围内完成窄整改；不需要重规划或扩大设施。
- 当前等待指定审查者再次复验；`LOCAL_TRAINING_READINESS_PASS` 尚未成立。

## 实质修改

- `training_states_equal()` 纳入 codec adapter 合同。Disposable probe 与 fresh resume adapter 使用自己的类型感知 comparator 核对
  decoded、restored、recaptured state；异常、非原生 bool 或局部 restore 值漂移均在 retention/marker 前失败。
- 未资格 checkpoint 的异常路径先恢复 committed progress 并写入 `recovery_required`，再尝试原子隐藏/删除；rename 前或 tombstone
  删除失败仍如实上抛 cleanup error，原始资格失败保留为 context，旧恢复锚和 controller 状态不被半提交污染。

## 验证

- Plan 081 fixture/fake 36/36 通过；连同 7 项 Plan 060/066/073 精选历史回归共 43/43 通过。
- 新回归覆盖多元素 ambiguous-bool Tensor-like state 的 checkpoint 与 fresh resume、optimizer 单值漂移、comparator 异常/非 bool、
  以及未资格工件 rename 前和 tombstone 删除阶段失败后的状态收口、续清和旧锚恢复。
- 两路定点独立复核与最终全差异复审均确认无剩余或新增 P1/P2。
- 2 个变更 Python 文件无落盘编译、100 字符行检查与 `git diff --check` 通过。

## 边界

未运行真实模型、推理或训练，未使用 GPU、云端、Docker、Cargo、全 workspace 或外部写操作；未读取 unseen 正文、`.env.local`、
模型权重或 checkpoint，未修改其它任务 worktree 或 ignored 大型资产。
