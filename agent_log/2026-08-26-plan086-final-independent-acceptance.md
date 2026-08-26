# Plan 086 / #39616 最终独立验收

## 结论

候选实现 `3dc31d5f39edaef7d8f4a440c364db98dc0f9039` 与审查整改
`fdbdaf8e2ba2c33fbe3162858b07bffe90be87ba` 已通过最终独立验收；第一轮 P2 已关闭，无剩余高、中等级
correctness/security finding。验收通过、任务目标完成，接受 `M4_W_39616_ADAPTATION_PASS`。

本结论只接受 086 本地分支成果，不表示已合入 `main` 或已推送。`#39153` 成为下一工作包，但只能在 Plan 086 获用户批准并进入本地
`main` 后启动；M4-W1 继续锁定。

## 复验结果

- hardened resolver 仍要求 linked checkout、worktree admin directory、`gitdir` backlink、`commondir`、registered checkout、common
  directory 与 main checkout ownership 闭合；伪造、缺失、失配、symlink、超限和代表性变化现场 fail-closed。
- 整改把 active-project 查询优先级统一为 exact cwd、当前 checkout root、hardened resolver 验证的继承 root。checkout root 只承载
  用户对当前 checkout 的直接显式决定，不授予未验证的主仓 trust 继承。
- nested cwd 回归同时覆盖 checkout `trusted` 覆盖 main `untrusted`、checkout `untrusted` 覆盖 main `trusted`，并在行为层验证
  config、permission、host MCP ready 与进程 marker；第一轮 finding 已完整关闭。
- 执行者保存的整改正式轮 Nextest `cf9287bf-ed1d-4a47-aaaf-d4b874877c29` 为 2/2，watchdog `final_rc=0`、无 stop/cleanup；
  scoped `just fix -p codex-config -p codex-core` 也以 `final_rc=0` 完成。独立复验检查提交差异与 `git diff --check` 通过，未重复运行
  此前已通过的重型 resolver/MCP/hooks 矩阵。

## 审查决定

- 维持第一轮决定：不把任意完全外置且缺乏主 checkout 反向登记的 `--separate-git-dir` 布局扩张为本任务要求，也不为此引入目录搜索、
  registry 或宽松 fallback；保留 exact-upstream、可证明归属和 fail-closed 边界。
- 不要求 workspace 全量、Docker、真实 API/模型、额外审计或可信设施。既有安全矩阵与整改直接因果轮足以覆盖实际写集；未运行项不冒充
  通过。
- 无需用户追加授权或任务内技术决策。后续唯一需要用户决定的是是否把 086 分支合入本地 `main`；远端推送仍未授权。

## 交付状态

- Plan、WBS 与 COMPLETED 已按最终事实收口；086 分支等待本报告及文档提交后保持 clean。
- 未修改主工作区、其他 worktree、Plan 082 保留资产或远端；未启动 `#39153`、M4-W1。
