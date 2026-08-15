# Plan 026：WP3b-A2b static payload v2 的 47/47 exact-token census 重跑

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只处理真实 exact-token 重跑；跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

基于已验收的 provider-neutral static payload v2 和现有 census 入口，使用冻结 b10333 CUDA runtime、
GGUF tokenizer、官方模板及真实 Local request builder，对既有 47 条真实 `E_final` 完成 count-only
exact-token 普查。通过一致性复跑后发布唯一正式 baseline 和全集摘要，为后续上下文档位决策提供事实；
本任务不做档位决策，也不产生任何模型输出。

### 完成/验收标准

- 既有完整集合恰好 47 条，47/47 都取得 exact input token 数；没有 request rejection、通用 500 或缺失计数。
- Plan 023 冻结锚点精确复现 **5,313 input tokens**，不一致则整次无效。
- 同一个正式 census 入口运行两次；两次逐条记录、全集摘要和结果 digest 一致。
- 固定 `max_output_tokens=512`，正式结果至少给出 4k/8k 的全集 fit 与不 fit 数，并保留逐条 token 数。
- `eval/results/baselines/local-approval-exact-token-census-v1.json` 是唯一正式 baseline，稳定、机器可读，
  不含证据正文、渲染 prompt、token ids/pieces 或模型输出。
- 当前相关 focused Python tests 与 `just eval-lock` 通过；不扩大到全量 eval。
- 两次运行结束后，本任务的服务、端口、私有日志和临时对象均清理；capability 仍为
  `linux_cuda_built_model_unvalidated`，没有资格成功 evidence。

## 2. 范围

### 允许修改

- 原则上直接复用 `eval/rondo_eval/local_approval/token_census.py`、static payload v2 builder 和已有测试；
  若运行前发现 census 自身的窄缺陷，可最小修改直接相关 `eval/` 代码与 focused tests。
- 成功后生成一份正式 census baseline，并精炼更新本计划、`doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 和一份 `agent_log/`。
- 只读处理 shared ignored 47 份真实 `E_final`/meta、冻结 runtime/model/template 和本机非密钥配置；
  运行期可使用现有 `eval-data/local-approval/` 私有临时目录，结束时只清理本任务创建的对象。

### 不允许修改

- static payload v2 语义、真实归档/meta、冻结 runtime/model/template/locks、资格档位常量、
  `rondo.local.toml`、qualification/launcher/capability 逻辑和 Plan 023 冻结证据。
- `mydev/`、`multidev/`、Cargo、Docker、云 API、训练、权重下载、依赖升级、L7 或 Local M3。
- 不做 generation、结构化审批判定、8k/其他档位试跑、压缩、裁剪或动态上下文实现。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash、source 或经现有 secret loader 间接加载。
- 不把真实证据正文、完整请求体、渲染 prompt、token ids/pieces 或 server free text 写入控制台或 Git。

## 3. 硬约束

1. 输入只能是现有生产 reader/meta 校验得到的完整 47 条集合，不得按旧结果、run outcome、长度或 fit 筛样。
2. 每条必须使用 static payload v2 与真实 Local client 共用的 request builder，再由冻结 GGUF 的 exact
   tokenizer/template 计数；字符数、近似 tokenizer 或自行渲染 prompt 均不算有效结果。
3. 只调用 count-only 路径，生成 token 数必须为 0；锚点不是 5,313 时立即失败且不发布 baseline。
4. 所有 fit 都按 `input_tokens + 512 <= context_size` 计算。本任务只报告覆盖事实，不选择或修改正式档位。
5. 两次正式运行都必须独立走同一入口和完整 47 条集合，并在每次结束后完成清理；一致性属于执行验收，
   不要求新增 double-pass 编排器。
6. 只有两次都 47/47 成功且记录、摘要、digest 一致时才能保留正式 baseline；任何不完整或不一致结果都不得发布。
7. 若出现通用 500，整次保持 incomplete 并停止，后续另开窄诊断任务；若出现 400 或其他形状拒绝，
   停止并回到窄兼容修复。不得现场换样本、放宽合同、反复调参或改上下文档位。
8. 真实运行必须使用现有共享资源锁/watchdog，GPU 独占并与 Cargo、Docker及其他真实模型任务互斥；
   失败路径同样清理本任务进程和私有对象，不处理来源不明的现场对象。
9. census 不等于 model-backed qualification：不得写审批/资格成功 evidence、晋级 capability、修改配置或绕过 launcher。
10. 只更新职责对应的权威文档；成功才写 WBS-COMPLETED。失败只在 plan、当前 WBS 和精炼日志记录阻塞事实。

执行者只在分支 `026-wp3b-a2b-exact-token-census-rerun`、worktree
`.claude/worktrees/026-wp3b-a2b-exact-token-census-rerun` 内实现、运行、记录和提交；不合并、不推送、
不删除 worktree，提交后交给 Codex 审查。

## 4. 软性建议

- 现有 `POST /v1/responses/input_tokens` 已是与真实 `/v1/responses` 共用 adapter、Jinja 和 tokenizer 的
  count-only 路径；若它按现状工作，优先不改生产代码。
- 可把第一次结果写到 ignored 的任务临时路径，第二次写正式 baseline，再直接比较 JSON 与文件 digest；
  也可采用同样简单且可证明等价的做法。不要为此建设发布、provenance 或 attestation 子系统。
- focused 门禁优先覆盖 `test_contracts_and_evidence.py` 与 `test_local_approval.py`；只有实际改到相邻配置代码时
  才补对应 config test。继续使用现有 ignored venv/cache，不运行全量 eval。
- 结果可沿用现有 schema、稳定排序、分位数和额外窗口统计；本任务不要求改字段或新增统计框架。
- 正式运行前检查锁、GPU、端口和既有进程；发现未知占用时 fail-closed 并报告，不自行清理。
- 两次正式运行是已授权范围；不要用额外模型生命周期做探索。若合同失败，保留非敏感错误码和必要现场事实后收口。

## 5. 当前状态

### 已完成

- 2026-08-14：Plan 025 / WP3b-A2a 已验收、合并并推送；`main == origin/main == 31e0157`，主工作区干净。
- 2026-08-14：47/47 已通过 static payload v2 无模型构造检查；Local client 与 token census 共用同一 v2 request builder。
- 2026-08-14：确认正式 census baseline 不存在，旧真实结果仍只有 24/47，capability 保持
  `linux_cuda_built_model_unvalidated`。
- 2026-08-14：用户已授权两次 count-only 真实本地模型运行、GPU 独占和只读处理 47 条真实归档；
  明确不使用网络/API、不外发数据、不下载权重且不读取 `.env.local`。
- 2026-08-14：从 clean `main@31e0157` 创建本任务专用 worktree 与分支，并完成本执行计划。
- 2026-08-14：模型启动前完成只读现场核对与无模型门禁，未发现 census 自身的直接窄缺陷，因此未改任何生产代码。
- 2026-08-14：执行第一次正式 census（共享锁 + GPU 独占 + count-only）。合成探针通过，随后在真实归档
  计数阶段收到通用 **HTTP 500 `server_error`**，blocker `count_endpoint_unavailable`、
  `message_sha256 bfd4dade…`，退出码 70。当前失败输出无法区分锚点请求还是后续集合请求；本次没有留下
  5,313 锚点的新测量记录。按 §3.7 整次 incomplete、未发布 baseline，服务、端口与私有目录均已清理
  （三项 cleanup 全为 true）。
- 2026-08-14：按用户「首次正式运行已触发合同失败即不再增加模型生命周期」的指示，**未执行第二次运行**，
  因此不存在两次一致性结论，也没有新增可发布 token 记录。
- 2026-08-14：只读离线确认一项独立兼容阻断（不占用模型）：`developer` 消息在套用模板前被
  `map_developer_role_to_system`
  统一改成 `system`，而冻结 Ministral 模板规定 `assistant` 之后只能接 `assistant`/`user`/`tool`，
  遇到 `system` 直接 `raise_exception`；minja 抛 `std::runtime_error`，服务端兜底为 500
  （只有 `std::invalid_argument` 才是 400）。聚合式离线检查 47 条真实 v2 请求得到 24 条可渲染、
  23 条因 `assistant → developer` 映射后违反模板顺序而失败。该结论证明这 23 条当前存在模板兼容问题，
  但不证明 Plan 026 的具体 500 发生于其中某条，也不追认 Plan 024 两条旧 500 的实际原因。
- 2026-08-14：收尾核验 —— focused tests 109/109 通过；`uv lock --check` 85 packages 通过；
  8080 端口空闲、无 GPU 计算进程、`eval-data/local-approval/` 无本任务残留、`git status` 干净；
  doctor 返回 `model_backed_validation: not_run` 与 `runtime_capability:
  linux_cuda_built_model_unvalidated`，无新增资格成功 evidence，正式 census baseline 仍不存在。

### 当前工作

- 本任务按合同失败收口，只落文档与日志，不在现场做兼容修复。

### 本任务剩余步骤

- 无。修复方向已交回两份 WBS。

### 阻塞项

- **聚合式离线确认会话角色顺序与冻结模板不兼容**：23 条真实 v2 请求含
  `… assistant → developer → user`，经 developer→system 映射后会触发模板顺序校验。
  这 23 条在当前形态下无法完成计数；该独立结论不等于已经定位 Plan 026 通用 500 的具体请求或原因。
  后续需在公共 builder 做版本化、provider-neutral 的角色顺序兼容，不能静默改写已冻结的 v2。
- **census 失败报告的诊断精度不足**（已记录，未在本任务修改）：`count_input_tokens` 的默认 code 让
  「锚点 500」与「循环中某条 500」都表现为 `count_endpoint_unavailable`，也不报已计数条数。
  因而本次只能确认失败发生在真实归档计数阶段，不能确认锚点是否已经成功计数；锚点 5,313 未被本次运行
  直接复证。该缺陷留给后续无模型任务增加最小阶段、样本哈希和失败前 counted 数。

### 当前验收状态

- **不通过**。47/47 未达成（本次没有新增可发布计数）、只运行一次、未发布 baseline、
  未写 `doc/WBS-COMPLETED.md`。
- 未运行：第二次 census、双跑一致性比较、`just eval-lock` 原样配方（该配方硬编码 `$PWD/eval-data/uv-cache`，
  本 worktree 无 `eval-data/`，改用等价的 `uv lock --directory eval --check` + 主仓 cache）、
  Cargo、Docker、云 API、全量 eval、任何 generation。

### 交接边界

- 本计划就此冻结。版本化角色顺序兼容与最小 census 失败阶段标识先由后续无模型任务处理；通过后再重新
  申请模型授权、重跑 47/47，最后才选择档位。后续路线只按两份 WBS 推进，不在本计划中追加。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 复用现有 census，不预设设施开发 | Plan 024 已建立入口，Plan 025 已闭合 v2 构造 | 实现范围 | 已采纳 |
| 002 | 两次运行是验收动作，不建专用编排系统 | 直接重跑和比较已足够证明确定性 | 执行与测试 | 已采纳 |
| 003 | 47/47 与 5,313 同时成立才发布 | 子集统计不能替代全集，锚点约束 exact 口径 | baseline | 已采纳 |
| 004 | census 后仍不选档位、不晋级 | 本任务只补齐上下文事实，不是 qualification | WBS 交接 | 已采纳 |
