# Plan 032 首批 Sol 教师标签

- 落地 L3 canonical static v3 教师 prompt、严格 label schema、稳定语义身份/分区/代表选择、冻结 manifest 与
  prepare receipt、原始返回与 attempt provenance 保存、完整导入校验及 body-free 聚合锁。tracked CLI 仅保留
  不含正文的 transport 长度/分块数/hash 信息，不提供正文 stdout 出口。
- 真实源为 47 条生产 `E_final`：45 个语义身份、2 个重复实例、42 个 12k 适配实例；语义去重后生成 40 条
  教师标签（seed 24、holdout 16），聚合排除超窗 5、语义重复 2。教师为当前开发用 Codex
  `gpt-5.6-sol`，生成日期 2026-08-15；标签是时点蒸馏目标，不是人工 ground truth。
- 一个完整批次后，16 条只因首次传输失败按完全相同 prompt 与输入各重试一次；schema 重试为 0，未因标签
  内容重试。最终 labels SHA-256 为
  `7eaafa25aa99de804559ee77f034f4e69f8ff4227f5cf5d8d70c66f0a7b82a40`。
- 独立只读审查指出终检绑定、summary 复验、正文 stdout、retry provenance、census 漂移和消息边界问题；已收紧为
  当前 tracked 合同 + prepare receipt 全绑定、summary 重跑 verify、删除正文 stdout 入口、严格 attempt 记录、
  固定 census digest 与不可跨消息/后续 item 的 approval block 解析，并增加布尔类型和同步篡改回归。
- focused `PYTHONPATH=eval python -m unittest eval.tests.test_teacher_labels -v` 为 12/12，`py_compile` 通过；
  真实批次 verify / summarize 两次幂等通过，`ready_for_l3=true`。
- 完整正文和逐条数据仅在 ignored 私有目录，权限为目录 0700、文件 0600；未运行 L3/L4、Local-static、
  本地模型、Docker、Cargo、API、训练、全量测试或 CI，未修改产品代码、run ledger，未发布 shadow 结果。
