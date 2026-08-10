# Plan 008 第四次独立审查：v4 失败、去 chown 修复与后续闭环条件

时间：2026-08-10（Asia/Shanghai）

审查对象：`5f584273297cac3ec91799d8cf53904c748357f7`

直接前序：`07d0a487f8c498032a6da7ce4fd37a91c607bdac`

整改记录：`agent_log/2026-08-10-164500-plan008-third-review-remediation.md`

## 1. 范围与结论

本轮从第一轮审查合同继续向下复核，重点检查：

- v4 真实 Docker 失败是否被如实分类、是否保持 fail-closed、是否改写或复用了 pair；
- `cap_drop=ALL` 下移除 adapter 运行时 `chown` 的实现是否越权、泄露 secret 或弱化隔离；
- pair、safe summary、watchdog、Docker 有效态和失败证据能否在崩溃、清理或新 clone 后保持一致；
- 277 项轻量测试及锁文件口径是否可独立复现；
- B2、B3/M1 与 L2 的当前状态是否足以宣告 Plan 008/P1 闭环。

审查只读取源码、文档、冻结资产和保留现场，并复跑轻量测试；没有启动 Docker daemon workload、容器、
构建或拉取，没有运行 Cargo、真实 API、本地模型或网络下载，没有读取 `.env.local`。透明说明：一个只读
审查分区误执行过一次 `docker compose version`，只返回 CLI 版本 `v5.3.1`，没有连接/创建 Docker 对象。
除本日志外未修改实现或权威文档。

**总判断：不能宣告本次任务、Plan 008 或 P1 已“无隐患、无缺陷、无 bug”并闭环完成。**

- v4 的真实结果确为 RONDO slot 1 `infra_failed`、pair `failed/blocked`，Codex slot 2 未运行；执行方没有
  把失败改写为成功，也没有削弱 seccomp、capability、用户、cgroup 或资源监督边界。
- `5f58427` 的去 `chown` 窄修静态设计合理，现有 pure/fake 回归成立，但真实 Docker ownership、workdir、
  secret mount 和日志目录有效态尚未经过修复后路径验证，因此 B2 仍未验收。
- 未发现当前 enabled no-API 路径中的新 P0 或远程安全 P1；但发现三项应在消耗新 pair 前修复的中等级
  合同/证据缺口：v4 的 tracked 退休状态缺失、恢复路径不绑定请求 side、失败 Docker 证据未耐久绑定。
- B3/M1 和 L2 model-backed 继续 hard-disabled/gated，文档总体诚实；但二者仍各有明确解锁阻断，不能把
  “当前不可达”解释成“功能已经完成”。
- `5f58427` 尚未合并或推送：整改 worktree tracked clean；`main == origin/main ==
  2cc9140022f69803afff7bc373e3beeee0579be9`。分支在合并前已命名为 `zz-done/...`，不符合项目约定顺序，
  也容易误导交付状态。

## 2. 真实 v4 失败的独立复核

### 2.1 pair 与 trial 终态

保留现场的 common-root ledger：

`eval-data/pairs/p1-fix-git-pair-v4-no-api.json`

独立计算 SHA-256 为：

`23ceecfebfb058fe6dd814df09a217674f62374740d3e2282b90f4aff069edef`

内容满足当前 schema v3，关键事实为：

- `pair_id = p1-fix-git-pair-v4`；
- `eval_harness_commit = 07d0a487f8c498032a6da7ce4fd37a91c607bdac`；
- `blocked = true`、`next_slot = 1`；
- 唯一 run 为 `tb-no-api-rondo-e2cd95f5bc72`，side 为 RONDO、status 为 `failed`；
- `safe_summary_sha256 = null`、`container_metrics = null`；
- 没有 Codex slot 2 记录。

trial 的 `result.json` 与 `exception.txt` SHA-256 分别为：

- `01486136523de7d3a6f030d75aa1ffe10a64a583a125c3cd0866d7c4e8c199dc`；
- `c949f5714ed9ecedcb15d76ba7222011b930345d2297c30a4b89bc04fc90d35f`。

`result.json` 中 reward、agent、verifier 均为空，异常是泛化的
`AdapterError: container command failed`。trace 精确落在 `07d0a48` 版本 adapter 上传 bundle 后执行
`chown -R 0:0 && chmod ...` 的 `_checked_exec()`，因此“失败发生在包含 chown 的复合命令”有直接证据；
但没有保留 stderr，不能独立证明具体失败 syscall 一定是 `chown`。整改日志用“强归因而非 syscall 直证”
描述是公正的。

provider secret staging 文件当前为 `0600`、owner `1000:1000`、大小 0；trial 没有 agent execution，
支持“在任何 fake/API 请求前失败，0 request、0 USD”的判断。

### 2.2 watchdog 与 Docker 事实边界

watchdog summary：

`eval-data/build-metrics/p1-v4-noapi-rondo/20260810-164759-1000-97046/summary.env`

SHA-256 为：

`95c4c23a886d0048a11fa898e310b739c9964ef464e353562bf8efc6d5ae47a0`

其中 `run_rc=70`、`final_rc=70`、无 watchdog stop/cleanup、swap peak 为 0，与整改日志一致。

真实 run 能进入 adapter install，且当时 supervisor 未因有效态失配而 fail，结合 overlay/inspect 生产合同，
可以支持“本次观察到 pinned image、custom seccomp、private cgroup、`cap_drop=ALL`、container metrics 与
VHDX”等运行时事实。不过具体 daemon image/VHDX/CPU/peak memory/seccomp 数值只保留在人工 agent log；
失败 ledger、trial 文件和 watchdog summary 都没有绑定这些数值。它们是可信度较高的当场人工观测，
不是可从现存机器产物独立重算的 durable acceptance evidence。

### 2.3 失败后的序列行为

当前本机 v4 ledger 会在 `pair.py:237-244` 拒绝任何后续 claim；Codex 未运行符合“首槽失败即停止”的序列
合同。没有发现删除、改写 v4 ledger 或绕过 slot order 的行为。

## 3. 去 chown 修复的代码审查

### 3.1 已确认合理的部分

`eval/rondo_eval/terminal_bench/adapters.py:185-249` 的 install 路径：

- 不再执行任何 `chown`；
- 上传后逐个要求固定目录/文件存在、类型正确且不是 symlink；
- 消费实际 ownership，要求上传物为 `0:0`；
- 再执行限定的 mode、SHA-256 与 `--version` 校验；
- 没有增加 capability、`SYS_ADMIN`、privileged 或放宽 seccomp。

`adapters.py:264-337` 的 run 路径：

- root 操作前先用 `pwd -P` 把递归 chmod 精确限定在 `/app/personal-site`；
- home、secret state、auth 和 `/logs/agent` 由 `1000:1000` agent 身份创建；
- Docker secret 必须是实际 `1000:1000`、普通文件、非 symlink、非空、可读且不可写；
- root 不读取 secret，API key 不通过 `docker argv` 或环境 `-e KEY=value` 传输；
- 没有发现 workdir 越界、root 读取 secret 或将 `chown` 变相引回。

这些是有效的 fail-closed 收窄，不是为了过测而弱化安全合同。

### 3.2 尚未由真实环境确认的假设

当前测试的 `FakeEnvironment` 直接返回预期 owner，不能证明 Docker Desktop/Compose 实际语义。修复后的真实
路径仍需确认：

- `docker compose cp` 后两个目录和三个文件是否确实为 `0:0`；
- root 在 `cap_drop=ALL` 下是否能对镜像中 root-owned 的固定 workdir 完成 `chmod -R a+rwX`；
- `/logs/agent` 是否能由 agent 用户创建并满足 0750/owner 合同；
- Compose secret 在容器内是否确实显示为 `1000:1000`、只读且不可写。

当前宿主 placeholder 是 `1000:1000/0600`，镜像 workdir 也预期由 root 创建，因此这些假设具有合理基础；
但它们在 v4 中未全部走到，不能用 17/17 fake 测试替代真实 Docker 验收。这是待验证的生产可达性，
不是已经复现的新 bug。

## 4. 本轮新增问题

### R4-M01（中，B2 身份/历史合同）：v4 只在 ignored 本机 ledger 中退休

受跟踪 `eval/locks/p1-terminal-bench-pair-v1.json:3-7` 仍声明：

- `pair_id = p1-fix-git-pair-v4`；
- `modes.no_api.enabled = true`。

而 `PairSequenceLedger.__enter__()` 在 ledger 路径不存在时会于 `pair.py:192-205` 创建一个全新的 schema v3
空 ledger。`eval-data/` 按合同不入库，所以新 clone 天然没有本机 blocked ledger；误删或跨 common-root
执行也有同样结果。这样，`5f58427` 可以在新 clone 上重新消费同一个 v4 identity，与
`doc/WBS.md:142-146` 和整改日志“v4 永久 failed/blocked，未来必须使用新受跟踪 pair”的口径冲突。

当前机器不会自动重跑，因为本地 ledger 确实存在且 blocked；问题是“永久退休”没有进入当前 tracked
source-of-truth。下一次执行前应把受跟踪当前 identity 推进到新的 pair（自然可命名 v5），保留 v4 ledger、
trial、watchdog 和日志不改写；不能在 `5f58427` 的 v4 lock 上直接重跑。若文档继续使用“永久”措辞，
还应明确它指当前项目历史与 identity，不声称能阻止人为 checkout 旧提交。

现有测试反而断言 v4 no-API enabled，只覆盖“已存在空/损坏 ledger 拒绝”，未覆盖“已知失败 identity 在
ledger 缺失或新 clone 中不得重新创建”。

### R4-M02（中，B2 崩溃恢复）：safe-summary 恢复没有绑定本次 CLI `--side`

`docker_smoke.py:624-659` 先解析 `args.side`，但只要 pair ledger 中任意 active summary 可恢复，就无条件
调用 `reconcile_no_api_summary()` 并返回 0。`pair.py:322-345` 的 reconcile 不接受 expected side。

轻量注入已经复现：ledger 中为 active RONDO 且 RONDO summary 已耐久，然后调用
`docker_smoke --side codex --pair-validation`，返回码仍为 0，stdout 显示
`status=recovered, side=rondo`。

ledger 不会伪写 Codex，stdout 也披露真实 side，所以这不是结果伪造或高等级安全问题；但只消费退出码的
串行脚本会把本次 Codex 命令误判为成功，实际只收敛 RONDO，然后跳过 Codex slot。恢复入口必须核对
requested side 与 active/durable summary side 一致，或使用不会被误当本次 side 成功的专用恢复命令/退出码。
现有 CLI 回归只覆盖请求 side 与恢复 side 都为 RONDO。

### R4-M03（中，B2 证据可靠性）：failed slot 不绑定去敏 Docker 失败摘要

`docker_smoke.py:738-762` 只在 `result.passed` 时原子写 safe summary 并把摘要交给 ledger；失败只写
`completed=False`。schema 又禁止 failed run 携带 safe summary/metrics。因此 v4 ledger 只有
failed/blocked/run-id/commit，不绑定：

- daemon image、effective seccomp、private cgroup、cap drop/NNP/limits/mount/network；
- container CPU/peak memory、VHDX baseline/peak/final、final cleanup；
- failure stage、安全的 command identifier、trial/result/exception/watchdog digest。

`adapters.py:586-595` 还丢弃 stdout/stderr，所有命令失败统一成 `container command failed`。对一次性 pair，
这会导致每次真实失败都消耗 identity，却只能靠当场 stdout 和记忆做根因分析。本次 agent log 很诚实，
不会形成 completed 假通过；但“失败历史可长期机器复核”的合同没有完成。

高性价比修复是增加**不改变 failed/blocked 语义**的 identity-bound、去敏 failure summary，让 ledger 绑定其
固定路径与 SHA-256；包含必要 Docker effective facts、cleanup、failure stage 与安全 command-id。成功 summary
也应补齐 cap_drop/private-cgroup/NNP/limits/mount/network/cleanup 的有效态字段。adapter 诊断可保留受限、
去敏的阶段标识或 stderr 摘要，但不得记录 secret 或完整敏感 argv。

### R4-L01（低，文件边界）：pair/safe-summary 父目录不防 symlink

pair ledger 和 safe-summary 只约束最终文件；`pair.py:134` 会直接创建/跟随 parent，临时文件同样跟随父目录。
按个人本地同 UID 威胁模型列低，不要求复杂可信链。当前现场 `eval-data/pairs` 是 0700 真实目录，ledger/lock
是 0600 普通文件，本次结果未受影响。

### R4-L02（低，VHDX 连续性）：数值未绑定同一 VHDX 文件身份

40/60GB 增长门禁与 80GiB free floor 已正确接线，但 probe 只持久化 drive/free/length；候选路径或文件
identity 没有贯穿采样。正常 Docker Desktop 生命周期下概率低，但候选文件切换时可能跨文件比较。

### R4-L03（低，测试/交付卫生）

- stable sidecar lock 的实现静态合理，进程死亡切点覆盖较强，但仍没有两个进程并发 opener/claim/finish 的
  争锁回归；这是测试盲区，不是已复现 bug。
- worktree tracked clean，但 ignored 约 220.5 MiB：允许保留的 `eval/.venv` 约 210 MiB、uv cache 与
  `__pycache__`；没有 `target`。justfile 的相对 `UV_CACHE_DIR=eval-data/uv-cache` 配合 `uv --directory eval`
  实际生成 `eval/eval-data/uv-cache`，与顶层 `eval-data/` 分区约定不一致。

## 5. 文档状态问题

总体状态口径可靠：WBS、Plan 008 与整改日志均明确 v4 RONDO 失败、Codex 未运行、adapter 窄修只有
pure/fake、B2 待新 pair、B3/M1 hard-disabled、L2 model-backed 未验收。

仍需收窄三处表述：

1. `doc/WBS.md:173-176` 和 `doc/WBS/eval-benchmark.md:139-145` 仍说本轮/当前只有 pure/fake、没有真实
   Docker 重验。准确说法应是“RONDO 失败路径已有一次真实有效态采样，但修复后双侧 completed 与正式比较
   口径未验”。
2. `doc/eval-data-layout.md:131-135` 的“不得重跑或另起 pair”与 WBS/Plan 要求后续新 tracked pair 冲突。
   应限定为“不得在当前 identity/授权下静默重跑或另起；新的独立 identity 需明确续跑决定”。
3. `doc/WBS.md:53-55` 将 L2 的 receipt 字段比较称为“请求前后重验 runtime/model digest”过强；当前没有
   对实际已加载 executable/dynamic closure/model bytes 做前后重哈希。

## 6. 已知的 B3/M1 解锁阻断

paid mode 当前受跟踪 lock 为 disabled，以下问题不可达，不构成现有结果造假；但启用 B3 前必须修复。

### R4-B3-01（高，B3 解锁）：生产 adapter 不发送逐请求 declared role

`adapters.py:351-387` 只配置共享 provider/base URL，不发送 `X-RONDO-Eval-Role`。proxy 对缺 header 的请求
只能标为 inferred；`results.py:807-824` 与 milestone/M1 又正确要求
`declared == inferred == final`。因此任何当前 paid 真实请求都不能产生 completed/M1。

不能给共享 provider 静态写一个 `main` 或 `guardian` header，因为另一类请求会与请求 shape 冲突。需要
按请求来源可信地区分 main/Guardian 的生产投影和跨模块回归；若因此修改 RONDO Rust，必须在规范 watchdog
内重建并重新冻结 bundle。

### R4-B3-02（高，B3 解锁）：pre-journal 验证失败永久卡 `publishing`

paid CLI 在 `terminal_bench/__main__.py:203-210` 先把 completed slot 持久化成 `publishing`，之后才执行
metadata/evidence/record/tree 校验并创建 publication journal。若 journal 前发生普通确定性校验失败，
`:230-232,306-318` 故意保留 publishing；重启只有 journal/index 恢复，没有 durable record 时仍无法收敛。

这条路径 fail-closed，不会重复 API 或假通过，但会永久消耗 pair/run/预算槽。启用 B3 前应把 journal 前的
确定性验证失败收敛为有证据的 `failed/blocked`，同时保持 journal 已存在时的 crash recovery。

### R4-B3-03（中）：paid durable Docker evidence 与生产 M1 收口尚未完整

运行时可以验证 image/seccomp/cgroup/VHDX/metrics，但 paid record/ledger/M1 仍未耐久绑定全部有效事实；
`assess_m1()` 也没有生产阶段收口调用点。B3 运行前应完成去敏 durable schema 与机器聚合入口。

## 7. 已知的 L2 解锁阻断

当前 CPU gate 会在 Popen 前拒绝 model-backed 启动，因此以下问题当前不可达，状态没有造假；真实 GPU/model
serving 前仍必须处理。

### R4-L2-01（高，L2 解锁）：server 可脱离 launcher/watchdog 后继续被 client 信任

receipt 只绑定 llama-server 子进程，没有 launcher/watcher PID、start ticks、heartbeat 或 lease。launcher
死亡而 server 继续监听时，client 仍可能通过 server PID/cmdline/listener 校验。全局 wrapper heartbeat 修复
没有自动进入 local client 的 identity contract。

### R4-L2-02（中）：receipt SHA 不等于实际已加载字节身份

client 只比较 lock/config 与 receipt 中保存的预期 SHA，没有请求前后重哈希实际 model/runtime，或核对
`/proc/<pid>/exe` 与动态映射闭包。Popen 前后替换/原位修改仍可能让 receipt 字段正确而实际加载字节漂移。

## 8. 独立验证

在审查 worktree 现有冻结环境中复跑：

- `just eval-test`：`Ran 277 tests`，0 failure/error/skip，约 22 秒；静态 AST 计数也是 277。
- `just eval-lock`：`Resolved 85 packages`；`uv.lock` 静态包数也是 85。
- `git diff --check a37dc761dff015e37649036077d87c737b9d91b5..5f584273297cac3ec91799d8cf53904c748357f7`：通过。
- adapter 定向 17/17 与 adapter + smoke + pair 40/40 可由统一 277 套件覆盖并重构。
- `bash -n mydev/scripts/with-build-lock.sh`：通过。

新测试不仅有 mock：pair 有真实 fork/`os._exit` 崩溃切点，watchdog 有宿主 wrapper heartbeat 反事实，
ArtifactWriter/migration 有真实临时文件/索引恢复。但 5f 的三个 ownership/permission 测试全由
`FakeEnvironment` 伪造 owner/命令返回，不能替代真实 Docker。

执行日志的若干“独立 11/11、5/5”没有列出命令或独立输出，无法从仓库单独重构；本审查不依赖这些数字。

## 9. 闭环与授权建议

当前不应把 `5f58427` 以“Plan 008 闭环完成”的名义合并/推送。若只把它作为失败现场记录与部分整改提交，
代码本身可以继续保留，但必须在交付说明中明确 B2 未验收、v4 不可再用。最小后续顺序是：

1. **先做项目内窄修，不运行 Docker：**
   - 解决 R4-M01：让当前 tracked identity 不再是 enabled v4，并冻结新的 v5/新 ID；保留 v4 所有现场与日志；
   - 解决 R4-M02：恢复入口绑定 requested side；
   - 解决 R4-M03：failed slot 持久化去敏、identity-bound evidence；补成功摘要的关键有效态；
   - 给 adapter probe 增加安全 stage/command-id 或受限去敏 stderr 摘要；
   - 同步上述实时文档，并补对应轻量回归。
2. **再运行一个新的 no-API pair：**严格 RONDO→Codex、最多两个 run、slot 1 失败即停；禁止 pull、Cargo、
   API、model、付费重试；继续使用 pinned image、custom seccomp、`cap_drop=ALL`、private cgroup、规范 watcher，
   保留成功或失败的结构化摘要和前后 VHDX/df/cleanup 证据。
3. 只有新 pair 双侧 completed、摘要可持续回读、ownership/secret/workdir/logs 有效态均通过，B2 才可称完整验收。
4. B3 先修 R4-B3-01/02/03，再冻结新的 paid pair/batch、任务/轮次/model/总预算与 per-run cap，另行取得
   真实 API 批量授权；当前不能只追加 API 权限后直接开跑。
5. L2 先实现 R4-L2-01/02 与 GPU runtime；权重下载、真实 GPU 加载/推理另行授权，并与 Docker/重型 Cargo
   严格串行。

创建 v5 和上述项目内代码/文档修复不引入新的宿主机或外部权限类别；但本轮是只读审查，仍需用户明确指示
执行方继续。Plan 008 原有 Docker 授权原则上覆盖同计划的 no-API 续跑，但鉴于 v4 已消耗并永久失败、下次是
新的受跟踪一次性 pair，建议用一条明确续跑指令固定边界。无需给真实 API、Cargo 或模型授权。

“未发现新的 P0/P1”只说明当前 hard-disabled/gated 状态没有已知立即误用路径，不能替代尚未通过的真实 B2，
也不能推出“无隐患、无缺陷、无 bug”。
