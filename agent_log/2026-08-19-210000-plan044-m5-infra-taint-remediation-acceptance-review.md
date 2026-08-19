# Plan 044 / M-5 证据污染整改验收与 code-mode 明文误标归因

日期：2026-08-19  
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`  
代码范围：`b0e5dfd..4f227cb`  
验收方式：完整 diff 静态复核、cm4 原始 trace/request 只读核对、80 条定向回归、`just eval-lock`；未调用真实 API、Docker、Cargo 或本地模型。

## 结论

**本轮总体验收不通过。**

执行者对上一轮五项问题的主要整改是正确的：

- 每次保守结算和 operator-confirmed-unbilled 结算都会独立持久化 `infra_taint`；
- Gate 1 的 tainted run 一律为 `infra_failed`，Gate 2 一律 `counts_as_effective=false`；
- 正式批次把 unpriced stop threshold 恢复为 1，只让合同外 smoke 使用放宽阈值，作为当前最小修法合理；
- “terra 不遵守协议”的结论已正确撤回，Root/member 线程统计和当前文档口径已纠正；
- 旧账本不带可选 `infra_taint` 键时仍能加载，新代码没有改写历史账本。

但对 `invalid_encrypted_content` 的解释仍有一个决定性的事实错误：cm4 成员请求里的
`agent_message.content[].encrypted_content` **不是 Root 的加密推理被 fork 到成员线程**，
而是 code-mode `spawn_agent` 的**明文 `message` 参数被产品错误包装成 encrypted content**。
这是当前 Gate 1 的确定性产品阻断，且尚未修复。

## Finding

### [P0] Code-mode 将明文团队消息错误标成 encrypted content — `mydev/codex-rs/core/src/tools/handlers/multi_agents_v2.rs:64`

`communication_from_tool_message()` 只把 `ToolCallSource::DirectPlaintextMessage` 当明文，
其余来源全部调用 `InterAgentCommunication::new_encrypted()`。但 code-mode 嵌套工具调用在
`core/src/tools/code_mode/mod.rs` 中从模型 JS 对象直接序列化参数，设置
`encrypted_function_args=None`，并以 `ToolCallSource::CodeMode` 分发；这里的 `message`
显然是明文。它随后被 `to_model_input_item()` 写成
`AgentMessageInputContent::EncryptedContent`，成员第一轮请求因此携带伪“密文”。

cm4 的原始证据可以把这条因果链闭合，且无需查看或打印任何密文：

- trace 的第一个 code cell 明文调用 `collaboration.spawn_agent`；
- 第一个成员 inference request 仅有一个 `author=/root`、`recipient=/root/worker` 的
  agent-message encrypted item；
- 只做等值比较，该字段与 spawn 的 139 字符明文 `message` **逐字相等**，并非 Root reasoning；
- 成员随后 8 次 inference 全部失败，Root 22 次 inference 全部成功。

因此 `fork_turns:"all"` 不是这条错误的必要条件；即使不继承 Root 历史，spawn communication
本身仍会以错误类型进入成员请求。同一 helper 还服务于 `send_message` / `followup_task`，
所以 code-mode 下后续成员通信也受影响。继续对同一构造调用 relay 或第一方 endpoint
不能增加归因信息，只会花钱。

## 独立验证

- `MultiM5FrozenModelIsolationTests`、`MultiM5BudgetStopHonestyTests`、
  `MultiM5Gate2FakeTests` 与 `test_api_budget_proxy`：**80/80 通过**；
- `just eval-lock`：通过；
- worktree 测试结束时实现树干净，HEAD=`4f227cb`；当前仅新增本验收报告、未提交；
- 主工作区 `main=origin/main=45efac6`，未被改动；
- 未调用真实 API，新增 `$500` 授权未动用。

全量 942 条结果未重复运行；执行者报告的结果与本轮定向复验没有冲突。

## 代用户作出的决定

1. **同意立即开始离线归因/修复，但范围已经收窄为产品 bug。**
   不先做第一方 endpoint 对照，不调用真实 API，不动用 `$500`。
2. 产品修复应让 `ToolCallSource::CodeMode` 的团队消息走明文 communication 路径；
   保留 `ToolCallSource::Direct` 的现有 encrypted-argument 语义，不能把所有来源统一降成明文。
3. 只补高价值定向回归：
   - code-mode `spawn_agent` 的 message 生成 plaintext `AgentMessage`，不得生成
     `EncryptedContent`；
   - `send_message` / `followup_task` 走同一规则；
   - 既有 Direct encrypted 路径继续保持 encrypted；
   - 最好再覆盖一次成员首请求 body 形状，防止 handler 正确而组装层回归。
4. Rust 定向测试必须走仓库 build lock；不跑无关全量重型测试。
5. 修复后一次性冻结 v3：更新产品 runtime bundle 身份，并冻结 endpoint、retry/backoff、
   continuation threshold 与“任一 unpriced 使观察无效”的规则。当前 v2 仍禁止正式运行；
   Gate 1 的 2 秒 backoff 尚未进入 v2 锁，只能在 v3 一并收口。
6. v3 后使用全新身份做一次 clean smoke。除既定条件
   `conservative_exposure_usd=0`、无 infra taint、成员至少完成一次工具调用、trace 绑定无误外，
   再确认成员请求的 agent message 是 plaintext input，而不是伪 encrypted content。
7. 只有 clean smoke 成立后才判断 instruction/terra 是否遵守协议；只有 Gate 1 通过后才启动 Gate 2。

## 当前状态

- 本轮整改：infra-taint 修复本身通过，但总体验收因新确认的 P0 产品阻断而**不通过**；
- M-5：**任务目标失败**（尚未实现两道门的预期目标）；
- Gate 1：未通过，禁止正式启动；
- Gate 2：未启动，不存在“未见退化”结论；
- `team_evidence` / Direct fact：仍未获得干净成员运行验证；
- `$500`：零使用。
