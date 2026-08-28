# Plan 097：M3-D 双后端工程端到端闭环与可替换 Scorer 接缝验证 ExecPlan

> 本计划是 Plan 097 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束、预算或完成标准，应暂停对应动作并按本计划指定的跨会话队列请求审查者批示。
> 普通代码、编译、测试、模型进程、配置、provider、网络、timeout 和局部基础设施问题，应在既有范围、预算与安全边界内自主修复并按需重跑，
> 不因一次窄修可解决的问题提前终止任务。
> 本计划只描述 Plan 097；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

使用两个真实但均未取得产品质量资格的 engineering fixture，完成代表性的 RONDO Multi Publication Critic 端到端工程闭环：

- 本地 exact `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` 原始
  safetensors backend；
- Plan 095/096 已验证的 `deepseek-v4-flash` 云端 reference backend。

两者必须通过同一 `PublicationScorer → service → typed client → team_publish` 产品边界工作。Producer 接收 Plan 057 既有固定反馈后，
自主完成下一稿并继续同一 publication cycle；最终稿只通过现有 canonical Team State mutation 提交。Root、Team State、cycle、权限、revision、
wake、evidence、fallback、取消与生命周期语义不感知 backend 类型。backend 替换只依赖工件、显式启动/配置选择和诚实 identity，不复制发布状态机。

本任务把原 M3-D 的当前目标收窄为**工程前置闭环**。它不推翻 Plan 096 的
`CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`，也不授予本地模型质量、云端 scorer 资格、产品价值、默认启用、生产部署或三期最终产品 GO。

### 完成/验收标准

- [ ] **关闭态是真正旁路。** Publication Critic 缺省关闭；代表性 OFF 流程保持既有 model-visible `team_publish` 工具合同和 store 行为，
      不构造 publication review cycle，不加载本地模型，不读取云端 scorer credential，不启动 scorer 请求，也不新增 Team State 状态。
- [ ] **两个真实 backend 共用同一产品接缝。** local/cloud 都从正式启动选择进入同一 service protocol、expected identity、typed client 和
      `team_publish` review cycle；Producer、Root、Team State 协议与发布状态机没有 backend 分叉。允许为真实职责缺口增加专用启动/配置或 E2E
      驱动薄能力，不允许绕过 service 直接给产品 verdict。
- [ ] **本地 exact 1.7B 全链成立。** 从物理根既有 exact 原始权重、tokenizer、Plan 068 serving env、worker 与 real-service 路径完成
      ready、真实 review、Producer 改稿、同 cycle 继续、canonical commit 和 shutdown；不转换、不量化、不训练、不下载或复制模型。
- [ ] **云端 DeepSeek 全链成立。** 复用 Plan 095/096 的 cloud service、template/projection、严格解析、有限 retry、identity 与生命周期，
      从代表性 RONDO Multi Producer 流程完成同等 review、改稿/commit 和关闭；provider 调用与 client/service deadline 相互兼容。
- [ ] **真实 verdict 自然覆盖必要分支。** commissioning 期间为每个 backend 找到少量 bounded、合成或代表性的非正式 publication，使真实模型输出
      自然覆盖 `PASS` 和 `REWRITE`；至少一个预声明的明显缺陷稿在本地 exact backend 下进入真实 `REWRITE`。需要改稿的正式代表路径必须让正常
      Producer 根据既有固定反馈自主生成下一稿，不能用测试代码直接注入预制 verdict 或把预写第二稿冒充自主重写。有效模型 verdict 不因不符合预期而
      对同一输入选择性重跑；commissioning 得到的可用案例只作为后续预冻结工程分支 fixture，不获得质量标签或 threshold 语义。
- [ ] **Team State 与 Root 不变量保持。** 前两次被拒稿不创建 Event/Version，不推进 revision、wake、Root attention 或 evidence cursor；
      最终成功稿只做一次现有 canonical mutation。Root 只消费正常公共 Team State；权限、stale、dedup/replay、生命周期、取消和 evidence 行为不变。
- [ ] **failure 与 cancel 代表路径闭合。** 在同一正式产品边界上用有界、可解释的受控故障/取消覆盖 typed failure fallback 与 commit 前取消；
      fallback 只尝试一次现有 store commit，取消零提交。无需故意制造付费 provider 故障、破坏模型工件或复制 Plan 055/057 的完整旧矩阵。
- [ ] **生命周期和资源有界。** local 模型/worker/service/socket/GPU task process 与 cloud service/provider request 均在既有 deadline/cancel/shutdown
      约束内结束；任务创建的进程、监听和临时文件全部回收，无 task-owned 孤儿。以小型 body-free 摘要记录 backend identity、路径终态、耗时/延迟、
      fallback/cancel 和资源回收；不把工程 latency 冒充正式性能资格。
- [ ] **先打通、再冻结、再跑干净正式轮。** commissioning 保留已验证进度并从首个未打通处继续，直到 OFF/local/cloud 及代表 failure/cancel
      全部闭合；随后冻结 clean source、两个 backend identity、两套非最终 reference threshold、Producer/runtime 条件、少量工程案例、配置与结果口径，
      从干净状态完整执行一轮 OFF、local、cloud、failure/cancel。调试片段不得拼成正式结果，正式身份改变后重跑受影响的完整正式轮。
- [ ] **证据与测试相称。** 新增或调整的正确性测试进入既有 Rust/Python 测试体系；运行最终 diff 所需的格式、lint、配置/生成物、相关 crate、
      `team_publish`/Team State 和 E2E 定向门禁。fake/loopback、受控故障、真实本地模型、真实 API、正常 Producer 调用、skip 与未运行项分开表述；
      不运行全 workspace。
- [ ] **结论边界固定。** 无论终态为何，项目口径都继续是：本地模型质量 `NO-GO / 待替换`、云端 scorer `NOT QUALIFIED`、M3-D 产品价值
      未验收、Publication Critic 默认 `OFF`、生产启用 `NO`。PASS 只增加“工程链 GO、双 backend 可替换 GO”。
- [ ] 完成 tracked/ignored/资源/费用/diff 检查，形成精炼实施日志并提交 097 本地任务分支；全部实施变动完成后通过指定 queue 主动表明身份并使用
      用户给定的最终消息模板交审查者验收。首次独立验收接受后，由审查收口轮追加 `doc/WBS-COMPLETED.md` 并把 WBS/计划收口为最终事实；若有
      finding，执行者按 queue 指示修复、提交并发送新的完成汇报。不合并、不推送、不归档/重命名分支、不删除 worktree。

### 任务终态

| 终态 | 含义 |
|---|---|
| `M3_D_DUAL_BACKEND_ENGINEERING_PASS` | OFF、本地 base、云端 reference 三态以及 rewrite/commit/fallback/cancel 的工程闭环成立；只有此终态表示 M3-D 工程前置完成 |
| `M3_D_DUAL_BACKEND_ENGINEERING_NO_GO` | 在范围内对普通问题进行合理修复后，至少一个真实 backend 仍无法完成工程闭环；这不是模型质量结论 |
| `M3_D_DUAL_BACKEND_ENGINEERING_INCONCLUSIVE` | 目标本地环境或外部服务持续不可用，无法形成有效工程结论；一次网络、配置、OOM 或其它可窄修问题不得直接冒充该终态 |

## 2. 范围

### 允许修改

- `multidev/` 内与 Publication Critic backend 选择/启动、现有配置和生命周期接缝、`team_publish` 组合闭环及其定向正确性测试直接相关的代码。
  只有 live code 证明存在真实职责缺口时才修改现有 product seam；职责契合时复用，强行复用会造成耦合或语义扭曲时可增加与现有架构契合的专用能力。
- `eval/rondo_eval/`、`eval/tests/` 或 `scripts/` 内职责明确的 Plan 097 E2E 驱动、少量 engineering case、简单 freeze/result/archive 与
  进程/资源收口能力；不得复制第二套 publication service、Team State、状态机、trace、预算或通用部署平台。
- 因真实代码、配置或依赖变化必须同步的 Cargo/Bazel/config schema/lock/生成物，以及已有 `rondo.local.example.toml`、
  `rondo.secrets.example.env` 非密钥接口。没有对应输入变化时不为形式完整机械改锁或生成物。
- 一份小型受跟踪工程运行合同/正式结果（若现有惯例确有需要）、本计划的“当前状态/关键决策记录”、精炼 Plan 097 实施日志，
  以及执行期间受影响的 `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md`。`doc/WBS-COMPLETED.md` 只在首次独立验收接受后追加。
- 物理仓库根 task-owned ignored `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan097/`，用于 commissioning、正式轮、socket、
  body-free 运行摘要和必要临时结果；以及确有需要的主根 ignored `rondo.local.toml` 非密钥机器参数。最终简洁报告路径、用途、体积、权限与保留状态。
- 普通依赖/公开源码/官方 provider 文档的只读访问；本次授权内的真实本地 exact 1.7B 加载/推理、目标 8GB GPU、DeepSeek scorer API、
  正常 RONDO Producer 必要模型调用，以及必要的定向 Rust/Python/Bazel 构建和测试。

本计划不固定文件布局、是否增加专用 E2E binary/runner、服务由脚本还是进程编排、case 形状、归档 schema、局部 refactor 或具体定向测试列表。
执行者可依据 live code、真实运行与维护成本选择更优、更干净的等强方案，只需满足本计划冻结的产品、安全、费用、正式轮和结论边界。

### 允许只读核对

- 根/`multidev/` 规则、README、当前 WBS、Publication Critic 产品合同、Plan 053/055/057/068/071/095/096 必要合同、结果、日志和主线实现。
- 物理根 Plan 068 exact base/tokenizer、serving env/worker 运行入口，Plan 071 最终 base descriptor/freeze，以及 Plan 095/096 tracked cloud
  descriptor 和 body-free 历史证据；不得写回旧 Plan namespace、旧 env 或模型树。
- 主工作区和其它 worktree 只用于 Git 状态、共享重型资源与冲突保护核对；不读取其它 worktree 未提交内容。

### 不允许修改、读取或执行

- 不修改 exact 1.7B 权重、tokenizer、Plan 068/071 模型/环境/历史结果或 Plan 095/096 正式结果；不选择 C1/C2/C3，不训练、微调、量化、
  转换、下载、上传或发布模型/adapter，不登录或写 Hugging Face。
- 不读取、搜索、评分、外发或释放 v8 validation、label/pair/split、train、unseen-test 及其 mixed bundle；不使用 Plan 096 的 55 条或任何质量
  数据调 prompt、threshold、case 或模型。本任务只用合成或代表性 bounded 非正式 publication。
- 不调 cloud prompt/projection 或两个 reference threshold 来提高质量，不把 verdict 正确性作为验收；不冻结产品 threshold、selection lock、
  模型质量门或产品价值指标。
- 不改变 Plan 057 两次固定反馈、第三次非阻断、typed failure fallback、取消、replay/dedup、canonical commit 或 Team State/Root 公共协议。
  若 live code 暴露的是上游产品合同冲突而非组合接缝缺口，必须通过 queue 请求决策。
- 不默认启用 Publication Critic，不把 cloud 设为默认 backend，不生产部署，不建设热切换、模型注册中心、通用 supervisor、第二套服务/client/
  Team State/trace、复杂鉴权、数据审计、可信、隐私或严格因果设施。
- 不使用 Docker、RunPod、云 GPU、远端资源创建/修改/删除、数据/源码上传、CI/PR、上游基线升级或全 workspace 测试；不修改宿主机配置、
  全局工具链、其它仓库、其它 worktree 或来源不明资产。
- `.env.local` 不允许打开、搜索、打印、复制、修改或 source；只能由已有严格 loader 静默检查主物理根文件存在、非符号链接、权限 `0600`、
  任务所需 allowlisted 变量存在且非空，并只向目标子进程注入所需变量。credential、endpoint 私有值、真实 provider request/response、
  runtime publication 正文和 provider error body不得进入普通日志、tracked artifact、queue 或提交。
- 未经用户后续批准，不合并/rebase/cherry-pick 到 main，不推送任何分支，不归档/重命名分支，不删除 worktree。

### Git-ignored、主物理根与宿主副作用

所有 tracked 修改只在以下 worktree 完成并提交，主工作区不得产生 tracked diff：

`/home/sjc/desktop/RONDO/.claude/worktrees/097-m3-d-dual-backend-engineering/`

linked worktree 不共享主根 ignored 资产。以下现有/任务内事项必须留在物理根原位使用或产生，不得复制进 worktree或提交：

- exact base：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan068/handoff/model/`；
- serving env：`/home/sjc/desktop/RONDO/eval-data/envs/publication-critic-plan068/`，只读复用，不安装/升级依赖；
- local reference：`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan071/formal/plan071-formal-20260825T064600Z-qualification-v5-inputs/`；
- 主根 `.env.local`、`rondo.local.toml` 与 task-owned `eval-data/publication-critic/plan097/`；
- 唯一共享 Cargo target：`/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi/`。

Plan 097 不写回 Plan 068/071/095/096 namespace，不复制 3.4GB 模型或 6.9GB serving env，不清理任何来源不明或历史资产。共享 target 是可再生
构建缓存而非交付物，也不是本任务清理对象。最终只需简洁报告实际创建/修改的 ignored 路径与 task-owned 进程/监听终态，不建设逐文件审计台账。

## 3. 硬约束

以下约束只冻结结果成立所必需的产品语义、真实 backend、费用、资源、安全与交付边界；不锁死执行者的具体实现路线。

1. **两个未获质量资格的真实 fixture，不作质量声明。** local 固定 exact 1.7B base，cloud 固定 `deepseek-v4-flash` 的 Plan 095/096
   backend/template/strict parser。两套 threshold 只沿用既有非最终 reference 值用于工程分支，不调参、不获得产品语义。Plan 096 NO-GO 保持有效。
2. **同一产品接缝、同一状态机、同一写路径。** local/cloud 只能替换 `PublicationScorer` backend 与其工件/启动/配置/identity；二者都进入
   同一 service、typed client 与 Plan 057 `team_publish` review cycle，最终且只调用现有 canonical Team State mutation。Producer、Root 和 Team State
   不得感知 backend 类型。
3. **关闭态是真正旁路。** off 时不得创建 packet/client call/review cycle，不得加载本地模型、读取 cloud scorer secret 或出网，也不得改变
   `team_publish` schema/output/store/Team State。仅仅存在未使用的 binary、配置示例或无副作用类型不算启用。
4. **identity 诚实且可替换。** local 必须绑定 exact 模型/tokenizer/render/scalar 与实际 worker/service 工件；cloud 必须保留 provider-managed/
   unverifiable serving/tokenizer 表述并绑定实际 requested model、template/projection/domain。expected/observed identity mismatch fail-closed，不能用名称占位
   或旧 binary hash 冒充当前运行；未来替换模型只需替换明确工件/配置/identity 接缝，不预建 registry 或热切换平台。
5. **有效 verdict 不挑选，普通故障可恢复。** 模型已经产生的有限合法 verdict 不因“不符合预期”重跑同一输入；不伪造 PASS/REWRITE。
   编译、测试、配置、worker/service、OOM 参数、timeout 对齐、网络、限流和 provider 暂时错误等普通问题可在身份不变、预算/deadline 内自主修复、重试或
   从未打通点继续，不设机械次数上限。只有原则边界变化、未授权外部状态、无法可靠归因的正式失败或合理修复后仍无法闭环时才请示/收口。
6. **commissioning 与正式轮分开。** 先在本地/offline/受控环境完成能完成的工作，再依次打通 OFF、本地真实模型、云端真实 API 和组合故障路径；
   commissioning 可保留有效进度。全链稳定后才冻结 clean source、配置、identity、runtime、case 与简单结果口径，并从干净状态完整执行一次正式轮；
   正式结果不拼接调试片段，也不因非关键文档/归档窄修重跑已经有效的真实模型/API 结果。
7. **真实 API 预算和外发边界。** Plan 097 新的独立真实 API 总硬上限为 `30 RMB`，覆盖 DeepSeek scorer、正常 Producer 必要调用、commissioning、
   clean 正式轮与网络/上游重试；Plan 095/096 的费用/余额不继承，也不要求用满。首次付费前以可用 usage、价卡/账单和简单保守估算确认最坏余额，
   累计到上限即停止新增计费动作并安全收口，不建设通用 ledger。只向 provider 发送任务内合成或代表性 bounded publication packet/Producer 输入，
   不发送 validation、标签、训练/unseen、源码、密钥或其它项目数据。
8. **重型资源严格串行且只用唯一 target。** 任务按“必要 Cargo 构建/测试 → 本地 exact 1.7B 真实加载与 E2E → 完全回收本地任务进程 → 云端 API E2E”
   使用重型资源；Docker 未授权。任何重型 Cargo 只能从 097 worktree 使用 `multidev/justfile` 或仓库正式入口，经
   `scripts/with-build-lock.sh` 自动路由物理根唯一 `.codex/cargo-target/rondo-multi`，禁止在 worktree、`/tmp` 或其它位置新建第二套 target、
   直接 Cargo 绕过锁/看门狗或提高并发。本地模型加载/推理服从同一全局 heavy 生命周期门，拿不到资源计数器时 fail-closed。
9. **取消、失败、日志和回收不放宽。** service/client 既有 queue、deadline、retry、cancel、shutdown 和 typed failure 语义保持；cloud client timeout
   必须覆盖并服从已冻结 backend/job 最坏预算。取消后不留 detached provider retry，本地 worker/model 不留 task-owned 孤儿。普通日志/归档/queue
   只保留 body-free identity、typed status、次数、耗时、usage/费用与资源终态，不保存 credential 或运行时正文。
10. **验证聚焦正确性。** 只跑受影响 crate/模块与必要相邻边界的定向门禁，不复制历史完整矩阵、不跑全 workspace、不为形式增加重型测试。
    修 bug 先复现并补合适回归；skip/未运行/受控 fixture 不冒充真实 local/cloud/Producer E2E。审查关注功能与正确性、遗漏和局部修改的相关回归，
    不扩大成产品质量、性能或通用审计验收。
11. **文档和 Git 停止点。** 实施与待审事实更新 plan/WBS/精炼日志；首次独立验收接受后，由审查收口轮追加 WBS-COMPLETED、审查报告并收口最终状态。
    执行者和审查者各自在完成本轮 tracked 变动后提交 097 本地分支并保持 clean。未经用户批准不合并、不推送、不归档/重命名分支、不删除 worktree。
12. **跨会话请示与验收。** 额外授权、计划外变数、不确定事项、独立验收和最终完成汇报只使用下述 Codex 跨会话队列。执行者每条消息必须
    主动表明“我是 Plan 097 执行者”，发送后停止会话，不等待、不轮询、不重复发送。

### 审查者跨会话队列（用户指定原文，执行者必须原样遵循）

```text
联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a0464a-7b40-7453-b3f6-8e982f648e05 替换。
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

以下建议基于 `main@84a0ff2` 的 live code与现存本地资产，只帮助执行者高效起步，不是固定路线。执行者可以依据真实代码、测试、运行结果和维护成本
采用更优、更简洁、与现有架构更契合的等强方案；审查者不得把本节偏好升级为硬约束。

- 现有产品接缝本身已经完整：local/cloud 都实现 `PublicationScorer`，两个 launcher 都复用同一 `serve()`，core 配置只消费 endpoint + expected
  descriptor，Plan 057 状态机只消费 typed client。最可能的缺口是“启动/配置选择 + RONDO Multi E2E 驱动/证据”薄能力；先证明缺口再改产品代码。
- local 优先从 Plan 071 v5 base descriptor提取 exact 模型/scoring identity和非最终 threshold，再以 097 当前 source/binary/runtime 诚实形成新的
  运行 identity；不要照搬已经失效的旧 worktree binary 路径/hash。复用 Plan 068 env 与 worker 时保持只读，不安装依赖。
- 当前 real scorer/worker 把 qualification-era `object_id` 限制为 `base|c1|c2|c3`。若 live code 确认这会让未来合格模型仍需改 service 实现，
  可以把运行层窄化为有界、诚实的 artifact identity，并把四对象限制留在 Plan 068/071 qualification runner；不要借机建设模型 registry。
- cloud 优先以 tracked `eval/locks/publication-critic-plan096-cloud-descriptor-v1.json` 为起点，保留 Plan 095/096 已验证的 8192 output、prompt、
  projection、retry 与 identity。该 descriptor 的 job budget 高于 core 默认 30 秒 client timeout，commissioning 应通过实际配置把外层 client timeout
  对齐为覆盖但仍有界的值；无需为此改变 service contract。
- 代表性 RONDO Multi 流程可复用现有 Multi M5/loopback、core/app-server Team full-chain、Plan 057 process test 或其它职责契合的驱动能力；
  若强行嫁接会扭曲 Producer/Root 语义，新增 Plan 097 专用小驱动更干净。正式证据必须让正常 Producer 真正消费 rewrite feedback，不能停在 handler 单测。
- commissioning 可先用确定性 provider/受控 scorer验证编排与 Team State 断言，再加载 exact base找自然 PASS/REWRITE case，最后进入付费 cloud/Producer；
  已经验证的路径保留，从首个未通点继续。先在本地暴露能暴露的问题，避免进入付费阶段后再处理可离线发现的错误。
- engineering cases 保持很少、bounded、明确非正式；可在 commissioning 中探索后预冻结能触发必要真实分支的合成稿，但不要给它们贴质量标签、追求
  成功率或把同一有效 verdict 重跑到满意为止。正式轮只验证固定 case 的产品路径与状态不变量。
- failure/cancel 可在现有正式接缝上控制 worker/service/provider 边界，不必故意断网、消耗真实 API、损坏权重或复制旧矩阵。资源报告只覆盖本任务
  process/socket/GPU/request 的有界收口，不承诺清理或证明系统中无关任务的资源。
- 测试按最终 diff 递进：E2E runner/pure fixture → `codex-publication-critic`/`codex-core` 或 app-server 相关定向测试 → 必需的 lint/format/lock/schema。
  如果产品共享代码未改，不机械重跑它的全部历史矩阵；不运行全 workspace。

### 建议执行步骤

1. 复核 live code、既有 exact/cloud identity、主根 ignored 资产和真实运行配置，明确组合闭环的最小职责缺口；先完成离线设计与定向回归。
2. 实现或窄泛化必要的启动/配置/E2E/简单结果能力；用 OFF、controlled/fake/loopback 先闭合状态断言、fallback、取消与资源回收。
3. 经共享正式入口完成必要构建后，独占重型槽加载 local exact base；从 load→worker→service→typed client→Producer rewrite→canonical
   Team State→Root 观察打通，保留进度并自主修复普通问题，结束时回收全部 task-owned 本地资源。
4. 本地链稳定且资源完全释放后进入付费阶段，用既有 DeepSeek backend 与正常 Producer 打通同等流程；在 30 RMB 内自主处理允许的网络/限流重试。
5. 全链稳定后提交或记录 clean pre-freeze source，冻结两个 identity/reference threshold、Producer/runtime、少量 case、配置与结果口径；从干净状态
   依次完整运行 OFF、local、cloud、failure/cancel 正式轮并生成简洁结果。
6. 运行与最终 diff 相称的定向门禁，检查 tracked/ignored、费用、进程/socket/GPU/request、主工作区与所有 worktree 状态；更新待审 plan/WBS 和精炼
   实施日志，完成全部实施变动，提交 097 分支并保持 clean。随后严格按用户指定的最终消息模板，通过 queue 主动表明身份交审查者验收并停止会话。
7. 若被审查者唤醒要求窄修，自主收敛 finding、提交并发送新的且不重复的完成汇报后再次停止。验收通过时审查者不会再通知；审查者负责形成审查报告、
   追加 `doc/WBS-COMPLETED.md`、收口 WBS/plan 最终状态并提交审查收口变动。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-27：用户明确把 Plan 097 从“合格 scorer 产品价值验证”改立为“两个未获产品质量资格但工程可运行的 scorer fixture 的双后端工程闭环”，
  并授予本计划列明的一次性本地模型、真实 API、正常 Producer、定向门禁与项目内实施权限；Plan 096 NO-GO、default-off 和产品锁保持不变。
- 2026-08-27：确认主工作区 clean，`main = origin/main = 84a0ff2b477fbacf407ab3e598fefc3618b44eaa`；093/095/096 worktree 均 clean且保持不动。
- 2026-08-27：从上述 clean main 创建
  `/home/sjc/desktop/RONDO/.claude/worktrees/097-m3-d-dual-backend-engineering` / `worktree-097-m3-d-dual-backend-engineering`。
- 2026-08-27：只读核对根/`multidev/` 规则、README、顶层/三期 WBS、plan 模板、Plan 057/068/071/095/096、相关主线实现/测试与物理根
  exact base、serving env、descriptor、credential 元数据和唯一共享 target；没有打开 `.env.local`，没有读取模型内容、validation/unseen 或其它 worktree 未提交内容。
- 2026-08-27：确认已有接缝分别覆盖真实 backend→service/client 与 controlled scorer→team_publish/Team State，Plan 097 的最小真实缺口是两种
  backend 各自贯穿正常 Producer rewrite、同 cycle 和 canonical commit 的组合链；编制本 ExecPlan并把两份 WBS 窄同步为 active 工程工作包。
- 2026-08-27：规划阶段未运行构建、测试、本地模型、GPU 推理、真实 API、Producer、Docker、RunPod 或任何付费/远端状态操作；未创建 Plan 097
  ignored 运行 namespace。
- 2026-08-27：独立只读规划复核确认模板、queue 原文、Plan 096 结论边界、WBS 一致性、实现自主度、ignored 资产和唯一 Cargo target 均无
  High / Medium / Low correctness finding；复核未修改文件。
- 2026-08-27：完成 body-free `team_publish` trace 证明、双 backend service/runtime 编排、正常 Terra Producer 重写回环、持久费用代理与
  Plan 097 专用正式 campaign；相关 Python 回归、格式/diff 门禁及受共享锁保护的 Rust process tests 均通过。
- 2026-08-27：commissioning 打通后在 clean `0ae9623` 上完成 `plan097-formal-5`。OFF 真实旁路；local/cloud 各 3/3 fixture 命中
  `PASS + REWRITE`，正常 Producer 各完成 3 次发布、2 次重写/回环与唯一 canonical commit；fallback 为一次提交、cancel 为零提交，全部
  task-owned 资源回收。正式终态 `M3_D_DUAL_BACKEND_ENGINEERING_PASS`，累计保守费用 `21.4197186 RMB / 30 RMB`。

### 当前工作

- `IMPLEMENTATION_COMPLETE / FORMAL_PASS / REVIEW_PENDING`：实现与正式结果已提交前自检，等待首次独立验收。

### 本任务剩余步骤

1. 提交待审记录并按用户给定最终消息模板通过 queue 交审查者首次独立验收后停止。
2. 若收到 finding 则修复、提交并发送新的完成汇报；若验收接受，由审查者完成审查报告和任务终态文档收口。

### 阻塞项

- 当前无已知阻塞。目标 GPU 或外部服务若持续不可用，只有在普通问题已合理收敛且仍无法取得有效证据时才进入
  `M3_D_DUAL_BACKEND_ENGINEERING_INCONCLUSIVE`。

### 当前验收状态

- 执行者正式轮终态为 `M3_D_DUAL_BACKEND_ENGINEERING_PASS`；正确性/功能性独立验收尚未完成。

### 交接边界

- 执行者只在现有 097 worktree/分支继续，tracked 工作提交到该本地分支；物理根 ignored 资产按第 2/3 节原位使用并单独汇报。
- 完成后由会话 `01a0464a-7b40-7453-b3f6-8e982f648e05` 的审查者验收。未经用户后续批准不合并、不推送、不归档/重命名分支、
  不删除 worktree；未来合格模型替换、模型质量资格、M3-D 产品价值与生产启用只由 WBS 后续另行立项，本计划不安排其步骤。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 097 改为双 backend 工程 fixture 闭环，不再以合格 scorer 或产品价值为前置 | 用户明确重定向目标，现有工程资产足够先闭合可替换产品链 | WBS、终态、结论 | 已采纳 |
| 002 | 固定 local exact 1.7B base 与 cloud DeepSeek V4 Flash；两者都保持未获产品质量资格 | 验证替换接缝而不改写 Plan 073/096 质量事实 | backend、identity、结论 | 已采纳 |
| 003 | 两 backend 只替换工件/启动/配置/identity，复用同一 service/client/team_publish/canonical mutation | 现有边界已完整，组合 E2E 才是真实缺口 | 架构、测试 | 已采纳 |
| 004 | commissioning 全链打通后再冻结 clean 正式轮；普通问题自主修复，有效 verdict 不选择性重跑 | 兼顾调试冗余、费用效率与正式证据一致性 | 运行、验收 | 已采纳 |
| 005 | 任务终态固定为工程 PASS/NO_GO/INCONCLUSIVE；三者都不授予质量、产品价值、默认或生产资格 | 防止工程链证据越界解释 | 终态、文档 | 已采纳 |
| 006 | 新真实 API 总硬上限 30 RMB，包含 scorer、Producer 与重试；不继承 095/096，不用 Docker/RunPod/unseen/训练 | 用户一次性授权范围 | 费用、外部动作 | 已采纳 |
| 007 | tracked 工作只在 097 worktree；模型/env/secret/config/shared target/raw 只在主物理根原位使用 | linked worktree 不共享 ignored 资产，且唯一 target/权重不能复制 | Git、宿主资源 | 已采纳 |
| 008 | 额外请示、计划外不确定性与验收只走指定 queue，执行者主动表明身份，发送后停止且不重复 | 遵循用户指定的跨会话审查机制 | 协调、交付 | 已采纳 |
| 009 | 完成后只提交 097 本地分支；合并、推送、归档和删除 worktree 等待用户批准 | 用户明确本任务 Git 停止点 | Git | 已采纳 |
| 010 | normal Producer 使用专用 runtime-injected member 指令与现有 collaboration/Team State 接缝；不复制第二套发布状态机 | 既有 Multi 驱动不提供固定 publication task，但产品状态机已完整 | Producer、E2E | 已采纳 |
| 011 | Plan 097 明确声明零 Guardian、串行排队 main 请求，并以持久 roll-forward ledger 计入全部旧轮次 | 正常 Producer 流程没有 Guardian；并发额度预留会造成假性 capacity failure | 费用、代理、运行 | 已采纳 |
| 012 | 30 RMB 总上限最终分账为 cloud scorer 6 RMB / Producer 24 RMB；正式结论按合并保守总账判断 | commissioning 显示主要费用来自正常 Producer，而 scorer 实耗很低 | 费用、正式轮 | 已采纳 |
