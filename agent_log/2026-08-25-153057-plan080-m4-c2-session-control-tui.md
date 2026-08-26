# Plan 080 / M4-C2 执行记录

时间：2026-08-25 ｜ 分支：`worktree-080-m4-c2-session-control-tui` ｜ 当时结论：`M4_C2_CONTROL_PASS` 候选，随后被独立验收拒绝

## 实质修改

- 新增独立默认关闭的稳定 app-server v2 `session/control`，由正式 `session/list` / `session/read` 投影 typed control proof 与
  availability。server 在每个请求执行前重读 canonical metadata/query projection 并精确比较 proof；online `SetRootState` 又在
  Team durable mutation 线性化点复验 instance/revision/commit generation，成功只来自既有权威领域边界。
- `Close` 复用 M4-S2 loaded Root owner removal barrier，effect 明确为 `OwnerClosed`；它不把 whole-Session lifecycle 虚构为
  `Closed`。cold archive/unarchive/delete 复用 ThreadStore 原生生命周期，不加载 Agent，不启动 turn、模型、工具或 API。
- protocol/client/TUI 贯通 Applied/Rejected/Partial/Unknown。client 使用 send-once attempt 与 accepted-read ticket；response loss、
  timeout、disconnect、lag、detach、attachment replacement 和 late completion 都会 stale/unknown，绝不自动重放 mutation。
  TUI 的确认、结果展示与自动 resync 只消费正式 query；query/control gate 独立默认关闭，C0 prototype 保持隔离。
- 更新 app-server README、stable/experimental app-server schema、config schema 和两份 TUI snapshot。没有建立新的 lifecycle registry、
  relay/queue/daemon manager、审计或可信体系。

## 调试中关闭的问题

- 阶段 A 唯一失败是 loopback 测试被宿主代理改写为 HTTP 502，发生在 mutation 前；改用明确 localhost `NO_PROXY`、全新临时
  Session/store 与 `--retries 0` 后通过，没有重放结果未知的 mutation。
- fresh 场景最初暴露“尚无 turn 的新 loaded Root 不一定出现在 persisted list”和任务私有 runtime 配置未落盘，fixture 改为先按
  当前 attachment 做 read，并写入任务私有 `config.toml`；重启后仍要求 persisted list 找回 Root。
- 正式轮实际执行 Close 后确认现有领域只能证明 owner barrier/removal，不能证明 whole-Session closed。协议 effect 因此收敛为
  `OwnerClosed`，后续 query 保持 lifecycle `Unknown` / residency `NotObserved`，没有为 UI 增建状态轴。

## 验收证据

- 首批未改产品代码的 query×lifecycle 合并树基线：`44/45` + 新状态定向复验 `1/1`，合计 `45/45`；watchdog
  `20260825-131057-1000-640839` / `20260825-132125-1000-700089`，均无资源 stop/cleanup。
- 最终正式控制聚焦轮：`17/17`，覆盖 protocol、client、公开 JSON-RPC、TUI confirmation/snapshot、fresh Session/store 及重启后
  rebuild/delete；watchdog `20260825-151443-1000-1076917`。
- 最终 query×lifecycle 邻接回归：`47/47`；watchdog `20260825-152004-1000-1100881`。所有正式 test 使用 `--retries 0`。
- stable schema `20260825-145358-1000-1004251`、experimental schema `20260825-145506-1000-1008778`、config schema
  `20260825-145538-1000-1010754` 均通过。scoped fix 通过；修正一处 TUI large-enum warning 后，scoped clippy
  `20260825-150732-1000-1056632` 零警告通过；`just fmt`、`just fmt-check`、`git diff --check` 通过，无 `*.snap.new`。
- 未参与主体实现的执行期只读自审当时未发现 high/medium finding；随后正式独立验收在 `aadddf4` 发现 2 High、5 Medium、1 Low，
  因而本日志最初的候选结论不构成验收接受。审查报告与整改结果分别见
  `agent_log/2026-08-25-154410-plan080-independent-review.md`、
  `agent_log/2026-08-25-170351-plan080-review-remediation.md`。

## 资源与未运行项

- 首次获批清理前项目/069 target/incremental/deps 为
  `262,408,773,632 / 187,705,122,816 / 97,147,797,504 / 91,746,553,856 B`；确认 realpath、非符号链接和归属后，仅移除
  069 `debug/incremental` 内容，清理后为 `168,019,832,832 / 93,316,182,016 / 102,400 / 91,746,553,856 B`。
- 最终只读实测项目/069 target/incremental/deps 为
  `249,859,561,911 / 176,171,908,350 / 69,723,108,087 / 106,486,267,376 B`；Windows `C:` 可用
  `77,131,886,592 B`。最后一批 watchdog 口径为项目/target `251,315,224,576 / 176,363,339,776 B`，所有门均
  `stop=none / cleanup=none`，未触及 270GB 告警线。
- 未运行 full-workspace、Docker、真实 API/模型、训练、测评、benchmark、CI/PR、发布、上传或远端操作；未读取或修改 079 review
  三期现场，也未清理 069 `debug/deps` 或来源不明资产。
