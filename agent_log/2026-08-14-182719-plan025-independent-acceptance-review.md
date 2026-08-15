# Plan 025 WP3b-A2a 独立审查验收报告

- 日期：2026-08-14
- 审查对象：`025-wp3b-a2a-static-payload-v2@41bc1f3`（parent `53b5f75`）
- 审查范围：Plan 025 合同、提交差异、static payload v2 投影、Local/census 共用路径、focused tests、
  47 份归档聚合式只读构造、两份 WBS 与历史记录
- 审查边界：未运行真实模型、GPU、census、Cargo、Docker、云 API 或全量 eval；未合并、未推送；
  未读取 `.env.local`，未输出或保存归档正文、正文派生内容或完整请求体

## 结论

**验收不通过，`41bc1f3` 暂不得合并。**

公共 v2 builder、v1/v2 分界、三个 consumer 同字节、Local/census 共用 builder、已知 24 个 encrypted-only item
移除以及 47/47 静态构造都已正确落地；独立复跑的 106 项 focused tests、eval lock 与 47 条聚合检查均通过。

阻断点很窄但触及本任务核心安全语义：实现把 reasoning `content` 内的 `reasoning_text` 和 `text` 认定为
“公开内容”，并转成普通 assistant `output_text`。冻结 Codex v0.147.0 源码却明确把这两个 subtype 一并映射为
`raw_content`，默认输出只展示 summary，只有显式打开 raw-agent-reasoning 才展示它们。因此当前实现会在未来遇到
含明文 `content` 的归档时，把隐藏推理变成发往 Luna/Sol/Local 的普通证据，违反 Plan 025 的“不暴露 raw
reasoning”硬约束。现有 47 份归档都没有 `content`，所以 47/47 通过无法覆盖这一风险。

另有一个直接的 fail-closed 缺口：`internal_chat_message_metadata_passthrough` 被列为已知 reasoning 字段，
但任何值（包括整数）都会被静默丢弃；这与“malformed reasoning 形状拒绝”不一致。

## 审查者代用户作出的决定

1. **只把 `summary[].summary_text` 视为可公开投影的 reasoning 文本。** `content[].reasoning_text` 与
   `content[].text` 均按冻结 Codex 语义视为 raw reasoning，不得进入 v2 canonical payload 或任一 provider 请求。
2. **已知 raw content 先校验形状，再丢弃，不要求用户另行选择。** 有 summary 时只投影 summary；只有 raw
   content、没有 summary 时整项删除。未知 content subtype、未知字段或 malformed 值仍 fail-closed。
3. **可选 passthrough metadata 必须先按冻结结构做最小形状校验再丢弃。** 至少非对象、未知键和明显错误类型
   应拒绝；无需为此建立新的 schema registry、审计设施或长期 CLI。
4. **当前不加载真实模型，也不重跑 census。** 先完成上述窄整改、focused regressions 和文档状态修正；
   通过复审后，真实模型重跑仍按 WBS 作为后续独立授权事项。
5. **不接受当前“Plan 025 已完成”文档状态。** `doc/WBS.md`、方向 2 WBS 与 WBS-COMPLETED 中的完成声明应随
   窄整改一并修正；本轮审查不改 capability、baseline、qualification 或 launcher gate。

## 阻断发现

### F1（Blocker）：raw reasoning 被投影为普通 assistant 证据

实现将 `reasoning_text` 与 `text` 放入公开 subtype 白名单，并把 summary 与 content 全部串接成
`message(role=assistant, content=[output_text...])`：

- `eval/rondo_eval/evidence.py:64-69,305-351`
- `eval/tests/test_contracts_and_evidence.py:75-87,197-224`

冻结上游源码给出的语义相反：

- `codex-source-code/codex-rs/core/src/event_mapping.rs:196-220` 将 summary 映射为 `summary_text`，将
  `ReasoningText` 和 `Text` 一并映射为 `raw_content`；
- `codex-source-code/codex-rs/exec/tests/event_processor_with_json_output.rs:331-361` 明确测试
  `reasoning_items_emit_summary_not_raw_content`；
- `codex-source-code/codex-rs/exec/src/event_processor_with_human_output_tests.rs:85-104` 证明默认隐藏 raw，
  只有显式启用 raw-agent-reasoning 才展示；
- `codex-source-code/codex-rs/protocol/src/models.rs:1343-1349,1714-1725` 也将两个 subtype 定义在
  `ReasoningItemContent` 下，并对 `ReasoningText` 采用特殊序列化抑制。

独立合成复现只输出布尔值，结果为：

```text
raw_reasoning_text_forwarded=true
raw_text_forwarded=true
```

这不是“文本已在归档中明文出现就等于公开”的问题；Plan 025 约束的是语义上的公开内容，冻结 Codex 对字段的
显示策略与命名共同证明这些字段是隐藏/raw 推理。应保留公开 summary，校验后丢弃 raw content。

### F2（Medium）：已知 reasoning metadata 的 malformed 值被静默接受

`eval/rondo_eval/evidence.py:55-62` 允许 `internal_chat_message_metadata_passthrough`，但
`_project_reasoning_item()` 没有读取或验证该值。独立合成输入把它设为整数 `7`，builder 仍成功并删除整项，结果为：

```text
malformed_metadata_accepted=true
```

冻结类型是可选 `InternalChatMessageMetadataPassthrough` 对象（
`codex-source-code/codex-rs/protocol/src/models.rs:781-795,849-860`）。窄整改只需在丢弃前验证已知结构；
不需要扩展为通用可信或审计系统。

## 已通过且可保留的部分

- static input payload 显式为 v2，decision output schema 继续为 v1；v1 payload 和 v1 policy identity 不能通过 v2 sink。
- reasoning 投影只位于公共 `build_static_payload()`；Local client 与 token census 未另造 provider-specific 路径。
- 已知 21 份归档的 24 个 encrypted-only、空 summary、无 content item 会被删除，原始 `type=reasoning`、
  `encrypted_content` 和 provider session id 不进入请求。
- Standard/Responses Lite 等价与三个 consumer canonical bytes 一致的合同已建立；最终 validator 会拒绝
  `type=reasoning` 和 `encrypted_content` 回流。
- tool authorization/private transport 清理保持，合法 `tool_search_output.tools` 证据未被误删。
- 47 条归档聚合式只读检查独立通过：47 个 v2 payload、47 条 Local request、三 consumer bytes 全部一致，
  出站 private transport 残留为 0；检查未打印正文。
- capability 和 qualification/launcher 文件不在提交差异内；census baseline 仍不存在。

## 独立验证

| 验证 | 结果 |
|---|---|
| `git diff --check 53b5f75..41bc1f3` | 通过 |
| 提交范围 | 实际为 9 files，`+517/-57`；执行者摘要所写 8 files、`+465/-57` 不准确，但不构成代码阻断 |
| focused unittest：evidence + local approval | 106/106 通过，13.054s |
| `uv lock --directory eval --check`（共享 cache） | 通过，85 packages |
| 47 条生产 reader/meta/builder 聚合检查 | 47/47 v2；47/47 Local request；三 consumer bytes 一致；private residual 0 |
| raw-content 合成复现 | `reasoning_text` 与 `text` 均会进入当前 canonical payload |
| malformed metadata 合成复现 | 整数值被当前 builder 静默接受并丢弃 |
| census baseline | 不存在 |
| 主工作区与相邻 worktree | 审查开始时 main clean `a66f497`；024 未改；025 仅任务提交 |

## 窄整改后再复审

1. 从“公开文本”投影中移除 `reasoning_text`/`text`；已知 raw content 仅校验后丢弃，summary-only 投影保持逐字节原文和顺序。
2. 增加少量直接回归：summary + raw content 只保留 summary；raw-only item 等价于不存在；两个已知 raw subtype
   都不出站；未知/malformed content 仍拒绝；malformed passthrough metadata 拒绝。
3. 把当前把 raw content 称为公开内容的代码注释、测试命名、Plan 当前状态、两份 WBS 和 WBS-COMPLETED 完成声明修正为准确事实。
4. 复跑现有 106 项 focused tests、eval lock 与一次 47 条聚合式只读构造即可；无需新增长期检查设施，
   无需真实模型、Cargo、Docker、云 API 或全量 eval。
5. 在同一任务分支提交窄整改并交回独立复审；仍不合并、不推送、不删除 worktree。
