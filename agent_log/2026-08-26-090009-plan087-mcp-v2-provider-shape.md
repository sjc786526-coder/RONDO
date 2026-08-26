# Plan 087 阶段 A MCP v2 provider 字段接缝整改

## 问题与结论

- 确认网络卷复审的 Medium 存在：provider observation 标为 RunPod MCP v2 原始响应，确认器与 fixture 却按 API v1/mixed shape 读取，真实 v2 正确挂卷对象无法形成 success receipt。
- 官方 MCP `get-pod` 在 v2 backend 下不使用 v1-only include query，并把 REST result 原样返回；官方 v2 Pod 以 `disk/status/cloud/dataCenterId/mounts.network[].volumeId/path` 表达创建配置与网络卷。
- 保留已经成立的 pending/final 两阶段设计，只新增一个职责明确的 v2 Pod 窄投影 helper。final receipt 必须绑定 exact Pod ID/name、image、GPU/count、secure cloud、data center、disk、可继续初始化/运行状态，以及唯一正确 network mount；缺失、空、null、错误卷/路径、persistent 冲突或其它配置漂移均 fail closed。
- provider observation envelope 不再记录在 v2 下不会生效的 include flags；runbook 明确原样保存 MCP v2 Pod，并禁止 final receipt 前连接、上传或 bootstrap。未增加 v1 兼容分支、通用桥接、凭据、编排、审计或可信设施。

## 验证与边界

- Create/terminal 定向测试 12 项通过（另有 23 个 subtests），覆盖官方 v2 shape 成功、mounts/network 缺失、空数组、null、错误卷、错误 path、persistent 冲突、deadline，以及 provider image/GPU/count/区域/cloud/disk/status 漂移。
- Plan 081/082/087 七个相邻聚焦测试共 93 项通过（另有 57 个 subtests）；15 个 Plan 087 Python 文件 AST、改动文件定向 Ruff/format、三个 shell `bash -n`、CLI help、diff check 与 WBS untouched 门禁通过。
- 云端生命周期审查者对最终 v2 接缝再次只读复核，确认官方 v2 成功路径可达、全部 mount/config 失败分支 fail closed，且 pending/deadline/单 create/不领养同名 Pod 均未回归；未发现 High/Medium correctness/functionality finding。
- WBS 保持不动；本批次未访问 RunPod/Hugging Face live 状态，未运行 Cargo、Docker或真实模型，未上传、训练或产生费用。付费门继续关闭。
