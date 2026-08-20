# Plan 048：Team Lens 重新验收

## 审查对象与结论

- 审查对象：`worktree-048-team-lens@2c10958a55a5b8bc782af3d7456bf2cc448a997c`，重点复核
  `a3f7c20..2c10958` 的验收返修。
- 范围保持轻量：检查上次 4 个阻断、相邻 reducer/schema/renderer 语义、定向测试、指定现场 bundle 和 CLI/HTML smoke；
  未扩大到 Rust、Docker、API、模型、完整数据集或 workspace 全量测试。
- **验收结论：通过。** 4 个阻断均以现有 typed 原生字段在 Python consumer/schema 内完成窄修，未发现新的可复现
  正确性或功能回归。
- **任务目标结论：完成。** 同一消费者、body-free 确定性 Team View、诚实四态降级与只消费 Team View 的离线单文件
  HTML 均达到本任务预期；零 hook 结论继续成立。

## 四项返修复核

1. 非 spawn 的结构化 `SessionSource` 现在不再伪造 parent 或被错误拒绝；只有结构正确且含非空 parent 的
   `subagent.thread_spawn` 才产生 parent，和冻结原生 reducer 的 best-effort 语义一致。
2. turn terminal 会按冻结原生映射关闭同 turn 仍 running 的 inference；turn-end 后的一个合法 late terminal 只补 usage，
   不覆盖已确定的状态和结束窗口。completed/cancelled、failed、aborted 组合均有回归。
3. 可选 invocation 缺失时，`ToolCallKind::Other.name` 和 `Mcp.server/tool` 的 body-free typed 身份会被保留，Team result
   不再因工具名退化成 `other` 而漏归约；普通 kind 仍可作为规范化类别名使用。
4. Team Event/Version/Route/Fact rows 及双向关系统一按 `(first_seq, stable_id)` 输出，schema 同步拒绝乱序合同；renderer
   不再自行猜测 Event/Version 链顺序。十进制 ordinal 超过 9 的回归已覆盖。

## 实际验证

- `PYTHONPATH=eval python3 -m unittest -v eval/tests/test_team_lens.py`：25/25 通过，约 0.1 秒。
- 指定 ignored 现场 24/24 个 RONDO M-5 bundle 归约成功；每个 bundle 重复归约和渲染的 JSON/HTML 均字节一致，
  capability 矩阵与返修前诚实降级结果一致，仍有 1 个样本五类 Team capability 全 `available`。
- 合成 CLI `--help`、两次 `reduce`、两次 `report` 全部返回 0；两份 JSON、两份 HTML 各自字节一致。
- 内嵌 JavaScript 通过 `node --check`；原有 body-free、Codex `not_applicable`、HTML 转义/自包含、renderer 单向依赖、
  Fact observation/omission、wait/interaction 与 terminal timing 回归继续通过。
- 独立只读复验未发现 findings；`git diff --check 7ba7eb6..2c10958` 通过。
- 变更路径没有 raw `trace.jsonl`、payload、`state.json`、生成的 `team_view.json`/`team_report.html`、依赖、Rust、任务 A
  或共享 WBS 修改。验证生成的 ignored `__pycache__` 已在审查结束前清除。

## 代用户作出的决策

1. **接受 `2c10958` 为任务 B 的完成提交。** 上次审查提交 `a3f7c20` 的阻断已经关闭，B 侧可以结束返修状态。
2. **保持零 hook。** 不为 viewer 增加 Rust/runtime/Team State 字段，也不建立第二套 tracing；现场与合成证据已经足够。
3. **不追加重型门禁。** 实现没有修改 M-5 共用 reader、Rust 或依赖，本次 25 项定向测试、24 bundle 和 CLI/HTML smoke
   已与风险相称；不补跑 Cargo、Docker、全量 eval 或 workspace 测试。
4. 上次报告中的 capability 局部 badge 观察继续作为非阻断：总 capability matrix 和空/降级状态已经清楚，不要求重复
   badge、额外前端框架或审计设施。
5. Codex 侧结构忠实的合成原生 fixture 继续作为本轮验收证据；在无现成真实 Codex bundle 且禁止 API/模型的边界下，
   不为“真实”标签扩大授权。
6. 任务 B 已不再阻塞最终整合；是否启动 A/B 统一整合仍取决于任务 A 已独立验收，并按用户原约定另行批准合并和推送。

## 当前交付状态

- 048 工作树代码与文档均已本地提交；本审查只新增本报告。
- 未合并、未推送、未修改 main 或任务 A。
- Team Lens 本任务没有未决产品/实现决策或返修项。
