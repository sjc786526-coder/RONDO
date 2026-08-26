# Plan 087 最终审查仓库收口

## 问题确认与实现

- 最终审查提出的三项阻塞均存在：抢卡脚本/测试仍带 Plan 079 名称，Plan 087 仍有专用 create/confirm/receipt 体系，根 AGENTS/CLAUDE
  尚未固定通用抢卡职责。研究终态本身无 High/Medium finding，因此本轮未访问云端、创建 Pod、重跑训练或改写结果。
- `scripts/create-runpod-plan079-initial-when-ready.py` 原位重命名为 `scripts/create-runpod-when-ready.py`；测试同步更名并移除 Plan 079
  模块、class 与 fixture Pod 标识。脚本行为未扩张，仍只负责库存轮询、自动创建和不确定 create 响应的 exact-name 防重复对账。
- 完整删除 `training/publication-critic-plan087/runpod-create.py`、八项 create/confirm 测试、current source-bundle required member，以及
  Plan 087 README/runbook/ExecPlan 的专用 pending/final 创建 receipt 语义。保留 `runpod-terminal.py` 及四项 shell/terminal 测试。
- Plan 087 当前流程改为库存紧张时使用通用脚本先创建；随后由执行者通过既有 RunPod MCP/CLI 独立核验实际价格、GPU、机房和网络卷挂载。
  脚本输出只是状态，不是资格 receipt；任一不符或无法确认都由保留的 terminal 能力立即释放并确认 0 Pod。
- 根 `AGENTS.md` 与 `CLAUDE.md` 的工作流程新增逐字一致第 7 条；Plan 079 runbook、冻结 Plan 082 ExecPlan 的有效旧路径引用仅做机械替换。
  非 `agent_log/` 的旧脚本路径与 Plan 087 专用创建器引用均为零。

## 验证与边界

- 通用抢卡脚本独立 6 项通过；Plan 087 shell/terminal 与 source-bundle 定向 8 项通过；Plan 081/082/087 加通用入口的完整聚焦回归
  共 91 项通过。
- 定向 Ruff correctness 与 format、5 个受影响 Python 文件 AST、通用脚本和 terminal CLI help、三个 shell `bash -n`、根工作流第 7 条一致性、
  非历史旧引用、`git diff --check`、正式结果 untouched 与三份 WBS/WBS-COMPLETED untouched 门禁通过。
- 既有 `source-bundle-6dd27d8.tar` 及 receipt 保持历史执行输入身份，没有重建；Route O 指标、41 张费用快照、handoff、终态结果、远端候选、
  0 Pod 和 57GB 保留卷事实均未修改或重跑。历史 `agent_log/` 未修改，本轮只纳入审查报告与本整改日志。
- 未运行 Cargo、Docker、本地/云端真实模型、API/Judge 或 unseen；未查询/修改 RunPod/HF，未合并、推送、归档分支或删除 worktree/网络卷。
