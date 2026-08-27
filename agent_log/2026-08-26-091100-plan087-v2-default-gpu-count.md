# Plan 087 阶段 A v2 默认 GPU count 整改

## 问题与修复

- 确认复审 Medium 存在：官方 REST v2 `gpu.count` 可省略并默认 1，原确认器要求显式字段且在投影时直接索引，使合法单 GPU 响应无法形成 final receipt。
- 在既有 `_project_runpod_mcp_v2_pod` 内先以官方默认值 1 归一化缺失 count，再要求严格 Python `int` 且精确等于任务请求的单 GPU。缺失值成功投影为 1；显式 `2`、JSON boolean `true` 和浮点 `1.0` 均拒绝。
- pending/final、exact Pod/spec/mount、deadline、单 create 与同名 Pod 拒绝语义不变；没有增加通用兼容、provider 桥接、审计或可信设施。

## 验证与边界

- Create/terminal 定向测试 12 项通过（另有 25 个 subtests）；Plan 081/082/087 七个相邻聚焦测试共 93 项通过（另有 59 个 subtests）。
- 15 个 Plan 087 Python 文件 AST、改动文件定向 Ruff/format、三个 shell `bash -n`、CLI help、diff check 与 WBS untouched 门禁通过。
- 云端生命周期审查者最终只读复核确认缺省成功、所有显式错误类型拒绝，且其它 v2 spec/mount 与生命周期边界未回归；未发现 High/Medium correctness/functionality finding。
- WBS 保持不动；本批次未访问 RunPod/Hugging Face live 状态，未运行 Cargo、Docker或真实模型，未上传、训练或产生费用。付费门继续关闭。
