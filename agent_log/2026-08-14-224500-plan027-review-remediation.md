# 2026-08-14 Plan 027 / WP3b-A2c 审查整改

针对独立审查 `0603008` 的两处阻断与两处事实表述错误做窄整改，起点 `2f51376`，仍在原任务分支。
两处阻断均已独立复核成立，不是误报。

## 阻断 1：拒绝后的健康探针失败缺少定位字段

`run_census()` 里 `_probe_count_endpoint()` 是在 `except RequestRejected` 分支**内部**调用的，它抛出的
`CensusError` 不会落进其后的同级 `except CensusError`，所以没经过 `_counting_stage_facts()` 包装 ——
`stage`、`e_final_sha256`、`counted_before_failure` 三项全缺。这是我在实现时明确考虑过、并以「保持最小」
为由略过的路径；审查者是对的：它同样是遍历阶段的通用失败，正好落在 Plan 026 那个「不知道停在哪」的盲区里。

整改：只在拒绝后的 probe 调用外包一层 `except CensusError`，用当前归档与 `archive_count` 补齐同样三项。
`stage` 仍只有两个有界取值，探针失败靠它自己的 `count_endpoint_probe_failed` 区分，没有引入第三个阶段名。
`test_probe_failure_after_a_refusal_fails_the_census` 从「只断错误码 + 不写 output」加强到断言三个字段。

## 阻断 2：终端 sink 只校验角色集合

`_reject_unnormalized_roles()` 只检查顶层 role 是否属于 `{user, assistant}`，而 `build_request()` 明确把
`validate_static_payload()` 当作唯一 gate。用重新 canonicalize、摘要自洽的伪造 v3 payload 复现，确认
`role=user` 配 `output_text`、`content=[]`、`type=custom_tool_call` 配 `role=user` 三种形状都能抵达出站边界。

整改：把中立消息合同抽成共享的 `_require_neutral_message()`（item 判别式、角色、非空 content、
与角色匹配的文本 subtype），builder 在产出前调一次、final sink 对每个顶层证据 item 再调一次，
函数改名为 `_reject_unneutral_messages()`。没有新增字段 allowlist，`phase`、passthrough 等 v2 延续字段
处理原样不动，也没有引入 schema registry、provenance 或审计设施。
`test_final_payload_validator_...` 增加 7 条伪造回归。

## 事实表述修正（非阻断）

- **「`user` 是唯一在所有前驱角色之后都被接受的角色」是错的。** 从冻结模板解析出的允许后继交集是
  `{user, assistant}`。这不推翻实现选择，但理由要改成语义理由：归档 developer 消息是输入侧
  `input_text`，映射为 `user` 只换 role 标签；映射为 `assistant` 会改变说话者，还得把文本 subtype
  一并重写。已同步修正 evidence.py 注释/docstring、Plan 027（当前状态与决策 006）、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 与上一份执行日志。
- `build_request()` 的 docstring 曾把三 consumer 的字节一致性写成「都收到与 census 相同的字节」。
  实际成立的是：三 consumer 共享同一份 canonical logical payload，census 计数的是由它构造出的
  **Local provider request** 字节。已改写。

## 复验结果

- focused tests `tests.test_contracts_and_evidence` + `tests.test_local_approval`：**116/116 通过**
  （新增 7 条伪造 sink 回归与 3 条探针定位断言，均并入既有用例，未新增测试类）。
- `tests.test_terminal_bench` 中消费 `policy_identity` 的用例：**1/1 通过**。
- `uv lock --directory eval --check`：**85 packages 通过**。
- 47 条无模型只读聚合检查：evidence 47/47、Local request 47/47、三 consumer canonical bytes 47/47、
  冻结模板角色顺序门 v3 47/47（规范化前 24/47），与整改前一致。
- 另按审查者的构造直接复现三种畸形形状：现在 `validate_static_payload()` 与 `build_request()`
  两处都拒绝（`EvidenceError` / `ConfigError`）。复现未输出证据正文、完整请求或服务端自由文本。

## 未运行 / 状态

未运行真实模型、census、count endpoint、任何 generation、Cargo、Docker、云 API、全量 eval。
WP3b-A2 仍 blocked/incomplete，无 token baseline，未选档位，capability 仍为
`linux_cuda_built_model_unvalidated`，qualification 状态不变。不合并、不推送。
