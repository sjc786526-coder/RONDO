# Plan 049 阶段 B 最终验收

日期：2026-08-21
受审提交：`267825f61e7f7bb48dd2bcad67ca6f7a5de9faa1`

## 结论

- **验收通过**：阶段 B 的恢复、结算、Root/Guardian 归约、激活判定和停止行为正确，未发现 correctness blocker。
- **任务目标失败**：Plan 049 按冻结合同完成并得到可信阴性结果，但六槽均未发生 Root 主动委派，因而没有实现原始的
  “委派后收益对比”目标。它不是设施失败，也不允许通过换题、追加样本或强制 spawn 改写结果。

## 核心证据

- recovery 与 formal prefix 均可只读验证；旧 `plan-049-paid-v1` 仍锁存原则性停止。新 identity 只承接旧首槽 a01，
  没有 a02—a05 或 formal run。
- 正式账本为 6 runs、100 个全局唯一请求，全部 `settled/usage_priced` 且 upstream attempt 为 1；无 reservation、
  infra taint 或 stopped run。Decimal 结算为 `2.533684 USD`，基础上限剩余 `97.466316 USD`。
- 六槽均为有效 attempt 1、`trace_status=available`：2 `completed`、4 `task_failed`。六份 Team View 与现场唯一
  Exec Root 归约一致；首槽独立 Guardian 没有进入 agent、interaction 或 spawn 指标。
- 六槽 Root spawn attempt/accept 均为 0，`activation_observed=false`；正式阶段要求六个有效 pilot 且至少一个
  Root-owned successful spawn，实际没有 formal record，停止符合冻结合同。
- 两侧继续使用相同 Terra/medium、共同 V2 工具、policy、并发、任务和 trace 条件，只保留预定 Team State 差异。
- 独立运行 `tests.test_proactive_eval tests.test_team_lens`：61/61，OK（15.343s）；另有两名只读审查者分别复核
  账本/恢复与公平性/Root 指标，均为 PASS。未重复 144 项未受影响共享回归。
- `git diff --check` 对阶段 B 范围及完整 049 范围均通过；本轮未调用 API、Docker、Cargo、本地模型、CI 或 PR。

## 审查中处理的遗漏

`doc/WBS/multi-agent-trusted-evidence.md` 仍有一句过期文本称“下一包是 C”，与文件头、C 的完成段和顶层 WBS
矛盾。本轮仅把它更新为 A/B/C 均完成、Multi 当前无已排期下一包；不改变产品、测评合同或历史结论。
后续文档交叉复查另将 Plan 开头“阶段 A 当前已授权”的状态改为已完成，并把本次修改过的 Multi 子 WBS 更新日期
同步为 2026-08-21。Plan 当前状态中的历史审查节点继续保留其形成时的“阶段 B 未授权”等事实，不改写历史。

## 替用户作出的决策

1. 接受 Plan 049 的阶段 A/B 实现和真实阴性结果；不再使用剩余预算追加 pilot，也不运行冻结正式十题。
2. 不把“未激活”写成 Team State 无收益；当前只能断言该模型、medium effort、共同 policy 与固定三题未触发主动委派。
3. 不另开“采到激活为止”的 Multi 重试包。若未来研究不同模型、effort 或 policy，应作为全新问题预注册，不能续接
   Plan 049 或复用其结论身份。
4. 下一任务选择 **Plan 050：Codex 上游基线升级与双产品同步**，先于首次 v7 canary。Local 目前仍挂起，现在为旧
   `v0.147.0` 花费 API 预算建立 v7 基线很可能很快失效；升级后再在同一新基线上冻结 v7 更合理。
5. Plan 050 只有在 Plan 049 经用户批准合并、推送并收口工作树后才能创建；本轮没有该 Git 交付授权。

## 下一任务给执行者的指令

> 任务编号：Plan 050。任务名：Codex 上游基线升级与双产品同步。建议工作树：
> `.claude/worktrees/050-upstream-baseline-upgrade`。
>
> 先阅读根、`mydev/`、`multidev/` 的 `AGENTS.md`，以及 README、当前 WBS、两侧 baseline machine facts、
> `plan/plan-example.md` 和最近相关升级历史。确认 Plan 049 已经用户批准合入并推送到干净 `main` 后，再从该 main
> 创建 050 专用工作树；若 049 尚未合入，停止创建并只报告前置条件。
>
> 按模板制定 `plan/050-upstream-baseline-upgrade-execplan.md`。任务启动时从 OpenAI 官方只读来源选择并冻结当时采用的
> 稳定 Codex tag、peeled 40 位 commit 与必要来源身份；不要在提示词中预写未经现场核验的目标版本。随后将 `mydev/`
> 与 `multidev/` 同步到同一上游基线，保留两套产品既有差异、默认关闭语义、安全边界和产品身份。具体迁移拆分、
> 冲突处理与实现路线由你自主选择，以最小完整实现为准。
>
> 用户把本提示词交给你，即授权：查询和下载官方 Codex 源码、下载普通项目依赖；在 common root 直接刷新 git-ignored、
> 只读用途的 `codex-source-code/`；编辑两套产品、直接相关的共享 eval 适配、机器事实、锁/生成文件、必要测试、Plan、
> WBS 和精炼日志；使用现有工具更新 snapshot/schema/lock；通过共享 build-lock/watchdog 串行运行必要 Rust 编译与定向
> 测试；自主修复普通冲突、编译、fixture、snapshot 与定向测试问题并重跑。`codex-source-code/` 不得作为开发目录，
> 其 ignored 变化必须单独汇报。
>
> 本任务不授权真实 provider/API、Docker、本地模型加载、训练、v7 canary、发布、上传或修改其他远端资源。不顺手做
> Local 性能优化、改变 Multi 产品原则语义、重跑 Plan 049，也不建立升级机器人、复杂审计或可信体系。只有目标官方
> 身份无法权威确认、升级必须改变原则性产品语义、资源门无法成立或需要越过上述外部边界时暂停；普通窄问题自行修复。
>
> 验收保持轻量：两侧 baseline facts 指向同一官方 tag/commit 且 verifier 通过；共享资源门下完成必要编译；Local 的
> P0/Guardian/config/evidence 与 Multi 的默认关闭、Team State、原生 trace/Team Lens 受影响面通过定向回归；生成物与
> 锁文件由现有工具产生并经 diff 审查。不要默认跑两个全 workspace，只有上游变化面确实过广时才据风险增补。
>
> 完成后只提交 050 本地分支并保持工作树干净。不得合并、推送、关闭或重命名工作树/分支，等待用户批准。

## 最终状态

- Plan 049：执行合同完成，结果为 `completed / activation_not_observed`。
- 验收状态：**通过**。
- 目标状态：**失败**（未发生主动委派，无法比较委派后收益）。
- 阶段 B 不再续跑；Plan 050 尚未创建或启动。
