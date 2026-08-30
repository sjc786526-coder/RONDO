# Plan 100 路线穷尽语义裁决与定向复核

## 结论

`ROUTE_FALLBACK_APPROVED_WITH_EXPLICIT_RESIDUAL_MARKER / STAGE_B_REMAINS_LOCKED`

批准执行者提出的穷尽规则：保留现有 route priority、五个 terminal 名称和前四个质量终态的既有条件；对于**完整有效 formal**，只有在所有既有质量谓词
均未命中时，最终返回 `CONSTRAINT_OR_DATA_ISSUE`，并在正式结果中明确标记 `residual_mixed_signal = true`。这不是第六个 terminal，也不得改写为技术或
预算型 `INCONCLUSIVE`。

该 fallback 是用户限定的有限路线集合下的保守归档：它只表示 A/B/C 的完整结果没有支持 scalar、direct 或 five-dimension 的某个既有正向路线，且也
不满足三臂全部不可执行；它**不证明数据有缺陷**、不证明存在集中 structured blocker、不归因 backbone，也不建议直接付费解冻训练。报告必须保留三臂
完整指标、实际 gate 命中情况和错误/pair/维度切片，使读者能看到真实 mixed signal，而不是只看到 terminal 名称。

## 冻结实现规则

1. `formal_valid = false` 仍且只允许返回 `INCONCLUSIVE_TECHNICAL_OR_BUDGET`。
2. 完整有效 formal 依次应用既有四个质量谓词：五维结构强支持、离散支持但五维增益未确认、预定义的集中 constraint/data blocker、三臂均未达到基本门。
3. 上述均不匹配时返回 `CONSTRAINT_OR_DATA_ISSUE` + `residual_mixed_signal = true`；集中 blocker 的既有路径不得被伪装成 residual，二者须在正式结果中可区分。
4. residual 不得修改 arm metrics、`dimensions_generally_good`、`concentrated_blocker` 或其它原始事实来凑条件。它是 route 层最后一个穷尽分支。
5. 至少补回归覆盖 A-only、B-only、其它代表性 mixed signal、原四类优先级不回归，以及任何完整有效 formal 不再因 route 未映射而被误标为 invalid/
   `INCONCLUSIVE`。具体测试组织由执行者自主决定，不需要建设额外通用决策平台。

## 新发现的阶段 A 技术阻塞

本轮定向核对提交 `2987a4fb` 时发现价档实现与冻结合同相反：

- `structured_diagnostic/cost.py` 把 `peak_days` 冻结为 `daily`，`price_tier_at()` 没有工作日判断；
- 对应测试明确断言 2026-08-29 周六在名义峰时窗口按 `peak`；tracked diagnostic contract 也写成 `peak_windows_daily`；
- 当前 DeepSeek 官方价卡明确峰时仅为 UTC 周一至周五 01:00–04:00、06:00–10:00，即北京时间周一至周五 09:00–12:00、14:00–18:00，
  其它时段均为 off-peak：<https://api-docs.deepseek.com/quick_start/pricing/>。

这是 20 RMB 账本与用户特别强调的周日谷价口径的 correctness blocker。执行者须做窄修：价卡 identity/contract 与 `price_tier_at()` 统一为北京时间周一至
周五峰窗，周六/周日在相同钟点仍为 off-peak；补工作日、周末及窗口边界定向测试。首次真实请求前的 live refresh/freeze 规则继续保留。本裁决不授权
真实 API，也不要求重跑无关重型测试。

## 审查范围与状态

- 本轮只核对 clean worktree、提交 `2987a4fb` 的相关实现/测试摘要、route mapper、费用 mapper、tracked 合同和 Plan 100 语义；没有重新验收全部
  阶段 A 实现，也没有重跑执行者已报告的 Python/Rust 门禁。
- 未读取 qualification、v9 test 或其它 unseen 正文，未调用 API、模型、GPU、RunPod 或 Docker。
- 执行者修复 route fallback 与周末价档后，应运行相称的 Python 定向测试、提交全部变动并再次申请阶段 A 验收。
- 阶段 A：`REMEDIATION_REQUIRED / NOT_YET_ACCEPTED`
- 阶段 B：`LOCKED_PENDING_STAGE_A_REVIEW`
- Plan 100：`IN_PROGRESS / NO_QUALITY_CONCLUSION`
