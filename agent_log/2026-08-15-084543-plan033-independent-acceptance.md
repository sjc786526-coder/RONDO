# Plan 033 独立验收审查

日期：2026-08-15 ｜ 审查对象：`033-l3-l4-unfinetuned-baseline@671f82c`

## 结论

**验收不通过；任务目标完成。**

冻结的 40 条教师输入、私有 Local-static 终态、四条公开 shadow 记录和聚合 baseline 本身正确，未发现会使
本次测量失真或泄漏 holdout 明细的问题。核心目标——建立首个未微调 12k Local-static baseline——已经实现，
现有真实模型结果不作废，也不需要重新回放。

但交付分支还有两个直接违反 Plan 033 已写明合同的窄缺口，以及两处权威文档事实未收干净。它们都可在
现有 worktree 内用小改动和 pure/focused tests 修复；修完后再复验即可，不得借此改模型结果、指标或扩大设施。

## Findings

### 1. [中] 统一结果校验没有落实 shadow 来源映射和 holdout 公共边界

`eval/rondo_eval/artifacts.py:704` 只检查 `source=auto|imported` 枚举及 imported 的部分空字段；
`eval/rondo_eval/artifacts.py:798` 对 `tasks` 只检查类型。当前 `_validate_record()` 会接受
`local-static/imported`、`sol-static/auto`，也会接受两类携带非空 `tasks` 的 holdout shadow 行。

这与 Plan 033 §3.4 和 `doc/eval-data-layout.md:225` 的固定合同不符，也说明执行日志所称的
“artifacts.py 窄扩展 shadow 来源合同”没有完整落到统一门禁。现有四行由专用 builder 生成，组合正确且两条
holdout 均为 `tasks=null`，所以不影响已发布 baseline；合并前仍应补当前 v1 的 source/side 映射和
`holdout => tasks=null` 负向校验，并补少量纯测试。

### 2. [中] 最终交付 HEAD 无法按正式 CLI 幂等重算/发布

`eval/rondo_eval/local_approval/shadow_replay.py:1454` 要求当前 HEAD 精确等于真实运行时 harness commit
`bbb572d`。结果与文档提交后 HEAD 已是 `671f82c`，因此在当前 clean worktree 实际重跑 `publish` 返回退出码 70：
`harness_commit_moved_since_run`，并不是执行日志 `:59` 所称的 no-op。

这不影响现有结果：审查已用当前聚合代码从冻结私有 run 逐字段重建四行和 baseline，全部精确相等。但正式 CLI
在最终交付状态不能完成同一验证，与“baseline 可由冻结输入和同版本聚合代码重算”及幂等发布目标不一致。
应窄修最终交付后的离线重算/no-op 路径并补回归；不要放宽真实运行前 clean harness 约束，也不需要重跑模型。

### 3. [中低] WBS 和数据布局仍有两处当前事实陈旧

- `doc/WBS/local-approval-model.md:308` 仍写“当前只推进尚未完成的 L3/L4”，与同文 L3/L4 已完成、下一步
  L5b/L6 冲突。
- 新增四条 shadow 后 `runs.jsonl` 实际为 248 条。`doc/eval-data-layout.md:85` 仍称当前共有 244 条；
  `doc/WBS.md:25`、`doc/WBS/eval-benchmark.md:34` 应明确 244 是原有 TB/replay campaign 子集，当前总账本
  另含四条 shadow。

这是文档窄修，不应回开或重写既有历史。

## 独立核验结果

- Plan 032 tracked lock 与私有 manifest/outbound/labels/receipt/import metadata 匹配；40 条逐条身份、代表
  `E_final` SHA、payload SHA、分区、教师标签和 input-token 绑定一致，seed 24 / holdout 16，无缺失、额外或重复。
- 私有 run 为 40 outcomes / 40 attempts、无重试；终态 allow 16、deny 19、结构失败 5、超时 0、infra 0。
  五条结构失败均为截断的无效 JSON 且 output token 达冻结上限 512，按 fail-closed 保留正确。
- 独立重算总体教师一致 16/35、有效判定覆盖 35/40；seed、holdout、overall 的终态、分布、nearest-rank
  延迟/token 指标均与 baseline 一致。
- 从私有结果重建的四条 public record 全部逐字段相等；重建 baseline 逐字节相等，SHA-256 为
  `ca0bbc21a24b23b607a1308462fcac16447d4577d779819e6c8f683bb09d4dcd`。
- 两条 holdout 公开行均 `tasks=null`；tracked 文件未发现 holdout semantic id 或 payload SHA。既有 census
  中不带分区的归档哈希不构成本任务泄漏。
- 私有目录/文件权限为 0700/0600，cleanup 四项均为 true；当前无 `llama-server`，端口已释放。
- 独立复跑 205 项直接相关 unittest 通过；`uv lock --directory eval --check` 解析 85 个包通过；
  `verify` 返回 `ready_for_replay`；worktree diff check 通过。

## 代用户作出的决定

1. **保留并接受现有 40 条真实 baseline 数据。** 不重新 prepare、重标、调用 Sol、改变指标或重跑模型；
   上述两个代码缺口只做离线/统一门禁窄修。
2. **接受教师批次 40/40 allow 的客观局限。** 16/35 只作为时点 Sol 蒸馏目标下的描述性基线，不设采用门槛，
   不把分歧称为漏放/误拦；后续 L5b 自行保证训练数据的类别与风险多样性，不回开 Plan 033。
3. **保留五条 512-token 结构失败。** 它们是有效 fail-closed baseline 结果，不提高本轮输出上限、不按内容重试。
4. **接受 WSL GPU 进程枚举限制为本轮非阻断限制。** 8,048,869,376 B 只表述为受控运行窗口内的设备级
   `memory.used` 峰值；不声称 `nvidia-smi --query-compute-apps` 已证明进程级独占，不为此扩建资格/审计设施或重跑。
5. **不处理未知来源对象。** 主工作区仍为 `main@1c5f704 == origin/main`，但验收时已有两个未知未跟踪
   `doc/research/RONDO Multi*.md`；四个旧 `.staging-*` 目录亦保留，均不归因于 Plan 033、不清理。
6. **暂不合并、不推送。** 执行者先在同一 033 worktree 完成上述窄修、相关测试和一次修复提交，再交回复验；
   无需再次申请真实模型、Sol、Docker、Cargo 或云资源授权。

## 当前状态

- 分支/worktree：`033-l3-l4-unfinetuned-baseline@671f82c`，写入本报告前 clean，未合并、未推送。
- 现有 baseline：有效且应保留。
- P2 文档状态：目标结果已取得，但在上述合同与文档缺口修复、复验前，不应把本分支视为可合并交付。
