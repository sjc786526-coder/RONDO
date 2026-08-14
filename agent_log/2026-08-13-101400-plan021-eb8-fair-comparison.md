# E-B8 公平比较设施闭合（Plan 021）

- 输入：`doc/WBS.md` 工作包 1、`doc/WBS/eval-benchmark.md` E-B8、归因报告
  `doc/research/plan020-b7-canary-baseline-failure-attribution.md` §8。
- 边界：只改 `eval/` 设施与文档，未运行 Cargo、Docker、真实 API 或本地模型，未创建新 campaign identity。

## 实质变更

- **共享 catalog**（`frozen_model_catalog.py`）：新增 `load_shared_model_catalog()`，保留完整 8 模型、只在
  main entry 上加 `auto_review_model_override`。artifact 身份改为自身 SHA-256 + 双来源 provenance
  （commit / path / blob ID）+ 投影算法与版本 + main/Guardian model + override 目标 entry。两来源 blob 不同
  即报“无共享工件”。旧 Codex-only 投影原样保留为 `load_frozen_model_catalog()`，只服务 v1—v6 复算。
- **对称交付**（`adapters.py` / `runner.py` / `live.py`）：catalog 从“只发 Codex”改为两侧同发。identity 分两种模式，
  互斥且必须二选一：legacy（绑二进制 source commit，仅 Codex）与 shared（绑 provenance SHA，两侧均可）。
  `_validate_safe_codex_command` 不再按 side 判断是否允许 `model_catalog_json`，改为按声明校验存在性与唯一性。
- **请求前置硬门**（新增 `fair_comparison.py` + `api_budget_proxy.py`）：见下节的投影范围决定。注册点在
  `_inspect_request` 之后、`_claim_and_reserve_logical_request` 与 `_transport.open` 之前，
  失败以 409 + 分区级原因码返回，两侧都不产生费用。
- **运行条件与交错**（`baseline.py` / `baseline_cli.py`）：`ComparisonConditions` 冻结 harness commit、deadline、
  task/image digest、provider profile、投影版本。`base_round_order` 承担顺序合同：v7 task-major、v1—v6 保持 round-major。
- **判据分层与重复合同**：assessment 拆为 `aa_consistency` / `cross_side` / `directional` 三层；`RepeatContract`
  奇数 ≥3、严格多数、pilot 冻结；条件加跑进入最终聚合。
- **产品身份**：`contracts.Product` + `product_for_side()`，与 `side` 正交，`codex` 不是产品取值。
- **入口**：新增 `just eval-preflight-symmetry` 与 `rondo_eval/preflight_cli.py`（离线、禁网、退出码区分 blocked）。

## 关键判断

1. **投影必须覆盖 developer 前缀，不能只看顶层 `instructions`。** 归因报告 §5.1 指出 Responses Lite 把
   catalog 派生的 `spawn_agent` 工具描述作为 developer `AdditionalTools` 前缀塞进 `input`。只投影顶层
   `tools`/`instructions` 会恰好漏掉这次要抓的那类不对称。采用的机械规则是“`input` 中首个 user 之前的
   连续 developer/system 项”——任务正文是 user 消息，因此天然被排除。已加回归证明任务正文不同不算漂移。
2. **所有新行为绑定 campaign schema v7，v1—v6 逐字节冻结。** slot 顺序一旦变化，run_id 的序号分配随之改变，
   v22 及更早的历史复算会全部错位。因此顺序、重复数、assessment 分层、catalog 投影都按 schema 分叉，
   老路径连同旧的 trimmed 投影函数一并原样保留。
3. **重复数把基础 A/B 轮计入总观测数。** 合同要求“奇数且不少于 3”，若基础轮之外再跑 3 次会得到偶数总数、
   出现平局。定义为总观测 = 1 基础 + (n-1) 条件加跑后，n=3 时条件槽仍是每侧 2 次，
   slot 总数恰好维持 321，不需要动预算几何。
4. **交错后仍保留提前停机。** 原实现每跑完一整轮就检查 infra 阈值并抛错；改成 task-major 后若挪到最后统一检查，
   infra 饱和的轮次会白跑后续所有题。改为“某轮最后一题落地即刻检查”，v1—v6 的停机时机不变。
5. **跨侧与同侧不对称都 fail-closed。** 每个 `(task_id, role)` 只冻结一份合同，任何一侧后续请求不符都拒绝，
   原因码区分 `cross_side_asymmetry` / `same_side_asymmetry`。完整请求 digest 只记录不断言，
   因为轨迹分叉后动态内容本就该不同。

## 验收

- `just eval-lock`：通过。
- `just eval-test`：532 项全通过（含新增 42 项 `test_fair_comparison`、12 项 catalog 用例，
  以及 adapter/runner 的对称交付与身份歧义用例）。
- 未运行：`eval-b7-baseline`、`eval-b2-no-api`、`eval-b3-oracle-no-api`、任何 Docker 或真实 provider 入口。
- 未改动：`mydev/`、`codex-source-code/`、`eval/locks/` 既有 lock、`eval/results/` 历史结果、依赖锁。

## 遗留边界

设施闭合不等于产生了结论。本批没有跑 pilot、没有冻结具体重复数、没有建立任何 v7 campaign identity，
因此仍不存在可归因的 RONDO/Codex 能力比较。新 campaign 的任务范围、轮数、预算与授权见 `doc/WBS.md`。

## 独立验收后的修正（GPT 审查 `e55a4ac` → blocked）

四项问题全部自行复现属实，已修复。审查日志见
`agent_log/2026-08-13-acceptance-review-e55a4ac-eb8.md`（不改写，作为形成时点证据）。

1. **付费 runner 没接 preflight，且首侧被放行**（BLOCKER）。原实现只把 `symmetry_preflight` 做成代理参数，
   生产路径从未传入；即便传入，注册表也是"首次出现即冻结并放行"，只能拦第二侧 —— 而归因报告 §8.2 明确指出
   那时第一侧已经产生费用。修正：新增 `PreflightReceipt`，由两侧在 stub 上零成本产生的请求冻结而成，
   绑定 campaign_id / lock SHA / task / 两侧 bundle manifest。`live.py` 对 v7 强制要求 receipt，
   缺失或绑定不符即在启动代理前拒绝；代理用 `SymmetryPreflight(require_expectation=True)` 预置期望，
   因此第一侧也要对照预冻结合同，未被 receipt 覆盖的请求直接拒绝。
   *边界*：真正生成 receipt 需要一次无 API 的双侧 stub 运行（Docker），不在本任务授权内，故未执行；
   已实现并测试其纯函数产出路径 `preflight_receipt_from_stub_run()`。
2. **successor 生成器硬编码 v6**（BLOCKER）。`just eval-b7-next-identity` 会造出可加载、可激活的 v6 campaign，
   完全绕过 v7 门禁，直接违反"重复数与聚合公式未冻结前不得建立正式 campaign"。修正：生成器只产 v7，
   新增必填 `--comparison-contract`，且把纯校验提到函数最前 —— 合同不合法时在读 registry、写 lock 之前就失败。
3. **运行条件与 catalog identity 只是声明**（HIGH）。`require_match()` 无生产调用；`_parse_comparison_block()`
   只查 key 集合，导致 `commit: "zzz"`、`projection_algorithm: "totally-made-up"`、
   `task_image_digests: {"unrelated-task": "not-a-digest"}` 这样的块能干净加载（已复现）。修正：
   新增 `actual_conditions()` 从 campaign 自身权威字段重建条件，`require_declared_conditions()` 在加载时等值校验，
   harness commit 因是运行期事实改在 `_execute_task_slot` 校验；catalog provenance 补齐 commit/blob/path 格式、
   两侧 blob 一致、投影算法与版本、override 目标必须等于 main model 且在 slug 列表内。
4. **条件重复只覆盖一个方向**（HIGH）。触发条件写死 RONDO fail / Codex pass，于是 RONDO pass / Codex fail
   的题在 `sigma` 吸收后完全不跑重复（已复现：`status=passed`、`delta=1`、`conditional_tasks=[]`），
   `delta` 因此混合了三次多数结果与单次结果。修正：v7 起触发条件改为**任一方向**的跨侧差异；
   方向性兜底保持单向（它检测的是回退，不是差异）。`baseline_cli` 的执行侧同步改为同一规则。

修正后 `just eval-lock` 通过、`just eval-test` 552 项全通过；两条审查复现用例现在都被拒绝，并已固化为回归。
