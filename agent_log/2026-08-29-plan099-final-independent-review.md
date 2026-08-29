# Plan 099 最终独立验收

## 结论

`REQUEST_CHANGES`。本轮基于执行者最终提交
`7c7a14bb34960414d5087098d87b085f0be8eba0`审查，确认唯一冻结方案已完成 commissioning 与 clean formal，
正式轨迹是有效的 `VALID_FORMAL_NO_GO`；step 8 fresh-process 恢复、小型回传证据、费用结算和 0 Pod /
compute `$0/h` 收口均可接受。没有理由重跑训练、重建 Pod 或扩大验证。

但最终 tracked 状态存在 **1 High / 2 Medium** 文档与授权边界问题，因此当前提交不能通过最终验收。
整改只需要精确收口 WBS、ExecPlan 和执行日志，不需要 GPU、真实模型、训练、资产上下传或重型测试。

## Findings

### High — 有效 `NO-GO` 终态后仍保留无固定 Pod 次数的继续付费入口

- 阶段 A 最终授权明确限制同时最多一个、累计最多两个 Pod，第二个只用于首 Pod 确认不存在后的同路线
  技术恢复；有效质量不足必须冻结 `NO-GO`。本轮两个 Pod 均已使用并删除，formal 又已被认定为有效质量失败。
- `doc/WBS.md`、Plan 099 ExecPlan 的硬约束/阻塞项/决策 017，以及阶段 B 执行日志却声称后续同路线恢复不设
  固定 Pod 次数。这会让已终止的 Plan 099 在无新任务、无新授权时继续产生付费外部状态，也与“有效质量失败不得重跑追结果”
  的任务合同直接冲突。
- 执行者记录的 evidence-first 立即释放可作为已发生的安全降费事实保留；它不能在有效 `NO-GO` 后继续授予新 Pod。

必须改为：Plan 099 付费执行已关闭，不得再建 Pod、恢复训练、调参或追求正向结果。网络卷按用户决定继续保留；任何后续 GPU、
恢复、新路线、资格测试或卷变更都必须另立任务并重新授权。本 finding 不要求回退已完成的 Pod 释放，也不允许为整改重建
Pod。

### Medium — ExecPlan 同时保留两套相反的资源收口规则

- ExecPlan 当前硬约束与决策 016/017 写为证据回传后立即释放、可按实时预算重新抢卡。
- 同一 ExecPlan 保留的执行提示词仍要求先走 queue 预释放审查，正常释放只能由 reviewer 批准，absolute trigger
  才是唯一例外。

本轮不需要争辩哪一套还能指导已结束的执行；应当统一改为历史事实与终态边界：证据完成后已立即释放两个 Pod，当前 0
compute，Plan 099 不再赋予任何新付费动作。若保留旧启动提示词作为历史合同，需明确其已完成/失效，不得与当前可执行指令并列。

### Medium — 方向 3 权威子 WBS 仍停在阶段 A，与根 WBS 终态冲突

`doc/WBS/multi-agent-trusted-evidence.md` 仍把 Plan 099 写为“阶段 A 已提交待验收 / 阶段 B 锁定”，并把“工作包三冻结
候选后解锁工作包四”仍写成当前串行路线。根 WBS 与实际执行已是 `VALID_FORMAL_NO_GO`、无候选、工作包四不解锁，两个权威
规划源不能同时保留相反状态。

窄同步子 WBS 的当前路线、串并行与外部授权段即可：Plan 099 有效训练 `NO-GO`、无候选、工作包四未解锁，Plan 099
外部动作授权关闭；后续改变路线或处置网络卷须新任务/新授权。不要在该子 WBS 复制训练日志。

## 已接受的实施与证据

- `formal-result.json` 标记 formal 有效轨迹、`NO-GO`、无 best checkpoint、development-only 且不声称 qualification。
  五个冻结评价点在本地 tail 中均有唯一 checkpoint hash、finite loss 和
  `decision_config_unavailable:QualificationError`；这与预冻结的 fail-closed `NO-GO` 语义一致。
- step 8 checkpoint hash 与 recovery receipt 相同；不同 process nonce、评价 hash 和 `reproduced=true` 闭合中程 fresh-process 恢复。
- exact model repository/revision、12 文件清单和权重 SHA-256 与冻结主方案相符；无 candidate 目录符合 `NO-GO` 分支。
- 两份 terminal receipt 均表明对应 Pod 已删除、`pod_count=0`、compute `$0/h`。第二 Pod 与首 Pod 保守累计时间低于
  10,800 秒；现有卷 `mwemzrn33y` 为 US-TX-3 / 100GB 并按用户决定保留。
- 费用账目可闭合：`3.4531142827 - 2.018521311 + 0.1 = 1.5345929717`；余额高于六小时卷费 `$0.06`。
- source/data receipts 绑定正式运行源码提交 `36f39439d0384792791532fb06d180890ef93545`，data receipt 明确
  `test_body_files=0` 与 `qualification_body_files=0`。本地只保留预冻结 `NO-GO` 分支允许的小型证据，大型
  step 8/16 checkpoint 留在现有卷。
- 审查者独立复跑 Plan 099 focused 为 `16 passed in 3.08s`，`validate-freeze` 为 `verified`，freeze SHA-256 为
  `8a19618210a37970ec0d8b127c35753c56b40f77f754a992b18f9ed3fc6c4e0f`；`git diff --check` 通过。

本审查未运行真实模型、GPU/RunPod、Docker、Cargo、付费 API 或重型测试，未读取 v9 test、qualification sealed
或旧 unseen 正文，未修改或删除任何 ignored 资产。

## 审查者代用户决定与整改边界

1. 接受两个 Pod 的实际释放与当前 0 compute 结果，确认不再需要 Pod；不要为验收、文档整改或重看 `NO-GO` 重建
   compute。
2. 接受 `VALID_FORMAL_NO_GO` 为本次唯一主方案的有效正式结果；不许沿 Plan 099 重跑、换模型/loss/数据/scope/门限或开第二
   路线。工作包四保持锁定。
3. 本轮整改仅修改 tracked 文档与增补精炼整改日志；运行 `git diff --check` 和必要的文档/冻结校验即可，不重跑 Plan 099
   focused、不重新打包、不动 ignored 资产。
4. 网络卷 `mwemzrn33y` 与 Plan 099 大型资产继续按用户当前决定保留，本验收不授权删卷、缩容、上传、下载或其他外部变更。
5. 整改完成后只提交现有 099 工作树，不合并、不推送、不归档/重命名分支、不删除 worktree；再按指定 queue 申请纯文档复验。

## 当前状态

`FINAL_REVIEW_REQUEST_CHANGES / VALID_FORMAL_NO_GO_ACCEPTED / ZERO_POD / VOLUME_RETAINED / NO_FURTHER_COMPUTE`。

最终判定：**验收不通过 / 任务目标失败**。这里的“验收不通过”指当前 tracked 收口尚有授权与 WBS 正确性问题；“任务目标失败”指预期的合格候选未形成。
整改可使完整任务进入“验收通过 / 任务目标失败”的诚实终态，但不应把合法的质量 `NO-GO` 改写成目标完成。
