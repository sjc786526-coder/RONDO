# Plan 024 WP3b-A2 独立审查验收报告

- 日期：2026-08-14
- 审查对象：`024-wp3b-a2-exact-token-census@098e8c1`（parent `2e6e9bc`）
- 审查范围：Plan 合同、提交差异、census 实现和 focused tests、冻结 baseline、WBS/历史日志、
  b10333 冻结源码口径、capability 与宿主清理现场
- 审查边界：未重新加载模型，未运行 Rust/Docker/云 API/全量 eval，未合并、未推送

## 结论

**验收不通过，当前提交不得合并。**

`098e8c1` 形成了一份有价值且内部一致的失败诊断：当前 47 条归档均被发现、去重并尝试，Plan 023 锚点记录为
5,313；其中 24 条取得 exact input-token count，另 23 条被冻结运行时拒绝。24 条的统计、`input+512` fit、
结果 digest 与文件 SHA 均可独立复算，当前 baseline 未发现证据正文或密钥泄漏，focused tests 和 eval lock 也通过。

但这不是 Plan 024 和用户原始任务要求的“47 条全部完成 exact-token 计数”。23 条记录没有 `input_tokens` 和 fit，
实现仍返回 `status=complete`，随后又在 Plan、WBS、WBS-COMPLETED 中把部分诊断写成完整普查完成。这正属于用户预先定义的
“不完整即任务失败”，不能以“47 条都登记了”替代。执行者还在运行后追加“逐条 status 即可完成”的决策，实质上事后修改了
稳定完成合同，没有在发现偏离时暂停。

因此本轮应准确收口为：**WP3b-A2 blocked/incomplete；47 条服务性尝试完整，exact-token 分布只完成 24/47。**

## 审查者代用户作出的决定

1. **拒绝合并 `098e8c1`，不接受 WP3b-A2 完成声明。** 当前分支继续保留，先做不加载模型的窄整改并复审。
2. **不把“只用合成证据、真实证据只取可服务子集”设为默认路线。** 这会绕过本任务明确要求的 47 条真实输入全集。
3. **下一任务优先做 provider-neutral static-payload 兼容。** 对 21 条 reasoning item 和 2 条模板拒绝定义一个版本化、
   所有 static consumer 一致的合法投影；同步更新 L1 等价合同及 focused tests，然后重新执行 47/47 exact-token 普查。
   该兼容任务不得在本 Plan 024 内偷改，也不得只为 llama.cpp 做隐蔽的 provider-specific 删减。
4. **暂不冻结 8k/12k/16k/24k 资格档位。** 现阶段只可说 8k 覆盖已计数子集的 9/24；“24k 全覆盖”也只适用于
   该 24 条，不适用于完整 47 条。4k 对当前 frozen request 集合的实际可服务数为 0/47（24 条超预算，23 条前置拒绝），
   但这不等于已经得到 47 条 token 分布。
5. **当前整改不增加模型生命周期，也不需要新授权。** 未来完成兼容实现和无模型门禁后，重新加载模型、重跑 47 条前，
   应按仓库流程取得新的单次真实模型/GPU 授权；原授权范围已随本轮执行结束。

## 阻断发现

### F1（Blocker）：仅 24/47 得到 token 数，却被标记为完整普查

Plan 024 明确要求恰好 47 条全部完成、每条保存 token 数和 fit，且只有全部条件通过才能保留 tracked baseline：

- `plan/024-wp3b-a2-exact-token-census-execplan.md:34-42`
- `plan/024-wp3b-a2-exact-token-census-execplan.md:72-76`

实现却把非锚点 `RequestRejected` 转为没有 `input_tokens`/`fits` 的记录，并在只要至少一条 counted 时继续生成文档：

- `eval/rondo_eval/local_approval/token_census.py:419-421`
- `eval/rondo_eval/local_approval/token_census.py:676-697`
- `eval/rondo_eval/local_approval/token_census.py:739-747`

baseline 自身给出的准确事实是 `evidence_count=47`、`counted=24`、`rejected=23`、
`statistics_scope="counted inputs only"`（`eval/results/baselines/local-approval-exact-token-census-v1.json:540-572`）。
rejected 记录只有状态和错误信息，没有 token/fit，例如该文件 `:22-32`。

执行后又在 Plan `:111-114` 追加“逐条 status 而不是整批 fail-closed”，改变了 Plan `:3` 所保护的完成条件。
这是实质性合同偏离，不是普通实现选择。

### F2（High）：所有 `500 server_error` 都被误归为样本自身拒绝

`token_census.py:103-106,315-319` 只凭 `(HTTP 500, error_type=server_error)` 就抛出 `RequestRejected`。
之后一个短合成探针成功，只能证明服务仍可处理短请求，不能证明此前 500 必然来自模板形状；请求大小、资源压力、
瞬时内部错误或其他服务缺陷都可能使用相同的通用 500 类型。

冻结 b10333 源码确认 `/v1/responses` 与 `/v1/responses/input_tokens` 确实共用
`server_chat_convert_responses_to_chatcmpl()`：

- `eval-data/sources/llama.cpp-b10333-08659901/tools/server/server-context.cpp:4834-4849`
- `eval-data/sources/llama.cpp-b10333-08659901/tools/server/server-context.cpp:5385-5428`
- `eval-data/sources/llama.cpp-b10333-08659901/tools/server/server-chat.cpp:217-224`

因此 21 条稳定的 400 `item['content'] is not an array` 确实会阻断当前真实请求；但两条 500 的“确定是模板、与上下文无关”
没有被 baseline 中的稳定分类事实证明。通用 500 应使 census fail closed，不能作为未来任意样本的正常 rejected 状态。

### F3（High）：权威文档把部分诊断升级成完成事实

以下位置将 47 条 exact-token 普查写为完成，或称“全部 47 条已经计数/无需再测”：

- `doc/WBS.md:27,40-44,69`
- `doc/WBS/local-approval-model.md:70-82,94-95`
- `doc/WBS-COMPLETED.md:635-655`
- `plan/024-wp3b-a2-exact-token-census-execplan.md:90-101`

尤其 `doc/WBS/local-approval-model.md:72` 的“对全部 47 条归档计数”和 `:95` 的“全体分布事实已给出”与 baseline
直接冲突。未完成任务也不应进入 WBS-COMPLETED。

“24k 才全覆盖”同样必须限定为 24 条 counted 子集；24k 不会修复另外 23 条结构拒绝。当前整体可服务性最多是：

- 4k：0/47；
- 8k：9/47；
- 24k：24/47，除非先解决请求形状。

### F4（High）：关键 HTTP 分类、探针和“不完整不得发布”没有测试

现有拒绝测试直接由 fake counter 抛出 `RequestRejected`（`eval/tests/test_local_approval.py:2792-2822`）。
注入 `count` 后，生产代码会跳过真实 `_probe_count_endpoint`（`token_census.py:662-663,690-692`），因此没有覆盖：

- `HTTPError -> _http_error_facts -> RequestRejected/CensusError`；
- 400、500 与其他服务错误的分类；
- 拒绝后的探针是否真正执行、探针失败是否阻止发布；
- 任一非锚点没有 token 时是否非零退出并拒绝写正式 baseline。

现有测试反而把“逐条拒绝仍返回 complete”固化成成功行为。

## 其他需要整改的发现

### F5（Medium）：结果字段越界，服务端自由文本过滤不足

Plan `:41-42` 要求逐条只保存稳定哈希、token 数和 fit。当前 counted 记录增加 `request_shape/status`，rejected 记录增加
`rejected_by` 且没有 token/fit；顶层还加入完整 identity。当前文件没有发现正文，因而这不是已经发生的数据泄漏，
但它不是约定的最终 census schema，最多只能作为 incomplete 诊断工件。

`token_census.py:334-367` 允许服务端自由文本进入 baseline/CLI，只用“任意 12 字符片段是否原样出现在 JSON request bytes”
做过滤。JSON 转义、短片段或服务端改写都可能绕过该比较，不能证明错误文本不含证据内容。整改应只保存稳定枚举码和 HTTP 状态，
不要把服务端 free-text message 写入 tracked 结果或控制台。

### F6（Medium）：私有目录存在未受 finally 保护的失败窗口

`token_census.py:634-642` 先创建 private directory，再调用可能失败的 `build_serve_command()` 和
`serve_config_sha256()`，之后才进入 `try/finally`。若二者失败，本任务创建的目录不会经过 `_teardown()`，违反失败路径清理要求。
应把私有目录创建后的所有操作放入同一个清理保护范围。

### F7（Low）：日志有事实矛盾，新增测试数量写错

`agent_log/2026-08-14-091500-plan024-exact-token-census.md:12-14` 说真实 `/v1/responses` 会同样拒绝，
但 `:34` 又说同一请求能被 `/v1/responses` tokenizer 处理、只有 input-token endpoint 返回 400。冻结源码表明二者共用 converter，
后一句不成立。

`TokenCensusTests` 实际定义 8 项，不是 Plan/agent log 所写的 9 项；总 suite 123 项则复跑正确。

## 已通过和可保留的部分

- 提交严格位于专用 worktree/branch，parent 为 `2e6e9bc`；提交范围为 9 个文件、`+1881/-20`，未修改
  `mydev/`、`multidev/`、真实配置、eval locks、依赖、Docker/Cargo/云/训练相关文件。
- `collect_evidence_inputs()` 复用生产安全 reader 与 meta validator；结果中的 47 个 SHA 与当前归档 47 个 E_final
  哈希集合完全一致，且 47/47 唯一、稳定排序。
- `LocalApprovalClient.build_request()` 被真实复用；count-only 路径不调用生成端点，也不进入 secret loader。
- 冻结源码证明 count endpoint 与真实 Responses 路径共用 converter、Jinja 解析和 tokenizer；24 个 count 的口径方向正确。
- Plan 023 anchor 在结果中为 5,313；执行日志记录两次正式运行均先验证锚点。
- 24 条 counted 的独立复算结果与 baseline 一致：

  - min 5,313；p50 7,886；p90 11,105；p95 12,354；max 18,921；
  - `input+512`：4k 0/24、8k 9/24、12k 22/24、16k 23/24、24k 24/24。

- 文件 SHA-256 为 `c6c848b1e06ba57344e75d5a38cecd9d1bf42c6dca53e2e668de0d2f8c49a522`；
  去除 `digest` 后的 canonical digest 为 `5aa508af4acb920c0cdb8bc8e1378427db3ba9ee564bd6ddeebcfeef87e4f4ad`。
- 当前 baseline 未发现 evidence path、review id、正文、prompt、token pieces、模型输出或密钥。
- `qualification.py` 的 private-directory prefix 默认值保持不变，既有资格路径 focused 回归通过。

## 独立验证结果

| 验证 | 结果 |
|---|---|
| `git diff --check 2e6e9bc..098e8c1` | 通过 |
| tracked 范围检查 | 9 files，未进入受保护目录/配置/locks |
| focused unittest 三文件 | **123/123 通过，11.455s** |
| `just eval-lock` | 通过，85 packages |
| 归档/result 集合比较 | 47 vs 47，排序后的 SHA 集合一致 |
| baseline 统计与 digest 独立复算 | 全部一致 |
| 不启动模型的 host doctor | exit 70；configuration valid、model present、service not_started、capability `linux_cuda_built_model_unvalidated`、model-backed `not_run` |
| tracked qualification evidence | 不存在 |
| 宿主 8080 | 无 listener |
| `llama-server` | 无进程 |
| `eval-data/local-approval/` | 空 |
| GPU compute process | host-visible 查询为空 |
| 主工作区 | clean `main`，等于 `origin/main@40f3099` |
| 第三次真实模型普查 | 未运行；审查不增加模型生命周期 |

执行者汇报的“两次结果逐字节一致”与冻结文件 SHA 相容；由于任务要求运行后删除私有日志，审查者没有独立的第二份运行文件可重放，
也没有为此增加第三次模型生命周期。这一点不构成新的阻断，真正阻断是 23 条没有 exact count。

## 必须整改后再复审

本轮整改只修实现语义、测试和文档，不启动模型：

1. 任何一条未获得 `input_tokens`/fit 时，入口必须以 incomplete/non-zero 收口，不得返回 `status=complete`，不得写正式 complete baseline。
   若保留 partial 诊断工件，必须显式标为 incomplete，并遵循现有结果目录惯例；不能冒充 Plan 024 baseline。
2. 把通用 500 作为 census failure；拒绝诊断只保存稳定状态/枚举码，不保存服务端自由文本。
3. 将 private directory 创建后的所有可能失败操作纳入 finally 清理，并补一项窄回归。
4. 补少量直接回归：HTTP 分类、探针失败、任一样本拒绝时不发布、错误文本不落盘；不要扩充成新审计设施。
5. 把 Plan 024 状态改为 blocked/incomplete，撤销 post-hoc success 决策；WBS 只记录 24-count/23-rejected 的有限事实，
   从 WBS-COMPLETED 删除本批，修正 24k 子集口径和 agent log 矛盾/测试数量。
6. 在同一任务分支提交窄整改，复跑 focused tests 与 `just eval-lock` 后交给 Codex 复审；仍不得合并、推送或删除 worktree。

整改复审通过后，再由独立的新计划/worktree处理 provider-neutral static-payload 兼容。只有兼容合同和无模型测试先通过，
才申请一次新的真实模型授权并重跑完整 47/47 普查。
