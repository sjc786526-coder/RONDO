# 2026-08-14 Plan 026 / WP3b-A2b：47/47 exact-token 普查重跑（未通过）

分支 `026-wp3b-a2b-exact-token-census-rerun`，起点 `a60ef0e`。目标是用 static payload v2 重跑 47 条真实
`E_final` 的 count-only exact-token 普查。**结论：未通过，未发布 baseline，没有生产代码改动。**

## 实质动作

1. 模型启动前只读核对现场与现有无模型门禁，未发现 `token_census.py` 的直接窄缺陷，因此不做窄修。
2. 在共享锁与 GPU 独占下执行**一次**正式 census（count-only，`max_output_tokens=512`），
   第一次结果写 ignored 临时路径。合成探针通过，随后在遍历的第一条真实归档收到通用 500，按合同 fail closed。
3. 按用户指示不为凑结果执行第二次运行，也未增加额外模型生命周期。
4. 用离线渲染定位根因（不占模型），把 v1/v2 两代真实失败统一成同一个解释。
5. 只更新 Plan 026、`doc/WBS.md`、`doc/WBS/local-approval-model.md`，不写 `doc/WBS-COMPLETED.md`。

## 失败事实

```
status  = not_counted     blocker = count_endpoint_unavailable
http    = 500 server_error（error_code 500）
message_sha256 = bfd4dade…    exit = 70
cleanup = server_stopped / port_released / private_artifacts_removed 均为 true
```

探针失败会给出另一个 code（`count_endpoint_probe_failed`），本次没有出现，因此服务与 count endpoint
本身正常，失败发生在真实归档请求上。

## 疑难问题：根因定位

阻断不在长度，也不在 reasoning，而在**会话角色顺序**：

- `common/chat.cpp` 的 `map_developer_role_to_system` 在套用模板**之前**把 `developer` 统一改成 `system`。
- 冻结 Ministral 模板规定 `assistant` 之后只能接 `assistant`/`user`/`tool`，遇到 `system` 直接
  `raise_exception`。minja 抛 `std::runtime_error`，服务端 `ex_wrapper` 兜底成 **500**；
  只有 `std::invalid_argument` 才映射成 400。
- 47 条真实 v2 请求的角色序列：成功计数过的 24 条是 `developer,user,user`（没有 assistant 轮）；
  另外 23 条都是 `… assistant → developer → user`。
- 离线用同一份冻结模板渲染这 47 条 v2 请求：**24 渲染成功 / 23 抛
  `Unexpected role 'system' after role 'assistant'`**，与 Plan 024 真实运行的
  24 计数 / 21 形状拒绝 / 2 条未定性 500 逐条对应。

因此 v1 时代的「21 条 400 + 2 条 500」其实是同一个根因：v2 移除 encrypted-only reasoning item 只消掉了
先触发的 400，把那 21 条推进到同一处 500。修复方向是在公共 builder 做一次 provider-neutral 的角色顺序窄兼容
（属 static payload 语义，本任务 §2 明确不允许改），已交回 WBS。

## 另一处已记录但未修的缺陷

`count_input_tokens` 的默认 code 使「锚点 500」与「循环中某条 500」都表现为
`count_endpoint_unavailable`，报告也不给已计数条数。本次可排除 `anchor_token_count_mismatch`，
但**锚点 5,313 未被本次运行直接复证**；按探针通过 + 锚点离线可渲染（遍历位置 28）+ 遍历首条离线 raise
推断，中断点是循环第一条。用户只允许模型运行前做窄修，此缺陷运行后才暴露，留给后续任务。

## 验收结果

- 47/47：**未达成**，本次 0 条新计数；无法给出全集 4k/8k fit 数，也不存在正式 baseline。
- 两次一致性：**不适用**（只运行一次）。
- focused tests `test_contracts_and_evidence.py` + `test_local_approval.py`：109/109 通过。
- 依赖锁：`uv lock --directory eval --check` 85 packages 通过。未按原样跑 `just eval-lock` ——
  该配方硬编码 `$PWD/eval-data/uv-cache`，本 worktree 无 `eval-data/`，改用主仓 cache 的等价命令。
- 清理与状态：8080 空闲、无 GPU 计算进程、`eval-data/local-approval/` 无本任务残留、`git status` 干净；
  doctor 报 `model_backed_validation: not_run`、`runtime_capability:
  linux_cuda_built_model_unvalidated`，无新增资格成功 evidence。
- 未运行：第二次 census、Cargo、Docker、云 API、全量 eval、任何 generation。
