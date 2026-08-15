# 2026-08-14 Plan 027 / WP3b-A2c 整改最终独立验收

- 审查对象：`027-wp3b-a2c-role-compat-census-diagnostics@cb66816`（整改基线 `0603008`，任务基线
  `78aefb1`）
- 审查范围：首轮报告的两处阻断、事实表述修正、focused tests、eval lock、47 条归档的无模型只读聚合检查
- 审查边界：未加载真实模型，未运行 census/count endpoint、generation、Cargo、Docker、云 API 或全量 eval；
  未读取 `.env.local`，未输出证据正文、完整请求或服务端自由文本

## 结论与项目状态

**验收通过。Plan 027 / WP3b-A2c 任务目标完成。**

`cb66816` 已按首轮报告关闭两处阻断，整改范围保持在共享中立消息校验、拒绝后探针的最小定位 facts、
对应回归和事实表述，没有扩建审计、可信、provenance、attestation 或 schema registry。独立复验未发现
新的任务内功能性或正确性阻断。

上面的“任务完成”只指 Plan 027。上层 WP3b-A2 exact-token 普查仍为 `blocked/incomplete`：全集仍只有旧的
24/47 exact count，没有正式 baseline，未选择上下文档位，Plan 026 的具体 500 仍未解释，capability 保持
`linux_cuda_built_model_unvalidated`，qualification 状态不变。

## 首轮阻断闭环

1. **拒绝后健康探针定位已闭环。** `RequestRejected` 分支现在单独捕获 `_probe_count_endpoint()` 抛出的
   `CensusError`，以 `archive_count`、当前 `e_final_sha256` 和 `len(counted)` 补齐与普通归档计数失败
   相同的三项 facts。错误仍以 `count_endpoint_probe_failed` 区分，通用失败立即停止且不写部分 baseline。
   定向 fake-server 回归断言三字段、失败前唯一计数为 1、无自由文本及无 output。
2. **最终 v3 sink 消息形状已闭环。** `_require_neutral_message()` 由公共 builder 与 final validator 复用，
   同时检查 item 判别式、`user`/`assistant` 角色、非空 content、精确文本 part 形状及与角色匹配的 subtype。
   重新 canonicalize 且摘要自洽的 `content=[]`、`user+output_text`、`custom_tool_call+role=user` 三种伪造
   payload 在 `validate_static_payload()` 与 `LocalApprovalClient.build_request()` 两层均被拒绝。

共享校验比逐条补洞更不易分叉，但仍只覆盖本任务的中立消息合同；`phase`、passthrough 等 v2 延续字段处理
没有被改成新 allowlist，既有工具 item 也未被误伤。

## 事实与语义复核

- 冻结模板允许后继的四组交集是 `{user, assistant}`，文档已不再声称 `user` 唯一合法。
- 保留 `developer -> user` 是正确选择：归档 developer 是输入侧 `input_text`；映射为 user 只改 role，
  映射为 assistant 会改变说话者并要求改写 subtype。
- 三 consumer 共享的是 canonical logical payload；census 计数的是由它生成的 Local provider request。
  client docstring 已按此修正。

## 独立验证

| 验证 | 结果 |
|---|---|
| `git diff --check 78aefb1..cb66816` | 通过 |
| evidence + local approval focused unittest | **116/116 通过，14.224s** |
| 下游 `policy_identity` 直接消费用例 | **1/1 通过** |
| 两处整改定向回归 | **2/2 通过** |
| `uv lock --directory eval --check`（共享 cache） | **通过，85 packages** |
| 47 条生产 reader/builder 聚合检查 | evidence 47/47；Local request 47/47；三 consumer bytes 47/47；模板角色门 47/47 |
| 出站残留聚合检查 | developer/system role 0；reasoning/encrypted residual 0 |
| 三种伪造 payload 独立反向复现 | validator 3/3 拒绝；Local sink 3/3 拒绝 |

## 审查者代用户作出的决定

1. 接受 builder 与 final sink 共用完整中立消息形状 predicate 的实现；它是本任务内的必要一致性校验，
   不要求退回逐条补洞，也不继续扩展到其他 evidence schema 字段。
2. 接受拒绝后探针沿用 `archive_count`，由稳定错误码区分 probe failure；不增加第三个 stage 或通用 tracing。
3. 保留 `developer -> user` 及其输入侧语义理由；不新增中立标签、占位符或对话重写器。
4. 本轮不运行真实模型或 census。Plan 027 验收后冻结，后续 47/47 重跑必须按 WBS 重新取得真实模型授权。
5. 将 Plan、方向 WBS 与 WBS-COMPLETED 收口为已通过独立复验；任务分支仍不合并、不推送，等待用户决定。

## 交付边界

Plan 027 的实现、整改、测试和独立验收均已完成。审查时主工作区保持干净，
`main == origin/main == 78aefb1`；任务分支与 worktree 保留，不在本轮合并或推送。
