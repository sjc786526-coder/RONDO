# Plan 102：五维云端判官产品接缝

日期：2026-08-31 ｜ 分支：`worktree-102-five-dimension-cloud-judge`

## 改动

- 拓宽接缝：`ScoringContract` / `ScorerProjection`，五维路径无 threshold；旧标量 identity 字节不变。
- 云端产品路径按 descriptor 显式二选一；五维固定 `thinking.type=disabled`。
- 48 组合穷举测到 in-process 服务与 loopback HTTP 服务出口。
- Plan 102 自建预算身份与 campaign，不改写 Plan 097 的 `6/24/7.5/30`。
- 失败侧 body-free 诊断：trace 保留 dispatch error；投影分类 typed 错误、用参数哈希比较 continuation、记录拒绝后是否还有 Producer followup。`team_publish` 在 Publication Critic 开启时把 log payload 换成候选/continuation 的 sha1，不再整段省略。
- `ScoringContract` 去掉 `#[serde(untagged)]`，改为按 `pass_rule` 显式判别；两个变体的 wire 字节不变。
- Producer ledger 改为代际：新一代只继承上一代剩余额度，换账本不再重置任务级 `50 USD` 上限。
- Plan 102 自己的 Producer 成员提示词（Plan 097 的常量不变，`build_producer_command` 参数化）：
  把重试机制讲死到"绑定结果、按下标传 cycle id、被拒后纠正而不是结束"，不放松任何证据不变量。
- 失败可读性：先查 `returncode` 再加载 trace；`TraceError` 折叠成 `producer_trace_invalid:<slug>`；
  投影记录最后一次 publish 之后 Producer 还调过哪些工具（只记工具名）。

## 疑难

- **`#[serde(untagged)]` 在产品构建图里解析不了旧标量 descriptor。** `codex-exec-server-protocol` 开了
  `serde_json/arbitrary_precision`，Cargo 特性统一后凡链接 `codex-core` 的二进制都带上；untagged 会把内容
  缓冲成 `Content`，此时数字变成内部 map，`domain` / `threshold` 的 `f64` 读不回来。叶子 crate 单跑全绿，
  只有 `codex-core` 的 `concurrent_exact_publish_reviews_and_commits_only_once` 暴露出来
  （`data did not match any variant of untagged enum ScoringContract`）。已改为按 `pass_rule` 显式判别。
- 旧 `codex` 二进制仍按标量 `ServiceDescriptor` 解析，Producer 段必须先 `just build -p codex-cli`。
- **B2 跑满 17 个 Producer run 仍无 canonical commit，卡点在 Producer 侧模型行为，不在接缝。**
  每轮第一次 `team_publish` 都被正常评审为 `rewrite_required` 且带合法 `next_review_cycle_sha1`；
  第二次要么不发（多数轮），要么不带 `review_cycle_id`（r6），要么带了对不上的 id（r13）。
  后两种被 core 以 typed `cycle_mismatch` 正确拒绝，错误也回给了模型，模型随后自行结束。
  已排除：接缝返回不可用 cycle id、模型看不到评审结果、cell 间不共享状态。
- r3 的 `continuation_matches_previous=False` 是空失败结果的投影假象；r13 才是真的送错 id。
  旧投影把 `type=error` 读成空结果，丢掉了 typed 原因，这也是本次补诊断的直接动机。
- `reasoning_effort` 被合同锁钉死为 `low`。Plan 097 在相同配置下最终成功，且其留有 attempt 投影的轮次
  19 次 dispatch 全部 `completed`；差异未能完全解释。调高 effort 需改合同身份，未擅自更改。

## 验收

- 阶段 A：`just test-with-codex-v8-conservative -p codex-publication-critic` 79/79（离线，审查者复跑）。
- 产品构建图：`-p codex-core --lib -E 'test(publish)'` 6/6，含修复后的
  `concurrent_exact_publish_reviews_and_commits_only_once`。
- 阶段 B1 判官：真实 `deepseek-v4-flash`，PASS+REWRITE，thinking 关闭，completion 42–44。
- 阶段 B1 写作者：真实 `gpt-5.6-terra`，`rewrite_required` 后发起第二次尝试。回执不干净：
  `error_code: trace_wire_binding_invalid`、`status: rewrite_observed_canonical_not_required`。
  该码实为严格证据校验要求的 `team_inspect` dump/log 未发生（`inspect_actions: []`）所致，
  是 Producer 未完成导致 Root 未被正常唤醒的连锁结果，不是 wire 绑定缺陷。
- 阶段 B2：无 canonical 轮。真实跑过并全部披露为废弃：`plan102-b2-r1`…`r16`（含 B1 共 17 个 Producer run）。
- 判官累计 `0.0191452 RMB` / 剩余 `9.9808548 RMB`，65 次调用。
- 写作者累计 `2.585289 USD` / 剩余 `47.414711 USD`，17 个 run；三代 ledger cap
  `50` → `49.247218` → `48.265400`。
- 证据：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan102/`，约 596K。
- 定向测试：`test_publication_critic_plan097_producer_runtime` + `..._plan102_contract` 24/24。
- 真实/离线分界：真实 API 覆盖云端判官段与写作者段；local backend 与 OFF 分支只有离线守护，
  未做真实本地模型加载推理。
