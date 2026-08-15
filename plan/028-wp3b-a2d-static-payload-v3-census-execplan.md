# Plan 028：WP3b-A2d static payload v3 的 47/47 exact-token census

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理本次真实普查；后续档位选择与 qualification 以两份 WBS 为准。

## 1. 目标

### 最终目标

使用已验收的 static payload v3、现有公共 Local request builder 和冻结 GGUF/tokenizer/template，
对既有 47 条真实 `E_final` 完成两次 count-only exact-token census。两次结果一致后发布唯一正式 baseline，
给后续上下文预算决策提供完整事实；本任务不生成审批结果，也不选择上下文档位。

### 完成/验收标准

- 既有全集恰好 47 条，47/47 都取得 exact input-token 数；没有 400、通用 500、缺失计数或事后筛样。
- 冻结锚点继续精确得到 **5,313 input tokens**；不一致则本次普查无效。
- 同一正式入口独立运行两次，两次逐条记录、全集摘要和结果 digest 一致。
- `max_output_tokens=512` 保持不变；正式结果至少给出 4k/8k 的全集 fit 与不 fit 数。
- 只有两次成功且一致后，才发布
  `eval/results/baselines/local-approval-exact-token-census-v1.json`；结果确定、机器可读且不含证据正文。
- 直接相关 focused Python tests 与 eval dependency lock 通过；不扩大到全量 eval。
- 每次运行启动的服务、端口、私有日志和临时对象均已清理；capability 仍为
  `linux_cuda_built_model_unvalidated`，没有资格成功 evidence。

## 2. 范围

### 允许修改

- 本计划的“当前状态”和“关键决策记录”。
- 成功时：唯一正式 census baseline、`doc/WBS.md`、`doc/WBS/local-approval-model.md`、
  `doc/WBS-COMPLETED.md` 和一份精炼 `agent_log/`。
- 失败时：只精炼更新本计划、两份 WBS 和一份执行日志；不得发布 baseline，也不写完成记录。
- 只读使用 Git common root 下 ignored 的 47 份 `E_final`/meta、冻结 runtime/model/template、
  `rondo.local.toml` 非密钥配置和共享 eval cache；运行期可创建现有设施所需的私有临时对象。

### 不允许修改

- static payload v3、公共 request builder、token census、qualification、launcher、冻结模板、模型/runtime、
  上下文档位、`rondo.local.toml`、capability 投影或既有资格证据。
- Plan 024—027、既有历史日志、`mydev/`、`multidev/`、依赖版本或无关测试/测评设施。
- 不新增诊断、追踪、provenance、attestation、可信发布或通用批处理设施。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash、source 或经 secret loader 间接加载。
- 不把真实证据正文、完整请求体、渲染 prompt、token ids/pieces、模型输出或服务端自由文本写入
  控制台、日志、测试输出或 Git。

## 3. 硬约束

1. 普查必须复用现有安全 reader/meta 校验、static payload v3 和真实 `LocalApprovalClient` request builder；
   不得另造请求、改变角色/模板、换样本或按长度、run outcome、错误类型筛选全集。
2. 只调用现有 count-only 路径；不得调用 generation/qualification，不得生成审批判定或资格 evidence。
3. 第一遍先写临时结果。只有其 47/47 成功、锚点为 5,313 后才执行第二遍；第二遍也先写临时结果，
   确认逐条记录、摘要和 digest 一致后再发布唯一正式 baseline。
4. 任一遍出现 400、通用 500、transport failure、锚点漂移、缺失计数或清理失败，都立即 fail-closed；
   不保留部分 baseline，不现场修改 payload/模板/档位，不靠重试或调参掩盖失败。
5. fit 必须按 `input_tokens + 512 <= context_window` 计算。本任务只报告覆盖事实，不选择或修改正式档位。
6. 两次真实运行都必须持有现有共享资源锁并满足 GPU 独占；与 Cargo、Docker 和其他模型任务互斥。
   每次结束都只清理本次创建的服务、端口占用、私有日志和临时对象。
7. 正式结果逐条只保存现有稳定的 hash 标识、token 数和 fit 状态；不得加入正文、路径、请求、token 明细
   或新的身份/审计字段。若现有 schema 已有摘要/identity 字段，直接沿用，不扩展体系。
8. 成功只证明上下文长度事实。不得晋级 capability、写 qualification success evidence、启动正式 launcher、
   做结构化审批推理，或把 4k/8k 算术 fit 表述为真实档位资格通过。
9. 只运行 census/evidence/local-approval 直接相关 focused tests 与现有 eval lock；不运行 Cargo、Docker、
   云 API、网络下载或全量 eval。未运行项如实记录。
10. 所有实现、运行记录、结果和提交都留在分支 `028-wp3b-a2d-static-payload-v3-census`、worktree
    `.claude/worktrees/028-wp3b-a2d-static-payload-v3-census`。执行者提交后停止，不合并、不推送、不删除 worktree。

## 4. 软性建议

- 当前 `eval/rondo_eval/local_approval/token_census.py` 已包含全集校验、锚点、count-only 服务、失败定位、
  确定性 JSON 和清理逻辑，预计直接运行即可；本任务不预期生产代码改动。
- 两遍都使用独立输出文件；逐字节比较是验证记录、摘要和 digest 一致的简单充分方式。
- eval lock 可使用指向 common root `eval-data/uv-cache` 的等价 `uv lock --directory eval --check`，
  不必在 worktree 复制 ignored cache。
- 执行日志只保留运行结论、必要计数、digest、门禁和清理状态；不要记录工具调用流水账。

## 5. 当前状态

### 已完成

- 2026-08-14：确认 `main == origin/main == dc1de71` 且主工作区干净；正式 census baseline 不存在。
- 2026-08-14：确认 Plan 027 已完成并合入：static payload v3 在无模型检查下 47/47 通过公共 builder、
  Local request 构造和冻结模板角色顺序门；census 已具备最小失败阶段定位。
- 2026-08-14：从 `main@dc1de71` 创建本任务专用分支和 worktree，完成本执行计划。
- 规划阶段未读取真实证据正文或 `.env.local`，未启动模型/GPU/服务，未运行测试，未修改 WBS 或主工作区。

- 2026-08-14：运行前门禁全部通过——正式 baseline 不存在、8080 空闲、无 GPU 计算进程、共享锁可用、
  `eval-data/local-approval/` 无残留；doctor 报 `configuration: valid`、`model: present`、
  `linux_cuda_built_model_unvalidated`、`model_backed_validation: not_run`。
- 2026-08-14：focused tests `test_local_approval` + `test_contracts_and_evidence` **116/116 通过**；
  `uv lock --directory eval --check` 通过（85 packages，指向共享 cache 的等价命令）。
- 2026-08-14：第一遍真实 count-only 运行 **fail-closed 于锚点**，详见下方验收状态。按硬约束 3/4
  未执行第二遍、未发布任何 baseline。

### 当前工作

- 已收口为失败执行。本计划冻结，不在本任务内继续尝试。

### 本任务剩余步骤

- 无。第一遍未满足锚点合同，硬约束 3 禁止第二遍，硬约束 4 禁止现场改 payload/模板/档位。

### 阻塞项

- **本计划的完成标准在当前代码下不可达**：合同要求锚点精确为 5,313，而 v3 payload 的锚点实测为 5,311。
  继续推进必须改动生产常量 `ANCHOR_INPUT_TOKENS` 或改写本计划的完成标准，两者都超出本任务范围
  （§2 不允许修改、决策 002）。按交接边界停止并上交 WBS。

### 当前验收状态

- **未通过**。第一遍在锚点阶段 fail-closed：模型加载、服务身份、`/props` 上下文与合成探针均通过，
  锚点请求被**成功计数**（无 400、无通用 500、无 transport failure），但得到 **5,311** 而非合同要求的
  5,313，触发 `anchor_token_count_mismatch`，退出码 70。
- 47/47 未达成；本次没有新增可发布计数，因此没有全集分布，也无法给出全集 4k/8k fit 数。
- 两次一致性：**不适用**（按合同只运行一遍）。
- 清理三项 `server_stopped` / `port_released` / `private_artifacts_removed` 全为 true；
  正式 baseline 不存在，capability 仍为 `linux_cuda_built_model_unvalidated`，无资格成功 evidence。

### 交接边界

- 本计划冻结。锚点常量在 v3 下如何重新确立、以及随后的 47/47 重跑，属于新任务，只按 WBS 另立并重新取得
  真实模型授权；不在本计划内继续维护。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 第一、第二遍都先写临时结果，一致后才发布 baseline | 避免第二遍失败时留下冒充正式结果的第一遍工件 | census 发布顺序 | 已采纳 |
| 002 | 本任务不允许生产代码或兼容逻辑变更 | Plan 027 已关闭前置兼容；本任务只验证真实运行 | 任务范围 | 已采纳 |
| 003 | ignored 资产从 Git common root 复用 | 现有路径设施已支持，无需复制数据或在 main 开发 | 运行环境 | 已采纳 |
| 004 | 锚点实测 5,311 后立即停止，不改常量也不改完成标准 | 两者都属本计划禁止修改项；锚点是否重新确立要由用户按 WBS 决定 | 本任务收口方式 | 已采纳 |
