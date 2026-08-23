# Plan 054：M3-A2 Publication Critic 输入合同、数据/评价设施与 Skywork 1.7B 基座测评 ExecPlan

> 本计划是 M3-A2 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通实现、依赖、模型加载、格式、测试和局部兼容问题
> 应在范围内自主修复并有界重跑。
> 本计划只描述 M3-A2；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

依据 [`Publication Critic 产品合同`](../doc/rondo-multi-publication-critic-product-contract.md)、Plan 055 已交付的 typed packet/identity，
以及 Plan 057 已交付的 Team State canonical preparation，冻结 Publication Critic **实际送给模型的输入合同**：模型可见内容、稳定
render、tokenizer/template/special-token/padding/batching 行为、上下文与溢出规则，以及 scalar score 的解释方式。

围绕该合同建立一套小而完整、可复跑并自动归档的 Publication Critic 专用评价设施和代表性样本；随后冻结
`Skywork/Skywork-Reward-V2-Qwen3-1.7B` 的 immutable revision、tokenizer、render 与 scoring identity，在本地完成有界真实基座测评，
形成质量错误切片、token 分布、延迟和内存/显存基线，并给 M3-B1a 留下明确的数据建设重点。

本任务的成功标准是得到可信且可复跑的结论，不要求基座模型表现良好。模型成功下载或加载不等于质量、训练或部署资格；若 exact
Skywork 路线在原则条件下 no-go，诚实收口同样完成本任务，不自动扩展候选模型池、启动训练或进入 M3-C1。

### 完成/验收标准

- [ ] 形成版本化输入合同，逐项定义模型可见的 qualification identity、权威 `root/member`、`new_event/existing_event`、canonical
      title/summary/optional handoff、continuity coverage/freshness/omission、`source_team_revision` / unavailable 时的
      `last_known_revision` 和 Evidence V1；同时明确 private transcript/reasoning、全 Team State、raw trace/evidence、Fact ID/body、
      监督标签与生成/审查元数据等禁入内容。
- [ ] 评价样本与 runner 直接消费 Plan 055 `PublicationPacket` 语义，并与 Plan 057 的权威角色、canonical preparation、最近至多四条
      event-local public history 和 body-free evidence projection 保持一致；不在 Python 或样本 schema 中另造一份近似 packet、clamp
      或 freshness 规则。若需要共享 bridge/exporter/parity fixture，可以做职责清楚的窄重构，但 Plan 057 review cycle 和最终 publish
      行为不变。
- [ ] 通过 Hugging Face 公共 metadata、模型仓库文件和真实加载冻结 exact model/tokenizer revision、license、模型类型、配置、权重文件、
      必要模型代码和依赖身份；下载后可在项目专用本地目录离线复验。若 exact 模型需要 remote code，只能执行已经固定 revision、完成必要
      检查并纳入身份的代码，不能继续跟随浮动分支。
- [ ] 冻结稳定 render 和 scoring identity：至少覆盖模板字节/版本、消息或字段次序、escaping、chat template 或等价输入形态、BOS/EOS 等
      special token、padding id/side、attention mask、batch 行为、scalar head/pooling/output shape、scalar projection/domain 和评价阶段临时
      threshold/校准规则；必须依据 exact 模型合同/实现明确选取哪个 tensor/index、投影变换前后语义及“更高 score 对应更合格 publication”
      的方向，不能看 measurement accuracy 后翻转。input identity 同时绑定最终采用窗口、overflow/drop policy 和新增 omission 的编码；这些变化
      必须升级 identity。Plan 055 的受控 scorer identity、`[0,1]` 和 `0.5` 不得冒充真实 Skywork identity。
- [ ] 用真实 tokenizer 分别统计固定 policy/render、candidate、continuity history、Evidence V1 与 special token 的 token 占用，覆盖代表样本、
      四类 publication、长 title/summary/handoff、history 较长、partial/stale/unavailable 合法边界、Evidence 数量省略和 Unicode/byte-scalar
      边界。统计以最终 template/special-token/overflow 处理后的真实 `input_ids` 为权威，分项 bucket 与总数严格对账；跨 segment token 归入
      framing，history 取舍后重新 render/tokenize，不能把各字段独立 tokenize 后相加估算。报告清楚标注这是 M3-A2 代表性/边界语料的真实
      tokenization，不冒充生产流量分布。
- [ ] 同时记录模型声明窗口、tokenizer/config 窗口、真实 forward 已验证窗口和本任务最终采用的可用窗口；最终值由模型事实、packet census、
      真实运行和本地资源共同决定，不直接照抄 metadata 最大值。
- [ ] 溢出语义确定且可测试：完整 canonical title、summary、optional handoff 和必需合同语义不能被 tokenizer 静默截断或被局部截成另一份
      publication；continuity 若需缩减，应按冻结的确定性规则整项取舍并诚实更新模型可见 omission。必需 candidate 仍不能完整容纳时形成明确
      typed/input failure，不得对残缺输入给出正常 score。
- [ ] padding/batching 不改变单样本含义：同一 packet 单独运行与进入代表性 padded batch 时，token/attention 边界和 scalar score 在声明容差内
      一致；空 optional handoff、不同 Unicode、边界长度和不同 batch 组成不触发错位 pooling 或读取 padding。正式推理冻结 deterministic
      inference/eval mode、dtype/device、同步与峰值采样方法，并用少量重复验证相同 packet 的 score 稳定性；不固定实现或轮数。
- [ ] 建立小规模版本化样本集和数据合同，覆盖新/已有 Event × 已完成/未完成四类、明显 `PASS/REWRITE`、关键 hard qualification、接近边界的
      原子差异、continuity/Evidence/长度变化及必要的角色变化；label、defect/slice、pair direction、sample/source/reviewer identity 和临时数据
      角色与 model-visible packet 物理分离。每条标注保留简短的 M3-A1 hard-requirement rationale/anchor 供数据检查与错误切片使用，但不进入
      renderer。样本没有明显模板、标签、长度或近重复捷径；M3-A1 的八条边界例只作语义锚点，不直接冒充完整 benchmark。
- [ ] 评价入口能从冻结样本与身份运行 token census、真实 scalar inference、临时 threshold/校准、指标、错误切片和结果归档；同一运行不会覆盖
      旧结果。原始运行对象留在任务专用 ignored 目录，入库结果保持小而可读；最小逐样本投影包含 `sample_id`、M3-A2 数据角色、expected
      label、raw scalar 或 typed failure 和 derived verdict，足以重算主要指标而不重复正文。
- [ ] 在看到正式 measurement 结果前冻结模型、tokenizer、render、scalar projection、样本 manifest、临时 threshold 选择规则和主要指标。
      threshold 若需校准，只使用预先标明的 M3-A2 calibration 角色并按预定规则计算，不能查看 measurement 标签来调参；这些角色不是
      M3-B1a 的正式 train/validation/test split。
- [ ] 真实基座结果至少报告：有效 score/失败数量、raw score 分布、临时 threshold 下的 confusion matrix、False PASS/False REWRITE、总体和
      四类/slice 指标、可适用时的 threshold-free ranking 或 boundary-pair 指标、主要错误例型、input token 分布，以及逐样本/P50/P95 延迟、
      wall time、峰值 RAM/显存和采用的 device/dtype/batch/window；说明 load/cold-start、warm forward、同步和 peak reset 的测量边界，避免把
      不同口径混成一个资源数字。
- [ ] 普通实现或基础设施问题可以修复、重建和重跑；有效模型输出不能因为“不满意”而定向重问。若 runner/合同缺陷使正式运行无效，应保留
      失败原因、升级 identity/version，并从冻结起点完整重跑，不能无痕覆盖或只挑有利样本。
- [ ] pure/fake/focused tests 覆盖 packet/监督隔离、deterministic render、token 组成和溢出、Unicode、padding/batch、scalar shape/domain/threshold、
      结果归档与 identity 漂移；另有真实 tokenizer 和真实模型 smoke/基线证据。fake、tokenizer-only、模型加载、真实质量与资源证据分层表述，
      skip 或未运行不写成通过。
- [ ] 结果明确给出 Skywork C0 基座的工程适配和质量 go/no-go、当前结论上限，以及 M3-B1a 应重点增加的 hard-defect、boundary、长度/context
      和监督类型；不冻结正式训练集、最终生产 threshold、部署格式或最终候选模型，不启动训练、量化、转换、RunPod/H100 或 M3-C1。
- [ ] 完成后只精炼更新方向 3 子 WBS、本计划状态/决策和一份 Plan 054 `agent_log`；顶层 WBS、WBS-COMPLETED、共享结果索引/入口留给后续
      主线整合者基于届时 `main` 窄同步。完成 diff/大文件/敏感边界/并行 worktree 检查并安排一次聚焦独立验收；普通 finding 由执行者窄修
      后复验。最终只提交 054 worktree 本地分支并保持干净，不合并、不推送、不归档或重命名分支。

## 2. 范围

### 允许修改

- `eval/` 内 Publication Critic 任务专用 namespace：输入/数据合同、render/tokenization/scoring、runner、CLI、轻量依赖 lock、fixtures、
  tests、model lock、结果和报告；可以新增架构契合的专用包或目录。
- `multidev/` 内为共享现行 `PublicationPacket`、Plan 057 canonical preparation/packet bridge、Plan 055 identity/scoring parity 所必需的最小
  public seam、adapter、fixture exporter 或测试；真实需要时可以窄调通用 typed scoring 合同，但不得改变 `team_publish` review cycle、
  Team State mutation 或关闭态产品行为。
- `training/` 内仅在职责确实属于数据与未来训练共同消费的输入合同、schema 或说明时允许落轻量合同；不得建立正式 train/validation/test
  数据、训练 recipe、权重、adapter 或训练输出。若 `eval/` 的版本化 identity 已足够，则无需修改 `training/`。
- 与上述专用能力直接相关的任务局部模板、fixture、lock、生成物、测试和必要构建/依赖定义。职责确实公共时可窄改已有 eval 原语；不得为
  绕开 Plan 058 冲突复制第二套公共设施。
- 本计划的“当前状态”和“关键决策记录”、一份精炼 Plan 054 `agent_log`，以及任务完成时
  `doc/WBS/multi-agent-trusted-evidence.md` 中 M3-A2 的当前事实、结论和 M3-B1a 交接。
- 主工作区 git-ignored `eval-data/` 下 Plan 054 专用的模型/tokenizer、Hugging Face cache、Python 环境、原始运行、临时文件与资源记录；
  具体布局可由执行者按现有规范选择，但必须有清楚的 `publication-critic/plan054` 或等强任务身份，且模型权重永不入库。

实现布局不预设为纯 Python、Rust 调 Python、独立本地进程或其他形式，也不预设模板文案、最终 token 数、样本数、batch、dtype、指标内部类
或结果文件名。执行者可根据 exact 模型、live code 和维护成本选择更优方案，只要共同语义、真实运行和验收边界成立。

### 允许只读核对与外部读取

- 根/局部规则、README、当前 WBS、Plan 053/055/057、M3-A1 产品合同、两份 2026-08-21 冻结研究材料、完成/验收证据，以及相关
  tracked 源码、测试、Git 历史和现有 eval 模式。
- Hugging Face 公共 model card、metadata、repository tree、license 和 exact-revision 模型/tokenizer/必要源码；允许普通公开网络查询和
  一个冻结 Skywork 1.7B revision 的下载/校验，不改变登录或远端状态。
- 主工作区和其他 worktree 的 Git/资源元数据只用于并行保护；不读取其他 worktree 的未提交内容或 Plan 058 ignored 私有资产。

### 不允许修改或执行

- Plan 057 的 publication review cycle、rewrite/fallback/cancel/replay、`team_publish` model-visible 产品行为、Team State canonical mutation、
  Event/Version/revision/wake/evidence/lifecycle 语义，或 M3-A1 qualification。
- `mydev/`、Plan 058 的 C2 行为/方向 1 评价/结果/子 WBS，其他任务 worktree、历史结果、来源不明修改或无关 README/WBS/研究快照。
- 顶层 `doc/WBS.md`、`doc/WBS-COMPLETED.md`、共享 `eval/results/runs.jsonl` 或其他并行共享入口；这些由后续主线整合者处理。
- M3-B1a 正式训练/验证/测试集、训练 recipe，或把 M3-A2 的已测代表/边界 cohort 冒充未来未见测试集；微调或任何训练，量化、转换、部署资格、
  候选扩池、RunPod/H100、HF Jobs/Endpoint、付费 API、真实 API、
  数据/模型上传、Hub/账号远端写入、CI/PR、上游升级、宿主机/全局工具链配置或 M3-C1。
- 通用模型平台、通用数据平台、第二套产品状态/trace、审计/签名/可信链、复杂鉴权、教师委员会、人工标注平台或大型 benchmark。

### 不允许读取/查看

- `.env.local` 内容，以及项目外个人文件、凭据、密钥、账号 token 或私有数据；不得运行会把 Hugging Face token 打印到终端的命令。
- ignored 历史 raw trace/payload、真实 publication/transcript/reasoning 正文、Fact observation 正文、Plan 058 私有运行数据或与本任务无关的
  模型权重。M3-A2 的“真实 token 分布”来自真实 tokenizer 对本任务代表/边界 packet 的测量，不以读取旧私密正文为前提。

### Git-ignored 与主工作区边界

tracked 实现、合同、测试和小型结果全部在 `.claude/worktrees/054-publication-critic-eval-baseline` 完成并提交；主工作区不得产生 tracked
修改。以下重资产/机器本地资产因 `eval-data/` 和环境目录被 git-ignore、linked worktree 不共享这些文件，预计必须直接放在主工作区项目根的
任务专用位置，执行者应在开始真实下载前单独核对并在交付中汇报：

- exact Skywork model/tokenizer、Hugging Face cache 与必要 frozen source；
- Plan 054 专用 Python/模型运行环境和依赖 cache；
- raw per-sample outputs、详细运行日志、临时/失败运行、RAM/VRAM 采样与其他大体积结果。

优先使用 `/home/sjc/desktop/RONDO/eval-data/models/publication-critic/`、`eval-data/publication-critic/plan054/`、
`eval-data/envs/publication-critic-plan054/` 和项目内 cache 的等强命名空间；可以采用更契合现有设施的项目内布局，但不得写用户全局
Hugging Face/Python 配置，不得把模型复制进 worktree 或用 symlink 伪装 tracked 资产，也不得触碰 Plan 058 namespace。任务内清理只针对本任务
明确创建且确认不再需要的临时对象；冻结模型、必要 cache 和原始测评产物是否保留按数据布局与交付需要决定，不清理来源不明资产。

## 3. 硬约束

以下约束只冻结必要产品、安全和可信测量边界，不固定执行者的可替换实现路线。

1. **053/055/057 是输入语义上游。** 模型输入由现行 typed `PublicationPacket` 驱动，raw publish 场景必须经过 Team State 共享
   canonical preparation 或经证明等价的同一原语；不能复制 title/summary/handoff clamp、角色、target、history 顺序、freshness、Evidence V1
   或 cap。现行 packet 的 title/summary/handoff scalar/byte 上限、最多四条 prior publication 和最多 32 个可见 evidence count 是产品事实，
   Plan 054 只决定如何稳定 render 与在模型窗口内处理，不能另设近似产品 packet。
2. **model-visible allowlist 与监督隔离。** completion、label、defect/slice、pair direction、sample/source/generator/reviewer identity、临时数据角色
   等只属于评价 metadata；renderer 只能读取版本化 packet 和固定 rubric/policy。new Event 明确无 continuity；existing Event 只含 packet 已允许的
   public local continuity，不补 event/version/Fact identity、participant/lifecycle/route、observation body 或私有上下文。
3. **exact 模型与输入/评分 identity。** 模型、tokenizer、必要 model code、render、adopted context window、overflow/drop/omission encoding、
   scalar projection/domain 和临时 threshold 必须由 immutable revision、版本/内容摘要和真实 smoke 共同确定，并能映射到 Plan 055 的
   `ModelIdentity` / `ScoringIdentity` 骨架；任一组成变化都升级相应 identity。模型自报、浮动 `main`、tokenizer 默认值、受控测试 identity
   或“能加载”都不能代替该组合身份；license 或所需代码无法确认时不得形成可用基线声明。
4. **完整 candidate 优先且无静默截断。** canonical title、summary、optional handoff、qualification 和必需结构标记必须完整进入模型；不得启用
   tokenizer 的隐式 `truncation=True` 后仍按正常样本计分。continuity 取舍须确定、整项、可解释并显式反映新增 omission；若必需内容仍超出最终
   采用窗口，按 input failure 处理。具体预算、保留顺序和可用窗口由真实 census/model/resource 结果冻结。
5. **单一 scalar 语义。** 明确 actual output shape、选取的 tensor/index、pooling/head、变换前后语义、higher-is-better 方向和从模型输出到一个
   finite scalar 的投影；离线 runner、临时 threshold 映射、
   Plan 055 identity parity fixture 与未来训练/runtime 引用同一 score 定义。raw logit 是否需要有界单调变换、operational domain 多大以及临时校准
   方法由实测决定；方向必须来自 exact 模型合同/实现而不是 measurement 标签，无法确认则 no-go/typed failure。不能沿用受控测试
   `[0,1]/0.5`，也不能用生成式 `PASS/REWRITE` 字符串建立第二判定器。有限 `ScoreDomain` 必须来自定义完备的 projection/合同或对 typed
   合同的职责清楚窄调，不能拿本次小样本 observed min/max 冒充完整 operational domain。
6. **先冻结口径，再测 measurement。** 样本、render/model/scoring identity、数据角色、threshold 选择规则、指标和错误切片在正式 measurement
   前进入本地 clean commit 或等强不可歧义冻结点。calibration 可以按预定规则产生临时 threshold，但 measurement 标签不得参与。看到质量结果后
   不得为提高分数改样本、输入、projection 或分母；真实合同/runner bug 可版本化修复并完整重跑，旧失败不覆盖。
7. **评价轻量但结论完整。** 只建设 Publication Critic 需要的最小数据/runner/归档/报告能力，不建立通用平台或复杂 provenance 系统；同时
   必须保留重算主要质量、token 与资源结论所需的 sample manifest、identity、代码 commit、运行环境和失败分类。基座 no-go 是允许的正式结论，
   但不得据此自动换模型、削弱 rubric、启动训练或把 M3-B1a/M3-C1 标为已解锁。
8. **普通失败可自主修复，不按结果挑选。** 下载中断、依赖/API 兼容、模型初始化、OOM 前的参数错误、render/batch/runner bug 和 focused test
   问题可在本任务范围内诊断、修复、重新下载/加载并重跑，不设僵硬的一次失败即停止规则。已产生合法 scalar 的样本不能因判定不好而重试；同一
   原因反复且合理窄修仍不能收敛、exact model 根本不提供可定义 scalar、license/identity 不清、必需 candidate 无法容纳或必须越界时，才形成
   blocker/no-go 并停止模型链。
9. **本地资源与外部边界。** Hugging Face 只做公开只读查询和一个 exact revision 下载，cache/环境都落在项目专用 ignored 目录；不登录、
   上传或修改远端。真实模型加载/推理必须经仓库共享 `scripts/with-build-lock.sh`/watchdog 取得同一全局重型资源槽，与 Plan 058 的 Docker、
   重型 Cargo、真实 API/模型任务错峰；允许执行者按 live capability 选择有界 CPU 或 GPU 路径，使用 GPU 时必须保持独占。记录适用的 RAM、
   VRAM、device 和 Windows `C:` 宿主容量事实；拿不到共享槽/watchdog 或所选路径的关键资源计数时 fail-closed。不得终止未知进程或清理
   未知 cache/model。
10. **Docker 只是有条件备选。** 优先使用任务专用项目内 Python 环境；只有职责清楚且本地隔离确有必要时，才可使用一个明确、任务专用、固定
    身份且并发 1 的 Docker 镜像/环境。此时完整遵守根规则的 Docker 与 Windows `C:` 前后计数、40/60GB 增量门和 80GiB floor，并只回收本任务
    精确创建的对象；不得无边界 pull/build 或建设通用容器平台。
11. **Plan 058 与 Git 隔离。** 054 拥有方向 3 输入/数据/评价/模型资产和方向 3 子 WBS；058 拥有 `mydev/`、C2 行为、方向 1 评价与子 WBS。
    两者可并行编辑和轻量测试，`eval/` 使用任务专用 namespace；公共原语只有职责确实共同且不复制替代设施时才窄改。054 不读取/修改 058
    未提交或 ignored 内容，不争写顶层 WBS、WBS-COMPLETED、共享结果入口；最终只提交 054 worktree，合并与推送等待用户批准。
12. **验证与证据诚实。** Python 只跑 Publication Critic focused tests/lock check；若修改 `multidev/`，使用其现有 `just` 入口和共享构建锁完成
    受影响 crate 的 fmt/lint/定向测试及必要生成物检查，不跑全 workspace。一次聚焦独立验收由计划审查者在执行者提交后进行；普通 finding
    可回到同一 worktree 窄修复验。任何未运行、skip、fake 或 tokenizer-only 证据都不能冒充真实模型质量或生产资格。

## 4. 软性建议

以下建议基于 `main@be427b4` 的现行代码，只提供高性价比方向。执行者可以依据 exact 模型、live code 和测试结果采用更优等强方案，并在
关键决策记录中简要说明实质偏离。

- 优先在 `eval/rondo_eval/publication_critic/` 建立专用能力，并沿用现有 eval 的配置、CLI、结果和测试风格。若新增 ML 依赖会与 Plan 058
  争写共享 `eval/pyproject.toml` / `uv.lock`，可采用受跟踪的任务局部环境 lock + 主工作区 ignored 专用 venv；只有依赖确实成为公共原语时才
  改共享 lock。
- Plan 057 私有 `build_packet()` 是当前唯一明显复用缺口。可窄抽为共享纯函数、提供 Rust validator/exporter，或用少量 Rust 生成/校验的 golden
  packet 保证 Python parity；选择维护成本最低的方案即可，不必为跨语言共享预建 RPC、schema registry 或代码生成平台。
- render 可优先使用模型官方推荐的 conversation/reward 输入形态，并把固定 rubric/policy、结构化 public context 和 candidate 明确分区；模板
  的 exact text/roles 由模型事实和 smoke 决定。不要依赖 JSON object 偶然 key order或 tokenizer 隐式默认值。
- overflow 可优先完整保留固定 policy 与 candidate，再从最旧 continuity 开始整条减少、保留最近的完整 prior，并在 render 中表达额外 omission；
  若实测证明另一确定性策略更符合模型与产品语义，可以采用并记录。不要在 prior summary 中间切断一句后假装它仍是完整 history。
- 样本规模以覆盖和诊断为准，不预设大数量。可用 M3-A1 四组例作语义锚点，扩展少量 synthetic product-shaped packet、原子 boundary pair 和最大
  合法 packet；contract-valid 但当前 Plan 057 不常产生的 `Unavailable` 应单列边界，不混作常见 runtime 分布。
- 若基座 score 没有官方产品 threshold，可先冻结小型 calibration/measurement 角色和一个简单、确定的临时规则，并同时报告 raw score、
  threshold-free 指标与两类错误；无需在 M3-A2 建复杂校准框架。临时 threshold 应在命名和 identity 上明确不是 production threshold。
- 资源测量可复用现有 GPU 独占、device-level VRAM sampler、host metrics 和结果归档模式，但不要复用 Local approval 的模型/schema/GGUF/launcher
  资格结论。代表/边界 forward 与小规模 baseline 足够，不需要把 metadata 最大窗口逐 token 扫满或运行大型 benchmark。
- Hugging Face 建议使用 `hf models info/card/list` 与 `hf download --revision <immutable-commit>`/cache verify 的只读路径，显式设置项目内 cache；
  不调用会显示 token 的 auth 命令，不修改登录状态。先做 download dry-run/文件清单和宿主容量检查，再下载一个 exact revision。
- 正式 measurement 前可在同一分支先提交输入合同、样本、runner 和 identity freeze，再运行真实模型并提交小型聚合结果。普通 smoke/infra 尝试
  留在 ignored run 目录；只有会影响结论的失败、版本变化和最终资源事实进入精炼日志。
- 独立验收聚焦：packet/canonical parity、model-visible allowlist、tokenizer/render/overflow、single-vs-batch score parity、scoring identity、样本捷径、
  baseline 重算、资源/清理、no-go/go 与 B1a 交接、Plan 058/Git 写集即可；不建立多审查者委员会或长期审计流水线。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已建立 Rust/Python PublicationPacket v1 parity、24 条监督物理分离样本、两条 cap census case、版本化输入/render/overflow/scalar
  合同、Publication Critic 专用 runner/归档/指标以及 exact 环境/model/freeze identity；没有修改产品 review cycle 或 Team State mutation。
- 已下载并离线校验 exact Skywork revision `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`。CPU BF16 finite scalar 未满足
  `1e-4` batch parity，正式 identity 采用 CPU FP32。
- v1 run `plan054-20260823T021754Z-measurement-fp32` 产生 16 条 finite scalar；独立验收发现 freeze identity、全 cohort parity 和
  render 描述不一致，因此 v1 结果只保留为 superseded 历史 attempt，不作为完成证据。
- v2 已修正资格/render/output shape/CLI/calibration artifact/committed-freeze identity，并对 8 条 calibration scored row 完成
  single、repeat、标准左右 padding 和替代 composition parity，最大 projected delta `1.5709748450998262e-06`；独立 16,384-token
  context forward finite。校准 run `plan054-20260823T040900Z-calibration-v2` 固定临时 threshold `0.9350569011196121`。
- v2 freeze SHA-256 为 `abb06abfa218695d38b8c9d681c939cbd37f8197d631c42ab3ccd63fa733797e`；24 个 Python focused tests、
  Rust typed identity 定向测试、`just fix -p codex-core`、format 与 diff check 已通过。
- 正式 run `plan054-20260823T042500Z-measurement-v2` 从 clean commit `c9a5e4671c3f74381b2bade7300f5e96a24bcdc7`
  一次完成：16/16 valid、零 typed failure，全部 16 条 scored row parity 最大 projected delta `4.523673587608634e-06`，
  accuracy / balanced accuracy `0.6875`、ROC AUC `0.765625`、atomic pair `7/8`；但最终独立复验发现 3 个 frozen declared slice
  名称不存在于正式 annotation/result，v2 因此只保留为 superseded attempt，不作为完成证据。
- v3 已对齐 10 个真实 measurement slice，把 pair 只保留为独立 `atomic_boundary_pair_ranking`，并新增 cohort 与 `quality.by_slice`
  双重覆盖校验；不改变 sample、render、model、scalar、threshold 或 calibration artifact，正式 measurement 将从新 clean freeze 完整重跑。

### 当前工作

- 正在固定 v3 freeze clean commit；随后完整重跑正式 16 样本 measurement。

### 本任务剩余步骤

1. 从 v3 clean freeze commit 完整重跑正式 measurement，并同步 tracked/raw 结果、报告、方向 3 WBS 与日志。
2. 交回同一干净上下文独立审查者复验；确认真实 finding 后窄修并再次交回，直到 PASS。
3. 复核 tracked/ignored 资产和资源结果，精确清理本任务不再需要的下载分块，完成 054 本地分支最终提交并保持 clean。

### 阻塞项

- 当前无阻塞。

### 当前验收状态

- v3 slice identity 与覆盖校验 focused tests 已通过；等待新 freeze commit、正式 v3 measurement 和最终独立复验。

### 交接边界

- 执行者对模块布局、Python/Rust 边界、模板、batch/window、临时校准、样本规模和内部数据结构保留自主权；审查者只按硬约束、真实产物和
  完成标准验收，不把软建议或个人实现偏好升级为门槛。
- 本任务完成后冻结本计划；M3-B1a 是否解锁、no-go 后如何调整路线只在方向 3 WBS 中写当前结论，不能由本计划自动扩写。M3-C1 继续等待
  M3-B1c 提供至少一个训练候选。
- 执行者完成并本地提交 054 worktree 后停止；不得合并、推送、rebase、归档、删除 worktree 或重命名分支。用户将把提交交回本计划制定者
  做独立验收，主线整合及共享文档同步另行批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | M3-A1 产品合同、Plan 055 typed packet/identity 与 Plan 057 canonical preparation 共同构成输入上游 | 数据、评价、训练和 runtime 必须审同一 publication，避免 Python 近似 schema 漂移 | packet、render、测试 | 已采纳 |
| 002 | Plan 054 冻结 exact model/tokenizer/render/scalar identity，但只使用评价阶段临时 threshold，不决定 production threshold | 本任务要形成可复验基线，同时保留后续训练和联合横评的正式选择权 | scoring、结果、交接 | 已采纳 |
| 003 | 完整 canonical candidate 不允许 token 级静默截断；history 可以按版本化规则整项缩减并诚实表达 omission | 截 candidate 会变成“审 A 写 B”，history 则已有有界/省略产品语义 | overflow、failure | 已采纳 |
| 004 | 正式 measurement 前用普通 Git/identity freeze 固定口径；runner bug 可版本化完整重跑，不按模型判定挑选重试 | 既防止看结果调口径，又不给普通工程问题设置一次失败即停止的僵硬门槛 | 执行、结果 | 已采纳 |
| 005 | 代表样本与边界样本使用真实 tokenizer/model，但不冒充生产流量统计；M3-A2 数据角色不冒充 M3-B1a 正式 split | 当前没有获授权的生产 publication corpus，任务目标是关闭输入与基座事实 | 数据、结论 | 已采纳 |
| 006 | tracked 交付留在 054 worktree；模型、环境和 raw runs 直接放主工作区项目根的 Plan 054 ignored namespace | linked worktree 不共享 ignored 大资产，且权重不得入库或重复下载 | Git、资产 | 已采纳 |
| 007 | 054 与 058 使用独立 eval namespace并共享单一重型资源槽；顶层 WBS/COMPLETED/共享入口留后续整合 | 允许两方向并行而不争写状态、依赖或宿主资源 | 并行、文档、资源 | 已采纳 |
| 008 | 允许必要的专用新能力，也允许职责匹配时复用/窄抽公共能力；不以改动最少或强行复用为目标 | 保持架构契合、干净且不重复建设第二套体系 | 实现架构 | 已采纳 |
| 009 | no-go 是有效结论，但不自动扩池、训练或启动 M3-C1 | 负面基线仍可指导 B1a/路线，原则边界不能靠扩大任务掩盖 | 结论、WBS | 已采纳 |
| 010 | 用 Rust canonical preparation 生成 parity fixture，再由 Python strict loader 消费；不公开生产 private bridge | 保证现行产品 packet 一致，又避免为离线评价扩大产品 API | packet、测试 | 已采纳 |
| 011 | 采用 16,384-token window，完整保留必需 candidate，仅整条丢最旧 continuity 并显式编码新增 omission | exact tokenizer census 与真实 context smoke 均支持推荐窗口，同时维持产品语义 | render、overflow | 已采纳 |
| 012 | CPU BF16 作为已记录不合格 attempt；正式 identity 采用通过 `1e-4` batch parity 的 CPU FP32 | 不用放宽容差掩盖同一输入在 batch 中的数值漂移 | model、scoring、资源 | 已采纳 |
| 013 | v2 正式确认基座工程与 M3-B1a 数据建设 GO、未微调 direct-product NO-GO；M3-C1 继续等待训练候选 | 7/8 pair ranking 显示可训练信号，但 3 个 false pass 与 new/completed 弱项不足以直接上线 | 结果、交接 | 已采纳 |
| 014 | v1 正式 run 因 identity/parity/render 合同不一致降级为 superseded attempt；升级 v2 后完整重跑 | 已产生 scalar 不等于满足冻结合同，不能用文档修饰替代重新测量 | identity、runner、结果 | 已采纳 |
| 015 | parity 覆盖全部 calibration/measurement scored row；两条 `token_census_only` cap 只做 exact census，另以独立 16k forward 验证 context | census cap 不参与 threshold/quality，强塞入 batch parity 会扭曲 `every_scored_row` 语义并放大无关计算 | parity、census、资源 | 已采纳 |
| 016 | v2 因 declared slices 与真实结果键不一致降级为 superseded attempt；v3 对齐真实键、加 cohort/result 覆盖校验并完整重跑 measurement | 冻结声明必须对应实际可计算指标，主分数正确不能替代缺失的 declared-slice 结果 | freeze、指标、结果 | 已采纳 |
