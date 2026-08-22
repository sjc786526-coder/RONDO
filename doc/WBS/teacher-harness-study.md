# 方向 1：教师 harness 研究与优化实验

最后更新：2026-08-22 ｜ 状态：**Plan 052 已完成；下一唯一包为 10 题 × 2 轮 Local 有界观测复测** ｜ 产品线：RONDO Local ｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 定位与状态

**方向 1 已由 Plan 052 正式重启，只针对 RONDO Local。** 默认关闭的原生 trace opt-in、任务级安全离线投影、
历史普查器与日期冻结证据已经落地；Plan 052 没有实施 C1—C13 行为优化，也不涉及 RONDO Multi。

教师 harness 的只读研究 T1—T3 已完成，结论基本不受本轮路线调整影响。四套参考实现的主题比较、与冻结 Codex
的差异矩阵、13 个候选机制及证据等级已收敛到 `doc/research/teacher-harness-performance-candidates.md`。
该报告是研究证据和候选池，本页是候选何时进入实现、如何排序和验收的唯一规划来源。

方向 1 不受旧 M2 解锁门约束；v22 仍不满足公平能力归因条件，不能据其三项 A/B 差异直接选定优化项。
E-A 轻量离线冻结回放当前不恢复（见 `doc/WBS/eval-benchmark.md`）；Plan 052 的结论是现有资产、原生事实投影与一次
有界真实复测足以承接下一步，未来只有已选定机制确需低成本反复实验时才重新评估最小 replay 能力。

## 已完成研究

- T1：按上下文、工具、子智能体、计划自纠错、停止条件、提示组织与权限边界通读教师源码。
- T2：形成冻结 Codex `v0.147.0` 的对照矩阵，区分设计差异、可观测缺口与待验证假设。
- T3：形成 C1—C13 候选，记录机制、证据、风险、测评轨、规模和否证条件。
- 边界：只学习机制，不复制许可证边界不清的源码；研究结果不等于收益承诺。

## Plan 052 结论

任务合同见 `plan/052-direction1-local-harness-bottleneck-census-execplan.md`，冻结证据见
`doc/audit-snapshots/2026-08-22-rondo-local-harness-bottleneck-census.md`：

1. 复用既有 rollout trace 与 API metadata；只对目标 Local 测量请求显式开启 trace，结果发布前生成固定名称的
   schema-v2 body-free 投影。v2 对 main/Guardian failed/cancelled partial usage 做分角色核对，分别记录 model-visible 与
   code-mode-runtime render 的 measured/partial/unmeasurable 覆盖、精确重复调用 lifecycle 时长及真实 turn 时长。
   原始 trace 不进入归档；缺失、残缺、重复、schema 漂移或两来源不一致均拒绝发布。
   重复的 `codex-exec` collector 已删除，产品默认路径和行为不变。
2. v28 Local cohort 为 10 个任务 × 3 次运行；API metadata 覆盖 30/30 run、10/10 任务，exec JSONL 覆盖
   24/30 run、8/10 任务，另 6 次为集中在 2 个任务的既有敏感脱敏，不按 0 处理。
3. C1 为 1/24 run 的 raw-output 阈值弱代理；C2 为 2/24 run 的精确重复弱信号；C11 在 311/311 完整终态请求中
   当前样本未观察到；C7 因没有类型化完成声明—验证关系而不可测。C4 只显示 cache reuse，C5 不可测。
4. 当前实际样本中 C2 比 C1 更常见，但没有候选达到“已观察且影响明显”，因此不能判断哪个“最值得处理”，
   不选行为优化；E-A 当前不恢复。

## 当前唯一工作包：10 题 × 2 轮 Local 有界观测复测

- 同一冻结 10 题 canary，只运行 RONDO Local 两个完整 round，共 20 个任务运行；main
  `gpt-5.6-terra/medium`、Guardian `gpt-5.6-terra/low`，硬预算 20 USD。
- 不运行 Codex、validation、holdout、E-A 或条件补题。真实 API/Docker 必须另行授权并在独立 ExecPlan 中冻结
  新 Local bundle、campaign 与预算身份。
- 唯一变量是给目标 Local 测量开启原生 trace 并执行安全离线投影；预期只改善 C1/C2/C11 的覆盖与影响归因，
  不预先承诺产品性能收益，C7 仍保持不可测。
- 第一轮任一投影缺失、trace 完整性非零、trace/API 交叉核对不一致、schema/body-free 或资源门失败即停止；
  任一新预留会达到 20 USD 即停止；两轮后
  无条件停止，不加题、补轮或改分母。
- 20/20 个预定 run 全部得到唯一完整投影才是有效测量；任一缺口使整包无效。failed/cancelled inference 缺 usage
  时保留类型化 C11 终态并把 usage 标为不可测，不把它误作残缺或 0；completed response 缺 usage 仍拒绝。观测引入新
  infra 失败时关闭 opt-in 并回到设施修复。C1/C2 须两轮均出现、跨至少 2 个任务且有相应表面已覆盖的
  omission/truncation，或精确重复调用 lifecycle 时长负担；partial/unmeasurable render 覆盖不按 0 解释；
  C11 出现影响任务的类型化 request/context 失败时可按严重性入选。多项满足时按任务覆盖、失败/耗时影响、行为
  风险依次只选一个；无人满足则明确保留无优化结论。在此之前 C1—C13 均不进入行为实现。

## 首轮候选参考

以下顺序是研究形成时的先验参考，不是当前复测必须选 C1 的排序。最终决策综合真实发生率、影响范围、预期收益、
实现成本和行为风险；每次只立一个 plan：

1. **C1 可恢复的聚合工具输出预算**：先验证超限、截断与恢复提示是否真实发生，优先走离线回放。
2. **C11 完整请求上限预检与分因单次恢复**：只在已出现 request-size 失败时进入。
3. **C7 确定性完成证据检查**：先记录缺失证据的频率，再决定是否注入一次提醒。
4. **C2 停滞观测与单次纠偏**：需要可重复的停滞轨迹，属于行为改变型，必须跑真实 canary。
5. **C4/C5 纯观测项**：用于 prompt/cache 与并发可见性归因，不单独宣称提高成功率。

C3、C6、C8、C9、C10、C12、C13 继续留在候选池；只有前序证据指向相应瓶颈时再提升优先级。

上述顺序中提到的“离线回放”指当前不恢复的 E-A。只有未来已经选定的机制确需反复低成本实验时，才重新评估
必要的最小 replay 能力。

## 单项实验合同

每个优化项必须：

- 单独建立 `plan/`，只包含该项任务内实现与验收；跨项顺序只维护在本页。
- 明确类型：行为保持、行为改变或 bug 修复，并选择 E-A、E-B 或正确性测试。
- 先记录前置机制指标，再实现一个最小变量；不得把多个候选打包后只看总分。
- 保留无收益或负收益结果；不为凑正向结果更换样本、口径或停止条件。
- 触碰 reference-agent-harness 时只读，采用自主重写，不复制源码。

## 暂不进入实现

当前有界复测完成前所有 C1—C13 均不进入行为实现；以下方向继续不排期：

- 团队拓扑、自由讨论式多智能体、动态 task router 或复杂调度器。
- 大规模 prompt 重写、完整会话系统、第二套工具协议。
- 未出现真实瓶颈前的资源键并行、按关键度重试或广泛参数归一化。
- 仅凭外部论文或教师实现存在就推断 RONDO 必然获益。

方向 3 的 RONDO Multi 产品线另见 `doc/WBS/multi-agent-trusted-evidence.md`；两者是不同产品源码，
不互相夹带实现。
