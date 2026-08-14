# Plan 022 第二轮独立复验修复

时间：2026-08-14（America/Los_Angeles）

基线：`c5eb380148ffbc0b838a24031d07ee31e99a79a6`

依据：`agent_log/2026-08-14-011251-plan022-fix-independent-reacceptance.md`（原报告保持不改）

## 修改

- v7 campaign publication context 显式携带 schema 身份，两侧都必须绑定冻结的 campaign product；RONDO 侧再与
  manifest/RunSpec/record 产品等值，Codex 侧继续不写 RONDO 产品字段。缺失整组绑定在 finalize 前拒绝。
- 正常与失败 publication 都写八键 `run-summary.json`，并用版本标记要求其 config/summary/tasks 等字段与 tracked
  row 相同；finalize、journal recovery 和 durable index reader 都重新核对，历史无标记行继续只读兼容。
- 终态 aggregate 不再因 private/tracked 两份自洽而提前成功；每次恢复都读取 state、budget、runs index 与 record
  digest，验证冻结 identity/selected profile 后重建并逐字节核对。缺 index、缺 run、错误 digest、未执行槽夹带预算
  和 Local/Multi 混绑均 fail-closed。
- replay 的 product/config/binary 合同与当前 shadow `local-static` / `local-ft-static` 仅 Local 映射已收紧；
  Terminal-Bench auto-review/campaign 字段不得混入。历史无产品行保持兼容。
- 同步 Plan 022 当前状态、权威 WBS 与数据布局；独立复验报告未覆盖。

## 验证

- 受影响 focused 八模块：319/319，`OK`。
- 完整 pure/fake/loopback 无 API eval：607/607，`OK`，0 fail、0 skip；使用 `uv run --frozen --no-sync` 复用
  主仓库 ignored `eval/.venv`，并清除代理变量。
- `just eval-lock`：85 packages，pass。
- Local watchdog helper：9/9；Multi watchdog helper：9/9。
- 首次单独运行 `test_terminal_bench_baseline.py` 时，既有 diagnosis evidence 测试一次报错；同一测试立即重跑通过，
  随后的 319 项 focused 与 607 项完整套件均通过。未以首次失败计作通过或删除测试。
- 未修改 Rust 产品源码，因此未重复 Cargo 构建；未运行 Docker、真实 no-API 双侧、真实 API、真实模型、付费测评
  或全 workspace Rust。

## Diff 与现场

- 本修复相对 `c5eb380` 和从 Plan 基线排除 `multidev/**` 的全部手写差异均通过 `git diff --check`。
- `mydev/` / `multidev/` 仍各 6,011 个 tracked 条目，规范化路径后的 blob/mode 映射完全相同，Multi 无额外未跟踪
  文件。完整 Plan diff 仍为既有窄例外：`rc=2`、12,707 行诊断，只来自与 `mydev/` 精确相同的复制内容；决策
  011 继续等待用户明确确认。
- 保留 ignored 现场：约 20G Multi target、两份既有 build metrics、32K uv cache 与现有 Python `__pycache__`；
  未清理、未写正式 identity/run/result/budget。

当前任务分支提交后停止，不合并、不推送、不清理 Multi target，等待再次独立复审。
