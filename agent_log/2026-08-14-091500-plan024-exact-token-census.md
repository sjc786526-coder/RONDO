# Plan 024 WP3b-A2：真实 `E_final` exact-token 普查

日期：2026-08-14 ｜ 分支：`024-wp3b-a2-exact-token-census` ｜ 未合并、未推送

## 结论

47 条真实 `E_final` 全部走冻结 b10333 CUDA runtime + 唯一 GGUF + 冻结模板做了一次只计数、不生成的普查。
两个决定性事实：

1. **长度**：24 条可计数，min 5,313、p50 7,886、p90 11,105、p95 12,354、max 18,921。
   按 `input_tokens + 512` 判断，**4k 覆盖 0/24，8k 覆盖 9/24**（12k 22/24、16k 23/24、24k 24/24）。
2. **形状**：另 23 条被冻结运行时直接拒绝，与上下文档位无关。21 条是 Responses adapter 400
   `item['content'] is not an array`——归档里的 `reasoning` item 有 `summary` 但没有数组 `content`；
   2 条是冻结聊天模板 500。真实 `/v1/responses` 判定路径会被同样拒绝，**加大上下文救不回这 23 条**。

Plan 023 的锚点精确复现 **5,313**。能力保持 `linux_cuda_built_model_unvalidated`，未新增任何资格证据。

## 实质性改动

- **新增 `eval/rondo_eval/local_approval/token_census.py`**：完整集合建立（47 条、去重、逐条经生产
  `_read_safe_evidence_file` + `_validate_guardian_meta`，期望 Guardian 模型/effort 取自受跟踪
  `eval/results/runs.jsonl`，不按 run outcome 筛样，infra-failed run 的归档同样纳入）；复用真实
  `LocalApprovalClient.build_request` 构造请求；经 count-only `POST /v1/responses/input_tokens` 计数；
  统计、稳定排序与 JSON 输出。服务用 `_sanitized_environment()` 启动，不进 secret loader、不读 `.env.local`。
- **`qualification.py`**：`_prepare_private_directory` 增加 `prefix` 形参（默认值不变），让普查的私有目录可区分。
- **测试**：`eval/tests/test_local_approval.py` 新增 `TokenCensusTests` 9 项——集合完整性/去重、账本身份缺失、
  `input+512` 边界与分位算法、稳定排序与 digest、锚点不匹配即停、逐条拒绝仍继续、锚点被拒即停。
  不重复覆盖既有 reader/meta 行为。
- **结果**：`eval/results/baselines/local-approval-exact-token-census-v1.json`（version/identity/anchor/records/summary/digest，
  逐条只存 `e_final_sha256`、shape、status、token 数与 fit，不存正文）。

## 疑难问题

**同一条请求在 `/v1/responses` 能被 tokenizer 处理，在 `/v1/responses/input_tokens` 却 400。** 最初的实现把
所有 HTTP 失败都归成一个 `count_endpoint_unavailable`，报不出到底是服务坏了还是这条证据不可服务，
连续两次真实运行都只拿到这一个码。定位分三步：

1. 加合成短证据探针（与真实请求同构、内容无关），证明 endpoint 与请求形状本身没问题；
2. 加"回显守则"后才敢报服务端错误原文——只有当消息里任何 12 字符片段都不出现在请求体内时才输出，
   否则整条替换为 `<redacted>`。由此拿到 `item['content'] is not an array`；
3. 对照冻结源码 `tools/server/server-chat.cpp` 确认是 Responses→ChatCompletions 转换对 `reasoning` item 的硬要求。

随后又暴露第二类：2 条走到冻结模板才被 500 拒绝（消息回显请求内容，按守则未输出原文）。
最终把 `400 invalid_request_error` 与 `500 server_error` 都记为**逐条拒绝**而不是整批 fail-closed，
并在每次拒绝后立即重跑合成探针——服务只要还健康，就证明这是该条证据自身的属性；探针失败则整次普查失败。
这样 47 条全部登记、统计口径显式标注只覆盖 counted，既不漏报也不把 24 条的分布一起埋掉。

代价是共消耗 **7 次模型生命周期**（5 次定位 + 2 次正式普查），每次都是先定位再修再跑，没有靠重试掩盖。

## 验收结果

- focused tests：`test_local_approval` + `test_config_hardening` + `test_config_and_artifacts` 共 123 项通过；
  `just eval-lock` 85 packages 通过。未跑 Rust、Docker、全 workspace、全量 eval。
- 真实运行：同一入口两次，结果文件逐字节相同（sha256 `c6c848b1…`，文档内 digest `5aa508af…`），
  锚点两次都是 5,313。全程未调用生成端点，`generated_tokens=0`。
- 收尾：capability 仍 `linux_cuda_built_model_unvalidated`、`model_backed_structured_output` 仍 `not_run`、
  `eval/locks/local-approval-b10333-ministral-4k-v1.json` 不存在；两次运行的 server、8080、私有临时对象
  全部清理，GPU 无 compute process，普查用临时结果文件已删除。
- 未做：8k 试跑、压缩/裁剪实现、配置或资格档位改动、Turn B、L7、Local M3、训练。
