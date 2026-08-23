# Plan 058 formal-v2 projector fault

从 clean source `c89013bb0119d658ac01c485acfcf3af1b1b5610` 重建并复验 legacy、companion、bwrap 与
runtime manifest 后，`plan058-direction1-c2-formal-v2` 按冻结顺序完成十题零 API preflight `10/10`。首个付费
canary（绝对槽 8）完整执行 agent、Harbor、verifier、预算与清理，verifier reward 为 `1`；但 schema-v2 projector
遇到无 native runtime 的 `write_stdin failed: Unknown process id 9` 后 fail-closed。该槽同一 trace 还包含一个真实
Guardian 拒绝的 `exec_command`，同样在命令 runtime 创建前终止。两者都是既有 projector 未覆盖的真实、类型化
工具终态，不是模型/parity、transport 或上游故障，也不能篡改成命令已执行。

formal-v2 因本地投影设施故障永久作废并 body-free 发布，未产生正式逻辑结果。错误路径中的
`paid_requests_sent=0` 只表示没有逻辑结果发布，并不表示没有发出 API；私有 metadata 与总账确认实际结算 20 个
可靠 attempts（18 main、2 Guardian）、`0.818354 USD`。Plan 058 累计费用为 `7.351781 USD`、reserved `0`，
剩余 `42.648219 USD`。Docker/VHDX 增长均为 `0`，Windows C: 实际余量从 `201869733888` 降至
`201807400960` bytes；私有 campaign、原生 trace、预算与作废终态均保留。

projector 窄修只新增两类严格入口：调用参数中 session id 与错误中 process id 精确一致的 missing-process
`write_stdin`，以及固定 Guardian 安全拒绝合同的 pre-runtime `exec_command`。两类都保留真实 failed 生命周期、
零输出、无 exit code；missing-process 不补造 command/cwd，也不参与 exact-repeat identity；Guardian 安全拒绝不
冒充本地 Guardian logical-limit，后者原有 409 inference 豁免仍独立。其他 missing-runtime 或畸形结果继续
fail-closed。

修复后真实 formal-v2 trace 可完整、body-free 投影为 20 responses（18 main、2 Guardian）、17 tools、13 command
tools、1 次 exact repeat、1 次 repeated-after-failure、`162140` command output bytes。相关定向回归
`368/368`、Python compile 与 `git diff --check` 通过。按用户冻结的局部 commissioning 合同，下一步只以全新
diagnostic identity 复验受影响的绝对槽 8；成功后重新冻结并用全新 formal identity 完整运行 20/20，formal-v2
任何结果均不拼入正式分母。

## diagnostic-v3 finalize fault

`plan058-direction1-c2-diagnostic-v3` 只冻结绝对槽 8，零 API preflight `1/1`，付费链路在 attempt 1 完成 agent、
Harbor、verifier、projector、预算和 record 发布。该 task reward `1`/pass，但 agent 在真实 Guardian 安全拒绝后非零
退出，故结果合同为 `agent_failed` 且保留有效 verifier reward；17 个可靠 attempts（14 main、3 Guardian）、
`0.554663 USD`，无 transport retry。projector 修复本身已生效：raw exact repeat 为 `0`，工具真值完整保留。

finalize 随后误用通用 Plan 056 source revalidator，而不是 record 写入/恢复已经使用的 Plan 058 专用 revalidator；前者
未启用 `preserve_agent_failure_verifier_reward`，因此把同一 Terminal-Bench result 错误重投影并报
`Terminal-Bench projection drifted`。campaign 按本地发布设施故障作废为
`published_slot_source_integrity_failed`，不得用其 task 结果或 refined 分类；费用、record、trace 和 invalid 公共结果
均保留。累计 Plan 058 费用为 `7.906444 USD`、reserved `0`，Docker/VHDX 增长 `0`，Windows C: 最终实际余量
`202379096064` bytes。

修复只把 finalize 对每个 record 的验证切回既有 `_revalidate_plan058_record_sources`，不改变 agent-failure、Guardian、
reward 或通用 Plan 056 语义；新增回归确保 finalize 不再调用通用入口。相关测试 `149/149` 通过，且 diagnostic-v3
真实私有 record 可由专用入口只读重验证。v3 已永久作废，下一 identity 仍只复验槽 8。
