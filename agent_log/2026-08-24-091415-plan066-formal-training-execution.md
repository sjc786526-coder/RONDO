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

- 连续余额基线为 `$23.5953643966`，唯一预算政策硬上限为 `$23`。2026-08-24T16:15:59Z 的保守 balance delta 为 `$11.446590234`，
  距硬上限 `$11.553409766`；账户当前总时薪 `$2.902/h`。provider 账单尚未终态结算。
- stopped legacy Pod `b0fazq4ueaii2k` 与 loser 卷 `bbfxl15nqr` 已删除。用户在训练完成后明确要求等待批准再释放资源，因此当前 Pod
  `oe6gbptvq5yhja` 仍 RUNNING，winner Standard 60GB 卷 `hi3iaz8rsr` 保留三个候选、正式 checkpoint、exact 模型、venv 与 cache。
- 由于 Plan 066 finalizer 要求 compute `TERMINATED` 和 settled billing，terminal provider facts 与 formal final receipt 尚未生成；这不是训练路线失败。

## 本地证据与验证

- ignored 证据根：`eval-data/publication-critic/plan066/`，当前约 5.5MB；其中 bundle archive 1,761,280 bytes、commissioning 小型证据
  50,774 bytes、formal 小型证据 71,453 bytes、resource-hold receipt 1,806 bytes。未下载模型权重或 checkpoint。
- actual formal start/pending receipt validator：通过。
- Plan 060+066 focused unit tests：61 项通过，1 项既知可选本地 real-Torch seam skip。
- 三个 launcher `bash -n`、bundle 独立解包验证、实际候选/checkpoint 远端复验和 `git diff --check`：通过。
- 只读独立执行证据复核：`remaining_findings=[]`；同时确认唯一未闭合边界是用户延后的资源终态、settled billing 与 final receipt，
  因而本轮不冒充 terminal `COMPLETE`。

当前状态为训练执行完成、资源释放与 terminal receipt 待用户批准、待独立验收；不提前写 M3-B1c 完成、产品资格或 M3-C1 解锁。
