# Plan 025 WP3b-A2a 首轮整改复审报告

- 日期：2026-08-14
- 审查对象：`025-wp3b-a2a-static-payload-v2@28339e4`（parent `90fa8e9`）
- 审查范围：首轮报告 F1/F2、同一 reasoning 投影边界的相邻形状、focused tests、eval lock、
  47 份归档聚合式只读构造与当前文档状态
- 审查边界：未运行真实模型、GPU、census、Cargo、Docker、云 API 或全量 eval；未合并、未推送；
  未读取 `.env.local`，未输出或保存归档正文、正文派生内容或完整请求体

## 结论与当前任务状态

**整改验收仍不通过，`28339e4` 暂不得合并；当前状态是“实现与整改批次已完成，但任务验收失败”，不是
Plan 025 已完成。**

F1 已完整闭环：只有 `summary[].summary_text` 被投影；`content[].reasoning_text` 与 `content[].text`
都按 raw reasoning 校验后删除，raw-only item 等价于不存在，Local 请求也不含 raw 文本。

F2 只闭合了 metadata 外层。`internal_chat_message_metadata_passthrough.executed_tool_calls` 目前只验证为数组，
不验证数组元素；整数、缺必需字段或未知形状会以“数组合法”的名义静默通过并被删除。这与 Plan 025 的
malformed/未知 reasoning 形状 fail-closed，以及本次“先理解再丢弃”的整改原则直接冲突。它不造成正文泄露，
也不影响当前 47 份归档，但仍是完成合同内的窄缺口。

## 首轮发现闭环情况

### F1（Blocker）：已闭环

- `eval/rondo_eval/evidence.py:309-372` 只收集 summary text；两个已知 raw content subtype 均严格校验后丢弃。
- summary + raw、两个 raw subtype、raw-only 与 Local 出站均有直接回归。
- 独立合成复现只输出布尔值：`summary_preserved=true`、`raw_reasoning_removed=true`、
  `raw_text_removed=true`。

### F2（Medium）：部分闭环，仍阻断验收

`eval/rondo_eval/evidence.py:375-386` 已拒绝非对象 metadata、未知 metadata 键、非字符串 `turn_id` 和
非数组 `executed_tool_calls`，但没有检查 calls 的元素。

冻结结构明确是 `Option<Vec<ExecutedToolCall>>`，其中每个 `ExecutedToolCall` 是带字符串 `name` 和
`arguments` 的对象：

- `codex-source-code/codex-rs/protocol/src/models.rs:781-795`
- `codex-source-code/codex-rs/protocol/src/models/executed_tool_calls.rs:229-247`

独立合成复现：

```text
nonobject_executed_call_rejected=false
```

即 `executed_tool_calls: [7]` 当前会通过 builder。相同原因也会让空对象、缺 `name`/`arguments` 或未知键
被静默吞掉。

## 审查者代用户作出的决定

1. **F2 必须闭合到数组元素的最小已知结构。** 每个 call 至少必须是对象，字段与冻结序列化形态一致，
   `name` 为字符串且存在 `arguments`；`arguments` 本身可保持任意 JSON 值，因为冻结类型就是
   `serde_json::Value`。未知字段继续 fail-closed。
2. **通过校验后仍整体删除 metadata。** 不把 warehouse-only calls 引入 static payload，也不建立新的
   metadata schema registry、审计设施或长期命令。
3. **只补少量直接回归。** 覆盖非对象 call、缺必需字段/错误 `name`、未知字段；无需扩大到全量 eval。
4. **当前继续不加载真实模型、不重跑 census。** 该缺口完全可由合成合同测试闭合；47 条聚合检查在窄修后
   再复跑一次即可。
5. **两个文档勘误与窄修一并处理。** `doc/WBS/local-approval-model.md:335` 仍提前写“兼容已完成”，应在
   最终复审前保持“待复审”；整改日志 `:4` 的 `…-181620` 是错误占位，应改为真实前序日志
   `2026-08-14-181740-plan025-static-payload-v2.md`。这些是低风险文档问题，不是新的代码阻断。

## 已通过且可保留的部分

- static payload v2、decision schema v1、v1/v2 sink 分界均正确。
- reasoning 投影仍只发生在公共 `build_static_payload()`，三个 static consumer 使用同一 canonical bytes。
- F1 的 raw reasoning 不出站语义、summary 顺序与原 UTF-8 文本保留、raw-only 删除均正确。
- Local client 与 token census 共用同一 v2 request builder；census focused test 比较真实 builder request bytes。
- 工具授权、`encrypted_function_args`、`executed_tool_calls`、reasoning `encrypted_content` 和 provider id
  不进入当前 canonical payload；最终 validator 拒绝伪造回流。
- 47/47 归档通过生产 reader/meta/builder 的聚合式只读构造：47 个 v2 payload、47 条 Local request、
  三 consumer bytes 一致、private transport residual 为 0。
- capability、qualification、launcher、baseline 与受保护范围未被修改；census baseline 仍不存在。
- 执行者本轮统计准确：`28339e4` 为 8 files、`+227/-72`；从 `53b5f75` 到当前、排除审查报告后为
  9 files、`+672/-57`。

## 独立验证

| 验证 | 结果 |
|---|---|
| `git diff --check 90fa8e9..28339e4` | 通过 |
| focused unittest：evidence + local approval | 108/108 通过，12.108s |
| `uv lock --directory eval --check`（共享 cache） | 通过，85 packages |
| 47 条生产 reader/meta/builder 聚合检查 | 47/47 v2；47/47 Local request；三 consumer bytes 一致；private residual 0 |
| F1 合成复现 | summary 保留；两个 raw subtype 均不进入 canonical payload |
| F2 相邻合成复现 | scalar metadata 拒绝；`executed_tool_calls:[7]` 未拒绝 |
| census baseline / worktree `eval-data` | baseline 不存在；未产生 worktree-local cache/artifact |
| 主工作区与相邻 worktree | 审查开始时 main clean `a66f497`；024 未改；025 在 `28339e4` clean |

## 最小剩余整改

1. 给 `_require_known_passthrough()` 增加 calls 元素的最小结构校验，并补上述三类直接测试。
2. 修正方向 2 WBS 的一处提前完成表述和整改日志的一处错误时间占位。
3. 复跑 evidence/local-approval focused tests、eval lock 与一次 47 条聚合式只读构造；不增加其他设施或重型门禁。
4. 同一任务分支提交后再交独立复审；通过前不写 WBS-COMPLETED、不合并、不推送、不删除 worktree。
