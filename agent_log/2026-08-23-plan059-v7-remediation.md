# Plan 059 revision v7 修复与正式冻结

## 结果

- 独立验收对 revision v6 提出的两个 finding 均确认存在：公开 `DatasetConsumer(...)` 可绕过 factory 的 train-only 裁剪与固定 rubric；六组
  Scope Q− 的 candidate-token 长度明显偏大，可替代 `scope_and_signal` 判断。v6 保留为历史冻结，tracked release 升级为
  `training/publication-critic-v7/`。
- `DatasetConsumer` 关闭 dataclass 自动构造，只允许 `from_rows()` / `from_frozen_directory()` 走严格 validation、Plan 054 固定 input/rubric
  与 holdout 裁剪；直接注入全量 rows 和错误 rubric 现在抛出 `TypeError`，并有定向回归。
- Scope 修复没有缩短 Q− 来凑长度。压缩版 rehearsal-v21 被独立 reviewer 判定 6 个 Q− 实际仍为 PASS 后立即停止；v23 恢复六类已确认的
  product-shaped process dump，并扩充 Q+ 的有用结构化状态。exact candidate-token 为 Q+
  `150/179/182/144/176/186`、Q− `138/175/204/124/166/196`，4 组 Q− 更短、2 组更长。

## 复核与冻结

- 独立 teacher reviewer：`gpt-5.6-sol/xhigh`，session `/root/teacher_reviewer_v2`，prompt SHA-256
  `38235f56bcb3a0a29ce39dd90b6ca1d32dda4e6c9866c430bf9f72db25878d2c`。v23 新审 12/12 Scope endpoint、6/6 Boundary 和受 Q+ 扩写影响的
  1/1 Within-PASS，全部 accept；六个 Q− 只失败 `scope_and_signal`，pair direction/context/omission/atomicity 与软方向均确认。
- generator：`gpt-5.6-sol/runtime_not_exposed`，session `01a02ec2-6085-73a1-95bf-dee63931a3c1`，v7 prompt SHA-256
  `a37213453e87c4b4d61dcdd2514b197bd4493f75dea242fee6edbc9b5ed191bf`。formal-v12 对 60 个未变 candidate 与 29 个未变 pair 先验证
  model-visible packet/endpoint 相等，再复用既有 review；变化的 12 candidate 与 7 pair 使用 v23 新审结论。
- `formal-v12-final` 冻结 36 scenario group、72 candidate（39 PASS / 33 REWRITE，train/validation/unseen-test=`42/16/14`）、30 Boundary、
  6 Within-PASS；C1/C2/C3=`42 Binary / +18 Boundary / +3 Within-PASS`。12 条 near-duplicate edge 全部进入 group closure；Plan 054
  reference match、model-visible char-4 shortcut 与双向 candidate-token threshold shortcut 均为 0。
- 全量 exact-tokenizer census 为 50,073 tokens，单条 553–1,367，continuity omission 为 0。tracked v7 与 ignored formal final 的 12 个文件
  逐字节一致，manifest content SHA-256 为 `07666936706786c456e83a7130c211013ff95cfb3e494154e62fca1e3bc528eb`。

## 验证与边界

- 5 个 focused Python `unittest` 模块共 62/62 PASS。另从 tracked v7 重新运行 exact census 并与 stored census 逐行相等；默认/evaluation
  consumer 分别只保留 `42/42/21` 与 `72/72/36` packet/supervision/pair，C1/C2/C3 pair 为 `0/18/21`，train-only bundle 与固定 rubric
  模型输入通过。
- 未运行 Rust、Cargo、Bazel、Docker、完整模型/权重、model forward、训练、真实 API、CI 或 PR；新增付费预算为 0 USD。Plan 058、
  `.env.local`、`mydev/`、`multidev/` 产品源码和主工作区 tracked 内容均未触碰。
- 主根 Plan 059 ignored namespace 当前保留 51 个顶层证据目录、489 个文件、约 9.0 MiB；目录/文件均为 0700/0600，无 symlink。当前关键证据为
  `rehearsal-v23{,-final}`、`formal-v12{,-final}`；v21/v22 与更早批次保留为失败/返修历史，最终验收和获批主线整合后可安全清理。
  本轮临时 tokenizer-only venv 因含解释器 symlink，完成 census 后已删除，可从既有离线 cache 重建。
- 执行者 provisional 数据建议为 **GO**。这不是计划制定者最终 M3-B1b 数据 GO，不解锁 M3-B1b，也不授权合并、推送或训练。
