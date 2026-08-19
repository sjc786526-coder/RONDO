# Plan 044 / M-5 code-mode 明文通信修复验收

日期：2026-08-20
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
代码范围：`4f227cb..6fe1379`

## 结论

**本轮产品修复验收通过。**

`ToolCallSource::CodeMode` 的 message 确实来自模型 JS 对象的本地序列化，
`encrypted_function_args=None`，应当与 `DirectPlaintextMessage` 一样走明文 communication；
保留 `Direct` 的 encrypted-argument 语义也是正确的。修改位于唯一共享构造口，
因此同时修复 `spawn_agent`、`send_message`、`followup_task` 以及调用同一 helper 的 team-route notice，
没有发现新的功能性回归。

五条 Rust 回归覆盖了：

- CodeMode 构造层不再产生 `encrypted_content`；
- 发给模型的 `AgentMessage` 组装结果不含伪 encrypted field；
- `trigger_turn` 两种语义均保持明文；
- `DirectPlaintextMessage` 保持明文；
- `Direct` 保持 encrypted。

执行者做的反向验证（临时回退后 3 条 CodeMode 测试失败、2 条 Direct 测试继续通过）
与缺陷边界一致。此次验收不重复重型构建；已静态复核完整 diff、相关调用点及 cm4 等值证据。
执行者报告的 Rust 5/5、Python 206/206 可以作为本轮验收证据。

## Finding

### [P2] 同步仍在发布旧归因的权威子 WBS 与任务 Plan

根 `doc/WBS.md` 已改成正确结论，但 `doc/WBS/multi-agent-trusted-evidence.md:341-348`
仍写“Root 的加密推理被带进成员会话、产品 vs relay 待定”，
`plan/044-multi-m5-real-workflow-and-nondegradation-execplan.md:307-309`
仍把错误归因列为当前阻断。它们会让下一执行者再次考虑 endpoint 对照或重复归因。

这是文档同步遗漏，不否定产品修复；应在 v3 批次内一并改成：
CodeMode 明文被误标、产品缺陷已修、当前阻断是旧 bundle 尚未重建。

## 代用户作出的决定

**批准继续第 1 步：重建 Multi runtime bundle，并一次性冻结新合同。**

授权范围与约束：

1. 以已提交且干净的
   `6fe1379e4a77a604407b335fd94b3cc81d53501a` 为 Multi bundle 源码身份；
   重型 musl 构建必须走仓库 build lock 和资源看门狗，门禁不可用时 fail-closed。
2. 不覆盖或删除旧 bundle / 旧锁。新增 `multi-m5-runtime-v2`，
   保留冻结 Codex v0.147.0 baseline 身份不变；workflow / nondegradation 新锁使用 v3 并显式引用 runtime-v2。
3. v3 一次冻结：
   - provider endpoint、terra root/member 与 medium effort；
   - upstream attempts 与 2 秒指数退避；
   - 正式 `unpriced_stop_threshold=1`；
   - `any_unpriced_invalidates_observation=true`；
   - runtime bundle 的 source commit 与所有二进制/manifest 摘要。
4. loader、readiness、archive/loopback 的 lock/runtime 身份必须一致投影，旧 v1/v2 归档不得升级冒充 v3。
5. 同步上述两处 stale 文档；只跑相关 loader、readiness、rehearsal 和定向测试，不扩大到无关全量 Rust。
6. 本步骤不调用真实 API、Docker 或本地模型，`$500` 继续零使用。
7. v3 离线验收通过后先停下交回复审；不要直接启动 clean smoke，更不得启动正式 Gate 1/2。

建议创建新的专用 measurement worktree；不要在状态不明时改动旧的 detached measurement tree。

## 当前状态与下一指示

- 本轮 code-mode 产品修复：**验收通过**；
- M-5：仍未完成；
- Gate 1：未通过；Gate 2：未启动；
- 冻结 runtime bundle：仍是带缺陷的旧版本，禁止 smoke；
- 下一步：按上述授权重建 runtime-v2、冻结 workflow/nondegradation-v3、完成离线门禁后停下交验。
