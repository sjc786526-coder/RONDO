# Plan 096：首次验收返修复验

日期：2026-08-27 ｜ 对象：`worktree-096-validation-cloud-scorer-qualification@08a4adb` ｜
首次报告：`agent_log/2026-08-27-134602-plan096-first-independent-review.md`

## 1. 结论

**首次独立验收通过，0 High / 0 Medium / 0 Low correctness finding。**

首次报告的唯一 Medium 已按既有 archive 职责窄修：已有根级 formal authority 时，runner 会在 validation release 处理、namespace 创建和
evaluator 调用之前 typed fail-closed，不再可能因误用不同 `run_id` 重复外发 55 份 validation packet 或产生费用。现有正式结果、冻结合同、
tracked projection、费用和研究终态均未改变。

接受 `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH` 为 Plan 096 唯一冻结研究终态，Plan 097 不解锁。执行者现在可以按 decision 013 完成
`doc/WBS-COMPLETED.md`、WBS 最终状态与最终实施日志收口；完成后提交全部变动并请求最终复验。未经用户批准仍不得合并、推送、归档或删除
worktree。

## 2. Finding 闭合

- `CloudQualityArchive.require_formal_unclaimed()` 复用现有 `load_authority()` 的结构、symlink、schema、run identity 与 SHA 校验；有效
  authority 返回既有 typed `formal_result_already_authoritative`，不安全或无效 authority 继续 fail-closed。
- `run_formal()` 在构造 archive 后立即执行 preflight，随后才校验 release、创建 write-once namespace 和评分；时序满足首次报告要求。
- 末尾 `claim_formal_result()` 的 `O_EXCL` 原子写入和冲突复核保持不变，未增加通用锁、状态机、审计或可信设施。
- 新回归先形成第一份 authority，再以不同 formal `run_id` 调用 runner；断言第二 evaluator 调用数为 0、authority bytes 不变、第二 namespace
  不存在且不是 symlink。该测试直接覆盖 finding 的外发与归档副作用。

## 3. 独立验证与边界

- `git diff --check 63d22f5..08a4adb`：通过。
- Plan 073/079/096 相关 Python unittest：`95/95 passed`。
- `eval/locks/`、`eval/results/`、`multidev/` 与 `doc/WBS-COMPLETED.md` 相对首次报告提交均零差异；因此接受首次审查已通过的 Rust
  `62/62`，本轮不重复重型构建。
- 096 worktree clean，且 worktree 内不存在第二个 `multidev/codex-rs/target`；main、093、095 worktree 也无 tracked 修改。
- 未运行真实 API、commissioning、Rust 重型门禁或全 workspace；未读取 `.env.local`、unseen、密钥或 provider body；未产生外部费用。

## 4. 剩余收口

本轮通过的是首次独立验收及 finding 返修。任务仍需按 ExecPlan decision 013 完成受跟踪的完成历史、WBS 最终状态和最终日志，并提交后请求
最终复验；该机械收口不得改变 formal archive、tracked result、终态或 Plan 097 锁定状态。
