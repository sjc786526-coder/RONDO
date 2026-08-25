# Plan 069 阶段 E 外部验收审查

日期：2026-08-25
审查对象：`617d3d294d7679e9495c9ea7586d39cb89b80ee1`

## 结论

- Stage E 产品实现与正式证据通过 correctness/functionality 审查。精确 merge、单一 Root authority、activation retry gate、异常退出后的
  committed read/cold resume/继续 mutation/close，以及 persisted cwd 与 live override 分工均未发现高/中等级产品问题。
- 当前外部验收 **不通过**，交付目标 **尚未完全完成**：存在一项中等级文档/集成正确性 finding。该 finding 不撤销
  `M4_S1_PASS` 技术结论，但必须在最终交付分支中关闭。

## Finding

### M-1：完成文档没有收敛为同一组当前事实

069 分支基于授权的 `main@62d3ed732bf9452014a85722e7ed88c50a63dd94` 宣布 `M4_S1_PASS`，但同一分支仍有互相矛盾或已经进入
当前 main 的旧事实：

- `doc/WBS/multi-agent-trusted-evidence.md` 仍称正式 Session query 等待 M4-S1、M4-S1 继续推进，并称 Plan 073 / M3-C2 尚未完成。
- `doc/WBS.md` 仍称 Plan 073 尚未完成、M3-D 等待其结果；当前已提交 `main@bc88957a3213bc24f94fce3a7e6fffb62bbbb522`
  已记录 Plan 073 的 `NO-GO` 与 M3-D 保持锁定。
- 069 的 `doc/WBS-COMPLETED.md` 只有 Plan 069 新完成条目，尚未合并当前 main 已提交的 Plan 073 完成条目。直接把旧分支文档作为
  后续整合选择会覆盖或冲突于已经进入 main 的事实。

这不是要求吸收 Plan 073 产品实现或 Plan 075 现场。修复应仅以当前 main 的受跟踪文档为事实源，把 Plan 073 `NO-GO` / M3-D
锁定与 Plan 069 `M4_S1_PASS` 合并到同一份当前 WBS，并在 completed history 中保留两项完成记录。`doc/WBS/durable-team-runtime.md`
现有 S/C/W 条件边正确，无需扩大改写。

## 产品与证据核验

- merge 双亲精确为规划提交 `f970f133cb4613b0b7f9f27db266aa36164fce12` 与授权 main
  `62d3ed732bf9452014a85722e7ed88c50a63dd94`；相对该 main 的新增产品代码只把 activation retry gate 从 Tokio mutex 改为一许可
  `Semaphore`，另有等价条件格式收敛。permit 覆盖 marker reconcile、generation-1 register 与完成发布；失败、取消或等待不会创建新
  authority、释放 Root owner 或发布虚假完成。
- 正式 Durable Team JUnit 真实包含领域跨进程、产品 cold resume、产品 immediate-crash 三项；immediate-crash 子进程在首次
  `team_publish` 成功后直接 `process::exit(0)`，父进程从同一 fresh home 做 non-owner committed read，验证原 Session/Root/
  TeamInstance，冷恢复后继续 mutation 并正常 close。
- persisted cwd 两项与 app-server 两项证明 read-by-ID/path/list 的持久投影一致，resume 中 `thread.cwd` 保持 persisted view，实时
  `cwd` 与 `runtime_workspace_roots` 来自已建立 Session 的显式 live 配置，而非把持久投影冒充执行 binding。
- 五份成功 JUnit 的用例数、状态与 SHA-256 均和最终日志一致：3/3、2/2、2/2、191/191、3/3，均 `run_rc=0`、
  `final_rc=0`、`stop_reason=none`。`git diff --check` 通过。
- 全 workspace run `20260825-041855-1000-2298859` 确为 `run_rc=101`、JUnit absent，未被写成通过。保留元数据不能独立复原
  HTTP 404 stderr，但该默认 rusty-v8 输入阻断与仓库既有记录一致，且没有产品测试失败证据。

## 代用户作出的决策

- 接受 Stage E 的产品正确性与 `M4_S1_PASS` 技术结论；不要求为了已知 rusty-v8 默认 URL 404 再跑完整 workspace，也不要求
  Docker、真实模型/API 或额外审计设施。当前通过的聚焦正式链、邻近 crate、clippy 和静态审查与本次窄产品改动相称。
- 不授权把当前 `main@bc88957` 的产品代码合入 069，也不读取或触碰 Plan 075 未提交现场。允许且要求执行者只读使用当前 main 的
  已提交 WBS/COMPLETED 事实，形成一次文档窄修提交：以当前 main 版本为底合并 Plan 073 与 Plan 069 两组事实，并同步
  `doc/WBS/multi-agent-trusted-evidence.md` 的 M4-S1/Session query 状态。
- 文档窄修只需 `git diff --check` 和范围/状态复核，不重跑 Rust。修复后重新提交外部复验；仍不得 merge/push 069、归档分支或
  吸收更新后的 main。

## 当前状态

- 验收：**不通过**（产品正确，完成文档尚有一项中等级矛盾）。
- 当前授权任务目标：**尚未完全完成**。
- M4-S1 技术结论：**`M4_S1_PASS` 成立，等待文档整改后完成外部交付验收**。
