# Plan 052 方向 1 规划

- 基线：clean `main@9f32f22`，创建专用 worktree
  `.claude/worktrees/052-direction1-bottleneck-census` 与分支
  `worktree-052-direction1-bottleneck-census`；未改动主工作区 tracked 文件。
- 规划：按 `plan/plan-example.md` 建立方向 1 RONDO Local Harness 聚合观测与瓶颈普查 ExecPlan；同步顶层、
  方向 1 与方向 0 WBS，明确本包只做行为保持型观测、证据普查和单一后续决策，不实施 C1—C13 优化。
- 核对：阅读相关 AGENTS、README、WBS、候选研究、数据布局、Plan 051、现有 eval 接线与 Local 实时源码。
  现有 `codex exec --json` 资产能提供部分 token/cache、终态、命令与文件变化证据，但 compact、完整请求终止原因、
  Guardian 与完整工具时序尚未统一进入任务结果；不可测项将在执行期如实分类。
- ignored 资产：仅对主物理根 `eval-data/` 做了 body-free 结构盘点，确认普通 worktree 不复制这些资产；未复制或
  汇报 prompt、命令、工具输出、任务正文等私有内容，未读取 `.env.local`。
- 现场保护：收尾时主工作区出现一份来源不明、与本任务不重叠的 untracked 研究文档；未打开、移动或纳入，当前
  规划提交继续只落专用 worktree，执行开始和未来合并前需再次复核。
- 验证：本次只有文档规划，未运行 Cargo、Docker、真实 API、本地模型、训练或全 workspace 测试。交付边界为只
  提交任务分支，合并、推送和分支归档等待用户另行批准。
