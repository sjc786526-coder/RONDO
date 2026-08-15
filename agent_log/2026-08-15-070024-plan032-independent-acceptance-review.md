# Plan 032 独立验收审查

日期：2026-08-15

审查对象：`95d4f89 eval: freeze first Sol teacher labels`

基线：`ca1fde0dd725fed81138df3306b53cee663a567a`

## 结论

- **验收：不通过。** 已冻结的 40 条私有教师标签及其导入绑定本身正确，但当前 tracked `prepare` 正式入口
  无法读取任何一条现有生产归档，不能复现本批 prepare，也不能作为后续增量批次的可用入口。
- **任务目标：失败（指当前提交形态）。** 47 条身份、去重、分区、40 条标签和 L3 私有输入已经正确落成；
  失败点是本任务同时交付的 prepare 设施在最终提交中发生了功能性回归。当前不得合并或推送，只需做一个窄修
  和对应 focused 回归，不需要重做标签、扩大审计设施或改变 L3/L4 路线。

## 阻断问题：归档槽位名被误当作 `review_id`

`eval/rondo_eval/local_approval/teacher_labels.py:511` 从
`eval-data/runs/<run>/guardian-evidence/0001/E_final.json` 的父目录取 `0001`，并把它作为 `review_id` 交给
production meta validator。真实归档中该四位目录只是顺序槽位，`meta.review_id` 是独立身份；当前 47/47 条二者
均不同。`token_census.collect_evidence_inputs()` 的生产逻辑已经正确地从 meta 自身读取非空 `review_id` 后再校验
其余冻结字段，Plan 032 的二次读取不应另加“目录名等于 review_id”的假设。

使用提交内正式 CLI 对当前 47 条源归档复现：

```text
python -m rondo_eval.local_approval.teacher_labels prepare ...
=> exit 2, {"blocker":"evidence_meta_invalid","status":"not_ready"}
```

失败发生在创建输出目录之前，没有留下复现批次。进一步只读聚合检查得到：源实例 47，当前 `_read_meta()` 失败
47，目录槽位与 meta review id 不同 47。现有 12 项测试覆盖 identity、代表选择、响应、attempt、summary 篡改和
census，但没有运行真实或合成的 prepare 路径，因此未发现这一回归。

## 已确认正确的部分

- 独立从当前 47 条源归档读取 production meta（按生产逻辑使用 meta 自身的 review id）并重算后，得到 45 个
  语义身份、2 个重复实例、42 个 12k-fit 实例和 40 个最终候选；重算的全部 manifest instance 与 outbound
  均和私有冻结文件精确相等，census identity 也相等。现有标签批次没有因此失真。
- 真实私有批次 `verify` 通过：40 条、seed 24 / holdout 16、`ready_for_l3=true`；labels SHA-256 为
  `7eaafa25aa99de804559ee77f034f4e69f8ff4227f5cf5d8d70c66f0a7b82a40`。
- `summarize` 重跑完整 verify 后与 tracked lock 字节一致，summary SHA-256 为
  `237a57b4378c6c0cc4ee5ce919246dca150ea7c8646b946f17e41acc6593a57e`。
- focused unittest **12/12** 通过。决策复用 live static validator；缺失、额外、重复、identity/usage、attempt、
  prompt/schema/census/hash 不一致均整批拒绝。Plan 031 Guardian bridge 没有被误用为 static 教师请求。
- 私有批次目录为 0700、七个文件均为 0600，实际 SHA 与 tracked lock 一致；本提交 11 个 changed tracked 文件
  中没有出现私有逐条 semantic id、E_final SHA 或 review id，`eval-data/` 仍由根规则忽略。
- 主工作区保持 `main == origin/main == ca1fde0` 且 clean；未运行 L3/L4、Local-static、本地模型、Docker、Cargo、
  API、训练、CI 或全量测试，未读取 `.env.local`，未修改产品代码或 `eval/results/runs.jsonl`。

## 审查者代用户作出的决定

1. **保留现有私有标签批次，不重新生成标签。** 当前源归档重算结果与 manifest/outbound 精确相等，完整 label
   集合仍通过终检；本缺陷只在 tracked prepare 的 meta 二次读取。不得借整改启动第二批 Sol、扩大重试或改变
   prompt、schema、身份、分区和既有哈希。
2. **只修 review id 的错误来源并补一项 focused 回归。** 实现应与现有 production reader 一致，从已安全读取且
   通过 schema 检查的 meta 取得 review id；回归至少覆盖 `guardian-evidence/0001` 与 `meta.review_id=review-1`
   不同仍可通过。具体函数拆分由执行者决定，不新增 schema registry、签名、审计或可信体系。
3. 修复后只需重跑 teacher-label focused tests、一次当前 47 条无正文输出的只读 prepare 重算，以及现有私有批次
   `verify/summarize`；不重跑 Sol、不运行模型、L3/L4、Docker、Cargo、API、训练、全量测试或 CI。
4. 执行者在原 worktree 提交窄修后交回复验。当前不合并、不推送；WBS 的下游顺序不需要重新决策，验收通过后
   仍按既定 L3/L4 工作包推进。

执行者没有留下需要用户选择的 Plan 032 未决项；上述整改范围和“保留标签、不重新生成”决定已代用户确定。
