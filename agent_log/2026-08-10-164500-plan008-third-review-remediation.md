# Plan 008 第三轮独立审查整改与 B2 前置复审

时间：2026-08-10（Asia/Shanghai）

审查来源：`agent_log/2026-08-10-161500-plan008-third-independent-review.md`

实现基线：`a37dc761dff015e37649036077d87c737b9d91b5`

## 1. 范围与结论边界

本批只修第三轮审查要求在 B2 v4 Docker 前完成的 R3-H01、R3-M01、R3-M02。
paid B3/M1 与 L2 model-backed 继续 hard-disabled；没有运行 Cargo、真实 API、模型或模型下载，
没有读取、搜索、打印或复制 `.env.local`。

修复完成后的聚焦独立复审结论是：当前没有发现阻断 B2 v4 真实 Docker 执行的新增 P0/P1，
可以在提交并确保 checkout clean 后按 RONDO→Codex 严格串行执行。该结论只覆盖三个整改项和
B2 启动前置，不代表 B2 已验收，不代表 Plan 008 闭环，也不推导“无隐患、无缺陷、无 bug”。

## 2. R3-H01：绑定真实 watcher 活性

`mydev/scripts/with-build-lock.sh` 现在为每次运行在 owner 0700 的 metrics run directory 中创建
固定 inode、owner 0600 的 `watchdog-heartbeat`。wrapper 在启动 scope 前及每个监督循环刷新同一
heartbeat，并向 scope child 只注入以下机器事实：

- canonical `with-build-lock.sh` 路径；
- wrapper PID；
- `/proc/<pid>/stat` start ticks；
- heartbeat 的 absolute path。

`runtime_bridge.lease_from_watchdog()` 在 mint 时及每次 `guard.is_held()` 时同时重验：

- wrapper PID 仍存在且不是 zombie/dead；
- start ticks 未变化，避免 PID reuse；
- cmdline 指向当前 checkout 的 canonical wrapper；
- heartbeat 位于 Git common root 内，路径、owner、0600、dev/inode 未变化；
- heartbeat age 不超过 15 秒；
- 原有 cgroup membership、19G/21G/5G、canonical flock、Git common root 和环境 override 合同。

wrapper 异常消失时 PID/start ticks/cmdline 会立即拒绝；wrapper 仍暂存但主动监督循环停止时，
heartbeat 最迟在 15 秒窗口后使 guard fail-closed。heartbeat 刷新失败时 wrapper 主动停止本次 scope。

### 2.1 已授权的宿主反事实

反事实 A 使用短生命周期 user `systemd-run --scope`，人工满足旧合同的 scope 名、19G/21G/5G 和
canonical flock，但不经过规范 wrapper。结果：

```json
{"mint_rejected":true,"status":"passed"}
```

精确 unit `rondo-build-1000-99999999-81645.scope` 随后为 inactive，并执行 exact
`systemctl --user reset-failed`；没有遗留 unit 或进程。

反事实 B 由真实 wrapper 启动诊断，先成功 mint live proof，再只对已验证的 wrapper 发送 `SIGSTOP`，
等待 heartbeat 过期后检查既有 guard，最后在 `finally` 中 `SIGCONT`。结果：

```json
{"guard_rejected_stale_watcher":true,"status":"passed"}
```

专用证据：

`eval-data/build-metrics/r3-h01-counterfactual/20260810-163343-1000-82142/summary.env`

其精炼字段为：

```text
unit=rondo-build-1000-20260810163343-82142.scope
wrapper_status=complete
run_rc=0
final_rc=0
stop_reason=none
cleanup_reason=none
```

unit 最终 inactive；诊断未使用 `SIGKILL`，没有修改宿主配置或服务。

## 3. R3-M01：safe summary 与 pair ledger 崩溃收敛

no-API pair ledger 升级为 schema v3。每个 claim 机器固定：

`<pair_id>/no-api-safe/<run_id>.json`

作为 `safe_summary_path`。完成路径具有以下语义：

- safe summary 使用 canonical bytes 原子写；同路径重试只接受逐字节相同内容；
- `finish(completed=true)` 不信任调用方提供的 64 位字符串，而是从固定路径重读完整 schema、pair/side/run/
  harness identity 与 Docker 有效事实，重算 SHA-256 后再写 ledger；
- ledger 每次 reload 都持续回读 completed summary，缺失、symlink、schema/identity 漂移或 digest 漂移均
  fail-closed；
- 进程在 summary 已耐久、ledger 仍 active 时死亡，下一次 `docker_smoke` CLI 会在 eval checkout、配置、
  manifest、Harbor、watchdog、Docker 和新 claim 之前恢复该 slot 为 completed，输出结构化 recovered 并
  退出 0，不重跑任务；
- 遗留 active 若 summary 缺失或非法，则原子写为 `failed + blocked` 后拒绝；completed 状态的摘要漂移
  只拒绝，不改写历史。

真实 `fork/os._exit` 回归覆盖 summary 已写而 ledger 未写的切点；另覆盖不存在摘要、completed 后删除/漂移、
伪造 digest 和绕过早期 reconcile 直接 claim 的负例。

## 4. R3-M02：生产 Compose 强制 cap_drop ALL

Terminal-Bench production overlay 明确生成：

```yaml
cap_drop:
  - ALL
```

runner 的 `HostContainerContract.cap_drop` 固定为 `("ALL",)`，daemon inspect 的 `CapDrop` 必须精确相等。
overlay 缺失/漂移、runner 合同缺失、daemon 未回显或多出 capability 都 fail-closed。该投影与已冻结的
custom seccomp 反事实保持一致；仍禁止 privileged、`SYS_ADMIN` 和 `seccomp=unconfined`。

## 5. 轻量门禁与聚焦复审

- R3-M01/M02 四模块 pure/fake：75/75；
- R3-H01 runtime/diagnostic pure/fake：26/26；
- 统一 `just eval-test`：274/274，0 failure/error/skip；
- `just eval-lock`：85 packages；
- `bash -n mydev/scripts/with-build-lock.sh`：通过；
- `git diff --check`：通过；
- 聚焦独立复审：11/11 pure/fake，未发现阻断 B2 v4 执行的新增 P0/P1。

上述数字存在重叠，不相加冒充总数。宿主反事实不是 Docker 验收；fake inspect 也不能代替真实 daemon。

## 6. 仍未完成与下一步

- B2 v4 尚未运行真实 Docker，因此 image/VHDX/private-cgroup/container-metrics/seccomp/cap-drop 的组合
  仍未验收；
- B3 仍受 declared request role、pre-journal `publishing` 终态收敛和完整 paid Docker 耐久证据阻断；
- L2 仍受 launcher/child 生命周期绑定和实际已加载 runtime/model bytes 身份阻断；
- VHDX 文件身份、pair/safe-summary 父目录纵深和 canonical pair recipe 等低项仍存在。

下一步只按用户已授权范围，在完整 watcher 下使用受跟踪 v4 identity，严格串行运行 RONDO→Codex
两侧 no-API Docker pair；不拉取镜像，缺少 pinned image 即停止。任一侧失败都保留其终态并停止，
不改写或另起 pair。
