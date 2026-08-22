# Plan 055：M3-B2a Publication Critic 本地服务与稳定调用边界 ExecPlan

> 本计划是 M3-B2a 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通实现、测试、依赖或格式问题可在范围内自主修复并有界重跑。
> 本计划只描述 M3-B2a；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

依据 [`Publication Critic 产品合同`](../doc/rondo-multi-publication-critic-product-contract.md)，在 RONDO Multi 内建立一套真实可启动、
可检查、可调用并可关闭的本地 Publication Critic 服务，以及可直接交给 M3-B2b 消费的 typed 调用边界。

本任务自行冻结服务协议、服务/模型/scoring identity 的校验方式、资源数值和 failure 分类。正式测试使用明确标为测试身份的
受控 scorer 替身，但必须启动真实服务进程并经过正式协议、限流和 client 路径；本任务只冻结 threshold 如何参与 scoring
identity 与 verdict 映射，不替 Plan 054 决定真实 threshold，也不依赖、下载或运行最终模型或接入 `team_publish`。

### 完成/验收标准

- [ ] 请求、响应、服务身份和错误在一个版本化合同中定义；实现与测试共享同一事实源，不存在 client/server 各自维护的漂移副本。
- [ ] 合同覆盖 M3-A1 的完整 packet 语义，但 wire 只允许该合同所需的公共、有界字段且没有任意 metadata 扩展袋；未知 schema、
      未知字段或未知/漂移的 qualification、model、scoring identity 被拒绝，不能猜测兼容或静默降级。B2a 机械保证的是 typed
      字段面没有禁入入口；合法 summary/handoff 正文的权威来源与 packet 构造仍属于 B2b，不能虚称服务能识别手工混入的私密语义。
- [ ] 服务端原始评分结果只有在 shape 合法、数值有限、identity 完全匹配并按冻结 scoring 规则映射后，才能成为
      `PASS/REWRITE`；M3-B2b 面向的调用结果只可能是合法 verdict 或 typed failure，原始 score 不成为 Producer、Root 或
      Team State 的产品字段。
- [ ] typed failure 至少能稳定区分合同/响应错误、基础设施/生命周期错误和调用取消；timeout、连接失败、队列满、异常退出、
      malformed/超限响应、非有限 score、identity drift 不会冒充 `PASS/REWRITE`。具体 enum 与错误粒度由实现结合可操作性决定。
- [ ] 受控 scorer 替身通过真实服务进程完成“启动 → liveness/ready → 调用 → 关闭”闭环；替换的只能是 scorer backend，不能
      绕过生产协议、identity、资源门、序列化或 typed client。
- [ ] liveness 与 readiness、启动超时、正常关闭、关闭期间拒绝新请求、异常退出和清理语义明确；测试结束不遗留子进程、监听器
      或永久占用的并发/队列许可。
- [ ] 请求/响应上限、端到端 timeout、最大并发和有限队列均有冻结数值及确定性回归；队列满和取消不会无限等待，失败或取消的
      请求不会污染下一次调用。
- [ ] 本地入口不能意外暴露为远端服务。若采用 TCP/HTTP，只允许 loopback 并由 client 复验，且不得跟随到非预期端点的 redirect；
      若采用其他本地 transport，须提供等强的本机边界。测试使用临时端点，不能依赖固定端口或常驻 daemon。
- [ ] 普通日志、错误展示和进程 stdout/stderr 不包含 packet 正文、candidate、continuity context、原始响应正文、凭据或 M3-A1
      禁入字段；用唯一 sentinel 覆盖成功与失败路径并断言不泄漏。允许记录必要的 body-free 运行元数据。
- [ ] 覆盖正常闭环、未 ready、异常退出、连接失败、timeout、并发、队列满、取消、malformed、非有限 score、请求/响应超限、
      schema/model/scoring drift，以及故障后健康请求的定向回归；测试不得依赖 sleep 竞速或真实模型。
- [ ] `team_publish` handler/tool schema、Team State mutation/store、Event projection、committed replay fast path、Team Lens 和现有
      trace 行为零修改；本任务不实现 off/shadow/enforce、Producer 重写、最终发布 fallback 或产品取消状态机。
- [ ] fake/受控替身证据只证明协议、生命周期和故障语义，不表述为 Skywork 基座、最终模型、质量或部署资格证据；真实模型资格
      明确保留给方向 3 WBS 所指的后续工作包。
- [ ] 依照根和 `multidev/AGENTS.md` 使用现有 `just` 入口完成格式、受影响 crate 的 lint 和定向测试；重型 lint/test 必须经入口
      已接入的共享构建锁，不为本局部任务运行全 workspace。新依赖、Cargo/Bazel 锁或生成文件如发生变化，按仓库工具更新并
      审查差异。
- [ ] 任务内完成 diff/允许写集检查和一次独立验收；普通 finding 允许执行者自主窄修并重跑。完成后只提交 055 worktree 本地分支，
      保持工作树干净；不合并、不推送、不归档或重命名分支。

## 2. 范围

### 允许修改

- `multidev/` 内 Publication Critic 专用协议、服务、scorer 抽象、typed client、配置边界和定向测试；可以新增职责清晰的模块、
  crate 或本地服务入口。
- 为上述实现必需的 `multidev/` workspace 清单、依赖、Cargo/Bazel 锁、构建定义、生成文件和小范围共用代码重构。
- 本计划的“当前状态”和“关键决策记录”。
- 任务完成时，精炼更新与 M3-B2a 直接相关的 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、
  `doc/WBS-COMPLETED.md` 和一份 Plan 055 `agent_log`；不得改写 Plan 054 的状态、数据或结论。并行分支尚未整合的事实应留给
  用户批准后的串行整合，不得从其他 worktree 抄取未提交内容。

如执行者根据 live code 判断专用 crate、现有轻量 transport 或其他布局更合适，可以自主选择；计划不预设 Rust/Python 边界、
HTTP/UDS、字段名、默认数值或错误枚举的具体形状。选择必须满足本计划的外部行为和验收，不得为复用而引入 Local approval
产品语义。

### 允许只读核对

- 根/`multidev/` 规则、README、当前 WBS、Plan 053、Publication Critic 产品合同、2026-08-21 两份冻结研究材料及其引用的
  tracked 源码和测试。
- `mydev/`、Local approval 和现有服务代码只允许用于学习通用的 loopback、进程生命周期、cap 与 body-free 日志模式；不得
  复制其 allow/deny schema、产品身份、qualification lock、配置命名或最终模型资格声明。
- Git 历史、主工作区和其他 worktree 只做状态/冲突保护核对，不进入其他 worktree 读取未提交内容。

### 不允许修改

- `team_publish` handler、tool schema、Team State model/store/mutation、Event projection 或 committed replay fast path。
- Producer/Root 交互、两次重写、最终发布 fallback、off/shadow/enforce、产品取消状态机、Event/wake/revision/evidence 行为。
- Team Lens、现有 trace/telemetry 语义、第二套 Team State、第二套 trace、复杂鉴权或通用模型服务平台。
- `eval/`、`training/`、Plan 054 的数据/样本/阈值/基座评价，以及 `mydev/` 的 Local approval 产品合同与源码。
- 真实模型权重、真实本地推理、Docker、真实 API、训练、云资源、上传/发布、宿主机或全局工具链配置、CI/PR。
- 其他工作树、来源不明的现有修改、历史日志/快照和无关 README/WBS 内容。

### 不允许读取/查看

- `.env.local` 内容，以及任何项目外个人文件、凭据、密钥或私有数据。
- ignored 原始 trace/payload、真实 publication 正文、Fact observation 正文、Plan 054 私有数据或模型权重。
- 其他 worktree 的未提交文件内容；仅可检查其 Git 元数据以避免覆盖。

### Git-ignored 与主工作区边界

本任务的正式交付物都应是 tracked 文件，**没有必须直接在主工作区完成的工作**。`.claude/worktrees/055-publication-critic-service`
本身按仓库设计被 git-ignore，但其中的 Git worktree 正常跟踪并提交交付文件。测试临时端口、socket、进程文件和输出应使用系统
临时目录或 055 worktree 内的任务专用临时位置；构建使用 worktree 内受监控的 `target` 和共享锁，不需要写主工作区。

如果实施中发现确实必须在主工作区物化 ignored 资产、复用 Plan 054 私有状态或写入项目外位置，说明范围判断发生变化，应先
停止该动作并向用户说明，不得自行扩张授权。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或追求形式上的复用而违反。

1. **M3-A1 是产品语义上游**：B2a 可以冻结服务 schema、identity、数值和错误，但不能改写完整 candidate、公共/禁入字段、
   Evidence V1 或 `PASS/REWRITE` qualification。发现真实冲突时停止并请求产品决策，不在服务层发明新语义。
2. **单一版本化合同**：请求、响应、服务 identity 和 failure 必须从一个权威定义派生或共享；wire schema、qualification 版本、
   model identity 与 scoring identity 均显式校验，调用方 expected identity 来自可信 typed 配置，不能接受服务任意自报值。
   未知或漂移只能形成 typed failure，不能按相似字段猜测解释，也不得用任意 metadata map 绕过字段 allowlist。
3. **严格 verdict 边界**：只有符合冻结 shape 的有限 score 才能按已冻结 scoring 规则转成 `PASS/REWRITE`。malformed、NaN、
   ±Inf、越界/额外值、identity mismatch 或超限响应均是 failure；不得设置“解析失败默认 PASS/REWRITE”。B2a 只冻结 threshold
   的配置、identity 和映射合同及受控测试值，不冻结或冒充 Plan 054/后续横评产生的真实 threshold。
4. **正式进程路径的受控替身**：集成测试必须启动实际服务进程并走正式 transport、协议、identity、限额和 typed client。
   scorer 替身必须带不可混淆的 test identity，只替换模型计算，不得另建一条绕过正式边界的 fake client 或测试专用协议。
5. **本地且有界**：transport 保持本机边界；请求/响应、startup、ready、queue、执行、shutdown、并发和队列都有显式有限值。
   所有等待和重试都必须有共同 deadline 或独立硬上限，不得出现无限队列、无界 task/process、静默后台重试或 timeout 后继续
   占用资源的永久工作。接收侧 cap 必须在无界缓冲之前生效，不能只依赖对端自觉控制大小。
6. **生命周期可判定**：liveness 不冒充 scorer ready；只有合同与期望 identity 均可用时才 ready。关闭开始后拒绝新工作，
   在有限时间内完成清理或明确终止；异常退出、启动失败和关闭失败形成 typed failure，测试不能残留服务进程。
7. **取消与隔离**：queued、in-flight 和等待响应时的取消均有明确、可复现语义，并最终归还容量。一次 malformed、timeout、
   断连、backend failure 或取消不能污染服务身份、下一次结果或资源计数。
8. **正文不进入普通日志**：服务/client/错误链不得记录或格式化 packet、candidate、continuity context、raw body、私有字段或凭据。
   日志测试必须检查成功和代表性 failure；不能通过只关闭测试日志来规避生产代码泄漏。
9. **只建立 B2b 可消费边界**：可以公开 typed client/trait 和必要配置，但不得调用、修改或挂接 `team_publish`，不得构造 Team
   State packet、读取 Event projection、实现重写/fallback/mode/cancel cycle 或创建产品 trace。B2a 接收调用方已准备好的 typed
   packet，不能声称已解决 store canonicalization 或正文来源校验；B2a failure 后是否发布属于 B2b。
10. **测试与证据诚实**：所有正式协议测试使用受控 scorer，不使用最终权重。fake、静态 schema、进程集成、真实模型、Docker
    和产品端到端是不同证据层；skip/未运行不能表述为通过，也不得削弱边界或断言凑绿。
11. **并行与 Git 隔离**：不进入或修改 Plan 052/054 等其他 worktree，不 stash、覆盖或删除来源不明修改。执行、修复和验收只在
    055 分支进行；完成后只本地提交，合并、推送和分支归档等待用户批准。
12. **适度验证与自主修复**：执行者应自行修复普通编译、测试、lint、生命周期竞态和局部设计问题，并按需要有界重跑；不因一个
    窄修可解决的失败立即停工。只有产品语义冲突、必须越界、预期外高危操作，或合理修复后仍无法满足原则性完成门时才暂停。
13. **资源与外部禁区**：重型 Cargo 入口必须使用 `multidev/justfile` 已接入的共享构建锁/看门狗，不绕过并发和资源门；只跑受
    影响 crate。普通 Rust 依赖允许按需下载；本任务不授权 Docker、真实模型/推理、真实 API、训练、云资源、上传、付费、
    全 workspace、宿主机/全局配置或远端状态变更。

## 4. 软性建议

以下建议基于 `main@4823c40` 的现行材料，不固定执行者的实现路线。执行者可根据 live code、测试和维护成本选择更优的等强方案，
并在关键决策记录中简要说明有实质影响的选择。

- 优先把协议/identity、服务 backend 与 typed client 的职责分开，保持公开 API 很小；若现有 crate 职责不匹配，新建一个或少量
  Publication Critic 专用 crate 通常比继续扩大 `codex-core` 更清晰，但不强制具体拆分。
- transport 可选择 loopback HTTP、UDS 或其他轻量本地方案；优先使用仓库已有、依赖少且跨平台测试清楚的机制，不必建设 TLS、
  token 鉴权、服务发现、远端部署控制面或常驻服务管理器。
- 可用 barrier/channel 驱动的 deterministic scorer 构造阻塞、延迟、错误和取消，不建议依赖长 `sleep` 猜时序。malformed wire
  或异常退出可以使用最小 fault injection；client 的恶意/超限响应校验也可由最小 loopback adversarial peer 覆盖，但不能把它
  冒充正式服务闭环，也不要把测试开关扩成生产产品能力。
- timeout 是否包含排队、是否允许极少量 bounded retry、queue-full 是立即失败还是有界等待，可由执行者按接口清晰度决定；一旦
  选择须冻结并测试。identity/contract/malformed 不应靠重试掩盖，任何 retry 都不得越过 deadline 或取消。
- 受控 scorer 可输出可预测的 finite score，并支持测试所需的有界故障模式；未来真实模型只需替换 backend 并声明自己的精确
  model/scoring identity，不应要求 B2b 改 wire 或重新解释 verdict。
- 配置宜采用 typed 有效配置并在启动前拒绝零/无界/互相矛盾的上限。数值以 2–8 Agent 本地场景和稳定测试为依据即可，不为
  本任务建立自动调参、性能 benchmark、容量审计或通用 policy 系统。
- 普通日志只保留 body-free 的 lifecycle、identity 摘要、failure kind、容量状态和耗时；若现有 tracing 已足够，不新增第二套
  trace。测试 sentinel 应覆盖 client 和 child process 的 stdout/stderr/error display。
- 测试优先收敛在新增/受影响 crate：纯合同测试验证严格 serde/identity/finite score，进程集成测试验证真实闭环与故障隔离。
  只有实际修改共享 crate 时才增加该 crate 的定向门禁；本任务不因“更放心”默认跑全 workspace。
- 独立验收聚焦合同单一来源、正式进程闭环、资源/取消确定性、日志正文泄漏、允许写集和 B2b/Team State 边界即可。发现普通
  finding 后窄修并复验，不建立多审查者委员会、复杂审计设施或长期合规流水线。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已从干净 `main@4823c40c1ce22c9fff0f24bc353ebcd6b2e22087` 创建
  `.claude/worktrees/055-publication-critic-service` / `worktree-055-publication-critic-service`；现有 Plan 052/053 worktree 未修改。
- 已核对根/`multidev/` 规则、README、当前 WBS、Plan 053、M3-A1 产品合同、Plan 053 验收日志、两份 2026-08-21 研究材料的
  服务相关事实，以及现行 workspace、构建锁和 `team_publish`/Team State 写入边界。
- 已确认本任务可只用 tracked 代码、受控 scorer、loopback/临时端点和定向 Cargo 完成；没有必须直接写主工作区或读取 ignored
  私有资产的事项。
- 已由只读子智能体独立复核 live repo 与计划草稿；据此明确 typed 字段边界不冒充正文来源审查、expected identity 来自调用方
  可信配置、真实 threshold 不由 B2a 冻结，并保留实现路线与数值选择空间。该复核只验收规划，不替代实现后的独立验收。
- 已冻结本执行合同；协议字段名、模块布局、transport 和具体资源数值留给执行者结合实现决定。
- 已在专用 crate 内完成版本化合同、可替换 scorer、loopback framed-JSON 服务、typed client、受控服务进程及定向回归；
  审查修复后的 `just test -p codex-publication-critic` 最终 27/27 通过，定向 Clippy 通过，Cargo/Bazel 锁按仓库入口更新核对。
- 首次实现提交 `2c47adb` 的独立审查发现公开配置字段可绕过构造器、无界 timeout 可导致 `Instant` 算术 panic；已将配置字段收口为
  crate 内部、在 client/service 消费边界复验，并统一应用 5 分钟硬上界及两个回归测试。

### 当前工作

- Plan 055 已完成。实现提交 `2c47adb`、配置边界修复提交 `dbc1d7a`；同一干净上下文独立审查者复验结论为 `PASS`。

### 本任务剩余步骤

1. 已完成：冻结版本化 schema、identity、failure、lifecycle 和资源数值并记录关键决策。
2. 已完成：实现可替换 scorer 服务与 B2b 可消费的 typed client；用受控 scorer 建立真实进程闭环。
3. 已完成：补齐资源、故障、取消、隔离和 body-free 日志回归，完成受影响 crate 的格式、lint 与定向测试。
4. 已完成：检查 diff/允许写集/并行 worktree，完成首个本地提交并交给唯一的干净上下文独立审查者。
5. 已完成：首次审查 finding 已修复、复验并追加提交；同一审查者再次验收为 `PASS`，本计划冻结。

### 阻塞项

- 当前无阻塞。Plan 054 可在 `eval/`、`training/` 独立推进，不是 B2a 的实现前置；双方不得互相读取或改写未整合状态。

### 当前验收状态

- 受控 scorer 的真实子进程闭环、严格协议/identity、资源门、timeout/cancel、故障隔离和正文 sentinel 回归均已通过；
  证据只覆盖受控 backend，不覆盖真实模型、最终 threshold、B2b 接入或产品端到端。
- 首次独立审查的配置绕过 finding 已修复，修复后 27/27 定向测试、Clippy、argument-comment lint、fix/fmt 通过；同一审查者
  复验为 `PASS`，无剩余 correctness/functionality finding。055 worktree 已有本地提交，尚未合并、推送或归档分支。

### 交接边界

- 本任务完成后冻结本计划。M3-B2b 只接收版本化服务合同和 typed verdict/failure 边界；发布流程、重写/fallback/mode、Team State
  invariants 的实现仍以 [`方向 3 WBS`](../doc/WBS/multi-agent-trusted-evidence.md) 为准，不在本计划继续展开。
- 最终模型/权重、本地部署资格和产品端到端证据不属于 B2a；受控 scorer 的通过不能替代后续工作包的真实模型验收。
- 055 工作树完成并通过审查后只保留本地提交。合并 `main`、推送和完成分支归档均需用户批准，不由本次执行授权推定。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | B2a 冻结服务与调用合同，但不冻结具体模块、transport、字段名和数值 | 关闭 B2b 必需的稳定边界，同时保留执行者按 live code 选择轻量实现的空间 | 架构与协议 | 已采纳 |
| 002 | 受控 scorer 只替换 backend，正式测试必须经过真实服务进程与同一 client/wire | 在无最终权重时取得可信的协议/生命周期证据，避免 fake 绕过正式路径 | 测试与可替换性 | 已采纳 |
| 003 | 对外只产生合法 `PASS/REWRITE` 或 typed failure，raw score 需经 finite/identity/scoring 校验 | 防止模型或协议故障伪装成产品判定，并给 B2b 稳定消费面 | verdict/failure | 已采纳 |
| 004 | B2a 不接 `team_publish`、不构造 projection、不实现发布 fallback 或产品取消状态机 | 保持 M3-B2a/M3-B2b 分工和现行 Team State 行为 | 产品边界 | 已采纳 |
| 005 | 允许普通失败自主窄修和有界重跑，只对原则性越界或无法收口的冲突停工 | 避免可修小问题造成不必要中断，同时保持安全与产品边界 | 执行流程 | 已采纳 |
| 006 | Plan 054 与 055 按写集并行；055 不读取其私有/未提交状态，主线整合另行批准 | 防止共享文档和数据资产互相覆盖，维持可审查提交 | 并行与 Git | 已采纳 |
| 007 | expected identity 由调用方可信配置提供；B2a 只冻结 threshold 的合同参与方式和受控测试值 | 避免信任服务自报身份或越界替 Plan 054/后续横评决定真实 scoring 参数 | identity 与并行边界 | 已采纳 |
| 008 | 在 `multidev/codex-rs` 新建单一 `codex-publication-critic` crate，library 与 service binary 共用同一私有 wire 定义；不依赖 `codex-core`、`team-state` 或 Local approval | 保持 B2b 消费 API 小且职责独立，避免把服务依赖压入核心 crate 或复制协议 | 模块与构建 | 已采纳 |
| 009 | transport 使用仅绑定 IP literal loopback 的一请求一连接 TCP，采用 4-byte 长度前缀和 strict JSON；协议没有 redirect、proxy、远端 hostname 或常驻端口语义 | 在接收分配前实施 byte cap，并天然消除 HTTP redirect/proxy 与既有 request-body logging 风险 | transport | 已采纳 |
| 010 | packet v1 只允许 qualification、权威角色、target、local title、candidate、最多 4 条 prior publication 的 continuity/freshness/coverage 和固定 Evidence V1 状态；正文 cap 对齐现行 canonical store 上界 | 完整承载 M3-A1 语义且没有 metadata 扩展袋；B2a 只保证字段面禁入，canonical 来源、权限投影和正文语义仍由 B2b 负责 | schema 与 B2b 边界 | 已采纳 |
| 011 | caller expected identity 精确绑定 service/protocol、qualification、model+tokenizer、input template、scalar projection、score domain、threshold 与 `score >= threshold` 规则；backend observed identity 和单值 score 均由服务复验 | ready 自报值只作 observed evidence，不能成为信任来源；漂移、非单值、非有限或越 domain 均不能形成 verdict | identity 与 scoring | 已采纳 |
| 012 | 受控 test scoring identity 使用 domain `[0,1]`、threshold `0.5`，`0.75 => PASS`、`0.25 => REWRITE`、等于 threshold 也 PASS；真实模型 domain/threshold 留给后续资格任务形成新 identity | 只冻结 threshold 如何参与配置、identity 与映射，不越界替 Plan 054/横评决定真实值 | 受控测试 | 已采纳 |
| 013 | 公共结果只有 `PASS/REWRITE` 或 `Contract/Infrastructure/Cancelled` typed failure；wire/service error 只有固定 code，body-bearing 类型使用 redacted Debug，错误和 stdout/stderr 不保存或回显 raw body | 让 B2b 可操作地区分失败，同时机械阻断正文经普通错误链和日志泄漏 | failure 与日志 | 已采纳 |
| 014 | production defaults 冻结为 request 128 KiB、response 16 KiB、scorer concurrency 1、queue 4、服务 job deadline 25s（含排队）、client E2E 30s、startup 60s、I/O 2s、graceful shutdown 3s + force/reap 2s、零 retry；受控测试可用显式更短的同型配置 | 符合单本地 GPU 与 2–8 Agent 小团队场景，所有等待和容量均有硬上限且测试无需长时间等待 | 资源合同 | 已采纳 |
| 015 | liveness、readiness 与 draining 分离；每次调用独占一个 loopback connection，queued/in-flight/等待响应取消通过 token 或连接关闭传播，server 以 admission/execution permit 和自身 deadline 作最终回收保证 | shutdown 后立即拒绝新调用，一次 timeout/cancel/fault 不污染下一请求或永久占用许可 | 生命周期与取消 | 已采纳 |
| 016 | `ClientConfig`、`ServiceConfig` 与 `RuntimeLimits` 的字段不向外部开放；构造器和 client/service 最终消费点均复验配置，所有 timeout 统一限制在 `(0, 5min]` | 防止外部 struct literal 或反序列化对象绕过 loopback/frame/resource 门，并避免无界 `Duration` 在 deadline 算术中 panic | 配置边界 | 已采纳 |
