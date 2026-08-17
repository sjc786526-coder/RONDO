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

## Multi M-3 —— 证据锚定（Plan 042，2026-08-17，待独立审查与合入）

**状态**：实现与定向门禁完成，落在工作树分支 `worktree-042-multi-m3-evidence-anchoring`
（提交 `db39e28`、`8360bbf`、`ce32394`、`cfe3dc1`），**尚未合入 `main`**。一轮只读独立审查已完成，
findings 全部整改（见下）。

- **两步捕获**：工具处理器产出终态时记下观察（此处才知道跑的是哪个工具、结果什么形状），结果进入
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
  相邻结果或 producer 的其他上下文。TeamState 只持 typed Fact refs，不复制工具输出。
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
- **门禁**：`codex-team-state` **101/101**；新增产品纵切 `suite::team_evidence` **2/2**；M-1/M-2 回归
  `suite::team_world_state` + `suite::team_routing` **12/12** 无退化；`core` 的 `team::evidence` **5/5**；
  合并 `tools::` 与 `context::` 共 **539/539**；`just clippy -p codex-core`、
  `just fix -p codex-team-state -p codex-core`、`just fmt`、`just fmt-check` 通过。
- **边界**：功能默认关闭，关闭时不注册 `team_evidence`、不改变普通工具结果与 rollout 行为。未建 artifact
  store、全量输出副本、完整 transcript/provenance graph、自动 freshness 验证或跨进程持久化；未运行全
  workspace、Docker、真实 API、本地模型或付费测评。执行细节与环境坑见
  `agent_log/2026-08-17-040656-plan042-multi-m3-evidence-anchoring.md`。
