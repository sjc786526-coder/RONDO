# GPT 修复批次（`6cc5806`）独立验收

日期：2026-08-09

被验对象：`.claude/worktrees/0809-claude-fix-acceptance`，分支 `audit/0809-claude-fix-acceptance`，
commit `6cc5806`（父 `b9f724c`）。本轮未修改任何代码、测试、文档或 GPT 工作树；只在其工作树内
运行了受看门狗监督的验证命令（产物全部落在 git-ignored 的 `.codex/` 与 `target/`）。
`main` 与 `origin/main` 仍为 `58cc429`，005 工作树仍为 `b9f724c`。

## 结论

`6cc5806` 可以合并。GPT 本轮设定的四项目标（F2、F3、F7、第一批测试遗留）全部关闭或实质关闭，
计数与资源数字的更正与我的机械重数一致。

更重要的是：**GPT 因宿主 user D-Bus 不可用，本轮改动的 Rust 代码一行都没有编译过**，这是它自己
如实记录的验收边界。用户已恢复 D-Bus，我把这段缺口补齐了——编译、定向测试与 clippy 全部通过。

## 1. 我实际运行的验证

全部经 `mydev/scripts/with-build-lock.sh`，一次一组，串行。

| 轮次 | 命令 | 结果 |
|---|---|---|
| smoke | `with-build-lock.sh sleep 3` | exit 0，`wrapper_status=complete`，summary 完整 |
| 定向测试 | `just test -p codex-core -p codex-tui -p codex-skills-extension --lib -E '…'` | **3,630 运行 / 3,630 通过 / 0 失败**，`run_rc=0`，`junit_status=retained` |
| clippy | `just clippy -p codex-core -p codex-tui -p codex-skills-extension` | exit 0，**零 warning**，`junit_status=not_applicable` |
| 探针 | 一次性 hello-world crate 验证 nextest 绝对 JUnit 路径语义 | 见 §2 |

三轮均 `stop_reason=none / cleanup_reason=none`。定向轮内存峰值 `20,404,760,576` B（与第一批
13 轮的 `20,403,429,376` B 同一档），项目从 84.9 GB 增至 107.2 GB，远低于 180 GB 告警线。

本轮改动涉及的 6 个测试，均已在 JUnit 中按名核到并通过：
`cli_version_sanitizer_only_rewrites_known_rendered_shapes`、
`repo_ancestry_without_project_marker_does_not_walk_parents`、
`snapshot_for_config_merges_extension_host_and_legacy_plugin_roots`、
`snapshot_for_config_preserves_host_precedence_for_symlinked_plugin_root`、
`concurrent_rounds_keep_their_own_final_request`、
`guardian_source_baseline_rejects_ambiguous_or_malformed_identity`。

**未运行**：完整 workspace 全量、其余各包定向测试、Bazel（本机仍未安装）。39 个严格失败仍未实施，
`plan/004` 是方案不是结果。

## 2. F7：关闭

我此前证明的缺陷是"clippy 轮复制了上一轮 nextest 的 JUnit（同 SHA、内部时间戳更早）"。现在这个
缺陷在结构上不可能发生了，三条独立证据：

1. **探针**：nextest 0.9.140 确实接受 `[profile.local.junit]` 的绝对 `path`，并且**只**写该路径——
   `target/nextest/local/junit.xml` 根本没有被创建。这条是 GPT 只做了 `show-config` 解析、没有实跑
   验证的关键未知，现已实测闭合。
2. **真实轮**：`junit_path` 指向本轮 run directory，`junit_sha256=0060c32c…` 与我对该文件重算的
   sha256 逐字相同——记录的哈希是真实内容绑定，不是摆设。
3. **反例消失**：clippy 轮 `junit_status=not_applicable`，run directory 里根本没有 JUnit 文件。

逐轮配置也核对过：是 `.config/nextest.toml` 的逐字副本 + 追加的 junit 块，没有丢失任何 profile、
test-group 或 override。

## 3. F2：实质关闭，留一处后续项

存活主判据改为 cgroup v2 `cgroup.events: populated`，`systemctl is-active` 完全退出判定链——
D-Bus 出错不再能伪装成 inactive。报告节奏改按 `SECONDS` 计真实经过时间，我提的"最坏约 330 秒
才打印第一条、且打印的秒数不是真实秒数"两个缺陷同时消失。拿不到 ControlGroup 时即使命令返回 0
也按 81 fail-closed。

我另外确认了一处容易出错的地方是对的：EXIT trap 在最终 summary 写入**之前**被解除，所以完整
summary 不会被 `write_minimal_summary` 覆盖，`memory_peak_sampled_bytes` 等字段完好——三轮实测
summary 均完整。

**后续项（非阻塞）**：终止动作本身仍走 `systemctl --user kill`，而这正是 D-Bus 挂掉时失效的东西。
D-Bus 丢失且 scope 仍活时，包装器现在会拒绝交还控制权并每 30 秒报告——这是把"静默 fail-open"
换成了"有监督的挂起"，是实打实的改进——但它没有不依赖 D-Bus 的兜底杀法（例如递归遍历 cgroup
子树的 `cgroup.procs` 直接 SIGKILL）。建议后续补上。

**理论残留**：若 cgroup 目录先于 bash 回收子进程被移除，`scope_population_state` 会返回 unknown，
主循环将据此判 `cgroup_population_unknown` 并以 125 退出一轮本来成功的运行。3/3 真实轮均未触发；
bash 在 SIGCHLD 里异步回收后台子进程，时序强烈偏向"先回收后删目录"。记录备查，不夸大。

## 4. F3：关闭

新增受 Git 跟踪的 `mydev/codex-rs/core/upstream-source-baseline.toml`（schema/tag/peeled_commit），
编译期嵌入并严格解析，meta 同时带 tag 与 peeled commit。我独立核对：
`git -C codex-source-code rev-parse 'rust-v0.147.0^{}'` 与 `HEAD` 都是
`be6e8eac029b183056b7e4402879f15d2c85f61b`，与 manifest 一致。

对 `CARGO_PKG_VERSION` 的语义耦合被切断：二者的关系现在由
`verify_upstream_source_baseline.py` **断言**，而不再是默认假设。我原先提的"解析 WBS 文档取值"
被否掉是对的——那会让文档变成运行时配置，依赖方向反了。

小注：解析失败时的行为是"告警并丢弃该轮整个证据包"。由于该文件编译期嵌入、且被
`concurrent_rounds_keep_their_own_final_request` 的 `.expect()` 实际覆盖，实际风险约等于零。

## 5. 第一批测试遗留：三项都关闭，且都是加强而非放松

- **ancestry**：空 marker 改为唯一且确定不存在的非空 marker，恢复了"遍历全部祖先均未命中后回退
  cwd"这条测试名承诺的分支。在 `/tmp` marker 原样存在的前提下通过。
- **home override**：从可变 setter 改为构造期注入，直接消除了"setter 与既有 cache 组合"的隐患。
- **TUI 版本规范化**：从整行裸替换收窄到 `(v<version>)` 与 `<version> ->` 两种真实渲染结构，并补了
  宽度回归。我逐个核对了全部 24 份含 `[[version]]` 的快照，占位符只以这两种形态出现，所以零快照
  改动是正确的而不是侥幸——3,630 项全绿也印证了这点。

计数 42 覆盖 / 39 严格 + 2 附加、峰值 `20,403,429,376` B 与 swap `141,979,648` B，与我的重数一致。

## 6. `plan/004`：可以作为实施入口

我此前指出的错误全部被修正：计数口径、A 族 resolver 约束（禁 catch-all、禁把 TEST-NET 当公网，
改用确为公网的 `8.8.8.8`）、B 族重新分族（只有第 1 项能在测试侧直接 `.no_proxy()`）、Landlock 改以
hermetic 与断言强度立论而非"已证代理污染"、V8 全量单向蕴含 + 独占双 canary 成对。

我另外核了这份计划所依赖的工具假设，全部成立（nextest 0.9.140）：
`--stress-count`（语义确为"每个测试运行 N 次"）、`--flaky-result fail`、`--test-threads`、
`-E 'test(/regex/)'` 均存在；`environment_id_fallback_has_cwd_prefix` 确实在 `codex-secrets`，
§9 的门禁写对了。

§3 硬约束 1 要求"实施前先有一轮真实 `just test` 的 JUnit 归属 smoke"——该前置条件已由本轮满足。

## 7. 合并前建议修的文档小问题（不阻塞）

1. `doc/development-environment.md` 说按"Bash **单调** `SECONDS`"计时。Bash 的 `SECONDS` 取自
   wall-clock `time()`，与原来的 `date +%s` 是同一时钟源，并不具备抗时钟跳变的单调性。真实收益是
   每次采样少一次 fork、且报告的是真实经过时间而非重试轮数。这是一处能力表述，正好是 GPT 此前
   （正确地）要求我收紧的同一类问题。
2. 同文件把 `junit_status` 枚举为 `retained|absent|unreadable|invalid|hash_failed|not_applicable`，
   但实现还会写出 `pending`、`config_failed`、`unsupported_invocation`（preflight 路径），枚举不全。
3. `agent_log/2026-08-09-130949-claude-verification-consensus.md` 的标题读起来像是我写的，且内容
   与我在 005 的验证日志高度重复，把同一段裁决历史堆在了第二处。

## 8. 行为收窄（不是缺陷，但需知情）

- 经包装器的 nextest 现在硬性要求 `NEXTEST_PROFILE=local` 且不带 `--profile`/`--config-file`，
  否则 83 拒绝。正式入口 `just test` 满足，`plan/004` 的各族门禁也都满足。
- 快到来不及读 ControlGroup 就结束的命令，即使成功也返回 81。对重型构建无影响，但快速失败的
  cargo 调用会被掩盖真实退出码。
- 证据强制只在 `run_rc == 0` 时生效；失败轮若报告缺失只记录 `junit_status` 不 fail-closed。
  考虑到编译失败本就不产报告，这个取舍是合理的。
