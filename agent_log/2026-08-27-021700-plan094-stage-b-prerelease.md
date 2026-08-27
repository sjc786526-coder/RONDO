# Plan 094 阶段 B 预释放交接

- 阶段 B 在唯一 Secure US-TX-3 L40S Pod `0bsry5tbei7p4o` 上完成 commissioning 与 clean formal。Plan 090 guarded import 因历史 cursor 不兼容按合同失败，formal 从 exact base fallback 干净重建 step 1，未拼接部分状态。
- 正式轨迹在 step 1--4 逐点完成 checkpoint-first 训练与同口径 train/validation overlay；step 2、step 3 分别被新进程恢复并继续。预冻结 step-4 平台规则形成有效负向终态 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT`，没有 material/strict/operating event，不重跑规避负面结果。
- 修正后的 terminal qualification 深读卷上三份保留 checkpoint（steps 1/3/4），receipt SHA-256 `0f0d91331886fafd474371ec13baa6cd4e98cbc8dcdcaf3b304d364a36f7933b`。大型权重留在 `/workspace/rondo-plan094-20260827-stageb01`，任务根约 13.22GB。
- 最终预释放小包为主物理根 ignored `eval-data/publication-critic/plan094/rondo-plan094-20260827-stageb01/formal-small-prerelease.tar`，2,017,280 bytes / 181 members / SHA-256 `a0b227bdc606e76c0e17b1500e9770665631f576b9d409d66e30a2f9b32e9ea4`；本地复核无 checkpoint 权重和 source/data tar。整个本地 ignored task root 约 23MB。
- 卷仅在容量上界确有需要时从 57GB 扩到 70GB；用户后续放宽到 120GB 未使用。`2026-08-27T09:14:48Z` 保守成本 `$1.52`，`$0.82` closure reserve 含完成后至少 6 小时卷保留的 `$0.06` 保守余量，低于 `$5` 硬上限。
- 本地轻量门禁：Plan 094 focused 17/17、相邻 Plan 087 terminal 4/4（合计 21/21）通过；相关 `bash -n`、Python `compileall`、结果 JSON parse 与 `git diff --check` 通过。
- 按用户最新顺序，Pod 保留等待预释放审查；审查接受后才释放、实时确认 0 Pod / compute `$0/h` 并在本地运行 finalizer。绝对 lifecycle guard 不取消，最晚 `2026-08-27T11:17:42.117Z` 自动止费。
- 未运行本地真实模型、Cargo、Docker、全 workspace、真实 API/Judge 或 unseen；没有 HF 上传、第二卷、换区/换卡、多 GPU、卷删除或产品动作。
