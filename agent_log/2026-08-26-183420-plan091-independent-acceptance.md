# Plan 091 独立验收

## 结论

`PASS`。实现符合 Plan 091 的目标和边界，未发现高、中等级 correctness finding；本地任务结论为
`COMPLETED / ACCEPTED / UPSTREAM_37421_BACKPORT_PASS / MAIN_INTEGRATION_PENDING / NOT_PUSHED`。

## 验收摘要

- `d68db9743e6208b5cdcc062c05a1c1094740a355` 以一次性只读投影合并已加载 turn snapshot 与当前 replay buffer，按 turn/item ID
  去重，只补 prompt-edit 定位所需的用户消息、review 边界与 completion 元数据；投影不写回 store，也不改变源线程、持久格式或既有
  backtrack 裁决。
- buffer-only 端到端回归验证所选 turn 可在 `Interrupted` 后正确 fork-before，恢复文本、attachment 与 mention；源 rollout 字节、源
  turn 顺序及分支历史均保持正确。辅助单测覆盖 `Completed`/`Interrupted`、snapshot/buffer 重叠、重复通知、orphan item、review marker
  和完成元数据。
- 正式聚焦稳定轮 Nextest `14e30ee7-43ad-49ce-b828-9aad98605836` 为 20/20 passed；scoped
  `just fix -p codex-tui`、`just fmt`、`just fmt-check`、`git diff --check` 通过。验收采用现有正式证据与源码/JUnit 只读复核，未重复运行
  重型测试。
- 完整 `codex-tui` 额外批次如实为 3436 passed、3 failed、4 skipped。三项失败均是 Plan 091 未修改的 durable-session
  `setRootState` fixture/snapshot 既有欠账；提交父版本已具备相同缺口，091 对相关文件零差异，因此不阻断本任务，也不在本任务越界代修。
- 正式重型批次均经共享 lock/watchdog，复用 Plan 069 target，`stop=none cleanup=none`；30GB Windows `C:` 停止线仅按用户临时批准
  作用于 Plan 091 命令，未修改长期资源配置。退出时无 Cargo/rustc/nextest 或活跃构建 scope。
- diff 仅涉及 TUI prompt-edit 直接代码/测试、Plan 与实施日志；未触及 Plan 090、`mydev/`、协议/持久格式、WBS 路线、第四期结论、
  上游基线或其它 transcript 修复。

## 审查决定

1. 接受完整 `codex-tui` 批次的三项既有 fixture/snapshot 失败为非阻断基线欠账；本任务已有相称的根因、相邻行为和稳定轮证据，不新增
   重型复跑或跨范围修复。
2. 接受命令级 30GB Windows `C:` 临时停止线的实际使用；该例外随 Plan 091 本地执行结束，不写入仓库默认门禁，也不继承给后续任务。
3. Plan 091 在独立工作树内完成即满足本轮验收；合并本地 `main`、推送、分支归档和 worktree 清理均等待用户另行批准。

## 未执行与停止点

未运行 full workspace、`--all-features`、真实 API/模型、Docker、训练、测评、发布或上传。未 merge/rebase/push，未归档分支或删除
worktree。
