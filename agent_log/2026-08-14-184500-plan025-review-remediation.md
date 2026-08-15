# 2026-08-14 Plan 025：首轮独立审查整改

针对 `2026-08-14-182719-plan025-independent-acceptance-review.md` 的 F1/F2。两条都独立复核成立并已整改。
前一份日志 `2026-08-14-181740-plan025-static-payload-v2.md` 记录的是整改**前**的实现，
其中把 `reasoning_text`/`text` 称为"公开内容"这一判断是错的，以本篇为准。

## F1（Blocker）：raw reasoning 曾被投影为普通证据

- **复核**：冻结上游 `core/src/event_mapping.rs` 把 `ReasoningItemContent::{ReasoningText, Text}` 一并映射为
  `raw_content`（summary 单独映射为 `summary_text`）；`exec/src/event_processor_with_human_output.rs`
  的 `reasoning_text()` 只有在 `show_raw_agent_reasoning` 为真时才取 content，默认取 summary。
  所以这两个 subtype 在冻结语义里是默认隐藏的 raw 推理，不满足 Plan「语义明确的公开内容」，
  投影它们会违反「raw/encrypted reasoning 不出站」。审查结论成立。
- **整改**：`_project_reasoning_item()` 只把 `summary[].summary_text` 转成中立 assistant 消息；
  `content[]` 先按已知 raw 形状（`reasoning_text`/`text` + 字符串 `text`，无多余键）校验，再整体丢弃；
  没有公开 summary 的 item 整项删除。未知 subtype、缺 `text`、非字符串 `text`、非对象条目仍 fail-closed。
- **为什么仍要校验再丢**：不校验的话，一个无法理解的形状会以"反正要丢"的名义通过，
  这正是 Plan 要求 fail-closed 的场景。

## F2（Medium）：passthrough metadata 任意值被静默接受

- **复核**：`protocol/src/models.rs` 的 `InternalChatMessageMetadataPassthrough` 是强类型可选对象
  （`turn_id: Option<String>`、warehouse-only `executed_tool_calls`）。原实现把该字段列入已知字段后
  未做任何校验，整数 `7` 也能通过。成立。
- **整改**：`_require_known_passthrough()` 在丢弃前校验：必须是对象、键在冻结结构内、
  `turn_id` 为字符串或缺省、`executed_tool_calls` 为数组或缺省；否则 fail-closed。

## 回归与文档

- 新增/调整测试：只投影 summary、raw content 被丢且不出站（两个 subtype 各一）、
  raw-only 与 encrypted-only item 都等价于不存在、malformed raw content 与 malformed passthrough 拒绝；
  Local client 用例的证据加入 raw content，断言出站请求里不含它。
  测试 fixture 名从 `PUBLIC_REASONING` 改为 `SUMMARY_AND_RAW_REASONING`，避免继续把 raw 叫成 public。
- 文档：Plan 当前状态与决策 006、`doc/WBS.md`、方向 2 WBS 的完成声明改为"实现已落地、待复审"；
  撤回上一轮写入 `doc/WBS-COMPLETED.md` 的完成记录，等复审通过后再写。

## 验收（整改后，全部本地，无模型/GPU/网络）

- focused tests：`test_contracts_and_evidence.py` + `test_local_approval.py` 108/108 通过（较上轮 +2 项）。
- `just eval-lock`：85 packages 通过。
- 47/47 只读静态构造复跑：47/47 建成 payload v2、三 consumer 逐字节一致、47/47 Local 请求构造成功；
  24 个 reasoning item 全部因无公开 summary 被删除，0 条走投影分支；出站 `type=reasoning` 与
  `encrypted_content` 残留均为 0。只输出计数与布尔，未输出正文或完整请求体，未读取 `.env.local`。
- 未运行：真实模型、GPU、census 重跑、Cargo、Docker、云 API、全量 eval。结论仍限于构造层与合同层。

## 复审补充整改（同批次）

复审报告 `2026-08-14-184600-plan025-remediation-recheck.md` 判定 F1 已闭环、F2 只闭合到 metadata 外层：
`executed_tool_calls` 只验证为数组，元素不验，`[7]`、空对象、缺字段或带未知键的对象都会以"数组合法"
通过并被删除。复核成立 —— 冻结 `ExecutedToolCall`（`protocol/src/models/executed_tool_calls.rs`）是
`name: String` + `arguments: ExecutedToolCallArguments`（untagged `serde_json::Value`），两个字段都不可选，
所以线上形态就是恰好两个键。

- **整改**：`_require_known_executed_call()` 要求每个元素是对象、键恰为 `{name, arguments}`、
  `name` 为字符串；`arguments` 保持任意 JSON（含 null 与 truncated 变体的对象形态），不扩大验证体系。
  校验通过后 metadata 仍整体删除，warehouse-only calls 不进入 static payload。
  该校验只作用于 reasoning 边界，其他 item 类型维持既有 v1 处理，不在本任务范围内改动。
- **回归**：新增 1 项正向用例（4 种 `arguments` 形态都通过且 metadata 被整体删除），
  畸形用例扩充 5 条（非数组、`[7]`、缺 `arguments`、`name` 非字符串、未知键）。
- **文档勘误**：方向 2 WBS 第 335 行的"兼容已完成"改为"待复审"；本日志开头的错误时间占位改为真实前序日志名。
- **复跑**：focused tests 109/109、`just eval-lock` 85 packages、47/47 只读静态构造均通过，
  47 条结果与上一轮完全一致（24 个 item 全删、0 条投影、私有运输残留 0）。
