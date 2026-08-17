# Plan 041 独立验收审查（2026-08-16）

## 结论

- **验收暂不通过，需窄修后复验。** Local M4 的正式评测链路、结果和人工决定均成立，核心任务目标已实现；
  但当前提交仍有一项权威文档同步错误、一项匿名扫描缺口和一处结果表述失真，尚不能作为最终交付直接合入。
- 这些问题均不改变已完成的 146 条盲评，不需要重判、重打包、重跑本地模型或扩大测试设施。
- 审查基线：041 提交 `8fe4e71de32e7bc39026892a2c4936a8f0fa5d79`；审查时 main 与 origin/main 均为
  `7050121a7998d2b3b444dfd45641ba23135be22a`。写入本报告前，041、主工作区和其他 worktree 均干净；041 未合并、
  未推送。

## 必须整改

1. **顶层权威文档没有保留最新 Multi M-2 状态。** `doc/WBS.md` 页首已写 M-2 完成、M-3 为下一阶段，
   但第 28、82—83、108、111、183 行仍写 M-2 待实施，且第 190 行仍把 Local M4 写成未完成。
   当前 main 已记录 M-2 完成；041 与 main 对 `doc/WBS.md`、`doc/WBS-COMPLETED.md` 的三方合并也产生真实冲突。
   执行者须基于届时最新 main 保留 M-2 完成历史和 M-3 当前状态，再叠加 Local M4 事实；不得用 041 的旧基线
   覆盖 Multi 进展。
2. **匿名扫描漏掉直接 side 身份措辞。** `cross_eval.py` 当前会放过 `the local decision`、
   `the fine-tuned model`、`the unfine-tuned baseline` 等明确身份提示。应只扩充必要的直接身份模式并补既有
   side-leak 回归，继续允许 `local git history` 等普通小写技术英语。本次四个正式 judge package 对这些直接
   身份模式的只计数扫描为 0 命中，因此现有盲评有效，无需重判。
3. **“每一项指标都改善”不符合实际计数。** `doc/WBS.md` 第 27 行和 tracked 结论锁的 decision rationale
   使用了这一概括；实际结构化可用性和漏放有持平项，synthetic 的 `sole_preferred` 也不是单调改善。
   应改成准确列举主要结果，例如教师/裁判一致、误拦、理由弱项和总体未偏好显著改善，漏放保持为 0；
   `keep_as_experiment` 选择及依据不变。若结论锁字节改变，同时更新引用它的 SHA-256。

## 已通过的核对

- synthetic 为 65 + 65 条、390 行三方输入；holdout 为 11 + 5 条裁判结果、16 条来源和 48 行三方终态。
  两个 partition 的 cohort、seed、mapping、结果与 aggregate 独立，位置计数每个候选位最多相差 1，未混合分母。
- tracked 结论锁 SHA-256 为 `2c8af519…cd3e`；锁内列出的两个 aggregate、四个 package、四个 judge result、
  synthetic/holdout 三方输入、holdout source 和 pair receipt 哈希均与私有文件一致。
- synthetic 冻结 v1 prompt/result/summary 相对任务基线无改动；实际请求、结果和锁中的 prompt/schema 哈希一致。
  holdout-only v2 正确表达两个 `structured_output_failure` 为 `no_decision/not_applicable`，禁止进入偏好，未将其
  当作 deny；其模板哈希同样与请求和锁一致。
- synthetic、holdout 和 Plan 037 的 pair receipt 逐字节一致，SHA-256 均为 `1d57def1…129c`。
- 结果计数与私有 aggregate、tracked 锁和执行日志一致：synthetic 未微调/微调教师一致为 104/130、130/130，
  误拦为 26、0；holdout 为 8/14（覆盖 14/16）、15/16，误拦为 6、1；两分区漏放均为 0。
- 复跑直接相关 7 个 unittest 模块，**253/253 通过**。未运行全量 eval、Cargo、Docker、CI 或 PR，符合本任务边界。
- 两个私有目录及嵌套目录为 0700、普通文件为 0600。当前无 `llama-server`、端口 18041 无监听、无 GPU compute
  process，GPU 使用约 1608 MiB；Windows `C:` 实际余量约 188.6 GiB。
- `mydev/`、`multidev/`、生产默认、provider、launcher、部署开关和 `eval/results/runs.jsonl` 均未修改。

## 代用户作出的审查决定

1. **维持 `keep_as_experiment`，不改为采用或停止。** 微调结果足以证明该工件值得保留，但同生成器 synthetic
   和全 allow 的 16 条 holdout 不能证明安全放行能力；不启动生产启用、默认切换或部署。
2. **接受 holdout-only terminal-carrying v2 作为本次必要的格式兼容。** 它完整保留 16/16，未改变判据、样本或
   v1 synthetic 合同；不因此重开裁判。
3. **不修改 10 条理由含臆造细节的冻结 Sol 标签，不重新裁判。** 继续把它们作为已知教师理由缺陷记录；其 outcome
   仍有支持，不以事后改标签改善结果。
4. **整改范围限定为上述三项。** 同步最新 main 的权威文档、窄修匿名扫描并补回归、纠正表述及关联哈希后，复跑
   直接相关测试和 `git diff --check` 即可申请复验；无需模型、Cargo、Docker 或全量 eval。

## 当前状态

- **验收：不通过（待整改复验）。**
- **任务目标：完成。** 正式 M4 横评与人工决定已实现，质量结果有效；只是当前分支的交付正确性尚未收口。
