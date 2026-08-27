# Plan 087 非付费阶段 A 最终验收

## 结论

- 验收状态：**通过**。
- 阶段目标：**完成**。阶段 A 已形成足以安全进入真实云端搜索的非付费准备，不代表 Plan 087 整体研究目标已经完成。
- 付费门：**阶段 A 验收通过，批准进入付费阶段**。
- High finding：0；Medium finding：0。

## 关闭的最后一项 finding

提交 `6dd27d8cd7cc6447c2f6762a3054c55d64dc3237` 已正确关闭上一轮 v2 默认字段 Medium：

- 缺失 `gpu.count` 只按 RunPod v2 官方默认值归一化为整数 1；
- 使用精确整数类型检查，显式 JSON boolean、浮点、字符串及其它 count 不会借 Python 相等语义通过；
- 最终 provider projection 使用归一化值，不再二次索引缺失字段；
- 回归用例同时覆盖缺省成功、最终值为 1，以及显式 `2`、`true`、`1.0` 拒绝。

官方依据：<https://docs.runpod.io/api-reference-v2/pods/get-a-pod>。

## 已确认的阶段 A 边界

- exact Pod ID/name、image、GPU、SECURE cloud、data center、container disk、唯一 network mount 与无 persistent mount 的绑定保持严格。
- pending/final receipt、有限 deadline、空账户后的单次 create、跨调用不领养同名 Pod 以及失败后先止费再重建的语义没有回归。
- exact 1.7B revision、v8 train/validation 与 pair 语义、物理 unseen 隔离、无 LoRA/QLoRA/PEFT/量化训练、validation 不进入梯度等训练边界已由阶段 A 设施和相邻回归闭合。
- 自适应路线仍允许执行者依据真实 parameter inventory 与观测选择更优 scope/优化动态/节奏；没有引入机械路线数或通用调参平台。
- WBS 未改，符合用户要求；只在 Plan 087 整体最终验收通过后统一同步。

## 审查验证

- 审查基线为专用 worktree clean commit `6dd27d8cd7cc6447c2f6762a3054c55d64dc3237`，未合并、未推送。
- Plan 081/082/087 七个相邻聚焦测试独立复跑：`93 passed, 59 subtests passed`。
- 定向 Ruff correctness、三个 shell 的 `bash -n`、RunPod create CLI help、`git diff --check 1c65cb5..HEAD` 与 WBS untouched 检查通过。
- source archive 独立 exact-tree 复验通过：2,355,200 bytes、120 files、commit `6dd27d8`、SHA-256
  `8b59f28d55c69c51fc95997ee82a66b8d964ff978f8b9f2fbd5b101be4e24ccb`。
- data bundle 独立复验通过：808,960 bytes、SHA-256
  `6d98c163a2b1f64cf23eec8357b3158ed56e7a2719fbfeb84eb0aa21ee888163`；train 128/58、validation 55/26、physical unseen 0。
- 独立只读生命周期复审结论为 High 0、Medium 0。
- 本轮未调用 RunPod/Hugging Face live API，未运行 Cargo、Docker 或真实模型，未训练或产生费用。

## 代用户作出的决定与付费阶段授权解释

- 用户原先给出的 Plan 087 一次性外部授权在本报告批准后生效，无需再次向用户申请同一范围授权。执行者可按 ExecPlan 进入阶段 B，先刷新 live 库存、价格、余额、卷兼容性与账户 0 Pod，再在既有硬边界内创建至多一个计费 Pod。
- 任务新增费用硬上限仍为 9 USD；实际余额中的 0.14 USD 留给任务结束后的网络卷持有，不要求在任务 9 USD 内为终态后卷费预留。卷从实际所需容量起步、按需扩容且不超过 60GB；不得删除任何卷。
- 普通 provider/网络/脚本/恢复小问题可在预算内自主窄修并从已验证进度重试，不设机械尝试次数；exact 模型、数据/pair/unseen 语义、单 Pod、费用上限、禁止上传发布和终态 0 Pod 等原则边界不得改变。
- 找到 promising candidate 后立即停止搜索；完整 checkpoint/权重留网络卷，只回传验收和后续必须留本地的小型资产。无候选或基础设施终态也必须释放全部 Pod并确认持续 compute 费率为 0。
- 本报告应由执行者纳入下一次 worktree 提交。已验证的 `6dd27d8` source bundle 可作为阶段 B 的不可变执行输入；若只增加本报告或更新任务状态文档，无需为纳入纯文档而机械重建 source bundle。任何后续实现代码变动则应重新生成并验证相称 source bundle。
- WBS 继续留到 Plan 087 整体最终验收通过后统一更新；当前不得合并或推送 worktree 分支。
