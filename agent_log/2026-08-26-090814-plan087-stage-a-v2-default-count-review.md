# Plan 087 非付费阶段 A MCP v2 字段接缝复审

## 结论

- 验收状态：**不通过**。
- 阶段目标：**当前批次尚未完成，可经一次 v2 默认字段窄修复后复验；这不是 Plan 087 研究路线失败**。
- 付费门：**继续关闭**。本报告不批准查询或变更云端实时状态、上传、下载/运行真实模型、训练或产生费用。
- High finding：0；Medium finding：1。

## Medium finding

### v2 `gpu.count` 的合法省略形态仍会使最终成功路径失败

`training/publication-critic-plan087/runpod-create.py:208` 用 `gpu.get("count") != requested["gpu_count"]`
要求 provider 必须显式返回 `gpu.count`，`training/publication-critic-plan087/runpod-create.py:223` 随后又直接读取
`gpu["count"]`。测试 fixture `eval/tests/test_publication_critic_plan087_scripts.py:82` 始终构造显式
`"count": 1`，因此没有覆盖省略形态。

RunPod 官方 v2 `Get a pod` 页面内嵌 schema 将 `gpu.count` 定义为最小值 1、默认值 1 的整数，但没有把它标为
required。故原样 MCP v2 Pod 合法地只返回 `"gpu": {"id": "NVIDIA A40"}` 时，当前确认器会把单 GPU Pod
误判为配置漂移；若只放松条件而不改投影，随后仍会触发缺键错误。这样 Stage B 的 final receipt 成功路径仍取决于
provider 是否选择显式序列化默认值，付费启动前不能接受。

这是一个窄接缝问题，不需要新增设施。执行者可自行选择等价实现；建议把缺失 `count` 按官方默认值归一化为 1，
仍只接受任务请求的单 GPU，拒绝其它数值与非整数（尤其 JSON boolean），并让最终投影使用归一化值。补一个省略
`count` 仍成功的 fixture 即可；无需扩充通用 provider 兼容层或审计机制。

官方依据：<https://docs.runpod.io/api-reference-v2/pods/get-a-pod>。

## 已确认成立的部分

- MCP v2 原始 shape 已正确用于 exact Pod ID/name、image、disk、允许状态、SECURE cloud、data center 与 GPU ID 绑定。
- `mounts.network` 缺失、空、null、非唯一、错卷或错路径均 fail closed；任何非 null persistent mount 均拒绝。
- pending 与 final receipt 使用不同 schema，runbook 明确 final receipt 前不得连接、上传或 bootstrap。
- 先前关闭的同名 Pod 领养、自适应路线/scope、提前收口与恢复角色问题没有回归。
- WBS 保持不动，符合用户要求；应在 Plan 087 整体最终验收通过后统一更新。

## 审查验证

- 提交 `1c65cb54bc9c4cca7c42eaff5e485552be8ce52b` 位于 Plan 087 专用 worktree；审查开始时 tracked 状态 clean，未合并、未推送。
- Plan 081/082/087 七个相邻聚焦测试独立复跑：`93 passed, 57 subtests passed`。
- 定向 Ruff correctness 检查、三个 shell 的 `bash -n`、`git diff --check cd9792d..HEAD` 与 WBS untouched 检查通过。
- source archive 独立 exact-tree 复验通过：2,344,960 bytes、120 files、commit `1c65cb5`、SHA-256
  `4aec3b8a6e28c847af890cc6f2da6d0a6d6ecbfd51f35754ae06dc0a0e9341bf`。
- data bundle 独立复验通过：808,960 bytes、SHA-256
  `6d98c163a2b1f64cf23eec8357b3158ed56e7a2719fbfeb84eb0aa21ee888163`；train 128/58、validation 55/26、physical unseen 0。
- 本次只读查阅 RunPod 官方静态文档；未调用 RunPod/Hugging Face live API，未运行 Cargo、Docker 或真实模型，未训练或产生费用。

## 代用户作出的决定

- 继续保留两阶段 pending/final 与当前 v2 窄投影设计，只修正 `gpu.count` 默认值语义及相称测试；不返工其它已闭合能力，不增加通用设施。
- WBS 继续不改，等 Plan 087 整体最终验收通过后统一更新。
- 该非付费窄修复与复验属于既有授权，无需另行请示；明确复验通过前付费门保持关闭。
