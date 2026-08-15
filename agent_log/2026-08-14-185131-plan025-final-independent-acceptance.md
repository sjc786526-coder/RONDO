# Plan 025 WP3b-A2a 最终独立验收报告

- 日期：2026-08-14
- 审查对象：`025-wp3b-a2a-static-payload-v2@422a90f`（parent `4317dea`）
- 审查范围：前两轮报告的 F1/F2、补充整改、同一 reasoning 投影边界、focused tests、eval lock、
  47 份归档聚合式只读构造与最终文档状态
- 审查边界：未运行真实模型、GPU、census、Cargo、Docker、云 API 或全量 eval；未合并、未推送；
  未读取 `.env.local`，未输出或保存归档正文、正文派生内容或完整请求体

## 结论与任务状态

**验收通过。Plan 025 已完成，不是 completed-with-failure。**

`422a90f` 完成了最后一个窄缺口：reasoning passthrough 中的 `executed_tool_calls` 不仅要求为数组，
每个元素还必须是冻结 `ExecutedToolCall` 的已知序列化形态（恰有 `name` 与 `arguments`，且 `name` 为字符串），
校验后 metadata 仍整体删除。非对象、缺字段、错误 name 与未知字段均 fail-closed。

前两轮发现现已全部闭环，未发现新的任务内实现阻断。

## 审查闭环

- **F1 已闭环**：只有 `summary[].summary_text` 被投影；`reasoning_text` 与 `text` 均作为默认隐藏的
  raw reasoning 校验后丢弃，raw-only item 等价于不存在，Local 请求不含 raw 文本。
- **F2 已闭环**：metadata 外层、`turn_id`、calls 数组与 calls 元素均按冻结形态验证；所有 metadata
  通过验证后仍删除，不进入 canonical payload。
- **版本与共用路径正确**：static input 为 v2，decision output 保持 v1；v1 payload/identity 不能通过 v2 sink；
  reasoning 投影只在公共 builder，Local client 与 census 使用同一 request builder。
- **私有与工具字段正确**：原始 reasoning、encrypted content、provider id、raw content、warehouse-only calls、
  `encrypted_function_args`、顶层 tools/Lite additional tools 均不出站，合法 `tool_search_output.tools` 仍保留。
- **未知形状正确拒绝**：reasoning 未知字段/subtype、malformed summary/raw content/metadata/call 均有直接回归。

## 审查者代用户作出的决定

1. `arguments` 保持任意 JSON 值，不增加 Python 专用递归 JSON validator。生产输入来自已解析的 `E_final` JSON，
   冻结字段本身是 `serde_json::Value`；继续深挖语言内部不可达值会偏离本任务且没有收益。
2. 不扩展 validation 到其他 item 的既有 v1 metadata 处理。补充校验只属于 Plan 025 新增的 reasoning 投影边界，
   避免把本次兼容任务扩大成全 evidence schema 重构。
3. 不运行真实模型或重跑 census。当前验收只确认 provider-neutral v2 构造合同；真实可服务性、2 条通用 500、
   上下文档位与 baseline 均留给 WBS 后续任务和新的真实模型授权。
4. 验收通过后立即把 Plan、两份 WBS 和 WBS-COMPLETED 收口为当前事实；任务分支仍不合并、不推送，等待用户决定。

## 独立验证

| 验证 | 结果 |
|---|---|
| `git diff --check 4317dea..422a90f` | 通过 |
| focused unittest：evidence + local approval | 109/109 通过，12.616s |
| `uv lock --directory eval --check`（共享 cache） | 通过，85 packages |
| 47 条生产 reader/meta/builder 聚合检查 | 47/47 v2；47/47 Local request；三 consumer bytes 一致；private residual 0 |
| F1 合成复现 | summary 保留；两个 raw subtype 与 metadata 均删除 |
| F2 合成复现 | 非对象、缺 arguments、错误 name、未知 call 字段全部拒绝 |
| census baseline / worktree `eval-data` | baseline 不存在；未产生 worktree-local cache/artifact |
| 主工作区与相邻 worktree | 审查开始时 main clean `a66f497`；024 未改；025 在 `422a90f` clean |

## 交付边界

Plan 025 的实现、整改、测试和独立验收均已完成。当前分支和 worktree 保留，未合并、未推送。
后续重跑 47/47 exact-token census 需要新的真实模型授权；本报告不对真实 b10333 可服务性、两条通用 500、
baseline 或上下文档位作超出证据的结论。
