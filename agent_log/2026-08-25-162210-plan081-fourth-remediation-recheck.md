# Plan 081 第四轮整改指定审查复验

## 结论

- 复验对象：`867b887f2b02432de6119693123b1e3aa120a8b1`。
- 当前结论：**验收不通过 / 任务目标失败（针对当前提交，继续整改后复验）**。
- disposable fresh probe、跨进程 exact-base restart 及正常未资格 checkpoint 退出 live 集合的主路径已关闭，但仍有 2 个 P2。无 P1/P3。
- 两项均为 Plan 081 范围内普通 correctness 问题，不构成 `REPLAN_REQUIRED`，无需真实模型、GPU、云端、Docker、Cargo、
  registry、journal、复杂审计或可信设施。

## Findings

### P2-1：恢复 state 的普通字典等值比较不能处理合法 Tensor 状态

`plan081_controller.py:1231-1235` 在 restore 后 recapture 四块训练状态，再调用 `_training_states_equal()`；该 helper（约
`plan081_controller.py:1245-1250`）只执行 Python `left == right`，比较异常即返回 `False`。

仓库既有真实 checkpoint 状态包含 optimizer `state_dict()` 与 `torch.get_rng_state()` Tensor。两个 round-trip 后不同对象的多元素 Tensor
执行 elementwise `==`，嵌套字典比较在归约布尔值时会产生 ambiguous-bool 异常；因此即使逐值恢复正确，也会被误报
`plan081_checkpoint_restore_state_mismatch`。当前 fake 只含 bytes、tuple 和普通 Mapping，未覆盖该真实状态形态。

独立轻量反例用多元素 tensor-like 值模拟该语义：两份内容相同的 optimizer state 传入 `_training_states_equal()` 返回 `False`。
这会迫使 Plan 082 修改 controller 比较或扭曲合法 state 表示，尚未达到真实环境可直接消费的恢复合同。

整改可把等值断言交给 adapter/codec 的 tensor-aware 窄 seam，或使用其它能处理实际 state 类型的等强比较；具体策略由执行者选择。
focused 回归至少证明多元素 tensor-like 正确 round-trip 可以通过、任一局部值漂移必须拒绝。无需通用 canonicalization 或审计设施。

### P2-2：未资格 checkpoint 清理失败会跳过 controller 的恢复态回滚

`plan081_controller.py:398-427` 的异常路径先调用 `discard_unqualified_checkpoint()`，返回后才恢复 `committed_state` 并设置
`status=recovery_required`。若 tombstone rename/删除或其它普通 I/O 清理步骤抛错，异常会在状态回滚前再次退出。

独立复现让首 checkpoint state 不可解码，并让已原子 rename 的 checkpoint tombstone 在 `rmtree` 时失败，结果为：

- 抛出 `plan081_artifact_prune_failed`；
- controller 留在 `status=running/current_step=2/latest_checkpoint_id=None` 的 post-update 半态；
- live checkpoint 已退出集合、严格 tombstone 保留。解除 I/O 故障后跨进程入口能够续清并重启，但原实例不再满足
  `restart_from_exact_base()`，也违反“post-update 任一失败进入 recovery_required”的明确合同。

整改应保证 controller 回滚和 `recovery_required` 状态不依赖清理成功；清理错误仍可如实上抛并由既有 tombstone/store 能力重试。
focused 回归应覆盖 discard 在原子隐藏前和隐藏后失败，均不得留下 `running` 半态。无需增加新恢复系统。

## 已确认关闭且未退化的事项

- checkpoint 资格使用 disposable fresh exact-base probe、probe 自身 reader、model-load postcondition、完整 restore 与 recapture；live adapter
  no-op、data-only、self/non-fresh probe 均被拒绝。
- class/store 级跨进程 exact-base restart 已能复用 write-once base、保留 orphan、单调预留 generation；存在 live checkpoint 时要求 resume。
- 正常资格失败的首 checkpoint 会经严格 tombstone 退出 live 集合；旧有效锚、已资格新锚及 stale completion marker 边界未退化。
- retention、selection、train/validation/cohort、cloud handoff 精确清单及 fake/真实证据边界未见回归。

## 独立验证

- Plan 081 专用 fixture/fake：`34/34` 通过。
- Plan 081 加精选 Plan 060/066/073 回归：`43/43` 通过；两个新增反例不在现有用例覆盖内。
- tensor-like 等值误拒与 tombstone 删除失败留下 `running` 半态，均在 `/tmp` 临时目录独立复现。
- `git diff --check 3d931e5..867b887f` 通过；复验前工作树 clean，未产生 `pyc`、ignored Plan 081 资产或重型产物。
- 未运行真实模型、GPU、云端、Docker、Cargo、全 workspace、unseen 或 `.env.local`。

## 代用户作出的决定与后续

- 执行者继续在现有授权和 worktree 内完成上述两个窄整改，可采用有充分证据的更优等强实现；不扩大为通用恢复或审计平台。
- 当前不更新 `doc/WBS-COMPLETED.md`，不把 Plan/WBS 状态改成 PASS，不合并、不推送。
- `LOCAL_TRAINING_READINESS_PASS` 尚未成立；完成 focused 回归、提交并再次通知指定审查者后复验。
