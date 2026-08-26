# Plan 082 付费前阶段 A 整改复验

时间：2026-08-26 ｜ 审查提交：`e7b754ce9afa37f2efe387b4a42bf50e3e4cc8e3`

## 结论

`PHASE_A_REMEDIATION_REVIEW_NOT_ACCEPTED / PAID_GATE_PENDING`。

上一轮 9 个 Medium 的原始失效路径均已关闭，整改的总体方向和大部分实现成立，未发现 High；但当前仍有 2 个 Medium
correctness/functionality finding。第一项会把 scope 内已经发生的真实参数更新误判为整步 no-op，第二项会让 handoff manifest 的生成动作
污染并破坏正式保留工件。两者都可能在付费 commissioning/formal 或 Pod 释放前收口阶段造成可避免的中断，因此阶段 A 尚未通过。

本次不授予、也不传达阶段 B 付费授权。执行者应继续在原 task branch 做局部修复和直接回归；无需增加逐 tensor hash、签名链、通用
审计平台或第二套工件体系，具体实现策略由执行者自主选择。

## 中等级问题

### 1. 单参数探针会把 scope 内真实有效的更新误判为数值 no-op

- `plan082_adapter.py` 的 `_parameter_change_probe()` 只克隆按 `numel/name` 排序后的第一个非零梯度参数；optimizer step 后也只比较这个
  参数。如果它因 BF16 舍入或参数尺度而保持不变、同一 scope 的另一个非零梯度参数实际改变，实现仍抛
  `plan082_update_parameter_unchanged`。
- 已用现有 fixture 独立复现：scope 同时包含 `tail.bias` 和 `tail.weight`，optimizer 只让 `tail.weight` 从 `0` 变为 `0.125`，
  `tail.bias` 保持不变；当前实现仍报 unchanged，`global_step` 留在 `0`，但模型已经发生真实变化。
- 这不是无害的保守拒绝：recipe 合同仍支持 `bfloat16`，扩大 scope 后该路径可真实到达；commissioning 或 formal 会在一次参数更新已经
  发生后错误中断并消耗当前运行状态/namespace。
- 修复验收：成功 receipt 必须证明当前 scope 的非零梯度参数中至少一个实际改变；只有全体均未改变时才拒绝为 no-op。实现可自行选择
  更省显存的证明方式，或有证据地收窄精度合同，不要求逐步复制或散列全模型。

### 2. retained bootstrap 输出可写进正式 artifact tree 并破坏工件

- `plan082_handoff.py` 的 `create_retained_bootstrap_manifest()` 会先验证并扫描正式 retained artifacts，随后把 `destination` 直接交给
  `write_exclusive()`；它没有要求输出位于 task root 内且位于 artifact root 外。
- 已独立复现：把 destination 指向
  `artifact_root/recovery-checkpoints/<checkpoint-id>/bootstrap.json`，producer 成功返回并写入文件；紧接着同一 checkpoint 的
  `Plan081ArtifactStore.verify_checkpoint()` 报 `plan081_artifact_tree_mismatch`。
- 这会让 Pod 释放前必须执行的 handoff bootstrap 生成动作反过来污染正式 checkpoint/observation/snapshot tree，使后续 0 Pod inventory、
  下载或最终验证失去有效来源。
- 修复验收：写入前 fail-closed 约束 destination 是 task root 内、artifact root 外的安全新输出，拒绝相同路径、祖先/后代和符号链接
  alias；负例应证明失败发生在任何写入前。无需扩大到通用文件系统审计设施。

## 已核验通过的部分

- worktree 审查开始时 clean，HEAD 为执行者声明的 `e7b754ce9afa37f2efe387b4a42bf50e3e4cc8e3`；未合并、rebase 或推送。
- 上一轮 9 项原始问题的目标失效路径均已关闭：全 no-op 不再被接受；formal 绑定 exact base、真实 checkpoint 和完整 history；输出冲突
  前置；环境 freeze、retained artifact 投影、稳定 bootstrap receipt、0 Pod 本地入口、完整 validation guard 和 Plan 081 fixture claim
  边界均已落地。上述两项是整改策略的剩余 false-negative/路径隔离缺口。
- Plan 082 training/handoff/scripts、Plan 081 training、Plan 068 handoff 共 `81/81` 相关轻量测试复跑通过；五支 shell `bash -n`、
  `git diff --check 9637bbe..e7b754ce` 通过。
- inventory/download 两个真实 wrapper 的 `--dry-run` 均通过，绑定当前 worktree、固定 venv 和完整 7 包闭包，回执为
  `secret_access=false`、`network_access=false`；未构造 S3 client。
- source archive 现场为 `2150400 B`，SHA-256
  `f78b91c68c715934b35f5fbfb779ba309b1215c5c600b99dc73f92d6cef801d9`，与执行者汇报一致。数据投影和 archive 未被本轮整改改变；
  本次不重复扩大数据测试。
- 审查未读取 `.env.local` 或任何凭据，未访问 RunPod/HF/S3，未查询或创建 Pod/网络卷，未下载或加载真实模型，未运行训练、Cargo、
  Docker、全 workspace 或其它付费/外部状态变更。

## 替用户作出的决定

- 阶段 A 本轮仍不通过；任务目标尚未完成。
- 付费阶段继续保持未授权。只有上述 2 项 correctness/functionality 缺口修复并重新通过阶段 A 验收后，才能再等待用户本人明确人工批准。
- 除这两项必要修复及直接回归外，不要求新增设施；执行者可以采用证据充分的更优局部方案。
