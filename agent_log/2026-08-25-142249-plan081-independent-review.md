# Plan 081 指定审查者验收

## 结论

- 审查对象：`f954d3049cad5662d2b251cc78b02766d0a99497`。
- 当前结论：**验收不通过 / 任务目标失败（针对当前提交，整改后可复验）**。
- `LOCAL_TRAINING_READINESS_PASS` 尚未成立；以下问题均是 Plan 081 边界内可修复的 correctness 缺口，不构成
  `REPLAN_REQUIRED`，也不需要扩大真实模型、GPU、云端、Docker、Cargo 或复杂审计设施。
- 共发现 4 个 P2；无 P1。文档归位、云端授权边界、Plan 080 并行边界及 fake/真实证据区分本身没有 finding。

## Findings

### P2-1：update 后的 observation/checkpoint 失败会留下不可安全续跑的半提交状态

`plan081_controller.py:193-247` 先让 adapter 修改模型，再追加 update 并推进 `current_step`，随后才完成 observation、snapshot、
retention 和 checkpoint。任一后半段失败后，直接再次 `run()` 会从下一 step 开始，永久跳过当前必需的 observation/checkpoint；
若模型已更新但 receipt 校验失败，直接重试还可能重复同一 update。`_record_observation()` 又在 state record 入列前依次写入 write-once
observation 和 snapshot，简单回退计数也不能处理 observation 已存在但 snapshot 未发布的窗口。

独立复现中，step 1 的暂态 observation 失败后状态为 `running / current_step=1 / updates=1 / observations=0`；修复输入后直接重跑虽返回
`completed`，最终 checkpoint 在 resume 时以 `plan081_checkpoint_observation_history_invalid` 被拒绝。另一次 checkpoint 保存失败后，
控制器保留了一个不存在的 `latest_checkpoint_id`，再次 `run()` 仍返回 `completed`。

整改需使一次 step 的 update、observation、snapshot 和按计划 checkpoint 具有明确的提交/失败恢复语义：普通失败不得静默跳步、重复更新、
留下虚假 latest 指针或宣称 completed。具体可采用 pending phase、显式 fail-closed 后从已验证 checkpoint 恢复、attempt 重放或其它等强方案；
不限定实现路线。应增加 update receipt、observation/snapshot、checkpoint 和 scope expansion 相邻失败窗口的 focused 回归。

### P2-2：best/candidate 与 turning-point retention 在合法组合下给出错误结果

`plan081_controller.py:780-787` 使用带 tolerance 的 `compare_values()` 选择 training best。若每次相对当前 best 的小幅提升均未超过容差，
累计提升即使已经相对 base 构成 `improved`，也不会成为 training best。复现 `tolerance=0.05, base=2.00, step1=2.04,
step2=2.08` 时，step 2 observation 明确给出 `base=improved`，selection 却仍选择 step 1 并输出 `no_improvement`；后续 retention
还可能删除真实最佳 step 2 工件。

此外，`ControlPlan` 允许稀疏 observation，但 `expanded` 只在 scope 实际生效的单个 update 内传递到同 step observation
（`plan081_controller.py:193-217,407-415`）。若在一个 observation 后安排下一 update 扩大 scope，而下一 observation 隔了多个 update，
扩大事实虽进入 scope history，却不会成为 turning point，对应首次 expanded-scope snapshot 也不会按转折点保留。

整改需把“训练序列中的实际 best”和“相对 base 是否超过比较容差”分开计算，并保证合法的稀疏 observation 配置不会丢失 scope expansion
转折语义；也可以收紧配置合同，但必须保持 runtime-configurable 且给出清晰错误。增加小幅累计改善与稀疏观测扩层的 focused 回归即可，
无需统计显著性或复杂选择设施。

### P2-3：Plan 081 组合边界未保持 train/validation 隔离，也未把 logits 绑定到声明的 validation cohort

控制器分别计算 train 与 validation identity，却没有检查二者 candidate ID 不相交。独立构造两套 `proposed_split` 各自正确、但 candidate ID
完全重叠的数据后，controller 仍能 initialize/run 并声明 `typed_train_only_input_bound=True`。Plan 066 canonical loader 虽有交集检查，
Plan 081 对拆开的两个 dataset 建立自己的组合边界后仍需保持这一不变量。

同时，`plan081_controller.py:341-354` 无参数调用 `adapter.evaluate_validation()`，receipt 也没有 validation identity；随后只按 candidate ID
keyset 接收 logits，却把 controller 自身 dataset identity 写入 observation。这样相同 ID、不同 packet/render 的评分可能被错误归属为当前
validation cohort。

整改需在 controller 组合边界拒绝 train/validation 重叠，并让 validation 调用或 receipt 以简单、可测试的方式绑定 controller 当前持有的
validation identity/cohort。实现可由 controller 传入 typed dataset/identity，或由 adapter 返回并核对 identity；不要求建立 provenance、签名或
可信体系。增加 overlap 与错误 cohort receipt 的 focused 回归。

### P2-4：完整 recovery checkpoint 的可插拔 state codec 没有接入 controller

`Plan081ArtifactStore.save_checkpoint()` / `read_checkpoint()` 已提供 `state_writer` / `state_reader` 接缝，但 controller 在
`plan081_controller.py:235-246,270-272` 均未传入，因而固定使用 `plan081_artifacts.py:390-391` 的 JSON writer/reader。真实
optimizer、scheduler 和 RNG state 通常包含 Tensor、tuple、整数键或其它需要保型的状态，不能通过当前 JSON 路径可靠往返；现有 fake
仅因状态都是小型 JSON mapping 才通过。

整改需把既有 codec 接缝接到 controller/adapter 生命周期，使后续真实 adapter 无需重设计 checkpoint 控制即可选择安全的状态格式；不要求
本任务导入 torch 或保存真实模型，可用轻量的非 JSON/需保型 fake state 做 round-trip、resume 和 tamper/failure focused 回归。

## 独立验证

- Plan 081 专用测试及精选 Plan 060/066/073 回归：`19/19` 通过，耗时约 `0.22s`。
- canonical 物理无 unseen bundle 只读复核：train `128/58`、validation `55/26`；两项 identity 与执行日志一致。
- `git diff --check 4e2b717..f954d304` 通过；审查前执行者工作树 clean，未发现 `pyc`、ignored Plan 081 资产或重型产物。
- 未运行真实模型、GPU、云端、Docker、Cargo、全 workspace 或 unseen 流程，未读取 `.env.local`。

## 代用户作出的决定与后续

- 上述 finding 都按普通范围内 correctness 问题处理：执行者应自主修复、补 focused 回归并重跑相称门禁，不申请重规划。
- 修复策略由执行者自主选择；报告中的建议只是可行方向，可以采用证据充分的更优等强方案，不建设额外审计/可信平台。
- 当前不更新 `doc/WBS-COMPLETED.md`，不把 Plan/WBS 状态改为 PASS，也不合并或推送。执行者完成全部整改并提交后，再通知指定审查者复验。
