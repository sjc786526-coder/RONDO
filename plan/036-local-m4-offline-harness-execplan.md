# Plan 036：Local M4 本地离线三方盲评准备设施

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 Local M4 的离线准备设施；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

为未来 L6 产出的本地模型建立版本化、可机器校验的 Local M4 三方横评准备设施：冻结全部 130 条合成
validation 主体，严格导入 `sol-static`、`local-static`、`local-ft-static` 的同输入输出，生成匿名且位置平衡
的 Opus 5 裁判包，严格导入裁判结果并私有解盲、按 synthetic / holdout 分开聚合。

本任务不运行 L6、模型推理或正式 M4；真实主体只完成无模型 preflight，终态必须是
`waiting_for_l6_outputs`。

### 完成/验收标准

- [x] body-free cohort manifest 精确绑定 tracked `validation.jsonl` 全部 130 条、Plan 034 manifest/hash、
      sample/payload/target/group 身份、两批分配与合同版本；训练样本不进入 cohort。
- [x] 130 条由确定性算法分成两批，每批不超过 100；同一 source `group_id` 或近重复 `split_group_id` 均不跨批，
      合计无重无漏。
- [x] 三方导入严格拒绝缺 side、重复/未知 side、样本或 payload/prompt/schema 漂移、输入正文或消息边界漂移，
      并要求两种 Local 工件来自同一 L6 成对底模谱系、runtime、模板、采样和输出合同。
- [x] `sol-static` 只接受 validation 内已冻结的 point-in-time Sol target；Plan 033 GGUF baseline 不能冒充
      L6 成对未微调工件。
- [x] 冻结裁判 prompt、结果 schema 与 blinding 合同；裁判包只含同一审批输入和匿名候选，不含 side、模型路径
      或可推断身份字段，同批每个 side 在三个位置的出现次数差不超过 1。
- [x] seed、匿名映射、三方正文、逐条裁判结果和解盲结果只写任务专用 ignored 私有目录；目录 0700、普通文件
      0600。tracked 只保留算法/合同、必要哈希和允许的聚合投影。
- [x] 裁判结果严格绑定批次、样本、cohort、裁判 prompt、裁判模型标识和日期后才允许解盲；聚合只报告事实，
      不自动作出采用/保留/停止决定，也不新增机械质量阈值。
- [x] holdout 只建立独立私有导入和批次级聚合投影合同；本任务不读取正文、不物化真实 anchor 包，synthetic 与
      holdout 不混算，tracked holdout 投影不含逐条身份、正文、输出、理由或映射。
- [x] 用完全合成的 5—10 条 fixture 完成导入、匿名打包、模拟裁判导入、解盲、聚合 round-trip，并覆盖用户指定
      的主要负向合同；直接相关测试 0 skip 通过。
- [x] 对真实 tracked validation 执行无模型 preflight，复核 cohort、批次、分组与哈希稳定，报告
      `waiting_for_l6_outputs`；通过 `git diff --check` 与 tracked 敏感信息/side 泄漏检查。
- [x] 精炼同步权威 WBS、完成历史、数据布局和一份 agent log；任务分支形成少量清晰本地提交，停在未合并、
      未推送、待独立验收状态。

## 2. 范围

### 允许修改

- `plan/036-local-m4-offline-harness-execplan.md` 的“当前状态”和“关键决策记录”。
- `eval/rondo_eval/local_approval/` 内直接相关的 stdlib-only 轻量实现。
- `eval/templates/cross-eval-judge/` 的版本化 prompt、schema 和 blinding/holdout 合同。
- `eval/tests/` 的直接相关合成 fixture 测试。
- `eval/locks/` 下不含正文的 synthetic cohort manifest。
- `doc/eval-data-layout.md`、`doc/WBS.md`、`doc/WBS/local-approval-model.md`、
  `doc/WBS-COMPLETED.md` 与一份 `agent_log/`。
- 主工作区任务专用 ignored `eval-data/local-approval/m4/plan036-preflight-v1/`，仅保存本次无模型 preflight
  收据，保持 0700/0600。

### 不允许修改

- `training/local-approval-synthetic-v1/` 冻结数据、Plan 032/033/034/035 历史产物、既有 shadow 结果或
  `eval/results/runs.jsonl`。
- `mydev/`、`multidev/`、runtime、模型配置、GGUF/权重、static payload v3 或决策 schema v1 核心语义。
- L6 训练方案或路线、Local M4 的人判定结论、质量阈值、CI/PR、上游基线。
- 主工作区 tracked 文件、其他 worktree 与两份既有未跟踪 `doc/research/RONDO Multi*.md`。

### 不允许读取/查看

- Plan 032 私有 holdout 正文、逐条身份或本地模型权重。
- `.env.local`、`rondo.local.toml`、无关私有数据。

## 3. 硬约束

1. 全过程不联网，不调用 Sol/Opus/API，不加载本地模型，不推理、训练、转换或量化，不运行 Cargo、Docker、
   重型测试或完整测评，不新增或下载依赖。
2. synthetic 正式主体只能是冻结 validation 的全部 130 条；不得混入 train、抽样或按结果选择。cohort 验证必须
   从 tracked 数据重算所有身份、分组、文件哈希和两批覆盖。
3. 三方的 canonical approval input 必须逐字节相同；输入正文、消息顺序/边界、policy/instructions、payload v3
   和输出 schema 任一漂移均 fail-closed。Sol target 是蒸馏目标，不冒充人工 ground truth。
4. `local-static` / `local-ft-static` 必须声明同一 L6 pair、base lineage、runtime、chat template、sampling 和
   output contract；未微调侧 provenance 只能是 L6 成对工件，不能接受 Plan 033 历史 baseline。
5. 裁判包不得携带 side、运行/工件 metadata、模型路径或已知模型身份；候选位置使用私有 seed 的版本化算法
   随机化并逐批平衡。真实 seed 与映射绝不进入 tracked 文件、终端或日志。
6. 导入裁判结果前必须验证集合完整、唯一和所有身份；解盲/聚合只消费同批私有 package + mapping + results。
   任何 prompt/model/date/batch/sample/hash 漂移均拒绝。
7. synthetic / holdout 的 cohort、结果、分母和摘要始终分开；聚合入口拒绝混合分区。holdout 的公共投影只能是
   批次级摘要，不含逐条数据。
8. 不以 fake round-trip 冒充真实横评，不以 cohort preflight 冒充模型质量，不为绿色结果填充 fake Local 输出、
   弱化校验或把 skip/未运行写成通过。
9. 所有写入采用明确目标、fail-closed 和 0700/0600 私有权限；不覆盖既有文件、不跟随符号链接。
10. 只跑 directly related 的 Python/pure 测试与静态检查；不扩大为全量 eval。

## 4. 软性建议

- 在现有 `rondo_eval.local_approval` 包新增单一小模块和 CLI，复用 Plan 034 的 canonical JSON、static-v3 与
  decision-v1 校验语义，不建立数据库或第二套测评工程。
- tracked cohort 使用逐条 body-free identity；私有三方 import row 才携带完整 approval input 和 decision。
- 位置平衡使用按 batch 私有 seed 派生、分组三元 Latin-square permutation 的轻量算法；无需统计框架。
- 结果聚合只报告 preferred/sole-preferred/tied、候选 finding 和 decision outcome 等计数，不推导机械结论。

## 5. 当前状态

### 已完成

- 已核对 `main` / `origin/main` 均为 `230f7a65851565beff44e9763cec7deaf60907e8`；主工作区仅有两份用户
  未跟踪研究文档，其他 worktree 均保持不动。
- 已确认既有 `036-local-m4-offline-harness` worktree/分支干净，残留锁记录对应进程已不存在，接管时 HEAD
  仍为基线提交。
- 已阅读根规则、README、WBS、方向 2 WBS、数据布局、Plan 034/035、冻结 validation manifest/schema 与
  相关 eval 实现/测试。
- tracked validation 确认为 130 条、26 个 `split_group_id`，每组 5 条；130 个 sample/payload identity 均唯一。
- 已冻结 body-free cohort：精确覆盖 130 条 validation，source / near-duplicate 联合闭包确定性分为 65 / 65，
  cohort manifest SHA-256 为 `9dd901fff3df072ed65ff3962d1e4524255a5a42a3f810903d191457cb494b95`。
- 已完成 L6 pair receipt + 三方导入、匿名平衡打包、严格裁判结果导入、全批次验证后私有解盲、分区聚合及
  holdout 批次级白名单投影合同；正式执行目录限定为 ignored `eval-data/cross-eval/<execution_id>/`。
- 6 条完全合成 fixture 已完成含 0600 JSONL/JSON 落盘重载的端到端 round-trip；focused unittest 27/27
  通过、0 skip，`py_compile` 与 `git diff --check` 通过。
- 真实 no-model preflight 复算为 130 条、两批 65 / 65、26 个 source group、26 个 split group，状态为
  `waiting_for_l6_outputs`；没有创建 fake Local 输出，也未开始正式 M4。

### 当前工作

- 已完成。

### 本任务剩余步骤

- 无。

### 阻塞项

- 无。缺少未来 L6 输出是预期等待状态，不阻塞本任务交付。

### 当前验收状态

- 验收项全部满足；focused unittest 27/27 通过、0 skip，真实 preflight 为 `waiting_for_l6_outputs`，
  `git diff --check` 通过。没有执行模型、训练、网络、Cargo、Docker、真实 holdout 或正式裁判。

### 交接边界

- 本任务完成后冻结本计划；方向 2 下一产品工作仍由 WBS 指向 L6，正式 M4 与人判定保持未完成。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | cohort manifest 按逐条 sample/payload/target/group identity 冻结，但不保存 input/target 正文 | 可完整复算又不复制正文 | tracked cohort | 已采纳 |
| 002 | 三方导入使用一个完整 JSONL 集合，只有三 side 对每个 sample 各一条时才接受 | 直接拒绝缺失、重复与部分导入歧义 | 私有导入 | 已采纳 |
| 003 | Local pair 必须携带 canonical 私有 L6 pair receipt；receipt 内容哈希绑定两种输出的不同工件身份、训练 receipt、base lineage 与五项共同运行合同 | 只有输出自报字段不足以阻止 Plan 033 baseline 改标签冒充 | Local 工件合同 | 已采纳 |
| 004 | 每批由私有 seed 与版本化 SHA-256 label 排序派生三元 Latin-square block，不依赖语言运行时 RNG | 保持匿名随机性、跨运行时稳定，并机械保证每 side 每位置差不超过 1 | 盲评算法 | 已采纳 |
| 005 | holdout 与 synthetic 共用严格私有 row 语义，但使用独立 partition/batch 合同；公共投影一律去除逐条信息 | 防止混算与 holdout 泄漏 | holdout 边界 | 已采纳 |
