# Plan 095：Publication Critic 云端参考 Scorer 后端接入 ExecPlan

> 本计划是 Plan 095 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并按本计划指定的跨会话队列请求审查者批示。
> 普通代码、编译、依赖、provider、限流、结构化输出解析、timeout、identity 配置和模板问题，应在既有范围与预算内自主修复并按需重跑，
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 095；跨任务路线、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 RONDO Multi 已有 Publication Critic 服务边界内新增一个云端大模型 API scorer backend，使它与 Plan 068 的本地 worker backend 并列、
可显式选择且保持 eval/reference-only。相同的 `PublicationPacket` 继续经过现有 `PublicationScorer`、service identity、单标量到
`PASS/REWRITE` 的 verdict 合同和 typed client；云端实现只负责有界构造请求、调用 provider、严格解析一个有限标量并返回既有
`RawScorerOutput` 或既有 typed backend failure。

先使用 fixture/fake/loopback provider 打通完整离线生命周期；随后在本次已授权的预算内用合成测试 packet 做少量真实 API
commissioning，保留已经验证的进度并从首个未打通处边修边跑。全链稳定后冻结 clean commit、非密钥配置、provider/model/scoring
identity 与 backend 模板，从新的小型运行空间完整执行一轮真实 API smoke，作为正式真实证据。该任务不做质量横评、threshold 标定或
产品启用，也不延续 Plan 094 的训练路线或解锁 M3-D。

### 完成/验收标准

- [ ] 新 backend 通过现有 `PublicationScorer` 接缝在同一 service 协议内启动、ready、校验 expected identity、打分、返回
      `PASS/REWRITE` 或 typed failure，并能有界关闭回收；不建立第二套服务协议、客户端或控制面。
- [ ] 云端 backend 的显式选择路径完整且默认关闭：未选择时不解析 secret、不探测 provider、不产生网络出口，也不要求 cloud credential；
      既有受控 scorer、本地 worker、Publication Critic 默认关闭与 `team_publish` 行为保持不变。无副作用的 client 对象初始化不是验收边界。
- [ ] provider 输出只能严格投影为声明 domain 内恰好一个有限标量；现有 service 继续负责 model/scoring identity 复验和按现有
      threshold/pass rule 生成 verdict。解析失败、拒答、非 2xx、限流、连接错误、超时和取消不能伪装成业务 verdict。
- [ ] 云端无法提供可验证 tokenizer、serving revision 或其它身份分量时，expected/observed identity 显式表达
      `unverifiable/provider-managed` 语义，并明确 service 的 equality check 只验证配置一致，不冒充 provider 侧可验证身份；不得用看似
      exact 的占位 revision 伪装成与本地工件同级。
- [ ] 使用 fake/loopback provider 和真实 Publication Critic service 入口覆盖 Plan 055 既有受控后端矩阵在云端 backend 上的适用项：
      startup/readiness、identity match/drift、有效标量与 `PASS/REWRITE`、malformed/out-of-domain、typed provider failure、job timeout、
      queued/in-flight cancel、并发 1/队列 4/queue-full、故障后健康请求、graceful/forced shutdown 与资源回收；测试不依赖真实 API 或长
      `sleep` 竞速。
- [ ] 用同一组窄 fake/loopback 测试确认 absent/local/controlled 等非 cloud 选择不要求 cloud credential 且 provider 零请求；provider
      错误正文或 credential sentinel 不穿透 typed failure、普通日志或输出。若 endpoint 可配置，还须拒绝把凭据嵌入 endpoint 的配置形状。
- [ ] 至少一轮新的 clean 小型真实 API smoke 从正式 service/selection 路径消费合成 `PublicationPacket`，得到合法 typed verdict，
      并证明网络调用确实到达选定 provider；commissioning 与 clean smoke、fake 与 real、成功与失败、保守费用和未运行项分开记录。
      是否用两条明显正反合成稿取得两个 verdict 由实际稳定性决定，不为凑 `PASS/REWRITE` 修改最终 threshold 或扩大为质量测评。
- [ ] 真实 smoke 只发送本任务合成、无密钥、无私有项目数据的 packet；不上传真实 publication、transcript、Fact 正文、训练/测评数据、
      v8、unseen、模型、项目源码或其它项目数据。真实/运行时 provider 请求与响应正文、Authorization、API key 不进入普通日志、错误、
      提交或最终报告；允许跟踪为严格解析测试所需的最小、无秘密合成 fixture。
- [ ] 真实调用、可选 Docker/smoke 与任何可能计费的外部动作合计不超过 50 USD；不设机械轮数上限但受总预算约束。明确不计费的动作记 0，
      任何不确定是否计费或已计费但金额未知的事件按 1 USD 保守计入，不以耗尽预算为目标。
- [ ] 既有本地 worker 路径及其定向测试无回归；`team_publish` 接入/default-off 的代表性聚焦回归通过。只运行受影响 crate 和必要相邻
      模块的格式、lint、生成物/锁文件检查与定向测试，不运行全 workspace。
- [ ] 完成 diff/允许写集、ignored/宿主副作用、费用与未运行项检查；普通 finding 由执行者自主窄修并重跑相关门禁。完成后只提交 095
      worktree 本地分支并保持 clean，通过指定队列请求审查者验收；不合并、不推送、不归档/重命名分支、不删除 worktree。

## 2. 范围

### 允许修改

- `multidev/codex-rs/publication-critic/` 内职责明确的云端 scorer backend、显式 backend 选择/启动入口、cloud request/response
  适配、严格配置、body-free 错误与定向测试。可以新增兄弟模块、测试 fixture 或复用同一 service 的新启动入口；不能复制服务协议。
- 云端 backend 所需的版本化 prompt/structured-output schema/descriptor 示例。它们必须绑定独立的 cloud scoring identity，不改写或冒充
  既有本地 reward-model render/template identity。
- 因上述实现确实需要的 `multidev/` Cargo/Bazel 清单、锁文件、Nextest setup、生成物和小范围测试设施重构。
- 若现有职责确实契合，可窄复用已有 HTTP/provider/config/secret loader；若强行复用会把 eval campaign、Codex 主模型或本地 worker
  语义耦合进 scorer，可增加最小的 Publication Critic 专用适配。不得建设第二套通用 provider、配置、预算、trace 或归档平台。
- 仅在 live code 证明选择路径需要稳定配置接口时，精炼更新受跟踪的 `rondo.local.example.toml`、`rondo.secrets.example.env` 及其既有
  loader/tests；优先复用已有 allowlisted key name，不预设必须新建 profile 或 API 协议。
- 本计划的“当前状态”和“关键决策记录”；完成实现时受影响的 `doc/WBS.md`、
  `doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md` 与一份精炼 Plan 095 `agent_log`。
- 普通依赖下载、公开源码/官方 API 文档只读查询，以及用户已授权的少量真实 API 调试、可选 Docker 与 smoke。Docker 不是完成目标的
  必选项；职责不需要时不为形式完整而运行。

本计划不固定 cloud 模块名、是否增加独立 binary、HTTP client/provider adapter 的具体复用层、配置字段、prompt 文案、structured-output
API 形状、有限 retry 策略或测试文件布局。执行者可依据 live code、provider 行为和维护成本选择更优方案，只需满足产品合同、预算、安全与
验收边界。

### 允许只读核对

- 根/`multidev/` 规则、README、当前 WBS、Plan 053/055/057/068、Publication Critic 产品合同、相关实现/测试、公开 Git 历史与官方
  provider API 文档。
- `eval/` 中已有通用 provider/config/secret 与真实调用模式只用于判断职责是否契合；不得把方向 0 的 campaign/ledger/结果体系整体搬入
  Publication Critic。
- 主工作区和其它 worktree 只做 Git 状态、共享重型资源和冲突保护核对；不得读取其它 worktree 未提交内容。

### 不允许修改或执行

- `PublicationScorer` trait 语义、`RawScorerOutput`/`ScorerError` 基本合同、`service.rs` 核心、Plan 055 transport/client/resource
  合同、`PublicationPacket`/既有 render、`team_publish` 接入与既有 `real_scorer.rs` 本地 worker 路径。为测试复用做不改变行为的窄整理
  也应优先避免；若身份诚实在现有 public identity 形状中确实无法表达，必须先通过指定队列请求计划变更，不能自行扩大公共合同。
- 最终 threshold、质量门、operating point、selection lock、批量测评、冻结 v8 train/validation 正文、unseen、训练、量化或模型选择。
  本任务 descriptor 中的 threshold 只能是显式非最终的 reference/smoke 配置，不能继承或冒充 Skywork 的最终标定。
- Publication Critic 产品默认启用、云端 backend 成为默认、第二套服务/协议/client、第二套 trace/archive、通用 daemon supervisor、
  provider 平台、复杂鉴权、审计/可信/因果/隐私平台或与本任务无关的重构。
- GPU、RunPod、真实本地模型加载/推理、模型权重/adapter、unseen、项目数据上传、外部发布、CI/PR、全 workspace 测试或上游基线升级。
- 修改宿主机配置、全局工具链、系统服务、其它仓库、其它 worktree 或来源不明资产；清理非本任务创建的 Docker/临时/ignored 对象。
- 未经用户后续批准合并/rebase/cherry-pick 到 main、推送任何分支、归档/重命名分支或删除 worktree。

### 不允许读取/查看

- `.env.local` 内容。只允许既有严格 loader 静默确认它是主物理根普通非符号链接文件、权限 `0600`，以及所需 allowlisted 变量存在且
  非空；不得 open/search/print/copy/source，且只向 cloud scorer 目标进程注入所需变量。
- v8 unseen-test 或任何需要先读取 mixed 数据再过滤的路径；真实 publication/transcript/private reasoning、Fact observation 正文、
  模型权重、其它任务 ignored 原始 payload/response 或项目外个人文件、凭据和私有数据。
- 其它 worktree 的未提交文件内容；只可检查 Git 元数据和公开已提交内容保护并行工作。

### Git-ignored、主物理根与宿主副作用

所有 tracked 修改在以下 095 worktree 完成并提交，主工作区不得产生 tracked diff：

`/home/sjc/desktop/RONDO/.claude/worktrees/095-publication-critic-cloud-reference-scorer/`

下列事项因 linked worktree/宿主机制可能必须直接发生在主物理根或 Docker daemon，执行者须在最终汇报中单独列出实际发生项；规划阶段均未
创建或修改：

- 重型 Cargo 只能从 095 worktree 使用 `multidev/justfile` 的正式入口，经共享锁/看门狗自动复用主物理根
  `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`；不得显式另建 worktree target。该 ignored target 是可再生共享缓存，
  不是交付物，也不是本任务清理对象。
- 主物理根 `.env.local` 只由上述严格 loader 使用，不手工修改。若真实运行确需补齐/调整非密钥 provider/model/endpoint 选择，可对主物理根
  ignored `rondo.local.toml` 做最小任务内修改，并报告修改的配置职责；不得写入 key、复制内容到 worktree 或提交真实 endpoint/model 私有值。
- 真实 API 的临时响应/调试/smoke 工件优先使用 `/tmp` 并清理；只有确有复核价值时才允许保留在主物理根 task-owned ignored
  `eval-data/publication-critic/plan095/`。若创建，最终只报告路径、用途、大致体积、权限与保留/清理状态，不建逐文件审计台账，不提交正文。
- 如确需 Docker，只处理一个明确镜像/任务、并发 1，并与重型 Cargo、真实本地模型互斥；运行前后记录 `docker system df` 与 Windows
  `C:` 实际余量，只清理本任务精确创建对象。Docker 增长 40GB 告警、60GB 停止保持不变；本任务 Windows `C:` 余量停止线按用户授权
  临时改为 30,000,000,000 bytes，只通过该次命令/监督上下文覆盖，不修改受跟踪默认阈值。若现有入口不支持安全的任务级覆盖且 Docker
  确实必需，先用指定队列请求审查者决定，不为此扩建监督平台。

## 3. 硬约束

以下约束只冻结现有产品语义、外发/秘密、费用、资源和交付边界；不锁死内部实现路线。

1. **只增加 backend 与选择路径。** 云端 scorer 必须进入 Plan 055 同一 `PublicationScorer → service → typed client` 链；现有 trait、
   packet/render、service verdict/resource 核心、`team_publish` 和本地 worker 路径不变。允许增加同一 service 的启动选择入口，不允许并行
   发明另一套 service/wire/client 或绕过 service 直接给产品 verdict。
2. **单标量与 threshold 合同不放宽。** cloud response 最终只能产生声明 domain 内恰好一个有限 scalar；现有 service 按既有
   scoring identity、threshold 与 `>=` pass rule 形成 `PASS/REWRITE`。多标量、任务分解、直接让 provider 决定业务 verdict 或解析失败
   默认 PASS/REWRITE 都不在本任务。
3. **identity 必须诚实。** provider/model/requested revision 与 cloud prompt/projection/domain/非最终 threshold 应进入可信配置和
   expected identity；provider 无法证明 tokenizer/serving revision 时必须显式标为不可验证/provider-managed。service equality 不能被
   描述成 provider 身份证明；响应中可可靠观察到的 model drift 应拒绝，无法可靠观察的分量不得伪造 exact 值。
4. **default-off 且只有显式选择才出网。** 未配置或选择 cloud backend 时不得读取 secret、做 provider readiness、后台 retry 或发送
   请求，也不得要求 cloud credential；无副作用的 HTTP client 对象初始化不作为硬边界。选择 cloud backend 后，允许执行者按 provider
   需要做有界、预算内且不发送 packet 正文的 readiness/model-metadata 校验，实际 review/显式 smoke 才能发送 packet；不得付费预热，
   不静默 fallback 到另一个 provider/backend，不改变产品默认 backend。
5. **failure、deadline、cancel 与资源门服从现有 service。** 云端调用必须在现有有界 `RuntimeLimits` 所声明的 job deadline、并发、
   队列、shutdown 和 cancellation 语义内完成，future 被取消/丢弃后不得留下应用层 detached retry 或继续占用本任务资源。有限
   provider retry 可由执行者决定，但必须服从
   同一 deadline/cancel/预算；identity/shape/认证等原则错误不靠重试掩盖。默认 25 秒是否适合真实 provider 由 commissioning 证明，
   可在既有最大 5 分钟合同内通过 descriptor 选择相称数值并对齐 client timeout，不修改 `resource.rs` 的边界或引入无界等待。
6. **外发和日志最小化。** 生产能力只发送既有 bounded `PublicationPacket` 的 cloud-template 投影，不增加私有字段；本任务真实 smoke
   只用合成 packet。认证、真实/运行时 provider request/response body、真实 candidate/context、原始 provider error body 不进入普通
   日志、错误展示、tracked artifact 或队列消息；仅保留 body-free identity/failure kind/耗时/usage/费用摘要。严格解析测试所需的最小、
   无秘密合成 fixture 可以跟踪。
7. **简单预算门。** 本任务真实 API、Docker/smoke 及相关可能计费外部动作总额硬上限 50 USD；每次可能计费动作前保留足够余额，累计保守
   值达到上限即停止新增计费动作并安全收口。轮数不限只表示不因固定 retry/commissioning 次数停工，不覆盖预算、deadline 或取消。
   确定免费记 0；不确定是否计费或金额未知记 1 USD。使用一份简单任务内累计即可，不建设预算平台或追求花完额度。
8. **先离线、再 commissioning、最后 clean smoke。** 离线 fixture/fake/loopback 必须先通过完整 service 生命周期和故障矩阵，才进入真实
   API。commissioning 可保留已验证节点并从未打通处窄修续跑；全链稳定后冻结 clean commit/config/identity/template，从新运行空间完整
   跑一轮小型真实 smoke。正式证据不拼接调试轮，不把真实 smoke 冒充批量质量测评。
9. **普通问题自主收敛，原则变化才请示。** provider 报错、限流、结构化输出、timeout、identity 配置、模板、编译、测试和 fixture 等
   普通问题在范围/预算内自行修复、重试或重跑。只有计划边界/预算/产品合同改变、必须使用未授权外部状态/数据、出现预期外高危动作，或
   合理修复后仍无法满足原则性完成门时，才通过指定队列请示审查者。
10. **定向验证与诚实证据。** fake、真实 API、可选 Docker、静态检查与未运行项分层报告；skip 不算通过。重型 Cargo 必须走共享入口并
    使用主物理根共享 target，C: 30GB 仅作本次运行时覆盖。只跑 `codex-publication-critic` 与实际受影响相邻模块的必要门禁，不跑全量
    workspace，不为本任务建立 CI/PR 或复杂审查设施。
11. **Git 停止点。** 所有 tracked 工作只在 095 worktree；完成全部变动、测试和精炼日志/WBS 后提交并保持 clean，再按指定队列通知
    审查者并停止会话。未经用户批准不合并、不推送、不归档/重命名分支、不删除 worktree；主工作区和 093 worktree 保持不动。
12. **跨会话请示与验收。** 额外授权、计划外变数、不确定事项和最终任务验收只使用下述 Codex 跨会话队列。执行者每条消息必须主动表明
    “我是 Plan 095 执行者”，发送后停止会话，不等待、不轮询、不重复发送。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a0433c-df76-7cc1-8568-f490f27ed8e7 替换。
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

以下建议基于 `main@76f3539` 的 live code，仅帮助执行者高效起步，不是固定路线。执行者可采用更简洁、优雅、与现有架构更契合的等强或
更优方案，并在关键决策记录中简要说明有实质影响的选择。

- `publication-critic/src/scorer.rs` 与 `service.rs` 已是 backend-neutral；优先把 cloud scorer 做成 `real_scorer.rs` 的兄弟实现，并让
  选择/启动层组合现有 `serve()`。增加独立 cloud binary、对既有 launcher 做不影响 local 路径的 additive 选择，或其它更干净方案均可。
- HTTP/provider 侧优先复用仓库已有、职责匹配且不会把 `codex-core` 或完整 eval campaign 拉进来的客户端能力。若依赖面反而更重，专用的
  小型 adapter 可能更合适；无论哪种都应使用 HTTPS、拒绝 credential-bearing URL、默认不跟随跨端点 redirect，并在测试中用 loopback
  provider 注入，不必建设通用多 provider 框架。
- cloud prompt 可消费既有 typed packet 的稳定 JSON 投影与产品 rubric，但应拥有独立、版本化的 cloud template identity；不要声称与本地
  reward-model chat render/tokenizer 逐 token 等价。structured output 优先直接请求 `[0,1]` quality scalar，让现有 service 做 threshold
  verdict；若 provider API 的原生 schema 不足，可用同样严格的最小解析层。
- 若现有 `ModelIdentity.tokenizer` 字段足以用明显不可混淆的 component（例如语义明确的 provider-managed/unverifiable 标记）诚实表达，
  优先不改 identity 类型，并在 descriptor/test/log 文案中说明其不是校验过的 tokenizer revision。只有确实无法等强表达时才请求范围变更。
- readiness 可基于完整、有效且 identity-bound 的 cloud 配置，而不必为“就绪”发送付费探针；实际 provider 可用性由首次 review/显式 smoke
  的 typed 结果体现。若 provider 提供免费且可靠的 model metadata，也可使用，但不得让默认/off 路径出网。
- retry 只用于有明确价值的短暂 provider 故障，并始终受本次 descriptor 选定的既有有界 job deadline、取消和 50 USD 预算约束；认证、
  schema、identity 和 deterministic parse error 通常不应重试。具体 timeout、状态码、backoff 和 attempt 数由 provider 实测决定，
  不从方向 0 配置机械继承。
- 离线测试可把 cloud provider 设计成确定性 loopback server，并通过真实 cloud service launch/selection 路径复用 Plan 055 的进程、协议、
  queue/cancel/shutdown 断言。测试聚焦 cloud 新增行为与相邻回归，不复制整套旧矩阵的实现代码。
- 真实 commissioning 使用极少量明显、无项目内容的合成 publication；先确认 request schema、身份、响应解析、timeout/cancel 与 usage，再从
  clean 状态跑正式小 smoke。保留 body-free 摘要即可，不需要存完整 provider request/response 或建立 result archive。
- Docker 只在真实依赖或 smoke 隔离确有收益时使用。普通 loopback provider、Rust 测试和真实 HTTPS smoke 已足够时，跳过 Docker 更符合
  本任务范围；如使用，遵守第 2/3 节的单任务、互斥、容量和精确清理边界。
- 最终定向门禁通常包括 `codex-publication-critic` 的格式/lint/tests、实际改变的 config/loader/lock/generated 检查，以及少量既有
  `team_publish` default-off/enabled 聚焦回归。具体命令按最终 diff 选择；共享代码未改时不要扩大到全 workspace。

### 建议执行步骤

1. 核对 live code、现有 provider/config/HTTP 设施和准确修改面，先冻结 cloud identity、模板、scalar/domain 与选择路径的最小设计。
2. 实现 backend 与显式选择路径；用 fake/loopback provider 打通完整 service 生命周期、故障/取消/队列矩阵及本地路径相邻回归。
3. 离线门禁通过后，在 50 USD 总预算内使用合成 packet 进行真实 commissioning，保留已验证进度并自主修复普通 provider 接缝问题。
4. 全链稳定后冻结 clean commit/config/identity/template，从新运行空间完成一轮小型真实 API smoke；分开记录 fake/commissioning/clean real
   证据、保守费用和未运行项。
5. 运行与最终 diff 相称的格式、lint、生成物/锁文件和定向测试，检查主物理 ignored/Docker 副作用，精炼更新计划/WBS/COMPLETED/日志。
6. 提交 095 worktree、保持 clean，按指定队列主动表明身份并发送最终完成汇报后停止会话，等待审查者自动唤醒；不合并、不推送。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-27：确认主工作区 clean，`main = origin/main = 76f3539809589d844d7b6423d0a7a6d84f0b0518`；既有 093 worktree 保持不动。
- 2026-08-27：从上述 clean main 创建
  `.claude/worktrees/095-publication-critic-cloud-reference-scorer` / `worktree-095-publication-critic-cloud-reference-scorer`。
- 2026-08-27：只读核对根/`multidev/` 规则、README、顶层/三期 WBS、plan 模板、Plan 055/057/068/073/094、相关日志、
  Publication Critic trait/service/identity/resource/local worker/配置与测试边界，并完成三路并行只读分析和两轮合同复核；最终复核为 `ACCEPT`。
- 2026-08-27：编制本 ExecPlan 并精炼同步顶层/三期 WBS 的 active 工作包、reference-only 定位、一次性授权与边界。规划阶段未运行测试、
  Cargo、Docker、真实 API/模型或网络查询，未读取 `.env.local`、v8/unseen、权重或其它任务 ignored payload，也未创建主物理 ignored 工件。

### 当前工作

- Plan 095 任务合同与 WBS 立项同步完成；规划提交后由执行者继续使用本 worktree 实施。

### 本任务剩余步骤

- 实现云端 backend 与显式选择路径，完成 fake/loopback 全生命周期和相邻回归。
- 在离线门通过后完成真实 API commissioning、clean 小型 smoke、费用/副作用收口和相称定向门禁。
- 更新动态状态、完成历史/WBS 与精炼实施日志，提交 worktree并通过指定队列请求最终验收。
- 本任务完成后冻结此计划；不在此安排 threshold 标定、批量测评、v8/unseen、产品启用或 M3-D。

### 阻塞项

- 当前无已知原则阻塞。真实 provider/model 非密钥配置和 allowlisted credential 是否已就绪尚未在规划阶段检查；执行者只能通过安全入口核对。

### 当前验收状态

- `PLANNED / EXECUTION_NOT_STARTED / OFFLINE_NOT_RUN / REAL_API_NOT_CALLED / READY_FOR_IMPLEMENTATION`。

### 交接边界

- 执行者继续使用现有 095 worktree，不另建工作树，不在主工作区修改 tracked 文件。
- 一次性外部授权已经生效，不需要新增付费阶段审批；必须先通过离线全链再进入真实 API，范围/预算内普通问题自主修复续跑。
- 需要额外授权、计划变更或不确定原则事项时只通过指定队列联系审查者；每条消息主动表明 Plan 095 执行者身份，发送后停止、不轮询。
- 最终完成全部变动与验证后，先提交并保持 clean，再按用户给定的固定正文拼接原始 TUI 完成汇报发送审查者，随后停止会话。
- 本任务不自行合并、推送、归档/重命名分支或删除 worktree，等待用户批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 095 是 Plan 055/057 服务链上的 eval/reference-only cloud backend，不是 Plan 094 训练后继，也不解锁 M3-D | 复用已完成产品接缝，同时保持训练研究与参考 scorer 职责正交 | WBS、产品定位 | 已采纳 |
| 002 | 只新增 backend 与显式选择路径，现有 trait/service/packet/render/team_publish/local worker 语义保持不变 | 现有服务已证明 backend-neutral，避免无关重构和第二套体系 | 架构、允许写集 | 已采纳 |
| 003 | 云端 identity 对无法验证的 tokenizer/serving 分量显式标为 unverifiable/provider-managed，不冒充 exact | 兼容现有 expected identity 校验并保持身份陈述诚实 | identity、文档、测试 | 已采纳 |
| 004 | cloud 输出保持一个 `[0,1]` 或其它明确声明 domain 内有限 scalar，由既有 threshold 合同形成 verdict；不冻结最终 threshold | 保持现有 operating-curve 能力与产品合同，不把 backend 接入混成质量选择 | scoring、范围 | 已采纳 |
| 005 | 一次性 50 USD 授权已生效，不加第二付费门；先离线、再 commissioning、最后 clean real smoke | 尽早暴露接缝问题，又避免调试结果冒充正式证据 | 执行顺序、费用 | 已采纳 |
| 006 | 真实 smoke 只发送合成 packet；不做批量测评、不上传项目数据、不读 v8/unseen | 满足真实打通证据同时控制外发范围 | 数据、外部动作 | 已采纳 |
| 007 | 轮数不设机械上限，普通 provider/解析/timeout/template 等问题在范围和预算内自主修复续跑 | 避免一次窄失败导致不必要停工 | 调试、重试 | 已采纳 |
| 008 | 共享 Cargo target、必要的主根 machine config/secret loader、可选 task-owned ignored smoke 目录单独汇报 | linked worktree 不复制这些 ignored/宿主资产，且构建必须复用共享 target | workspace、交付 | 已采纳 |
| 009 | Docker 可用但非必选；C: floor 仅本任务临时为 30GB，不改 tracked 默认 | 授权与实际必要性分离，避免为形式完整扩大重型操作 | Docker、资源 | 已采纳 |
| 010 | 额外请示与最终验收只走指定 Codex queue，消息表明身份、发送后停止且不重复 | 遵循用户指定的跨会话审查方式 | 协调、交付 | 已采纳 |
| 011 | 最终只提交 095 worktree；合并、推送、归档和删除等待用户批准 | 遵循本次明确 Git 停止点 | Git | 已采纳 |
