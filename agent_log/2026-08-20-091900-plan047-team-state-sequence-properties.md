# Plan 047 Team State 序列性质测试

## 实质修改

- 在 `codex-team-state` 内新增默认 ignored 的有限序列性质测试，按冻结权重生成 11 类操作，并用 32 步固定核心保证
  publish、双生命周期、route、delivery、retry、wake 默认批次实际覆盖。
- 薄 reference 独立预测 canonical ID ordinal、revision、对象归属、三方权限/active/route 视图、delivery/duty 与 wake；
  每个有意义步骤后通过公开 API 对比产品状态。无有效引用时纯跳过并断言无产品调用、无状态变化。
- 新增 canonical 绑定错误与重复 active assignment 两项 invariant checker 自测，以及相同 seed 产生相同符号候选的自测。
- 增加 `just team-state-sequence-properties [seed]`；直接使用既有锁中的 `proptest 1.9.0`，只启用 `std`。Cargo lock
  仅增加 Team State 到 proptest 的直接依赖边，Bazel 模块锁核验后无差异。
- 未修改 Team State 产品实现；性质测试未发现现行合同内的产品缺陷。

## 验证

- `UV_CACHE_DIR=/tmp/rondo-plan047-uv-cache just fmt`：通过；首次未指定临时 cache 时因宿主 uv cache 只读失败，改为
  任务临时 cache 后下载锁定格式依赖并成功。最终 `just fmt-check` 与 `git diff --check` 均通过。
- `just clippy -p codex-team-state -- -D warnings`：首次发现测试代码的 `manual_is_multiple_of`，窄修后两次复跑通过；
  最终 watchdog `20260820-091814-1000-9645`，status 0。
- `just test -p codex-team-state --lib --status-level skip --final-status-level skip`：最终 `128 passed, 1 skipped`；
  `sequence_properties_tests::team_state_sequence_properties` 明确显示为 `SKIP`，watchdog
  `20260820-091823-1000-10064`，status 0。
- `just team-state-sequence-properties`：迭代与最终复跑均通过；最终唯一目标测试 `1 passed`，默认 seed
  `20260820047`、64 cases、每 case 最多 32 步，watchdog `20260820-091839-1000-11232`，status 0。
- `just team-state-sequence-properties 424242`：两次复现运行均通过；最终唯一目标测试 `1 passed`，watchdog
  `20260820-091853-1000-11771`，status 0。
- 临时 Bazelisk 1.29.0 SHA-256 校验为官方发布值，启动冻结 Bazel 9.0.0；`just bazel-lock-update` 通过且
  `MODULE.bazel.lock` 无差异，`just bazel-lock-check` status 0。输出保留仓库既有 `platforms` / `rules_cc` 版本解析警告，
  未造成锁错误。

## 提交后独立审查

- 干净上下文子智能体审查实现提交 `b0a8db079a642a5ea965b2ff789c5460359c5eff`，只关注正确性和功能性；未提出
  finding，并明确“验收通过”。
- 审查者独立复跑默认 crate 测试（`128 passed, 1 skipped`）、默认 seed 与显式 seed `424242` 主动入口（各
  `1 passed`）及定向 Clippy；另以非法 seed 验证参数确实传入并在解析处按预期失败，没有静默回退默认值。
- 审查者环境 PATH 中没有 Bazel/Bazelisk，因此未再复跑 Bazel lock check；其静态确认最小 Cargo 依赖边和
  `MODULE.bazel.lock` 无差异。执行阶段已用任务临时 Bazelisk/Bazel 9.0.0 完成实际锁更新与一致性检查。

未运行 Windows recipe、workspace 全量测试、Docker、API、模型或性能测评；它们均不在本任务范围内。
