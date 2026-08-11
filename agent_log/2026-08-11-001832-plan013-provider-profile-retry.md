# Plan 013 Provider/Model 配置化与未计费重试

## 实质修改

- 新增独立 `[paid_eval]` 本地合同：动态 provider/model tables 加 `active_provider`、`main_model`、
  `guardian_model` 三个选择字段。生产 eval 路径不再按中转/OpenAI 官方、Sol/Terra/Luna 或 base URL 分支；
  既有 DeepSeek/Qwen/local-model 配置保持不变。
- `ModelPricing` 冻结官方 Standard 基础费率、长上下文 threshold/input/output multipliers、cache-write multiplier、
  snapshot date/source。全部字段进入 selected profile SHA，结果保存 effective model/价卡与 profile/endpoint hash，
  不保存 raw endpoint、provider display name 或 key env。
- 预算代理为 main/Guardian 提供同一套 1~5 upstream attempts：只对 provider profile allowlist 中完整规范、无
  terminal/usage 的非 2xx 做 operator-confirmed-unbilled 重试；每个 downstream request 只 reserve 一次。
  timeout、disconnect、2xx 缺 usage、malformed/超限响应或其他计费不明情况不重试并保守结算。attempt count 与
  settlement kind 在外发前/结算时原子持久化，进程恢复只保守结算，不自动再发。
- provider probe 在请求前写 profile hash，成功或失败均写去敏 receipt；已有 active reservation 只恢复账本并拒绝
  重试，恢复后会刷新与 ledger 不一致的旧 receipt。Terminal-Bench CLI、runner、live proxy、两侧 adapter、
  Guardian evidence 与 success result 都改用 resolved provider projection；v8 的历史 exact identity 与 no-API smoke
  常量保持原样。
- ignored 主仓库 `rondo.local.toml` 配置了 relay/official 与 Sol/Terra/Luna profile，active 为 relay + Sol main +
  Sol Guardian，最大 5 attempts。未读取、打印、复制或修改 `.env.local`；仅由严格 loader 复用 active key。

## 真实 API 结果与费用边界

- v1 在默认开发沙箱中得到 `upstream_status=0`、usage invalid，ledger 保守结算 `$5.000000`。DNS 阻断是执行环境
  观测；ledger 只能证明没有取得 HTTP status/usage，不能单独证明上游未收到字节。
- 获得授权后用剩余 5 USD 新建 v2 ledger 并在宿主网络运行。Sol main 第 1 次 HTTP 200、terminal/usage valid，
  按价卡本地估算 `$0.022105`；Sol Guardian 第 1 次 HTTP 502，响应不满足 operator-confirmed-unbilled 合同，故
  未重试并保守结算剩余 `$4.977895`，run 停止。
- v1/v2 本地 ledger 合计 10 USD，达到本计划授权上限；没有继续发送请求。`actual_usd=null`，未查询供应商账单。
- v2 执行发生在 failure receipt/profile 代码补齐之前，原历史目录只有 budget/metadata；未伪造或回填 profile
  binding。随后独立审查按 2026-08-11 官方文档更新 Terra/Luna 价卡及三模型非线性规则，Sol 基础价格未变，
  但 selected profile SHA 因新字段而变化；该历史 v2 不能作为 Plan 014 的 profile-bound pair 证据。

## 验收

- `just eval-lock`：85 packages，退出 0。
- `just eval-test`：293 tests，全部通过。
- `python3 -m py_compile`：受影响的 11 个生产 Python 模块通过。
- `git diff --check`：通过。
- 未运行 Docker、Cargo、本地模型、B3、Codex paid slot 或 M1。

## 下一阶段

Plan 014 使用全新 pair/lock/ledger/IDs；slot 1 绑定 selected profile SHA，slot 2 前重验。paid 前必须先为
RONDO/frozen Codex 统一 effective Guardian 条件，并可靠阻止 completed+usage 后的产品层 parse retry；无法关联
同一 review 时 fail-closed。新 lock/result 使用专门的 public/redacted projection，success/failure 都保存相同的
profile/endpoint hash。真实 pair 与 Docker 需要新的授权，不能沿用 Plan 013 额度。
