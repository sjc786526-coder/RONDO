# Plan 108：Local 最终全 workspace 执行记录

113 分支实现候选冻结于 `fbe3484f0b69360bc957a00d71ad23053b9fbaf6`。正式入口最终在该 clean commit 上取得
`14122 tests run: 14122 passed (4 slow), 23 skipped`，零 failure/error/timeout/retry/flaky；执行阶段已完成，等待独立验收，
尚未合并或推送。

## 诊断与修复

首次完整轮在 clean `e7939823` 上全部实际测试通过，但有 2 项 retry/flaky，不能作为最终轮：

- loopback allowlist fixture 首次由代理返回 502。目标 server 在未消费请求时关闭 socket 会发 RST，代理可能在读取已写出的
  204 时把它判为 upstream failure。修复为有界读取完整 HTTP request head，随后写出并 flush 204，再有序 half-close。
- sticky environment 选择测试先等待预期不可达的远端环境，默认 10s connect timeout 与外层等待预算相撞。该用例验证选择
  优先级而非产品连接默认值，因此只在私有 fixture 中配置 50ms connect timeout，没有扩大通用 timeout。

两项修复提交为 `869bdde7`；经 conservative 入口新进程、`--retries 0` 定向复验 3/3 通过。

`869bdde7` 上的下一完整轮为 `14118 passed / 4 failed / 23 skipped`。四项
`turn_start_shell_zsh_fork_` 在 Local 现有四线程 app-server 组中同波启动，首次与 retry 均因初始化期限/零请求而失败；隔离后
串行运行稳定。修复只把该过滤器路由到既有 `app_server_integration`（max-threads=1），不改 timeout、retry、断言或 skip。
新进程 `--retries 0` 定向复验 4/4 通过（18.326s），提交为 `fbe3484f`。

`UV_CACHE_DIR=/tmp/plan108-uv-cache just --justfile mydev/justfile fmt` 与 `git diff --check` 通过。临时 UV cache 选择只为绕过
当前 side sandbox 对默认用户 cache 的只读限制，不属于产品或正式测试口径。

## 最终完整门禁

命令：

```text
just --justfile mydev/justfile test-with-codex-v8-conservative --locked
```

最终 console 记录 clean HEAD、空 tracked status、无代理变量与无 `FORCE_COLOR`；入口解析为
`CARGO_BUILD_JOBS=1`、`CARGO_INCREMENTAL=0`、`NEXTEST_PROFILE=local`，并使用共享锁、watchdog 与唯一
`/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-local`。V8 cache hit，archive SHA-256 为
`a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583`，binding SHA-256 为
`7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506`。

Nextest 为 14122/14122 passed、4 slow、23 skipped；console 无 TRY/FLAKY/FAIL/ERROR/TIMEOUT 标记。JUnit 根为
14122 tests、0 failures、0 errors，SHA-256 为
`ea17296f008abba2c0e56de32950301e089831f2b6494a214d34a487042d6ace`。wrapper 为
`run_rc=0 / final_rc=0 / stop_reason=none`。

项目峰值 151,650,816,000 B，Local target 峰值 102,980,476,928 B，Windows `C:` 最低可用 120,187,826,176 B；
内存峰值 2,940,092,416 B，swap、cgroup PSI 与 host PSI 峰值均为 0。命令成功后仍有非 Cargo 后代超过 5s grace，watchdog
按设计限于本轮 cgroup 清理并记录 `cleanup_reason=residual_processes_after_command`；收尾复核无 Cargo、Nextest、rustc、LLD
或 app-server 残留。该资源事实不隐去，留给独立验收判断。

## 证据与边界

主物理工作区的 git-ignored 保留目录
`test-data/_retained-test-evidence/plan108-local-final-full-workspace/` 含首次诊断、两组定向复验、第二次诊断与最终轮的原始
JUnit、summary、metrics、Nextest 配置和 console，并保留中性环境与正式运行脚本。最终 console SHA-256 为
`5a9067d84d84941126801de937909771fef44038dc6009e6579a97f8851e6e9a`；副本与 wrapper 原件一致。

正式运行还直接复用了主物理工作区 git-ignored 的唯一 Local target。Nextest 在 113 worktree 下创建了
`mydev/codex-rs/target/nextest/local/` 三层空目录（无文件、无构建产物，不是第二套 Cargo target）；任务没有删除授权，故保留并
单独报告。未发现 `.snap.new`、tracked lockfile 漂移或 Multi 变更，也未运行 Docker、真实 API/模型、训练、发布、tag、合并、
推送或任何删除操作。
