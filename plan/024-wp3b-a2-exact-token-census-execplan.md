# Plan 024：WP3b-A2 真实 E_final exact-token 普查与上下文预算决策输入

> 本计划是本任务的稳定合同。目标、范围、硬约束或完成标准若需改变，应暂停并请用户确认。
> 本计划不冻结后续资格档位；跨任务路线仍以 `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为准。

## 1. 目标

对当前项目内完整的 47 条真实 Guardian `E_final` 做一次可重复、无生成的 exact-token 普查，给出 4k/8k
上下文覆盖事实。计数必须使用 Plan 023 冻结的 GGUF tokenizer、模板，以及与真实 Local 请求一致的输入构造；
不得用字符数、经验比例或近似 tokenizer 代替。

本任务只测量输入长度与静态窗口适配性，不产生审批结果，不验证 8k 推理，不改变资格档位或 capability。

### 完成标准

- [ ] 全集恰好 47 条，去重且全部完成；缺失、重复、额外或身份无法确认时，不发布总体结论。
- [ ] 每条均通过现有安全读取及 meta/identity 校验，再构造真实 Local 请求。
- [ ] exact-token 口径精确复现 Plan 023 锚点 **5,313 input tokens**；否则本次普查无效。
- [ ] 固定 `max_output_tokens=512`，按 `input_tokens + 512` 判断 4k/8k fit；报告各档覆盖数、未适配数、
  min、max 和足以说明分布的确定性分位数，并声明所用算法。
- [ ] 产出确定、机器可读的结果；逐条只保存稳定哈希、token 数和 fit 结果，不保存或打印正文、prompt、token pieces
  或模型输出。独立重复计数得到相同逐条结果及摘要。
- [ ] 基于实测覆盖给出下一步建议，包括 4k/8k 覆盖事实、oversize fail-closed 的需要，以及是否已需考虑压缩、
  裁剪或更大窗口；不预先替用户冻结“足够覆盖”的战略阈值。
- [ ] focused Python tests 与 `just eval-lock` 通过；真实运行完成资源清理。
- [ ] 最终 capability 仍为 `linux_cuda_built_model_unvalidated`，formal launcher 仍拒绝启动，无新增资格成功证据。

## 2. 范围

### 允许修改

- 本计划的当前状态与关键决策。
- `eval/rondo_eval/local_approval/` 内完成普查所需的最小实现；可窄幅提取可复用的纯请求构造。
- `eval/tests/` 内与普查直接相关的 focused tests。
- `eval/results/baselines/` 内一份版本化、机器可读的普查结果；具体文件名和 schema 由执行者按现有惯例选择。
- 成功后的两份 WBS、`doc/WBS-COMPLETED.md` 和一份精炼 `agent_log/`。
- shared ignored `eval-data/local-approval/` 内本任务运行期临时对象；它们不是交付物，结束时清理。

### 不允许修改或进入

- `mydev/`、`multidev/`、Cargo、Docker、云 API、训练、权重下载或上游升级。
- Plan 023 及其冻结证据、现有 47 条 E_final/meta、eval locks、4k 资格常量、capability 投影和真实配置。
- `rondo.local.toml`、依赖集合、GGUF、runtime、CUDA 或模板。
- token generation、审批判定、qualification success evidence、8k 试跑、L7、Guardian、Local M3、摘要/裁剪/压缩实现。
- `.env.local` 内容：不得打开、搜索、打印、复制、hash、source 或间接加载。
- 证据正文、渲染后 prompt、token ids/pieces 和模型 raw output 不得进入 stdout/stderr、普通日志、Git 或测试快照。

## 3. 硬约束

1. **全集完整**：以当前受跟踪记录和私有归档确认完整集合，最终必须恰好 47 条、去重且全部计数；不得按 run outcome、
   长度或 fit 结果筛样。集合不完整时 fail closed，不得发布分布或路线结论。
2. **安全读取与身份**：每条复用现有安全读取及 meta/identity 校验，并从通过校验的内容构造请求；不能只依赖 glob、
   JSON 可解析或待验归档自身声明。
3. **真实 exact 口径**：复用真实 Local 请求构造，使用 Plan 023 冻结的 GGUF tokenizer 和模板。锚点必须精确为 5,313；
   任何近似、fallback 或锚点漂移都使普查无效。
4. **窗口口径**：输出预算固定为 512 tokens，4k/8k fit 必须比较总需求 `input + 512`。结果至少包含两档覆盖数、
   未适配数、min、max 和声明算法的必要分位数。
5. **最小披露与确定性**：结果机器可读且排序/序列化稳定；每条只含稳定哈希标识、token 数和 fit 结果，不能反向泄露正文。
   至少一次独立重复计数必须得到相同逐条结果和摘要。
6. **无生成、无晋级**：不得调用生成端点、生成审批字段、写 qualification success evidence、改资格档位、配置或 capability，
   也不得试跑 8k。
7. **资源与清理**：真实模型运行必须通过仓库共享 watchdog/build lock，GPU 独占并与 Cargo、Docker及其他模型任务互斥。
   成功或失败都清理本任务创建的 server、端口占用、receipt、私有日志和临时对象；未知对象只报告、不清理。
8. **聚焦验收**：实现需有必要的 focused Python tests，并通过相关测试和 `just eval-lock`；不为本任务扩大到全量测试。
   fake/loopback 结果不能冒充真实 exact-token 普查。
9. **能力边界不变**：收尾时 formal launcher 仍应在生成前拒绝，capability 保持
   `linux_cuda_built_model_unvalidated`，`model_backed_structured_output` 仍为 `not_run`。
10. **交付边界**：执行者只在 `024-wp3b-a2-exact-token-census` 分支实现、测试和提交，不合并、不推送、不删除 worktree；
    由 Codex 独立审查后再决定交付。

## 4. 软性建议与当前观察

以下用于减少探索成本，不限定具体实现。执行者可采用更简单或更合适、但能证明满足 §3 的等价方案；偏离时简要说明。

- 冻结 b10333 提供 `POST /v1/responses/input_tokens`，源码与真实 `/v1/responses` 共用 Responses 转换、Jinja 模板和
  tokenizer，且不生成 token；这是目前最直接的 exact 路径。若采用其他路径，应证明请求构造和 token 语义等价。
- 当前只读观察为 47 份 E_final 和 47 份配对 meta，分布在 24 个 RONDO run；公共账本含 41 条 completed evidence
  和 6 条 infra-failed run 内已归档 evidence。这些是定位提示，不是额外冻结的数量合同，run outcome 也不应用来筛样。
- 早期公共 evidence path 与编号后的私有归档路径不同。可用 artifacts 范围及 `review_id` 匹配账本和 meta，也可采用其他可靠的
  一一绑定方式；不要直接假设所有历史 relative path 都能 join。
- 当前 `serve_environment()` 会进入 secret loader。建议为 census 使用无密钥、禁 ambient proxy 的窄环境；硬要求只是整个任务
  不得读取 `.env.local`，不强制具体函数拆分或函数名。
- 可提取 `LocalApprovalClient` 的纯 request builder，让真实 client 与 census 共用；若现有接口已能无漂移复用，不必重构。
- 稳定哈希可基于安全解析后的 canonical static payload，也可选其他与实际计数对象一一对应、不会泄露正文的定义，并在结果中说明。
- 结果可包含 schema/version、measurement identity、records、summary 和 recommendation，但不强制字段名或顶层分组；
  重点是机器可读、逐条最小披露、可重复验证。结果属于 measurement baseline，不是 qualification lock。
- 建议至少报告 P50、P90、P95，nearest-rank 是简单选择；执行者可选择其他明确且确定的常规分位算法，避免库默认含糊。
- 两次顺序 count pass 可共享一次 server 生命周期以减少模型加载；第二遍须重新计数，但不强制把所有不变文件再读一遍，
  只要能证明输入集合与第一遍相同且重复结果独立获得。
- 结果写入采用符合仓库惯例的安全确定性写法即可，不要求为单份 baseline 建造 fsync/no-clobber 发布协议。
- 路线建议应报告 4k/8k 的覆盖数与比例、8k 后仍 oversize 的数量及其含义。是否达到产品所需覆盖率由用户在后续决策，
  不在普查代码里预置 47/47 为唯一战略阈值。
- focused tests 可优先覆盖：47 条集合/去重失败、meta/identity 失败、请求同构、锚点失败、512 边界、统计与稳定输出、
  重复计数不一致、正文不落盘，以及失败清理。真实 5,313 只能由冻结服务验收，不能由 mock 代替。

## 5. 实施与验证顺序

### A. 基线与纯实现

1. 核对任务 branch、main 和其他 worktree 状态；只读确认共享锁、GPU、端口及现有对象，未知对象不处理。
2. 建立完整 47 条 manifest，逐条安全读取并验证 meta/identity；只输出数量或 aggregate digest，不输出正文或私有标识。
3. 复用真实请求构造，实现最小 exact count、统计、稳定结果与清理路径。
4. 补 focused tests，先通过相关 Python tests 与 `just eval-lock`。

### B. 唯一真实普查

1. 经共享 lock/watchdog 做资源与身份 preflight；不改配置、不读 `.env.local`，启动冻结 CUDA server 的 count-only 路径。
2. 先验证锚点为 5,313，再计数完整 47 条；独立重复计数并比较逐条结果及摘要。
3. 只有锚点、全集、重复一致性和清理全部通过，才写入 tracked baseline；否则不发布总体结论。
4. 复核 formal launcher 拒绝、capability/evidence 未变化，并确认本任务对象均已清理。

### C. 解释与交付

1. 基于实测结果报告 4k/8k 覆盖与 oversize 事实，给出可解释的后续建议，同时明确 8k fit 不等于 8k 已验证。
2. 成功时最小更新两份 WBS、WBS-COMPLETED 和一个 agent log；失败时只记录非敏感 blocker 与清理状态。
3. 检查 diff、敏感正文、tracked 大文件、ignored 临时物和各 worktree 状态，在任务分支提交并交给 Codex 审查。

## 6. 当前状态

### 已完成

- 2026-08-14：读取根规则、README、当前 WBS、数据布局、Plan 模板、Plan 023 及相关实现/日志。
- 2026-08-14：确认主工作区为 clean `main@40f3099` 且等于 `origin/main`；创建专用 worktree
  `.claude/worktrees/024-wp3b-a2-exact-token-census` 和同名任务分支。
- 2026-08-14：只读确认当前归档恰好有 47 份 E_final 和 47 份 meta，未打印或持久化正文；确认 Plan 023 锚点冻结结果为 5,313。
- 2026-08-14：确认 b10333 的 input-token endpoint 可复用真实 Responses/template/tokenizer 路径；发现早期 evidence path
  与编号归档不一致，以及现有 serve environment 会触发 secret loader。这些已作为实现提示而非指定实现合同记录。
- 2026-08-14：依据用户反馈将本计划从身份/发布框架式设计缩减为结果型合同，把 endpoint、join、schema、分位算法、
  双 pass 编排和路线阈值降为软建议。

### 当前工作与剩余步骤

- 仅计划已完成；尚未实现、运行测试、启动模型或计算 47 条 token。
- 执行者按 §5 完成最小实现、focused tests、唯一真实普查、结果解释与任务分支提交。
- Codex 随后独立复核合同、diff、测试、真实 anchor、重复一致性、结果摘要、capability 和最终清理状态。

### 阻塞与交接

- 当前无已知阻塞。anchor 不等于 5,313、全集不为 47、身份漂移、共享锁/资源不可用、GPU 非独占或清理失败时，
  必须停止且不发布总体结论。
- ignored 模型、runtime、配置和 47 条私有归档由所有 worktree 经 Git common root 只读共享；本计划不要求在主工作区持久修改它们。
- 本任务结束后冻结此计划；资格档位选择、8k qualification 或压缩路线继续由 WBS 承接。

## 7. 关键决策记录

| 编号 | 决策 | 原因 | 状态 |
|---|---|---|---|
| 001 | exact 语义、5,313 锚点是硬约束；具体计数 endpoint 是软建议 | 锁定结果口径，同时允许等价实现 | 已采纳 |
| 002 | 完整 47 条是硬约束；当前 run/evidence 分布只是定位观察 | 防止挑样，不把易漂移仓库快照变成新合同 | 已采纳 |
| 003 | 结果是 measurement baseline，不是 qualification lock | 普查不承担晋级或资格证据职责 | 已采纳 |
| 004 | schema、哈希、分位和双 pass 生命周期由执行者选择并声明 | 保留确定性与最小披露，不微观规定实现 | 已采纳 |
| 005 | 只报告覆盖事实和建议，不在代码中冻结“足够覆盖”阈值 | 战略取舍留给普查后的用户决策 | 已采纳 |
