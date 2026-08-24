# Plan 066 正式训练执行

## 结果

- 将最新本地 `main` 合入既有 Plan 060/066 worktree 后，以提交 `b543bbba2dacdcfeddb6540746bde13166a61618` 冻结训练源码；未创建新 worktree、Pod 或卷。
- `final-01` bundle 严格验证通过：archive SHA-256
  `897dc5ad9c47018de5e190fb55668f069e8f796be022b640d9cd0cc4e71275b0`，bundle manifest SHA-256
  `2970c693fa32d1118d3b8e949a04231970bf96dfc27f7c7d14a22f98a4ed2252`，63 个文件；只含 v8 train 128/58、validation 55/26，unseen-test 0。
- 在唯一 Secure `NVIDIA H100 PCIe` 80GB、US-KS-2、CUDA 13.0 Pod `oe6gbptvq5yhja` 上完成 commissioning start/resume；新恢复点成立后删除
  Plan 060 final-19 与 commissioning 两个已被替代的 10.56GB checkpoint，保留 receipt/log。
- 从 exact Skywork revision `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` 干净执行正式 C1→C2→C3：C1 95,483 tokens，
  C2 172,921 tokens，C3 183,339 tokens，共 451,743 tokens。三个阶段均为 BF16 全参数 FlashAdamW，1,720,577,024 参数与
  311/311 optimizer tensors 完整覆盖，loss、gradient、model/effective master、optimizer state 与 LR 均有限；峰值 CUDA allocated 约 28.52GB。
- 保存并重新验证三个 model-only safetensors 候选：C1/C2/C3 manifest 分别为
  `157d93d65d18dba02800a233338789b719a58faf003d9cd7c3f5cd42f80d5a46`、
  `5943d3004f5f04c90a60e01cf5f1c1c5ebd05aebd5eddea63cadc7d586975677`、
  `3c0ff2ed90c69c0ad585c97fa89b61582d79850f26756097ad956eabb6fef602`，每个 3,457,072,872 bytes。
- 每阶段固定 validation 均消费 55 candidates、19 Boundary 与 7 Within-PASS；`inference_mode` 下 optimizer/scheduler 未改变、全部 gradient 为 None，
  validation 不反馈 recipe 或训练。unseen-test 未导出、未运行。
- 正式 full checkpoint 10,555,059,139 bytes，manifest
  `f0bc46612e12ecfa491129291d355ccb7f51c577905d084216b50a3533cd4aff`；新 OS 进程恢复 model、FlashAdamW、scheduler、RNG 和 exact 128/58 cursor，
  再用冻结 6/2 C3 probe 完成 step 3→4 有限更新。候选不被 resume probe 覆盖。

## 预算与资源

- 唯一预算政策硬上限为 `$23`。final-01 曾误用账户余额差作为任务费用，并因 provider 延迟追账被终审降级为 superseded；账户余额还包含非任务历史，
  不再用于任务费用。用户确认控制台 2026-08-24 任务期账单为最终权威口径：总额 `$10.476`、GPU `$10.207`、存储 `$0.269`，距硬上限 `$12.524`。
- stopped legacy Pod `b0fazq4ueaii2k`、loser 卷 `bbfxl15nqr` 与最终计算 Pod `oe6gbptvq5yhja` 均已永久删除，账户 Pod 数为零、计算持续费为零。
  winner Standard 60GB 卷 `hi3iaz8rsr` 保留三个候选、正式 checkpoint、exact 模型、venv 与 cache，持续卷费约 `$0.005833/h`。
- final-02 terminal provider facts SHA-256 为 `4b1f95be70f39ed52effaad44223924b8f1293bb1d63dffcf112b17287c537eb`；Plan 066 final-02 receipt
  SHA-256 为 `2b58396b857e327c1da6d8cda514cc9bc2f9c7cbe2ca5b6307bbcb2d3588a9e4`，状态
  `execution_complete_pending_independent_acceptance`，建议 `GO_RECOMMENDED`。

## 本地证据与验证

- ignored 证据根：`eval-data/publication-critic/plan066/`，当前约 5.6MB；其中 bundle archive 1,761,280 bytes、commissioning 小型证据
  50,774 bytes、formal（含两次 terminal receipt）129,076 bytes、provider 证据 8,279 bytes。未下载模型权重或 checkpoint。
- actual formal start/pending receipt validator：通过。独立预验收指出 Plan 066 resume validator 未自行比较 process identity；已复用现有严格
  process contract，要求 start/resume 的 PID 与 instance ID 均不同，并补同 PID、同 instance、畸形 PID 负例。
- Plan 066 focused：11 项通过；Plan 060+066 相邻 focused：62 项通过，1 项既知可选本地 real-Torch seam skip。
- finalizer 新增窄 v2 console-billing 合同：严格绑定任务期日期、总额与 GPU/存储/其他分项相加、费用来源及 `$23` 门，同时保留 superseded v1
  receipt 的历史可验证性；账户余额只记录为上下文。
- 三个 launcher `bash -n`、bundle 独立解包验证、实际候选/checkpoint 远端复验和 `git diff --check`：通过。
- 训练主体独立预验收 `PASS`，无训练证据 blocker；candidate 真实加载验证按决定留给 M3-C1 或删除唯一卷副本前完成。

当前状态为执行与 terminal receipt 完成、待独立验收；不提前写 M3-B1c 完成、产品资格或 M3-C1 解锁。
