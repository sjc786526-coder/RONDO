# Plan 086 / #39616 独立审查（第一轮）

## 结论

候选提交 `3dc31d5f39edaef7d8f4a440c364db98dc0f9039` 的 linked-worktree 注册、回链、common directory 与主仓
ownership 验证和上游 `#39616` 的安全语义一致；未发现伪造 checkout 继续继承主仓 trust 的旧 resolver 或并行绕过。

本轮结论为 `REVIEW_NOT_ACCEPTED / REMEDIATION_REQUIRED`：存在 1 个未关闭的 P2 correctness finding，暂不接受
`M4_W_39616_ADAPTATION_PASS`，不更新 WBS/COMPLETED，也不启动 `#39153` 或 M4-W1。

## Finding

### P2：linked worktree 子目录会跳过 checkout root 的显式 trust

`ConfigToml::get_active_project` 只按精确 `resolved_cwd`、随后按 hardened resolver 返回的主仓 root 查找 trust。cwd 位于 linked
worktree 子目录时，用户为 worktree checkout root 写入的显式 `trusted` 或 `untrusted` 不会命中，可能转而采用主仓决定或 `None`。
与此同时，config loader 的 `ProjectTrustContext::decision_for_dir` 会按 project/worktree root 优先，因此 project config/hooks 与
`active_project`、permission defaults、TUI/app-server trust 流程可能得到不同结论。

这不是要求新建 trust 体系；应在现有单一结论链内补齐 checkout-root 优先级，并增加至少一条从 linked worktree 子目录启动的回归，证明
checkout root 的显式 `trusted` 和 `untrusted` 不会被主仓 trust 覆盖。具体 API、候选路径传递方式和测试拆分由执行者自主选择。

## 审查决定

- 不把“common Git directory 位于主 checkout 之外的任意 `--separate-git-dir` 布局”列为本轮 finding。当前实现与 exact upstream
  增量一致，并已覆盖上游保护的主 checkout `.git` pointer / colocated separate Git directory 形式。完全外置的 common directory
  不含可供无 Git 子进程 resolver 证明主 checkout 路径的反向登记；为支持它而引入目录搜索、registry 或宽松 fallback 会偏离本任务
  fail-closed 窄适配。若未来要扩展这类布局，应作为明确兼容需求另行设计。
- 不重复运行重型 Cargo。审查复核了提交差异、关键消费者与执行者保存的 nextest/watchdog 证据；独立只读复核执行的
  `git diff --check 3dc31d5f^ 3dc31d5f` 通过。整改后只需运行直接覆盖该 finding 的聚焦测试及受影响 crate 的必要格式化/fix，随后从
  clean 临时 Git 现场重跑受影响的正式行为场景；无需扩大到 workspace 全量、Docker、真实 API/模型或额外审计设施。

## 其余审查结果

- `.git`、admin directory、`gitdir` backlink、`commondir`、registered checkout、canonical identity 与 main ownership 的验证闭环
  fail-closed；metadata 类型、symlink、64KiB 门限、代表性 stat/read 替换和原生路径处理有相称覆盖。
- forged/missing/mismatch/symlink 等反例与 registered linked worktree 正例覆盖有效；config、permission、host MCP 启动 marker 和
  app-server hooks 的行为证据职责清楚。
- 实施日志如实记录 exit 125 资源停止、拆窄重跑、未运行项和未合并/未推送状态；未发现需要用户追加授权或计划外决策的事项。
