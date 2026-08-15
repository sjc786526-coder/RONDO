# Plan 032 prepare review_id 整改

- 独立验收确认正式 `prepare` 把 `guardian-evidence/0001` 的四位归档槽位误作 `review_id`，导致当前生产归档
  47/47 在 meta 二次校验时失败；已确认冻结 manifest/outbound 与 40 条标签本身正确，未重新生成标签或扩大重试。
- `_read_meta()` 现在从已安全读取、JSON 解析为对象的 production meta 取得非空 `review_id`，再调用现有
  production validator；归档槽位只保留路径职责。新增回归覆盖槽位 `0001` 与 meta `review-1` 不同仍通过。
- focused unittest **13/13**、`py_compile` 通过。使用真实 production reader/census/ledger/canonical builder 对
  当前 47 条做无写入 prepare 重算，得到 47 / 45 / 2 / 42 / 40 聚合计数，manifest、outbound、prepare receipt
  SHA-256 均与冻结批次一致，且未创建重算输出目录。
- 现有私有批次 verify / summarize 继续通过：40 条、`ready_for_l3=true`，labels 与 summary SHA-256 均未变化。
  未运行 Sol 第二批、L3/L4、Local-static、本地模型、Docker、Cargo、API、训练、CI 或全量测试；未合并、未推送。
