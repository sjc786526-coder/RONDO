# Plan 008 独立审查整改与 B2 no-API 验收

时间：2026-08-10（Asia/Shanghai）

基线：`6d4cd751b1bb4d0faa81f8df587c59e83a6083a3`

工作树：`.claude/worktrees/0810-plan008-review-remediation`

缺陷源：`agent_log/2026-08-10-120053-plan008-independent-implementation-review.md`

## 1. 结论

独立审查 F-01～F-16 的当前阶段缺口已完成代码整改与对应验收。Plan 008 现可诚实认定：

- B1 冻结结论保留；B2 的生产 preflight、公平双侧身份、Docker/看门狗有效态和结果归档已闭合；
- 固定 `fix-git` 镜像内的 default/custom seccomp 反事实确认 builtin profile 是 nested user namespace
  阻断原因；受跟踪最小 profile 下，RONDO→Codex no-API 配对均完成；
- L1 的 Standard/Lite、合法 ToolSearch、最终无工具 sink 和三组 consumer 协议/fixture 逐字节投影完成；
- L2 的项目局部 llama.cpp 完整动态运行闭包、redirect/endpoint/model identity 已闭合，无模型 doctor
  仍为 `infrastructure_ready_model_missing`/78；
- 三次早期零请求诊断恢复为永久 `infra_failed` 终态；费用仍为 0 USD；
- B3/M1、真实本地模型、L2a/L3/L4、训练和 canary 没有运行，不在本日志中冒充完成。

## 2. 边界与安全约束

- 未读取、搜索、打印或复制 `.env.local`；no-API 只使用固定 fake bearer。
- 未调用真实 OpenAI API，未查询供应商账单，项目内代理/账本记录为 0 request / 0 USD。
- 未下载权重、未加载模型、未做真实本地推理、GPU/上下文/延迟测试。
- 本整改未运行 Cargo、编译或链接；既有冻结两侧 runtime bundle 只做 hash/preflight 和容器执行。
- Docker 只运行固定 digest 的 Plan 008 镜像，单容器、并发 1；始终禁止 privileged、`SYS_ADMIN`、
  `seccomp=unconfined` 和宿主全局修改。
- 所有正式 Docker 诊断/no-API 均在项目 `with-build-lock.sh` cgroup/flock 内，并由 Docker supervisor
  独立进行 5 秒采样、资源有效态检查、绝对 deadline 和 exact-label/Compose cleanup。

## 3. 审查项整改映射

| Finding | 实质整改 | 验收边界 |
|---|---|---|
| F-01/F-02 | 新增受跟踪 `p1-terminal-bench-pair-v1.json` 与 `pair.py`；绑定完整 manifest bytes、三份实际二进制、Harbor wheel/安装 closure、公平字段、Rondo→Codex 顺序；no-API/paid 共用 preflight，paid hard-disabled；崩溃遗留 `active` 会持久转为 `failed` 并永久封锁 pair | no-API pair v3 双侧实际通过；没有把人类日志当启动门禁；遗留槽位不可重复 claim |
| F-03 | Docker 必须至少观察一次 exact-label 容器；daemon inspect 核对 user、memory/swap/pids、network、mount、capability、NNP、seccomp、read-only 等有效态 | fake 负测 + 实际双侧容器，最终 task bytes/对象为 0 |
| F-04 | watchdog proof 绑定规范 flock inode、默认 memory/swap 限额与 cgroup counters；每轮完整 Docker counter sample 独立限时 5 秒且受外层 deadline 上界，内部 Docker/PowerShell probe 共享该 deadline；失锁/超时/计数异常 fail-closed | supervisor/runtime bridge 慢 probe 回归与实际 watcher summary |
| F-05 | ArtifactWriter journal v2 绑定工件树、record、index pre/post 长度与 SHA；完整 index 临时文件 fsync + atomic replace；恢复只接受精确 pre/post identity | partial write + `KeyboardInterrupt`、子进程 `os._exit` crash points、恢复前篡改回归 |
| F-06 | llama lock schema v2 覆盖项目 runtime 52 个普通文件、10 个 symlink、8 个宿主动态依赖；每次 inspect 复核目录/ldd closure，移除 ambient `LD_LIBRARY_PATH` | 项目现场 runtime closure 静态复核通过；没有模型推理 |
| F-07 | LocalApprovalClient 使用 no-redirect opener，拒绝所有 3xx，并要求 final URL 与配置 endpoint 精确相同 | 同源/跨源 redirect 均拒绝，目标 server 零 bearer 命中 |
| F-08 | 一次性、默认 dry-run migration 首次应用时从 retained work/ledger 证据重建 3 条 `infra_failed` 结果；发布后以 index、私有 migration artifact、Git source 与 ledger 实现无 work 幂等；不回收预算槽，不伪造 CPU/RSS | `runs.jsonl` 现 3 行、request=0、cost=0；对应私有 migration 说明已发布，原 work 已作为可再生中间产物清理 |
| F-09 | Lite policy item 强制 `type=message`；合法 `tool_search_output.tools` 作为历史证据保留；最终 validator 仅允许该上下文的 tools，并拒绝 private transport | Standard/Lite ToolSearch fixture 在 Luna/Sol/Local 三组协议投影字节完全一致；本批没有把 fixture helper 冒充三套生产调用端 |
| F-10 | 配置新增可空 `model_sha256`；有模型时检查 GGUF header/digest；launcher 使用固定 alias；doctor 核对 `/props` 和 `/v1/models`，client 核对 response model | 无模型现场保持 78；model-backed identity/结构化输出未运行 |
| F-11 | 单 trial 结果解析不伪造 JobResult；completed/agent/infra/cancel 与 reward/success/attribution/verified roles 交叉验证 | ordinary 与 claimed failure 均有负向回归 |
| F-12 | M1 公平 pair aggregator 与 S2 状态拆分；没有 request↔E_final 一对一绑定时 S2 明示 `unbound` | no-API 不被误报成 M1/S2 |
| F-13 | 固定容器收集 userns sysctl、CapEff、NNP、Seccomp、`unshare` 与 frozen bwrap 结果；比较 builtin 与受跟踪最小 profile | 实际反事实已确认 builtin seccomp 根因 |
| F-14 | timeout/retry 收紧为有界整数；根 `justfile` 提供 hermetic eval sync/test/lock/check，显式清除 ambient proxy | 完整 237 项在统一入口通过 |
| F-15 | Harbor 改用 deterministic `harbor trials start`；host 使用独立 process group；监督/cleanup 覆盖 exact Compose container/network/volume | 实际运行退出后 exact task bytes 0，无资源告警 |
| F-16 | fresh 单 run CLI 记录 runner-host self+children 的 wall/user CPU/system CPU/peak RSS/exit code；ArtifactWriter 对 completed TB 强制五键 | 这些值不含 Docker daemon 管理的容器进程，也不是并发进程 RSS 之和；仅作设施诊断。paid B3 在补齐受监督容器 CPU/峰值内存前保持禁用 |

## 4. Docker namespace/seccomp 诊断

### 4.1 冻结 profile

- 基线：Moby `profiles` tag `seccomp/v0.2.3` 的 default profile；上游 SHA 与受跟踪 README 均固定。
- project profile source SHA：`9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f`。
- Docker daemon reserialize 后的 effective SHA：
  `a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf`。
- 唯一语义 delta：对没有 `CAP_SYS_ADMIN` 的进程允许 frozen bwrap 所需
  `clone/mount/pivot_root/umount2/unshare`；`clone3`/`setns` 等其余规则保持上游语义。
- profile 必须是 Git tracked、index/worktree clean 的普通文件；production 同时核对 source bytes 和
  daemon inspect 返回的 effective content，不能只信 argv 路径或 label。

### 4.2 default 结果

看门狗：
`eval-data/build-metrics/namespace-default-bfae104-r7/20260810-133222-1000-64287/summary.env`

- `uid:gid=1000:1000`，`CapEff=0`，`NoNewPrivs=1`，`Seccomp=2`；宿主 userns sysctl 允许创建大量 namespace；
- `unshare(CLONE_NEWUSER)` 返回 `EPERM`，frozen bwrap 失败；
- watcher `run_rc=0/final_rc=0/stop_reason=none/cleanup_reason=none`，swap peak 0；
- Docker total 18.128 GB 前后不变，任务对象最终 0。

诊断命令自身成功，只表示成功采集到了“被拒绝”的预期反事实，不表示 bwrap 成功。

### 4.3 custom 结果

看门狗：
`eval-data/build-metrics/namespace-custom-c6fe0f5-r2/20260810-133530-1000-72010/summary.env`

- UID/capability/NNP/资源/网络/只读条件与 default 相同；
- `unshare(CLONE_NEWUSER)` 成功，frozen bwrap 成功；
- watcher `run_rc=0/final_rc=0/stop_reason=none/cleanup_reason=none`，swap peak 0；
- Docker total 18.128 GB 前后不变，任务对象最终 0。

因此阻断不是普通 UID、userns sysctl 或缺少 privileged capability；在本次冻结环境内，builtin seccomp
是可重复、单变量确认的原因。profile 是面向该固定 bwrap 的兼容配置，不应推广为宿主或全局 Docker 配置。

## 5. B2 双侧 no-API 配对

### 5.1 生产接线中发现并修复的问题

1. Compose `secrets.environment` 在当前 Harbor/Compose 路径没有形成 daemon 可观察的 secret mount。
   改为工作目录内 0600 私有 placeholder：执行前仅 backend 写入 fake/downstream bearer，Harbor env 只含
   `HARBOR_TELEMETRY=off`；supervisor 核对 exact RO bind；成功或异常后都 fsync 清空。
2. v2 RONDO 已完成 Docker 生命周期，但 `codex.txt` 混入两行 stderr warning，严格 JSONL parser 正确拒绝。
   adapter 保留 `pipefail`，将 stderr 分离到不归档的 `codex.stderr.txt`；stdout JSONL 仍逐行严格解析。
3. 每个失败 pair identity 都保留独立、不可复用的 terminal ledger；没有删除/改写 v1/v2 来凑绿。

### 5.2 v3 结果

Pair ledger：`eval-data/pairs/p1-fix-git-pair-v3-no-api.json`

- pair lock SHA：`192d311619ca61be74bad90f5257d847cb418a2086ba3d2d816b69fa7490690d`；
- slot 1 RONDO：`tb-no-api-rondo-e126d52e053c`，completed；
- slot 2 Codex：`tb-no-api-codex-c70b5de61ef7`，completed；
- 两侧均为 2 fake requests、6 个 JSONL events、code-mode tool round-trip true、host return 0；
- `reward=0/task_outcome=fail` 是 fake 响应不解真实 `fix-git` 的预期结果，不是 B3 agent 分数；no-API
  的验收对象是完整设施路径与双侧公平性。

RONDO watcher：
`eval-data/build-metrics/no-api-pair-v3-rondo-9404c5a/20260810-140501-1000-26552/summary.env`

- memory peak 2,006,228,992 bytes，swap peak 0；
- Docker total 18.128 GB 前后不变；C 盘 free 196,730,925,056 → 196,731,117,568 bytes；
- final task bytes 0，5 samples，warnings 0；watcher/command/cleanup 全部成功。

Codex watcher：
`eval-data/build-metrics/no-api-pair-v3-codex-9404c5a/20260810-140555-1000-32466/summary.env`

- memory peak 1,588,289,536 bytes，swap peak 0；
- Docker total 18.128 GB 前后不变；C 盘 free 196,730,806,272 → 196,730,933,248 bytes；
- final task bytes 0，5 samples，warnings 0；watcher/command/cleanup 全部成功。

## 6. 结果、预算与 L2 现场

- `eval/results/runs.jsonl`：3 行，均为旧 claimed 诊断的 `infra_failed`，cost estimated/actual 均 0；
- `eval-data/budgets/p1-fix-git-20260810.json`：3 个不可复用 run，每个 `requests={}`、spent 0；20 USD
  总 cap 未消费；migration 前后账本 bytes/SHA 不变；
- paid mode：受跟踪 pair lock 中明确 disabled，原因
  `fresh_pair_and_budget_authorization_required`；
- L2 doctor 实跑输出：`configuration=valid`、`runtime=ready`、`model=missing`、
  `service=not_started`、`status=infrastructure_ready_model_missing`、exit 78。

## 7. 测试与静态门禁

- `just eval-test`：237/237，0 failure/error/skip；入口清除大小写 HTTP(S)/ALL proxy 并固定 loopback
  `NO_PROXY`；
- `just eval-lock`：85 packages，`uv lock --check` 通过；
- 密钥 staging/JSONL 修复后定向 Terminal/pair/results：53/53；
- Docker supervisor/runtime bridge/namespace 纯 fake 定向由实现阶段分别通过 52 项以上组合回归；
- 独立终审第二轮复跑四模块 63/63，并复核 F-08 真实现场三条均为 `already_applied`；未发现 P0/P1；
- `git diff --check` 通过；
- 没有运行 Rust fmt/clippy/Nextest/workspace，因为本批没有修改 `mydev/` Rust 源码。

## 8. 清理与宿主影响

- 开工在看门狗内精确清理旧 Plan 008 venv、Python/uv/ruff cache 和可重建 no-API work；保留 frozen
  bundle、预算账本、F-08 已发布的 migration artifacts 与 build-metrics。F-08 原 work 在迁移完成后清理，
  迁移器已验证无 work 时仍可返回 `already_applied`。
- 当前 worktree venv 由 `uv sync --frozen` 重建；第一次 offline 因缺 wheel 正确失败，随后网络同步成功。
- Docker 没有 pull/build 新镜像；所有本批容器/Compose 网络均由 exact identity cleanup，正式两侧最终
  task bytes 均为 0。没有删除来源不明镜像、volume 或 build cache。
- 子任务排查时曾误执行一次只读 `docker compose version` 和一次丢弃输出的 `docker info`，未创建、运行、
  拉取或删除 Docker 对象；这两次没有走 watchdog，明确不作为验收证据。其后所有 Docker 行为均按正式门禁执行。

## 9. 未运行与后续授权门

- 未运行真实 API，B3/M1 保持未完成；若继续，需要新的 paid pair/batch、任务/轮次/预算和批量 API 授权。
- 未下载模型或权重，未运行本地推理、L2a/L3/L4、训练、正式 canary 或离线回放。
- no-API v3 的 completed 只证明 B2 设施和公平路径，不代表 `fix-git` 被模型解决，也不产生性能基线。
- M1 仍要求同一 task 的 RONDO/Codex 真实 API 两侧都 completed 且可归档；S2 另行验收，不与 M1 混写。
- paid B3 启用前还必须从 Docker supervisor 的有效态采样补充容器 CPU 与峰值内存；当前 host rusage
  只描述 runner/CLI 开销，不能作为 Codex/RONDO agent 性能横比。

官方资料：Docker seccomp 说明 <https://docs.docker.com/engine/security/seccomp/>；Moby profile
<https://raw.githubusercontent.com/moby/profiles/refs/tags/seccomp/v0.2.3/seccomp/default.json>；Luna 定价
<https://developers.openai.com/api/docs/models/gpt-5.6-luna>。
