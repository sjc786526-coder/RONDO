# Plan 101：DeepSeek V4 Flash 思考开关 × 三种输出表达对比测评 ExecPlan

> 本计划是 Plan 101 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并向审查者请示。
> 范围内的普通实现、provider 接缝、解析、恢复、费用、归档和测试问题由执行者自主修复、续跑或从相称的干净边界重跑，
> 不因一个窄故障提前终止。
> 本计划只描述 Plan 101；后续产品接入、qualification、训练及跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 `publication-critic-v10` development validation 的同一批 27 candidates / 12 pairs 上，用同一个 `deepseek-v4-flash`，
测量**思考开关**与**输出表达**两个因素下的真实判别能力，产出一份可复算、可重复、可长期连成曲线的测评结果。

因子矩阵为 `2 × 3`：

- **思考条件**：`thinking_off`（贴近本地一次前向 scorer 的部署形态）与 `thinking_on`（该任务的信息上界）。
- **输出表达**：`A` 单标量 `[0,1]`、`B` 直接 `PASS/REWRITE`、`C` 五项 hard decision + 本地 non-compensating AND。

两个因子之外的一切保持冻结且完全相同：provider、requested model、模型可见 packet 字节、task v2 / rubric v2 语义、
cohort 与行序、timeout/retry、本地 labels/pairs/指标口径。`thinking_on` 下 provider 会忽略 temperature，
这对三臂是共同条件，不破坏输出表达之间的对照。

本任务同时修复 Plan 100 已确认的两处测量缺陷：输出契约中的**具体示例值被原样抄回**，以及**单次采样无方差估计**。

### 本任务不做什么

- **不设通过门，不产出路线终态。** 交付物是数字、区间和差值表，不是 `PASS/FAIL`、资格结论或路线裁决。
- 不读取、不解封 `publication-critic-qualification-v1` 与 v9 test。
- 不训练、不改变 Publication Critic 产品默认状态或发布路径、不授予任何产品或模型资格。
- 不建设第二套 provider、账本、测评平台或审计/可信设施。

### 阶段

- **阶段 A：离线实现。** prompt 占位符化、thinking 开关、条件/重复维度、新增指标切片与定向测试。不调用真实 API。
- **阶段 B1：打通轮。** 6 个单元（3 臂 × 2 条件）各用少量 packet 打通真实链路，并完成 §3.6 的客观自检与费用外推。
  自检全部通过且外推在预算内时，执行者**自行冻结配置并继续**，不必等待审查者。
- **阶段 B2：正式矩阵。** 从空 namespace 跑完整矩阵，产出结果与报告。

### 完成/验收标准

- [ ] `A/B/C` 三个输出契约中不再出现任何合法示例取值；改用占位符或多示例形式，使模型无法通过复述示例得到合法输出。
- [ ] thinking 开关成为 Plan 101 诊断路径的运行期参数，两种取值都能真实生效；产品 scorer 与其它 eval 路径的行为不变。
- [ ] 正式 observation 的唯一键包含 `condition × arm × candidate × repeat`，write-once、可中断续跑、重复响应幂等。
- [ ] 正式矩阵完成 `3 臂 × 27 candidate × 2 条件 × 3 次重复`，即 `486` 个 terminal observation；
      3 轮结束后仅依据预算决定是否补第 4、5 轮（两条件保持同 n），该决定必须在查看补轮是否改变任何结论之前做出并记入账本；实际次数如实记录。
- [ ] 结果按 §4 报告六个单元的候选级指标与 Wilson 区间、A 的完整曲线/AUC/**并列比例与不同取值个数**、
      C 的五维 confusion 与逐维 failure recall/continuity N/A recall、12 个 pair 结果、
      **漏检与归错抽屉的分离计数**、**跨重复自洽率**，以及每次调用的 token 与耗时。
- [ ] 报告给出两组差值：同臂的 `thinking_on − thinking_off`，以及同条件下 `C − B`、`C − A`、`B − A`。只报差值与区间，不判定优劣通过与否。
- [ ] 全部实际发生的轮次（含被判为技术无效或配置有误而废弃的轮次）在结果与日志中如实列出，不得只报告最好的一轮。
- [ ] 三臂两条件对每个 candidate 使用完全相同的模型可见 packet 字节；labels、pairs、defects、brief、split、生成/审查记录
      只在 provider 结果落盘后由本地 join，不进入 prompt、请求日志或错误回显。
- [ ] task-wide 真实 API 消费不超过 `20 RMB`；费用优先按 provider usage 与当次适用价卡结算，缺失 usage 时按 §3.5 的保守兜底入账。
- [ ] 结果落到 `eval/results/publication-critic/plan101-thinking-comparison-v1.json` 与同名 `.md`，可从冻结 raw observation 独立复算。
- [ ] 相称的定向测试通过；涉及 Rust 时只走主物理根 `just` + `scripts/with-build-lock.sh` 与唯一 `.codex/cargo-target/rondo-multi`。
- [ ] 只提交 101 任务分支并保持 worktree clean；合并、推送、分支归档与 worktree 删除等待用户批准。

## 2. 范围

### 允许修改

- `multidev/codex-rs/publication-critic/src/cloud_diagnostic.rs`：三个输出契约的示例形式。
- `multidev/codex-rs/publication-critic/src/cloud_scorer.rs`：把 Plan 101 诊断路径的 thinking 由硬编码 `disabled` 改为运行期参数。
  改动只允许作用于 `ResponseProjection::Diagnostic`，不得触及产品 scorer 分支或 wire 协议。
- `eval/rondo_eval/publication_critic/structured_diagnostic/`：条件与重复维度、运行/恢复/归档、费用、指标与报告。
  优先在既有 Plan 100 模块上做小幅泛化，不复制第二套 runner 或账本。
- `eval/templates/publication-critic/` 与 `eval/locks/` 中本任务需要的小型 tracked 合同/descriptor。
- 与上述改动直接对应的定向 Python/Rust 测试与 fake/loopback fixture。
- 本 ExecPlan、`doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md` 的最小登记、精炼 `agent_log`，
  以及 `doc/WBS-COMPLETED.md`（只在最终审查接受后）。
- 主物理根 task-owned ignored `eval-data/publication-critic/plan101/`（见 §5 交接边界）。
- 普通依赖下载与 DeepSeek 官方文档/价卡的只读查询。

### 不允许修改

- `publication-critic-v10` 数据正文、labels、pairs、task v2 / rubric v2 语义、既有历史结果与已接受的审查结论。
- Plan 100 的既有实现、合同、结果与 ignored 证据；本任务只复用，不改写、不删除。
- Publication Critic 产品 scorer 默认、local scorer 行为、Team State、`team_publish`、生产配置或发布语义。
- Plan 099 保留卷、Pod/RunPod、训练权重、GPU/Docker/本地模型设施、其它 worktree、宿主机配置、全局工具链或其它仓库。

### 不允许读取/查看

- `publication-critic-qualification-v1` 的 `sealed/` 正文、`blind-review.json`、`coverage.json`、`family-lineage.jsonl`，
  以及 v9 test 正文和任何其它冻结 unseen 正文、旧 unseen 逐样本输出或其 label/pair 方向。
  该集合的 manifest 规模元数据（rows/bytes/sha256）已知且无需再查。
- `.env.local` 内容。只允许静默检查存在、非符号链接、权限 `0600`，以及所需变量存在且非空。
- 与本任务无关的个人文件、密钥、私有日志或外部服务数据。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试、追求好看的数字或提高局部指标而违反。

1. **两个因子之外一切相同。** `thinking` 与输出表达之外的 provider、requested model、packet 字节、rubric 语义、cohort、
   行序、timeout/retry 必须完全一致。`thinking_on` 忽略 temperature 属于该条件的固有属性，可以接受并记录，
   但不得为某一臂单独调整任何其它请求参数。
2. **示例值不得可复述为合法输出。** 三个输出契约中不允许出现任何本身合法的示例取值。
   这是 Plan 101 的核心修复项，任何“为了让模型更听话”而恢复具体示例值的做法都超出授权。
3. **外发最小化。** 只允许向 DeepSeek 外发 v10 validation 的 bounded public packet、必要的无监督 synthetic 打通 packet
   和冻结的 task/rubric/output 指令。不得外发 labels、pairs/direction、split、defects、candidate brief、生成/审查记录、
   qualification/test 正文、源码、密钥或私有日志。
4. **预算硬上限 `20 RMB`。** 不继承历史余额，不授权充值。发起下一次可能计费动作前，
   “已结算费用 + 未结算预留 + 下一动作的保守预估”必须 ≤ `20 RMB`。余额不足以完成下一必要步骤时停止并如实报告。
5. **费用结算从简。** provider 返回 usage 时按 usage 与当次请求北京时间适用的官方价卡精确结算。
   usage 缺失时按阶段 B1 实测的最大单次成本向上取整所得的保守固定值入账，该值必须显著高于任何合理实际成本。
   **不要求、也不得建设**离线 token 复算、tokenizer 冻结或“离线复算必须与 provider 精确相等”的自检门——
   Plan 100 正是因为该自检门被迫关闭 thinking，而其兜底路径 99 次调用中一次未被使用。
6. **只有客观自检，没有质量门。** 阶段 B1 的放行条件只能是 §3.6 列出的可机器判定项。
   任何时候都不得用“结果好不好看”决定是否继续、是否重跑或是否记入结果。
7. **全轮次披露。** 所有实际发起过真实调用的轮次都必须在结果与日志中列出，包含被判为技术无效或配置有误而废弃的轮次
   及其废弃原因。禁止只保留最好的一轮、拼接不同配置的行，或把 skip/未运行表述为已完成。
8. **配置冻结与重跑规则。** 阶段 B1 自检通过后冻结 prompt/schema/descriptor/release/指标口径。
   进入 B2 后若发现配置本身有误，允许修复并**从新的空 namespace 完整重跑正式矩阵**，但旧轮次按 §3.7 全量披露；
   不得只重跑部分单元或部分 candidate 来替换不满意的结果。纯技术中断只补未完成的键。
9. **不产出门与终态。** 本任务不得引入 route terminal、资格判定、`meets_gate` 类字段或任何形式的通过/不通过结论；
   也不得复用 Plan 099 训练开发门的阈值作为判据。结果只呈现数字、区间与差值。
10. **不解锁任何下游。** 无论数字多好，本任务都不读取或解封 qualification/v9 test，不启动训练，不改变产品默认，
    不授予 scorer/model 产品资格，不执行发布或生产动作。后续路线必须由 WBS 和新的独立任务承接。
11. **构建与 Git。** Rust 构建/测试只走主物理根既有 `just` + `scripts/with-build-lock.sh` 并复用唯一
    `.codex/cargo-target/rondo-multi`；不直接 Cargo，不扩大到全 workspace。tracked 变动只在 101 worktree；
    完成后提交任务分支，合并与推送等待用户批准。
12. **不建设审计/可信设施。** 保留 body-free、可复算的 identity、typed outcome、usage 与费用即可。
    不得引入事务系统、可信证明、权限体系、通用测评平台或第二套 provider/账本。

## 4. 报告内容

### 4.1 六个单元各自报告

| 指标 | A | B | C |
|---|:--:|:--:|:--:|
| balanced accuracy + Wilson 区间 | ● | ● | ● |
| PASS / REWRITE recall、false PASS、false REWRITE | ● | ● | ● |
| 完整 operating curve、ROC AUC | ● | | |
| **并列比例、不同取值个数** | ● | | |
| 五维 confusion、逐维 failure recall、continuity N/A recall | | | ● |
| **漏检 vs 归错抽屉分离计数** | | | ● |
| 9 个 boundary pair、3 个 soft-invariance pair 结果 | ● | ● | ● |
| **跨重复自洽率** | ● | ● | ● |
| 每次调用的 prompt/completion token 与耗时 | ● | ● | ● |

加粗三项是 Plan 101 相对 Plan 100 新增、且信息量最高的切片：

- **并列比例 / 不同取值个数**：直接量化标量输出退化。Plan 100 中 A 的 27 个输出只有 3 个不同取值、
  180 个跨类比较里 105 个精确并列，这一事实当时没有任何指标暴露出来。
- **漏检 vs 归错抽屉**：对每个 gold 含 FAIL 的 candidate，若 C 的本地 gate 判为 REWRITE，
  再区分“预测 FAIL 集合与 gold 完全一致”“gate 正确但 FAIL 集合不同”。
  逐维层面，对每个未被预测为 FAIL 的 gold FAIL，按同一 candidate 上是否存在其它被预测为 FAIL 的维度，
  分为**归错抽屉的漏检**与**完全未察觉的漏检**。
- **跨重复自洽率**：同一 `condition × arm × candidate` 在多次重复间给出相同结果的比例，直接量化单次采样噪声。

### 4.2 差值表

- 同臂的 `thinking_on − thinking_off`：回答“一次前向与允许推理之间差多少”。
- 同条件下的 `C − B`、`C − A`、`B − A`：回答“三种输出表达之间差多少”。

只报差值与区间。不设阈值，不判定“明显优于”或“接近”。

### 4.3 建议附带的切片

`2026-08-29` 研究报告识别出三条标注与模型可见 rubric 文本不一致或边界模糊的 candidate
（`pcv9-hard-boundaries-validation-03-qminus` 与 `pcv9-soft-combinations-020-hard-fail` 的 `scope_and_signal=FAIL`，
`pcv9-continuity-context-019-qminus` 的 `conditional_continuity=FAIL`）。
建议在报告中附一个排除这三条的对照切片，便于判断结论对这几条标注是否敏感。
**不得因此修改 v10 数据或标签。**

### 4.4 结果留存

结果写入 `eval/results/publication-critic/plan101-thinking-comparison-v1.json` 与同名 `.md`，
沿用既有 `eval/results/publication-critic/` 惯例，使同一 cohort 上的历次测评可以自然连成曲线。
tracked 结果不得包含 packet 正文、provider 响应正文、credential 或私有 endpoint。

## 5. 补充执行约定

### 5.1 阶段 B1 的客观自检项

全部通过才可冻结配置并进入 B2，任何一项失败时先在范围内修复重试：

1. 6 个单元（3 臂 × 2 条件）各自完成真实请求、严格解析与归档，无技术失败。
2. thinking 开关真实生效：`thinking_on` 单元的 completion token 显著高于同臂 `thinking_off` 单元，
   且 `thinking_off` 单元维持 Plan 100 观察到的短输出量级。
3. **输出非退化（按臂分级）**
   - a. 任何单元的响应不得与输出合同中的尖括号模板逐字节相同（模板本身不是合法 JSON，出现即为抄写）。
   - b. 每个 thinking 条件下，至少有一个臂在 3 条 packet 上产生 ≥2 种不同响应 —— 用于证明 packet 确实被投递且被读取。
   - c. A 臂在打通样本上至少出现一个非边界取值。
   - d. 某个单元在打通样本上恒定，不构成打通失败。 但必须在 B2 冻结前，把该单元连同其恒定取值写进 contract 的 `preregistered_observations`，作为待 B2 检验的预登记现象。
4. 按 B1 实测 token 与当次价卡外推的 B2 保守总成本，加上已结算费用，落在 `20 RMB` 以内。

第 3 项的目标始终是识别“抄示例导致解析成功但零信息”。该特征只对高熵输出通道成立；对 1-bit 的 B 臂，n=3 上的恒定不构成链路故障证据，故改为跨臂验证 packet 可达性。

### 5.2 重复次数与补轮

默认两条件都跑 3 次重复：`3 臂 × 27 条 × 3 次 × 2 条件 = 486` 次。两条件同 n，自洽率口径直接可比；奇数次多数票不出平局。

3 轮跑完后，若剩余预算仍能覆盖两整轮（约 5.9 RMB）加余量，再补第 4、5 轮。补轮与否**只能依据预算判断**，必须在查看补轮是否改变任何结论之前决定并记入账本。不允许看了结果再决定要不要加数据。

不得改变矩阵结构或删减 candidate。余额不足以完成已冻结的 3 轮时停止并如实报告，不再自行削减臂、条件或 candidate。实际使用的重复次数必须在结果中记录。

### 5.3 主工作区必须完成的事项

以下两项因 git-ignored 与凭据位置的原因，无法在 linked worktree 内自足完成，必须落在主物理仓库根：

- **ignored 证据 namespace**：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan101/`，
  存放 raw receipt、terminal observation、费用账本、run freeze 与恢复状态。
  `eval-data/` 是 git-ignored 且不随 worktree 复制，因此必须使用该主物理根路径，不得在 worktree 内另建。
  执行者须在阶段与最终汇报中单列该目录的精确路径、用途、大致体积与保留/清理状态。
- **凭据读取**：`.env.local` 只存在于主物理仓库根。运行入口按既有方式从该路径加载所需变量并只注入目标子进程；
  AI、测试与工具不得打开、搜索、打印、复制或记录其内容，也不得 shell source。

tracked 代码、测试、合同、结果与文档变动仍然全部落在 101 worktree 内。

## 6. 软性建议

以下是基于现有代码的执行建议，不是固定实现路线。执行者可依据 live code、测试与打通结果采用更优的等强方案，
前提是不改变 §3 的硬边界。

- 优先复用 Plan 100 的 DeepSeek provider 接缝、write-once 归档、恢复、预算账本与结果投影，
  在其上增加 `condition` 与 `repeat` 两个维度即可；把 Plan 100 的 route/gate 判定整体旁路掉，不要迁移。
- 输出契约的占位符形式可以是 `{"quality":<number between 0 and 1>}` 一类明确非法的模板，
  或给出两三个取值互不相同的示例。哪种更稳可在阶段 A 用 fake/stub 设计、在 B1 用真实响应确认。
- Plan 100 的 tokenizer/recounter 路径按 §3.5 不再需要；保留其代码不动即可，不必删除，也不要为 Plan 101 复活它。
- 并发 1 通常最利于预算控制与次序核对；若执行者能证明更高并发同样安全且不影响结果，可自主选择。
- 定向门禁按实际 diff 选择：纯 Python 变化不触发 Cargo；Rust 变化后按 `multidev/AGENTS.md` 运行 fmt 与
  `just test -p codex-publication-critic`，不重跑完整 workspace，也不复制 Plan 095/096/100 的全部历史测试矩阵。
- Wilson 区间用于表达分辨率，不必引入更复杂的统计设施；`n=27` 下不要给出精密统计声明或因果结论。

### 建议执行步骤

1. 核对 live code 与 Plan 100 既有设施，确定“小幅泛化”的最小改动面。
2. 完成 prompt 占位符化、thinking 运行期开关、条件/重复维度、新增指标切片与 fake/dry-run 定向测试。
3. 执行阶段 B1：6 个单元打通，完成 §5.1 四项自检与费用外推，冻结配置。
4. 从空 namespace 执行 B2 完整矩阵；中断只补未完成键，配置性错误按 §3.8 整轮 clean 重跑并全量披露。
5. 独立复算指标，产出结果 JSON/MD，检查费用、外发边界、产品不变性、ignored 资产与 Git 状态。
6. 更新本计划当前状态、WBS 最小登记与精炼 agent_log，提交任务分支，向用户交付完成汇报并停止。

## 7. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-29：审查者确认主工作区 clean，`main = origin/main = 22a3737dbaba9de3ed4b5eb1c1a5b6f8e1e88d4e` 之后的当前 HEAD；
  既有 093/095/097 worktree 未复用或修改。
- 2026-08-29：从 clean main 创建 `.claude/worktrees/101-publication-critic-ds-thinking-eval` /
  `worktree-101-publication-critic-ds-thinking-eval`。
- 2026-08-29：建立本 ExecPlan 并把 Plan 101 最小登记到根 WBS 与方向 3 子 WBS。规划阶段未调用 API、未构建、未训练。
- 2026-08-31：阶段 A 落地（占位符契约、thinking 运行期开关、对比 runner）并提交任务分支。
- 2026-08-31：阶段 B1 多次真实打通。审查者裁定原 §5.1 第 3 项对 1-bit 通道误用；`thinking_off:B` 在打通三元组上恒定 PASS 是测量结果，须预登记后由 B2 检验。r4 prompt 冻结，r5 已撤回。

### 当前工作

- B1 复审通过。按修正后的 §5.1 / §5.2 冻结 B2 并开跑正式矩阵。

### 本任务剩余步骤

- 冻结 B2（含 `preregistered_observations`）并跑 486 次；按预算决定是否补第 4、5 轮。
- 出报告、文档与任务分支提交，交付完成汇报后停止。

### 阻塞项

- 无。未授权项与 `20 RMB` 上限不变；`conservative_fixed_missing_usage` 1.00 不得回冲。

### 当前验收状态

- 规划：`COMPLETE / FROZEN`。
- 阶段 A：`COMPLETE`（任务分支已提交）。
- 阶段 B1：`COMPLETE`（r4 为通过证据；原第 3 项判据已按审查者批复替换）。
- 阶段 B2：`IN_PROGRESS`。

### 交接边界

- 执行者只在 101 worktree/branch 完成 tracked 实现、测试、文档与提交；主物理根 ignored `plan101` 资产按 §5.3 单列汇报。
- 本任务完成后冻结本计划；产品接入、qualification、训练等后续路线只链接 WBS，不列入本任务剩余步骤。
- 合并、推送、分支归档与 worktree 删除等待用户批准。

## 8. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 101 是测评（eval）而非资格门，不产出 route terminal 或通过/不通过结论 | 本任务要回答“差多少”，不是“够不够格”；门与资格属于后续独立任务 | 指标、结果、交付 | 已采纳 |
| 002 | 思考开关作为对照因子，而不是隐含前提 | 一次前向对应部署形态，允许推理对应任务信息上界；只有并排测才能把两者分开 | 矩阵、成本 | 已采纳 |
| 003 | 输出契约禁止出现合法示例取值 | Plan 100 中 A 臂 20/27、C 臂 13/27 逐字节复述示例，整臂结果作废 | prompt、Rust | 已采纳 |
| 004 | 取消离线 token 复算与其精确相等自检门，改为 usage 优先 + 保守固定兜底 | 该自检门正是 Plan 100 被迫关闭 thinking 的唯一硬原因，而兜底路径 99 次调用中零使用 | 费用、provider | 已采纳 |
| 005 | 用重复采样 + 全轮次披露替代“首个有效 formal 即停 API” | 防挑结果应靠预冻结判据与全量披露，而不是限制只跑一轮；单次采样方差是当前主导误差源 | 矩阵、诚实性 | 已采纳 |
| 006 | 继续使用 v10 development validation，不动 qualification | 测评需要可反复运行的集合才能连成曲线；qualification 只能开一次，留给未来真正的一次产品判断 | 数据、边界 | 已采纳 |
| 007 | 新增“并列比例/不同取值个数”“漏检 vs 归错抽屉”“跨重复自洽率”三个切片 | 这三项分别对应 Plan 100 未能暴露的输出退化、维度归属错误与采样噪声 | 指标 | 已采纳 |
| 008 | tracked 变动只在 101 worktree；ignored raw/账本只在主物理根 `eval-data/publication-critic/plan101/` | linked worktree 不共享 ignored 资产，需保持主工作区 tracked clean | Git、资产 | 已采纳 |
| 009 | 阶段 B1 由执行者按客观自检自行放行，不等待审查者 | 用户已预先授权付费与上限，自检项均可机器判定，为 3 元量级实验设人工闸门不相称 | 阶段、节奏 | 已采纳 |
| 010 | 原 §5.1 第 3 项“单元内响应不得全部逐字节相同”对 1-bit 通道误用，改为按臂分级：禁抄模板、跨臂 packet 可达性、A 非边界、恒定单元预登记；正式重复改为两条件同 n=3，补 4/5 轮只看预算 | 该检测器是高熵抄示例病的特征，套到 B 臂会把测量结果当成链路故障，并逼着改 prompt 洗掉现象；n=3 恒定不是打通失败 | B1 门、B2 重复、contract 预登记 | 已采纳 |
