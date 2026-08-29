# Plan 099 阶段 B 运行手册

本手册只执行 `freeze-lock-v1.json` 锁定的唯一方案。阶段 A 审查者尚未通过指定队列明确回复
“Plan 099 阶段 A 验收通过，批准进入阶段 B”及完整外部边界时，以下任何真实模型、上传、RunPod、
GPU 或付费步骤都不得执行。

## 固定边界

- exact base：`Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`；
  权重 SHA-256 为 `117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9`。
- 只训练五个 FP32 无 bias 线性 head，共 22,528 个参数；BF16 backbone 冻结、eval、no-grad；16 次完整
  train cohort macro update，不得改模型、scope、loss、数据、门限或另开路线。
- RunPod Secure Cloud、`US-TX-3`、单张 `NVIDIA L40S 48GB`、exact image
  `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`、20GB container disk。
- 复用网络卷 `mwemzrn33y`，预计初始 70GB、上限 100GB；不新建卷，不删除该卷；任务 root 必须匹配
  `/workspace/rondo-plan099-*`，历史 root 只读。
- 同时最多 1 个计费 Pod，累计最多 2 个；累计墙钟最多 10,800 秒。第二个 Pod 只允许在首个已确认不存在且
  属于技术恢复时创建。库存紧张只使用根目录 `scripts/create-runpod-when-ready.py` 抢卡。
- 动态预算为批准时实时可用余额减已知未结/延迟费用，再减现有网络卷 6 小时实时保留费后取非负值；不得充值。
  每段运行前刷新预算快照，并确认 commissioning、formal、候选回传、预释放审查等待及 stop/delete 收口均可覆盖。

## 资产和环境

阶段 A 只生成并允许上传四个文件：`phase-a/source-bundle.tar`、`source-bundle-receipt.json`、
`data-bundle.tar`、`data-bundle-receipt.json`。data bundle 的物理成员只来自
`training/publication-critic-v10/`，含 train/validation，无 v9 test、qualification sealed 或旧 unseen 正文。
上传后先逐个校验 receipt 中的 archive SHA-256；`runpod-bootstrap.sh` 只用 source bundle 建立临时引导树，随后
由 `assemble-execution-root` 分别安全解包、逐树验签 source/data，合并至一个全新的 task-owned source root，最后
重新执行 freeze 校验。训练不得直接在临时引导树中运行。
远端公共下载只允许 `asset-contract-v1.json` 中 exact repository/revision/file 列表；先校验全部 SHA-256，
再加载模型。不得上传 `.env.local`，不得把密钥当 shell 文件 source。

Pod 创建后，训练前独立核验实际 provider、Secure Cloud、`US-TX-3`、L40S 数量/显存、单价、镜像、20GB
container disk 和卷 `mwemzrn33y` 的挂载；任一项不符立即释放，不进入 commissioning。创建响应不确定时先按
exact name 对账，不得重复创建。将核验结果、source/data receipt、模型 snapshot receipt、版本、GPU、价格和预算
快照写入任务 root 的小型 JSON evidence。

每次付费动作紧邻执行前按以下唯一链路重新授权：先生成带 canonical content SHA-256 的 live-resource receipt 和
不超过 Pod 累计 10,800 秒的 lifecycle authorization，再刷新 budget snapshot，最后生成 paid-segment authorization。
segment 必须逐哈希绑定 budget、resource、lifecycle、exact Pod id/name、实际 compute/container 单价、termination
trigger、60 秒 kill grace 与 360 秒终态确认预留；worker 的 `RONDO_PLAN099_MAX_SECONDS` 必须与 segment 完全相等。
所有云端 snapshot、artifact、state 和输出路径都必须在当前 `/workspace/rondo-plan099-*` task root 内；宿主 lifecycle
authorization 与 guard receipt 留在主物理根 Plan 099 ignored host namespace，并把 immutable authorization 复制进
云端 task root 供 segment/worker 逐哈希绑定。

Pod 创建并独立核验后，必须先在主物理根 Plan 099 ignored host namespace 生成 lifecycle authorization，并在授权后
60 秒内用 `nohup setsid` 启动冻结的宿主 guard；armed receipt 中的 PID 必须仍存活且 exact Pod id/name、绝对 trigger
与 authorization 一致。未成功武装不得上传、bootstrap 或使用 Pod。固定调用轮廓如下（变量值均来自本轮已核验 receipt）：

```bash
nohup setsid env RONDO_PLAN099_STAGE_B_APPROVED=1 PYTHONPATH=eval \
  python3 -B -P training/publication-critic-plan094/runpod-lifecycle-guard.py \
  --profile plan099 --authorization "$PLAN099_LIFECYCLE_AUTHORIZATION" \
  --terminal-helper training/publication-critic-plan087/runpod-terminal.py \
  --task-root "$PLAN099_HOST_TASK_ROOT" --armed-output "$PLAN099_GUARD_ARMED" \
  --result "$PLAN099_GUARD_RESULT" > "$PLAN099_GUARD_LOG" 2>&1 </dev/null &
```

正常提前释放仍只接受指定 queue 的批准 receipt 并走 `runpod-release.py`。Pod 预释放审查等待与绝对 trigger 取先到者：
若批准先到，立即走 gated release；若绝对 trigger 先到，guard 无需 queue receipt，直接调用 exact-Pod helper 自动
stop/delete，并在 360 秒窗口内确认 0 Pod、compute `$0/h`。guard 不得取消，也不触碰网络卷；提前释放后它到点仅对
已不存在的 exact Pod作幂等零费用确认。此绝对截止例外只守住累计 10,800 秒硬上限，不授权提前释放、延后 trigger
或改变训练路线。

## Commissioning

设置 `RONDO_PLAN099_STAGE_B_APPROVED=1`、exact image identity、任务 root、source root、segment authorization
等 worker 所需环境后，从 exact base 和独立空 `rondo-plan099-commissioning-*` namespace 运行 `start --run-kind
commissioning`。它只取 train 中每头一条 boundary 加一条 soft-only pair，执行 1 次非零更新，先原子保存完整
checkpoint，再评价，并停在 `recovery_required`。

必须由新的 OS 进程运行 `resume`：它只从 checkpoint 的完整模型、optimizer、precision、RNG、data cursor、
selection 和冻结 feature cache 恢复，逐字节复现 checkpoint 后评价，形成 recovery receipt。随后用小型临时回传
文件验证下载与校验路径。失败属于实现、环境、存储、传输或资源适配问题时，在总预算/墙钟/单路线边界内窄修并
重做 commissioning；不得把 commissioning checkpoint 当候选。

commissioning 只有在新进程复现成功后才能形成 `COMMISSIONING-PASS`；正式 `start` 必须显式读取并绑定该终态、
同一 source identity 与 freeze。commissioning 永远不能形成 `CANDIDATE` 或 `NO-GO`。

## Clean formal

commissioning 完整通过后，从 exact base 与全新空 `rondo-plan099-formal-*` namespace 运行 `start --run-kind
formal`。checkpoint/evaluation 固定在 2、4、8、12、16；每次严格 checkpoint-first。第 8 步停在
`recovery_required`，必须由新的 OS 进程 `resume` 并复现后才能继续至 16。最佳 checkpoint 只按预冻结排序自动
选择；所有 12 个 validation pair 闭合前不可准入。
控制状态在 checkpoint 落盘后和评价发布后都原子写回外部 state；进程若停在 `evaluation_pending`，新进程从已验证
checkpoint 恢复并补齐或逐字节复现 evaluation。正常暂停也只能从 latest 完整 checkpoint 恢复。到达第 16 步后，
若最佳 checkpoint 尚未被独立新进程复现，控制器再次停在 `recovery_required`，复现最佳点后才允许冻结终态。

若轨迹因代码、依赖、OOM、存储、连接、保存或恢复等技术正确性问题无效，可在同一 exact recipe 和总边界内
修复，从相称完整 checkpoint 恢复，或清空本任务无效 formal namespace 后最多用第二个 Pod clean rerun。若轨迹
有效但质量未过冻结开发门，终态必须是 `NO-GO`，不得追结果调参或开启第二路线。

## 候选回传和资源收口

形成 `CANDIDATE` 时，在 Pod 预释放审查前运行 `export-candidate`，并把完整 `candidate/inference-ready/`、
decision config、candidate manifest 及允许的小型 evidence 下载至主物理根
`eval-data/publication-critic/plan099/`。本地重新执行 exact-tree、bytes、逐文件 SHA-256 和 manifest 校验；不得只回传
adapter 或摘要。完整 recovery checkpoints、optimizer/scheduler/RNG state、feature cache、venv 和 HF cache 留在网络卷
的 Plan 099 root。`NO-GO` 只回传足以证明有效负向结论的小型结果与恢复证据。
`export-candidate` 会从全部五个不可变 checkpoint/evaluation 重新计算最佳点和严格 step-zero 改进，核对最佳点的
fresh-process recovery 与 retention marker，再输出完整 inference-ready tree、decision config、development
assessment、recovery receipt、controller state 及外层逐文件 bytes/SHA-256/exact-tree manifest。本地回传后必须运行
`verify-candidate`，不得信任传输前的摘要。

核心训练、fresh-process 恢复、正式评价、候选/`NO-GO` 冻结和回传完成后先提交 tracked 变动，通过指定 queue
申请“Plan 099 阶段 B 核心任务与 Pod 预释放准备”审查并停止。收到审查者明确回复“确认不再需要 Pod，批准立即
释放”前不得 stop/delete。收到后立即 stop/delete 所有任务 Pod并实时复核任务 Pod 为 0、compute 为 `$0/h`；
保留既有网络卷。批准释放后不得因文档整理重建 Pod。
释放必须把审查队列原文写成带 canonical content SHA-256 的 approval receipt，并通过冻结的
`runpod-release.py` 调用 exact-Pod terminal helper；wrapper 固定审查 thread、批准短语和 `rondo-plan099-` 名称前缀，
最终仍须得到 0 task Pod 与 compute `$0/h` 的实时回执。
