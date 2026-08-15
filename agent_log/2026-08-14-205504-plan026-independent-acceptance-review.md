# Plan 026 / WP3b-A2b 独立验收报告

- 日期：2026-08-14
- 审查对象：`026-wp3b-a2b-exact-token-census-rerun@3686770`（parent `a60ef0e`）
- 审查范围：Plan 026 失败语义、真实运行结论口径、冻结 Responses/template 路径、47 条 v2 请求角色形状、
  focused tests、eval lock、baseline/文档/capability 与资源清理
- 审查边界：未重新加载模型或增加 GPU 生命周期；未运行 Cargo、Docker、云 API 或全量 eval；
  未读取 `.env.local`，未输出真实证据正文、完整请求、渲染 prompt 或 token ids

## 结论

**当前验收不通过，`3686770` 暂不应合并。**

执行者对失败合同的处理本身正确：第一次正式 census 遇到通用 500 后立即 fail closed，没有执行第二次、
没有发布 baseline、没有写 WBS-COMPLETED、没有修改生产代码或晋级 capability，且资源已经清理。
Plan 026 的 47/47 目标确实未完成。

阻断合并的原因只有一项文档事实边界，不需要重新加载模型或扩建设施：当前错误报告无法区分通用 500
发生在锚点请求还是锚点之后的循环请求，但四份文档多处把“循环第一条归档失败”和“本次 500 的根因”写成
现场已测事实，并进一步把 Plan 024 的两条旧 500 追认为相同根因。这超过了现有证据。

独立静态复核同时确认，23 条 v2 请求确有一个**确定存在的模板兼容阻断**：它们均含
`assistant → developer` 相邻关系；冻结 llama.cpp 会在套模板前把 `developer` 映射成 `system`，而冻结
Ministral 模板拒绝 `assistant → system`。这个离线兼容结论可以保留，但必须与“Plan 026 这次通用 500
发生在哪一条、由什么触发”分开陈述。

## 阻断发现

### F1（High）：把无法定位的通用 500 和历史失败追认为已测角色顺序根因

`token_census.run_census()` 先计锚点，再遍历完整集合；两处都调用默认 `count_input_tokens()`，通用错误均为
`count_endpoint_unavailable`。当前失败输出不含阶段、当前样本哈希或失败前已计数数。因此只凭本次保留下来的
非敏感输出，无法判断：

1. 锚点请求本身返回了 500；还是
2. 锚点成功计数后，循环中的某条请求返回了 500。

Plan 自己在 `plan/026-wp3b-a2b-exact-token-census-rerun-execplan.md:126-130` 已准确承认这一点，
但同一文件 `:97-100`、执行日志 `:10`、根 WBS `:27,44` 和方向 2 WBS `:89-92` 又把
“遍历第一条归档失败”写成事实，前后矛盾。当前运行也没有留下锚点 5,313 的新测量记录。

离线角色检查是有效但不同的证据：生产 reader/meta + static payload v2 + 真实 Local builder 得到 47 个唯一输入，
其中 24 个没有 `assistant → developer`，23 个具有该相邻关系。冻结源码和模板进一步证明这 23 个请求若到达
模板阶段会触发角色顺序异常。这能证明“23 条当前静态请求存在确定的模板兼容问题”，却不能反向证明
Plan 026 留下的那一个通用 500 必然来自其中某条。

同理，Plan 024 的 21 条 400 仍应描述为当时先触发的 reasoning 形状拒绝；v2 删除 reasoning 后，离线分析预测
它们会继续碰到角色顺序阻断。Plan 024 的 2 条旧通用 500 也不能追认为已证明的相同实际根因；历史错误签名与
Plan 026 当前签名不同，旧记录本身不足以建立这种因果等同。

#### 必须整改

- 四份文档统一把现场事实改为：合成探针通过后，真实归档计数阶段出现一个通用 500；具体是锚点还是后续样本未知，
  本次没有复证 5,313，也没有新增可发布 token count。
- 把 23 条角色顺序问题明确标成独立、聚合式离线确认的兼容阻断；可以据此安排下一兼容任务，但不要声称它已解释
  Plan 026 的具体 500。
- 删除或改写“v1 的 21 条 400 + 2 条 500 实为同一个根因”。准确表述应是：v2 消除了 21 条先触发的
  reasoning 400，而这 23 个 v2 请求现在都暴露出共同的角色顺序兼容问题；旧 2 条 500 的实际原因仍未由历史现场证明。
- `doc/WBS.md` 和 `doc/WBS/local-approval-model.md` 只保留当前状态与下一步；推断细节留在 Plan/agent log。

这是纯文档整改。不要在 Plan 026 分支实现角色转换、修改 census、重新运行模型、生成 baseline 或写
WBS-COMPLETED。整改后 `git diff --check` 并提交即可，不必机械重跑 109 项测试和 eval lock。

## 已通过并可保留的部分

- 第一次通用 500 后按合同停止；第二次正式运行未执行，没有用重试或额外生命周期掩盖失败。
- `status=not_counted`、退出码 70、没有正式 baseline、没有全集 4k/8k 结论，均符合失败语义。
- 生产代码、static payload v2、配置、档位、qualification、launcher 与 capability 均未修改；
  `doc/WBS-COMPLETED.md` 未写 Plan 026。
- 执行者记录的 cleanup 三项均为 true；独立现场复核也确认 8080 无 listener、无 `llama-server`、
  GPU compute process 为空、`eval-data/local-approval/` 为空。
- capability 继续保持 `linux_cuda_built_model_unvalidated`，正式 census baseline 不存在。
- 47 条角色聚合：47 个唯一输入；24 条无 `assistant → developer`，23 条有；没有输出正文。
- 冻结源码链条成立：Responses count endpoint 走 Responses→Chat 转换与同一模板/tokenizer；
  `developer` 在 Jinja 前映射为 `system`；模板拒绝 `assistant` 后的 `system`；普通异常由服务端兜底为 500。

## 审查者代用户作出的决定

1. **不接受 `3686770` 当前文档合并，但只要求上述窄文档整改。** 失败执行本身不需要重做，也不把
   “未完成 47/47”误判成执行者违反失败合同。
2. **接受 eval lock 的等价入口。** 执行者把 cache 指向 Git common root 后运行
   `uv lock --directory eval --check`，语义与 `just eval-lock` 相同；独立复跑仍为 85 packages。
   不要求为了命令名字在 worktree 新建一份 cache。
3. **不在 Plan 026 追加模型授权或现场兼容修复。** 本轮真实授权随第一次合同失败收口；下一次真实 census
   必须在无模型兼容任务通过后重新授权。
4. **下一无模型任务可合并两个紧邻的小改动，但不得扩建通用诊断系统：**
   - 在公共 static builder 做版本化、provider-neutral 的角色顺序兼容；若 canonical payload/角色语义改变，
     必须升 static input schema 版本，不能静默改写已冻结的 v2。
   - 给 census 通用失败增加最小阶段信息：锚点或集合遍历、当前 `e_final_sha256`、失败前 counted 数；
     只保存稳定非敏感字段，并补锚点 500/样本 500 两个直接回归。
5. **角色兼容不预先写死具体转换。** 硬结果是保序、保留可见文本语义、把归档中的 developer 内容作为证据而非
   Local provider 私有旁路，且 Luna/Sol/Local static consumer 继续同字节。合并到相邻 user、投影成中立证据消息
   或其他等价实现由执行者结合现有合同选择；不得简单删除文本或只给 llama.cpp 特判。

## 独立验证

| 验证 | 结果 |
|---|---|
| `git diff --check a60ef0e..3686770` | 通过 |
| focused unittest：evidence + local approval | 109/109 通过，13.126s |
| `uv lock --directory eval --check`（shared cache） | 通过，85 packages |
| 47 条生产 reader/meta/v2 builder 聚合 | 47/47 唯一；24 无、23 有 `assistant → developer` |
| 冻结模板与 llama.cpp 路径静态核对 | 角色映射、顺序拒绝、500 兜底均确认 |
| 正式 census baseline | 不存在 |
| `doc/WBS-COMPLETED.md` | 本提交未修改 |
| 资源现场 | 8080/llama-server/GPU compute/private directory 均为空 |
| 主工作区 | clean `main == origin/main == 31e0157` |

## 复审入口

GPT 只需按 F1 清单修正 Plan 026、根 WBS、方向 2 WBS 和原执行日志，保持其他已通过事实不变；
提交后交回 Codex 复审。当前分支仍不得合并、推送或删除 worktree。
