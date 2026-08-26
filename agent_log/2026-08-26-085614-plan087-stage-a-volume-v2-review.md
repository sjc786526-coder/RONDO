# Plan 087 非付费阶段 A 网络卷确认复审

## 结论

- 验收状态：**不通过**。
- 阶段目标：**当前批次尚未完成，可经一次字段接缝窄修复后复验；这不是 Plan 087 研究路线失败**。
- 付费门：**继续关闭**。本报告不批准查询或变更云端实时状态、上传、下载/运行真实模型、训练或产生费用。
- High finding：0；Medium finding：1。

## Medium finding

### 标为 MCP v2 的确认器仍按 v1 Pod shape 解析，真实成功路径不可达

`training/publication-critic-plan087/runpod-create.py:168-188` 要求 provider Pod 含有 v1 字段
`containerDiskInGb`、`desiredStatus`、`machine.gpuTypeId/dataCenterId/secureCloud`、`networkVolume.id` 和
`volumeMountPath`；`training/publication-critic-plan087/runbook.md:181-205` 却要求把 RunPod MCP v2 `get_pod` 的 Pod 原样写入，并把 source 标为
`runpod-mcp-get-pod-v2`。

用户汇报引用的 `https://docs.runpod.io/api-reference/pods/GET/pods/podId` 是 API v1 合同。官方 API v2 的
`https://docs.runpod.io/api-reference-v2/pods/get-a-pod` 返回 `image`、`disk`、`status`、`cloud`、`dataCenterId`、`gpu` 及
`mounts.network[].volumeId/path`，没有上述 v1 字段。官方 `runpod/runpod-mcp` 的 `src/tools/pods.ts` 也表明 `get-pod` 只在 v1 backend
附加 `includeMachine/includeNetworkVolume`，v2 不附加这两个参数，并把 REST result 直接交给 `jsonReply`，没有 v2→v1 输出归一化。

因此当前测试中的 `_provider_observation` 是手工构造的 v1/混合 shape，不代表真实 v2 接缝。审查者用官方 v2 shape 做只读内存复现时，
`confirm_exact_pod_attachment` 对正确的 `mounts.network[0].volumeId/path` 返回
`CreateError: provider_attachment_configuration_drifted`。两阶段 pending/final 设计本身正确，但 final success 在默认 v2 MCP 下仍不可达。

修复不需要新增桥接、凭据、审计或编排设施：让本地确认器直接严格校验实际 MCP v2 原始 shape，或在 helper 内做明确且受测的 v2→内部投影；
至少增加一份官方 v2 shape 的成功 fixture，并继续覆盖 network mount 缺失、空数组、null/错误卷、错误 path 与配置漂移的 fail-closed。
是否保留 v1 兼容由执行者根据实际价值自主决定。

## 已确认成立的部分

- 第一阶段只产出独立 pending schema，pending 不会冒充最终 success receipt；runbook 明确禁止在 final receipt 前连接、上传或 bootstrap。
- 空账户基线、单次 create、跨调用不领养同名 Pod、有限 deadline、失败先 terminalize 后再创建等边界保持正确。
- 两阶段确认对同一 Pod identity、image、GPU、区域、cloud、disk、mount 和卷 ID 的校验意图正确；问题只在 provider 字段版本接缝。
- 前两轮已经关闭的 adaptive scope、路线提前收口与 recovery role 设计没有回归。

## 审查验证

- 提交 `cd9792da0aa10db6cdba2a7b583955c974488c18` 位于 Plan 087 专用 worktree；审查开始和测试结束时 tracked 状态 clean，未合并、未推送。
- Plan 081/082/087 七个相邻聚焦测试独立复跑：`93 passed, 53 subtests passed`。
- 定向 Ruff `E9/F63/F7/F82`、三个 shell 的 `bash -n`、`git diff --check c86f030..HEAD` 与 WBS untouched 检查通过。
- source archive 独立 exact-tree 复验通过：2,344,960 bytes、120 files、commit `cd9792d`、SHA-256
  `4c68b8f23047b7c8494fd677c57f2255d434b55d0fc4e3b1bfb867dabe0ce365`。
- data bundle 独立复验通过：808,960 bytes、SHA-256
  `6d98c163a2b1f64cf23eec8357b3158ed56e7a2719fbfeb84eb0aa21ee888163`；train 128/58、validation 55/26、physical unseen 0。
- 未调用 RunPod/Hugging Face live API，未运行 Cargo、Docker或真实模型，未训练或产生费用。

## 代用户作出的决定

- WBS 继续不改，等 Plan 087 整体最终验收通过后统一更新。
- 保留两阶段 pending/final 方案，只窄修 v2 provider shape 与相称测试、runbook；不返工已经闭合的其它能力，不扩建通用设施。
- 该非付费修复与复验属于既有授权，无需另行请示；明确复验通过前付费门保持关闭。
