# Plan 033 验收整改独立复验

日期：2026-08-15 ｜ 审查对象：`033-l3-l4-unfinetuned-baseline@2c52bbf`

## 结论

**验收通过；任务目标完成。**

上一轮独立验收报告指出的两个代码合同缺口和两处文档事实均已在同一 worktree 窄修。复验未发现新的
功能性或正确性阻断项。冻结教师输入、40 条私有终态、四条公开 shadow 记录、指标定义和聚合 baseline
均未改变，不需要重新运行模型。

本报告取代 `agent_log/2026-08-15-084543-plan033-independent-acceptance.md` 中“验收不通过”的当前状态；
前一报告继续作为整改前的历史证据保留。

## Findings 复核

### 1. 统一 shadow 合同：通过

- `artifacts.py` 现强制 `sol-static => imported`、`local-static/local-ft-static => auto`；反向组合被拒绝。
- 未声明来源合同的 shadow side（当前包括已退役且无结果行的 `luna-static`）被 fail-closed 拒绝。
- `config.taskset=holdout`，以及 shadow 的 `config.partition=holdout`，均强制 `tasks=null`；seed 的 body-free
  逐条投影仍允许发布。
- 新增负向测试覆盖错误映射、未声明 side、holdout 明细拒绝和 seed 放行；现有四条 shadow 记录通过收紧后的
  统一校验。

这项实现符合 Plan 033 和更新后的 `doc/eval-data-layout.md`，没有为本轮引入新结果库、权限系统或审计设施。

### 2. 最终交付 HEAD 离线重算：通过

- 发布阶段以 `git merge-base --is-ancestor <run_commit> HEAD` 要求真实运行 commit 仍在当前历史中；非法 SHA
  或非祖先 commit 均阻断。真实运行前的 clean committed harness 约束保持不变。
- 在 clean `2c52bbf` 上独立执行正式 `publish`：exit 0、`newly_published=[]`，四个 run id 不变，
  `runs.jsonl` 前后均为 248 行；baseline SHA-256 前后均为
  `ca0bbc21a24b23b607a1308462fcac16447d4577d779819e6c8f683bb09d4dcd`，worktree 未产生修改。

祖先绑定满足本任务“运行后提交结果与文档，最终交付仍能离线重算”的功能需求。结合现有 baseline 字节相等、
统一账本校验和运行前 clean-tree 门禁，本轮不再增加路径哈希、签名或通用 provenance 设施。

### 3. 权威文档事实：通过

- `doc/WBS/local-approval-model.md` 已明确 L5a、L3/L4 完成，当前进入 L5b。
- `doc/WBS.md`、`doc/WBS/eval-benchmark.md` 和 `doc/eval-data-layout.md` 已把 244 明确为 `track=tb`
  子集，并写明另有 4 条 shadow、当前总账本 248 条。
- 新的 side/source 与 holdout 投影规则已同步到数据布局合同；WBS-COMPLETED、Plan 当前验收状态和整改日志
  与 live 实现一致。

## 独立验证

- 复跑执行者声明的七个直接相关 unittest 模块：**326 项通过，0 失败，0 skip**。
- `uv lock --directory eval --check`：85 packages，通过。
- `git diff --check bd4085c..2c52bbf`：通过。
- 整改提交未修改 `eval/results/`；正式 no-op 复验后账本仍 248 行、baseline 哈希不变、worktree clean。
- 主工作区仍为 `main@1c5f704 == origin/main`；两个未知未跟踪 `doc/research/RONDO Multi*.md` 未触碰。

## 代用户作出的决定

1. **接受执行者对 `luna-static` 的 fail-closed 处理。** 该 side 当前无发布合同和结果行，不推测其 source；
   将来若恢复使用，应先在数据布局规范中定义，不为本任务保留宽松兼容。
2. **接受 harness 祖先绑定方案。** 它修复了结果/文档提交后无法重算的问题，同时保留真实运行前 clean-tree
   约束；本轮不扩建更复杂的可信或审计体系。
3. **维持上一轮对真实数据的决定。** 保留 40 条 baseline、全 allow 教师分布和 5 条 512-token
   fail-closed 结果；不重标、不改指标、不重跑模型，也不把教师分歧称为漏放/误拦。
4. **维持设备级显存表述。** 8,048,869,376 B 是受控窗口内的 device-level peak，不将 WSL 空的
   compute-app 查询表述成进程级独占证明；不因此扩建设施或重跑。
5. **允许进入交付审批。** 033 worktree 已达到可合并状态，但本次仍不合并、不推送；等待用户批准后再按仓库
   流程完成本地 main 合并与推送。未知主工作区文件和旧 `.staging-*` 目录继续保留不动。

## 当前状态

- Plan 033：验收通过，任务目标完成，方向 2 的 P2 剩余项可以保持关闭。
- 下一工作包：按权威 WBS 进入 P3 的 L5b/L6。
- 分支：`033-l3-l4-unfinetuned-baseline`，整改实现 HEAD `2c52bbf`；未合并、未推送。
