# Plan 058 formal-v1 作废与 runner 修复

## commissioning 验收判断错误

commissioning-v1 已在 `sanitize-git-repo` 暴露第 4 次 Guardian logical request 被本地冻结上限拒绝后，agent
非零退出且 Harbor 跳过 verifier。commissioning-v2 改用 `openssl-selfsigned-cert`，只打通 7 次 main、0 次
Guardian 的普通成功链路。它证明了 agent → Terminal-Bench → verifier → 投影 → 结算 → 发布的普通路径，却没有
修复和复验 v1 已暴露的异常路径。把 v2 的 `1/1` 称为“彻底打通”是执行方的 commissioning 验收判断错误。

## formal-v1 作废

`plan058-direction1-c2-formal-v1` 完成冻结十题 preflight `10/10` 和前 7 个 paid logical slots。第 8 槽
`sanitize-git-repo` 再次在三次 Guardian 后触发
`guardian_logical_request_limit_exceeded`。该类型化 `409` 由本地预算代理产生，不是 transport、网络或临时上游
故障。adapter 把真实 agent exit `1` 转成通用 `AdapterError`，Harbor 因而跳过 verifier；本地运行链不完整，整个
formal-v1 已按 `terminal_bench_infrastructure_failed` 作废并 body-free 发布。前 7 个结果只保留为私有诊断历史，
不得进入或续接任何正式 20-result 分母。

formal-v1 共结算 96 个可靠 upstream attempts、`1.749536 USD`；Plan 058 跨 identity 累计费用为
`2.938249 USD`、reserved `0`。收尾时 Docker 占用 `11.5GB`、活动容器/卷均为 `0`，Docker Desktop VHDX 增长
`0`，Windows C: 实际余量 `191108644864` bytes。

## runner 缺陷与窄修

- 对 Plan 058 专用路径，adapter 原样保存 agent/tee exit receipt；仅精确的 agent exit `1` 使用 Harbor 0.20 的
  `NonZeroAgentExitCodeError`，让 Harbor 如实记录 agent failure 后继续 verifier。tee、receipt 或其他 exit 仍按
  本地设施故障 fail closed。通用历史 parser 默认行为不变；Plan 058 只有在 receipt、budget stop、API metadata、
  Guardian evidence 和 verifier 结果精确一致时，才保留该有效任务结果及 reward。
- adapter 不再把 `CODEX_HOME` 放在 `/tmp`。release RONDO 会拒绝在临时目录创建所需的
  `codex-linux-sandbox` arg0 helper；新路径使用 `/logs/agent` 下 adapter 独占的隐藏目录，沿用既有生命周期并在
  finally 中精确清理，不修改 sandbox 或审批策略。

## 重新 commissioning 的硬门

修复后不直接启动 formal。先建立明确的 commissioning/diagnostic identity，按旧 formal-v1 顺序覆盖第 `8..20`
槽（含首尾，共 13 槽），不重复前 7 槽。有效任务失败/reward 0 记录后前进；本地设施故障保留工件和费用，窄修后以
新 diagnostic identity 从当前失败槽继续；纯 transport/临时上游故障在本地条件不变时重试同一 logical slot。只有
13 槽全部完成 agent → Terminal-Bench → verifier → observe/project → settle → diagnostic record，才提交、重建、
复验并统一冻结；随后用全新 identity 从 1/20 运行唯一正式 campaign。

修复后的 `py_compile`、Python 定向回归 `131/131` 和 `git diff --check` 均通过；其中实际 Bash 管道测试确认 agent
exit `1` 与 tee exit `0` 被分别记录。尚未把这些本地测试冒充 commissioning：下一步仍必须真实运行 diagnostic
`8..20`，验证已暴露的 Guardian-limit/verifier 分支及其余剩余槽。
