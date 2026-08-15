# Plan 024：WP3b-A2 真实 E_final exact-token 普查与上下文预算决策输入

> 本计划是本任务的稳定合同。若需改变目标、范围或完成条件，应暂停并请用户确认。
> 本任务不决定后续资格档位；跨任务路线以 `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为准。

## 1. 目标与总原则

对项目内既有的完整 47 条真实 Guardian `E_final` 做一次可重复、无生成的 exact-token 普查，给出 4k/8k
上下文覆盖事实。计数必须使用 Plan 023 冻结的 GGUF tokenizer、模板和与真实 Local 请求一致的输入构造，
不得使用字符数、经验比例或近似 tokenizer。

本任务只复用现有安全读取、身份校验、资源锁和结果目录；**不得新增审计、可信发布、provenance、attestation、
资格证据或通用安全框架**。重复运行是执行验收，不要求建设专用编排或比较系统。

## 2. 范围

### 可以修改

- `eval/rondo_eval/local_approval/` 内完成普查所需的最小实现；必要时窄幅提取可复用的纯请求构造。
- `eval/tests/` 内少量直接相关测试，以及 `eval/results/baselines/` 内一份机器可读结果。
- 本计划的当前状态；成功后最小更新两份 WBS、`doc/WBS-COMPLETED.md` 和一份精炼 `agent_log/`。
- shared ignored `eval-data/local-approval/` 内本任务运行期临时对象；它们不是交付物，结束时清理。

### 不进入

- `mydev/`、`multidev/`、Cargo、Docker、云 API、训练、权重下载、上游升级或新增依赖。
- Plan 023 冻结证据、现有 47 条 E_final/meta、eval locks、4k 资格常量、capability 投影或真实配置的修改。
- token generation、审批判定、qualification success evidence、8k 试跑、L7、Guardian、Local M3 或压缩/裁剪实现。
- `.env.local` 内容：不得打开、搜索、打印、复制、hash、source 或间接加载。
- 证据正文、渲染 prompt、token ids/pieces 和模型 raw output 不得写入控制台、普通日志、Git 或测试快照。

## 3. 完成合同

1. 输入必须是既有完整集合，恰好 47 条、去重且全部完成；不得按 run outcome、长度或 fit 挑样。缺失、重复、
   额外或身份无法确认时停止，不发布总体结论。
2. 每条使用现有安全 reader 和 meta/identity 校验确认后再构造请求；只需复用现有设施，不新增账本审计层或身份子系统。
3. 复用真实 Local 请求构造及冻结 GGUF tokenizer/template；Plan 023 锚点必须精确得到 **5,313 input tokens**，
   否则整次普查无效。
4. 固定 `max_output_tokens=512`，4k/8k fit 按 `input_tokens + 512` 判断；报告两档覆盖数、未适配数、min、max
   和少量声明算法的分位数。
5. 产出稳定、机器可读的 JSON，包含版本、逐条记录和摘要；每条只保存稳定哈希标识、token 数和 fit 结果，
   不保存或打印正文。
6. 运行同一个普查入口两次并比较结果文件 digest 及总体摘要，两次必须一致；不要求实现专用 double-pass 框架。
7. 根据实测覆盖说明 4k/8k、oversize fail-closed 及是否已需考虑压缩、裁剪或更大窗口；不在代码中冻结
   “足够覆盖”的产品阈值。
8. 不调用生成端点，不写审批或资格成功证据，不修改资格档位、配置、capability，也不试跑 8k。
9. 真实运行使用现有共享 watchdog/build lock，GPU 独占并与 Cargo、Docker及其他模型任务互斥；成功或失败都清理
   本任务创建的 server、端口占用、receipt、私有日志和临时对象，未知对象不清理。
10. 少量 focused Python tests 与 `just eval-lock` 通过；收尾时只需确认 formal launcher 仍拒绝、capability 仍为
    `linux_cuda_built_model_unvalidated` 且没有新增资格证据，不为此扩充 doctor 或资格验证代码。

执行者只在 `024-wp3b-a2-exact-token-census` 分支实现、测试和提交；不合并、不推送、不删除 worktree，提交后交给 Codex 审查。

## 4. 实现提示（非强制）

- 冻结 b10333 的 `POST /v1/responses/input_tokens` 与真实 `/v1/responses` 共用 Responses 转换、Jinja 模板和 tokenizer，
  且不生成 token，是目前最直接的 exact 路径；允许采用可证明等价的更简实现。
- 当前只读观察为 47 份 E_final 和 47 份 meta，其中包含 infra-failed run 内已归档的 evidence；复用现有定位方式，
  不因 run outcome 筛样，也不为历史路径差异建设 provenance 图。
- 当前 `serve_environment()` 会进入 secret loader。普查宜使用不加载密钥的窄环境；硬要求只是不得读取 `.env.local`，
  不指定函数拆分或命名。
- 如果现有 client 不能直接复用，可提取纯 request builder；若已能保持同一构造，不必重构。
- 结果用普通 version/records/summary JSON 即可。稳定哈希可基于实际计数的 canonical payload；字段名、哈希定义、
  分位算法和文件名由执行者选择并简要声明，不附加身份或可信发布结构。
- 重跑可以是同一命令执行两次，再比较结果 digest/摘要；不要求在一个进程内做双 pass，也不要求重复建设 reader 校验测试。
- focused tests 建议只覆盖：47 条完整性/重复检测、`input+512` 边界与统计、稳定排序/序列化、锚点不匹配时停止。
  现有 reader/meta 行为若已有测试，不在本任务重复覆盖。

## 5. 实施与验收顺序

1. 核对任务分支、main 和其他 worktree 状态；确认现有锁、GPU和端口现场，未知对象只报告。
2. 用现有 reader/meta 设施建立完整 47 条输入集合，复用真实 request builder，实现最小 count、统计和 JSON 输出。
3. 补 §4 所述少量 focused tests，并通过相关 Python tests 与 `just eval-lock`。
4. 经现有共享锁启动冻结 count-only 服务，先验证 5,313 锚点，再完成 47 条计数；全程不改配置、不读 `.env.local`。
5. 清理本次服务和临时对象；再次运行同一入口并比较结果摘要，第二次完成后再次清理。
6. 只在全部条件通过后保留 tracked baseline；否则不发布总体结论。做一次 launcher/capability/资格证据收尾检查即可。
7. 根据结果给出 4k/8k 覆盖事实与下一步建议，明确 8k fit 不代表 8k 已实际验证。
8. 最小更新任务状态和权威文档，检查 diff、敏感正文与临时物，在任务分支提交并交给 Codex 审查。

## 6. 当前状态

### 已完成

- 2026-08-14：读取根规则、README、当前 WBS、数据布局、Plan 模板、Plan 023 及相关实现/日志。
- 2026-08-14：确认主工作区为 clean `main@40f3099` 且等于 `origin/main`；创建专用 worktree 和任务分支。
- 2026-08-14：只读确认当前有 47 份 E_final 和 47 份 meta，未打印或持久化正文；Plan 023 锚点冻结结果为 5,313。
- 2026-08-14：确认 b10333 input-token endpoint 可复用真实 tokenizer/template 路径，并记录历史 path 与 secret loader
  两个实现提示；它们不构成指定实现。
- 2026-08-14：按用户反馈两次瘦身，明确本任务不得演变为审计、provenance、attestation 或可信发布工程。
- 2026-08-14：实现 `eval/rondo_eval/local_approval/token_census.py`（复用现有 reader、meta 校验、受跟踪账本身份、
  真实 request builder、watchdog/build lock 与冻结服务合同），补 focused tests，`just eval-lock` 通过。
- 2026-08-14：用**当时的实现**同一入口真实运行两次，两次结果一致，锚点精确复现 **5,313**。但 **47 条只有
  24 条取得 exact token count**，另 23 条被冻结运行时在计数前拒绝（21 条 adapter 400、2 条通用 500），
  因此 §3.1 的“恰好 47 条全部完成”**未满足**。
- 2026-08-14：收尾确认能力仍为 `linux_cuda_built_model_unvalidated`、`model_backed_structured_output` 仍为 `not_run`、
  未新增任何资格证据；两次运行的 server/端口/私有临时对象全部清理。
- 2026-08-14：独立审查（`agent_log/2026-08-14-092926-plan024-independent-acceptance-review.md`）判定不通过。
  已按其整改项完成不加载模型的窄修复：incomplete 不再返回 `complete`、不写 baseline 并以非零退出；
  通用 500 恢复为整次 census failure（只有 adapter 的 400 记为该条证据自身的拒绝）；服务端 free text
  不再进入结果或控制台，只保留 HTTP 状态、error type 与 message digest；私有目录创建移到所有可失败前置之后；
  补 HTTP 分类、探针失败、incomplete 不发布、CLI 退出码与私有目录残留 5 项回归；
  撤回上一轮 baseline 工件（不完整且不符合当前 schema，历史保留在 `098e8c1`）。

### 当前状态：blocked / incomplete

- **WP3b-A2 未完成**：47 条的服务性尝试完整，但 exact-token 分布只拿到 24/47，不构成本计划要求的普查。
- 已确证的有限事实：24 条 counted 为 min 5,313、p50 7,886、p90 11,105、p95 12,354、max 18,921；
  按 `input+512`，这 24 条里 4k 适配 0 条、8k 适配 9 条。**这些数只描述这 24 条**；
  另外 23 条没有 token 数，因此全集的 fit 数量和上限都无法给出。
- 21 条已定性：其 `reasoning` item 没有数组 `content`，被 b10333 的 Responses adapter 以 400 拒绝，
  真实判定路径共用同一 converter，加大上下文不解决这 21 条。
- 2 条未定性：返回通用 500，即服务端对任意内部异常的兜底状态，原因（长度、形状、模板或其他故障）无结论。
- 版本边界：上述真实运行属于 `6b36d05` 之前的实现；整改后的当前代码只通过无模型回归，尚未真实运行。
- 交接：先另开独立任务，以**已证实的那 21 条**为输入做 provider-neutral static-payload 兼容
  （版本化、所有 static consumer 一致，同步更新 L1 等价合同与测试），通过无模型门禁后再重新申请一次
  真实模型授权、重跑 47/47 普查；重跑仍出现通用 500 时继续 fail closed 并单独诊断。
  该兼容工作不在本计划内实施。跨任务路线以 `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为准。

## 7. 关键决策

| 决策 | 说明 |
|---|---|
| 锁定结果，不锁定实现 | exact、锚点、全集和输出预算是合同；endpoint、schema、哈希和分位算法由执行者判断 |
| 只复用现有保障 | 不新增审计、provenance、attestation、可信发布、资格证据或通用安全框架 |
| 重跑是验收动作 | 同一入口运行两次并比较即可，不建设专用双 pass 系统 |
| 只报告覆盖事实 | 产品覆盖阈值和后续资格档位留给普查后的用户决策 |
| 结果文档不含时间戳 | 去掉日期后同一输入两次运行逐字节相同，重跑一致性直接用文件 sha256 判定 |
| 逐条登记拒绝，但整次 census 判为 incomplete | 拒绝信息对下一步有用，所以 47 条都登记；但任何一条没有 token 数就不满足完成合同，入口非零退出、不写 baseline。**上一轮把这种情况报成 `complete` 是错的，已撤回** |
| 只有 adapter 的 400 算该条证据自身的拒绝 | `400 invalid_request_error` 来自 Responses adapter 无法映射的 item 形状，真实 `/v1/responses` 同样会拒；通用 `500 server_error` 任何内部故障都会产生，短探针成功不能证明它源于该样本，因此恢复为整次 census failure |
| 服务端 free text 一律不落盘、不打印 | 没有任何过滤能证明服务端拼装的字符串不含证据片段；只保留服务端错误对象里的结构化字段（HTTP 状态、`type`、数值 `code`）与 message 的 SHA-256，足以区分拒绝类别 |
