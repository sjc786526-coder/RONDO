# Plan 052 public `exec` 最终交付边界整改

日期：2026-08-22

## 修改

- 复现并确认 public code-mode `exec` 的 parse/runtime-start/initial-response 错误可早于 code-cell render 返回模型，
  旧投影会误报 `0 deliveries / measured`。
- 在统一 caller-facing `ToolCallRuntime` 边界增加 body-free 原子事件：每个 public `exec` 最终输出记录一次
  model-call 身份与可选 render。正常输出携带安全整数/布尔聚合；早期错误、取消或最终输出替换缺少可靠 render
  时记录 delivery + missing；Fatal 不产生模型输出，因而不记录 delivery。
- 停止在 execute handler 生成新的首次 code-cell render。旧事件类型保留用于读取和一致性核对，但不能把原子事件的
  missing 升级为 measured。投影对重复 delivery、dangling cell 和不一致 render 失败关闭。
- WBS 将交叉核对能力收敛为 main/Guardian population、completed/non-completed、分角色 usage 缺失数与已知合计；
  首个真实请求或非空 API/trace/result 工件固定正式 slot 与 20-run 分母，边界前普通接线问题可窄修，边界后不得
  替换、补题、补轮或改分母。

## 验证

- `just fix -p codex-rollout-trace -p codex-core`：通过（共享构建锁与 cgroup 看门狗）。
- `just test -p codex-rollout-trace code_mode_exec_delivery_records_only_model_call_identity`：1/1 通过。
- `just test -p codex-core public_exec_parse_failure_records_one_model_output_delivery`：1/1 通过。
- Plan 052 observation/census/Team Lens/Terminal-Bench/config/fair-comparison 相关 Python：294/294 通过。
- `just eval-plan052-census <临时输出>` 后与 tracked v1 census `cmp`：逐字节一致；临时文件与专属目录已删除。
- `just fmt` 与 `git diff --check`：通过；格式化器触及的无关 config test 换行已还原。

未运行 Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI 或 PR。

## ignored 资产边界

冻结 census 仍从 Plan 052 worktree 发起，只读访问 Git common root 下既有的 v28 ignored Local 运行资产；未打印或
持久化正文、prompt、命令、输出、原始参数或私有字段。本轮只在工作树 `eval-data/plan052-remediation/` 写入一份
body-free 临时 census，逐字节核对后已精确删除。主物理根未产生新的 ignored 写入，既有运行资产未改写、移动或删除。

## 独立复核

最终聚焦只读复核发现一项真实 fail-closed 关系：原子事件的 `Some(render)` 还须证明同一 model-call 已形成 cell
initial response。投影已增加该约束与损坏 trace 回归，相关 294/294 通过；复核另跑 observation + Team Lens 51/51
并确认 PASS：无剩余阻断、正文泄露或明显局部回归。
