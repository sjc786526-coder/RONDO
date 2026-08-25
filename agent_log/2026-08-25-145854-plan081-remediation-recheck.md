# Plan 081 指定审查整改复验

## 结论

- 复验对象：`ea023e6902090cde51a185b158cde5789acbb295`。
- 当前结论：**验收不通过 / 任务目标失败（针对当前提交，继续整改后复验）**。
- 首轮 P2-2（best/retention 选择）和 P2-3（train/validation/cohort 绑定）已完整关闭；首轮恢复整改又暴露 2 个相邻 P2，
  `LOCAL_TRAINING_READINESS_PASS` 仍未成立。
- 两项均属 Plan 081 范围内普通 correctness 问题，不构成 `REPLAN_REQUIRED`，无需扩大真实模型、GPU、云端、Docker、Cargo 或
  复杂审计/可信设施。

## Findings

### P2-1：checkpoint 在淘汰旧恢复点前没有用声明的 reader 读回验证

`plan081_controller.py:255-295` 调用自定义 writer 保存 checkpoint 后，直接把它作为新状态执行 retention 并发布 completion marker；
绑定的 reader 直到 `resume()`（约 `plan081_controller.py:332-368`）才首次使用。artifact manifest 只能证明 writer 产生的字节未被随后
篡改，不能证明这些字节能被同一 codec 解码并恢复 optimizer/scheduler/RNG/data cursor。

独立复现中，自定义 writer 正常返回但写入不可解码内容，`run()` 仍返回 `completed`，`has_retention_completion=True`，且 retention
可先淘汰旧恢复点；随后使用同 codec resume 报 `plan081_training_state_decode_failed`。这会把不可恢复 checkpoint 标成已经验证的替代点。

整改需在 prune 旧恢复点和发布 completion marker 之前，用当前绑定 reader 读回新 checkpoint，并核对 controller state、training state
结构及 data cursor 等现有恢复不变量。具体可以复用当前 `read_checkpoint` / resume 校验能力或采用其它等强的轻量 preflight；不要求
额外签名、registry 或通用可信设施。增加 writer 产生不可解码或错误保型内容时不得 completed/不得 prune 的 focused 回归。

### P2-2：retention 删除中途失败会留下不可重试的残树

`plan081_artifacts.py:172-214` 验证 keep/discard 工件后直接逐个 `shutil.rmtree`。若删除过程中发生普通 I/O 错误，目录可能只删除了一部分。
之后 resume 对最新无 marker checkpoint 重跑 retention 时，`_artifact_ids()` 会再次枚举该残树，prune 又先执行完整 artifact verification，
因此在残树上永久报错，无法到达再次清理。

独立复现中，checkpoint 4 retention 在删除旧 snapshot 2 时先丢失 manifest 再失败；checkpoint 4 已存在、completion marker 不存在，
但 resume checkpoint 4 立即报 `regular_file_missing`。即使回到已完成的 checkpoint 2 重放，新 checkpoint 的 retention 仍被同一残树阻塞。

整改需使任务明确拥有且已经判定为 discard 的工件删除可恢复、可幂等。可采用同目录原子 rename 到严格命名的 task-owned tombstone 后再删、
在 resume 时识别并续清理，或采用其它不会把残树重新当作有效 artifact 验证的等强方案。只处理本 store 已验证所有权和明确 discard 的路径，
不得扩展成 GC、registry 或清理来源不明资产。增加删除中途失败、恢复后续清理与最终正常 resume 的 focused 回归。

## 已确认关闭的首轮问题

- training best 已按实际有限实值最大值选择，better-than-base 才应用 tolerance；累计小幅改善回归通过。
- 稀疏 observation 能把区间内 scope expansion 记录并保留为 turning point，运行态与恢复态重建一致。
- controller 拒绝 train/validation candidate overlap；typed validation dataset 与 receipt identity 已绑定。
- 显式非 JSON codec 已进入 controller save/read 生命周期，整数键、tuple、bytes 保型与 codec mismatch/tamper 路径通过；本轮 finding 只要求
  在发布新恢复锚点前补读回资格，不推翻该 codec 设计。

## 独立验证

- Plan 081 专用测试及精选 Plan 060/066/073 回归：`33/33` 通过，约 `0.64s`。
- 两个新增复现均在 `/tmp` 临时目录完成：坏 writer 被错误标记 completed；retention 半删后最新 checkpoint 无法 resume。
- `git diff --check 3f69d41..ea023e6` 通过；复验前工作树 clean，未产生 `pyc`、ignored Plan 081 资产或重型产物。
- 未运行真实模型、GPU、云端、Docker、Cargo、全 workspace、unseen 或 `.env.local`。

## 代用户作出的决定与后续

- 执行者继续在现有授权和 worktree 内完成这两个窄整改，自主选择简洁等强实现，补相邻 focused 回归后提交并再次通知审查者。
- 当前不更新 `doc/WBS-COMPLETED.md`，不把 Plan/WBS 状态改成 PASS，不合并、不推送。
