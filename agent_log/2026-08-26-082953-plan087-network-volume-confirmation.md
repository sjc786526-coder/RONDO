# Plan 087 阶段 A 网络卷确认整改

## 问题与修复

- 确认首轮整改复审的 Medium 存在：创建 helper 显式查询 network-volume projection，但 `networkVolume` 缺失或 `null` 时仍可能签发成功 receipt，无法证明 checkpoint 将落在任务卷。
- 保留空账户基线、单次 create、跨调用不领养同名 Pod 的既有边界。只读复核用本地 dummy provider 证明冻结 `runpodctl 2.9.0-c094cac` 会剥离 network-volume attachment，直接轮询虽安全却没有真实成功路径，因此没有采纳该表面修复。
- 最终采用两阶段窄确认：CLI create 只产生带有限 deadline 的 pending receipt；既有 RunPod MCP v2 safe entry 的原始 Pod `networkVolume.id` 作为卷 attachment 来源。只有 exact Pod/config、精确卷 ID 和 `/workspace` path 全部一致才形成最终 success receipt；缺失/null 可在 deadline 内重新查询，错误或超时 fail closed，全程不会发出第二次 create。
- runbook 明确在最终 receipt 成功前不得连接、上传或 bootstrap。没有读取/新增凭据，也没有增加通用资源编排、审计或可信设施。

## 验证与边界

- Plan 087 create/terminal 脚本定向测试 12 项通过（另有 19 个 subtests），覆盖稍后出现正确卷、持续字段缺失、持续 null、错误 ID、provider image/GPU/secure cloud/区域/disk/mount 漂移和单 create 约束。
- Plan 081/082/087 七个相邻聚焦测试共 93 项通过（另有 53 个 subtests）；15 个 Plan 087 Python 文件 AST、改动文件定向 Ruff/format、三个 shell `bash -n`、diff check 与 WBS untouched 门禁通过。
- 原先发现 CLI 成功路径不可达的云端生命周期审查者对最终 provider 字段对齐再次只读复核，未发现剩余 High/Medium correctness/functionality finding。
- WBS 保持不动；本批次未访问 RunPod/Hugging Face live 状态，未运行 Cargo、Docker或真实模型，未上传、训练或产生费用。付费门继续关闭。
