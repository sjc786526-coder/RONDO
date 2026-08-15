# Plan 032：L5a 首批 Sol 教师标签

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 L5a 首批教师标签；跨任务路线、优先级、顺序和依赖以
> `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为唯一来源。

执行者固定为人在场使用的开发用 Codex，模型为 **`gpt-5.6-sol`**。Sol 在本任务中既负责项目内实现，
也按冻结 prompt 生成教师标签；不再设置 Claude 到 Sol 的二次交接层或人工抽查暂停点。

## 1. 目标

### 最终目标

为当前 47 条真实 `E_final` 冻结可增量延续的语义身份、语义去重和互斥 `seed` / `holdout` 分区；
基于 L3 的 canonical static payload v3 与 `rondo_static_approval_v1` 冻结首版教师 prompt、标签 schema、
批次 manifest 和必要哈希。对当前 12k 长度适配子集完成一批人在场、订阅制 `gpt-5.6-sol` 教师标签，
把正文标签保存在 git-ignored 数据区，给后续独立 L3 工作包提供完整、可严格导入的固定输入。

教师标签是特定时点 Sol 的**蒸馏目标**，不是人工 ground truth，也不是 L3/L4 或 Local M4 的运行结论。

### 完成/验收标准

- 47/47 个当前归档实例均通过既有生产 meta、tracked run ledger 与 canonical static v3 解析检查，并各自记录：
  唯一实例 SHA、稳定语义身份、分区、去重组、12k 适配状态和批次选用/排除原因。
- 同一语义身份只能属于一个分区；历史身份和分区冻结后不因后续新增实例而重划。新增实例按同一版本化规则
  增量归类，已有语义组的代表实例不被静默替换。
- 当前理论上限仍是 42 个 12k 适配实例；实际标签数以语义去重后的冻结 manifest 为准。
  只读规划预检按本计划 v1 规则得到 **45 个语义身份、2 个重复实例；42 个适配实例去重后 40 个候选**。
  执行设施必须从真实数据重新验证这些数；任一项不一致时停止，不得用预检数字覆盖现场。
- 冻结且入库一版教师 prompt、机器可校验标签 schema、版本号与内容 SHA-256。教师看到的审批问题必须来自
  `build_static_payload()` 的完整 canonical static v3 合同，输出判定必须是 `rondo_static_approval_v1`；
  不得改用 Plan 031 Guardian bridge 的正式请求 instructions 或 Guardian 自身输出 schema。
- 用户已明确取消首次外发前的人工抽查；当前 `gpt-5.6-sol` 执行者应在同一任务内从 prepare 连续完成标签生成、
  校验、文档和提交，不生成抽查预览，也不设置中途人工确认点。
- 只允许一个冻结完整批次。仅对传输失败或格式不合规项定向重试一次；重试必须使用同一 prompt 版本、同一
  canonical payload 和同一语义身份，不能扩充证据集合、改判据或因不满意判定而重问。
- 每条最终标签与唯一语义身份、代表 `E_final` SHA、canonical payload SHA、分区、prompt 版本/SHA、
  实际 `gpt-5.6-sol` 模型标识、生成日期和批次身份一一绑定。
- 导入校验必须整批 fail-closed：缺失、额外、重复、未知字段、格式/schema 错误、身份/分区/prompt/model/date
  不一致，或文件 SHA 不符时，整批不得标记 ready；不能静默跳过坏行或发布部分批次。
- git-ignored 私有区保存完整 manifest、待处理 payload、原始返回、冻结标签和 L3 导入元数据；
  Git 只保存 prompt、schema、无正文/无逐条 holdout 明细的批次摘要、manifest/标签哈希及实现测试。
- focused pure/local 格式与一致性测试、47 条现场 prepare 检查和最终标签 verify 检查均通过且无 skip。
  不加载本地模型，不运行 Local-static、Docker、重型 Cargo、L3/L4 或真实 API。
- 完成后只提交 `032-l5a-sol-teacher-labels` 工作树分支；不合并、不推送。

## 2. 范围

### 允许修改

- `plan/032-l5a-first-sol-teacher-labels-execplan.md` 的“当前状态”和“关键决策记录”。
- `eval/rondo_eval/local_approval/` 下必要的轻量 manifest/export/label 校验实现。
- `eval/tests/` 下对应 pure/local 回归测试与不含真实正文的合成 fixture。
- `eval/templates/local-approval/` 下冻结的 Sol 教师 prompt 与标签 schema；如现有布局更适合，可在 `eval/`
  内选择同职责的窄目录，但不得建立第二套 eval 工程。
- `eval/locks/` 下一个无正文、无逐条 holdout 明细的版本化批次摘要；本轮不产生 baseline，不能把摘要放进
  `eval/results/baselines/` 冒充测评结果。
- 若实际数据落点或字段合同需要同步，精炼更新 `doc/eval-data-layout.md`；L5a 真正完成后，按文档职责更新
  `doc/WBS.md`、`doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 与一份精炼 `agent_log/`。
- 主工作区 git-ignored `eval-data/` 下本任务专用目录中的私有数据文件，权限遵循目录 `0700`、文件 `0600`。

### 不允许修改

- `mydev/`、`multidev/` 产品代码，Guardian bridge、launcher、资格证据、GGUF/runtime/template lock。
- `eval/rondo_eval/evidence.py` 中 static payload v3 的语义、`STATIC_INSTRUCTIONS` 或
  `rondo_static_approval_v1`；本任务消费现有合同，不借生成标签改变合同。
- `eval/results/runs.jsonl`、L3/L4 结果账本、shadow 分数或历史 baseline。现有结果 publisher 尚不是本轮
  教师标签的导入入口；L5a 只准备冻结输入与校验元数据。
- L4 指标/分数、漏放/误拦结论、Opus 裁判、L5b 合成数据、训练/LoRA、云 GPU、Local M4 或 16k 路线。
- 剩余 5 个 12k 超窗实例的外发、标签补齐或推理；它们只在私有全量 manifest 中记录排除原因。
- CI、PR、远端发布、worktree 分支推送、主分支合并。

### 不允许读取/查看

- `.env.local` 的任何内容；也不得搜索、打印、复制或 source。任务不需要任何 API key。
- `rondo.local.toml`、本地模型权重和与本任务无关的私有运行数据；本任务不需要本地 provider/model 配置。
- 冻结 manifest 未选中的真实证据正文不得发送给 Sol；所有真实正文均不得出现在终端输出、Git diff、
  agent log 或公开摘要中。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

### 3.1 数据源与 canonical static 合同

1. 当前全集只认 `eval-data/runs/*/guardian-evidence/*/{E_final.json,meta.json}` 中与 tracked
   `eval/results/runs.jsonl` 一致的 47 个生产归档；复用或等强实现 `token_census.collect_evidence_inputs()`
   的普通文件、读前后身份、production meta、run/model/effort 与重复实例校验，不扫描 `eval-data/work/`
   等 staging 副本。
2. 每个教师输入必须由公共 `build_static_payload(E_final)` 产生，并以
   `static_payload_bytes_for_consumer(payload, "sol-static")` 取得完整 canonical bytes；它必须与
   `local-static` consumer bytes 逐字节相等。合同包括：
   static payload schema v3、`STATIC_INSTRUCTIONS`、policy、规范化 evidence input 和
   `rondo_static_approval_v1` 输出 schema。routing/批次身份只能在外层元数据绑定，不得改变此 canonical payload。
3. 不使用 `guardian_bridge.py` 构造教师请求。Plan 031 bridge 只复用了 `input` 规范化与 serving contract；
   它发送 Guardian 自己的 instructions/schema，整条请求不等于 L3 qualification/static 请求。
4. Sol 只可定向读取本轮冻结 export 并把返回写入本轮私有标签目录，这两类文件工具操作仅承担输入/输出运输；
   不得用工具调查仓库、网络或其他证据，不得把正文回显到普通终端/日志，只依据 canonical payload 判定。

### 3.2 语义身份、去重与分区 v1

1. 从 canonical payload 中取**最后一个完整 approval request block**的 planned-action/network-access JSON；
   先验证边界唯一可解析，再按 UTF-8、`sort_keys=true`、紧凑分隔符、`ensure_ascii=false`、拒绝 NaN 的 JSON
   canonicalization 计算 `action_fingerprint_sha256`。当前 47 条仅含 `exec_command`；遇到未覆盖动作形态时
   fail-closed，不能猜测或静默退化到整份 `E_final`/`review_id` 哈希。
2. 当前 47 条的 `task_id` 必须从归档所属 `run_id` 在 tracked ledger 的唯一 task 行取得，缺失或多值即停止。
   有 task id 时语义身份固定为：
   `sha256(b"rondo-guardian-semantic-v1\0" + task_id_utf8 + b"\0" + action_fingerprint_sha256_ascii)`。
   后续若某种受支持来源按其 schema 确实没有 task id，则按 WBS 退化为
   `semantic_id = action_fingerprint_sha256`；不能把当前 ledger 缺失误当成合法退化。
   `review_id`、Guardian thread id、run id、文件路径和生成时间都不得参与语义身份。
3. 同一语义身份的多个归档实例只生成一条教师标签。私有 manifest 分开记录“语义组冻结代表”和“本批 12k-fit
   标签代表”：前者按公开、确定性的排序从当前全组选择并在后续增量中保持不变；后者只能从该组本轮 12k-fit
   成员中确定性选择，标签绑定后也不改变。一个语义组没有 fit 成员时整体排除，绝不能外发其超窗代表。
   排序细节可由执行者选定，但必须测试确定性并记录版本。
4. 分区固定为：取 `semantic_id` 前 8 个十六进制字符为无符号整数，`value % 10 < 4` 为 `holdout`，
   其余为 `seed`。这是语义身份上的稳定 40/60 哈希切分，不按 outcome、长度、任务名或人工偏好挑选。
5. `holdout` 可以在本轮获得教师评测标签；其身份与正文不得进入 L5b 合成上下文、合成 prompt、合成期人工参考
   或训练集。本任务不实现 L5b，但产物中的用途字段必须使后续误用可被拒绝，而不是只靠说明文字。

### 3.3 12k 批次、私有产物与 tracked 摘要

1. 12k 适配必须与已发布 exact-token census 的同一 `e_final_sha256` 对齐，并使用
   `input_tokens + 512 <= 12_288`。缺失、重复、未知 SHA、census digest 漂移或 token 字段错误均停止。
2. 私有全量 manifest 至少逐实例记录：schema/version、source instance identity、`e_final_sha256`、
   `static_payload_sha256`、task/动作/semantic identity、partition、代表/重复关系、input tokens、12k fit、
   selection 与明确 exclusion reason。正文/路径只留私有区；tracked 摘要只写聚合计数与文件哈希。
3. 私有产物必须放在主工作区 `eval-data/` 下一个本任务专用、可持久交给 L3 的命名空间，且不得占用 launcher
   receipt 使用的 `eval-data/local-approval/`。具体目录名、文件拆分和中间形态由执行者决定，但必须能区分
   Sol 原始返回与已验证标签，并在 tracked 摘要中留下稳定引用和哈希。
4. tracked 摘要必须绑定：batch/schema 版本、static payload 版本、census digest、prompt/schema SHA、
   私有 manifest SHA、最终标签 SHA、教师模型标识/日期、源实例/语义唯一/重复/12k fit/最终标签/分区计数、
   exclusion/retry 计数和 `ready_for_l3`。不得包含正文、source path、逐条语义 id 或逐条 holdout 归属。
5. 任一失败只能留下明确 `not_ready` 的私有诊断或不产出摘要；不得先写 `ready_for_l3=true` 再补校验。

### 3.4 Sol 生成与一次重试

1. prepare 与所有本地检查完成后，冻结待处理 manifest 和 prompt SHA；随后由当前人在场的开发用 Codex
   `gpt-5.6-sol` 在同一任务中直接生成标签，不暂停等待人工抽查或第二次授权。任务应核对并记录会话实际显示的
   模型标识和生成日期；模型身份不清楚或不是明确的 Sol 时停止。订阅侧模型版本不能由仓库冻结，产物只能表述为
   该时点教师判定。
2. Sol 执行者读取冻结 export 只作为接收本轮明确提供的 canonical payload 的运输方式；生成判断时不得调用工具
   调查仓库、网络或其他证据。允许在同一任务/批次内按上下文容量分块，但所有块必须共享同一 manifest、prompt、
   模型标识，不能形成会话间重新定标或人工挑选；每条如实记录实际生成日期，tracked 摘要记录日期集合或范围，
   不为维持单日假象改写跨午夜事实。
3. 这是人在场的订阅制会话，不得新增 Sol API client、批处理 API、密钥、预算代理或 eval 自动后端。
   当前 Sol 执行者可以直接完成生成和保存，因此不需要 Claude 转交、二次复制协议或额外代理身份。
4. 一次完整批次后先校验全部返回。只有 `transport_failed` 或 `schema_invalid` 的明确项可用同一输入定向重试一次；
   缺失/身份错配如能明确归属于上述两类才可重试。不得因结论、理由或风险标签“不理想”而重试。

### 3.5 标签与导入校验

1. 决策对象必须与 live static decision validator 等强：`outcome = allow|deny`、非空 `rationale`、最多 16 个
   唯一且各自非空的字符串 `risk_tags`，且无额外字段。本地外层绑定可以携带 identity/provenance，但不得
   混进 decision 对象或改写 Sol 原始判定文本。
2. 最终标签集合必须与冻结 selected semantic-id 集合完全相等，并逐条核对代表 `E_final`、payload、partition、
   prompt、model、date 与 batch identity；文件级 SHA 也必须匹配。集合相等是整批条件，不接受按行 best-effort。
3. L3 import metadata 只声明标签批次已通过格式/身份检查和用途边界；本轮不把教师标签写成 shadow run，
   不计算任何一致率或 L4 指标，不修改结果账本。

### 3.6 现场、Git 与证据纪律

1. tracked 实现和文档只在本 worktree 编辑、测试和提交。由于 worktree 不共享 ignored 文件，当前 47 条源归档
   从主工作区 `/home/sjc/desktop/RONDO/eval-data/runs/` 读取，新生成的私有产物写入主工作区 `eval-data/`
   下本任务专用且不与既有设施冲突的目录；这不是修改主工作区 tracked 文件。所有命令都应使用解析后的显式
   根路径，不能依赖当前目录碰巧指向哪棵 worktree。
2. 写私有文件采用窄权限、临时文件后原子替换；不覆盖未知既有批次。不得创建 symlink 把私有数据引入 worktree，
   也不得复制真实正文到 tracked fixture。
3. 提交前检查 worktree 与主工作区状态、tracked diff、ignored 产物落点和敏感正文扫描。只提交本任务 tracked
   文件；不 `git add -f eval-data`，不合并、不推送。

## 4. 软性建议

- 优先在现有 `local_approval` Python 包内做一个小模块，并复用 production evidence reader、
  `build_static_payload()` 和 census baseline；不新增第三方依赖、数据库、签名、访问控制或审计系统。
- 私有目录可优先采用 `eval-data/teacher-labels/<batch_id>/`，决策校验可优先直接复用
  `validate_static_decision()`；如果 live code 表明有更干净的等强实现，执行者可以调整并在关键决策记录中说明。
- CLI 可保持为少量阶段：`prepare`（冻结私有 manifest/outbound）、`verify-labels`（严格导入与最终私有文件）、
  `summarize`（最后生成 tracked 摘要）。具体命名和类结构由执行者依据 live code 决定。
- 对 Sol 的批次载荷可把 routing identity 放在外层，把 `canonical_payload` 原样嵌入；回收后把原始 decision 与
  本地 identity 绑定。关键是测试 payload bytes 没有被 envelope 或 prompt 组装改写，不必设计复杂协议。
- 合成 fixture 覆盖 Standard/Lite、历史中含多个 approval block 的 `E_final`、重复语义动作、不同 task、
  12k 边界和各类坏标签；不要把真实证据正文复制进测试。
- focused 门禁建议为相关 `unittest` 模块与一次真实 47 条的无网络 prepare/verify；不跑全量 eval，
  不启动模型。若未改变依赖，无需重写 lock 或扩大测试范围。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已完成根规则、两级 WBS、数据布局、Plan 030/031 与 live canonical static/census/production meta 实现复核。
- 已在 `032-l5a-sol-teacher-labels` worktree/分支落地 prompt、schema、identity/partition/manifest、
  私有运输、原始返回保存、整批导入校验、body-free 摘要与 focused 回归。
- 真实 prepare 重新验证 47 条生产归档：45 个语义身份、2 个重复实例、42 个 12k 适配实例，语义去重后
  选中 40 条；seed / holdout 语义组为 27 / 18，最终标签为 24 / 16，排除原因为超窗 5、重复 2。
- 当前人在场开发用 Codex `gpt-5.6-sol` 已于 2026-08-15 完成冻结完整批次；最终 40 条均得到合规判定。
  其中 16 条仅因首次传输失败，使用完全相同的 prompt 与冻结输入定向重试一次；schema 重试为 0，未因标签
  内容重试。教师标签是时点 Sol 蒸馏目标，不是人工 ground truth。
- 私有批次已通过两次幂等 verify 并标记 `ready_for_l3=true`；tracked 摘要不含正文、路径、逐条 semantic id
  或逐条 holdout 明细。prompt / label schema / manifest / labels SHA-256 分别为
  `5425f3de…312c` / `62c4e8ec…aa18` / `c96b621a…feba` / `7eaafa25…2a40`。

### 当前工作

- Plan 032 已完成并通过最终独立验收；本计划已冻结，后续工作只按 WBS 另开 L3/L4 工作包。

### 本任务剩余步骤

- 无。本计划冻结为已完成任务合同与历史记录。

### 阻塞项

- 无。

### 当前验收状态

- 完成判据已满足：真实 47 条 prepare、40 条冻结教师标签、完整集合 verify、focused pure/local 门禁、
  私有/公开边界与现场一致性检查均通过，无 skip。未运行 L3/L4、Local-static、本地模型、Docker、Cargo、
  API、训练、合并或推送。

### 交接边界

- 执行者按结果合同自主选择最小实现，不进入 L3/L4、L5b/L6、16k、产品代码或结果发布。
- 审查者按 frozen prompt/manifest/labels 的实际哈希、完整集合校验、测试与 Git 边界验收，不以建议文件布局
  或逐条实现方式作为额外门槛。
- 本任务完成后冻结此计划；下一独立工作包只由 WBS 指向 L3/L4，不在本计划继续维护下游路线。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 教师输入使用完整 canonical static payload v3，不复用 Plan 031 Guardian bridge 整请求 | bridge 的 instructions/schema 与 qualification/static 不同，只共享 input 归一化与 serving contract | 输入合同 | 已采纳 |
| 002 | 47 条全量身份/分区 manifest 与标签正文留在 ignored 私有区，Git 只留 prompt/schema/聚合摘要/哈希 | 同时满足增量冻结、L3 导入与真实正文/holdout 明细不入库 | 数据边界 | 已采纳 |
| 003 | 语义身份使用 task id + 最后待审批动作的 canonical JSON 指纹；分区为 semantic id 前 32 bit 模 10 的 40/60 切分 | 去掉 review/run 实例身份，保持跨运行稳定、互斥且不人工挑样 | 身份与分区 | 已采纳 |
| 004 | L5a 只准备私有严格导入批次，不写 imported shadow run | live 结果 publisher 尚未实现 imported shadow 行，本轮也明确禁止进入 L3/L4 和结果账本 | 导入边界 | 已采纳 |
| 005 | 执行者与教师均为同一人在场开发用 Codex `gpt-5.6-sol`，取消 Claude→Sol 交接 | 用户修正了实际执行方式，同一执行者可直接保存冻结结果 | 执行流程 | 已采纳 |
| 006 | 真实私有数据读写使用主工作区 `eval-data/`，tracked 工作继续留在 032 worktree | Git ignored 数据不随 linked worktree 共享，且必须在 worktree 删除后继续供 L3 使用 | 工作区 | 已采纳 |
| 007 | 只允许格式/传输失败项按原输入重试一次，不允许按标签内容重问 | 控制一次批次的判定漂移，又保留最低限度的格式恢复 | 生成 | 已采纳 |
| 008 | 取消首次外发前人工抽查，由同一 Sol 执行者从 prepare 到提交连续完成 | 用户明确修正执行流程，不再要求查看预览或中途确认 | 授权与执行 | 已采纳 |
| 009 | 无正文批次摘要固定放 `eval/locks/`，不放 baseline 目录 | L5a 冻结输入而不运行 L3/L4，不能制造结果语义 | 产物职责 | 已采纳 |
| 010 | 实现集中在现有 `local_approval/teacher_labels.py`，复用 production reader、公共 static builder、census 与 live decision validator；私有入口在 TTY 下关闭回显后原样保存返回 | 以最小模块关闭 canonical bytes、身份、完整集合与正文不回显边界，不新增依赖或第二套 eval 工程 | 实现与私有运输 | 已采纳 |
