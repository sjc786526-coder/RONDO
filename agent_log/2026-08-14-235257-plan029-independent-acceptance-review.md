# 2026-08-14 Plan 029 / WP3b-A2e 独立验收审查

- 审查对象：`029-wp3b-a2e-static-payload-v3-census@6a39db7`
- 任务基线：`f3c2d57`（Plan 029 规划提交）
- 审查范围：提交差异、锚点与 fail-closed 路径、直接测试、正式 baseline、两份 WBS、完成历史、
  执行日志、focused tests、eval lock、端口/GPU/私有目录/共享锁与 doctor 现场。
- 边界：未重新加载模型或重跑真实 census；没有运行 Cargo、Docker、云 API、全量 eval 或全量测试。

## 结论

**验收通过；任务目标完成。**

Plan 029 的实现与执行符合合同：锚点从 pre-v3 的 5,313 窄迁移为 v3 的 5,311，没有改变 static payload v3
语义、schema、模型、tokenizer、模板、样本、输出预算或失败标准；两遍真实运行均报告 47/47 完整成功且结果
逐字节一致，唯一正式 baseline 已发布。独立审查没有发现需要整改 Plan 029 的功能或正确性问题，
WP3b-A2 可以保持 closed。

当前分支仍未合并、未推送；主工作区仍停在 `f207d67` 且干净。capability 仍为
`linux_cuda_built_model_unvalidated`，qualification 仍为 `not_run`，因此本结论不包含 model-backed
qualification、L7 或 Local M3。

## 独立审查结果

### 1. 锚点变更是窄改，既有失败语义未漂移

`token_census.py` 的功能差异只有：

- `ANCHOR_INPUT_TOKENS = 5_313` 改为 `5_311`；
- 模块说明、常量注释和锚点前说明同步到 v3 口径；
- 继续保留并解释 pre-v3 5,313 的历史事实。

没有新增容差、版本注册表、第二套锚点、重试或错误降级。锚点仍在 47 条遍历前 exact 比较；400 结构拒绝、
通用 500、transport failure、缺失计数和清理失败仍按原合同阻止完整 baseline。直接测试只同步了三处当前锚点
fixture、一处 `锚点 - 1` 断言和一句过时注释，没有为凑绿弱化测试。

### 2. 正式 baseline 自洽、完整且不含证据正文

独立解析与复算 `eval/results/baselines/local-approval-exact-token-census-v1.json`：

- schema v1、`status=complete`、`missing_counts=0`；
- 47 条记录、47 个唯一 `e_final_sha256`，全部 `status=counted`，按 digest 稳定排序；
- ignored 归档现场恰好 47 份，逐文件 SHA 集合与 baseline 的 47 个记录标识完全一致；
- 锚点记录与受跟踪 selector 同为 `eaa2dfb1…ebaca`，`input_tokens=expected_input_tokens=5311`；
- 逐条复算 fit 无一不一致；重新排序 token 数得到 min 5,311、p50 8,989、p90 12,352、p95 13,754、
  max 22,499，4k fit 0/47、8k fit 11/47，与摘要一致；
- 删除顶层 `digest` 后按既有 canonical JSON 算法重算得到
  `22b8452717f1bcfa692cffa69389ebb4a21a0aef1a9187cd066879a6b0831144`；
- 整文件 SHA-256 为 `0c49ca78d8ca53ff2331fec7734e67f0d2302223d6e5f7a5d64554d5be882606`；
- 结果只含现有 identity、摘要、hash、token 数与 fit，没有路径、请求、prompt、token 明细、模型输出或证据正文。

仓库内只有这一份 exact-token 正式 baseline；`f3c2d57` 基线中不存在该路径，符合“比较两份临时结果后再发布”
的提交边界。执行日志记录两份临时结果 digest 与整文件 SHA 均相同、`cmp` 逐字节相等并已删除。审查者没有为
重复这项已完成的真实测量再增加两个模型生命周期。

### 3. 冻结身份、资格边界和文档口径正确

baseline 的 GGUF SHA、模板 SHA、CUDA runtime identity、服务 build info、request/serve contract digest 与现有冻结
合同一致，`generated_tokens=0`。两份 WBS 正确把 WP3b-A2 收敛为 47/47 全集事实，并保留以下边界：

- Plan 026 的旧通用 500 只写“未再复现，未单独定位”，没有补猜根因；
- exact-token census 只证明真实请求能被 count endpoint 精确计数，不冒充结构化审批成功；
- 4k 0/47、8k 11/47 是 `input+512` 算术覆盖，不是上下文档位资格；
- capability 与 qualification 均未晋级，正式 launcher 的 model-backed 门仍关闭。

`doc/WBS-COMPLETED.md` 只追加一次完成历史；Plan 当前状态与执行日志记录任务内细节，没有改写 Plan 023—028 或
冻结快照。

### 4. 独立门禁与现场

- `git diff --check f3c2d57..6a39db7`：通过；提交恰好 8 个申报文件。
- focused tests：`tests.test_contracts_and_evidence` + `tests.test_local_approval`，**116/116 通过，13.712s**。
- eval dependency lock：共享 cache 下 `uv lock --directory eval --check`，**85 packages**，通过。
- baseline：canonical digest、文件 SHA、全集 SHA 集合、统计量和 fit 均独立复算通过。
- 现场：8080 无 listener；无 `llama-server` 进程；NVML 无 compute process；
  `eval-data/local-approval/` 为空；共享构建锁未占用。
- doctor（无模型启动）：`configuration=valid`、`model=present`、
  `runtime_capability=linux_cuda_built_model_unvalidated`、`model_backed_validation=not_run`、
  `service=not_started`。
- 两个 ignored watchdog 目录权限为 0700、文件为 0600，只含 wrapper 资源计数与终态；它们是现有 wrapper 的小型
  本地运行记录，不是 census 临时结果、服务对象或正式交付物。允许随 worktree 保留到该 worktree 后续正常收口，
  不为此阻断验收或新建清理设施。

## 审查发现：后续路线仍有一处 4k 旧合同（不阻断 Plan 029）

Plan 029 已用全集证明 4k fit 为 0/47，但当前路线的旧段落仍把 Local M3 写成“4k model-backed”，生产资格合同
`model_backed.py` 也仍硬编码 `QUALIFIED_CONTEXT_SIZE=4096`、`gpu_layers=auto`、`fit=on` 和 4k evidence 文件名。
这不是 Plan 029 的任务内实现缺陷——本计划明确不选档位、不做 qualification——但在下一次模型运行前必须通过新任务
同步，否则 WBS 的当前事实与可执行资格合同互相矛盾。

## 替用户作出的决策

### 1. 接受 `6a39db7`，不要求 Plan 029 返工

锚点迁移、47/47 双跑、baseline 发布、清理和能力边界均满足合同。上节 4k 遗留属于 census 完成后才具备充分事实
作出的下游档位决定，不回写或扩张 Plan 029。

### 2. 下一次资格与 Local M3 的最小主档位定为 **8k**，4k 从前向路线退役

理由：

- 4k 已被全集精确证伪（0/47），不再具备真实证据 smoke 的功能意义；
- 8k 是现有 tracked example 与 launcher 已表达的冻结 baseline（8192 / all layers / fit off），可容纳 11/47，
  包括 5,311 锚点加 512 输出预算；
- 冻结工程核算中 Q4_K_M 权重 + 8k F16 KV 约 5.904 GiB，仍保留约 2.1 GiB 毛余量，符合此前约 1.5 GiB
  保守运行余量；16k 已约 6.966 GiB，只剩约 1.0 GiB，不能在未实测前作为本机 8GB 的首个资格档；
- 直接跳到 16k/24k、改 KV 量化或做压缩会同时引入新的显存、质量或语义变量，没有必要。

下一任务应窄迁移 WBS 的 Local M3 口径和 `model_backed.py` 的 4k 身份/evidence 合同到新的 8k 合同，补直接 focused
tests，再单独申请真实模型授权做 8k model-backed structured smoke 与 L7。8k 成功只证明“对档位内真实证据可用”；
11/47 的覆盖率必须继续显式报告，较长输入仍 fail-closed，不得声称全集可推理。

### 3. 不单独追查 Plan 026 的旧 500

static payload v3 已连续两遍对同一 47 条全集完成计数，旧 500 当前不可复现且没有仍在发生的功能缺陷。单开追溯任务
收益低；只有它在 v3/8k 新合同下重新出现时，才使用现有 stage/digest/count 定位信息按当前失败复现处理。

### 4. 不把 ignored watchdog metrics 升格为正式证据或清理阻断

保留现有 wrapper 的本地资源记录即可；正式 census 真相仍只有 tracked baseline、任务日志与提交。无需增加签名、
attestation、持久追踪或新的可信设施。

## 最终状态

| 维度 | 结论 |
|---|---|
| 执行是否做对 | **验收通过** |
| Plan 029 任务目标 | **完成** |
| WP3b-A2 | **closed** |
| 正式 baseline | 已发布，完整、自洽、唯一 |
| 上下文事实 | 4k 0/47；8k 11/47；全集 max 22,499 |
| 下一档位决策 | **8k**，由新任务迁移资格合同并真实验收 |
| capability | `linux_cuda_built_model_unvalidated` |
| qualification / Local M3 | 未完成 |
| Git 交付 | worktree 已提交；未合并、未推送 |
