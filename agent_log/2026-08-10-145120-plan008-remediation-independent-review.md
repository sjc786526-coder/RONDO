# Plan 008 审查整改与阻塞排查第二轮独立审查

时间：2026-08-10（Asia/Shanghai）

审查对象：整改工作树 `c5fa0c775179016d20f3884753a9369ee7c4c877`

交付主树：merge `2cc9140022f69803afff7bc373e3beeee0579be9`，本地 `main == origin/main`

第一轮问题基线：`agent_log/2026-08-10-120053-plan008-independent-implementation-review.md`

执行方整改记录：`agent_log/2026-08-10-141210-plan008-independent-review-remediation.md`

## 1. 审查范围与方法

本轮逐项回看第一轮 F-01～F-16，不以新增测试通过替代源码和状态机审查；同时反向检查以下边界：

- pair/fairness 身份、顺序、崩溃语义与 M1 聚合；
- Harbor、两侧 bundle、eval harness、Docker 镜像和 llama.cpp 的实际运行身份；
- Docker 有效态、seccomp 反事实、宿主/daemon 资源门禁与 cleanup；
- ArtifactWriter、一次性迁移、预算账本和 pair 账本之间的崩溃一致性；
- L1 evidence/sink、L2 redirect/service/model identity 与状态口径；
- 测试数量、保留证据、清理、Git 合并和文档当前态声明。

遵守本批边界：未运行 Docker、Cargo、真实 API 或本地模型，未下载依赖/权重，也未读取 `.env.local`。
没有为重背书而复跑 237 项全量测试。独立轻量复核中，六个新增合同相关模块 78/78 通过；另做了一次
只写 `/tmp` 的真实进程死亡故障注入。审查前 tracked worktree clean，审查只新增本日志。

## 2. 总结论

整改不是表面补测，第一轮多数问题已有实质改进：

- F-03 的“零容器也成功”已关闭，容器 user/capability/NNP/seccomp/memory/swap/pids/network/mount 等
  有效态已进入监督合同；
- F-04 原来单轮可拖 135～195 秒的采样盲窗已关闭，规范 flock、默认 cgroup memory/swap 和 counters
  也已校验；
- F-05 的共享 `ArtifactWriter` 已改为 journal v2、完整索引临时文件 fsync + atomic replace，并绑定
  record、index pre/post 与 artifact tree；
- F-06 已从只锁 18KB launcher 扩展到 52 个普通文件、10 个 symlink、8 个宿主动态依赖，并移除
  ambient `LD_LIBRARY_PATH`；
- F-07 redirect/bearer 泄漏路径已关闭；F-09 的 Lite discriminator、合法 ToolSearch 历史证据和最终
  private-transport sink 已修复；
- F-08 当前三条旧诊断已正确迁移为 `infra_failed`，预算槽不回收，现场无事务残留；
- F-11 正式 Terminal-Bench producer 已关闭 non-completed + success/reward、request-role 少报等交叉矛盾；
- F-12 已正确拆开 M1 与 S2；F-15 process group 与 container/network/volume exact cleanup 已落实；
- 固定容器 default/custom seccomp 对照设计合理，no-API v3 的 RONDO→Codex 正常路径通过具有可信依据。

但不能接受整改日志中“F-01～F-16 当前阶段缺口全部闭合”“B2 生产门禁全面闭合”的总括结论。本轮发现
4 项当前生产/资源门禁高严重度缺口，以及 1 项未来 M1 高严重度缺口。它们不推翻已经发生的 v3 正常路径
结果，也不改变 0 API/0 USD、B3/M1 未运行、无模型 doctor=78 等事实；但阻止把 B2 设施描述为完整验收。

## 3. 高严重度问题

### R2-H01：PairSequenceLedger 的终态写入崩溃可把整个 pair 重置为全新账本

证据：`eval/rondo_eval/terminal_bench/pair.py:222-234` 的 `_persist()` 在原文件上执行
`seek(0) -> truncate(0) -> write -> flush -> fsync`。下次打开时，`:120,137-149` 把 0 字节文件解释为
首次创建，并重建 `next_slot=1 / blocked=false / runs=[]`。

现有回归 `eval/tests/test_terminal_bench_pair.py:185-212` 只覆盖 active 已完整 fsync 后进程退出；它没有覆盖
任务已经执行完、`finish()` 写 completed/failed 时进程死亡。后者不是理论上的“未运行便重试”：外部任务已经
发生，随后在终态持久化窗口被杀，原 slot 历史才被清空。

本轮用实际类和 `os.fork/os._exit` 做了 `/tmp` 故障注入：先持久 claim RONDO slot 1，再让子进程在
`finish(completed=True)` 的 truncate+fsync 后退出。结果为：

```text
child_exit 77 ledger_size 0
reopened_before_claim ... "next_slot": 1, "blocked": false, "runs": []
replacement_claim ... "run_id": "replacement-after-reset", "slot": 1, "status": "active"
```

no-API run-id 每次随机生成，因此确实可以形成替代 slot 1。paid 的固定 run-id/预算账本能降低重复付费风险，
但不能恢复 pair 拓扑。整改日志“崩溃遗留 active 永久封锁 pair”只对完整 active 文件成立。

影响：F-01 的 crash 语义未闭合；当前 v3 ledger 本身完整，不据此否定已完成 pair，但 B2 设施不能称全面验收。

### R2-H02：WatchdogProof 仍可在外层宿主安全阈值被放宽时签发生产 lease

`eval/rondo_eval/runtime_bridge.py:54-60,248-250` 只拒绝 lock/watchdog 和三个 memory/swap override；
`mydev/scripts/with-build-lock.sh:16-27,49-64,119-131` 还接受：

- `RONDO_PROJECT_ROOT`；
- project warn/stop/max、filesystem free floor；
- host memory、PSI、nonreclaimable、swap stop；
- disk sample interval、residual grace 等覆盖。

例如把 `RONDO_PROJECT_ROOT` 指到另一个小目录，或提高 project stop/max，规范 flock 和默认 cgroup
`memory.high/max/swap.max` 仍成立，`lease_from_watchdog()` 仍会通过，但真正 RONDO 根目录、宿主内存/PSI
和残留进程门禁已不是规范默认值。Docker 内层 supervisor 不能替代这些外层门禁。

既有 watcher summary 能支持本轮正式运行实际使用了项目 wrapper/default limits；问题是生产 proof 的
fail-closed 合同仍可被 ambient override 绕开。当前测试只覆盖 lock/memory override，未覆盖上述变量。

### R2-H03：Docker Desktop VHDX 实际增长已被读取，却没有进入 40/60GB 门禁

`eval/rondo_eval/runtime_bridge.py:918-1015` 读取实际 `docker_data.vhdx/ext4.vhdx` 的
`vhd_size_bytes` 和宿主盘 free bytes；但 `:703-711,766-792` 构造 `DockerCounterReading` 时丢弃
`vhd_size_bytes`。`eval/rondo_eval/docker_supervisor.py:1355-1391` 的 40/60GB 判据只使用
`docker system df` 与 task logical bytes。

因此 VHDX 的真实新增分配如果因临时空间、元数据、共享层或统计时序与 `docker system df` 不一致，只要宿主
剩余空间尚高于 80GiB，就不会触发 40/60GB 警戒/停止。这没有完整实现 AGENTS.md 要求的“以本次任务开始时为
基线”的 Docker 实际新增占用门禁。现有测试只验证 PowerShell 能解析 VHDX 数值，没有把它传到 supervisor。

本轮 v3 两侧的保留 summary 显示 logical Docker total 未增长、宿主 free 充足；本项不表示当时实际超限，而是
生产安全门禁仍缺一条已采集事实。

### R2-H04：pair 没有绑定两个 slot 共用的 eval harness commit

`eval/rondo_eval/terminal_bench/results.py:113-128` 会返回 clean eval harness commit；paid 路径把它写入
结果，并在单 run 前后复核。no-API 入口 `docker_smoke.py:583-599` 调用了检查却丢弃返回值；受跟踪 pair lock
和 `PairSequenceLedger` 都不记录 harness commit。

于是 RONDO slot 可在 clean commit X 完成，仓库随后正常提交/切换到 clean commit Y，再执行 Codex slot；只要
pair lock 本身没变，机器仍会把两槽认作公平 completed pair。这个场景不需要同 UID 恶意篡改，是普通跨提交执行
就可产生的公平漂移。

现有 v3 两个 watcher 目录都标记 `9404c5a`，运行间隔很短，且从该 commit 到当前相关 no-API core 未变化，
所以本项不推翻 v3 现场；它阻断的是 F-01“未来 pair 的公平条件已由机器完整绑定”的强结论。

### R2-H05（B3/M1 前置）：已发布 completed 结果可与 failed pair ledger 同时令 M1 判 passed

paid CLI 在 `terminal_bench/__main__.py:168-186` 先完成正式 result publication，直到 `:242-245` 才
`sequence.finish()`。若在两者之间进程死亡或 ledger 持久化失败，结果行已经 durable，而 slot 仍为 active；
下次 claim 又会按 `pair.py:165-180` 把它转成 failed/blocked。

`assess_m1()`（`pair.py:554-620`）只聚合两条 record，不读取或核对对应 pair ledger。因此两侧正式结果均为
completed 时可以返回 `m1=passed`，即便其中一侧的持久 pair 状态最终是 active/failed，CLI 也没有完成正常收尾。

这是跨 `ArtifactWriter` 与 pair ledger 的状态机问题，不是共享 writer 单体原子性问题。当前 B3/M1 没有运行，
所以没有现成虚假 M1；但它是重新启用 paid 前的里程碑阻断项。

## 4. 中严重度问题

### R2-M01：Harbor preflight 只绑定包本体，不绑定实际入口字节和依赖运行闭包

`pair.py:847-883` 只哈希 `harbor/`、少量 `harbor-0.20.0.dist-info` 文件，并明确跳过 pyc；没有覆盖
`uv.lock` 中 fastapi/httpx/litellm/pydantic/requests/typer/uvicorn 等 Harbor 实际依赖。
`pair.py:886-911` 对真正由 `runner.py:456-480` 执行的 ignored `.venv/bin/harbor` 也只检查解释器及
`from harbor.cli.main import app`/`app()` 文本标记，不校验完整字节。保留这两段标记即可加入额外行为而通过。

这按已约定的个人项目威胁模型属于身份漂移/复现性问题，不上升为同 UID 对抗或签名体系要求；但“Harbor wheel/
安装 closure 已闭合”仍过强。轻量修复应绑定生成入口字节，并对 frozen sync 的实际依赖版本/内容形成可复核 closure。

### R2-M02：pair ledger 与 ArtifactWriter 没有可恢复的跨事务衔接

除 H05 的 false M1 外，另一个方向也会形成 fail-closed 状态分裂：pair 先写 active，ArtifactWriter 的 journal/
target/index 已完成或可恢复后，进程在 `sequence.finish()` 前死亡。下次 writer 能恢复完整结果，pair 却把遗留 active
无条件解释为“发布前失败”并永久 block。

影响是已授权 run/budget 被消耗、正式结果存在、pair 仍失败，无法由现有恢复器自动收敛。它不凭空放行付费请求，
故低于 H05；测试把“遗留 active”等同于“未发布”，没有覆盖 publication 边界。

### R2-M03：F-08 migration 包装层会抢在 ArtifactWriter 恢复前作出错误状态判断

`migrations/plan008_claimed_diagnostics.py:164-181` 先 `prepare_migration()`，之后才可能启动 writer；prepare
只看 index row 和 target：

- target 已 rename、index 仍为 before 时会先判 conflict，writer 无机会恢复；
- index 已替换、journal 未删时会直接报 already_applied，journal 留存；
- journal 已写、target 未 rename 时先判 pending，`writer.start()` 恢复后又因同 run 已存在报错，往往需再跑一次。

当前三条真实迁移已成功，index、私有 migration artifact、Git source 和 ledger 均一致，且无 journal/staging/temp
残留；“原 work 删除后稳定 already_applied”也成立。本项只否定“任意 publication crash 后一次重跑即可幂等恢复”。

### R2-M04：容器有效态没有绑定 daemon 实际运行的镜像 ID/digest

F-03 的大部分有效态已正确补齐；但 `runtime_bridge.py:1187-1286` 忽略 container inspect 顶层 `Image`，
`DockerContainerFact`/`HostContainerContract` 也没有 image 字段。当前只证明 staged Compose 输入写了冻结 digest，
没有在 exact-label 容器的 daemon 有效事实中证明实际镜像就是冻结 `fix-git` 镜像。

正常 Docker digest 语义显著降低现场风险，因此定为中等，而不是否定本轮容器结果。应把 materializer 已知 digest/
resolved image ID 投影到 inspect equality contract。

### R2-M05：paid 路径尚未接入已经验证的 custom seccomp

no-API 在 `docker_smoke.py:588-627` 注入 profile path/source/effective SHA，`pair.py:396-414` 也只在
`mode=no_api` 检查。paid CLI `terminal_bench/__main__.py:91-106` 没有填写三个字段，因此按当前代码重新启用
paid 会回到 builtin seccomp，并重现本轮已确认的 nested user namespace/bwrap 失败。

当前 paid hard-disabled 是可靠的，且发生在密钥/API/Docker 前；所以本项不影响 B2，也不表示未授权运行可能发生。
但 B3 的后续条件不能只写“新 pair/预算/API 授权 + 容器 metrics”，还必须增加 custom seccomp 的生产接线与明确
安全决策。

### R2-M06：F-16 只有文档延期，没有成为未来 paid/M1 的机器启用门禁

文档诚实说明 runner-host rusage 不含 daemon 容器进程；但 pair lock 的 paid disabled reason 只有新 pair/预算授权，
`RunPublicationContext.validate()` 和 `assess_m1()` 仍只要求五键 host metrics，没有字段或谓词要求 supervisor 的
容器 CPU/峰值内存。若后续只按当前启用步骤改 lock，host-only metrics 仍能发布并满足 M1。

另有口径限制：timer 在多项 preflight 之后才启动，CPU 是起止差值，但 `ru_maxrss` 是进程生命周期累计峰值，无法
扣除 timer 前峰值；`max(self, children)` 也不是进程树 RSS 总和。当前把它只用于设施诊断是正确边界。

### R2-M07：Local service/model identity 仍是可选、自报且没有绑定 launcher 实例

`LocalApprovalClient.decide()`（`local_approval/client.py:222-255`）不调用 `verify_service_identity()`；doctor
先请求 `/props`/`/v1/models`，再独立发 decision。任意占用配置 loopback 端口的 responder 只要自报预期 build、
model path、alias，即可通过；identity probe 与 decision 之间服务也可被替换。没有 launcher PID/nonce/实例归属，
服务自报 path/alias 也不证明实际加载的模型 bytes。

F-07 redirect 已闭合、模型文件 GGUF header/digest 和 response model alias 校验也有价值；当前无模型 doctor 78
不受影响。但“endpoint/model identity 已闭合”不能成立，真实 L2 前需要把 launcher 创建的实例与 probe/decision
绑定，且普通 consumer 不能绕开该门禁。

### R2-M08：当前 CPU-only runtime 使“L2 前置只待模型接入”过度简化

`eval/locks/llama-cpp-b10333.json:95-96` 明示 `cpu_only_no_model`，而 L2 权威 WBS 要在 RTX 4060 Laptop
上实测显存、上下文与延迟；示例 `gpu_layers=auto` 会映射为 `--n-gpu-layers 99`，这些 model-serving flags 又明确
尚未实模验证。即使只补 GGUF，也可能仍需 CUDA backend/runtime 与 GPU 启动参数验收。

更准确状态是“CPU x64、无模型的 client/doctor/launcher 前置已就绪；GPU/model-backed L2 仍待实现和验收”，
而不是只差权重文件。

### R2-M09：缺 role header 的请求仍会被推断后记成 verified role

`api_budget_proxy.py:693-698,898-904` 先把缺 header 的请求记 unknown，再按 payload 形状提升为 main/guardian；
metadata 不保留 declared/inferred provenance，`milestone_metadata_ready()` 及 `assess_m1()` 会把推断后的 main 当作
满足真实主请求门槛。测试还明确固化了这个语义。

当前 paid disabled，未造成虚假 M1。B3 前应要求显式 role，或至少保留 provenance 并禁止 inferred-only evidence
满足 M1；形状推断可继续用于诊断，不能称 verified。

### R2-M10：非零 actual_usd 仍只是本地冻结价格估算

`terminal_bench/results.py:280-299,416-433` 把同一个 usage×price `spent` 同时写入 `estimated_usd` 和
`actual_usd`。当前三条记录和账本均为 0，因此“0 USD”数值不受影响；未来付费 run 若不查询账单，字段必须改称
metered/estimated，不能把本地估算写成 actual。

### R2-M11：关键 Docker/no-API 细节没有耐久的机器产物

seccomp 诊断 parser 同时接受 denied/ok，CLI 只把结构化观测打印到 stdout；保留 watcher summary 只证明命令 rc=0，
没有保存 default/custom 的 uid/CapEff/NNP/Seccomp/unshare/bwrap JSON。因此准确表述应是“本次受控、单变量反事实
的执行日志观测支持 builtin seccomp 归因”，不是可从现存机器产物独立重算的冻结 oracle。

同样，no-API v3 的 pair ledger、两份 watcher summary 和 `result.passed` 控制流足以支持正常路径 completed；但 raw
trial/safe summary 已清理，现存资产不能逐项重算“2 fake requests、6 events、tool round-trip、reward、5 samples”等
日志细节。它是证据保留局限，不单独推翻 B2 结果；后续高价值 no-API pair 宜原子保留去敏 safe summary。

### R2-M12：Plan 008 交付后的 current-state 仍停留在待终审/待合并

实际 merge tree 与 `c5fa0c7` 一致，主树和本地远端跟踪均为 `2cc9140`，done 分支已重命名；但
`plan/008-p1-terminal-bench-and-local-approval-execplan.md:196-206` 仍写“正在同步/清理/独立终审”、
“实现仍位于 worktree”“只剩合并与推送”，`:159` 仍保留旧 main/origin SHA。按项目文档只展示实时状态的约定，
这是明确的交付后过时陈述。

## 5. 低严重度与明确边界

- seccomp profile 是面向整个 container、对 non-`CAP_SYS_ADMIN` 进程放开 syscall-name 集，并非内核层只绑定
  frozen bwrap；README 仍称“只用于 opt-in diagnosis”，与实际 no-API production 使用不一致。现有 non-root、
  cap-drop ALL、NNP、非 privileged、有效 profile digest 大幅限制风险，不据此称越过用户安全禁令。
- sampler 现在是先 wait 最多 5 秒，再给整轮 probe 最多 5 秒，最坏相邻完成样本约 10 秒；原 135～195 秒盲窗
  已关闭，“5 秒采样”宜写成“5 秒等待 + 5 秒绝对 probe deadline”。
- llama runtime 闭包主体已修复；configured binary 若是可替换 symlink，校验 resolved target 后仍用原路径 exec，
  留有同 UID TOCTOU。当前正式配置使用普通文件，按个人本地威胁模型仅属纵深加固。
- ToolSearch `tools` 白名单只检查局部 `type=tool_search_output` 和 list，没有完整 schema/合法位置负测；最终无顶层
  工具授权，主要影响协议歧义，不是工具能力逃逸。
- 共享 `ArtifactWriter` 仍可接受 track-specific 矛盾 TB record，但正式 TB producer 已在发布前严格验证；这是
  future producer/所有权边界，不是当前 CLI 可达漏洞。holdout `tasks=null` 仍属 L3/L4 后续设计债务。
- `RuntimeConfig` nested dict 可变、配置/secret 检查读取有同 UID TOCTOU、target no-overwrite 是 check 后
  `os.replace`，沿用第一轮 Low 结论；optional local key 的既定无鉴权 loopback 语义不是问题。
- `already_applied` 用 Python 对象相等，`False == 0 == 0.0` 可产生低风险类型歧义；当前三条现场无此问题。
- 当前审查期间的轻量测试重新生成约 832KiB ignored `__pycache__`。这发生在执行方有证据的最终清理之后，不应归责
  为其“393.71 MiB 清理”虚假；tracked 状态不受影响。整改日志的“393MB”更准确是 393.71MiB。

## 6. 第一轮 F-01～F-16 逐项判定

| 第一轮项 | 第二轮判定 | 说明 |
|---|---|---|
| F-01/F-02 pair/fairness/身份 | **部分修复** | pair lock、两侧 manifest/bundle、顺序和正常 preflight 已落地；账本 crash-reset、跨槽 harness commit、Harbor 入口/依赖 closure 仍未闭合 |
| F-03 Docker 有效态 | **主体修复** | 零容器成功及大部分 inspect 合同已关闭；实际 image ID/digest 未绑定 |
| F-04 watchdog/采样 | **部分修复** | flock、默认 cgroup memory/swap、共享 probe deadline 已落实；外层 safety overrides 和 VHDX 增长仍可漏过 |
| F-05 原子归档 | **单体修复、跨事务未闭合** | ArtifactWriter 本身显著加强；pair publication/finish 与 migration wrapper 仍有恢复状态分裂 |
| F-06 llama runtime closure | **主体修复** | 目录、symlink、ldd、宿主依赖和环境已绑定；仅余低风险 configured symlink TOCTOU |
| F-07 redirect | **修复** | no-redirect、禁 proxy、final URL、bearer 不转发均有负测 |
| F-08 claimed diagnostics | **当前现场修复** | 三行 infra_failed、ledger、migration artifacts 一致；故障切点的一次重跑恢复仍不完整 |
| F-09 L1 evidence/三 consumer 口径 | **修复** | 协议/sink 问题关闭，文档已明确只是三组 fixture 投影 |
| F-10 local identity | **部分修复** | model digest/GGUF/alias/props 增强；launcher/service/model 实例未绑定，CPU-only 也不是完整目标 runtime |
| F-11 结果交叉约束 | **正式 producer 修复** | ordinary/claimed 路径已一致；共享 writer/future holdout 保留后续债务 |
| F-12 M1/S2 | **语义拆分修复，M1 状态机未闭合** | 不再强迫每条 run 触发 Guardian；但 M1 聚合不核对 pair ledger |
| F-13 seccomp 归因 | **受限接受** | 对照设计和 custom 有效态可靠，足以支持本冻结环境归因；原始成对 JSON 未耐久保存 |
| F-14 配置/入口 | **部分修复** | timeout/retry 与 proxy-sanitized frozen just 入口已加强；第一轮低风险 mutable/TOCTOU 保留 |
| F-15 cleanup/process tree | **修复** | process group、exact container/network/volume 监督与最终空检查均已接线 |
| F-16 metrics | **诚实延期、未机器封锁** | host 五键只作诊断的表述正确；paid/M1 尚未强制容器 CPU/peak memory |

## 7. 阻塞排查与 no-API 证据复核

### 7.1 可以接受的事实

- custom profile 不是 `privileged`、`SYS_ADMIN` 或 `seccomp=unconfined`；source bytes、Git clean、上游 delta
  和 daemon reserialized effective SHA 均进入校验。
- default/custom 在固定镜像、UID 1000、CapEff=0、NNP、同一 bwrap 下的单变量设计合理；custom 后真实 no-API
  双侧路径通过，显著增强“本冻结环境中 builtin seccomp 阻断 user namespace”的因果判断。
- v3 pair lock SHA 与 ledger 一致；ledger 当前为 RONDO slot 1、Codex slot 2 completed、`next_slot=3`、
  `blocked=false`。两份 watcher summary 均 `run_rc=0/final_rc=0`、无 stop/cleanup、swap=0。
- `DockerNoApiSmokeResult.passed` 只在 Harbor completed、恰好 2 个 accepted fake request、agent JSON event 和
  tool round-trip 均成立时为真，ledger 又只在 `result.passed` 时记 completed。因此现存 pair+watchdog+代码足以
  支持“正常路径 RONDO→Codex no-API completed”。

### 7.2 需要收窄的结论

- 只能说“受控反事实支持在本冻结环境中 builtin seccomp 是原因”，不把它推广成所有 Docker/userns 故障的
  唯一原因；也不能说现存机器产物可独立重放每个原始 probe 值。
- no-API v3 是 B2 正常路径证据，不是 agent 性能成绩；reward=0 不影响设施验收。
- 当前 paid 路径没有 custom seccomp 接线。即使取得新 API 授权、冻结新 pair/预算并补 metrics，仍会回落到
  builtin seccomp；这是 B3 的额外前置阻断。

## 8. 测试、账本、清理与交付声明

- 静态精确统计为 237 个 unittest test method；执行方的 `237/237` 与 `uv lock --check: 85 packages` 有执行日志，
  但没有持久 JUnit/transcript。清理后没有 `eval/.venv`/uv cache，本轮没有为复跑全量而重新联网同步。
- 独立轻量复跑 78/78 通过，覆盖 contracts/evidence、ArtifactWriter/config、F-08 migration、namespace 与 TB
  results 等关键模块；H01 另有真实进程死亡故障注入。新增测试总体有价值，但没有覆盖本日志列出的切点。
- `eval/results/runs.jsonl` 当前正好三条 `infra_failed`，request/cost 为 0；预算账本三个 run 均
  `requests={}`、`spent_usd=0`、权限 0600。0 API/0 USD 是项目代理/账本证据，未查询供应商账单；在零值场景
  不影响结论。
- 最终清理 summary 证明减少 412,835,840 bytes，即 393.71MiB，并且交付时 target/.venv/所列 cache 为 0。
  审查者后续测试新生成的 ignored pycache 不应反推执行方清理不实。
- merge `2cc9140` 的 tree 与整改 tip `c5fa0c7` 一致；本地 `main == origin/main`，origin/main reflog 也有 push
  记录，done 分支重命名成立。本轮未联网做 `ls-remote`，因此这里是本地远端跟踪/ref-log 证据，不冒充实时服务器查询。

## 9. 最终状态建议

- **B1**：版本、task、archive、image 和两侧 bundle 冻结可保留；Harbor 只能称“包本体/版本已绑定”，不能称
  完整安装/执行闭包。
- **B2**：v3 双侧 no-API 正常路径通过可保留；但 pair crash、跨槽 harness identity、完整 watchdog 和实际
  Docker growth 门禁仍有高严重度缺口，因此不应标记“全面闭合/完整验收”。
- **L1**：按当前收窄后的“共享协议 + 三组 fixture 投影”口径可以接受完成。
- **L2 前置**：redirect、runtime closure 和模型文件检查已有实质进展；service instance/model identity 仍未闭合，
  且当前只是 CPU-only runtime，不能写成只差权重即可满足目标 GPU L2。
- **B3/M1**：保持未运行。重启前除新 pair/预算/API 授权与容器 metrics 外，还必须接入已批准的 paid seccomp、
  让 M1 核对 durable pair 状态、区分 inferred/declared request role，并修正 actual cost 口径。

本轮终审结论：**整改可合并作为显著进展，现有 no-API 与零费用事实可保留，但“F-01～F-16 全部闭合、B2
完整验收、L2 identity 已闭合、B3 只待授权”的强表述不通过。**
