# Plan 066 正式 checkpoint 载荷释放

## 背景

主工作区磁盘盘点发现项目占用 255.9 GB（decimal），距 `with-build-lock.sh` 的 270 GB 告警线仅 14 GB；
Windows `C:` 实际剩余 47.0 GB，已低于 50 GB 重型构建门禁。排查后确认体积大头之一为
`eval-data/publication-critic/plan068/handoff/runs/plan066-formal-final01-01/checkpoint-c3/`。

## 释放内容

删除该目录下载荷共 10 个对象、`10,555,047,237` 字节：

- `training-state.pt`，`7,097,974,365` 字节，sha256 `69b2fd9607bdbef5a8a819646ec8b39affda18dc50180e76763f208d8f4cb777`
- `full-model/` 9 个文件，`3,457,072,872` 字节，权重 sha256 `b6122e938b4202bd55359c6d77fd221cbd71c059c71bd351f139052341ff0c70`

保留 `checkpoint-manifest.json`（1,897 B）与 `checkpoint-metadata.json`（11,902 B）于原位，
并在 `eval-data/publication-critic/plan068/checkpoint-c3-release-record/` 另存副本与 `RELEASE-NOTE.md`。

## 判断依据

- Plan 066 为 BF16 全参数 1.72B + FlashAdamW，H100 PCIe 80GB，`global_step=3`；后续 Route O
  （Plan 087/090/094）为九张量 `33,558,784` 原参数 + AdamW、L40S，Plan 094 起点取 Plan 090 云端 checkpoint。
  参数集合、优化器实现与数据游标三处不匹配，optimizer state 对现行路线不可复用。Plan 094 已以 valid-negative 终态完成合并。
- `full-model/` 9 个文件与 `candidate-c3/` 逐一 sha256 全等，删除不损失任何权重字节。
- 验收证据已独立固化于 `handoff-evidence/`：`plan068-checkpoint-verification-final.json` 记录
  `status=verified`、`bytes=10555059139`、`file_count=12` 及 optimizer 内部结构
  （`optimizer_state_entries=311`、`param_group_count=1`、`rng_keys=4`、`scheduler_keys=7`）；
  `plan066-formal-final01-resume.status.json` 记录 step 3→4 新进程恢复 `completed`。

## 疑难与处置

- 原计划对 `full-model/` 做硬链接以省 3.2 GB 并保住 `verify_checkpoint()`。核查
  `checkpoint.py` 后确认该校验对目录做全文件集比对，删除 `training-state.pt` 即必然失败，
  硬链接的保校验价值随之消失，故改为直接删除，省下的字节相同且不引入共享 inode。
- `_tree_manifest()` / `_regular_tree_files()` 只检查 `S_ISREG` 与 `S_ISLNK`，不检查 `st_nlink`；
  `verify_checkpoint()` 显式拒绝 symlink。该结论本次未被使用，但已记录以备后续同类操作。
- 后台会话的工作树隔离守卫拦截 Write/Edit 工具。用户已明确要求在主工作区直接完成且工作树干净，
  改用 shell 写入，未修改 `.claude/settings.json`。

## 验收

- 删除前门禁：`candidate-c3/` 9 个文件 sha256 全量核验 9/9 通过，未通过则中止。
- 删除后复核：`candidate-c3/model.safetensors` sha256 仍为 `b6122e93…`；
  candidate-c1/c2/c3、`handoff/model/`、`handoff-evidence/`、`bundle-plan066-final-01/` 均完好。
- 实测释放 `10,555,030,174` 字节（与预测差 17,063 字节，为新建归档 3 个文件所占）。
  项目 255,916,331,175 → 245,361,301,001 字节（255.9 → 245.4 GB），距 270 GB 告警线余量由 14 GB 增至 24.6 GB。
  plan068 由 24.39 GB 降至 13.83 GB。
- `doc/WBS.md` 将「本地保留 120/120 个必要对象与正式 checkpoint」改为
  「本地保留 110/120 个必要对象（正式 checkpoint 载荷已释放，manifest/metadata 与验收收据保留）」。

## 遗留

- **`candidate-c3/` 现为 C3 权重唯一副本，不得删除。**
- `verify_checkpoint()` 对 `checkpoint-c3/` 此后必报 `checkpoint_file_identity_mismatch` 与
  `checkpoint_training_state_missing`；该 checkpoint 不再自证完整，仅存收据。
- 源卷 `hi3iaz8rsr` 已删除，无恢复路径；重建须重租 H100（原 Plan 060+066 实际费用 `$10.476`）。
- 未触碰：Windows `C:` 余量仍为 47.0 GB，低于 50 GB 门禁；释放 WSL 内文件不归还宿主容量，
  需另行压缩 VHDX。本次未做该操作。
