# Plan 031 独立验收审查

日期：2026-08-15
审查对象：`031-local-guardian-config-switch@61a538eed1dbe582f3d7a41e8bc49443c23e1cbd`
任务合同：`plan/031-local-guardian-config-switch-execplan.md`

## 结论

- **验收通过**：未发现会破坏正式审批闭环、fail-closed、provider 隔离、身份门控或清理语义的阻断问题。
- **任务目标完成**：本分支已实现 L7，Local M3 的完成声明与代码、定向回归和正式链证据相符。
- 该结论只适用于当前专用 worktree/分支；本地 `main` 仍停在 `26b4770`，尚未合并或推送，因此主分支上的
  项目状态尚未吸收 Plan 031。

## 审查范围与主要判断

逐文件审查 `61a538e` 相对规划提交 `1b32193` 的 11 个 tracked 文件，并按合同核对以下主链：

1. `guardian_bridge.py` 只在 loopback 上接收正式 Guardian Responses 请求；model、`text.format` 与可判定
   schema 先验不符时，在调用本地模型前拒绝。入站 `input` 复用公共 `build_static_payload()` 做既有 v3
   角色/推理投影，冻结 b10333 收到顶层 `response_format`，不收到其不能与 grammar 共存的 tools。
2. 本地请求前绑定 launcher receipt 和服务身份，响应完整读回后再次校验同一 receipt；后验通过前不发送
   成功 SSE。服务、身份、envelope 或 schema 的错误都成为固定 HTTP 错误，不被伪造成业务 deny。
3. 判定按 Guardian 自己携带的受支持 schema 本地复验后才原样交给生产 parser。结构化输出错误用 fake
   upstream 证明“模型已回答但 bridge 不写出 `data:`”；正式 CLI 又证明 bridge 的 HTTP 错误会使动作
   `declined`、证据终态为 `failed_closed`，两段组合足以支持该失败合同，无需故意诱导真实 12k 输出坏 JSON。
4. `formal_switch.py` 的 local profile 只覆盖 `[auto_review]` 的 model、effort、provider 及对应 provider
   registry；主 Agent provider 由独立配置固定。CLI 环境不继承 ambient provider/代理/工具配置，bridge
   凭据只进入目标子进程环境，不进入请求正文、日志或 tracked 文件。
5. `client.py` 的拆分保持原有一次请求、无 redirect、响应大小上限和严格 envelope 解析；`launcher.py`
   的 SIGTERM 处理复用既有 terminate/kill 与 receipt finally 清理路径，没有改变模型启动资格门。

所选 eval-side 适配器路线合理：receipt 是 local-approval/eval 侧已有语义，把它塞入通用 Rust Guardian
反而会扩大产品边界；本提交没有修改 `mydev/` Rust 源码，只增加了受锁正式构建入口。

## 独立复验

- `git diff --check 1b32193..61a538e`：通过。
- focused unittest：`tests.test_local_approval`、`tests.test_config_hardening`、
  `tests.test_config_and_artifacts`，**159/159 通过，0 skip**，22.967s。
- `uv lock --directory eval --check`：85 packages，检查通过。
- 使用 worktree 当前 `codex-cli 0.147.0` binary 重跑三项无模型正式 `--approve-for-me`：
  - `guardian-inherits-main`：Guardian 确实到主 endpoint 1 次，动作完成，证明 provider 轴不是静态假设；
  - `local-service-down`：bridge 4 次 `service_unavailable`，marker 不存在，动作 `declined`，
    `terminal_status=failed_closed`，主 endpoint 收到 0 次 Guardian 请求；
  - `local-model-mismatch`：bridge 1 次 `invalid_guardian_request`，marker 不存在，动作 `declined`，
    `terminal_status=failed_closed`，主 endpoint 收到 0 次 Guardian 请求。
- 没有启动第 5 个真实模型生命周期。执行日志已经明确记录最终代码上的真实 12k 正例和身份漂移复跑；
  本轮对相同 GPU 正例再跑一次不会增加新的判别力，反而违反“尽量减少模型生命周期”的任务约束。
- 宿主机只读复核：无 llama-server、launcher、bridge、formal-switch、Cargo/build wrapper 或 GPU compute
  残留；8080 未监听；launcher receipt 不存在，`eval-data/local-approval/` 为空。工作树在写本报告前 clean。

## 非阻断观察

1. `test_bridge_fails_closed_when_the_local_service_is_unreachable` 的当前 fixture 没有 `model_path`，实际先命中
   “未绑定 launcher 实例”门，而不是建立有效 receipt 后再触发 socket connection refused。正式
   `local-service-down` 同样证明的是 launcher/service 已消失这一常见异常。代码中有效 receipt 后的网络失败
   仍由 `LocalApprovalClient` 明确转换为 `ServiceUnavailableError`，再由 bridge 转为 503，因此不影响本次
   功能结论；以后若正好维护该测试，可改名，或先绑定 synthetic receipt 再关闭 endpoint，不为此另建任务。
2. `guardian_bridge.py` 文件头有一句“exactly the request shape its 12k qualification covered”表述偏强；同一
   docstring 后文、Plan、WBS 和执行日志都已准确说明只有 input 归一化与 serving contract 复用，Guardian
   instructions/schema 与 qualification static 请求不同。它是注释口径问题，不影响实现或能力边界，后续触碰
   该文件时顺手收窄即可，不阻塞合并。

## 代用户作出的决策

1. **接受 eval-side adapter，不要求改 Rust 产品代码。** 当前路线更窄，也保持通用 Guardian 语义干净。
2. **接受“定向坏输出/响应后身份漂移 + 正式 HTTP fail-closed”的组合证据。** 不为凑形式而修改 prompt、
   放宽 parser 或诱导合格模型故障，也不增加新的审计设施。
3. **接受脚本化主 Agent 与云端离线恢复证明。** L7 的变量是 Guardian 路由；本任务没有云 API 授权，真实云端
   复跑既无必要又会引入费用/外发。
4. **保留 launcher 优雅停止的 130 -> `INFRA_ERROR` 映射。** 清理功能已正确；人为停止不是一次成功服务运行，
   当前非零语义可接受。若将来有调用方需要区分“操作者停止”和“基础设施故障”，再作为独立退出码合同处理。
5. **不改写 Plan 030 的冻结历史日志。** Plan 031 的执行日志、WBS-COMPLETED 与本审查已经留下 SIGTERM
   实测反例和修复事实；回写旧历史会破坏形成时点记录。

## 边界

本审查未运行 Docker、云 API、16k、批量 generation、训练、横评、全量测试或全量 eval；未查看
`.env.local` 内容，未输出/保留真实 `E_final`、模型文本、rationale 或 risk tags；未合并、未推送、未删除
worktree、未重命名分支。
