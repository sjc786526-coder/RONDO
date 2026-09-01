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

## 疑难

- **`#[serde(untagged)]` 在产品构建图里解析不了旧标量 descriptor。** `codex-exec-server-protocol` 开了
  `serde_json/arbitrary_precision`，Cargo 特性统一后凡链接 `codex-core` 的二进制都带上；untagged 会把内容
  缓冲成 `Content`，此时数字变成内部 map，`domain` / `threshold` 的 `f64` 读不回来。叶子 crate 单跑全绿，
  只有 `codex-core` 的 `concurrent_exact_publish_reviews_and_commits_only_once` 暴露出来
  （`data did not match any variant of untagged enum ScoringContract`）。已改为按 `pass_rule` 显式判别。
- 旧 `codex` 二进制仍按标量 `ServiceDescriptor` 解析，Producer 段必须先 `just build -p codex-cli`。
- B2 Producer 多次在第一次 `rewrite_required` 后停住，或第二次 `team_publish` dispatch 失败；未形成 canonical commit。
- r3 的 `continuation_matches_previous=False` 是空失败结果的投影假象，不是接缝返回了不可用 cycle id。第二次 dispatch 的 typed 原因因旧投影丢 error、且 traces 已删而无法从 r3 回执恢复。
- Producer ledger `plan102-producer-terra-v1` 的 `max_runs=6` 已用尽（不是预算耗尽）。继续 B2 需要新的 ledger 身份。

## 验收

- 阶段 A：`just test-with-codex-v8-conservative -p codex-publication-critic` 79/79（离线，审查者复跑）。
- 产品构建图：`-p codex-core --lib -E 'test(publish)'` 6/6，含修复后的
  `concurrent_exact_publish_reviews_and_commits_only_once`。
- 阶段 B1 判官：真实 `deepseek-v4-flash`，PASS+REWRITE，thinking 关闭，completion 42–44。
- 阶段 B1 写作者：真实 `gpt-5.6-terra`，`rewrite_required` 后发起第二次尝试。回执不干净：`error_code: trace_wire_binding_invalid`，`status: rewrite_observed_canonical_not_required`。
- 阶段 B2：无正式轮。废弃 `plan102-b2-r1`…`r5`。r3 已离线定性；未再付费。
- 判官累计 `0.0075277 RMB` / 剩余 `9.9924723 RMB`。
- 写作者累计 `0.752782 USD` / 剩余 `49.247218 USD`。
- 证据：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan102/`，约 220K。
- 定向测试：`test_publication_critic_plan097_producer_runtime` 12/12；`test_publication_critic_plan102_contract` 8/8。
