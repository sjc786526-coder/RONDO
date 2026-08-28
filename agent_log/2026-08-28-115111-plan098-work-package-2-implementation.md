# Plan 098 工作包二实施日志

## 实质交付

- 数据设计与生成配置绑定工作包一 accepted identity：implementation commit
  `55342bdb11b09c11b589fd398717f7712fca012c`、`rondo-publication-critic-task@v2`、合同 SHA-256
  `3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560`。设计锁 SHA-256 为
  `60ebfd8c650b48f60be9e665d12a9f80258d0eb39e6aea60455fc531f8a6eb72`。
- 新增轻量 module/review 合同、严格 validator 和 transactional finalizer；模块配额、split/target schedule、完整五头标签、Boundary、
  soft-only invariance、quoted continuity basis、tag/coverage、重复、明显捷径、长度分布、review hash、renderer、manifest 与 consumer
  均 fail-closed。正式设计和配置按原始字节进入 release，避免重新序列化导致身份分叉。
- 冻结新 revision `training/publication-critic-v9/`：216 candidates、96 pairs；train/validation/test 物理拆分为
  162/27/27 candidates 与 72/12/12 pairs。训练 consumer 只打开 train，validation 为独立显式入口，不提供 test loader；另有一个只含
  train、覆盖三个模块闭合 group 的 smoke bundle。
- 正式 release manifest SHA-256 为 `756d7ea4c53673a447860fb4cfc245a98f5c15383569f137b1e07eacf7f90118`，
  release identity SHA-256 为 `08d854c3b848d2135915c8908d74b27d72000128b8b29e93bab0866564f68a0e`，体积约 392 KiB。

## 来源、模块与盲审

- 只读取 v8 已物理排除 unseen 的 `train-only-smoke-bundle.json` 安全投影；其 6 条 v1 scalar-era candidate/pair 无法无歧义提供完整五头
  v2 监督，因此正式直接复用为零。mixed v8 主体、旧 validation、旧 unseen 和旧 ignored namespace 均未读取，v7/v8 未改。
- 三个 `fork_turns="none"` 干净负责人各自生成并只整改一个 24-group 模块；三个另外的干净盲审员逐块一一审查，主执行者只做合同、机械
  验证、全局覆盖与冻结：
  - `hard-boundaries`：module `a150c56213c0c870e70c42bff8550f6e01ee736475a16da0a258bc310e4b2551`，review
    `1dc416bec1787af3502a9199b425208a5db7cada1522948ff7399c95a936476b`；首轮 9 findings、复验 2 findings，最终 0。
  - `continuity-context`：module `59b572814e91d13a3cbf6a7555bd6cb1f5990411443227c23ce52a586057dd1d`，review
    `c82af82461bc22bc2dd78d86dfbf0bbb6bb4719ff9ba928ecb2a29408929da0c`；首轮 3 findings、复验 3 findings，最终 0。
  - `soft-combinations`：module `f7ff59b9470a4484e6ddd7d21e0f27146ffcd6b4f35a6e49e461c1c8c2c18f78`，review
    `8b3f7d911f969279d4d434c8c11a3140202b6938df6d871608f94eb9854f42b0`；首轮 5 findings、复验 2 findings，最终 0。
- 整改实际闭合了 continuity 将“有具体进度但无 handoff”误标 FAIL、Boundary 非目标事实漂移、consistency/uncertainty 混入、soft-only
  事实强度漂移、soft tag 机械分配、scope 不足以及跨组模板/自我批注式监督捷径；每轮只回原模块负责人并由原盲审员绑定新 SHA 复验。

## 覆盖与验证

- 正式 coverage：PASS/REWRITE 为 96/120；五维 FAIL 为 52/42/38/40/32；continuity PASS/FAIL/N/A 为 94/38/84；
  Boundary 各维 15/14/14/14/15，三个 split 各有每维 Boundary；soft-only invariance 为 train/validation/test 18/3/3。
- 三类 public context 各 72 candidates；四种 hard/soft 组合为 48/48/60/60；single/multi、real-shaped anchor、visible conflict 为
  72/48/26/23。精确重复 0、跨组近重复 0（阈值 0.94）、明显模型可见元数据捷径 0，所有 split 的 PASS/REWRITE 长度范围重叠。
- 实际模块先在 ignored commissioning 目录完整通过 finalizer、renderer、manifest、train/validation consumer 和 smoke；随后从不存在的
  tracked 目标目录运行一次干净正式 finalizer，未拼接调试片段。
- successor contract/release 与旧 contract/training-data/identity 定向回归合计 `46/46` passed，0 failure/error/skip；Python compile、
  JSON 解析、identity/hash、Git diff 与历史 tree 门在提交前复核。
- 冻结 v8 tree 保持 `63981483baa00c671987d4b82887909fcc320690`，v7 tree 保持
  `435c06fba3196bee21d59d88b9e6d6b1a1e1999a`。未运行 Rust/Cargo、真实模型、GPU、RunPod、Docker、付费 API 或产品动作。

## ignored 资产

- 实际创建 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/`，当前约 632 KiB：`modules/` 保存三份负责人源模块，
  `reviews/` 保存三份最终盲审记录，`commissioning/actual-release-check/` 保存正式冻结前的完整实际链副本；测试临时目录已自动清除。
- 该 namespace 在最终验收期间应保留，便于审查 module/review 原文和重现冻结；Plan 098 最终验收并完成后可整体清理，tracked v9 release
  自包含训练所需输入、标签、pair、split、manifest、coverage、smoke 与模块冻结哈希。未修改或清理其他任务 namespace。
