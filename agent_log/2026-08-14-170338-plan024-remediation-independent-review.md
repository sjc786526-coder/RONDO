# Plan 024 `6b36d05` 整改独立复审报告

- 日期：2026-08-14
- 审查对象：`024-wp3b-a2-exact-token-census@6b36d05`（复审基线 `48fed68`）
- 审查范围：上一份审查 F1—F7、实现与无模型回归、Plan/WBS/历史日志、baseline 撤回、capability 与现场清理
- 审查边界：未加载模型，未读取 `.env.local`，未运行 Cargo/Docker/云 API/全量 eval，未合并、未推送

## 验收结论

**实现层整改通过；`6b36d05` 作为包含权威文档的整体提交暂不通过，不得合并。**

F1、F2、F4、F5、F6、F7 的代码和测试整改均已成立：不完整运行不再冒充成功，默认 baseline 不再发布；
只有明确的 adapter 400 被记为输入拒绝，通用 500/503 整体 fail closed；真实 HTTP 分类和拒绝后探针已有无模型回归；
服务端自由文本不落盘；私有目录清理窗口已关闭；census 测试确为 12 项。旧的不完整 baseline 已删除，
WBS-COMPLETED 的 Plan 024 完成记录也已撤回。

但 F3 尚未完全关闭：文档一方面把 2 条通用 500 正确写成“未定性”，另一方面仍把全部 23 条归为请求形状，
断言增大上下文无效并预设 static-payload 兼容可解决；同时把 counted 子集的 `0/24`、`9/24` 写成全集
“可服务性上限” `0/47`、`9/47`。这两个全集结论均超出现有证据。整改后的实现也没有真实运行，部分文档仍没有把
“两次运行一致”限定为整改前实现。

因此本次应收口为：**WP3b-A2 继续 blocked/incomplete；代码可保留为后续基础，但先补一个纯文档窄提交再复审。**

## 审查者代用户作出的决定

1. **不合并、不推送 `6b36d05`，也不恢复 baseline/WBS-COMPLETED。** 分支和 worktree 继续保留。
2. **下一步只做文档窄整改，不改代码、不加载模型。** 明确区分 21 条已证实 adapter shape rejection 与
   2 条未定性通用 500；删除全集 fit/可服务性“上限”，只保留 counted 子集 `0/24`、`9/24`。
3. **static-payload 兼容任务只以已证实的 21 条为当前输入。** 重跑若再次出现通用 500，继续 fail closed 并单独诊断；
   不预先承诺兼容能解决全部 23 条。
4. **不批准本轮重新加载真实模型。** 文档整改无需新授权；其通过复审后，另开 provider-neutral 兼容任务。
   兼容和无模型门禁完成后，再为 47/47 重跑申请一次新的模型/GPU 授权。
5. 两个 Low 边界——拒绝 facts 还含数值 `error_code`、incomplete 门禁按正式 baseline basename 判断——
   本轮不要求扩建通用发布或审计设施，也不阻止代码整改验收；保持轻量，后续有实际需要再顺手收紧。

用户当前无需补充策略选择或授权。

## 仍需整改的发现

### R1（High）：两条未定性 500 仍被写成请求形状结论

整改代码已经把通用 500 定义为整次 census failure，而不是某一输入的结构拒绝：

- `eval/rondo_eval/local_approval/token_census.py:103-108,317-323`
- `eval/tests/test_local_approval.py:2854-2886`

文档却仍将 23 条整体称为“按请求形状拒绝/被请求形状阻断”，并说加大上下文不能解决：

- `doc/WBS.md:27,40-43,69`
- `doc/WBS/local-approval-model.md:70-83`
- `plan/024-wp3b-a2-exact-token-census-execplan.md:106-113`
- `agent_log/2026-08-14-091500-plan024-exact-token-census.md:18-22`

当前能支持的结论只有：21 条 adapter 400 已证实为 reasoning item shape rejection，真实 `/v1/responses`
共用 converter，当前请求路径也会拒绝；另外两条旧运行中的通用 500 **原因未知**。它们是否与长度、形状、模板或其他内部故障有关，
现有证据不能定性。路线应写成先兼容已证实的 21 条，重跑后对仍出现的 500 继续 fail closed/单独诊断。

### R2（High/Medium）：`0/47`、`9/47` 不是已证明的全集可服务性上限

以下位置把有限统计升级成“全集当前可服务性上限”：

- `doc/WBS/local-approval-model.md:73-79`
- `plan/024-wp3b-a2-exact-token-census-execplan.md:107-111`
- `agent_log/2026-08-14-091500-plan024-exact-token-census.md:14-22`

已证明的只有 counted 子集按 `input_tokens+512` 的算术 fit：4k `0/24`、8k `9/24`；21 条当前请求路径先被
adapter 拒绝；2 条 500 的 token 数与原因均未知。`0/47`、`9/47` 最多只能描述这次失败尝试中已确认取得 token 数且适配的数量，
既不是完整 47 条 fit，也没有经过 generation 证明“可服务”。最清晰的整改是删除全集数字，只保留子集事实和“全集未知”。

### R3（Medium）：整改前真实运行证据没有处处限定版本

`doc/WBS/local-approval-model.md:70-72` 称设施“两次运行一致”，Plan `:92-94` 也记录两次运行，但 `6b36d05`
从未真实运行。执行日志 `:70-71` 已正确标成“整改前的实现”；WBS 和 Plan 应采用同样限定，并说明当前代码只通过无模型回归。
这不否定旧运行的 5,313 锚点和部分诊断价值，只是不能把它写成整改后实现的现场验收。

## F1—F7 复审结果

| 原发现 | 复审 | 证据摘要 |
|---|---|---|
| F1 不完整却 complete/发布 baseline | **通过** | 任一拒绝使文档 `incomplete` 并列出 `missing_counts`；正式 baseline 名拒写；CLI 非零。旧 baseline 已删除。 |
| F2 通用 500 被当成样本拒绝 | **通过** | 仅 `(400, invalid_request_error)` 进入 `RequestRejected`；500/503/其他错误整体失败。 |
| F3 权威文档冒充完成 | **部分通过** | 完成声明、WBS-COMPLETED 和 baseline 已撤回；仍有 R1—R3 的过度结论，故未关闭。 |
| F4 未覆盖真实 HTTP/探针/不发布 | **通过** | fake server 增 count endpoint；HTTP 分类、探针失败、incomplete、CLI 与发布门禁均有直接回归。 |
| F5 自由文本与逐条 schema | **通过** | message 只留 SHA-256；counted 记录只含 sha/status/token/fit，shape 移到 summary；未发现正文输出。 |
| F6 private directory 清理窗口 | **通过** | command/config digest 在建目录前完成，建目录后的操作受 `try/finally` 覆盖，并有失败前置回归。 |
| F7 日志矛盾/测试数 | **通过** | 错误事实已改写；`TokenCensusTests` 独立计数为 12 项。 |

## 非阻断观察

- `_http_error_facts()` 除 HTTP status、error type、message SHA 外仍可能保存数值型 `error_code`
  （`token_census.py:352-358`），与日志所称“三元组”不完全一致；冻结服务该字段不含正文，本次不作为泄露或阻断。
- `write_document()` 以正式 baseline 的 basename 阻止 incomplete 写入（`:495-517`）；显式改名仍可写诊断结果。
  当前默认入口、提交和现场都没有 baseline，且本项目不需要为本任务新增通用可信发布子系统，因此不扩大整改。

## 独立验证

| 验证 | 结果 |
|---|---|
| `git diff --check 48fed68..6b36d05` | 通过 |
| focused unittest 三文件 | **127/127 通过，13.486s**；census 12 项 |
| `just eval-lock` | 通过，85 packages |
| 正式 baseline | 不存在，提交中已删除 |
| WBS-COMPLETED | Plan 024 完成记录已删除 |
| no-model doctor | exit 70；configuration valid、model present、service not started、capability `linux_cuda_built_model_unvalidated`、model-backed `not_run` |
| 正式 launcher | exit 70，`runtime_error`；未启动服务 |
| 8080 / private local-approval 目录 | 无 listener；目录无对象 |
| GPU compute process | host-visible 查询为空 |
| 主工作区 | clean `main`，等于 `origin/main@40f3099` |
| 真实模型普查 | 未运行；本次复审未增加模型生命周期 |

## 最小复审入口

执行者只需在同一分支提交 R1—R3 的文档修正，运行 `git diff --check`，并交回 Codex 复审。
这是纯文档收口，不需要重跑 127 项测试或 `eval-lock`，也不得借机改代码、选上下文档位、启动模型或新增 baseline。

### 逐文档收口清单

- `doc/WBS.md`
  - 当前事实改为：24 条取得 token 数，21 条已证实为 adapter shape rejection，另 2 条旧运行中的通用 500 未定性。
  - 下一步写成先解决已证实的 21 条 provider-neutral static-payload 兼容；重跑时如再遇 500，fail closed 并单独诊断。
  - 删除“23 条均被请求形状阻断”“加大上下文均无效”等全集归因；仍保持 WP3b-A2 blocked/incomplete、全集后再定档位。
- `doc/WBS/local-approval-model.md`
  - 保留 24 条的 min/max/分位数与 `0/24`、`9/24`；删除“全集可服务性上限 0/47、9/47”。
  - 把“两次运行一致、锚点 5,313”明确限定为 `6b36d05` 之前的实现；当前整改代码只通过无模型回归，尚未真实运行。
  - 将 21 条 adapter 400 与 2 条未定性 500 分列，不承诺 static-payload 兼容能解决后两条。
- `plan/024-wp3b-a2-exact-token-census-execplan.md`
  - Plan 作为任务历史仍保持 blocked/incomplete，不改原始 47/47 完成合同，也不追加新的事后 success 条件。
  - 在执行记录和当前状态中限定旧真实运行/新整改代码的版本边界，删除全集“上限”和两条 500 的形状归因。
  - 交接仍指向 WBS；只描述本任务内失败事实，不在 Plan 冻结下游实现或上下文策略。
- `agent_log/2026-08-14-091500-plan024-exact-token-census.md`
  - 作为本次执行日志，如实保留错误、整改和 7 次历史模型生命周期；修正结论段中的两处过度推断。
  - 只说 21 条 400 已证实共用 converter，2 条 500 原因未知；删除全集“可服务性上限”。
  - 保留“整改后的实现未真实运行”和当前 127/127、eval-lock 结果。
- `doc/WBS-COMPLETED.md`
  - 当前删除 Plan 024 完成记录的状态正确；文档窄整改中不得恢复，直到未来真正完成 47/47 并通过独立验收。
- `eval/results/baselines/local-approval-exact-token-census-v1.json`
  - 当前不存在的状态正确；本轮文档整改不得恢复或另存同义 tracked baseline。

`README.md`、`AGENTS.md`、其他 WBS 方向文档和历史独立审查报告没有需要同步的当前事实，不应为保持“多处一致”而扩大修改范围。
