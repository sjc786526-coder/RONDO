# Multi 明确委派三任务比较案例排期

- 日期：2026-08-21
- 基线：`main@18aca497f13c7d50deaae9ab4c9a5add47ee1d4d`
- 范围：只读研究 Plan 049 收口分析、本地冻结 Terminal-Bench canary 任务和软 proactive policy；只更新当前 WBS，
  未运行 Docker、API、模型、Cargo 或测评

## 结论

- Plan 049 已可信证明共同软 policy 在三道 pilot 上可以合法产生零委派；新任务不追加或改写该实验，而是明确进入
  post-delegation conditional regime。
- 下一包是一个三任务 comparative case study，同时也是产品展示。两侧使用相同、明确要求实质委派与动态沟通整合的
  developer policy；policy 不指定 Team State 工具、Event/Fact 数量、成员角色或调用顺序。
- 从本地十道已冻结且可执行的 canary 中选择 `db-wal-recovery`、`filter-js-from-html`、`headless-terminal`：三者均有
  外部 verifier，并分别提供取证假设变化、攻击面反馈和多行为约束整合的协作机会。
- `sanitize-git-repo` 更适合作为稳定并行扫描，`openssl-selfsigned-cert` 与 `fix-git` 容易产生仪式性拆分；其余候选的
  双向影响或展示价值较弱，因此不进入本次三题。

## 规划更新

- `doc/WBS.md`：把明确委派三任务比较案例设为当前下一工作包，并同步方向 3、P5 与里程碑状态。
- `doc/WBS/multi-agent-trusted-evidence.md`：冻结研究问题、强化 policy 语义、三题、比较口径、完成条件和授权门。
- 真实 API、Docker、轮数和总预算仍须由该任务自己的 plan 冻结并另获明确授权；本次没有创建 execplan 或启动执行。
