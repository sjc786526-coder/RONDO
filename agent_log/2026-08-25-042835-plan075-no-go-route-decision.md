# Plan 075：Publication Critic `NO-GO` 原因调研与路线决策

## 实质工作

- 在独立 worktree 中读取并交叉核对产品/WBS、v7/v8 数据、Plan 060/066 训练、Plan 054/068/071 基线与资格、Plan 073
  正式结果及其 ignored 归档；分别标记正式事实、辅助事实和未知。
- 静态复算 Plan 073 的 confusion、balanced accuracy、AUC、完整 threshold curve、pair 与 runtime；核对 Plan 066
  bundle/receipt、候选哈希、训练方向及 base/C1/C3 tokenizer/config 身份。未发现能推翻 `NO_GO` 的错绑或 correctness 故障。
- 形成冻结报告，并在当前 WBS 登记唯一路线：待授权的训练动态与质量门有界诊断。下游没有在本任务实施。

## 结论

- 直接原因是 exact base/C1/C3 在冻结 validation 上均达不到发布质量底线；threshold、部署、runtime、typed failure 和
  Judge 完整性不是原因。
- Plan 066 训练后的候选发生输出/排序退化，且训练期没有质量停止门；但现有单 recipe/seed/run 不能唯一归因到 LR、裁剪、
  optimizer、objective、数据或底模。base 自身也不合格。
- 证据足以决定先做训练动态的有界诊断，不足以支持直接正式再训练、扩数据、换底模、重跑 M3-C2 或暂停整个产品方向。

## 验收与边界

- `PYTHONPATH=eval python3 -m unittest eval.tests.test_publication_critic_plan073_selection \
  eval.tests.test_publication_critic_plan066_training eval.tests.test_publication_critic_full_model_training`：122 项通过，1 项 skip。
- 独立因果审查 `ACCEPT`，无 P1/P2，`remaining correctness/functionality findings=[]`；独立范围复验 `ACCEPT`，规划唯一来源、
  数值资源上限和 exact base 仅作诊断 control 的整改均关闭。
- 未运行或使用模型/GPU、Cargo、Docker、真实 API、HF 网络、云资源或付费服务；未触碰 unseen-test 正文、Plan 073 历史结果、
  产品默认或任何并行 worktree。Plan 069 阶段 E 的未提交现场保持原样。
