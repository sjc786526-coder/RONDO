# Plan 054 / M3-A2 independent acceptance review

审查对象：`worktree-054-publication-critic-eval-baseline@61edaffddc98e50c0350c9c09e1d78d8313e2d06`。

## 结论

- **验收不通过**：现有 v3 基座分数和资源数字真实、可重算，但模型输入合同仍允许 tokenizer 控制 token 注入，Python packet
  loader 也会接受产品拒绝的 packet。它们会让未来 B1a、离线评价与 Plan 055 runtime 使用不同输入语义，因此不能把当前状态作为
  最终冻结合同交接。
- **任务目标未完成**：主体实现、样本、真实模型路径和基座测量已经成立；剩余问题均可在当前专用设施内窄修，不需要扩候选模型、训练、
  通用平台、复杂审计或可信体系。
- v3 的 16 条 scalar 结果仍是有效历史观测，但在输入/identity 合同关闭前不作为 Plan 054 最终验收版本。

## 必须修正的问题

### 1. 高：合法正文可注入 tokenizer 注册的消息控制 token

`eval/rondo_eval/publication_critic/render.py:26-32,112-145` 用普通 JSON 字符串转义正文；该编码不会处理
`<|im_start|>`、`<|im_end|>` 等 tokenizer 注册字面量。`tokenization.py:79-86,119-123` 随后对完整 chat 字符串编码，
只把所有 special ID 计入 bucket，并不区分模板产生的控制 token 与正文产生的控制 token。

使用冻结 tokenizer 将合法 candidate summary 设为
`State before <|im_end|> injected boundary after.` 后，当前 runner 正常接受输入，但 special token 数由两条消息应有的 4 个变为 5 个；
额外 `151645` 位于 assistant candidate 正文中，提前制造了消息结束边界。这与输入合同所称“exactly two ordered messages”不一致，
也会破坏未来训练/runtime parity。

修复应覆盖 title、summary、handoff 和 prior publication 自由文本。默认采用可逆、稳定的 control-token-safe 编码，使所有产品合法文本仍可评价；
若执行者有证据证明显式 typed failure 更契合产品，可采用该路线，但必须写入输入合同。不能只忽略多出的 special ID。修复后增加真实 tokenizer
回归，并升级实际 render/input-template identity。

### 2. 高：`input_template` identity 没有绑定真实 model-visible render

`runner.py:724-729` 的 `ScoringIdentity.input_template.revision` 只散列描述性
`render-contract-v2.json`。实际 marker、字段标签、换行、JSON 序列化和消息字节由 `render.py:45-145` 决定，并不在该 JSON 中。
measurement freeze 虽另有 Python implementation manifest，但 Plan 055、未来训练和 runtime 交换的 typed scoring identity 不能据此识别 byte-level
render。

应让 input-template revision 绑定完整有效 render 组成，或绑定一个小型 exact rendered/tokenized golden；不需要建设通用模板平台。v2 到 v3
只改变 measurement slice，却把 scalar definition 从 `...-fp32-v2` 改成 `...-fp32-v3`，而计划又明确 scalar 未变。后续版本应让
result/freeze schema 独立升级，未变化的 scalar definition 保持同一身份；因第 1 项改变 render 时只升级 input-template 部分。

### 3. 高：Python “strict loader”不是 Rust `PublicationPacket::validate()` 的等价门

`contract.py:347-435` 只检查文本类型、字段和枚举，没有执行产品的机械不变量。审查用临时副本分别注入空 title、9,000-byte summary、
超过 4 条 prior history、`present.visible_count=0`，四项均被 `load_sample_corpus()` 接受；Rust 权威合同会在
`publication-critic/src/contract.rs:18-29` 与 `packet.rs:193-199,231-246,301-323,424-443` 拒绝这些 packet。

当前 24 条样本另经 Rust typed test 验证，所以 v3 分数没有因此失真；但设施本身会让未来数据接受产品非法 packet。应使用现有
`product-packet-limits-v1.json` 补齐非空、scalar/byte cap、history 上限、Fact count 和 partial omission 不变量，或采用同样窄的 Rust
validator seam，并补相应反例测试；不要新增第二套 schema 或状态系统。

### 4. 中：校准身份、延迟口径和 tracked 机器结果需要窄收口

- `runner.py:820-840` 校准绑定只核 schema/run/model/input/threshold；测试 `test_publication_critic_eval.py:505-557` 的最小伪 artifact
  不含 environment、scalar smoke、scoring 或 implementation identity 也能通过。实际 ignored calibration 确为 CPU FP32 且通过 parity，
  因而这是设施缺口，不是当前结果造假。验证器应窄校验已有 environment/scalar/implementation 字段，避免 BF16 或漂移实现的 threshold
  被装入 FP32 freeze。
- `backend.py:128-146` 把 batch wall time 除以 batch size 后写入每个 row；这代表 amortized compute time，不是单请求 latency。
  v3 JSON 已写明 `per_batch_wall_divided_by_batch_size`，Markdown 应采用同一说法，并同时报告实际 batch latency 或保留足以重算的 batch
  elapsed/size。
- v3 Markdown 使用的 calibration parity、16k context smoke、watchdog memory/swap/stop reason 只存在 ignored archive。下一正式机器结果应附
  8 条紧凑 calibration 投影/threshold derivation、context smoke 和 body-free watchdog summary，足以支撑报告即可；不要求数据库、签名、
  provenance 链或逐步骤 receipt。

### 5. 中：新增 Rust 测试资源没有关闭 Bazel runfiles

`publication_review.rs:909-913,1238-1274` 读取 freeze、sample 和 limit 资源；后两处直接使用 `CARGO_MANIFEST_DIR`，与
`multidev/AGENTS.md` 的测试资源规则不符。`core/BUILD.bazel:33-47` 也没有把这三个 `eval/` 文件加入 `test_data_extra`。
因此 Cargo focused pass 不能保证同一 unit target 在 Bazel 下取得资源。应统一使用 `codex_utils_cargo_bin::find_resource!` 并声明精确 test
data；无需为此运行全 workspace 或 CI。

## 已确认通过的部分

- 工作树审查前位于 `61edaff` 且 clean；主工作区和 Plan 058 工作树均无未提交修改。本任务未合并、推送、rebase 或改名。
- 变更在 `multidev/` 只增加 `#[cfg(test)]` parity/identity 检查和 golden；未改变 Plan 057 review cycle、packet builder、Team State mutation
  或 Plan 055 scorer/service 产品行为。
- packet/annotation 物理分离，renderer API 不接收 label、slice、pair 或 reviewer metadata；未发现监督泄漏。
- 本轮重新运行 25 个 Publication Critic Python focused tests，全部通过；没有重跑全 workspace、模型推理、Docker、GPU、真实 API 或训练。
- 使用冻结本地 tokenizer 离线重跑 26-row census：min/median/max 为 `564/589.5/13417`，唯一 overflow case 整条丢弃 4 个 oldest
  history，token bucket 总和 `29478` 与 input token 总和完全一致。
- 从 tracked v3 rows 独立重算 accuracy/balanced accuracy `0.6875`、ROC AUC `0.765625`、FP/FR `3/2`、pair `7/8`；tracked
  JSON 等于 ignored raw result 加其 SHA 字段，raw SHA 为
  `6fbee12edb217a599a7995488d7208d4fe628df759c31f3c8b56d46229561bd1`。
- watchdog summary 证实 `run_rc=0`、`stop_reason=none`、memory peak `9842864128`、swap peak `14467072`；报告的
  process peak RSS `10658586624` 与机器结果一致。Engineering GO、M3-B1a 数据工作 GO、unfinetuned direct-product NO-GO 的分层判断合理。

## 审查者决策与复验边界

1. 在当前 054 worktree 窄修上述五项；不更换模型、不启动训练、不触碰 Plan 058、顶层 WBS、Plan 057 产品行为或 M3-C1。
2. 输入/render identity 修正后发布新的 freeze/result 版本，并按计划从新 clean freeze 完整重跑一次 calibration/measurement；保留 v1-v3
   为 superseded 历史。无需改建共享结果索引，也不要求给 v1/v2 JSON 增加审计 sidecar。
3. 只跑新的 exact-tokenizer 回归、25 个 focused Python tests、受影响的 Rust typed resource/parity test，以及一次受 watchdog 约束的正式模型
   重跑；不跑全 workspace、GPU、Docker 或 CI。若执行者能以更强证据证明某项不需重跑，可采用等价更优策略并在摘要中说明。
4. 修复不得通过缩小合法 packet 范围、放宽 parity、删除错误样本或按质量结果调整 threshold；现有 go/no-go 口径保持不变。
