# Plan 060 付费重启最终 readiness 验收

## 结论

- **本地 readiness 验收通过，`remaining_findings=[]`。** 上轮两项阻断均已正确闭合，未发现局部修复引入的相邻 correctness/functionality 回归。
- **批准恢复付费运行：** 仅允许启动现有唯一 Pod `b0fazq4ueaii2k`，额外 GPU 运行最多 3,600 秒，并继续受 Plan 060 的费用、监控、止费和清理边界约束。
- 本结论只批准进入 H100 commissioning/formal smoke；Plan 060 的任务目标尚未完成，也不预判最终 M3-B1b GO/NO-GO。
- 审查期间只进行了本地轻量验证和 RunPod 只读查询，没有启动 Pod、上传、训练或新增 GPU 费用。

## 修复验收

### optimizer/scheduler LR finite

- runner 现在遍历全部 optimizer param group，拒绝缺失/非法、NaN/Inf 和负 LR；同时读取 scheduler last LR，拒绝数量不符、非有限、负值及与 optimizer 的有限值错配。
- post-update receipt 记录 param-group 数和两侧 LR，receipt 合同严格绑定字段、数量、有限非负与两侧一致性。
- stage-update 负向回归覆盖 optimizer LR NaN 和 scheduler LR Inf；receipt 回归也拒绝非有限 LR。

### 真实 CPU Torch seam

- 新用例确实导入真实 Torch/NumPy，调用项目 `extract_raw_scalar`、`binary_loss`、`pair_loss`，执行 autograd/backward、有限梯度和参数更新。
- 用例实际执行 checkpoint save/verify/load，新建并恢复 model、optimizer、scheduler，恢复 Python/NumPy/Torch RNG 后继续一次更新，并验证 optimizer step 与 scheduler epoch 前进。
- 普通 AdamW 只用于无 GPU 的 CPU 组合 seam；正式 runner 和 bundle 仍只允许 FlashOptim/FlashAdamW，因此不构成训练 fallback。
- 执行者冻结门记录 Torch `2.8.0+cpu`、NumPy `2.4.6` 下 51/51 PASS、0 skip。临时 779 MB 环境按计划删除后，本轮未重新安装依赖；当前环境复跑为 50 PASS、真实 Torch 单例 1 个预期 skip。该复跑结果与冻结的 0-skip 证据用途明确区分。

## bundle 与轻量回归

- `bundle-final-07.tar` 为 716,800 bytes，SHA-256：
  `9b878b7323fc0dfb2907ad6a6114f273387e822b238b86fcc61087cb3d301636`。
- 从外部 cwd 使用 `python -B -P` 严格验证通过：53 files、6 Binary、2 Pair、C1/C2/C3 pair 数 0/1/2；解包树无 `__pycache__`。
- final-07 中 Plan 060 Python source、训练合同和三个远端脚本与当前 worktree 一致；3 个脚本通过 `bash -n`，`git diff --check` 通过。
- 两路独立窄复核均为 `remaining=[]`。

## 实时远端与费用门

- 只读刷新时，唯一 Pod `b0fazq4ueaii2k` 仍为 `EXITED`，规格为 `1 H100 PCIe`，价格 `$2.89/h`。
- H100 PCIe 80 GB 当前库存为 `Low`，secure price 为 `$2.89/h`；账户当前小时费率仅停止态存储 `$0.017/h`。
- 按基线余额与最新只读余额复算，当前保守累计费用约 `$1.1064492799`；再计最多一小时 GPU 与一小时运行存储后的保守投影约 `$4.0134492799`，低于 `$4.75` 正常收口线及 `$6` 硬上限。

## 代用户作出的决策与批准条件

- **批准本次最多 3,600 秒的付费重启。** 启动瞬间必须再次只读确认：仍是同一 Pod、H100 PCIe 80 GB 容量可用、价格不高于 `$2.89/h`，且按最新累计费用计算的 3,600 秒投影不超过 `$4.75`；任一门不满足则不得启动并应报告。
- 不允许创建第二个或 replacement Pod，不允许替换 GPU/后端/模型/数据/优化器路线。
- 保留共享 uv cache 是合理的并行任务保护，不要求为了本任务清理；临时测试环境已经删除即可。
- 延续上一轮轻量决策：不追加 provider pending hash/Pod `created_at` 或 launcher 控制平台等偏审计化设施。
- 若付费后暴露新的本地代码、bundle 或启动设施问题，应立即停止 Pod、回本地窄修，并按既定语义重新申请下一次付费重启；网络或 provider 瞬态问题仍可在本次 3,600 秒、费用门和同一 Pod 范围内有界恢复。

## 当前项目状态

- 验收状态：**通过（本地 readiness / 付费重启门）**。
- 任务目标：**尚未完成**；必须完成 H100 commissioning、干净 formal、new-process resume、证据回收、资源删除和最终账单后，才能验收 Plan 060 目标及 M3-B1b GO/NO-GO。
- 当前可进入下一步：执行者可按上述条件启动同一 Pod。
