# Plan 033 验收整改

日期：2026-08-15 ｜ 分支/worktree：`033-l3-l4-unfinetuned-baseline`
针对：`agent_log/2026-08-15-084543-plan033-independent-acceptance.md`（验收不通过的两个窄缺口 + 两处文档事实）

三条 finding 全部复现属实，已按审查意见在同一 worktree 窄修。未重跑模型、未改冻结输入、未改指标口径，
40 条真实结果与 baseline 逐字节不变。

## 1. 统一结果校验补齐 shadow 合同（finding 1）

复现：`_validate_record()` 会接受 `local-static/imported`、`sol-static/auto`，也会接受携带非空 `tasks`
的 holdout shadow 行。原因是我只在 `artifacts.py` 落了 `source` 枚举与 imported 的空字段规则，
把 side 映射和 holdout 投影留在了专用 builder 里——而 Plan 033 §3.4.2 明确要求统一校验理解该合同。

修复：
- 新增 `_SHADOW_SOURCE_BY_SIDE`：`sol-static`=`imported`、`local-static`/`local-ft-static`=`auto`。
  **未声明映射的 shadow side 一律拒绝发布**，包括已退役且零行的 `luna-static`；不为它猜一个 source，
  要用先在 `doc/eval-data-layout.md` 写清合同。
- 新增 `_validate_hidden_set_projection()`：`config.taskset == "holdout"`（shadow 行另按
  `config.partition`）时 `tasks` 必须为 `null`。规则按行自身声明判定，对所有 track 成立，不只服务当前写入方。
  已确认 244 条历史行的 `taskset` 全为缺省，收紧不影响既有账本。

## 2. 交付状态下的离线重算（finding 2）

复现：最终 HEAD 上 `publish` 返回 exit 70 `harness_commit_moved_since_run`。我此前那次"幂等 no-op"
是在结果与文档提交**之前**跑的，当时 HEAD 仍是 `bbb572d`；把它写成交付物的性质是我的表述错误。

修复：把等值绑定改为**祖先绑定** `require_run_commit_in_history()`（`git merge-base --is-ancestor`）。
发布本来就发生在运行之后，结果与文档本身就是新的 commit，要求 HEAD 恒等于运行 commit 会让交付状态
永远无法重算自己的 baseline；真正需要成立的是"测量所用的 harness 仍在本历史里、没有被改写"。
运行前的 clean-tree 约束一个字没动，运行时仍要求 `git_dirty=false`。

## 3. 文档事实（finding 3）

- `doc/WBS/local-approval-model.md`：L5 段落改为"L5a 与 L3/L4 均已完成；当前推进 L5b"。
- `doc/eval-data-layout.md`、`doc/WBS.md`、`doc/WBS/eval-benchmark.md`：把 244 明确为 `track=tb` 子集，
  当前账本共 248 条（另含 4 条 shadow）。同时补写新强制的 side→source 映射与 holdout 投影规则。

## 验收结果

- focused `test_shadow_replay` 44 项（新增 3 项：side/source 映射负向、holdout `tasks=null` 负向兼 seed 放行、
  真实 git 历史上的祖先绑定）与直接受影响的既有测试合计 **326 项通过、0 skip**；
  `uv lock --check` 85 packages 通过。
- 最终交付 HEAD 上 `publish` 为真正的幂等 no-op：exit 0、`newly_published=[]`、
  baseline SHA-256 仍为 `ca0bbc21…9d4dcd`、账本仍 248 条。该次发布会用收紧后的校验重新验证全部 248 行，
  因此已发布的四条 shadow 行本身也满足新映射与 holdout 规则。
- 既有 `test_config_and_artifacts` 的 shadow 用例按新合同调整：`sol-static` 改用合法的 `imported` 组合
  继续验证"教师侧不得携带 product"，`luna-static` 改为验证"无声明映射即拒绝"。

## 边界

未启动模型、GPU、Docker、Cargo 或任何 API；未重新 prepare 教师批次、未改标签、未改指标定义、
未改 40 条私有终态或已发布结果内容；未合并、未推送。主工作区两个未知 `doc/research` 文件与四个旧
`.staging-*` 目录按验收决定保持不动。
