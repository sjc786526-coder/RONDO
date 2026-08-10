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

## 6. v4 真实 Docker 结果

整改提交 `07d0a487f8c498032a6da7ce4fd37a91c607bdac` 的 clean checkout 上，按用户授权启动
`p1-fix-git-pair-v4` no-API pair。只执行了 slot 1 RONDO；没有拉取镜像、没有 Cargo、API、模型或
密钥读取。命令由规范 `with-build-lock.sh` 包裹，使用 `/mnt/c` 作为 Docker Desktop 宿主数据盘事实。

运行标识：

- run id：`tb-no-api-rondo-e2cd95f5bc72`；
- trial：`rondo-p1-rondo-fce8cbf561f7`；
- pair ledger：`eval-data/pairs/p1-fix-git-pair-v4-no-api.json`，SHA-256
  `23ceecfebfb058fe6dd814df09a217674f62374740d3e2282b90f4aff069edef`；
- ledger schema v3，`blocked=true`、slot 1 `failed`、`next_slot=1`；
- watchdog summary：
  `eval-data/build-metrics/p1-v4-noapi-rondo/20260810-164759-1000-97046/summary.env`，SHA-256
  `95c4c23a886d0048a11fa898e310b739c9964ef464e353562bf8efc6d5ae47a0`。

真实 daemon/宿主证据：

- pinned image reference 与 daemon image id 均为
  `sha256:389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74`；
- Docker system df total baseline/final 均为 `18128000000` bytes；本任务 bytes baseline/final 均为 0；
- Docker Desktop VHDX baseline/peak/final 均为 `69467111424` bytes，增长 0；
- Windows 数据盘 free bytes 从 `196717150208` 变为 `196717023232`；
- exact container `658be8a9987961bf16cf7f653e851a1d25005cc0f7d6ef246429efd2dcd6cec5`：
  CPU `0.237511` seconds，cgroup peak memory `9838592` bytes；
- daemon 回显 custom seccomp SHA-256
  `a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf`；
- contract 同时核对 private cgroup namespace、non-root user、`cap_drop=ALL`、NNP、memory/swap/pids、
  network/mounts；最终 task bytes 为 0，监督器完成精确清理；
- wrapper `run_rc=70`、`final_rc=70`、`stop_reason=none`、`cleanup_reason=none`；项目峰值约
  `12091826176` bytes，宿主文件系统仍余 `908160872448` bytes，峰值内存约 `2209697792` bytes，swap 0。

失败发生在 Harbor adapter install。host return code 为 0，但 trial 的 `exception_info` 是
`AdapterError: container command failed`，trace 精确定位到 `adapters.py` 上传 bundle 后的
`chown -R 0:0 && chmod ...` 复合命令。原执行层丢弃了 stderr，不能从现有证据独立证明具体失败的 syscall；
结合 daemon 已核对 `cap_drop=ALL` 与命令位置，可强归因为运行时 ownership mutation 和 capability-free
安全合同不兼容，但不把该推断写成直接内核证据。失败发生在任何 agent/fake 请求前：
`fake_requests=0`、fake contract 未满足、tool round-trip=false、API 调用 0、费用 0 USD。

按照 pair 合同和用户授权，失败终态未改写，未运行 Codex slot 2，也未另起 pair。保留的 trial
`result.json` SHA-256 为 `01486136523de7d3a6f030d75aa1ffe10a64a583a125c3cd0866d7c4e8c199dc`，
`exception.txt` SHA-256 为 `c949f5714ed9ecedcb15d76ba7222011b930345d2297c30a4b89bc04fc90d35f`。

### 6.1 失败后的无 Docker 窄修

不改动失败 ledger/work evidence，也不重跑 Docker。adapter 的 install 和 run 路径均移除运行时
`chown`，且没有通过添加 capability 或放宽 `cap_drop=ALL` 规避问题：

- Harbor 上传后的 2 个目录与 3 个 bundle 文件逐项验证类型、非 symlink 和实际 owner `0:0`；
  只有全部通过才 chmod、重算 SHA-256 和执行 `--version`；
- root 在 run 阶段只允许 `pwd -P` 精确等于冻结 workdir `/app/personal-site`，再对该引号包裹的精确目录
  执行 `chmod -R a+rwX`；`/`、其他 workdir 或失败 chmod 均在 agent/secret 前拒绝；
- 1000:1000 agent 自行创建 CODEX_HOME、secrets 和 agent log 目录，验证 `.git`、refs、logs、index 可写；
- agent 读取 Compose secret 前验证实际 owner `1000:1000`、普通非 symlink、非空、可读且不可写，随后自行
  创建 0600 auth JSON；root 不读取 secret。

定向 `test_terminal_bench` 17/17；adapter + docker-smoke + pair 联合 40/40；统一
`just eval-test` 277/277、`just eval-lock` 85 packages；`py_compile` 与 `git diff --check` 通过。
这些只是 pure/fake 证据，不能把本次失败改写为通过，也不能证明下一次 Docker 已成功。

### 6.2 失败后聚焦独立复审

独立复审核对了现场 ledger、watchdog、trial/result/exception 哈希、adapter diff 与文档，聚焦 5/5
通过；结论仅为本次窄修可以提交，不是 B2 验收或全项目缺陷结论。复审保留以下边界：

- 真实 `docker compose cp` 是否产生期望的 root ownership 尚未到达；不符合时新门禁会安全失败；
- workdir 递归 chmod、`/logs/agent` owner、secret bind 的 1000:1000/只读有效态尚未由 Docker 重验；
- failed run 按合同不生成 completed safe summary，因此本节 daemon 数值是详细人工日志证据，不能作为
  completed B2 的机器摘要；
- failure trace 没有原始 stderr，具体 syscall 原因只能强归因，不能写成独立直接证明。

复审指出的上传目录 symlink 低项已顺手收紧：2 个目录与 3 个文件均显式拒绝 symlink；随后重新运行
`test_terminal_bench` 17/17、统一 `just eval-test` 277/277、`just eval-lock` 85 packages 和
`git diff --check`，均通过。

## 7. 仍未完成与下一步

- B2 v4 已在 RONDO 侧真实验证监督与 daemon 有效态，但 agent 链路未完成；Codex 侧未运行，不能认定
  双侧 B2 验收；
- B3 仍受 declared request role、pre-journal `publishing` 终态收敛和完整 paid Docker 耐久证据阻断；
- L2 仍受 launcher/child 生命周期绑定和实际已加载 runtime/model bytes 身份阻断；
- VHDX 文件身份、pair/safe-summary 父目录纵深和 canonical pair recipe 等低项仍存在。

当前失败 pair 永久保留；未来是否创建新 pair 并重跑 Docker，须以新的 clean harness identity 和用户
后续指示为准。
