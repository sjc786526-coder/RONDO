# Plan 008：Terminal-Bench P1 与本地审批前置设施实施日志

时间：2026-08-09 ～ 2026-08-10（Asia/Shanghai）
计划：`plan/008-p1-terminal-bench-and-local-approval-execplan.md`
开发 worktree：`.claude/worktrees/0809-p1-terminal-bench-local-approval`
测量 worktree：`.claude/worktrees/0810-p1-measurement`（detached、clean）
冻结 RONDO source commit：`cb652e1418e06d53171755963ad9eb8075259ffc`
冻结 Codex 基线：`rust-v0.147.0` / `be6e8eac029b183056b7e4402879f15d2c85f61b`

## 1. 结论

本批完成了以下可独立使用的设施：

- 顶层轻量 `eval/` 共享合同、严格配置、Standard/Responses Lite `E_final` 解析、`PolicyIdentity`、
  无工具静态审批 payload、原子结果归档、持久预算账本与统一退出码。
- Terminal-Bench B1 的 Harbor/TB2.1/task/image 精确冻结，B2 的统一 runner、Codex/RONDO 双 adapter、
  生产 Harbor backend、结果解析/归档、Docker 实时监督、no-API fake 链路和预算代理。
- 两侧静态 musl CLI、`codex-code-mode-host` 与同一官方 v0.147.0 musl bwrap 的自包含 runtime bundle。
- 方向 2 的 L1 静态审批协议；L2 的 llama.cpp server 配置、client、doctor、fake server、结构化输出
  校验与启动入口。

本批没有完成 B3/M1。完整 Codex Docker no-API agent 链路在进入冻结 bwrap 后，被 Docker 守护进程
默认 seccomp 下的嵌套 user namespace 限制拒绝；root 和固定 UID/GID 1000 两条路径结果一致。计划明确
禁止为凑绿弱化安全边界，因此没有启用 privileged、`SYS_ADMIN` 或 `seccomp=unconfined`，也没有关闭
Codex workspace-write sandbox。

三次 B3 诊断尝试均在第一个官方 API 请求前因设施问题 fail-closed；独立终审后已从正式结果库移除，
预算账本仍保留三个不可复用的尝试槽位。真实 OpenAI API 调用 **0 次**、实际费用 **0 USD**。
没有同一任务 Codex/RONDO 两侧 `completed` 结果，因此 M1 保持未通过。

L2 只达到“代码与项目局部运行时已就绪、缺模型”状态。当前没有模型权重，按任务边界没有下载权重、
没有启动真实本地推理、没有量显存/上下文/首 token/总耗时；L2a、L3/L4、训练和正式 canary 均未进入。

## 2. 授权、安全与工作区边界

- 用户一次性授权了项目内编辑/依赖/测试、Docker、受监督重型构建与清理、最多四个 Luna benchmark
  run、按官方 API 直接按量计费总硬上限 20 USD，以及完成后的合并/推送。
- API Key 只允许由 Git common root 的 `.env.local` 严格 loader 在运行时加载。执行过程没有打开、搜索、
  打印、复制、哈希或记录该文件内容；日志里没有密钥、长度、前后缀或派生值。
- 云端/本地模型参数只从 ignored `rondo.local.toml` 读取；受跟踪的
  `rondo.local.example.toml`/`rondo.secrets.example.env` 只定义接口。
- API 容器只拿 loopback budget proxy 随机生成的短生命周期下游 token；真实上游 key 只留在代理内存，
  每次上游请求重新写 Authorization。代理 metadata 只存 request/body SHA 与去敏统计。
- 所有 Cargo、链接、Docker、项目局部运行时下载和重型清理都经
  `mydev/scripts/with-build-lock.sh`，每次要求同一 flock、systemd cgroup 和可读资源计数器。Docker 又在
  daemon 侧按 5 秒周期采样容器、镜像/缓存、宿主实际数据盘和 exact task label。
- 进入任务时 main 与 origin/main 都是 `4df098ca5a75b998682c79864f17c93a8f6f1e0b` 且干净。
  `0809-remaining-test-failures` 的用户未跟踪日志未被读取、移动、清理或覆盖。

## 3. 共享 eval 合同

### 3.1 配置和秘密

`eval/rondo_eval/config.py`：

- 通过 Git common dir 定位主仓库根，使 linked worktree 共用唯一 `.env.local` 和 `rondo.local.toml`。
- TOML 使用明确 schema/allowlist，密钥只允许通过 `api_key_env` 间接引用；Key 不能直接进入 TOML。
- `.env.local` 必须是 common root 内的普通非符号链接文件、Unix mode `0600`；按 UTF-8 `KEY=VALUE`
  数据解析，不 source shell；拒绝 `export`、命令替换、shell 展开、重复项和接口外变量。
- 只解析并向目标子进程返回当前 provider 所需变量。未使用的可选变量不阻断当前任务。

### 3.2 `E_final`、policy 和静态审批

`eval/rondo_eval/evidence.py` 与 `contracts.py`：

- Standard：policy 必须来自非空顶层 `instructions`；Lite：必须有唯一 `additional_tools` developer item，
  后接唯一 developer policy message。两者并存、缺失、重复、错位或 malformed 均 fail-closed。
- `PolicyIdentity` 对 policy 的原始 UTF-8 bytes 做 SHA-256，不 trim、不 Unicode normalize；解析不确定时
  标为 unknown，禁止聚合或作为公平性证据。
- 静态 payload 删除顶层 `tools`、Lite `additional_tools`、warehouse-only
  `internal_chat_message_metadata_passthrough` 和 provider-private `encrypted_function_args`；保留既有
  function call/output、approval reason 与 retry reason。
- canonical JSON 使用 UTF-8、排序键、紧凑 separators；Luna-static/Sol-static/Local-static 共用同一
  provider-neutral bytes，认证、URL 和 header 不属于逻辑公平边界。
- 静态出站另带“只能依据现有证据、不得调用工具”的固定约束，不篡改 Guardian policy 本身。

### 3.3 归档

`eval/rondo_eval/artifacts.py`：

- `ArtifactWriter` 统一拥有私有 staging、no-overwrite rename、结果 schema、secret scan 和
  `runs.jsonl` 文件锁追加；adapter 只返回结构化 outcome 和 artifact refs。
- run id 固定为毫秒时间戳 + track/side/round；重复 run id、符号链接/祖先逃逸、异常字段、无效
  completed 记录和 secret marker 均拒绝。
- 付费前先原子 claim 私有 staging 并在持久账本消耗一次不可复用 run-id；已 claim 后即使 Docker、
  watchdog、parser 或 publication 抛异常，也先发布分类失败记录与实际账本费用，再返回非零退出码。
- 原始产物写 Git common root 的 ignored `eval-data/runs/<run_id>/`；受跟踪索引写开发 worktree 的
  `eval/results/runs.jsonl`，不会污染 detached measurement source 的 clean 判定。
- 结果终态为 `completed|agent_failed|infra_failed|budget_stopped|cancelled`；早期 Harbor 失败可归档
  “unavailable”证据，不伪造正常 metadata/E_final。
- Harbor 原始树只按明确 allowlist 归档去敏 job/trial 摘要、agent transcript、verifier 结果；不复制
  config、lock、raw log 或 exception trace。RONDO 的动态 `E_final/meta` 另按完整生产 schema、review id、
  Guardian source tag/commit 与 `PolicyIdentity` 二次校验后，以稳定编号原样写入私有归档。

## 4. Terminal-Bench B1/B2

### 4.1 精确冻结

受跟踪 `eval/locks/terminal-bench-2-1.json` 固定：

| 对象 | 身份 |
|---|---|
| Harbor harness | `0.20.0`，commit `459ff6ec99417589b7f679d14ddf3b3f0ae4f1dc` |
| Harbor wheel | SHA-256 `4b7e48223aea2384cdb8c9eff35eaebd482fc9b1ec09f8193a121c47356ff19a` |
| TB 2.1 dataset | `terminal-bench/terminal-bench-2-1@ffccbe05ee73a9d59518217f294ad711bda39304` |
| P1 task | `terminal-bench/fix-git` |
| task archive | SHA-256 `16948b980df9d96de616a205f5acca1c5d395de83ff4f8ffabcafacb93226f2e` |
| linux/amd64 image | `alexgshaw/fix-git@sha256:389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74` |
| no-API fixture base | `ubuntu@sha256:019e8eb29a85e74d64925745884f2ec79aa27e3feab36353d24656f4d6b89467` |

Harbor telemetry 固定关闭，并发固定 1。materializer 从精确 dataset checkout 读取唯一 task，复核 HEAD、
scoped clean、dataset digest、Harbor Packager 内容 digest 和 task metadata，再复制到 ignored staging，
把唯一浮动 image tag 替换为 digest；运行前再次检查 task/overlay 全部身份。

官方 Harbor hello-world oracle 已在受监督真实 Docker 下通过：1 个任务、`completed`、reward 1.0、
0 error。它只证明 harness/Docker 生命周期，不冒充 TB2.1 模型任务。

### 4.2 runner 和双 adapter

`eval/rondo_eval/terminal_bench/`：

- `runner.py` 以 `RunSpec` 冻结 side、task/digest、binary manifest、模型/effort、approval/sandbox、网络、
  timeout/retry/budget；两侧公平指纹不一致即拒绝。
- `materialize.py` 只产生单任务、单并发、本地 `--path` Harbor 命令，禁止 repo/latest、dataset upload、
  retry、env-file、agent-env 等旁路。
- `adapters.py` 的两侧 adapter 继承 Harbor 0.20 Codex 解析，但覆盖安装/运行：不 npm install、不使用
  `@latest`，只上传冻结 CLI、code-mode-host、bwrap，并在本地/远端核对 SHA。
- 固定 `supports_websockets=false`、`auto_review`、`on-request`、`workspace-write`、
  `sandbox_workspace_write.network_access=true`、主/Guardian Luna、Guardian low、`code_mode_host=true`。
  Codex baseline 不注入它不支持的 RONDO S1 字段，实际 Guardian model/effort 必须由代理 metadata 证明。
- Compose overlay 固定 task service user `1000:1000`、2GiB memory、3GiB memory+swap、pids 256、唯一
  task label；显式拒绝 root agent、privileged、`SYS_ADMIN` 和 seccomp unconfined。
- root 只负责上传后 chmod/SHA/version、目录准备和从 Docker secret 写 0600 auth；Codex、task 命令和
  cleanup 以非 root 运行。真实上游 key 不进入 Docker argv、Compose environment 或文件日志。
- `results.py` 严格解析唯一 job/trial；completed 要求 reward、timestamps、agent result，早期 errored
  trial 的 optional 字段按明确空值归档；host 非零且无 job tree 合成为 `infra_failed`，不会被二次 parser
  异常覆盖。没有已验证 API metadata 的 adapter/CLI 退出统一归设施失败，不能归因给模型。

### 4.3 API 预算代理

`eval/rondo_eval/api_budget_proxy.py`：

- 上游 base URL 只允许 `https://api.openai.com/v1`；下游只监听 `127.0.0.1`，用随机临时 bearer，
  并以恒定时间比较；上游 Authorization 始终重写为 common-root loader 提供的 key。
- 只允许 Responses JSON/SSE；拒绝 WebSocket、hosted tools、redirect、自动 retry、超大请求/响应。
- Lite header 只接受单个精确 `true` 并转发。请求角色分 main/guardian；Guardian 必须实测
  `gpt-5.6-luna` + `low`，unknown role 不能成为 milestone evidence。
- 价格快照日期 2026-08-10：Luna Standard input 0.20 USD/M、cached input 0.02 USD/M、output
  1.20 USD/M；保留 >272K 长上下文与 cache-write multiplier。最坏 1.05M input + 128K output
  每请求先预留 0.755400 USD。
- batch 总上限 20 USD、每 run 5 USD、最多 4 个 run；账本 0600 原子持久化。usage 缺失/非法时扣掉
  全预留并停止 run；进程崩溃后的未结预留可恢复，不能绕过总上限。

### 4.4 Docker 专项监督

`docker_supervisor.py` + `runtime_bridge.py`：

- 只有当前 PID 位于严格 `rondo-build-*.scope` cgroup v2 且 9 个必要 counter 均可读，才签发
  `WatchdogProof`；每次采样重验 PID/cgroup/counters，丢锁或未知状态 fail-closed。
- pull/build/run/Harbor host lifecycle 每 5 秒读取 Docker system df、exact-label task objects 和 Docker
  Desktop 实际宿主数据盘剩余；新增 40GB 告警、60GB 停止、宿主低于 80GiB 停止。
- 超时、锁丢失、counter 失败、阈值失败或 host 非零时先停当前 host，再只清 exact-label 已观察容器；
  cleanup 非零、超时或有残留同样 fail-closed。host 成功后给 Compose 最多 30 秒自然 teardown grace。
- 冻结二进制 probe 只允许 absolute/canonical/regular/non-symlink host path，O_NOFOLLOW fd 校验 SHA 和
  inode 稳定，容器固定 `--network none --read-only`、只读 bind、固定 entrypoint `--version`。

Docker 最终基线/收尾：

| 项目 | 开始 | 收尾 |
|---|---:|---:|
| Docker 总占用 | 18.128GB | 18.128GB |
| task containers | 0 | 0 |
| task volumes | 0 | 0 |
| Windows Docker 数据盘剩余 | 195,496,624,128 B | 195,431,911,424 B |

未触发 40/60GB 增量或 80GiB 宿主停机线。对应看门狗 summary：

- `eval-data/build-metrics/docker-prestate-final-smokes/20260810-062605-1000-43208/summary.env`
- `eval-data/build-metrics/docker-poststate-final-smokes/20260810-064406-1000-69186/summary.env`
- `eval-data/build-metrics/docker-security-info/20260810-064326-1000-68438/summary.env`

## 5. 两侧冻结二进制与 runtime bundle

### 5.1 构建方法

- 测量 worktree 固定在 clean `cb652e1`；Codex baseline 从 clean detached/tagged 只读快照导出到私有
  scratch，只机械替换 135 个 workspace package `0.0.0 -> 0.147.0`，规范化 lock SHA 为
  `bc4fe450de929afe82928734f860ca83e5f9dc5f9f1211b0974ea47b57af77ca`。
- 两侧使用 Rust/Cargo 1.95.0、target `x86_64-unknown-linux-musl`。eval-owned V8 gate 在 watchdog lease
  内重验 clean/source identity，拒绝 ambient V8 override，按冻结 source resolver 获取官方 musl V8
  archive/binding 并校验 SHA，再用一个 Cargo invocation 构建 `codex` 与 `codex-code-mode-host`。
- RONDO/Codex 严格串行：构建一侧、固化、verify、清理 target，再处理另一侧。成功构建 summary：
  - RONDO：`eval-data/build-metrics/rondo-musl-v8-two-bin-build-cb652e1418e06d53171755963ad9eb8075259ffc/20260810-042700-1000-59854/summary.env`
  - Codex：`eval-data/build-metrics/codex-musl-v8-two-bin-build-be6e8eac029b183056b7e4402879f15d2c85f61b/20260810-044542-1000-33043/summary.env`
- 两次 `wrapper_status=complete`、`run_rc=final_rc=0`、`stop_reason=cleanup_reason=none`、swap peak 0；
  构建约 16m09s/17m47s。完成后 target 和 Codex normalized scratch 均经 watchdog 精确清理。

### 5.2 bwrap 选择与失败路径

最初尝试从两侧同源 `codex-bwrap` crate 构建静态 musl bwrap：

1. 首次证明 cross pkg-config 找不到静态 libcap；
2. 固定 libcap 2.78 源码/归档/静态库后，第二次证明当前最小 musl C 环境缺少 bubblewrap 所需 Linux
   UAPI header chain。

这两次都由 watchdog 正常收口，不是资源停止；失败 summary 保留在
`rondo-bwrap-build-*`/`libcap-2.78-musl-*` metrics。没有继续扩大成系统交叉 C 工具链。RONDO 和冻结 Codex
的 `codex-rs/bwrap` 与 `codex-rs/vendor/bubblewrap` Git tree ID 分别完全一致，因此改用同一官方
`rust-v0.147.0` x86_64-musl release asset，并同时绑定 release commit 与组合源码身份。

最终 `eval/locks/bwrap-rust-v0.147.0.json`：

| 对象 | SHA/身份 |
|---|---|
| asset archive | `e73dc46e2ec7176499cb14e26c7b80b9d8e24a39cd51fe8fa0d45ddd8f6fb87c` |
| archive size/member | 261,563 B / `bwrap-x86_64-unknown-linux-musl` |
| extracted bwrap | `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c` |
| bwrap tree | `ffb46ea517e46871c52d494da3870e61260f2429` |
| vendored bubblewrap tree | `709a9d2d381455d74fd04838a8e708e59dd7f10c` |
| canonical combined source | `b00d1fc21795a8286d18d470b4d7edae887ac593cf6b0b81d2a90b86f48723f4` |

asset 下载、safe single-file tar 解包、ELF 静态门禁、prepare/verify 和 bundle 发布均在 watchdog 内完成；
废弃的 `eval-data/deps/libcap-2.78-x86_64-unknown-linux-musl` 已经精确删除，其他 deps/cache 未清理。

### 5.3 最终 15 键 bundle

RONDO：`eval-data/bin/rondo/cb652e1418e06d53171755963ad9eb8075259ffc-x86_64-unknown-linux-musl-runtime-bundle`

- CLI SHA：`d2f5063aaf908d0d9f9409af44eebf4b57784b307c3e18957da912e4874767fb`
- code-mode-host SHA：`302cc74803d3a37822b4dd30e5c6496fb2ec9bfd60f9f01552eb6c24bb307293`
- bwrap SHA：`77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`

Codex：`eval-data/bin/codex/rust-v0.147.0-be6e8eac029b183056b7e4402879f15d2c85f61b-x86_64-unknown-linux-musl-runtime-bundle`

- CLI SHA：`8bd5f096af8302c0d5bf272a15a563d243fe77e8b704b749321a437c815f1a80`
- code-mode-host SHA：`93e16201d425f9024992052dd0e9c44ef5c5a639807be196a017be3aca9be56a`
- bwrap SHA：同 RONDO。

manifest 还记录 source commit/dirty=false、完整工具链、两条构建命令、官方 bwrap URL/archive/source SHA
和 baseline normalization。三文件 mode 0555、manifest 0600、资源目录 0700，发布为 no-overwrite rename。

## 6. Docker no-API 与 B3 事实

no-API fake server 只监听宿主 `127.0.0.1`，容器通过 Docker Desktop 的 `host.docker.internal` 到达；
固定非秘密 bearer，严格要求两轮 Responses：第一轮返回 code-mode function call，第二轮必须携带
`custom_tool_call_output`，最终需看到合法 Codex JSONL `turn.completed`。它不加载 `.env.local`，不访问
官方 API，也不使用预算账本。

真实排障顺序：

1. 最初单 CLI 路径在 API 前被 Luna `code_mode_only` 能力门禁拒绝；增加同源
   `codex-code-mode-host`。
2. helper 启动后发现正式 Linux package 还要求 `codex-resources/bwrap`；改为自包含 runtime bundle。
3. 官方 bwrap 已找到并通过 SHA/version，但 root service 缺少建立 nested namespace 的权限。
4. service/agent 固定 UID/GID 1000，root 只做安装/auth/目录准备后再次真实 Docker 复验，仍得到：
   `bwrap: No permissions to create a new namespace`。
5. `docker info` 安全选项只有 builtin seccomp/cgroupns，无 AppArmor。现象已经与二进制身份、文件权限、
   root/nonroot 和 loopback fake 分离，剩余边界是 Docker 守护进程的 nested namespace/seccomp 能力。

最终非 root smoke summary：
`eval-data/build-metrics/docker-smoke-codex-nonroot-final/20260810-064125-1000-62544/summary.env`，
`run_rc=final_rc=65`、`stop_reason=cleanup_reason=none`、swap peak 0；exact task container 已清空。

由于该阻塞对两侧共享的 frozen v0.147 bwrap/sandbox/runtime 环境是确定性的，没有再重复运行 RONDO，
也没有在 no-API 未通过时消耗最后的真实 API run 槽位。

### 6.1 三条 API 前诊断尝试与终审迁移

| run_id | side | outcome | API metadata ready | actual/estimated cost |
|---|---|---|---|---:|
| `20260810-022300000-tb-codex-r1` | codex | 设施诊断 | false | 0 / 0 USD |
| `20260810-024000000-tb-codex-r2` | codex | 设施诊断 | false | 0 / 0 USD |
| `20260810-032600000-tb-codex-r3` | codex | 设施诊断 | false | 0 / 0 USD |

初版 publisher 曾把这些 API 前 adapter/config 失败归为 `agent_failed` 并复制完整 Harbor tree。终审确认
这既错误归因模型，也与最终主动 allowlist 合同不一致，因此三行已从受跟踪
`eval/results/runs.jsonl` 删除，对应三个本任务私有发布目录也已精确清理；它们不再是正式测评结果。
持久账本 `eval-data/budgets/p1-fix-git-20260810.json` 不回写：三条 run 的 request map 均为空、batch actual
为 0，但尝试槽位保持不可复用。最多 4 run 尚余 1 个槽位；第四槽不能同时补齐同一任务两侧，所以
即使单侧未来完成，也不能误报 M1。

## 7. 方向 2：L1/L2

### 7.1 L1

`local_approval/client.py` 消费共享 static payload，以同一 schema 构造 provider request；拒绝任何顶层
tools、Lite additional tools、非法 URL/响应和非结构化结果。决策结果本地再次按冻结 schema 强校验，
不会把 server “尽力支持 JSON schema”当作可信结构化输出。

fake server 覆盖正常 allow/deny、malformed/oversized payload、invalid structured output、无工具合同与
Standard/Lite 字节公平性。错误码区分配置 64、证据 65、结构化输出 66、服务不可达 69、基础设施 70、
模型缺失 78。

### 7.2 L2

受跟踪 `eval/locks/llama-cpp-b10333.json` 固定：

- llama.cpp `b10333` / commit `08659901c43b51de735740f1cf61bb82fbe0c4e4`
- CPU x64 asset `llama-b10333-bin-ubuntu-x64.tar.gz`，size 16,507,165 B，SHA-256
  `936ce04d98abe2a977e9dd2ff92659bb96947e136acee8f2bc3e21d8eaebbf23`
- 项目局部 `eval-data/tools/llama-b10333/llama-server`，SHA-256
  `1d374fdb717832ec01d4829eff9feb46dfc83b7ccbb9d867c15315dbd8aa4bbe`

doctor 先核对 common-root config、项目局部 binary 的冻结 SHA-256、`--version` 的 build/commit，再短暂以
`--offline --no-models-autoload --no-ui --host 127.0.0.1` 启动无模型 router，验证 `/health` 和 `/props`
后停止。router 健康只证明 runtime，不证明模型；model path 缺失时终态固定
`infrastructure_ready_model_missing`/78。正式 launcher 在 model 存在时必须先取得 watchdog lease，
运行中每 5 秒重验；丢锁只终止本进程。

client 使用 b10333 pin-specific `/v1/responses` + 顶层 `response_format`，并在本地强校验返回 JSON；
这一 Structured Outputs 映射只由 fake 覆盖，明确标为待真实模型实测。launcher 永远带 `--offline`，不会
从配置生成 `-hf` 或 model URL，不会隐式下载权重。秘密只可能映射为子进程 `LLAMA_API_KEY`，不进入 argv。

## 8. 测试与验收矩阵

轻量最终门禁：

```text
cd eval
.venv/bin/python -m unittest discover -s tests -v
Ran 182 tests ... OK

uv lock --check
Resolved 85 packages ... OK

git diff --check
OK
```

| 层级 | 结果 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| pure/unit | 通过，182 总集合的一部分 | contracts、parser、schema、路径/锁/预算/监督状态机 | Docker daemon 或模型行为 |
| fake/loopback | 通过，182 总集合的一部分 | HTTP/SSE、Lite header、临时 bearer、两轮 code-mode 合同 | OpenAI 官方服务、真实模型质量 |
| Harbor hello-world Docker | 通过 | 固定 Harbor + Docker 生命周期、oracle verifier | Codex agent/code-mode |
| frozen binary Docker `--version` | 两侧通过 | musl 可移植性、digest bind、容器资源/cleanup | 完整 agent sandbox |
| Terminal-Bench Codex no-API | **失败/阻塞** | 已到 frozen bwrap；builtin seccomp 下 nested namespace 不可用 | 不算 B2 全链路或 B3 通过 |
| 真实 OpenAI API | **0 次、0 USD** | 预算门禁阻止了设施未就绪时付费 | 无模型端到端、无真实 E_final |
| llama.cpp no-model doctor | 通过，终态 78 | binary/router/config ready，模型明确缺失 | 无真实本地推理、显存或延迟 |
| L2a/L3/L4/训练/canary | 未运行 | —— | 不在本批范围 |

本批没有运行完整 Rust workspace 测试，因为产品 Rust 源码没有改动；只构建了测评所需冻结二进制，相关
重任务都由 watchdog 记录。没有运行 Bazel、CI 或 PR。

## 9. 清理与宿主影响

- 已清理：RONDO/Codex Cargo target、Codex normalized source scratch、失败的 bwrap target、废弃 libcap
  依赖目录、测试生成的 Python bytecode cache；清理均限于明确路径，重型目录经 watchdog。
- 保留：两侧 runtime bundle、官方 bwrap/llama.cpp 下载与安装、TB dataset checkout、Docker 镜像、
  预算账本和 watchdog summaries。三条旧 raw run 已精确删除；账本保留其不可复用尝试身份。
- 未清理 Docker 既有镜像/build cache/网络/卷；只检查并清空本任务 exact-label 容器。Docker 总占用没有
  相对基线增长，宿主数据盘下降约 61.7MB，远低于阈值。
- 没有修改 Docker Desktop、WSL、代理、DNS、GPU 驱动、系统服务或全局工具链配置。

## 10. 独立终审与收尾修补

任务主体完成后由独立子智能体对当前 diff、生产调用链、预算账本、原始归档和权威文档逐项复核。确认并
修补的实质问题如下：

1. CLI 现在在读取 secret 和进入外部执行前校验固定 batch/run-id，并由 `ArtifactWriter.start()` 检查
   target、任意进程 staging、journal 和 `runs.jsonl` 重复项；同一时刻由预算账本进程锁串行
   `claim_run()`，已有 run-id 永久拒绝复用。
2. run claim 之后的预算停止、Docker/watchdog、Harbor parser 与出版异常统一写
   `run-failure.json`、去敏 metadata 状态、账本实际成本和正式失败行；异常类别只保存固定枚举，不把
   可能含凭据的异常文本写入归档。`KeyboardInterrupt`/async cancellation 单独记为
   `cancelled/interrupted` 并返回 130，不吞 `SystemExit`；失败记录的 `metadata_ready` 和请求角色从
   严格验证后的真实 metadata 派生，不把 API 后失败误写成“未请求”。
3. RONDO `guardian-evidence/<review_id>/E_final.json` 与 `meta.json` 从“只存摘要”改为显式私有归档。
   consumer 要求生产 meta 的 14 个字段精确匹配，并复核 review id、`rust-v0.147.0`、peeled commit、
   Luna/low、token/timing 类型与 effective policy hash；归档前再次读取和比对，防止收集后漂移。
4. Harbor 归档从完整 jobs tree 收缩到明确 allowlist；config、lock、job/trial raw log 和 exception trace
   均不再复制。所有路径逐级拒绝 symlink，文件大小受限，最终仍经过通用 secret scanner。
5. API 前、无 verified metadata 的 CLI/adapter 退出从 `agent_failed` 纠正为 `infra_failed`。三条旧诊断
   记录和不符合最终 allowlist 的私有目录被移出正式结果库，预算槽位保留。
6. eval harness 与冻结产品 commit 分开记录：measurement `git_commit` 绑定 `cb652e1` 产品/二进制；
   `config.eval_harness_commit` 绑定运行时实际加载且 clean/tracked 的最终 eval 源码，避免新 harness 借旧
   product commit 冒充同一身份。
7. llama.cpp launcher 除 build/commit 自报信息外，先对项目局部 `llama-server` 做 O_NOFOLLOW、稳定
   inode/stat 的流式 SHA-256，并与受跟踪 lock 中 installed binary digest 比对。

终审修补后的完整轻量集合为 182/182；独立复核结论为“可合并、无新增阻断”。未借终审重启
Docker、Cargo、真实 API 或本地模型。

## 11. 实现提交

从初始 main 到文档收尾前的实现提交：

```text
cb652e1 feat(eval): add P1 benchmark and local approval infrastructure
bdafd82 fix(eval): close benchmark failure paths
2cb61bf fix(eval): encode multiline toolchain provenance
c423f1d fix(eval): expose custom adapters to Harbor child
f19e85e fix(eval): accept Harbor optional exec streams
dfaccd8 fix(eval): freeze portable musl benchmark binaries
1abc934 feat(eval): add frozen binary container probe
cf53e16 fix(eval): use isolated responses provider
575d331 feat(eval): add full Docker no-API smoke
8003aa6 fix(eval): create ignored smoke work root
d72c222 fix(eval): harden live benchmark integration
9996a8e fix(eval): support code mode in benchmark containers
53895ff fix(eval): package frozen bubblewrap runtime
749654f fix(eval): freeze static libcap for bubblewrap
0aa528e fix(eval): resolve pinned libcap toolchain paths
af1aa94 fix(eval): freeze official bubblewrap runtime
2c5bd62 fix(eval): run benchmark agent as nonroot
```

`749654f`/`0aa528e` 的 libcap 路线由后续 `af1aa94` 正向删除/替代，保留提交历史与失败 metrics 便于
code review，不通过 reset/rewrite 隐藏试错。

## 12. 后续边界

当前安全选择是按部分完成状态交付。若后续要继续 B3，需要先为“仅固定 `fix-git` 任务、单容器、单次
no-API 验证”的 Docker seccomp/capability 变化取得新的精确授权，并继续保留 memory/swap/pids/timeout、
预算代理、exact-label cleanup 和宿主空间阈值。不能把该授权泛化到完整数据集或其他容器。

只有安全 no-API 全链路通过，才应使用当前账本剩余的第 4 个真实 API 槽位；不得添加第 5 个 run。即使
第四次单侧完成，因为缺同任务另一侧 `completed`，M1 仍需新的明确批次和预算安排，不能在本批补写成功。

本地模型后续也必须由用户提供/授权模型权重后，才可执行模型 server、显存/上下文/延迟测量和真实
`E_final` 结构化审批；这不会自动解锁 L2a/L3/L4、数据外发、训练或正式 canary。
