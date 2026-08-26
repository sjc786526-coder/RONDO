# Plan 080 独立验收整改执行记录

时间：2026-08-25 ｜ 分支：`worktree-080-m4-c2-session-control-tui` ｜ 被整改提交：`aadddf4`

## 修改

- 为每次 live Root writer authority 增加稳定的 owner incarnation，并把 committed online proof 绑定该 incarnation。Team mutation
  gate 与 M4-S2 close barrier 均复验 exact owner、Team instance/revision/commit generation；先赢的 Team commit 使 Close、active
  Archive/Delete fail closed，保留 replacement owner 和新事实。
- formal shutdown 使用 exact submission-id handoff 消费既有 close permits，不新增 registry/relay。parented child 在正式 control 入口拒绝；
  Delete partial 只在 canonical Root marker 仍存时经权威 query 产生专用 retry-anchor proof，由用户显式重试，结果未知 mutation 不自动重放。
- client 增加 query-bound control preview；TUI 只对权威 available target 展示确认，并明确 Session、canonical Root、subtree/目标状态。
  control-only 关闭只退休 control preview，不 detach 仍启用的 query attachment。

## 验证与资源

- 整改直接轮 29 项首跑为 27 pass、2 fail；失败分别是发布后 Root 已为 `Tracking` 的测试夹具仍期望 `Pending`，以及确认框信息增强后的
  snapshot 差异。按真实语义修正后余下 2/2 通过；审查点名但首筛未命中的 default-off、query-only/control-off 与 removal token
  另行 3/3 通过。既有 45/45、17/17、47/47 与 fresh 证据按审查结论只在原覆盖范围沿用，没有重复跑宽门禁。
- stable schema watchdog `20260825-163723-1000-1316586`、experimental schema `20260825-163904-1000-1321370` 均 1/1；scoped fix
  `20260825-164441-1000-1338347` 与七 crate clippy `20260825-164924-1000-1350199` 通过；`fmt`、`fmt-check`、`git diff --check`
  通过，无 `*.snap.new`。
- 2/2 直接复验 watchdog `20260825-162847-1000-1284482`；3/3 邻接复验 watchdog
  `20260825-165714-1000-1369350`。所有正式 test 使用 `--retries 0`，watchdog 均 `stop=none / cleanup=none`。
- 整改收口前的独立只读复核另发现一项 Medium：persistence/runtime teardown 后若 Team close completion 失败，旧路径仍保留
  submission loop 与 owner mapping。修复后该不可回滚分支关闭 lifecycle、终止 loop，并让 app-server 只清 exact owner、保留
  replacement，同时仍返回 typed Unknown。新增故障注入 1/1（watchdog `20260825-173155-1000-1427468`）与 app-server 邻接 1/1
  （`20260825-173353-1000-1431720`）通过；前两次编译只暴露并修正模块导入和测试夹具接缝，未进入运行期。
- 最终 core/app-server scoped fix（watchdog `20260825-173544-1000-1438467`）与 clippy
  （`20260825-173946-1000-1449319`）通过，均 `stop=none / cleanup=none`。
- 未参与修复的同一只读复核者最终确认该 Medium 的 terminal completion、loop termination、exact-owner removal、replacement 保留、
  typed Unknown/no-replay 与故障注入链闭合；限定范围内无剩余 high/medium/low correctness finding。该结论是提交前内部复核，正式
  验收仍交由用户指定的跨会话审查者判定。
- 270GB 告警后停止扩大测试范围。再次确认无 Cargo/Docker/本地模型重型 owner、realpath/归属/非符号链接无误后，仅清空已授权的 069
  `debug/incremental`；项目/target 从 `276,932,814,938 / 203,243,122,156 B` 降至
  `196,336,300,056 / 122,646,607,274 B`，保留 `debug/deps`。最终项目/target/incremental/deps 为
  `232,965,910,785 / 159,275,684,252 / 30,800,000,843 / 127,745,879,278 B`，Windows `C:` 可用
  `75,184,451,584 B`。
- 未运行 full-workspace、Docker、真实 API/模型、训练、测评、benchmark、CI/PR 或远端操作；未读取或修改 079 现场。

## 当前结论

审查报告的 2 High、5 Medium、Plan 状态 Low 与收口复核追加的 1 Medium 均已形成对应代码、测试或文档整改，执行者侧无已知未关闭
high/medium finding。
`M4_C2_CONTROL_PASS` 作为候选结论等待整改提交后的独立复验，不提前把执行者自审写成验收接受。
