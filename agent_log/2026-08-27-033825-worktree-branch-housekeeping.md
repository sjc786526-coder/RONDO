# Plan 094 收口后的工作树与分支清理

## 背景

Plan 094 已以 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT / ZERO_POD / VOLUME_RETAINED / FINAL_REVIEW_ACCEPTED`
完成并合入 main。盘点发现工作树与分支归档流程有遗留：Plan 090 的分支已按 CLAUDE.md §5.5 改名
`zz-done/`，但 worktree 未移除；另有 4 个已并入 main 的分支未归档。

## 孤儿进程

`runpod-lifecycle-guard.py`（PID 3125976）自 `00:56:47` 起持续运行 2h39m，状态 `armed`，
守护对象 `pod_id=0bsry5tbei7p4o`，`termination_trigger_at=2026-08-27T11:17:42Z`，未写出 `pod-terminal.json`。

该 Pod 实际已由 Plan 087 exact terminal helper 完成 stop/delete（receipt SHA-256 `25d3377e…`），
独立 live query 确认账户 0 Pod、compute `$0/h`，WBS 终态为 `ZERO_POD`。该守护因此是孤儿：
若放任到期，会对已不存在的 Pod 发起一次无谓的外部删除调用。经用户批准以 SIGTERM 终止，进程已退出。

注：`pod-lifecycle-guard-armed.json` 仍保留 `status=armed` 与已失效 PID，作为当时的历史证据未改写。

## 工作树与分支处置

移除前逐个复验：工作区改动数 0、未并入 main 的提交数 0、`git diff --diff-filter=D <branch> main` 为空
（分支内容无一遗失）。两个 worktree 均以 `git worktree remove` 干净移除，未使用 `--force`。

| 对象 | 处置 |
|---|---|
| worktree `090-publication-critic-route-o-confirmation` | 移除（184M），分支此前已为 `zz-done/` |
| worktree `094-publication-critic-route-o-continuous-training` | 移除（185M） |
| `worktree-094-publication-critic-route-o-continuous-training` | 改名 `zz-done/` |
| `worktree-074-persisted-cwd-read-consistency` | 改名 `zz-done/` |
| `worktree-078-m4-s2-recovery-lifecycle` | 改名 `zz-done/` |
| `worktree-083-m4-z-core-durable-team-closure` | 改名 `zz-done/` |
| `review-079-3bb1253` | 改名 `zz-done/`，**分支与历史完整保留** |

5 个分支改名前后 SHA 逐一核对完全一致，无历史丢失。

## 保留项

- worktree `093-clean-full-workspace-baseline`（290M）与其分支继续保留：既有提交明确记为
  pending approval，且它承载当前 RONDO Multi Linux 全 workspace 正确性基线，其中约 108M 为
  `multidev/scripts/.venv` 等构建环境，重建须跑重型流程。
- `zz-done/review-079-3bb1253` 含 1 个未并入 main 的提交 `e32c77d`（766 行新增：Plan 079 checkpoint
  review 日志、`test_runpod_plan079_initial_controller.py` 245 行、
  `create-runpod-plan079-initial-when-ready.py` 453 行）。归档只改名，未合并、未删除。

## 验收

- `git worktree list` 仅剩 main 与 093；`git worktree prune` 已执行。
- 除 093 外全部本地分支已在 `zz-done/` 命名空间。
- `e32c77d` 及其 766 行改动复核完好。
- `eval-data/publication-critic/plan094/` 23M、38 个文件未受影响（数据资产本就在主仓库，不在 worktree）。
- `.claude/worktrees` 由 658M 降至 290M，释放 368M。主工作区 `git status` 干净。
