# Plan 060 付费重启前独立验收

## 结论

- **验收不通过；暂不批准付费重启。** final-06 的 bundle、脚本、数据边界和大部分上一轮整改均正确，但仍有 2 项付费前 correctness/evidence finding。
- 本结论不是 BF16 全参数或 FlashAdamW 路线的技术性 NO-GO。Plan 060 尚未执行 H100 commissioning/formal smoke，任务目标仍未完成。
- 审查期间只进行了本地定向验证和 RunPod 只读查询，没有启动 Pod、上传、训练或新增 GPU 费用。

## 已核对证据

- `bundle-final-06.tar` 为 716,800 bytes，SHA-256 为
  `9be0695a31a1507128477f51c4b4373dad082a729ad65ca45a83ee9c92cbf8ac`；从外部 cwd 使用 `python -B -P` 严格验证通过，结果为 53 files、6 Binary、2 Pair、C1/C2/C3 pair 数 0/1/2，未生成新的 `__pycache__`。
- bundle 内 Plan 060 Python source 与训练合同/脚本和当前 task worktree 内容一致；3 个 shell 脚本通过 `bash -n`；`git diff --check` 通过。
- 按项目入口复跑 focused Python tests：50/50 PASS。首次使用了不适合本仓库布局的 `eval.tests...` 模块名并得到 import error；改用 `PYTHONPATH=eval` 的正式入口后完整通过，该首次结果不是代码失败，也未被计作通过。
- 只读刷新显示唯一 Pod `b0fazq4ueaii2k` 仍为 `EXITED`，规格仍为 `1 H100 PCIe`、标价 `$2.89/h`；账户当前小时费率仍只有停止态存储 `$0.017/h`。本次刷新时 H100 PCIe 不在可启动库存列表中。

## 剩余 finding

### 1. post-update finite 未覆盖 optimizer/scheduler LR（阻断）

`runner._run_stage_update()` 在 optimizer/scheduler step 后调用的
`_validate_post_update_finiteness()` 只检查 BF16 参数、FlashOptim effective master 和量化 moment scales，没有检查 optimizer param-group LR 或 scheduler last LR；receipt 也没有对应事实。

已独立复现：向现有 tiny context 注入 `optimizer.param_groups[0]["lr"] = NaN` 后，校验仍返回 `all_finite=True`。当前 constant scheduler 使实际触发概率较低，但这会让“更新及必要训练状态均有限”的正式结论出现假阳性，也未闭合上一轮明确提出的 scheduler LR 检查。

最小整改：在现有 post-update 检查和 stage receipt 中加入 optimizer/scheduler LR finite 事实，并补一个 NaN/Inf 负向回归；无需逐参数 hash 或额外审计设施。

### 2. 本地“真实 objective/autograd/update 与 save-load-continue”证据仍未成立（阻断）

现有 objective 用例把 `torch` 替换为自制 `_mini_torch()`；stage update 用例又把真实 `binary_loss` / `pair_loss` 替换为 `_MiniLoss`，其 `backward()` 手工写入梯度。checkpoint 用例只用 JSON 编解码保存/加载字段，没有执行 optimizer、scheduler、RNG 恢复后再继续一次更新。本机当前也没有可导入的 Torch。

这些测试对 Python 控制流有价值，但不能称为真实 Torch autograd/update，也没有覆盖恢复组合 seam；H100 commissioning 仍会第一次覆盖这些路径。最小整改是在 task-local tiny/random fixture 中用真实 Torch 跑 objective -> backward -> update，并跑一次 optimizer/scheduler/RNG save -> load/restore -> continue；不下载完整模型、不要求 FlashAdamW 或 GPU，也不建设通用训练测试平台。现有 fake 合同测试可以保留，但证据名称应如实区分。

## 代用户作出的决策

- **不把 provider facts 继续增加 formal-pending hash 和 Pod `created_at` 作为新阻断。** 当前固定唯一 Pod ID/name、任务 billing window，以及 finalizer 对 start/pending identity、coverage、process 和 checkpoint 的直接绑定，对本次单 Pod、单 formal namespace 已足够。继续增加字段的收益偏审计化，不符合本任务轻量边界。
- **不要求为 launcher 另建动态控制平台。** 现有 fallback status、active lock、唯一 launch artifact、持久路径约束和 `bash -n` 对本次有界脚本已足够；动态 shell 覆盖不足不单独阻断。
- 后续批准应按启动瞬间的最新费用重算，而不是无限沿用本次金额。只有同一 Pod、H100 PCIe 容量恢复、价格不高于 `$2.89/h`，且“最新保守累计费用 + 最多 3,600 秒 GPU + 运行存储”仍不超过 `$4.75` 正常收口线时，才可批准启动；否则缩短窗口或重新报告。

## 当前状态与下一门

- `remaining_findings` 为上述 2 项；Plan 060 状态应保持 `LOCAL_REMEDIATION_REQUIRED / REMOTE_INCOMPLETE`。
- 执行者应在原 task worktree 内窄修、重跑 focused gate、重新冻结 bundle 并报告新 SHA-256；Pod 继续停止。按执行者已声明的失败语义，修复后需要重新申请付费重启批准。
- 当前不能开启 Pod：代码验收尚未通过，且只读实时库存也没有 H100 PCIe 可用容量。
