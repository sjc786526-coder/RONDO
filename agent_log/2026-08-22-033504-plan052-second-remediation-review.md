# Plan 052 二次整改独立复验

## 对象与结论

- 复验对象：`worktree-052-direction1-bottleneck-census@4aecafb287422b47025871411eb1a0fd027b16c5`
- 上次审查提交：`002e702`
- 结论：**验收不通过；当前提交的任务目标失败。** 上次 F1—F4 的主体修复均成立，但 public code-mode `exec`
  的早期错误输出仍可能完全绕过 delivery/render 统计，投影会把实际缺失覆盖误报成 `0 deliveries / measured`。
  该问题直接影响下一轮 C1 覆盖与候选决策，不是外围审计或可信设施问题。

## Finding

### F1（P1，阻断）：public code-mode 早期错误输出被误报为完整可测

`mydev/codex-rs/rollout-trace/src/tool_dispatch.rs:213-217` 对无 namespace 的 public custom `exec` 无条件抑制通用
tool-dispatch trace。正常成功路径由 code-cell trace 接管，这是合理的；但
`mydev/codex-rs/core/src/tools/code_mode/execute_handler.rs:40-58` 的源码解析/runtime 启动错误发生在 code-cell trace
创建前，`:88-95` 的首次响应错误发生在 `code_cell_started` 后、`code_cell_initial_response` 前。以上错误仍会作为
tool error 返回模型，却没有通用 `tool_call_ended` render，也可能没有可计数的 code-cell render。

当前 `eval/rondo_eval/harness_observation.py:961-998` 只从 `tool_call_ended` 建立 tool delivery，`:1002-1041` 只把
有 initial response/render 的 code cell 纳入 delivery；单独出现的 `code_cell_started` 不会成为 missing delivery。
随后 `:1077-1085` 在 delivery 为 0 时直接返回 `measured`。因此完整 capture 终态并不能阻止覆盖被高估。

本次用现有 synthetic bundle 语义加入一个 `code_cell_started`、随后正常结束 turn/rollout、但没有 initial response/render；
当前投影成功返回：

```text
model_visible_output_deliveries = 0
model_visible_output_truncation = measured
```

这与 `initial_response().await` 的真实错误路径一致；更早的 parse/runtime-start 错误因连 code-cell start 都没有，当前投影
更无法察觉。下一轮若出现这类运行，会把模型可见错误输出从分母中遗漏，并可能把 C1 的 partial/unmeasurable 覆盖写成
完整阴性，违背 schema-v2 的核心语义。

修复只需关闭这一观测缺口，不要求新平台：可在最合适的原生边界记录 public `exec` 的安全 delivery/missing 事实，或从
已有 conversation/code-cell 关系可靠派生；至少 dangling `code_cell_started` 必须标为 missing 或使投影失败关闭，且
cell 创建前的模型可见 error 也不能继续完全不可见。具体路线由执行者选择，只要不重复建设 telemetry、不记录正文、
默认关闭态及产品行为不变。

## 已确认正确的部分

- F1（上轮编号）：failed/incomplete 等非 completed inference 缺 usage 可保留类型化 C11；completed 缺 usage 仍拒绝，
  main/Guardian 的缺失数与已知 usage 合计均交叉核对。
- F2（上轮编号）：direct-model 与 code-mode-runtime 已分面；已有 tool delivery 缺 render 时会得到
  `partial/unmeasurable`，关联的 code-cell/tool render 一致时只计一次、不一致时拒绝。
- F3（上轮编号）：`repeated_exact_command_lifecycle_duration_ms` 只累加同 requester/command/cwd 的后续重复
  `exec_command` 自身 lifecycle。
- F4（上轮编号）：`turn.duration_ms` 已改为唯一 exec turn 的 `ended-started` 窗口。
- schema-v2、compare、Terminal-Bench 固定结果写入、raw trace 不归档、默认关闭和 v28 历史普查边界均未发现回归。
- 四问的当前结论仍应是“历史样本只能给出 C2/C1 弱信号，证据不足，不选行为优化”；E-A 继续不恢复。

## 本次轻量验证

- `tests.test_harness_observation`：20/20 通过。
- Terminal-Bench Local opt-in 发布与缺失投影停止：2/2 通过。
- 额外 `response.incomplete` + failed trace + no usage 投影：通过，得到 typed incomplete 与 unmeasurable usage。
- `XDG_RUNTIME_DIR=/tmp just eval-plan052-census | cmp ...`：与 tracked v28 JSON 逐字节一致。
- `git diff --check 002e702..4aecafb`：通过。
- 未重跑重型 Rust、Docker、真实 API、本地模型、全 workspace、CI 或 PR。一次从仓库根启动 unittest 的包路径错误、
  两次 `just` 默认 `/run/user` 临时目录被审查沙箱拒绝，均为调用环境问题；改用正确 `eval/` cwd 和 `/tmp` 后通过。

## 代用户作出的决策

1. **暂不授权 10 题 × 2 轮真实复测。** F1 关闭前，正式样本仍可能把 code-mode 早期错误输出误作完整阴性。
2. **保留现有原生 trace/API metadata → 安全离线投影架构。** 只补 public `exec` 的必要观测边界，不恢复 collector，
   不扩建 telemetry、数据平台或审计体系。
3. **停止/重跑规则按用户偏好解释为有边界的冗余。** 已产生付费模型行为或残缺观测的正式 slot 不静默替换、不改分母；
   但在正式 slot 前发现的 fixture、schema 接线、启动配置等普通小问题，可在授权与预算内窄修、复验后开始/恢复运行，
   不因一次可修技术错误永久结束任务。后续 ExecPlan/WBS 应用这一边界，不能继续写成“任何首次技术问题都禁止修复”。
4. WBS 所称 trace/API“终态核对”当前实际是 response population、completed/non-completed、分角色 usage 缺失数与已知
   合计核对；若不增加更细粒度对应关系，应把文案收窄到真实能力，避免宣称逐请求终态等价。
5. 修复仍只提交 Plan 052 工作树；不合并、不推送、不归档，不触碰主工作区或其他 worktree。

## 再验收条件

- public `exec` 在 cell 创建前失败、cell started 后 initial response 前失败、正常成功三类路径均有窄回归；前两类不得
  再输出虚假的 `0 deliveries / measured`，成功路径不得重复计数。
- body-free、raw trace 不归档、默认关闭和产品行为保持边界不变；文档能力与实现一致。
- 只需相关 Python 和必要的单个/窄 Rust 回归，不要求真实运行、全 workspace 或重型扩展。
- 工作树干净且有新的执行者提交；不合并、不推送、不归档。
