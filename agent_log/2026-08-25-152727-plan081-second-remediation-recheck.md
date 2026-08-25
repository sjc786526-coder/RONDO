# Plan 081 二次整改指定审查复验

## 结论

- 复验对象：`74ede884879a098ce53236b04efc2940f69909ac`。
- 当前结论：**验收不通过 / 任务目标失败（针对当前提交，继续整改后复验）**。
- 上轮 checkpoint state reader 读回顺序和 retention tombstone 半删幂等问题已关闭，但完整恢复闭环仍有 2 个 P2；另有 1 个
  非阻塞 P3。无 P1。
- 这些问题均属 Plan 081 范围内普通 correctness/合同问题，不构成 `REPLAN_REQUIRED`，无需真实模型、GPU、云端、Docker、Cargo、
  registry、复杂审计或可信设施。

## Findings

### P2-1：新 checkpoint 的资格检查尚未证明 adapter 能完整恢复

`plan081_controller.py:281-305` 已正确把新 checkpoint 的 reader 读回放在 controller state 切换、prune 和 completion marker 之前；
但 `_qualify_checkpoint()`（约 `plan081_controller.py:330-360`）只证明 state 可解码、controller state 相等、四个顶层 section 是 Mapping
且 data cursor 相同。模型 payload 真正加载和 optimizer/scheduler/RNG state 真正恢复直到 resume 的
`plan081_controller.py:424-431` 才发生，此时旧恢复点已经可能被删除。

两个独立轻量反例均通过现有资格检查：

- step 4 `save_model` 返回成功但写入 manifest-valid、adapter 无法加载的 payload；`run()` 仍返回 `completed`，新 marker 已发布、旧 cp2
  已删除，resume cp4 才报 `JSONDecodeError`。
- step 4 state 可由 reader 解码，四块均为 Mapping 且 cursor 正确，但 optimizer/scheduler/RNG 不满足 adapter restore 契约；同样先
  completed/marker/prune 旧 cp2，resume 才报 `KeyError` 或 scope mismatch。

这与“verified complete checkpoint 才能替代旧恢复点”的合同冲突。整改应在淘汰旧锚前提供轻量 adapter 级完整恢复资格接缝，或保留旧锚
直到新锚首次完成等强恢复验证；具体实现由执行者自主选择。focused 回归至少覆盖模型 payload 不可加载和 state 可解码但不可 restore 时，
不得 completed、不得发布 marker、不得 prune 旧恢复点。不要求真实模型加载或通用可信设施。

### P2-2：首个 checkpoint 前的 post-update 失败没有可执行的恢复或重启路径

`ControlPlan` 允许首个 checkpoint 晚于 step 1。若 step 1 update 后的 validation/snapshot 等阶段失败，controller 会进入
`recovery_required`，但 `latest_checkpoint_id=None`；同实例按合同不能继续，相同 artifact store 新建 controller 又会撞固定 write-once
`base-step-000000`。

独立复现中，step 1 snapshot 失败后得到 `status=recovery_required`、`latest_checkpoint=None`；用新 adapter 在同 store 重建立即报
`plan081_observation_write_failed`。这使普通早期失败只能依赖未定义的人工换根操作，与 README 所述“失败后从完整 checkpoint 恢复”及
开发期可修复重跑边界不一致。

整改可建立 base/initial recovery anchor，或明确实现同 task store 内 fresh attempt 从 exact base 重启的等强语义；不要求固定具体路线。
focused 回归应覆盖首 checkpoint 前 update 已发生后的失败，并证明新 adapter 能从明确锚点恢复或从 base 以新 attempt 安全重启，旧的
write-once 记录不被覆盖。

### P3：cloud handoff 的必要输入/输出列表没有冻结必要项

`plan081_contract.py:380-392` 只验证 `required_inputs` / `required_outputs` 是非空、唯一字符串列表；删除
`separate_external_action_authorization`、same-cohort comparison policy 或 `better_than_base_candidate_or_no_improvement` 仍能通过。
当前 JSON 内容正确，但 validator 没有守住该合同。建议直接按当前两份小列表精确验证并补删项回归即可，不新增 schema 平台。

## 已确认关闭且未退化的事项

- 新 checkpoint 的 state reader 解码、controller state、四块顶层结构和 cursor 检查已正确前置；本轮 P2-1 只补足 adapter 级完整恢复资格。
- verified discard 的严格 tombstone、半删续清、near-miss fail-closed、多 checkpoint 从新到旧隐藏及 snapshot 后置删除已闭合。
- strict training best、better-than-base tolerance、稀疏 scope turning、train/validation overlap 拒绝及 typed cohort receipt 未退化。
- exact 1.7B 非 LoRA 路线、A40/L40S、12 小时/15 USD、Plan 082 另行授权及 fake/真实证据边界保持正确。

## 独立验证

- Plan 081 专用 fixture/fake：`29/29` 通过。
- Plan 081 加精选 Plan 060/066/073 回归：`38/38` 通过；本轮两个 P2 不在现有用例覆盖内。
- 两类不可完整恢复 checkpoint 及首 checkpoint 前 snapshot 失败均在 `/tmp` 临时目录复现。
- `git diff --check a21d290..74ede884` 通过；复验前工作树 clean，未产生 `pyc`、ignored Plan 081 资产或重型产物。
- 未运行真实模型、GPU、云端、Docker、Cargo、全 workspace、unseen 或 `.env.local`。

## 代用户作出的决定与后续

- 执行者继续在现有授权和 worktree 内完成上述两个 P2 的窄整改，并建议同时关闭低成本 P3；可采用有充分证据的更优等强方案。
- 当前不更新 `doc/WBS-COMPLETED.md`，不把 Plan/WBS 状态改成 PASS，不合并、不推送。
- `LOCAL_TRAINING_READINESS_PASS` 尚未成立；完成 focused 回归、提交并再次通知指定审查者后复验。
