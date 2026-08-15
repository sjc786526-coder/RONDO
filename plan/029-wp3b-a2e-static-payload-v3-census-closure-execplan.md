# Plan 029：WP3b-A2e static payload v3 的 47/47 exact-token census 闭合

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 v3 锚点迁移与本次完整普查；跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

在不改变 static payload v3 核心语义、模型身份、冻结模板、47 条归档集合和 fail-closed 标准的前提下，
把当前 v3 请求的 exact-token 锚点从 pre-v3 的 5,313 窄改为 **5,311**，随后使用现有正式入口完成两遍
一致的 47/47 count-only census，发布唯一正式 baseline，并闭合 WP3b-A2。

### 完成/验收标准

- 锚点常量、必要说明和直接测试已同步到 v3 的 **5,311**；历史 pre-v3 5,313 事实不被改写。
- 同一正式入口从头独立运行两遍；两遍锚点都精确为 5,311，且各自 47/47 均取得 exact input-token 数。
- 两遍都没有 400、500、transport failure、结构拒绝、缺失计数或清理失败；逐条记录、摘要和结果 digest 一致。
- 只有双跑全部成功且一致后，才发布唯一正式
  `eval/results/baselines/local-approval-exact-token-census-v1.json`；正式文件不含证据正文，失败或中间成功结果不占用该路径。
- census/evidence/local-approval 直接相关 focused tests 与 eval dependency lock 通过；未运行项如实记录。
- 本任务启动的服务、端口、GPU 计算进程和任务私有对象全部清理；来源不明的既有对象不被终止或删除。
- `max_output_tokens=512`、模型/runtime/tokenizer/template/样本集合均不变；capability 仍为
  `linux_cuda_built_model_unvalidated`，没有 qualification 成功 evidence。
- 成功口径同步到两份 WBS，WP3b-A2 写入 `doc/WBS-COMPLETED.md`，并留下精炼执行日志。

## 2. 范围

### 允许修改

- `eval/rondo_eval/local_approval/token_census.py` 中 v3 锚点常量及其必要说明；直接相关 focused tests。
- 只有真实运行已由现有定位信息证明明确、局部、provider-neutral 的实现缺陷时，才可最小修改直接相关的
  census / Local provider-neutral 适配代码和 focused regressions；每次整改不得越过 §3 的停止边界。
- 本计划的“当前状态”和“关键决策记录”。
- 双跑成功时：唯一正式 census baseline、`doc/WBS.md`、`doc/WBS/local-approval-model.md`、
  `doc/WBS-COMPLETED.md` 和一份精炼 `agent_log/`。
- 未成功时：本计划、两份 WBS 和一份精炼失败日志；不得写完成记录或保留正式 baseline。
- 只读复用 Git common root 下 ignored 的真实归档、非密钥本机配置、冻结模型/runtime/template 和 eval cache；
  运行期可在既有 ignored 位置创建本任务私有临时结果与服务对象，收尾时只清理本任务创建的对象。

### 不允许修改

- static payload v3 的核心语义或 schema、公共 payload 内容、角色/文本/顺序/消息边界、47 条样本集合。
- 模型、GGUF、tokenizer、冻结模板、runtime 身份、请求输出预算、上下文档位或 5,311 锚点标准。
- 锚点容差、跳过/替换/裁剪样本、错误降级、重试掩盖或任何 fail-closed 弱化。
- qualification、L7、launcher 正式资格、capability 投影、真实配置、已有资格 evidence。
- Plan 023—028、历史日志、冻结审计快照、`mydev/`、`multidev/`、依赖版本和无关测试/测评设施。
- 不新增通用审计、追踪、provenance、attestation、可信发布或批处理设施。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash、source 或经 secret loader 间接加载。
- 不把真实证据正文、完整请求体、渲染 prompt、token ids/pieces、模型输出或服务端自由文本写入
  控制台、任务日志、测试输出或 Git。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **锚点只做窄迁移。** 把 `ANCHOR_INPUT_TOKENS` 改为 `5_311`，并同步把当前实现说明从 pre-v3
   5,313 收敛为 v3 5,311；不得引入新 schema、版本注册表、容差或第二套锚点机制。历史文档中的 pre-v3
   5,313 保留为形成时点事实。
2. **先过无模型门禁。** 在首次模型加载前完成 diff 审查、直接相关 focused tests 和 eval lock；门禁失败只修
   本任务直接原因，通过后才进入真实运行。
3. **复用同一真实路径。** 两遍都必须复用现有安全 reader/meta 校验、static payload v3、真实
   `LocalApprovalClient` request builder、冻结 b10333 count endpoint 和同一个 census 入口；不得另造请求、
   换 tokenizer/template/model，或按长度、run outcome、错误类型筛选全集。
4. **只做 count-only。** 生成 token 数必须为 0；不得调用 generation、结构化审批、qualification 或 L7，
   不得写审批判定或资格 evidence。
5. **双跑后发布。** 第一遍写任务临时路径；只有第一遍锚点为 5,311 且 47/47 完整成功才执行第二遍。
   第二遍也写独立临时路径；只有两份完整结果的逐条记录、摘要和 digest 一致后，才把其中的字节一致结果发布为
   唯一正式 baseline。中间成功文件和失败结果不得出现在正式 baseline 路径。
6. **失败默认停止，局部缺陷才整改。** 任一真实运行失败后，先完成清理并依据现有有界 stage、archive digest、
   counted-before-failure、稳定错误 facts、源码和 focused reproduction 定位原因。只有同时证明“原因明确、局部实现
   缺陷、修复 provider-neutral、不改变 v3 核心语义/样本/模型/模板/锚点/fail-closed、可由 focused test 直接覆盖”
   时，才可进入一次整改循环。未知 500、信息不足或只能靠猜测的失败不得现场修改或盲目重试。
7. **整改后从头计数。** 每个整改循环只处理已定位的直接缺陷并补回归；重新通过无模型门禁后，此前所有真实运行
   都只算失败尝试，必须从新的第一遍 47/47 开始，成功后再运行新的第二遍。多个循环仍逐次服从 §3.6，不夹带
   重构或扩大设施。
8. **越界立即另开任务。** 若需要改变 static payload 核心语义或 schema、模型/tokenizer/template/样本集合、
   选择或修改上下文档位、改变 5,311、引入容差、跳样本或弱化 fail-closed，本计划立即停止，不做替代方案。
9. **资源与清理。** 每次真实运行都必须从本任务 worktree 使用同 checkout 的
   `./scripts/with-build-lock.sh`，持有现有共享锁并确认 GPU 独占；与 Cargo、Docker 和其他本地模型任务互斥。
   每次尝试结束都验证本任务服务已停止、端口已释放、无本任务 GPU 计算进程、任务私有目录已移除。若发现来源
   不明的占用，不得清理，直接停止并报告。
10. **结果边界不漂移。** 正式 baseline 沿用现有 schema，只保存现有稳定 hash 标识、token 数、fit、identity、
    摘要和 digest，不加入证据正文或新审计字段。fit 仍按 `input_tokens + 512 <= context_window` 计算；本任务只
    形成完整事实，不选择档位。
11. **状态声明克制。** census 成功只闭合 WP3b-A2，不等于 model-backed qualification 或 Local M3 成功；
    capability 保持 `linux_cuda_built_model_unvalidated`，qualification 状态不得晋级。
12. **只跑必要门禁。** 不运行 Cargo、Docker、云 API、全量 eval 或全量测试，不下载依赖；只运行直接相关
    focused Python tests、eval lock、两遍真实 census 及必要的局部整改回归。
13. **worktree 交付。** 所有 tracked 实现、结果、文档、日志和提交只留在分支
    `029-wp3b-a2e-static-payload-v3-census`、worktree
    `.claude/worktrees/029-wp3b-a2e-static-payload-v3-census`。执行者完成后自审 diff 并提交，然后停止；不合并、
    不推送、不删除 worktree、不重命名分支。

## 4. 软性建议

以下内容用于根据现有代码给出的执行建议，但不是固定约束。执行者可以依据实际代码和定位证据选择更窄、更清楚的做法。

- 当前锚点相关窄改预计只涉及 `ANCHOR_INPUT_TOKENS`、模块/行内说明，以及
  `eval/tests/test_local_approval.py` 中直接代表当前锚点或 `ANCHOR_INPUT_TOKENS - 1` 的断言/fixture；不要批量替换
  历史 5,313。
- focused 门禁优先复用 Plan 028 已验证的 `tests/test_local_approval.py` 与
  `tests/test_contracts_and_evidence.py`。worktree 可通过 Git common root 复用 `eval/.venv` 和
  `eval-data/uv-cache`；eval lock 可用指向同一 cache 的 `uv lock --directory eval --check` 等价入口，不复制环境。
- 真实运行前只做既有现场核对：正式 baseline 不存在、共享锁可用、目标端口空闲、GPU 无其他 compute process、
  既有任务私有目录无残留、doctor/capability 状态符合合同。不要为此扩充 doctor 或建立新清单。
- 两遍使用独立临时输出文件并比较 canonical JSON/digest；确认一致后再发布 tracked baseline。失败/中间文件在
  ignored 任务目录内短暂保留到定位或比较结束即可，收尾删除。
- 若需要整改，先写一个能复现明确缺陷的 focused regression，再做最小修复；测试技巧和文件拆分由执行者按
  现有局部惯例决定。
- 成功文档只写最终全集摘要、两遍 digest、一致性、门禁和清理结论；失败文档只写安全的定位 facts、是否满足
  整改条件和停止原因，不记录工具流水账或证据内容。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-14：Plan 028 已验收并合入本地 `main@f207d67`；主工作区干净，本地 main 比
  `origin/main@dc1de71` 超前 4 个提交。正式 census baseline 不存在，WP3b-A2 仍 incomplete。
- 2026-08-14：Plan 028 的唯一正式模型生命周期证明 v3 锚点请求被成功计数为 5,311；没有 400、500 或
  transport failure，但旧常量 5,313 触发 fail-closed，未遍历其余 46 条，第二遍未运行。
- 2026-08-14：确认现有 census 已具备全集校验、锚点先计、count-only、失败阶段定位、确定性结果、
  不完整 baseline 拒绝和任务私有清理；本任务不需要新增设施。
- 2026-08-14：从本地 `main@f207d67` 创建分支和 worktree
  `029-wp3b-a2e-static-payload-v3-census`，完成本执行计划。
- 规划阶段未读取真实证据正文或 `.env.local`，未加载模型/GPU、未启动服务、未运行测试，未修改 WBS 或主工作区。
- ignored 资产无需复制或在主工作区开发：worktree 已由 common-root 机制复用主仓的真实归档、
  `rondo.local.toml`、冻结模型/runtime、eval venv/cache。真实运行会在 common root 的 ignored
  `eval-data/local-approval/` 创建并清理任务私有对象；这不构成 tracked 主工作区修改。

### 当前工作

- 计划已起草，等待执行者按本合同实施。

### 本任务剩余步骤

1. 窄改 v3 锚点为 5,311，同步必要说明和直接测试。
2. 通过 focused 无模型门禁与 eval lock，完成运行前资源/状态检查。
3. 执行第一遍完整 census；仅在满足 §3.6 时进行局部整改并从头重跑。
4. 第一遍 47/47 成功后执行第二遍，验证逐条记录、摘要和 digest 一致，再发布唯一正式 baseline。
5. 完成清理、相关文档/日志同步、diff 自审和 worktree 提交，交给 Codex 独立验收。

### 阻塞项

- 无已知阻塞。其余 46 条在 v3 下的真实可计数性尚未验证，必须由本任务第一遍完整运行给出事实。

### 当前验收状态

- 待执行。当前只有 Plan 028 的一次锚点 5,311 观测；47/47、第二遍一致性和正式 baseline 均尚未完成。

### 交接边界

- 本任务成功后冻结此计划并以 WBS 作为后续唯一交接；不在本计划安排上下文档位、qualification、L7 或 Local M3。
- 若触发 §3.8，记录停止事实并把新的决策门交回 WBS，不在 Plan 029 内改写任务合同。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | v3 锚点直接冻结为 5,311，不新增锚点版本机制 | Plan 028 已取得一次 exact 实测，用户已明确选择窄迁移；额外机制没有本任务收益 | census 常量、说明与直接测试 | 已采纳 |
| 002 | 不额外运行一次只测锚点的模型生命周期 | 第一遍完整 47/47 同时是 5,311 的独立复证，可减少一次模型加载 | 真实运行顺序 | 已采纳 |
| 003 | 两遍均先写临时结果，一致后才发布 baseline | 避免第二遍失败或漂移时让中间成功冒充正式结果 | 结果发布 | 已采纳 |
| 004 | 失败整改以“已证明的单个局部缺陷”为循环边界 | 允许完成明确小修，同时禁止未知 500 下猜测和范围膨胀 | 故障处理 | 已采纳 |
| 005 | ignored 资产从 common root 原位复用，tracked 改动只在 worktree | 现有加载器和运行设施已支持，无需复制重资产或在 main 开发 | 执行环境 | 已采纳 |
