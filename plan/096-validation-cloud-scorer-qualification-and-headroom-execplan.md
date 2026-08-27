# Plan 096：Validation 云端 Scorer 资格与任务对齐参考上界测定 ExecPlan

> 本计划是 Plan 096 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算、正式对象或完成标准，应暂停对应动作并按本计划指定的跨会话队列请求审查者批示。
> 普通实现、provider 接缝、解析、timeout、限流、费用计量、恢复、归档和定向测试问题，应在既有范围与预算内自主修复并按需重跑，
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 096；Plan 097 是否解锁及跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在不改变 Publication Critic 产品行为的前提下，复用 Plan 095 已交付的 default-off、eval/reference-only 云端 scorer backend，
以及既有 v8 validation 释放、quality metrics、operating curve 和结果归档基元，为强通用模型 `deepseek-v4-flash` 建立一条能保留
typed scalar 与必要 usage 的测评接缝。先使用合成或非正式输入完整打通 provider、scalar、费用、恢复、聚合、复算和归档；随后在正式结果
产生前冻结 clean source、非密钥配置、模型与 scorer identity、Plan 095 cloud template/projection、采样与 retry 条件、validation identity、
评价协议和终态规则，从全新空 namespace 对冻结的 55 条 validation 完成一轮干净正式评分。

正式轮分开回答：云端 scorer 是否存在满足既有发布质量门的 admissible operating point；以及冻结的 DeepSeek V4 Flash scorer stack
在该任务上的 threshold-free 分辨能力属于 HIGH、LOW 还是 INCONCLUSIVE。结果与 exact 1.7B、4B 历史结果按真正可比的口径对照，并形成且只形成
一个有效研究终态。Plan 096 不启用产品、不运行 unseen、不训练模型，也不直接执行 Plan 097。

### 完成/验收标准

- [ ] 在任何 validation 正式 score 产生前，以受跟踪的机器可读 freeze 或等强小型合同唯一绑定：clean Git commit 与环境锁、
      provider/API shape、requested/effective model、不可验证的 serving/tokenizer 语义、reasoning effort 与全部采样条件、timeout/retry、
      cloud descriptor/scorer identity、template/projection/domain、validation release、评价方法、质量门、headroom 规则、价格来源和正式
      namespace 规则；若价卡不是 RMB，还须冻结保守币种换算来源/时点；不保存密钥或原始私有 endpoint。
- [ ] 正式模型为 `deepseek-v4-flash`。若 provider 无法完成该模型的真实 scalar 路径，需要替换正式模型或改变任务语义，必须通过指定队列
      请求审查者批示；不能静默 fallback 到 Sol、Terra、Luna、Qwen、其它 DeepSeek 型号或任何其它模型。
- [ ] 正式数据唯一绑定 `publication-critic-v8` manifest content SHA-256
      `a9a31a61e0a1e070ee8d076dd313b7efabb5e01ffa42773a841b123a2686cb98` 与 canonical validation release SHA-256
      `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`：55 candidate、34 PASS / 21 REWRITE、
      19 Boundary pair、7 Within-PASS pair、unseen row 为 0。发送 provider 的每份请求只含一个既有 bounded `PublicationPacket` 的
      cloud projection，不含 candidate 标签、pair、split supervision、unseen、训练集、源码或密钥。
- [ ] commissioning 使用合成/非正式输入先完整打通 scalar capture、typed failure、usage/cost、55 项批处理、恢复、聚合、完整 curve、
      write-once archive 和独立复算。可以保留已验证进度并从未打通处边修边跑；不得用正式 validation 标签或已产生的正式 score 优化
      prompt、模型、effort、采样条件、评价口径或终态规则。
- [ ] 唯一有效正式轮来自冻结 clean source 和新的空 namespace；55 个冻结 candidate ID 恰好各有一份同配置、不可覆盖的有限 `[0,1]`
      scalar，零遗漏、零重复、零 typed failure、零跨 namespace/config 拼接。成功 scalar、有效负向质量结果或有效模型失败不得选择性重跑
      求绿；纯基础设施/实现问题按本计划的重跑规则处理。
- [ ] 完整 operating curve 复用既有 search：`0`、`1`、全部 unique scalar 与相邻 midpoint；同一 operating point 同时满足
      False PASS ≤ `0.25`、False REWRITE ≤ `0.35`、balanced accuracy ≥ `0.75` 才是 threshold-dependent feasible point；
      全局还须 ROC AUC ≥ `0.80`、Boundary strict win ≥ `0.70`、typed failure = `0`。selected fallback 继续按既有
      balanced accuracy 最大、False PASS 数最少、threshold 最大的顺序确定；Within-PASS 只报告，不新增事后质量门。
- [ ] 四个研究终态只在上述 55/55 有效完整性成立时按下列顺序唯一产生：

  | 终态 | 冻结判定 |
  |---|---|
  | `CLOUD_SCORER_QUALIFIED` | 存在满足全部既有质量门的 operating point；解锁 Plan 097 的立项入口，但不在本任务执行 097 |
  | `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH` | 不合格，且 ROC AUC ≥ `0.80`、Boundary strict win ≥ `0.70` |
  | `CLOUD_SCORER_TASK_HEADROOM_LOW` | 不合格，且 ROC AUC < `0.80`、Boundary strict win < `0.70` |
  | `CLOUD_SCORER_RESULT_INCONCLUSIVE` | 不合格，且上述两个 threshold-free 门恰好一个通过 |

  因预算、provider、基础设施、实现、缺 score、重复、跨配置或无效指标而未形成 55/55 时，只能诚实记录任务
  `FORMAL_INCOMPLETE`/阻塞事实，不能把它包装成第五种研究质量终态。
- [ ] 正式归档至少能从 freeze + validation release + 55 scalar rows 独立复算完整 curve、selected point、资格门、threshold-free 指标、
      唯一终态和标签分歧清单；逐项 raw/receipt 可留在 ignored task namespace，tracked 结果只保留必要 identity、逐行 score/label 或等强
      可复算材料、聚合、历史比较和不含 packet 正文的分歧 ID，不建设额外审计/可信平台。
- [ ] 与 `eval/results/publication-critic/m3-c2-joint-selection-v1.json` 的 exact 1.7B base 和
      `eval/results/publication-critic/skywork-reward-v2-qwen3-4b-base-quality-v1.json` 的 exact 4B base 比较同 cohort/label/pair/curve/gate 下的
      False PASS、False REWRITE、balanced accuracy、ROC AUC、Boundary 与 Within-PASS。raw logit、绝对 threshold/score calibration、
      tokenizer/window、cloud/local template、延迟与资源不作伪精确同类比较；模板天然不同不触发本地重跑。
- [ ] 费用以正式运行前核验的 provider 价卡、每次 usage 或可核验账单记录保守累计；无法可靠核验费用的每个实际发出的可能计费 provider
      HTTP request/attempt 按 `1 RMB/次` 计入。commissioning、formal 与基础设施重试合计严格低于或等于 `30 RMB`。本任务不追求用满
      预算，进入付费阶段前完成尽可能多的离线工作。
- [ ] default-off、既有本地 scorer、产品 `PublicationScorer → service → typed client → team_publish` wire/verdict 语义、Team State 和
      发布行为保持不变；云端 scalar 观测只服务 eval/reference，不把 raw scalar 扩成产品 API。
- [ ] 运行与最终 diff 相称的格式、lint、锁文件/生成物检查和定向正确性测试；不跑全 workspace，不把 skip/未运行写成通过。完成后检查
      worktree、主工作区、其它 worktree、ignored 资产、费用与意外生成物。首次独立审查接受后再同步 WBS 完成状态、
      `doc/WBS-COMPLETED.md` 和最终实施日志，避免未验收结果提前进入完成历史。
- [ ] 所有完成变动在 096 task branch 提交并保持 worktree clean，再通过指定队列请求审查者验收并停止会话。未经用户后续批准，不合并、
      不推送、不归档/重命名分支、不删除 worktree。

## 2. 范围

### 允许修改

- `eval/rondo_eval/publication_critic/` 中与本任务职责匹配的 validation release、cloud scalar batch runner、freeze、usage/cost、archive、
  recompute、curve/headroom/result 投影；优先复用 `selection/metrics.py`、`selection/release.py` 与 write-once 基元。若旧 schema 强绑定
  本地 raw logit/GPU 或三候选 selection，允许建立薄的 Plan 096 专用模块，不把不适用字段伪造成真实事实，也不复制第二套评价体系。
- `multidev/codex-rs/publication-critic/` 中仅为 DeepSeek V4 Flash 的显式 thinking/reasoning 配置、eval/reference-only scalar/usage
  观测或正确性所需的窄适配与测试。Plan 095 已验证的 Chat Completions 路径是默认起点，不为本任务增加新的 Responses API 或其它
  provider adapter。
  可以复用 `CloudPublicationScorer`/`RawScorerOutput` 建立独立 eval 入口，或采用其它更契合的等强设计；不能改变产品 wire/verdict 或默认路径。
- 与实际修改面相称的 `eval/tests/`、crate/Bazel/Cargo/uv 清单、锁文件、生成物和小型 fixture。若未改变相应依赖或生成输入，不为形式完整
  机械改锁。
- 一份小型受跟踪 pre-freeze 合同、`eval/results/publication-critic/` 下的正式 JSON/Markdown 结果及非门槛标签分歧投影；具体目录与 schema
  由执行者依据现有惯例选择。
- 本计划的“当前状态”和“关键决策记录”；执行期间受影响的 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md` 和精炼 Plan 096
  `agent_log`，以及首次独立审查接受后才追加的 `doc/WBS-COMPLETED.md` 与最终完成状态。
- 主物理根 task-owned ignored `eval-data/publication-critic/plan096/` 中的 commissioning/formal raw、usage、receipts、archive 与复算材料；
  以及确有需要的 ignored `rondo.local.toml` 非密钥机器配置。所有这些路径须在交付时单独报告用途、体积、权限与保留状态。
- 普通依赖下载、公开源码/官方 provider 文档只读查询，以及本计划已经授权的真实 API 调试、commissioning、正式 55 条和基础设施重试。

本计划不固定 module/file 布局、是否增加独立 eval binary、Rust/Python 之间的薄适配方式、provider adapter 的具体复用层、archive schema、
commissioning fixture 形状、逐项还是批量编排、有限 transient retry 策略或定向测试文件布局。执行者可依据 live code 与 provider 行为选择更优、
更干净的方案，只需满足数据、身份、费用、正式轮和产品不变边界。

### 允许只读核对

- 根/`multidev/` 规则、README、当前 WBS、Plan 054/055/064/066/068/071/073/079/094/095 的必要合同、最终结果与实施/验收日志，
  Publication Critic cloud scorer、selection metrics、validation release 和归档实现。
- 主物理根既有 Plan 066/073/079 ignored validation-only bundle/release 及相关 receipts，只用于确认/复用 55 条冻结输入与历史身份；
  不读取或搜索 mixed unseen 内容。
- 主工作区和其它 worktree 只做 Git 状态、共享重型资源与冲突保护核对；不读取其它 worktree 未提交内容。

### 不允许修改、读取或执行

- 不修改 v8 candidate、标签、split、pair、rubric、既有 quality floors 或历史 1.7B/4B 结果；不读取、释放、评分或上传 unseen-test，
  不用正式 validation 结果反向优化 prompt/model/sampling。
- 不改变 Publication Critic 产品 trait/service/wire/typed client/verdict、产品默认关闭、本地 worker、`team_publish`、Team State、两次重写与
  发布生命周期。为取得 curve 不允许反复改变产品 threshold 反推 scalar，也不新建自由文本 Judge、第二套产品服务或通用 provider 平台。
- 不训练、微调、量化、下载/转换新权重，不使用 GPU、RunPod 或 Docker，不创建/修改/删除远端资源，不发布或上传数据，不执行 Plan 097
  或 M3-D，不启用产品 cloud backend。
- `.env.local` 不允许打开、搜索、打印、复制、修改或 source；只能由既有严格 loader 静默检查存在、非符号链接、`0600` 及任务所需变量
  非空，并只向目标子进程注入必要变量。`rondo.local.toml` 不得保存 API key。
- 不改 `codex-source-code/`，不触碰其它 worktree 现场，不删除来源不明的既有 ignored/Git 资产，不扩大为 CI、PR、数据审计、可信、隐私、
  严格因果或通用预算平台。

## 3. 硬约束

以下约束只冻结结果成立所必需的数据、身份、评价、费用、正式轮、产品与交付边界；不锁死内部实现路线。

1. **同一 scorer，eval-only scalar。** 55 个正式 scalar 必须来自 Plan 095 同一 cloud prompt/projection、严格解析、requested model 与诚实
   scorer identity 的真实执行，不允许用产品 verdict 反推、另写一个语义不同的 prompt caller 或让 provider 直接决定 PASS/REWRITE。
   产品 client 当前只返回 verdict，因此允许增加职责明确的 eval/reference-only scalar/usage 接缝；该接缝不得成为产品 wire 或默认路径。
2. **先打通，再冻结，再运行。** synthetic/fake/loopback 和少量真实合成 packet 先完整覆盖 provider、scalar、usage、失败、恢复、55 项
   编排、curve/archive/recompute。只有全链闭合后才冻结 source/config/identity/data/metrics/cost，从新空 namespace 开始正式 55 条；不得为
   抢进度过早把尚未打通的流程称为 formal。
3. **冻结之后不看结果改尺子。** 正式第一份 validation score 产生后，不得改变 model/provider/API shape/effort/prompt/projection/domain/
   sampling/retry、validation release、curve/门限/headroom 规则后继续冒充同一正式轮。纯本地实现 bug 若确实使该轮无效，须窄修、重做必要
   commissioning 并从新的空 formal namespace 完整开始；含混是否属于模型有效失败时通过队列请求审查者裁定。
4. **成功不可覆盖，失败按原因处理。** 每个 formal namespace write-once，successful scalar 与有效负向分数不可覆盖或挑选；provider 已成功
   返回但模型拒答、malformed、out-of-domain 或其它有效模型失败不因不好看而重试。冻结 retry policy 内的网络/限流/上游暂时错误可作为同一
   logical call 的 attempts；超出该策略导致不完整时，保留原 attempt，只有确认是基础设施/实现问题才可在预算内从新空 namespace 整轮重跑，
   不拼接旧成功 rows。任务层不设机械重试次数，仍受 30 RMB、deadline 和原则边界约束。
5. **正式完整性先于质量终态。** 55/55、同一 freeze、零 duplicate/missing/typed failure 和可复算指标是四种研究终态共同前提；完整但负向
   的质量结果必须接受。正式结果及 authority 已形成后，off-path 归档/文档 bug 可窄修并定向验证，不因此重跑有效云端质量结果。
6. **费用是简单硬门。** 首次真实调用前用 provider 可核验价格形成保守 forecast，并为 formal 55 条与安全收口留足余额；每个 logical call
   记录可用 usage、实际 attempts、费用估算与无正文失败类别。usage 缺失时优先使用可核验账单差额或按冻结输入/输出上界和价卡保守估算；仍
   无法可靠核验时，每个实际发出的可能计费 provider HTTP request/attempt 按 `1 RMB/次` 保守计入，不建设通用 ledger。累计保守费用达到
   30 RMB 时停止新增计费动作并诚实收口。价卡若区分 cache hit/miss 而 usage 不足以区分，则把相关输入全部按较高的适用费率计算；非 RMB
   价卡使用 pre-freeze 绑定的保守换算口径。
7. **历史比较不制造等价。** 1.7B/4B 只比较相同 validation/label/pair/curve/gate 指标；cloud template 与本地 reward render/tokenizer 天然
   不同，因此结论是“scorer stack 在同一冻结任务上的参考上界”，不是模型参数规模或 prompt 的严格因果效果。现有 tracked 历史资产已足以
   确认 1.7B 身份，默认不重跑；只有实施中发现它不能按 exact release/metrics 复算时，才使用用户已授权的 narrow exact 1.7B validation
   对照，并与重型 Cargo、Docker和真实本地模型全局串行，仍不读取 unseen。
8. **默认关闭与秘密边界不变。** 未显式运行 Plan 096 eval 时不得读取目标 credential、探测 provider 或出网；真实请求/响应正文、packet
   正文、标签、密钥、endpoint 私有值不进入普通日志、tracked 结果、queue 消息或提交。允许归档 body-free scalar、usage、模型回显、
   failure kind、attempts、耗时与费用。
9. **唯一共享构建 target。** 一切重型 Cargo build/test 必须从 096 worktree 走仓库 `just`/`scripts/with-build-lock.sh` 正式入口，
   绝对只使用主物理仓库根 `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`；禁止在 worktree、`/tmp` 或其它位置新建第二套
   `target`，禁止直接 Cargo 绕过共享锁/看门狗，禁止提高既有并发。只跑最终 diff 所需模块，不跑全 workspace。
10. **授权外动作才请示。** 普通 provider、解析、恢复、费用、测试和归档问题在范围内自主收敛。只有需要扩大预算/数据/模型/产品合同、
    使用未授权外部状态、执行计划外高危动作，或遇到无法可靠归因的 formal failure 时，才通过指定队列请示审查者；不以文件、终端输出或
    人工提醒替代队列批示。
11. **Git 停止点。** tracked 工作只在 096 worktree。正式前允许为 clean source 提交 pre-freeze 实现，完成后必须把结果、文档、日志与
    全部剩余变动提交并保持 clean；不推送 task branch。未经用户批准不合并、不推送 main、不归档/重命名分支、不删除 worktree。
12. **跨会话请示与验收。** 执行者每条 queue 消息必须主动表明“我是 Plan 096 执行者”；发送后停止会话，不等待、不轮询、不重复发送。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a0446f-90bf-7a11-b8a1-de8cdd4a2b74 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。
```

```text
需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。
```

```text
执行者完成最终任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<执行者的完成汇报>”
其中
<执行者的完成汇报>就是执行者本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）执行者你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。
```

```text
执行者给审查者发送消息的时候，必须主动表明身份。
```

## 4. 软性建议

以下建议基于 `main@00502a9` 的 live code，只帮助执行者高效起步，不是固定路线。执行者可以采用更优、更简洁、与现有架构更契合的
等强方案，并在关键决策记录中简要说明有实质影响的选择。

- Plan 095 的 `CloudPublicationScorer` 已拥有真正的 `RawScorerOutput.scores`，而产品 service/client 有意只暴露 verdict。优先考虑在
  eval/reference 边界直接复用 scorer 的 prompt、strict parser、identity 与 lifecycle，补一个薄的 scalar/usage 观测入口；除非 live code
  证明更优，不要为了 curve 扩大产品 wire。
- Plan 095 已用 `deepseek-v4-flash`、Chat Completions、JSON object 与同一 template/projection 完成真实 smoke；优先保留这条已验证路径。
  四个成功 packet 的历史记录均包含 `prompt_tokens` / `completion_tokens`（935/896、873/153、935/970、873/432），证明该 provider shape
  能返回 token usage；现有实现只把这两个字段写到 stderr，历史没有 provider 实际金额。因此本任务宜把既有 usage 结构化带入 eval archive，
  再按冻结价卡计算。若 live response 还含价卡需要的 cache usage，可一并窄投影；否则把全部 prompt tokens 按较高的适用输入费率计算。
  无有效 usage/账单的可能计费请求才使用 1 RMB fallback。
  DeepSeek 官方接口支持 thinking 与 reasoning effort，而当前 descriptor 尚未显式表达这两项；可做窄配置适配，或在 freeze 中诚实绑定经
  commissioning 证明的 provider 默认语义。请求/effective model、thinking/effort、sampling、response model policy 与不可验证分量都应
  进入 freeze，不把 provider-managed marker 说成 provider 证明。
- Plan 095 的 `rondo-publication-cloud-template@v1` 与 `rondo-cloud-json-quality-scalar@v1` 是首选正式模板/投影。若 pre-freeze synthetic
  commissioning 暴露真实的 correctness/compatibility bug，可做最小语义修复并升版本/identity、重跑完整 commissioning；若变化会改任务
  rubric、输出含义或属于性能调优，应先通过队列请示。正式 validation score 产生后不再改。
- validation 输入优先复用物理无 unseen 的 Plan 066 bundle 与 Plan 073/079 canonical release；provider scoring 阶段只消费 candidate ID +
  packet，所有 scalar 封存后再在本地 join labels/pairs 计算指标。保持这种自然分层即可，不需建设新的盲化或数据审计设施。
- `selection/metrics.py` 已完整实现 curve 与质量门，但 `LabeledRow` 当前要求本地 `raw_logit`。云端没有真实 raw logit，适合做小幅
  score-only 泛化或薄适配，明确 raw logit 不适用；不要把 cloud scalar 复制到 raw-logit 字段伪造同类事实。
- archive 可复用 `WriteOnceNamespace` 和 Plan 079 的 spec/release binding、per-candidate immutable row、formal authority、独立复算思路，
  但不必继承 4B/GPU/snapshot schema。commissioning 可恢复，formal 空 namespace/write-once，已经足够，无需通用 transaction/audit 系统。
- 付费流程可按“离线 fake 55 → 少量 DeepSeek V4 Flash 合成 packet → usage/价格/恢复闭合 → pre-freeze commit → 空 namespace 55 条 formal → 独立复算”
  递进。并发 1 通常最容易控制费用、顺序和 provider 限流；若实测支持其它安全方案可自主选择。
- 正式分歧清单只列 selected operating point 下 label 与 verdict 不同的 candidate ID、score/margin、错误类型和必要 slice 元数据；它是未来
  数据复核线索，不是本任务改标签或增加门限的入口。
- exact 1.7B v8 历史报告已包含 55 row 与同口径 metrics，当前没有重跑理由。若后续真的触发条件性重跑，先关闭/等待 Cargo 和其它真实
  本地模型资源槽，复用既有重型 lifecycle，不下载新权重、不用 Docker。
- 定向测试优先覆盖 DeepSeek thinking/reasoning request 与 Chat Completions response shape、strict scalar/identity/usage、score-only curve、
  55 ID 完整性、headroom 四分支边界、
  commissioning/formal 隔离、write-once、重算、`1 RMB/未知请求` fallback 与 30 RMB stop。再按真实 diff 选择 crate tests、eval unittest、
  fmt/fix/clippy/lock check；
  不复制 Plan 095 全矩阵，也不重跑完整 workspace。

### 建议执行步骤

1. 核对 live code、ignored validation-only assets、DeepSeek V4 Flash provider 能力与真实配置可用性；先在离线环境确定最小 scalar/usage
   和 archive 接缝。
2. 实现或窄泛化所需能力，使用 fake/loopback 55 项和定向测试闭合完整 lifecycle、curve、恢复、费用与复算。
3. 离线门禁通过后，以少量合成 packet 进行 DeepSeek V4 Flash 真实 commissioning；保留已验证进度，自主修复普通
   provider/解析/timeout/usage 问题。
4. 全链打通后提交 pre-freeze clean source，冻结非密钥 spec、identity、data/metrics/headroom、价格与 namespace；确认 30 RMB 余额足够。
5. 从新空 namespace 完整执行正式 55 条；不选择性覆盖。完成后用独立入口复算 curve、唯一终态、历史对照和分歧清单。
6. 运行与 diff 相称的定向门禁，检查费用、default-off、主物理 ignored 资产、共享 target、worktree/主工作区状态和未运行项；更新
   plan/WBS 当前状态与实施日志并提交，通过指定 queue 主动表明身份请求首次独立审查，然后停止会话。
7. 被审查者唤醒后自主收敛 finding；首次独立审查接受后再追加 `doc/WBS-COMPLETED.md`、WBS 最终状态与最终日志并提交全部变动。随后按用户
   指定的最终消息模板 queue 完成交付摘要并停止会话；若被唤醒要求窄修，修复、提交并发送一条新的完成汇报后再次停止。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-27：确认主工作区 clean，`main = origin/main = 00502a9cc94a3a69f7ecb46a6aec7c8a371e62b1`；既有 093/095 worktree
  保持不动。
- 2026-08-27：从上述 clean main 创建
  `.claude/worktrees/096-validation-cloud-scorer-qualification` / `worktree-096-validation-cloud-scorer-qualification`。
- 2026-08-27：只读核对根/`multidev/` 规则、README、顶层/三期 WBS、plan 模板、Plan 054/064/066/073/079/094/095、相关结果/日志、
  Plan 095 cloud backend、Plan 073 metrics/release、Plan 079 archive 和主物理 ignored 资产边界；完成三路并行只读研究。
- 2026-08-27：确认 exact 1.7B 与 4B tracked 历史结果都绑定同一 canonical v8 validation release，现有资产足以同口径比较，不计划
  条件性 1.7B 重跑；确认产品 typed client 不暴露 scalar，因此只需补 eval-only scalar/usage 与批量归档接缝。
- 2026-08-27：用户在计划讨论中将正式模型统一改为 `deepseek-v4-flash`。Plan 095 已真实验证其 Chat Completions + JSON output 路径，
  因此不再为 Plan 096 增加新的 Responses API/provider shape；正式 headroom 解释为该冻结 scorer stack 的模型条件参考上界。
- 2026-08-27：用户将真实 API 总硬上限调整为 30 RMB，并指定不能可靠核验费用的实际可能计费 provider HTTP request/attempt 按
  1 RMB/次保守计入。Plan 095 的四次成功 DeepSeek 历史调用均返回 prompt/completion usage，但没有实际金额；本计划据此优先结构化归档
  usage 并按冻结价卡计算，只对无法可靠核验者使用 1 RMB fallback。
- 2026-08-27：按 OpenAI 官方 Graders API 窄核对，score model grader 的职责是用模型为输入分配 score，且 model grader 使用结构化输出；
  本任务继续采用 typed scalar + curve，而不增加自由文本 Judge。
- 2026-08-27：编制本 ExecPlan，预冻结既有质量门与新的 headroom 三分规则，并最小同步顶层/三期 WBS 的 Plan 096 当前工作包与 Plan 097
  条件依赖；没有运行 API、构建、测试、Docker、GPU、RunPod 或本地模型。
- 2026-08-27：执行者完成 live code 与允许资产复核：Plan 079 canonical validation release 的 canonical SHA-256 为
  `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`，Plan 066 bundle verifier 确认 55/26 validation、
  unseen row/body 为 0；exact 1.7B/4B tracked 结果足以同口径比较，不触发 1.7B 重跑。
- 2026-08-27：核对 DeepSeek 官方 Chat Completions、thinking 与人民币价卡：`deepseek-v4-flash` 当前支持 JSON output，thinking 默认
  enabled、effort 默认 high；首次实时刷新发现价卡已改为北京时间峰谷分档，谷时每百万 cache-hit input `0.05 RMB`、cache-miss input
  `1.5 RMB`、output `4.5 RMB`，峰时为其两倍。当前谷时窗口适用，首次真实调用尚未发生；freeze 将绑定来源 URL、核对时点与实际 descriptor。
- 2026-08-27：完成 eval-only Rust scalar/usage observation、one-shot binary、Python freeze/cost/archive/runner/recompute/history 接缝；
  94 项相关 Python 测试、62 项 crate 测试、Clippy、fmt 与 55 条 compiled-binary loopback commissioning 均通过，loopback 为 55/55、
  零 typed failure、55 HTTP attempts。严格 secret loader 的零输出 credential 门禁通过，仍未发送真实请求。
- 2026-08-27：首轮真实合成 commissioning 在冻结的 4096 output-token 上限下完成 55 次单 attempt：54 个成功 scalar，1 个响应恰好
  `completion_tokens=4096` 并因截断成为 `provider_malformed_response`，累计 `0.3987545 RMB`。该轮作为无效 commissioning 保留且不拼接；
  模型、prompt、默认 thinking/high effort 与严格 parser 不变，仅把 output 上限提升到 8192 后重新验证并使用新 clean commit/namespace。
- 2026-08-27：在 source commit `7bdcad9196d4e7a2de39f6618e0d193476b0d6e6` 与新 8192 namespace 上完整重跑真实合成
  commissioning：55/55 成功、55 attempts、零 typed failure，费用 `0.3548550 RMB`；随后冻结 validation release、descriptor、静态合同、
  binary/environment 与价卡，formal freeze SHA-256 为 `4497883159a2d278ca6611b6b6ce4101efec09d56f319e357c9214fbfd31836b`。
- 2026-08-27：从全新空 namespace `plan096-formal-20260827T201304Z-validation-55` 完成唯一正式轮：55/55 有限 scalar、零最终
  typed failure、56 次 provider attempts。`pc064-rpg-webhook-mask-rewrite` 首次出现冻结 retry policy 允许的
  `ProviderTransientFailure` 且无 usage，保守计 `1 RMB` 后同一 logical call 第二次成功；没有选择性重跑有效模型结果。
- 2026-08-27：正式轮独立复算与 archived result 逐字段一致，终态为
  `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`。选定 fallback threshold `0.9`：False PASS `8/21`、False REWRITE `0/34`、
  balanced accuracy `0.809524`；ROC AUC `0.840336` 与 Boundary strict win `15/19` 均过 threshold-free 门，但不存在满足全部质量门的
  admissible operating point，因此 Plan 097 不解锁。正式费用 `1.3855704 RMB`，Plan 096 三轮真实调用累计 `2.1391799 RMB`，预算余量
  `27.8608201 RMB`。
- 2026-08-27：生成 tracked JSON/Markdown 结果与精炼实施日志；task-owned ignored archive 位于主物理根
  `eval-data/publication-critic/plan096/`，不含 provider 正文、credential 或 unseen。首次独立审查接受前不写
  `doc/WBS-COMPLETED.md`。
- 2026-08-27：首次独立验收接受唯一正式轮、费用、重试、数据外发、产品不变性、独立复算与研究终态，但以 0 High / 1 Medium
  暂不通过：已有 `formal-authority.json` 时，不同 formal `run_id` 仍会先创建 namespace 并评分，直到 claim 阶段才拒绝。
- 2026-08-27：finding 已窄修。archive 新增与 Plan 079 同职责的 `require_formal_unclaimed()`，runner 在 validation release 处理、namespace
  创建和 evaluator 调用前执行 authority preflight；末尾 atomic claim 继续承担并发兜底。离线回归先形成 authority，再用不同 `run_id` 验证
  typed `formal_result_already_authoritative`、evaluator 0 调用、authority bytes 不变且新 namespace 不存在；相关 Python 测试 95/95 通过。
  未运行真实 API，既有正式结果、tracked projection、费用与终态不变。
- 2026-08-27：返修复验提交 `8d1640e` 以 0 High / 0 Medium / 0 Low correctness finding 接受首次独立验收；审查确认 authority
  preflight 时序、95/95 相关 Python 回归、formal/result/price/cost 零漂移与 Plan 097 锁定均成立。按 decision 013 完成
  `doc/WBS-COMPLETED.md`、WBS 最终状态和最终日志收口；未重跑真实 API、Rust 重型门禁或全 workspace。

### 当前工作

- `COMPLETED`：实现、正式运行、结果归档、finding 返修、首次独立验收和最终文档收口均已完成；task branch 只待用户决定是否合并、推送或归档。

### 本任务剩余步骤

- 本任务内无剩余实施步骤；提交最终收口并按用户指定模板通过 queue 通知审查者后冻结本计划。后续路线只以 WBS 为准。

### 阻塞项

- 无。

### 当前验收状态

- `COMPLETED / FIRST_INDEPENDENT_REVIEW_ACCEPTED / GOAL_COMPLETED /
  CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH / NOT_INTEGRATED / NOT_PUSHED`。

### 交接边界

- 执行者在既有 096 worktree 内完成实现、验证、真实 API、正式结果、记录和 task branch 提交；本计划制定者作为指定 thread 审查者验收。
- 只有 `CLOUD_SCORER_QUALIFIED` 解锁 Plan 097 的另行立项入口；其它终态或 formal incomplete 均不启动 097。Plan 097 的具体范围、授权与
  执行不属于本计划。
- Plan 096 完成后冻结本计划；未经用户批准不合并、不推送、不归档/重命名分支、不删除 worktree。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 096 是 Plan 095 后端的 validation 资格/参考上界任务，不改变 Publication Critic 产品行为 | 把 backend 接入与质量测量分开，避免 reference 结果自动产品化 | WBS、产品边界 | 已采纳 |
| 002 | 正式模型冻结为 `deepseek-v4-flash`；换模型须 queue 批示 | 用户确认该独立 scorer 不受 Codex 主模型兼容性约束，并优先复用 Plan 095 已验证且更经济的 Chat Completions 路径 | 模型、identity、formal | 已采纳 |
| 003 | 资格门沿用 Plan 073/079 发布质量门，不沿用 Plan 068/071 本地 deployment 资格门 | 本任务回答 55 条任务质量，不回答 CPU/CUDA/worker 部署可比性 | metrics、终态 | 已采纳 |
| 004 | 新 headroom 规则只用既有两个 threshold-free 门：都过为 HIGH、都不过为 LOW、一过一不过为 INCONCLUSIVE | 不引入结果后新数字，能区分校准/表达问题与任务分辨不足 | 终态 | 已采纳 |
| 005 | 产品 typed client 继续只返回 verdict；允许 Plan 096 eval-only scalar/usage 接缝 | operating curve 必须保存 scalar，但把 raw score 加入产品 wire 会扩大产品语义 | 架构、允许写集 | 已采纳 |
| 006 | commissioning 可恢复，formal 必须空 namespace/write-once/55 完整且不可拼接 | 给普通故障修复足够冗余，同时避免选择性覆盖正式质量结果 | 运行、归档 | 已采纳 |
| 007 | 1.7B 对照引用 Plan 073 exact base，4B 引用 Plan 079；当前不重跑 1.7B | 两者已有同 release、55 rows 和可复算指标；Plan 054 的 16 条 baseline 不可冒充 v8 对照 | 历史比较、资源 | 已采纳 |
| 008 | 真实 API 总硬上限为 30 RMB；按 provider 价卡/usage/账单累计，仍无法核验时每个实际可能计费 HTTP request/attempt 按 1 RMB/次计入 | 采用用户为 DeepSeek 指定的新预算与保守费用兜底，同时让可核验的 55 次正式 usage 按实际价格计算 | 费用 | 已采纳 |
| 009 | 构建绝对复用主物理根唯一 `rondo-multi` target，不允许 worktree 自建 target | 遵守用户强调与全局资源门禁，避免重复构建占用 | 构建、宿主资源 | 已采纳 |
| 010 | 额外请示、计划外不确定性和最终验收只走指定 queue，主动表明身份，发送后停止且不重复 | 遵循用户指定的跨会话审查机制 | 协调、交付 | 已采纳 |
| 011 | 完成后只提交 task branch；合并、推送、归档和 worktree 删除等待用户批准 | 本轮授权明确停在本地工作树提交与审查 | Git | 已采纳 |
| 012 | headroom 是 DeepSeek V4 Flash scorer stack 在同一冻结任务上的模型条件参考上界，不称所有强模型的理论极限 | cloud/local template 与具体模型共同构成被测 scorer，需避免过度外推 | 结论解释、历史比较 | 已采纳 |
| 013 | WBS-COMPLETED 与最终完成状态只在首次独立审查接受后同步 | 保持完成历史只记录已接受结果；执行细节与待审状态先留在 plan/WBS/实施日志 | 文档、审查顺序 | 已采纳 |
| 014 | Rust 侧在同一 `CloudPublicationScorer` 增加 eval-only body-free scalar/usage observation 与 one-shot binary；Python 侧建设薄的 Plan 096 runner/archive/recompute，复用既有 release、metrics 与 write-once 基元 | 保持 prompt/retry/parser/identity 单一来源和产品 wire 不变，同时让费用、恢复、curve 与独立复算各归其职责 | 架构、测试、归档 | 已采纳 |
| 015 | Plan 096 不为形式完整改变 Plan 095 已验证请求：Chat Completions 继续省略 `thinking`/`reasoning_effort`，freeze 绑定 provider 官方当前默认 enabled/high，并把实际 serving 语义记为不可验证 | 省略值正是已 commissioning 的 scorer stack；显式补发虽可能等价，却会无必要地改变正式被测请求 | provider、freeze、解释 | 已采纳 |
| 016 | 价卡在首次真实请求前重新刷新并冻结当前北京时间谷时档 `0.05/1.5/4.5 RMB/M`；官方文档版本 `DeepSeek-V4-Flash-0731` 只作说明，实际 serving revision 仍不可验证 | 官方价格发生了时变更新且引入峰谷档；不能沿用早期快照，也不能把公开版本标签误写成单次响应证明 | 费用、identity、formal | 已采纳 |
| 017 | 真实合成 commissioning 证明默认 high thinking 会偶发吃满 4096；保持 scorer 语义不变，仅把 `max_output_tokens` 与允许上限提升到 8192，并从新 clean commit/namespace 完整重跑 | 截断有完整 usage 且严格 parser 正确拒绝，属于 formal 前应修复的请求容量兼容性问题；不能重试该有效失败后与旧成功拼接冒充同配置结果 | provider、descriptor、commissioning | 已采纳 |
| 018 | 正式轮只对一次 `ProviderTransientFailure` 按冻结 retry policy 在同一 logical call 内重试；无 usage 的首次 attempt 按 1 RMB fallback 计费，不重跑任何有效 scalar 或负向质量结果 | 区分获准的基础设施恢复与禁止的结果选择；保留完整 attempt provenance 与 55 个唯一最终 observation | formal、费用、恢复 | 已采纳 |
| 019 | 正式终态冻结为 `CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`，不解锁 Plan 097；tracked 结果同时保留资格失败与高 headroom 两层事实 | 完整 curve 无 admissible operating point，但两个预冻结 threshold-free 门均通过，不能把校准/error trade-off 问题误写为低任务分辨能力 | 结论、WBS、交接 | 已采纳 |
| 020 | formal runner 在处理 release、创建 namespace 与调用 evaluator 前，先由 archive 校验根级 authority 未被 claim；末尾 atomic claim 保留为并发兜底 | 已有 authority 时继续评分会重复外发有效 validation 并产生费用；前移现有门禁即可闭合，无需引入通用锁或新状态机 | formal、archive、费用安全 | 已采纳 |
| 021 | 首次独立验收复验 0/0/0 后，按 decision 013 将任务收口为 `GOAL_COMPLETED`，同时保留 scorer `NOT_QUALIFIED` 与 Plan 097 不解锁 | 研究任务已得到完整、可复算且验收接受的唯一质量终态；任务完成不等于被测 scorer 获得产品或后继资格 | WBS、历史、交付 | 已采纳 |
