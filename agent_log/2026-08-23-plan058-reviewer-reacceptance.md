# Plan 058 reviewer reacceptance

## 结论

- 验收状态：**通过**。
- 任务目标：**完成**。
- 上一轮 P1 与三个 P2 已关闭，无未解功能 finding。Plan 058 `formal-v6` 继续作为有效历史结果，最终产品保留
  UnderDevelopment、默认关闭、root-only 的 C2 repeat guidance。

## 整改复验

1. `spec_plan.rs` 现在要求 `ExecCommandRepeatGuidance` 开启且
   `!turn_context.session_source.is_non_root_agent()`，因此 CLI/VSCode/Exec/MCP 等 root 入口保持原正式行为，
   ThreadSpawn、Review、Compact、MemoryConsolidation 与 Guardian 均不接入。legacy shell、runtime 和工具执行资格
   未改变。
2. tool-plan unit 覆盖 feature off/on、Guardian 与普通 ThreadSpawn，保留全部参数、身份不确定和副作用边界断言；
   JUnit 证明相关 unit `2/2` 通过。
3. 新增的 `core/tests/suite/repeat_guidance.rs` 覆盖 root off/on、ThreadSpawn、direct `exec_command` 以及
   CodeModeOnly root/non-root 五条 model-visible request 路径。测试及相关 crate 编译成功；CodeModeOnly 从同一已
   root-gated `ExecCommandHandler` spec 生成嵌套描述，没有第二条绕过路径。
4. integration 在当前代理环境中未收到 mock request，但未改动的既有 unified-exec 请求体对照也以相同的
   30 秒/0 request 失败，watchdog 均为 `stop=none`。这证明失败发生在产品断言前，不是本次 gate 回归；不要求为此
   重建已精确清理的约 27 GB Cargo target。
5. Phase A 已分别记录并核对 Plan 056 formal-v6 campaign lock `263cc3...` 与 v28 task lock `a9567c...`；ExecPlan
   过期待办、方向 1 WBS 和最终状态已收口。四个 detached Plan 058 measurement/source worktree 与可重建 target
   已精确清理，正式 campaign、binary、manifest、预算、trace、结果和 metrics 保留。

## 独立验证与决策

- 清除大小写 HTTP(S)/ALL proxy 变量后，本轮复跑六个相关 Python 模块，`262/262` 通过。执行者此前的
  214 pass/42 fail/6 error 是 localhost 请求被代理后的环境噪声，不是 Rust 或 Phase A 修改造成的回归。
- `git diff --check` 通过；Plan 058 与 main 在写入本报告前均 clean，四个临时 worktree 已不在 worktree registry。
  未运行 Cargo 重建、Docker、真实 API、正式 campaign、全 workspace、CI、PR、本地模型或训练。
- 代用户决定：接受未实际跑通的 integration 作为环境受阻证据，因为代码已编译、关键 unit 已执行、同一既有对照
  复现相同前置失败且静态调用链无旁路；不重建 target，不重跑 API/Docker/题目/round。正式 `retain` 决策不变，
  feature 继续默认关闭。

## 当前交付状态

本地分支已通过验收；不合并、不推送、不归档，等待用户批准后由主线整合者处理。
