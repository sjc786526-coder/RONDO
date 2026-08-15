# Plan 024 文档整改终审报告

- 日期：2026-08-14
- 审查对象：`024-wp3b-a2-exact-token-census@e9305d9`（parent `1c4c9b2`）
- 审查基线：`agent_log/2026-08-14-170338-plan024-remediation-independent-review.md`
- 审查边界：纯文档复审；未改代码、未重跑模型、未读取 `.env.local`、未合并、未推送

## 结论

**终审通过。** `e9305d9` 已完整关闭上一轮 R1—R3，`6b36d05` 的实现整改与后续文档收口可以作为
**WP3b-A2 blocked/incomplete 状态**验收。上一轮“暂不合并”的整改阻断解除；分支已达到可交付状态，
但本次未执行合并或推送。

通过的是 census 失败语义、无模型回归和文档事实边界，**不是 WP3b-A2 普查完成**：当前仍只有 24/47 条 exact-token
计数，未发布 baseline、未选择上下文档位，整改后的当前代码也尚未真实运行。

## R1—R3 关闭情况

### R1：21 条已定性与 2 条未定性已严格分开

- `doc/WBS.md:27,40-46,71`
- `doc/WBS/local-approval-model.md:70-87,172`
- `plan/024-wp3b-a2-exact-token-census-execplan.md:106-117`
- `agent_log/2026-08-14-091500-plan024-exact-token-census.md:16-25`

四份文档现在只对 21 条 adapter 400 断言 reasoning item shape rejection、共用 converter 和增大上下文无效；
另外 2 条通用 500 明确保持原因未定性。下一任务只以已证实的 21 条为 provider-neutral static-payload 兼容输入；
重跑若仍出现 500，继续 fail closed 并单独诊断，不预设兼容能解决。

### R2：全集 fit/可服务性上限结论已撤回

`0/47`、`9/47` 和“全集可服务性上限”已从四份目标文档删除。当前只保留 counted 子集的算术事实：

- 4k：0/24；
- 8k：9/24；
- 12k：22/24；
- 16k：23/24；
- 24k：24/24。

文档明确说明其余 23 条没有 token 数，完整 47 条的 fit 数量与非平凡上限均不可得，不据此选档位。

### R3：旧真实运行与当前实现的版本边界已写清

Plan、子 WBS 和执行日志均明确：两次结果一致、锚点 5,313 的真实运行属于 `6b36d05` 之前的实现；
整改后的当前代码只通过无模型回归，尚未重新真实运行。根 WBS 没有把旧运行写成当前代码的现场验收。

## 文档与工件状态

- `e9305d9` 恰好修改上一轮清单中的 4 份文档，共 `+49/-36`；`eval/` tree 无变化。
- `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 保持 WP3b-A2 `blocked/incomplete`，下一步路线一致。
- Plan 保留原始 47/47 完成合同，不追加事后 success 条件；交接仍指向 WBS。
- 执行日志保留 7 次历史模型生命周期、127/127 focused tests 与 eval-lock 结果，并准确限定版本。
- `doc/WBS-COMPLETED.md` 没有恢复 Plan 024 完成记录。
- `eval/results/baselines/local-approval-exact-token-census-v1.json` 在 HEAD、索引和工作树中均不存在。
- 未修改 README、AGENTS、其他方向 WBS 或历史独立审查报告，范围没有扩张。

## 验证

| 验证 | 结果 |
|---|---|
| `git diff --check 1c4c9b2..e9305d9` | 通过 |
| 提交范围 | 4 个目标文档，`+49/-36` |
| `eval/` 代码与测试 | 与 `1c4c9b2` 一致 |
| focused tests / eval lock | 未重跑；继承代码整改复审的 127/127 与 85 packages 通过证据 |
| baseline / WBS-COMPLETED | 均未恢复 |
| 8080 / private local-approval 目录 / llama-server | 无 listener、无对象、无进程 |
| 主工作区 | clean `main`，等于 `origin/main@40f3099` |
| worktree | 提交前 clean，分支未合并、未推送 |

## 后续边界

当前不需要用户补充决策或授权。若用户随后要求交付，可按仓库流程合并该分支并推送；这只能表述为合入
“blocked/incomplete 的 census 设施与失败诊断”，不能写成 WP3b-A2 完成。

后续另开 provider-neutral static-payload 兼容任务，完成已证实 21 条形状的兼容合同和无模型门禁后，
再单独取得真实模型/GPU 授权重跑 47/47。只有完整计数通过后，才能发布 baseline、决定上下文档位或完成 WP3b-A2。
