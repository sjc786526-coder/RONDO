# Plan 099 阶段 A 实现

## 结果

- 冻结唯一方案：`Skywork/Skywork-Reward-V2-Qwen3-1.7B` revision
  `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`，BF16 backbone 全冻结且保持 eval/no-grad；五个独立 FP32 无 bias linear heads 共
  22,528 个可训练参数。不存在第二基座、第二 scope 或付费探索路线。
- 冻结 16 次完整 v10 train cohort 更新与 2/4/8/12/16 checkpoint；step 8 和最终最佳 checkpoint 均要求不同 OS 进程恢复并逐字节复现
  development evaluation。checkpoint 后、评价后都会原子发布 controller state，并支持 `evaluation_pending` 与正常暂停恢复。
- 训练只读 v10 train/validation 的 162/72 与 27/12 candidate/pair；data archive 使用 17 个文件的物理 allowlist。未读取 v9 test、
  qualification sealed 或旧 unseen 正文。
- 候选导出会从五个不可变 checkpoint/evaluation 重新计算选择与 step-zero 严格改善，核对最佳点 recovery/retention，再形成完整
  inference-ready 与外层逐文件 bytes/SHA-256/exact-tree manifest。
- 阶段 B 入口绑定审查批准短语、task-owned 路径、实际 RunPod resource、Pod lifecycle、实时动态预算、segment timeout、environment receipt、
  commissioning pass 与 formal 空 namespace；Pod 释放另由指定审查 queue approval receipt 解锁。

## 开发准入

- 27 条 validation structured output 必须 finite，12 个 validation pair 全闭合；五头预测覆盖各自全部受支持 class。
- gate false-pass ≤ 3、false-rewrite ≤ 4、balanced accuracy ≥ 0.75。
- failure recall 下限依次为 `2/3、4/5、2/3、2/3、3/4`，continuity N/A recall ≥ `2/3`，各头 supported-class macro recall ≥ `3/5`。
- decision config 只从预冻结 12 项 margin grid 形成；最佳点按冻结总序选择，并须相对 step zero 严格改善或从不合格变为合格，否则形成有效
  `NO-GO`。

## 验证与边界

- Plan 099 focused pure/fake 测试：`6 passed`。覆盖 freeze/v10 split、objective、准入 fail-closed、动态预算/lifecycle、checkpoint-first
  双恢复/保留以及 checkpoint 后评价前进程丢失恢复。
- `validate-freeze`、Python compile、Ruff 0.12.12、shell syntax、`git diff --check` 均通过。
- source/data bundle 在阶段 A tracked 提交后从 exact commit 生成，并在独立临时树完成 source/data 分别校验、合并和 freeze 复验；精确 receipt
  保存在主物理根 task-owned ignored namespace，不进入 Git。
- 未运行真实模型加载/推理/训练、GPU/RunPod、Docker、付费 API或外部上传；未修改 Rust，未运行 Cargo。
