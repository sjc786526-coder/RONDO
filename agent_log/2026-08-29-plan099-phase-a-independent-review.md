# Plan 099 阶段 A 独立验收

## 结论

阶段 A **验收不通过**，阶段 B 保持 **未授权**。五头模型身份、冻结训练范围、四类 loss 职责、formal decoder、pair-aware selector、v10 train/validation 隔离和动态预算公式本身未见 High/Medium 漂移；但当前实现仍有会在 commissioning、正式恢复或候选回传时确定阻断的功能缺陷，不适合开始计费。

这些问题都属于既有阶段 A 授权内的实现正确性整改，不需要更换模型、数据、loss、scope、准入门或申请新的用户授权。整改后应重新生成绑定新实现提交的 source/data bundle 与 receipt，再提交一次独立验收。

## 阻断项

### 1. CANDIDATE 终态与导出/保留顺序互相矛盾（High）

`Plan099TrainingController._finish()` 先只保留 best/latest/step 8 最多三个完整 checkpoint（`plan099_training.py:921-939`），而 `validate_terminal_candidate()` 随后遍历五个正式观察点并逐一调用 `store.verify_checkpoint()`（`plan099_training.py:1093-1125`）；`export-candidate` 在复制最佳模型前必经该验证（`plan099_cli.py:374-383`）。因此正常形成 `CANDIDATE` 后，step 4/12 等被裁掉的 checkpoint 会让完整候选导出报 `directory_missing`。

同一 validator 还拒绝任何 `assessment=None` 的中间点（`plan099_training.py:1100-1108`），但控制器明确允许早期没有 pair-closed decision config、后期才形成合格候选。这会错误拒绝一条合法改善轨迹。

本次用现有 fake adapter 在 `/tmp` 复现：终态为 `CANDIDATE`，保留 checkpoint 为 step 2/8/16，随后 `validate_terminal_candidate()` 在 step 4 报 `directory_missing`。现有测试只验证保留三个 checkpoint，没有覆盖终态后的 candidate export。

整改结果应保证：五点选择证据可以从不可变工件重新核验；完整权重只需按冻结保留策略保存；合法的早期无 config 点不阻断后期候选；candidate export 与本地 verify 有直接 fake 回归。

### 2. 隔离 venv 无法获得镜像内 PyTorch（High）

`runpod-bootstrap.sh:38-41` 使用默认 `python3 -m venv` 创建隔离环境，`dependencies-v1.txt` 又明确不安装 Torch，worker 固定调用该 venv 的 Python（`runpod-worker.sh:30-37`）。普通 venv 不继承镜像系统 site-packages，`capture-environment` 和训练会在 `import torch` 处失败，commissioning 无法启动。

仓库中同一镜像已验证的 Plan 094 路径使用 `--system-site-packages` 并显式断言 `torch.__version__ == "2.8.0+cu128"`。执行者可复用该方式或采用证据充分的等价方案，但必须在付费前把“镜像供应 Torch、pip 不替换 Torch、worker 实际解释器可导入冻结版本”闭合，并补窄测试/静态门。

### 3. checkpoint/recovery 状态机仍有三个真实中断缝（High）

- step 8 fresh-process recovery 成功后没有清除 `recovery_checkpoint_id`（`plan099_training.py:832-895`）。若之后合法停在 step 12，状态同时保留旧 step 8 与 latest step 12；CLI 按 pending/recovery/latest 顺序选择旧 step 8（`plan099_cli.py:307-340`），而 continuation 只接受 latest（`plan099_training.py:679-684`），恢复必失败。本次 fake 复现输出为 `status=paused, recovery=step8, latest=step12, cli_choice=step8`。
- 完整 checkpoint 原子发布后、外部 `evaluation_pending` state 发布前若中断（`plan099_training.py:711-735`），耐久 controller 仍从上一点重跑固定 checkpoint ID，但 artifact store 对已存在的完整工件直接报 `plan081_artifact_exists`（`plan081_artifacts.py:471-498`），没有验证并采用该 orphan checkpoint 的路径。
- retention completion marker 写入后、terminal state 发布前若中断（`plan099_training.py:935-955`），重试会再次写同一 write-once marker（`plan081_artifacts.py:272-292`），同样不幂等。

整改不需要新增通用事务或审计平台；只需让本任务固定状态机在这些明确中断点可验证地采用已有完整工件或安全续跑，并补对应 fake crash-seam 回归。

### 4. 无 decision config 的有效负向轨迹不能结束（Medium）

selector 无法形成 pair-closed config 时，评价会合法返回 `assessment=None`（`plan099_training.py:1021-1038`），选择器跳过该点（`plan099_training.py:773-786`）。若五点全部如此，`best_checkpoint_id` 保持 `None`，`_finish()` 却把它当成尚未 fresh-recover 的 checkpoint，进入 `recovery_required` 且 `recovery_checkpoint_id=None`（`plan099_training.py:897-905`），不能形成计划要求的有效 `NO-GO`。

本次 fake 复现得到 `status=recovery_required, recovery_checkpoint_id=None, best=None, terminal=None`。整改后全无 config、全不合格以及中途才形成 config 三类轨迹都应有确定终态和直接回归。

### 5. 10800 秒硬上限没有覆盖 queue 审查等待（Medium）

当前 lifecycle authorization 只记录绝对 trigger；`runpod-worker.sh` 的 `timeout` 只终止 Python worker。核心任务通过 queue 申请预释放审查后，执行者按合同停止会话且未经审查不得释放 Pod，因此若审查等待越过 trigger，Pod 会继续计费，10800 秒总墙钟、动态预算和必须留下的 6 小时卷费都无法兑现。

本审查代用户作出以下收敛决策：正常的提前释放仍必须等待审查者明确回复“确认不再需要 Pod，批准立即释放”；与此同时，阶段 B 必须在 Pod 创建后立即武装一个 absolute-deadline 精确 Pod 止费兜底，硬截止到达时即使尚未收到 queue 回复也只 stop/delete 本任务 exact Pod，并记录 0 task Pod、compute `$0/h` 回执。优先复用/窄适配已有 Plan 094 lifecycle guard，不建设第二套通用设施。该紧急兜底是总预算和墙钟硬边界的一部分，不得用于提前终止正常训练或删除网络卷。

## 非阻断观察

`reference_objective` 的 weighted CE 按固定样本数平均，而 Torch 默认按目标权重和归一。正式 162-row full cohort 因冻结 inverse-frequency 权重使两者等价；commissioning/validation 子集的 loss 标度不完全相同。它不改变正式优化轨迹、decoder 或 selector，本轮记为 Low，不单独阻断；若执行者改动 objective 测试，宜顺手消除“exact oracle”表述与实际 reduction 的偏差。

## 已复核证据

- worktree 在审查写报告前 clean，受审实现提交为 `131243e1c85b3bb59eb94017c902ecf45d68e77f`；主工作区 tracked 状态 clean，未合并、未推送。
- `validate-freeze` 通过，freeze SHA-256 为 `c50beefce2abf071fa35d37f6c08ab313444f3809648c32428b9c3adec5dcd94`。
- Plan 099 focused 测试窄重跑：`6 passed in 0.47s`；测试本身未覆盖上述 candidate export、全无 config NO-GO 和三个 crash seam。
- source/data bundle 的 bytes、SHA-256 和 receipt 与执行者汇报一致；只列出 data tar 成员名确认 17 个 allowlist 文件，未读取受限正文。
- 未加载真实模型，未使用 GPU/RunPod/Docker/付费 API，未上传资产，未读取 v9 test、qualification sealed 或旧 unseen 正文，未运行 Cargo 或其他重型测试。

## 再验收最小条件

1. 修复上述五组功能问题，不改变冻结模型路线和任务语义。
2. 增加 candidate export、早期无 config 后合格、全无 config NO-GO、step 12 continuation、checkpoint publish orphan、terminal retention 重入、venv Torch 可见性和 absolute lifecycle guard 的窄 fake/pure 回归。
3. 只重跑 Plan 099 focused 门、freeze/compile/lint/shell/diff 等相关检查；无需扩大到全仓重型测试。
4. 提交 clean worktree，重建并复核绑定新实现提交的四个 Phase A bundle/receipt 工件，再通过既定 queue 申请阶段 A 复验和阶段 B 批准。

当前状态：`PHASE_A_REVIEW_FAILED / REMEDIATION_ALLOWED`；`PHASE_B_NOT_AUTHORIZED`；完整 Plan 099 仍为 `IN_PROGRESS`。
