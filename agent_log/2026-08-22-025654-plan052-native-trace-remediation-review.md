# Plan 052 原生 trace 整改独立复验

## 对象与结论

- 复验对象：`worktree-052-direction1-bottleneck-census@97b66fb98512408f9be641f29792144e5d7e52f4`
- 前次审查提交：`e35acf3`
- 结论：**验收不通过；当前提交的任务目标失败。** 原生 trace/API metadata → 安全任务级投影 → Terminal-Bench 固定结果文件的总体架构已经闭合，历史 census 修复也正确；但 C11 信号会被完整性门提前拒绝，C1 的 code-mode 输出会重复计数且覆盖语义过强，C2 又缺少 WBS 选候选所需的重复调用耗时。这三项直接阻碍“四问”决策，不是外围审计问题。

## Findings

### F1（P1，阻断）：C11 正好出现时，投影会因 usage 缺失而失败

`eval/rondo_eval/harness_observation.py:445-455` 要求每个 bundle 的 Team Lens `usage` capability 必须是
`available`。但 failed/cancelled inference 没有 usage 时，reducer 会正确产生 `partial`；现有
`eval/tests/test_team_lens.py:1064-1092` 已覆盖该语义。于是 response.incomplete、context-window 或 HTTP/stream
失败这类 C11 目标样本，会在 `_project_complete_sources()` 有机会把 `response_usage` 标成 `unmeasurable` 之前，
先被归为 observation incomplete。下一轮将因此丢掉最重要的正样本并判整包无效。

最低修复：生命周期仍须完整、trace/API population 与终态仍须一致；仅允许与 API metadata 一致的终态失败导致
usage `partial`，把聚合 usage 诚实标为不可测并保留类型化 C11 计数。增加一个 failed/incomplete 且无 usage 的合成
投影回归，证明 observation 能生成而不是放宽其它完整性门。

### F2（P1，阻断）：C1 的模型可见输出统计会重复计数，并对未覆盖工具宣称完整可测

code-mode 首次返回在 `mydev/codex-rs/core/src/tools/code_mode/execute_handler.rs:114-127` 写入
`code_cell_output_rendered`；同一个带 render metadata 的 `FunctionToolOutput` 随后又由通用 dispatch 在
`core/src/tools/tool_dispatch_trace.rs:98-127` 写入外层 `tool_call_ended.output_render`。投影器
`eval/rondo_eval/harness_observation.py:813-852` 无关联地把两类记录都追加进同一 `observations`，因此同一次模型可见
code-mode 输出的 render、字节、截断和 omission 会累计两次。Terminal-Bench 明确启用 code-mode host，这不是边缘路径。

同一投影只对 command/write_stdin 缺 render 事实时报错；例如 `McpToolOutput` 没有实现 render metadata，但 schema
仍把 `model_visible_output_truncation` 固定声明为 `measured`。这会把部分覆盖误报成完整覆盖。

最低修复：为每次实际模型可见交付选择一个规范记录并按已有 cell/tool 关系去重，补一条同时含外层 code-mode tool
与 code-cell 事件的投影回归；对其它工具类型逐字段判断，能在现有原生边界可靠取得就补齐，不能取得就用明确覆盖
计数或 partial/unmeasurable 表达，不能继续宣称全量 measured。无需重建 collector 或新遥测平台。

### F3（P2，阻断本次四问）：C2 有发生次数，却没有重复调用自身的耗时负担

`eval/rondo_eval/harness_observation.py:742-748` 只汇总所有工具耗时，`:755-783` 识别重复命令时只增加次数，schema
没有 repeated-tool duration。WBS 已要求 C2 只有在重复调用形成实际时长负担时才可入选；当前发布后的 body-free
资产无法把总工具耗时归因到重复调用，因此即使 20-run 复测完成，也回答不了“是否值得处理”。

最低修复：在现有逐工具 started/ended 与重复身份计算中增加一个安全聚合的重复调用耗时（是否再区分失败后重复由
执行者按最简一致语义决定），纳入 exact schema、compare 和窄回归即可。

### F4（低）：`turn.duration_ms` 实际写入的是 rollout 总时长

`harness_observation.py:625-628` 取 `exec_view["summary"]["duration_ms"]`，该值从 manifest 开始到 rollout 结束，
并非 `turns[0]` 的 started/ended 差。应按字段名计算真实 turn 时长，或把字段改名为 task/rollout duration 并同步比较
语义，避免后续影响归因混用。

## 已确认正确的部分

- Local measurement builder 确实只给 RONDO Local 注入 `CODEX_ROLLOUT_TRACE_ROOT`；普通历史 campaign、Codex、
  RONDO Multi 和默认产品路径不启用。
- 发布前投影写入固定 `harness-observation.json`，raw trace 不在归档 allowlist；未发现正文进入安全投影。
- writer 完整性终态会拒绝缺失、重复、非最终或 dropped operation；默认关闭时 render metadata 不计算、不持久化。
- 历史 census 已拒绝空 API requests、缺终态、重复/冲突终态和终态后继续写入；v28 的 30-run/311-request 与
  C1/C2/C11/C7 既有结论没有被整改推翻。
- WBS 对证据不足不硬选候选、只保留一个有界测量包、E-A 不恢复的决策合理。

## 本次轻量验证

- observation/census/Team Lens：42/42 通过。
- Local opt-in、发布投影、缺失投影停止及正式 campaign projector：4/4 通过。
- `just eval-plan052-census` 实时输出与受跟踪 v28 JSON 逐字节一致。
- `git diff --check e35acf3..97b66fb` 通过。
- 一次合并运行六个 Python 模块时被审查 sandbox 的 localhost 网络门阻止，随后改跑上述无网络窄集合；该环境阻止不算代码失败，也不冒充通过。
- 未重跑执行者已完成的 Rust 套件；未运行 Docker、真实 API、本地模型、全 workspace、CI 或 PR。

## 代用户作出的决策

1. **暂不授权 10 题 × 2 轮真实复测。** F1—F3 修复并复验前运行会在 C11 正样本上失败，并产生错误的 C1/C2 决策数据。
2. **认可当前总体架构，不要求机械删除或机械复用。** 继续以原生 trace/API metadata 和安全 Local 投影为主；已有语义合适则复用，确有决策价值的缺口允许在最合适的原生位置窄补，但不另起平台。
3. **原定下一包、模型、20 USD 上限及单变量原则保持不变。** F1—F3 是 Plan 052 观测正确性修复，不是开始实现 C1—C13 行为优化。
4. **E-A 继续不恢复。** 当前问题都可在既有 trace/投影链内窄修。
5. 修复仍只在 Plan 052 工作树提交，不合并、不推送、不归档；主工作区和 Plan 053 工作树不得触碰。

## 再验收条件

- F1—F3 有定向回归并通过；F4 语义同步；
- v28 census 保持逐字节一致，默认关闭态和 raw-trace 不归档边界不变；
- 相关 Python 与必要窄 Rust 测试通过，不要求全 workspace 或真实运行；
- 工作树干净且修复已提交，执行摘要说明仍不可测字段和未运行项。
