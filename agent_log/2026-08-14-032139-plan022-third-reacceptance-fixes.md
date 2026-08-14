# Plan 022 第三次独立复验修复

时间：2026-08-14（America/Los_Angeles）

基线：`20b8e7874635b12e19a2c12ba4d3f9be1eb2d2de`

依据：`agent_log/2026-08-14-023312-plan022-third-independent-reacceptance.md`（原报告保持不改）

## 修改

- Terminal-Bench campaign 成功/失败 publisher 在 finalize 前必须接收真实冻结 `CampaignIdentity`，并把 context
  的 campaign/lock/schema/product/side/slot/run/profile/timeout 与该 identity 逐项绑定；RONDO 与 Codex 的错误冻结
  产品组合均在落盘前拒绝。
- campaign、continuation 与 result-record digest 的 durable reader 统一复用完整 run index 校验；版本化
  `run-summary.json` 缺失、篡改或整个私有目录缺失都会从 terminal aggregate 写入入口 fail-closed。
- JSON schema 与冻结 profile 比较改为类型严格，拒绝 `bool` 冒充整数或浮点数；修正数据布局文档笔误。
- 按用户决定采纳 Plan 决策 011：非 `multidev/**` 差异必须通过 `git diff --check`，复制目录只有在 tracked
  相对路径、Git type/mode/blob 与工作树字节逐项等同 `mydev/` 时豁免既有尾空格诊断。

## 验证

- 四个直接受影响模块：234/234，`OK`。
- 完整 pure/fake/loopback 无 API eval：610/610，`OK`，0 fail、0 skip；使用
  `uv run --frozen --no-sync` 复用主仓库 ignored `eval/.venv`，并清除代理变量。
- 当前 tracked `runs.jsonl` 244/244 通过同一完整 durable reader，历史无摘要 marker 行保持只读兼容。
- `just eval-lock`：85 packages，pass。
- Local / Multi watchdog helper：各 9/9；另运行 Local `test-github-scripts` 44/44。
- 未修改 Rust 产品源码，因此未重复 Cargo 构建；未运行 Docker、真实 no-API、真实 API、真实模型、付费测评
  或全 workspace Rust。

## Diff 与现场

- 从 Plan 基线排除 `multidev/**` 的差异通过 `git diff --check`。完整 Plan diff 保留已采纳窄例外：`rc=2`、
  12,707 行诊断、419 个路径，全部位于 `multidev/`。
- `mydev/` / `multidev/` 各 6,011 个 tracked 条目；规范化相对路径后的 Git mode/blob 清单无差异，
  两侧 tracked 工作树均相对索引无修改，mode 分布同为 5,951 个 `100644`、59 个 `100755`、1 个 symlink。
- 保留 ignored 现场：约 20G Multi target、既有 `eval-data/`、28K worktree uv cache 与 Python `__pycache__`；
  未清理、未写正式 identity/run/result/budget。

当前任务分支提交后停止，不合并、不推送、不清理 Multi target，等待再次独立复审。
