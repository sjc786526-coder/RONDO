# 方向 1：Harness 优化

最后更新：2026-08-23 ｜ 状态：**Plan 062 实现已提交、等待独立审查；Plan 058 历史结论保持冻结** ｜
源码位置：`mydev/` ｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 当前状态

方向 1 已完成 Plan 052 的观测设施、Plan 056 的候选复测和 Plan 058 的单变量 C2 行为优化。默认关闭的原生 trace
opt-in、任务级安全离线投影、历史普查器与日期冻结证据继续复用；Plan 058 只新增默认关闭、显式 opt-in 的
`exec_command` repeat guidance，不改变工具执行资格、Guardian、审批、sandbox 或方向 2/3。外部验收发现普通非 root
agent 会继承该 feature 后，最终分支已把 recipient 收紧到 root agent，并补 model-visible integration regression；
外部复验已通过并完成主线整合，feature 保持 UnderDevelopment、默认关闭。

Plan 062 已在专用 worktree 提交三项学习教师源码后筛选并自主实现的优化：history orphan normalization 收敛为
借用式索引与必要时单次删除，模型可见工具规格以不可变共享所有权跨 prompt 复用，unified-exec 快照直接形成连续
bytes 并在合法 UTF-8 denial 判定中借用视图。无真实 API 的轻量 benchmark 与直接语义等价回归一并提交；本包保持
`v0.147.0` 基线身份，不改变模型可见语义、工具资格、Guardian、审批或 sandbox，不恢复 E-A、正式
Terminal-Bench campaign 或开放式候选探索。当前状态是实现已提交，等待独立审查；未合并或推送。

此前教师 harness 的只读研究 T1—T3 已完成。研究交付
`doc/research/teacher-harness-performance-candidates.md` 保留为形成时点的证据与候选池；候选进入实现仍必须由
当前方向 1 的真实瓶颈和影响证据决定，不能根据教师实现或历史 v22 差异直接选择。

E-A 轻量离线冻结回放当前不恢复。Plan 052 已确认现有资产、原生事实投影和一次有界真实复测足以承接下一步；
只有未来已经选定的机制确需反复低成本实验时，才重新评估必要的最小 replay 能力。

## Plan 062 当前结果

- clean baseline `d5535fc` 与 clean candidate `22b8766` 使用同一 harness SHA-256
  `ef8364c8a225226fa1085355ae447f55b9a0aabb3fab6d2f8f264703c77fd5f2`、同一 Divan 0.1.21 workload；两侧
  `dirty=false`。tracked body-free 聚合见
  `eval/results/observations/plan062-direction1-teacher-hotpath-optimizations.json`，raw 留在 062 ignored namespace。
- history 8/32/128-turn case 的 allocation count 从 `11/37/135` 降至 `3/5/7`，allocated bytes 从
  `860/3650/14750` 降至 `524/2188/8748`；对应 median time 下降约 `37.2%/30.9%/40.5%`。
- 8/32/64 个工具规格重复共享 case 的 allocation count/bytes 均从 `1296/565200`、`5136/2261000`、
  `10256/4523000` 降至 `0/0`；4 KiB/256 KiB/1 MiB snapshot 的 allocation count 从 `3/3/4` 降至
  `1/1/1`，allocated bytes 从 `8240/524300/1572000` 降至 `4096/262100/1048000`。这些结果只解释命名的
  同步热路径，不外推 API 延迟、模型质量、任务成功率或通用 agent 能力。
- clean candidate 正式轮为 benchmark smoke、定向 48/48、release exact 1/1、parser 4/4、`codex-core`
  3332/3332（8 skipped、2 slow）和正式 benchmark 9/9；所有 Rust 命令均经共享 build lock/watchdog。

## Plan 058 结论

- Phase A 将 Plan 056 的 9 次 raw C2 occurrence 冻结为 harmful `1`、reasonable `8`、insufficient `0`；
  主要收益门为 harmful 降至 `0`，并要求合理重复、恢复/用户控制、工具可执行性与任务正确性四项无害门全部通过。
- 产品只在主 agent 的 `exec_command` tool spec 增加有界 guidance；feature 为 UnderDevelopment、默认关闭，
  Guardian 明确不接入。写入、网络或副作用未知调用仍执行，关闭态保持 Plan 056 行为。
- 最终 `formal-v6` 绑定同一 v28 十题、两个 round、Terra medium/low 与冻结顺序，完成可信 `20/20`：
  20 completed、8 pass/12 fail，225 upstream attempts、1 次同槽 pure transport retry，campaign
  `4.985650 USD`。Plan 058 全生命周期累计 `20.379152 USD`、reservation 0。
- 正式 raw C2 为 7 次/4 slot/3 task、9,693 ms；逐项按预冻规则分类为 harmful `0`、reasonable `7`、
  insufficient `0`，四项无害门通过。正式决策为保留该默认关闭 opt-in；不以 raw 数下降为由压制七次合理复测与恢复。
- 第一次独立验收后按预冻 `adjust` 边界进一步把最终 guidance 收窄到同 requester/tool path 且全部调用参数不变，
  并明确任何条件不确定即照常执行；后续外部验收又确认普通非 root agent 未被 gate 排除，最终分支已复用既有
  session-source 判定收紧为 root-only。formal-v6 公共结果仍如实绑定原冻结文案，不把收窄后的版本冒充为正式原样
  被测版本；同一外部审查者复验通过，没有重跑正式实验。
- Docker/VHDX 增长均为 0，最终无容器、volume 或 build cache；未运行 Codex 对照、validation、holdout、额外
  题目/round、完整数据集、本地模型、训练、CI 或 PR。详细合同、失效 campaign 与设施修复证据见 Plan 058 及日志。

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

## Plan 056 冻结输入

- `formal-v6` 使用同一冻结 10 题、两个完整 round、RONDO Local、main `gpt-5.6-terra/medium` 与 Guardian
  `gpt-5.6-terra/low` 完成可信 20/20；20 个 slot 均为 `completed`，8 pass/12 fail，来源、usage、投影与 Docker
  receipt 完整。
- formal-v6 为 219 attempts、`4.677962 USD`；Plan 056 连同所有历史 campaign 累计 483 attempts、
  `10.329028 USD`、reservation 0。首个可信 20/20 后已停止真实 API。
- C2 达到冻结门槛：9 次 occurrence，覆盖 6 个 slot/4 个任务，3 个失败 slot，两轮均出现，影响值 10108；C1/C11
  未达门槛，C7 仍不可测。结果只支持“选择 C2 作为下一候选”，不证明具体优化一定有收益。
- 当前可测 C2 只指同一 trace 内 requester、完整命令字符串与 cwd 均相同的重复 `exec_command`，影响值来自重复调用
  本身的工具耗时；不能把它直接外推成所有停滞循环、重复工具或无进展状态。
- Plan 058 已按该边界完成 C2 单独 ExecPlan、正确性/恢复规则、真实授权与正式决策；Plan 056 的历史 identity、
  trace、账本、终态和公共结果保持只读，不与 Plan 058 数据拼接。

## 持续实验原则

- 一次只验证一个主要变量；没有发生率和影响证据的候选不直接进入实现。
- 先建立正确性回归，再选择与改动性质相称的测评；无收益和负收益结果同样保留。
- 不为得到正向结果事后更换样本、指标、分母或停止条件。
- 每个行为优化单独建立 ExecPlan，明确成功指标、停止条件和回滚条件。
- `reference-agent-harness/` 只读；只学习机制并自主实现，不复制许可证边界不清的源码。
- 不把方向 1 夹带成方向 3 的调度、协作或 Publication Critic 语义改造。
