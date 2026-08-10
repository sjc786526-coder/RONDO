# Plan 008 第二轮整改第三次独立审查

时间：2026-08-10（Asia/Shanghai）

审查对象：`a37dc761dff015e37649036077d87c737b9d91b5`

对比基线：`c5fa0c775179016d20f3884753a9369ee7c4c877`

执行方记录：`agent_log/2026-08-10-152813-plan008-second-review-remediation.md`

## 1. 范围与结论

本轮逐项回看第二轮独立审查的生产缺口，重点核对 pair 崩溃语义、Harbor 安装闭包、
ArtifactWriter/migration 恢复、watchdog 证明、Docker 有效事实、paid/M1、L2 launcher identity，
并从测试之外反向检查生产组合路径。

审查只做源码、文档、冻结资产和轻量测试核对；没有运行 Docker、Cargo、真实 API、本地模型或网络下载，
也没有读取 `.env.local`。除本日志外未修改实现或权威文档。

总体判断：`a37dc76` 的多数整改为有效的生产合同修复，不能视为表面补测；但**不能宣告本次任务、
Plan 008 或 P1 已无缺陷并闭环完成**。当前仍有一项资源安全证明缺口和两项 B2 v4 前应先收口的
生产缺口；B2 v4 也尚无真实 Docker 证据。B3/M1 与 L2 model-backed 虽被正确 hard-disable/拒绝，
但各自仍有明确解锁阻断。

按当前可达性分层：

- 未发现能使当前 hard-disabled paid 或 CPU-gated L2 被意外启用的 P0；现有状态口径总体诚实。
- B1 与 L1 协议状态可保留；`a37dc76` 的 pure/fake/loopback 静态整改有可靠通过依据。
- B2 v4 **不可验收**：真实 Docker 未运行，且下述 R3-H01、R3-M01、R3-M02 应先修复。
- B3/M1 **不可解锁**：至少 R3-B3-01、R3-B3-02、R3-B3-03 未完成。
- L2 只可称 CPU x64 前端/运行闭包与 client 协议前置；R3-L2-01/02 未完成，GPU/model-backed
  启动、推理和性能仍未验收。
- 此提交尚未进入主线：工作树 tracked clean，分支为
  `zz-done/0810-plan008-review-remediation`；`main == origin/main == 2cc9140022f69803afff7bc373e3beeee0579be9`。
  `zz-done/` 命名早于合并，不符合项目约定的顺序，也容易让人误以为已经交付。

## 2. 当前/B2 前置问题

### R3-H01（高，资源安全合同）：watchdog lease 不证明外层 watcher 仍在运行

`eval/rondo_eval/runtime_bridge.py:169-264,384-434` 能证明调用进程位于符合命名的 cgroup、
默认 `19G/21G/5G` 限额和 counters 可读、canonical flock 被占用、common root/环境覆盖符合约束；
但它不绑定或检查真正执行项目盘/50GB floor、host memory/PSI、外部 Cargo 和残留进程循环的
`with-build-lock.sh` watcher。

这些主动监督动作只存在于 `mydev/scripts/with-build-lock.sh:507-678`。同一用户持有 canonical lock
并创建同名同限额 transient scope 时即可 mint proof；更现实的非对抗边界是 wrapper 被 `SIGKILL` 而
scope/继承的 lock 仍存活时，内部 guard 没有 watcher PID/start-ticks/heartbeat 等活性事实可复核。
现有 `test_runtime_bridge.py` 的正例本身只靠合成 cgroup tree 与 held lock 即可签发 proof，未覆盖
wrapper 消失而 scope 继续存活。

这是项目 fail-closed 资源合同缺口，不是远程提权或要求复杂可信链。轻量修复应绑定一个由规范 wrapper
产生、可反复核验的 supervisor 实例/活性事实；必要时用短生命周期 user `systemd-run --scope` + flock
反事实确认旧路径会被拒绝。

### R3-M01（中，B2 证据事务）：no-API safe summary 与 pair ledger 不能崩溃收敛和持续复核

`terminal_bench/docker_smoke.py:715-733` 先原子写 safe summary，再单独将 pair slot 写为 completed。
若进程在两步之间死亡，summary 已耐久、ledger 仍为 active；下次 claim 会按
`terminal_bench/pair.py:206-219` 把它永久改为 failed/blocked，而不会根据固定 summary 恢复。

反方向也缺少消费校验：`PairSequenceLedger.finish()` 和 ledger reload 只检查传入 digest 的 64 位格式，
不回读 `eval-data/pairs/<pair>/no-api-safe/<run>.json`，也不重算内容哈希。现有测试可用不存在文件的
`"4" * 64` 完成槽位。完成后摘要被删除或漂移，ledger 仍会被当作 completed。

这不会伪造已经实际发生的 Docker 执行，但会浪费并永久阻断一次重型 pair，也使 completed ledger
不能独立证明其最小耐久证据仍存在。v4 是新的一次性 pair，建议在消耗真实 Docker 槽位前修复并覆盖
“summary 已写/ledger 未写”的进程死亡切点，以及 completed 后摘要缺失/漂移负例。

### R3-M02（中，B2 隔离合同）：生产 Compose 未落实 `cap_drop: ALL`

受控 seccomp 反事实明确使用 `cap_drop=("ALL",)`（`terminal_bench/namespace_diagnostic.py:185-203`），
`eval/seccomp/README.md:29-32` 也要求 custom profile 保持 `--cap-drop ALL`。实际 production overlay
`terminal_bench/materialize.py:520-535` 没有生成 `cap_drop`，生产 `HostContainerContract` 在
`terminal_bench/runner.py:558-573` 沿用默认空 tuple，测试 inspect fixture 也接受 `CapDrop=None`。

容器 UID 1000、NNP、非 privileged、没有 `SYS_ADMIN` 且通常 `CapEff=0` 会明显缓解风险；但 production
并不是文档和反事实所声明的同一隔离边界。应在 v4 Docker 重验前把 `cap_drop: ALL` 投影、inspect equality
和负测接入，或者正式修改安全合同；优先选择机器强制 ALL。

### R3-L01（低）：VHDX 数值未绑定同一文件身份

VHDX bytes 已正确进入 `max(system df, task logical, VHDX)` 的 40/60GB 门禁，宿主 free `<80GiB`
也会停止，这是有效修复。但 `runtime_bridge.py:1138-1209` 只返回 drive/free/length，未保留候选 VHDX
路径或文件 identity；Docker Desktop 生命周期中若候选路径切换或文件替换，可能跨文件计算增长。

### R3-L02（低）：pair/safe-summary 父目录和 durable schema 仍偏弱

- pair ledger 与 safe-summary 只给最终文件做防 symlink 检查，未逐级约束父目录；预置同 UID symlink
  可把文件写到 common root 外。按个人本地威胁模型列低，不要求复杂资产鉴权。
- safe-summary schema 对 sample/baseline/final 多为类型与非负校验，没有独立要求样本数大于零、终态资源归零
  及字段间一致；正常 supervisor producer 会执行这些条件，但耐久 sink 自身还不能独立证明。
- no-API pair gate 仍是可选 `--pair-validation`，且根 justfile 没有唯一 canonical pair recipe。standalone
  smoke 会标 `pair_validation=false`，不会伪造机器证据，但操作上容易被误当 B2。

## 3. B3/M1 解锁阻断

以下问题当前不可达，是因为 tracked pair lock 的 paid mode 在读取配置/密钥、启动 watchdog/Docker 前
就 hard-fail；它们不构成已有结果造假，但启用 B3 前必须修复。

### R3-B3-01（高）：生产 adapter 不发送 declared role

`terminal_bench/adapters.py:290-326` 为 main 与 Guardian 共用同一 provider/base URL，但不发送
`X-RONDO-Eval-Role`。proxy 在缺 header 时只能记录 inferred role；milestone/publication 已正确要求
`declared == inferred == final`，因此任一真实 paid run 都无法 completed/M1。

不能简单给共享 provider 配一个静态 `main` 或 `guardian` header：另一类请求会因 shape 与声明不一致被拒绝。
需要按请求来源可信地区分 main/Guardian 的生产投影，并增加 adapter→proxy 集成回归；若必须修改 RONDO Rust，
需重建并重新冻结 bundle，不能沿用旧 CLI。

### R3-B3-02（高）：pre-journal 验证失败会永久卡在 `publishing`

paid CLI 在 `terminal_bench/__main__.py:203-210` 先将 completed slot 持久化为 `publishing`，之后才执行
metadata/evidence/record/tree 校验和 ArtifactWriter publication。若 journal 创建前发生普通确定性验证错误，
`:230-233,306-318` 保留 publishing；重启恢复只会尝试恢复已有 journal/index，因没有 record 而再次失败。

这条路径会永久消耗 pair/run/预算槽，虽 fail-closed 且不会重复 API 或产生假 M1，但不是可接受终态。
整改日志已诚实记录，严重度应按 B3 解锁 blocker 管理，而不是启用后仍允许保留的普通 P2。

### R3-B3-03（中）：paid durable record/M1 没保留完整 Docker 安全事实

运行时已验证 custom seccomp、daemon actual image、private cgroupns、VHDX、容器 CPU/peak memory；但 paid
pair ledger 只保存 container metrics，正式 result 只保存 sample count/warnings，`assess_m1()` 也只复核 metrics。
启用 paid 前，应把足以重算 image/seccomp/cgroup/VHDX 的去敏证据耐久写入正式 record/ledger，并由 M1 回读。

另有两个低风险接线债务：`assess_m1()` 当前只有测试调用，没有生产阶段收口入口；publication/M1 只凭 index row
和 artifacts 字段，不复核 artifact tree 的持续存在。自然 publication 顺序能保证首次落盘时 target 先于 index，
因此后者主要是发布后删除/同 UID 漂移风险。

## 4. L2 解锁阻断

### R3-L2-01（高，当前 CPU gate 下不可达）：receipt 不绑定 supervisor/launcher 活性

`local_approval/identity.py:23-37` 的 receipt 只记录 llama-server 子进程 PID/start ticks/cmdline 等；
`launcher.py:529-555` 的 Python 父进程负责反复检查 watchdog，但 receipt/client 没有 launcher PID、watchdog
lease 或 heartbeat。若 launcher 被 `SIGKILL`/`os._exit`，Popen 子进程可能继续监听；client 仍可通过子进程
与 listener 校验并接受一个已脱离 watchdog 监督的模型服务。

当前 `launcher.py:520-523` 会在 CPU-only runtime 上、Popen 前拒绝，因此尚未形成错误能力声明；实现 GPU/model
serving 前必须让子进程生命周期与 supervisor/watchdog 失效绑定，并补父进程死亡故障注入。

### R3-L2-02（中）：receipt 中 digest 不等于实际已加载字节身份

launcher 在 Popen 前校验 model/runtime，receipt 保存相应 SHA；client 只比较 lock/config 与 receipt 字段，
没有重新哈希 model/runtime，也没有核对 `/proc/<pid>/exe`/映射的动态库或实际模型映射。因此最后一次 hash 与
Popen 之间替换文件、或运行中原位修改时，path/cmdline/receipt SHA 均可保持预期而实际字节不同。

这主要属于同 UID/并行修改和 TOCTOU 纵深，不要求签名体系；但 `doc/WBS.md:48-50` 所称“请求前后重验
runtime/model digest”过强。真实 L2 前应绑定可行的进程 executable/runtime closure identity，并至少在请求前后
重算模型文件身份，或收窄文档声明。

低项：两个 worktree 可并发发布 receipt 并 last-writer-wins（通常 fail-closed 为不可用）；
`doc/development-environment.md:426-430` 仍保留旧 doctor 状态
`infrastructure_ready_model_missing`，与当前 `cpu_frontend_ready_model_missing_gpu_unvalidated` 不一致。

## 5. 已确认有效的修复

- PairSequenceLedger 改为稳定 sidecar flock、同目录 0600 temp、file fsync、atomic replace、parent fsync；
  既有空/损坏 ledger fail-closed，四个进程死亡切点不会再把拓扑复位为 slot 1。
- pair 首槽绑定 clean eval harness commit，后续 claim/finish/reconcile/M1 精确核对；v4 lock SHA 重算为
  `9e274c05af1f87003c34dd6b5f8e8fb124711fe5a83cf3f03d582f55473d3d89`。
- Harbor console script、Harbor 包和 marker-active 传递运行依赖 closure 已绑定；当前实际安装 preflight 通过，
  76 个依赖/7303 个文件闭包与 lock 一致。它满足非对抗性身份漂移门禁，不需要签名或复杂可信链。
- ArtifactWriter journal v2、target/index/tree 绑定与 `recover_only()` 主体成立；migration 在分类前恢复，
  journal/target/index 三切点可一次重跑收敛；F-08 当前现场稳定 `already_applied`。
- watchdog 环境 override、common root、metrics/target 路径限制已收紧；VHDX、image ID、private cgroupns、
  exact container metrics 和 custom seccomp 的运行时校验已进入代码路径。
- no-API safe summary 已去敏并包含 image/VHDX/container metrics/effective seccomp；上述 R3-M01 是其跨事务与
  持续消费校验缺口，不否定单文件原子写实现。
- Local client 对 configured model 强制 receipt；PID reuse、cmdline、listener owner、endpoint 和请求前后同一
  receipt 的检查成立；CPU/GPU 能力口径已真正 fail-closed。
- role provenance 与非零费用口径主体已修复：inferred-only 不能完成，非零本地计价只写 estimated，
  `actual_usd=null`。现有三次账本 `requests={}`，所以 0 API/0 USD 仍成立。

## 6. 独立验证与证据边界

- 独立复跑 `just eval-test`：269/269，0 failure/error/skip，约 21 秒。
- 独立复跑 `just eval-lock`：85 packages。
- `git diff --check c5fa0c7..a37dc76`：通过。
- 静态 testcase 数也是 269；当前 Harbor 版本为 0.20.0，production installation validator 在现有 ignored
  venv 上通过。
- 统一测试有真实进程死亡、真实临时文件/索引和 loopback 覆盖，并非全部 mock；但 Docker/VHDX/daemon
  cgroup/seccomp 的新组合仍主要依赖 fake executor/构造 inspect JSON，不能替代 v4 真实 Docker。
- 执行日志所称“最后一轮独立 29/29”没有对应命令清单或独立日志，无法从仓库单独复核；本轮 269/269
  可独立复现，故不依赖该叙述。
- tracked worktree 在审查前 clean；本轮只新增本日志。ignored 约 217 MiB，包括允许保留的 `eval/.venv`、
  uv cache 与 `__pycache__`，没有 `target`。其中 justfile 的相对 `UV_CACHE_DIR=eval-data/uv-cache` 配合
  `uv --directory eval` 实际生成 `eval/eval-data/uv-cache`，与顶层 `eval-data/` 布局约定不一致，列为低风险
  交付卫生/路径问题。
- `actual_usd=0` 当前由空 requests 账本支持；未来若请求计价为零，不能只凭 `spent == 0` 推断供应商实际费用为零。

## 7. 验收与后续顺序

当前不建议把 `a37dc76` 合并/推送为“Plan 008 闭环完成”。建议顺序：

1. 先在当前 worktree 收口 R3-H01、R3-M01、R3-M02，并补窄回归；同时修正文档旧状态。
2. 只在上述代码稳定后，执行 v4 no-API RONDO→Codex 严格串行 Docker pair，保留两侧 safe summary、
   pair ledger、watchdog 与 Docker/VHDX 前后事实。任一侧失败即保留终态并停止，不改写或另起 pair。
3. B2 通过后再决定是否合并本阶段静态+Docker整改。B3 先完成 declared role、publishing 收敛、paid
   durable Docker 证据和生产 M1 入口，再冻结新 paid pair/batch/预算并单独取得真实 API 授权。
4. L2 先完成 supervisor 生命周期和实际 runtime/model identity，再实现/冻结 GPU runtime；模型权重下载与
   真实 GPU 加载/推理需另行授权，并继续与 Docker/重型 Cargo 严格串行。

“未发现 P0/P1”只能说明在当前 hard-disabled/gated 边界下没有已知立即误用路径，不能替代尚未运行的真实门禁，
也不能推导“无隐患、无缺陷、无 bug”。
