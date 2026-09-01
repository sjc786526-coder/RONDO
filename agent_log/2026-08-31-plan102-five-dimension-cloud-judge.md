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
  把重试机制讲死到"绑定结果、只打印 status/反馈/cycle id、按下标传 cycle id、被拒后纠正而不是结束"，
  不放松任何证据不变量（每个 cell 一次 publish、不预写、单 Event、唯一 canonical commit 仍由校验器强制）。
- 失败可读性：先查 `returncode` 再加载 trace；`TraceError` 折叠成 `producer_trace_invalid:<slug>`；
  投影记录最后一次 publish 之后 Producer 还调过哪些工具（只记工具名）。

## 疑难

- **`#[serde(untagged)]` 在产品构建图里解析不了旧标量 descriptor。** `codex-exec-server-protocol` 开了
  `serde_json/arbitrary_precision`，Cargo 特性统一后凡链接 `codex-core` 的二进制都带上；untagged 会把内容
  缓冲成 `Content`，此时数字变成内部 map，`domain` / `threshold` 的 `f64` 读不回来。叶子 crate 单跑全绿，
  只有 `codex-core` 的 `concurrent_exact_publish_reviews_and_commits_only_once` 暴露出来
  （`data did not match any variant of untagged enum ScoringContract`）。已改为按 `pass_rule` 显式判别。
- 旧 `codex` 二进制仍按标量 `ServiceDescriptor` 解析，Producer 段必须先 `just build -p codex-cli`。
- **B2 前 22 轮都卡在第二次 `team_publish`，真因是成员提示词让模型读不到裁决。**
  `code_mode_result` 把完整结果交给 code cell，模型只看得见 cell 的输出；我先前把提示词写成
  "绑定结果后立刻结束 cell"，等于劝阻打印。表现是第二次 publish 不带 `review_cycle_id`
  且候选一字未改，随后转去 `team_history` / `team_inspect` / `send_message` 查发生了什么——
  这是看不到裁决的样子，不是无视裁决。改为显式打印 status / 反馈 / `review_cycle_id`
  （只打印这三项）后，下一轮 r23 即取得 canonical commit。Plan 097 原文的
  "inspect the actual result" 隐含了这一步。
- 全程每一轮的第一次 `team_publish` 都被正常评审并带合法 `next_review_cycle_sha1`，
  失败从未落在接缝上；两种畸形重试都被 core 以 typed `cycle_mismatch` 正确拒绝。
- r3 的 `continuation_matches_previous=False` 是空失败结果的投影假象；r13 才是真的送错 id。
  旧投影把 `type=error` 读成空结果，丢掉了 typed 原因，这是本次补诊断的直接动机。
- 已排除：接缝返回不可用 cycle id、`redacts_tool_bodies` 挡住模型、cell 间不共享状态。
- `reasoning_effort` 经用户批准由 `low` 提两档到 `high`。它把走到第二次 publish 的比例从
  少数轮提到 3/6，但不足以单独打通；真正解锁的是上面的打印修复。

## 验收

- 阶段 A：`just test-with-codex-v8-conservative -p codex-publication-critic` 79/79（离线，审查者复跑）。
- 产品构建图：`-p codex-core --lib -E 'test(publish)'` 6/6，含修复后的
  `concurrent_exact_publish_reviews_and_commits_only_once`。
- 阶段 B1 判官：真实 `deepseek-v4-flash`，PASS+REWRITE，thinking 关闭，completion 42–44。
- 阶段 B1 写作者：真实 `gpt-5.6-terra`，`rewrite_required` 后发起第二次尝试。回执不干净：
  `error_code: trace_wire_binding_invalid`、`status: rewrite_observed_canonical_not_required`。
  该码实为严格证据校验要求的 `team_inspect` dump/log 未发生（`inspect_actions: []`）所致，
  是 Producer 未完成导致 Root 未被正常唤醒的连锁结果，不是 wire 绑定缺陷。
- 阶段 B2：正式轮 `plan102-b2-r23`，真实 API、`status: passed`、`effort: high`：
  3 次 publish、2 次重写（feedback v1+v2）、唯一 canonical commit（1 event / 1 version / 1 mutation）、
  `root_wake=true`、`inspect_actions=[dump,log]`；判官 6 次请求全部 `thinking_disabled`，
  同一轮内 `direct_branch_coverage=[pass, rewrite]`。
  废弃轮全部披露：`plan102-b2-r1`…`r22`（low 段 r1–r16，high 段 r17–r22）。
- 判官累计 `0.0277544 RMB` / 剩余 `9.9722456 RMB`，95 次调用。
- 写作者累计 `4.009768 USD` / 剩余 `45.990232 USD`，24 个 run；五代 ledger cap
  `50` → `49.247218` → `48.265400` → `47.414711` → `46.135724`。
- 证据：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan102/`，约 876K。
- 定向测试：`test_publication_critic_plan097_producer_runtime` + `..._plan102_contract` 26/26。
- 真实/离线分界：真实 API 覆盖云端判官段与写作者段；local backend 与 OFF 分支只有离线守护，
  未做真实本地模型加载推理。
