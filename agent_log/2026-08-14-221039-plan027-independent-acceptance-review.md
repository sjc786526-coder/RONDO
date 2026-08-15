# 2026-08-14 Plan 027 / WP3b-A2c 独立验收审查

审查对象：分支 `027-wp3b-a2c-role-compat-census-diagnostics` 的执行提交 `2f51376`
（基线 `78aefb1`）。本次只做源码、合同、focused tests 与 47 条归档的无模型只读检查；未加载模型，
未调用 count endpoint，未运行 Cargo、Docker、云 API 或全量测试。

## 结论

- **验收不通过**：主路径实现大体正确，但仍有两个可复现的合同缺口。
- **任务目标失败（当前提交未完整实现预期）**：已知 47 条归档的正常构造目标达成，但“通用失败均可定位”
  和“未知/畸形消息形状在最终出站边界 fail-closed”尚未完整达成。
- 不合并、不推送执行提交；完成下述窄修后再复验。WP3b-A2 继续保持 `blocked/incomplete`，不产生正式
  baseline，不选择上下文档位，capability 与 qualification 状态不变。

## 阻断问题

### 1. 拒绝后的健康探针失败缺少最小定位字段（中等）

`eval/rondo_eval/local_approval/token_census.py:738-742` 在捕获 `RequestRejected` 后直接调用
`_probe_count_endpoint()`。如果这次探针返回通用 500 或 transport failure，抛出的 `CensusError`
发生在 `except RequestRejected` 分支内部，不会进入其后的同级 `except CensusError`，因此没有经过
`_counting_stage_facts()` 包装。

用现有 fake server 路径复现得到：错误码仍为 `count_endpoint_probe_failed`，但 `stage` 为 `None`，
`e_final_sha256` 缺失，`counted_before_failure` 为 `None`。现有
`test_probe_failure_after_a_refusal_fails_the_census` 只断言错误码和不写 output，未覆盖三个定位字段。

该路径仍然立即停止且不会发布部分 baseline，安全边界没有退化；但它违反 Plan 027 对下一次通用失败的
最小定位要求。窄修即可：只在拒绝后的 probe 周围捕获 `CensusError`，使用当前条目、
`archive_count` 和 `len(counted)` 补齐三个 facts，并增强现有回归测试。

### 2. 最终 v3 sink 未复核 provider-neutral 消息形状（中等）

公共 builder 的 `_normalize_evidence_role()` 已检查 message type、role、非空 content 及文本 subtype；
但 `eval/rondo_eval/evidence.py:505-517` 的 `_reject_unnormalized_roles()` 在最终校验时只检查顶层 role
是否为 `user`/`assistant`。`LocalApprovalClient.build_request()` 又明确把
`validate_static_payload()` 当作唯一 sink gate。

独立构造并重新 canonicalize/摘要自洽的 v3 payload 后，以下形状仍被最终 validator 接受：

- `role=user` 搭配 `output_text`；
- message 的 `content=[]`；
- `type=custom_tool_call` 搭配 `role=user`。

真实 47 条归档均未出现这些形状，所以本次 47/47 正常构造结论不受影响；缺口在于伪造或错误组装的
v3 对象可以绕过 builder 后抵达 sink，不符合本任务的 fail-closed 验收条件。窄修即可：让 builder 与
final sink 复用一个小型、只读的中立消息形状校验，并补上述 forged regressions。无需引入通用 schema
registry、provenance、attestation 或审计体系，也不应顺带新增 `phase`、passthrough 等字段 allowlist。

## 非阻断但应一并修正的事实表述

执行记录和当前文档把 `user` 写成“唯一能跟在 system/user/assistant/tool 后的角色”，与冻结模板不符。
从模板解析出的允许后继交集是 `{user, assistant}`。这不推翻 `developer -> user` 的实现选择：归档中的
developer 消息是输入侧 `input_text`，映射为 user 只改 role 并保持输入证据语义；映射为 assistant
会改变说话者语义且需要把 subtype 改成 `output_text`。应保留实现，仅把理由修正为“最小且语义合适的
输入侧映射”，并同步修正 Plan、WBS、WBS-COMPLETED 和执行日志中的相关表述。

`LocalApprovalClient.build_request()` 的 docstring 还应避免把三 consumer 的字节一致性写成“都收到与
census 请求相同的字节”：实际成立的是三 consumer 的 canonical logical payload 字节一致，census
计数的是由该共享 payload 构造出的 Local provider request 字节。

## 已确认正确的部分

- `developer -> user` 在公共 builder 内原位、无条件执行；保留文本、顺序和消息边界，三个 consumer
  没有各自的角色特判。
- static input schema 升至 v3，决策输出 schema 仍为 `rondo_static_approval_v1`。
- builder 对未知/缺失 role、冲突 type、空/畸形 content、错误文本 subtype 保持 fail-closed。
- raw reasoning、encrypted content 与已知 provider 私有字段仍不进入出站 payload。
- anchor 和普通 archive_count 路径的通用失败带有三个定位字段；失败立即停止，部分结果不生成正式
  baseline；`counted_before_failure` 按唯一归档计数，anchor 不重复累计。
- 47 条归档均能构造 v3 payload 和 Local 请求；Luna-static、Sol-static、Local-static 的 canonical
  logical payload 字节 47/47 一致；残留 developer/system、reasoning/encrypted 均为 0；冻结模板角色
  顺序门 47/47 通过。

## 独立验证记录

- `git diff --check 78aefb1..2f51376`：通过。
- `tests.test_contracts_and_evidence` + `tests.test_local_approval`：**116/116 通过**。
- `tests.test_terminal_bench` 中消费 `policy_identity` 的相关用例：**1/1 通过**。
- `uv lock --directory eval --check`：**85 packages 通过**。
- 47 条无模型、只读聚合检查：evidence **47/47**、Local request **47/47**、三 consumer canonical
  bytes **47/47**、冻结模板角色门 **47/47**。
- 另行复现了上述两个缺口；复现未输出证据正文、完整请求或服务端自由文本。
- 审查开始时任务工作树干净；主工作区保持干净，`main == origin/main == 78aefb1`。

## 审查者代用户作出的决定

1. **保留 `developer -> user` 方案**，但按真实模板集合修正选择理由；不要求增加中立标签、占位符或
   对话重写器。
2. **只要求修复上述两个阻断点及相应 focused regressions**；不扩建通用审计、可信、provenance、
   attestation 或 schema registry，也不把现有 v2 延续字段处理扩大成新 allowlist。
3. 一并修正文档中的“user 唯一”事实错误和 Local request 字节表述；这是准确性修订，不改变实施路线。
4. 修复后只需重跑本报告列出的 focused tests、eval lock 与 47 条无模型只读聚合检查；不运行真实模型、
   census、Cargo、Docker、云 API 或全量测试。
5. 执行者在原任务分支提交窄修并交回复验；当前不合并、不推送，WP3b-A2 状态不变。
