# Plan 105：Multi 最终全 workspace 测试与修复闭环

分支 `worktree-107-multi-full-workspace-closure`，实现冻结于 `2199316c`。
最终全量在 clean HEAD `39d5841f` 上全绿：`14713 tests run: 14713 passed, 24 skipped`，
零 failure/error/timeout、零 retry。

## 初始全量诊断轮

preflight：Windows `C:` 可用 109.8 GB、项目 168.7 GB、唯一 Multi target
`.codex/cargo-target/rondo-multi` 104 GB、无并发重型进程、锁空闲。

入口 `just --justfile multidev/justfile test-with-codex-v8-conservative --locked`
（V8 cache hit、`CARGO_BUILD_JOBS=1`、`CARGO_INCREMENTAL=0`、LLD 单线程、`NEXTEST_PROFILE=local`）：

```
14713 tests run: 14707 passed (5 slow, 3 flaky), 6 failed, 24 skipped
```

watchdog `stop_reason=none`，JUnit SHA-256
`3628c33baa26b73941c1053de4b77fb4691412c28fad11209046d4ee2317659f`。
测试段 392 秒，绝大部分耗时在冷编译。

## 6 项 failure 的归因与处置

两个根因，都不是 Multi 产品缺陷。

**（一）`FORCE_COLOR=3` —— 4 项 `codex-exec`**
`suite::approval_policy::` 三项加 `suite::resume::exec_resume_preserves_cli_configuration_overrides`。
raw 日志显示实际输出是 `^[[1mapproval:^[[0m on-request`，而断言找的是纯文本 `approval: on-request`。
产品是刻意尊重 `FORCE_COLOR` 的（`tui/src/terminal_palette.rs`、`tui/src/diff_render.rs`），
是 agent shell 注入了该变量，使 `codex exec` 头部写进管道时也带 ANSI 属性。
清空后新进程 `--retries 0` 定向复跑，4/4 通过。

**（二）app-server 启动争用 —— 2 项 `suite::fuzzy_file_search::`**
两项都停在 `initialize` 握手的 10 秒期限（`Error: deadline has elapsed`），且失败对象在不同轮次之间漂移：
初始轮是 `accepts_cancellation_token` 与 `query_cleared_sends_blank_snapshot`，
换一轮变成 `two_sessions_are_independent`。

隔离复跑同一组 12 项全部通过，单项 0.17–1.4 秒、整套 1.68 秒——`initialize` 本身约 0.2 秒。
全量轮里的 8–12 秒来自四个 app-server 同波启动时的宿主 I/O 争用，多项耗时甚至完全相同
（8.143 / 8.142 / 8.143 秒）。

修复复用既有设施：`.config/nextest.toml` 把 `suite::fuzzy_file_search::` 并入
`app_server_integration`（max-threads=1）。相邻的 zsh-fork override 早就为同一症状写了同样的处置和注释，
所以这是跟随既有惯例而不是新建机制。`cargo nextest show-config test-groups` 确认过滤器精确命中 12 项 fuzzy
加 4 项 zsh-fork。**没有放宽任何 timeout、没有弱化断言、没有新增 skip/ignore。**

另外 3 项 flaky（retry 后通过）：`fuzzy_file_search_session_multiple_query_updates_work`、
`turn_start_shell_zsh_fork_exec_approval_cancel_v2`、`sandbox_with_network_proxy_allows_explicit_loopback_access`。
第一项已被上述分组覆盖；后两项在定向复验中新进程 `--retries 0` 一次通过，
其中 loopback proxy 那项与 Plan 093 记录的既有瞬态同源。

## 定向复验

新进程、`--retries 0`，覆盖 fuzzy-file-search、zsh-fork、`sandbox_with_network_proxy`
与 4 项 exec：**22/22 通过**。

## 中途的基础设施阻断

约 22:05 起本机到 GitHub 的 HTTPS 经代理与直连全断
（`SSL_ERROR_SYSCALL`、`SSL: UNEXPECTED_EOF_WHILE_READING`）。
`scripts/with_codex_v8_artifacts.py` 每次调用都会无条件重下 `.sha256`，缓存里的 archive/binding 虽然完好且校验通过，
只差这个小文件也无法启动官方入口，任务因此中断并如实汇报，没有为了跑通去跳过校验下载。
用户处理网络后直连恢复，最终轮据此完成。

诊断阶段的隔离复跑改用受跟踪的 `just test` 入口（同一共享锁与 watchdog），
把已被 wrapper 验证过的 V8 工件按缓存内 `.sha256` 本地重校验后 pin 给构建，因此诊断不依赖网络；
官方门禁仍走真实 wrapper 与实时下载（最终轮 `ambient_overrides_replaced=false`，确认没有沿用诊断期的 pin）。

**磁盘代价（执行者失误）**：定向复验时误用了非 conservative 入口，缺少 `CARGO_INCREMENTAL=0`，
target 从 190 GB 涨到 260 GB，其中 `debug/incremental/` 20 GB 为本任务新增、conservative 入口根本不使用。
用户单独授权后只删除该目录，项目由 336.4 GB 降到 316.2 GB。
需要更正的是：当时预判"切回 `CARGO_INCREMENTAL=0` 会导致 workspace 成员全量重建"过于悲观——
最终轮实际只重编了 3 个 crate（`codex-code-mode-runtime`、`codex-code-mode-host`、`codex-v8-poc`），
构建产物基本复用，整轮不到 11 分钟。

## 最终全量

clean HEAD `39d5841f`（相对实现冻结点 `2199316c` 只多 Plan/日志提交），
`just --justfile multidev/justfile test-with-codex-v8-conservative --locked`，
V8 实时取回、`cache_status=hit`、digest 与初始轮一致：

```
14713 tests run: 14713 passed (4 slow), 24 skipped
```

零 failure、零 error、零 timeout、零 retry/flaky；watchdog `stop_reason=none`、`cleanup_reason=none`。
JUnit SHA-256 `97fb4a43daf397c46d45b7f3ff3b82f7accb0604a614926d0e3f4c66ebb3c2fc`，
其中 `tests="14714"` 比 nextest 多 1，是把 `@setup-script:publication-critic-service-unix` 也计为一项。
24 项 skipped 与 Plan 093 基线一致。

资源终态：项目 316.7 GB（峰值 320.3 GB，warn 350）、Multi target 257.9 GB、
Windows `C:` 可用 118.2 GB、内存峰值 8.3 GB、PSI 0。

## 证据

`test-data/_retained-test-evidence/plan105-multi-final-full-workspace/`：
`final/` 存最终轮 `junit-local.xml`、`summary.env` 与生效的 `nextest.toml`；
`run1-diagnostic/` 存初始诊断轮的 `junit-local.xml`（SHA-256
`3628c33baa26b73941c1053de4b77fb4691412c28fad11209046d4ee2317659f`）与 `summary.env`；
`neutral-env.sh` 记录中性环境定义。
逐轮 console 日志与运行脚本留在 107 工作树的 `.codex/build-watchdog/plan105-console/`。
