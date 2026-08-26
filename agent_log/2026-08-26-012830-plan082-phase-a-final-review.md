# Plan 082 付费前阶段 A 最终验收

时间：2026-08-26 ｜ 审查提交：`8734d5f8bb41256eb0e3a6655f55e9571c14b7be`

## 结论

`PHASE_A_ACCEPTED / USER_PAID_APPROVAL_PENDING`。

阶段 A 实现、两轮整改和非付费验证通过，未发现遗留 High/Medium correctness/functionality finding。真实训练 adapter、Plan 081
连续训练生命周期接缝、物理无 unseen 的 source/data bundle、云端 bootstrap/launcher、formal freeze/finalize、新进程恢复、保留工件
bootstrap 和参数化 0 Pod S3 handoff 已达到进入用户人工付费决策的准备状态。

本结论只验收不付费阶段 A，不授权查询实时库存、创建 Pod/网络卷、上传数据、访问真实 S3/HF、下载或加载真实模型、训练或产生费用。
阶段 B 仍须用户本人明确人工批准，随后由审查者通过指定 Codex 跨会话队列传达给执行者。

## 两项最终整改复验

- 参数变化证明现在于 optimizer step 前保存当前 scope 全部非零梯度参数的 CPU 前值，step 后逐个精确比较；已复现较小参数不变而
  较大参数改变时正确接受并推进 step，多参数全部 bit-identical 时仍拒绝。该实现不复制第二份 GPU scope；最大持久额外 CPU 数据
  约为当前 scope 参数体积，对本任务少量宏更新属于有界 commissioning 开销。
- retained bootstrap destination 在任何 artifact store 验证、扫描或写入前即要求位于 task root 内、artifact root 外，且已有父目录链
  均为非符号链接普通目录。task 外、artifact 同径/祖先/后代和符号链接 alias 均被直接回归拒绝；失败后 checkpoint 树零污染并继续
  通过原 content identity 验证。

## 验证证据

- Plan 082 training/handoff/scripts、Plan 081 training 与 Plan 068 handoff 相邻轻量回归 `81/81` 通过；五支 shell `bash -n`、相关
  `compileall`、`git diff --check 4d65245..8734d5f` 通过。执行者另报告 Ruff `0.15.12` 通过，本轮未重复联网安装或扩大验证。
- inventory/download 两个真实 wrapper 的 `--dry-run` 均绑定当前 worktree 和固定 7 包 venv，返回 `secret_access=false`、
  `network_access=false`，未构造 S3 client。
- ignored source archive exact-tree 复验为 commit `8734d5f8bb41256eb0e3a6655f55e9571c14b7be`、109 files、
  `2160640 B`、SHA-256 `7fc50f4d4261fa8d916670932a3a8c9c43035e5d30637bc03e4e9c0f8056c656`、source content
  SHA-256 `562e1e2dd5bbd21d20e198248819c30ab86afd0054f11d47972e0327c3afde21`。
- 两路独立窄复验分别覆盖参数变化证明和 handoff 路径隔离，均为 `ACCEPT`，无 High/Medium。
- 审查未读取 `.env.local` 或凭据，未访问 RunPod/HF/S3，未查询或创建 Pod/网络卷，未上传、下载或加载真实模型，未运行训练、Cargo、
  Docker、全 workspace 或其它付费/外部状态变更。

## 替用户作出的决定

- 阶段 A 验收通过，阶段 A 目标完成；Plan 082 总体任务尚未完成。
- 付费阶段保持未授权。下一步只等待用户本人明确人工批准；在获得并由审查者通过队列传达前，执行者应保持停止，不查询库存、不创建
  Pod/网络卷，也不执行任何真实外部写动作。
- 当前无需追加设施、审计或测试；CPU snapshot 的实测吞吐与内存表现留给已规划的 commissioning 观察，如出现普通可修问题可按既有授权
  调整并继续。
