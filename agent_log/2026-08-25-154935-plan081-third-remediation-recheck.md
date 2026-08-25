# Plan 081 第三轮整改指定审查复验

## 结论

- 复验对象：`ce849a8f075a70fcbe28a2bc8ffc0d8a82da2c2e`。
- 当前结论：**验收不通过 / 任务目标失败（针对当前提交，继续整改后复验）**。
- 第三轮报告中的 cloud handoff P3 及 checkpoint 显式 load/restore 失败边界已关闭，但恢复闭环仍有 2 个 P2。无 P1/P3。
- 两项均属 Plan 081 范围内普通 correctness 问题，不构成 `REPLAN_REQUIRED`，无需真实模型、GPU、云端、Docker、Cargo、
  registry、journal、复杂审计或可信设施。

## Findings

### P2-1：checkpoint 资格复用携带现态的训练 adapter，漏恢复实现可以假通过

新 checkpoint 在 `plan081_controller.py:340-366` 把当前正在训练的同一 adapter 交给 `_qualify_checkpoint()`；
`_restore_adapter_checkpoint()` 虽调用 load/configure/restore/scope/cursor 检查，但该实例在刚完成 update 后本来已经携带目标 scope、data
cursor、optimizer/scheduler/RNG 等状态。因此，restore 的遗漏可能被旧内存状态掩盖，不能证明后续 fresh adapter 可以恢复。

独立轻量复现把 fake 的 `restore_training_state()` 改为静默 no-op：

- 当前 adapter 在 step 2 后已有 cursor/scope，资格仍通过，`run=completed`、completion marker 已发布；
- `restored_typed_state=False`，说明 state 实际未恢复；
- 使用相同 no-op 实现的 fresh adapter resume 同 checkpoint 时才报 `fixture_data_cursor_mismatch`；optimizer/scheduler/RNG 的漏恢复甚至
  不一定被 cursor 断言发现。

整改需让替代旧锚前的资格代表 fresh 恢复，而非依赖 live adapter 已携带的状态。可使用 fresh/disposable recovery probe，或由 adapter
提供会先清除携带状态、重建并自证恢复的窄 qualification seam；执行者可选择更简洁的等强策略。focused 回归应证明 no-op/漏恢复实现
不得 completed、不得 marker、不得 prune 旧锚。无需真实模型或通用可信设施。

### P2-2：首 checkpoint 前的 fresh exact-base 重启仍依赖未丢失的内存实例

`restart_from_exact_base()`（约 `plan081_controller.py:163-209`）要求原 controller 仍在内存中且为 `recovery_required`、
`latest_checkpoint_id=None`、`base` 非空。同进程捕获异常后的重启已可用，但首 checkpoint 前若进程直接退出，新进程只剩同一 artifact
store、route/control/datasets 和 fresh adapter，没有公开恢复入口：

- 新 controller `initialize()` 会重新写固定 write-once `base-step-000000`，报 `plan081_observation_write_failed`；
- 新 controller 调 `restart_from_exact_base()` 又因 `created/base=None` 报 `plan081_exact_base_restart_not_allowed`。

独立复现丢弃 step 1 snapshot failure 后的原 controller，即得到上述两项失败；store 中 base 与 orphan observation 均仍在，但无法进入新
generation。这意味着硬中断仍需换 store 或由 Plan 082 重新设计恢复入口，与当前任务的云端就绪和失败恢复交接目标不符。

整改宜提供 class/store 级 fresh exact-base recovery 入口，复用已有 base 精确匹配、exact-base adapter 断言、generation reservation 与
orphan 保留；已有可用完整 checkpoint 时应要求走 checkpoint resume。至少覆盖原 failed controller 已丢失后的新进程式重启，以及已有
checkpoint 时拒绝 base restart。无需新建持久 journal 或训练平台。

## 已确认关闭且未退化的事项

- checkpoint 模型/state restore 显式失败会在 prune/marker 前停止并保留旧锚；缺 marker resume 也先在调用方 fresh adapter 完整恢复，
  再执行 retention。
- 同进程保留原 failed controller 时，首 checkpoint 前 fresh exact-base 新 generation 路径成立；本轮 P2-2 只补跨进程入口。
- cloud handoff 必要输入/输出已按精确有序列表冻结，删项、增项和换序均拒绝。
- reader/codec、tombstone、多 checkpoint retention、best/latest/turning、train/validation/cohort 及 fake/真实证据边界未退化。

## 独立验证

- Plan 081 专用 fixture/fake：`31/31` 通过。
- Plan 081 加精选 Plan 060/066/073 回归：`40/40` 通过；两个新增反例不在现有用例覆盖内。
- live adapter no-op restore 假资格与丢弃 failed controller 后同 store 无法重启，均在 `/tmp` 临时目录独立复现。
- `git diff --check d7589c5..ce849a8f` 通过；复验前工作树 clean，未产生 `pyc`、ignored Plan 081 资产或重型产物。
- 未运行真实模型、GPU、云端、Docker、Cargo、全 workspace、unseen 或 `.env.local`。

## 代用户作出的决定与后续

- 执行者继续在现有授权和 worktree 内完成上述两个窄整改，可采用有充分证据的更优等强实现；不扩大为通用恢复平台或审计体系。
- 当前不更新 `doc/WBS-COMPLETED.md`，不把 Plan/WBS 状态改成 PASS，不合并、不推送。
- `LOCAL_TRAINING_READINESS_PASS` 尚未成立；完成 focused 回归、提交并再次通知指定审查者后复验。
