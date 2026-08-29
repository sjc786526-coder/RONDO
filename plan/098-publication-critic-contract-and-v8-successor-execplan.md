# Plan 098：Publication Critic 任务合同重构与 v8 后继数据 revision

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 普通实现、schema、生成、复核、测试或机械整合问题由执行者在授权范围内自主修复、整改和重跑；目标、范围、硬约束、阶段闸门、完成标准或授权边界确需改变时，必须通过本计划指定的 Codex 跨会话队列请求审查者转交用户确认，审查者不能自行扩大用户授权。
> 本计划只描述工作包一和工作包二；更后的训练、资格、产品启用与跨任务顺序只见 `doc/WBS.md` 与 `doc/WBS/*.md`。

## 1. 目标

### 最终目标

本任务由两个严格串行的大阶段组成：

1. **工作包一：任务合同重构。** 把已认可的 Publication Critic 五项 hard decision 设计落实为单一权威任务合同及必要轻量实现，使输入、完整五维标签、结构化输出、损失、确定性聚合和评价语义闭合。执行者完成自检和提交后必须通知审查者并停止；只有审查者明确验收通过，工作包二才被解锁。
2. **工作包二：v8 后继数据改造与有限扩充。** 仅以工作包一已验收冻结的合同为上游，从不可改写的 v8 候选素材和新增高信息样本形成独立后继 revision。数据设计、模块生成、逐块盲审、分组 split、正式冻结、renderer、manifest、consumer 和轻量 smoke 全部闭合后，再提交最终任务验收。

工作包一未获审查者明确批准时，工作包二保持锁定；工作包一 finding 只在工作包一内整改、提交、重新申请验收，不能以并行生成数据或预先固定新 revision 规避审查。完整任务只有在工作包二最终验收通过后才完成。

### 工作包一完成/验收标准

- [ ] 单一权威任务合同完整定义并版本化以下语义；产品合同、模板、schema、reference implementation、consumer 与评价代码只引用或实现它，不形成相互冲突的并列权威：
  - 模型判断五项 hard dimension 所需的 bounded、permission-scoped 公共可见输入及适用性；
  - `useful_state_transfer`、`honest_uncertainty`、`conditional_continuity`、`scope_and_signal`、`internal_consistency` 的绝对标签；
  - `conditional_continuity` 的 `PASS / FAIL / N/A`；其他四个始终适用的 heads 只能是 `PASS / FAIL`，不得增加 `N/A / UNKNOWN / ABSTAIN` 等绕过 gate 的状态；
  - 单 backbone、一次 forward、五个 hard decision heads 的结构化输出；
  - `L_dim + λ_gate L_gate + λ_boundary L_boundary + λ_inv L_invariance` 各项职责、合法输入及评价语义；
  - 结构化 heads 到内部 gate、必要兼容 scalar 和产品 typed verdict 的唯一投影。
- [ ] 资格判定固定为确定性、非补偿的 all-hard-pass：任一适用维度 `FAIL` 即 `REWRITE`，全部适用维度 `PASS` 才为 `PASS`；`N/A` 只排除不适用维度，不提供正向补偿。
- [ ] 若现有 scorer 接缝确实需要 scalar，只允许派生 `quality = min(applicable satisfaction)`，等价于 `1 - max(applicable violation)`；没有决定资格的自由 global-quality head，也没有平均、加权和或学习式补偿聚合。
- [ ] 五维绝对分类损失是主体。Binary 只监督由五头派生的 gate；Boundary 只监督目标 hard head、`Q+ PASS && Q- REWRITE` 两端绝对资格与非目标维度不变性；Within-PASS 只监督双端资格及 hard heads/gate 不变性。Soft preference 完全退出资格 loss、threshold、verdict 和 PASS 内资格排序。
- [ ] 正式输入足以完成五项判断，尤其是 continuity 适用性和 useful-state 判断；不得使用 scorer 看不到的 `public_state`、candidate brief、隐藏生成意图、split、defect 或 reviewer 信息决定标签。无法从公共输入识别的事实必须通过输入合同、标签或适用性修正闭合。
- [ ] 产品外部仍只消费 typed `PASS/REWRITE`；内部多维诊断不得改变现有重写、fallback、取消、canonical commit 或 Team State 语义，也不扩张为自由解释、自动改写或第二套在线决策系统。
- [ ] 新任务路径与冻结历史明确分界：v8、旧模板/manifest、旧单标量训练结果和旧计划仍可复算且不被改写；新合同不能被旧 scalar objective、Within-PASS ranking 或 cloud engineering fixture 冒充。
- [ ] 相称的纯函数/schema/validator/focused tests 至少直接证明：
  - 任意一个适用 hard failure 不能被其他 heads 的高 satisfaction 补偿；
  - soft-only 反事实变化不改变五头资格与派生 gate；
  - 每个 Boundary 必须满足目标维度定向变化、非目标维度不变、`Q+ PASS && Q- REWRITE`；
  - continuity `N/A` 的排除语义、完整五维标签和派生 scalar/gate 一致性成立。
  - successor 输出合同恰好表达一次 forward 的五个 heads，并拒绝旧 `[B, 1]` scalar、额外第六个 global head 或缺失 head 冒充新任务输出；
  - successor loader/schema 拒绝旧 scalar/v8 schema 冒充新 revision，同时旧历史合同和文件身份保持不变；
  - 正式 renderer/packet 明确包含 applicability 所需公共事实且继续排除监督/隐藏生成元数据；若修改 Rust packet/projection，则 Python/Rust 语义与序列化 parity 进入定向门禁；
  - 新 consumer 在 train 模式物理上只打开 train 资产，不先读取再过滤 validation/test；validation 使用独立显式入口，test 不提供给训练/方案选择入口。
- [ ] 执行者完成工作包一自检、相关定向门禁、diff/历史资产保护检查和精炼实施日志，提交工作树分支并保持 clean；随后按 §7 的队列协议主动表明身份、发送完整阶段汇报并停止会话。
- [ ] 审查者以正确性和功能性为中心独立验收；finding 由执行者在工作包一范围内整改并重提。接受时，审查者须在精炼 `agent_log` 和本计划“当前状态/关键决策记录”绑定 exact accepted commit、权威合同版本和内容 SHA-256；只有审查者明确发回带该身份的工作包一验收通过消息，才满足工作包二前置。

### 工作包二完成/验收标准

- [ ] 在生成正式数据前，从工作包一冻结合同导出一份轻量、可执行的数据设计：它绑定审查者接受的 commit、权威合同版本和内容 SHA-256；关键字段、模块划分、覆盖目标、数量/配比依据、盲审清单、split/group 规则、停止条件和正式冻结输入均能说明服务哪项输入可识别性、hard 判断、非补偿 gate、Boundary 或 invariance 目标。工作包二 finalizer/manifest 必须 fail-closed 核对该身份；核心合同漂移即重新锁定工作包二并退回工作包一复验。
- [ ] `training/publication-critic-v8/` 及其 manifest、split、labels、pairs、templates 和历史复算路径保持原样。v8 仅是候选素材库，复用率不是目标；允许在新 revision 中复用、重标、重渲染、封存或舍弃合适素材，但不得原地改写 v8、机械继承旧类别/pair/配比/模板或为历史投资凑保留率。
- [ ] v8 的 tracked 主体文件混合 train/validation/unseen，禁止为了筛选可复用素材而打开这些混合正文。工作包二只可从已物理排除 unseen 的现有受跟踪安全投影（当前至少包括 `train-only-smoke-bundle.json`）或用户以后明确提供/批准的等强安全投影读取正文；安全来源不足时允许 v8 语义复用为零并转向新生成，不得为提高复用率扫描 mixed release 或旧 Plan ignored namespace。
- [ ] 旧 validation 的定位仍是开发数据而非新 test，但本计划不授权从 mixed v8 中读取它；没有现成安全投影时不使用。旧 unseen 继续封存且不得读取。新 revision 形成独立 train/validation/test，source/scenario/template/pair/近重复关系按组隔离；各 split 物理分区或采用能证明未打开非目标 split bytes 的等强布局，默认 train consumer 不先加载再过滤 validation/test。
- [ ] 正式 candidate 都具有完整五维绝对标签和模型可见输入；缺陷未列出不能自动推定为 PASS。Boundary 明确 target hard dimension、两端绝对资格与非目标不变性；Within-PASS/soft-only pair 明确双端 hard-pass 与资格不变性。
- [ ] 覆盖达到数百条量级，但不以机械条数判定成功；应以设计给出的关键切片有效覆盖、质量和可消费性为准。至少闭合单一 hard 缺陷、自然多缺陷、`hard-fail/soft-good`、`hard-fail/soft-bad`、`hard-pass/soft-good`、`hard-pass/soft-bad` 与 soft-only 反事实不变性，并保留适量真实或真实形态锚点。
- [ ] 数据按 hard dimension、组合缺陷、invariance 或执行者证明更合适的有界模块拆分。语义样本实际生成不得由总执行者或一两个 Agent 包办大部分：至少由三位完全干净上下文的模块负责人分担，且每个模块只由其负责人生成和整改；每块另配一位未接触生成过程、完全干净上下文的盲审员，一一对应审查。
- [ ] 模块未通过时只退回对应负责人整改或重做并重新盲审；通过后立即冻结该模块。除任务合同变化或集成发现可证明的机械/schema/group 冲突外，不再跨块反复语义审查或重写；总执行者只负责合同分块、机械整合和全局覆盖检查，不冒充全量语义 reviewer。
- [ ] 每块保留最小必要的负责人身份、盲审结论、finding/整改和冻结记录；这些记录服务恢复和验收即可，不扩张为人工标注平台、教师委员会、签名链、数据库、复杂审计/可信/隐私或严格因果设施。
- [ ] 先用有界代表块调试并打通 schema、生成、复核、renderer、split、freeze、manifest 与 consumer 全链，保留身份未变的已验证进度并从未打通处继续；设施和语义稳定后再冻结正式代码、配置和已通过模块，从干净输出目录完整运行一次正式整合/冻结链，不能把调试片段拼成正式 release。
- [ ] 最终 revision 的 manifest、renderer、strict validator/consumer、group/split、重复与明显捷径检查、覆盖统计及 train-only smoke 闭合；训练方无需补标签、猜语义或读取 test 即可开始后续工作包。
- [ ] 执行者完成相称定向测试、diff/体积/敏感信息/ignored 资产/历史 v8 保护检查和精炼实施日志，提交全部变动并保持工作树 clean；随后按 §7 队列协议主动表明身份、发送完整最终汇报并停止会话。
- [ ] 审查者完成最终独立验收，并在 `agent_log/` 写明精炼结论、finding、代用户作出的决定（如有）以及“验收通过/不通过 + 任务目标完成/失败”；只有最终验收通过才表示 Plan 098 完成。

## 2. 范围

### 允许修改

- `doc/` 内现有 Publication Critic 产品合同及一个单一、版本化的权威任务合同；稳定产品语义与训练任务语义应各守职责并有清晰引用关系，不在多份文档复制当前路线或执行历史。
- `eval/templates/publication-critic/` 内与公共可见输入、五维标签、结构化输出、loss/aggregation/evaluation、数据 release、生成和盲审直接相关的新版本合同、schema 与模板。优先新增版本而不是覆盖被冻结的 v1/v2/v3 历史身份。
- `eval/rondo_eval/publication_critic/`、`eval/tools/`、`eval/tests/` 内必要的轻量 reference、validator、consumer、renderer、objective、聚合、统计、split、生成/复核编排和 focused tests。职责契合时复用现有设施；强行复用会扭曲新任务时可增加架构契合的专用能力，但不复制第二套通用平台。
- 若模型可见事实或兼容 scorer 接缝确有产品侧职责缺口，可修改 `multidev/` 内 Publication Critic packet/projection/scorer/service 及相邻定向测试；外部 wire 仍只消费 typed verdict，不能借机改写发布状态机。`multidev/` 内修改须遵守其就近 `AGENTS.md`。
- `training/` 下一个新的、受跟踪且满足仓库体积门限的 v8 后继 revision、数据卡、manifest、完整数据、模块/盲审冻结记录与 train-only smoke；不得覆盖 `training/publication-critic-v8/` 或历史 `training/publication-critic-plan*/`。
- 本计划的“当前状态”和“关键决策记录”、工作包一与工作包二各自必要的精炼实施/审查日志，以及验收通过后受影响的权威 WBS 状态。WBS 只写当前状态与下一工作包，`doc/WBS-COMPLETED.md` 只在完整任务最终验收通过后追加，不在多处堆叠历史。本轮按用户明确要求已把 WBS 的任务单位窄改为“Plan 098 两阶段共享、工作包一验收硬锁工作包二”。
- 必要的项目局部依赖与锁文件、格式化/生成工件、定向 Rust/Python 测试，以及普通依赖下载、公开源码或官方文档的只读网络访问。
- 完成工作包二所需的 Codex 干净上下文模块负责人和盲审员；工作包一也可使用子智能体做有界只读分析或独立审查，但不得用并发绕过阶段闸门。

本计划不固定具体学生基座、head 代码布局、平滑 max/min 公式、loss 权重、margin、batch、优化器、训练资源、新 revision 的精确版本号、样本精确总量、split 比例、生成 prompt、模块数量/名称或局部重构方式。执行者可依据 live code、数据质量和维护成本采用更优的等强方案，只需满足本计划冻结的任务语义、数据组织、产品边界和验收目标。

### 不允许修改或执行

- 不原地修改、重命名、重冻结、重写 manifest 或删除 `training/publication-critic-v8/`、旧 v7、历史 Plan 053/054/059/060/064/066/068/071/073/079/081/082/087/090/094/095/096/097 的合同、数据、结果、模型工件或正式证据；旧路径若需兼容，只做不改变其历史语义的版本化扩展或并行新路径。
- 不把工作包一退回单标量自由 global quality、hard/soft 混合排序、可补偿总分、五次独立模型 forward 或五个独立模型；不把旧 cloud/local engineering fixture 当作新任务质量实现。
- 不在工作包一批量生成正式数据；不在工作包二返改工作包一已验收的核心任务语义，也不根据数据生成便利临时改变标签、gate 或评价定义。若确有原则性冲突，使用指定队列请求审查者转交用户确认。
- 不训练、微调、量化、转换、下载、加载或推理真实模型；不使用 GPU/RunPod、Docker、付费 API、真实数据外发、远端上传/发布、冻结测试释放、产品默认启用、生产动作、CI/PR 或上游 Codex 基线升级。
- 不运行全 workspace 或与修改无关的重型测试。若必要 Rust 修改需要构建/测试，只能经仓库已有 `just` 配方或根 `scripts/with-build-lock.sh` 使用物理仓库根唯一共享 target；绝对禁止直接 Cargo 正式重型入口、另建 target 或在 worktree 设置第二套 `CARGO_TARGET_DIR`。
- 不建设通用数据平台、人工标注平台、教师委员会、模型委员会、复杂权限/鉴权、签名/可信链、数据库、重型审计、严格因果证明、隐私系统、第二套 Publication Critic service/client/Team State/trace 或没有本任务现实消费者的预留平台。
- 未经用户后续明确批准，不 merge/rebase/cherry-pick 到 `main`，不推送任何分支，不归档/重命名任务分支，不删除 worktree；执行者和审查者都只在 098 工作树内形成必要提交并保持 clean。

### 不允许读取/查看

- `.env.local` 内容、密钥、凭据、token、私有 provider request/response、项目外个人文件和无关数据；本任务无需任何秘密。只允许按根规则对 `.env.local` 做静默存在/类型/权限/所需变量非空检查，但本任务预期不需要该检查。
- v8 或更早数据中标记为 `unseen_test`/旧 unseen 的正文、标签、pair、review、split 成员或 ignored 资产，以及包含这些内容的 mixed v8 JSONL 正文；不得用旧 unseen 设计合同、生成样本、调 schema/比例/阈值或作 smoke。只允许对冻结目录做不向 Agent/日志暴露正文的机械完整性/哈希保护检查，并读取已物理排除 unseen 的受跟踪安全投影。
- 新 revision 的 test 正文不得进入后续训练 consumer、训练 smoke 或方案选择；本包的数据负责人/盲审员只按各自模块职责接触必要内容，总执行者对隔离块只做 schema、覆盖和关系等机械整合。
- 其他 worktree 的未提交内容、ignored 运行资产或来源不明的修改；执行者不得复制、暂存、覆盖、回退或提交它们。

### Git-ignored 与主工作区边界

- 全部 tracked 合同、源码、schema、模板、测试、正式数据、文档和日志只在 `/home/sjc/desktop/RONDO/.claude/worktrees/098-publication-critic-contract-data/` 修改并提交；主工作区不产生本任务 tracked 修改。
- linked worktree 不共享物理根 `eval-data/`。工作包二若需要 raw、draft、commissioning、模块交接或 prefreeze 临时资产，只允许在物理仓库根任务专属 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/` 创建；不得复用、修改或清理其他 Plan namespace，也不把该 ignored 目录当第二份 tracked release。
- 每次阶段交接和最终交付都应单列上述 ignored namespace 实际创建/修改的路径、体积、用途和保留/可清理状态。任务内清理只针对本任务明确创建且确认不再需要的对象；未知来源资产保持不动。
- **本次规划阶段没有必须直接写入主工作区的 git-ignored 工件。** 上述物理根 namespace 仅是后续执行工作包二时按需使用的已授权边界。

## 3. 硬约束

以下约束只冻结任务定义、阶段闸门、数据独立性、安全边界和诚实验收，不固定执行者可替换的实现路线。

1. **两个工作包严格串行。** 执行者必须先完成工作包一全部实现、自检、日志和提交，再通过指定队列申请审查。审查者可以给出 finding 并要求同阶段整改重提；在审查者明确回复工作包一验收通过之前，禁止开始工作包二的设计锁、正式数据生成、复用选择、分块或 split。最终工作包二也须提交审查。
2. **与审查者的任务沟通只有 Codex 跨会话队列。** 需要额外授权、遇到计划外变数、原则性不确定、申请工作包一验收/解锁工作包二、提交最终验收或整改复验时，都必须按本计划 §7 中用户原文指定的方法联系审查者；不得用文件、终端输出或人工提醒传递。每条消息主动表明“Plan 098 执行者”及当前工作包身份；发送一次后立即停止会话，不等待、不轮询、不重复发送。审查者可直接决定范围内普通技术/验收事项；若请求会改变目标、范围、硬约束、完成标准、授权外真实外部状态或高危边界，审查者必须转交用户明确确认后再回复，不能自行批准扩权。
3. **单一权威任务语义。** 工作包一必须选定并明确一个权威任务合同；产品合同保持稳定产品职责，schema/template/reference code 都作为该合同的投影或实现。发现旧文档、旧模板、旧 objective 与新语义冲突时，版本化隔离并指向权威合同，不能靠重复描述制造多个近似真相。
4. **五头和 gate 不可退化。** 一次 backbone forward 产生五个 hard heads；正式 verdict 是适用 heads 的确定性合取。自由 overall head、可补偿权重、平均/求和 gate、PASS 内资格排序和 soft preference 进入 threshold/verdict 都是原则性违约，不能作为执行者自主选择。
5. **监督职责同向且闭合。** `L_dim` 是完整五维绝对分类主体；只有 `conditional_continuity` 可按模型可见 applicability 规则标为 `N/A`，其余四头严格 `PASS/FAIL` 且非法状态 fail-closed。其他 loss 只沿五头 hard gate 提供派生合取、定向 Boundary 和不变性辅助；Binary 不能创建第六个资格 head，Boundary 不能退成单纯 `Q+ > Q-`，Within-PASS 不能继续训练 preferred PASS 分更高。精确连续近似、权重和 margin 由执行者选择，但结果语义必须通过纯函数 reference 与 focused tests 固定。
6. **输入可识别性先于数据。** 每项标签必须能由正式模型输入中的公共事实判断；监督 metadata 不得补充 scorer 看不到的世界。尤其须显式解决当前 completion/applicability 可能只存在于数据蓝图而未进入 packet 的缺口，并保持 permission scope、bounded projection、Evidence V1 与监督禁入边界。
7. **外部产品 seam 保持 typed。** 内部五头、诊断和派生 scalar 可以版本化增加，产品外部仍只返回/消费 `PASS/REWRITE`。若不改 Rust 产品 seam 也能完整闭合，可只做任务级轻量实现；若公共事实或兼容性确需改 seam，则做最小完整修改并跑相称定向门禁，不扩张 wire 或发布状态机。
8. **v8 只读历史，新 revision 自包含。** 新数据不能要求训练者跨目录手工拼 v8、旧 validation 或 hidden metadata；所有正式输入、五维标签、pair、split、manifest 和 consumer 在新 revision 内直接闭合。v8 复用必须逐项重新满足新合同，且只来自物理排除旧 unseen 的安全投影；安全投影不足时复用为零。无法识别、监督不完整、重复旧模板或不再有信息价值的条目应舍弃或封存。
9. **数据活动必须有合同理由。** 任何字段、模块、数量、配比、pair、renderer、review、split、统计门和指标若不能说明服务哪项输入可识别性、hard 判断、非补偿 gate、Boundary 或 invariance 目标，就不进入正式 revision。精确数量和比例由执行者在工作包二设计中有据冻结，不能事后为已生成数据倒推理由。
10. **分布式负责人—盲审员闭环。** 工作包二必须使用多个 `fork_turns="none"` 或等强完全干净上下文的子智能体。负责人只收到冻结合同、自己的模块 brief/schema 和必要公共素材；盲审员只收到冻结合同、review checklist 和待审模块，不接触该块生成过程或负责人上下文。每块一一对应、finding 只回本块、通过即冻结；不得由总执行者或一两个 Agent 承担多数语义 authoring/review。
11. **独立 split 和 shortcut 边界。** train/validation/test 按所有可识别关系闭包分组隔离；重复、近重复、模板、source、scenario、pair 和明显 label shortcut 检查覆盖完整逻辑 release。检查只发现高价值明显问题，不承诺统计因果、数据可信或隐私证明。旧 validation 只能来自安全投影且只是开发素材，旧 unseen 零读取；新 test 不进入训练/选择路径。train consumer 的门禁必须证明没有打开 validation/test bytes，不能只证明过滤后的返回对象不含 holdout。
12. **普通问题自主收敛。** 范围内解析、schema、prompt、模块质量、测试、格式、生成或机械整合失败由相应负责人/执行者自主修复、返工和重跑，不因一个窄问题停下请示，也不设机械轮数上限。原则性任务冲突、授权外动作、真实外部状态变化或合理修复后仍无法闭合，才按队列请求审查者；审查者只可自主决定既有范围内事项，任何扩权由审查者转交用户确认。
13. **先调试全链，再干净正式冻结。** 调试阶段保留身份未变且已验证的进度，从首个未打通处继续；不得过早冻结后反复在正式目录修补。代码、schema、模块和 review 稳定后，从干净输出目录完整运行正式 finalization、split、检查、renderer、manifest 和 consumer。正式身份相关内容改变时，重跑受影响的完整正式链，不只改 hash。
14. **验证与结论相称。** 优先 pure/schema/validator/consumer tests 和必要局部 Rust tests；不使用真实模型、云端、Docker、旧 unseen、skip 或历史结果冒充本次通过。执行者可为真实影响面选择更优测试集合，审查者也不得为了形式完整扩大到无关重型门禁。
15. **文档和 Git 职责单一。** WBS 只维护当前路线/状态，plan 只维护本任务合同和任务内状态，日志只记实质实施与审查，COMPLETED 只在全任务最终验收后记历史。所有提交只 stage 范围内文件，检查 diff、体积、敏感与 ignored 边界；worktree 完成后 clean，不合并、不推送、不归档、不删除。

## 4. 软性建议

以下建议基于 `main@bf28b50` 的 live 代码与 WBS，不是验收门。执行者可依据实际代码、数据与维护成本采用更优等强方案；审查者不得把本节偏好升级为硬约束。

- 工作包一先做一次语义影响面盘点：产品合同、packet/render、rubric、training-data contract/consumer、旧 scalar objective/scoring、Rust scorer/wire。把“稳定历史路径”和“新任务默认路径”分开后，再选择新增版本化模块还是兼容扩展，避免无意改坏冻结 v8 的 manifest/hash 与旧训练复算。
- 单一权威合同宜保持人工可读，同时用小型 machine-readable schema/reference 固定枚举、适用性、gate、scalar projection、loss 输入和评价规则；不需要为了防漂移建设代码生成器或签名系统。
- 输入缺口应从产品确实拥有的公共事实出发解决。可以扩展 packet、调整适用性表达或采用其他不泄露隐藏状态的干净方案；不要预先假定必须新增某个具体字段、修改 `team_publish` 参数或扩张产品 wire。
- 旧训练模块大量绑定 `[B,1]` scalar、Binary/Boundary/Within-PASS ranking。若原地兼容会造成条件分支和历史回归负担，新增清楚的 successor task/objective/consumer 通常更干净；若窄扩展能保持职责清晰，也可复用。
- 工作包二的模块可围绕五个 hard dimensions、自然组合缺陷、soft-only invariance 和少量真实形态锚点组织，但不必做笛卡尔积。先根据合同找薄弱交叉和容易混淆的可见事实，再决定模块、数量和配比。
- 数据作者与盲审员的交接可使用小型 JSON/JSONL/Markdown brief 与结论；只记录模块身份、合同版本、覆盖、finding、整改和冻结状态，不需要通用任务数据库或额外服务。
- 正式扩大前先用少量代表模块验证新 schema、renderer、review packet、split/group、manifest 和 consumer 能全程工作；模块 authoring/review 可并行，正式集成和 freeze 保持单线，避免不同 agent 同时改共享 manifest/schema。
- 若新 release 在仓库体积门限内，完整物化通常最易消费；若执行者证明版本化组合更干净，也必须让训练者通过一个 strict consumer 一次得到闭合 release，不得手工补标签或绕过 test 隔离。
- 验收指标以 per-dimension 适用性/分类、gate false PASS/REWRITE、Boundary 绝对闭合、invariance、覆盖和消费正确性为主；旧 ROC AUC、单阈值和 PASS 内 strict-win 可作为历史诊断，但不能继续主导新资格语义。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根/`multidev/` 规则、README、当前 WBS 与方向 3 子 WBS、计划模板、现行 Publication Critic 产品合同、Plan 053/054/059/064、冻结 v8、当前 input/render/training-data/consumer/objective/scoring 设施及相邻测试。
- 创建 worktree 时，主工作区两份用户 WBS 修改尚未提交；制定期间它们已由外部提交为 `main@bf28b50`。经用户明确授权，098 分支已 fast-forward 到同一提交，未重复提交或改写该 WBS 变动。
- 已创建专用 worktree `/home/sjc/desktop/RONDO/.claude/worktrees/098-publication-critic-contract-data/` 和分支 `worktree-098-publication-critic-contract-data`；本次规划没有创建主物理根 ignored 工件。
- 已按用户“一个 Plan、两个大阶段”的直接决定窄同步根 WBS 与方向 3 子 WBS：Plan 098 统一承接工作包一、二，工作包二仍由阶段一验收硬锁；工作包三、四继续各自立项。
- 已完成本计划起草、独立审查、整改与规划提交。
- 工作包一已形成唯一权威 `rondo-publication-critic-task@v2` 与 v2 rubric、v3 input、v4 render、结构化输出 schema/release contract projection；新增纯函数 gate/loss target/pair/evaluation reference 和物理 split successor consumer，保留产品 typed seam 与冻结历史路径。
- continuity applicability 已闭合为只依据 model-visible candidate：明确完成才允许 `N/A`，未完成或未明确闭合时适用，冲突时不得用隐藏 completion metadata 绕过 gate。
- 工作包一定向门禁通过：successor 合同 11/11，旧 contract/training-data/identity 回归 31/31；冻结 v7/v8 tree identity 保持不变。权威合同当前内容 SHA-256 为 `3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560`。
- 工作包一首轮独立审查结论为不通过；报告所列 findings 已在本阶段整改。第二轮复验确认 3 High/3 Medium 全部闭合、无新增 finding，并以 implementation commit `55342bdb11b09c11b589fd398717f7712fca012c`、`rondo-publication-critic-task@v2`、SHA-256 `3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560` 接受工作包一；报告见 `agent_log/2026-08-28-103405-plan098-work-package-1-second-review.md`。
- 工作包二已冻结 `publication-critic-v9`：三个干净上下文负责人分别生成并整改 `hard-boundaries`、`continuity-context`、`soft-combinations`，三个一一对应的干净盲审员最终均以 0 finding 接受绑定的新模块 SHA。正式 release 含 216 candidates、96 pairs，物理 split 为 162/27/27 candidates 与 72/12/12 pairs；完整 commissioning 与正式 finalizer、coverage、重复/捷径、renderer、manifest、train/validation consumer 和 train-only smoke 均通过。
- 工作包二最终验收首轮确认当前 v9 工件和数据闭合，但发现 finalizer 只写入 accepted implementation commit 常量，没有核验工作包一必要语义组件仍与 accepted commit 相同；报告见 `agent_log/2026-08-28-120115-plan098-work-package-2-final-review.md`。
- 工作包二最终验收整改已把工作包一的 13 个必要语义组件冻结为组合 SHA-256 `b0124de561f52fb464c223989d003af1e9f2a8a24eccd9ca349a4d769e3488d5`；finalizer 在写出前核验实际组件字节，design、generation config 与 release identity 绑定同一 identity。权威 Markdown 不变而任一其他组件漂移的 focused regression 与定向旧回归均通过，v9 数据正文和 manifest 未变化。
- 最终整改复验确认首轮 High 闭合、无新增 finding，接受工作包二 implementation `7ee479beb1f34677a54b815faf42284c0d8968e4`；报告见 `agent_log/2026-08-28-122011-plan098-final-review-remediation-recheck.md`。Plan 098 两个工作包均已冻结。
- 用户要求的验收后方向性复审确认四项窄缺口：逐头/N/A operating config 未显式冻结，逐维 failure recall/confusion 不足，train/validation 存在 honest 词汇与 scope 长度/旁白捷径，现有 test 只能作为同分布 holdout 且不足以独立承担最终资格。主体结论保留，最终接受暂停；报告见 `agent_log/2026-08-28-183143-plan098-post-acceptance-directional-review.md`。

### 当前工作

- `POST_ACCEPTANCE_DIRECTIONAL_REMEDIATION_REQUIRED / IN_PROGRESS`：只整改四项资格前置，工作包三继续锁定。

### 本任务剩余步骤

1. 显式闭合逐头 decision config、continuity N/A 保守规则和资格级逐维 confusion/failure recall；保持五头 non-compensating gate。
2. 原模块负责人只整改受影响 train/validation 反例并由原盲审员复验，不读取或改写 v9 test，不全量重审已通过语义。
3. 由全新 test-only 负责人/盲审员冻结 family-isolated 独立资格确认集；总执行者只做合同和机械冻结，不读取正文。
4. 更新 accepted semantic bundle 与 release identity，完成 clean finalizer、定向测试和独立复验；通过后 Plan 098 才重新完成。

### 阻塞项

- 四项方向性 finding 尚待整改；真实模型、付费训练和 test 释放继续禁止。

### 当前验收状态

- 规划：`ACTIVE_REMEDIATION`。
- 工作包一：`ACCEPTED_BASELINE_REOPENED_FOR_DECISION_AND_METRICS`。
- 工作包二：`ACCEPTED_BASELINE_REOPENED_FOR_SHORTCUT_AND_QUALIFICATION_SET`。
- 完整任务：`IN_PROGRESS`。

### 交接边界

- 执行者和审查者复用本计划指定的 098 worktree/branch，所有 tracked 变动先提交再交接，交接时 worktree 保持 clean。
- 工作包一完成汇报、工作包二解锁申请、计划外请示、整改复验和最终完成汇报只通过 §7 指定的 Codex queue；消息发送后主动停止会话，不等待或轮询。
- 审查者对每轮有意义的验收形成精炼 `agent_log` 报告；若需要代用户作范围内普通决策，给出理由和影响并写入报告。工作包一通过时由审查者通过同一队列明确解锁工作包二；最终通过后不再唤醒执行者。
- 工作包一接受记录必须包含 exact commit、权威合同版本与内容 SHA-256。工作包二的设计锁、生成配置和最终 manifest 都绑定并核对该身份；任何核心合同变化都使阶段一接受失效并重新锁定工作包二。
- 本计划因用户要求的方向性复审重新进入窄整改；通过后再冻结。工作包三/四仍只由 WBS 规划，不在本计划扩写训练路线。
- 未经用户批准，不合并、不推送、不归档/重命名分支、不删除 worktree。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 按用户本轮明确决定，一个 ExecPlan 包含工作包一和工作包二，并同步窄改 WBS；二者之间设置审查者明确批准的硬闸门 | 当前直接用户指令覆盖 WBS 原“每包独立 plan”粒度，同时仍避免数据工作反向固化未验收任务语义 | 阶段、WBS、验收 | 已采纳 |
| 002 | 新任务只保留一个权威语义合同，其他 schema/template/code 是其投影或实现 | 避免产品合同、训练合同和数据 schema 各自演化成近似真相 | 合同、维护 | 已采纳 |
| 003 | v8 保持物理和语义不可变，只作为可重新判断的候选素材；新 revision 自包含 | 保护历史证据，同时不让旧 scalar/排序目标绑架新数据 | 数据、历史兼容 | 已采纳 |
| 004 | 工作包二由多个干净上下文负责人分块生成，并为每块配置独立干净盲审员；总执行者只做机械整合 | 满足模块化质量与生成/审查隔离，又不建设重型标注体系 | 生成、review | 已采纳 |
| 005 | 不预先冻结基座、head 代码、平滑公式、权重、margin、batch、优化器、精确数量/比例和模块形态 | 给执行者保留实现冗余和采用更优干净方案的空间 | 实现、数据设计 | 已采纳 |
| 006 | 计划外请示、阶段验收和最终验收只使用用户指定的 Codex queue，发送后停止，不轮询 | 保证跨会话审查和唤醒语义清晰，避免重复消息 | 协作、审批 | 已采纳 |
| 007 | tracked 交付只在 098 worktree；后续 raw/临时数据按需放物理根 `eval-data/publication-critic/plan098/` 并单列汇报 | linked worktree 与主根 ignored 数据隔离，同时避免主工作区 tracked 污染 | Git、数据布局 | 已采纳 |
| 008 | 不增加 Plan 064 式额外人工 prefreeze 审批点；工作包二按模块盲审后由执行者完成一次干净正式冻结，再整体提交最终验收 | 本任务必要强制闸门是工作包一验收；减少不必要停顿，同时保留先调试后正式运行 | 执行、验收 | 已采纳 |
| 009 | worktree 创建后，用户 WBS 变动已独立提交为 `main@bf28b50`；经用户明确授权，098 已 fast-forward 到该提交 | 让执行者从同一 worktree 读取最新权威 WBS，避免启动前额外同步请示 | WBS、Git | 已采纳 |
| 010 | 工作包一接受绑定 exact commit、权威合同版本与内容 SHA-256；工作包二全链 fail-closed 核对，漂移则退回阶段一 | 用轻量身份防止已验收任务语义在数据阶段静默变化 | 阶段、manifest | 已采纳 |
| 011 | mixed v8 正文不读取；只从物理排除 unseen 的安全投影复用，安全来源不足时允许复用为零 | 当前冻结文件混合 split，不能为复用而突破旧 unseen 封存 | 数据来源、隔离 | 已采纳 |
| 012 | 工作包一复用严格 `PublicationPacket@v1` 公共字段，不修改 Rust product seam；完成/未完成 applicability 只从 candidate 可见文本判定，隐藏 completion metadata 被 successor runtime contract 拒绝 | 现有公共 packet 已包含作出五项判断所需的 bounded candidate/context；新增产品字段会制造可规避标签的并列事实 | 输入、产品、标签 | 已采纳 |
| 013 | 新 successor release 采用 train/validation/test 物理 split 文件；训练 consumer 只打开 train bytes，validation 使用独立入口且不提供 test loader | 直接满足 holdout 字节隔离并避免延续旧 mixed-file 后过滤模式 | schema、consumer、隔离 | 已采纳 |
| 014 | 首轮审查接受“不改 Rust seam、以模型可见 candidate/public packet 操作化 completion”的路线，但要求可见 basis 引用与产品/任务合同明确对齐；schema 设施保持轻量 | 闭合可识别性而不引入隐藏完成事实、NLP 规则或重型可信平台 | 输入、schema、审查 | 已采纳 |
| 015 | release JSON 改为明确的 contract projection，跨字段/关系约束由 strict runtime validator 权威执行；output JSON Schema 明示额外 runtime 约束 | 避免非标准描述冒充可执行 schema，同时不建设无现实必要的通用 schema 平台 | schema、runtime、测试 | 已采纳 |
| 016 | 第二轮复验接受工作包一：implementation commit `55342bdb11b09c11b589fd398717f7712fca012c`，合同 `rondo-publication-critic-task@v2`，SHA-256 `3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560`；工作包二解锁 | 首轮全部 findings 已闭合，42/42 定向门禁与独立复验无新增 finding | 阶段、合同、数据前置 | 已采纳 |
| 017 | 后继 revision 冻结为 `publication-critic-v9`，由三个 24-group 模块组成；旧 v8 安全投影只用于判断可复用性且直接复用为零 | v1 scalar 监督不足以无歧义投影完整五头标签；新合同原生数据以 216 candidates / 96 pairs 有界覆盖 Boundary、invariance、自然组合与三类 public context | 数据、split、消费 | 已采纳 |
| 018 | 工作包二首轮最终验收不接受“accepted implementation commit 仅作为常量自洽写入”；对工作包一 13 个必要语义组件执行轻量字节/组合 SHA 漂移门，并绑定 design、generation config 与 release identity | 权威 Markdown 不变时，renderer/schema/loss/consumer 等实现仍可能漂移；固定组件序列的 canonical SHA 足以让阶段一 accepted identity 成为可执行前置，无需建设通用审计体系 | finalizer、身份、验收 | 已采纳 |
| 019 | 最终整改复验接受工作包二 implementation `7ee479beb1f34677a54b815faf42284c0d8968e4`，Plan 098 完成；工作包三只作为 WBS 下一工作包，不继承本计划执行授权 | 首轮 High 已闭合，47/47 定向回归与独立身份/字节复核无新增 finding；训练、云资源和产品动作仍需单独规划授权 | 验收、交接 | 历史接受，终态由 020 暂停 |
| 020 | 用户要求的验收后方向性复审暂停 019 的终态，只窄补逐头 decision config、逐维资格 metrics、honest/scope 反例与 family-isolated 独立资格确认集 | unique argmax 可接受 calibrated decision logits，故不推翻五头 decoder；但当前隐含 operating seam、开发集表面捷径和小型同作者 test 不足以支撑付费训练后的资格 GO/NO-GO | 任务、数据、资格前置 | 整改中 |

## 7. 给执行者的启动提示词

你是 Plan 098 的执行者。请在 `/home/sjc/desktop/RONDO/.claude/worktrees/098-publication-critic-contract-data/`、分支 `worktree-098-publication-critic-contract-data` 内工作。开始前完整阅读根 `AGENTS.md`、`multidev/AGENTS.md`、当前 WBS 和 `plan/098-publication-critic-contract-and-v8-successor-execplan.md`，随后直接按计划执行，不另拟一份重复计划，也不要向用户复述 ExecPlan 或 AGENTS 内容。

你必须明确分为工作包一和后续工作包二。先完成并提交工作包一，按下述队列协议申请审查，然后停止会话；只有审查者明确通知工作包一验收通过，才能进入工作包二。最终完成工作包二和整个 Plan 098 后，再按同一协议提交最终验收并停止会话。所有队列消息开头必须主动表明身份，至少写明“Plan 098 执行者”和当前工作包/整改轮次。

用户已经一次授权：在本计划范围内修改项目内合同、源码、schema、模板、测试、文档、必要重构和生成工件；使用干净上下文子智能体完成工作包二的模块生成与一一盲审；使用任务专属本地 ignored 暂存；下载普通依赖、只读查询公开源码/官方文档；运行相称定向验证；在工作包内自主修复普通问题、整改、重生成并重跑；完成独立审查所要求的范围内修复。若涉及 Rust，必须复用物理仓库根唯一共享 target 和现有构建锁入口，绝对不得新建 target。所有 tracked 变动完成后提交 098 工作树并保持 clean。

本授权不包含真实模型加载/推理或训练、GPU/RunPod、Docker、付费 API、数据外发、旧 unseen 或冻结测试读取、产品启用/生产、上游基线升级、宿主机/全局工具链修改、合并、推送、分支归档/重命名或删除 worktree。需要额外授权、出现计划外变数或原则性不确定时，不要自行扩大范围，使用下述队列联系审查者作为批示；范围内窄问题由审查者直接决定，若请求涉及上述排除项、目标/范围/硬约束变化或其他真实外部/高危扩权，审查者会转交用户明确确认后再回复。范围内窄问题自行修复重跑，不要反复请示。

以下是用户指定的跨会话沟通方法，必须原样遵循：

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a048fa-99d0-70e2-afaa-a75a8088e245 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。

需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。

执行者完成工作包1阶段，申请进入工作包2，以及最终完成完整任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了<阶段性任务>，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<执行者的完成汇报>”
其中
<阶段性任务>就是执行者想申请验收的部分，一般情况下主要是工作包1的验收和最终整个任务完成（主要是工作包2）的验收。
<执行者的完成汇报>就是执行者本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）执行者你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。

执行者给审查者发送消息的时候，必须主动表明身份。

为同时满足“阶段验收消息模板原样使用”和“主动表明身份”，实际 `XXX` 必须由两部分连续组成：第一行先写 `【身份：Plan 098 执行者｜工作包一/工作包二｜轮次】`，随后原样粘贴上述从“执行者完成了<阶段性任务>”开始的模板，只替换两个尖括号占位符；身份前缀不算入 `<执行者的完成汇报>`，完成汇报本身仍一模一样嵌入。

上述原文中的“如果验收通过，他不会再通知你”只适用于**最终完整任务验收**。工作包一通过后，审查者必须通过同一 Codex queue 明确通知执行者并解锁工作包二；执行者在收到该消息前保持停止，不自行轮询或进入工作包二。

用户原文所说“以此作为批示”不扩大本计划既有授权：审查者可以直接批示范围内普通实现、整改和验收事项；若请求涉及本提示明确排除的动作、目标/范围/硬约束变化或其他真实外部/高危扩权，审查者必须先转交用户取得明确授权，再通过同一 queue 回复执行者。
