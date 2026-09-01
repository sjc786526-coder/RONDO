# Plan 102：五维云端判官实验性工程接入 ExecPlan

> 本计划是 Plan 102 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并向用户请示。
> 范围内的普通实现、provider 接缝、解析、恢复、费用、归档和测试问题由执行者自主修复、续跑或从相称的干净边界重跑，
> 不因一个窄故障提前终止。
> 本计划只描述 Plan 102；后续产品化、默认启用、qualification、训练及跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

把 Plan 095/097 已经打通的云端 scorer **产品接缝**，从单标量改造为**五维 hard decision + 关闭思考**：
`codex-publication-critic-cloud-service` 在同一服务边界向 `deepseek-v4-flash` 取回五个 hard decision，
本地按 `rondo-publication-critic-task@v2` §3 的非补偿合取派生 verdict，产品外部消费的仍然只有 typed `PASS/REWRITE`。

Plan 100/101 已经在**诊断路径**上实现并验证过五维输出合同、严格解析与 thinking 开关
（`multidev/codex-rs/publication-critic/src/cloud_diagnostic.rs` 的 `CloudFiveDimensionDecisions`、
`local_verdict()`、`CloudDiagnosticThinking`）。本任务的主要工作是**把它接到产品投影上**，而不是重写一套。

**本任务的成功定义是“工程上通了”**：接缝真通、语义与合同一致、既有不变量未破、有真实 API 证据。
不包含任何质量、资格或产品价值判断。

### 本任务不做什么

- **不投入生产、不正式发布、不改变默认关闭姿态。** Publication Critic 默认仍为 `OFF`，云端 backend 仍需显式选择。
- **不做质量测评或资格判定。** 不产出 balanced accuracy、ROC、gate 通过率一类质量结论，不设质量门，
  不给 scorer 或模型任何资格。真实调用只用来证明链路真通。
- 不训练、不解锁工作包四、不读取或解封 `publication-critic-qualification-v1` 与 v9 test 正文。
- 不删除、不改写旧标量路径；它保留为历史身份与可复算路径。
- 不建设第二套 provider、账本、测评平台，也不建设审计/可信/权限/严格因果一类设施。

### 阶段

按“先边修边跑打通，再冻结、从干净状态完整跑一轮作为正式结果”的顺序推进：

- **阶段 A：离线实现。** 产品投影接上五维合同与关闭思考、本地派生 verdict、typed failure 归类、
  旧标量路径可复算性、以及全部离线定向测试（含 §4.3 的穷举 gate 等价测试）。全程不调用真实 API。
- **阶段 B1：真实打通。** 用少量 packet 让云端 backend 在五维合同下真实取回并严格解析，
  完成 §4.4 的客观自检与费用外推。自检全部通过且外推在预算内时，执行者**自行冻结配置并继续**，不必等待用户。
- **阶段 B2：正式端到端。** 冻结代码与配置后，从干净状态完整跑通一次 `PublicationScorer → service → typed client → team_publish`
  发布链路，留下可复算回执与费用账本，并以该轮为正式结果。

阶段 A 的失败在范围内自行修复重跑；B1 允许反复打通直到全流程通；B2 出现配置性错误时允许修复后**整轮干净重跑**，
但所有实际发起过真实调用的轮次都必须如实披露。

### 完成/验收标准

- [ ] 云端 backend 在五维输出合同下向 `deepseek-v4-flash` 取回五个 hard decision，thinking 显式关闭；
      严格解析，非法输出（缺键、多键、非法取值、超长、非 JSON）走**已有的 typed failure**，不新造平行失败体系。
- [ ] 本地按 task contract v2 §3 派生 verdict，与合同**逐字一致**：
      `applicable = 除 conditional_continuity 为 N/A 时之外的全部 head`；`PASS = 全部 applicable head 为 PASS`；
      `REWRITE = 任一 applicable head 为 FAIL`；`N/A` 只排除该 head，**不提供正分**。
- [ ] §4.3 的穷举等价测试通过：五维 `2×2×3×2×2 = 48` 种合法组合全部覆盖，派生 verdict 与 §3 规则逐条相等。
- [ ] 五维模式下，**没有任何自由 threshold 能改变 verdict**；typed verdict 只由离散合取规则产生（见 §3.3）。
- [ ] 用真实 `deepseek-v4-flash` 跑通**判官段**：`PublicationScorer → service → typed client`
      在同一次服务运行中得到 typed `PASS` 与 `REWRITE` 两种外部结果。**不接受只有 fake/离线绿**。
- [ ] 用真实 `gpt-5.6-terra` 跑通**写作者段**：真实 Producer 调 `team_publish`，被判 `REWRITE` 后完成重写，
      形成唯一 canonical commit。判官段与写作者段合起来构成**一次完整发布链路**，
      从干净状态完整跑通一轮并留下可复算回执与费用账本（见 §4.2）。
- [ ] 默认关闭姿态、`team_publish` 语义、Producer 重写、canonical commit、infra fallback、取消、
      Root/Team State 不变量全部未变，并有测试守住。
- [ ] 旧标量路径仍可按**原身份**复算：既有 scalar identity、模板字节、解析与阈值语义不变，
      既有 Plan 095/096/097 结果不因本次改动而失效。
- [ ] 两笔预算各自独立、各自不超限：判官段 `deepseek-v4-flash` ≤ `10 RMB`（缺失 usage 按 `0.1 RMB/次` 兜底），
      写作者段 `gpt-5.6-terra` ≤ `50 USD`。两笔分账记录，不互相挪用、不合并计算（见 §4.1）。
- [ ] 相称的定向测试通过；Rust 构建/测试只走主物理根 `just` + `scripts/with-build-lock.sh`，
      并复用唯一 `.codex/cargo-target/rondo-multi`。
- [ ] 只提交 102 任务分支并保持 worktree clean；合并、推送、分支归档与 worktree 删除等待用户批准。

## 2. 范围

### 允许修改

- `multidev/codex-rs/publication-critic/`：产品投影接上五维合同所需的最小完整改动，包括
  `cloud_scorer.rs`、`cloud_template.rs`、`cloud_diagnostic.rs`、`cloud_config.rs`、`service.rs`、
  `scorer.rs`、`identity.rs`、`wire.rs`、`backend.rs` 及其就近测试中**确有必要**的部分。
  是否新建专用模块由执行者按 §5 的设计取向决定。
- `multidev/codex-rs/` 内因上述改动而必须同步的直接调用方与就近测试。
- `eval/rondo_eval/publication_critic/engineering/`（Plan 097 端到端 harness）与
  `eval/rondo_eval/publication_critic/structured_diagnostic/cost.py`（费用口径）中本任务所需的最小改动；
  优先小幅泛化既有模块，不复制第二套 runner 或账本。
- `eval/templates/publication-critic/` 与 `eval/locks/` 中本任务需要的小型 tracked 合同/descriptor。
- 与上述改动直接对应的定向 Rust/Python 测试与 fake/loopback fixture。
- 本 ExecPlan、`doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md` 的最小登记、精炼 `agent_log`，
  以及 `doc/WBS-COMPLETED.md`（只在最终验收接受后）。
- 主物理根 task-owned ignored `eval-data/publication-critic/plan102/`（见 §4.5）。
- 普通依赖下载与 DeepSeek 官方文档/价卡的只读查询。

### 不允许修改

- `doc/rondo-multi-publication-critic-task-contract-v2.md` 与
  `doc/rondo-multi-publication-critic-product-contract.md` 的语义。本任务是这两份合同的**实现**，不是它们的修订。
- 旧标量路径的身份与语义：`rondo-publication-cloud-template@v1`、`rondo-cloud-json-quality-scalar@v1`、
  既有 scalar 域/阈值语义与 `rondo-cloud-reference-` 前缀规则。允许围绕它扩展，不允许改写或删除。
- Publication Critic 的**默认状态**（保持 `OFF`）、local scorer 行为、`team_publish` 语义、
  Team State 不变量、生产配置与发布语义。
- `publication-critic-v9/v10/qualification` 数据正文、labels、pairs、rubric 语义、既有历史结果与已接受的审查结论。
- Plan 095/096/097/100/101 的既有实现、合同、结果与 ignored 证据；本任务只复用，不改写、不删除。
- Plan 099 保留卷、Pod/RunPod、训练权重、GPU 设施、其它 worktree、宿主机配置、全局工具链或其它仓库。

### 不允许读取/查看

- `publication-critic-qualification-v1` 的 `sealed/` 正文、`blind-review.json`、`coverage.json`、
  `family-lineage.jsonl`，以及 v9 test 正文和任何其它冻结 unseen 正文。
- `.env.local` 内容。只允许静默检查存在、非符号链接、权限 `0600`，以及所需变量存在且非空。
- 与本任务无关的个人文件、密钥、私有日志或外部服务数据。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试、让链路更快通或提高局部指标而违反。

### 3.1 授权边界

1. **已授权**：两个付费模型，两笔**互相独立**的预算：
   - 判官段：真实 `deepseek-v4-flash`，硬上限 `10 RMB`；
   - 写作者段：真实 `gpt-5.6-terra`（Producer），硬上限 `50 USD`。

   不限重跑次数与轮次，真实 API 只受各自预算约束；必要的重型 Cargo 构建与 Docker，仍走共享构建锁与看门狗；
   必须复用 `.codex/cargo-target/rondo-multi`。
2. **仍未授权**：训练、GPU/RunPod、真实本地模型加载与推理、上传、充值、产品默认启用与发布、
   qualification 与 v9 test 正文。任一项都不得因“为了把链路跑通”而突破。
3. **只授权了这两个付费模型，且两笔钱不串。** 付费外发对象只有 `deepseek-v4-flash` 与 `gpt-5.6-terra`。
   两笔预算**分账、独立、不得互相挪用**：判官段花不完不能挪给写作者段，反之亦然；
   任一笔耗尽时停止该段的付费动作并如实报告，不得用另一笔续命。
   注意 `LoopbackResponsesProxy` 与 `CloudBudgetProxy` **都不是离线假件**：它们是短命本地代理，
   持真实 key 转发到真实付费上游并计量扣账，走它们一样花钱。
   任何第三个付费模型、任何充值动作都未授权。
4. **不得新建 target 目录。** `CARGO_TARGET_DIR` 只能是 `.codex/cargo-target/rondo-multi`，
   且必须位于受监控的 RONDO 项目根内。不直接调用 Cargo 跑正式重型任务。

### 3.2 定位边界

5. **仅实验性质。** 不投入生产、不正式发布、不改变默认关闭姿态。默认路径与未显式选择云端 backend 时的行为
   必须与本任务开始前逐位一致，并有测试守住。
6. **不做质量测评或资格判定。** 不得引入 `meets_gate`、route terminal、质量阈值、资格结论或任何通过/不通过裁决。
   真实调用的唯一用途是证明接缝真通。链路通了就是通了，与判官判得准不准无关。
7. **不解锁下游。** 无论结果多好，本任务都不解锁工作包四、不启动训练、不改变产品默认、不授予任何资格。

### 3.3 合同保真

8. **verdict 只能由离散合取产生。** 五维模式下的 typed verdict 必须严格等于 task v2 §3 的
   `PASS = 全部 applicable head 为 PASS`。不得由平均、加权和、平滑近似、置信度或任何**自由 threshold**
   替代或改写。若实现上经过 §3 允许的 `quality = 1 - max(applicable violation)` 内部投影，
   其阈值必须固定在与离散规则**完全等价**的位置，且该等价性必须由 §4.3 的穷举测试机械证明。
9. **`N/A` 只排除，不加分。** `conditional_continuity = N/A` 只把该 head 移出 applicable 集合，
   不得当作 `PASS` 计入正分，也不得因此提升任何分数。
10. **严格解析、fail-closed。** 五维输出只接受**恰好五个键、取值恰好合法**的 JSON 对象；
    缺键、多键、未知键、非法取值、非 JSON、超长内容一律走已有 typed failure，
    不得宽松解析、不得猜测缺失维度、不得对解析失败重试。
11. **产品出口不变。** 产品外部消费的仍然只有 typed `PASS/REWRITE`。五维 decision 是内部诊断，
    不得泄漏到 `team_publish` 结果、Team State、wire 协议对外语义或产品日志正文。
12. **旧标量路径保留可复算。** 既有 scalar 身份、模板字节、解析与阈值语义不变；
    既有历史结果必须仍能按原身份复算。新旧两种投影必须由**显式配置**选择，不得互相污染或隐式切换。

### 3.4 数据与外发

13. **外发最小化。** 判官段只允许向 DeepSeek 外发 bounded public packet、必要的无监督 synthetic 打通 packet
    和冻结的 task/rubric/output 指令；写作者段只允许外发 Producer 正常完成发布任务所必需的运行上下文。
    两段都不得外发 labels、pairs/direction、split、defects、candidate brief、生成/审查记录、
    qualification/test 正文、源码、密钥或私有日志。
14. **body-free 证据。** tracked 结果与日志不得包含 packet 正文、provider 响应正文、credential 或私有 endpoint。
    响应正文只允许进入 task-owned ignored 回执。

### 3.5 预算与诚实

15. **两笔独立硬上限：判官段 `10 RMB`、写作者段 `50 USD`。** 不继承历史余额，不授权充值，两笔不互相挪用。
    发起下一次可能计费动作前，该段的“已结算费用 + 未结算预留 + 下一动作的保守预估”必须落在**本段**上限内。
    某段余额不足以完成下一必要步骤时，停止该段并如实报告，不得改用另一段的额度。
16. **费用结算从简。** provider 返回 usage 时按 usage 与当次请求北京时间适用的官方价卡精确结算；
    usage 缺失时按 `0.1 RMB/次` 保守固定值入账。**不得**建设离线 token 复算、tokenizer 冻结
    或“离线复算必须与 provider 精确相等”的自检门。
17. **全轮次披露。** 所有实际发起过真实调用的轮次都必须在结果与日志中列出，包含被判为技术无效
    或配置有误而废弃的轮次及其废弃原因。禁止只保留最好的一轮，或把 skip/未运行表述为已完成。
18. **证据分级不得混淆。** fake、loopback、离线、真实 API 与 Docker 证据必须明确区分并分别标注。
    只有真实 API 轮次可以用来支撑“端到端真通”的结论。

### 3.6 工程纪律

19. **不建设审计/可信设施。** 保留 body-free、可复算的 identity、typed outcome、usage 与费用即可。
    不引入事务系统、可信证明、权限体系、通用测评平台或第二套 provider/账本。
20. **构建与 Git。** Rust 构建/测试只走主物理根既有 `just` + `scripts/with-build-lock.sh`；
    按实际 diff 选择相称门禁，不无故扩大到全 workspace。tracked 变动只在 102 worktree；
    完成后提交任务分支，**合并与推送等待用户批准**。

## 4. 补充执行约定

### 4.1 预算与费用口径

两笔预算分账、互不挪用，各自覆盖阶段 B1 与 B2 的全部真实调用：

| 段 | 模型 | 上限 | 缺失 usage 兜底 | 参考单价 |
|---|---|---|---|---|
| 判官段 | `deepseek-v4-flash` | `10 RMB` | `0.1 RMB/次` | Plan 101 约 `0.008 RMB/次`；Plan 097 约 `0.003 RMB/次` |
| 写作者段 | `gpt-5.6-terra` | `50 USD` | 按 `maximum_usage_cost(pricing, envelope)` 的保守预留入账 | Plan 097 约 `0.124 RMB/次`（约 `0.0165 USD/次`） |

- usage 优先按 provider 返回值与当次适用价卡精确结算；判官段缺失 usage 时按 `0.1 RMB/次` 入账，
  该值取代 Plan 101 使用的 `1 RMB/次`（当时口径偏高）。
- 写作者段沿用既有 `PersistentBudgetLedger` 的 USD 记账与保守预留机制，不另造第二套账本。
- 参考量级：Plan 097 全任务 `172` 次 Producer 请求共 `21.35 RMB`（约 `2.85 USD`），
  且那已经包含两个 backend、多轮 commissioning 与七代废弃 ledger。
  因此 `50 USD` 对本任务是**宽裕**的额度，执行者不必为省钱牺牲打通质量；
  但仍须在每次可能计费动作前完成 §3.15 的预检。
- 费用账本落在 task-owned ignored namespace，并在阶段与最终汇报中如实列出已结算金额与剩余额度。

### 4.2 端到端链路的两段与它们各自的钱

完整发布链路 `PublicationScorer → service → typed client → team_publish` 由两段构成，**分别花不同的钱**。
两段都已授权，两段都要真跑：

| 段 | 覆盖内容 | 付费模型 | Plan 097 实际花费 | 本任务上限 |
|---|---|---|---|---|
| 判官段（direct case） | `service.review(packet)` → typed `pass`/`rewrite` | `deepseek-v4-flash` | `0.0741636 RMB` / 24 次 | `10 RMB` |
| 写作者段（Producer） | 真实 agent 调 `team_publish`、被判 REWRITE 后重写、canonical commit | `gpt-5.6-terra` | `21.3455550 RMB` / 172 次 | `50 USD` |

Plan 097 总花费 `21.4197186 RMB` 中 **99.65% 花在 Producer 段**，判官段几乎不要钱。
执行者据此安排节奏：判官段可以放开打通，**成本压力全在写作者段**，那一段要想清楚了再发起。

### 4.2.1 Plan 097 的预算合同不能直接复用

`engineering/contract.py#_validate_budgets` 把 Plan 097 的四个数**硬编码为身份**：
`cloud_scorer_rmb = 6`、`producer_rmb = 24`、`rmb_per_usd = 7.5`、`total_rmb = 30`，
任一不等即 `budget_identity_invalid`。`campaign.py` 里同样钉死了
`_PRODUCER_TOTAL_CAP_USD = 24/7.5 = 3.2`、`_PRODUCER_RUN_CAP_USD = 2.4`、`_PRODUCER_MAX_RUNS = 2`。

也就是说：**Plan 102 的 `10 RMB / 50 USD` 无法塞进 Plan 097 的合同**，必须有属于自己的预算身份。
怎么做由执行者定（Plan 102 专属 contract、把预算身份参数化、或另起一个 Plan 102 campaign 入口都可以），
硬要求只有两条：

- 不得改写 Plan 097 的既有合同数值或复用其 ledger，历史证据必须仍能按原身份复算；
- 新的预算身份必须同样是**机械校验、fail-closed** 的，不能退化成一个可随手改的普通配置项。

### 4.2.2 未授权的部分

真实**本地模型**加载与推理仍未授权。因此 local backend 与 OFF 分支只做离线守护，不做真实模型运行。
最终汇报必须写清楚"真实 API 覆盖了 cloud backend 的哪两段、local/OFF 只有离线证据"，
不得表述为"三态都做了真实验证"。

### 4.3 穷举 gate 等价测试

五维取值空间很小：四个二分类 head 各 2 种、`conditional_continuity` 3 种，合计 `2^4 × 3 = 48` 种合法组合。
必须有一个离线测试**穷举全部 48 种组合**，逐条断言派生 verdict 等于 task v2 §3 的离散规则，其中至少显式覆盖：

- 五维全 `PASS` → `PASS`；
- `conditional_continuity = N/A` 且其余四维全 `PASS` → `PASS`；
- `conditional_continuity = N/A` 且任一其它维为 `FAIL` → `REWRITE`（证明 `N/A` 不提供正分）；
- 任一单维 `FAIL`、其余全 `PASS` → `REWRITE`（四个二分类 head 各一条，证明非补偿性）。

这是本任务最便宜、最强的正确性证据，成本接近于零，必须做。

### 4.4 阶段 B1 的客观自检项

全部通过才可冻结配置并进入 B2；任何一项失败时先在范围内修复重试：

1. 云端 backend 在五维合同下完成真实请求、严格解析与归档，无技术失败。
2. thinking 真实关闭：请求显式携带关闭思考的参数，且 completion token 维持 Plan 101 `thinking_off` 的短输出量级。
3. 至少观察到一次 typed `PASS` 与一次 typed `REWRITE`，证明两种外部结果都能真实产生。
4. 至少构造一次非法响应（可用 loopback 注入），确认走的是**已有** typed failure 分类且不重试。
5. 默认关闭姿态与旧标量路径在同一次运行中仍然可用且未变。
6. 写作者段至少完成一次真实 Producer 往返：agent 调 `team_publish`，收到判官的 `REWRITE`，
   并据此发起第二次尝试。这是证明"判官接缝真的挂在发布链路上"的最小充分事实。
7. 两笔预算各自的 B2 保守外推（B1 实测 × 当次价卡 + 已结算）分别落在 `10 RMB` 与 `50 USD` 以内。
   任一笔外推超限即不得进入 B2，先缩减该段的 B2 规模或修实现，不得挪用另一笔。

自检项只能是可机器判定的链路事实。**任何时候都不得用“判官判得准不准”决定是否继续、是否重跑或是否记入结果。**

### 4.5 主工作区必须完成的事项

以下两项因 git-ignored 与凭据位置的原因，无法在 linked worktree 内自足完成，必须落在主物理仓库根：

- **ignored 证据 namespace**：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan102/`，
  存放 raw receipt、terminal observation、费用账本、run freeze 与恢复状态。
  `eval-data/` 是 git-ignored 且不随 worktree 复制，不得在 worktree 内另建。
  执行者须在阶段与最终汇报中单列该目录的精确路径、用途、大致体积与保留/清理状态。
- **凭据读取**：`.env.local` 只存在于主物理仓库根。运行入口按既有方式从该路径加载所需变量并只注入目标子进程；
  AI、测试与工具不得打开、搜索、打印、复制或记录其内容，也不得 shell source。

tracked 代码、测试、合同、结果与文档变动仍然全部落在 102 worktree 内。

## 5. 软性建议

以下是基于现有代码的执行建议，不是固定实现路线。执行者可依据 live code、测试与打通结果采用更优的等强方案，
前提是不改变 §3 的硬边界。

### 5.1 设计取向（用户偏好）

目标是优雅、干净，不是最轻或最省事：

- 职责契合时复用已有设施。
- 强行复用会造成耦合或语义扭曲时，**可以且应该新建专用能力**。
- 新能力仍遵循现有配置、生命周期、错误、测试与观测方式，与既有架构契合，而非另起炉灶。
- 可以增加解决问题所需的设施，但不重复建设第二套体系。
- 复杂度由实际问题决定；不刻意追求轻，也不预建冗余平台或不必要的审计/可信/机器校验设施。
- 不过早冻结、不过早进入正式运行；先在调试阶段边修边跑到全流程打通，再冻结并从干净状态完整跑一轮作为正式结果。
- 付费阶段之前尽量把能在本地完成的工作做完；进入付费后尽快打通、尽早暴露问题。

### 5.2 已经存在、可直接复用的东西

- **五维输出合同、严格解析、本地合取 gate、thinking 开关**：`cloud_diagnostic.rs` 里的
  `FIVE_DIMENSION_OUTPUT_CONTRACT`、`CloudFiveDimensionDecisions`、`local_verdict()`、
  `CloudDiagnosticThinking` 已经实现并被 Plan 100/101 真实验证过。`local_verdict()` 的逻辑已与 §3 一致，
  可直接作为派生规则的参考实现或复用对象。
- **provider 接缝**：`cloud_scorer.rs` 的 `call` / `build_request` / `attempt` / 重试策略 / usage 捕获 /
  served-model 校验对两种投影是共用的；`ResponseProjection` 已经是“同一请求路径、不同输出投影”的分叉点。
- **端到端 harness**：`eval/rondo_eval/publication_critic/engineering/`（Plan 097）已经具备
  service runtime、producer runtime、可续跑 write-once 回执、`PersistentBudgetLedger` 与
  `CloudBudgetProxy` / `LoopbackResponsesProxy`，是本任务端到端最自然的落点。
  注意其中的 direct case（`service.review(packet)`）与 Producer 运行是**两段不同花费**的东西，
  两个 proxy 也都是**真实付费转发**而非离线假件。预算身份不能直接复用，见 §4.2.1。
- **费用口径**：`structured_diagnostic/cost.py` 已有 `UNKNOWN_ACTUAL_ATTEMPT_RMB = Decimal("0.1")`，
  与本任务要求的兜底值一致。
- **集成测试**：`multidev/codex-rs/publication-critic/tests/cloud_process.rs` 已覆盖 ready、双 verdict、
  解析失败、model drift、重试、取消、并发、fail-closed 启动等场景，是新增用例的自然归属地，不要另起测试文件族。

### 5.3 必须自己做决定的地方（不预设答案）

产品接缝目前是**标量形状的**，从 trait 到服务一以贯之：

```text
PublicationScorer::score → RawScorerOutput { scores: Vec<f64> }
ScoringIdentity { scalar_projection, domain, threshold, pass_rule = ScoreGreaterThanOrEqualToThreshold }
service.rs: verdict_for_scores(&output.scores) → typed verdict
```

而 task v2 §3 要求 typed verdict 由**离散合取**产生，不由自由 threshold 替代。这两者之间存在真实张力，
**如何弥合是本任务的核心设计决定，由执行者做，并记入 §7 决策 001**。至少考虑两条路线：

- **薄适配**：五维在本地派生 verdict 后，按 §3 允许的合法投影压成离散取值走既有 threshold 路径。
  改动面最小，但 `ScoringIdentity` 的连续语义字段会承载一个并不连续的东西，需要说明为什么这不算语义扭曲。
- **拓宽接缝**：让 scorer 能返回 typed decision，服务不经 threshold 直接消费离散 gate。
  更贴合合同语义，但要动共享的 trait / identity / service，必须保证 local backend 与 Plan 097
  已验证的双 backend 语义不回归。

无论选哪条，§3.8 的等价性与 §4.3 的穷举测试都必须成立。也允许执行者提出第三条更好的路线。

另外注意 `cloud_diagnostic.rs` 目前的模块注释明确写着这些类型是 **eval-only、不被产品服务使用**。
把它们接到产品路径上之后，该注释与模块定位必须同步更正，否则文档与代码会当场矛盾。
`cloud_process.rs` 中的
`diagnostic_thinking_flag_is_runtime_and_does_not_change_the_product_path`
断言的正是“诊断路径不影响产品路径”这一现状，本任务会改变它的前提，需要重新表达该测试要守的不变量
（默认姿态不变、未选择五维时行为不变），而不是简单删掉。

### 5.4 门禁选择

按实际 diff 选择相称门禁：纯 Python 变化不触发 Cargo；Rust 变化后按 `multidev/AGENTS.md` 运行 fmt 与
`just test -p codex-publication-critic`，不重跑完整 workspace，也不复制 Plan 095/096/097/100 的全部历史测试矩阵。
只有在最终收口且确有必要时才考虑更大范围门禁。

### 5.5 建议执行步骤

1. 核对 live code，确定 §5.3 的路线并记入决策 001；划出最小且完整的改动面。
2. 阶段 A：落地产品投影接入、本地派生 verdict、typed failure 归类、旧标量路径可复算性，
   补齐 §4.3 穷举测试与既有集成测试的相应用例；跑相称门禁。
3. 阶段 B1：以少量 packet 真实打通，完成 §4.4 六项自检与费用外推，冻结代码与配置。
4. 阶段 B2：从干净状态完整跑一次端到端发布链路，产出回执与费用账本，以该轮为正式结果。
5. 核对费用、外发边界、默认姿态、产品不变量、ignored 资产与 Git 状态。
6. 更新本计划当前状态、WBS 最小登记与精炼 agent_log，提交任务分支，向用户交付完成汇报并停止。

## 6. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-31：确认主工作区 clean，`main = 7a9a0281`（`docs(wbs): record the Plan 102 authorization`）；
  既有 093/095/097 及各 `zz-done/*` worktree 未复用或修改。
- 2026-08-31：从 clean main 创建 `.claude/worktrees/102-five-dimension-cloud-judge` /
  `worktree-102-five-dimension-cloud-judge`，并建立本 ExecPlan。规划阶段未调用 API、未构建、未训练。
- 2026-08-31：用户追加授权写作者段 `gpt-5.6-terra` `50 USD`（独立于判官段），并确认判官段为 `10 RMB`。
  据此完整发布链路改为必做项，两笔预算分账写入 §3.1/§3.5/§4.1。
- 2026-08-31：产出执行者启动提示词
  `plan/102-publication-critic-five-dimension-cloud-judge-executor-prompt.md`。
- 2026-08-31：审查者裁定走拓宽接缝；执行者采纳为决策 001，并落地 `ScoringContract` /
  `ScorerProjection`、云端五维产品路径（thinking 关闭）、48 组合服务层穷举与
  `cloud_process` 产品用例。未调用真实 API。
- 2026-08-31：阶段 A 门禁 `just test -p codex-publication-critic` 77/77 通过（离线）。
- 2026-08-31：建立 Plan 102 独立预算身份与 campaign，不改写 Plan 097 合同数值。
- 2026-08-31：阶段 B1 判官段真实打通（`plan102-b1-r1`）：3 次 `deepseek-v4-flash`，
  观察到 typed `rewrite` + `pass`，thinking 均为 `disabled`，completion tokens 42–44。
- 2026-08-31：阶段 B1 写作者段 `plan102-b1-producer-r1`：首次 `team_publish` 得 `rewrite_required`，
  并发起第二次尝试（第二次 dispatch 失败）。B1 §4.4.6 按“REWRITE 后第二次尝试”记为打通。
- 2026-08-31：阶段 B2 五轮 e2e（`plan102-b2-r1`…`r5`）均未形成 canonical commit，全部披露为废弃轮。
  Producer v1 ledger 的 6 个 run slot 已用尽。

### 当前工作

- 阶段 A 已完成。阶段 B1 判官段与 Producer 最小往返已完成。阶段 B2 正式 canonical 尚未取得，已停止继续付费，交给审查者。

### 本任务剩余步骤

- 审查者验收。B2 若要求继续取得 canonical commit，需另开 Producer ledger 身份（当前 v1 `max_runs=6` 已用尽）。
- 合并与推送等待用户批准。

### 阻塞项

- 无。两笔预算与未授权项见 §3.1 与 §3.5，均已由用户确认。

### 当前验收状态

- 规划：`COMPLETE / FROZEN`。
- 阶段 A：`COMPLETE`（离线门禁）。
- 阶段 B1：`COMPLETE`（真实 API；判官双 verdict + thinking off + Producer REWRITE 后二次尝试）。
- 阶段 B2：`INCOMPLETE`（无正式 canonical 轮；r1–r5 均废弃）。
- 判官段累计结算 `0.0075277 RMB` / 上限 `10 RMB`，剩余 `9.9924723 RMB`。
- 写作者段累计结算 `0.752782 USD` / 上限 `50 USD`，剩余 `49.247218 USD`。
- ignored 证据：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan102/`，约 `220K`。

### 交接边界

- 执行者只在 102 worktree/branch 完成 tracked 实现、测试、文档与提交；
  主物理根 ignored `plan102` 资产按 §4.5 单列汇报。
- 执行者的启动提示词见 `plan/102-publication-critic-five-dimension-cloud-judge-executor-prompt.md`。
  本计划是合同，那份只是入场引导；两者冲突时以本计划为准。
- 本计划完成后冻结为任务合同与历史记录；后续路线只写入 `doc/WBS.md` 与
  `doc/WBS/multi-agent-trusted-evidence.md`，本文不复制。

## 7. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 走拓宽接缝，不走薄适配。实现形状：保留既有 `ScoringIdentity` 标量结构体与其 JSON 字节；新增 `FiveDimensionScoringIdentity`（只有 `definition` / `input_template` / `decision_projection` / `pass_rule=discrete_non_compensating_conjunction`，没有 domain、threshold、scalar_projection）和 untagged `ScoringContract`。`ServiceIdentity.scoring`、`RawScorerOutput`、`ScorerStatus` 改为合同枚举；`RawScorerOutput` 用 `ScorerProjection::{Scalar, FiveDimension}` 表达输出。服务按合同变体分派：标量仍走 `verdict_for_scores`，五维走 `decisions.product_verdict()`（复用 `local_verdict()`），路径上不存在 threshold。云端产品路径由 descriptor 里的 scoring 变体显式选择；未选五维时仍发标量模板且省略 thinking。 | 合同要求“没有任何自由 threshold 能改变 verdict”。薄适配下这个不变量只靠纪律维持，阈值仍在代码里，后人一调就破约；拓宽之后它是结构性的。另外 ScoringIdentity 的 scalar_projection / domain / threshold 会进 classify_backend 做身份比对，薄适配等于让身份系统去认证一份它并不实现的标量声明——身份系统正是最不该被塞进假声明的地方。 | trait、identity、service、cloud scorer、测试 | **已采纳** |
| 002 | Plan 102 是工程接入，不是质量测评或资格判定 | 用户定位为“工程上通了即可”；质量与资格属于后续独立任务与独立授权 | 验收标准、结果、交付 | 已采纳 |
| 003 | 复用 Plan 100/101 已验证的五维合同、解析与 thinking 开关，不重写 | 这些设施已在真实 API 下跑过 `810` 次调用，重写只会引入新风险 | 实现路线 | 已采纳 |
| 004 | 旧标量路径保留为历史身份与可复算路径，不删除、不改写 | Plan 095/096/097 的历史结果必须仍能按原身份复算 | 兼容性、历史证据 | 已采纳 |
| 005 | 真实 API 覆盖只包括云端 backend；local/OFF 分支用离线设施守不回归 | 真实本地模型加载与推理在本任务中未授权 | 端到端范围、汇报口径 | 已采纳 |
| 006 | 付费外发允许两个模型、两笔独立预算：`deepseek-v4-flash ≤ 10 RMB`、`gpt-5.6-terra ≤ 50 USD`，不得互相挪用 | 发布链路两段分别由不同模型驱动、分别计费；用户已就 Producer 段单独授权 `50 USD` | 预算、端到端范围、验收标准 | 已采纳 |
| 007 | missing-usage 兜底由 Plan 101 的 `1 RMB/次` 下调为 `0.1 RMB/次` | 原值明显高于实测约 `0.008 RMB/次` 的单次成本，过度保守会挤占有限预算 | 费用账本 | 已采纳 |
| 008 | Plan 102 建立自己的预算身份，不复用 Plan 097 的合同数值 | `_validate_budgets` 把 `6/24/7.5/30` 硬编码为身份，`10 RMB / 50 USD` 塞不进去；改写它会破坏 Plan 097 历史证据的可复算性 | 预算合同、campaign 入口 | 已采纳 |
| 009 | 判官段上限确定为 `10 RMB` | 用户 `2026-08-31` 明确确认按 `10 RMB`；判官段实测约 `0.003–0.008 RMB/次`，该额度已远超所需 | 预算 | 已采纳 |
| 010 | Plan 102 自建 `plan102_contract` / `plan102_campaign` 与独立 ledger schema `rondo-publication-critic-plan102-cloud-budget-v1`；`CloudBudgetProxy` 加法参数化，Plan 097 默认不变。五维 scoring identity 不含 threshold。Producer 用既有 `PersistentBudgetLedger`，batch `plan102-producer-terra-v1`。 | 097 的 `6/24/7.5/30` 是身份，不能塞进 `10 RMB / 50 USD`；改写会毁掉 097 可复算性。缺 usage 按 `0.1 RMB` 入账。 | 预算合同、campaign | 已采纳 |
