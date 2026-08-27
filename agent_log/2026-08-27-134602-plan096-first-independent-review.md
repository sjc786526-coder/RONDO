# Plan 096：首次独立验收

日期：2026-08-27 ｜ 对象：`worktree-096-validation-cloud-scorer-qualification@7c4e74c` ｜
正式 namespace：`plan096-formal-20260827T201304Z-validation-55`

## 1. 结论

**首次验收暂不通过：0 High / 1 Medium。**

唯一正式 55 条本身完整、干净且可复算，费用、重试、数据外发、产品不变性和终态均成立；接受研究结论
`CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`，不要求也不允许为本次 finding 重跑真实 API。当前阻断仅是 formal runner 在已有
authority 后没有于外发前 fail-fast，误用新 `run_id` 会先重复整轮评分并产生费用，最后才拒绝第二份 authority。

因此 Plan 097 继续不解锁；`doc/WBS-COMPLETED.md` 与任务最终完成状态应保持待收口，直至该门禁窄修、相关离线测试通过并完成复验。

## 2. Finding

### Medium — 已有正式 authority 时，新 namespace 仍会先重复整轮 provider 调用

`run_formal()` 在校验 release 后直接创建新 namespace 并进入 `score_items()`，55 条完成、`scores.json` 与 `result.json` 写入后才调用
`claim_formal_result()`。`CloudQualityArchive.create()` 只拒绝同一 `run_id` 的非空 formal namespace，不检查根级
`formal-authority.json`；已有 authority 的冲突直到 claim 阶段才会得到 `formal_result_already_authoritative`。

证据：

- `eval/rondo_eval/publication_critic/cloud_quality/runner.py:562-576`
- `eval/rondo_eval/publication_critic/cloud_quality/archive.py:58-75`
- `eval/rondo_eval/publication_critic/cloud_quality/archive.py:202-219`

这不会改写或污染当前 authority，但会让误用的新 formal `run_id` 再次外发 55 份 validation packet、产生费用并留下第二个完整
namespace，违反本任务“唯一正式轮、有效 scalar/质量结果不得重跑”的功能边界。

修复验收要求：

1. formal runner 在创建 namespace 或调用 evaluator 之前检查根级 authority；已有有效 authority 时立即 typed fail-closed。
2. 增加离线回归测试：先形成 authority，再使用不同 formal `run_id` 调用 runner，断言 evaluator 调用数为 0、既有 authority 不变，且没有创建
   新 formal namespace。
3. 不重跑 commissioning 或正式真实 API，不改变当前正式结果、终态、tracked projection、冻结合同、价格或产品行为。实现位置和错误码可由执行者
   按现有职责选择；无需扩建通用锁、审计或可信设施。

## 3. 已通过的独立核验

- 正式资产只有一个 formal namespace：55/55 success、0 final typed failure、56 HTTP attempts；唯一双 attempt 是冻结 policy 允许的
  transient failure 后同一 logical call 重试，没有重跑成功 scalar 或质量结果。
- freeze、55 份 call record、scores、result、authority 与 tracked JSON 的 canonical hash 链一致；从冻结 validation-only release 与 55
  scalars 独立逐字段复算得到同一完整 curve、fallback、usage、分歧清单和终态。
- 55 条为 34 PASS / 21 REWRITE，14 个 unique score 形成 27 个 search point，0 admissible point。fallback threshold `0.9`：False PASS
  `8/21`、False REWRITE `0/34`、balanced accuracy `0.8095238095`；ROC AUC `0.8403361345`；Boundary strict win `15/19`。两个
  threshold-free 门均通过，故唯一终态是 `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`。
- exact 1.7B 与 4B 历史对象均绑定相同 release；同口径复算与 tracked historical projection 一致。文档明确排除 raw logit、绝对
  threshold/calibration、template/tokenizer、latency/resources 的精确类比，没有为天然模板差异制造本地重跑。
- 正式 usage 为 cache-hit input `35,968`、cache-miss input `21,893`、output `77,985` tokens；唯一无 usage attempt 按 `1 RMB` 计，独立复算
  正式费用 `1.3855704 RMB`。两轮 commissioning 加正式轮总计 165 logical calls / 166 attempts / `2.1391799 RMB`，低于 `30 RMB`
  上限。审查时对照 DeepSeek 官方当前价卡，冻结的非高峰 `0.05 / 1.5 / 4.5 RMB per million tokens` 与页面一致。
- evaluator 只收到本地移除 candidate identity 后的 bounded packet；labels、pairs 和 supervision 在全部评分封存后才本地 join。call record 不含
  packet、prompt、响应正文、credential 或 supervision；ignored 树无 symlink，文件 0600、目录 0700。
- Rust eval-only one-shot binary 复用 Plan 095 的请求、template/projection、strict scalar parser、identity/domain 与 retry 路径；产品
  service/client/wire/verdict、local worker、Team State、`team_publish` 与 default-off 选择路径未改。
- 顶层 WBS、三期 WBS、ExecPlan、tracked 结果与实施日志在待首次验收状态、指标、唯一终态和 Plan 097 不解锁上相互一致；
  `doc/WBS-COMPLETED.md` 尚未提前写入 Plan 096。

## 4. 本轮门禁与边界

- Python 定向测试：`94/94 passed`。
- Rust 相关 crate：通过共享 build lock、唯一 `rondo-multi` target 和仓库 watchdog 复跑
  `just test -p codex-publication-critic`，`62/62 passed`、0 skipped；Nextest run
  `10205596-fa4a-40d2-97ca-9fe4eee41758`，watchdog `stop=none`。
- `git diff --check d807572..7c4e74c` 与对象完整性检查通过；首次审查开始时 main、093、095 与 096 worktree 均 clean。
- 未运行真实 API、全 workspace、clippy 或 fmt；未读取 `.env.local`、unseen、密钥或 provider body；未使用 Docker、GPU、RunPod 或本地模型，
  未产生新的外部费用。

## 5. 审查裁定

1. 接受当前唯一正式轮及其 `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH` 研究终态；该结果无需因 runner 门禁修复而作废或重跑。
2. 接受单次 transient attempt 按 `1 RMB` 保守计费、成功 attempt 再按 provider usage 计费的口径；当前总账和 30 RMB 上限闭合。
3. 接受职责明确的 eval/reference-only scalar/usage 接缝；不要求改变产品 wire 或另建 Judge、审计、可信、隐私或通用预算平台。
4. 要求只修复上述 formal authority preflight，并运行相称的离线测试。修复后再提交复验；首次审查接受前约定的 WBS-COMPLETED/最终状态收口
   放到复验通过后完成。
