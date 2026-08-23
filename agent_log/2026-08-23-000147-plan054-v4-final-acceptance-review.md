# Plan 054 / M3-A2 v4 final independent acceptance review

审查对象：`worktree-054-publication-critic-eval-baseline@1ed77b257723937376d259649d0e7a272a801b35`，重点复验上一轮
`2026-08-22-224024-plan054-independent-acceptance-review.md` 的五项 finding 及整改造成的局部回归。

## 结论

- **验收通过**：五项 finding 均已在原有 Publication Critic 专用设施内正确关闭，未发现新的阻塞性功能或合同回归。
- **任务目标完成**：Plan 054 已形成可复跑的输入/评价合同、真实 tokenizer 与 16k 模型证据、代表性基座结果和 M3-B1a 交接结论。
- v4 是当前权威结果；v1-v3 继续作为 superseded 历史 attempt。验收通过不改变“未微调模型不得直接进入产品”的 NO-GO。

## 定向复验结果

1. **输入与 tokenizer**：动态正文采用可逆 JSON `\u003c` 编码；冻结 tokenizer 对 title、candidate summary/handoff、prior
   summary/handoff 五处注入 `<|im_end|>` 与 `<think>` 后，registered-token 序列仍严格等于
   `151644,151645,151644,151667,151668,151645`，每条输入只有四个消息 envelope special token。26-row census 重新得到
   `564/589.5/13417` 的 min/median/max、总 token `29478`，唯一 overflow case 整条丢弃四个 oldest history。
2. **产品 packet parity**：Python loader 已覆盖 Rust 的 required text、Unicode scalar/UTF-8 byte、u64/u32、history、partial omission
   和 visible fact count 机械约束；31 个 focused Python tests 全部通过，前次可接受空标题、超长 summary、五条 history 和零 visible
   count 的路径均已有反例门禁。
3. **identity**：input-template revision 绑定 render contract、rubric、实际 `render.py`、冻结 `chat_template.jinja` 和
   `added_tokens.json`；freeze/result schema 升级未再改名未变化的 FP32 scalar definition，Rust typed identity 与 v4 freeze 一致。
4. **calibration、结果和资源**：只读 verifier 严格接受正式 calibration 与两份 watchdog summary。独立重算确认：freeze SHA
   `2a8081d3700f4209f5ac3cd7dabb7f6d31d0cb0b0ea0e9e8c639c8f10dbebfeb`，calibration SHA
   `14062beac6d8eee3d48665a76e9b9dcbf73182abbe999ef5aa08bc69412e58d1`，raw SHA
   `a70cbdf0bf24f5fccb94be1b5711922cfbd375cb9d5437db93796dc579254ca1`，tracked SHA
   `26534ab028dc951acd18251926dfdeaa61dd4674b477b074618a7eb891e97340`。tracked JSON 精确等于 raw 加 raw SHA 与最终
   watchdog 投影；threshold 从 8 条 calibration row 重算仍为 `0.9350569011196121`。
5. **质量与 timing**：16/16 valid、零 typed failure，accuracy / balanced accuracy `0.6875`，ROC AUC `0.765625`，atomic pair
   `7/8`，measurement parity 最大 delta `4.523673587608634e-06`。四个 standard batch 的 wall P50 为 `18.60s`，amortized
   compute P50 为 `4.65s`，机器结果与 Markdown 均未再把后者称为单请求 latency。measurement watchdog peak memory
   `8496590848` bytes、swap `0`、stop/cleanup `none`。
6. **Rust/Bazel resource**：三份资源均改用 `find_resource!`，`core/BUILD.bazel` 通过 `@eval` 精确声明 test data；相对路径在 Cargo
   下落到仓库根 `eval/`，在 Bazel runfiles 下规范化为 external `eval/...`。现场无 Bazel，因此没有为本次审查安装或运行 Bazel；执行者
   已运行受影响的三个 Cargo/nextest tests，本轮不重复重型 Rust 构建。

## 审查者代用户作出的决策

- 接受现有可逆 control-token-safe render；不再要求额外拒绝合法正文、golden 平台或通用模板设施。
- 接受 Bazel 的静态 runfiles 闭合与 focused Cargo 证据；不为单一资源检查安装 Bazel，也不扩大到全 workspace、CI、Docker、GPU、
  真实 API、训练或再次真实模型推理。
- 接受当前分层结论：exact 本地工程路径 **GO**，M3-B1a 数据建设 **GO**，未微调 direct-product **NO-GO**；M3-C1 继续等待
  M3-B1c 至少一个训练候选。无需用户追加技术决策。

## 交付状态

审查开始时 054、主工作区与 Plan 058 工作树均 clean；054 未合并、未推送、未 rebase、未改名。最终验收报告作为本次审查唯一新增
文件留在 054 worktree。后续只需用户批准后由主线整合者按届时 `main` 窄同步、合并并推送；本报告不授权这些动作。
