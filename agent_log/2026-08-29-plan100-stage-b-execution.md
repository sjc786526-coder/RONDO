# Plan 100 阶段 B 执行

## B1 请求前准备

- 审查提交 `f0af3360` 验收阶段 A 并明确批准阶段 B；真实 API 仍唯一限于 `deepseek-v4-flash`，task-wide 硬预算为 20 RMB。
- 首个真实请求前刷新 DeepSeek 官方价卡：北京时间周一至周五 09:00–12:00、14:00–18:00 为 peak，其余 off-peak；2026-08-30
  北京时间周日按 off-peak。价格与合同数值未变，checked identity 更新到本次 live refresh。
- 官方 live 文档确认 V4 默认 thinking 会忽略 temperature，并把独立 reasoning 计入 completion usage。为保留冻结 temperature、严格短 JSON 与可复算
  usage，Plan 100 diagnostic 三臂统一显式关闭 thinking；产品 scorer 与其它 eval 路径不变。
- 从官方 token 文档下载 V4 tokenizer 到 task-owned ignored namespace，冻结 archive/tokenizer/config hash；离线 recounter 通过同一个 Rust diagnostic
  executable 的 `render-messages` 模式取得精确 system/user bytes，不复制第二份 prompt。renderer 不加载 credential、不发 HTTP。

## 门禁

- Plan 100 Python unittest：21/21 通过；隔离 pytest：`21 passed, 24 subtests passed`；定向 ruff 与合同 JSON 解析通过。
- 正式 build-lock/shared `rondo-multi` target 下 `just test -p codex-publication-critic`：69/69 通过；新增回归证明 offline renderer 与真实请求消息
  完全一致、renderer 零 provider 请求，且 thinking 只在 Plan 100 diagnostic 中关闭。
- 官方 tokenizer + 更新后 Rust binary 的 A/B/C 离线复算自检通过，只输出 token 数，未调用 API。

## B1 commissioning

- 首轮真实 commissioning 为 9/9 strict success、0 retry、0 parse/technical failure，全部 provider usage-present，实际结算 `0.0069217 RMB`；因
  recounter prompt 与 provider usage 固定相差 21 tokens，binding 按合同未生成，既有 receipt/费用保留。
- 只读核对九项 usage/recount：A/B/C、synthetic/public 的 prompt delta 全部精确为 `+21`，completion delta 全部为 `0`。据此冻结 provider chat
  envelope 21 tokens 并绑定 recounter source hash；不修改 provider usage、prompt、schema、packet 或质量语义。下一步从新 clean commit 重跑 B1。

当前状态：`STAGE_A_ACCEPTED / STAGE_B1_RECOUNT_CALIBRATED_PENDING_CLEAN_RERUN / NO_QUALITY_CONCLUSION`。
