# 2026-08-14 Plan 026 / WP3b-A2b：47/47 exact-token 普查重跑（未通过）

分支 `026-wp3b-a2b-exact-token-census-rerun`，起点 `a60ef0e`。目标是用 static payload v2 重跑 47 条真实
`E_final` 的 count-only exact-token 普查。**结论：未通过，未发布 baseline，没有生产代码改动。**

## 实质动作

1. 模型启动前只读核对现场与现有无模型门禁，未发现 `token_census.py` 的直接窄缺陷，因此不做窄修。
2. 在共享锁与 GPU 独占下执行**一次**正式 census（count-only，`max_output_tokens=512`），
   第一次结果写 ignored 临时路径。合成探针通过，随后在真实归档计数阶段收到通用 500，按合同 fail closed。
3. 按用户指示不为凑结果执行第二次运行，也未增加额外模型生命周期。
4. 用聚合式离线检查确认 23 条 v2 请求的角色顺序兼容问题（不占模型）；该结论与本次通用 500 的具体位置
   和原因分开记录。
5. 只更新 Plan 026、`doc/WBS.md`、`doc/WBS/local-approval-model.md`，不写 `doc/WBS-COMPLETED.md`。

## 失败事实

```
status  = not_counted     blocker = count_endpoint_unavailable
http    = 500 server_error（error_code 500）
message_sha256 = bfd4dade…    exit = 70
cleanup = server_stopped / port_released / private_artifacts_removed 均为 true
```

探针失败会给出另一个 code（`count_endpoint_probe_failed`），本次没有出现；这只证明同次运行中 endpoint
能处理合成探针，随后失败发生在真实归档计数阶段。

## 疑难问题：离线确认的兼容阻断

23 条当前 v2 请求存在确定的**会话角色顺序**兼容问题：

- `common/chat.cpp` 的 `map_developer_role_to_system` 在套用模板**之前**把 `developer` 统一改成 `system`。
- 冻结 Ministral 模板规定 `assistant` 之后只能接 `assistant`/`user`/`tool`，遇到 `system` 直接
  `raise_exception`。minja 抛 `std::runtime_error`，服务端 `ex_wrapper` 兜底成 **500**；
  只有 `std::invalid_argument` 才映射成 400。
- 47 条真实 v2 请求中，历史上成功计数过的 24 条没有 assistant 轮；另外 23 条都含
  `… assistant → developer → user`。
- 离线用同一份冻结模板渲染这 47 条 v2 请求：**24 渲染成功 / 23 抛
  `Unexpected role 'system' after role 'assistant'`**。

这证明 23 条 v2 请求若到达模板阶段会被角色顺序阻断，但**不能证明** Plan 026 的具体 500 必然来自其中某条。
Plan 024 的 21 条 400 仍是当时先触发的 reasoning 形状拒绝；v2 移除 encrypted-only reasoning item 后，
这些请求又暴露出角色顺序问题。Plan 024 的 2 条旧通用 500 的现场原因仍未由历史证据证明。
后续应在公共 builder 做版本化、provider-neutral 的角色顺序兼容，不能静默改写已冻结的 v2。

## 另一处已记录但未修的缺陷

`count_input_tokens` 的默认 code 使「锚点 500」与「循环中某条 500」都表现为
`count_endpoint_unavailable`，报告也不给已计数条数。因此本次只能确认通用 500 出现在真实归档计数阶段，
无法确认是锚点还是后续样本；**锚点 5,313 未被本次运行直接复证**。该缺陷留给后续无模型任务增加最小阶段、
当前样本哈希和失败前 counted 数。

## 验收结果

- 47/47：**未达成**，本次没有新增可发布计数；无法给出全集 4k/8k fit 数，也不存在正式 baseline。
- 两次一致性：**不适用**（只运行一次）。
- focused tests `test_contracts_and_evidence.py` + `test_local_approval.py`：109/109 通过。
- 依赖锁：`uv lock --directory eval --check` 85 packages 通过。未按原样跑 `just eval-lock` ——
  该配方硬编码 `$PWD/eval-data/uv-cache`，本 worktree 无 `eval-data/`，改用主仓 cache 的等价命令。
- 清理与状态：8080 空闲、无 GPU 计算进程、`eval-data/local-approval/` 无本任务残留、`git status` 干净；
  doctor 报 `model_backed_validation: not_run`、`runtime_capability:
  linux_cuda_built_model_unvalidated`，无新增资格成功 evidence。
- 未运行：第二次 census、Cargo、Docker、云 API、全量 eval、任何 generation。
