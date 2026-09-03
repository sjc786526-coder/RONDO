# Plan 108 Local 最终全 workspace 独立验收

审查对象：`worktree-113-plan108-local-full-workspace@9aba9439602a00157dd1877196140fac63eec3c7`；
正式测试候选：`fbe3484f0b69360bc957a00d71ad23053b9fbaf6`；基线：
`main@a3288f2d4e84f894902845343e86be12974594bd`。

## 结论

`ACCEPT`。三项修复与实际故障匹配，没有改变 Local 产品行为、默认值、断言、通用 timeout、retry 或 skip；最终完整
workspace 在包含全部实质修改的 clean candidate 上全绿，没有未关闭 correctness finding。

工作树阶段判定为 **验收通过 / 任务目标完成**，候选实质代码与测试口径自 `fbe3484f` 起冻结。Plan 108 整体仍停在用户
指定的 Git 停止点：尚未合入、推送或完成 exact main 的 Local 轻量 CI，因此状态为
`FINAL_REVIEW_ACCEPTED / WORKTREE_GOAL_COMPLETED / LOCAL_CANDIDATE_FUNCTIONALLY_FROZEN /
MAIN_INTEGRATION_PENDING / NOT_PUSHED`。本轮未运行完整 workspace 或其它重型测试，也未运行 Docker、真实 API/模型、
训练、发布或删除操作。

## 正确性与回归审查

- `869bdde7` 只修两个测试 fixture。loopback HTTP fixture 先在 2 秒读取预算和 64 KiB 上限内消费 bodyless GET 的完整
  request head，再 flush 204 并 half-close 写端，直接消除带未读接收数据关闭 socket 时的 RST 竞争；没有放宽产品网络
  策略。定向 3/3 与最终完整轮中的 allow/block 两项均一次通过。
- sticky environment 用例只给它自己创建的 `ws://127.0.0.1:1` 不可达环境设置 50ms connect budget。该字段位于私有
  `environments.toml` fixture，产品默认 10 秒连接预算和外层读预算均未改变；同仓库已有同值测试先例。定向用例 1.205s、
  最终轮 1.651s 一次通过，仍验证原本的环境选择优先级。
- `fbe3484f` 只在 Local profile 中把精确的四项 `turn_start_shell_zsh_fork_` 测试路由到既有
  `app_server_integration`（max-threads=1）。第二次完整轮中四项并发时两次尝试均失败；新进程 `--retries 0` 定向轮
  4/4 通过，18.326s 总耗时与四项耗时之和相符，证明规则实际串行生效。最终完整轮四项均一次通过；没有改测试正文、
  初始化期限或全局并发。
- `a3288f2d..fbe3484f` 的实质差异仅为上述 52 行 Local 测试/调度改动，加规划期文档；`fbe3484f..9aba9439` 只有
  Plan、WBS 和实施日志。`multidev/`、根 CI/共享 runner、依赖与 lockfile 均无变化，最终测试证据与当前实质代码一致。
- 格式执行与 `git diff --check` 证据成立；独立复核完整差异也无 whitespace error，未发现 `.snap.new`、lockfile 漂移、
  未提交 tracked 内容或意外产品改动。

## 最终门禁与证据复核

- 保留的 final console 明确记录 clean `fbe3484f`、空 status、正式命令、无代理变量和无 `FORCE_COLOR`；入口解析为
  `CARGO_BUILD_JOBS=1`、`CARGO_INCREMENTAL=0`、`NEXTEST_PROFILE=local`，使用 checksum-verified V8、共享锁、watchdog
  和唯一 `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-local`。
- Nextest 实际运行 `14122/14122` passed、4 slow、23 skipped；最终 console 无 TRY/FLAKY/FAIL/ERROR/TIMEOUT，
  0 setup。skip 未计入 passed。JUnit 逐项复算为 14122 testcase、0 failure、0 error，未见 flaky/rerun 元素；SHA-256
  为 `ea17296f008abba2c0e56de32950301e089831f2b6494a214d34a487042d6ace`。
- retained final 的 JUnit、summary、metrics 和生效 Nextest 配置与 wrapper 原件逐字节一致。summary 为
  `run_rc=0 / final_rc=0 / stop_reason=none / junit_status=retained`；最终 console SHA-256 为
  `5a9067d84d84941126801de937909771fef44038dc6009e6579a97f8851e6e9a`。
- 资源均在门内：项目峰值 151,650,816,000 B，Local target 峰值 102,980,476,928 B，Windows `C:` 最低可用
  120,187,826,176 B，内存峰值 2,940,092,416 B，swap 与两级 PSI 峰值为 0。审查时主物理仓库只有
  `rondo-local` target，未出现 `rondo-multi` target。
- 主物理 retained 目录约 15 MB，包含两轮诊断、两组定向复验和最终轮的原始 JUnit/summary/metrics/Nextest/console；
  无需依赖 113 worktree 永久存在，也无需增加新的采集或可信设施。

## 代用户作出的决定

1. **接受最终轮的 residual cleanup，不要求重跑或修改 watchdog。** 首次完整轮在任何修复前也记录了同一 cleanup，排除
   本轮三项改动引入的回归；最终测试命令和 JUnit 均成功，watchdog 只在 runner 退出并等待 5 秒后清理本轮 cgroup，保留
   原始返回码，随后已确认无 Cargo/Nextest/rustc/LLD/app-server 残留。这是既有安全兜底的正常生效，不是测试失败。
2. **接受并保留 113 下三层空 `mydev/codex-rs/target/nextest/local/` 目录，不为它申请删除或阻断验收。** 独立复核只有
   三个目录、零文件、零构建产物；实际 Cargo 产物全部位于唯一共享 `rondo-local` target。它不是第二套 target，随未来经
   授权释放 113 worktree 自然消失，当前主动删除没有正确性收益。
3. **不重跑完整 workspace。** 最终轮已在 exact candidate 上直接覆盖全部改动且零 retry；审查没有改产品、测试、fixture、
   Cargo/Nextest 或正式入口。再跑同一重型门禁不会增加相称的正确性信息。
4. **补齐两处权威文档状态，但不把集成写成已完成。** WBS 的第二处旧指针改为“独立验收通过、等待用户批准 main 集成”；
   README 用 Plan 105 与 Plan 108 的最新已验收数字替换旧的 Multi-only 基线说明。两处都是结果记录，不使最终 Rust 门禁失效。
5. **下一步仍须用户明确批准合并和推送。** 获批后完成 exact main 的 Local 轻量 CI，再更新 WBS-COMPLETED 和最终状态；
   CI 通过前不记录 `INTEGRATED/PUSHED/CI_PASS`，也不提前启动 Local 发布、tag 或 target 清理。

## 验收状态

`ACCEPT / FINAL_REVIEW_ACCEPTED / WORKTREE_GOAL_COMPLETED / LOCAL_CANDIDATE_FUNCTIONALLY_FROZEN /
MAIN_INTEGRATION_PENDING / NOT_PUSHED`
