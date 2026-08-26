# Plan 082 阶段 A 首轮审查整改

时间：2026-08-26 ｜ 实施基线：`9637bbec74020c918270a5ddbafce20c8cf0e555`

## 修改

- 确认首轮审查的 9 项 Medium finding 均存在并完成局部修复。recipe 显式参数化参数 dtype；每个有效 update 证明当前 scope 至少一个
  非零梯度原参数发生实际数值变化，bit-identical no-op 不推进 step。validation guard 覆盖参数、buffer、optimizer/scheduler、data cursor
  和 Python/Torch CPU/CUDA/NumPy RNG；Plan 081 公开 controller 永久固定 fixture profile，共享能力仅下沉到内部 core。
- 训练 segment 在任何 artifact/base/update 前拒绝已存在、符号链接、相同或祖先/后代冲突的全部输出。实际环境 receipt 绑定 image、Python、
  driver、host/runtime CUDA、单 GPU 和完整 installed-distribution freeze；freeze/start/resume 继续复用既有 runtime exact compare。
- formal finalizer 重新打开 exact artifact root，验证 exact base、完整 update/scope/turning/observation/selection/checkpoint/latest/recovery/retention
  关系和内容；terminal checkpoint 的 manifest-protected controller state 除 `running → completed` 外必须与 final state 完全一致。
- cloud-side handoff producer 不再接受调用者自报 objects；它从 formal retention 精确核对并逐普通文件生成 base/全部 observation、snapshot 和
  checkpoint 的 task-root 相对 key、bytes、SHA-256 与 roles。bootstrap 子命令输出隔离到 task log，稳定 ready receipt 采用 identical-or-fail
  发布。0 Pod 入口用一个主物理根 ignored、固定版本 boto3 venv 和显式 worktree/PYTHONPATH launcher。

数值变化证明有意选择当前 scope 中最小的非零梯度参数做前后比较，而不做全模型逐步 hash：它可能保守拒绝“所选参数没变但其它参数变了”
的轮次，但不会把未证明变化的 update 记成进展，额外显存也保持有界；commissioning 可据此调整 dtype、LR 或 scope。

## 验证与资产

- Plan 082 training/handoff/scripts、Plan 081 training 和 Plan 068 handoff 相邻轻量回归 `81/81` 通过；修改 Python 的 Ruff、compileall、五支 shell
  `bash -n`、`git diff --check` 通过。三路整改窄复核最终均未报告剩余 High/Medium。
- 主物理根 ignored `handoff-runtime-v1/venv` 为 `34,089,297 B`，固定 boto3 `1.40.21` 及完整 7 包闭包。inventory/download 两个 wrapper
  dry-run 均绑定当前 worktree 和同一 venv，返回 `secret_access=false`、`network_access=false`；未构造 S3 client。
- `stage-a-final/` 当前为 `6,516,972 B`。原 physical train+validation bundle 与 extracted copy 双端重验一致：4 文件，train `128/58`、
  validation `55/26`、commissioning `6/2`、unseen `0`；data archive `808,960 B`，SHA-256
  `af1d9ac744529a6366b8158549fd74a653d6596313cc9769c255fd2dcecb2fc6`。

## 边界

- 未查询或创建 Pod/网络卷，未访问 RunPod/HF/S3，未读取凭据或 `.env.local`，未上传数据、下载真实模型、加载真实模型或训练，未产生费用。
- 未运行 Cargo、Docker、全 workspace、CI/PR。阶段 B 继续未授权；阶段 A 复验通过仍不构成用户人工付费批准。
