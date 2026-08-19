# Plan 044 / M-5：修复 code-mode 把明文团队消息误标为 encrypted content

日期：2026-08-19 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
范围：验收审查 1×P0 产品缺陷。**本轮未调用真实 API，$500 授权零使用。**

## 结论口径

**M-5 未通过，门 1 未通过，门 2 未启动，不存在"未见退化"结论。** 正式 `$120` 账本仍不存在。

## 审查是对的，我上一轮的归因是错的

我上一轮说成员请求里的 `encrypted_content` 是"Root 的加密推理被 fork 带进成员会话"。**这是错的。**
用 cm4 原始抓包做等值比较（只比长度与相等性，不打印密文）：

```
spawn_agent 明文 message 长度        = 139
成员请求 agent_message.encrypted_content 长度 = 139
author/recipient                     = ('/root', '/root/worker')
逐字节相等                            = True
是可打印文本                          = True
```

那个字段里装的就是 `spawn_agent` 的**明文任务描述本身**，不是任何密文，也和 Root 的推理无关。
`fork_turns:"all"` 不是必要条件。审查的归因成立。

## 缺陷与修复

`multidev/codex-rs/core/src/tools/handlers/multi_agents_v2.rs::communication_from_tool_message()`
只把 `ToolCallSource::DirectPlaintextMessage` 当明文，其余一律走
`InterAgentCommunication::new_encrypted()`。

而 code-mode 的嵌套调用（`core/src/tools/code_mode/mod.rs:345`）由运行时把模型的 JS 对象序列化成
`ToolPayload::Function`，并固定 `encrypted_function_args: None`，以 `ToolCallSource::CodeMode` 分发 ——
**这里的 `message` 必然是明文**。于是链路变成：

```
new_encrypted(message)                        // 明文被当成密文
  → InterAgentCommunication.encrypted_content = Some(<明文>)
  → to_model_input_item()
  → AgentMessageInputContent::EncryptedContent { encrypted_content: <明文> }
  → provider 拒收：invalid_encrypted_content
```

对照 cm4：成员 8 次推理 8 次失败，Root 22 次 0 失败。成员从未完成一个回合，
因此任何团队工具都不可能被它调用，门 1 根本无从判定。

**修法**（按审查决定 2，最小且不扩大）：`CodeMode { .. }` 与 `DirectPlaintextMessage` 一同走明文分支。
**没有**把所有来源统一降成明文 —— `Direct` 保留既有 encrypted-argument 语义，
因为那条路上模型确实可能发来加密参数，由 `ToolCall::direct_source()` 区分
（判据是 `encrypted_function_args == Some([])`）。

同一 helper 也服务 `send_message` / `followup_task`，一并受益。

## 定向回归（Rust，走仓库 build lock）

新增 `multidev/codex-rs/core/src/tools/handlers/multi_agents_v2_tests.rs`，5 条：

1. code-mode `spawn_agent` 消息不得产生 `encrypted_content`；
2. **组装层**断言：渲染出的 model input item 里不得出现 `encrypted_content` 字段
   （生产环境的故障只在子线程请求体里才看得见，只测 handler 不够）；
3. `send_message` / `followup_task`（`trigger_turn` 两种取值）同规则；
4. `DirectPlaintextMessage` 仍为明文；
5. **`Direct` 仍为 encrypted** —— 防止"修复"退化成一刀切。

结果：`5 passed; 0 failed`（`cargo test -p codex-core --lib -- tools::handlers::multi_agents_v2::tests::`，
经 `scripts/with-build-lock.sh`，看门狗 `status=0 stop=none cleanup=none`）。

**并做了反向验证**：临时把修复回退后重跑，3 条 code-mode 用例 FAILED、2 条 Direct 用例仍 ok。
这证明这组回归钉住的正是本缺陷，且没有把 `Direct` 语义一起改掉。随后已还原修复。

## 重要状态：冻结的 bundle 仍带此缺陷

`eval/locks/multi-m5-runtime-v1.json` 的 `source_commit=7a2ff68` 早于本次修复，
**冻结二进制里没有这个 fix**。因此：

- 现在跑任何 smoke 仍会以同样方式失败，这也是不动用 `$500` 的实证理由；
- 必须先按审查决定 5 重建并冻结 v3（runtime bundle 身份 + endpoint + retry/backoff +
  continuation threshold + "任一 unpriced 使观察无效"），才谈 clean smoke。

readiness 仍 `ready=true`（它校验的是磁盘上 bundle 的摘要，与源码树无关）。

## 验证

- Rust 定向：5/5 通过；反向验证 3 FAILED / 2 ok（预期）。
- Python 定向：`test_multi_m5_exec`、`test_multi_m5`、`test_multi_m5_trace_evidence`、
  `test_terminal_bench`、`test_api_budget_proxy` 合计 **206 用例全绿**。
- 未调用真实 API、Docker 或本地模型；未跑无关全量重型 Rust 测试。

## 下一步（未做）

1. 重建 Multi runtime bundle（含本修复），一次性冻结 **v3**：bundle 身份、endpoint、
   retry/backoff（门 1 的 2 秒退避目前还没进锁）、continuation threshold、
   `any_unpriced_invalidates_observation`。
2. 用全新身份做一次 clean smoke，验收条件：`conservative_exposure_usd=0`、无 infra taint、
   **成员至少完成一次工具调用**、trace 绑定无误，且**成员请求的 agent message 是 plaintext input
   而非伪 encrypted content**。
3. 只有 clean smoke 成立后，才谈 instruction / terra 是否遵守协议。
4. 门 1 通过后才启动门 2。
