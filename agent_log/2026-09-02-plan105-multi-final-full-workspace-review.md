# Plan 105 独立验收报告

## 结论

`ACCEPT`。无未关闭 High / Medium / Low correctness finding；Plan 105 的实现与最终全 workspace 目标完成，
RONDO Multi 实质代码与功能自实现提交 `2199316c` 起冻结。107 分支尚未合入或推送，后续 main 集成、CI、发布与
Multi target 删除继续等待用户分别授权，不提前记录 `INTEGRATED`、`PUSHED` 或发布完成。

本次只做差异、原始证据与 Git/ignored 现场复核，没有重跑全 workspace，也没有运行 Docker、真实 API/模型、
Local 测试、Bazel 或 benchmark。

## 正确性与范围复核

- 唯一实现变更位于 `multidev/codex-rs/.config/nextest.toml`：把 12 个
  `suite::fuzzy_file_search::` 测试与相邻 zsh-fork 测试一起路由到既有
  `app_server_integration`（`max-threads=1`）。没有产品代码、timeout、retry、断言、skip/ignore、依赖或 lockfile 改动。
- 初始证据显示 fuzzy 失败对象会漂移、同波启动耗时达 8--12 秒；隔离 12 项为 0.17--1.4 秒且全套 1.68 秒。
  最终 JUnit 的 12 项时间戳和耗时显示它们按该单线程组顺序执行，均在 0.33--1.09 秒通过，证明专用 override
  没有被后面的宽泛 local override 覆盖。复用既有测试组与当前故障性质匹配，不需要放宽 10 秒期限或新建机制。
- 4 项 `codex-exec` 初始失败的 raw 输出带 `FORCE_COLOR=3` 所要求的 ANSI 属性；产品尊重该变量是既有行为。
  清理交互 shell 的颜色强制与代理变量是 CI-like 本机测试环境归一化，不应通过修改产品或弱化纯文本断言解决。
  `doc/development-environment.md` 的两行说明属于当前维护职责，接受保留。
- 实现提交 `2199316c` 到最终测试 HEAD `39d5841f` 之间只新增 Plan/实施日志；最终测试之后的 `ec8f138f`
  也只更新 Plan/日志。最终结果因此与冻结实现、测试配置及依赖图对应。
- 主工作区 `main@d9dc3d51` 相对 107 基线只新增独立空间门日志，无产品或共享设施差异。执行者交审时 107 clean，
  main 未被执行任务改动；验收形成时尚未合并、推送、tag、发布或释放 worktree。

## 原始证据复算

- 最终 console 明确执行
  `just --justfile multidev/justfile test-with-codex-v8-conservative --locked`，解析为
  `CARGO_BUILD_JOBS=1`、`CARGO_INCREMENTAL=0`、`NEXTEST_PROFILE=local`、共享 build lock/watchdog 与唯一
  `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`；V8 `cache_status=hit`，archive/binding SHA 与初始轮一致，
  `ambient_overrides_replaced=false`。
- 最终 console 为 `14713 tests run: 14713 passed (4 slow), 24 skipped`，耗时 374.122 秒，零 retry/flaky。
  JUnit 根为 14714 testcase（14713 测试 + 1 个 Unix setup）、0 failure、0 error；逐元素复算同为
  14714 testcase、0 failure/error、0 flaky/rerun。setup 使用本轮共享 target 内的准确 Publication Critic service binary。
- 最终 JUnit SHA-256 复算为
  `97fb4a43daf397c46d45b7f3ff3b82f7accb0604a614926d0e3f4c66ebb3c2fc`，与 summary 和实施记录一致；
  retained 副本与 wrapper 原件逐字节相同。诊断轮 JUnit SHA-256
  `3628c33baa26b73941c1053de4b77fb4691412c28fad11209046d4ee2317659f`，可复算 6 个 final failure，
  与初始 console 的 14707 passed / 6 failed / 3 flaky 一致。
- 最终 summary 为 `run_rc=0 / final_rc=0 / stop_reason=none / cleanup_reason=none / junit_status=retained`。
  项目峰值 320,263,483,392 B、target 峰值 257,915,342,848 B、Windows `C:` 最低可用 117,680,525,312 B、
  内存峰值 8,268,972,032 B、swap 0、两级 PSI 峰值 0，均在现行门内。
- retained path 包含最终/诊断 JUnit 与 summary、最终生效 Nextest 配置和中性环境说明；现有 wrapper 证据足够，
  不需要新增 manifest schema、采集器或可信设施。未发现 `.snap.new` 或 tracked whitespace/lockfile 漂移。

## 审查决策

1. **接受现有并发修复，不要求重跑重型测试。** 最终完整 workspace 已直接覆盖修改后的配置并零 retry 通过；
   再跑同一轮不会增加正确性信息。
2. **接受中性环境口径。** `FORCE_COLOR` 与当前 shell 的无效 `127.*` no-proxy 写法属于执行环境，不是产品缺陷；
   不把产品行为改成忽略显式颜色请求，也不为本机条件改写四项上游风格断言。
3. **接受经用户单独授权的精确 incremental 清理。** 最终 conservative 轮只重建了 4 KiB 空占位目录，未恢复 20 GB
   增量缓存；不再清理共享 target，整个叶子仍留到 Multi 发布后由用户单独授权处置。
4. **关闭一项非阻断 bookkeeping finding。** 107 内曾存在未在完成汇报列出的
   `multidev/codex-rs/target/nextest/local/` 空目录，共 12 KiB、无文件、无构建产物，创建时间早于正式轮。
   它不参与最终命令、不是第二套 Cargo 缓存。审查时先因未获删除授权保留；用户随后明确要求顺手修复，审查者用
   `rmdir` 只移除已验证为空的 `local → nextest → target` 三层目录并复核路径不存在。该 ignored 清理不改任何
   tracked 内容、产品、测试或正式结果，无需重跑门禁。
5. **判定 Multi 功能冻结生效。** 后续只允许发布所需的 CHANGELOG、README 固定链接、WBS/完成记录等非实质修改；
   若 main 集成或审查后再发生 Multi 实质代码、测试或运行口径变化，必须按 WBS 重做受影响验证并重跑最终全量。

## 验收状态

`COMPLETED / FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED / MULTI_FUNCTIONALLY_FROZEN / MAIN_INTEGRATION_PENDING / NOT_PUSHED`
