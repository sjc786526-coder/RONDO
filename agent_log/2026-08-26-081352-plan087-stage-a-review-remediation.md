# Plan 087 阶段 A 首轮审查整改

## 问题确认与修复

- 确认同名 Pod 仅凭名称/状态复用会遗漏 image、GPU、区域、网络卷与止费配置。冻结的 provider client 无法回读完整网络卷和 stop/terminate 字段，因此删除跨调用复用语义：只有账户空基线后的单次精确 create 可在同一调用内消解不确定响应；后续同名对象一律 fail closed。创建后回读并核对 client 可见的 image、GPU、区域、磁盘与 mount，provider 若返回卷/止费字段也必须精确一致。
- 确认失败路线被强制跑满、强制候选级恢复且 scope 固定为最多四个末端 block 会机械限制搜索。路线现在可在同时保存完整观测和 checkpoint 的最新 step 提前诚实收口；`recovery_role` 明确区分无新进程恢复、必要恢复点和 promising candidate，且不会隐去已有 fresh-process 恢复事实。Plan 081 checkpoint qualification 与候选级新进程恢复分别记录。新 exact-base 路线可按真实 inventory 选择 score/final、任意末端深度、显式模块前缀或全参数；同一路线后续 phase 仍按实际参数集严格扩展。
- 远端顺序同步为先建立 mode `0700` 的 Plan 087 task root/incoming，再上传两个已验证 archive。没有建设通用云编排、调参、审计或可信平台。

## 回归验证

- Plan 081/082/087 相邻聚焦回归：90 passed，另有 44 subtests passed。
- 两个直接整改测试文件：20 passed，另有 10 subtests passed；覆盖同名 Pod 拒绝、单 create 超时消解、八类配置漂移、绝对止费时间、提前路线收口、恢复角色、任意/重选 scope 与同路线严格扩展。
- Plan 087 定向 Ruff 与 format check、15 个 Python 文件 AST、三个 shell 入口 `bash -n`、`git diff --check` 通过。
- 云端生命周期与训练/搜索两路只读复验均无剩余 High/Medium correctness/functionality finding；复验中识别并关闭了 checkpoint qualification 与 fresh-process recovery 语义混淆。

## 边界

- WBS 按审查决定保持不动，等待 Plan 087 整体验收通过后统一更新。
- 本批次未访问 RunPod/Hugging Face live 状态，未创建或修改 Pod/网络卷，未上传数据、下载/运行模型、训练或产生费用，未运行本地 Cargo/Docker。付费门继续关闭。
