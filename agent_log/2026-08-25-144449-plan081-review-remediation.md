# Plan 081 指定审查整改

## 结论

- 已逐项复现并确认首轮指定审查的 4 个 P2；均属 Plan 081 范围内 correctness 问题，无需重规划。
- 整改后由三路定点复核分别检查恢复原子性、选择/数据隔离和 state codec，再由一轮全 diff 独立复核检查组合回归；
  均未发现剩余或新增 P1/P2。
- 当前只等待指定审查者复验；`LOCAL_TRAINING_READINESS_PASS` 尚未成立。

## 实质修改

- post-update 的 receipt、observation/snapshot、checkpoint 或 retention 失败统一进入 `recovery_required`，禁止同 adapter 原地重试；
  checkpoint 发布前回退 controller 状态，发布后只接受可完整验证的新恢复锚点。
- retention 完成以绑定 checkpoint content hash 的小型原子 artifact 标记；resume 仅可为物理最新 checkpoint 补做未完成 retention，
  且在 generation reservation 和 adapter load/restore 前完成，旧已标记 checkpoint 不会重放历史 prune。
- training best 使用严格实值最大值，是否成为 better-than-base candidate 才应用比较容差；稀疏观测按两次 observation 间的 scope
  history 保留扩层转折点。
- controller 拒绝 train/validation candidate 重叠；validation 调用传入 typed dataset 并核对 receipt identity，避免 logits 错绑 cohort。
- adapter 显式提供 state codec id/writer/reader；checkpoint metadata、controller state、恢复解码与 data cursor 在模型加载前共同校验。
  轻量非 JSON fixture 保型覆盖整数键、tuple 与 bytes。

## 验证

- Plan 081 fixture/fake：24/24 通过；连同 7 项 Plan 060/066/073 精选历史回归共 31/31 通过。
- 覆盖累计小幅改善、稀疏扩层、overlap/错误 cohort、各 step 半提交窗口、retention marker 发布窗口、旧 checkpoint resume、
  非 JSON round-trip、codec mismatch、reader/writer failure 与篡改拒绝。
- 3 个变更 Python 文件 compile、100 字符行检查及 `git diff --check` 通过；未临时安装或同步依赖。
- canonical 物理无 unseen 接缝维持 train 128/58、validation 55/26、交集 0；两项 identity 与首轮执行日志一致。

## 边界

未运行真实模型、推理或训练，未使用 GPU、云端、Docker、Cargo、全 workspace 或外部写操作；未读取 unseen 正文、`.env.local`、
模型权重或 checkpoint，未修改其它任务 worktree 或 ignored 大型资产。
