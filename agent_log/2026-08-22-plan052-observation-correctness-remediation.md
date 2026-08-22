# Plan 052 任务投影二次正确性整改

## 结果

- schema-v2 不再要求所有 inference usage 完整：仅 failed/cancelled/aborted 缺 usage 可保留，completed 缺失继续拒绝；
  trace 与 API 按 main/Guardian 核对缺失数及已知 usage 合计，任务结果保留类型化 C11 终态并把 usage 标为不可测。
- model-visible 与 code-mode-runtime 分别记录 output delivery、render 覆盖和缺口，并据此给出
  measured/partial/unmeasurable。command render 缺失继续失败关闭，MCP 等没有 metadata 的工具不再使整份 observation
  失败，也不再冒充测得的零；partial 两侧的字节、omission、truncation delta 返回 `null`。
- 实时路径证明 public custom `exec` 已由 rollout-trace 的既有 suppress 规则排除通用 ToolDispatchTrace，复验报告所称
  正常首次输出必然双记并不存在。投影仍以相同 thread、turn、model-call ID 关联防御性双记录，选择 canonical
  code-cell render，相同值只计一次、不同值拒绝；code-mode nested tool 保持独立 runtime 表面。
- C2 新增 `repeated_exact_command_lifecycle_duration_ms`，只累计每次精确重复的后续调用自身，不含首次调用；
  `turn.duration_ms` 改为唯一 exec turn 的 `ended-started`，不再使用 manifest 到 rollout 结束的总时长。
- 当前唯一后续测量包、模型、20 USD 上限、停止/回滚判据及 E-A 不恢复决定均未改变；未运行真实复测或行为优化。

## 验证

- 相关 Python 288/288 通过：observation/census/Team Lens/Terminal-Bench/结果发布与配置 189 项，公平比较
  99 项；没有扩大到全 eval。
- 共享构建锁、cgroup 与容量看门狗下，`codex-rollout-trace` 的
  `suppresses_only_noncanonical_dispatch_boundaries` 1/1 通过（其余 61 项按精确过滤跳过）。
- `just eval-plan052-census` 重建结果与 tracked 冻结 JSON 逐字节一致；`just fmt` 与 `git diff --check` 通过。
- 最终只读独立复核结论为 PASS，无 correctness/functionality 阻断。复核确认 F1—F4、schema-v2、body-free
  比较和 WBS 四问均闭合；未要求为已由 surface/requester 合同覆盖的 nested runtime 再扩建重复设施。

## 边界

本轮未读取新的 private run 正文；census 重建只按既有 tracked v28 身份读取同一主物理根 ignored 资产。一次误用
worktree-local `uv run` 创建的 100 KiB ignored `eval/.venv` 已确认是本任务新建后精确删除，未触碰共享主根环境。
重建时只在工作树 `eval-data/plan052-remediation/` 写入一个 body-free 临时 JSON 并精确删除；主物理根同名空目录也
在确认未写入后删除。定向 Rust 单测只写既有项目 target/cache 与工作树 `.codex/build-watchdog` 证据。
未运行 Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI 或 PR；未修改主工作区
或 Plan 053 worktree。
