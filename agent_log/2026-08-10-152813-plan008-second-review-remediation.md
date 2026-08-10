# Plan 008 第二轮独立审查整改

时间：2026-08-10（Asia/Shanghai）

问题源：`agent_log/2026-08-10-145120-plan008-remediation-independent-review.md`

实现基线：审查对象 `c5fa0c775179016d20f3884753a9369ee7c4c877`

## 1. 结论与边界

逐项回读审查日志、生产代码和故障注入后，确认 R2-H01～H05 全部存在；R2-M01～M12
中与当前阶段相关的契约缺口也存在。本批以轻量、fail-closed 的机器合同收口，没有建设
签名、权限或复杂可信链。

本轮没有运行 Docker、Cargo、真实 API 或本地模型，没有下载权重，没有读取、搜索、打印或
复制 `.env.local`。因此当前结论是：

- B1 冻结与 L1 协议可保留为完成项；
- 旧 no-API v3 只证明旧 pair lock/schema 下的 RONDO→Codex 正常路径已经发生，不能作为
  第二轮新机器门禁的 Docker 验收；
- 新 tracked identity 为 `p1-fix-git-pair-v4`，lock SHA-256 为
  `9e274c05af1f87003c34dd6b5f8e8fb124711fe5a83cf3f03d582f55473d3d89`；它不复用、改写或删除
  common root 中保留的 v3 ledger，避免 schema v2 与历史身份冲突；
- B2 新门禁已代码落地并经 pure/fake/loopback 验证，仍待新 schema 下的双侧 Docker no-API
  重验；
- paid B3/M1 保持 hard-disabled/未运行，实际 API 调用仍为 0，项目代理/账本费用仍为 0 USD；
- L2 仅 CPU x64 frontend/runtime closure 和无模型前置就绪，GPU/model-backed 服务、真实推理与
  性能验收未完成，不再表述为“只差权重”。

## 2. Pair、公平性与 M1

### 2.1 R2-H01：pair ledger 崩溃重置

`PairSequenceLedger` 升级为 schema v2：

- flock 改在稳定的 `<ledger>.lock` 侧车文件上，避免 replace 后继续锁住旧 inode；
- ledger 本体使用同目录 0600 temp file，完整 write、file fsync、atomic replace、parent fsync；
- 已存在的空文件或超限/非普通文件一律视为损坏，不得重建为 slot 1；
- fork/`os._exit` 覆盖 temp write、temp fsync、replace、parent fsync 四个切点，重开时不会清空已存
  pair 拓扑或重新接受 slot 1。

### 2.2 R2-H04：跨槽 eval harness commit

首次 claim 必须提供 clean eval harness commit，pair ledger 在 pair 级别绑定该 commit。后续 slot、finish、
paid publication 和 M1 都必须精确一致；普通跨 commit 执行会在启动前 fail-closed。

### 2.3 R2-H05 / M02：paid publication 与 durable M1

paid 终态改为可恢复状态机：

1. claim 写 `active`；
2. Docker 结束后先将 `container_id/cpu_usage_seconds/peak_memory_bytes` 持久化并写
   `publishing`；
3. `ArtifactWriter` 完成 durable result publication；
4. 回读 `runs.jsonl` 中唯一 record，将 canonical record SHA-256 写入 pair ledger，再收敛为
   `completed`。

重启时若发现 `publishing`，先从 durable index reconcile，不重执行外部任务。`assess_m1()` 不再只聚合
两条 record；它必须读取 enabled paid pair 的 durable ledger，并核对两槽 completed、run/side/slot/round、
harness commit、publication digest 和 container metrics。S2 仍与 M1 独立。

### 2.4 R2-M01 / M11：Harbor 与 no-API 耐久证据

受跟踪 pair lock 现在绑定：

- 实际 `.venv/bin/harbor` console script 字节，只将绝对 shebang 规范化为固定占位符后哈希；
- Harbor package/dist-info 普通文件闭包；
- 从 Harbor metadata 出发、考虑 marker 后的传递运行依赖版本及包内文件闭包。

闭包排除 `.dist-info/RECORD`：该文件是安装器派生清单，会记录随 venv 根变化的 console script
绝对 shebang 哈希；console script 本身已有独立的规范化全字节身份。当前传递闭包为 7303 个文件，
SHA-256 为 `3b5e7c1da111a9e7d6dc0a6433647179fbcae4e024d7ea9527980d4e548ba59d`。
跨 venv 根和仅 `RECORD` 漂移保持同一闭包，真实包文件漂移仍改变闭包。

新 `p1-fix-git-pair-v4` 的 no-API 成功槽在写 ledger `completed` 前，先原子保留
`eval-data/pairs/<pair_id>/no-api-safe/<run_id>.json`。该文件只含 pair/bundle/Harbor/seccomp/harness 身份与
去敏计数/资源摘要，ledger 另写其 SHA-256。旧 v3 的 raw trial/safe summary 已不存在，本批没有伪造
或事后补写历史证据。

## 3. Watchdog 与 Docker 有效事实

### 3.1 R2-H02：外层 override

watchdog proof 只保留三个可验证的路径类配置：

- `RONDO_PROJECT_ROOT` 的 canonical path 必须精确等于 Git common root；
- `RONDO_BUILD_METRICS_DIR` 和 `CARGO_TARGET_DIR` 必须是已存在、leaf 非 symlink、canonical 位于
  common root 内的路径；
- 其他 `RONDO_BUILD_*` 全部拒绝。

每次 guard 继续重验 common root dev/inode、解析后允许路径、规范 flock/cgroup 及
`MemoryHigh=19G` / `MemoryMax=21G` / `MemorySwapMax=5G`。

### 3.2 R2-H03：VHDX 增长

`DockerCounterReading`/sample 现在传递 Docker Desktop VHDX bytes 及相对本次 baseline 的增长。
40GB 告警和 60GB 停止使用 `max(docker system df growth, task logical growth, VHDX growth)`；宿主实际
free space 低于 80GiB 仍立即停止。基线与后续 sample 的 VHDX 可见性不一致时 fail-closed。

### 3.3 R2-M04 / M06：daemon image 与 container metrics

在 runner lease 内用 bounded daemon image inspect 将冻结 registry digest 解析为 actual image ID；exact task container
另同时核对 `Config.Image` 和 inspect 顶层 `Image`。paid 合同强制 `require_container_metrics`，对 exact
container + inspected user 读 cgroup v2 `cpu.stat usage_usec` 与 `memory.peak`。缺失、换容器、CPU 倒退或
峰值非正数都 fail-closed；daemon inspect 的 `HostConfig.CgroupnsMode` 还必须是字面值 `private`，
避免 host cgroup namespace 把宿主根指标冒充任务容器指标。

### 3.4 R2-M05：paid custom seccomp

paid 入口与 no-API 共用受跟踪 profile path/source/effective SHA，不再默认回落 builtin seccomp。仍禁止
privileged、`SYS_ADMIN` 与 `seccomp=unconfined`。这项本轮只通过静态/pure/fake 接线验证，未在 paid
容器中执行。

## 4. 归档、请求归属与费用

### 4.1 R2-M03：一次性 migration 恢复

`apply_migration()` 先验证冻结输入，再通过 ArtifactWriter 锁内 journal v2 恢复路径收敛，最后才判定
`pending/conflict/already_applied`。dry-run 保持只读；遇到中断 journal 时明确 fail-closed 并要求使用
`--apply`。journal 落盘、target rename、index replace 三个持久化切点均能一次重跑收敛；原 work
已不存在的现场仍稳定返回三项 `already_applied`。

### 4.2 R2-M09：role provenance

缺少 `X-RONDO-Eval-Role` 时仍可按 payload shape 推断诊断 role，但 metadata 保留 `role`、
`role_provenance`、`declared_role`、`inferred_role`。只有 provenance 为 `declared`，且 declared/inferred/
最终 role 一致的请求，才能满足 milestone、completed publication 和 M1。inferred-only 保留为失败
诊断，不冒充 verified role。

### 4.3 R2-M10：`actual_usd`

冻结价格 × usage 的费用只写 `estimated_usd`。非零消费未查供应商账单时，`actual_usd=null`；
零请求/零费用保留 `actual_usd=0.0`。这不改变现有三条诊断的 0 API / 0 USD 结论。

## 5. L2 前置边界

### 5.1 R2-M07：launcher/service/model 实例

model-backed launcher 在主仓 `eval-data/local-approval/launcher-identity.json` 发布 0600 私有 receipt，
绑定 nonce、PID/start ticks、实际 cmdline hash、runtime/model digest、model path/id、endpoint 与 loopback
listener owner。receipt 路径拒绝祖先 symlink 和 common-root 逃逸。client 在 service identity probe 后、decision
请求前以及 response 返回后重验同一 receipt/进程/监听者；任一变化都拒绝结果。

### 5.2 R2-M08：CPU/GPU 状态口径

冻结 lock 明确记录 `capability=cpu_only_no_model` 和
`model_backed_structured_output=not_run`；launcher 将当前前端投影为
`runtime_capability=cpu_only_x64`、`model_backed_validation=not_run`。无模型 doctor 返回
`cpu_frontend_ready_model_missing_gpu_unvalidated`/78；launcher 返回
`model_missing_gpu_runtime_unvalidated`。即使补入权重，GPU runtime/model-backed 启动参数未验证时仍不启动服务。

## 6. 测试与未运行项

最终独立终审又发现并收口四个生产合同缺口：

- paid CLI 的早期 reconcile 原先只能读取 index，无法处理 ArtifactWriter 已有 journal/target、index 尚未
  replace 的崩溃状态。`ArtifactWriter.recover_only()` 现在只在既有 results/runs 锁内恢复，不创建 staging
  或新 claim；生产 CLI 对 journal 落盘、target rename、index replace 三个 `fork/os._exit` 切点均一次收敛，
  且恢复前不读取配置/密钥、不启动 watchdog、Docker、Harbor 或 backend；
- Harbor 传递闭包移除上述 root-dependent `RECORD`，保留 console 独立身份和真实包文件漂移门禁；
- 容器指标要求 private cgroup namespace，并将 daemon actual image reference/ID、VHDX
  baseline/peak/final/peak-growth、容器 ID/CPU/峰值内存、daemon 回显的 custom seccomp digest 投影为
  `DockerExecutionResult`；
- v4 no-API 与 paid 一样强制容器指标。no-API safe summary 的 `docker` 证据不可缺失或为 null，必须严格
  校验并耐久保存上面的镜像、VHDX、容器指标和有效 seccomp 事实，否则不能把 pair 槽写成 completed。

实现期定向门禁：

- ArtifactWriter + Terminal 五模块：92/92 pure/fake 通过，包含 pair 四个进程死亡切点、publication
  三个进程死亡切点、M1 durable ledger、可移植 Harbor closure、no-API/paid 证据负测；
- Docker supervisor/runtime/namespace 与 Terminal 联合：133/133 pure/fake 通过，包含 watchdog override、
  VHDX、daemon image、private cgroup namespace、container metrics 和 custom seccomp；
- Local approval + contracts/config/artifacts：83/83 pure/fake/loopback 通过，包含 launcher receipt 替换、
  listener owner 和 CPU/GPU 状态；
- migration 定向：32/32 通过，覆盖三个 publication crash point 与当前 `already_applied` 现场；
- API role/budget proxy：18/18 通过；Terminal-Bench results + ArtifactWriter/config：53/53 通过；
- 上述集合存在重叠，不相加冒充总数。`py_compile` 与 `git diff --check` 在各子模块收口时通过。

统一收口门禁：

- `just eval-sync`：frozen 安装 83 packages；
- `just eval-test`：269/269，0 failure/error/skip；
- `just eval-lock`：85 packages，`uv lock --check` 通过；
- `git diff --check`：通过。

最终独立终审在全部差异稳定后复核 pair/M1/Harbor、Docker/watchdog、migration/L2/docs 三组边界；
最后一轮独立定向 29/29 与 `git diff --check` 通过，未发现 P0/P1，结论为当前改动可提交。
唯一保留 P2 是下述 paid journal 创建前纯验证失败的终态收敛待办；它不改变当前 paid hard-disabled、
B3/M1 未运行的事实，也不会产生虚假 M1 或重复执行。

本轮明确未运行：

- 真实 Docker，包括新 pair/schema 的双侧 no-API 和 paid custom seccomp；
- Cargo、Rust 构建/连接/测试；
- 真实 OpenAI API、B3/M1 与供应商账单查询；
- 模型权重下载、llama.cpp 真模型服务、GPU runtime、真实推理、L2a/L3/L4、训练与 canary。

paid 生产 adapter 当前尚未发送 `X-RONDO-Eval-Role`；shape inference 只能形成失败诊断，
不能满足 completed/M1。B3 解锁前必须把 declared role 的发送和接收端一致性纳入同一生产投影与回归，
不能只修改 pair lock 的 enable 开关。

paid 入口还存在一个不影响当前 hard-disabled 状态的终态收敛待办：completed 结果进入
`publishing` 后，若后续纯 evidence/record 验证在 ArtifactWriter journal 创建前失败，当前会保留
fail-closed 的 `publishing`，不会产生虚假 M1 或重复执行，但也不会自动转成 `failed`。B3 解锁前应把
“尚无 publication journal 的验证失败”与“已有 journal 的可恢复崩溃”分开处理，并补生产回归。

## 7. 权威文档口径

已同步：

- `plan/008-p1-terminal-bench-and-local-approval-execplan.md`：重写当前状态，增加第二轮关键决策；
- `doc/WBS.md`：B2 改为新门禁待 Docker 重验，B3/M1 hard-disabled，L2 收窄为 CPU x64 前端；
- `doc/WBS/eval-benchmark.md`：明确新 pair/M1/Harbor/Docker/metrics 契约和历史 v3 证据边界；
- `doc/WBS/local-approval-model.md`：明确 launcher receipt 和 GPU/model-backed 未验收；
- `doc/eval-data-layout.md`：更新 pair/safe summary、容器 metrics、role provenance 和 `actual_usd`。

历史 v3 证据、第二轮审查结论与本批新代码门禁始终分层记录，没有用 skip、fake 或旧
Docker 结果代替当前未运行的真实门禁。
