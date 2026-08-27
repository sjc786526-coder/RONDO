# Plan 087 非付费阶段 A 首轮整改复审

## 结论

- 验收状态：**不通过**。
- 阶段目标：**当前整改批次尚未完成，可经一次窄修复后复验；这不是 Plan 087 研究路线失败**。
- 付费门：**继续关闭**。本报告不批准查询或变更云端实时状态、上传、下载/运行真实模型、训练或产生费用。
- High finding：0；Medium finding：1。

## Medium finding

### 创建后的网络卷缺失仍会被接受

`training/publication-critic-plan087/runpod-create.py:235` 仅在 `networkVolume` 非空且 ID 错误时拒绝；当显式
`pod get --include-network-volume` 返回缺失字段或 `null` 时，当前实现仍会签发成功 receipt。此时 image、GPU、区域、container disk 和 mount
字符串虽已匹配，但实际任务网络卷尚未得到确认，训练可能落在容器盘并在 Pod 终止后丢失 checkpoint。现有漂移回归只覆盖错误的非空卷 ID，
没有覆盖卷缺失或 `null`。

这属于上一轮 Pod 配置绑定 finding 的最后一个窄缺口。修复无需增加通用云编排或审计设施：创建确认必须最终观察到精确
`networkVolume.id == requested network_volume_id`；初始化期间若字段暂缺，可以在已有有限 deadline 内继续查询，超时则 fail closed。补充缺失/
`null` 拒绝（以及如采用轮询则覆盖稍后出现正确卷）的定向回归即可。具体等强、更简洁的实现由执行者自主选择。

## 已关闭事项

- 同名 Pod 不再跨调用按名称领养；只允许空账户基线后的单次 create 在同一调用内消解不确定响应，且不会盲目二次创建。
- 创建后已经核对 ID/name、image、GPU、区域、container disk、mount 和 provider 实际返回的止费字段；错误配置会拒绝。
- 弱路线可在完整 observation + checkpoint 点提前 `not_promising` 收口；`none`、必要恢复点与 promising candidate 的恢复职责已经分离。
- 新 exact-base 路线可按实际 inventory 选择更窄、更宽、不同模块或全参数；只在同一路线后续 phase 保持实际参数集严格扩展。
- Plan 081 checkpoint qualification、候选级不同 OS 进程恢复及 Plan 082 fixed recipe 历史语义没有被混淆或放宽。

## 审查验证

- 整改提交 `c86f030cb6b7a4296f52062cdf0eaa3eab2228ef` 位于 Plan 087 专用 worktree；审查开始时 tracked 状态 clean，未合并、未推送。
- Plan 081/082/087 七个相邻聚焦测试独立复跑：`90 passed, 44 subtests passed`。
- 定向 Ruff `E9/F63/F7/F82`、三个 shell 的 `bash -n`、`git diff --check d0574ab..HEAD` 通过。
- source archive 独立 exact-tree 复验通过：2,334,720 bytes、120 files、commit `c86f030`、SHA-256
  `08801415b44da0586dc68cec16547025353566b3a7009bf6372bd2b8e3f58091`。
- data bundle 独立复验通过：808,960 bytes、SHA-256
  `6d98c163a2b1f64cf23eec8357b3158ed56e7a2719fbfeb84eb0aa21ee888163`；train 128/58、validation 55/26、physical unseen 0。
- 两路独立只读复验分别覆盖 adaptive training/recovery 和 Pod creation；训练路线 finding 已全部关闭，Pod 路线保留上述一个 Medium。
- 未访问 RunPod/Hugging Face live 状态，未运行 Cargo、Docker或真实模型，未训练或产生费用。

## 代用户作出的决定

- WBS 按用户最新指示继续不改，等 Plan 087 整体最终验收通过后统一更新。
- 只修复网络卷缺失/`null` 的确认与相称回归，不扩大成通用资源审计、可信或编排设施；其余已闭合设计不要求返工。
- 修复、聚焦回归和提交均属既有非付费授权范围，无需另行请示；复验明确通过前付费门保持关闭。
