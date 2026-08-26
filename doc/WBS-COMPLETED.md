# RONDO 已完成阶段与成果

本文件按时间顺序追加记录已完成的开发阶段、成果与验收证据，作为历史参考。
当前阶段见 `doc/WBS.md`，单次任务的技术方案见 `plan/`，执行细节见 `agent_log/`。

## P0 共享地基（Codex `v0.146.1`，2026-08-07）

方案：`plan/001-p0-guardian-override-and-evidence.md`；日志：`agent_log/2026-08-07-233100-p0-guardian-override-and-evidence.md`。

方向 0（测评基准）与方向 2（本地审批模型）共用的两块地基落地，两条线可并行开工。

### S1 审批模型显式覆盖

`config.toml` 的 `[auto_review]` 新增 `model` 与 `reasoning_effort`：

- model 优先级：`[auto_review].model` > `ModelInfo.auto_review_model_override` > provider 默认 `codex-auto-review`。
- effort：配置了就用配置值，没配置则完整保留原有的按模型能力推导结果。
- **能力边界**：只覆盖模型名与 effort，**不覆盖 provider**。Guardian 仍克隆父会话的 provider 与 base_url，
  因此可以把审批模型钉在同 provider 的其他模型（测评所需），但**不足以切到本地模型**——那需要独立的
  provider 覆盖，见方向 2 的 L2a。

验收：集成测试 `suite::auto_review::auto_review_config_overrides_guardian_model_and_reasoning_effort`
用 `config.toml` 配置 `model = "gpt-5.6-luna"` / `reasoning_effort = "high"`，断言 Guardian **出站请求体**
的 `model` 与 `reasoning.effort` 与配置一致。effort 特意取 `high` 而非 `low`：默认逻辑本就优先选 `low`，
断言 `low` 无法证明覆盖生效。上游回退路径由既有测试
`remote_model_override_uses_catalog_model_for_strict_auto_review` 保持通过。

### S2 审批证据包快照 `E_final`

`[auto_review].evidence_dir` 配置后，每轮审批产出
`<evidence_dir>/<review_id>/E_final.json` + `meta.json`（目录 `0700`、文件 `0600`，先写 `.tmp` 再 rename）。

- 挂钩点：`core/src/client.rs` 的 `ResponsesApiRequest` 组装完成处，1 行。
- 捕获资格：`matches!(request_kind, Some(Turn))` **且**该会话登记着已开启的审批轮槽（白名单，
  预热 / 压缩 / memory 一并排除）。
- 关联：槽以 guardian 会话 `thread_id` 登记，RAII guard 管生命周期，覆盖所有提前返回与超时路径；
  retry 取最后一次请求。
- 未到 transport send point 即结束的轮次只写 `meta.json` 并标 `evidence: none`，不拿陈旧请求充数。
- 规范化确定性且幂等：剥离 `client_metadata` / `prompt_cache_key` / `store` / `stream` /
  `stream_options` 与 `input` 项的 `id`；`call_id` 按出现顺序成对确定性重映射，工具调用与结果仍配对。
- 未配置时不产生任何文件，钩子首个判定无分配；写入失败只 warn，不影响审批决策与 fail-closed 语义。
- **不做内容级脱敏承诺**：`instructions` / `input` 承载任意任务上下文，证据包按原始会话记录对待，
  默认落 git-ignored 的 `/eval-data/`。外发给云端模型属数据外发，需单独授权。

验收：`guardian::evidence::tests` 6 项 + `suite::guardian_review` 新增 2 项，覆盖剥离清单、规范化幂等、
`call_id` 配对、并发不串档、非 `turn` 与未绑定会话不捕获、文件权限、一轮一包、主 Agent 不被捕获、
websocket 预热不产包。

### 通用验收

- `just fmt`、`just fix -p codex-core`、`just write-config-schema` 均已运行且干净；
  schema 差异只含 `AutoReviewToml` 三个新字段。
- 非测试、非生成物改动 426 行（104 行修改 + 322 行新模块），未超 500 行闸。
- 未引入新第三方依赖，`Cargo.toml` / `Cargo.lock` 未动。
- **以下门禁未运行，不声称通过**：全量 `just test`（workspace 级并发在本机 19GB 内存下有 OOM 风险，
  待受控并发下补跑）、Bazel 门禁与 `just argument-comment-lint`（本机未装 Bazel）。
- 全程离线：未调用真实模型 API、未拉 Docker 镜像、未外发任何证据包。

### 解锁

方向 0 的 P1（TB 2.1 最小真实链路，需 Docker + 小额真实 API 授权）、方向 2 的 L1 / L2。

## 构建资源闸门与全量测试补跑（Codex `v0.146.1`，2026-08-08）

### 资源闸门

全量测试触发 WSL2 全局 OOM（内核杀 `systemd`/`sd-pam`，连带 VS Code Remote 与所有 agent 会话）后，
落地四道闸门，细节见 `doc/development-environment.md` §3.5：

- 仓库根 `.cargo/config.toml`：`build.jobs = 6`（覆盖 mydev、tools、codex-source-code 与所有 worktree）。
- `.config/nextest.toml`：`[profile.default] test-threads = 10`。
- `mydev/scripts/with-build-lock.sh`：机器级 flock，同时只允许一个重量级构建。
- 同一脚本把构建放进 systemd 临时 scope，`MemoryMax=16G` / `MemorySwapMax=2G`——唯一不依赖估算的一道，
  超限只杀壳内，宿主与会话存活。

取值依据为实测：`jobs=8` 的完整 workspace 测试二进制构建峰值 18.7 GB（8 槽同时链接），
空载基线 4.8 GB，得 `峰值 ≈ 4.8 + 1.74 × jobs`。

后续追加一层跨入口兜底：仓库根启用 `.cargo/rustc-throttle.sh`，让裸 Cargo、不同 agent 与不同
worktree 的 rustc 共用 6 个机器级槽，并在可用内存过低时暂停新 rustc 准入。它不替代
`with-build-lock.sh` 的单构建互斥；两者分别约束“Cargo 构建数量”和“rustc 总并发”。

### 补跑 P0 遗留的全量 `just test`

上条 P0 记录中「待受控并发下补跑」的全量门禁已执行完毕（本条为追加，不修改上文历史记录）：

- **结果**：13135 项运行，13062 通过 / 73 失败 / 23 跳过 / 25 flaky，执行阶段 346.7 s。
- **资源**：全程已用内存约 3.8 GB、可用 24 GB，scope 内峰值约 5 GB，swap 未增长，**无 OOM、无退出码 137**。
  闸门在真实全量负载下有效。
- **73 项失败与本次并发改动无关**：`codex-tui` 以 `--test-threads 1` 串行重跑，失败项完全相同（33 项）。
- **73 项失败也不是 RONDO 回归**：`tui` / `network-proxy` / `mcp-server` / `exec` 仅被两次基线导入提交
  （`0fe9217`、`102ec27`）触碰过；P0 提交 `95d3358` 只改了 config / core-guardian / core-client。
  名字含 guardian / auto_review / evidence 的 36 项测试中 35 项通过，唯一一项失败是 tui 快照里的版本号字符串。
- **两个已证实的系统性根因**：
  1. **版本号占位（25 项）**：上游快照与断言内嵌 `0.0.0`，RONDO 把 132 个工作区包钉成 `0.146.1`，
     所有内嵌版本号的断言必然失败。
  2. **Clash Verge fake-IP DNS（11 项）**：宿主所有域名解析到 `198.18.x.x`（连 `.invalid` 都解析成功），
     codex 网络代理正确判定为私有地址并拒绝。已验证与 `http_proxy` 等环境变量无关，去掉后仍失败。
- 其余 37 项为本地 mock 服务/超时（8）、其他快照差异（12）、其他（17），未逐项定位，
  按本次任务范围不做修复。
- **仍未运行**：Bazel 门禁与 `just argument-comment-lint`（本机未装 Bazel）。

## Codex 0.147.0 基线导入与 P0 兼容适配（2026-08-08）

日志：`agent_log/2026-08-08-212134-codex-0.147.0-upstream-baseline.md`、
`agent_log/2026-08-08-221708-codex-0.147.0-p0-acceptance.md`、
`agent_log/2026-08-08-233753-p0-strict-acceptance.md`。

只读标准快照 `codex-source-code/` 固定在官方 `rust-v0.147.0`（commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`），detached HEAD、工作区干净。产品树基线导入提交为
`1001929`；只把官方 `Cargo.lock` 中 135 个本地 workspace package 的发布占位值 `0.0.0` 机械
规范化为 `0.147.0`，相对官方 lock 没有其他产品侧改写。上游本身同时带来三个 workspace member
以及 `Cargo.lock`、`MODULE.bazel.lock`、`pnpm-lock.yaml` 的依赖图更新。

隔离 scratch 上完成原始上游冷构建与全量测试：14,065 项运行，13,981 通过 / 83 失败 / 1 超时 /
23 跳过，31 项首轮失败后重试通过。该结果只证明官方上游基线与当前工具链，不是 RONDO P0 验收。

### P0 兼容适配

- S1 出站测试改用非默认的 `gpt-5.5/high`。0.147 的 OpenAI API-key Guardian 默认本来就是
  Luna；继续用 Luna 断言 model 会让 override 失效时也可能误绿。正式测评仍显式钉
  `gpt-5.6-luna/low`。
- `E_final` 保留标准 Responses 与 Responses Lite 的完整逻辑请求形态；后者把 policy 放在
  `input` developer item，而不是顶层 `instructions`。
- 规范化剥离新增的 `FunctionCall.encrypted_function_args` provider-private 运输字段，继续保留并
  成对重映射 `call_id`，保证工具调用/结果关联。
- P0 仍只覆盖 model/effort，不覆盖 provider；L2a 的前置关系不变。

### 已完成验收

- 格式、fix、schema 门禁通过；P0 精确回归 8/8、Guardian/auto-review 10/10、config/schema 6/6
  通过；`codex-core` 冷编译通过。
- 全量 nextest 完整执行：14,074 run，13,998 passed / 74 failed / 2 timed out / 23 skipped。
  全量**不声称通过**；76 项终态未通过的完整清单、错误内容和与纯上游参照的差集见验收日志。
- 76 项中没有 Guardian evidence / model-effort override 的终态回归。唯一 Guardian/MCP 慢测在
  全量并发中两轮超时，恢复正式 `RUST_MIN_STACK` 后定向 1/1 通过（47.102 秒）。据此 P0 在
  `v0.147.0` 上的核心功能性定向验收通过。
- 未运行 Bazel 和 `just argument-comment-lint`；没有真实 API、Docker 或证据外发。

004 独立方案提出的两个产品边界已补强：permission hook 提前 resolve 不产证据有直接集成测试；
关闭 evidence 时捕获路径只做一次原子读取，不进入全局表、不分配、不序列化；写失败不影响审批也有
直接回归。新增精确测试 3/3 通过，完整 workspace 执行 14,077 项，13,996 通过 / 81 失败 /
23 跳过 / 27 flaky，失败中没有 P0 路径。字面 `just test -p codex-core` 经诊断会因 package-only
缺少 workspace helper binaries 与项目内 `TMPDIR` 污染 fixture 产生 216 项基础设施失败，故不作为
必须全绿的 hermetic 门禁；以 P0 精确边界加完整 workspace 结果替代。**P0 严格验收完成。**

### 2026-08-09 独立复验更正

后续独立审查证明上面的“严格验收完成”遗漏了三个真实缺口，不能继续原样作为当前结论：共享 builder
中的捕获早于 WebSocket 建连；全树递归 `call_id` 规范化可能误改工具 schema/元数据里的同名业务字段；
passthrough `turn_id` 未规范化。修复把 HTTP/WS 捕获点后移到 transport send 前，同时仍保存可离线复用
的完整逻辑请求；`call_id`/`turn_id` 只在 input item 的明确结构位置成对重映射，并增加
`guardian_source_baseline`。预取消且未到 send point 的已建轮只写 `meta.json`/`evidence:none`；
到达 send point 后即使发送/流读取失败或超时仍可保留该次尝试的 `E_final`。builder 不提前提交和
standard/Lite 形态均补回归。

规范化承诺同时收窄到真实边界：同一份已构造请求重复规范化字节一致；两个新会话的自由文本仍可能含
不同父会话 id，整包不保证跨运行字节相同。P1 的 seed/holdout 分桶必须继续使用规范化待审批动作指纹，
不得改用整份 `E_final` 哈希。Unix/WSL 权限为目录 `0700`、文件 `0600`；Windows 只承诺继承配置目录 ACL。
本轮 schema、fmt、clippy 与精确选择的 16 项回归均在项目看门狗下通过；这是 P0 定向功能验收，
不把历史 workspace 的 81 项失败改写成全绿。完整门禁与复验结论见
`agent_log/2026-08-09-020200-baseline-p0-test-audit.md`。

### 构建资源设施与实测

- `with-build-lock.sh` 固化为 fail-closed 的单构建 + systemd cgroup + 磁盘/内存/swap/PSI 实时
  看门狗。项目告警/主动停/绝对停为 180/195/200GB；内存为 `MemoryHigh=19G`、
  `MemoryMax=21G`、`MemorySwapMax=5G`。
- RONDO 完整运行的 target 历史峰值约 126.0GB；cgroup 总内存峰值约 20.4GB，其中匿名+内核
  不可回收最高约 12.2GB，swap 最高约 0.39GB；未触发资源停机。
- 一个网络迁移测试超时后留下 366 个 scope 内后代进程。已精确冻结/清理该 scope，并给看门狗增加
  主命令退出后的 5 秒残留清理；合成后台进程场景验证通过。

### 2026-08-09 看门狗与第一批测试维护收口

- scope存活判据改为cgroup v2 `cgroup.events: populated`，JUnit由Nextest直接写入逐轮独占目录并在
  summary中记录状态、路径与SHA-256；基线tag与peeled commit由受Git跟踪的manifest统一提供。
- user D-Bus终止请求失败时，先写 `cgroup.kill`；不可用时递归枚举子cgroup，并在发SIGKILL前重新核对
  每个PID的cgroup成员关系。未知状态继续监督，不把终止失败当作已退出。
- 第一批测试维护实际覆盖42个历史失败名；严格失败清单剩39项，migration与OAuth是2个附加设施事项。
  最终实施合同见 `plan/004-remaining-test-failures-investigation.md`，本批未实施39+2。
- 独立复验补跑三个受影响包：3,630项运行且全部通过，三包clippy退出0、零warning。收尾补丁另通过
  44项脚本测试（其中9项为看门狗helper）及1项skills定向Nextest；该轮JUnit为1项通过、SHA与summary一致，
  `stop_reason=none`、`cleanup_reason=none`。未重跑完整workspace或Bazel。

### 2026-08-09 Plan 004 当前平台实现与独立整改交付

- 39个严格失败合同与J/K两个附加设施事项已完成当前平台实现；独立验收识别的D/H假绿、K透传覆盖缺口和
  G非Unicode边界已完成窄整改。整改门禁共409 testcase、0 failure/error/skip，H两组压力各200/200，
  五个受影响crate严格clippy与统一fmt-check通过。
- 原实现提交 `216ccb7` 经 `06b2a0e` 合入主线；独立整改提交 `9570874` 经 `8c185af` 合入并推送远端。
  详细证据、逐份JUnit哈希与决策见 `agent_log/2026-08-09-203209-plan-004-independent-acceptance.md`。
- 本阶段只完成当前目标环境可执行部分，Plan 004整体仍为部分通过：Windows PowerShell正向合同未运行；V8
  `sandbox=true` canary与完整workspace在测试前被官方预编译资产404阻断。macOS Seatbelt入口保留但未实机运行，
  作为非阻断跨平台证据缺口披露。

### 2026-08-09 V8 sandbox本地资产门禁补验

- 新增显式`test-with-codex-v8`薄入口，复用既有OpenAI release下载、两行manifest和archive/binding双SHA校验，
  继续经build lock/watchdog执行；不新增V8构建体系，不使用`V8_FROM_SOURCE`。
- V8 v150.4.0 `x86_64-unknown-linux-gnu` sandbox=true canary 1/1与真实Code Mode host smoke 1/1通过，
  JUnit均为0 failure/error/skip；此前官方资产404阻断已解除，无需修改V8或Code Mode Rust代码。
- 完整workspace实际运行14,092项：14,060通过、31失败、1超时、23显式ignored。V8 POC 7/7与Code Mode
  专属crate 167/167通过；全量不称绿色，32项终态失败另列维护，Windows目标平台仍待补验。完整证据见
  `agent_log/2026-08-09-224108-v8-sandbox-local-gate.md`。

## Plan 008 P1 测评与本地审批前置设施（2026-08-10）

- 建立顶层轻量 `eval/` 项目，统一 Standard/Responses Lite `E_final`、`PolicyIdentity`、
  无工具静态审批 payload、严格 common-root 配置/密钥加载、结果归档、持久预算和退出码。
- 完成 Terminal-Bench B1 版本/任务/镜像冻结与 B2 统一 runner、Codex/RONDO 双 adapter、
  Harbor 生产 backend、Docker 实时资源监督、去敏预算代理和静态 musl runtime bundle。
  官方 hello-world oracle Docker smoke 与两侧镜像内 `--version` 探针通过；B2 全链路 no-API
  验收未通过，不列为完成阶段。
- 完成方向 2 的 L1 协议/测试，以及 L2 的 llama.cpp `b10333` 项目局部运行时、
  client、doctor、fake server、结构化输出校验和启动入口。无模型 doctor 返回
  `infrastructure_ready_model_missing`/78，未下载权重或进行真实推理。
- 轻量设施门禁 182/182 通过，`uv lock --check` 通过；所有 Cargo、Docker、运行时下载与
  重型清理均在项目看门狗下串行，废弃 target/scratch/libcap 产物已精确清理。
- **本条不宣称 P1/M1 完成**：完整 Codex Docker no-API agent 路径被 builtin seccomp 下的
  嵌套 user namespace 拒绝，未通过弱化 seccomp/capability 换取绿色。三次 API 前设施诊断
  已从正式结果库移除，预算槽位仍不可复用；真实 API 调用 0 次、实际费用 0 USD；B3/M1、L2 真模型、L2a/L3/L4、
  训练和 canary 保持未完成。详细证据见同日 P1 `agent_log`。

### 2026-08-10 Plan 008 独立审查整改与 B2 no-API 验收

- 按独立审查收口公平 pair/Harbor closure preflight、Docker daemon 有效态、规范 flock/cgroup 证明、
  绝对 deadline、Compose 全资源清理、runner-host 设施指标、结果交叉约束与 crash-consistent journal v2；
  三次零请求诊断以一次性迁移恢复为 `infra_failed` 永久终态。容器 CPU/峰值内存仍是 paid B3 启用前门禁。
- L1 补齐合法 `ToolSearchOutput`、Lite discriminator、最终 sink 与 Luna/Sol/Local 三组协议逐字节 fixture；
  L2 lock 扩为完整动态运行闭包并关闭 redirect/`LD_LIBRARY_PATH` 注入，绑定 endpoint/model identity。
- 固定镜像内反事实确认 builtin seccomp 是 bwrap user namespace 阻断原因；受跟踪 profile 仅放开
  non-`CAP_SYS_ADMIN` bwrap 所需 syscall，未使用 privileged、`SYS_ADMIN` 或 `seccomp=unconfined`。
  随后 `fix-git` 的 RONDO→Codex no-API 配对 v3 两侧均 completed，fake 请求各 2 次、任务残留 0。
- 最终轻量设施门禁 237/237、`uv lock --check` 85 packages；无模型 doctor 为
  `infrastructure_ready_model_missing`/78。本批没有 Cargo、真实 API、权重或真实推理；B3/M1、L2 真模型、
  L2a/L3/L4、训练和 canary 继续保持未完成。

### 2026-08-10 Plan 008 第二轮审查后的机器合同加固

- 第二轮独立审查证明上述 B2 “完整验收”口径过强：旧 no-API v3 确实是旧
  lock/schema 下的双侧正常路径证据，但当时未绑定 pair 原子更新、跨槽 harness commit、
  VHDX 增长、daemon actual image、container metrics 和 M1 durable ledger。新 identity 推进为
  `p1-fix-git-pair-v4`；历史 v3 ledger 保留原身份，不复用或冒充新 schema 的 Docker 验收。
- 机器合同已增加 stable sidecar pair lock + atomic replace、harness commit 绑定、paid
  `publishing`→record digest→`completed` 恢复状态机、M1 对 result/ledger 联合核对、去敏 no-API
  safe summary、Harbor console/package/传递依赖闭包、watchdog override/VHDX/image/container metrics、
  paid custom seccomp、declared request role 和 `actual_usd` 未知口径。migration apply 也在分类前先恢复
  journal v2。
- L2 状态收窄为 CPU x64 frontend/runtime closure；model-backed client 强制重验 launcher 实例
  receipt，但 GPU runtime、真模型服务和结构化推理仍未实现验收。本轮只做 pure/fake/
  loopback 验证，统一轻量门禁 269/269，`uv lock --check` 为 85 packages。未运行 Docker、
  Cargo、真实 API 或模型；B2 新门禁待 Docker 重验，B3/M1 保持 hard-disabled/未运行。

### 2026-08-10 Plan 009 B2 轻量 no-API Docker 验收

- 删除 no-API permanent ledger、retirement、失败摘要恢复和 Harbor 全依赖闭包，保留一个可重跑的
  RONDO→Codex 串行入口、一个 current receipt 和 Docker supervisor 唯一事实源。
- 在 clean commit `b47a7b4` 上使用已存在的 pinned `fix-git` image 完成双侧真实 Docker
  no-API 链路；两侧均 completed、tool round-trip 成功、cleanup verified empty，官方 API 0 次、
  费用 0 USD。看门狗、VHDX、容器资源与精确清理证据见本批执行日志。
- 该验收只证明 B2 设施链路；`reward=0` 不是真实任务成绩。B3/M1 、真实 API 与 L2 model-backed
  仍未运行。

### 2026-08-11 Plan 013 配置化 Provider/Model 与未计费重试

- paid eval 的 provider、HTTPS base URL、main/Guardian model、reasoning effort、Standard 价卡和重试策略已从
  生产代码固定值迁移到 ignored `rondo.local.toml` profile；active provider/main/Guardian 三个短字段可独立切换。
  价卡同时包含基础费率、长上下文 threshold/multipliers 和 cache-write multiplier，并进入 canonical profile SHA。
- 宿主 loopback proxy 对 main/Guardian 的每个 downstream Responses 请求执行最多 5 个 upstream attempts；只有
  profile allowlist 中完整、规范、无 terminal/usage 的非 2xx 才按 operator-confirmed-unbilled 重试。全部 attempts
  共用单 reservation；模糊 transport/响应失败仍一次即停并保守结算，crash recovery 不自动重发。
- 复用既有 active key 的有界真实探针中，v2 Sol main 首次 completed、usage valid，本地价卡估算 `$0.022105`；
  Sol Guardian 首次 HTTP 502 无法确认未计费，未重试并保守结算 `$4.977895`。加上 v1 沙箱失败的本地保守
  `$5.000000`，Plan 013 ledger 合计达到授权上限 10 USD；供应商实际账单未查询，`actual_usd=null`。
- `just eval-lock` 解析 85 packages；纯/fake/loopback 完整 eval 293/293 通过。没有运行 Docker、Cargo、B3、Codex
  paid slot 或 M1。旧 v8 保持 failed/blocked；下一阶段由 Plan 014 新建 identity，并先解决 charged Guardian
  parse retry 与 requested/effective 双侧公平门禁。

### 2026-08-11 配置化 Provider 的真实 CLI 诊断

- synthetic probe 已与真实 Codex/RONDO 请求对齐：`store=false`、Guardian `codex_output_schema`/
  `strict=false`；项目私有 role header 只在 loopback proxy 内校验，不再转发给上游。
- 新增去敏、有界 CLI 诊断入口。真实证据确认冻结 Codex 与 RONDO 的 Luna main/Guardian 均可完成；仅运行
  RONDO 的 Sol main + Sol/low Guardian 也在 4 次重试后完成 `main → guardian → main`、命令和最终消息闭环。
- 同批早期仍观察到 Terra 403、Sol 429、Luna 503 与缺 usage；一次成功不作为 provider 稳定或 B3/M1 通过证据。
  三笔独立授权的本地保守借记合计 `790.856957` USD，分别未超过 300/300/600 USD；实际账单未知。
- 冻结 Codex 通过与 bundle source commit 一致的最小 `model_catalog_json`，把 Sol 条目的
  `auto_review_model_override` 设为 Sol；RONDO 使用自身 `[auto_review]`，无需修改冻结源码。随后 3 轮双端
  Sol/Sol 零重试短测连续完成，24/24 个 upstream request 一次成功且 usage valid，两端审批均闭合为
  `main → guardian → main`；本地价卡估算合计 `1.234473` USD，`actual_usd=null`。
- 短测按每个 upstream request 预留 1 USD，正式/大请求继续按 5 USD；定向本地回环验收 62/62 通过，独立
  ledger 5/5 通过。没有 Docker、Cargo、paid pair、M1、合并或推送。

### 2026-08-11 Plan 014 正式链路审查修复

- proxy shutdown 与 handler 生命周期统一：close 先与 paid forward 起点线性化，再等待全部非 daemon handler
  结算退出；confirmed-unbilled retry 在关闭后不再产生下一次 upstream 请求。
- `main_reasoning_effort` 进入本地 profile、canonical SHA、RunSpec、Terminal-Bench adapter、proxy 请求校验和
  public result；completed/publication/M1 均要求精确 `main → guardian → main`，RONDO 另要求一份 Guardian evidence。
- M1 改为消费去敏 public provider schema，不再要求已移除的 key env；新增真实 public producer→双侧 record→
  pair ledger→M1 集成回归，避免手写旧 schema 掩盖 producer/consumer 断裂。
- CLI 诊断以环境白名单启动子进程，精确校验请求顺序/数量/usage/settlement、未停止 ledger、唯一最终消息、
  固定审批命令的 started/completed/exit-code 与先后顺序，以及唯一成功 turn 终态；单次 proxy attempts 按剩余
  campaign retry 配额缩小。
- `just eval-lock` 解析 85 packages；纯/fake/loopback 完整 eval 323/323 通过。没有运行真实 API、Docker、Cargo、
  paid pair 或 M1；新 pair identity/profile drift 仍是正式付费运行前置条件。

### 2026-08-11 Plan 014 新 Pair Identity 与 Profile Drift 离线门禁

- 新增 schema-v2 lock，唯一冻结 v9 pair、b4 batch、两侧 run ID、Sol/medium main、Sol/low Guardian、价卡/retry、
  单侧 5 USD/pair 10 USD 与 frozen Codex catalog source/SHA；tracked lock/result 不保存 raw endpoint、display 或 key env。
- sequence ledger v5 在 slot 1 claim 绑定 selected profile/endpoint SHA，并在 completed 发布前、durable publication
  收口和 slot 2 claim 重验；旧 v8 仅允许显式只读加载，不能新建或 claim ledger。
- success/failure producer 使用 lock 的同一 public profile，M1 精确核对两侧 result、lock 与 ledger。focused 63/63、
  `just eval-lock` 85 packages、完整 eval 325/325 通过；未运行真实 API、Docker、Cargo、paid pair 或 M1。

### 2026-08-11 Plan 014 B3/M1 真实链路闭环

- 针对历史 paid 终态逐轮完成最小修复：Guardian transport/proxy 身份投影、并发 reservation、任务 Git identity、
  多个不同审批与同体 charged replay 门禁、E_final secret scanner 误报、Docker 完整 counter round 时限，以及
  cap-drop-all 容器中 0400 frozen catalog 的 owner 读取。所有旧 identity/result/ledger/artifact 与费用事实保持原样。
- v19 以唯一 schema-v2 lock 和新 pair/batch/run IDs 冻结 Sol/medium main、Sol/low Guardian、provider profile、
  endpoint hash、价卡/retry、catalog/bundle identity。fresh exact-wire canary 4/4 请求一次成功后，RONDO 与 frozen
  Codex 严格串行完成同一 `fix-git` task，分别 17/17 与 18/18 upstream request attempt 1、usage valid；双侧均
  `completed`/reward 1、run 未停止、reservation 0。
- RONDO 归档两份自然 Sol/low Guardian `E_final/meta`，均 approved；v19 的不可改写旧合同只能证明
  task-scoped request/evidence count match，后续合同才要求 canonical digest 一一绑定。
  durable public result、pair lock、sequence ledger、profile/endpoint 和 container metrics 经生产 `assess_m1` 得到
  `m1=passed`、`reasons=[]`、`s2=task_scoped_count_match`。
- v19 正式 pair 本地估算 `$0.870787`；Plan 014 全阶段累计 `$6.988825 < $280`，无悬挂 reservation，供应商账单
  未查询且 `actual_usd=null`。focused 155/155、`just eval-lock` 85 packages、完整 eval 345/345 通过；Docker/watchdog
  最终 `stop=none`、`cleanup=none`，0 containers/volumes。

### 2026-08-12 Plan 016 本地审批 model-free launcher 与 CUDA 构建前交接

- 依据 llama.cpp `b10333` 精确源码补齐两阶段服务合同：4k 使用原生 `gpu-layers=auto`/fit on，8k baseline 使用
  all/fit off；两者固定 512/256 batch、F16 K/V、parallel 1、flash on、no-mmproj、单卡 split/main GPU、offline/
  loopback/no UI/no autoload。配置拒绝未知/缺失/错误类型、bool 整数、越界与任意额外 CLI 透传。
- 冻结 `mistralai/Ministral-3-8B-Instruct-2512@5b26027…` 的 11,912-byte 官方模板，SHA-256 `74eeb55f…`；
  launcher 以 exact lock、允许目录、普通非 symlink 文件、size/SHA 验证后显式传 `--jinja --chat-template-file`，
  不回退 GGUF 内嵌旧模板。现有 b10333 CPU 工具的 parser/model-free 分析通过。
- launcher receipt 升级 schema v2；在既有进程/runtime/model/endpoint/实际 cmdline 验证外增加
  `serve_config_sha256`，由生成实际 argv 的同一构造器计算。客户端修改任一关键服务参数后不再接受旧 identity。
- focused fake/model-free unittest 80/80（45 + 8 + 27）通过，`git diff --check` 和模板/TOML/lock 一致性通过。
  本批未下载权重，未安装/构建 CUDA 或 llama.cpp，未运行模型/GPU/Docker/Cargo/Bazel/just；当前 CPU lock/capability
  不变，Plan 015 仍为 `download_ready_blocked_on_user_approval`。Linux CUDA build-ready 合同与三项汇合门见 Plan 016。

## L2a Guardian 独立 provider 覆盖（2026-08-12）

- `[auto_review].model_provider` 可从合并后的 provider registry 选择 Guardian 独立 provider；未知/空白 ID
  fail-closed，项目局部配置不能改变 provider 目的地。未配置时继续继承主 Agent provider。
- Guardian 使用完整 provider 配置并保持 request/stream retry `1/1`；显式无鉴权 provider 不继承主 Agent
  凭据，provider 鉴权继承策略进入 session 复用键。主 Agent provider 与现有 Guardian 安全收缩不变。
- 阶段 B 经资源门禁和仓库受锁入口完成 schema、clippy/fix、格式化、11 项 config/Guardian/schema 精确回归、
  sample crate 编译，以及 2 项非 skip loopback 出站验收。双 endpoint 分别精确收到主 Agent 2 请求与 Guardian
  1 请求，并验证 Guardian 独立 header/query/model/effort 与无主凭据泄漏。
- 该阶段只完成 provider 分流能力；没有加载本地模型、调用真实 provider、运行 Docker/GPU，也不宣称 L2
  model-backed 或 L7 一键切换完成。详细合同与证据见
  `plan/019-l2a-guardian-provider-override-execplan.md`。

### 2026-08-11 Plan 014 运行后预算与结果合同收口

- 保留 v19 双侧 completed/reward 1、M1 passed、35 次一次成功请求与 `$6.988825` 阶段费用事实，不修改任何历史
  lock/result/ledger/artifact；v8—v19 进入统一只读 registry，正式 paid 与 Plan 014 canary 当前无 active identity。
- 正式 proxy 默认按模型价卡的最大合法 usage 预留，Sol 当前上界 `$18.885000`；显式短测 overage 会保存完整估价、
  停止 run，ledger 只对精确 overage delta 放宽持久化校验。claim/reserve 原子化，handler 获得 lifecycle lock 后重算
  deadline，过期请求不会发往上游。
- completed/publication/M1 统一要求 budget run 未停止、无 reservation、全部请求 settled/usage valid/usage-priced，且
  budget request ID 与 API metadata 精确一致。后续 S2 以 canonical Guardian request 与 E_final digest 一一绑定；
  v19 不可回填的旧 evidence 诚实标为 `task_scoped_count_match`，M1 仍为 passed。
- Docker counter probe 返回前重验 lease；cleanup 的 counter、wait、terminate、kill、reap 共用 30 秒 absolute
  deadline。public evidence 路径指向实际归档，Guardian meta 拒绝矛盾组合，secret scanner 只在合法 schema 枚举
  位置接受 `user_authorization`。
- dependency lock 解析 85 packages；pure/fake/loopback 完整 eval 349/349 通过。本批未运行真实 API、Docker、Cargo，
  未读取密钥，也未改写真实结果。

### 2026-08-11 P2 B4/B5/B6 与 B7 执行设施

- 仅按 pinned TB 2.1 的 89 个 task ID 用无盐 SHA-256 先冻结 18 个 holdout，再从 71 个可见任务冻结
  10 canary / 61 validation；tracked catalog 绑定 canary 的 source digest、exact image、workdir、资源和三类 timeout。
- B5 机械计分覆盖 agent、Guardian correct/false deny 与 infra；未知 deny 保守归 false deny，technical Guardian
  failure 排除分母，holdout 只允许整批聚合。新 RONDO evidence 以 canonical request digest 一一绑定归档 `E_final`。
- B6 冻结独立 200 USD campaign、161 个一次性 slot、18.885 USD request reservation、40 USD run cap、唯一
  task/batch/run IDs 和 profile/catalog/bundle identity；usage、request/attempt 与费用可从预算/metadata 机械聚合。
- 通用 10-task materializer/runner、no-API oracle 前置、campaign 状态机、公开结果与 `just eval-b7-baseline`
  已接入既有设施。`just eval-lock` 85 packages、正式离线 unittest 379/379 通过；本条不声称 B7 真实基线已运行。

### 2026-08-12 Plan 020 B7 增量编排与恢复门禁

- v9 保持不可改写的 blocked 终态：Oracle 10/10 与 wire canary 有效，首个正式任务 reward 0、12 个请求全部
  settled；后继累计 debit 为 `282.287684 USD`，reservation 为 0。
- Oracle 改为 campaign-independent 单题 proof 与十题 manifest，按 task/source/image、verifier、共享执行组件、
  Harbor/TB、seccomp 和稳定 Docker 合同精确失效；campaign/profile/wire 不参与 proof identity。
- campaign coordinator 仅持轻量 lease，每个 Oracle/paid task 由独立 heavy-lock/watchdog worker 推进。已发布且
  budget 完整的中断 slot 可收敛，其他含糊状态阻断，不重复请求、结算或 run ID。
- active identity 统一由 tracked pointer 选择，v1—v9 只读 registry 与 161-slot 派生规则不变；生成器机械校验
  版本、ID、profile/bundle、terminal predecessor、prior debit 和 600 USD cap。
- focused 185/185、`just eval-lock` 85 packages、完整 eval 420/420 通过；本批未调用 API、Docker 或 Cargo。
- v10 后续按其原 161-slot/600 USD 合同自然 blocked：Oracle 10/10、wire canary与 13 个 paid run 全部保留，
  第三个不同 task 的 provider-response-integrity 触发全局熔断；累计 debit `343.896195 USD`、reservation 0。
- 后继 schema-v2 将 slot 机械扩为 321，冻结 700 USD 累计 cap，并新增 infra-only a1—a4、同类第二次 durable
  diagnosis hold、外部瞬态 resolution 与第三次 task-local 熔断；Docker counter 同时保留有界脱敏的 exit/stderr
  诊断，不放宽失败标准。完整 eval 430/430、lock 85 packages 通过；生成器随后冻结唯一 v11 identity，尚未执行。
- v11 的 diagnosis hold 阻止 filter a3：a1/a2 同为 Docker metric exec 128。独立 no-API Oracle 采样确认 Selenium
  多次达到 `256/256` PIDs，故 v11 以本地合同缺陷 blocked，累计 debit `345.963147 USD`、reservation 0；后继
  versioned catalog 仅将 filter PIDs 冻结为 512，历史 catalog/lock/result 不改写；v12 以唯一新 IDs 和精确 prior
  冻结，尚未执行。
- v12 完成 Oracle 10/10 与 fresh wire 后，在 filter a3 Docker failure 的失败发布处发现 producer 仍限 a1/a2；
  a3 已结算 `0.381782 USD` 但无 public record，恢复按 operator interruption 保守退役。累计 debit
  `385.923585 USD`、reservation 0。a1—a4 publication、pre-Oracle crash reconciliation 与 bounded stopped
  teardown 合同已进入离线回归；v12 无 512 PID 用尽证据，历史 v12 未回填。
- v13 的 Oracle 首次在 sqlite 官方 verifier 下载阶段超时且 API 为 0；增量恢复仅补齐该题并形成 10/10 proof。
  fresh wire 结算 `0.198335 USD` 后暴露 post-wire paid 分支不可达的本地控制流缺陷，320 个 paid slot 均未
  claim、paid ledger 未创建。v13 原子 blocked，累计 debit `386.121920 USD`；路由与退役原子性回归闭合后，
  v14 以全新 run base `20260812-340000000`、lock/IDs 和精确 prior 冻结。
- v14 的 filter a2/a3 在同类 Docker metric failure 后进入 diagnosis；512 PIDs 的 no-API Oracle 达到上限，
  v14 以 local implementation defect blocked，累计 debit `406.691123 USD`。v15 将 filter 提至 1024 PIDs，
  fresh wire 与四个 paid run 共结算 `1.870700 USD` 后再次在 a3 前停诊断。RCA 证明 1024 PIDs 的 reward 1 实为
  19/28 个 Selenium driver 创建失败，4096 PIDs 才完成 28/28；同时闭合 stopped-container inspect/remove 竞态。
  v15 blocked 后累计 debit `408.561823 USD`、reservation 0；v16 以 run base `20260812-360000000`、全新
  lock/IDs、filter 4096 PIDs 和精确 prior 冻结，v1—v15 保持只读。

### 2026-08-12 Plan 020 首次 B7 真实基线终态

- v22 fresh wire 4/4 usage-valid；25 条历史首个非 infra 结果经冻结 SHA 重验后复用，只为缺失/infra 逻辑链
  使用新 IDs。四轮在同一九项共同集合上形成 RONDO A/A `5/9`、`5/9`，RONDO A/B `5/9` 和 frozen Codex
  A/B `4/9`。
- `sigma=0`、`delta=3`，因此冻结的 `delta <= sigma` 机械一致性子门以 `ab_delta_exceeds_aa_sigma` 判 failed。
  唯一条件任务 `db-wal-recovery` 的两侧各两次加跑未形成 RONDO 三败/Codex 三过；这不是设施 blocked，
  但后续归因确认比较条件不对称，不能解释为产品能力或性能差异。
- `vulnerable-secret` 的四条逻辑链均收到 HTTP 200 SSE `error/cyber_policy` 且无 usage，按合同各保守结算并
  排除共同分母；其余任务使用首个非 infra 终态，未通过选择性重跑改变成绩。
- v22 paid `329.767745 USD`、wire `0.192860 USD`，Plan 020 累计 `1466.074133 < 1600 USD`；202/202 upstream
  attempts settled、reservation 0、`actual_usd=null`。结果与 aggregate 已进入独立 results 分支；v1—v22
  只读保留，active paid pointer 关闭。

### 2026-08-12 Plan 020 合并前离线收口

- Oracle proof 的执行闭包补入 Harbor compatibility 与 frozen task/image 合同；真实 contract 漂移回归确保这些
  组件变化会使旧 proof 失效。
- terminal state 到 private/tracked aggregate 支持幂等恢复；schema-v3+ 的 provider-integrity 只豁免机械熔断，
  不再绕过单轮最终 infra 上限。
- v22 历史数据只读重放保持一致；机械一致性子门 failed，但该批比较不具备能力归因条件。E-A 与 M2 尚未完成，
  方向 1 正式优化未解锁。

### 2026-08-13 Plan 018 GGUF 静态验收与 b10333 Linux CUDA model-free runtime

- 唯一冻结 Bartowski Q4_K_M GGUF 下载至项目 ignored 路径，普通文件、`5,198,387,456` bytes 与完整 SHA-256
  `7deb50ec…54802a` 精确匹配；没有下载其他模型资产，没有加载 GGUF。
- 官方 CUDA 12.6.2 以项目局部 toolkit-only 方式安装；exact b10333/`08659901…` source 在项目 build lock/watchdog
  内以 Ada `89-real` strict link 成功，无 CCCL/CUB 3DOT2 或 permissive linker flag。
- 独立 CUDA lock 冻结 source/toolchain/build、9 个 ELF 文件、14 个 symlink、RUNPATH、cudart/cuBLAS、WSL
  `libcuda.so.1` 与系统闭包。version/help、RTX 4060 Laptop device probe 与 model-free router 通过，不依赖调用者
  `LD_LIBRARY_PATH`。
- CPU/CUDA exact binary path 只映射各自 lock；受跟踪示例配置的 model-free doctor 返回
  `linux_cuda_built_model_unvalidated`，正式 launcher 仍拒绝。真实 ignored 配置未迁移，直接 doctor 仍为
  `configuration_error`；focused tests 58/58 通过，4k/8k model-backed、推理与 structured output 均未运行。

### 2026-08-13 教师 harness 性能候选调研

- 完成 Claude Code、Kimi Code、OpenCode 与 OpenHands SDK 的主题化源码比较，以及与冻结 Codex `v0.147.0`
  的差异矩阵；只学习机制，没有复制教师源码或运行产品代码。
- 形成 C1—C13 候选及证据等级、适用条件、风险、测评轨和否证边界。候选是待验证假设，不代表收益或实施已解锁。
- 研究交付为 `doc/research/teacher-harness-performance-candidates.md`；方向 1 的当前顺序统一由 WBS 管理。

### 2026-08-13 可信证据型多智能体内核调研

- 完成公开研究、冻结 Codex 和本地教师源码的对照，收敛出“私有上下文 + 持久证据引用 + ResultCard 原件定位 +
  有界复核 + root 合成”的候选内核语义。
- 明确 root 单 writer 起步、持久化先于发布、恢复不可伪装成功、开放第二 writer 前必须有 Workspace Manager 等边界，
  并排除自由群聊、投票、trust score、平行鉴权和通用副作用缓存等低收益复杂化。
- 研究交付为 `doc/research/multi-agent-trusted-evidence-research.md`；产品实现未开始，阶段路线统一由 WBS 管理。

### 2026-08-13 Plan 020 B7 failed 归因收口

- 对产品源码、四轮结果和执行时间线完成独立复核，未发现能解释三项 delta 的 RONDO 产品机制退化。
- 确认 A/B 两侧存在完整 catalog prompt 161-token 非对称，同时混有 harness/deadline 与非交错时间块差异；
  因此 v22 机械一致性子门真实 failed，但不能据此归因 RONDO/Codex 的能力或性能差异。
- catalog 字节/provenance、规范化请求 preflight、同 harness/deadline、交错执行、判据分层与重复数预冻结等
  实验约束已达成共识，报告分歧全部关闭。

### 2026-08-13 P2 v2—v22 公共结果账本交付

- 结果分支使用的执行设施 commit `ba16cb2` 和被测对象 commits `14341a1` / `cb652e1` 均已存在于主线历史；
  结果分支相对主线的净文件差异仅为 `eval/results/`，没有产品或设施代码。
- 完整合入 `eval/results/runs.jsonl` 的 227 条增量记录和 v6—v22 的 11 份聚合 JSON；合入后共 244 条唯一
  `run_id`，其中 v22 为 32 条。全部 JSON/JSONL 解析通过，冻结历史标签“Plan 015”保持不改写。
- 原 `0811-p2-b7-results@564a602` 提交链完整并入交付历史，完成分支改名为
  `zz-done/0811-p2-b7-results`；该操作只交付公共结果，不重跑测评或改变 B7 归因。

### 2026-08-13 E-B8 公平比较设施闭合（工作包 1，无真实 API）

- **catalog 对称**：`frozen_model_catalog.load_shared_model_catalog()` 保留完整 8 模型，只在 main entry 上写
  `auto_review_model_override`，两侧加载同一份 artifact。artifact 身份改为自身 SHA-256，另绑上游/RONDO 双来源
  commit/path/blob ID、投影算法与版本、main/Guardian model 和 override 目标 entry；两来源 blob 不一致即判定
  无共享工件。adapter/runner 不再禁止 RONDO 接收 catalog，也不再把 catalog 身份绑到某侧二进制 source commit。
  旧 Codex-only 投影保留为 `load_frozen_model_catalog()`，仅供 v1—v6 复算。
- **请求前置硬门**：新增 `rondo_eval/fair_comparison.py`，投影 tool specs、instructions、输出 schema、采样合同
  与 `input` 中首个 user 之前的 developer/system 前缀（Responses Lite 的 catalog 派生工具描述所在处）。
  `SymmetryPreflight` 挂在 `api_budget_proxy` 请求体解析之后、预算预留与 `_transport.open` 之前，
  不对称时以分区级原因码 409 拒绝。完整请求 digest 各侧分别记录，只作 provenance/drift。
  离线入口 `just eval-preflight-symmetry`，`NoUpstreamTransport` 使其结构上无法连上游。
- **运行条件与顺序**：`ComparisonConditions` 冻结 harness commit、deadline、task/image digest、provider profile
  与投影版本，漂移给出可归因原因码。基础轮调度由整轮分块改为按任务交错（v7 起），并保留轮末 infra 阈值提前停机。
- **判据分层与聚合**：assessment 分别输出 `aa_consistency` / `cross_side` / `directional` 三层状态、原因与指标；
  条件加跑进入最终聚合，触发题按冻结重复的严格多数得出每题 outcome，`delta` 用聚合结果计算并保留 `base_delta`。
- **重复合同**：`RepeatContract` 要求奇数且不少于 3（基础 A/B 轮计其中一次）、聚合固定严格多数、冻结点为 pilot；
  未冻结、偶数、样本数不符或事后改公式均拒绝，因而在冻结前无法建立 v7 campaign。不采用 pairwise-max `σ`。
- **产品身份**：新增 `contracts.Product`（`rondo-local` / `rondo-multi`）与 `product_for_side()`，与比较侧正交，
  `codex` 不是产品取值；v7 lock 显式记录产品身份。未创建 `multidev/`，未提前实施工作包 2。
- **历史保护**：全部新行为绑定 campaign schema v7；v1—v6 的 slot 顺序、run_id 分配、assessment 输出与
  catalog 投影逐字节不变，v1—v22 的 lock/result/ledger/aggregate 未改动。
- **独立验收后的四项修正**（GPT 审查 blocked，四项均已复现属实并修复）：
  1. 付费 runner 原先根本没接 preflight，且注册表会放行首个到达的一侧。新增 `PreflightReceipt`：
     两侧在 stub 上零成本产生请求并冻结合同，receipt 绑定 campaign_id / lock SHA / task / 两侧 bundle manifest；
     付费 slot 缺 receipt 直接拒绝，代理以 receipt 预置期望，第一侧同样受检。
  2. `eval-b7-next-identity` 原先硬编码生成 schema v6，可绕过全部 v7 门禁。生成器改为只产 v7，
     必须传入 pilot 后冻结的 comparison 合同，且在任何读写之前完成纯校验。
  3. `ComparisonConditions` 原先无生产调用，且非法/矛盾的 comparison 块可被接受。现在加载时与 campaign
     自身权威事实逐项等值校验（deadline、provider profile、catalog artifact、task/image），
     harness commit 在执行时校验；catalog provenance 的 commit/blob/path/投影/override 目标全部格式与一致性校验。
  4. 条件重复原先只覆盖 RONDO fail / Codex pass，反方向差异会绕过重复合同。v7 起触发条件改为任一方向的
     跨侧差异；方向性兜底仍只检测 RONDO 全败/上游全过。
- **二次验收后的五项修正**（GPT 复审仍 blocked，五项均已复现属实并修复）：
  1. `_TASK_ID` 不允许 `/`，而正式 TB 任务 ID 形如 `terminal-bench/fix-git`，导致任何正式任务都无法生成或消费
     receipt（设施不可用，非 fail-open）。放开命名空间分隔符，每段仍须以字母数字开头；receipt 文件名改为
     `<leaf>-<task_id 摘要>` 以保持不同命名空间的任务不共享文件。receipt 测试全部改用正式带 `/` 的 ID。
  2. 没有真正驱动双侧冻结二进制的 receipt 产出入口，且付费 wire canary 早于 receipt 校验。新增
     `terminal_bench/preflight_producer.py` 与 `just eval-b7-preflight-receipts`：两侧走真实 Harbor/Docker 链路，
     唯一可达端点是本地捕获 stub，原子写出 receipt；付费 worker 启动时一次性校验全部任务 receipt，位置在
     wire canary 之前。stub 与付费路径共用 `campaign_terminal_bench_request()` 与 `project_shared_model_catalog()`，
     receipt 冻结的请求不会与被付费的请求分叉。
  3. successor 无条件继承 v22 的 25 条 continuation（既违反 v7 公平条件，又因 profile 已被剥离两个旧 catalog 字段
     而必然以 `continued execution contract drifted` blocked），且仍继承旧 prior 与固定 1600 cap。v7 改为
     continuation 恒为空（加载时强制）、prior 为 0、cap 由 `--campaign-cap-usd` 单独授权传入且不超过历史封顶；
     写 lock 前用真实事实核对新 comparison（共享 catalog 复现、harness commit、task/image、provider profile）。
     生成器侧的 continuation 继承代码已整体删除。
  4. `validate_successor_run_range()` 固定只查 321 个 run ID，而 5/7/9 次重复会把 slot 扩到 481/641/801，
     尾部与历史区间的重叠被放行。改为接收由冻结重复数算出的真实 slot 数并校验完整区间。
  5. 代理 409 只返回 `frozen_contract_asymmetry` 等 scope 码而非合同要求的分区级原因。
     `FairComparisonError.reasons` 改为最具体在前，409 现在直接返回 `task_independent_<partition>_differs`。
  同时修正两处措辞不实：`stub_preflight()` 声称"carries a transport"（`SymmetryPreflight` 无 transport 字段），
  以及 `preflight_cli` 输出里名义上的 `upstream_transport` 字段。
- **后续独立审查闭合**：harness commit 改为排除 identity-only commit 的已提交代码投影，并在 producer/worker 的
  Docker、Oracle 与 wire 之前校验；stub 强制真实 main → Guardian → main，receipt 必须覆盖两类角色；receipt
  批次先全量验证再发布，同字节幂等重试、异字节冲突拒绝。真实 Responses Lite `additional_tools` 与随后
  developer/system 前缀进入投影 v2，任务正文仍被排除；identity lock 使用完整 Git 路径历史拒绝 addition 后改写、
  恢复及 TREESAME merge 隐藏；receipt schema v2 保存双侧六段完整请求 digest，不保存正文、不要求跨侧相同。
- **最终验收**：`just eval-lock` 通过；focused `test_fair_comparison` 87/87、完整 `just eval-test` 578/578，均
  0 fail、0 skip。synthetic v7 identity 下，冻结双侧的 fix-git 2/2 side runs 与完整 catalog 10/10 tasks、
  20/20 side runs 全部通过；60/60 请求形成非空 Lite 稳定投影、六段 provenance 与 gate registration。
  全程真实 API 请求 0、费用 0，未 pull/build 镜像，最终 Docker 占用与基线一致、临时对象已清理。第五次独立验收
  结论为设施实现通过，相关实现与验收提交已合入 `main@ce316a6`。
- **边界**：没有创建正式 v7 identity，未执行正式 identity → producer CLI → worker CLI、Oracle、wire canary、
  paid task、pilot/repeats 或能力比较；这些仍需各自冻结合同与单独授权。设施闭合不产生任何可归因的能力比较结论。

### 2026-08-14 Plan 022 RONDO Multi 产品基线实现批次（独立验收未通过，不计为已完成）

> 该实现提交 `d2c16073` 的独立验收结论为拒绝合并；本节只保留当时实施事实，不代表工作包完成。
> B1/B2/B3/M1 修复已在同一任务分支继续落地，须经独立复审后才可转为完成记录。

- **共享看门狗迁根**：`with-build-lock.sh`（`100755`）与 `build-watchdog-lib.sh`（`100644`）经 `git mv` 移到仓库根
  `scripts/`，字节内容、阈值、退出码与安全语义不变；`script_dir` 仍按 `BASH_SOURCE` 解析同目录 helper，
  `project_root` 仍走 git common dir。全部现行引用点改为根路径：根 `justfile`（3 处）、`mydev/justfile`
  （新增 `watchdog` 变量，8 处）、`runtime_bridge` 的 canonical wrapper 校验、`binary_freeze` 的 build-command
  合同、`baseline_cli`、`results` 的 `_EVAL_HARNESS_PATHS`、三个测试文件与 `AGENTS.md` / `CLAUDE.md` /
  `doc/development-environment.md`。**不留 shim、软链或兼容分支**；`eval/locks/*.json`、`agent_log/` 与
  `doc/audit-snapshots/` 里的旧路径作为冻结 provenance 保持原样。共享 helper 的 9 项回归改由两条产品线的
  `just test-github-scripts` 各自显式指向根 helper（`parents[3]/scripts`）。
- **`multidev/` 精确复制**：由 `git ls-files --stage -z -- mydev/` 清单驱动、按工作树内容复制，保留 mode 与
  symlink。6,011 个条目（5,951 个 `100644`、59 个 `100755`、1 个 `120000`），与 `mydev/` 的 blob 与 mode
  **逐条相同**，工作树 sha256 与文件类型也逐条相同，且 `multidev/` 内没有清单以外的文件。WBS 点名的六个
  `mydev/codex-rs/core/` 未跟踪残留目录（`.git`、`.agents`、`.codex`、`project`、`absolute-turn`、
  `request-permissions-environment`）全部未进入 Multi。
- **默认关闭行为门**：`codex-rs/core/src/config/config_loader_tests.rs`（两棵树同源）新增两项回归，经
  `ConfigBuilder` 真实配置加载路径断言空 `config.toml` 下 `[auto_review]` 的 `model`、`model_provider`、
  `reasoning_effort`、`evidence_dir` 全为 `None`，同时断言 `approvals_reviewer` 保持上游默认 `User`
  （不靠改 reviewer 伪造关闭态）；配套的正向用例证明四项确实仍被接线，避免断言空转。
- **产品身份贯通**：`Product` / `product_layout()` 成为唯一映射（`mydev|multidev`、Cargo target 前缀、
  `bin/{rondo,rondo-multi}`、`models-manager/models.json` 路径）。身份现在贯通 binary freeze 的源码根 /
  target / legacy artifact / code-mode bundle / runtime bundle、三种 manifest、共享 model catalog 来源、
  campaign lock 的 catalog provenance、adapter 与 agent kwargs、`RunSpec`、结果记录与归档 `run-summary.json`。
  `RunSpec.validate()` 交叉校验运行声明的产品与其冻结二进制的产品，任一层缺失或矛盾 fail-closed。
- **只加不改的历史兼容**：缺 `product` 的 manifest 与结果行按 `rondo-local` 读取，不回填；`side=codex`
  既不携带也不推定产品身份。Local 的 build-command 合同保持逐字不变（`--product` 仅在非 Local 时出现），
  因此历史 seven-key 工件的合同形状未被改写。
- **默认关闭的结果合同**：新增版本化 `auto_review_config` 块，记录该次运行**配置了什么**（未配置写 `null`），
  由结果顶层与归档 `run-summary.json` 共用同一投影，成功与失败发布路径不分叉。Multi 四项全 `null`；
  Local 沿用既有公平合同；冻结上游不写该块。adapter 的 `-c` 覆盖与该块出自同一个 `auto_review_overrides()`，
  运行命令与记录状态无法互相矛盾。
- **eval 入口**：`binary_freeze` 与 `docker_smoke` CLI 新增显式 `--product`；根 `justfile` 的 `eval-b2-no-api`
  改为按产品选择命名空间与 bundle，并新增 `product-build`、`product-default-off-test` 两个带锁入口。
- **验收（全部本地、无真实 API、无 Docker、无本地模型）**：`just eval-lock` 通过；完整 `just eval-test`
  592/592 通过（0 fail、0 skip），其中新增 7 项 Multi 冻结布局回归与 6 项产品/`auto_review_config` 结果合同回归；
  共享 helper 9/9；经迁移后根看门狗的 Multi `codex-core` 默认关闭回归 80/80（含两项新门），
  以及一次 Multi `cargo build --locked -p codex-cli --bin codex`。看门狗两次均 `stop_reason=none`、
  `cleanup_reason=none`。不重跑全 workspace。
- **边界**：`eval-data/bin/rondo-multi/` 仍为空，Multi 没有冻结 runtime bundle，因此本工作包没有做任何
  Docker、no-API 双侧、真实 API 或能力验收，也没有产生正式 campaign identity、run ID 或结果行。
  看门狗改根后，历史 Local/Codex bundle 的 `binary_freeze verify*` 会因 build-command 里记录的旧 wrapper 路径
  而不再通过（按 WBS §4.4「拒绝旧路径」的要求，属预期）；冻结 bundle 字节与 `eval/locks/*.json` 均未改动。

### 2026-08-14 Plan 022 RONDO Multi 产品基线最终独立验收与交付

- **结论**：第四次独立验收确认上一轮技术问题全部闭环，未发现新的实现级阻断；Plan 022 的实现与测试合同通过，
  随后完成文档收口与合并交付。前一节保留首次未通过批次的形成时点事实，不改写其历史结论。
- **最终闭环**：campaign publication 在落盘前绑定真实冻结 identity；campaign、continuation、result digest 与
  aggregate 共用完整 durable record/private-summary reader；缺失或篡改私有摘要与 bool 冒充数字均 fail-closed。
- **验收证据**：执行者完整无 API eval 610/610、`eval-lock` 85 packages、两侧 watchdog helper 各 9/9；独立验收
  复跑直接相关模块 234/234，并确认历史 durable index 244/244 可读。未运行 Cargo、Docker、真实 no-API、API、
  模型或付费测评；Multi 仍无冻结 runtime bundle，不据此主张功能或能力结论。
- **复制合同**：用户已采纳决策 011。非 `multidev/**` 差异通过 `git diff --check`；`multidev/` 的 6,011 个
  tracked 条目在相对路径、Git type/mode/blob 与工作树字节上逐项等同 `mydev/`，只对这份精确复制内容保留
  上游尾空格窄例外。
- **交付**：验收通过的任务分支以 merge commit `c7b7bd4` 合入 `main`；其后 `main` 前进到 `e4e0b47` 并已推送，
  最终核对 `main == origin/main == e4e0b47`。工作包 2 至此完成，后续路线转入 `doc/WBS.md` 的工作包 3。

### 2026-08-14 Plan 023 RONDO Local 4k model-backed qualification 失败收口

- **设施进展**：真实 ignored 配置迁移到 exact b10333 CUDA runtime、唯一 GGUF 与 4k `auto`/fit-on 合同；新增受限
  qualification、严格 model-backed evidence/capability 投影和按 backend 精确 `/props.build_info` 身份校验。
  正式 launcher 对未晋级 runtime 仍在 Popen 前拒绝，不存在通用 bypass。
- **真实结果**：第 4 次、也是授权上限内最后一次生命周期成功加载 exact GGUF，实证 CUDA、正数 GPU offload、
  `build_info=b1-0865990`、context 4096、单 slot 与模型身份。所选冻结真实 `E_final` 经服务端计数为
  5,313 input tokens，超过 4096 并被拒绝，未产生结构化判定；该事实不能外推到其余 46 条归档。
- **失败语义**：未写成功 evidence，显存峰值/TTFT/总耗时不冒充有效资格指标，capability 保持
  `linux_cuda_built_model_unvalidated`；正式 doctor 报 `model_backed_validation=not_run`。Turn A 因而是
  completed-with-failure，不是 4k 服务成功，未进入 Turn B、L7 或 Local M3。
- **复审与交付**：独立审查发现并闭合 evidence selector/TOCTOU、结论外推和 VRAM 全窗口采样三类问题；focused
  tests 115/115 与 `just eval-lock` 通过，模型进程、8080、receipt、private objects 和 GPU compute process 均无残留。
  任务分支以 `3edf08a` 合入并推送 `main`，worktree 已移除，分支保留为
  `zz-done/023-local-4k-qualification`。后续上下文预算与真实证据可服务口径只由当前 WBS 承接。

### 2026-08-14 Plan 025 WP3b-A2a provider-neutral static payload v2

- **成果**：static input payload 显式升为 v2，结构化决策输出 schema 保持 v1；reasoning 规范化只发生在
  公共 `build_static_payload()`，Luna/Sol/Local 三个 static consumer 获得相同 canonical bytes，Local client
  与 token census 共用同一 v2 request builder。
- **公开与私有边界**：只有 `summary[].summary_text` 按原文与顺序转成中立 assistant 证据；
  `content[].reasoning_text`/`text` 按冻结 Codex 语义作为 raw reasoning 校验后丢弃。encrypted/provider id、
  warehouse-only metadata 与 tool authorization 字段不出站；未知或 malformed reasoning 形状 fail-closed。
- **审查闭环**：独立审查先后发现 raw content 误投影、passthrough metadata 外层及 executed-call 元素校验缺口，
  均以窄整改和直接回归闭合；没有增加 provider-specific fallback、长期审计设施或新 schema registry。
- **验收**：最终独立复跑 focused tests 109/109、eval lock 85 packages 与 47/47 真实归档聚合式只读构造通过；
  47 个 v2 payload、三 consumer bytes 和 47 条 Local request 均构造成功，24 个无公开 summary 的 reasoning item
  全部删除，出站无 `type=reasoning` 或 `encrypted_content`。检查未输出正文或完整请求体。
- **边界**：未运行真实模型、GPU、census、Cargo、Docker、云 API 或全量 eval；不据此宣称那 21 条已在
  b10333 上可服务，也未触及 2 条通用 500。capability 保持 `linux_cuda_built_model_unvalidated`，
  exact-token census baseline 仍不存在；后续重跑与档位选择只按当前 WBS 推进。

### 2026-08-14 Plan 027 WP3b-A2c provider-neutral 角色顺序兼容与 census 最小失败定位

- **成果**：static input payload 从 v2 显式升为 v3，结构化决策输出 schema 仍是 `rondo_static_approval_v1`。
  公共 `build_static_payload()` 内把证据消息的 `developer` 角色原地改写为 `user`：只改 role，文本、顺序、
  消息边界和其余字段不变，内容仍留在 `input` 里作会话证据，不并入 Guardian policy/instructions，
  也不跨越 tool call/output 重排。改写无条件执行，不按前驱角色分情况，三个 static consumer 与 token census
  继续消费同一份 canonical bytes，没有 Local/llama.cpp 私有旁路。
- **选择理由**：47 条归档只含 `user`/`developer`/`assistant` 三种消息角色；冻结 Ministral 模板中在
  system/user/assistant/tool 之后都合法的是 `user` 与 `assistant` 两种，而归档 developer 消息是输入侧
  `input_text`，映射为 `user` 只换 role 标签，映射为 `assistant` 则会改变说话者并被迫重写文本 subtype。
  因此这是保文本、保序的最窄改法，不需要新增中立结构标记或对话重写器。
- **fail-closed**：未知/缺失 role、非消息 item 携带 role、空或畸形 content、与角色不匹配的文本 subtype
  一律 `EvidenceError`；公共 builder 与终端 validator 复用同一份中立消息形状合同，终端另拒绝 v1/v2
  payload 与被手工回填的 `developer`/`system` 角色。Plan 025 的 reasoning/raw/encrypted/passthrough
  出站边界原样保留。
- **census 诊断**：通用计数失败新增有界 `stage`（`anchor_count` / `archive_count`）、当前 `e_final_sha256`
  与 `counted_before_failure`；归档计数以及样本拒绝后的健康探针遇到通用 500/transport 都立即停止并带同一组
  定位字段，不发布结果、也不降级成样本拒绝；per-record `refusal` 未被污染，没有新建事件/追踪设施。
- **验收**：首轮独立审查发现终端 sink 消息形状复核与拒绝后探针定位两处缺口，均由 `cb66816` 以窄整改
  和直接回归闭合。最终独立复跑 focused tests 116/116、`test_terminal_bench` 中唯一 `policy_identity`
  消费用例 1/1、`uv lock --directory eval --check` 85 packages 通过。47 条只读聚合检查（无模型、无网络、不输出正文）：
  47/47 构造 v3 payload 与 Local 请求，三 consumer 逐字节一致 47/47，无残留 `developer`/`system` 角色与
  reasoning/encrypted；从冻结模板资产解析规则的角色顺序门下 v3 为 47/47 通过、规范化前 24/47，
  与 Plan 026 的离线结论一致。该门禁只在测试中，不进入生产 consumer。
- **边界**：未运行真实模型、GPU、count endpoint、census 重跑、任何 generation、Cargo、Docker、云 API 或
  全量 eval。本次只证明构造层与模板角色顺序兼容，**不证明** 47 条在真实 b10333 上可完成计数，
  也不解释 Plan 026 的具体通用 500。WP3b-A2 仍 blocked/incomplete，正式 exact-token baseline 仍不存在，
  未选上下文档位，capability 保持 `linux_cuda_built_model_unvalidated`，qualification 状态不变。

### 2026-08-14 Plan 029 WP3b-A2e static payload v3 的 47/47 exact-token 普查闭合

- **成果**：**WP3b-A2 闭合**。v3 锚点常量从 pre-v3 的 5,313 窄改为实测 **5,311** 后，
  用现有正式 census 入口、static payload v3、公共 Local request builder 和冻结
  b10333/GGUF/tokenizer/template，从头独立运行两遍完整 count-only 普查，两遍全部成功。
  唯一正式结果发布为 `eval/results/baselines/local-approval-exact-token-census-v1.json`。
- **锚点迁移**：只改 `ANCHOR_INPUT_TOKENS`、模块说明与两处行内说明，以及
  `eval/tests/test_local_approval.py` 中直接代表锚点或 `锚点 - 1` 的 4 处断言/fixture。
  没有新增 schema、版本注册表、容差或第二套锚点机制；历史文档中的 pre-v3 5,313 保留为形成时点事实。
- **两遍一致性**：两遍均 `status=complete`、`missing_counts=0`、47/47 counted、0 refused、
  锚点精确 5,311、`generated_tokens=0`、exit 0、`server_stopped`/`port_released`/
  `private_artifacts_removed` 三项全 true；两份结果文档**逐字节一致**，digest 同为
  `22b8452717f1bcfa692cffa69389ebb4a21a0aef1a9187cd066879a6b0831144`，
  文件 SHA-256 同为 `0c49ca78d8ca53ff2331fec7734e67f0d2302223d6e5f7a5d64554d5be882606`。
  比较通过后才发布正式 baseline，两份临时结果随即删除。
- **全集事实**：47 条真实 `E_final` 全部为 `responses_lite`；input tokens min 5,311、p50 8,989、
  p90 12,352、p95 13,754、max 22,499。按 `input+512`：**4k 适配 0/47、8k 适配 11/47**。
  这是本方向第一次拥有全集分布而非 24 条子集；此前从未被计过数、含 `assistant → developer`
  相邻关系的 23 条这次全部被精确计数，Plan 026 的通用 500 未再复现（但本次没有单独定位那一次失败）。
- **服务身份**：两遍都绑定同一冻结资产——`service_build_info=b1-0865990`、
  runtime `eval-data/tools/llama-b10333-cuda-linux-x64`、GGUF SHA `7deb50ec…54802a`、
  chat template SHA `74eeb55f…a1ea56`、count endpoint `/v1/responses/input_tokens`。
- **验收**：focused `tests.test_local_approval` + `tests.test_contracts_and_evidence` **116/116**（14.274s）、
  `uv lock --directory eval --check` **85 packages** 均在首次模型加载前通过。
  收尾现场：8080 空闲、无 llama-server、GPU 无 compute process、`eval-data/local-approval/` 为空、
  共享构建锁已释放、主工作区干净。
- **边界**：未运行 generation、qualification、L7、Cargo、Docker、云 API、全量 eval 或全量测试；
  未改模型/tokenizer/template/样本集合/payload schema/输出预算/fail-closed 规则，未新增审计或
  provenance 设施。census 成功只闭合 WP3b-A2，**不等于** model-backed qualification 或 Local M3 成功：
  capability 仍为 `linux_cuda_built_model_unvalidated`、`model_backed_validation: not_run`、
  CUDA lock 的 `model_backed_structured_output` 仍为 `not_run`，上下文档位尚未选择。

## WP3b-A3 Local 12k model-backed qualification 与 capability 晋级（2026-08-15）

方案：`plan/030-local-12k-model-backed-qualification-execplan.md`；
日志：`agent_log/2026-08-15-011600-plan030-local-12k-model-backed-qualification.md`、
`agent_log/2026-08-15-023616-plan030-acceptance-remediation.md`、
`agent_log/2026-08-15-024713-plan030-stdio-remediation.md`。

- **成果**：RONDO Local 首次取得 **model-backed** 能力。既有 selector 预绑定的真实 `E_final`
  （`eaa2dfb1…9ebaca`，5,311 tokens，与 v3 census 锚点同一 SHA）在冻结 b10333 CUDA runtime、
  唯一 GGUF、冻结 tokenizer/template、static payload v3 与 **12,288 / 512** 合同下，
  返回了合规的 `rondo_static_approval_v1` 结构化判定。capability 由
  `linux_cuda_built_model_unvalidated` 晋级为 `gpu_model_serving_validated`。
- **实测指标**：服务 `n_ctx=12288`、`total_slots=1`、`build_info=b1-0865990`；
  GPU offload **33/35 层**；设备级显存 baseline 1,386,217,472 B、峰值 **7,855,931,392 B**、
  delta 6,469,713,920 B；TTFT **3,183 ms**；结构化判定总耗时 **7,049 ms**；
  进程/端口/receipt/私有对象四项清理全 true。
- **最终冻结服务参数**：12,288 / `gpu_layers="auto"` / `fit="on"` / batch 512 / ubatch 256 /
  flash attention `on` / K,V 均 f16 / 单 slot。正式 launcher 使用 verbosity 3，并把 server stdout/stderr 定向到
  `DEVNULL`；只有 qualification 的
  0600 私有临时日志使用 verbosity 4 读取 offload 事实。8GB 现场可用显存 7,096 MiB，
  `--fit` 自动收敛到 33 层、6,049 MiB used、1,046 MiB free，**未动用已授权的低精度 KV 方案**。
  冻结 b10333 的 `--fit` 只调整仍为默认值的参数、上下文仅在等于 0 时才改写，服务端逐字打印
  `context size set by user to 12288 -> no change`。
- **合同迁移**：evidence 改为版本化的
  `eval/locks/local-approval-b10333-ministral-12k-v1.json`（schema v2）；
  `model_backed.serving_contract()` 成为服务参数的唯一漂移源，identity 显式记录
  gpu_layers/fit/batch/ubatch/flash/K/V；`request_contract_sha256` 升为 v2 并纳入
  `static_payload_schema_version`，identity 另存同名显式字段，**补齐了 static payload v3 绑定**；
  KV cache 校验由“只允许 f16”放宽为冻结 b10333 `kv_cache_types` 白名单（实际冻结值仍是 f16/f16）。
  主仓 ignored `rondo.local.toml` 只改 `context_size` 一个字段，`providers`/`paid_eval`
  规范化 digest 与 0600 权限均未变。
- **疑难问题**：前两次生命周期都以 `gpu_offload_not_reported` 失败，但决策与清理其实都成功。
  根因是冻结 b10333 的 `common_get_verbosity()` 把 libllama 自身的 `GGML_LOG_LEVEL_INFO`
  映射为 verbosity **TRACE(4)**，而默认阈值是 **INFO(3)**，因此 GPU offload 计数在默认级别下
  根本不输出，而该事实又没有任何 endpoint 可取。首次实现把 verbosity 4 同时带入正式 launcher；独立审查还发现
  启动指纹包含模板的 worktree 绝对路径。最终把 trace 限定在 qualification 私有采集，正式 launcher 保持 verbosity 3；
  启动指纹 schema v2 改用仓库相对资源身份，linked worktree 与 main 对同一合同得到相同 hash，参数漂移仍失配。
  失败摘要也只输出固定类别，不再从任意日志正文派生 label。后续复审确认冻结 runtime 的 WARN/ERROR 仍有模型正文路径，
  因而正式 launcher 最终将子进程 stdout/stderr 直接定向到 `DEVNULL`；qualification 的私有日志保持不变。
- **正式入口复验**：晋级后由无 qualification 特权的正式 launcher 用同一合同独立加载，
  receipt schema v2 的 `serve_config_sha256`（`7cb5a45a…`）与证据 identity 逐字节一致；
  服务存活期间正式 doctor 报告 `status=ready`、exit 0、
  `runtime_capability=gpu_model_serving_validated`、`model_backed_validation=model_schema_probe_passed`。
  随后定点 SIGTERM 该 exact PID，launcher rc=0、receipt 自清、进程退出。
- **验收**：focused `tests.test_local_approval` + `tests.test_config_hardening` +
  `tests.test_config_and_artifacts` 最终 **140/140**、`just eval-lock` **85 packages**。首次模型加载前实际为
  138/138；首次诊断整改后为 139/139；独立审查整改后、重新加载模型前为 140/140。首次加载前另已证明：真实 12k 配置下
  doctor 报 `linux_cuda_built_model_unvalidated`、正式 launcher 在 `Popen` 前以 exit 70 拒绝。
  共使用 8 个模型生命周期：原 6 次完成参数探索与首轮资格/复验，审查整改后再用 1 次资格和 1 次正式复验。
- **边界**：本次只证明 12k 档位内这条真实证据可服务。**未**验证其余 41 条适配证据、剩余 5 条超窗证据、
  16k、47 条批量 generation、L7 配置切换或 Local M3；未运行 Cargo、Docker、云 API、训练、
  全量 eval 或全量测试；未改模型/runtime/tokenizer/template/static payload v3 核心语义、
  输出预算、selector、census baseline、run ledger 或历史 CUDA base lock；
  未新增 provenance、签名、attestation 或通用审计设施。

## WP3b-A4：L7 正式 Guardian 路由与配置切换（Plan 031，2026-08-15，Local M3 收口）

- **结论**：RONDO Local 现在可以只靠运行配置把 Guardian 审批在云端模型与已资格化的本地 12k 模型之间切换。
  真实 `--approve-for-me` 链在本地 12k 上取得生产 parser 可接受的 allow 并执行了待审批动作，
  三类关键失败全部 fail-closed。**L7 与 Local M3 同时完成**。
- **为什么需要一个适配器**：正式 Guardian 直连冻结 b10333 有四点过不去——(1) 该 pin 不映射
  OpenAI `text.format`，输出合同会被静默丢弃；(2) `common/chat.cpp` 在 `tools` 与 grammar 并存时抛
  `Cannot specify grammar with tools`，而 Guardian 请求必带 `exec_command`/`write_stdin`/`view_image`；
  (3) 请求 `input[0]` 是 `developer` 消息，经 `map_developer_role_to_system` 会撞上冻结 Ministral 模板的
  角色顺序限制（正是 static payload v3 已解决的形状）；(4) 通用 provider 路径不消费 launcher receipt，
  无法在请求窗口内判定身份漂移。
- **落地形态**：`eval/rondo_eval/local_approval/guardian_bridge.py`，**`mydev/` Rust 源码零改动**
  （只在 `mydev/justfile` 增加受锁构建配方 `build-codex-cli`）。适配器把入站 Guardian 请求交给公共
  `build_static_payload()` 归一化——与 token census、12k qualification 同一条边界，不存在第二套角色/
  reasoning 处理——再按冻结服务合同重建请求；响应完整缓冲，**身份后验通过前不写出任何字节**；
  判定按 Guardian 自己送来的 schema（`codex_output_schema`）校验；一切失败都是 HTTP 失败，永不渲染成判定。
  配套 `formal_switch.py` 驱动真实 CLI 五场景（主 Agent 由 loopback 脚本化端点应答，本任务无云端授权）。
- **验收数据**：`just build-codex-cli` 经 build lock 4m02s 产出含 L2a 的当前 binary；
  focused `tests.test_local_approval` + `tests.test_config_hardening` + `tests.test_config_and_artifacts`
  **159/159、0 skip**；`just eval-lock` 85 packages。正式链五场景：
  未设 provider 时 Guardian 落到主 provider（证明 provider 轴真实存在）；
  真实 12k 正例 `decision=approved` / `terminal_status=approved` / `token_usage` 非空、动作 `completed`、
  marker 生成、整轮 5.02s 与 7.03s；服务异常（bridge 503）、请求契约不符（bridge 400）、
  身份漂移（bridge 4×503 且 upstream 一次未调）三场景均 `terminal_status=failed_closed` +
  `failure_reason=session_error`、动作 `declined`、`main_endpoint_guardian_requests=0`。
  cloud/local 差异只落在 `[auto_review]` 的 model/effort/provider 三轴及其 provider registry 条目；
  主 Agent 侧不受影响由两处佐证——所有本地场景 `main_endpoint_guardian_requests=0`（脚本化端点的真实计数），
  以及两份 profile 组装出的完整调用里主 provider 那几行逐字相同（`main_provider_identical`）。
- **独立审查发现并整改**：适配器原先在配置无 `model_path` 时会跳过全部身份校验仍返回判定
  （真实配置有 `model_path`，实跑证据不受影响，但该路径本身违反“身份判定覆盖真实请求窗口”），
  且新增 bridge 测试多数跑在身份门关闭状态；已改为无绑定实例即拒绝服务，测试改为发布真实 receipt。
  同轮还纠正了一个恒真的主 provider 指标（改为对完整调用逐字比较并补反例测试）和一处过头的
  docstring 断言（这条路线不等于已资格化的 static 请求，census 长度分布不用来给它定界）。
  整改后在最终代码上重跑了真实 12k 正例与身份漂移。
- **顺带修复的既有缺陷**：`launcher.py` 的 `run_server()` 只处理 `KeyboardInterrupt`，
  收到 SIGTERM 时会被直接结束，留下仍在跑的 llama-server（占 8080 与显存）和陈旧 receipt，
  只有 with-build-lock 的 `residual_processes_after_command` 兜底。修复后同样的 `kill -TERM` 得到
  `exit_code 130`、server 退出、receipt 自清、wrapper 记 `cleanup: none`；两份 wrapper summary 构成前后对照。
- **覆盖边界（不冒充正式链证据）**：“结构化输出不合规”与“响应读回后的身份后验”只做到定向回归端到端
  （bridge 已调用 upstream 却仍返回 502/503 且不写出任何 `data:` 字节）；正式链上覆盖的是适配器错误通道
  到 RONDO fail-closed 这一段。要在真实 12k 上复现不合规输出必须改 prompt 或放宽 parser，两者都被禁止。
  云端侧只做离线无残留证明，未发出任何云端请求。
- **最终独立验收**：审查者复跑 focused unittest **159/159、0 skip** 与 85-package lock，
  并用当前 binary 复跑未配 provider、本地服务缺失、本地模型配置漂移三项无模型正式链；
  provider 分流、动作阻断、`failed_closed` 与无主 provider 回退均与执行证据一致。宿主无相关进程、
  8080、GPU compute、receipt 或私有 evidence 残留。不额外启动第 5 个真实模型生命周期；
  结论为 **验收通过、任务目标完成**。报告见
  `agent_log/2026-08-15-050341-plan031-independent-acceptance-review.md`。
- **边界**：只证明 12k 档位内这条正式链可用。未验证 16k、剩余 5 条超窗证据、其余 41 条 12k 证据、
  47 条批量 generation、教师标签、横评、训练或模型优化；未跑 Docker、云 API、全量测试或全量 eval；
  未读 `.env.local`；未改 Plan 030 资格证据、runtime/model/template lock、census baseline 或历史结果。
  共使用 4 个模型生命周期（每次改动适配器后重跑，确保交付物与证据同一份代码）。

## WP3b-A5：L5a 首批 Sol 教师标签（Plan 032，2026-08-15）

- **结论**：47 条真实生产 `E_final` 经 production meta、tracked ledger 与冻结 census 重新校验，得到 45 个
  稳定语义身份与 2 个重复实例；42 个实例适配 12k，语义去重与代表冻结后生成 40 条标签
  （seed 24 / holdout 16）。聚合排除原因为超窗 5、语义重复 2。教师标签是生成时点的 Sol 蒸馏目标，
  不是人工 ground truth；holdout 可用于评测标签，仍禁止进入合成或训练。
- **冻结合同**：prompt `rondo_sol_teacher_prompt_v1` SHA-256
  `5425f3defeb900c691ed497919a65fca38d05a22460cd4bef503aa7612b9312c`；label schema v1 SHA-256
  `62c4e8ecd8c122006680df1105c188b260d268e10953d042fbaef3c353f1aa18`；manifest v1 SHA-256
  `c96b621a31d0983e47f5bcac22d90c5636d20a147138d5b1b335f1b4cbfdfeba`；labels v1 SHA-256
  `7eaafa25aa99de804559ee77f034f4e69f8ff4227f5cf5d8d70c66f0a7b82a40`。教师为当前开发用 Codex
  `gpt-5.6-sol`，生成日期 2026-08-15。
- **生成与校验**：一个完整批次后，16 条仅因首次传输失败按完全相同 prompt 与输入定向重试一次；
  `schema_invalid=0`，没有因判定内容重试。严格终检重新计算 semantic identity、代表关系、canonical
  payload 与用途绑定，并绑定 prepare receipt 及当前 tracked prompt/schema/census；summary 会重跑完整 verify，
  labels 与 metadata 同步篡改回归也 fail-closed。独立验收发现 prepare 曾把四位归档槽位误作 `review_id`；
  已改为从通过 schema 检查的 production meta 取独立身份并补回归。focused unittest **13/13** 与
  `py_compile` 通过，当前 47 条无写入 prepare 重算得到与冻结批次相同的 manifest / outbound / receipt 哈希，
  真实批次 verify / summarize 继续幂等通过并得到 `ready_for_l3=true`。最终独立验收结论为
  **验收通过、任务目标完成**，报告见
  `agent_log/2026-08-15-071427-plan032-final-independent-acceptance.md`。
- **数据边界**：完整 manifest、canonical outbound、原始返回、attempt provenance、标签与导入元数据只在
  ignored `eval-data/teacher-labels/20260815-sol-teacher-labels-v1/`（目录 0700、文件 0600）；tracked 仅保存
  prompt、schema、轻量实现/测试、文档和不含正文、source path、逐条 semantic id、逐条 holdout 明细的
  `eval/locks/local-approval-sol-teacher-labels-v1.json`。
- **边界**：未运行 L3/L4、Local-static、本地模型、Docker、Cargo、API、训练、全量测试或 CI；未修改
  Guardian bridge、launcher、`mydev/`、`multidev/` 或 `eval/results/runs.jsonl`，未发布 shadow 结果。

## WP3b-A6：L3/L4 未微调 Local-static baseline（Plan 033，2026-08-15）

- **结论**：冻结的 40 条 `gpt-5.6-sol` 教师标签经严格导入后，在已资格化的 12k 本地服务上完成一次
  Local-static 批量回放。40/40 样本首次尝试即进入唯一终态：`decided_allow` 16、`decided_deny` 19、
  `structured_output_failed` 5、`timed_out` 0、`infra_failed` 0，定向重试 0 次。5 条结构化输出失败
  全部撞上 512 输出上限并返回不合规 JSON，按 fail-closed 归档，不折算成模型 deny。
- **指标口径先冻结再运行**：`rondo_l4_local_static_v1` 与 tracked 模板
  `eval/templates/local-approval/l4-metric-contract-v1.json` 连同实现和 focused tests 先提交为
  clean harness（`bbb572d`），真实回放从该 commit 启动，运行后只按同一口径填数。
  主教师一致率固定为 `teacher_agreement / comparable_decision_count`，分母为 0 时写 `null`；
  百分位固定为升序 nearest-rank `index = ceil(p/100*n)`。
- **结果**：教师一致 16/35（seed 9/21、holdout 7/14），教师不一致 19；有效判定覆盖 35/40 = 87.5%；
  fail-closed 5；本地判定分布 allow 16 / deny 19；P50/P95 延迟 8,335.01 / 25,758.68 ms；
  input token P50/P95 8,827 / 11,103，output token P50/P95 92 / 512；峰值显存 8,048,869,376 B
  （基线 1,629,487,104 B，delta 6,419,382,272 B，1,351 次设备级采样，窗口完整）。
  服务返回的 input token 与冻结 census 40/40 逐条一致。
- **重要口径边界**：该批教师标签**全部为 `allow`**（seed 24/0、holdout 16/0），因此本轮"教师一致率"
  在数值上等于本地 allow 率，**不构成有区分度的审批质量信号**，只作为微调前的固定对照起点。
  相对教师标签的差异一律称"教师不一致"，不称漏放/误拦；本轮不存在独立裁判结果。
- **发布**：四条 shadow 记录 `20260815-082704844/845/846/847`（seed/holdout × `sol-static/imported`、
  `local-static/auto`）与聚合 baseline
  `eval/results/baselines/local-approval-unfinetuned-static-baseline-v1.json`（SHA-256
  `ca0bbc21a24b23b607a1308462fcac16447d4577d779819e6c8f683bb09d4dcd`）。imported 行
  `binary_sha256`/`metrics`/`cost.actual_usd` 均为 `null`、不写 `product`、`artifacts` 指向冻结教师目录且
  不占用 run 工件树；`local-static` 行绑定未微调 GGUF、b10333 CUDA runtime、12,288/512 服务合同与资格身份。
  holdout 两条只有整批摘要、`tasks=null`；seed 两条保留不含正文的逐条投影，可独立重算公开结论。
- **统一门禁**：`artifacts.py` 强制 shadow 的 `side` → `source` 映射（`sol-static`=imported、
  `local-static`/`local-ft-static`=auto，未声明映射的 side 一律拒绝）与 `holdout ⇒ tasks=null`，
  两条都由负向 pure tests 覆盖，不依赖写入方自觉。发布对运行 harness commit 采用**祖先**绑定而非等值绑定：
  运行时的 clean-tree 约束不变，但发布在结果与文档提交之后仍可离线重算，交付状态可复现同一 no-op。
- **验证**：focused `test_shadow_replay` 44 项与直接受影响的既有
  `test_teacher_labels` / `test_local_approval` / `test_config_and_artifacts` /
  `test_terminal_bench_results` / `test_terminal_bench_pair` / `test_terminal_bench_baseline`
  合计 **326 项通过、0 skip**；`uv lock --check` 85 packages 通过。在最终交付 HEAD 上重跑 publish
  为幂等空操作（exit 0、0 条新记录、baseline SHA 不变、账本仍 248 条）。真实模型生命周期 1 次；
  一次运行前的失败是 wrapper 相对路径调用导致的 lease 拒绝，未启动模型。
- **最终独立验收**：整改后复验确认统一 shadow 门禁、holdout 公共投影、最终 HEAD 幂等发布及权威文档状态
  均正确，未发现新的功能性阻断；结论为**验收通过、任务目标完成**。报告见
  `agent_log/2026-08-15-085839-plan033-remediation-independent-acceptance.md`。
- **现场清理**：`server_stopped` / `port_released` / `receipt_cleared` / `gpu_released` 四项全 true，
  8080 空闲，无 llama-server 残留，显存回落到 1,498 MiB。
- **数据边界**：逐条正文、模型原始 envelope、attempt 与全部 holdout 明细只在 ignored
  `eval-data/local-approval/l3-replay-f747e9ed89e4694c/`（目录 0700、文件 0600）。tracked 结果与文档中
  无 holdout 逐条身份、无 rationale/risk_tags、无 payload 正文。未运行 Docker、Cargo、云 API、16k、
  L5b/L6 或全量 eval；未修改 `mydev/`、`multidev/`、runtime、GGUF、prompt、static 合同、资格 evidence
  或 `rondo.local.toml`。

## WP3b-A7：L5b 合成训练数据与资产冻结（Plan 034，2026-08-15）

- **成果**：当前人在场开发用 Codex `gpt-5.6-sol` 同时完成实现与合成 authoring，只使用 Plan 032 冻结批次的
  24 条 seed 受控投影作为真实参考，生成 600 个唯一 synthetic static-v3 审批候选。六类分布为明确安全 180、
  明确危险 100、边界模糊 120、证据不足 70、伪装成安全的危险动作 65、工具结果与请求不一致 65；
  allow 240、deny 360。
- **冻结资产**：版本化 prompt/schema、数据卡、机器 manifest、`train.jsonl` 470 条和
  `validation.jsonl` 130 条位于 `training/local-approval-synthetic-v1/`。两份正文共 1,670,240 bytes，
  符合总量 100 MB / 单文件 40 MB 入库门限；train / validation SHA-256 分别为
  `1e66c06e…c110a` / `cbab8084…8dd2`，manifest SHA-256 为 `dbf5fffe…7190`。
- **校验与隔离**：每条 input/target 均通过 static payload v3 与 `rondo_static_approval_v1` 强校验；精确重复 0。
  120 个源/近重复连通组整体落入单一 split，无交叉。holdout 16 条未进入生成上下文，只由本地 finalizer 在内存中
  以冻结 word 5-gram 规则排除近重复，命中 0、聚合最大分数 0.202128；逐条匹配与正文未进入 Git、日志或终端。
- **私有数据**：seed 投影、Sol-authored authoring、候选、receipt 与逐条过滤明细保存在
  `eval-data/synthetic-training/20260815-l5b-synthetic-training-v1/`，目录 0700、普通文件 0600。
  两次候选落盘前的纯格式错误（unterminated string、brace formatting）均窄修后重新做内存校验；没有候选重试、
  按 outcome 重问或正式批次重生成。
- **验证边界**：新增 focused 合成 fixture 覆盖 seed-only 投影、严格 schema/identity、800 唯一候选上限、精确去重、
  holdout 排除、确定性 group-safe split、私有权限及哈希绑定；真实 release verify 从私有候选和冻结教师批次重算
  tracked 数据与 manifest。未运行训练或 training dry-run、本地模型、Docker、Cargo、API、Hub、云资源、CI 或全量测试；
  未修改 Plan 032/033、static v3、L4 结果、`mydev/` 或 `multidev/`。

## WP3b-A8：Local M4 本地离线三方盲评准备设施（Plan 036，2026-08-15）

- **冻结主体**：body-free cohort 精确绑定 Plan 034 全部 130 条 validation、原 dataset/validation 哈希、逐条
  sample/payload/target/source-group/split-group 身份及合同模板哈希；26 个 source group 与 26 个 near-duplicate
  group 均不跨批，确定性两批各 65 条。cohort SHA-256 为
  `9dd901fff3df072ed65ff3962d1e4524255a5a42a3f810903d191457cb494b95`。
- **离线合同**：新增 stdlib-only `rondo_eval.local_approval.cross_eval`，严格接收完整 `sol-static` / `local-static` /
  `local-ft-static`；canonical L6 pair receipt 的内容哈希绑定两种 Local 输出、不同工件身份、微调 receipt、共同底模
  谱系及 runtime/template/request/sampling/output 合同。Plan 033 部署 baseline、缺 side、重复/未知 side 或任何
  input/payload/prompt/message/schema 漂移均 fail-closed。
- **盲评与结果**：版本化裁判 prompt、side/result/receipt/holdout schema 和 SHA-256 稳定 Latin-square 算法；真实
  seed、mapping、三方正文、逐条裁判与解盲结果限定在 ignored `eval-data/cross-eval/<execution_id>/`（0700/0600）。
  每批独立保证 side × position 差不超过 1；所有批次结果完整验证后才解盲，aggregate 只报事实，不给采用结论或
  机械阈值。
- **holdout 边界**：只建立独立私有导入与严格批次级 tracked 计数白名单；私有 source hash 绑定教师 provenance，
  公共投影拒绝逐条身份/正文/输出/理由，synthetic / holdout 入口拒绝混算。本任务没有读取或物化真实 holdout。
- **验证与状态**：6 条完全合成 fixture 完成 0600 文件级三方导入、打包、模拟裁判重载、解盲和聚合 round-trip；
  focused unittest **27/27 通过、0 skip**，`py_compile` 与 `git diff --check` 通过。真实 no-model preflight 复算
  130 条、65 / 65、26 + 26 组，终态 `waiting_for_l6_outputs`。未创建 fake Local 输出，未调用模型/网络，未运行
  L6、正式 M4、Opus 裁判、训练、Cargo、Docker、CI 或全量测试；三选一人判定仍未完成。

## WP3b-A9：L6 首轮 LoRA 阶段一本地准备（Plan 037，2026-08-15）

- **训练数据与 token 合同**：冻结 train `1e66c06e…110a` 的 470 条记录确定性投影为
  `0026cddd…c14`；固定 allowlist 的 train-only bundle 拒绝 validation、holdout、未知文件、symlink、清单外正文
  及自改 manifest 后加入的额外文件。冻结 tokenizer/template 的精确序列统计为 145,360 tokens，
  min/P50/P95/max = 278/311/331/333，4096 上限超限 0、无 packing/截断；470/470 prompt 全 mask，470/470
  非空 completion 均有训练 label。
- **候选训练与回收设施**：落地候选 QLoRA recipe、7 个直接依赖 pin、RunPod smoke/formal 分门入口、checkpoint
  resume、adapter 隔离重载、pending→completed training receipt、逐文件 artifact export/download 验真和超时/止费说明。
  本地 mock 只验证同格式数据/mask，未加载模型且 optimizer step 为 0；最终 recipe 仍须在阶段二真实 smoke 后冻结。
- **成对输出前置**：Plan 036 增加版本化 decision / structured-output failure / refusal / timeout 终态，非 decision
  不补造 deny；paired runner 每次重读两侧 canonical b10333 deployment manifest，支持 adapter on/off 与 paired GGUF，
  绑定实际加载 GGUF/adapter、共同转换/量化身份和 formal source adapter tree。formal v2 文件导入用 0600 private
  evidence locator 重建并重哈希全部 source；先写 attempt journal、再 fsync 唯一终态，悬空
  attempt 显式收敛为 infrastructure failure 后只继续剩余样本。既有 decision v1 导入、盲化和裁判语义保持兼容。
- **审查窄修**：PEFT target 改为只完整匹配 Transformers runtime 文本层的单个 regex，并对实际 targeted modules 与
  trainable LoRA 参数二次 fail-closed；阶段二 RunPod 上传、安装、smoke/formal、预算止费、下载验真、一次恢复重启与删除
  命令已落盘。completed receipt 最后一步中断时只接受逐字一致的 orphan manifest 恢复。
- **验证**：直接相关 unittest **75/75 通过**；真实 no-model preflight 仍为 130 条、65 / 65、26 + 26 groups、
  `waiting_for_l6_outputs`。精确 census 重算逐字一致，mock dry-run、最终 tar 解包后 bundle 自校验、`py_compile`、
  entrypoint `bash -n`、JSON/候选依赖解析、敏感/大文件/权限和 `git diff --check` 通过；训练与 pair 两轮独立复验
  均无阶段一阻断。
- **阶段边界**：阶段一没有创建/修改 RunPod/HF 资源、上传、付费、下载 base 权重、加载 8B、训练、转换、调用真实
  模型/API、运行 130 条成对输出或正式 holdout。推荐阶段二候选为 Secure A40 48 GB；具体对象、预算和上传仍待用户
  单独授权，WBS 保持 L6 进行中而不提前记为完成。

## WP3b-A10：L6 首轮 LoRA 训练与成对输出（Plan 037，2026-08-16）

- **唯一正式训练**：一个 Secure A40 48 GB Pod 上的真实 smoke 完成 1 optimizer step、238 个文本 LoRA target
  和隔离 adapter reload；候选 recipe 无需技术漂移。正式训练完成 118 steps / 2 epochs，train loss
  `0.2667613620381463`。completed training receipt SHA-256 为 `d551e5cf…c97f`，178,328,936-byte adapter
  SHA-256 为 `146d6871…4c41`；29 项 formal 工件在 Pod 删除前回收到本地并逐文件验真。
- **同源部署转换**：冻结 adapter converter 会把 rank-16 adapter 展开为 309 个全模型张量和约 17 GB GGUF，故只按
  技术兼容性改走 `paired_gguf`，未重训、未据 validation 选路线。最终 base / fine-tuned Q4_K_M 均来自同一冻结
  BF16 revision，大小 5,198,378,592 / 5,198,378,560 bytes，SHA-256 为 `9d2ae96a…9eeb` /
  `c3f34fe8…6621`；14 项 deployment receipt/manifest 已在远端和本地分别验真。
- **本地成对输出**：冻结 b10333 对两份部署的两样本 structural smoke 通过；之后串行完成两侧各 130 条，260 个
  新终态均为真实 decision。连同 frozen `sol-static` 形成 390 行，输出 / canonical pair receipt / private evidence
  SHA-256 为 `0e8fbbc7…00aa` / `1d57def1…129c` / `4dd7966c…1727`，Plan 036 正式 CLI 导入为
  `ready_for_blind_packaging`。未运行裁判、解盲或真实 holdout，不形成 Local M4 质量结论。
- **费用与清理**：全程最多一个 Pod；未创建 template、registry credential、network volume 或 HF repo。任务结束时
  Pod 和 volume 均已删除、`currentSpendPerHr=0`；最终账单 `$1.4046356059`（GPU `$1.3439874556`、Pod disk
  `$0.0606481503`、network volume `$0`），与余额差额一致且低于 `$12` 授权上限。本地 llama-server、端口、
  Docker/Cargo 占用和任务 GPU 显存均已清理。
- **现场窄修与门禁**：训练 tokenizer 返回的单 batch Mapping 已兼容解包；paired merge 改为逐字复制冻结 tokenizer，
  转换控制器禁止 bytecode 污染并对产物角色/增长做早期止损；`python -m cross_eval` 的 formal evidence 类身份误拒绝已在
  完整 source 重验后窄修。相关 unittest **89/89 通过**，真实 no-model cohort preflight 为 130 条、65 / 65、
  26 + 26 groups、0 模型调用/0 fake 输出；Bash、Python、JSON、敏感/大文件和 `git diff --check` 门禁通过。

## Multi M-2：选择性路由（Plan 039，2026-08-16）

- **成果**：Root 可把一个 canonical Event 路由给同团队目标，先授予不可撤销可见性和所需指派，再经既有
  inter-agent communication 投递不复制 Event 正文的紧凑通知。目标读取完整 chain、在同一 Event 追加 Version，
  Root 获得新的协调机会；指派结束后严格按活动谓词保留或退出活动视图，历史权限继续存在。
- **投递与权限**：运行中目标并入既有 turn，空闲工作目标触发下一轮，空闲信息目标只排队；通知失败保留 canonical
  route 并明确可重试。route 仅 Root 可发起，`retry_notice` 仅 original router 可执行，未知身份、未知目标和跨实例
  引用均 fail-closed。
- **整改与验收**：首轮审查发现的 retry identity 未绑定、重放返回旧 `pending`、target 可先重发后记账失败三项缺陷
  均已窄修。最终独立复验为 `codex-team-state` **78/78**、真实产品纵切 **12/12**、关键发送前拒绝回归 **1/1**，
  格式检查通过；详见 `agent_log/2026-08-16-180544-plan039-m2-final-acceptance.md`。
- **边界**：未引入第二套状态、调度器、通信协议、持久化 outbox 或复杂审计设施；未运行全 workspace、Docker、
  真实 API、本地模型或付费测评。

## Local M4 —— 正式三方盲评与人判收口（Plan 041，2026-08-16）

- **人判结论：保留为实验**（`keep_as_experiment`）。决定由用户作出，只作记录：未改动生产默认、provider、
  launcher 或部署开关。body-free 结果锁为 `eval/locks/local-approval-m4-formal-review-v1.json`
  （SHA-256 `4e27d06a…1d89`）。
- **synthetic 主体（130 条，冻结 v1 裁判合同）**：直接消费 Plan 037 已验真的 390 行，未重跑 130×2 推理、
  未重新调用 Sol。两批各 65 条，位置平衡、匿名性与完整集合校验通过。未微调侧教师一致 104/130（80.0%）、
  相对 Opus 误拦 26；微调侧 130/130、误拦 0；两侧漏放均为 0，结构化输出均 130/130 成功；理由被判“弱”
  从 29 降到 5，未被偏好从 29 降到 5。
- **真实 holdout（16 条，独立 cohort 与 aggregate）**：从 Plan 032 冻结批次严格重验后物化——按真实归档重算
  manifest / outbound / prepare-receipt 并要求逐字节一致，再复跑 Plan 032 verifier。两种 Local 使用与 Plan 037
  **完全相同**的 canonical pair（pair receipt SHA-256 `1d57def1…129c`，逐字节一致），在资源互斥门内串行完成
  16×2。未微调侧 14/16 合规判定（2 次结构化输出失败）、有效判定内教师一致 8/14、误拦 6；微调侧 16/16 合规、
  教师一致 15/16、误拦 1；漏放均为 0。synthetic 与 holdout 从不合并分母。
- **两处证据缺口（写入结论的直接依据）**：validation 与 470 条训练数据同源且逐字写明判定线索，故 synthetic
  的高一致率很大程度是线索匹配；holdout 教师标签与裁判独立判断全部为 allow，因此只能检出误拦与可用性问题，
  无法检验过度放行。
- **裁判**：经 Claude Code 订阅入口、人在场的 `claude-opus-5`（2026-08-16）。裁判阶段只读取冻结 prompt/schema、
  judge request 与匿名包，未读 seed、mapping 或模型身份材料；订阅侧模型不由仓库冻结，结论只作时点判定。
  盲评中另发现 10 条冻结 Sol synthetic 目标的理由断言了证据中不存在的具体事实，其结论仍成立。
- **合同变更（用户现场授权）**：真实 holdout 出现 2 个既有结构化失败终态，冻结 v1 包无法表达，故新增
  **holdout 专用** terminal-carrying v2 裁判 prompt/result/summary 合同以完整表达 16/16；v1 三件套未修改，
  synthetic 全程仍用 v1。无判定候选记为 `no_decision`/`not_applicable`，禁止进入偏好，也不当作隐含 deny。
- **现场窄修**：Plan 033 的 shadow 行会让 Plan 032 的 ledger 查找把非 Guardian 运行当成证据运行而 fail-closed；
  holdout 私有 batch id 会经 cohort id 进入裁判包；`local` 的通用英语用法被匿名扫描误判；`python -m` 双重导入
  使 holdout cohort 与 formal 运行的类身份不匹配。四项均已窄修并补回归。
- **验证与现场**：focused unittest **253/253 通过**。本地模型阶段持共享重型锁串行运行，运行后 llama-server 进程、
  监听端口与任务 GPU 显存均已清理，Windows `C:` 实际余量全程在门禁之上。私有逐条输入、模型输出、seed、mapping、
  裁判理由与解盲明细永久留在 ignored `eval-data/cross-eval/20260816-cross-eval-01-synthetic/` 与 `…-02-holdout/`
  （目录 0700、文件 0600），未进入 Git。
- **独立验收**：两轮审查发现的 Multi 状态同步、匿名身份措辞漏检和指标概括失真均已窄修；正式四个 package 与
  四份 judge result 重扫仍为 0 身份命中，146 条判定无需重判。最终 focused unittest **253/253**、
  `git diff --check` 通过，2026-08-17 独立验收确认任务目标完成；详见
  `agent_log/2026-08-17-001729-plan041-final-independent-acceptance.md`。

## Multi M-3 —— 证据锚定（Plan 042，2026-08-17）

**状态**：实现与定向门禁完成，落在工作树分支 `worktree-042-multi-m3-evidence-anchoring`
（提交 `db39e28`、`8360bbf`、`ce32394`、`cfe3dc1`、`35356ab`、`eb53218`），并通过 merge commit
`5783ac0` 合入 `main`。
第三轮独立复验的三项残余 findings 已补修并通过最终独立复验。

- **两步捕获**：Harness 在 dispatch 前为输出预留唯一 item identity，工具处理器产出终态时按该身份记下观察
  （此处才知道跑的是哪个工具、结果什么形状），同一 item 进入
  conversation history 时才铸造 Fact 并按 retention 顺序分配序号。落点是
  `ToolRegistry::dispatch_any_with_terminal_outcome` 的两个终态分支、`ToolCallRuntime` 的 abort 分支
  （宿主要自己顶替回答时先撤销该次 note，否则被打断的调用会变成证据）与
  `Session::record_conversation_items`。未确认保留的观察不铸造任何东西。
- **支持集**：已完成、正式保留、body 为纯文本的工具结果，成功与失败都形成 Fact
  （`tool_result_success` / `tool_result_failure`）。content-item body（媒体载体）、模型消息与推理、
  tool-search 结果、被放弃调用、流式增量、嵌套 code-mode 步骤、团队工具与证据读取自身一律不入集；
  统一排除机制是"没被记下的结果在 retention 时不铸造"。
- **发布窗口**：每个 producer 一个游标。`publish` 在同一次 mutation 内取走本作者上次成功发布之后的新 Fact
  并推进游标，因此被拒绝的发布不消耗证据，按 committed submission 回答的重试报告同一组引用、
  不漂移到之后的观察；重载成员不回退游标，后加入的参与者不继承既有证据，他人证据不进入本作者窗口。
- **权限与边界**：Root 读本团队证据，producer 读自己的，其他人只读自己可见 Event 的某个 Version 显式引用的
  那一条；猜中 ID、同团队 sibling、看见别的 Event ID 与跨实例引用均 fail-closed。新增窄工具 `team_evidence`
  返回 producer、工具名、类别、可用状态、有界文本（4,000 字符上限）与截断信息，不返回调用参数、
  相邻结果或 producer 的其他上下文。TeamState 只持 typed Fact refs，不复制工具输出。Version 保留发布窗口的
  全部引用；上下文预算只作用于打印列表的 surface（投影 4 条、工具结果 32 条），并报告省略数；
  `team_history(evidence_refs_offset=...)` 可继续有界分页取得完整 refs。
- **一对一定位与配对**：预留 item identity 同时用于 pending 配对和最终 locator，不是 call_id —— 后者来自模型请求，
  可并行复用。该身份不需要跨重放稳定，重放要复现的是 Fact 序号与每次发布携带的窗口。
- **诚实退化**：可用状态**每次读取现场判定，不缓存在 Fact 上**。两种读不到的原因分别命名：producer 未加载，
  或 producer 当前 history 已不携带该项（一次普通 compaction 就会造成后者，而 rollout 仍持有它）。
  两者都只陈述 Harness 实际确认到的事，都不写死引用。Version 的 authored 内容不可改写，引用永远留着，
  读取时总能得到显式解释，不出现无标记悬空引用。
- **独立审查整改**：可用状态原本缓存在 Fact 上并在读不到时永久降级 —— 而“不在 producer 当前 history 里”
  正是一次普通 compaction 的结果（rollout 仍持有该项），
  于是例行压缩会把该参与者的全部引用逐条写死，成员重载后还会返回 `unavailable` 与正文并存的矛盾结果。
  另一处：`waits_for_runtime_cancellation` 的工具在 abort 抢到终态后仍会返回结果，宿主丢弃它并用同一 call id
  写 filler，于是被打断的调用变成证据。两项诚实性缺陷均已修正。加固三处：同一 call id 的重复 note 保留第一条、
  Version 引用数量设上限并报告未装下的条数、移除不可达的 join watermark。五处测试质量问题（退化路径无覆盖、
  按字符串排序的伪断言、两处注释过度声称）同批修好。
- **验收审查整改**：发布窗口超过打印上限时，较早引用被游标消费却没有写进 Version —— 永久失去锚点；
  locator 用 `call_id` 匹配，而 call_id 来自模型请求，复用会串线、并在 compaction 后把旧 Fact 静默重定向到
  新文本；pending 暂存上限全团队共用，一个成员的突发会挤掉另一个成员即将保留的结果；`PostToolUse` 拦截后
  正式保留的失败文本没有任何 Fact 可指向。四项均已修：Version 保留窗口全部引用（上限只加在打印 surface）、
  locator 改用 Codex 为每个已保留 item 分配的身份（一对一）、暂存上限按 producer 计并在逐出时告警、
  拦截结果纳入支持集。
- **补充复验整改**：并行重复 call ID 仍因 pending 先到先得而漏 Fact/错配 metadata；工具输出只报告前 32 条 refs
  且没有继续读取路径；同 producer 超过 256 条仍会逐出正式保留前的 note。`eb53218` 改为 dispatch 前预留唯一
  output item identity 并让 note/retention/locator 共用，移除固定 pending 截断，同时为 `team_history` 增加 refs offset
  分页。真实纵切以 33 个本地文本工具结果验证重复 call ID 一成一败各自下钻，并取得第 33 条引用。
- **门禁**：`codex-team-state` **101/101**；产品纵切 `suite::team_evidence` **3/3**；M-1/M-2 回归
  `suite::team_world_state` + `suite::team_routing` **12/12** 无退化；`core` 的 `team::evidence` **6/6**；
  合并 `tools::` 与 `context::` 共 **541/541**；`just clippy -p codex-core`、
  `just fix -p codex-team-state -p codex-core`、`just fmt`、`just fmt-check` 通过。
  补充整改另跑 `codex-team-state evidence` **23/23**、新边界纵切 **1/1**、其余 M-1/M-2/既有 M-3/
  `tools::parallel` **19/19**、`team::evidence` **6/6**，scoped fix 与 fmt-check 通过；未重跑 541 条合并门禁。
- **最终独立复验**：静态复核未发现新的 P0/P1/P2 缺陷，并经共享构建锁独立重跑
  `codex-team-state evidence` **23/23** 与重复 call ID/refs 分页产品纵切 **1/1**；结论为验收通过、任务目标完成。
  详见   `agent_log/2026-08-17-055152-plan042-m3-supplemental-remediation-reverification.md`。
- **边界**：功能默认关闭，关闭时不注册 `team_evidence`、不改变普通工具结果与 rollout 行为。未建 artifact
  store、全量输出副本、完整 transcript/provenance graph、自动 freshness 验证或跨进程持久化；未运行全
  workspace、Docker、真实 API、本地模型或付费测评。执行细节与环境坑见
  `agent_log/2026-08-17-040656-plan042-multi-m3-evidence-anchoring.md`。

## Multi M-4 —— 协调闭合与可观测性（Plan 043，2026-08-17）

**状态**：首次落地 `e03eef1` 至第四轮整改 `def76b6` 均未通过独立验收（最近未通过报告 `8a3d7eb`）。
第五轮整改 `da4b7cd` 已通过最终独立验收，Plan 043 / Multi M-4 任务目标完成，并通过 merge commit
`601de62` 合入 `main`。

- **可用性**：产品分类按显式 `resume_agent` 恢复能力派生——loaded 且 `is_running()` 为 `available`；死驻留与未加载均按 store+history 派生 `recoverable_unloaded` / `unavailable` / `unknown`。store transition 期间一律 `unknown`；snapshot 在现有 gate 下成对采样 generation/active，避免发布原子边界上的双义 epoch。自动 V2 load 仍走单独的 `probe_v2_restore`。
- **退休**：仅 Root；作者在提交时须为 `unavailable`。store delete 用可跨 await 的 active token 夹住删除；token 存活期间 Root 不得退休。app-server `thread/delete` 走同一协议。退休是独立终态覆盖层。同状态 lifecycle 是 no-op。
- **可观测性**：dump cursor `instance:revision:epoch:observe_generation:offset`；跨实例 `InstanceReset`；裸 offset 拒绝。Version→Fact 用独立 `VersionFact` 行分页。Agent 关系行同时带 label 与 `thread_id`。
- **最终独立验收**：静态复核确认 coherent marker 关闭原子边界双义 epoch；经共享构建锁重跑 `codex-team-state --lib` **125/125**、availability **5/5** 与 explicit resume **1/1**。第五轮执行的 M-4 产品纵切 **1/1**、scoped fix 与格式化结果一并采用。未重跑 M-1—M-3、全 workspace、Docker、真实 API 或本地模型。
- **边界**：功能仍随 `team_state_enabled` 默认关闭。未做自动退休、orphan 清理、escalation、产品 UI、跨进程日志持久化或审计链。执行与审查记录见
  `agent_log/2026-08-17-081500-plan043-multi-m4-coordination-closure.md`、
  `agent_log/2026-08-17-082629-plan043-m4-independent-acceptance-review.md`、
  `agent_log/2026-08-17-090000-plan043-m4-acceptance-gap-remediation.md`、
  `agent_log/2026-08-17-091208-plan043-m4-remediation-independent-rereview.md`、
  `agent_log/2026-08-17-093500-plan043-m4-rereview-gap-remediation.md`、
  `agent_log/2026-08-17-094215-plan043-m4-second-remediation-independent-rereview.md`、
  `agent_log/2026-08-17-100500-plan043-m4-third-remediation.md`、
  `agent_log/2026-08-17-101517-plan043-m4-third-remediation-independent-rereview.md`、
  `agent_log/2026-08-17-102800-plan043-m4-fourth-remediation.md`、
  `agent_log/2026-08-17-103327-plan043-m4-fourth-remediation-independent-rereview.md`、
  `agent_log/2026-08-17-104430-plan043-m4-fifth-remediation.md`、
  `agent_log/2026-08-17-105030-plan043-m4-final-independent-acceptance.md`。

## Multi M-5 阶段 A —— 真实运行条件（Plan 044，2026-08-17）

**状态**：首次交付时独立验收不通过（门 1 判据），经两轮整改后于 2026-08-18 复验通过，见下两节。
未跑 Docker、真实 API 或付费调用，**不能**表述为 M-5 通过、门 1 通过或未见退化。阶段 B 未开始。
成果在 044 工作树分支，未合入 `main`、未推送。

- **门 1 载体**：不用 TB `fix-git`。受控 host fixture `eval/fixtures/multi-m5-collab-v1/` +
  `eval/templates/multi-m5/collab-workflow-instruction-v1.md`。完成标准 = `TEAM_REPORT.md` 含 finding
  且六项协作谓词；孤儿退休不是必触发项。Docker 只为门 2。
- **门 2 合同**：P2/B7 v4 十任务，task-major 每题 Codex 然后 Multi；轻 runner，不套 v7 campaign，
  不计算 σ/delta。条件复跑仅「Codex 完成、Multi 未完成」时双方各加两次。最大有效运行 60，infra 总上限 12，
  每槽 3 次，每 run 请求上限 80。价格快照 2026-08-17；硬上限 $120。
- **Runtime bundle**：冻结到
  `eval-data/bin/rondo-multi/7a2ff684c504c7530660f9a33a372daa949bdb00-x86_64-unknown-linux-musl-runtime-bundle/`。
  身份写入 `eval/locks/multi-m5-runtime-v1.json`：CLI sha `2f5f25e0…0c32`（legacy musl CLI），
  host sha `eb54cac2…6705`，bwrap 与冻结 Codex 同资产。测量树 detached 于 ExecPlan 提交 `7a2ff68`。
- **接线**：团队能力单条 inline TOML 只给 Multi；`non_code_mode_only=false`。`just eval-multi-m5-loopback`
  证明 `code_mode_host` 下团队工具可注册并完成 `team_publish` 往返（`counts_as_effective=false`）。
- **门禁**：eval 定向 Python 与 `just eval-lock` 通过；清代理后 team-state + 四个 core team suite **142/142**。
- **任务合同与授权清单**：`plan/044-multi-m5-real-workflow-and-nondegradation-execplan.md`。
  执行日志：`agent_log/2026-08-17-190000-plan044-m5-phase-a.md`。
  独立验收：`agent_log/2026-08-17-210000-plan044-m5-phase-a-independent-acceptance.md`（不通过）。

## Multi M-5 阶段 A 门 1 窄整改（Plan 044，2026-08-17）

**状态**：第一轮整改，复验时发现同类新缺陷（见下节），本节内容已被后续整改继承。未进阶段 B。

- 同一 Event 合取；按真实 dump 顺序分组（Version 行没有 `event_id`）。
- `root_resolved` 只认成员作者 Version；新增 `root_woken`。
- dump 合同改为 harness 捕获的 Responses `function_call_output`（`codex exec --json` 不承载 team_inspect）。
- 成员默认模型 + 隐藏 `spawn_agent` 的 model 覆盖；门 2 归因边界写入不退化锁。
- 执行日志：`agent_log/2026-08-17-220000-plan044-m5-phase-a-predicate-remediation.md`。
- 复验：`agent_log/2026-08-17-233000-plan044-m5-phase-a-remediation-rereview.md`（不通过：证据采集不绑定工具身份，
  `exec_command` 回显即可伪造门 1 通过）。

## Multi M-5 阶段 A 收口 —— 门 1 证据绑定（Plan 044，2026-08-18）

**状态**：门 1 判据三处缺陷全部关闭，**复验通过，阶段 A 收口**。含义仅是「M-5 已具备真实运行条件」，
**不是** M-5 通过、门 1 通过或未见退化。阶段 B 未开始：两道门的 runner 尚未实现，真实 API、付费与
Docker 未授权。成果在 044 工作树分支，未合入 `main`、未推送。

- **证据按产出工具绑定**：dump/log 只采纳 `team_inspect` 输出，唤醒信号只采纳 `wait_agent` 输出；
  其它工具产出的「团队形状」负载记入 `unattributed` 并在判定中忽略，同时经
  `CollaborationVerdict.ignored_evidence` 暴露，便于区分「模型伪造」与「wire 形状变化」。
- **wire 形状已实测**（无 API，冻结二进制 + 本地 stub）：团队工具以 `name=team_inspect` +
  `namespace=collaboration` 调用即可执行，CLI 写回的 `function_call_output` 正文就是真实 dump 负载；
  因此按工具名绑定不会把门焊死。指令模板补 `next_cursor` 续页要求（`MAX_OBSERVE_LIMIT=50`），
  `instruction_sha256` 重算入锁。
- **门禁**：`tests.test_multi_m5` 28/28；完整离线 `just eval-test` 854 项，仅剩 2 项既有 Local 模块加载
  失败（干净 `main` 同样复现，与本任务无关）；`just eval-multi-m5-loopback` 通过。未跑 Rust、Docker、
  真实 API，未产生费用。
- **独立复验**：`agent_log/2026-08-18-010000-plan044-m5-gate1-attribution-rereview.md`（通过）。
  正向通路首次实测确认：真实 `team_inspect` 输出被正确归属，采到 6 行真实 dump、`unattributed` 为空；
  Root 独角戏与伪造回显两个反例均被拒。
- **付费前置**：门 1 runner、门 2 交错执行面、预算记账与归档落盘均**未实现**；按复验决议，
  这些部件实现后须再过一次独立审查，通过后才申请真实 API/付费授权。

## Multi M-5 阶段 B 离线前置准备（Plan 044，2026-08-18）

**状态**：阶段 B 的离线前置准备完成，**门 1 整条链路在花钱之前已验成绿的**。真实付费、真实 API 与 Docker
仍未授权、未执行，**不是** M-5 通过，也**不是**门 1 通过。成果在 044 工作树分支，未合入 `main`、未推送。

- **五项交付物**：门 1 host runner（`gate1.py`/`command.py`/`capture.py`）、门 1 离线彩排 stub
  （`rehearsal.py`）、门 2 轻量交错执行面（`gate2.py`，真实执行器 fail-closed）、$120 预算记账
  （`budget.py`，批次 `multi-m5-phase-b`，硬上限在代码里）、归档落盘（`store.py` →
  `eval-data/multi-m5/archives/records.jsonl`）与就绪自检（`ready.py`）。入口：
  `just eval-multi-m5-{rehearsal,ready,gate2-fake}`。
- **门 1 彩排**：冻结二进制真跑、stub 只替代模型侧，**连续五次全绿**，请求数稳定 16。
  真实 canonical 状态经独立复核：真 spawn 出 `/root/worker`，同一 Event 三个 Version 跨两位作者，
  证据由成员真实 `exec_command` 结果铸成并挂在成员 Version 上，route 已投递，Root 把成员作者的 Version
  置 `resolved`，变更日志的 `member_publish` / `root_does_not_self_wake` / `assignment_wakes_target`
  逐条成立，`wait_agent` 返回真实 TeamActivity 原文。M-1/M-2/M-3 在一次真实纵切里全部被触发。
  记录标注 `evidence_kind=loopback`、`rehearsal=true`、`counts_as_effective=false`。
- **本轮修复三处**：门 2 被重试掉的 infra 尝试不再从归档消失（原先每槽只留最后一条，导致"infra 未计入
  有效结果"无法核对）；`Gate2Error` 改为计入 infra 预算并按上限重试（原先绕过总上限 12）；
  二进制哈希缺失时不再回填占位值，改为 fail-closed。
- **门禁**：`tests.test_multi_m5` + `tests.test_multi_m5_exec` 39/39；完整离线 `just eval-test` 865 项
  （基线 854 + 新增 11），仅剩既有的两项 Local 模块加载失败（干净 `main` 同样复现，属另一任务）；
  `just eval-multi-m5-ready` `ready=true`；fake 门 2 20 槽位调度、记账与归档正常。未跑 Rust、Docker、
  真实 API，未产生费用。
- **付费前仍缺**：门 1 付费入口（预算代理 + forward 捕获接成付费运行函数）与门 2 真实执行器
  （走既有 `terminal_bench` adapters/runner/results）。按阶段 A 收口的 F3 决议，二者实现后须先过独立审查。
- **独立审查不通过并已整改**：冻结指令模板按字面执行必然过不了 `two_authors` —— Root 全程不发布
  Version，而 `team_update` 只改生命周期、不产生 Version；彩排全绿仅因 stub 多做了一次模板未要求的
  Root 发布。已在冻结二进制上实测复现（唯一失败原因 `predicate:two_authors`，其余六项全过）。
  模板补入 Root 在同一 Event 发布的步骤、重算 `instruction_sha256`
  （`b11136af…` → `b0925723…`），新增两条回归把模板与判据绑定（已验证能抓住旧模板）；
  另就地修掉 `gate2` 把 `evidence_kind` 写死为 `fake` 的付费陷阱并加 fail-closed 守卫。
  整改后彩排复跑全绿，离线套件 868 项、除既有 2 项外无新增失败。
- 执行日志：`agent_log/2026-08-18-030000-plan044-m5-phase-b-preparation.md`、
  `agent_log/2026-08-18-070000-plan044-m5-template-predicate-remediation.md`；
  审查报告：`agent_log/2026-08-18-050000-plan044-m5-phase-b-prep-review.md`。
  模板整改复验通过：`agent_log/2026-08-18-090000-plan044-m5-template-remediation-rereview.md`。

## Multi M-5 阶段 B 付费入口接线（Plan 044，2026-08-18）

**状态**：门 1 付费运行函数与门 2 真实 Terminal-Bench 执行器已落地，**仍锁在授权门后**。未跑真实 API、
未拉/跑 Docker、未产生费用。独立审查先因门 2 `$8`/`$24` `ensure_run` 冲突判 FAIL，已修并复审通过。
**不是** M-5 通过，也**不是**已授权花钱。成果在 044 工作树分支，未合入 `main`、未推送。

- **门 1**：`run_gate1_paid` 在冻结二进制上走 CaptureProxy(forward, 180s 流式、保留 User-Agent) →
  环回预算代理（单次上限 $24、请求预留 $8）→ HTTPS provider。超时或空捕获落 `infra_failed` /
  `evidence_kind=real_api`。无授权口令时 CLI 退出 78，不加载 `.env.local`。
- **门 2**：`TerminalBenchSlotExecutor` 构造无 campaign / 无 preflight 的 `TerminalBenchRequest`，
  经既有 `prepare_terminal_bench_run` / Harbor / `parse_single_task_result` 跑一槽；Docker 未授权则
  fail-closed。`run_gate2_real` 显式 `evidence_kind=real_api`、`charge_fake_usage=False`，单次上限 $8、
  请求预留 $2。脚本执行器不能冒充 `real_api`。
- **授权**：冻结口令只存在于 `paid.py`；`just eval-multi-m5-gate1-paid` / `gate2-real` 永不转发口令。
- **门禁**：`tests.test_multi_m5` + `tests.test_multi_m5_exec` **49/49**（含彩排）。未跑 Rust、Docker、
  真实 API，未产生费用。未跑完整 `just eval-test`（既有两项 Local 导入失败与本任务无关）。
- **审查修复**：预算代理新增 `run_cap_usd`；门 2 真实槽位与编排器同用 $8；漏传 cap 的回归
  `test_budget_proxy_keeps_the_gate2_eight_dollar_run_cap`。
- **独立验收（2026-08-18）**：通过，但先在预算层查出三处只会在真花钱时暴露的缺陷，已由审查者窄修 +
  各钉一条反向回归：①门 1 可用额度是 `cap − 2×预留`（Guardian 附加容量），`$8` 预留把门 1 掐在 `$8`，
  正好等于冻结点估计，实测第 21 请求即耗尽（累计 `$8.19`）→ 预留改 `$4`，额度回到 `$16`；
  ②代理对耗尽的 run 就地回 429 不抛异常，掐断被记成 `agent_failed`，门 2 还 `counts_as_effective=true`
  直接污染退化判据（Multi 成本更高，系统性偏向"退化"）→ 新增 `run_stop_reason`，两道门都落
  `budget_stopped`，门 2 不计有效并停批；③共享账本槽位按 `60+12` 算，没给门 1 的 3 次尝试留位 → 改 `75`。
  门禁：`test_multi_m5` + `test_multi_m5_exec` + `test_api_budget_proxy` + `test_terminal_bench`
  + `test_terminal_bench_results` + `test_binary_freeze` **237/237**，`just eval-lock` 通过。
- **最终独立验收（2026-08-18）**：通过。又查出三处只在真实运行才显形的问题，均已窄修 + 各钉一条
  已验证的反向回归：①真实 TB 槽位把 `request_count` 写死成 1，归档数字失真且冻结的「每 run 80 请求」
  上限成为死代码（代理层 `max_logical_requests` 被校验成 `1..4`，拦不住）→ 新增 `run_request_count`
  从账本读真实逻辑请求数，超限落 `infra_failed` 且不计有效；②`_UrllibTransport` 的 test-only
  `endpoint_override` 被宿主 `HTTP_PROXY` 劫持（Python 的 `no_proxy` 不认 `127.*` 通配），
  离线捕获链在用户日常 shell 里假失败 502 → 只在 override 时挂空 `ProxyHandler({})`，生产 env 行为不变；
  ③门 2 真实批次 `require_frozen=False`，bundle 不在位要烧完 12 次 infra 才停 → `real_api` 时第一槽前即失败。
  门禁：上述六个套件 **240/240**，`just eval-lock` 通过。**Python 门禁须在清掉
  `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 的环境下跑。**
- **第三轮独立终审（2026-08-18）**：判「不通过，暂不应授权付费」，列 6 项阻断，复核**全部属实**，已全部关闭
  并各钉一条已验证的反向回归：①门 2 只看 `stopped` 决定退出码，退化结论、`uncertain`、证据不完整都可能退出 0，
  且不打印 `verdicts` → 新增 `gate2_passed`（未停批 + 十任务齐全 + 全部无退化）；②「每 run 80 请求」是事后分类，
  第 81 次仍会真实发出并计费（代理的 `max_logical_requests` 被校验成 `1..4`，用不了）→ 新增 `RequestCappedLedger`
  在 `reserve()` 硬拦，停止原因与「钱不够」分开（钱停批、请求上限停槽）；③付费配置未绑定冻结合同 —— 预算代理用
  可变 `rondo.local.toml` 的费率给 $120 记账，实测快照日期已漂移（锁 `2026-08-17` vs 配置 `2026-08-11`，费率一致）
  → 新增 `require_frozen_provider` 逐项核验并把生效身份写进每行归档；④Docker 的 80GiB/60GB 硬停止被压成
  `Gate2Error` 并重试 → 新增 `DockerResourceStop` 子类，门 2 立即停批；⑤Harbor 的 `docker_evidence` 未进归档
  → 新增 `docker_summary` 有界投影；⑥门 1 载体只是协议演示（答案写在 fixture 里、指令规定工具顺序）→ 按决策 032
  **保持冻结载体**，改为把边界写进 `eval/locks/multi-m5-workflow-v1.json` 的 `scope_limits`、子 WBS 与本节：
  WBS 的「真实任务上跑通完整协作语义」须门 1+门 2 合起来读，任一门单独不得引用。
  次要项：门 1 通过增加 `returncode==0`（实测彩排 rc=0，只会把通过变失败）、付费行绑定 `harness_commit`/`harness_dirty`、
  `.gitignore` 补全局 `__pycache__/`。不改项：不强制门 2 依赖门 1（§1 明写两门独立）、不改 `base_order`
  （顺序偏差利于 Multi，只会让退化判定更保守）、退化诊断槽位仍按决策 021 不预跑。
  门禁：**292/292**（新增 `test_docker_supervisor`），`just eval-lock` 通过，worktree 干净。
- **第四轮终验（2026-08-18）**：判「不通过」，列 2 项阻断 + 2 项伴随缺口，复核**全部属实**，已全部关闭
  并各钉一条已验证的反向回归：①请求上限不是并发硬边界 —— `snapshot→判断→reserve` 是 TOCTOU，
  预算代理跑在 `ThreadingHTTPServer` 上且 Multi 的 Root/成员并发，实测上限 8 被冲到 13
  → 包装层加 `threading.Lock` 合成单一临界区（该包装层是真实槽位里交给代理的唯一 reserve 路径）；
  ②付费 endpoint 未冻结 —— 校验函数只把 `base_url` 记进归档却从不比较，锁里也没这一项，同名 provider
  换 endpoint 密钥与数据即流向未批准地址 → 锁新增 `provider_base_url` 并逐字校验、缺失即 fail-closed，
  门 1 独立传入的 `upstream_base_url` 一并绑定；③`DockerResourceStop` 携带的 samples 被丢弃（撞线那一刻
  证据最该留下）→ 新增 `docker_stop_summary`；④`image_reference` 读了不存在的 `reference` 属性恒为 null
  → 读正确字段并补 `image_id`。
  门禁：**297/297**，另因改动锁 schema 加跑 `test_config_hardening` + `test_contracts_and_evidence`
  + `test_fair_comparison` **124/124**。终验替用户作出的决策（门 1 载体、口径边界、两门独立但先门 1 后门 2、
  Codex-first 与诊断后置、结论只能说"小样本中未观察到稳定单向退化"）与已冻结内容一致，无异议。
- 执行日志：`agent_log/2026-08-18-110000-plan044-m5-paid-entries.md`；
  验收报告：`agent_log/2026-08-18-130000-plan044-m5-paid-entries-acceptance-review.md`、
  `agent_log/2026-08-18-150000-plan044-m5-paid-entries-final-acceptance.md`；
  终审整改：`agent_log/2026-08-18-170000-plan044-m5-paid-boundary-remediation.md`、
  `agent_log/2026-08-18-190000-plan044-m5-paid-boundary-remediation-2.md`。

## Multi M-5 正式门前 runtime-v4 收口（Plan 044，2026-08-20）

**状态**：runtime-v3 的递归证据/分页假绿已关闭，runtime-v4、两把 v5 门锁、离线验证、唯一一次真实
clean-smoke-v5 与独立后审全部完成。这里只记录门前开发成果；正式门 1/门 2 未启动，**不是** M-5 通过、
门 1 通过或“小样本未见退化”。

- 产品修复提交 `0eee6dc`；共享 build-lock Rust 146/146。runtime-v4 的 CLI/host/bwrap/manifest 摘要与
  clean measurement tree 一致；合同提交 `b078e28` 固定 workflow-v5→runtime-v4→nondegradation-v5。
- `just eval-lock`、Python M-5 定向 136/136、ready、loopback 通过。rehearsal 20/20 dispatch 均为 code cell、
  0 Direct；dump 7 页/log 2 页到 null，七谓词与成员自身证据链成立。
- clean-smoke-v5 只运行一次：20 请求全部 usage-priced/settled，计价 `$0.273138`、保守暴露 0、零 taint；
  明文 16/加密与未知 0，七谓词全真。真实 trace 18/18 dispatch completed、0 Direct，成员 exec Fact 被成员
  Version 引用并由 `team_evidence` 读回。
- 独立预审与付费后审均为 GO、无 P0/P1。正式归档仍为 26 行且哈希未变；`multi-m5-phase-b` 账本/锁不存在，
  Docker 未运行。完整证据见
  `agent_log/2026-08-20-100000-plan044-m5-runtime-v4-prebuild-remediation.md`。

## Multi M-5 v6 正式付费前设施整改（Plan 044，2026-08-20）

**状态**：后续独立审查确认 v5 仍有协议假绿、capture 身份串线、provider 预检过晚和不可恢复中断四类缺口；
v5 的门前 ready 结论因此作废，但其 rehearsal/smoke 历史不改写。整改只改变 eval 合同与执行设施，产品字节未变，
继续复用 runtime-v4。正式 Gate 1/Gate 2 仍未启动，**不是** M-5 通过或不退化结论。

- 新冻结 workflow-v6 / nondegradation-v6：Gate 1 最多 6 次；Gate 2 每槽最多 5 次 infra、全批最多 40 次；
  共享槽位 `60 effective + 40 infra + 6 Gate 1 + 10 diagnostic = 116`；80 requests/run、5 HTTP attempts 与
  `$120` 硬上限不变。点估计 `$10.40`，最坏调度形状预测 `$67.80`。
- Gate 1 机械验证成员两次 Version 之间真实完成自身 exec Fact 的 `team_evidence`，并要求 Root publish、route、
  completed wait TeamActivity 的顺序链；测试 capture、v6 rehearsal 与正式 capture 完全隔离。
- provider 全量冻结提前到任何正式 receipt/ledger/claim 之前。正式 resume 绑定 batch、两把锁、runtime 与
  provider receipt；完整归档跳过，pristine run 安全重领，已请求未归档只追加一次 abandoned infra，未来或冲突
  状态 fail-closed。Gate 2 attempt 在 claim 下一 id 前立即持久化，正常模型失败保持产品分类。
- 最终定向 Python 162/162、`just eval-lock`、ready、loopback 通过。全新 canonical v6 rehearsal 20/20 dispatch
  全为 code cell、0 Direct/failed；dump 7 页/log 2 页到 null，明文 9/加密与未知 0，严格协议链和七谓词全真。
  正式 v6 archive、ledger、identity receipt 均未创建。
- 审查与整改证据见 `agent_log/2026-08-20-110000-plan044-m5-paid-readiness-independent-review.md` 与
  `agent_log/2026-08-20-120000-plan044-m5-v6-paid-readiness-remediation.md`。

## Multi M-5 v6 正式门前恢复与协议再验收（Plan 044，2026-08-20）

**状态**：13:00 独立验收发现的协议假绿、终止预算停止误分类和首请求前自有产物恢复死路均已关闭；
append-only v6-r2 rehearsal 与独立终审通过。这里只记录门前设施进展；正式 Gate 1/Gate 2 未启动，
**不是** M-5、Gate 1 或不退化结论。

- Gate 1 现在以 rollout manifest、trace start/end 和完整 inspect-log revision 共同绑定 Root
  wait/publish/route/update、成员 evidence 以及不同的二次 Version；乱序、错误 actor、复用 Version、失败或缺失
  update 均有反例并 fail-closed。
- resume 先保留 ledger 的 terminal budget/capacity stop，幂等归档为 `budget_stopped` 后停止；精确白名单内的
  pre-Harbor 零请求自有产物只追加一次 abandoned infra。未知、错型、symlink、exact trial dir 或 exact-label
  Docker/Compose 残留继续 fail-closed，等待受监督精确清理，不做无证据自动删除。
- 串行 M-5 Python 179/179、Docker resume 精确探针 29/29、`just eval-lock`、ready 与 loopback 通过。
  `m5-g1-rehearsal-v6-r2` 追加到独立 archive：20/20 dispatch 均为 code cell、0 Direct/failed；dump 7 页、
  log 2 页到 null；明文 9、加密/未知 0，七谓词与完整 update 链全真。
- workflow-v6 / nondegradation-v6 继续复用未变化的 runtime-v4；v5 历史不改写。正式 v6 archive、ledger、
  identity receipt 与 paid capture 均未创建，本轮未运行 Docker、Rust 或真实 API。
- 形成时点 NO-GO 与最终整改证据分别见
  `agent_log/2026-08-20-130000-plan044-m5-v6-remediation-independent-acceptance.md` 和
  `agent_log/2026-08-20-140000-plan044-m5-v6-remediation-final-readiness.md`。

## Multi M-5 v6 canonical mutation 再收口（Plan 044，2026-08-20）

**状态**：15:00 独立验收发现的幂等 publish 假绿与跨线程 wrapper 假阴均已关闭；append-only v6-r3
rehearsal 通过。正式 Gate 1/Gate 2 仍未启动，**不是** M-5、Gate 1 或不退化结论。

- 协议中的 first/Root/second publish 与 route 必须明确 `deduplicated=false`；evidence 后只重试旧 Version
  不再被误计为新成员 Version，缺字段、非布尔与 `true` 均 fail-closed。
- canonical mutation 顺序改由精确 inspect-log revision 证明；wrapper end 不作跨线程提交时钟，同 actor 仍用
  end/start，wait 另用端点证明重叠，route start 必须先于 evidence start。
  Root wait 与首次成员 publish 以区间重叠、精确 wake log 和 TeamActivity 返回绑定，因此 store 已提交但另一线程
  wrapper 尚未写 end 的三类合法交错不再误杀。
- 批量 `team_update` 允许同批其它目标及同一 Version 的独立 producer 轴更新，但协议只能唯一匹配一个成功
  resolve 的成员 Version；两个成员 resolve、重复、错状态或错 ID 继续拒绝。
- 最新串行 M-5 Python 183/183、相关窄回归 105/105、`just eval-lock`、ready、loopback 均通过。
  `m5-g1-rehearsal-v6-r3` 为 23 requests、20/20 code-cell、0 Direct/failed、dump 7 页/log 2 页、明文 9、
  加密/未知 0，七谓词全真；历史 v6/v6-r2 行和 raw 均保留。
- 正式 v6 archive、ledger、identity receipt 与 paid capture 仍未创建；未运行 Docker、Rust 或真实 API。
  形成时点报告与收口日志见
  `agent_log/2026-08-20-150000-plan044-m5-v6-second-remediation-independent-acceptance.md` 和
  `agent_log/2026-08-20-160000-plan044-m5-v6-canonical-mutation-final-readiness.md`。

## Multi M-5 v6-c2 纯执行环境门禁（Plan 044，2026-08-20）

**状态**：首个 v6-c1 正式 Gate 1 的 6 次运行均在模型输出前被开发 sandbox 阻断，本地正确归档为 infra，
不是产品结论。保持 workflow-v6 / runtime-v4 / nondegradation-v6 字节不变，新增轻量 v6-c2 campaign generation。

- c1 ledger/receipt/archive 摘要与 6 条连续 infra、6 request 全 settled、priced `$0`、conservative `$13.32`、
  无 Gate 2 的语义在 c2 启动前 fail-closed 核验；用户确认中转站实际账单 `$0`。
- c2 独占 receipt/ledger/archive/capture/run-id，正式身份再绑定 clean harness commit。c2 ledger cap `$106.68`，
  与保留的 c1 `$13.32` 暴露相加严格等于共享 `$120`。
- 同进程无密钥 direct GET 在所有正式状态、secret 与 Docker 前执行，禁 auth/body/proxy/redirect。sandbox 内 rc78
  且零 c2 资产；批准的 sandbox 外得到 HTTP 301 并通过。真实 Responses 请求一旦启动，usage 不明仍消耗 attempt。
- 零费用门禁：M-5 定向 193 项、`just eval-lock`、ready、runtime-v4 loopback 已验证；未运行 Rust、Docker、
  API smoke 或付费模型请求。

## Multi M-5 c3 正式两门验收（Plan 044，2026-08-20）

**状态**：workflow-v6 / runtime-v4 / nondegradation-v6 行为合同未变；c3 Gate 1 与 Gate 2 正式通过，独立终审
重放 resume、调度与 verdict 后给出 GO。Plan 044 的开发与验收目标完成，分支尚未合入 `main`。

- collector 精确接纳 code-mode runtime 的默认 `wait` continuation 后，c3 Gate 1 a2 以 22 请求完成：七谓词
  全真、`team_evidence=true`、明文 14 / 加密与未知 0。a1 的单次 `upstream_unavailable` 保持 infra 分类。
- Gate 2 在十个锁定镜像上串行完成 20 个基础有效 run：4 对双方通过、6 对双方失败，零 Codex-only 完成，
  因而没有条件复跑或诊断；十题均为 `no_stable_one_way_degradation`。冻结的 60 是最大容量（基础 20 +
  条件最多 40），本次 20 是合同正确终态。
- c3 ledger 22 runs、237/237 request settled、0 held、最大 attempt 1；Gate 2 的 199 个 usage-priced 请求计价
  `$3.248131`，c3 总暴露 `$5.840974`。加 prior `$13.981683` 后，跨代保守口径为 `$19.822657 < $120`。
- 20/20 Docker 记录 returncode 0、无 warning、`cleanup_verified`；峰值 Docker 增长 2.556GB、VHDX 增长 0，
  最低 Windows `C:` 余量约 190.835GB。结束后无任务容器、网络、卷或 build cache 残留。
- 正式运行提交 `c9fcb0fb1cd57254558e811ecddfab65e2c452df` 上的 `just eval-lock`、
  `just eval-multi-m5-ready` 与独立后审通过；receipt、provider、二进制、全部归档均绑定该 clean HEAD。后继提交
  仅收口文档，不是 c3 的可恢复运行身份。完整执行证据见
  `agent_log/2026-08-20-210000-plan044-m5-v6-c3-formal-final.md`。

## RONDO Multi 第一期总收口（2026-08-20）

**状态**：第一期产品与验收目标全部完成。Plan 044 的 P2 文档修正提交为
`eae16904bfa321425fbe8ada16263634f255564a`，最终通过 merge commit
`a220b77488f48a40474cf14261b3961fcf520213` 合入并推送 `main`；此前各条目中“分支尚未合入”的表述是对应
形成时点的历史状态，不改写。本条记录后续正式交付事实。

第一期从产品基线到真实验收形成了完整纵向能力：

- 产品基线建立独立的 `multidev/` 身份、默认关闭与 Local 隔离合同；既有完成证据见 Plan 022 条目。
- M-1 交付 Team State、Event/Version、双生命周期、活动投影、revision/retry 与 wake 纵切，通过
  `bcad5b22ca5cb226ff7bed15fec64aa8ddecf84b` 合入；这是此前 COMPLETED 缺失的独立收口索引。
- M-2 交付选择性 route、assignment 与通知投递分离，通过
  `dbeba04168632019a564f199837d35012f59a0d6` 合入。
- M-3 交付 Fact 与 retained observation 的机械绑定、Event 可达权限和诚实不可用语义，通过
  `5783ac0e798508ec730a886ffa45608b9388cca7` 合入。
- M-4 交付 producer 可用性、Root retire、恢复边界及有界 inspect/dump/log/stats，通过
  `601de62e1ff2ec7af0ecc9941b2ba3686cda7d01` 合入。
- M-5 完成“协作链真实激活”和“小样本无稳定单向退化”两道独立验收门；逐批设施整改、失败历史及正式证据见
  本页前述 Plan 044 条目和冻结日志，不在当前 WBS 重复维护。

M-5 正式结果如下：

- Gate 1 的 c3 a2 在 22 个请求后七项谓词全真，`team_evidence=true`，明文 evidence 14，
  加密/未知 0；a1 的单次 `upstream_unavailable` 保持 infra 分类。
- Gate 2 完成 20 个基础有效 run：4 对双方通过、6 对双方失败、0 个 Codex-only 完成（Codex 完成而 RONDO
  失败），因此无需条件复跑；
  十题均为 `no_stable_one_way_degradation`。冻结合同中的 60 是基础 20 加条件最多 40 的最大容量，
  不是固定运行数。
- 正式运行身份保持在 `c9fcb0fb1cd57254558e811ecddfab65e2c452df`；后续文档与 merge 不改变 receipt，
  不创建新 campaign，也不重跑付费样本。
- c3 账本 237/237 request settled、0 held，暴露 `$5.840974`；跨代保守合计
  `$19.822657 < $120`。Gate 2 的 20/20 Docker 清理记录成立，最终无任务容器、网络或卷残留；
  两轮独立终审均无剩余 P0/P1。

**能力边界**：第一期证明的是在 `medium` 且明确协作指令下，RONDO Multi 的完整链路真实可达，并在该冻结
小样本内没有观察到稳定单向退化。它没有证明自然真实任务中的 Root 会主动 `spawn_agent`，也没有证明
RONDO 相对冻结 Codex 带来质量、速度、token 或成本收益。该缺口由当前 Multi 第二期的 Team Lens 与后置主动
委派收益测评承接；当前路线只在 `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md` 维护。

## RONDO Multi 第二期 A/B 工程包收口（Plan 047/048，2026-08-20）

**状态**：两个并行工程包均已完成实现、独立验收和统一整合。A/B 从同一 `main@7ba7eb65…` 基线开发，写集没有
重叠；最终分别通过 merge commit `df74082`、`59fab50` 保留完整提交历史并合入 `main`。执行细节与审查往返留在
对应冻结 plan 和 agent log；当前后续路线只在 WBS 维护。

### Plan 047：Team State 序列性质测试

- 在现有 `codex-team-state` crate 内加入默认 ignored 的有限性质测试、薄 reference state、固定 seed 和唯一主动
  `just team-state-sequence-properties` 入口；核心操作覆盖 publish、producer/Root 双生命周期、route、delivery、
  retry 与 wake，未新建 crate、runner、corpus 或通用 fuzz 设施。
- 默认合同为 64 cases、每 case 最多 32 个候选步骤、默认 seed `20260820047`。动态 selector 始终从当前 canonical
  绑定解析；不适用变更操作不会改变 reference/store/revision/wake，只读观察用于核对前后状态。
- 最终验收：默认门禁 128 passed、1 skipped，性质测试保持 ignored；主动入口 1 passed。invariant checker 自测、
  固定 seed 复现、依赖/锁一致性和定向 lint 均已有记录。未发现 Team State 产品缺陷，产品语义代码未修改。
- 实现提交 `b0a8db079a642a5ea965b2ff789c5460359c5eff`；最终验收报告提交
  `7eaa8f28ce7d9575ca65a4a793fe88b525b9cec6`，报告为
  `agent_log/2026-08-20-094034-plan047-final-acceptance-review.md`。

### Plan 048：RONDO Team Lens

- 交付本地离线 Team Lens：同一消费者按显式产品身份读取冻结 Codex/RONDO 原生 v1 rollout bundle，白名单归约为
  确定性、body-free 的 `team_view.json`；静态报告器只消费该合同并生成自包含、无需网络的单文件 HTML。
- 四态 capability、原生 reader 必需错误、Agent/turn/inference/tool/terminal/interaction 语义、Team
  Event/Version/Route/Fact 关系和统一时序均有定向回归。Codex 的 Team State 诚实标为 `not_applicable`；报告不复制
  prompt/response、命令输出、Fact 正文或 raw trace 路径。
- 最终验收：25/25 定向测试通过；24/24 个代表性 RONDO bundle 均可归约，JSON/HTML 重复生成字节一致；CLI、内嵌
  JavaScript、body-free 与降级语义检查通过。冻结 Codex 侧采用结构忠实且明确标记的合成原生 fixture。
- 零 hook 证据足够，因此没有修改 Rust runtime、Team State 或 trace writer，也没有新增前端 toolchain、Docker、API、
  模型或全量测试。关键语义返修提交 `78736a7ec2c6d37fdad74ae30fdbf682e4801ec1`；最终验收报告提交
  `7e8ef8ee80a492e0fcc49fe3467d5e75d5812505`，报告为
  `agent_log/2026-08-20-110755-plan048-team-lens-reacceptance-review.md`。

## RONDO Multi 第二期后置主动委派测评（Plan 049，2026-08-20）

**状态**：阶段 A 无费用设施与阶段 B 固定 activation pilot 均完成。阶段 B 的正确结论为“当前共同 policy 与固定
pilot 任务未激活 Root 主动委派”，因此按预先冻结的停止门没有运行正式十题，不能形成 Team State 委派收益结论。

- 阶段 A 建立两侧共同 Multi-Agent V2、同模型/effort/并发/policy、确定性 schedule、body-free archive/Team Lens、
  持久预算与 fail-closed paid/resume；多轮独立审查关闭原则性停止、重复费用、身份前缀、工具投影与分类缺口。
- 首个 paid Codex 槽因 Guardian 形成第二个原生 root bundle 暴露单-bundle locator 缺口。Plan 049 selector 随后机械要求
  唯一 Exec Root、允许身份明确的 Guardian，并让 Team Lens 只消费 Root；RONDO 同构路径也纳入回归。
- 新 recovery identity 只读承接旧 a01、15 个已结算请求和 `$0.262759`，没有 a02 或 provider 重放。随后六个固定 pilot
  全部以 attempt 1 完成：2 个成功、4 个有效任务失败、0 infra、100 个 usage-priced 请求，累计 `$2.533684`。
- 六槽的 Root spawn attempt/accept 均为 0，故 `activation_observed=false`。追加机动预算没有被实例化或消费；不通过
  事后追加有效 pilot、换题或强制 spawn 改写阴性结果。完整代码、运行、资源和未运行项见
  `plan/049-multi-proactive-delegation-eval-execplan.md` 与
  `agent_log/2026-08-20-231500-plan049-phase-b-final.md`。

## RONDO Multi 明确委派三任务案例（Plan 050，2026-08-21）

**状态**：阶段 A/B 已完成并通过修复后独立验收。冻结 Codex 与 RONDO Multi 在同一 `gpt-5.6-terra/high`、明确
collaboration policy、任务、并发、deadline、Docker 和 task-native verifier 下完成三题六槽比较；唯一产品差异为
RONDO Team State。结果只构成冻结三题的条件性案例，不估计总体成功率、自然委派率或 Team State 单因素因果收益。

- C01 `sqlite-db-truncate` 与 C02 `headless-terminal` 两侧均 `completed`；C03 `extract-elf` 两侧均
  `task_failed`。C01 RONDO 为 `collaboration_observed / not_observed`，C03 RONDO 为
  `collaboration_observed / observed`，其余四槽为 `policy_noncompliance / not_observed`；外部结果优先，过程判读不证明
  成员贡献内容质量或因果收益。
- 正式 100 USD 账本共 13 attempts、165/165 settled requests。七个 relay 加密内容/流错误保留为 infra invalid；
  六个有效槽位费用 `3.156021 USD`，含 12 个 unknown-usage 保守 reservation 的总账为 `30.307445 USD`，无悬空状态。
- 原聚合遗漏 completed member-to-Root `send_message` 返回形态；窄修后仍独立要求 accepted Root spawn、实质成员活动和
  typed contribution return。75 项定向测试为 73 通过、2 个约定 skip，37 个正式值通过 body-free/schema 校验，
  finalizer 重入 digest 不变。
- 修复候选 `f4854ec` 经干净上下文独立复验 PASS，无剩余 correctness finding。执行、失败复验、修复与最终复验报告分别见
  `agent_log/2026-08-21-060000-plan050-phase-b-final.md`、
  `agent_log/2026-08-21-062443-plan050-phase-b-reacceptance.md`、
  `agent_log/2026-08-21-063528-plan050-phase-b-collaboration-return-remediation.md` 与
  `agent_log/2026-08-21-064519-plan050-phase-b-collaboration-return-rereview.md`。
- Plan 050 的语义化协作展示可从既有本地原始证据离线重建，无需重跑付费槽位：保留 ignored
  `eval-data/plan-050/paid/plan-050-paid-v1/`，从各有效 run 的 `rollout-trace/trace.jsonl` 与 `payloads/` 按
  `seq`、agent/thread 和 typed interaction 关联 spawn、`send_message`、`agent_result`、`team_publish`（含
  `title/summary/handoff`）及 `team_update`，再与 verifier、usage 和费用终态合并生成新页面。现有
  `team_view.json`/HTML 是 body-free 投影，不能单独恢复交接正文；当时未采全的 Fact metadata、route 与 attention
  字段也不得事后补造。若原始 ignored 目录被删除，语义正文将无法从受跟踪产物恢复；仅为改善现有 handoff 展示不需要
  重跑，只有补采缺失字段或取得新的成功案例才需要另立运行。

## 方向 0 首次 schema v7 正式 canary（Plan 051，2026-08-21）

**状态**：稳定入口、冻结 bundle、无 API 预检、正式运行、聚合、结算、结果发布和资源清理均完成。产品基线固定为
RONDO Local `54f62e5f7e86a7ab0d4f8d788eafec7176809395` 与 Codex
`v0.147.0@be6e8eac029b183056b7e4402879f15d2c85f61b`；双方 main 为 `gpt-5.6-terra/medium`，双方
Guardian 为 `gpt-5.6-terra/low`。

- schema v7 增加显式 runtime bundle、跨 successor 的 400 USD task envelope、可靠 usage / 1 USD fallback /
  provably-unsent 0 USD 三分法、wire 有界重试、崩溃恢复与稳定 `just eval-plan051` 入口；默认动作不发送请求。
  外部验收发现首版入口仍把 Local commit 与唯一 Plan 051 envelope 固定在 loader 中；收口后同一入口可显式初始化
  新 Local commit/manifest、campaign/batch、价格日期和独立授权 task budget，新 envelope 不覆盖 Plan 051 历史，
  付费确认绑定新 budget ID。
  Local bundle 走共享构建锁与看门狗从冻结源码构建，manifest SHA-256 为 `de414d3f...`；Codex 既有 bundle
  manifest `e13a9d0f...` 自包含校验通过，未重建或升级上游。
- v23—v26 在零 API preflight 阶段依次暴露并关闭本地 projection/verifier/supervisor 适配缺口，费用均为 0。
  v27 的 20-side stub/10-receipt 通过，正式 wire 与首个 RONDO 槽可靠结算后暴露 v7 结果发布 schema 缺口；旧
  identity 以 `$0.270445` 原子退役，未发送新请求。修复保持 v1—v6 历史 pair schema 严格不变，并以 v28 接续。
- v28 完成 1 个 wire 与 40 个基础产品槽，400/400 个上游 attempt 均有可靠 usage；10/10 共同有效任务中 Local
  的两轮 A/A 与一轮 A/B、Codex A/B 均为 5/10，`sigma=0`、`base_delta=0`、`delta=0`，无条件题，A/A、cross-side、
  directional 三层均 `passed`。五道双方通过、五道双方有效失败，所有 reward 0 与失败均原样保留。
- v28 identity 结算 `$9.142443`（wire `$0.116195`），跨 v23—v28 的 Plan 051 累计 `$9.412888`；
  `actual_usd=null`，task envelope 已关闭且剩余 `$390.587112`，无 active identity、reservation 或 running slot。
- distinct results worktree 发布 40 条 `track=tb` 与 `p2-b7-canary-baseline-v28.json`。正式 Docker 前后均为
  26 images / 11.5 GB、0 container、0 volume、0 build cache，VHDX 增长 0；Windows `C:` 全程高于 80 GiB。
  受影响的无 API harness 回归初轮 243/243、最终相关集合 346/346 通过；终态 finalizer 会在预算确认关闭后原子
  清空 active pointer，默认入口复验为 `idle` / 0 requests。未运行全 workspace、CI、PR、validation、holdout、
  本地模型或训练。
- 合法 `failed` 正式基线现与 `passed` 一样先确认发布、关闭任务 envelope 并原子退役 active pointer，再分别返回
  2/0；`run`/`resume` 与恢复用 `finalize` 共用该收口，`blocked` 保留给 successor 且不生成相对正式基线。结果侧新增
  独立 relative-baseline JSON，v28 明确为无前驱的 `first_formal_baseline`，原 v28 tracked public baseline
  SHA-256 `53e9b4b3...` 保持不变。`finalize` 可在 envelope 已闭合但 pointer 尚未退役的中断窗口直接恢复；正式终态与
  runner 退出码错配会明确失败。整改相关 9 模块最终 362/362 通过，未重跑 Docker、Cargo、真实 API 或全 workspace。
- 独立审查闭环：任务内审查先发现 active-pointer 终态问题；后续外部验收逐轮定位并关闭稳定入口输入/预算、
  failed/blocked 收口、自动 finalize 与 close/pointer 中断恢复缺口。最终复验另跑入口相关 32/32、核对 v28 结果字节、
  默认零请求状态与三棵工作树，结论 `PASS`，无剩余 correctness/functionality finding；报告见
  `agent_log/2026-08-21-174146-plan051-final-independent-acceptance.md`。

## 当前 WBS 清理与方向收口决定（2026-08-22）

- **方向 2（RONDO Local 本地审批模型）永久收口。** 既有 Local M3/M4 工程、训练与横评结果继续按本页前述
  WP3b-A2—A10 和 Plan 041 条目解释，最终结论保持“保留为实验”，不改写成生产采用。用户决定今后不再开启该方向；
  顶层与子 WBS 因此只保留一笔状态和必要能力边界，不再维护已完成任务分解。
- **RONDO Multi 第二期归档。** Plan 047 的 Team State 序列性质测试、Plan 048 的 Team Lens、Plan 049 的主动委派
  activation pilot 与 Plan 050 的明确委派三任务案例均已完成，其实现和验收由本页相应条目、冻结 plan 与 agent log
  继续承载。当前 WBS 不再把这些内容表述为进行中的“当前任务包”。
- **后续方向尚未启动。** 用户将另行定义并重新启动方向 1，也将另行定义 RONDO Multi 三期；本次整理没有替它们
  预设目标、候选、顺序、依赖、预算或验收合同。
- 方向 0 的既有设施和首次 schema v7 正式 canary 已归档，当前只保留可复用设施边界，没有 active campaign 或
  可继承授权。由此，`doc/WBS.md` 与四份子 WBS 恢复为只描述当前状态和待定义路线的精炼入口。

## RONDO Multi 三期 M3-A1 Publication Critic 产品合同（Plan 053，2026-08-22）

**状态**：M3-A1 已完成并通过独立验收。实现提交 `3f048b9103a42d25ccc8a233bf2cc97f9fc30c09` 冻结
Publication Critic 产品语义；验收报告提交 `36a106c` 给出 `PASS`，无剩余 correctness/functionality finding。

- 新增 [`Publication Critic 产品合同`](rondo-multi-publication-critic-product-contract.md)，冻结完整 canonical
  publication candidate、公共且有界的最小输入、Evidence V1 禁入边界、四类统一 hard qualification、PASS 区软偏好、
  两次 Producer 重写、最终非阻断审查、故障继续发布与取消不提交语义。
- 合同保持 Producer、Critic、Harness、Root 职责和现行 Team State 的权限、stale、retry/dedup、revision、wake、
  evidence window、双生命周期及 Root attention 不变量；不实现数据设施、模型服务或 `team_publish` 接入，也不冻结
  API/schema、模块布局、历史条数、预算、threshold、训练参数或部署格式。
- 四类合成边界例各覆盖一组 PASS/REWRITE，不把 handoff、evidence、篇幅或文风变成隐藏门槛；Plan 050 只作为三任务
  条件性历史事实使用，没有展开 ignored 原始正文或外推一般性能结论。
- M3-A2 与 M3-B2a 可依赖同一合同分别立项，后续路线只在方向 3 WBS 维护。实现可优先复用职责相符的现有设施；强行复用会
  扭曲语义或架构时，允许新建必要且架构契合的专用能力，同时避免重复、平行或无现实需求的重型体系。
- 轻量验收覆盖允许写集、相对链接、四类例、合同内部一致性及现行源码事实；未运行 Cargo、Docker、真实 API、本地模型、
  训练或全量测试。执行与验收分别见
  `agent_log/2026-08-22-014140-plan053-m3-a1-product-contract.md`、
  `agent_log/2026-08-22-022619-plan053-acceptance-review.md`。

## 方向 1 Harness 聚合观测与瓶颈普查（Plan 052，2026-08-22）

**状态**：默认关闭的方向 1 被测对象原生 trace opt-in、任务级安全离线投影、v28 历史普查、候选四态决策和独立
复核均完成；本任务没有实施 C1—C13 行为优化，也没有恢复 E-A。

- 删除首版重复的 `codex exec --json --rondo-local-observation` collector。最终链路复用 rollout trace 与 API
  metadata；只对目标 Local 测量显式开启 trace，发布前生成固定名称的 schema-v2 body-free 结果。原始 trace 不
  归档，缺失、残缺、重复、schema 漂移，或 trace/API 的 main/Guardian population、completed/non-completed 合计、
  分角色 usage 缺失数/已知合计不一致均拒绝发布。
- 原生 trace 只窄补 writer 完整性终态与真实输出边界的安全事实，区分 direct model 与 code-mode runtime，
  保存字节数、截断/collection omission、预算和有限枚举，不保存正文。public `exec` 在统一 caller-facing 边界原子
  记录最终交付与可选 body-free render；早期错误、取消或最终输出替换缺少可靠 render 时明确记为覆盖缺失。既有
  Team Lens 严格 reader/reducer 扩展为支持 Local 单智能体 bundle，没有建设第二套 telemetry、数据库或审计平台。
- 只读 census 先校验 288 行 tracked index，再只验证选中的 30 个 Local private summary；所有 private 文件从
  common root 以 `dir_fd`/`O_NOFOLLOW` 逐级打开。公共 report/delta 使用 exact schema 与 body-free allowlist，缺失
  覆盖不可比较时所有 delta 为 `null`。
- v28 cohort 为 10 题 × 3 次 Local 观测：API metadata 30/30、exec JSONL 24/30，后者覆盖 8/10 任务，6 个
  redacted 集中在另外 2 个任务。C1/C2 为弱信号，C11 仅在当前样本未观察到，C7 当前资产不可测；C4/C5 只作归因
  辅助，因此没有选行为候选。
- 当前唯一后续包是另行授权的 10 题 × 2 Local round 观测复测，main Terra medium、Guardian Terra low、20 USD
  硬上限；唯一变量是开启安全观测而非改变产品行为。首个真实请求或非空工件固定正式 slot 与 20-run 分母；此后
  20/20 个 run 都得到严格投影才有效，任一完整性/schema/来源核对失败即停且不得替换。正式边界前普通接线问题可
  窄修复验，资源门不可用则不进入 slot；预算到顶即停，两轮后无条件停止。E-A 继续不恢复。
- 历史读取器拒绝空 API 请求集以及缺终态、重复终态或冲突终态的 exec JSONL，不再把残缺资产计成“测得的零”；
  schema-v2 同时保留 failed/cancelled inference 无 usage 的 C11 正样本，将 usage 标为不可测；按 model/runtime 表面
  记录 render delivery/covered/missing，关联去重 code cell 输出，并新增重复调用 lifecycle 与真实 turn 时长。修复后
  v28 census 与冻结机器结果逐字节一致。定向门禁和最终独立复核结果见本次整改日志。
  Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI、PR 均未运行。详细执行
  与首次只读资产边界见 `agent_log/2026-08-22-003425-plan052-local-harness-census.md`；验收整改与最终门禁见
  `agent_log/2026-08-22-plan052-native-trace-remediation.md`；二次正确性整改见
  `agent_log/2026-08-22-plan052-observation-correctness-remediation.md`；public `exec` 早期交付边界整改见
  `agent_log/2026-08-22-plan052-public-exec-delivery-remediation.md`。
- 第三轮独立验收确认 public `exec` 早期错误不再被误计为零；Python 51/51、Rust 2/2 通过，结论 `PASS`，
  未发现新的功能性回归或冗余设施问题。未运行真实 API、Docker、本地模型、训练或费用任务。最终报告见
  `agent_log/2026-08-22-041330-plan052-third-remediation-acceptance.md`。

## RONDO Multi 三期 M3-B2a Publication Critic 本地服务（Plan 055，2026-08-22）

**状态**：实现提交 `2c47adb` 与配置边界修复提交 `dbc1d7a` 曾被过早记录为完成；后续独立验收提交 `d216bfb` 发现最小 frame
cap、terminal backend status 与测试 release barrier 三项局部缺口。整改提交 `3be09927` 已关闭三项 finding，并通过 29/29
定向测试、Clippy、argument-comment lint、fix/fmt 与最终独立复验。结论为**验收通过、任务目标完成**。

- 新增专用 `codex-publication-critic` crate，提供 protocol v1 的严格 allowlist packet、loopback 长度前缀 JSON 服务、可替换
  scorer 与 B2b 可消费的 typed client；不依赖 `codex-core`、Team State 或 RONDO Local approval 产品合同。
- expected identity 由调用方可信 typed 配置提供，精确绑定 service/protocol、qualification、model/tokenizer、render/projection、
  score domain、threshold 和 verdict rule；服务复验 backend identity 与单值 finite score，故障不会猜成 verdict。
- production defaults 为 request 128 KiB、response 16 KiB、concurrency 1、queue 4、job 25s、client 30s、startup 60s、I/O 2s、
  graceful 3s + force/reap 2s、零 retry。配置字段对外只读，构造和最终消费点复验 loopback/frame/resource/timeout 上界。
- 受控 scorer 只替换 backend；整改后 29/29 定向测试通过真实服务子进程、正式 transport、协议解析、identity、admission、资源门
  和 typed client，覆盖 PASS/REWRITE、严格 ingress、最小 frame cap、queue full、timeout/cancel、终态 backend/故障漂移、无丢唤醒
  release、异常退出、两阶段关闭及正文 sentinel。
- 定向 Clippy、argument-comment lint、fix/fmt 与 Bazel lock update/check 通过；Cargo/Bazel 依赖均为 workspace 既有依赖，
  `MODULE.bazel.lock` 无差异。未运行全 workspace、全 Bazel、CI、PR、Docker、真实 API、训练或真实模型。
- 未修改 `team_publish`、Team State、Team Lens、`eval/` 或 `training/`。证据只覆盖受控 backend 的进程/协议/资源闭环；
  canonical packet 构造与产品接入属于 M3-B2b，真实 threshold、模型质量与部署资格留给后续工作包。执行与整改记录见
  `agent_log/2026-08-22-051709-plan055-m3-b2a-publication-critic-service.md`、
  `agent_log/2026-08-22-062600-plan055-independent-review-remediation.md`；最终验收见
  `agent_log/2026-08-22-063239-plan055-remediation-final-acceptance.md`。

## 方向 1 原生观测有界复测 v1 历史节点（Plan 056，2026-08-22）

**状态**：v1 已按原合同以无效 campaign 终态关闭；没有行为候选结论。用户随后追加授权，整个 Plan 056 任务仍在
rehearsal/全新正式 campaign 中继续，本节只冻结 v1 历史事实。

- 新建 `plan056-direction1-bounded-observation-v1` 独立 campaign/batch/task-budget/result namespace，固定 v28
  同一 10 题、两个 round、20 个 round-major slot、RONDO Local、`gpt-5.6-terra` main medium / Guardian low。
  runtime bundle 绑定 clean `2765ff8f82ce21262af46bdf93a62c75b381b631`，CLI/code-mode host/bwrap SHA-256
  分别为 `7d960131...016f`、`5b9dcd88...afb6`、`77360cb7...2c4c`。
- 10/10 零 API Docker/Harbor 预检完成。正式第 1 个 slot `db-wal-recovery` 发布且 task pass；第 2 个
  `extract-elf` 已发送后，投影器报 `rollout trace lifecycle is incomplete`。合同禁止重发已发送 slot，因此整包
  立即标记 `sent_slot_execution_or_projection_failed`，剩余 18 slot 未启动，20-run 分母保持不变。
- 日期冻结 body-free 结果为 `campaign_invalid`：正式发布 1/20、source-validated 0、25 个上游 attempts、
  `0.631065 USD`、reservation 0、候选 assessment/null。task envelope 已按 invalid 关闭，active pointer 已退役。
- 只读根因复核发现 3 个完整 runtime-end 事件晚于对应 tool-end；旧 reducer 在较早事件处永久标记 missing。设施已
  改为整束读完后判断 start/end 集合，并补乱序回归；原始第 2 题 trace 复放恢复 `terminal=available`，但不撤销
  已冻结的 campaign 终态。另修持久预算只读 loader 与 CLI snapshot 语义错配。
- 相关 Team Lens、harness observation 与 Plan 056 定向 Python 集合 69/69 通过；未运行 Codex 对照、validation、
  holdout、E-A、完整数据集、全 workspace、CI、PR、本地模型、训练、云任务或上传。
- Docker total 前后均为 11.5 GB，Docker Desktop VHDX 前后均为 69,467,111,424 bytes，Windows `C:` 余量从
  186,093,740,032 降至 186,090,741,760 bytes；所有 Plan 056 容器、网络和卷已清空，固定镜像保留。

## 方向 1 原生观测有界复测完成（Plan 056，2026-08-22）

**状态**：完成首个可信正式 20/20，选择 C2；真实 API 已停止。Plan 056 只完成测量与候选决策，没有实施行为优化。

- 用户把 v1 后续任务累计预算扩为 `100.000000 USD`，允许开发性 rehearsal 和可修复设施问题后的全新 identity。
  rehearsal-v2/v3 分别因 Docker 实时事实瞬时失败和合法 pre-runtime sandbox denial 投影缺口关闭；相应设施窄修后，
  rehearsal-v4 连续完成 10/10，6 pass/4 fail。formal-v5 因响应头前 transport open 失败缺少可区分终态而关闭；
  观测链新增严格 `open_error`/`non_sse` 分类，旧工件继续 fail-closed，不改写历史。
- 修复提交 `4965d7483d9e2812ec8e39debdb5988107e8101a` 的 RONDO Local runtime bundle 经共享锁/看门狗重建和复验；
  CLI/code-mode host/bwrap SHA-256 为 `cc523bd8...a0d5`、`ddda3ddb...1e0`、`77360cb7...2c4c`。formal-v6 lock
  SHA-256 为 `263cc3fa...9e7f`，10/10 零 API preflight 全部通过。
- `formal-v6` 从第一题干净执行同一 10 题两个 round，20 个 slot 全部 `completed`、来源复验通过、usage 可定价、
  schema-v2 body-free 投影完整且 Docker receipt 为 `verified_empty`；Terminal-Bench 为 8 pass/12 fail。正式结果为
  219 attempts、`4.677962 USD`、reservation 0。
- 候选门槛只选出 C2：9 次 occurrence，影响 6 个 slot/4 个任务，其中 3 个失败 slot，两轮均观察到，影响值 10108；
  C1 为 7 次 occurrence 但只影响 2 个 slot/1 个任务且 impact 0，不合格；C11 未观察到；C7 保持不可测。公共结果为
  `eval/results/observations/plan056-direction1-bounded-observation-formal-v6-2026-08-22.json`。
- 累计账本保留 6 个 identity：v1、rehearsal-v2/v3、rehearsal-v4、formal-v5、formal-v6，费用依次为
  `0.631065/0.569748/0.842369/1.970204/1.637680/4.677962 USD`，合计 483 attempts、`10.329028 USD`；
  task budget 已关闭、reservation 0、hard stop 未触发。三次 rehearsal 中两次 invalid、一次 complete；另有 v1 和
  formal-v5 两个 invalid campaign，共 4 个 invalid campaign。
- Docker total 前后均为 11.5 GB，VHDX 前后均为 69,467,111,424 bytes，Windows `C:` 从 191,850,123,264 降至
  191,832,576,000 bytes；最终 0 container/volume/build-cache。按追加授权精确清理两座旧 Plan 056 Cargo target，
  共释放 27,105,466,102 bytes；对应提交、bundle/manifest、账本、campaign、费用和公共结果均保留。
- 验收后继续按精确归属清理 formal-v6 Cargo target 与三份 clean detached source，共释放 14,127,722,496 bytes；
  正式 campaign、账本、trace/API metadata、Terminal-Bench 结果、公共结果、formal-v6 runtime bundle 与发布 bundle
  均保留，离线状态复验仍为 `finalized`、20/20、C2、`4.677962 USD`、reservation 0。删除内容均可由仓库提交
  重新检出或构建。
- 定向设施回归为预算代理 62/62、harness observation 与 Plan 056 合集 54/54；构建、runtime verify、preflight 和
  20-run 均通过相应资源门。未运行 Codex 对照、validation、holdout、E-A、完整数据集、全 workspace、CI、PR、
  本地模型、训练、云任务或上传。独立最终验收和对应整改结果见 Plan 056 最终日志。

## RONDO Multi 三期 M3-B2b Publication Critic 发布流程接入（Plan 057，2026-08-22）

**状态**：实现、四项 correctness finding 整改、最终独立验收与主线整合均已完成。受控产品路径成立，但尚无真实模型
质量、threshold 或性能结论。

- 默认关闭的 typed Critic 配置已接入 `team_publish` 前置流程。关闭态保留原 schema、输出与 store 路径；启用态从
  Team State 权威 canonical preparation 和 actor 可读的 event-local 有界公共 history 构造 Plan 055 packet，最终提交
  仍且只由现行 Team State `publish()` 完成。
- 产品流程支持最多两次阻断式 `REWRITE`、第三次非阻断审核、typed failure 后当前稿单次 fallback、commit 前取消零提交，
  并保持 attempt/committed replay、并发、revision、wake、evidence 与 Root attention 语义。候选正文只出现在必要的
  Producer 反馈中，开发者观测保持 body-free。
- 首轮独立验收发现无关请求清理 cycle、旧 continuation 跨阶段复用、锁内全量 history clone 与脱敏 trace 缺终态四项问题；
  整改后 cycle 按归属隔离、每阶段轮换 continuation、Team State 使用不含 route/Fact ID/body 的专用有界 history，
  PostToolUse feedback 也能产生安全唯一终态。最终复验结论为 `PASS`，无剩余 correctness/functionality finding。
- 整改证据包含 Team State 2/2、Publication Critic 聚焦组 13/13（其中 7 项启动 Plan 055 正式受控服务进程）及
  registry/trace 4/4；相邻 Clippy、fix、fmt/fmt-check 与 `git diff --check` 通过。argument-comment 固定工具链不兼容和
  Bazel 三目标 10 分钟未完成继续如实记录，但按验收决定不阻断本包。
- 未运行 Docker、真实 API、真实模型、本地推理、训练、全 workspace、CI 或 PR。产品链已到达 M3-C1 前置边界，但
  M3-C1 仍等待模型链完成；当前方向 3 下一包是 M3-A2。执行、首次审查、整改与最终验收分别见
  `agent_log/2026-08-22-094518-plan057-publication-critic-integration.md`、
  `agent_log/2026-08-22-102052-plan057-independent-acceptance-review.md`、
  `agent_log/2026-08-22-105310-plan057-review-remediation.md`、
  `agent_log/2026-08-22-110158-plan057-final-acceptance-review.md`。

## RONDO Multi 三期 M3-B1a Publication Critic 训练数据冻结（Plan 059，2026-08-23）

**状态**：revision v7 已完成正式冻结、独立复核、两轮验收整改与最终独立验收，结论为**数据 GO、验收通过、任务目标完成**；
实现提交 `6b66e3df7f54a97b680120035537798e3ffbb725`，最终验收报告提交
`6b7fe6ee507c4b01cb230bfe3d5ee773359fa0fd`。

- 在 Plan 054 v4 的 PublicationPacket、两条有序 message、control-token-safe render、exact tokenizer/template/special-token identity、
  16,384-token window 与 overflow 语义之上，新建 Scenario/Candidate/Binary/Pair/review 合同及 grouped split、dedup/shortcut、
  exact-token census、freeze/manifest 和轻量 consumer；没有复制第二套 renderer、packet validator 或 eval runner。
- 最终 `publication-critic-v7` 含 36 scenario group、72 candidate（39 PASS / 33 REWRITE）、30 Boundary 与 6 Within-PASS；
  train/validation/unseen-test 为 42/16/14。训练阶段成员为 C1 42 Binary、C2 再加 18 Boundary、C3 再加 3 Within-PASS；
  train-only smoke bundle 不含 holdout。
- teacher 为 GPT-5.6-sol，独立 reviewer 为 GPT-5.6-sol/xhigh。v7 受影响的 12 candidate、6 Boundary 与 1 Within-PASS 全部接受；
  未变化 review 仅在模型可见输入逐字节相等后复用。最终无 coverage、Plan 054 reference、跨 split group、文本或 exact-token 长度 shortcut
  finding；12 条 near-duplicate edge 均闭合在 scenario group 内。
- 全量 exact census 为 50,073 tokens，单条 553–1,367，continuity omission 与 candidate truncation 均为 0；tracked freeze 与
  ignored `formal-v12-final` 的 12 个文件逐字节一致。consumer 默认只持有 train `42/42/21`，显式 evaluation 为 `72/72/36`，
  默认 holdout 与公开直接构造旁路均拒绝。
- 最终复跑 62/62 聚焦 Python tests 与 tracked freeze consumer smoke 通过；未运行 Docker、Cargo/Bazel、模型 forward、训练、真实 API、
  CI 或 PR，未触碰 Plan 058。最终报告见
  `agent_log/2026-08-23-184721-plan059-v7-final-independent-acceptance.md`。
- M3-B1b 数据前置已解锁，但尚未启动；它需要独立 ExecPlan 及 RunPod/H100、训练、上传与付费预算授权。Plan 059 的 GO 不代表训练成功、
  性能提升或产品上线资格。

## 方向 1 C2 行为优化与有界正式决策（Plan 058，2026-08-23）

**状态**：单一 C2 优化、真实测评、独立验收整改、外部复验与主线整合均已完成；最终决策为
`retain`，能力继续 root-only、UnderDevelopment、默认关闭。实现/验收分支 HEAD 为
`65184a20158f19559d908ecd5140bd0d64076756`，主线整合提交为
`6c9503980f1cd870d1e4e70a3cdc16ed0e9c65a9`。

- Phase A 对 Plan 056 raw C2 的私有 trace 做最小只读分类，冻结 harmful/reasonable/insufficient 为
  `1/8/0`。产品只在 root agent 的 `exec_command` tool spec 增加有界 guidance；关闭态不增加文本，
  启用态不抑制工具，不改变 exit/error、Guardian、审批、sandbox、取消或用户 steer。
- `formal-v6` 使用同一 v28 十题、两个 round、Terra medium/low 与冻结顺序完成可信
  20/20：20 completed、8 pass/12 fail、225 upstream attempts，campaign `4.985650 USD`。唯一 pure
  transport 故障按冻结语义保留费用后同槽重试成功。
- 正式 raw C2 为 7 次/4 slot/3 task/9,693 ms；七次均有状态/结果变化、失败恢复或修改后复测依据，
  refined harmful/reasonable/insufficient 为 `0/7/0`。合理重复、恢复/用户控制、工具可执行性和任务
  正确性四门通过，因此保留 feature，不为降低 raw 次数而压制合理复测。
- 任务全生命周期累计 `20.379152 USD`、reservation 0。Docker/VHDX 增长为 0，最终无 active
  container、volume 或 build cache。失效 commissioning/formal/diagnostic identity 与费用保留；正式 campaign、
  binary、manifest、账本、trace、结果和 metrics 继续作为历史证据保留。精确清理的可重建 Cargo target
  及临时 detached source 不再重建。
- 首次验收后 guidance 按预冻 `adjust` 边界收窄到同 requester/tool path、全部调用参数不变，
  且条件不确定时照常执行；外部验收继续发现非 root agent 继承缺口，最终复用既有
  session-source 边界收紧为 root-only。`formal-v6` 仍绑定原冻结文案，不把验收后收窄版冒充为正式原样重测。
- 最终 root-only unit `2/2` 通过；清除代理变量后 Python 回归 `262/262` 通过。新增 model-visible
  integration 与既有对照都在 mock request 前受当前环境阻断，只作编译与静态调用链证据，不表述为运行通过。
  未重建已清理 target，未重跑 API、Docker、正式实验、全 workspace、CI、本地模型或训练。
- 最终报告见 `agent_log/2026-08-23-plan058-final.md`，外部复验见
  `agent_log/2026-08-23-plan058-reviewer-reacceptance.md`。任务完成不自动授权方向 1 后继 campaign。

## 构建资源固定门线调整（Plan 061，2026-08-23）

**状态**：固定门线修改、聚焦测试和真实 scope 验收均已完成；没有引入动态策略或资产迁移。

- 共享 wrapper 默认内存从 `19G/21G/5G` 调整为 `21G/22G/5G`，项目十进制告警/主动停止/绝对线
  从 `180/195/200GB` 调整为 `240/255/260GB`。Windows `C:`、Docker、宿主内存/swap/PSI、
  不可回收内存、并发和锁语义保持不变。
- `runtime_bridge.py` 同步 high/max 精确字节，现有 drift 测试覆盖 high/max/swap；override 仍直接覆盖，
  未覆盖维度继承新默认，因此部分旧单变量组合不再有效。
- Shell/diff 门禁、runtime bridge 6/6 和 Plan 054 v4 旧证据 1/1 通过。最终约两秒真实 scope 的
  production lease 前后有效，cgroup 精确为 `22548578304/23622320128/5368709120 B`，summary 与 unit
  收尾门禁通过。
- Plan 054 v4 历史 evidence/result/summary 保持不变并继续可验证，但不再接受新 wrapper summary；
  未来新 campaign 另行升级证据版本。未运行 Cargo、Docker、模型、API 或全量测试。

## 方向 1 教师源码热路径优化完成（Plan 062，2026-08-23）

**状态**：三项行为保持型热路径优化、轻量测评、独立验收和主线整合均已完成。clean candidate 为 `22b8766`，
最终通过 merge commit `2fff868c9d7ffac013cc0447d6993d6b560e7354` 进入 `main`；收口时本地 `main` 与
`origin/main` 一致。

- 学习教师源码后筛选并自主实现 history orphan normalization 借用式索引、模型可见工具规格不可变共享、
  unified-exec 连续字节快照与合法 UTF-8 借用判定；保持 Codex CLI `v0.147.0` 基线身份，不改变模型可见语义、
  工具资格、Guardian、审批或 sandbox。
- clean baseline `d5535fc` 与 candidate `22b8766` 使用同一 harness SHA-256
  `ef8364c8a225226fa1085355ae447f55b9a0aabb3fab6d2f8f264703c77fd5f2`。正式结果为 benchmark smoke、定向
  48/48、release exact 1/1、Python parser 4/4、`codex-core` 3332/3332（8 skipped、2 slow）及 9/9 benchmark；
  独立审查重聚合正式 raw 后与 tracked body-free JSON 逐字节一致，无剩余 correctness finding。
- history 8/32/128-turn allocation count 从 `11/37/135` 降至 `3/5/7`；工具规格共享 case 的 allocation
  count/bytes 从 `1296/565200`、`5136/2261000`、`10256/4523000` 降至 `0/0`；4 KiB/256 KiB/1 MiB
  snapshot allocation count 从 `3/3/4` 降至 `1/1/1`。这些结果只解释命名热路径，不外推 API 延迟、模型质量、
  Terminal-Bench 成功率或通用 agent 能力。
- 所有 Rust 构建、测试和 benchmark 均经共享 build lock/watchdog；未运行全 workspace、Bazel、Docker、
  Terminal-Bench、真实 API、真实本地模型、训练、云任务、CI 或 PR。详细执行与验收见 Plan 062 及对应 agent log。

## 方向 1 正式收口与当前 WBS 迁移（2026-08-24）

**状态**：用户决定方向 1 在 Plan 052、056、058、062 完成后正式收口。当前不再安排新的观测、内核/Harness
优化、热路径优化或正式 campaign。

- 既有默认关闭观测能力、任务级安全投影、root-only C2 guidance、三项热路径优化、轻量测评和历史结果均保持；
  本次收口不回退实现、不删除证据，也不把历史测评外推成未证明的端到端收益。
- 已完成任务的分解、指标和验收记录由本文件、冻结 plan、审计快照与 agent log 承载。顶层 WBS 只保留正式收口
  状态；方向 1 子 WBS 精简为状态与归档入口，不再维护已完成任务流水。
- 这是当前阶段的收口决定，不是永久禁止。未来如果用户决定重新启动方向 1，应按届时目标重新立项并建立新的
  任务合同；旧 campaign、预算与真实执行授权不自动继承。

## Publication Critic 正式训练数据扩充与冻结（Plan 064，2026-08-24）

**状态**：阶段 A--D、正式 v8 freeze 与最终独立验收均已完成；验收通过、任务目标完成，最终数据资格为
“证据不足（训练预算适配未决）”，不是数据 GO。正式实现提交为 `5b9da6d070100504cfb15523e9bb3ef287137e7c`，
最终验收提交为 `65ec14a541c7e4ae2a850d074c44eb66d028f155`，主线合并提交为
`6a50168d59cd9ccb6c9097c73f3bf9ac48194c1f`。

- `publication-critic-v8` 完整物化 123 scenarios、228 candidates、104 pairs，train/validation/unseen-test 为
  128/55/45；exact-token 总量 178,646，单项 553--2,094，continuity omission 为 0。C1/C2/C3 为 128 Binary、
  50 Boundary、再加 8 Within-PASS；默认 consumer 仅暴露 train，evaluation 模式才可访问完整 holdout。
- 正式 manifest core identity 为 `a9a31a61e0a1e070ee8d076dd313b7efabb5e01ffa42773a841b123a2686cb98`，绑定获批
  prefreeze universe `3fdfc0ada4a67451e4f1fc7e66302067119172fea809802ff1d01576b3be40d9`、Plan 054 输入、23 个实现合同、
  review/disposition、lineage、split、token census、consumer 与 train-only bundle。
- Plan 059 v7 物理 tree 保持 `435c06fba3196bee21d59d88b9e6d6b1a1e1999a`；v8 只按设计锁投影逐字节不变的继承成员，
  v7 holdout 与 Plan 060 smoke 输入未迁移、未替换。104 个 pair 与 37 条 near-duplicate edge 均保持 split 闭合。
- 最终独立验收复算 manifest/files/contracts/universe 与 consumer 边界，12 个 Publication Critic focused Python 模块
  `137/137` 通过。未运行 Cargo、Docker、完整模型、真实 API、云任务、上传或训练，也未增加通用审计/可信设施。
- Plan 060 尚无进入 main 或正式交接的吞吐、费用与预算事实，因此冻结数据不能宣称训练预算适配 GO。后续只在 Plan 060
  正式结果到达后对冻结 v8 做一次有界预算适配复核；默认不生成新数据、不修改 split/label/review、不重新 freeze，M3-B1c 仍锁定。

## Publication Critic H100 全参数训练资格 Smoke（Plan 060，2026-08-24）

**状态**：final-19 正式 smoke、本地提交与独立验收均已完成；验收通过，`remaining correctness/functionality findings=[]`，
M3-B1b 结论为 `TECHNICAL_GO`。实现提交为 `c7cf3b4c7999c76dbeea2c129186c05ee4de9299`，验收与 Plan 066 规划提交为
`6273705d30ca509fbd27674a11883f611c84bd46`。

- Secure 单卡 H100 PCIe 80GB 上完成 BF16 全参数 FlashAdamW commissioning 与 final-19 干净 formal start/resume；
  1,720,577,024 个参数、311/311 optimizer tensors 完整覆盖，C1/C2/C3 和新 OS 进程 step 3→4 均有真实、有限更新证据。
- final-19 archive、start/pending receipt、约 10.56GB full checkpoint、依赖/recipe、模型 revision 与提交源码身份闭合；两路独立复核均
  `remaining=[]`。formal C1/C2/C3 为 11.108/1.342/1.471 秒，resume C3 为 2.381 秒，峰值 CUDA allocated/reserved 约 18.29/21.27GB。
- Plan 064 v8 的 128 train candidates、C2 50 Boundary、C3 再加 8 Within-PASS，三个阶段各一遍约 451,743 tokens；基于 Plan 060 正式吞吐、
  当前费用与 23 USD 连续总账的有界复核转为 `DATA_GO`，不重做数据或 freeze，也不代表模型质量 GO。
- 用户决定不为任务切换停止稀缺热资源。当前 Pod、胜者 Standard 卷、exact 模型/venv/FlashOptim/cache 与 final-19 checkpoint 直接交给
  Plan 066；Plan 060/066 从原 Plan 060 基线连续计费，资源终态和 settled billing 由 Plan 066 完成正式训练后统一收口。
- focused 门禁为 128 passed、1 optional local Torch seam skipped、77 subtests；真实 H100 链覆盖对应组合路径。未运行 Docker、Cargo、
  本地完整模型、validation/unseen-test 训练、M3-C1、CI 或 PR。

## Publication Critic 正式全参数训练（Plan 066，2026-08-24）

**状态**：C1→C2→C3 正式训练、候选保存、恢复验证、资源收口与独立终验均已完成；验收通过，任务目标完成，
correctness/functionality `remaining_findings=[]`，路线结论为 `GO`。

- exact base 上消费 128 Binary、50 Boundary 与 8 Within-PASS，共 451,743 tokens；三阶段均以 BF16 全参数 FlashAdamW 更新
  1,720,577,024 个参数，311/311 optimizer tensors 完整且有限。
- C1/C2/C3 三个约 3.46GB safetensors 候选、约 10.56GB 正式 checkpoint 和新 OS 进程 step 3→4 恢复继续均已复验；每阶段固定
  validation 55 candidates，不进入梯度或改变 optimizer/scheduler，unseen-test 未运行。
- 计算 Pod 已永久删除，RunPod Pod 数为 0；唯一 Standard 60GB winner 卷 `hi3iaz8rsr` 保留候选、checkpoint、exact 模型与环境。
  独立终审按用户指定冻结最新 provider 快照总费用 `$10.9647715263`，距 `$23` 连续硬上限 `$12.0352284737`。
- final-02 的 v1/v2 兼容、费用算术、哈希绑定与预算门正确；终审 focused 11/11、三个 launcher `bash -n` 和 diff 门禁通过。
  本结论只使候选具备进入 M3-C1 独立工作包的资格，不代表模型质量、threshold、部署或产品收益通过，也不自动授权 M3-C1。

## RONDO Multi 四期共同合同（Plan 067 / M4-A，2026-08-24）

**状态**：共同产品合同、两轮独立审查整改与最终复验均已完成；验收通过、任务目标完成，结论为 `M4_A_GO`。
合同提交为 `c9a6f8795a2e55f7d358a57ab558350158a5f505`，整改提交为
`304510dcf16055bb69a9086f227e0ded132a9a8e`，最终独立验收提交为
`309e1d64864ae616124d51b6fdbe2ae74f170574`。

- 冻结 `SessionId`、canonical Root `ThreadId`、`TeamInstanceId` 的 lineage、生命周期/authority anchor 与 Team generation
  职责，并统一 resume、顶层 fork、child `spawn_agent fork_turns`、`/new`、slash `/clear`、detach、idle unload、退出和冷态
  archive/unarchive/delete 的产品语义。
- canonical Team State 保持唯一状态权威；现有 Root active-writer 作为唯一排他基础做架构内扩展，并增加与 Team State 集成的
  专用 durability/read 能力。durable success、committed read、失败关闭、partial/unknown 与损坏/不兼容降级均已有明确边界，
  child writer 不能绕过 Root 归属。
- 独立审查补齐两项真实遗漏：mutation-capable descendant 存活时 Root/Team close 不得完成或释放 authority；第四期 WBS 按已提交
  main 同步三期完成与资源终态。具体锁、permit、状态机、持久介质、API、字段、调用顺序和测试 fixture 仍由下游自主决定。
- 四项 `v0.149.1` 候选增量均已明确采用、条件适配或延期决定及消费边，但本任务未回移或升级上游。M4-S1、M4-C0、M4-W0
  可分别建立 ExecPlan；正式 W1 仍等待 W0 binding GO 与 S1 接缝，W 线不阻塞 S/C 核心收口。
- 验收只使用现行源码、既有测试定义、冻结上游与官方 PR 的静态证据，并通过精确写集、链接、术语和 `git diff --check`；未运行
  Cargo/Rust、Docker、真实 API/模型、训练、测评、全 workspace、CI 或 PR，也未修改 Plan 068 内容。

## Publication Critic 本地部署资格与候选交接（Plan 068 / M3-C1，2026-08-24）

**状态**：本地工件交接、真实模型服务接入、四对象正式资格运行、独立审查整改、远端清理与最终验收均已完成；
实现和任务流程验收通过。base `NOT_QUALIFIED`、C1 `QUALIFIED`、C2 `NOT_QUALIFIED`、C3 `QUALIFIED`，
但因 base 对照未取得同口径资格，M3-C2 前置未满足。资格与远端清理提交为
`261164fb82747b2f175b5f29613bec1a56a756fa`，最终独立验收提交为
`a0f0220452a1f8f084a0645888e7de5918db84eb`。

- 通过无 Pod RunPod S3 入口安全接收并验证 120/120 个必要对象、24,385,153,354 bytes，覆盖 exact base、
  C1/C2/C3、正式 checkpoint 与必要恢复环境；本地副本的 bytes/hash/身份闭合，unseen-test 始终封存。
- 在 Plan 055/057 的既有协议、typed failure 与产品语义上接入真实 scorer，正式部署路径使用原始 safetensors 与
  CUDA BF16，CPU FP32 作为转换前 reference；没有量化、修改权重、继续训练或另建通用模型服务体系。
- 调试阶段先用 fresh worker 完成窄 commissioning，再冻结统一 BF16 projected cap `0.005` 和干净正式配置。
  唯一有效正式轮为 `plan068-formal-20260824T222852Z-qualification-v3`：base 因 projected drift
  `0.03404159` 和 1 次临时 verdict mismatch 失败；C2 因 ranking/direction 失败；C1/C3 的 runner/service
  projected parity、0 verdict mismatch、15/15 stress、typed failure、取消与关闭语义通过，本地资源和延迟适合既定有界场景。
- 正式 evidence、freeze、offline/service observations 与 result 以普通 JSON/SHA-256 绑定；此前调试或基础设施失败轮均明确失效，
  未拼接成正式结果。相关定向 Python 113/113、Rust 34/34、整改复验 41/41，以及 fmt/lock/compileall/diff 门禁通过；
  最终清理未改变代码、模型或资格证据，因此未机械重跑真实模型、Cargo 或 Docker。
- 本地交接经独立审查明确接受后，永久删除 exact RunPod winner 卷 `hi3iaz8rsr`；删除后实时复核为 0 Pod、
  0 volume，当前 compute/volume 持续费用均为 0。本地候选、正式 checkpoint 与资格证据继续保留。
- 未运行 unseen-test、真实 API、Docker、云端训练或 Hugging Face 上传，未启动 M3-C2/M3-D，也未默认启用 Critic。
  任务执行日志见 `agent_log/2026-08-24-210426-plan068-local-qualification.md`，最终独立验收见
  `agent_log/2026-08-24-185009-plan068-final-review.md`。

## RONDO Multi 实验性 Session 协议与 TUI 原型（Plan 070 / M4-C0，2026-08-24）

**状态**：默认关闭的 experimental app-server v2→app-server client→TUI 纵向原型、两轮独立审查整改与最终复验均已完成；
验收通过、任务目标完成，结论为 `M4_C0_PROTOTYPE_PASS`。最终实现提交为
`bb60a04938b2f55c5ceede4fd5820f1e7637b30f`，最终独立验收提交为 `dab5db3d5a938b8f9ee74a238f6294aa1582ac55`，
主线合并提交为 `5fdd4db5cd65243c93362ae62bf375d934728463`。

- 新能力只位于 v2 experimental surface，并由独立、默认关闭的 `experimental_session_control` product gate 保护；关闭态不显示
  `/sessions` 原型、不增加后台查询或 startup tooltip，TUI 继续只经 app-server 工作。
- discovery/read 不取得 writer、不 repair metadata、不加载 Session 或启动 Agent/model/API；identity、domain lifecycle、runtime
  residency、operation availability、freshness/certainty 与 provenance 分轴，state DB 和 prototype input 不冒充 S1 durable read model。
- online Team mutation 只路由 current/running canonical Root owner；non-owner、ChildOnly、owner unavailable 与 stale preflight
  fail closed。cold unarchive 只在 fresh prototype projection 证明 stored Root 后调用既有权威入口，不直接写持久介质。
- lag、disconnect、EOF 与真实 response loss 会进入 stale/result unknown；非幂等 mutation 不自动重放，显式权威 read 恢复 Fresh，
  迟到 request-id response 不覆盖新投影。Root filtering 使用 `RecencyAt + thread-id` 稳定双键 cursor，DB error 与扫描预算耗尽明确
  返回 unavailable/incomplete。
- 最终聚焦证据覆盖 protocol/features、app-server/client、core、TUI、schema generator、snapshot、真实 loopback response-loss 和
  26 条同毫秒跨页回归；app-server 最终 `experimental_session` 全集 13/13 通过。历史全 workspace 14,380 项中 16 项失败均被验收
  判定在 070 写集外，本任务未弱化或掩盖。
- 正式 Session query 仍等待 M4-S1，以真实 durable read model 替换 prototype input；正式 control/TUI 再等待 M4-S2 的恢复和 close
  barrier。C0 不冻结正式 RPC、字段、UI、timeout 或通用 `thread/unarchive` authority，也不授权产品启用、S1/S2、外部资源或远端操作。

## Publication Critic base 对照可比性修正与重验（Plan 071，2026-08-25）

**状态**：base 归因、资格口径分层、同口径正式重验、独立审查整改与最终复验均已完成；验收通过、任务目标完成，结论为
`BASE_COMPARABILITY_GO`。实现与资格边界提交为 `c72edde0f6f7cdd3b944b38fc2a47dbb7ceae65e`、
`90ce6ba5eb3ba3faa3ffa4db41934c1147e18653`，终态逻辑整改提交为
`c69868f07d46f7991c6b9bac4904fdaf22dc6088`，最终独立验收提交为
`5e13251a2fd647e746e6daee34ced1b4a25d494f`。

- Plan 068 的 base 失败来自把 CPU FP32→CUDA BF16 cross-runtime 差异、sigmoid 区域放大、near-threshold 临时 verdict 与
  同 runtime worker parity 混在同一 projected gate。Plan 071 复用既有真实 scorer/service，将 cross-runtime raw cap 及其
  stable-sigmoid envelope、同 CUDA BF16 fresh-worker parity 和精确 descriptor threshold 的 service verdict 分层判断；没有改变
  Plan 054 输入/scalar、Plan 055 服务协议或 Plan 057 发布/fallback/cancel/store 语义。
- 唯一有效正式轮 `plan071-formal-20260825T064600Z-qualification-v5` 绑定 clean source `90ce6ba...` 和既有 24 条非 unseen
  cohort。base、C1、C3 均为 `QUALIFIED`，C2 未重验并保持 Plan 068 历史 `NOT_QUALIFIED`；三对象均完成 CPU FP32 reference、
  CUDA BF16 deployment、fresh-worker parity、18/18 真实 service verdict、15/15 stress 与 clean shutdown，C1 另完成
  cancel/post-cancel ready/review。
- 独立验收发现并闭合一个三态终止分支：无 C1/C3 合格锚点时统一返回 `INCONCLUSIVE`，只有存在合格锚点且 base 不合格时才返回
  `BASE_NOT_COMPARABLE`。最终 41/41 定向 unittest、compileall 与 diff 门禁通过；修复后从 v5 raw 机械重建的
  observations/result 与正式 archive 完全一致，因此保留 v5，不机械重跑真实模型、Cargo 或 Docker。
- exact base/C1/C2/C3、完整 checkpoint 与 Plan 068/071 证据继续保留在本地；未读取 unseen-test，未修改权重或数据，未训练、量化、
  下载 HF 资产、调用真实 API 或写入远端。RunPod 保持 0 Pod/0 volume、持续费用为 0；本任务未启动 M3-C2/M3-D，当前路线只见
  `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md`。

## 共享重型任务启动前冲突观察门（Plan 072，2026-08-25）

**状态**：共享 wrapper 补丁、独立审查整改、clean-HEAD 正反例与最终复审均已完成；结论为
`STARTUP_GUARD_ADDED`，`remaining_findings=[]`。正式验收代码 HEAD 为
`c517896924977fe6f044fdc514edc83586294884`。

- `scripts/with-build-lock.sh` 在成功取得 canonical flock 后、任何 payload 前调用共享 helper；匹配的 RONDO heavy scope
  仍 `populated=1` 或观察事实不可可靠取得时以 `84` fail-closed，且不等待、kill、清理、接管或调度旧 scope。
- inactive/failed 历史 unit 只有在无 ControlGroup、明确 `populated=0`，或 cgroup 已消失且终态复读一致时才 clear；非空且
  populated 的 failed scope 仍是冲突。独立审查发现并推动关闭了过早 clear 的真实缺口。
- 正式轮从 clean `c517896…` 创建全新 task-owned scope/nonce/PID/marker，聚焦 Python **7/7** 通过：冲突时 contender
  返回 `84` 且 marker 不存在、旧 scope identity/population 不变；精确 teardown 并确认 gone 后，新 marker 正常执行。
  既有 helper 回归 **9/9**、`bash -n` 与 diff 门通过；正式轮后无 active RONDO scope 或 Plan 072 临时目录残留。
- 未运行 Cargo、Docker、真实模型、GPU、API、训练、性能测评或全量测试；未写入主工作区 ignored 资产，未触碰、合并或推送
  069、071 及其它工作树/分支。

## Persisted CWD Read Consistency 窄回移（Plan 074，2026-08-25）

**状态**：`#37198` 所需能力已按冻结 `v0.147.0` 和当前 RONDO 架构完成窄回移、外部整改复验与本地主线整合；验收通过、
任务目标完成。实现提交为 `bf8b7da6a7a4bc1db962c1f5a4b97dc55267673c`，整改提交为
`8c60ad4ae411d6f314c0432dc6531e8bab8d5fb8`。

- ThreadStore read-by-ID/read-by-rollout 只在 canonical rollout lineage 匹配时采用 persisted absolute cwd；空/相对 rollout cwd 可由
  同 lineage 的可信 metadata 修复，metadata 缺失、不可解析或 mismatch 时仍在最终 projection fail-closed。legacy permission 按最终
  cwd 自洽重算，state-only list 不会把损坏 cwd 绝对化为进程 cwd。
- persisted cwd 只代表已持久读取事实；显式 resume cwd/workspace roots 继续按既有优先级决定 live execution 和权限上下文，恢复或
  投影不会把历史事实冒充 writer binding，也不会扩大执行权限。实现对照官方 exact commit `547080e4d690cdeea12f427a8d9c5165928821ed`，
  未整体升级上游或引入第二套 ThreadStore、workspace registry、权限或审计体系。
- 整改后的聚焦证据为 ThreadStore **191/191**、app-server read/list/resume **2/2**、新增 lineage/cwd/permission 回归 **1/1**，
  ThreadStore clippy、`just fmt` 与 diff 检查通过；外部复验结论 `ACCEPT`，无剩余高/中等级 correctness finding。
- 069 相邻 mock sampling 的 `/v1/responses` 502 超时和未修改 core 的既有 clippy 阻断已如实记录为非 074 问题，本任务未为其扩大
  写集或重跑全 workspace。未运行 Docker、真实 API/模型、训练、性能测评、CI/PR，也未执行 Plan 069 阶段 E；因此本条只解除
  `#37198` 代码前置，不代表 `M4-S1 PASS`。

## Publication Critic 联合横评与最终选择（Plan 073 / M3-C2，2026-08-25）

**状态**：exact base、C1、C3 的正式同口径 validation 横评、Claude Opus 5 盲化异构判断、三轮独立审查整改与最终验收均已完成；
验收通过、任务目标完成，终态为 `NO-GO`。最终实现提交为 `67f8ab0977a0371ffae4b86e3218fd78f2f7aeda`，最终独立验收提交为
`ea0b919df6f8c3bf74203453a360ceb6d5684a62`，主线合并提交为 `a7647a4e28eb77c2968a1116965c7f820f7bf69e`。

- 唯一正式轮 `plan073-formal-20260825T084317Z-selection-v1` 在冻结 v8 validation 的 55 candidates、19 boundary pairs 与
  7 within-PASS pairs 上使用同一协议和运行时比较三候选。base/C1/C3 的最佳 balanced accuracy 分别仅为 `0.666/0.524/0.616`，
  ROC AUC 为 `0.6169/0.3894/0.5567`，没有任何 threshold 能达到冻结发布质量底线，因此不选择 base 兜底。
- Claude Opus 5 经订阅入口盲评全部 55 条，与冻结 GPT-5.6-sol 标签一致 53/55（`0.964`）；异构判断补充而未替代确定性指标，
  支持“模型未达标而非标签整体失真”的解释。三模型 runtime 门均通过且资源/延迟接近，不参与伪精度排名。
- 轻量 selection 能力覆盖 split release、threshold/metrics、Judge exchange、selection lock、confirmation 和结果归档。最终整改使
  validation 只读 canonical Plan 066 train+validation bundle，lock/confirmation/report 从冻结 release、raw score 与成对 Judge
  package/aggregate 重算并精确绑定；Plan 073 focused `60/60` 与追加 lock metadata 聚焦 `7/7` 通过。
- 正式 validation release/result/tracked report 可逐字节重建，SHA-256 分别为 `757dd624…a91`、`2b36eb4b…8915`、
  `f97fcdcc…8e4`。未生成 selection lock，unseen-test 未释放、render、score 或送 Judge；未量化、继续训练、调用付费 API、
  运行 Docker/Cargo 或启用产品。Publication Critic 保持 default-off，M3-D 保持锁定；后续路线须由用户另行立项决定。

## Publication Critic `NO-GO` 原因调研与路线决策（Plan 075，2026-08-25）

**状态**：从数据、监督、训练、候选资格、部署到 Plan 073 联合横评的正式与辅助证据链已完成独立重建；现有证据足以作出
唯一路线决策，但不足以把任一超参数、objective、optimizer、数据或底模确定为单一根因。任务选择合同阶段 D 第 2 类终态，
验收通过、任务目标完成。

- 独立复算确认 base/C1/C3 的完整 operating curve 均无可行点，最佳 balanced accuracy 为 `0.666/0.524/0.616`，
  ROC AUC 为 `0.6169/0.3894/0.5567`；三者 runtime 门均通过且接近，直接失败层是冻结 validation 上的模型质量，
  不是 threshold、部署资源、不完整打分或 base fallback。
- Plan 066 技术上成功，但沿用 Plan 060 数值资格 recipe，C1/C2/C3 各只有一次 full-stage update；正式 pre-clip norm、loss、
  validation ties 与 Plan 073 的 raw-logit/排序退化形成强证据。该证据支持“缺少训练动态开发和训练期质量门”，不支持把 LR、
  裁剪或其他单一机制宣布为已验证根因；exact base 自身也未达标。
- 数据 freeze、body-free train+validation bundle、objective/pair 方向、候选工件和资格/产品路径均未发现会推翻结论的
  correctness 故障。Opus 5 与冻结 validation 标签 53/55 一致，反驳标签整体失真，但合成监督规模、分布和泛化能力仍是未知。
- 现有证据已足以停止 Plan 075 内追加测量。唯一后续建议及其待授权、有界状态已交接到 `doc/WBS.md` 与三期子 WBS；本任务
  没有实施正式训练、新候选、产品启用或 M3-D。
- 本任务只执行静态摘要/指标复算和普通 Python 定向测试；Plan 073、Plan 066 与 full-model-training 聚焦测试 122 项通过、
  1 项按既有条件 skip。未加载模型，未运行 GPU、Cargo、Docker、真实 API、HF 网络操作或云资源；未读取 unseen-test 正文、
  逐行 label 或 pair 方向，未 render、score、Judge 或释放其内容，只核对过冻结 split assignment/聚合 metadata；也未修改
  Plan 069 及其他并行 worktree。
- 因果审查与范围/WBS 复验均为 `ACCEPT`，前者 `remaining correctness/functionality findings=[]`，后者提出的规划唯一来源、
  资源有界性和诊断 control 歧义均已关闭。冻结调研报告见
  `doc/research/2026-08-25-plan075-publication-critic-no-go-route-decision.md`，执行日志见
  `agent_log/2026-08-25-042835-plan075-no-go-route-decision.md`。

## M4-S1 Team Session 持久生命周期（Plan 069，2026-08-25）

**状态**：主体实现、六轮独立预验收整改、Plan 074 / `#37198` 精确合流、阶段 E 正式轮与最终独立终审均已完成；结论为
`M4_S1_PASS`。阶段 E 从 `f970f133cb4613b0b7f9f27db266aa36164fce12` 精确整合
`main@62d3ed732bf9452014a85722e7ed88c50a63dd94`，未吸收更晚主线或 Plan 073 现场。

- 默认关闭的 Durable Team Session 以 canonical Root ThreadStore authority 为唯一写权威，版本化 checksummed Team snapshot、typed
  `SessionMeta` lineage、committed read/reconcile、跨进程 cold resume、非 owner read、失败保留 owner 与最小 live-child close
  barrier 已闭合；缺失、损坏、unknown/unavailable 和 identity mismatch 均 fail-closed，不另建 Team lock、registry 或控制面状态源。
- 阶段 E 在同一全新 Session/store 产品链中完成 create、mutation、durable commit、非 owner committed read、非优雅进程退出、同
  Session/Root/TeamInstance cold resume、继续 mutation 与正常 close；Plan 074 的 persisted cwd read 与显式 live cwd/workspace override
  保持各自职责。最终独立终审结论 `ACCEPT`，无剩余高/中等级 correctness finding。
- 正式证据为 Durable Team/跨进程链 **3/3**、ThreadStore persisted cwd **2/2**、app-server persisted/live override **2/2**；邻近
  ThreadStore **191/191**、activation/retry **3/3**、ThreadStore/core clippy、`just fmt` 与 diff 检查通过。所有成功重型轮均由
  canonical lock/watchdog 执行，`complete`、退出码 0、`stop_reason=none`。
- shared core 触发的一次标准全 workspace `just test` 在测试前被 rusty-v8 v150.4.0 默认 archive URL 的 HTTP 404 阻断，未产生
  JUnit，未表述为通过或重复扩大完整轮；既有 checksum-verified 历史完整轮仍为 14,373 项中 14,363 通过、10 项既知相邻失败。
  本阶段未使用 Docker、真实模型/API、训练、测评、CI/PR，未把 069 合入或推送主线。

## M4-C1 正式 Durable Session Query（Plan 077，2026-08-25）

**状态**：基于 M4-S1 canonical durable read model 的正式只读 Session Query、四项独立审查整改与最终复验均已完成；验收通过、
任务目标完成，结论为 `M4_C1_QUERY_PASS`。初始实现提交为 `3642b04405bfad5daff3462f9a9f9ef7edd86a9a`，整改提交为
`c14d66143433acc887e7bce1ef6747ccd6574ba5`，最终独立验收提交为 `7f179b19615d3e3e4ea8eb54bb0ca2f6b63812c4`。

- 默认关闭的正式 app-server v2 `session/list` / `session/read`、app-server client 与 TUI `/sessions` 纵向链已经闭合。查询从
  ThreadStore 的 canonical persisted `SessionMeta` 定位 Session/Root identity，再与 durable marker 和同一完整 committed Team
  snapshot 交叉验证；state DB 只提供有界候选，不成为第二份 durable 状态源，prototype input 不再参与正式事实。
- 查询可在服务重启后发现 active/archived Durable Session，并分轴投影 Session/Root/Team identity、domain lifecycle、runtime
  residency、operation availability、provenance 与 freshness。分页 continuation、source change、损坏、不完整、backend unavailable
  和 stale retained view 均保守表达，不把不同一致性边界拼成当前事实。
- 整条查询链不加载或恢复 Agent/Session，不取得 writer authority，不启动模型、工具或 API，也不产生 Team mutation。C0 control
  保持独立默认关闭 gate；两个 gate 同开时 `/sessions` 固定正式 query、`/session-control` 固定 C0，仅开启 C0 时保留旧
  `/sessions` alias，query-only 不暴露控制操作。
- 提交级独立审查发现并推动关闭四个中等级问题：InMemory 易失 metadata 不再冒充 persisted seam；client 在提交前对称验证
  `Available <=> Team` 及 canonical Root viewer；双 gate 不再互相遮蔽；Team authored label/summary 只在正式 renderer 边界
  单行化。最终复验无剩余高、中或低等级 correctness finding。
- 正式证据包括 lower locator/meta **18/18**、app-server/client/TUI query **46/46** 与整改直接因果轮 **8/8**，均为 0
  failure/error；相关 schema export、四 crate scoped fix、fmt/fmt-check 与 diff 门禁通过。workspace `just test` 在测试前被既有
  rusty-v8 v150.4.0 archive HTTP 404 阻断，core/protocol 宽轮也受范围外 proxy/mock 环境失败影响，均未冒充通过或用于扩大写集。
- 未运行 Docker、真实 API/模型、训练、测评、CI/PR 或远端操作。Plan 078 的 `#37847` 前置已先期进入本地 `main`；Plan 077 /
  M4-C1 正式实现随后、先于 M4-S2 正式轮进入主线。M4-S2 正式轮作为后整合者负责 shared 接缝收敛及 query/lifecycle 聚焦兼容
  验收；这是 Plan 077 完成时的交接状态，M4-S2 的随后完成事实见下节。

## M4-S2 恢复与生命周期收口（Plan 078，2026-08-25）

**状态**：`#37847` 独立前置、M4-S2 产品实现、两轮 correctness 整改与外部复验均已完成；验收通过、任务目标完成，结论为
`M4_S2_PASS`。主体提交为 `8300826`，最终 owner-race 整改提交为 `7014250`，外部复验提交为 `4fd5805`。

- Durable Root cold resume 保持 Session/Root/Team identity，V2 member 仅在真实消费入口 lazy reload；顶层 fork/new/clear 创建新
  Session/Root/空 Team，`spawn_agent fork_turns=none/all/N` 只改变 child context 并留在原 Team。`#37847` 同时保证 inherited
  environment 在 member reload 后保留且显式 override 优先，不自动启动 turn、模型或 API。
- detach 不等于关闭；idle unload、正常/失败 shutdown、InternalAgentDied、archive/delete 与 running-resume timeout 均复用
  descendant-first close/admission barrier。late observer 持有 exact owner/generation 到最终收尾，失败保持可定位、可重试 owner，
  不误清 replacement、residency 或提前释放 Root authority。
- archive/unarchive/delete 通过 ThreadStore 冷态域处理 writer、subtree、partial 与 unknown。delete 先移除 Team artifact、后移除
  Root marker，支持中断后重试；旧版、损坏、身份不一致和不兼容状态 fail-closed，未建设 takeover、relay、queue 或第二套 registry。
- 正式证据包括 thread-store `199/199`、app-server `1134/1134`（1 skipped）、fresh 生命周期 `23/23`、core 聚焦 `19/19`；最终
  owner-race 整改又通过 core `8/8` 与 app-server `1/1`。三个受影响 crate 的 scoped clippy/fix、fmt 与 diff 门禁通过，外部复验
  无剩余 high/medium correctness finding。
- core 全量历史批次为 `3417 pass / 16 fail / 8 skipped`；16 项来自范围外 Publication Critic 环境、旧 fixture、realtime timeout
  与共享 target 的旧 schema artifact，不冒充全量 PASS。未运行 Docker、真实 API/模型、训练、测评、CI/PR 或远端操作。
- 主线整合时，Plan 077 的 canonical query read/locator seam 与 Plan 078 的 snapshot path/lifecycle-write seam 在三个 shared 文件中
  做加法收敛，`just fmt-check` 与 diff 检查通过。因用户未追加重型 Cargo 授权，合并树 query×lifecycle 聚焦回归未在本批重跑；
  该轮作为后续正式 Session Control/TUI 的首批获批门禁，不表述为已通过。

## Publication Critic Skywork 4B 云端基座质量测评（Plan 079，2026-08-25）

**状态**：exact `Skywork/Skywork-Reward-V2-Qwen3-4B@fd958fef475f323f4e6b195930e3dd918485c668` 原始 BF16 base 的
commissioning、唯一正式轮、独立复算、一次验收整改与最终复验均已完成；验收通过、任务目标完成，终态为
`4B_BASE_QUALITY_NO_GO`。正式评分绑定源码 `610d880`，交付实现为 `b671f51ff63f1f80aaddbd035e57634adb1838f5`，
formal retry 整改为 `d29e857`，最终独立验收提交为 `43cf0eeb3e1b4826c60924fc1385319d7adead3a`。

- 唯一正式轮 `plan079-formal-20260825T175912Z-610d880-r1` 从 clean source 与空 namespace 完成冻结 v8 validation 55/55，
  typed failure 为 0；完整 operating curve 无 admissible point。False PASS 为 `12/21 = 0.5714`、False REWRITE 为
  `4/34 = 0.1176`、balanced accuracy 为 `0.6555`、ROC AUC 为 `0.6218`、boundary strict win 为 `13/19 = 0.6842`，
  within-PASS 为 `6/7 = 0.8571`。相较历史 1.7B base，4B 降低 False REWRITE 但显著增加 False PASS，仍未达到发布门限。
- 正式运行复用冻结 typed packet/render、16,384 context、scalar head、score 方向、validation 与 pair/metrics；只消费物理不含
  unseen-test 的既有 train+validation bundle。未重问 Judge、训练、量化、转换、重跑 1.7B/C1/C2/C3、启用产品或解锁 M3-D。
  正式结果与独立复算逐字节一致；formal 崩溃恢复整改只允许通过完整既有合同验证的 `INCONCLUSIVE` 进入新空 namespace 重跑，
  不改变本次完整 NO-GO 结果。
- 任务 Pod `iocp8k8w6zvh4s` 已删除并确认同名查询为 0，GPU 持续费用为 `$0/h`。20 GB Standard 网络卷 `v1us0nmk0p` 按用户
  要求保留在 `US-IL-1`，观察使用量约 `7.68 GiB`、费率 `$0.00194444449/h`，删除仍须单独批准；任务交接累计费用保守上界
  `$0.3207`。没有运行本地重型 Cargo、Docker 或真实本地模型。
- 聚焦 base-quality 与 Pod monitor 测试 23/23，复用的 Plan 073 threshold/selection/archive/freeze 测试 23/23；format、定向
  `py_compile`、shell syntax、JSON 与 diff checks 通过。最终独立复验无剩余 correctness/functionality finding。
- 结果见 `eval/results/publication-critic/skywork-reward-v2-qwen3-4b-base-quality-v1.{json,md}`，执行与验收细节见对应 Plan 079
  `agent_log`。本任务没有形成后继任务授权；三期当前状态与后续选择只由 `doc/WBS.md` 及三期子 WBS 维护。

## M4-C2 正式 Session Control / TUI（Plan 080，2026-08-25）

**状态**：稳定 app-server v2→client→TUI 控制链、fresh Session/store 正式轮、两轮独立审查整改与最终复验均已完成；验收通过、
任务目标完成，结论为 `M4_C2_CONTROL_PASS`。最终验收提交为 `6865a649af11f8f93e069f436a8db855dad272cb`，主线整合提交为
`dbb8247baa202035476404c59a90af577368f238`。

- 新增独立默认关闭的稳定 `session/control`。正式 query 投影 control proof/availability；committed online proof 绑定 live Root owner
  incarnation，Team mutation gate 与 M4-S2 close barrier 在线性化点复验 exact owner、Team instance/revision/commit generation。
  cold archive/unarchive/delete 复用原生 ThreadStore 生命周期；控制面不直接写持久介质，也未新建第二套 Session/Team 状态源。
- `Close` 复用 M4-S2 owner removal barrier，成功只承诺 `OwnerClosed`；whole-Session lifecycle 不能由现有领域事实证明时仍为 typed
  `Unknown`。Applied/Rejected/Partial/Unknown 贯穿 protocol、client 与 TUI，response loss、timeout、disconnect、lag、detach 和
  late completion 均不自动重放 mutation，操作后只用正式 query 重建当前视图。
- parented child 在正式 control 入口 fail closed。Delete 对 M4-S2 保留的 canonical Root retry anchor 只允许权威重读后的用户显式重试，
  不自动重放。TUI `/session-control` 在展示确认前由 query availability/freshness 驱动 preview，并显示 Session/Root/目标范围；仅关闭
  control 不 detach query attachment。双开时正式入口优先，C0 prototype 继续隔离。
- persistence/runtime teardown 之后的 Team close completion 故障已按不可回滚终态处理：Session loop 终止，lifecycle 不重开，app-server
  只清理 exact owner mapping、保留 replacement，控制结果保持 typed Unknown；没有新增 registry 或 mutation 自动重试。
- 第二轮整改统一了 loaded-descendant/no-Root 下 Archive/Delete query availability 与 server admission；accepted handoff 后 sender/loop
  异常进入 terminal exact-owner cleanup，显式 RetainedError 仍可回滚；owner incarnation mismatch 统一为 `NotCurrentOwner`。Close 与
  active Archive 的 after-preflight Team commit race、query residency、typed Unknown 和 replacement-safe cleanup 已形成 13/13 直接回归。
- fresh 正式轮完成 owner close、cold archive/unarchive、进程重启 list/read rebuild、delete 与 SessionNotFound，且没有启动 turn、模型
  或 API。首次独立审查的 2 High、5 Medium、1 Low 及后续复验 finding 均已闭合；最终独立复验无未关闭 correctness finding。
- 改产品代码前的合并树 query×lifecycle 基线为 `45/45`；原正式控制轮 `17/17`、邻接 query×lifecycle `47/47` 与 fresh 证据按审查
  结论在原覆盖范围继续有效。整改直接轮 29 项最终全部通过，另补 default-off/query-only/removal token 3/3、teardown 后故障注入
  1/1 与普通 app-server query 邻接 1/1；第二轮冻结代码直接回归 13/13。stable/experimental app-server schema、七 crate及最终
  core/app-server scoped fix/clippy、fmt/fmt-check 和 diff 门禁通过。
- 首轮获批清理只移除 069 `debug/incremental`。整改测试触及 270GB 告警后停止扩大范围，并在再次核对 owner/realpath/归属后只清同一
  已授权 incremental；`debug/deps` 始终保留。提交前项目/target 为 `248,862,612,879 / 175,170,759,743 B`。未运行 full-workspace、
  Docker、真实 API/模型、训练、测评、benchmark、CI/PR 或远端操作。初始执行与整改细节分别见
  `agent_log/2026-08-25-153057-plan080-m4-c2-session-control-tui.md`、
  `agent_log/2026-08-25-170351-plan080-review-remediation.md`、
  `agent_log/2026-08-25-190915-plan080-rereview-remediation.md`；最终独立验收见
  `agent_log/2026-08-25-192431-plan080-final-independent-acceptance.md`，无剩余 correctness/functionality finding。

## Publication Critic 1.7B 非 LoRA 本地训练就绪（Plan 081，2026-08-25）

**状态**：实现、五轮指定验收整改与最终复验均已完成；验收通过、任务目标完成，终态为
`LOCAL_TRAINING_READINESS_PASS`。最终实现提交为 `87929a50bb031f418ef5e1f55784e1d5b538dd23`。

- exact 1.7B、冻结 pair/input/v8、非 LoRA/QLoRA 与 unseen 隔离保持不变；新增专用轻量 route/cloud 合同、连续
  update/observation、观测驱动 scope 扩大、候选/no-improvement、评价 snapshot、完整恢复 checkpoint、retention 与归档闭环，
  未放松 Plan 060/066 历史合同或复制第二套数据/评价体系。
- checkpoint 只有经 fresh exact-base probe 完成模型载入及 controller、scope、optimizer/scheduler/RNG/data/cursor 恢复资格核对后，
  才能替代旧锚、执行 prune 或发布 completion marker；类型感知 state 等值和 task-owned tombstone 保证合法 Tensor-like state、
  资格失败、清理中断及跨进程恢复均保持保守且可续。
- cloud handoff 冻结 A40 48GB 首选、L40S 48GB 备选、单卡不超过 12 小时、外部总费用不超过 15 USD，Plan 079 保留卷非前置。
  本地 fixture/fake 只证明控制闭环，不证明真实显存、吞吐、数值稳定、训练质量或预算可行性。
- 最终独立验收复跑 Plan 081 36/36 与 Plan 060/066/073 精选历史回归 9/9，合计 45/45；主审与三路独立复核无剩余
  P1/P2/P3。未运行真实模型、GPU、云端、Docker、Cargo、全 workspace 或 unseen，也未启用 Publication Critic 或解锁 M3-D。
- Plan 082 是下一三期工作包但仍须另行立项授权；当前路线、顺序和授权边界只由 `doc/WBS.md` 与三期子 WBS 维护。

## M4-Z(core) Durable Team 全链收口（Plan 083，2026-08-26）

**状态**：公开 S/C 全链、fresh store/真实进程替换正式轮、两轮独立审查整改与最终复验均已完成；验收通过、任务目标完成，结论为
`M4_Z_CORE_PASS`。最终验收提交为 `0a68f37667188bb7886ce51d4f79436b54bb9faa`，主线整合提交为
`c71bac2040c11fb8a46830f7f420dcec921a41b9`。

- Durable child graph 持久化、participant commit 与 registry/residency 发布按 fail-closed 顺序收口；persisted Open descendant 与 loaded
  running descendant 共同阻塞 Root close。V2 `close_agent` 在当前 Team membership 边界内复用 subtree close，拒绝 foreign Root/child、
  Root 与 self；V1 合同保持不变。公开错误与 serde/schema camelCase 合同已对齐。
- 新增公开 app-server v2 全链回归：从 fresh Session/store 创建 Root/child、提交 Team State、由非 owner 权威查询，真实替换旧/新
  app-server OS 进程后恢复同一 Session/Root/TeamInstance，继续 mutation，并闭合 child/Root close、archive/unarchive/delete 与最终
  SessionNotFound。顶层 fork/new/clear 与 child `spawn_agent fork_turns`、query/control/no-replay/gates/non-durable/shared workspace
  由职责层与邻接证据共同覆盖。
- 首轮独立审查的 foreign target 与 phantom participant 两项 Medium 已整改；复审追加的 activation cleanup 顺序问题也已关闭。
  cleanup 复用 shutdown captured owner → exact map lease → Closed edge → exact retirement，任一 teardown/owner/graph 失败仍保留 Root
  close barrier；仅测试编译的定向 fault seam 不增加产品状态或第二套事务/审计设施。
- 原宽聚焦 `30/30`、schema/precomputed 与相关 scoped clippy/fmt 门禁通过；最终整改又通过 failure-ordering `2/2`、graph/Root-close
  邻接 `6/6` 与 `codex-core` scoped clippy。最终 fresh 正式轮 Nextest `fc6e8c7d-ff74-4af0-9147-a91580541ef8` 为 `1/1`，watchdog
  `20260826-012504-1000-2261794` 为 `stop=none / cleanup=none`。
- 未运行 full workspace、Docker、真实 API/模型、训练、benchmark、CI/PR 或远端写操作。执行与整改见对应 Plan 083 `agent_log`；
  最终独立验收见 `agent_log/2026-08-26-013416-plan083-final-independent-acceptance.md`，无未关闭的高/中等级 correctness finding。

## M4-W0 Writer Workspace Binding 原型与价值门（Plan 084，2026-08-26）

**状态**：test-only 价值原型、首次独立验收整改与最终复验均已完成；验收通过、任务目标完成，唯一终态为
`BINDING_ONLY_GO`。最终实现提交为 `c1870836cb3cc829d5055ffe77b042a500df18b0`，最终独立验收提交为
`d3d0ffe5d70ed81f9b7f2b6536fb568260a56c0c`，本地主线整合提交为 `df0e2902117139a100294cf08ab61edb46f633c0`。

- task-owned 临时 Git repository/two-linked-worktree fixture 以同一 fake action 形成 cooperative 与 caller-relative baseline，证明
  binding 能在两个 writer 首次动作前固定各自 cwd、workspace roots、permission 与 Git identity；cold reload 重新核对当前授权、
  worktree 和执行环境，缺失、同路径换库、权限/roots/执行环境失配只使对应 writer 不可用。
- 初次 admission 在读取目标路径/Git 前先核对调用者精确 roots 与写策略；actual action 只接受普通相对组件，对真实目标应用现有
  filesystem policy 并逐组件拒绝 symlink。父目录、绝对路径和 symlink 跨 writer 反例均在副作用前 fail-closed；replacement 先完整
  admission 后替换，失败保留旧 binding 与未交接成果。
- 合理自然语言说明加 branch/HEAD/status/diff 已能分别定位 replacement 前后 tracked 未提交成果，没有出现 minimal structured
  handoff 独有且可重复的失败，因此不新增 handoff 能力。该结论只证明 binding 的原型可行性和产品价值，不冒充 W1 生产 trust、
  持久化或 race-free 文件保证。
- 整改正式轮 Nextest `de36d02e-b180-49a1-b271-0b0e9de3b80b` 为 8/8，包含 5 项 W0 场景和 3 项
  spawn/resume/reload 相邻回归；scoped fix/fmt 与 diff 门禁通过。最终独立复验复用该保存证据，未扩大重跑范围。
- 未实施 M4-W1、上游增量或 Workspace 控制面，未运行 full workspace、Docker、真实模型/API、训练、性能测评、CI/PR 或远端操作。
  正式 W1 尚未立项，后续先按实际消费决定上游窄适配；当前路线只由 WBS 维护。

## Publication Critic 1.7B 云端连续训练与候选形成（Plan 082，2026-08-26）

**状态**：阶段 A、真实 commissioning、参数开发、干净正式轮、GPU 专项验收、大型资产交接与最终验收均已完成；验收通过、任务目标完成，
研究终态为 `VALID_NO_IMPROVEMENT`。结果相关源码为 `ff7e8a1f70b03c6b2d7a8f9a7967734d918b363b`，最终执行者提交为
`2f91f32ed0d8703038f3142e740159443b23a883`。

- exact `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`、冻结 v8、pair/input/scalar
  方向、无 unseen 与非 PEFT 边界保持不变。正式 freeze `747420ddce99e73b1e787cc4b1979629c9e5a353da6595273d0b780923b6ab87`
  在观察正式结果前绑定环境、recipe、scope、比较与保留规则；干净正式轮从 exact base 和空 namespace 完成四步 score-head 原参数更新。
- 同 cohort boundary pair mean margin 从 base `0.8252560622` 连续回落到 step 4 `0.8252007961`，没有形成 better-than-base
  checkpoint，因此按冻结规则诚实发布 `VALID_NO_IMPROVEMENT`。该终态完成研究目标，但不提供产品 GO、本地部署资格、M3-C2/unseen
  证据或 M3-D 解锁；Publication Critic 继续 default-off。
- step 2 checkpoint 经另一新进程实际恢复 model、optimizer、scheduler、RNG 与 data state 后继续完成 step 4。正式 step 2/step 4
  checkpoint、五份正式 observation 与三个 snapshot 由冻结 bootstrap 精确保留；39 个正式对象合计 `13,797,142,360` bytes，连同
  bootstrap 共 40/40 文件、`13,797,156,884` bytes，已在本地逐对象验证 bytes/SHA-256、exact-tree、`0600/0700` 权限与无符号链接。
  最终 verification receipt SHA-256 为 `7e7782b764db2a8a45bbe1a639337980b3086dc91b0975b453df4fe098e60fef`。
- 正式训练使用 US-TX-3 Secure L40S；GPU 专项验收关闭 Pod 依赖后删除训练 Pod。因 US-TX-3 不支持网络卷 S3 API，按用户一次性例外
  使用单个 Secure RTX 4090 transfer Pod 通过 SSH/rsync 只读续传，完成校验后立即删除。最终实时复核为 0 Pod、持续 compute 费率为 0；
  唯一 40GB Standard 网络卷 `mwemzrn33y` 继续保留，未经用户本人明确批准不得删除。
- 2026-08-26T11:54Z provider 可见 Plan 082 入账至少约 `$1.720537`，当前小时仍可能延迟追记；按已知训练/transfer Pod 完整墙钟、
  transfer container disk 与已见卷费计算的资源口径约 `$2.32`，另有约 `$0.003889/h` 的持续卷费。费用远低于 `$10` 告警和 `$15`
  边界；执行者交接时的 `$1.007324` 是延迟账单快照，`$1.728857` 不再作为保守上界。
- 最终审查复跑 Plan 081/082 training、handoff、scripts 与 Plan 068 相邻轻量回归 83/83；相关 Ruff 0.15.12、compileall、五支 shell
  `bash -n` 和 `git diff --check` 均通过。终审未重哈希约 13.8GB checkpoint payload，而是复核正式 loader/validator、已生成逐对象摘要、
  实树 bytes/权限和 manifest/receipt 闭合关系；无遗留高/中等级 correctness/functionality finding。
- 最终验收后，用户本人明确决定继续保留 40GB Standard 网络卷 `mwemzrn33y`；该卷当前仍未删除并继续产生约 `$0.003889/h` 的卷费。
  未来若改变决定，删除仍须新的明确人工授权。

## Linked-Worktree Trust RONDO 窄适配（Plan 086，2026-08-26）

**状态**：`#39616@bc3545b805de6e91a11b88114fe1673b678633ca` 的产品安全语义窄适配、一次独立审查整改与最终复验均已完成；
验收通过、任务目标完成，结论为 `M4_W_39616_ADAPTATION_PASS`。主体提交为
`3dc31d5f39edaef7d8f4a440c364db98dc0f9039`，nested cwd 整改提交为
`fdbdaf8e2ba2c33fbe3162858b07bffe90be87ba`。

- linked worktree 只有在 `.git` pointer、worktree admin directory、`gitdir` backlink、`commondir`、registered checkout、canonical
  identity、common directory 与 main checkout ownership 全部可证明时才继承主仓 trust；缺失、伪造、失配、symlink、超限和代表性
  metadata 变化均 fail-closed。
- project config、hooks、permission/active-project、host MCP、app-server/TUI trust target 与邻接 resolver 消费采用同一 hardened
  结论。独立审查发现并关闭 nested linked-worktree cwd 跳过 checkout root 显式 trust 的 P2；最终顺序为 exact cwd、当前 checkout
  root、已验证继承 root，直接显式 `trusted/untrusted` 保持优先。
- resolver/path/config 正式聚焦簇 21/21、合法 config/hooks 2/2、host MCP 1/1、app-server hooks 1/1 通过；整改正式轮 Nextest
  `cf9287bf-ed1d-4a47-aaaf-d4b874877c29` 为 2/2，相关 scoped fix、fmt 与 diff 门禁通过。一次组合批次被 watchdog 因 memory full
  PSI 以 exit 125 主动停止，随后拆窄通过；该设施停止未冒充产品测试失败，也未清理 target。
- 未建设 workspace registry、第二套 permission/trust、审计或可信平台，未升级冻结基线，也未运行 workspace 全量、Docker、真实
  API/模型、训练、测评、CI/PR 或远端操作。用户批准后，验收头已 fast-forward 进入本地 `main`，无冲突且未推送；`#39153`
  已获得下一任务启动资格但尚未启动，M4-W1 继续锁定。

## Permission Restore Fail-Closed RONDO 窄适配（Plan 088，2026-08-26）

**状态**：`#39153@539a09cb28ca1ded4278c6d54716abbacab42428` 的 RONDO fail-closed 产品语义窄适配、正式聚焦验证与独立验收均已完成；
验收通过、任务目标完成，结论为 `M4_W_39153_ADAPTATION_PASS`。实现提交为
`57b7efbe12808b6e06089194ab6676b5a7e537e4`；当前等待用户批准整合本地 `main`。

- cold resume 与顶层 fork 统一按“合法显式 override、最近持久设置、当前配置”恢复 approval policy、approvals reviewer 与
  active permission-profile identity。canonical `TurnContext` 以 presence-aware 三态补足普通 turn/compaction 的最小 identity 事实；
  legacy missing 与 explicit clear 都不会向前复活更老 ID。
- 只恢复 profile identity，并通过当前 catalog、Plan 086 hardened project trust、profile inheritance、workspace roots、network 与
  requirements 重新解析。missing/invalid/disallowed/incompatible profile 明确失败，不使用历史 concrete permission snapshot，
  不静默切换 configured/required default；合法显式权限 override 保持最高优先级。
- resume 的 config load 早于 runtime/thread 创建，fork 的 config load 早于 child 创建；静态独立审查确认 invalid persisted profile
  不会启动可执行 runtime、MCP/model/tool 链或带默认权限继续。唯一低等级测试余项是负向集成未直接断言 child/started 不存在，
  当前路径正确且分层证据充分，未为此扩建副作用审计设施。
- 正式证据为 protocol `1/1`、core `6/6`、app-server lib `279/279`、legacy/paginated resume/fork 集成 `5/5`，scoped fix 与 fmt
  通过；通过批次均 `stop=none / cleanup=none / swap peak=0`。未运行完整 workspace、Docker、真实 API/模型、训练、测评、CI/PR
  或远端操作，未冒充通过。
- 本任务未实施 M4-W1、primary binding、scoped authorization、replacement binding、workspace/permission registry 或第二套恢复状态。
  088 进入本地 `main` 前 M4-W1 继续锁定；进入后也只解锁另行规划资格，不自动启动。
