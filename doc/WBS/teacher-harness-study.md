# 方向 1：Harness 优化

最后更新：2026-08-22 ｜ 状态：**Plan 052 已完成；下一唯一方向内工作包为 10 题 × 2 轮有界观测复测** ｜
源码位置：`mydev/` ｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 当前状态

方向 1 已由 Plan 052 正式重启。默认关闭的原生 trace opt-in、任务级安全离线投影、历史普查器与日期冻结证据
已经落地；本任务没有实施 C1—C13 行为优化，也不涉及方向 3。

此前教师 harness 的只读研究 T1—T3 已完成。研究交付
`doc/research/teacher-harness-performance-candidates.md` 保留为形成时点的证据与候选池；候选进入实现仍必须由
当前方向 1 的真实瓶颈和影响证据决定，不能根据教师实现或历史 v22 差异直接选择。

E-A 轻量离线冻结回放当前不恢复。Plan 052 已确认现有资产、原生事实投影和一次有界真实复测足以承接下一步；
只有未来已经选定的机制确需反复低成本实验时，才重新评估必要的最小 replay 能力。

## Plan 052 结论

任务合同见 `plan/052-direction1-local-harness-bottleneck-census-execplan.md`，冻结证据见
`doc/audit-snapshots/2026-08-22-rondo-local-harness-bottleneck-census.md`：

- 最终事实链复用 rollout trace 与 API metadata，并在结果发布前生成 schema-v2 body-free 任务投影。原始 trace
  不进入归档；缺失、残缺、重复、schema 漂移或两来源不一致均拒绝发布。
- public `exec` 在最终 caller-facing 边界记录交付事实与可选安全 render 聚合；早期错误、取消或最终输出替换缺少
  可靠 render 时形成覆盖缺失，不再冒充“测得的零”。重复的在线 collector 已删除，默认产品行为保持不变。
- v28 历史 cohort 为 10 个任务 × 3 次方向 1 被测运行。API metadata 覆盖 30/30 run，exec JSONL 覆盖
  24/30 run、8/10 任务；另外 6 次集中缺口不按零处理。
- C1 为 1/24 run 的弱代理，C2 为 2/24 run 的弱信号；C11 在当前样本未观察到，C7 因缺少类型化完成声明—验证
  关系而不可测。现有证据不足以回答哪个行为候选最值得处理，因此不选择行为优化。
- 第三轮整改关闭了 public `exec` 早期错误被误计为零的缺口；最终 Python 51/51、Rust 2/2 通过，独立验收 PASS，
  未发现新的功能性回归或冗余设施问题。

## 下一唯一方向内工作包：10 题 × 2 轮有界观测复测

- 使用同一冻结 10 题 canary，对 `mydev/` 被测对象执行两个完整 round，共 20 个 run；main
  `gpt-5.6-terra/medium`、Guardian `gpt-5.6-terra/low`，费用硬上限 20 USD。
- 不运行 Codex 对照、validation、holdout、E-A 或条件补题。真实 API、Docker 与费用必须另行授权，并在独立
  ExecPlan 中冻结新 binary、campaign 与预算身份。
- 唯一变量是为目标测量开启原生 trace 并执行 schema-v2 安全离线投影；不改变 prompt、输出、compact、重试、
  Guardian、调度或其他产品行为。预期只改善 C1/C2/C11 的覆盖和影响归因，不预先承诺性能收益；C7 继续不可测。
- 首个真实 API 请求或首份非空 API metadata、trace、结果工件（以先发生者为准）固定正式 slot 身份与 20-run
  分母。正式边界后的投影缺失、残缺、重复、来源不一致或 schema/body-free 失败均使整包无效并停止，不替换 slot、
  不加题补轮。正式边界前的 fixture、schema 接线或启动配置问题可窄修复验；资源门不可用则不进入正式 slot。
- 20/20 个预定 run 都形成唯一、完整、严格可校验的投影，才是有效测量。failed/cancelled inference 缺 usage 时保留
  类型化终态并把 usage 标为不可测；completed response 缺 usage 仍拒绝。观测 opt-in 引入新 infra 失败时关闭 opt-in，
  保留默认产品行为并回到设施修复。
- C1/C2 只有在两轮均出现、跨至少 2 个任务，并有充分覆盖证明真实 omission/truncation 或重复调用耗时负担时才可
  入选；C11 出现影响任务的类型化 request/context 失败时可按严重性入选。多项满足时按任务覆盖、失败/耗时影响、
  行为风险依次只选一个；无人满足则明确保留“无候选”。在此之前 C1—C13 均不进入行为实现。

## 持续实验原则

- 一次只验证一个主要变量；没有发生率和影响证据的候选不直接进入实现。
- 先建立正确性回归，再选择与改动性质相称的测评；无收益和负收益结果同样保留。
- 不为得到正向结果事后更换样本、指标、分母或停止条件。
- 每个行为优化单独建立 ExecPlan，明确成功指标、停止条件和回滚条件。
- `reference-agent-harness/` 只读；只学习机制并自主实现，不复制许可证边界不清的源码。
- 不把方向 1 夹带成方向 3 的调度、协作或 Publication Critic 语义改造。
