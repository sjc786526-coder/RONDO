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
  默认落 git-ignored 的 `/test-data/`。外发给云端模型属数据外发，需单独授权。

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
