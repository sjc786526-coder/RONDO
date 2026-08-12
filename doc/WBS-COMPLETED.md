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
- RONDO 归档两份自然 Sol/low Guardian `E_final/meta`，均 approved，S2 request/evidence 集合绑定为 verified。
  durable public result、pair lock、sequence ledger、profile/endpoint 和 container metrics 经生产 `assess_m1` 得到
  `m1=passed`、`reasons=[]`、`s2=verified`。
- v19 正式 pair 本地估算 `$0.870787`；Plan 014 全阶段累计 `$6.988825 < $280`，无悬挂 reservation，供应商账单
  未查询且 `actual_usd=null`。focused 155/155、`just eval-lock` 85 packages、完整 eval 345/345 通过；Docker/watchdog
  最终 `stop=none`、`cleanup=none`，0 containers/volumes。

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

### 2026-08-12 Plan 015 B7 增量编排与恢复门禁

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
  versioned catalog 仅将 filter PIDs 冻结为 512，历史 catalog/lock/result 不改写。
