# Plan 022 独立验收修复

时间：2026-08-14（America/Los_Angeles）

基线：`d2c16073beb94b45f2bacceb8b0fbae41ad65204`

依据：`agent_log/2026-08-13-232200-plan022-independent-acceptance-review.md`（原报告未改写）

## 修改

- **B1**：binary freeze 对新 Local/Multi manifest 显式写合法 `product`，对 Codex 及历史形状省略该键；三类
  reader 与 Terminal-Bench 生产 loader 严格接受旧键集或旧键集加合法产品，显式 `null`、未知值和多余键均拒绝。
- **B2**：v7 campaign 的 RONDO request 显式继承锁定产品，Codex 保持无产品；manifest、RunSpec、preflight、
  publication、tracked record/replay 与 aggregate 逐层绑定 campaign、bundle 和 product。durable consumer 还用
  生产 loader 复核 binary sha、source commit 和 workspace normalization。successor generator 不再把 Multi
  声明绑定到继承的历史 Local bundles。
- **B3 / C4**：no-API 入口按选择的产品校验真实 namespace、生产 manifest 及三份 runtime 文件摘要，并把双侧
  manifest 摘要写入 receipt；删除伪造 counterpart RunSpec 的公平性校验。Codex safe summary 同 paid/result
  形状省略 product 与 auto-review 块。
- **M1**：generic tracked index、journal、TB publication、campaign continuation/recovery/aggregate 与 pair reconcile/
  assessment 共用严格产品合同；新产品行的顶层/config/binary/campaign/版本化 auto-review 必须一致，历史无产品
  行继续只读兼容。Local 实际 Guardian 覆盖与 Multi 全关闭都由生产 adapter 回归覆盖。
- 同步 Plan 022 任务状态、当前 WBS 与方向 WBS；修正旧日志中 manifest/build-command 混淆。独立验收报告保持
  原文，不覆盖。

## 验证

- 受影响 focused：312/312，`OK`。
- 完整 pure/fake/loopback 无 API eval：600/600，`OK`，0 fail、0 skip；使用根 `eval-test` 等价的
  `uv run --frozen --no-sync`，复用主仓库 ignored `eval/.venv`。
- `just eval-lock`：85 packages，pass。
- Local watchdog helper：9/9；Multi watchdog helper：9/9。
- 本轮未修改 Rust 产品源码，未重复 Cargo 构建；未运行 Docker、真实 API、真实模型、付费测评或真实 no-API
  双侧执行。helper 最初一次把脚本路径误作 unittest 模块而未完成 discovery，改用脚本入口后的上述结果为最终门禁。

## Diff 与现场

- 本轮工作树 `git diff --check` 通过；从 Plan 基线 `6611683` 排除 `multidev/**` 的手写差异也通过。
- 完整 Plan diff 仍为预期窄例外：`rc=2`，419 个 `multidev/` 文件、6,479 个诊断位置、12,707 行输出；
  `mydev/` 与 `multidev/` 各 6,011 个 tracked 条目，规范化 path 后 blob/mode 映射精确相同。该例外仍待用户确认，
  未为消除上游尾空格改写复制内容。
- 保留既有 ignored 现场：约 20G `multidev/codex-rs/target`、两份 build metrics、32K eval uv cache、五处
  `__pycache__`。未清理 Multi target 或来源不明缓存；未生成正式 identity、run、结果行或预算账本。
