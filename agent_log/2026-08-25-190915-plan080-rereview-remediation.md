# Plan 080 整改复验问题修复记录

时间：2026-08-25 ｜ 分支：`worktree-080-m4-c2-session-control-tui` ｜ 被复验提交：`4b508916`

## 修改

- 复核 `agent_log/2026-08-25-175902-plan080-remediation-rereview.md` 后确认 3 Medium、1 Low 均存在。正式 query 的 active
  Archive/Delete 现按 Root residency 与 server admission 同步：loaded descendant/no Root 为 `OwnerUnavailableHere`/unavailable，
  未知 residency 保持 unknown；明确的 owner-incarnation-only mismatch 统一返回 `NotCurrentOwner`。
- exact shutdown submission 被 Session loop 接受后，completion sender loss、loop-first 与 terminal completion 都进入既有
  `ShutdownTerminatedWithError`；app-server 只用 `remove_thread_if_same` 清理 exact old owner，保留 same-ID replacement，继续返回
  typed Unknown，不自动重放。显式 `RetainedError` 仍保持可回滚、可重试。
- 增加 doc-hidden、默认未安装的 in-process after-preflight hook，只用于确定性测试 app-server 已完成 query preflight 后 Team commit
  先赢的竞态。Close 与 active Archive 均在 M4-S2 真正线性化点拒绝 stale，Root 与新 Team fact 保留；没有新增协议、registry、relay、
  持久状态或生产控制路径。
- 纠正上一轮日志：watchdog `20260825-173353-1000-1431720` 是普通 query 邻接，不是 exact-owner cleanup 直接证据。本轮新增 helper
  直接测试，并复验真实 ThreadManager exact-owner/replacement-safe 原语。

## 验证与资源

- 调试阶段按未打通接缝窄跑；无副作用的编译/fixture 失败修正后，冻结代码并以 fresh 临时 state DB/store 完成正式窄轮
  `13/13`（watchdog `20260825-190752-1000-1587834`）。覆盖 query residency 2 项、Close/active Archive race 2 项、replacement
  owner 1 项、accepted handoff 3 项、typed Unknown 1 项、app-server exact cleanup 3 项及真实 ThreadManager 1 项。
- core/app-server scoped fix（`20260825-185839-1000-1564505`）与 clippy（`20260825-190308-1000-1575968`）通过；`fmt`、
  `fmt-check`、`git diff --check` 通过。协议与 schema 未变化，按复验决定未重复运行 generator；既有 45/17/47、fresh、schema 与 snapshot
  证据只在原覆盖范围继续有效。
- 首次重型命令前确认无 Cargo/rustc、Docker 或本地模型 owner；069 target/incremental/deps 的 realpath、非符号链接与 `sjc:sjc` 归属
  无误。开始项目/target/incremental/deps 为 `234,203,975,680 / 159,247,073,280 / 30,845,054,976 / 127,470,071,808 B`，Windows
  `C:` 可用 `75,183,681,536 B`。正式窄轮结束时为 `250,079,399,936 / 175,121,977,344 / 38,634,786,816 /
  135,675,695,104 B`，Windows `C:` 可用 `75,179,724,800 B`；提交前只读复核为 `248,862,612,879 / 175,170,759,743 /
  38,577,035,217 / 135,984,905,103 B`，Windows `C:` 可用 `75,175,342,080 B`。未触及 270GB 告警线，watchdog 均
  `stop=none / cleanup=none`，本轮未再清理资产。
- 未运行 full-workspace、Docker、真实 API/模型、训练、测评、benchmark、CI/PR 或远端操作；未读取或修改 079 现场。

## 当前结论

复验点名的 3 Medium、1 Low 均已有对应实现和直接回归，执行者侧无已知未关闭 high/medium correctness finding。
`M4_C2_CONTROL_PASS` 仍只是等待独立复验接受的候选结论。
