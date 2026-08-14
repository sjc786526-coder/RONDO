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
