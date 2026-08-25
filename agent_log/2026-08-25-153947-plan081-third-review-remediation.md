# Plan 081 第三轮复验整改

## 结论

- 第三轮复验的 2 个 P2 与 1 个 P3 均确认存在，并在 Plan 081 原范围内完成窄整改；不需要重规划或扩大设施。
- 两路定点与一轮全 diff 只读复核未发现剩余或新增 P1/P2。
- 当前等待指定审查者再次复验；`LOCAL_TRAINING_READINESS_PASS` 尚未成立。

## 实质修改

- checkpoint 资格现在实际执行 model payload load、scope 重建与核对、optimizer/scheduler/RNG/data state restore 和 cursor 核对；
  新 checkpoint 与最新缺 marker checkpoint 均须先通过该资格，才可淘汰旧恢复点或发布 retention completion。
- 首 checkpoint 前 post-update 失败后，原失败 controller 可用 fresh adapter 从 exact base 重启：adapter 先显式断言 fresh exact base，
  重算结果必须精确匹配既有 write-once base observation，随后保留旧 orphan 并预留新 attempt generation。
- cloud handoff 的 required inputs/outputs 按当前冻结合同精确校验，删项、增项或换序均拒绝。

## 验证

- Plan 081 fixture/fake 31/31 通过；连同 7 项 Plan 060/066/073 精选历史回归共 38/38 通过。
- 新回归覆盖不可加载 model payload、可解码但不可 restore 的 state、坏 checkpoint resume 不得删除旧锚，以及首 checkpoint 前
  snapshot 失败后同 store exact-base 新 attempt 重启；cloud 必要项删除、增项与换序拒绝亦受覆盖。
- 3 个变更 Python 文件无落盘编译、100 字符行检查与 `git diff --check` 通过。

## 边界

未运行真实模型、推理或训练，未使用 GPU、云端、Docker、Cargo、全 workspace 或外部写操作；未读取 unseen 正文、`.env.local`、
模型权重或 checkpoint，未修改其它任务 worktree 或 ignored 大型资产。
