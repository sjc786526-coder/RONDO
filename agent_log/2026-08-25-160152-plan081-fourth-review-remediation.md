# Plan 081 第四轮复验整改

## 结论

- 第四轮复验的 2 个 P2 均确认存在，并在 Plan 081 原范围内完成窄整改；不需要重规划或扩大设施。
- 当前等待指定审查者再次复验；`LOCAL_TRAINING_READINESS_PASS` 尚未成立。

## 实质修改

- 新 checkpoint 资格不再复用 live training adapter：adapter 提供一次性 fresh exact-base recovery probe，probe 使用自己的 codec reader
  读回并在任何 scope/state restore 前证明 model load postcondition，再 restore 并 recapture optimizer/scheduler/RNG/data 四块 state
  与解码值深度等值。
- resume 传入的 adapter 也必须先证明完整 fresh exact-base，restore 后通过同一 recapture 核对；no-op、只恢复 data、返回 live/self 或
  非 fresh probe 均在 retention/marker 前失败并保留旧锚。
- 新增 class/store 级 exact-base 重启入口；原 controller 丢失后仍可复用固定 base observation 并预留新 generation。Store 只枚举、
  校验 live recovery checkpoint，不读取 stale completion marker；存在任何 live verified checkpoint 时先要求显式 resume。
- 整改后全差异复核补出首个 checkpoint 资格失败仍占据 live 集合的 P2。失败且从未发布 completion marker 的本次 checkpoint 现复用
  prune tombstone 原子隐藏并删除；旧有效锚及 postpublish 已通过资格的新锚继续保留，跨进程 exact-base restart 不再被坏首锚卡死。

## 验证

- Plan 081 fixture/fake 34/34 通过；连同 7 项 Plan 060/066/073 精选历史回归共 41/41 通过。
- 新回归覆盖 model/state no-op、data-only restore、self/non-fresh probe、异常抑制与 cleanup failure、携带旧状态的 resume adapter、
  丢弃原 controller 后同 store 重启、首个未资格 checkpoint 清理后跨进程重启、live checkpoint 拒绝和 pruned checkpoint stale marker。
- 两路 checkpoint/restart 定点复核及最终全差异复审均确认无剩余或新增 P1/P2。
- 3 个变更 Python 文件无落盘编译、100 字符行检查与 `git diff --check` 通过。

## 边界

未运行真实模型、推理或训练，未使用 GPU、云端、Docker、Cargo、全 workspace 或外部写操作；未读取 unseen 正文、`.env.local`、
模型权重或 checkpoint，未修改其它任务 worktree 或 ignored 大型资产。
