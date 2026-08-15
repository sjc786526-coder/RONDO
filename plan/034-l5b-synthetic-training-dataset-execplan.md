# Plan 034：L5b 合成训练数据集与训练资产冻结

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 L5b；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

本任务由当前开发用 Codex `gpt-5.6-sol` 单独完成：同一执行者负责项目内实现、合成样本生成、校验、
文档与提交，不设置 Claude→Sol 或其他模型间交接，也不把 Sol 接成 `eval/` 的程序化 API 后端。

## 1. 目标

### 最终目标

只使用 Plan 032 冻结批次的 `seed` 分区作为真实场景参考，由当前 Sol 执行者生成一套规模适中、类别多样、
同时含 allow 与 deny 的合成审批训练数据。冻结最终使用的生成 prompt、样本合同、训练/验证划分、数据卡和
内容哈希，使下一独立 L6 工作包可以直接消费，而不必重做 L5b。

目标约 600 条；最终有效集应在 **400—800 条**之间，且本任务最多生成 800 个唯一候选样本。本任务只交付
训练数据资产，不运行训练，也不根据本任务结果判断模型是否可采用。

### 完成/验收标准

- 复核 Plan 032 私有批次及 tracked lock，确认 40 条冻结集合、seed 24 / holdout 16 与
  `ready_for_l3=true` 未漂移；不重新 prepare、重标或修改原批次。
- 最终数据覆盖明确安全、明确危险、边界模糊、证据不足、伪装成安全的危险动作、工具结果与请求不一致六类，
  且 allow/deny 均有实际样本；不要求机械等量。
- 每条样本均为合成审批场景，目标输出通过 `rondo_static_approval_v1` 等强校验；训练集与验证集非空、互斥，
  同源变体和近重复组不跨 split。
- 完成精确去重和本地 holdout 近重复排除。holdout 不进入 Sol 的合成上下文，逐条匹配信息不进入 Git、日志
  或终端输出。
- 数据卡与机器可读摘要记录 Sol 模型标识和日期、prompt/schema 版本及 SHA-256、样本和 split 数量、类别/
  outcome/长度分布、过滤统计、最终体积与数据文件 SHA-256。
- 最终正文按 WBS 阈值落点：总量不超过 100 MB 且单文件不超过 40 MB 时纳入 `training/`；否则正文留在
  git-ignored 私有区，Git 只保存数据卡、合同、摘要和哈希。真实参考、草稿、失败候选和逐条过滤映射始终私有。
- 直接相关的 pure/local 测试、真实批次校验和 Git/敏感边界检查通过；完成后精炼更新权威文档与一份日志，
  在本 worktree 分支提交，不合并、不推送。

## 2. 范围

### 允许修改

- 本计划的“当前状态”和“关键决策记录”。
- 新增顶层 `training/` 的最低必要数据资产结构，以及符合体积规则的最终训练/验证 JSONL。
- `eval/rondo_eval/local_approval/` 或现有 eval 架构内完成 seed 读取、合成批次保存、校验、去重、划分、
  holdout 近重复排除和摘要所需的轻量代码；具体文件和抽象由执行者决定。
- 版本化生成 prompt/schema、直接相关的 `eval/tests/` 合成 fixture 与测试；确有必要时可窄改 eval 依赖、
  lock 或现有命令入口，但不引入训练框架。
- 根 `AGENTS.md` 中 `training/` 的仓库职责、`doc/eval-data-layout.md` 的实际数据合同；任务全部完成后更新
  `doc/WBS.md`、`doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 和一份 `agent_log/`。
- 主工作区 `/home/sjc/desktop/RONDO/eval-data/` 下本任务专用的 git-ignored 私有目录，保存真实参考的
  受控投影、生成草稿/候选、过滤明细和必要的私有最终正文；目录 0700、普通文件 0600。

### 不允许修改

- Plan 032 私有批次及其 tracked lock、Plan 033 shadow 记录与 baseline、L4 指标或其他历史结果。
- canonical static payload v3、`STATIC_INSTRUCTIONS`、`rondo_static_approval_v1`、runtime/GGUF、资格 evidence、
  Guardian bridge、`mydev/` 或 `multidev/` 产品代码。
- `eval/results/runs.jsonl` 和 `eval/results/baselines/`；L5b 是数据资产，不是测评结果。
- L6/LoRA/QLoRA、训练 dry-run、Local M4、本地模型推理、Docker、Cargo、云 GPU、Hub/远端存储、权重下载、
  按量付费 API、CI、PR 或上游升级。
- 主工作区 tracked 文件和两个既有未跟踪 `doc/research/RONDO Multi*.md`。

### 不允许读取/查看

- 不打开、搜索、打印、复制、hash 或 source `.env.local`；不读取本地权重和无关私有数据。
- holdout 不得被 Sol 或人工当作合成参考查看。获授权的本地校验代码可在内存中读取冻结 holdout 做近重复排除，
  但只能输出聚合计数。

## 3. 硬约束

### 3.1 单一 Sol 执行者与数据来源

1. 当前执行者就是本任务唯一的开发与生成角色，模型固定为 `gpt-5.6-sol`。它可以直接读取获授权的 seed、
   生成候选并通过自己的文件工具保存，无需调用或等待另一个模型；产物记录实际模型标识与日期。
2. 真实参考只来自 `20260815-sol-teacher-labels-v1` 的 seed 分区。允许进入当前 Sol 上下文的只有生成所需的
   seed canonical 审批上下文和对应冻结教师目标；holdout、真实路径/运行身份、provider 私有字段和无关仓库
   内容不得进入合成上下文。
3. 不新增 Sol API client、批处理 API、密钥或第二个生成后端。最终候选仍须由本地严格 reader/validator
   校验，不能因为生成者和执行者相同就跳过数据合同。

### 3.2 数据合同与泄漏边界

1. 正式纳入最终数据集的样本必须绑定版本化 prompt/schema 和合成批次。允许在正式冻结前小规模试生成；
   若后来发现合同缺陷，可以新版本修复并重生成，但不得无痕改写已保存批次。
2. 最终有效集为 400—800 条、目标约 600 条，唯一候选总数不超过 800。六类场景和 allow/deny 均须覆盖；
   不预设更细配额，也不因喜欢或不喜欢某条判定而挑选重问。
3. 样本不得复制真实 `E_final`、真实身份或 provider 私有字段。目标 decision 必须是合规 allow/deny、非空
   rationale 与合规 risk tags；具体 JSONL 字段、消息渲染和 split 比例由执行者选择，只需能被 L6 确定性消费。
4. 去重、split 和 holdout 近重复规则必须版本化且可重复执行。命中 holdout 的合成样本直接剔除，只发布聚合
   数量，不查看或输出对应 holdout 正文来指导改写。
5. 原始真实参考、生成草稿、失败候选、holdout 对照和逐条过滤映射只留 ignored 私有区；只有通过校验的最终
   合成数据可按 100 MB / 40 MB 规则进入 `training/`。

### 3.3 自主纠错与停止边界

1. 执行者应自主修复普通实现、格式、去重、划分、类别缺失和 focused test 问题，不因一次可窄修失败就结束。
2. 允许小规模试生成、对运输/格式失败做有界重试、在剩余额度内补齐缺失类别；实现或合同缺陷使批次无效时，
   可以保留失败事实后用新版本重生成。所有候选合计仍受 800 上限约束。
3. 不得按 outcome/rationale 是否“理想”反复生成。只有需要使用 holdout 指导合成、突破 800 上限、改变数据用途，
   或需要 API、远端资源、训练、权重、本地模型、Docker/Cargo 等新授权时，才停止请求用户决定。

### 3.4 验证、文档与 Git

1. focused tests 使用完全合成 fixture，覆盖本任务实际实现的 seed-only 边界、严格解析、去重/split、holdout
   排除、确定性写出与摘要/hash；不为列清单而重复现有测试，不跑全量 eval 或重型测试。
2. 真实批次执行 body-free 校验，核对最终数量、分布、互斥、体积、哈希、权限和 tracked 敏感扫描；skip 或
   未运行不能写成通过。
3. linked worktree 不共享 ignored 数据。真实私有读写使用显式主工作区路径，不建 symlink、不把真实正文复制
   到 tracked fixture。tracked 修改全部留在本 worktree。
4. 只有 L5b 数据合同与资产完整通过后才更新 WBS，把 P3 当前工作指向 L6；不在本计划展开 L6 方案。
5. 最终检查主工作区和所有 worktree，只提交 `034-l5b-synthetic-training-dataset` 分支；不 `git add -f eval-data`、
   不合并、不推送、不删除 worktree或重命名分支。

## 4. 软性建议

以下只是当前仓库下的实现建议，执行者可以采用更简洁或更合适的等强方案。

- 优先复用 `teacher_labels.py` 的严格批次 reader/validator，在现有 `local_approval` 包增加一个小模块；
  不必新建第二套 eval 工程。
- 可以采用少量 `prepare/finalize` 阶段：prepare 生成 seed-only 私有参考与版本化合同，当前 Sol 直接生成并保存
  候选，finalize 负责校验、去重、划分、holdout 排除和最终资产。无需模型间导出/导入协议。
- split 可采用稳定合成组哈希，近重复可用轻量 n-gram Jaccard 或等强方法；具体比例、阈值和类别分块由执行者
  依据数据决定并记录。
- `training/` 保持简洁：必要 README/数据卡、schema/manifest 和最终 train/validation JSONL 即可；不建设
  数据库、签名链、模型服务或复杂数据治理。

## 5. 当前状态

### 已完成

- 已核对根规则、WBS、数据布局、Plan 032/033 与 Plan 033 最终独立验收。
- Plan 033 已合入 `main@f98431e`；P2 已关闭，下一工作包为 L5b。
- 已创建并提交 `034-l5b-synthetic-training-dataset` 专用 worktree/分支。
- 已严格复核 Plan 032 私有批次和 tracked lock：40 条、seed 24 / holdout 16、`ready_for_l3=true` 与
  labels SHA-256 均未漂移；只把 seed 受控投影纳入当前 Sol 生成上下文。
- 已按用户决定把执行方式修订为单一 `gpt-5.6-sol` 全程完成，并删除 Claude→Sol 交接设计。
- 已落地 stdlib-only 的 strict reader/validator、精确去重、holdout 内存近重复排除、近重复连通组稳定 split、
  确定性写出和聚合 manifest，并用完全合成 fixture 覆盖直接合同。
- 当前 `gpt-5.6-sol` 已于 2026-08-15 生成 600 个唯一候选；最终 600 条全部有效，六类分布
  180 / 100 / 120 / 70 / 65 / 65，allow 240 / deny 360，train 470 / validation 130。
- 精确重复 0、holdout 近重复命中 0；120 个源/近重复组未跨 split。最终正文共 1,670,240 bytes，已按门限进入
  `training/local-approval-synthetic-v1/`，私有 seed 投影、authoring、候选与过滤明细留在主工作区 ignored 区。
- 正式 release verify 已从私有候选和冻结教师批次重算 tracked JSONL / manifest，文件内容、hash 与权限一致。

### 当前工作

- 首轮独立审查指出 tracked validator 固化私有批次 marker；窄修、复验与记录均已完成，本次整改提交即为复审交付物。

### 本任务剩余步骤

- 无；交由独立审查者验收，后续路线只以 `doc/WBS.md` 为准。

### 阻塞项

- 无。

### 当前验收状态

- `7974f4f` 首轮审查结论为“目标完成、验收不通过”，唯一 blocker 是 tracked validator 固化私有 marker；
  该字面量扫描已删除，600 条数据、split 与三个发布 hash 未改变，90 项 focused 测试和 release verify 已复验通过。
  当前任务完成，待独立复审。未运行模型、训练或重型任务。

### 交接边界

- 执行者自主选择实现路线；审查者按硬约束和真实产物验收，不把软建议升级为门槛。
- 任务完成后冻结本计划；后续只由 WBS 指向 L6。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 当前 `gpt-5.6-sol` 同时负责实现与合成生成，不设模型间交接 | 用户明确指定单一 Sol 执行者，交接层没有价值 | 执行流程 | 已采纳 |
| 002 | Plan 034 一次交付完整 L5b，不拆小包，也不并入 L6 | 保持任务有实质规模并守住训练授权门 | 任务范围 | 已采纳 |
| 003 | 目标约 600、最终 400—800、唯一候选上限 800 | 避免玩具规模和无界生成，并保留合理纠错空间 | 数据规模 | 已采纳 |
| 004 | seed 可进入当前 Sol 上下文；holdout 只由本地程序做聚合近重复排除 | 保持训练/评测互斥 | 数据边界 | 已采纳 |
| 005 | 允许试生成、格式重试、缺类补齐和版本化重生成，不按判定内容重问 | 支持自主纠错而不把生成变成结果挑选 | 失败语义 | 已采纳 |
| 006 | 最终正文按 100 MB / 40 MB 阈值决定 tracked 或 ignored | 直接遵循 WBS 的数据落点规则 | 数据落点 | 已采纳 |
| 007 | 用 canonical payload SHA 做精确去重，用 NFKC word 5-gram 的 Jaccard/containment 最大值做近重复；源组与近重复连通组整体 split | stdlib 足够覆盖当前 600 条规模，并能机械保证同源/近重复不跨 split | 去重与划分 | 已采纳 |
| 008 | 保留 Sol-authored scenario blueprint 与候选在 ignored 私有批次，Git 只跟踪最终合规数据、prompt/schema、manifest 和数据卡 | 避免把草稿/过滤明细混入交付，同时保持本次冻结批次可复核 | 数据边界 | 已采纳 |
| 009 | 正文总量 1,670,240 bytes，采用 tracked `training/local-approval-synthetic-v1/` 落点 | 明确低于 100 MB 总量与 40 MB 单文件门限 | 数据落点 | 已采纳 |
| 010 | 删除 validator 中硬编码的私有批次 marker，不改数据，也不引入运行时 DLP | 硬编码本身违反 holdout/tracked 边界；现有 synthetic workspace 强校验与 holdout 内存近重复排除已覆盖本批冻结合同，额外治理不属于本任务 | 验收整改 | 已采纳 |
