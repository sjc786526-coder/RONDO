# Plan 031：本地 Guardian 正式路由、L7 配置切换与 Local M3 收口

日期：2026-08-15 ｜ 分支/worktree：`031-local-guardian-config-switch`
方案：`plan/031-local-guardian-config-switch-execplan.md`

## 实质性改动

- **新增 `eval/rondo_eval/local_approval/guardian_bridge.py`**：正式 Guardian 与冻结 b10333 之间的
  身份门控 loopback 适配器。做且只做四件事：
  1. 用严格 loader 的本地 key（缺省时改用只存在于本进程内存的一次性 token）校验 RONDO→bridge 这一跳；
  2. 把入站 `input` 交给**公共 `build_static_payload()`** 归一化——与 token census、12k
     qualification 同一个边界，所以 `developer→user` 角色规范化、reasoning 投影与私有运输拒绝
     不存在第二套实现；随后按冻结服务合同重建请求（`text.format` → 顶层 `response_format`，
     不转发 `tools`，采样/输出预算取已资格化的值）。
     需要说清楚的是：**整条请求并不等于已资格化的 static 请求**——它带的是 Guardian 自己的
     instructions 与 schema，而不是 `STATIC_INSTRUCTIONS` + `rondo_static_approval_v1`
     （给一次真实审批 turn 前置一段测评侧指令会改变 Guardian 问的问题）。复用的是 `input` 归一化
     与决定"怎么产生答案"的服务合同。因此 census 的长度分布不用来给这条路线定界；
     超窗只会在 upstream 报错后 fail-closed。
  3. 请求前后各校验一次 launcher receipt，整份响应先完整缓冲，**身份后验通过前不写出任何字节**；
  4. 用 Guardian 自己送来的 schema 校验判定，然后才发出 `response.created` /
     `response.output_item.done` / `response.completed` 三事件 SSE。
     任何失败都是 HTTP 失败（401/400/502/503），永远不渲染成判定。
- **新增 `eval/rondo_eval/local_approval/formal_switch.py`**：正式 `--approve-for-me` 链验收入口。
  主 Agent 由 loopback 脚本化端点应答（本任务无云端授权，且 L7 要验的不是主模型），Guardian 侧走真链；
  只回读 `meta.json` / `E_final.json` 的 allow-list 字段，不带出任何证据正文。
  五个场景：`guardian-inherits-main`、`local-service-down`、`local-model-mismatch`、
  `local-model-backed`、`local-identity-drift`。
- **`client.py` 窄重构**：`decide()` 拆成 `require_service_identity()` + `post_decision_request()`，
  并把 envelope 解析中"取唯一 assistant `output_text`"一段提为公共 `response_output_text()`。
  顺序、异常类型与校验强度都未变，bridge 因此复用同一条运输与 envelope 校验，不另写一份。
- **`launcher.py`：SIGTERM 现在走既有的优雅停止路径**（见下）。
- **`mydev/justfile` 新增 `build-codex-cli`**：经仓库根共享 build lock 与看门狗构建 RONDO Local
  可执行文件。此前只有 `just codex`（裸 `cargo run`），没有受锁的正式构建配方。
- `eval/tests/test_local_approval.py`：新增 `GuardianBridgeTests`（11 项）、
  `FormalSwitchConfigTests`（6 项）与 launcher SIGTERM 回归 1 项。

## 疑难问题

### 一、冻结 b10333 与正式 Guardian wire 有三处不匹配，而不是一处

规划只确认了 `text.format` 缺口。实跑抓到的完整清单是三条，缺任何一条修复都过不去：

1. `text.format` 不被映射，必须转成 pin 专用的顶层 `response_format`（`server-common.cpp:940-949`）。
2. 冻结源码 `common/chat.cpp:3288-3292` 在 `tools` 与 grammar 并存时直接抛错；而正式 Guardian 请求
   **一定**带 `exec_command` / `write_stdin` / `view_image` 三个只读工具。适配器因此不转发 `tools`
   —— 这与方向 2 既有硬约束（static 组不给模型工具与自主取证）一致，不是为了绕开报错。
3. 真实 Guardian 请求的 `input[0]` 是 `developer` 消息，经 `map_developer_role_to_system` 会变成
   `system`；这正是 static payload v3 已经解决的形状。适配器复用公共 builder 而不是自己改角色。

### 二、watchdog lease 要求用**绝对路径**调用 wrapper

第一次启动 launcher 直接以 exit 70 失败。定位到 `runtime_bridge.py:459`：lease 会把
`RONDO_WATCHDOG_SCRIPT_PATH`（已 resolve 的绝对路径）与 wrapper 进程 `/proc/<pid>/cmdline` 里的
参数逐字比较，因此 `./scripts/with-build-lock.sh` 这种相对写法必然不匹配。改用
`"$(realpath .../scripts/with-build-lock.sh)"` 后 lease 正常。这是调用方式问题，不是 lease 逻辑缺陷。

### 三、launcher 收到 SIGTERM 不会清理现场（本次修复）

第一次真实生命周期结束时用 `kill -TERM` 停 launcher，结果：launcher 退出，但 **llama-server 仍在跑、
仍占 8080 与显存，receipt 也没被清掉**，最后是 with-build-lock 的
`cleanup: residual_processes_after_command` 兜底把它扫掉的。

根因：`run_server()` 只 `except KeyboardInterrupt`，而 Python 默认 SIGTERM 直接结束进程，
`_stop_server_process()` 与 `finally` 的 receipt 清理都不会执行。修复是把 SIGTERM 接进同一条中断路径
（`_graceful_termination()`），退出时恢复原 handler。修复后同样的 `kill -TERM`：launcher 报
`{"exit_code": 130, "status": "server_exited"}`，llama-server 退出，receipt 自清，端口释放，
wrapper 记 `cleanup: none`。前后两份 wrapper summary 就是这条修复的直接对照证据。

（附带记录一个未改的既有语义：优雅停止返回 130，`main()` 仍把非 0 的 server 退出码映射为
`INFRA_ERROR`。属于退出码契约，不在本任务范围内改动。）

### 四、独立审查发现：适配器允许在"未绑定 launcher 实例"时照常服务

独立审查指出一个真实缺口：`GuardianBridge.decide()` 拿到 `require_service_identity()` 的返回值后
**没有检查它是否为 `None`**。而 `settings_from_config` 允许 `model_path=""`，此时客户端返回 `None`，
于是 `/props` 身份校验、`/v1/models` 别名校验、receipt 前验与后验**全部被跳过**，适配器仍然返回 200 判定。
真实 `rondo.local.toml` 有 `model_path`，所以实跑证据不受影响，但这条路径本身违反"身份判定覆盖真实请求窗口"。

更糟的是它污染了测试：新增 bridge 测试原本沿用 `_local_data` 默认的空 `model_path`，
**10 项里有 9 项是在身份门关闭的状态下跑绿的**。

修复两处：适配器在 `identity is None` 时直接 fail-closed；测试改为为持有监听的本进程发布真实 receipt
（`_bound_bridge`），凡是要抵达 upstream 的用例现在都真正过身份门，并单独补一条
`test_bridge_refuses_to_serve_without_a_bound_launcher_instance` 钉住这个拒绝。

同一轮审查还纠正了三处：`switch_diff` 的 `touches_main_provider` 在结构上恒为 false（改成对两份 profile
**完整调用**里主 provider 行做逐字比较，并补反例测试证明它会失败）；docstring 把整条请求说成"与 12k
qualification 同形"是过头的（见上）；`_supported_schema` 的类型检查写在两次 `.get` 之后。
另外收紧了三处小项：失败响应加 `Connection: close`，standalone CLI 在只有一次性 token 时直接拒绝启动
（否则它对任何调用方都只会 401），SIGTERM handler 恢复时对 `previous is None` 加保护。

## 验收结果

### 构建与门禁

- `just build-codex-cli`：4m02s，`cargo build -p codex-cli --bin codex`，受锁与看门狗全程有效
  （wrapper 记 project=32.3GB / target=12.9GB / swap=0），产物 `codex-cli 0.147.0`，源码身份含 L2a。
- focused tests：`tests.test_local_approval` + `tests.test_config_hardening` +
  `tests.test_config_and_artifacts` 共 **159/159 通过，0 skip**。
- `just eval-lock`：85 packages，通过。未新增任何依赖。

### 正式 `--approve-for-me` 链（真实 CLI，主模型脚本化）

| 场景 | Guardian 去向 | bridge | 动作 | `terminal_status` |
|---|---|---|---|---|
| `guardian-inherits-main`（未设 provider） | 主 provider（1 次） | 不参与 | 执行 | `approved` |
| `local-service-down` | bridge（主 provider 0 次） | 503 | **declined** | `failed_closed` / `session_error` |
| `local-model-mismatch` | bridge（主 provider 0 次） | 400 `invalid_guardian_request` | **declined** | `failed_closed` / `session_error` |
| `local-identity-drift` | bridge（主 provider 0 次） | 4× 503，**upstream 一次都没调** | **declined** | `failed_closed` / `session_error` |
| `local-model-backed`（真实 12k） | bridge（主 provider 0 次） | 1 次，0 失败 | **执行** | `approved` |

- **真实 12k 正例**：`meta.model=rondo-local-approval`、`meta.reasoning_effort=low`、
  `decision=approved`、`terminal_status=approved`、`failure_reason=null`、`token_usage` 非空；
  `E_final` 的 `model` / `reasoning.effort` / `text.format.name=codex_output_schema` 与之一致；
  待审批动作 `command_execution` 为 `completed`，marker 文件生成，整轮 6.879s。
  判定是模型自己给的 allow，prompt 沿用既有付费诊断原文，未为凑 outcome 调整。
- **三类失败都不执行动作、都不伪装成业务 deny**：`decision=denied` 但
  `terminal_status=failed_closed` + `failure_reason=session_error`，与真正的业务 deny
  （`terminal_status=denied`、`failure_reason=null`）在证据里可区分。全部场景
  `main_endpoint_guardian_requests=0`，没有静默回退主 provider。
- **配置-only 切换**：cloud/local 两份 profile 由同一生成器产出，差异只落在
  `auto_review.model` / `auto_review.reasoning_effort` / `auto_review.model_provider` 三轴及其
  provider registry 条目；三轴在两份 profile 中都是显式写出的。主 Agent 侧不受影响由两处佐证：
  所有本地场景 `main_endpoint_guardian_requests=0`（脚本化端点的真实计数），以及两份 profile 组装出的
  完整调用里主 provider 那几行逐字相同（`main_provider_identical`，有反例测试证明它会失败）。
  云端侧只做离线对比，未发出任何云端请求。

### 覆盖边界（重要）

- **"结构化输出不合规"这一类只在定向回归里做到端到端**：
  `test_bridge_fails_closed_on_a_decision_outside_the_requested_schema` 证明 upstream 已被调用、
  bridge 仍返回 502 且一个 `data:` 字节都不写出。它**没有**在真实 12k 正式链上复现，因为要让已资格化的
  模型吐出不合规判定，只能改 prompt 或放宽 parser，两者都被禁止。正式链上证明的是 bridge 错误通道
  （400/503）到 RONDO fail-closed 的这一段。
- **身份后验（响应读回之后再验 receipt）**同样由定向回归覆盖：
  `test_bridge_withholds_a_decision_when_the_receipt_changes_in_the_window` 在服务应答的瞬间替换
  receipt，断言"模型确实答了、结果仍被扣住"。正式链上的身份漂移场景命中的是**请求前**这道门
  （因此 upstream 0 次调用）。
- **四次模型生命周期**，都在同一条正式入口上、未改动任何 prompt、parser 或判据；每次改动适配器后重跑，
  是为了让交付物与证据始终是同一份代码，不是为了换结果：
  1. 正例 + 身份漂移（正例跑了 2 遍，第一遍因我自己截断输出没记全，第二遍为完整留证）；
  2. SIGTERM 修复后复跑正例并首次验证优雅停止；
  3. 四处收紧后（schema 可判定性前移、handler 兜底 catch-all + 静默 `handle_error`、
     先读完请求体再鉴权、payload 构造移进 try）复跑；
  4. 独立审查整改后（见"疑难问题·四"）最终复跑。上表数字取自第 4 次。
  三个无模型场景同样在最终代码上复跑通过。

### 现场清理

结束时：无 llama-server / launcher / wrapper / cargo 进程，8080 空闲，
`eval-data/local-approval/` 为空（receipt 由 launcher 自清），显存回到 1,477 MiB 基线，
本任务 formal-switch 私有运行目录（含真实 evidence）已随成功退出删除。
身份漂移场景改写的 receipt 已按原字节还原并复核。

## 边界

只证明 12k 档位内这条正式链可用。未验证 16k、其余 5 条超窗证据、其余 41 条 12k 证据、47 条批量
generation、教师标签、横评、训练或模型优化；未跑 Docker、云 API、全量测试或全量 eval；
未修改 `mydev/` 下任何 Rust 源码（只加了一条 `mydev/justfile` 构建配方）；未读 `.env.local`；
未改 Plan 030 资格证据、runtime/model/template lock、census baseline 或历史结果。
真实证据正文、完整请求、模型输出、rationale 与 risk tags 均未进入终端、日志或 Git。
