# Plan 082 一次性 transfer Pod 大型资产交接

## 结论

- 状态更新为 `FINAL_REVIEW_PENDING / ZERO_POD / VOLUME_RETAINED_PENDING_USER_DELETE`。正式研究终态仍为
  `VALID_NO_IMPROVEMENT`，没有重跑、换 seed 或修改比较规则。
- 冻结 bootstrap 的 39 个正式对象已完整回传到主物理根 ignored 目录；逐对象 bytes/SHA-256、exact-tree、文件/目录权限和无符号链接
  检查全部通过。正式对象共 `13,797,142,360` bytes，加 14,524-byte bootstrap 后共 `13,797,156,884` bytes、40/40 文件。
- transfer Pod 已删除，控制面确认账户 0 Pod、持续 compute 费率 0；40GB 网络卷 `mwemzrn33y` 继续保留，未获用户删除授权。

## 资源与运行

- 创建前实时 CPU catalog 在 US-TX-3 无兼容供给；选择该 DC 当时最低费用的可用 Secure RTX 4090，费率 0.74 USD/h，仅一张卡、仅一个
  Pod `4zhyem0wq6nx6q`。原 40GB 卷以 `/workspace` 挂载并核对身份，没有创建第二卷。
- 首个 `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` 容器因宿主驱动不满足 CUDA 12.8 要求而未启动；同一 Pod 改为官方
  `runpod/base:1.0.2-ubuntu2204` 后只用 SSH/rsync 读取冻结对象。没有训练、加载模型到 GPU、修改正式结果或写回远端卷。
- 续传使用 `--partial --append-verify`。为减少计费先对不同大对象并行读取；在路径可能相遇前主动收敛为单流，最终对完整辅助对象停止
  冗余网络复验，并以本地全量 SHA-256 作为接受标准。缺失的 5 个小型 checkpoint 文件和 bootstrap 随后按精确清单补传，未扩大对象集合。

## 证据与费用

- 本地验证 receipt：
  `eval-data/publication-critic/plan082/stage-b-20260826/transfer/local-transfer-verification-receipt.json`，SHA-256
  `7e7782b764db2a8a45bbe1a639337980b3086dc91b0975b453df4fe098e60fef`。
- 资源终态 receipt：
  `eval-data/publication-critic/plan082/stage-b-20260826/transfer/transfer-terminal-receipt.json`，SHA-256
  `b88f92e245c4f7d7f3689cf4fb850be35b91a2448a4b44489dd2ea941d1d359e`。项目物理根最终
  `266,995,116,597` bytes，Windows C: 可用 `75,144,908,800` bytes，均通过 270GB/50GB 门禁。
- provider 当前记录 transfer Pod 费用 0.239372 USD、当前卷费 0.007778 USD；任务当前 provider 入账合计约 1.007324 USD。
  transfer 按创建到 0 Pod 全墙钟计算的保守上界为 0.960904 USD，任务保守累计上界约 1.728857 USD，未达到 10 USD 告警线。

## 本地回归

- Plan 082 training/handoff/scripts、Plan 081 training 与 Plan 068 handoff 相邻轻量回归 `83/83` 通过。初次 `uv --directory eval`
  调用漏传工作树根 `PYTHONPATH`，66 项通过后在模块收集时报 ImportError；补齐既有调用环境后原样完整重跑通过，不涉及代码修复。
- 五支 Plan 082 shell 的 `bash -n`、相关 Python compileall、Ruff 0.15.12 聚焦检查和 `git diff --check` 通过。

## 边界

- 原始数据、commissioning/formal checkpoint、observations、日志和其它任务工件均继续保留在网络卷；本地下载目录也完整保留。
- 未读取或输出 `.env.local`/S3 凭据，未访问 HF、未训练、未运行 Cargo、Docker、全 workspace 或本地真实模型，未合并或推送。
