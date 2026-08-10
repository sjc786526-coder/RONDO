# Plan 008 独立实现审查结论

时间：2026-08-10（Asia/Shanghai）
审查对象：`main` / `origin/main` / `HEAD` = `19c650c3ef2d17079b1bf0cd7aac5a6d000282c2`
对照计划：`plan/008-p1-terminal-bench-and-local-approval-execplan.md`
对照实施日志：`agent_log/2026-08-10-064707-p1-terminal-bench-local-approval.md`
异议复核：2026-08-10 已与执行者就 F-02、F-08、F-11、F-12、F-14 和最小 metrics/attribution 边界
达成共识，本文按复核结论收窄。

## 1. 审查结论

本批实现可以作为 **Plan 008 的部分基础设施** 保留，但不能接受“共享合同、B1/B2 代码、L1 已完整完成，
唯一剩余阻断只是 Docker builtin seccomp”的强结论。

更准确的状态是：

- Standard/Lite 解析、配置、预算代理、单侧 runner、task/image materialize、两侧 bundle、Docker 监督框架、
  llama.cpp client/doctor/fake/launcher 等主体骨架已经落地；正常 pure/fake/loopback 路径有较充分测试。
- B1 的 dataset commit、`fix-git` task/archive、image digest 与 Harbor 版本资料冻结较扎实；现有日志记录的
  两侧精确 SHA 也是有效事后证据。但实际 Harbor 安装缺少版本 preflight，runner 也没有消费受跟踪的
  pair/batch identity，因此运行前身份闭环尚未完成。
- B2 不只是“真实 Docker 环境尚未跑通”：两侧公平配对、run 拓扑、有效容器隔离、看门狗锁/限额证明、
  运行时身份和原子结果归档仍有代码级验收缺口。即使 Docker namespace 问题消失，也不能直接进入付费 B3。
- B3、M1 确实未完成；三次诊断已占用同一批次三个 Codex 槽位，只剩一个槽位，同批次已不可能再形成
  “同任务 Codex/RONDO 各一轮”的最小合规 pair。最小逐 run wall/CPU/peak RSS 也尚未实现。
- L1 的共同逻辑 payload 方向正确，但尚未真实验收 Luna/Sol/Local 三个消费者，且合法
  `ToolSearchOutput` 会被 Local client 拒绝；因此当前只能称“L1 协议骨架/正常样例完成”，不能称普适完成。
- L2 当前应继续保持“无模型、无真实推理”的前置状态；此外，现有 pin 只覆盖动态启动壳，不覆盖实际共享库，
  loopback redirect 还可越过本地边界。它不是“只差下载权重”即可验收的状态。
- “真实 OpenAI API 请求 0 次、费用 0 USD”有强的项目内账本/代理证据；本审查没有查询供应商账单，
  因此它是受控链路证据，不是外部账单审计。

据此，本审查结论为：**部分实现可合并这一历史决定可以理解；Plan 008 的 B2、B3、M1、完整 L1 与真实 L2
均不得据此标记验收通过。当前 WBS 中“原子归档”“L1 已完成”“B1/B2 代码已落地”的口径需要在后续修复时
收窄或重新验收。** 原终审中的“可合并、无新增阻断”不能转述为“无验收阻断”。

## 2. 审查范围与方法

本次按用户要求只做审查并写本日志，没有修改源码、测试、计划、WBS、结果库或本地运行资产。

审查覆盖：

- `README.md`、`doc/WBS.md`、两个方向 WBS、`doc/eval-data-layout.md`、Plan 008 与实施日志；
- 合并批次全部 `eval/` 生产代码、关键测试、受跟踪 locks、ignored runtime manifests、预算账本与保留现场；
- 与冻结 Codex `v0.147.0` 源码相关的 Guardian/Responses Lite/`ToolSearchOutput` 结构；
- merge/feature 历史中的 `runs.jsonl` 增删、当前 worktree/main/origin 状态；
- 既有 Docker/no-API/watchdog 原始证据的静态复核。

本次没有运行 Docker、Cargo/链接、真实 API、llama.cpp server、模型推理，也没有联网下载依赖或权重。
不需要重做执行者已经完成的数十分钟构建和 Docker 探针；相关结论通过代码控制流、冻结产物和原始日志交叉验证。

唯一在线资料核对是 OpenAI 官方 Luna 模型页。2026-08-10 页面所列输入、缓存输入、输出价格分别为
`$0.20 / $0.02 / $1.20 per 1M tokens`，长上下文倍率也与实现一致；因此本审查**没有**发现价格常量错误。
来源：<https://developers.openai.com/api/docs/models/gpt-5.6-luna>。

严重度含义：

- **高 / 验收阻断**：在对应能力被标为完成或进入真实付费/真实审批前必须修复；不等于现场已经被恶意篡改。
- **中**：会造成结果失真、合法输入不可用、错误能力声明或未来阶段失败，应在相关阶段前修复。
- **低**：复现性、文档语义或纵深防御问题，不单独阻断当前部分基础设施保留。

## 3. 高严重度 / 验收阻断项

### F-01：B2 的双侧公平与 pair/batch 身份门禁没有进入生产（合并原 F-02）

证据：

- `eval/rondo_eval/contracts.py:193-242` 定义了 `fairness_fingerprint()` / `assert_fair_pair()`；
- 全仓生产路径没有调用 `assert_fair_pair()`，引用仅在定义和单元测试；
- `eval/rondo_eval/terminal_bench/__main__.py:40-88` 每次只接收一侧并允许独立传
  `--timeout-seconds`；`runner.py:307-377` 也只构造/校验单个 `RunSpec`；
- `PersistentBudgetLedger` 只约束总数不超过 4 和 run-id 不复用，不约束
  `2 task × 2 side × 1 round`、两侧顺序或每侧各一次；
- paid/no-API 入口接受 common-root 下符合结构的 ignored binary manifest；adapter 会复核三份实际文件 SHA，
  但期望值来自同一 manifest。受跟踪实施日志中的精确 SHA 可供事后核查，runner 不会在启动前读取并绑定它；
- 实际 Harbor 使用 ignored `eval/.venv/bin/harbor`，`uv.lock` 固定了 0.20.0，但生产入口只检查可执行路径，
  没有核验实际安装版本/环境身份。

可构造的错误成功：Codex 用 timeout 1800、Rondo 用 timeout 900，或两次之间修改 provider config；两个
`RunSpec` 均可独立通过并归档，系统没有任何生产 aggregator 把它们配成一对并 machine-reject。

现场账本已经接受同一 `fix-git`/Codex 的 r1、r2、r3，正好证明轮次拓扑没有机器执行。三个 run 的
`requests={}`、`spent_usd=0`，所以预算安全没有失守；但只剩一个槽位，不能再完成最小双侧 pair。

影响：Plan 008:29-31、48-52、109-114 的核心公平合同没有进入真实执行路径。B2 不能称合同完成，B3
也不能仅在 Docker 环境恢复后继续消耗最后一个槽位。

身份部分应按非对抗性漂移/复现性问题理解，不是同 UID 篡改安全漏洞，也不需要签名、权限体系或复杂可信链。
合适修法是把它并入同一 pair/batch 门禁：由 clean runner 读取轻量、受跟踪的结构化 manifest，核对两侧
CLI/code-mode-host/bwrap digest、source identity、Harbor 锁定身份与公平配置；no-API 和 paid 共用同一 preflight。
主树不提交 ignored `.venv` 是正常行为，缺口只是生产入口没有核验实际同步后的 Harbor 身份。

### F-03：Docker supervisor 可以在未观察到任务容器、也未验证有效隔离时返回成功

证据：

- `docker_supervisor.py:457-532` 只拒绝 baseline 已有 exact-label 容器；host 返回 0 且每次 sample 都为空时
  仍返回成功；`test_docker_supervisor.py:248-275` 明确把这一场景固化为成功；
- runtime inspect 主要验证对象 ID、label、尺寸，没有复核最终 `Config.User`、`Privileged`、`CapAdd/CapDrop`、
  `SecurityOpt/seccomp`、memory/swap/pids、mount、network/read-only 状态；
- overlay 中写入 non-root/资源限制只能证明配置意图，不能证明 Compose 合并和 daemon 生效后的事实。

错误成功场景包括：Harbor/Compose 漂移导致 label 没应用、容器活得短于采样窗、基础 compose 覆盖 overlay，
或 daemon 实际配置偏离。此时任务容器可完全脱离计数/清理或以错误权限运行，host 仍可能返回 0 并进入结果解析。

当前冻结 Harbor compose 静态上未发现明显危险字段，既有运行也没有观察到泄漏容器；这不能替代生产
fail-closed 门禁。尤其不能据当前证据断言“最终有效态已确认非 privileged、无 SYS_ADMIN、固定资源上限”。

### F-04：看门狗 lease 与 Docker 采样不真正证明硬安全合同

有两个独立问题：

1. `runtime_bridge.py:124-206` 的 `WatchdogProof` 只证明进程位于匹配命名的 cgroup 且 counters 可读；
   它不证明持有规范 flock，也不读取/核对 `memory.high/max/swap.max`。用 `RONDO_BUILD_LOCK=0`、自定义 lock
   或自定义限额启动同一 wrapper，仍可获得可通过的 proof。
2. `docker_supervisor.py:477-494` 在一次 5 秒 wait 后串行执行多个 Docker CLI/inspect 和 15 秒 Desktop
   probe；单个 Docker CLI 默认可等 30 秒。daemon 变慢时一次 sample 最坏可拖到约 135～195 秒，期间不再
   检查 wall timeout、60GB 新增占用或 80GiB 剩余空间。

因此，“所有生产重任务严格共享同一 flock/默认限额”“每 5 秒实时停止”不是代码能够 fail-closed 证明的事实。
既有正式运行确实通过项目 wrapper 且 summary 未显示 swap/stop 异常；发现针对的是可执行门禁与最坏情况延迟，
不是声称本次构建实际绕过了锁。

### F-05：`ArtifactWriter` 不是进程崩溃下的原子归档

证据：

- `artifacts.py:476-494` 多次 `os.write` 追加 JSONL，只在 `except Exception` 时截回原长度；部分写入后发生
  `KeyboardInterrupt`、SIGKILL、进程崩溃或主机异常时会留下半行；
- journal（`artifacts.py:283-295`）没有记录 append 前的 `original_size`；
- 恢复先由 `_run_id_exists()`（`:497-515`）解析整个 JSONL；遇半行即报 invalid JSON，既不能安全截断，
  也不能完成/撤销 journal，后续所有 run 会被永久阻断；
- 恢复路径 `artifacts.py:298-355` 不重新扫描 staging/target，也不绑定工件 manifest/hash；journal 写入后到
  下一次恢复前若工件被并行进程修改，恢复会直接发布修改后的内容，而且恢复时已经没有原 secret 集合。

已有测试只覆盖可捕获 OSError、append 调用前的 `KeyboardInterrupt` 和未篡改恢复，没有覆盖“已写部分字节后
进程死亡”或“崩溃后工件变化”。

影响：Plan 008 的“原子结果归档”和 WBS 的“原子归档已落地”不成立。正常无崩溃路径的 file lock、fsync、
staging/rename 设计仍有价值，但不能把它外推到 crash consistency。

### F-06：llama.cpp 的 runtime pin 只覆盖动态启动壳，不覆盖实际执行闭包

证据：

- `eval/locks/llama-cpp-b10333.json` 与 `launcher.py:83-134` 只校验 `llama-server` 单文件 SHA 和版本输出；
- 现场 `llama-server` 约 18KB，ELF `NEEDED libllama-server-impl.so` 且 `RUNPATH=$ORIGIN`，随后加载多份
  `libllama*` / `libggml*` 共享库；
- `launcher.py:360-370` 的所谓 sanitized environment 还保留 `LD_LIBRARY_PATH`。

替换同目录共享库或通过 `LD_LIBRARY_PATH` 注入兼容库，可以保持启动壳 SHA 和预期 `--version` 文本，
却改变 HTTP/路由/推理逻辑。当前 archive SHA 和启动壳 SHA 确实匹配 lock；问题是 pin 的覆盖范围不足。

影响：当前最多能称“b10333 launcher executable 已校验”，不能称“llama.cpp runtime 已完整冻结”。
真实 L2 前至少要关闭环境注入并绑定实际动态依赖闭包，或使用真正可独立验证的静态/完整目录产物。

### F-07：LocalApprovalClient 会跟随跨端点 redirect，可能泄露 bearer 并接受非本地审批

证据：

- `local_approval/client.py:84-110` 只验证初始 base URL 是 loopback；
- `client.py:222-245` 使用默认 `urllib.request.urlopen()`；当前 Python 标准库对 POST 的 301/302/303 默认
  跟随 redirect，并复制除 content headers 外的原请求 headers，包括 `Authorization`。

如果本地端口被错误服务占用或服务返回外部 `Location`，`RONDO_LOCAL_MODEL_API_KEY` 可被发送到非 loopback
地址，且远端结果可进入审批解析。client 也不核对 response model/服务身份。此问题不依赖下载模型，属于当前
client 的信任边界缺口。

## 4. 中严重度问题

### F-08：三次 claimed 诊断在结果索引与永久账本之间形成状态分裂

证据：

- `doc/eval-data-layout.md:70-72,115-118,152-160` 在三次诊断前已经规定 `runs.jsonl` 只追加、永久、
  claim 后异常也写分类失败行；
- commit `d72c222` 通过当时的 production publisher 向 tracked `runs.jsonl` 加入 3 条 schema-v1 行，
  commit `127f6b0` 在 feature branch 收束时删除这 3 行；
- 当前账本仍保留 r1/r2/r3 三个不可复用槽位，但 index 为 0 行，结果史与预算史没有一一对应；
- 已发布 `eval-data/runs/<run_id>` 目录已删除，三个 `eval-data/work/*-tb-codex-r{1,2,3}` 现场仍保留。

本项不应定性为“已发布 main 的正式结果数据丢失”：三行从未进入合并后的 main，均为 API 前、零请求、零费用，
Git 对象和 work/ledger 证据仍可达。原三行又把设施错误错误归为 `agent_failed`，不应为了字面 append-only 原样恢复。

准确问题是一次 **pre-merge provisional dataset reset 与最终 claim 合同不一致**。合理处理是显式的一次性迁移：
证据足够时用保留现场重建三条正确的 `infra_failed` 诊断终态；证据不足时增加轻量的 attempt/correction 记录，
使每个永久预算 claim 都有可解释终态。今后若需纠正已经发布到正式 main 的行，应使用 append-only correction/
tombstone 或版本化数据集边界，而不是删除或覆盖历史行。

原用户转述中的“旧 raw run 目录全部删除”也需收窄为“发布目录和索引删除，work staging 保留”。本项降为
中低严重度的迁移/治理问题，不再作为独立 High 验收阻断。

### F-09：L1 对合法 evidence 的可消费性和最终出站门禁不完整

- 冻结协议 `mydev/codex-rs/protocol/src/models.rs:963-974` 的合法 `ToolSearchOutput` 本身含 `tools` 证据字段；
  `evidence.py:174-190` 会保留它，但 `local_approval/client.py:291-299` 递归拒绝任意层级的 `tools` key。
  因而包含 tool-search 历史的真实 `E_final` 无法进入 Local-static。硬约束禁止的是顶层工具授权和 Lite
  `additional_tools`，不是丢弃既有工具搜索结果。
- `evidence.py:161-171` 没验证 Lite policy item 自身 `type == "message"`；带 developer role/content 的
  malformed item 可被当作 known/aggregatable policy。
- `LocalApprovalClient.build_request()` 最终边界只拒绝 `tools`/`additional_tools`。调用者若构造 canonical
  自洽的 `StaticApprovalPayload`，仍可夹带 `encrypted_function_args` 或
  `internal_chat_message_metadata_passthrough.executed_tool_calls`；正常 builder 会删除，但最终 sink 未独立 fail-closed。
- 现有测试只证明 Standard/Lite 经同一 builder 得到相同 bytes；没有 Luna、Sol、Local 三条真实消费者路径。
  因此“共同 provider-neutral payload 协议已实现”成立，“三消费者逐字节验收完成”不成立。

### F-10：本地模型、服务和 launcher 之间没有身份绑定

- model path 只检查普通文件和 `.gguf` 后缀，不检查 GGUF 结构、digest、size 或稳定 inode；
- model 存在时 doctor 直接探测配置端口，未证明端口属于本次已校验 launcher，也未通过 `/props` 等核对
  build/model/path identity；
- client 只检查 200、completed envelope 和 allow/deny schema，不核对 response model。

因此“任意 `.gguf` 后缀文件 + 同端口任意 schema responder”可以让 doctor 返回 ready。当前配置的
`model_path` 为空，`infrastructure_ready_model_missing`/78 本身没有被此问题推翻；这是未来真实 L2 的阻断前置。

### F-11：结果 schema/状态交叉约束不足，会生成自相矛盾统计

- `artifacts.py:404-434` 对 config/summary/tasks/metrics 只做大类类型和非空检查，未实现文档展示的
  track-specific task schema。当前 P1 正式 CLI 只通过固定 producer 构造 record，不能从命令行注入
  `{"forged": true}`；因此这是共享 schema owner 与 producer 之间未封装的不变量，不是当前生产伪造路径。
  合适修法是增加 track-specific validator/constructor，而不是把所有未来 track 规则塞进通用文件 I/O。
- `terminal_bench/results.py:189-236,529-553` 可在顶层 `infra_failed`/errored 时仍按 reward 写
  `success_rate=1.0` 和 task pass；这是当前正式 producer 可达的自相矛盾状态，只消费 summary 的下游会
  把基础设施失败当成功；
- ordinary `publish_terminal_bench_result()` 的非 completed 路径在 metadata 已存在时仍返回空 roles
  （`:700-723`），导致 tracked summary 少报 agent failure 前已经发生的 main/Guardian 请求；原始
  `api-metadata.json` 仍会归档。claimed-exception 的 `publish_terminal_bench_failure()` 已正确读取并统计
  verified roles，不受此问题影响；
- completed TB 一律要求非空 `tasks`，与 holdout `tasks=null` 规则冲突，但 holdout 属后续 L3/L4/B4，
  不是当前固定 `fix-git` P1/B2 的阻断；应作为未来 track validator 的验收债务处理。

当前 P1 需要优先修复的是 `infra_failed + success_rate=1.0` 和 ordinary non-completed summary 少报 roles；
共享 schema 完整性与 holdout 分支按各自 producer/后续阶段收口。

### F-12：B3 的 S2 实证应与 Terminal-Bench M1 分开验收

`terminal_bench/results.py:700-714` 对 RONDO 只要求“是否观察到 Guardian request”与“是否有任意 evidence”
两个布尔值相等；已有 evidence 也没有与 proxy request id、request body hash/response id 一对一绑定。这种布尔
关联不足以验收 S2/真实 `E_final` 的轮次归属。

但 M1 的定义只是同一 Terminal-Bench task 两侧真实 `completed` 且可归档；若某次正常 run 没有进入 Guardian
send point，Guardian request 与 evidence 同为零是正确语义，不应让 `fix-git` 因未触发审批而失败。两侧 completed
可以满足 M1，但不能同时证明 B3 的独立 S2 子目标已经通过。

合理修法是拆开两个验收结果：M1 由公平 pair aggregator 判定；S2/真实审批链另用一个可确定触发审批的 fixture
或独立实证，并在发生 Guardian 请求时建立 request 与 `E_final` 的一对一关联。不能把“每条 RONDO run 必须出现
Guardian”设为 M1 条件。

### F-13：Docker 阻断现象真实，但 builtin seccomp 的单一根因没有被证明

原始日志证明冻结 Codex 已到 bwrap，随后报：无法创建 namespace，当前环境不允许 unprivileged user namespaces。
root/non-root 路径都失败，能排除普通 UID/文件权限问题。

但 `docker info` 显示 builtin seccomp 只是相关事实；现有证据没有隔离 userns sysctl、capability、Docker daemon
namespace 配置和其他安全策略，也没有安全的 syscall-level 归因。未通过 `seccomp=unconfined`、`SYS_ADMIN` 或
privileged 做反事实试验是正确决定。

严谨表述应为：**当前默认 Docker 安全环境阻断嵌套 user namespace，builtin seccomp 是合理嫌疑之一，精确根因
未确认。** 同一 bwrap/runtime 对 RONDO 很可能同样失败，但 RONDO 完整 no-API path 并未实际运行，仍属于推断。

### F-15：容器清理不覆盖完整 Compose 资源/进程树

异常清理只处理已观察到的 exact-label 容器 ID，未覆盖 Compose network/volume；host runner 只 terminate/kill
直接 Harbor Popen，没有独立 process group。父进程退出后若子进程延迟创建容器/网络/卷，supervisor 可能已完成
最终“零容器”检查。外层 cgroup 残留进程清理能缓解宿主进程问题，但没有验证 Compose network/volume。

当前既有运行没有发现容器泄漏，本项是生命周期完整性缺口，不代表存在来源不明对象可由本任务清理。

### F-16：B3/M1 前要求的最小逐 run 外部指标尚未实现

Plan 008:7-9 明确继承 Plan 003 的 B1～B3 约束；Plan 003:35-41 要求每条 P1/B3 run 记录 task outcome、
基础 attribution、wall/CPU/peak RSS、可取得的 token/cost、artifact 路径并区分退出状态。

当前实现已经记录 duration、token、cost、artifact 和粗粒度 `agent|infra` attribution，但 `metrics=null`，
没有统一的进程外 wall/CPU time/peak RSS；现有 trial duration 不能替代双侧一致的 runner 外部采集。
它是 B3/M1 宣告完成前的验收缺口。

边界需要保持克制：完整计分和系统化 Guardian 归因仍属于 B5，完整探针体系仍属于 A4；本项只要求继承合同中
最小、双侧一致的逐 run 外部 wall/CPU/RSS 与基础归因。当前 B3/M1 本来就未通过，因此这不构成已有结果造假，
也不否定 B1/B2 已落地的基础设施代码。若决定延期，应正式修订 Plan 008，不能仅以 WBS 的后续阶段安排隐式覆盖。

## 5. 低严重度与后续阶段债务

### F-14：配置 provenance/读取竞态仅作为低风险加固；optional local key 不是缺陷

- `RuntimeConfig.data` 是可变 dict，理论上可在加载后突变而保留旧 `source_sha256`；但生产代码没有修改该
  dict，也没有把引用交给不受控插件。它是冻结投影未由类型完全保证的低风险 API 加固，不是当前真实 run 的
  自然错误路径。
- `.env.local`、`rondo.local.toml` 和 allowlist 的检查、stat、读取分多次解析路径，技术上存在同 UID 替换
  窗口；同 UID 本身已有读写能力，在个人本地威胁模型下归为低风险 TOCTOU 加固。
- `RONDO_LOCAL_MODEL_API_KEY` 的权威语义是可选：loopback llama.cpp 未启用 `--api-key` 时不要求该变量，
  loader 返回 `None` 与 launcher/client 同步使用无鉴权模式是既定合同，不是静默降级缺陷。若未来需要强制
  鉴权，应新增明确的 `auth_required`/`api_key_enabled` 配置并同步模板和文档，不能直接改变现有缺值语义。

- `RunSpec.validate()` 对 timeout/retry 只比较大小；`bool`、`NaN`、`inf` 或极大值的类型/有限性/上界约束不完整。
- 结构化审批允许空 `rationale`，与“allow/deny + 理由”口径不完全一致，但不会改变 allow/deny outcome。
- `actual_usd` 与 `estimated_usd` 都由冻结价格快照和 API usage 本地计算；没有 invoice 查询。当前 0 请求时不影响
  数值，但未来非零结果里 `actual_usd` 字段名过强。
- proxy 在没有 `X-RONDO-Eval-Role` 时会按请求 shape 推断 main/guardian 并将其当 verified role；生产代码没有
  找到稳定注入该 header 的路径。实现和测试对此一致，但实施日志“unknown role 不成为 milestone evidence”的表述不实。
- ArtifactWriter 拒绝 symlink，但不拒绝同文件系统 hardlink；结果 index/lock 可被同 UID 预置 hardlink 后向仓库外
  inode 追加。task source digest 到 `copytree` 之间也有 TOCTOU。二者需要同 UID/并行修改能力，按个人仓库威胁模型
  归为纵深防御，不应压过已确认的公平与 crash-consistency 缺口。
- 顶层 eval 测试没有接入现有 `just`/统一测试入口。`eval/.venv` 按合同应 ignored，fresh main 需要先执行文档
  已写明的 `uv sync --frozen`；虚拟环境不入库本身不是缺陷。本审查为避免下载依赖，才复用了既有 worktree venv。

## 6. 独立验证结果

### 6.1 Git、账本与结果现场

- 审查开始时 `main == origin/main == HEAD == 19c650c3...`，主工作区 clean。
- `eval/results/runs.jsonl` 当前 0 行。
- `eval-data/budgets/p1-fix-git-20260810.json` mode `0600`，包含 3 个不可复用 Codex run；每个
  `requests={}`、`spent_usd=0.000000`、`stopped=false`，总 cap 20 USD，剩 1 个槽位。
- 三个 `eval-data/work/*-tb-codex-r{1,2,3}` 目录仍存在；已发布 `eval-data/runs/` 对应目录不在当前现场。
- 受跟踪 locks、现场 manifests 与实施日志记录的主要 SHA/commit/权限相互一致；本审查没有重新哈希两个约
  1.26GB CLI，也没有把 ignored manifest 的自洽误表述为运行前受跟踪的 pair/batch 门禁。

### 6.2 轻量测试

当前 main 没有 `eval/.venv`，故使用已完成 Plan 008 worktree 的现有 venv interpreter，对**当前 main 的
`eval/tests` 源码**运行测试。

第一次继承当前 shell 的 `HTTP_PROXY` 且 `NO_PROXY` 为空，完整套件为 182 项、1 项失败：无鉴权 loopback 请求
被环境代理污染并返回 502，而测试期望 401。该单项可稳定复现。显式设置
`NO_PROXY=127.0.0.1 no_proxy=127.0.0.1` 后，单项通过；在同一条件下完整结果为：

```text
Ran 182 tests in 15.209s
OK
```

因此执行者的“182/182 pure/fake/loopback 通过”可以复现，但测试入口对宿主代理环境不完全 hermetic，且依赖
另一个 worktree 的 ignored venv；这与“行为测试全绿”应分开记录。

另以离线临时 cache 运行 `uv lock --check`，通过（`Resolved 85 packages`）。没有下载依赖。

### 6.3 已确认的可靠实现点

- Standard/Lite 正常形态冲突、重复、错位会 fail-closed；policy 按原 UTF-8 bytes 哈希，不 trim/normalize；
- 常规 canonical JSON、provider-private metadata 清理、approval/retry reason 保留在已有 fixture 上正确；
- 配置按数据解析而非 shell source，未知/重复 key、直接 TOML secret、静态 symlink 和非 0600 secret 会拒绝；
- budget ledger 有进程级 flock，先 reserve 后 upstream，缺失/非法 usage 与 crash reservation 按 full cap 停止；
- upstream 只接受官方 OpenAI `/v1` 并禁 redirect；短期 downstream bearer 使用恒定时间比较；
- task checkout commit/scoped clean、task/archive/Packager digest、唯一 image tag→digest rewrite 和 overlay bytes
  复核较严；Harbor 命令固定 local path、telemetry off、单任务/单并发/零 retry；
- Docker image 使用 digest 或明确 local image ID；版本探针请求 network none/read-only root/read-only bind；
- bwrap 资产对 size/SHA/tar member/static ELF/mode/bundle allowlist 的校验扎实；
- 现有 no-API raw 错误来自真实冻结 Codex 的 bwrap 路径，不是 fake 测试伪造；
- 当前 WBS/实施日志对“B3/M1 未完成、无模型、无真实推理、未弱化安全边界”总体诚实。

## 7. 建议的修复/重新验收顺序

本日志不改代码，以下仅给出后续优先级：

1. 暂停消耗最后一个 API 槽位；当前 batch 已无法形成公平 pair，修复后应重新明确 batch/轮次/预算授权。
2. 先修结果库 crash consistency，并显式迁移三次 claimed 诊断：不原样恢复错误的 `agent_failed` 行，
   而是依据保留证据重建 `infra_failed` 终态或写 attempt/correction 记录，使永久账本与结果史重新对应。
3. 增加生产 pair/batch aggregator，机器约束 side/task/round/order/config/timeout/budget；同一受跟踪结构化
   manifest 绑定两侧 bundle digest/source identity 与 Harbor 实际安装身份，no-API 和 paid 共用 preflight。
   M1 只能由合规 pair 产生；B3 的 S2 实证另用可确定触发审批的 fixture，不把 Guardian 未触发当作 M1 失败。
4. B3 前补最小、双侧一致的 wall/CPU/peak RSS 与基础 attribution；若决定延期，先显式修订 Plan 008，
   完整计分/Guardian 归因和探针体系仍留给 B5/A4。
5. 收紧 Docker 有效态 inspect、至少观察一次任务容器、watchdog lock/limit proof 和 absolute-deadline 采样；
   之后在既有安全边界内重新做 no-API 双侧验收，再讨论 namespace 兼容路径。
6. 修复 L1 合法 `ToolSearchOutput`、policy discriminator 与最终 sink 禁止字段；分别走 Luna/Sol/Local consumer
   fixture，而不只比较同一 builder。
7. L2 在下载模型前先关闭 redirect/动态库注入、冻结完整 runtime 闭包并绑定 launcher↔endpoint↔model identity；
   权重、真实推理、显存/延迟和 L2a 仍需按原授权边界另行处理。
8. 最后修正 WBS/实施日志当前状态：保留真实通过项，撤回或收窄“原子归档完成”“L1 完成”“B2 代码完成”
   和“builtin seccomp 已确认为唯一根因”等表述。

在这些验收阻断项处理前，不建议把当前实现作为可用于付费对比、里程碑聚合或本地安全审批的已完成设施。

## 8. 未验证与边界

- 未运行 Docker，因此没有取得当前 daemon 的实时 inspect、seccomp syscall 或 storage counterfactual；
- 未运行 Cargo/链接，未重做两侧静态 musl build；
- 未启动 llama.cpp server/模型，未验证 b10333 的真实 `response_format`、上下文、GPU offload 和延迟；
- 未发出真实 OpenAI 请求，未查询供应商账单；
- 未做 kill -9、断电、并发目录替换、hardlink 或外部 redirect 的动态破坏实验；相关结论来自明确控制流、
  系统调用/标准库语义与现有负向测试缺口；
- 未读取 `.env.local` 内容，也未读取其他 worktree 的用户日志或修改其状态。

本次唯一新增文件为本审查日志；其余项目状态保持不变。
