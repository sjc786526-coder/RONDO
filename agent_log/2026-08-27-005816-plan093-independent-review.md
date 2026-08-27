# Plan 093 独立验收报告

## 结论

`ACCEPT`。整改后 High/Medium/Low correctness finding 均为 0；Plan 093 技术目标完成，主线集成、推送、093 分支归档与 worktree
释放仍等待用户授权。本报告不提前记录 `INTEGRATED / PUSHED / MULTIDEV_FULL_WORKSPACE_BASELINE_PASS`。

审查以执行者 clean HEAD `ca6c172ef9fec037867928e3674d98abf3ef130e` 为起点。第一轮只发现一项验收阻断：正式全量虽以
`jobs=1 + LLD threads=1` 通过，仓库日常默认仍是 `jobs=6` 且没有持久 LLD 限制，也没有受跟踪的 jobs=1 备选。用户授权审查者直接
整改；提交 `028996efc53b48e4d95f8e4f6b87d84325343991` 将日常默认固化为 `jobs=2 + LLD threads=1`，rustc 机器级槽同步为 2，
并在 Multi/Local Justfile 增加 `test-with-codex-v8-conservative`，以受跟踪入口固定 `jobs=1` 并继承 LLD 单线程。没有建设第二套构建或
审计设施。

## 正确性与原任务保护

- Realtime 修复只约束每次 websocket handshake，Core 复用既有 provider timeout；延迟 session 初始化和 sideband per-attempt retry
  均有回归。该缺口在 Plan 070/089 已出现，整改没有缩短 session 生命周期、删除 realtime 功能或弱化 Error/Closed 断言。
- Publication Critic 的 Nextest setup 只为对应 process tests 构建并注入本轮精确 service binary，测试仍拒绝缺失、相对或非文件
  binary；Plan 057 的真实进程/正式 transport 目标未被 mock 或 stale-target fallback 替代。
- JSON packet 修复只消除 object key 遍历顺序假设，typed golden、逐值相等、反序列化与回序列化断言保留。client/review/resume
  fixture 改用 absolute TempDir 或明确 ephemeral history，符合 cwd fail-closed 目标，没有修改产品行为。
- 四项 zsh/app-server 测试只进入既有单线程组；测试体、10 秒期限、全局 test threads、retry 和 skip 均未改变。watchdog kill-status
  修复只校正 OOM 文案，资源停止条件和失败返回路径不变。
- tracked diff 未修改项目外文件、宿主机配置、代理、浏览器或全局工具链。`NO_PROXY`、`BROWSER=/bin/true`、C30 和并发设置只在
  获批命令或受跟踪仓库配置内生效；旧 target/worktree 删除和主物理 shared target/retained evidence 写入均在原授权范围。

## 证据复核

- 原正式全量仍绑定实现提交 `b25b5bb2e57490b8615a8c5c1c432c0fe39440db`。重算 JUnit SHA-256 为
  `ef2d16c4e1f4d1bfb411ddf7fe47127a0b7832cf7f35e649d1fe239e44f55e4b`；XML 为 14661 testcase（14660 tests + 1 Unix
  setup）、0 failure、0 error，console 为 14660/14660 passed、24 skipped、1 retry-pass。唯一 retry 的新进程 `retries=0` 复核为
  1/1 passed；Plan 091/092 四项保护均可在 JUnit 定位并通过。
- `b25b5bb..ca6c172` 只有 Plan/实施日志。并发整改只改 Cargo 配置、rustc throttle、Just 入口、轻量测试和文档；产品代码、测试逻辑、
  Cargo.lock、features、依赖图和 canonical target 路由均未改变。持久 conservative 入口的 `CARGO_BUILD_JOBS=1` 与原正式命令相同，
  持久 LLD flag 与原正式 `-C link-arg=-Wl,--threads=1` 字节等效；Cargo jobs 只改变调度，不改变产品语义。
- `python3 scripts/test_build_watchdog_contract.py` 为 7/7，通过默认 jobs/LLD/rustc slots、保守入口、主/linked target 映射、产品隔离、
  项目根外 target、资源计数不可用、门限顺序、summary 和 OOM 文案合同。两产品 Justfile 格式与入口枚举通过。
- 日常默认入口在正式锁/watchdog 下实际重新编译、链接并运行 `codex-utils-string`：18/18 passed，`rust-lld_count` 采样峰值为 1，
  `run_rc=0 / stop=none / cleanup=none`。保守 checksum-V8 入口同包 18/18 passed，console 明确解析为 `CARGO_BUILD_JOBS=1`，V8
  archive/binding identity 与正式全量一致，watchdog 同为零 stop/cleanup。
- 审查者曾在用户作出“无需重复全量”的决定前尝试启动一次保守全量；sandbox 无权读取 user D-Bus，wrapper 在 payload 前以 rc84
  fail-closed，没有启动 Cargo/Nextest。该空目录只有 console/status，确认无进程后已精确删除，不计验证结果。

## 审查决策

1. 接受用户关于不重复全 workspace 的决定。上一轮正式全量已经在等效 `jobs=1 + LLD1` 下通过；本次只持久化同一保守组合并把日常
   默认改为 `jobs=2 + LLD1`，重复运行 14660 项不会额外验证编译并发。现有正式 JUnit 继续作为功能基准。
2. 不清空共享 target。并发设置不改变 Cargo.lock、features、build script、依赖图或 target 路由；窄编译已证明持久 LLD flag 可用，
   保守入口已证明解析正确。保留 target 与原正式证据供后续任务复用。
3. Windows setup 仍只作静态复核，不声称原生 Windows 已通过；这不影响本任务明确的 Linux 全 workspace 口径。
4. 不触碰并行 owner 的 090/094、main 或任何宿主机配置；不合并、不推送、不归档或释放 093，等待用户下一步授权。

## 验收状态

`REVIEW_ACCEPTED / TECHNICAL_GOAL_COMPLETE / MAIN_INTEGRATION_PENDING / NOT_PUSHED`
