# Plan 071 验收整改复审

## 结论

- 审查状态：`ACCEPTED`
- 任务状态：`BASE_COMPARABILITY_GO / COMPLETE`
- 前次 P2 finding 已闭合；本轮未发现新的范围内 correctness 或功能性问题。
- 唯一有效正式真实模型轮继续为
  `plan071-formal-20260825T064600Z-qualification-v5`。base、C1、C3 均为 `QUALIFIED`，C2 未重验并保持
  Plan 068 历史 `NOT_QUALIFIED`，`m3_c2_prerequisite_satisfied=true`。

## Finding 闭合

整改提交 `c69868f07d46f7991c6b9bac4904fdaf22dc6088` 将 formal 终态判断改为先检查合格锚点：

- C1/C3 均无 `QUALIFIED` 时，base 为 `QUALIFIED`、`NOT_QUALIFIED` 或 `INCONCLUSIVE` 均返回
  `INCONCLUSIVE / no_qualified_anchor_for_shared_comparability_rule`；
- 至少一个锚点 `QUALIFIED` 时，base `QUALIFIED` 返回 `BASE_COMPARABILITY_GO`，base
  `NOT_QUALIFIED` 返回 `BASE_NOT_COMPARABLE`，base `INCONCLUSIVE` 保持 `INCONCLUSIVE`；
- commissioning 继续只返回 `INCONCLUSIVE / commissioning_has_no_task_terminal`。

新增回归直接覆盖了三对象同时 `NOT_QUALIFIED` 的遗漏组合；原有 base 失败且锚点合格的
`BASE_NOT_COMPARABLE`、base 合格但无合格锚点、base 基础设施不确定等覆盖继续通过。另以轻量构造补查 base
`INCONCLUSIVE` 且 C1/C3 均 `NOT_QUALIFIED`，结果也正确为无合格锚点的 `INCONCLUSIVE`。

## v5 不变性

使用整改后的 `build_observations/evaluate_run` 从 v5 manifest/raw 重新构建：

- rebuilt observations 与 raw observations、archive observations 完全相等；
- rebuilt result 与 archive result 完全相等；
- observations canonical SHA-256 仍为
  `46d7b4bfc725f61d66d2ca20030b7409f124467020b8201eec114c4cd93eb6ac`；
- result canonical SHA-256 为
  `bfc5f1e42e65093d63e3731e3671a8c5f7fa5dbf549e65cc7062611ebad2d8ad`；
- 终态仍为 `BASE_COMPARABILITY_GO / base_and_anchor_qualified`，对象结论仍为 base/C1/C3
  `QUALIFIED`。

因此前次审查代用户作出的决定成立：本次窄逻辑修复没有改变 v5 实际走过的分支、模型输出、对象结论、正式归档或 schema，保留 v5
为唯一正式真实模型轮，不需要重跑真实模型、Cargo 或 Docker。

## 验证

- Plan 068 qualification/service runner 与 Plan 071 comparability unittest：41/41 通过。
- 终态遗漏组合轻量补查：通过。
- v5 observations/result 机械重建一致性：通过。
- 受影响 Python `compileall`、`git diff --check`：通过。
- worktree 在整改提交处 clean；主工作区保持 clean，未合并、未推送。
- 未运行真实模型、Cargo、Docker、HF 下载、真实 API 或外部写入。

## 代用户作出的终态决定

接受 Plan 071 的 `BASE_COMPARABILITY_GO`。M3-C2 的 base + 已合格训练候选前置可以在后续获授权的 WBS 同步中解除；这不等于启动
M3-C2，也不授权模型排名、最终 threshold、产品配置选择或默认启用 Publication Critic。
