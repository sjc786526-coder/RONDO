# Plan 058 diagnostic sweep

## diagnostic-v1 invalid

`plan058-direction1-c2-diagnostic-v1` 冻结旧 formal 绝对槽位 `8..20`，零 API preflight `10/10` 一次通过。
绝对槽 8–17 共 10 条运行链均在 attempt 1 完成 agent、Terminal-Bench、verifier、Docker cleanup、预算与记录发布；
其中有效 task pass/fail 均保留，不重跑。

绝对槽 18 `sanitize-git-repo` 自然复现三次 Guardian 后第 4 次请求被本地
`guardian_logical_request_limit_exceeded` 拒绝。修复后的 adapter 如实记录 agent exit `1`、tee exit `0`，Harbor
以原生 `NonZeroAgentExitCodeError` 保存 agent failure 后继续 verifier，得到 reward `0`；API metadata 为 3 个已发送
Guardian 请求，私有 evidence 为 3 个终态决定加 1 个 `failed_closed/session_error`。随后 schema-v2 projector 因未识别
这个类型化、未执行命令的 failed tool call，报 `missing command runtime is not a pre-runtime denial`。这是本地投影
设施故障，不是任务失败、transport 或上游故障；v1 已作废并 body-free 发布，槽 19–20 未运行。

v1 结算 132 个可靠 upstream attempts、`3.110194 USD`；Plan 058 累计 `6.048443 USD`、reserved `0`。最终 Docker
占用 `11.5GB`、VHDX 增长 `0`，Windows C: 实际余量 `190684532736` bytes。修复 projector 并通过定向回归后，新
diagnostic identity 只从尚未打通的绝对槽 18 继续到 20，不重复已有完整证据且未受 projector 修改影响的 8–17。

projector 窄修后只接受 `exec_command`、`code_cell` requester、tool/ended 均 failed、无 native runtime、结果顶层严格
为 `{type,error}` 且错误同时包含 HTTP 409 与精确 Guardian limit code 的组合；投影保留失败生命周期和零输出，
`exit_code` 保持不存在，不声称命令执行。普通 missing-runtime/error 继续 fail-closed。相关 Python 定向测试
`171/171`、`py_compile`、`git diff --check` 通过；对 diagnostic-v1 槽 18 的私有 trace/API metadata 只读实测投影
通过，body-free 统计为 40 次 command、6 次 exact repeat、1 次 repeated-after-failure。修改后再次核验槽 8–17
十条已发布记录的绑定、投影与终态，全部通过且未改写私有工件。

## diagnostic-v2 complete

`plan058-direction1-c2-diagnostic-v2` 绑定 harness commit `0213ea3`，只冻结绝对槽 18–20；零 API preflight `3/3`
一次通过。三槽 paid run 均在 attempt 1 完成 agent、Terminal-Bench、verifier、schema-v2 投影、Docker cleanup、预算
与 record 发布，任务均 pass，raw/refined C2 都为 `0`，无害四项全通过，source validation `3/3`。槽 18 本次是
0 Guardian 的普通成功路径；typed Guardian-limit 异常路径由 v1 保留的真实 trace 在修复后完成只读 projector 验收，
未把 v1 结果拼入 v2。

v2 共 24 个可靠 upstream attempts、0 transport retry，费用 `0.484984 USD`；Plan 058 累计 `6.533427 USD`、
reserved `0`。Docker 前后均 `11.5GB`，容器/卷/build cache 为 0，VHDX 增长 `0`，Windows C: 最终实际余量
`190665900032` bytes。结合 v1 已完整且重新核验的绝对槽 8–17，commissioning sweep 的 8–20 共 13 个槽已全部
打通；下一步提交本批次、实现 formal 唯一顺序，再从 clean source 重建正式 runtime。

## 后续局部 commissioning 合同

首轮 8–20 全部完成后，若新 formal 再暴露本地设施故障，修复版 commissioning/diagnostic 只复验受影响或未打通
的题目/分支；不机械重跑其他已有完整证据且未受改动影响的题目。局部复验通过后重新冻结，但全新 formal 始终从
1/20 完整运行，不拼接或缩短正式分母。

下一 formal 的 identity 在创建前冻结 20 个唯一绝对槽位的执行顺序为
`8 → 18 → 1–7 → 9–17 → 19–20`。8 是最高风险 canary，18 次之；两者只是同一新 campaign 的前两个正式结果，
不是额外试跑。后续区间排除已执行的 18，因此总分母仍恰好 20，不重复、不复用旧结果。
