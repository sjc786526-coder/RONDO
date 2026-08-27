# Plan 096：首次验收返修

日期：2026-08-27 ｜ 基线：`63d22f5` ｜ finding：0 High / 1 Medium

首次独立验收报告：`agent_log/2026-08-27-134602-plan096-first-independent-review.md`。

## 问题确认

finding 存在。`run_formal()` 原先先创建新 formal namespace、调用 evaluator 完成评分并写入 scores/result，最后才由
`claim_formal_result()` 检查根级 `formal-authority.json`。因此 authority 已存在时，误用不同 `run_id` 会重复外发 55 条并产生费用，最后才
以 `formal_result_already_authoritative` 拒绝；既有 authority 虽不会被改写，但 fail-closed 时序不正确。

## 修复

- `CloudQualityArchive.require_formal_unclaimed()` 负责校验根级 authority；已有有效 authority 时返回既有 typed
  `formal_result_already_authoritative`，authority 不安全或无效仍沿用既有 typed 错误。
- `run_formal()` 在 validation release 处理、namespace 创建和 evaluator 调用前执行该 preflight。末尾 atomic
  `claim_formal_result()` 保留，继续作为无通用锁前提下的并发 claim 兜底。
- 回归测试先用第一 `run_id` 形成完整 authority，再用不同 `run_id` 调用 runner，断言 evaluator 0 次、authority bytes 不变且第二
  namespace 既不存在也不是 symlink。

该路线与 Plan 079 archive 的 `require_formal_unclaimed()` 职责一致，比在 runner 复制 authority 解析更契合现有架构；没有扩建通用锁、审计、
可信设施或状态机。

## 验证与边界

- 新增定向回归：1/1 passed。
- Plan 073/079/096 相关 Python unittest：95/95 passed。
- `git diff --check`：通过。
- Rust、tracked result、formal archive、freeze、费用与研究终态均未修改，因此未重跑 Rust 重型门禁、commissioning 或真实 API。
- 首次审查的 Rust Nextest 复跑在 worktree 留下 12 KiB 空 `multidev/codex-rs/target/nextest/local`；确认无 build artifact 后已精确
  `rmdir`，交付审计中不存在第二套 target。
- `doc/WBS-COMPLETED.md` 与最终完成状态仍未写入，等待指定审查者复验接受。
