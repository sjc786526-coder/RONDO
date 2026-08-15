# Plan 034 独立验收整改

日期：2026-08-15 ｜ 分支/worktree：`034-l5b-synthetic-training-dataset`
针对：`agent_log/2026-08-15-102449-plan034-independent-acceptance.md`

## Finding 复核与修复

审查 finding 属实：`synthetic_training.py` 为拒绝复制源参考而硬编码了五个来自 Plan 032 私有批次、同时与
holdout 重叠的 marker。虽然这些值没有进入 600 条最终数据，把它们放进 tracked validator 本身仍违反本任务的
holdout/tracked 边界。

本次删除该 marker 列表及其逐字扫描，不修改 prompt/schema、私有候选、train/validation、manifest 或数据卡。
没有改为运行时派生通用 DLP：当前 strict static-v3/decision-v1、synthetic action workspace 和 holdout 内存近重复
过滤已足以复核本次冻结批次；增加一套数据治理设施不属于 Plan 034，也不能挽回把私有值固化进源码的错误。

## 复验

- 原四组 focused 测试 **90/90 通过**。
- 正式 release verify 从私有候选和冻结教师批次重算成功：600 条、train 470 / validation 130、allow 240 /
  deny 360、六类分布及 holdout 排除 0 均不变。
- train / validation / manifest SHA-256 仍分别为 `1e66c06e…c110a`、`cbab8084…8dd2`、
  `dbf5fffe…7190`；当前源码已无该 marker 列表和拒绝分支，`git diff --check` 通过。
- 未重新生成数据、调用 Sol、运行训练/dry-run、本地模型、Docker、Cargo、API、Hub、Job、上传、CI 或 PR；
  未修改主工作区、其他 worktree、`mydev/`、`multidev/`、Plan 032/033 或历史结果。
