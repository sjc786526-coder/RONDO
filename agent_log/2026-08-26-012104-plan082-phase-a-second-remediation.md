# Plan 082 阶段 A 整改复验剩余问题修复

时间：2026-08-26 ｜ 实施基线：`4d65245e8cce309f65094fa1a56ae5a685348d49`

## 修改

- 确认整改复验报告的 2 项 Medium 均存在。update 变化证明改为在 optimizer step 前保存当前 scope 全部非零梯度参数的 CPU 前值，
  step 后按参数大小和名称顺序逐个 `torch.equal`，任一参数真实变化即接受、全部 bit-identical 才拒绝；成功 receipt 记录实际变化的参数和
  最大绝对变化。这样关闭单参数 false no-op，不增加 GPU 全 scope clone、概率 hash 或第二套训练设施。
- retained handoff producer 在任何 artifact store 验证/扫描前约束输出必须是 task root 内、artifact root 外的安全新路径，父目录必须已存在且
  全为普通目录；相同路径、祖先、后代、task 外路径和符号链接 alias 均 fail-closed。直接负例证明 checkpoint 内未产生 bootstrap 文件，
  原 checkpoint 仍可按原 content identity 验证。

## 验证

- 两项直接回归先复现原失败，再由红转绿；Plan 082 training/handoff/scripts、Plan 081 training 与 Plan 068 handoff 相邻轻量回归
  `81/81` 通过。
- 修改 Python 使用 Ruff `0.15.12` 检查通过；相关 compileall、五支 shell 的 `bash -n`、`git diff --check` 通过。inventory/download
  两个真实 wrapper 的 dry-run 继续绑定 exact worktree 与固定 venv，均返回 `secret_access=false`、`network_access=false`。

## 边界

- 未查询或创建 Pod/网络卷，未访问 RunPod/HF/S3，未读取凭据或 `.env.local`，未上传数据、下载或加载真实模型、训练或产生费用。
- 未运行 Cargo、Docker、全 workspace、CI/PR。阶段 B 继续未授权；阶段 A 验收通过仍不构成用户人工付费批准。
