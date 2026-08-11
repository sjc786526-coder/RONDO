# Plan 014 Pair Identity 与 Profile Drift 离线闭环

## 实质修改

- 新增 `p1-terminal-bench-pair-v2.json`：唯一冻结 v9 pair、b4 batch、两侧 run ID、Sol/medium main、
  Sol/low Guardian、官方价卡、未计费 retry、单侧 5 USD/pair 10 USD、单 Guardian 上限及 frozen Codex
  catalog source/SHA。tracked lock 不含 raw endpoint、display name 或 key env。
- 默认 paid 入口只加载 schema v2；v8 仅保留显式 legacy 只读加载，不能新建、claim 或继续 paid ledger。
- sequence ledger 升为 schema v5：slot 1 claim 首次绑定 selected profile/endpoint SHA，后续 stage、finish、
  crash recovery 和 slot 2 claim 均重验；正式 CLI 还会在 completed 发布前与 durable publication 收口前从
  `rondo.local.toml` 重新投影。
- public success/failure 统一保存 lock 的 selected redacted profile，包括 requested/effective model、价卡、retry、
  catalog 与 logical-request 上限；M1 精确比较两侧 public result、pair lock 和 sequence ledger。
- 正式 frozen Codex 路径会核对运行时生成的最小 catalog SHA/source/model 与 lock，proxy 的 Guardian logical
  request 上限也由 lock 投影。

## 离线验收

- focused：Terminal-Bench pair/result/runner 63/63 通过。
- `just eval-lock`：85 packages。
- `just eval-test`：325/325 通过。
- 当前 ignored local profile 与新 lock 的 public projection 精确相等；source-bound Sol/Sol catalog SHA 精确相等。
- 新 pair/batch/run IDs 在现有 `eval-data`、tracked results 与 `test-data` 中无历史占用。
- `git diff --check` 与 Python compileall 通过。

## 未运行边界

- 未调用真实 API，未运行 Docker、Cargo、paid pair 或 M1。
- v9 identity 目前只是未消费的 tracked reservation；fresh exact-wire canary 未通过前不得创建 pair ledger 或
  claim slot 1。profile 变化时必须新建 lock/IDs，不能改写 v9。
