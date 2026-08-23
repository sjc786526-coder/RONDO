# Plan 059 Publication Critic 训练数据实现

## 实质修改

- 新增 Plan 059 版本化 Scenario/Candidate/Binary/Boundary/Within-PASS/review 合同，以及分组切分、exact/near-duplicate、shortcut、exact-tokenizer census、freeze/manifest 和轻量 consumer；PublicationPacket、render 与 tokenizer 继续直接复用 Plan 054 v4 seam。
- 合成前冻结 72 candidate、30 Boundary、6 Within-PASS 的 coverage/stop lock。rehearsal-v1/v2 的 continuity metadata、length bucket、pair mechanism 和 mixed `hard_focus` finding 均在扩量前关闭；rehearsal-v3 全链路通过。
- 正式数据按六个小批独立复核。formal-v1/v2 暴露一个 uncertainty mechanism 粒度问题和三个 incomplete consistency pair 夹带 continuity defect；只重生成受影响 endpoint，并以逐行 Scenario/packet/supervision/pair 相等门禁复用未变化 review。formal-v3 终态为 72/72 candidate 与 36/36 pair accept。
- 首次正式冻结虽通过结构、review、token 和 consumer 门禁，但干净上下文审查发现跨 split 固定 Q-/Within-PASS marker 可完美预测标签，故 v1 判定数据 NO-GO，未提交其 tracked release；失败证据保留在主物理根 ignored Plan 059 namespace。
- revision v2 把 30 个 Q- 和 6 个 Within-PASS endpoint 改为逐场景显式文本，增加跨 split、支持数至少 4 的 label-exclusive char-4-gram 门禁。formal-v5 review 又发现 6 个 continuity 负例仍可接续、5 个 scope 负例噪声过轻；局部返修先由 rehearsal-v6 完整验证，再从 clean commit 生成 formal-v6 并对 72/36 全量重审。
- formal-v6 虽通过 teacher、split、token 与 consumer 门禁，最终干净审查仍发现 6 个 scope Q- 是唯一超过 80 candidate tokens 的样本，形成跨 split 完美 REWRITE 长度捷径，故 v2 判定数据 NO-GO。revision v3 让 scope Q+/Q- 长度相近且交错，新增双向 exact-token threshold 门禁；formal-v7 又发现 scope-04 Within-PASS 软方向因 Q+ 扩写而倒置，局部返修后的 rehearsal-v9 已完成 17/17 candidate、9/9 pair accept 和全链路 finalization。
- 从 clean implementation freeze 生成 formal-v8，并由独立 GPT-5.6-sol reviewer 对 72 candidate / 36 pair 全量重审；全部 accept，scope-04 Boundary 与 Within-PASS 方向均确认成立。正式 finalizer 生成 `training/publication-critic-v3/`，与主根 ignored `formal-v8-final` 逐字节一致。

## 验收结果

- v3 rehearsal：5 train / 5 validation / 7 unseen-test；10 PASS / 7 REWRITE；7 Boundary / 2 Within-PASS。17/17 candidate、9/9 pair 独立 accept，2 条 near edge 闭包，Plan 054 reference match、文本与 exact-token 长度 shortcut 均为 0。
- exact tokenizer：v3 rehearsal 17/17 census，10,941 tokens，单条 558–745，continuity omission 为 0；未加载模型、权重或执行 forward。
- consumer：rehearsal C1/C2/C3 累计为 5 Binary / 2 train Boundary / 1 train Within-PASS；默认拒绝 validation/unseen-test，train-only bundle 物理排除 holdout。
- 测试：Publication Critic contract/eval/training-data focused Python tests 44 项通过。Rust、Bazel、Docker、模型推理、训练、真实 API、CI/PR 均未运行。
- v3 正式数据：36 scenario group；train / validation / unseen-test 为 42/16/14；39 PASS / 33 REWRITE；30 Boundary / 6 Within-PASS。C1/C2/C3 为 42 Binary / +18 Boundary / +3 Within-PASS。
- 正式 teacher review：72/72 candidate、36/36 pair accept，remaining finding 为 0。11 条 near-duplicate edge 均在同 scenario；Plan 054 reference match、文本 shortcut 与 exact-token 长度 shortcut 均为 0。
- 正式 exact tokenizer：72/72 census，53,294 tokens，单条 553–2,753，continuity omission 为 0；manifest、frozen consumer、默认 holdout 拒绝与 train-only bundle 通过。首次向 tracked 目录物化时 tokenizer 进程偶发 exit 139，只生成空目录；安全移除后以 `TOKENIZERS_PARALLELISM=false` 同参数重跑成功，冻结内容与已成功的 ignored 正式结果一致。
- 两次早期干净上下文审查各发现 1 个真实 shortcut finding，v1/v2 均已判定数据 NO-GO。最终干净上下文预审独立复算 v2 finding closure、v3 全量语义、split/dedup/token/freeze/consumer 和文档事实后 PASS，remaining finding 为 0。v3 执行者 provisional 数据 GO，仍待计划制定者验收；M3-B1b 未解锁。
- 交付检查：tracked v3 与 ignored formal-v8-final 的 12 个文件逐字节一致；staged diff/空白、体积、symlink、敏感模式和允许路径通过。Plan 059 ignored namespace 为 4.3 MiB、27 个目录/264 个文件，全部目录 0700、文件 0600、无 symlink；主工作区保持 clean，Plan 058 未检查也未触碰。
