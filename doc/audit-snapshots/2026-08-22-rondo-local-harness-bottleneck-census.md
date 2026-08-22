# RONDO Local Harness 瓶颈普查快照

日期：2026-08-22
范围：Plan 052，只针对 RONDO Local
机器结果：`eval/results/baselines/rondo-local-harness-bottleneck-census-v1.json`

## 1. 口径与样本

普查器先校验 tracked `eval/results/runs.jsonl` 的全部 288 行，但该步不打开 private artifact；再按固定
身份选择 schema v7 campaign `p2-b7-canary-baseline-v28` 中 `track=tb`、`side=rondo`、
`product=rondo-local`、`outcome=completed` 的 attempt-1 基础槽。它同时核对 campaign lock、slot、round、run 与
单任务投影，最后只对选中的 30 个 Local 槽验证 private summary 和后续 ignored 工件；不从目录名、成绩或候选
结论反向选样。

最终 cohort 是 10 个冻结 canary 任务、每题 3 次观测，共 30 次 Local 运行。API metadata 在 30/30 次运行、
10/10 个任务上可读；exec JSONL 在 24/30 次运行、8/10 个任务上可读。其余 6 次均有既有
`sensitive_private_artifact_omitted` 占位，且集中在另外 2 个任务，因此属于任务级非随机缺失，不能按 0 处理。

分析只从 tracked artifact 引用定位主物理根的 ignored 资产。命令、工具输出和逐条身份只在进程内用于长度、
固定分类和精确重复判断；公共 JSON 与本快照不含正文、路径、逐运行 ID/hash 或临时 fingerprint。

## 2. 可测事实与覆盖

- 30 次运行共有 311 个已记录请求：main 300、Guardian 11；311/311 均为 HTTP 200、
  `response.completed/completed` 终态且 usage 有效。聚合 usage 为 input 8,006,983、cached input 6,009,953、
  cache-write input 0、output 130,469，cached/input 比例为 750,589 ppm。
- 24 份可读 exec JSONL 共有 700 个事件、24 个 completed turn、0 个 failed turn、0 个顶层 error。
  其中 214 个 command terminal item（156 completed、58 failed）、42 个 file-change、116 个 agent-message。
  command 失败是运行内工具终态，不等同于任务失败。
- command output 的 body-free 字节统计为中位数 241、最大 10,626。相对当前 10,000-byte 单工具模型投影策略，
  有 2 个 raw output、分布在 1/24 个可读 run 中越过阈值；历史 JSONL 不记录模型实际看到的替换结果或可恢复性，
  因此这里只是风险代理，不能声称已证明模型可见内容被截断。
- 精确相同 command 在 2/24 个可读 run 中各多出现 1 次；其中 1 次发生在同一 command 的失败之后。
  历史事件没有可靠的 request-round、compact 原因或“无进展”语义，无法把这些重复直接归因为停滞或性能损失。
- 历史 exec JSONL 没有类型化“完成声明—相关验证证据”关系，也没有完整 tool/approval timeline、record lag、
  model-visible truncation、compact 原因/token 或 Guardian token 归属。这些字段保持 unavailable，而不是 0。

## 3. 四态候选结论

| 候选 | 互斥终态 | 分母与发生率 | 结论边界 |
|---|---|---|---|
| C1 可恢复的聚合工具输出预算 | **已观察但影响较弱** | 24 个可读 run / 8 个任务；raw-output 阈值代理 1/24 run（41,667 ppm），2 次 | 只证明低频 raw-output 风险代理；模型可见截断、跨工具聚合影响和恢复需求仍不可测。 |
| C11 完整请求上限预检与分因单次恢复 | **当前样本未观察到** | 30 个 run / 10 个任务；311/311 请求完整终态，缺口 0 | 只适用于本 cohort；历史 metadata 不提供 request-size 失败的更细原因，不能写成全局不存在。 |
| C7 确定性完成证据检查 | **当前资产无法测量** | 0/30 run、0/10 任务具备类型化关系；发生率不适用 | 不用最终回答正文启发式猜测完成声明，也不把缺字段当 0。 |
| C2 停滞观测与单次纠偏 | **已观察但影响较弱** | 24 个可读 run / 8 个任务；2/24 run（83,333 ppm）有精确重复，1 次跟随失败 | 只证明低频重复；时间损失、compact/无进展与任务结果因果不可测。 |

C4 只提供归因辅助：当前样本有较高 cache reuse，但缺少 prompt 分层，不能把 cache 比例归因到某项设计。C5 的
工具/审批并发、等待与记录滞后在历史资产中不可测。两者均不单独包装成成功率优化。

## 4. 决策与下一包

当前没有“已观察且影响明显”的候选。C1/C2 都只有低频、覆盖不完整且缺少影响归因的弱信号；C11 是窄样本阴性，
C7 不可测。研究先验、教师实现数量和候选编号不足以替代发生率与影响证据，因此 Plan 052 不选首个行为优化项。

唯一后续工作包是一次**不在本任务运行**的 RONDO Local 有界观测复测：使用同一冻结 10 题 canary、2 个完整
Local round（20 个任务运行），main `gpt-5.6-terra/medium`、Guardian `gpt-5.6-terra/low`，费用硬上限
20 USD，不运行 Codex 对照、validation 或 holdout。开始前须另行批准真实 API 与 Docker；第一轮任一
`task.observation` 缺失、schema/body-free 校验失败或资源门失败即停止，不启动第二轮；任何预算预留会使累计达到
20 USD 时停止；两轮完成后无条件停止，不事后加题、补轮或改分母。该测量用新的 opt-in 聚合补齐未脱敏任务级覆盖，
再按发生率、耗时占比、预期收益、实现成本和行为风险决定是否只立 C1 或 C2，或保留无优化结论。

现有 v28、task-level schema、只读普查器和上述小规模真实复测足以承担下一步；当前不恢复 E-A，也不排 A1—A7
任一最小子集。只有未来已经选定的行为机制确需低成本反复实验时，才重新评估单独的最小 replay 能力。

## 5. 实现与限制

RONDO Local 新增 `codex exec --json --rondo-local-observation` 显式开关。关闭时不构造 collector，也不接收仅供
聚合的 raw-response/Guardian 通知；开启时只在 primary turn 结束追加一个 schema-v1 `task.observation`，字段为
固定计数、时长、token、有限状态与 unavailable flags。它不写额外文件、不发网络请求，也不改变 prompt、请求、
工具、compact、审批、重试、停止、调度或退出码。普通 `codex exec --json` 事件仍可能包含正文，不能把原始 JSONL
当作公共观测结果；只有 `task.observation` 与通过严格 allowlist 的普查输出可公开持久化。

本轮没有运行 Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI 或 PR。
主物理根的 30 个合格 run 目录只读；未创建 Plan 052 ignored 临时目录，未改写、移动或删除既有运行资产。

## 6. 后续验收整改附记（不改写首轮普查数字）

本页 §1—§5 是首轮实现形成时点的冻结记录；其中 v28 cohort、覆盖、C1/C2/C11/C7 四态结论与局限继续有效。
后续独立验收确认 §4 的 `task.observation` 停止条件和 §5 的专用 `codex-exec` collector 不应作为当前实现或规划：
重复 collector 已删除，最终链路改为只对目标 RONDO Local 测量显式启用既有 rollout trace，以 API metadata 交叉核对，
并在 Terminal-Bench 发布前生成固定名称的 schema-v1 body-free 任务投影；原始 trace 不归档，缺失、残缺、重复、
完整性终态非零、schema 或两来源不一致均失败关闭。当前唯一后续包及有效/无效/回滚判据以
`doc/WBS.md` 和 `doc/WBS/teacher-harness-study.md` 为准，整改证据见
`agent_log/2026-08-22-plan052-native-trace-remediation.md`。
