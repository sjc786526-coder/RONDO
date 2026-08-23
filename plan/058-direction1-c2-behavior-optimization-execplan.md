# Plan 058：方向 1 C2 行为边界、优化与有界正式复测 ExecPlan

> 本计划是 Plan 058 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通实现、构建、测试、runner、
> Docker、观测、结算和发布问题应在授权范围内自主诊断、窄修并按本计划重跑。
> 本计划只描述 Plan 058；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/*.md` 为唯一来源。
>
> 只有执行者收到用户明确引用本计划、并包含 §2—§3 所列 Plan 056 私有工件只读、Docker、真实 API 累计
> `50.000000 USD`、三类重跑、独立验收和精确资源清理授权的一次性提示词后，才可进入实施和真实运行。
> 最终只提交 Plan 058 worktree；合并、推送和分支归档均等待用户另行批准。

## 1. 目标

### 最终目标

1. 以 Plan 056 `formal-v6` 的真实 trace 为依据，逐项区分 C2 exact-command repeat 中的有害无进展重复、
   合理重复和证据不足，并冻结 C2 的触发、豁免、恢复、生命周期、关闭与回滚边界。
2. 只实现一个与上述边界一致的 C2 主要行为优化变量。机制必须有界、可关闭、可回滚；合理重复继续执行，
   不能只因 requester、完整命令字符串和 cwd 相同就自动抑制工具。
3. 用 fake、定向正确性回归和必要真实 commissioning 打通配置、构建、Docker、trace、投影、预算、恢复、
   结算与发布；随后冻结实际源码、binary、配置、评价口径和运行身份。
4. 在 Plan 056/v28 同一冻结 10 题上，以 `gpt-5.6-terra/medium` main 和
   `gpt-5.6-terra/low` Guardian 串行完成两个 round、20 个正式逻辑结果；唯一主要产品变量为 C2 优化。
5. 按正式前冻结的收益与无害门决定保留、调整或撤销行为变化。没有收益、出现负收益或最终撤销同样是完整、
   可接受的任务结论，不为得到正向结果修改样本、分母、指标或运行规则。

### 完成/验收标准

- [ ] 只读复核 `formal-v6` 6 个 C2 命中 slot 的 9 次 occurrence 及其任务终态、工具结果、文件/环境/进程或
      服务变化和运行时间线；必要对照有明确选择理由。每次 occurrence 至少归为“有害无进展”“合理重复”或
      “证据不足”，并给出简短证据理由；证据不足不作为限制工具执行的依据。
- [ ] 分类与回归覆盖：无新结果/文件变化/错误变化的重复、合理轮询、改码后复测、同命令但文件/环境/进程/
      服务状态变化、transport 或上游失败重试、compact/resume/user steer/明确继续、同命令不同结果或错误、
      写入/网络/未知副作用，以及参数/cwd/requester 不同。
- [ ] 在正式测评前冻结触发、豁免、恢复、生命周期/重置、关闭、回滚、收益、无害和停止规则；正式结果产生后
      不再放宽判据。tracked 记录只保留 body-free 分类与聚合，不复制 prompt、响应、完整命令或工具正文。
- [ ] 只实现一个 C2 主要变量；关闭态保持 Plan 056 被测产品行为。启用态不得仅凭 exact identity 改变执行资格，
      写入/网络/未知副作用调用继续执行；任何安全只读干预都必须有界、可恢复且诚实表达，不篡改已执行工具的
      原始结果、exit/error、审批、sandbox、Guardian、安全策略或用户控制语义，也不产生硬停止或不可恢复终态。
- [ ] 定向测试证明有害无进展场景得到预期的有界纠偏，同时上述合理/恢复/副作用/不同身份场景不被误阻断；
      关闭、取消、恢复、compact、steer 和任务结束后的状态边界清楚，状态不无界增长或错误跨任务复用。
- [ ] 至少一个独立 commissioning identity 完整走通 initialize → run → observe/project → settle → publish；
      commissioning 不进入正式分母，但其 main/Guardian 请求和任何重试全部计入 Plan 058 总预算。
- [ ] 修复 formal-v1 已暴露的 runner 缺陷后，必须以明确标记为 commissioning/diagnostic 的 sweep 逐槽覆盖旧
      formal-v1 尚未证明运行链完整的第 `8..20` 槽（含首尾，共 `13` 槽）；这些槽全部完成 agent → Terminal-Bench
      → verifier → observe/project → settle → diagnostic record 后，才允许统一冻结并启动下一次 formal。sweep 不
      重复诊断旧 formal-v1 已完成链路的前 7 槽，也不得把旧 formal 或 diagnostic 数据拼入正式分母。
- [ ] commissioning 完成后提交并冻结实际被测源码，重新构建和复验 RONDO Local binary/manifest，并为正式
      campaign 创建全新 campaign/batch/run/task-budget/pointer/result namespace；不复用 Plan 056 身份或账本。
- [ ] 正式复测只使用 v28 lock SHA-256
      `a9567cb0ddeaa9c8e7cdfbd7253000a8453ec1ebbb03ca359deae2c048f7880b` 的同一 10 题、镜像与冻结顺序，
      两个完整 round 形成恰好 20 个正式逻辑结果；不运行 Codex 对照、validation、holdout、额外题目/round、
      E-A、完整数据集、本地模型或训练。
- [ ] 下一 formal identity 在创建前把 20 个唯一绝对槽位的执行顺序冻结为
      `8 → 18 → 1–7 → 9–17 → 19–20`；8/18 是同一 campaign 内最先运行的高风险 canary，不是额外试跑。
      每个绝对槽恰好出现一次，正式分母仍为同一冻结代码、配置和 identity 的完整 `20/20`。
- [ ] 每个正式结果都有唯一 Terminal-Bench 终态、API usage/预算终态、原生 trace/C2 与正确性投影及对应
      Docker receipt。网络 attempts 不扩大正式分母；有效任务失败、reward 0 或 C2 未改善不重跑、不补位。
- [ ] 公共结果同时报告原始 exact-C2 occurrence、影响 slot/task、重复调用耗时、任务 pass/fail，以及冻结的
      harmful/reasonable refined 指标；私有 trace 和正文不进入 Git、公共结果、日志或终端汇报。
- [ ] 只有预冻收益门和无害门同时满足才保留启用的优化。无收益、负收益、不可接受误报、正确性/恢复/用户控制
      退化或可信 20/20 不成立时，不宣称正向性能结论，并关闭或撤销行为变化；必要回归、观测和负面/不完整结果保留。
- [ ] Plan 058 所有 commissioning、诊断、无效本地设施运行、网络重试、main 与 Guardian attempts 合计不超过
      `50.000000 USD`；最终 reservation/未决账闭合，或达到硬上限后停止新请求并诚实记录未完成项。
- [ ] Docker 与 Windows `C:` 前后资源事实闭合，只精确清理本任务创建且不再需要的对象；不清理 Plan 056、
      Plan 054、共享缓存或来源不明的镜像、容器、卷、build cache 和文件。
- [ ] 只运行受影响模块所需的格式、静态检查、定向测试和相称构建，不运行全 workspace、CI 或 PR；测试证据明确
      区分 fake、受控回归、Docker、真实 API 和未运行项。
- [ ] 完成一次聚焦独立验收。普通 finding 由执行者自主窄修和复验；若 finding 改变正式产品、冻结评价口径或
      数据有效性，则旧正式 campaign 不冒充有效结果，按 §3 的本地设施规则重新收敛。
- [ ] 只同步方向 1 子 WBS、本计划当前状态、必要的 body-free 结果/快照和一份精炼 agent log；顶层 WBS、
      WBS-COMPLETED 与共享入口留给后续主线整合者基于届时 `main` 窄同步。Plan 058 分支提交后 worktree 干净，
      不合并、不推送、不归档。

## 2. 范围

### 允许修改

- `mydev/` 中与 C2 触发、豁免、恢复、生命周期、关闭/回滚和必要有界观测直接相关的产品代码、配置、生成物与
  定向测试；具体接入层、状态所有者和反馈形式由执行者结合真实 trace 与 live architecture 决定。
- `eval/rondo_eval/`、`eval/tests/`、Plan 058 专用 lock/result namespace 及必要任务专用入口中，与分类、
  commissioning、20-result runner、预算/网络重试、Docker、投影、结算、恢复、比较和发布直接相关的设施。
- 若职责确实公共，可窄修改现有 eval 公共原语；若强行复用会扭曲 C2 语义，可在现有配置、生命周期、错误、
  测试和观测方式上新建职责清楚的 Plan 058 专用能力，但不得复制第二套 runner、telemetry 或结果体系。
- `plan/058-direction1-c2-behavior-optimization-execplan.md` 的当前状态和关键决策、
  `doc/WBS/teacher-harness-study.md` 的方向 1 当前事实、必要 body-free 结果/日期冻结快照，以及一份精炼 Plan 058
  `agent_log`。顶层 WBS/WBS-COMPLETED 和共享入口按用户的并行编排留给后续主线整合。
- 主仓库 Git common root 下 Plan 058 独占的 ignored `eval-data/` campaign、budget、run、bundle/manifest、
  build/work、分类证据和临时对象；命令仍从 Plan 058 worktree 发起，物理边界见 §5。
- 冻结 10 题所需的 Docker/Harbor 预检和任务运行，普通项目依赖下载、定向构建/测试，以及累计不超过
  `50.000000 USD` 的 Terra medium/low 真实 API 请求。

### 允许只读核对

- 根/`mydev/` 规则、README、当前 WBS、Plan 052/056、相关日志/完成记录、tracked 源码/测试、Git 历史，以及
  `codex-doc/` 和只读上游 `codex-source-code/` 中直接相关的冻结行为。
- Plan 056 `formal-v6` 6 个 C2 命中 slot 的完整私有 trace、API metadata、Terminal-Bench 终态、工具结果、
  verifier、文件变化和时间线；为区分误报所需的同 cohort 对照 slot，以及仍不能回答具体边界时直接相关的
  rehearsal/invalid campaign 工件。
- 主工作区和其他 worktree 的 Git/资源状态，用于保护并行任务和协调全局重型槽；不读取其他 worktree 未提交正文。

### 不允许修改

- Plan 056 的 tracked/ignored lock、campaign、budget、run、trace、结果、终态、公共结论和历史费用；历史只读，
  Plan 058 必须使用全新身份和命名空间。
- C1、C7、C11 或其他候选；Guardian、审批、sandbox、安全策略、方向 2/3、`multidev/`、Publication Critic、
  Plan 054 私有资产、M3-C1、训练资产、上游基线或冻结 `codex-source-code/`。
- 对写操作、网络副作用或安全性未知工具的自动抑制；把重复提醒做成工具硬停止、永久拒绝或不可恢复终态；仅凭
  命令字符串相同改变执行资格。
- Codex 对照、validation、holdout、额外题目/round、完整 Terminal-Bench、本地模型、训练、量化/转换、云任务、
  向外部服务上传/发布真实数据、全 workspace、CI、PR、合并、推送或分支归档。
- 第二套通用状态平台、数据库、常驻服务、telemetry、签名链、隐私审计、访问证明、复杂鉴权或严格因果系统，
  以及与 C2 无关的重构。

### 不允许读取/查看

- `.env.local` 内容；只能按根 `AGENTS.md` 静默检查文件存在、非符号链接、权限为 `0600`，以及任务所需变量存在
  且非空，并由既有严格 `KEY=VALUE` 数据加载路径向目标子进程最小注入，禁止 `source`、搜索、打印、复制或记录。
- validation/holdout 题目正文、solution、verifier 或逐题结果；Plan 054/其他任务的 ignored 私有资产与未提交文件。
- 项目外个人文件、其他仓库、凭据、密钥、私有数据和与 Plan 058 无关的 ignored 内容。

## 3. 硬约束

以下约束具有强制性。它们只冻结必要行为、实验和安全边界，不固定 prompt、状态机、指纹、wrapper 或其他可替换
实现路线。

1. **真实分类先于实现。** 先完成 formal-v6 9 次 occurrence 的逐项分类，再冻结边界并实现。分类至少区分
   “有害无进展 / 合理重复 / 证据不足”，以工具结果、错误、文件/环境/进程/服务状态、调用间事件、恢复原因和
   任务时间线为依据。无法从保留工件可靠判断时保持“证据不足”，不得补造最终文件系统事实或据此限制执行。
2. **同命令不是充分条件。** requester、完整命令和 cwd 相同只是候选入口；只有冻结规则能确认没有新状态、新
   信息或合法恢复原因时才可触发优化。参数、cwd 或 requester 不同不是同一次 C2；同命令但结果/错误或相关状态
   已变化、合理 polling/wait、改码后复测、transport/upstream retry、compact/resume、user steer、明确继续均为
   合法调用。信息不足或安全性未知时让调用继续。
3. **工具与用户控制优先。** 优化不得仅凭 exact identity 自动抑制 `exec_command`；写入、网络或副作用未知调用
   必须继续执行。若执行者选择对机械确认安全、只读且无进展的调用做 soft defer/短路或提供提醒/纠偏，该行为必须
   有界、诚实表达、非硬终态，并能由明确继续立即恢复；不得篡改已执行工具的真实结果、exit/error、审批、sandbox、
   Guardian 或取消语义。用户新输入、steer、明确继续和合法恢复必须能够继续执行。
4. **一个变量、清楚旁路。** 只实现一个 C2 主要行为变量，拥有明确 enable/disable 与回滚边界；关闭态在相关
   integration regression 中等价于 Plan 056 产品行为。必要配置、状态与观测只是该变量的支撑，不能夹带其他
   candidate、Guardian/安全策略改造或默认恢复 E-A。若新增模型上下文，须遵守 `mydev/AGENTS.md` 的增量历史、
   有界大小和 `ContextualUserFragment` 规则。
5. **判据先冻、结果后看。** Phase A 在看到 Plan 058 正式结果前冻结一个主要 harmful-repeat 收益指标及数值门槛，
   并冻结正确性、合理重复、恢复和用户控制的无害门。最低保留条件是 refined harmful signal 相对 Phase A 基线
   达到预冻收益，且没有材料支持正常行为被损害；原始 exact-C2 指标必须保持可比并完整报告，但合理重复不因原始
   C2 未下降而被错误优化。若 Phase A 没有有害基线，不能把零基线冒充正向收益。
6. **先闭环、再冻结正式身份。** fake/回归和必要构建通过后，至少完整打通一个真实 commissioning identity；
   其工件、费用和结果与正式命名空间隔离。随后提交并冻结实际源码，重建/复验 binary manifest，冻结配置、评价
   口径、收益/无害/停止/回滚门和正式 identity。正式首请求后不得修改被测行为或评价口径；commissioning 中可
   自主调整、修复并重跑，不强制额外完整 10 题 rehearsal，除非实际设施风险需要。
7. **正式输入与分母固定。** 正式 campaign 只运行 v28 同一 10 题与镜像，按冻结顺序串行两个完整 round，形成
   20 个正式逻辑结果；RONDO Local 单侧，main 为 `gpt-5.6-terra/medium`，Guardian 为
   `gpt-5.6-terra/low`。Plan 056 formal-v6 是历史基线；当前 `mydev/` 与其被测 commit 无差异，正式时仍须用
   clean source/binary/manifest 复验“唯一主要产品变量为 C2 优化”。
   下一 formal 的具体冻结执行顺序为 `8 → 18 → 1–7 → 9–17 → 19–20`：这里 `9–17` 明确排除已经第二个执行的
   绝对槽 18，因而总数仍恰好 20。8/18 只是同 campaign 内的早期风险暴露顺序，不产生额外结果或独立 canary run。
8. **三类失败严格分开。**
   - 运行链、请求/工具终态、观测、结算和结果完整，但任务失败、reward 0、C2 仍发生或性能不佳，是有效正式
     结果：进入分母，不重跑、不补位、不换 identity。
   - 本地 build/runner/Docker/观测/投影/结算/恢复/发布故障使当前正式 campaign 无效：保留工件和费用，自主窄修，
     重新完整 commissioning 和冻结后，用全新正式 identity 从干净状态重启；不得混合修复前后结果。
   - 可识别的单纯 transport、网络或临时上游故障：保持源码、binary、配置、题目、模型、effort、输入和本地运行
     条件不变，重试同一逻辑 slot；不设机械次数上限，但所有 attempts 进入同一预算且最终只发布一个正式结果。
     鉴权、配额、模型不可用或配置错误不是暂态网络故障，必须修复或诚实停止。
   formal-v1 已证明“单个普通任务闭环”不足以代表完整 commissioning。本次修复后新增硬性 diagnostic sweep，按旧
   formal-v1 顺序只覆盖第 `8..20` 槽（共 `13` 槽）：有效任务失败/reward 0 保留并前进；本地设施故障保留证据和
   费用、窄修并重跑当前诊断槽；纯网络暂态按同 logical slot 重试。13 槽全部完整后才统一冻结；之后只允许一个全新
   formal identity 从 `1/20` 开始，任何旧 formal/diagnostic 结果都不得进入正式分母。
   首轮 `8..20` 全部证明后，若后续 formal 又暴露新的本地设施故障，修复后的 commissioning/diagnostic 只复验受
   影响或尚未打通的题目/分支；不机械重跑未受改动影响且已有完整链路证据的其余题目。该局部复验仅用于重新建立冻结
   资格，绝不缩短 formal：修复后的全新 formal 仍须从 `1/20` 完整重跑，不得拼接旧正式结果。
9. **Plan 058 独立预算。** 新建从零开始的 task budget；不得复用或重开 Plan 056 已关闭账本。commissioning、
   invalid infra、诊断、网络重试、main/Guardian attempts 共用 `50.000000 USD` 硬上限。可靠 usage 按请求前冻结
   价格据实结算；机械确认未发送记 0；已发送或可能发送但 usage 不可靠按 `1.000000 USD/attempt`；发下一请求前
   至少预留最坏 1 USD，余额不足即停止。进程、修复或 identity 变化不得重置费用。
10. **重型资源全局串行。** 重型 Cargo 只走根共享 build lock/watchdog（优先已接入 `just` 的入口），不得直接
    Cargo 绕过；Docker/Terminal-Bench 与 Plan 054 真实模型加载/推理、任何重型 Cargo 和其他重型任务互斥，
    Docker 并发为 1。Docker 前后容量记录、Windows `C:` 门、内存/swap/项目存储阈值完全遵守根 `AGENTS.md`；
    拿不到锁、cgroup 或宿主容量事实时 fail-closed。只清理 Plan 058 exact identity/label 创建的对象。
11. **历史、正文和身份隔离。** Plan 056 全部资产永久只读；Plan 058 的 commissioning、无效和正式 identity 相互
    隔离且历史不改写。公共结果/body-free 记录只保存完成决策所需聚合；原始 trace、prompt、响应、完整命令和工具
    正文只留 ignored 私有区。不得为此建设新隐私、可信或审计平台。
12. **决策与交付不追结果。** 首个可信 20/20 是唯一正式决策数据。预冻收益与无害门均满足才保留；没有收益、
    负收益或误报不可接受时撤销/关闭行为变化，保留必要回归、观测和负面结果。正式后可以作出“收窄/调整”决定并
    落地定向回归，但 materially 改变已测行为的版本不得借旧 campaign 宣称性能有效，只能保持关闭或另行立项复测。
    普通问题与独立审查 finding 在范围内自主窄修；最终只提交 Plan 058 worktree，不合并、不推送、不归档。

## 4. 软性建议

以下建议基于 `main@be427b471edfa0b585c847fd8db4418aa735ea45` 的 live code 与保留资产，不固定执行者的
实现路线。执行者可依据真实 trace、代码、测试和维护成本采用更小或更优的等强方案，并在关键决策记录中简述有
实质影响的选择。

- 职责契合时优先复用 Plan 056 已验证的 `BinaryManifest`、task budget、Docker supervisor/Harbor preflight、
  Terminal-Bench runner、原生 trace、Team Lens/schema-v2 投影和结果发布。Plan 056 的 orchestration 冻结了自身
  identity 和更严的重试语义；强行复用会扭曲 Plan 058 时，应在公共低层原语上建立窄的 Plan 058 orchestration，
  不改写 Plan 056 历史合同，也不复制一套通用设施。
- 产品侧可评估现有 feature/config、`ToolCallRuntime`/`ToolCallSource`、turn/session 生命周期、tool result/context
  边界等接入点；这些只是架构地图，不预设状态必须放在 core、tool wrapper、prompt 或独立模块。若成组逻辑会继续
  膨胀 `codex-core` 高触达文件，优先职责清楚的小模块并保持 public API 最小。
- 私有分类表只需 occurrence id、slot/task、类别、原因码、状态变化摘要和私有证据引用；tracked 侧只留聚合。
  不要求哈希链、签名、访问日志、严格因果证明或第二套 trace。
- 收益门可从 harmful occurrence、影响 slot/task 和重复耗时中选择一个主要指标，并把其余作为保护/解释指标；
  可参考“至少一个 occurrence 的实质下降或按小样本比例设门”，但应根据 Phase A 实际分类一次冻结，避免机械追求
  原始 9 次 exact-C2 全部消失。无害门应纳入任务 pass/fail、合理重复误报、恢复/steer 和 off-path 回归。
- 主要 agent logic 改动按 `mydev/AGENTS.md` 包含 `mydev/codex-rs/core/tests/suite` 的 integration regression；
  必要的 classifier/state 纯逻辑可加窄 unit/fake。测试按真实接入点收敛，不为未改模块堆叠重复矩阵，不用长
  `sleep` 制造竞态。
- commissioning 的普通闭环可先由代表性 logical task 建立；一旦正式运行暴露此前未覆盖的设施分支，必须把该
  campaign 作废，并在修复后以 commissioning/diagnostic sweep 覆盖尚未证明的剩余槽。本次冻结范围固定为旧
  formal-v1 第 `8..20` 槽，不重复前 7 槽，也不扩大到额外题目、round、validation 或 holdout。
- 修改 `mydev/` 后遵守就近 `AGENTS.md`：重型命令走根锁/看门狗，完成代码后 `just fmt`，对受影响 crate 运行
  相称 `just test -p ...`/`just fix -p ...` 和必要生成物检查；不为“更放心”扩大到全 workspace。
- 独立验收聚焦分类证据、触发/豁免/恢复、零误抑制、关闭/回滚、20-result 分母、三类重跑、预算/资源和最终决策；
  直接复用保存工件与现有校验入口，不为审查新增平台。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已确认规划基线为 clean `main@be427b471edfa0b585c847fd8db4418aa735ea45`，与 `origin/main` 一致；已从该
  基线创建 `.claude/worktrees/058-direction1-c2-behavior`，分支 `worktree-058-direction1-c2-behavior`。
- 已核对根/`mydev` AGENTS、README、顶层/方向 0/方向 1 WBS、数据布局、execplan 模板、Plan 056 合同、完成记录、
  最终验收、资源清理、现行 C2 投影/候选逻辑和相关产品 tool-call/feature/lifecycle 接入面。
- 已确认 Plan 056 formal-v6 被测源码 commit `4965d7483d9e2812ec8e39debdb5988107e8101a` 到当前 HEAD 的
  `mydev/` diff 为空；当前产品基线没有夹带后续产品变化。
- 已只读确认 formal-v6 20 个 slot record 与私有三源仍保留在主物理根。C2 命中为
  `r01-t04-fix-git`、`r01-t08-sanitize-git-repo`、`r02-t01-db-wal-recovery`、`r02-t04-fix-git`、
  `r02-t06-openssl-selfsigned-cert`、`r02-t08-sanitize-git-repo`，合计 9 次、10,108 ms；规划阶段未形成最终
  harmful/reasonable 分类。
- 已确认 formal-v6 Cargo target 与 detached source 已按 Plan 056 清理，但正式 campaign、trace/API metadata、
  Terminal-Bench 结果、预算账本、公共结果和 runtime bundle/manifest 仍保留；Plan 058 不依赖已删除资产。
- 已由三个只读子智能体分别复核 execplan 合同、C2 live architecture 和 Plan 056 私有资产边界；规划整合不替代
  Phase A 的逐 occurrence 分类或实现完成后的独立验收。
- 已完成 Phase A：逐项复核 formal-v6 六个命中 slot 的 9 次 occurrence，冻结为 `1` 次有害无进展只读重复
  （`400 ms`）、`8` 次有状态变化或恢复依据的合理重复（`9,708 ms`）、`0` 次证据不足；总计与原始
  `9` 次、`10,108 ms` 严格对齐。六个命中 slot 已提供充分证据，未扩大读取同 cohort 对照或其他 campaign。
- 私有逐项表只保存在 Plan 058 ignored namespace；tracked body-free Phase A 聚合与预冻判据保存在
  `eval/results/observations/plan058-direction1-c2-phase-a-2026-08-22.json`，未复制命令、prompt、响应或工具正文。
- 已预冻主要收益门为 refined harmful occurrence 从 `1` 降至 `0`，并冻结合理重复/恢复/用户控制、所有工具仍
  执行、关闭态等价和可信 20/20 等无害门。原始 exact-C2、重复耗时和 pass/fail 仅作可比解释指标。
- 已完成 Phase B 产品实现：新增默认关闭的 `exec_command_repeat_guidance` feature，只在 RONDO Local main
  `exec_command` tool spec 中加入有界选择提示；Guardian、legacy `shell_command` 和关闭态均保持原行为，runtime
  不识别、抑制或改写任何调用/结果。提示明确保留状态变化、轮询、复测、恢复、transport retry、resume、steer
  与明确继续，并禁止仅凭命令/cwd 相同推断副作用安全。
- 已在既有公共预算、binary、Docker supervisor、Terminal-Bench runner、原生 trace 与 schema-v2 投影上新增窄的
  Plan 058 orchestration。该层冻结 v28、Terra medium/low、单请求物理尝试、50 USD 跨 identity task budget、
  三类重跑、body-free 发布与私有 refined classification，不复制通用 runner 或 telemetry。
- 已完成实现侧定向门禁：Rust 4 个相关 tool-spec/feature 测试通过；Python 相关 budget、Terminal-Bench 与 Plan 058
  orchestration 共 `126` 项通过；`just fix -p codex-core -p codex-features`、格式检查、Python compile、diff check 和
  零 API `eval-plan058 status` 均通过。恢复审查另补了退役 identity 不可重激活、冻结输入先验证后改指针的回归。
- 发生一次跨任务共享资源互斥事件：`23567b6` 的两段 Cargo 构建均经 canonical build lock/watchdog 成功，但并行
  Plan 054 模型校准报告在其生命周期内检测到外部 Cargo 并 fail-closed 终止。时间高度重合，按本次构建高概率触发
  处理；Plan 058 不接受该 build chain 为合规 commissioning 证据，未初始化 campaign、Docker 或 API。事件、判断
  与整改记录在 `agent_log/2026-08-22-plan058-shared-resource-collision.md`。
- 已从 clean detached source `c13ae981e3779305453621584e3259b5cb669d67` 完整重建有效 commissioning
  legacy/companion，分别用时 `22m59s`、`19m33s`，watchdog 均为 `status=0`、`stop=none`。runtime bundle 已用
  BinaryManifest 组装并复验，RONDO binary、code-mode host 与 bwrap SHA-256 分别为
  `859248187fd5b647bd380249a3c61ca0a46e50359da7f3464dd4a2fb288ea337`、
  `ad618afad71b6e0351f16d0bf009e8c9c82aeda92e4a8be23a318169f3aae098`、
  `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`。
- `plan058-direction1-c2-commissioning-v1` 已完成 Docker/Harbor 零 API 预检，随后真实运行在第 4 次需审批调用处收到
  冻结 Guardian 上限的 `guardian_logical_request_limit_exceeded`；agent 非零退出使 verifier 未运行，故运行链不完整，
  按本地设施类保留并发布为 invalid，不作为任务失败或模型结果。该 identity 共结算 28 个可靠 upstream attempts、
  `1.086600 USD`；不是 transport retry，未修改 Guardian、审批或安全策略。body-free 公共结果与详细 ignored 工件均
  保留，记录见 `agent_log/2026-08-22-plan058-commissioning.md`。
- `plan058-direction1-c2-commissioning-v2` 已以 `openssl-selfsigned-cert` 完整打通 initialize、零 API preflight、
  paid run、原生 trace/schema-v2 投影、预算结算、私有 refined 分类与 body-free 发布。运行链有效且任务 reward `0`
  作为任务失败保留、不重跑；7 个可靠 main attempts、0 Guardian、费用 `0.102113 USD`，raw/refined harmful 均为
  `0`，无害门全通过。Plan 058 跨 identity 累计费用为 `1.188713 USD`。
- `plan058-direction1-c2-formal-v1` 在冻结十题 preflight `10/10` 后完成前 7 个逻辑槽；第 8 槽
  `sanitize-git-repo` 再次触发冻结的第 4 次 Guardian 请求上限，adapter 把 agent 非零退出转成 `AdapterError`，
  Harbor 因而跳过 verifier。该 campaign 已以 `terminal_bench_infrastructure_failed` 作废并 body-free 发布：7/20
  只保留为私有诊断历史，不进入正式分母；96 个可靠 upstream attempts、`1.749536 USD` 已结算，Plan 058 累计
  费用为 `2.938249 USD`。
- 对 formal-v1 的复盘确认 commissioning-v2 只覆盖 7 main/0 Guardian 的普通路径，把 `1/1` 称为“彻底打通”是
  commissioning 验收判断错误；commissioning-v1 已暴露但未修复的 Guardian-limit 分支不应通过换题绕过。同时确认
  runner 将 `CODEX_HOME` 放在 `/tmp`，触发当前 release RONDO 拒绝创建 `codex-linux-sandbox` arg0 helper，导致普通
  workspace-write 调用在执行前失败。两项均按本地设施缺陷修复，不改 Guardian、审批或 sandbox 策略。
- 本 ExecPlan 已按用户要求保留必要行为、实验、预算和资源边界，把具体检测信号、模块、反馈形式、状态所有者、
  runner 拆分和数值收益门留给执行者基于 Phase A 证据自主冻结。
- 本计划未运行本地模型、训练、完整数据集、Codex 对照、validation、holdout、CI 或 PR。

### 当前工作

formal-v1 已因本地 runner 缺陷作废并关闭；旧 formal 的 7 个完整槽只作诊断历史。Guardian-limit 后继续 verifier/
真实 exit receipt 与非 `/tmp` CODEX_HOME 两项 runner 问题已窄修；独立 `diagnostic` mode 已纳入既有设施。diagnostic-v1
完成绝对槽 8–17 的 10 条完整链路；槽 18 自然复现 3 次 Guardian 后第 4 次本地上限，修复后的 adapter 如实保留 agent
exit `1` 并让 Harbor 完成 verifier/reward `0`，但 schema-v2 projector 未识别该类型化、未执行命令的 failed tool call，
campaign 以 `local_execution_or_projection_failed` 作废。该 identity 132 个可靠 attempts、`3.110194 USD`，Plan 058
累计 `6.048443 USD`。projector 已窄修为只接受精确的 typed Guardian-limit pre-runtime failure，不伪造进程 exit、
命令输出或已执行事实；相关 Python 回归 `171/171`、真实槽 18 私有 trace 投影和槽 8–17 十条既有记录 source
revalidation 均通过。下一 diagnostic identity 只复验未打通的绝对槽 18–20，不重复 8–17。

### 本任务剩余步骤

1. Phase C：用已通过 typed Guardian-limit 实迹验收的全新 diagnostic identity 只扫未打通的绝对槽 18–20。与
   diagnostic-v1 已完整的 8–17 合并为 commissioning 覆盖证据，直到 13/13 运行链完整；
   不把任何 diagnostic 数据放入正式分母。
2. Phase C 冻结：diagnostic sweep 完整后统一提交，从该 clean source 重新构建/复验 binary/manifest，冻结正式配置。
3. Phase D：以全新干净 identity 按 `8 → 18 → 1–7 → 9–17 → 19–20` 从执行位置 1/20 串行完成固定 10 题 ×
   2 round 的 20 个唯一正式逻辑结果；不得复用旧 formal 或 diagnostic 结果。
4. Phase E：比较 raw/refined C2、耗时、任务结果和正确性保护，作出保留/调整/撤销决定，完成文档、精确清理、
   聚焦独立验收、整改和工作树提交。

### 阻塞项

无当前阻塞。用户一次性执行授权已取得；进入重型 Cargo、Docker 或真实 API 前仍须机械取得共享资源槽并满足宿主
容量门。

### 当前验收状态

- Phase A：formal-v6 公共结果为有效 20/20、8 pass/12 fail；raw C2 为 9 次、6 slot/4 task、10,108 ms；refined
  基线为 harmful `1` 次/`400 ms`、reasonable `8` 次/`9,708 ms`、insufficient `0` 次。
- 实现门禁：Rust 定向 `4/4`、Python 定向 `126/126` 通过；共享看门狗记录 Rust 测试 peak memory
  `6,999,011,328` bytes、swap `0`、Windows C 可用空间前后 `192,379,305,984` bytes，资源硬门未触发。测试产生的
  Plan 058 worktree 独占 Cargo target 已精确删除，未动共享 cache/其他任务资产。
- Git：Plan 058 worktree 从 clean current `main` 创建；Phase A、实现快照与本事件记录只提交在 Plan 058 本地分支，
  未合并、推送或归档。
- 失效构建：`23567b6` legacy/companion 本侧均构建成功，但因已确认的跨任务互斥事实不作为 commissioning 验收；
  exact target、detached measurement worktree 与 `1,260,206,189` bytes legacy artifact 已清理，build metrics 保留。
  该事件没有 Plan 058 campaign、Docker 或 API 成本。
- 有效构建：`c13ae98` legacy/companion 与 runtime manifest 已通过 prepare/verify；冻结前本地启动参数的 sandbox bus、
  metrics 变量与 HOME/PATH 三次 fail-closed 均未发送 API，也未改变构建字节，成功证明单独保留。
- commissioning-v1：preflight `1/1`；正式 logical result `0/1`，campaign invalid；28 个可靠 upstream attempts、
  `1.086600 USD` 已关闭进总账。Docker 前后均为 `11.5GB`、容器/卷为 `0`，VHDX 增长 `0`，Windows C: 余量约
  `191.9GB`，未触发容量门。
- commissioning-v2：preflight `1/1`，完整 logical result `1/1`，7 个可靠 upstream attempts、`0.102113 USD`；
  Terminal-Bench outcome `completed`、task fail/reward `0` 作为有效结果，raw/refined harmful `0`，无害门全通过，
  Docker/VHDX 增长 `0`。累计 task budget 已结算 `1.188713 USD`，reserved `0`。
- formal-v1：preflight `10/10`，完成 7/20 后在第 8 槽发生本地设施故障，已作废并发布 body-free invalid；
  96 upstream attempts、`1.749536 USD`，最终 Docker `11.5GB`、容器/卷 `0`、VHDX 增长 `0`，Windows C: 余量
  `191108644864` bytes。累计 task budget `2.938249 USD`，reserved `0`。
- 未运行：正式 20-result、正式比较/决策、本地模型、训练、完整数据集、Codex 对照、validation、holdout、CI 或 PR。

### 主工作区 ignored 资产

`RepoPaths` 使用 Git common root，且根 `.gitignore` 忽略 `/eval-data/`。因此 tracked 编辑、测试源码和提交均留在
Plan 058 worktree，但执行阶段以下 I/O 会由 worktree 中的受控命令发起、物理发生在主仓库
`/home/sjc/desktop/RONDO` 的 ignored 区或宿主 Docker：

- 只读 Plan 056 私有资产：`eval-data/campaigns/plan056-direction1-bounded-observation-formal-v6/`、对应
  `eval-data/budgets/` 和 `eval-data/bin/rondo/` bundle/manifest；不得修改、复制、清理或续写。
- Plan 058 新建的 `eval-data/campaigns/`、`budgets/`、`runs/`、`bin/rondo/`、`build/`、`work/`、分类证据、
  预算和临时对象；必须使用 Plan 058 exact identity/namespace，不得覆盖其他任务资产。
- 主物理根已有 `eval/.venv`、`eval-data/uv-cache` 和其他职责吻合的项目局部共享缓存可复用，但不修改全局 Python
  或清理共享缓存。`rondo.local.toml` 只可由既有路径读取非密钥机器参数；`.env.local` 仍只做根 AGENTS 允许的
  静默门禁和最小变量注入。
- Docker 镜像、容器、卷、网络和资源记录属于宿主状态，不随 worktree 隔离；只创建/清理 Plan 058 明确标记对象，
  并与 Plan 054 真实模型、重型 Cargo 和其他重型任务串行。

规划阶段没有任何 tracked 工作必须在主工作区直接完成，也没有写入上述 ignored 区。执行阶段必须物理落在主根的
仅是既有 common-root 数据布局所要求的 ignored 运行资产和宿主 Docker 状态，仍应从 Plan 058 worktree 操作并在
最终报告中单独说明。

### 交接边界

- 本任务完成并通过独立验收后冻结本计划；后续方向 1 路线只交接到 WBS，不在本计划继续规划。
- 执行者最终只提交 Plan 058 分支并保持 worktree 干净。顶层 WBS、WBS-COMPLETED、共享入口、主线合并、推送和
  分支/worktree 归档由用户批准后的主线整合者基于届时 `main` 窄同步。
- 若与 Plan 054 并行期间确需修改公共 eval 原语，保持职责清楚和 Plan 058 专用 identity；不得读取/覆盖 Plan 054
  私有现场，最终整合时由主线整合者处理共享文件冲突。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 先分类 formal-v6 的 9 次 C2，再冻结行为边界和收益/无害门 | 原始 exact-command 指标不能区分有害与合理重复 | 分类、实现、评价 | 已采纳 |
| 002 | 同命令只作候选入口；证据不足、状态/结果变化和合法恢复一律继续执行 | 避免把合理轮询、复测与恢复误判成停滞 | 触发、豁免、回归 | 已采纳 |
| 003 | 副作用/未知调用继续执行；安全只读干预也必须有界、诚实、可恢复、可关闭 | 保留工具真值、安全边界与用户控制 | 产品语义、测试 | 已采纳 |
| 004 | 只实现一个主要 C2 变量，具体检测信号、接入层和状态所有者由执行者选择 | 控制实验变量，同时避免计划扭曲架构 | mydev、eval | 已采纳 |
| 005 | 至少一个完整真实 commissioning 后再冻结全新正式身份 | 先打通真实闭环，又不强制重复 Plan 056 的完整 rehearsal | runner、预算、身份 | 已采纳 |
| 006 | 正式固定 v28 同一 10 题、两个 round、Terra medium/low、20 个逻辑结果 | 保持与 Plan 056 的可比边界 | campaign、结果 | 已采纳 |
| 007 | Plan 058 使用独立 50 USD task budget，并按有效失败/本地设施/纯网络三类处理重跑 | 允许小问题自主收敛而不改变正式分母 | 预算、恢复、运行 | 已采纳 |
| 008 | 职责契合时复用现有设施，语义扭曲时在公共原语上新建窄能力 | 保持设计干净，不重复建设第二套体系 | 架构、runner、观测 | 已采纳 |
| 009 | ignored 运行 I/O 使用 Git common root；tracked 交付只在 Plan 058 worktree | 适配既有数据布局并保护主工作区 | 数据、Git | 已采纳 |
| 010 | 首个可信 20/20 按预冻门决定保留或撤销；正式后调整不得借旧结果背书 | 防止结果导向调参，接受负面结论 | 决策、交付 | 已采纳 |
| 011 | 最终只提交 Plan 058 worktree；共享权威文件与入口由后续主线整合者处理 | 遵守用户并行编排与集成批准边界 | Git、文档 | 已采纳 |
| 012 | Phase A 将 formal-v6 C2 冻结为 harmful `1`、reasonable `8`、insufficient `0` | 唯一 harmful 是相关状态与结果均未变化的第三次只读 scan；其他调用都有状态变化、复测或恢复依据 | 分类、收益门、回归 | 已采纳 |
| 013 | 主要收益门冻结为 harmful occurrence 从 `1` 降至 `0`；raw C2、耗时与 pass/fail 仅作解释和无害保护 | 小样本只有一个可信有害基线，不能追求删除八次合理重复或事后放宽判据 | 正式评价、最终决策 | 已采纳 |
| 014 | 单一变量采用默认关闭、无状态的 `exec_command` tool-spec guidance，不增加 runtime suppression 或跨调用状态 | 模型在作出第三次调用前已拥有历史与状态语义；post-execution nudge 无法减少当前孤立有害 occurrence，复杂 runtime detector 反而会扩大误判与生命周期面 | 产品、配置、回归 | 已采纳 |
| 015 | Plan 058 在既有低层原语上新增专用 campaign state/CLI，冻结 7.554 USD 的可靠 usage 最坏请求 reservation；未知 usage 仍按 1 USD/上游 attempt 结算 | Plan 056 orchestration 的固定 identity 与重试合同不适合 058，但通用 runner/预算/投影均可直接复用；请求前按冻结价格与 usage envelope 预留才能保证 50 USD 硬上限 | eval、预算、恢复 | 已采纳 |
| 016 | 初始化恢复先直接验证冻结 lock、manifest 与全部调用输入；仅未越过初始化窗口的 identity 可修复 pointer/state/budget | 防止错误恢复参数或已退役 campaign 在失败前重绑活动指针、重开预算 | identity、恢复 | 已采纳 |
| 017 | `23567b6` 构建因与 Plan 054 模型生命周期重叠而失效；保留事件证据，确认 Plan 054 v2 终态后 exact cleanup 并从新提交完整重建 | 本侧虽使用 canonical lock/watchdog，但跨任务互斥事实已被破坏，不能把成功字节冒充合规资源证据；仅瞬时拿到锁不足以证明模型窗口已结束 | 构建、资源、commissioning | 已采纳 |
| 018 | commissioning-v1 的 Guardian 上限终态按运行链不完整的 invalid 结算；不改 Guardian/审批，以 formal-v6 中 0 Guardian 且覆盖 C2 的 `openssl-selfsigned-cert` 新身份重做 commissioning | 第四次审批请求被正确硬拒绝后 verifier 未运行，不能伪装为有效 reward 0；但换题只证明普通链路，不能替代已暴露异常分支的修复和验收 | commissioning、预算、失败分类 | 部分撤销；由 020 取代冻结资格 |
| 019 | commissioning-v2 的完整 reward 0 作为有效任务失败保留；以其闭环提交冻结正式源码并重新构建，不复用 commissioning runtime identity | 运行链、verifier、投影、结算和发布完整，符合“有效失败不重跑”；正式必须绑定 commissioning 后的新 clean source/binary/identity | commissioning、正式冻结 | 已采纳 |
| 020 | formal-v1 永久作废；修复 runner 后用 commissioning/diagnostic sweep 只覆盖旧 formal 第 8–20 槽（13 槽），13/13 完整后统一冻结，再以全新 formal 从 1/20 只跑一次 | commissioning-v2 的 7 main/0 Guardian 只证明普通路径；commissioning-v1 已暴露的 Guardian-limit 分支被错误绕过，formal-v1 又确认 adapter 跳过 verifier 与 `/tmp` CODEX_HOME helper 两项本地设施缺陷。剩余槽先扫尾可尽早暴露问题且避免反复重跑前 7 题 | commissioning、runner、冻结、正式分母 | 用户确认，硬合同 |
| 021 | 首轮剩余槽覆盖完成后，若新 formal 暴露本地设施故障，修复后的 commissioning/diagnostic 只复验受影响或未打通题目；重新冻结后的 formal 仍从 1/20 完整重跑 | “局部重跑”描述的是脏版本/修复版重新打通，不是缩短正式分母；已有完整且未受修复影响的题目不做无意义重复，正式结果仍保持同一冻结版本和全新 identity | commissioning、修复、正式重启 | 用户确认，硬合同 |
| 022 | 下一 formal 在 identity 创建前冻结执行顺序为 `8 → 18 → 1–7 → 9–17 → 19–20` | 绝对槽 8 是已知最高风险 canary，18 次之；二者在同一正式 campaign 内优先暴露问题。18 不在后续区间重复，仍是 20 个唯一结果、无额外试跑或旧结果拼接 | formal identity、执行顺序 | 用户建议，已采纳 |
