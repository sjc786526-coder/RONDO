# Plan 034 独立验收审查

日期：2026-08-15 ｜ 审查对象：`034-l5b-synthetic-training-dataset@9b8990a`

## 结论

**验收不通过；任务目标完成。**

600 条合成训练数据、train/validation 划分、严格 static-v3/decision-v1 校验、去重、holdout 近重复排除、
tracked 哈希和私有批次均可独立重算，未发现标签集合、split 或最终数据正文需要作废的问题。L5b 的核心目标已经
实现，现有数据无需重新生成。

但交付实现把来自私有教师批次的真实 source marker 直接硬编码进 tracked Python 源码，其中包含 holdout 正文片段。
这是 Plan 034 明确禁止的 tracked 泄漏，合并前必须在现有 worktree 做一次窄修。修复不需要 Sol、API、训练、
本地模型或重做 600 条数据；移除私有字面量并保持现有最终数据与哈希不变后，复跑 focused tests 和 release verify
即可交回复验。

## Finding

### 1. [中，阻断] tracked validator 为防泄漏反而写入了真实 seed/holdout marker

`eval/rondo_eval/local_approval/synthetic_training.py:109-115` 的 `_SOURCE_MARKERS` 直接包含一个真实长标识片段、
两个真实专有名词片段及其他教师批次文本，并在 `:561-562` 用它们扫描候选。报告不重复这些私有字面值，避免
审查日志再次固化同一问题。

独立核验确认：列表中的五个 marker 均出现在私有 Plan 032 教师批次，也都出现在 holdout canonical payload；
其中上述三个值在基线 `main@f98431e` 的 tracked 文件中不存在，是 Plan 034 提交首次引入。即使它们只用于拒绝
候选，把真实 holdout 片段写进 Git 本身已经违反本计划“holdout 不进入 Git/日志/终端”和真实参考始终私有的边界。

这不是最终数据污染：独立从私有 manifest 提取 353 个真实 identity/path/hash 值扫描两份训练 JSONL，命中为 0；
600 条 payload 也没有与真实 payload SHA 重合。按实现的同一 5-gram 规则复算，相对 seed 与 holdout 的最大分数
都为 0.202128，在 0.72 阈值下命中均为 0。因此应保留现有数据，只窄修 tracked literal。

可接受的整改边界：删除这些私有字面量，或改成只在私有批次内存中派生比较、绝不把值写入 tracked 文件的等强
轻量方案。无需建设通用 DLP/审计设施，也无需修改 prompt/schema、split、manifest、数据卡或 600 条 JSONL。
整改后应确认 tracked tree 不再新增真实 seed/holdout 片段，90 项 focused 测试和正式 `verify` 仍通过，三个发布
SHA-256 保持不变。

## 独立验证

- 分支进入审查时 clean，HEAD 为 `9b8990a7789ebdf7a1f754497aba1b5c959ace57`；相对 `f98431e` 只修改
  Plan 034 允许范围，未碰 `mydev/`、`multidev/`、历史 results 或 Plan 032/033 产物。
- 独立运行 `test_contracts_and_evidence`、`test_teacher_labels`、`test_shadow_replay`、
  `test_synthetic_training`：**90/90 通过**。
- 正式 release verify 从私有候选和冻结教师批次重算成功：600 条，train 470 / validation 130，allow 240 /
  deny 360，六类分布 180 / 100 / 120 / 70 / 65 / 65，holdout 排除 0。
- train / validation / manifest SHA-256 分别精确匹配
  `1e66c06e…c110a` / `cbab8084…8dd2` / `dbf5fffe…7190`；私有目录为 0700，六个私有文件均为 0600，
  tracked/private 树未见符号链接，`git diff --check` 通过。
- 独立统计确认 600 条 payload 唯一、120 个 split group 无跨 split；六类代表样本的 action/outcome 总体语义合理，
  未发现明显反向标签。
- 未执行或发现 Hugging Face/Hub 登录、上传、Job、训练、权重下载、本地模型、Docker、Cargo、API、CI 或 PR。
  主工作区两个既有未跟踪研究文档与并行的 035 worktree 未触碰。

## 非阻断限制

当前数据是明确披露的轻量 template-expanded v1：真实 seed 的 input token 为 5,311—11,496，canonical payload
P50 为 34,707 bytes；合成 payload P50 仅 1,991 bytes，各类别 evidence 文本只有 5—10 个模板。少数 rationale
比输入 evidence 写得更具体。这会限制对长证据检索和复杂现场的代表性，但不构成 Plan 034 的正确性门槛：数据卡已经
声明其轻量、command-approval 与 template-expanded 边界，本任务也不承诺训练收益。

本轮不因此重生成或扩大数据工程。L6 应把它作为首版训练输入，在既定 dry-run/微调后对比中验证实际收益，不得把
`ready_for_l6` 解读为已经证明数据覆盖真实分布；若 L6 的实测表明该限制成为主要瓶颈，再另行决定是否生成 v2。

## 代用户作出的决定

1. **保留并接受现有 600 条数据、split 和三个发布哈希。** blocker 位于 tracked validator，不在数据正文；
   不重新调用 Sol、不修改 prompt/schema、不重生成候选。
2. **要求合并前窄修 `_SOURCE_MARKERS` 泄漏。** 只移除 tracked 私有字面量或改为 private-runtime 比较，
   不扩建通用扫描、签名、可信链或数据审计体系。
3. **接受短上下文与模板化为 v1 非阻断限制。** 不为追求更像真实 seed 而回开本批；L6 用真实训练后对比决定
   是否值得另做 v2，当前不提前增加数据规模。
4. **保留现有 WBS 的 L5b 完成与下一步 L6 方向，但本分支暂不可合并。** 窄修和复验通过后即可进入交付审批；
   L6 的数据外发、云 GPU、训练和权重仍需独立授权。
5. **不处理并行或未知对象。** 主工作区两个 `doc/research/RONDO Multi*.md`、035 worktree 和既有其他 worktree
   均保持不动。

## 当前状态

- 验收状态：**不通过**，存在一个窄的 tracked holdout marker 泄漏阻断项。
- 任务目标：**完成**，现有 600 条 L5b 数据有效且无需重生成。
- 交付状态：暂不合并、不推送；在同一 034 worktree 窄修后交回复验。
