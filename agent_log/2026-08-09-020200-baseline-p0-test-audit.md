# 0.147.0 基线、P0、测试设施与全量失败复验

日期：2026-08-09  
工作树：`.claude/worktrees/0809-baseline-p0-acceptance`  
分支：`audit/0809-baseline-p0-acceptance`  
边界：未修改只读 `codex-source-code/`，未修改网络/宿主配置，未修任务 4 的失败测试，未运行 Docker
或真实 API，未提交、未合并、未推送。

## 结论

- **0.147.0 基线迁移通过源码树验收**。迁移内容完整，RONDO overlay 被正确重放；唯一确定的迁移
  记录错误是七处文档写了不存在的 commit SHA，已统一改为真实 peeled commit。
- **P0 定向功能验收通过，但不称 workspace 全绿或“模型确定收到请求”**。复验发现并修复三个
  实质缺口：WebSocket 建连前过早生成 `E_final`、全树递归规范化误改业务 `call_id`、结构
  `turn_id` 未规范化。16 项精确回归最终 16/16 通过。
- **P0 测试设施复用合格**：沿用 codex-core/Nextest/TestCodexBuilder/WireMock/TempDir 等既有体系，
  没有新增 crate、依赖、服务或第二套重型框架。
- **看门狗阈值有实测支撑，主测试入口合格；原脚本可靠性不完全合格**。本轮补了信号清理、终止确认、
  活跃期计数器 fail-closed、rustc throttle fail-closed，并把 Unix benchmark 纳入入口。直接 Cargo 和
  部分 schema/run 脚本仍可绕过；彻底禁止所有旁路需要启动层设计，本轮没有大规模重构。
- **历史全量失败不能凑绿，也没有证据显示主体是 RONDO/P0 回归**。主要是上游 release fixture、
  `/tmp`/HOME/WSL/代理污染、非 hermetic 网络测试、V8 feature 组合和少数时序欠账。最新严格轮原始
  stdout/JUnit 未保留，只能以清单和另两轮 raw log 交叉归因，这是证据保存缺口。

## 1. 基线迁移证据

- 官方 annotated tag object：`3ed6f04f...`；`rust-v0.147.0^{}` 的真实 commit：
  `be6e8eac029b183056b7e4402879f15d2c85f61b`。原记录的
  `be6e8eac34711945bc47d57635f4759f20f08df9` 在上游对象库不存在。
- 已在 WBS、WBS-COMPLETED、开发环境、eval 数据布局、P0 plan 和两份 8 月 8 日日志共七处做最小
  事实纠错；历史行为和测试数字未改写。
- 上游 `0.146.1 -> 0.147.0` 与 RONDO 迁移提交父子之间均改变 1,543 个相同路径；迁移后双方均有
  6,004 个 tracked files。
- 除 `Cargo.lock` 外，15 个 RONDO overlay 文件精确等于旧产品、旧上游、新上游的无冲突三方合并
  结果。`Cargo.lock` 只有 135 个 workspace package 从 `0.0.0` 规范化到 `0.147.0`，无其他行差；
  SHA-256 为 `bc4fe450de929afe82928734f860ca83e5f9dc5f9f1211b0974ea47b57af77ca`。
- 三个新增 workspace member 及 Cargo/Bazel/pnpm 依赖图均保留。产品不带上游三个 `.vscode` 文件，
  同时多三个 RONDO 文件；这组差异在 0.146.1 迁移前已存在，属于既有 allowlist，不是本次遗漏。
- ignored 上游快照 detached、clean 且精确匹配 tag；本轮未在其中开发或写入。

## 2. P0 复验与修复

### 发现和处理

1. `capture_final_request` 原位于共享 `build_responses_request`，早于 WebSocket 连接、增量计算和发送；
   连接失败也会留下伪 `E_final`。现改为 HTTP/WS 各自在 transport send point 前捕获。WS 仍保存可
   离线复用的完整逻辑 `ResponsesApiRequest`，不保存依赖 `previous_response_id` 的 transport delta。
2. 原规范化递归改写所有名为 `call_id` 的字段，可能污染 tool schema/参数/metadata 中的业务字段。
   现仅规范化 `input[*].call_id`，保留函数调用与结果的等价关系，并增加同名业务字段保护回归。
3. Guardian durable history 中的
   `input[*].internal_chat_message_metadata_passthrough.turn_id` 会随 child turn 改变；现仅在该结构位置
   稳定重映射，未对自由文本做脆弱 UUID 正则替换。
4. 原计划声称跨新会话整包字节稳定，但 Guardian 文本含 parent session/action id。现把承诺收窄为
   “同一份已构造请求规范化幂等”；P1 分桶使用规范化待审批动作指纹，不使用整包哈希。
5. meta 的版本号不能代表 config/catalog 后的有效 policy。字段改为
   `guardian_source_baseline=rust-v0.147.0`；P1 从 standard/Lite `E_final` 提取有效 policy 并生成
   `guardian_effective_policy_sha256`。
6. `[auto_review]` 顶层 schema 说明已覆盖 policy/model/reasoning/evidence；生成 schema 的唯一差异是
   该说明更新。

### 精确语义

- 未到 transport send point 的预取消、prompt 构造失败或 WebSocket 建连失败只写
  `meta.json/evidence:none`；到达 send point 后即使发送或流读取失败/超时，仍可能保留该次尝试的
  `E_final`。这不证明服务端或模型已收到请求。
- 实际落盘集成覆盖默认 Luna/Responses Lite；standard 路径由既有出站 wire 集成与 normalizer 单测
  分层证明，未声称已有一份 standard Guardian `E_final` 端到端样本。
- Unix/WSL 目录/文件权限为 0700/0600；Windows 依赖配置目录 ACL，不做 POSIX mode 承诺。

## 3. 测试体系复用

- P0 测试位于既有 `codex-core` 单元测试及 `core/tests/suite/{guardian_review,auto_review}.rs`。
- 复用 `core_test_support::responses`、`ResponseMock`、WebSocket mock、`TestCodexBuilder`、TempDir 和
  Nextest；没有新依赖、test crate 或常驻服务。
- 单元测试负责纯规范化、关联/幂等、权限、关闭快路和写失败；集成测试负责 permission hook、轮次
  关联、主 Agent 排除、WS prewarm 和 model/effort 出站。职责没有简单重复。
- `guardian_review.rs` 已较大；若后续继续增加 Guardian evidence 场景，可在同一 suite 内机械拆文件，
  本轮不为行数单独重构。

## 4. 看门狗审查

### 已确认可靠的部分

- Unix `just test`（包括定向与全量）、`just clippy`、`just fix` 是正式主入口，统一经过机器锁、
  systemd cgroup、磁盘/内存/swap/PSI/残留进程监督；本轮又把 `just bench/bench-smoke` 和三个 schema
  generator 接入同一路径。
- 19G/21G/5G、项目 180/195/200GB、文件系统至少留 50GB 和 PSI 连续窗口均有两次 0.147 冷构建/
  全量数据支撑，本轮没有调整阈值。
- 包装器现在捕获 INT/TERM/HUP，且用 EXIT 兜底意外 shell 退出，停止整个 scope；主动停和残留清理
  会有界重试并确认 unit inactive；
  活跃 scope 任一资源计数器异常会 fail-closed；rustc 槽、内存计数或锁设施失效时拒绝无监督编译。
- 文档不再把提高 `-j` 或关闭 watchdog/throttle 当普通开发建议。

### 验证

- `bash -n`：wrapper 与 rustc throttle 均通过（命令自身也经 wrapper）。
- signal/exit smoke：受控 `sleep 60` 收到 TERM 后，wrapper 杀死 scope、返回 143；未显式捕获的 USR1
  触发 EXIT 兜底、返回 138；两轮均确认无遗留 child。
- 本轮 schema、fmt、clippy 和所有 P0 测试均经 wrapper；看门狗 summary 均为
  `stop_reason=none/cleanup_reason=none`。精确测试首轮峰值约 13.0GB、0 swap；修正断言后的增量轮峰值
  约 4.4GB、0 swap。

### 保留边界

- 直接 `cargo test/build/check/nextest`、app-server client、remote/version-skew
  脚本和 Windows Just 分支不能被机制上阻止；本轮只补最明确的 benchmark 入口。主**测试**入口已
  受保护，但不能写成“任何 AI 忘记约束都无法绕过”。
- 通用 Cargo 启动层/PATH 拦截会影响上游工具、IDE 和开发命令，属于大改，先不实施。
- 看门狗仍缺覆盖计数器损坏、kill 失败、锁竞争和低磁盘的自动化回归；本轮以真实 cgroup 运行和信号
  smoke 验证高风险路径，后续可用轻量故障注入补齐，不引入第二套重型测试。

## 5. 上游与 RONDO 全量失败归因

以下只调查，不改测试、不改网络。相关源码/测试与纯上游快照逐文件相同的类别均不是 P0 差异。

| 类别 | 现象/根因 | 应否修、建议方向 | 用户配合 |
|---|---|---|---|
| release 版本 27 | MCP fixture 与 23 个 TUI snapshot 写死 `0.0.0`，产品正确输出 `0.147.0` | 修测试：注入/规范化 `<VERSION>`，不要每次升级批量写死新版本 | 不需要 |
| `/tmp` marker 17 | 沙箱把 `/tmp/.git/.codex/.agents` 只读挂载，测试把祖先 marker 当项目根 | 修 fixture/注入 root resolver；不删宿主 marker、不改产品规则 | 不需要 |
| skills 泄漏 2 | 测试读到真实 `~/.agents/skills` | 注入 test home；不要在并行测试全局改 HOME | 不需要 |
| WSL 快照 2 | 实时 WSL 探测把 `Ctrl+V` 变成 `Ctrl+Alt+V` | 注入 `is_wsl`，分别覆盖两种合法输出 | 不需要 |
| IDE socket 5+1 | tempfile 权限依赖 umask；客户端在 accept 前被权限拒绝，1 项随后 join 超时 | fixture 显式创建 0700 目录；保留产品安全校验 | 不需要 |
| network-proxy 20 | Clash TUN DNS 把域名解析到 `198.18/15`，产品正确按本地/私网 fail-closed | 注入确定 resolver/按测试显式 allow-local；绝不白名单 fake-IP 网段 | 修好 fixture 后不需要；原样跑或实际用 managed proxy 时需 Clash real-IP DNS/fake-ip-filter，NO_PROXY 无法修 DNS |
| 代理污染 8 | localhost/closed-port、doctor、shell、plugin、landlock 等继承代理，预期 transport error 被代理响应替代 | no-proxy client、可控本地 server、隔离 shell HOME；landlock 加 unsandboxed 对照 | 不需要 |
| V8 1 | full-workspace feature unification 让 linked V8 开 sandbox，但 `v8-poc` 自身 cfg 为 false；默认 denoland archive 另有 404 | generic full 排除配置矩阵或显式匹配 feature；固定 OpenAI archive | 一般不需要，只在重下 archive 时需只读网络 |
| exec-server empty roots 1 | 本地 event wait 固定 2s，多轮复现，不是 `/tmp`/网络 | 定向 trace 判断终态真挂起还是 collector deadline 过紧，不能弱化 empty-roots 拒绝 | 不需要 |
| realtime/replay 2 | close tail 10ms poll/2s wait；1024 条通知制造截断且固定 5s，严格轮新出现 | 先保留 raw 错误，再做语义同步/背压确定化；不无脑全局增时 | 不需要 |
| PowerShell safe command 1 | WSL PATH 看见 Windows exe，但 Linux classifier 不启用 PowerShell safelist | 测试按 target OS 收口或 API 显式目标 OS；不能放宽安全分类 | 不需要 |
| external migration 间歇超时 | 测试真实 `git clone` GitHub，生产子进程无 timeout/cancel | 注入 local cloner；生产 git 增加超时/杀进程组 | 正确测试不需要；单独 live GitHub smoke 才需网络 |
| OAuth 浏览器副作用 | 测试虽通过，但 WSL 会打开 Windows 浏览器 | stub `BROWSER` 或注入 launcher/no-open-browser | 不需要 |

### 23 个 skipped

- 17 项可在标准全量中合理跳过：6 个父测试主动拉起的 child helper、4 个手工/tmux/schema writer、
  2 个真实 API smoke、5 个平台限制。
- 6 项是欠账而非“通过”：review item-id flaky、pending-input flaky、2 个注释已知错误的 compaction、
  2 个 Windows ConPTY `STATUS_DLL_INIT_FAILED`。ConPTY 需原生 Windows 复核；真实 API smoke 需要单独
  范围/轮数/预算授权。

### 网络结论

- 不建议为了测试长期关闭 Clash/TUN，也不应弱化 SSRF/local-address 策略。绝大多数失败应由测试
  hermetic 化解决。
- 只有两种情况需要用户改 Clash：原样运行这些非 hermetic 测试，或实际使用 Codex managed proxy。
  此时需让 WSL 对相关域名得到真实公网 IP（例如精确 fake-ip-filter/real-IP DNS）；仅设置 NO_PROXY
  不会改变 DNS fake-IP。

## 6. 本轮门禁

- schema generator：看门狗下通过，生成 diff 仅 `[auto_review]` 表说明。
- `just fix -p codex-core`：通过。
- `cargo fmt --all -- --check` 与仓库 `just fmt-check`：看门狗下通过；stable rustfmt 对 nightly-only
  `imports_granularity` 发出既有 warning，不影响结果。
- P0 精确组首轮：16 项中 15 通过；新 Lite 测试把缺席的 `instructions` 错写成空字符串断言。
- 修正为“`instructions`/`tools` 字段缺席”后同组复跑：16/16 通过，3,301 项因精确过滤未运行。
- 未重跑完整 workspace：本轮只窄改 P0 与看门狗，历史完整 raw 已足以定位非 P0 失败；重复冷全量会
  再占用约 100GB 级 target 且不改变任务 4 的只调查边界。
- Bazel、Docker、真实模型/API 均未运行；最新严格轮原始 stdout/JUnit 未保留。
- 收口检查无活跃 `rondo-build-*.scope`、Cargo/rustc/nextest 进程；主工作区仍为干净的
  `main...origin/main`，本轮所有修改只在审查 worktree。

## 7. 后续建议

1. Claude 先审查本 worktree 中 P0 捕获/规范化与看门狗终止逻辑，再决定是否合并。
2. 若先做测试维护，按“release + fixture 隔离 -> network no-proxy/resolver -> exec-server 定向 ->
   时序 flaky raw 保存”顺序另立任务；不要混进 P1。
3. P1 草稿见 `plan/003-p1-terminal-bench-minimal-chain-draft.md`。Docker 勘察与真实 API 分两次授权，
   精确 Terminal-Bench 版本/API/digest 必须在 B1 实测后更新。
