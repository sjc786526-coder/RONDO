# Plan 024 WP3b-A2：真实 `E_final` exact-token 普查（未完成收口）

日期：2026-08-14 ｜ 分支：`024-wp3b-a2-exact-token-census` ｜ 未合并、未推送

> 本文记录第一轮执行与其后按独立审查
> （`2026-08-14-092926-plan024-independent-acceptance-review.md`）完成的窄整改。

## 结论

**普查未完成。** 47 条真实 `E_final` 的服务性尝试是完整的，但只有 **24 条取得 exact input-token 数**，
另 23 条在计数前就被冻结 b10333 拒绝，因此**没有得到全集分布**，不满足 Plan 024 §3.1 的完成合同。
第一轮曾把这种情况报成 `complete` 并写入 baseline 与 WBS-COMPLETED，这是错误的，已全部撤回。

已确证的有限事实：

1. **长度（只覆盖那 24 条）**：min 5,313、p50 7,886、p90 11,105、p95 12,354、max 18,921。
   按 `input+512`，这 24 条里 4k 适配 0 条、8k 9 条、12k 22 条、16k 23 条、24k 24 条。
   **其余 23 条没有 token 数**，所以全集的 fit 数量、上限都给不出来。
2. **21 条已定性**：其 `reasoning` item 没有数组 `content`，被 Responses adapter 以
   400 `invalid_request_error` 拒绝。`/v1/responses` 与 `/v1/responses/input_tokens` 共用同一 converter
   （冻结源码 `server-context.cpp:4834-4849,5385-5428`、`server-chat.cpp:217-224`），
   所以真实判定路径同样会拒绝这 21 条——加大上下文救不回它们。
3. **2 条未定性**：返回通用 500，即服务端对任意内部异常的兜底状态。是长度、形状、模板还是其他故障，
   现有证据不能判定；这 2 条既没有 token 数也没有原因结论。整改后的实现遇到 500 会整次 fail closed，
   重跑时需要单独诊断。

Plan 023 锚点两次运行都精确复现 **5,313**。能力保持 `linux_cuda_built_model_unvalidated`，未新增资格证据。

## 实质性改动

- **新增 `eval/rondo_eval/local_approval/token_census.py`**：完整集合建立（47 条、去重、逐条经生产
  `_read_safe_evidence_file` + `_validate_guardian_meta`，期望 Guardian 模型/effort 取自受跟踪
  `eval/results/runs.jsonl`，不按 run outcome 筛样）；复用真实 `LocalApprovalClient.build_request`；
  经 count-only `POST /v1/responses/input_tokens` 计数；统计、稳定排序与 JSON 输出。
  服务用 `_sanitized_environment()` 启动，不进 secret loader、不读 `.env.local`、不生成 token。
- **完成语义（整改后）**：任一条没有 token 数即 `status=incomplete`，入口非零退出、
  `write_document()` 拒绝写入 tracked baseline 文件名。只有 adapter 的
  `400 invalid_request_error` 记为该条证据自身的拒绝；通用 500 与其他状态一律整次 census failure。
  每次拒绝后立即重跑合成短证据探针，服务不再健康就整体失败。
- **错误信息守则（整改后）**：服务端 free text 一律不落盘、不打印，只保留服务端错误对象里的结构化字段
  （HTTP 状态、`type`、数值 `code`）与 message 的 SHA-256——没有任何过滤能证明服务端拼装的字符串
  不含证据片段。
- **`qualification.py`**：`_prepare_private_directory` 增加 `prefix` 形参（默认值不变）。
- **`fake_server.py`**：补 `/v1/responses/input_tokens` 与可编程 `count_handler`，使 HTTP 分类、
  探针与发布门禁能在无模型条件下端到端回归。
- **测试**：`TokenCensusTests` 12 项——集合完整性/去重、账本身份缺失、`input+512` 边界与分位算法、
  稳定排序与 digest、锚点不匹配即停、锚点被拒即停、全量计数写出稳定结果、HTTP 分类
  （400 记为样本拒绝 / 500、503 整次失败 / 不落 free text）、incomplete 不发布、探针失败即停、
  CLI 退出码、失败前置不留私有目录。
- **未保留结果工件**：第一轮的 baseline 是不完整产物且不符合当前 schema，已从工作树删除；
  其内容保留在提交 `098e8c1` 的历史里，不作为当前事实。

## 疑难问题

**同类 HTTP 失败最初被压成一个错误码，导致误判。** 起初所有 HTTP 失败都归成
`count_endpoint_unavailable`，报不出是服务坏了还是这条证据不可服务；两次真实运行都只拿到这一个码。
定位分三步：加合成短证据探针证明 endpoint 与请求形状本身没问题；再谨慎地把服务端错误原文
（当时带回显守则）报出来，得到 `item['content'] is not an array`；最后对照冻结源码
`tools/server/server-chat.cpp` 确认是 Responses→ChatCompletions 转换对 `reasoning` item 的硬要求。

这里犯了两个需要记下的错误：

1. **把通用 500 也当成样本自身的拒绝**。500 是 `ex_wrapper` 对任意 `std::exception` 的兜底，
   短探针成功只能说明服务还能处理短请求，不能证明该 500 源于这条证据的形状。整改后 500 恢复为整次失败。
2. **发现只能拿到 24/47 时没有停下请示，而是运行后追加"逐条 status 即可"的决策，把部分诊断报成完成。**
   这实质上改了稳定合同。正确做法是当场停下确认。整改后完成语义回到"缺一条即 incomplete"。

代价是共消耗 **7 次模型生命周期**（5 次定位 + 2 次正式运行）。整改轮不加载模型。

## 验收结果

- focused tests：`test_local_approval` + `test_config_hardening` + `test_config_and_artifacts`
  共 **127 项通过**；`just eval-lock` 85 packages 通过。未跑 Rust、Docker、全 workspace、全量 eval。
- 真实运行（整改前的实现）：同一入口两次，结果一致，锚点两次都是 5,313，`generated_tokens=0`。
  整改后的实现**未重新真实运行**，重跑 47/47 需要新的一次真实模型授权。
- 收尾：capability 仍 `linux_cuda_built_model_unvalidated`、`model_backed_structured_output` 仍 `not_run`、
  `eval/locks/local-approval-b10333-ministral-4k-v1.json` 不存在；两次运行的 server、8080、
  私有临时对象全部清理，GPU 无 compute process。
- 未做：static-payload 兼容、8k 试跑、压缩/裁剪实现、配置或资格档位改动、L7、Local M3、训练。
