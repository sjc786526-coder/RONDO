# Plan 052 独立验收审查

## 审查对象与结论

- 对象：`worktree-052-direction1-bottleneck-census@a20d423eb90980451b78ecd5df1333fd0fe6d778`
- 基线：`main@607cba09567cd2065cb04b6191ab6471fe1e17aa`
- 结论：**验收不通过；当前提交的任务目标失败。** v28 历史普查结论有资产支持，eval 侧严格 body-free schema、比较器和离线聚合方向也合理；但正式复测所需的观测链路没有闭合，且当前在线 Rust collector 大量重复既有 rollout-trace 能力，不应继续接线和长期维护。

## Findings

### F1（阻断）：正式复测既没有可用的结果接线，又选择了重复的在线聚合来源

当前 `codex exec --json --rondo-local-observation` collector 聚合请求/token、命令/MCP、耗时、重复命令、输出字节、turn 和 compact 等事实；这些事实大部分已经由原生 rollout-trace 的 inference、tool runtime、turn/compaction 记录提供。普通 durable rollout 确实会过滤精确 `RawResponseCompleted`、Guardian 和 exec begin/end，但 `CODEX_ROLLOUT_TRACE_ROOT` 启用的 rollout-trace 才是本任务下一轮采样应复用的原始事实源。当前 collector 额外提供的 Guardian 摘要和 app-server lag 也不能证明底层所有事实完整：`RawResponseCompleted` 与 Guardian 通知仍可能在 best-effort 层丢失，因此 `event_stream_complete=true` 的语义过强。

与此同时，这套 collector 尚未进入真实 Local 测评链路：

- `eval/rondo_eval/terminal_bench/adapters.py:772` 的 Local 命令没有启用该 flag；
- `eval/rondo_eval/terminal_bench/adapters.py:548` 和 `runner.py:118` 已经提供可选 `CODEX_ROLLOUT_TRACE_ROOT` 接线，说明无需再造第二个在线事实源；
- `eval/rondo_eval/terminal_bench/results.py:920` 只处理有限的单文件私有证据，没有从 rollout-trace/API metadata 生成并归档稳定的安全任务级投影；
- 新增 observation validator/comparator 目前只被测试调用，下一工作包无法通过现有入口稳定取得、验证和比较完整的任务级结果。

因此，若按当前 WBS 直接进行 10 题 × 2 轮复测，要么不会生成 observation，要么需要继续固化重复 collector，均不满足 Plan 052 的轻量观测目标。

修复要求只约束结果，不限定具体实现路线：

1. 最终实现不再保留和维护重复的 `--rondo-local-observation`、Rust collector 及其专用事件消费接线；在离线投影达到所需字段后删除这些产品侧代码和相应测试。
2. 保留或按来源语义精炼 eval 侧 body-free schema、校验、聚合和比较；使用现有 rollout-trace 与 API metadata 作为下一轮的原始事实源，产出一个稳定、可比较、不会包含 prompt、命令正文、工具输出或私有正文的任务级结果。
3. 复用现有 Terminal-Bench `rollout_trace_root` 和已有 trace reader/reducer 能力，避免另建通用遥测、可信或审计平台。只有 Guardian 关联、截断边界或最小完整性状态确属本轮决策必需且现有 trace 无法表达时，才补少量原生 trace 字段；也可以把非必要缺口诚实标为 `unmeasurable`。
4. 下一轮入口必须在不运行真实 API/Docker 的窄测试中证明：仅目标 RONDO Local 测量启用 trace，原始私有 trace 不进入受跟踪结果，安全投影能够被唯一定位、严格验证和比较；缺失、重复、残缺或额外字段按合同失败。

### F2（阻断）：残缺历史工件会被计成“测得的零”

`eval/rondo_eval/harness_census.py:169` 接受 `requests: []` 并返回全零 `ApiStats`；`harness_census.py:220` 接受只有 `thread.started` 等非终态事件的非空 JSONL 并返回全零 `ExecStats`。随后 `harness_census.py:473` 和 `:502` 会把它们计入 measured 分母。这会把“工件残缺/不可测”错误归类为 C1/C2/C11 的 `not_observed`。

最低修复要求：API metadata 至少有一个请求；exec JSONL 至少具有一个基本一致的生命周期和恰好一个终态（completed 或 failed，不能缺失、重复或同时出现）。不满足时沿用现有 `missing.invalid` 路径并从 measured 分母排除。增加空请求、非终态/重复终态的窄回归测试即可，不需要复杂可信链。

这项问题不推翻当前 v28 数字：本次复验看到 30 份 API metadata 共 311 个请求，24 份已计量 exec 均有终态，当前 C1/C2/C11 普查结论仍有支持；修复后应保持冻结 census 字节一致。

### F3（低）：任务状态文档在架构收缩后不再准确

Plan 当前状态仍写“任务分支待提交”，验收清单未按实际完成项收口；WBS 又已把 Plan 052 和在线 `task.observation` 路线写成完成。完成 F1/F2 后，应同步精炼 Plan、顶层 WBS、方向 1 子 WBS、完成记录和执行日志：历史 v28 结论保留，正式采样来源改为 rollout-trace/API metadata 的安全离线投影，且不要在多份文档堆叠修复过程。

## 已验证内容

- 默认关闭路径、body-free 字段设计和历史资产读取边界未发现产品行为或私有正文泄漏问题。
- 定向 Python 门禁 47/47 通过。
- `just eval-plan052-census` 在设置可写 `XDG_RUNTIME_DIR=/tmp` 后重跑成功，输出与受跟踪 v28 census 逐字节一致；首次失败仅因审查 sandbox 下 `/run/user/1000/just` 不可写，不是代码失败。
- `git diff --check c7e9429..a20d423` 通过。
- 未重跑执行者已通过共享锁完成的 138 项 Rust Nextest；未运行 Docker、真实 API、本地模型、全 workspace、CI 或 PR。

## 代用户作出的决策

1. **暂不授权 10 题 × 2 轮、20 USD 的真实复测。** 先完成上述最小收缩与结果接线，再单独立运行 ExecPlan 和申请 API/Docker 授权。
2. **E-A 继续不恢复。** 复用现有 rollout-trace 不等于恢复 A1—A7，也不扩建第二套 telemetry。
3. **保留原定唯一后续包及其规模、模型、预算上限。** 但停止条件应从在线 collector 的 `task.observation` 改为“安全离线投影缺失、残缺或 schema 校验失败即停止”。
4. **不接受继续扩充在线 collector。** 执行者可自主选择更简洁的复用/投影路线，只需满足安全聚合、可比较、可复现和最小行为影响。
5. 主工作区目前存在来源不明的 `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md` 修改；本轮不得触碰、覆盖或据此合并。修复只在 Plan 052 工作树提交，合并和推送仍待用户批准。

## 复验条件

- F1、F2 已修复，F3 同步完成；
- 相关 Python/窄 Rust 测试通过，冻结 v28 census 保持一致；
- 工作树只包含范围内改动并已自觉提交，未合并、未推送；
- 执行摘要明确列出删除的重复代码、最终原始事实源、仍不可测字段和未运行项。
