# Plan 004 独立验收日志

> 复验补记（2026-08-09 21:33，Asia/Shanghai）：本文件从原验收工作树逐字复制到独立整改工作树后继续记录。
> 第 1–9 节保留 20:32 初验时的证据、finding 和判定；其中整改建议与 D/H/K/G-Low 状态由第 10 节的
> 共识实现及复验结果取代。范围校正：macOS 未运行是必须披露的跨平台证据缺口，但不是 Plan 004 原始完成门禁；
> Windows 正向合同、V8 `sandbox=true` canary 和完整 workspace 仍是原计划未闭环项。

- 验收时间：2026-08-09 20:32（Asia/Shanghai）
- 验收对象：`0809-remaining-test-failures` 工作树提交
  `216ccb73296024f18e6095741e4860cea79a7b6c`
- 基线：`37b0e6625bff81099170db9168d07b8d08ef4c17`
- 合并提交：`06b2a0e523b4cadd136f5ada5beca7d71a1a9f95`
- 依据：`plan/004-remaining-test-failures-investigation.md`、实施日志、提交差异、源码、
  watchdog/JUnit 工件和本机 systemd journal
- 初验写入范围：仅本验收日志；未修改产品代码、测试代码、plan、WBS 或其他文档
- 初验测试动作：未补跑 Cargo 测试；优先复核已存在的定向、压力、负对照和静态门禁证据
- 独立整改与复验范围：见第 10 节；代码只写入
  `.claude/worktrees/0809-plan004-independent-remediation`，未触碰原工作树

## 1. 验收结论

**截至 20:32 初验，Plan 004 暂不通过完整验收，状态为“待整改并复验”，不能宣称 41 项已经全部闭环。**

实现的大部分确定性 seam、生产默认路径和 Linux/WSL 当前平台行为经静态审查未发现产品功能缺陷；已有
26 份绿色 JUnit 也都是真实、非 skip 的执行结果。但独立审查发现两项会让专项门禁假绿的 P1 测试合同缺陷：

1. D 族 Landlock 用例会把 bwrap/user namespace 启动失败产生的宽泛 `SandboxErr::Denied` 当成 wget 的
   TCP connect 被沙箱拒绝；wget 可能根本没有启动，测试仍然通过。
2. H 族 truncated replay 使用带 `up_to_n_times(2)` 上限的 Wiremock matcher 记录请求；第三个及后续
   `/responses` POST 不进入记录器，因此 `requests().len() == 2` 不能证明真实总请求数恰为 2。

这两项是验收设施缺陷，**不是已经证实的产品运行时缺陷**；但它们直接削弱了计划要求的 fail-closed 和
fake 调用计数证据，所以在修复门禁并完成定向复验前，不能接受 D/H 为完整闭环。

此外，计划明确要求的 V8 `sandbox=true` canary 与唯一一次完整 workspace 测试没有进入测试体，Windows
目标测试未运行。这些边界在实施日志中有披露，不属于假报绿色，但仍阻止按 plan 原始完成标准宣告完整验收。
macOS Seatbelt 路径也未运行，但 Plan 004 的目标环境与 I 族原始失败均为 WSL2/Linux；macOS 在本计划中是
必须披露、不得冒充已通过的跨平台证据缺口，不是完成阻断。

按用户指令，实现在本次验收结束前已经合并并推送到 `main`。交付完成不等于验收通过；本日志如实保留上述
初验阻断。D/H/K/G-Low 后续已在独立 worktree 内按共识窄修并完成必要定向复验，详见第 10 节；环境门禁
仍不因代码整改而自动变绿。

## 2. Git 与交付状态

验收前后的只读核对结果：

- feature 提交 `216ccb7` 的唯一父提交为 `37b0e66`，提交主题为
  `fix: harden remaining test failure contracts`。
- feature tree 为 `96871bc09c1e96d8915ff437879b96f4ad4a6da5`。
- `main` 使用 `--no-ff` 合并，合并提交 `06b2a0e` 的两个父提交依次为 `37b0e66`、`216ccb7`。
- 合并提交 tree 同样为 `96871bc09c1e96d8915ff437879b96f4ad4a6da5`，即没有在合并时引入额外内容。
- 本地 `main` 与 `origin/main` 均为 `06b2a0e`；`git ls-remote --heads origin main` 已精确核对远端 SHA。
- 主工作区在合并、推送和验收核对时为 clean。
- feature 工作树在写入本日志前为 clean、HEAD 为 `216ccb7`；本日志是验收后新增的唯一未提交文件。
- feature 分支没有推送，也尚未重命名为 `zz-done/...`；由于验收仍有阻断，保留其当前状态便于后续整改。

首次 push 被仓库一次性治理钩子拦截；只读确认本批实施日志与 WBS 更新存在、且本任务不涉及性能测评后，
按钩子流程重试并成功推送。这是交付流程事件，不是代码或测试失败。

提交规模为 45 个文件、1,995 行新增、335 行删除；排除 `agent_log/`、`plan/`、`doc/` 后仍有 42 个
代码/测试文件、2,006 行变动。它超过 `mydev/AGENTS.md` 中通常建议的单批规模，降低了人工审查局部性；
考虑到本计划一次覆盖 A–K 多族，这一项记为非阻断的过程偏差，不据此推定功能错误。

## 3. 验收方法与证据边界

本次做了以下独立工作：

1. 完整阅读根目录与 `mydev/` 的 AGENTS、README、当前 WBS、plan 004 和实施日志。
2. 核对 `37b0e66..216ccb7` 全部差异及 A–K 相关生产调用点、测试 seam、平台 `cfg` 和失败分类链。
3. 独立解析实施方列作绿色证据的 26 份 JUnit；逐份复算 testcase、failure、error、skip、disabled 和
   SHA-256，并与对应 `summary.env` 对账。
4. 核对压力轮的 200 个 testcase 名称，确认均为唯一的 `@stress-0` 至 `@stress-199`，无缺号或重复。
5. 从 systemd journal 复核正式 Nextest 命令确实带 `--retries 0 --flaky-result fail`，并核对 H 的
   `--test-threads 1/10 --stress-count 200`、I 的 `--stress-count 200`、V8 canary 和 workspace 命令。
6. 检查 implementation 后的 clippy/fmt/manifest/diff-check 口径与可持久化证据是否一致。
7. 由独立代码审查分别覆盖 network/sandbox/H、core/realtime/session、CLI/OAuth/API/J 和计划/工件完整性。

没有重跑已经存在且无需用来判定新 finding 的测试。原因是：两个 P1 均可由当前源码和 Wiremock/错误分类的
确定控制流直接证明；原样重跑仍会绿色，不能消除假绿。按仓库规则，真正有价值的重跑应发生在门禁修复后，
且只运行 D、H/K 等受影响的精确集合。

### 3.1 工件能够证明什么

- 26 个 XML 均可解析，UUID 均不同，总计 1,297 个 testcase。
- XML 根统计与实际 testcase 节点逐份一致；总计 0 failure、0 error、0 skipped、0 disabled。
- 26 个 `summary.env` 均为 `wrapper_status=complete`、`run_rc=final_rc=0`、
  `stop_reason=cleanup_reason=none`、`junit_status=retained`。
- 逐份重算 SHA-256 全部与 `summary.env` 一致。
- 正式命令的禁重试参数可由当前 systemd journal 还原；压力参数和过滤器与 JUnit testcase 集合吻合。

### 3.2 工件不能独立证明什么

- `.codex/` 被 Git 忽略；JUnit、`summary.env` 和生成的 `nextest.toml` 都不记录 Git SHA 或 dirty-tree
  哈希，因此不能单凭工件证明执行树精确等于最终提交 `216ccb7`。
- `summary.env` 只记录 `command_name=cargo`，不保存完整 argv。生成的 `nextest.toml` 仍含默认
  `retries=1`、`test-threads=10`；CLI 的覆盖参数只能由尚未轮转的 systemd journal 证明。
- H/I 的 200 次压力早于部分审查后窄改动；最终树有后续单次联合回归，但没有在最终 SHA 上重做全部五组压力。
  truncated 文件在最后一份具名 JUnit 后还有一次等价 `format_args` 机械修改，之后只由严格 clippy 编译覆盖。
- 两次 V8 阻塞工件只持久化了 `final_rc=101`、JUnit absent；HTTP 404 的原始 stderr 没有保存在 run 目录，
  404 具体原因只能由实施日志和当时终端记录支持。
- `fmt-check`、manifest 校验和 `git diff --check` 的 rc/stdout 没有独立工件，只有实施日志声明；本次只读
  审查没有发现与这些声明相反的现象。

因此，本日志接受这些工件为“候选实现及其后续窄回归”的有效历史证据，但不把它们夸称为“精确绑定
`216ccb7` 的五组最终压力与完整 workspace 证据”。

## 4. 口径对账

计划中的严格失败为 A–I 共 39 项：

```text
A 21 + B 5 + C 1 + D 1 + E 6 + F 1 + G 1 + H 2 + I 1 = 39
```

J、K 是两项附加测试设施事项，不计入上述 39；“41 项”应准确理解为 **39 项严格失败 + 2 项附加事项**。
对照历史 81 项与第一批 42 项清单，未发现漏计、重计或通过重命名改变分母。

## 5. 阻断与改进项

### F-001（P1，初验阻断；第 10 节已闭环）：D 族会把 bwrap 前提失败误认成网络拒绝

证据链：

- `mydev/codex-rs/linux-sandbox/tests/suite/landlock.rs:559-578` 对沙箱轮接受任意
  `SandboxErr::Denied`，之后只补充检查非零退出和 listener 没有第二次连接。
- `mydev/codex-rs/core/src/exec.rs:817-822` 使用通用 `is_likely_sandbox_denied` 把进程输出分类为
  `SandboxErr::Denied`。
- `mydev/codex-rs/sandboxing/src/denial.rs:25-49` 的宽关键词包括
  `operation not permitted`、`permission denied`、`sandbox`、`landlock` 等。
- 同一个 `landlock.rs:205-213` 已明确把 bwrap mount `/proc`、user namespace 等前提失败识别为不可用；
  这些错误同样可能包含上述宽关键词。

由此可构造确定的假绿路径：bwrap 在执行 wget 前启动失败，通用分类器把错误归为 `Denied`；wget 没有运行，
listener 自然没有第二次连接；现有断言全部成立。未沙箱 wget 正对照只能证明 host wget 和 listener 可用，
不能证明 bwrap 在负例中已进入目标 sandbox/profile。

这违反 plan 完成标准第 31–32、43–44 行和 §9.2 第 268–273 行：必须验证具体拒绝语义，bwrap/二进制
前提缺失、任意非零或基础设施失败都不能算通过。

经实施方复核后采用的最小整改合同：

1. 不用两个独立 sandbox 进程做正反对照；它只能证明前一次启动成功，不能证明 wget 那一次已进入沙箱。
2. 在沙箱负例的同一条用户命令中先输出不含 denial 关键词的唯一 marker，再 `exec` 与 host 控制轮完全相同的
   canonical wget binary/argv。只有 marker 出现，才证明命令已经进入施加 sandbox/seccomp 后的用户阶段。
3. 拒绝 bwrap/user namespace 前提错误，并要求当前 listener endpoint、`connect`/`socket` 与
   `Operation not permitted` 位于同一条 wget stderr 诊断行；继续要求 listener 无第二连接。
4. 用合成负例覆盖无 marker 的 bwrap/userns/exec EPERM、错误 endpoint 和跨行 token 拼接，机械证明这些情况
   均不能通过。

修复前 D 族不接受。

### F-002（P1，初验阻断；第 10 节已闭环）：H 族请求总数断言看不到第三个请求

证据链：

- `mydev/codex-rs/core/tests/common/responses.rs:1542-1595` 的
  `mount_sse_sequence_without_request_count_expectation` 虽移除了 `.expect()`，内部仍无条件调用
  `.up_to_n_times(num_calls)`。
- `ResponseMock` 只在 matcher 被调用时记录请求。Wiremock 0.6.5 的 mounted mock 达到调用上限后会在运行
  matcher/responder 前直接返回不匹配。
- 因而第三个 `/responses` POST 只会得到默认 404：它不会进入 `ResponseMock.requests()`，也不会触发
  `SeqResponder` 的越界 panic。
- `mydev/codex-rs/core/tests/suite/unified_exec_process_events.rs:775-791` 最后断言
  `response_mock.requests().len() == 2`；这只能证明前两个匹配请求被记录，不能证明服务器真实收到的总数恰为 2。
- `responses.rs:1535-1537` 关于“超过响应数会 panic”的 helper 注释也与实际行为不符。

这违反 plan 第 41–42 行要求的 H 族 fake 调用计数直接证明；plan §13.2 第 391–393 行还专门记录过
`up_to_n_times(2)` 加内部日志不能排除第三请求。realtime-close 已改用 `StreamingSseServer::requests()`，
不受此问题影响；缺口集中在 truncated/unified-exec 的 sequence helper 和最终提前返回路径。

最小整改：

1. 在真正的 terminal/idle barrier 后调用 `MockServer::received_requests()`，过滤目标
   `POST /v1/responses`（或等价实际路径）并断言总数恰为 2；或增加不受 cap 影响的全局计数器。
2. no-expect 分支也可移除 cap，让第三请求进入 responder 并明确失败；仅删除 `.expect()`、继续检查
   `ResponseMock.requests()` 不足以修复。
3. 增加一个刻意发第三请求的 helper 回归，机械证明门禁会失败。

修复前 H 的 realtime-close 可接受，truncated replay 不接受；现有 200/200 只能证明弱合同稳定绿色。

### F-003（完成阻断，已披露）：V8、workspace 与 Windows 证据未完成；macOS 为非阻断边界

- V8 default=false canary 实际 1/1 通过。
- V8 `sandbox=true` canary run `20260809-193011-1000-912361` 在测试执行前退出 101，JUnit absent。
- 唯一一次 workspace run `20260809-194124-1000-981676` 同样在测试执行前退出 101，JUnit absent。
- 两者均未被实施日志误报为通过；但 plan 要求 default/sandbox canary 成对通过，并在全部批次后有一次真实
  workspace 全量，因此 G 与全量门禁仍未闭环。
- Windows PowerShell 正向测试未在 Windows 运行；WSL 结果不能替代 Windows 证据。
- I 族保持 `cfg(unix)` 和 macOS Seatbelt 入口，但本次没有在 macOS 运行。

前三项是原计划的环境/平台证据缺失，不是当前已定位的实现错误；在相应环境完成前必须继续写“未运行/未完成”。
macOS 不在 Plan 004 的 WSL2 完成门禁内；只能作为跨平台覆盖缺口披露，不能宣称 Seatbelt 已通过，也不据此阻断
本计划的当前目标环境验收。

### F-004（P2，初验覆盖缺口；第 10 节已闭环）：K 族 CLI 测试未机械覆盖首次授权与去 scopes 重试

- `mydev/codex-rs/cli/src/mcp_cmd_tests.rs:7-12` 只证明 Clap 参数映射得到
  `BrowserLaunch::Disabled`。
- rmcp-client 的 launcher 计数测试直接覆盖 Disabled=0 次、Enabled=1 次，但没有穿过完整 CLI login/retry 链。
- 当前产品代码经静态核对是正确的：`mcp_cmd.rs:562` 把值传入 retry wrapper，首次调用在 `:271`，
  去 scopes 重试在 `:291`，两次均透传同一个 `browser_launch`；core/silent/default 调用保持 Enabled。
- 但如果未来这三个位置之一硬编码 Enabled，现有名为
  `mcp_login_no_open_browser_propagates_launch_false` 的测试仍可能通过；cloud 集成测试也没有 launcher spy。

这不是当前产品功能错误，但证据弱于 plan §15.2 第 472–485 行要求的“首次与重试均透传、机械证明零调用”。
建议给 retry wrapper 注入 fake login，强制首轮返回 scope 错误并断言两次收到 Disabled；另让实际 OAuth flow
通过可注入 launcher 走到 finish。按原 plan 的严格口径，补强后再把 K 标为完整通过。

### F-005（Low；第 10 节已闭环）：G canary 把非 Unicode 环境变量当成未设置

`mydev/codex-rs/v8-poc/src/lib.rs:75-84` 使用 `std::env::var` 的 `if let Ok`。Unix 上变量存在但值不是
Unicode 时会返回 `NotUnicode`，当前逻辑把它当成未设置；ASCII 非 `0/1` 已正确 panic。该行为略弱于 plan 的
“非法值 fail-closed”。建议改用 `var_os` 区分 None 与非 Unicode Some，并对后者明确失败。

### F-006（P2，初验假红风险；第 10 节已闭环）：D 控制 listener 假设一次 read 得到完整请求行

`landlock.rs:523-531` 对 TCP stream 只调用一次 `read`，随后要求数据以完整 `GET /control HTTP/1.1` 开头。
TCP 允许任意分片，这可能在压力下产生 fixture 假红。应在已有 2 秒 deadline 内循环读到 CRLF/请求头终止，
并保持有界 accept、read timeout 和线程 join。

### F-007（证据口径）：clippy、SHA 与命令记录需要收窄表述

- 实施日志第 120–121 行称 A–F/J/K 的逐份 SHA 位于 plan §17；实际 §17 没有列出这些逐份 SHA。
  本日志在 §7 补齐全部 26 个绿色 JUnit 的哈希。
- 所有受影响 crate 的 `20260809-193855-1000-971128` clippy 命令没有统一的 `-- -D warnings`；
  它通过了 workspace 已配置的 deny lint。
- 真正带 `-- -D warnings` 的最终 run `20260809-200429-1000-1103492` 只覆盖
  `codex-http-client`、`codex-api`、`codex-exec-server`、`codex-linux-sandbox`、`codex-core`。
- 准确口径应为：“全部受影响 crate 通过 workspace 配置的 clippy；最终五个审查后受影响 crate 另通过
  `-D warnings`”，不能笼统写成全部 crate 均通过严格 `-D warnings`。
- `20260809-195819-1000-12` 在最终联合回归前发生一次 `watchdog_attach_failed`、rc 81、JUnit absent；
  随后的 `195832` 正常执行并通过。这不是测试红，但属于应保留的执行历史。

### F-008（文档实时性，现已闭环）：plan/WBS 初验时尚停留在提交前状态

- 初验时plan §17 和“当前工作/后续计划”仍写“正在提交前收口”“尚待提交”，与 `216ccb7` 已提交、`06b2a0e`
  已合并推送的事实不一致。
- 初验时`doc/WBS.md:109-110` 仍写提交前需收口静态检查与工作树提交。其只列 Windows/V8 符合原计划阻断口径；
  若文档另行宣称跨平台覆盖，则仍须披露 macOS 未执行，不能把它写成已通过。
- 实施日志整体诚实记录了 V8、workspace、Windows/macOS 未完成，但 A–F/J/K 逐份 SHA 和 clippy 口径有上述偏差。

初验时按用户约束未修改这些权威文档；第10节复验、提交与推送完成后，ExecPlan、WBS、WBS-COMPLETED和实施日志
已按最终事实同步。未完成平台证据仍保持未通过口径；macOS 放在非阻断跨平台边界，而非原计划完成阻断中。

## 6. 初验 A–K 逐族验收矩阵（状态由第 10 节复验结果覆盖）

| 族 | 实现/合同 | 独立结论 | 状态 |
|---|---|---|---|
| A | resolver seam、精确登记公网、未知域名 fail-closed；生产默认仍走系统 resolver，clone/reload 保持 resolver | 源码与 40/205/1 定向证据一致，未见生产回归 | 通过 |
| B | 测试专用 Direct policy；同步/异步绕过系统/env proxy 与缓存，client `.no_proxy()`；失败 socket 保持绑定 | 配置只产生原有两种生产 policy，Direct 显式构造静态检索仅见测试路径；未见 TOCTOU 回归 | 通过 |
| C | login-shell 产品合同只排除当前 session managed proxy 与 marker，不禁止用户 profile 自带代理 | 与 plan 的具名非 hermetic 例外一致，未读取/记录 profile 内容 | 通过 |
| D | 本地 wget 正控、沙箱负例、有界 listener | 现有 JUnit 1/1，但任意 `Denied` 可吞 bwrap 启动失败，存在 F-001 假绿；另有 F-006 假红风险 | **不通过** |
| E | fixture-bounded project roots、受限 FS seam、secrets 纯函数 seam | 生产 wrapper 保持 `LOCAL_FS`/原行为，5+1 项证据一致 | 通过 |
| F | PowerShell 正向分类仅 Windows；Bash/Zsh 和非 Windows 拒绝合同保留 | 静态 cfg 正确；Linux/WSL 可接受，Windows 实机未运行 | 部分通过 |
| G | V8 单向兼容断言与显式期望 canary | default=false 1/1；sandbox=true 与 workspace 未进入测试；另有非 Unicode Low | **未完成** |
| H | realtime close barrier；truncated replay 事件/子进程/代理隔离 | realtime 的真实 server 总数断言可接受；truncated 的封顶 matcher 看不到第三请求，存在 F-002 假绿 | **部分不通过** |
| I | empty roots 正负例、read collector、helper/bwrap fail-closed | Linux/WSL 200/200，正负例与静态路径合理；macOS Seatbelt 未运行 | 部分通过 |
| J | external migration fake adder，真实 source 推导到安装/config，生产 wrapper 保留 | fake 恰调用一次，source/ref/sparse/本地 manifest/outcome 均有断言，未触达真实 GitHub/git | 通过 |
| K | `--no-open-browser`、launcher seam、cloud fixture fail-closed | 当前产品透传静态正确、helper 0/1 次测试通过；完整首次/重试链缺机械 spy（F-004） | 条件通过/待补强 |

未发现以下方面的新产品缺陷：SSRF 私网/fail-closed 语义、Direct 的生产可配置入口、OAuth token/secret 日志、
core/silent OAuth 默认打开浏览器、external 生产 adder、Unix/macOS cfg、端口占用式 TOCTOU、防止无界 accept、
realtime 的 websocket/SSE terminal barrier。上述结论仅覆盖本提交差异与调用链，不扩大为真实网络、真实浏览器、
Windows/macOS 或 V8 sandbox 的运行证明。

## 7. 已有测试工件复核

### 7.1 26 份绿色 JUnit

以下 SHA 均由本次独立重算，与各自 `summary.env` 一致；每行均为 0 failure、0 error、0 skip、0 disabled，
`final_rc=0`、`junit_status=retained`、stop/cleanup reason 均为 none。

| 范围 | watchdog run | testcase | JUnit SHA-256 |
|---|---|---:|---|
| A network filter | `20260809-191628-1000-800809` | 40 | `2fdd129931ff8d50b3d62d5e12ca79854ae08d64abaa8627305ac5f3c709f3f4` |
| A network package | `20260809-191709-1000-807694` | 205 | `e67a25ba1eb142a83914c72be13c02501c5ac3effdab52b521c36766e4ccc791` |
| A core decider | `20260809-191719-1000-808585` | 1 | `9bf7053911f3f557fd568e195aca1dd91d59c280952cbffc1d2177d29000f660` |
| B HTTP client | `20260809-191735-1000-809139` | 18 | `317a96d422b16edf3748bb48eb0a23906a1e19abf34089411fee311e8e714d75` |
| B codex-api | `20260809-191808-1000-814542` | 1 | `7065d1854ad156541761f8465e1894368b3e5facff6c2466fe97172d7a26f094` |
| B CLI doctor | `20260809-191900-1000-821764` | 1 | `ad9cfd8805b4548a0c77dfac26a0c533e3755a346cf40b65e6be55f54d5957eb` |
| B core-plugins | `20260809-192411-1000-875452` | 1 | `4445daa6fb1615b614629df267fc858554e1e189738b3f61aec51659519186ce` |
| B exec-server | `20260809-192437-1000-877154` | 1 | `e65f796829f2a22e143d36cd794788846fa6667b11b605c05e0f63f3231a8dab` |
| B guard + C | `20260809-192500-1000-877913` | 2 | `ce63a95e3cffd25c7f3a779ff2bc5f9ef3a3d01ab18c6d8016276b6075ed7336` |
| D Landlock | `20260809-192759-1000-899499` | 1 | `c902d9fc0d647188a1312378055786f0e0b8bb6a37516c9f5ec3f1a96488b06c` |
| E core | `20260809-192832-1000-900662` | 5 | `fe97400b10ed9eb87ced2191391e1e0c1c4eff9449904a6e43162c8bc6474c20` |
| E secrets | `20260809-192844-1000-901190` | 1 | `5308fd796c571341aedfe1a77c1315976fbbfcddb27326686812c01d711972fd` |
| F Linux/WSL | `20260809-192935-1000-908765` | 1 | `6d2d5aa1f865041841831a479f66b5c5206e9de390484bda7407eda61ccebc12` |
| J external migration | `20260809-193058-1000-913811` | 3 | `30c5ac0d62dcbe7b6b3e178a501965df51b7e3e6865bac61097c3c7bd5220f56` |
| K rmcp-client | `20260809-193119-1000-915651` | 2 | `50d1d1845dc949d1c91a30e044ad638056eaa2bbb22e7c16ce92785d0c259e29` |
| K CLI/cloud | `20260809-193245-1000-933424` | 2 | `d23bf872c974dd754e909300342cd6b1f7a90042d4204dedd2c185ee0e00025d` |
| G default canary | `20260809-192947-1000-909276` | 1 | `d210bad3dc37e1ac66883e13d5b4f3724475c96870aa891d4015b502ebc968d4` |
| I 修改后压力 | `20260809-183819-1000-632851` | 200 | `7cf2b5f37327e43fcddc40327208275f837c036d8014f1de11f1e675df592a28` |
| H realtime 1 thread | `20260809-190338-1000-695860` | 200 | `e2538b998c2b9e1015cf1ac36e06871a24527da187f151569f2c18e0d40372c4` |
| H realtime 10 threads | `20260809-190508-1000-720055` | 200 | `c0f994937d3fd3680f1876312c610ec591dd54a7a456fc802a07dad9d73f3881` |
| H truncated 1 thread | `20260809-191127-1000-763175` | 200 | `f00da40dd0b41c78d2ddb07392af53760ba8a6f66ffccccbd72c7f6ced4f2d30` |
| H truncated 10 threads | `20260809-191322-1000-781597` | 200 | `e160f5dd15806bcaa8e17179bd6352b6e7d4cfe3a834cec3274329153430ffdd` |
| H clippy 后收口 | `20260809-194348-1000-1014436` | 2 | `5522cf573b6152c42f604d2b3adbf09feee6aecb17345fcf1a987c25a3706c93` |
| H 子进程收口 | `20260809-195026-1000-1037637` | 1 | `777f26b902d77ea864458d41b07781f50d8b3572ea1ccf09e5638574fcca3dd6` |
| D + I 审查回归 | `20260809-195141-1000-1041018` | 2 | `07fb3110ba7672530c0d161a5dad4f027c31920569f88e07f10bd9ee42f0851a` |
| 最终 B/D/H/I 联合回归 | `20260809-195832-1000-1068951` | 6 | `de9ae140ceb458613ea8b17b170f6e6b2380ceb3836074e59b054603ec42a7ef` |

总计：**1,297 testcase，0 failure，0 error，0 skip，0 disabled**。

工件路径统一为：

```text
.codex/build-watchdog/<run-id>/junit-local.xml
.codex/build-watchdog/<run-id>/summary.env
```

### 7.2 H/I 压力前后对照

| 阶段 | run | 通过/失败 | skip |
|---|---|---:|---:|
| H realtime 修改前，1 thread | `20260809-180749-1000-445342` | 200/0 | 0 |
| H realtime 修改前，10 threads | `20260809-181248-1000-497867` | 199/1 | 0 |
| H truncated 修改前，1 thread | `20260809-181533-1000-522598` | 197/3 | 0 |
| H truncated 修改前，10 threads | `20260809-181756-1000-540888` | 197/3 | 0 |
| I 修改前 | `20260809-182105-1000-559765` | 3/197 | 0 |
| I 修改后 | `20260809-183819-1000-632851` | 200/0 | 0 |
| H realtime 修改后，1 thread | `20260809-190338-1000-695860` | 200/0 | 0 |
| H realtime 修改后，10 threads | `20260809-190508-1000-720055` | 200/0 | 0 |
| H truncated 中间轮 | `20260809-190633-1000-741775` | 199/1 | 0 |
| H truncated 修改后，1 thread | `20260809-191127-1000-763175` | 200/0 | 0 |
| H truncated 修改后，10 threads | `20260809-191322-1000-781597` | 200/0 | 0 |

所有 200 次轮次的 testcase 都是唯一 `@stress-0..199`。修改前 realtime 的红项为等待事件超时，I 的
197 项为 `deadline has elapsed`；truncated 中间轮唯一红项记录 `responses_requests_observed=0`。

需要特别强调：失败压力轮中 Nextest/watchdog 最终码可能仍为 0，而 JUnit 是红色；这证实 plan 要求解析 XML、
不能只看进程码是必要的。另一方面，H truncated 修改后 200/200 也不能反驳 F-002，因为第三请求正是被 matcher
上限隐藏，原样压力只会重复验证同一个弱合同。

### 7.3 负对照与未运行工件

- H 禁网负对照 `20260809-200731-1000-1108959`：1 testcase、1 failure、0 error/skip，
  `final_rc=100`，SHA-256
  `7ecb8037a47d9ae4931344ed47ca6c41ac7d4bb006eac3823842a0ed10dec152`；failure 为
  `requires loopback networking`。它能证明禁网前提不再通过测试体内提前返回静默变绿。
- V8 sandbox canary `20260809-193011-1000-912361`：`run_rc=final_rc=101`、JUnit absent、
  stop/cleanup none；没有 testcase 结果。
- workspace `20260809-194124-1000-981676`：`run_rc=final_rc=101`、JUnit absent、
  stop/cleanup none；没有 workspace testcase 结果。
- 严格 clippy 首轮 `20260809-200154-1000-1088950` 因 `uninlined_format_args` 编译失败；等价机械修正后
  `20260809-200429-1000-1103492` 通过，命令为五个受影响 crate 的 `cargo clippy --tests ... -- -D warnings`。

### 7.4 关键命令证明

systemd journal 中的 `Started ... - <argv>` 记录确认所有正式 Nextest run 均含：

```text
cargo nextest run --config-file <run>/nextest.toml --no-fail-fast ... \
  --retries 0 --flaky-result fail
```

关键压力/阻塞命令分别为：

```text
-p codex-core --test-threads 1  --stress-count 200 ...
  -E 'test(/conversation_close_routes_only_remaining_transcript_tail_once/)'

-p codex-core --test-threads 10 --stress-count 200 ...
  -E 'test(/conversation_close_routes_only_remaining_transcript_tail_once/)'

-p codex-core --test-threads 1  --stress-count 200 ...
  -E 'test(/exec_command_consumes_pushed_remote_process_events::truncated_event_replay/)'

-p codex-core --test-threads 10 --stress-count 200 ...
  -E 'test(/exec_command_consumes_pushed_remote_process_events::truncated_event_replay/)'

-p codex-exec-server --stress-count 200 ...
  -E 'test(/remote_process_preserves_empty_workspace_roots/)'

-p codex-v8-poc --no-default-features --features sandbox ...
  -E 'test(/sandbox_feature_matches_linked_v8/)'

# 唯一一次 workspace 尝试
cargo nextest run --config-file <run>/nextest.toml --no-fail-fast \
  --retries 0 --flaky-result fail
```

这些 argv 当前可从 journal 复核，但没有写入 watchdog 工件；本日志只保存关键命令族，不声称替代完整 journal。

## 8. 初验提出的最小整改清单（实际执行见第 10 节）

在不扩大为无关重构的前提下，完整验收至少需要：

1. **D 必修**：在同一 sandbox 命令内输出唯一 inner-stage marker 后 `exec` 同一 wget binary/argv；拒绝
   bwrap/userns 不可用输出；把 connect 拒绝语义绑定到当前 endpoint 的同一诊断行；增加前提失败负对照。
2. **H 必修**：用 server 全局请求日志或不封顶计数器统计真实 `/responses` POST 总数；增加第三请求必红回归。
3. **K 按原 plan 补证**：让 Disabled 穿过首次 OAuth 和去 scopes 重试的 fake/spied 调用链，证明两次均不打开浏览器。
4. **G/全量必补**：解决或绕过官方 V8 sandbox 预编译资产可用性后，成对运行 default=false 与 sandbox=true
   canary；随后只运行一次完整 workspace，不能把编译前 404 写成测试通过。
5. **平台边界**：Windows PowerShell 正向门禁属于原计划必需证据；macOS I 族 Seatbelt 是非阻断的跨平台
   覆盖入口。无法获得平台时均须明确标为未运行，不以 WSL/Linux 替代，但二者严重性不同。
6. **低成本稳固**：D listener 在 deadline 内循环读完整请求行；G canary 对非 Unicode 环境值 fail-closed。
7. **文档收口**：获准后更新 plan/WBS 当前状态和实施日志的 clippy/证据口径；不要重复堆叠历史。

建议的最小 Cargo 复验范围（全部仍须走项目 build lock/watchdog）：

```text
# D：修复后 exact test + classifier 前提失败窄回归，JUnit 必须非 skip
just test -p codex-linux-sandbox --retries 0 --flaky-result fail \
  -E 'test(/sandbox_blocks_wget_tcp_connect/)'

# H：先跑 helper/第三请求负对照，再重做 truncated 的两组计划压力
just test -p codex-core --test-threads 1 --stress-count 200 --retries 0 --flaky-result fail \
  -E 'test(/exec_command_consumes_pushed_remote_process_events::truncated_event_replay/)'
just test -p codex-core --test-threads 10 --stress-count 200 --retries 0 --flaky-result fail \
  -E 'test(/exec_command_consumes_pushed_remote_process_events::truncated_event_replay/)'

# K：仅 CLI/retry/launcher 的新增或受影响精确测试
just test -p codex-cli -p codex-rmcp-client --retries 0 --flaky-result fail \
  -E 'test(/mcp_login_no_open_browser/) or test(/oauth_login_.*browser_launcher/)'
```

修复 D 不需要重跑无关 A/B/C/E/F/J；修复 H 的 truncated helper 不需要重跑已使用真实
`StreamingSseServer` 的 realtime 200 次压力。所有正式结果仍须独立解析 JUnit 的 testcase/failure/error/skip，
不能只看 rc。代码整改后的必要定向门禁应先独立解析 JUnit；待 V8 sandbox 资产前提具备后，再按 plan 补一次
完整 workspace，而不是在每个小修后重复全量。

## 9. 初验最终判定与可接受声明（由第 10 节复验结论更新）

当前可以准确声明：

- `216ccb7` 的大部分 A–K 实现与生产默认路径经独立静态审查合理；未发现已证实的产品安全回归。
- 26 份列作绿色证据的 JUnit 真实存在，合计 1,297 testcase，全部无 failure/error/skip，哈希匹配。
- H 的修改后压力数字和 I 的 200/200 数字属实；H 禁网负对照也按预期真实失败。
- 实现已经通过 merge `06b2a0e` 交付到远端 `main`。

当前不能声明：

- “A–F、H–K 全部验收通过”：D 与 H truncated 的门禁存在确定假绿路径，K 的完整透传证据不足。
- “41 项已经完整闭环”：G sandbox canary、workspace 与 Windows 证据尚未完成；macOS 是另行披露的非阻断边界。
- “五组压力均精确运行在最终提交 `216ccb7`”：工件不绑定 SHA，且最后审查改动晚于部分压力轮。
- “全部受影响 crate 均通过 `-D warnings` 严格 clippy”：最终严格命令只覆盖五个 crate。
- “V8 404 已由持久工件完整证明”：现有工件只证明测试前 rc 101 和 JUnit absent。

**初验状态：不通过完整验收，允许以当前已交付实现为整改基线；F-001、F-002、F-004、F-005、F-006 的
后续闭环与当前剩余环境边界见第 10 节。**

## 10. 独立整改与复验（2026-08-09 21:33）

### 10.1 工作树、授权与共识边界

- 独立整改工作树：
  `/home/sjc/desktop/RONDO/.claude/worktrees/0809-plan004-independent-remediation`
- 分支：`0809-plan004-independent-remediation`
- 基线：已推送的 `main@06b2a0e523b4cadd136f5ada5beca7d71a1a9f95`
- 整改提交前快照：7 个 Rust 文件，binary diff SHA-256：
  `939960a4a8e3f394e15d1ee988cef6c78716c9edf6d9aa85d1a606fafa9f5167`。
- 原工作树 `.claude/worktrees/0809-remaining-test-failures` 继续由原执行方使用；本次没有在其中编辑、构建、
  提交或切换分支。本日志最初从原工作树逐字复制到新工作树，之后只在新副本追加和校正。
- 收口核对时主工作区和 `origin/main` 仍同为 `06b2a0e`，但主工作区已有用户/并行任务的未提交修改；本次
  全部保留且未触碰。因此第 2 节“主工作区 clean”只描述 20:32 初验时点，不是本节收口时的实时状态。

原执行方对初验提出四项异议。独立评估后的共识如下：

1. macOS 未运行必须披露，但不自动阻断以 WSL2/Linux 为目标的 Plan 004；Windows 正向合同仍是原计划必需缺口。
2. K 的证据缺口成立，但严重性为 P2，不与 D/H 的确定 P1 假绿等同；采用 CLI retry fake、rmcp 实际 finish
   launcher 注入和既有 cloud E2E 的组合证明，不造重型单体 OAuth E2E。
3. D 不采用两个独立 sandbox 进程的正反对照；在同一沙箱命令中先输出唯一 marker，再 `exec` wget，才能证明
   发生拒绝的那次命令已经进入沙箱用户阶段。
4. H 保留 sequence helper 的 cap 与现有响应行为；在 terminal barrier 后读取 Wiremock server 全局请求日志，
   并用第三请求回归证明 cap 拒绝的请求仍能被全局计数看到。

上述四项均达成共识后才落地；没有遗留需要用户裁决的实现分歧。

### 10.2 实质修改

#### D：Landlock wget 合同与 listener

文件：`mydev/codex-rs/linux-sandbox/tests/suite/landlock.rs`

- host 控制轮和 sandbox 轮只解析一次 PATH，使用同一个 canonical、绝对、UTF-8 wget 路径和相同 wget argv；
  两轮均为 `--no-proxy --tries=1 --timeout=2 -O-`，目标是同一随机 loopback listener。
- 控制 listener 的 accept 继续有 2 秒 deadline；读取改为在同一 deadline 内循环到完整 HTTP header 终止符，
  上限 16 KiB，处理 `Interrupted`，避免单次 TCP read 的假红。
- sandbox 轮使用同一条命令：`bash --noprofile --norc -p -c` 先打印
  `__codex_wget_inner_ready_4d0bf61b__`，再 `exec` 原 wget argv。marker 不含 denial 分类关键词。
- 从 `ExecParams` 环境显式删除 `BASH_ENV`、`ENV`；Bash privileged mode 同时忽略导出的 shell functions、
  `SHELLOPTS`、`BASHOPTS` 等环境入口，防止 marker 后的 `exec` 被 ambient function 覆盖。
- 只有在以下条件全部成立时才接受 `SandboxErr::Denied`：非零退出、stdout 精确出现 inner marker、无已知
  bwrap/user namespace 前提错误，并且 stderr 的**同一行**同时含当前 listener `IP:port`、
  `connect`/`socket` 和 `Operation not permitted`。
- 仍要求 listener 没有第二次连接；Timeout、missing binary、connection refused、错误 endpoint、通用 Denied
  或任意非零都不能成为通过依据。
- 新 classifier 回归与主测试共享 `sandbox_blocks_wget_tcp_connect` 名称前缀，原 Plan filter 会同时选择两项。
  回归覆盖：真实形态正例、错误 endpoint、缺 marker、bwrap mount-proc、user namespace、marker 后 exec EPERM，
  以及 endpoint/connection-refused 与无关 EPERM 分散在两行的拼接假绿。

独立审查在整改过程中另外捕获并阻止了三次残余假绿：最初只要求 marker + 任意 EPERM；随后对整段 stderr
分别 `contains` 可跨行拼接；最后 Bash 仍可继承导出的 `exec` function。三项均在正式门禁前收紧并补负例。

#### H：真实 `/responses` POST 总数

文件：

- `mydev/codex-rs/core/tests/common/responses.rs`
- `mydev/codex-rs/core/tests/suite/unified_exec_process_events.rs`

修改内容：

- 保留 `.up_to_n_times(num_calls)`；修正“超过 body 数会 panic”的失实注释，明确超额请求会落入 Wiremock 默认响应。
- 新增 `received_responses_request_count`，读取 `MockServer::received_requests()`，只统计 method 为 POST 且 path
  以 `/responses` 结尾的全局请求；被 cap 拒绝并返回 404 的第三请求也在 server 记录中。
- 新回归连续发送三次 Direct POST，断言状态 `200/200/404`、局部 `ResponseMock` 只记录 2 次、全局记录为 3 次。
- Plan 点名的 non-managed truncated replay 在收到 `TurnComplete` 并等待 exec-server cleanup 后，断言真实全局
  POST 总数精确为 2，再读取前两个请求体。

独立审查确认 Wiremock 0.6.5 在 cap/matcher 判断前写入 server 全局日志，过滤条件与原 mock 的目标路径等价，
且目标断言位于可靠终态屏障后。参数化函数中的 managed-network case 仍使用原 capped `ResponseMock` 计数；它们
不是 Plan 004 点名的 truncated case，若以后要统一加固，需要先设计该路径自己的终态屏障，属于范围外 Low，
不把它升级为本批 P3。

#### K：CLI `--no-open-browser` 的两轮透传与实际 finish

文件：

- `mydev/codex-rs/cli/src/mcp_cmd.rs`
- `mydev/codex-rs/cli/src/mcp_cmd_tests.rs`
- `mydev/codex-rs/rmcp-client/src/perform_oauth_login.rs`

修改内容：

- 新增私有 `perform_mcp_login_from_args_with`；生产 `run_login` 与 CLI exact test 均从完整 `LoginArgs` 进入同一
  seam，`LoginArgs -> BrowserLaunch` 的映射只在该 seam 内发生。
- retry 逻辑拆成可注入 performer 的私有 helper。测试用真实 `OAuthProviderError(invalid_scope)` 强制首轮失败，
  断言第一次收到 discovered scopes、第二次收到空 scopes，并且两次均为 `BrowserLaunch::Disabled`。
- production closure 当前把收到的 `browser_launch` 原样传给 `perform_oauth_login`；`mcp add`、core、silent 和
  默认入口的显式 `Enabled` 行为未改变。
- `OauthLoginFlow::finish` 直接委托私有 `finish_with_launcher`，生产 launcher 仍是 `webbrowser::open`。
  rmcp 两个测试通过真实 finish 路径分别证明 Disabled 为 0 次、Enabled 为 1 次；fixture 使用 loopback metadata、
  Direct HTTP 和预置 callback error，不打开真实浏览器、不访问外网、不长等待。
- 既有 cloud E2E 继续验证 authorization URL、callback、token 持久化与 logout，三层组合闭环原 P2。

组合证明的固有窄边界是：若未来只在 `run_login` 的单行 production closure 内故意丢弃收到的参数并硬编码
`Enabled`，CLI fake 不直接执行真实 closure；当前转发已静态核对正确，下游 finish 又有独立机械证明，因此不再
作为原 P2。CLI 无 flag 的对称 Enabled seam 测试可作为 Low 后续补强，不影响本次合同。

#### G-Low：非 Unicode 环境值 fail-closed

文件：`mydev/codex-rs/v8-poc/src/lib.rs`

- canary 改用 `std::env::var_os`；只有 `None` 表示未设置。
- 解析函数只接受精确 Unicode `0`/`1`；其他 Unicode 或非 Unicode `Some` 都明确 panic。
- Unix 回归使用 `OsStringExt::from_vec(0xff)` 直接调用纯 parser，不修改进程环境，避免测试并发污染。
- 该修改只闭环 F-005；不改变或替代 V8 `sandbox=true` 资产门禁。

最终跨 7 个 Rust 文件的独立集成审查结论为 P1=0、P2=0、P3=0，diff 快照哈希与本日志记录一致。保留的 Low/
范围说明只有：两个 managed-network 参数 case 没有扩大为“全局总数恰为 2”的新合同；相邻、未参与本次 H 修复的
response/compact sequence helper 仍有同类“超额会 panic”的既存失实注释；CLI 无 flag 的 Enabled 映射缺一条
对称 seam 测试；Windows 非 Unicode OsString 没有对称构造测试。这些都不影响 Plan 004 本次点名合同，也不在
本批继续做加法。

### 10.3 当前树定向复验

所有 Cargo 门禁均从新工作树 `mydev/` 运行，并经 `scripts/with-build-lock.sh`、systemd cgroup 与项目 watchdog；
命令显式使用 `--retries 0 --flaky-result fail`。JUnit 由本日志再次独立解析 testcase 节点，而非只看 rc。

| 门禁 | watchdog run | testcase | failure/error/skip | JUnit SHA-256 |
|---|---|---:|---:|---|
| D 主合同 + classifier 负例 | `20260809-211533-1000-1369835` | 2 | `0/0/0` | `6e36e102916c75590ca41b41875ec0e1674ff43222b7edbddfea7ef7bcae832d` |
| H 第三请求回归 + truncated 单次 | `20260809-211614-1000-1371757` | 2 | `0/0/0` | `a9263e4a6c924eb78e387e284519616b880d6b0eda27a164475fda7dad9a53bb` |
| H truncated，1 thread × 200 | `20260809-211937-1000-1397868` | 200 | `0/0/0` | `c9477c7e3e6e81b9a61197927d6ddc9516dd6d914d0b723b62d7636adf0087e2` |
| H truncated，10 threads × 200 | `20260809-212147-1000-1416629` | 200 | `0/0/0` | `b6cb952f9d76c4c7b7e918fa08d507a9c514cbf4b7f5db841d200c90c53b41e2` |
| K CLI/retry + rmcp finish + cloud E2E | `20260809-212413-1000-1435904` | 4 | `0/0/0` | `7c5633ee4172f9a8f9ef4dcc860326f7cccd86fdcd11c616186a4a871a435b9e` |
| G 非 Unicode parser | `20260809-212820-1000-1482993` | 1 | `0/0/0` | `2235a674842dfbb795cb2bdf62741d9484fb52379f17aa688b979389127ae1f7` |

合计 409 个当前整改树 testcase，0 failure、0 error、0 skip。六份 `summary.env` 均为
`wrapper_status=complete`、`run_rc=final_rc=0`、`stop_reason=cleanup_reason=none`、
`junit_status=retained`；逐份重算 SHA 与 summary 一致。

补充执行事实：

- 受限工具沙箱内首次启动 build watcher 时，run `20260809-211155-1000-12` 因无法连接 user systemd bus
  fail-closed、rc 81，未执行 Cargo；获得既有任务授权后由同一项目 watcher 正常运行。它不是测试失败或通过证据。
- D 首次编译 run `20260809-211219-1000-1321462` 期间最后一处 `bash -p` 窄改进入工作树；虽然该轮 2/2，
  为避免“构建期间源码变化”的证据歧义，不把它列作最终证据，随后以 `211533` 原样快速复跑绑定最终代码。
- H 只重跑受全局计数改动影响的 truncated 两组压力；没有浪费时间重跑使用另一套真实
  `StreamingSseServer` 计数设施的 realtime 压力，也没有重跑 A/B/C/E/F/I/J。
- G 只运行新增 parser 回归。已知缺失的 rusty_v8 sandbox 预编译资产和完整 workspace 没有再次重复触发；
  其历史 rc 101/JUnit absent 边界保持不变。

### 10.4 静态与资源门禁

- `cargo fmt --all -- --check`：通过；stable rustfmt 只输出仓库既有 nightly-only
  `imports_granularity` warning。
- `env UV_CACHE_DIR=/tmp/rondo-plan004-uv-cache just fmt-check`：通过、无输出；临时 Python formatter 依赖
  放在 `/tmp`，未写入产品树。此前两次未形成有效门禁的尝试分别被只读默认 uv cache 和受限网络拦截。
- `git diff --check`：通过。
- 五个受影响 crate 的严格门禁：
  `just clippy -p codex-linux-sandbox -p codex-core -p codex-cli -p codex-rmcp-client -p codex-v8-poc -- -D warnings`。
  run `20260809-212921-1000-1487198` 为 `run_rc=final_rc=0`、`stop_reason=cleanup_reason=none`、
  `junit_status=not_applicable`。
- clippy run 的 peak memory 为 9,083,662,336 bytes、swap 为 0；最终 project/target 为
  179,060,555,776 / 56,289,705,984 bytes，低于 195/200GB 主动停/绝对停线，文件系统仍保留约 742GB。
- 最重的 K 组合测试 peak memory 为 17,944,965,120 bytes、swap peak 201,715,712 bytes，仍低于
  `MemoryHigh=19G`、`MemoryMax=21G`、`MemorySwapMax=5G`，watchdog 未清理或中止。

### 10.5 复验后的逐族状态与最终判定

| 族 | 复验后状态 | 说明 |
|---|---|---|
| A–C、E、J | 通过（沿用初验） | 本次未触及对应代码，不重复运行已有绿色门禁 |
| D | **通过当前平台整改验收** | P1 假绿与 listener 假红已闭环，2/2 非 skip |
| F | **部分完成** | Linux/WSL 静态 cfg 与负合同不变；Windows 正向门禁仍未运行 |
| G | **未完成** | F-005 已闭环且新增 1/1；`sandbox=true` canary 与 workspace 仍被资产前提阻断 |
| H | **通过整改验收** | helper/目标单次 2/2，两组 truncated 压力均 200/200 |
| I | 通过当前目标环境 | Linux/WSL 既有 200/200；macOS Seatbelt 未运行是非阻断跨平台边界 |
| K | **通过整改验收** | 初次/重试 Disabled、finish 0/1 次和 cloud E2E 共 4/4 |

因此可以准确声明：

- 初验 F-001、F-002、F-004、F-005、F-006 已在独立整改树闭环，独立审查未发现新的 P1/P2；当前代码
  经 409 个受影响 testcase、H 两组 200 压力、五 crate 严格 clippy 和统一 fmt-check 验证。
- macOS 未运行继续作为非阻断跨平台证据缺口披露，不能宣称 Seatbelt 已通过，但不阻断 Plan 004 的 WSL2
  目标环境判定。
- **Plan 004 仍不能宣称 41 项完整闭环**：Windows PowerShell 正向合同、V8 `sandbox=true` canary 与完整
  workspace 尚无通过证据；后两项仍受已披露的官方预编译资产缺失影响。
- 整改已提交为 `95708749f8efffa93c0a88e1b2ffe1b4db6460b3`，经no-ff合并提交
  `8c185af30d6c65b73d1f083af6c4a8add6fed71c` 进入主线并推送远端；`git ls-remote` 与随后fetch均核对
  `origin/main` 精确指向该合并提交。已合并分支重命名为 `zz-done/0809-plan004-independent-remediation`，
  原执行方工作树未受影响。

**复验结论：D/H/K 与 G-Low 的代码整改通过；原 Plan 004 的完整验收仍因 Windows、V8 sandbox 和
workspace 环境门禁未闭环而保持“部分通过”。macOS 仅为已披露的非阻断跨平台边界。**
