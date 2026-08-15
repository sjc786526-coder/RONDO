# Plan 035：关闭 Plan 031 独立验收的两项非阻断观察

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

关闭 `agent_log/2026-08-15-050341-plan031-independent-acceptance-review.md` “非阻断观察”的两项：

1. `test_bridge_fails_closed_when_the_local_service_is_unreachable` 实际命中的是“未绑定 launcher 实例”
   身份门，而不是服务不可达；该测试必须真正覆盖服务不可达。
2. `guardian_bridge.py` 文件头声称 pin 收到的是“exactly the request shape its 12k qualification covered”，
   口径偏强，需要收窄为实际合同。

本任务不改变 L7、Local M3 或 12k qualification 的完成状态，因此不更新任何规划状态文档。

### 完成/验收标准

- [x] 目标测试的失败不再由缺少 `model_path`、缺少 launcher receipt 或未绑定身份触发；身份前置条件在测试
      语义上已经满足（有 `model_path`、有 receipt、receipt 通过 `require_listener=True` 的进程/监听校验）。
- [x] 目标测试的失败来自对配置的本地服务 endpoint 建立连接后发生的受控 transport/service-unavailable 错误。
- [x] 目标测试断言 bridge 返回 503、响应不含 `data:`、不含 allow/deny 判定。
- [x] 目标测试有断言证明确实抵达 transport failure：本地服务侧记录到实际连接数，且异常链为
      `UpstreamUnavailableError <- ServiceUnavailableError <- OSError`。
- [x] `test_bridge_refuses_to_serve_without_a_bound_launcher_instance` 继续独立覆盖未绑定身份场景，并断言其
      `ServiceUnavailableError.__cause__ is None`，与 transport 场景清晰区分。
- [x] 生产代码的身份门控、HTTP 错误语义、schema 校验与 fail-closed 行为没有被削弱、绕过或删除。
- [x] `guardian_bridge.py` 文件头不再声称完整 Guardian 请求与 qualification static 请求同形。
- [x] `GuardianBridgeTests` 全类通过，0 skip；直接相关的 local-approval focused tests 通过。
- [x] `git diff --check` 通过。

## 2. 范围

### 允许修改

- `eval/tests/test_local_approval.py`
- `eval/rondo_eval/local_approval/guardian_bridge.py`
- `plan/035-plan031-nonblocking-cleanup-execplan.md`
- 一份 `agent_log/2026-08-15-*-plan035-plan031-nonblocking-cleanup.md`
- 仅当测试暴露真实相邻缺陷时，才允许窄改直接相关的 local-approval 代码。

### 不允许修改

- Plan 034 worktree 及其任何文件。
- `training/`、L5b/L6、教师标签、baseline、测评结果账本。
- `mydev/` Rust 产品代码。
- `doc/WBS.md`、专项 WBS、`doc/WBS-COMPLETED.md`、`README.md`、`AGENTS.md`。
- Plan 031 与既有 `agent_log/`。
- 两份未跟踪的 `doc/research/RONDO Multi*.md`。

### 不允许读取/查看

- `.env.local`、`rondo.local.toml` 及任何真实私有数据。

## 3. 硬约束

1. 不得为了让测试到达 transport 失败而放宽生产身份校验、HTTP 错误语义、schema 校验或 fail-closed 行为。
2. 不得把 transport failure 伪装成业务 deny，也不得让 bridge 在失败路径上写出任何 `data:`。
3. 不引入真实模型、真实网络、模型生命周期或长时间等待；fixture 必须稳定、快速、无脆弱竞态。
4. 不使用 Cargo、Docker、本地模型、真实 API、训练、批量测评或大资产下载。
5. 不合并 `main`、不推送远端、不删除 worktree、不触碰 Plan 034 worktree。
6. 只跑与改动直接相关的 focused 测试，不跑全量。

## 4. 软性建议

- 复用现有 `GuardianBridgeTests._bound_bridge`、`FakeApprovalServer`、`_guardian_request()`、
  `_post_to_bridge()` 等既有设施，不新建测试框架。
- 服务不可达的 fixture 可采用“端口被 receipt 进程持有但连接被立即丢弃”的形态。
- 文件头收窄只改能力口径，不做文档重写。

## 5. 当前状态

### 已完成

- 复现证明：旧 fixture（无 `model_path`，endpoint 指向 `127.0.0.1:1`）在 `bridge.decide()` 时抛出
  `UpstreamUnavailableError <- ServiceUnavailableError("local Guardian route is not bound to a launcher
  instance")`，且对配置 endpoint 的 TCP 连接尝试为 0 次——与
  `test_bridge_refuses_to_serve_without_a_bound_launcher_instance` 命中同一道门。
- 代码路径确认：`require_launcher_identity()` 走 `_verify_process(require_listener=True)`，要求 receipt 的
  pid 真实持有 `127.0.0.1:<port>` 的 LISTEN socket。因此在身份门通过之后，“connection refused”在结构上不可达；
  可达的“服务不可达”形态是连接被接受后立刻断开（或读超时）。
- 调用顺序确认：`require_service_identity()` 先读 receipt（无网络），再由 `verify_service_identity()` 对
  `/props` 发起本条路径上的第一次真实网络接触，transport 错误在 `_get_json()` 内被转换为
  `ServiceUnavailableError`。
- 测试改造：新增 `_UnreachableLocalService`（`socketserver.ThreadingTCPServer`，接受连接后不作任何应答直接
  关闭，并计数），`_bound_bridge` 改为接受 `base_url`，两个测试补充异常链断言。
- `guardian_bridge.py` 文件头口径收窄。
- 测试执行与提交。

### 当前工作

- 已完成。

### 本任务剩余步骤

- 无。

### 阻塞项

- 无。

### 当前验收状态

- `GuardianBridgeTests`：12/12 通过，0 skip，8.68s。
- local-approval focused：`tests.test_local_approval` 全模块 115/115 通过，0 skip，22.87s。
- `git diff --check`：通过。

### 关键决策记录

1. **不改生产代码。** 复核确认 bridge/client 在“receipt 有效 + endpoint 不可达”路径上的行为本来就正确
   （transport 错误 -> `ServiceUnavailableError` -> `UpstreamUnavailableError` -> 503，无 `data:`），旧测试
   只是没有走到这条路径。因此本任务只修测试与注释口径。
2. **用“接受后立即断开”而非“连接被拒绝”。** 身份门要求 receipt 进程持有该端口的 LISTEN socket，指向一个
   关闭的端口会先被身份门拦下；持有端口但不应答既满足身份前置条件，又是 llama-server 卡死/半退出后的真实形态，
   且无需等待超时。
3. **两个测试用异常链结构而非文案区分。** 未绑定身份场景的 `ServiceUnavailableError.__cause__ is None`，
   transport 场景的 `__cause__` 是 `OSError`，语义清晰且不依赖字符串匹配。

### 交接边界

- 本任务完成后冻结此计划。
- 分支保持隔离，不合并、不推送；Plan 034 合并后再由后续任务 rebase/复验并决定合并。
