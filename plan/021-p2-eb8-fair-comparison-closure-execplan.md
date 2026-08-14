# Plan 021：E-B8 公平比较设施闭合（无真实 API）

> 本计划是任务的稳定约束文档。
> 除"当前状态"和"关键决策记录"外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

按 `doc/WBS.md` 工作包 1 与 `doc/WBS/eval-benchmark.md` E-B8 合同，闭合冻结 Codex 与 RONDO 之间
公平比较设施的六类缺陷：catalog 非对称、请求前置合同缺失、运行条件与执行顺序混杂、聚合判据含糊、
重复规则可事后调整、实现假设只有一个 RONDO 产品。

本任务只改测评设施本身。不运行新的真实 B7 campaign，不调用真实 API，不建立 RONDO Multi，
不推进 Local 本地模型路线。

### 完成/验收标准

- [x] 两侧最终 catalog 字节相同；artifact SHA 与上游/RONDO 双来源 commit/path/blob ID、投影算法与
      schema 版本、main/Guardian model、override 目标 entry 均可机械核验；任一项漂移 fail-closed。
- [x] 存在完全禁止真实上游调用的 stub preflight，证明：对称时不触碰网络；tool specs / instructions /
      输出 schema / 稳定 developer 前缀任一分区不对称时在发送前失败并给出可归因原因码；
      任务正文不同不会被误判为 task-independent 合同漂移。
- [x] harness commit、deadline、task/image、provider profile 等冻结运行条件不一致时拒绝比较。
- [x] 正式调度顺序按任务交错，不按整轮时间分块（v7 起）。
- [x] assessment 分别输出方向性结果、A/A 行为一致性、跨侧差异三组状态；条件加跑进入最终聚合。
- [x] 重复合同未冻结、偶数或小于 3、正式数据后改轮数/删样本/改聚合公式时均被拒绝。
- [x] 产品身份入口存在且不假设只有一个 RONDO 产品；未创建 `multidev/`，未提前实现工作包 2。
- [x] `just eval-lock` 通过；阶段收口 `just eval-test` 通过；全程无真实 API / Docker / 真实模型。
- [x] `git diff --check` 通过；无意外生成物、密钥或历史数据改动。

## 2. 范围

### 允许修改

- `eval/rondo_eval/` 内与 catalog、adapter、请求代理、Terminal-Bench baseline、assessment、
  campaign identity、结果聚合相关的模块。
- `eval/tests/` 内对应的定向回归测试。
- 非历史的 schema/模板与必要的 `justfile` 入口。
- `plan/021-*.md`（本文件）、`agent_log/`、`doc/WBS.md`、`doc/WBS/eval-benchmark.md`、
  `doc/WBS-COMPLETED.md` 中受本次影响的部分。

### 不允许修改

- `mydev/` 的产品行为（只读核对可以）。
- `codex-source-code/`。
- v1—v22 的 lock、result、ledger、artifact、receipt 与聚合结果（冻结历史）。
- `eval/locks/` 中已冻结的历史 provenance 记录。
- 依赖版本与依赖锁（`eval/uv.lock` 不得升级改写）。

### 不允许读取/查看

- `.env.local` 内容。
- holdout 对应的任务正文、solution、verifier、日志或单任务结果。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. 不创建 `multidev/`，不建立第二条产品线，不提前实施工作包 2 的产品身份接入或看门狗迁移。
2. 不运行 `eval-b7-baseline`、`eval-b2-no-api`、任何 Docker 入口或真实 provider/API 入口。
3. 不创建、激活或消费新的付费 campaign、预算 ledger、run ID 或真实结果。
4. 历史 schema v1—v6 的 slot 顺序、run_id 分配、assessment 语义必须逐字节保持不变；
   新行为只在新 schema 版本（v7）下生效。
5. 不采用 pairwise-max `σ` 等事后扩大容忍度的方案。
6. 重复数与聚合公式未冻结前，设施必须拒绝建立正式 campaign。
7. 不为了让测试通过而弱化 fail-closed、安全、身份绑定或公平性检查。
8. 不扩大为统计显著性框架、可信审计平台或新的大型测评架构。
9. 只运行与本次改动相关的必要测试，不重跑无关重型套件。

## 4. 软性建议

- 复用 `api_budget_proxy.canonical_request_sha256` 作为唯一 canonical JSON/SHA 原语。
- 把"task-independent 请求投影"做成窄、版本化、纯函数式合同，不复制完整请求处理链。
- catalog artifact 身份与二进制 source 身份分层表达。
- 在现有测试体系中补充 focused 回归，不另起测试框架。

## 5. 当前状态

> 本节允许在执行过程中持续更新。

### 已完成

- 现状调研：确认 6 处缺陷的源码位置。
- 设施实现与定向回归全部落地，见"当前验收状态"。
- 独立验收（GPT，审查提交 `c970cbb`）提出 4 项问题，全部自行复现属实并修复：
  付费 runner 接入 stub preflight receipt 且第一侧同样受检、successor 生成器只产 v7、
  运行条件与 catalog provenance 绑定真实事实、条件重复改为双向触发。

### 当前工作

已完成，计划冻结。

### 本任务剩余步骤

无。

### 阻塞项

无。

### 当前验收状态

- `just eval-lock`：通过。
- `just eval-test`：通过（`Ran 552 tests ... OK`）。
- 全程未调用真实 API、未运行 Docker、未加载真实模型，未创建新 campaign identity。

### 交接边界

- 本任务完成后冻结此计划；后续 B7 campaign 合同、产品身份实际接入见 `doc/WBS.md`。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | catalog 保留完整 8 模型，只在目标 entry 上打 `auto_review_model_override`，两侧加载同一份 artifact | 消除已定位的 `spawn_agent` 工具描述非对称；两侧 `models.json` blob ID 相同使该方案有基础 | `frozen_model_catalog.py`、`adapters.py`、campaign lock | 已采纳 |
| 002 | catalog 身份改为独立 artifact SHA + 双来源 provenance，不再绑定某侧二进制 source commit | 仅绑最终 SHA 只能证明没漂移，不能证明来源正确；绑二进制 commit 则两侧无法共用同一份字节 | 同上 | 已采纳 |
| 003 | task-independent 投影覆盖 tools / instructions / 输出 schema / `input` 中首个 user 之前的 developer-system 前缀 | Responses Lite 把 catalog 派生的工具描述放在 developer 前缀而非顶层 `instructions`，只投影顶层会漏掉 161-token 那类差异 | `fair_comparison.py` | 已采纳 |
| 004 | 新行为只在 campaign schema v7 生效，v1—v6 完全冻结 | v22 及更早是不可改写的历史证据，slot 顺序与 run_id 分配一旦变化会破坏历史复算 | `baseline.py`、`baseline_cli.py` | 已采纳 |
| 005 | 多轮 outcome 聚合采用奇数重复的严格多数，不引入统计框架 | 奇数保证无平局，多数规则可机械执行、可测试；符合"不扩大为显著性框架"的边界 | `baseline.py` | 已采纳 |
| 006 | 产品身份只加窄入口（`Product` 取值 + 比较合同上的 `product` 字段），不接管归档/路径 | 本工作包不建 Multi，避免提前实现工作包 2 | `contracts.py`、`baseline.py` | 已采纳 |
| 007 | preflight 用注册表 + 禁网 transport 实现，挂在 proxy 的 `_inspect_request` 之后、`_transport.open` 之前 | 该位置是请求体已解析、任何字节尚未出站的唯一窄点 | `api_budget_proxy.py`、`fair_comparison.py` | 已采纳 |
| 008 | 合同必须先由 stub 运行冻结为 `PreflightReceipt`，付费 slot 缺 receipt 即拒绝 | 只在代理内比较会放行第一侧，那时费用已产生；归因报告 §8.2 要求两侧先在本地 stub 零成本生成请求 | `fair_comparison.py`、`live.py`、`baseline_cli.py` | 已采纳 |
| 009 | successor 生成器只产 schema v7 并强制传入冻结的 comparison 合同 | 原入口硬编码 v6，可造出绕过全部 v7 门禁的合法 campaign | `baseline_identity.py`、`justfile` | 已采纳 |
| 010 | 声明的运行条件必须与 campaign 自身权威字段等值，catalog provenance 全字段格式校验 | 否则 lock 里可以冻结一份与自身矛盾、实际未生效的比较合同 | `baseline.py`、`fair_comparison.py` | 已采纳 |
| 011 | v7 的条件重复触发改为任一方向的跨侧差异，方向性兜底仍单向 | 单向触发会让反方向差异绕过重复合同，`delta` 混合多数结果与单次结果 | `baseline.py`、`baseline_cli.py` | 已采纳 |
