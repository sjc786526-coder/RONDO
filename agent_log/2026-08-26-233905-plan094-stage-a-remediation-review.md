# Plan 094 阶段 A 首轮整改复审

## 结论

`REQUEST_CHANGES`。上一轮三个 Medium 已闭合，但 5 USD 预算问题仍有 **1 High / 0 Medium**，阶段 A 暂不通过，付费门继续关闭。整改仍可保持为 Plan 094 专用薄能力，不需要运行真实云端、模型、Cargo 或 Docker，也不需要建设通用预算、云编排、审计或可信平台。

复审基于整改提交 `ad91c5cb550cf575ff2323109f440db54cf66fef`。独立复跑 Plan 094 focused unittest 为 `16/16` 通过，`git diff --check`、worktree/main tracked clean 状态通过；测试证明预算算术、snapshot freshness、历史角色/训练 claim 与 Hub 环境的局部逻辑，但没有证明实际 Pod 计费生命周期已被 hard-cap。

## 已闭合项

- Plan 090 `source_external` 历史点现在只保留 continuation previous/reassessment 语义，不进入 Plan 094 material、latest、best、training-best 或 turning；首个 Plan 094 自有 checkpoint 后角色正常建立。
- `real_training_run` 只在已有 Plan 094 自有、完整并已资格化的 pending checkpoint 或 evaluation overlay 时成立，单纯导入历史 update 不再误报。
- bootstrap 在任何 existing/download snapshot 分支前无条件清除三个不需要的 Hub token 变量，并把 Hub cache/telemetry 固定在 task root；没有读取或打印凭据。

## Remaining finding

### High — worker timeout 仍不等于计费 Pod 生命周期上限

`training/publication-critic-plan094/runpod-launch.sh:42-50` 会在后台 worker 前生成 rate-bound authorization，但 `:54-62` 只把 `timeout` 包在 Pod 内 worker 上，launcher 随即返回。worker 完成或超时后不会 stop/delete Pod；两个 launch 之间、执行会话中断后以及最后一个 worker 结束后的 Pod 空转仍继续计费，不受 `maximum_seconds` 或 authorization 约束。`runpod-bootstrap.sh:22-24` 同样只限制 bootstrap 进程，不限制 Pod。当前实现因此仍不能保证用户授权的 5 USD 硬上限，且与计划已经明确的“停止本地脚本不等于释放 Pod”事实一致。

此外，两处 timeout 均使用 `--kill-after=60s`，而 `authorize_paid_segment()` 只按 `maximum_seconds` 计算 segment cost；最坏额外 60 秒和实际 stop/delete/确认余量没有进入该上界。新增测试只验证纯预算算术以及 authorize 位于 `nohup` 之前，不能覆盖 worker 结束后的持续计费。

整改目标：为本任务创建后的计费 Pod 建立一个由 live 预算、实际聚合费率和 closure reserve 推导的绝对生命周期/止费兜底，在 deadline 到达时能从 Pod 外部 stop/delete 并确认，而不是只结束 Pod 内命令；把 kill grace、终止和短暂确认余量计入授权上界。可以复用现有 Plan 087 terminal helper，加一个很薄的 Plan 094 deadline 接缝，或采用执行者有证据支持的更简洁等强方案；不得把预算/删除职责塞进根 `create-runpod-when-ready.py`，也不要求通用 watchdog、账单平台或复杂 receipt 链。轻量 fake clock/client 测试足够，不运行真实云端。

## 审查决定与用户最新决定

- 本轮不要求再改历史角色、训练 claim、Hub 清理、模型、数据、Route O、material rubric、停止或 retention；修复范围只保留实际 Pod 生命周期硬上限及相称回归。
- 用户已经明确要求：后续即使阶段 A 技术验收通过，**也不得批准或进入付费阶段**。执行者在最终闭合阶段 A 时，应把 Plan/WBS 当前状态更新为“阶段 A 已完成、付费阶段由用户暂停”，继续保持 `PAID_GATE_CLOSED`，不得刷新/创建/修改任何云资源。
- 阶段 A 最终提交还需留一份精炼 `agent_log` 接手文档：先指引后续 agent 阅读 Plan，只补充 Plan 和既有日志没有、但恢复工作必需的事实，例如最新提交/审查链、用户暂停付费决定、worktree/main 与 ignored 资产边界、未来恢复前必须重新核对的动态状态；不要复述 Plan 或堆叠工具流水账。
- 所有变更继续只在现有 Plan 094 worktree 提交；不合并、不推送、不归档或删除 worktree。

## 状态

`验收不通过 / 阶段 A 任务目标失败（可整改） / PAID_GATE_CLOSED / PAID_STAGE_PAUSED_BY_USER`。Plan 094 总体研究任务未进入付费执行，也没有形成任何 material/no-improvement/INCONCLUSIVE 结果。
