# Plan 030：RONDO Local 12k model-backed qualification 与 capability 晋级

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 12k model-backed 资格闭合；跨任务路线、优先级、顺序和依赖以
> `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

把 RONDO Local 当前仍绑定 4k 的 model-backed 资格合同迁移为 **12k（12,288 tokens）**。在当前
RTX 4060 Laptop 8GB、冻结 b10333 CUDA runtime、唯一 Ministral GGUF、冻结 tokenizer/template 和
static payload v3 下，使用既有 selector 预绑定的真实 `E_final` 完成一次合规结构化审批，生成严格绑定最终
12k 服务参数的版本化资格证据，把 capability 晋级为 `gpu_model_serving_validated`，并由无资格特权的正式
launcher 与 doctor 复验生产入口。

### 完成/验收标准

- 最终冻结的服务合同能稳定启动 exact runtime/model；服务实际报告 `n_ctx=12288`、单 slot，runtime、GGUF、
  tokenizer、模板和最终服务参数与配置及资格身份完全一致。
- 既有 selector 绑定的真实 static payload v3 样本返回符合 `rondo_static_approval_v1` 的结构化判定；
  `max_output_tokens` 仍为 512，不以 synthetic、换样本、裁剪或降低输出预算替代真实成功。
- CUDA/offload 为有效正值；取得完整的设备级显存 baseline/peak/delta、TTFT 与总耗时，且采样窗口保持 GPU 独占。
- 服务错误、输出/schema 错误、身份或配置漂移、指标缺失、watchdog/资源计数失败和清理不完整均 fail-closed，
  不生成可用成功证据、不晋级或不冒充任务完成。
- 新的版本化资格证据严格绑定 12k、static payload v3、最终 serve/request contract 与 exact 资产；缺失、旧 4k、
  malformed 或身份不匹配 evidence 均不能投影成功 capability。
- 真实 qualification 成功后，live loader 投影 `gpu_model_serving_validated`；正式 launcher 使用同一最终配置独立启动，
  doctor 在服务存活时报告 ready、匹配 capability/identity，并通过其正式结构化 probe。
- focused tests 与必要的 eval dependency lock 通过；不以 skip 或未运行项表示通过。
- 本任务启动的服务、端口、GPU 计算进程、launcher receipt、私有日志/临时对象全部清理；来源不明对象不被终止或删除。
- 成功后的 `rondo.local.example.toml`、主仓 ignored `rondo.local.toml` 与当前环境说明都表达同一组最终 12k 参数；
  历史 4k/8k 事实只保留在历史文档和冻结结果中，不继续冒充前向正式合同。
- 成功事实同步到两份 WBS、`doc/WBS-COMPLETED.md`、本计划当前状态和一份精炼 `agent_log/`；失败则按 §3 的失败语义
  记录，不写成功完成项。
- 所有 tracked 改动在专用工作树自审并提交；不合并、不推送、不删除 worktree、不重命名分支。

## 2. 范围

### 允许修改

- `eval/rondo_eval/local_approval/` 内直接负责 qualification、evidence/capability、launcher/doctor/client 身份与服务参数的实现，
  以及直接相关 focused tests；执行者可按现有架构做必要的局部重构，不预设固定文件、类或函数。
- 当前非密钥配置合同（包括确有需要的 `rondo.local.example.toml`）和新的版本化 12k model-backed evidence；旧 runtime/model/
  template lock 继续作为只读身份来源。
- 本计划的“当前状态”和“关键决策记录”；按真实最终结果精炼更新 `doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md`、`doc/development-environment.md` 当前机器事实与一份
  `agent_log/`。
- **唯一必须在主工作区原位完成的修改**：git-ignored `/home/sjc/desktop/RONDO/rondo.local.toml` 的
  `[local_model]`、`[local_model.server]`、`[local_model.request]` 中直接相关字段。linked worktree 通过 Git common root
  共用该文件，不得在 worktree 复制一份假配置；不得把它加入 Git。
- 从专用 worktree 只读复用主仓 ignored 的 exact runtime、GGUF、真实归档、eval venv/cache；在既有 ignored 目录创建并清理
  本任务私有的 0700/0600 运行对象。
- 在 12,288 固定不变的前提下，探索并冻结 8GB 机器上真正可重复的服务参数；允许按诊断调整 GPU offload、fit、batch、
  ubatch、flash attention、KV cache 等 runtime 支持的直接参数，只要最终值被配置、启动指纹和资格 evidence 严格绑定。

### 不允许修改

- 12,288 上下文档位、512 输出预算、模型/GGUF/runtime/tokenizer/冻结模板身份、static payload v3 核心语义或
  `rondo_static_approval_v1` 输出语义。
- 既有 qualification selector 所绑定的真实样本、path/digest/meta/Guardian 身份；不得换成 synthetic、其他归档或事后挑选的
  更简单输入。既有 exact-token census baseline 与 run ledger 也不得改写。
- 通过裁剪、摘要、压缩真实证据，跳过检查/样本，降低结构化校验，手工伪造证据或放宽 identity/fail-closed 来凑绿。
- L7、Guardian 产品代码、Local M3 配置切换、16k/其余 5 条超窗证据、47 条批量 generation、L5/L6、训练、云 API、
  Docker、Cargo、依赖升级、上游基线或无关测试/测评设施。
- Plan 023—029、历史日志、冻结审计快照和旧 lock 的形成时点事实；不新增通用审计、签名、attestation、provenance 或可信发布体系。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash 或 source；只可静默检查它是普通非 symlink、mode `0600`，以及本任务
  所需变量存在且非空，并由现有严格 loader 只注入目标子进程。
- 除 selector 已绑定样本外的私有 `E_final` 正文；所选样本只由现有安全 reader 在内存中读取，不得把正文、完整请求、token
  ids/pieces、模型 rationale/risk tags 或 server 自由文本写入控制台、普通日志或 Git。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **执行授权与生命周期上限。** 本规划回合没有授权真实模型加载。执行者进入实现阶段前须一次说明 tracked/ignored 修改、
   独占 GPU、本地模型加载/推理和宿主资源影响，并取得最多 **6 个受监管模型生命周期**的明确授权。每次真正启动一个会加载
   模型的服务进程即计 1 次，无论随后成功、失败或用于诊断；正式 launcher/doctor 复验同样计 1 次。达到上限仍未完成时，
   保持现场清理并申请追加授权，不得把次数用完解释为 12k 技术不可行。
2. **exact 12k 身份不漂移。** 上下文始终为 12,288；runtime/GGUF/model id/quantization/tokenizer/template、static payload v3、
   静态请求采样合同与 512 输出预算保持冻结。最终资格身份必须覆盖 exact runtime/model/template、12k、static payload v3、
   最终 serve config 与 request contract；服务 `/props`、launcher receipt、evidence 和本机配置必须相互一致。以后 payload
   合同版本或请求语义变化时，旧资格必须自动失配，不能继续沿用本次 capability。
3. **服务参数可探索但最终必须冻结。** 不预先指定 gpu-layers、fit、batch、ubatch、flash attention 或 KV 参数的最终值；
   每次真实启动前先在本计划当前状态记下生命周期编号和候选参数，结束后只记安全的结果/阻断 facts。参数调整必须由上一轮诊断
   支持，最终组合需由 qualification 与正式 launcher 两条路径实际复现，不能依赖未记录的手工参数或偶然成功。
4. **先过无模型门禁。** 首次模型加载前完成 live diff/配置审查、4k→12k 合同迁移实现、直接回归、eval lock 与无模型
   fail-closed 检查。代码或配置缺陷先用 focused test 固化；普通实现/测试不消耗模型生命周期。
5. **真实样本和 static payload 固定。** qualification 必须复用现有 selector 与生产 safe-reader/meta 校验，发送 selector digest
   对应的 5,311-token static payload v3；按 `input+512` 它已由正式 census 确认适配 12k。不得改 selector、另造请求、二次转写
   payload 或以 doctor 的 synthetic probe 代替这条真实结构化判定。
6. **失败后允许有依据地继续。** 每次失败先清理现场，再用稳定错误码、allow-listed 数值、私有日志的有界基础设施摘要、源码与
   focused reproduction 定位。属于 12k 资格范围且存在新的合理方向时，允许反复调整参数或做局部修复并补回归，然后从新的有效
   起点重跑；不得盲目重试掩盖同一失败。只有出现下列情况才停止并回到路线规划：需要改用 8k/16k/其他档位；需要更换
   model/GGUF/runtime/tokenizer/template；需要改变 static payload v3 核心语义、裁剪/摘要/压缩/替换真实证据、跳样本或弱化
   fail-closed；需要进入 L7、Guardian 产品代码或其他独立工作包；8GB 现场已证明 12k 基本不可承载且无合理新方向；或 watchdog、
   资源计数器和生命周期授权阻止继续。
7. **证据和晋级只能来自完整成功。** 只有 exact identity、`n_ctx=12288`、static payload v3、正数 CUDA offload、
   真实 schema-compliant response、完整 VRAM/TTFT/总耗时以及 qualification 自身清理全部成功后，才可由正式代码原子生成
   版本化 12k evidence。不得手工编辑成功字段或 capability；旧 4k/中间/失败 evidence 不得被 loader 接受。若后续参数变化使
   evidence 过时，必须由严格身份降级并按新合同重新资格化。
8. **正式入口必须独立复验。** 晋级后另起一个无 qualification 特权的正式 launcher 生命周期；服务存活期间用正式 doctor
   验证 ready、12k、exact runtime/model/service identity、`gpu_model_serving_validated` 与结构化 probe。随后只关停本任务已验证的
   exact 进程并让 launcher 正常清理 receipt；该复验失败时不得宣称 launcher/doctor 验收完成。
9. **watchdog、互斥、指标与清理。** 所有真实生命周期必须从任务 worktree 经仓库根的**绝对路径**
   `scripts/with-build-lock.sh` 运行，持有同 checkout 的 fail-closed lease，并与重型 Cargo、Docker 和其他真实本地模型任务互斥。
   运行前确认端口/GPU 无来源不明占用；显存采样覆盖加载到请求结束的完整独占窗口。每次尝试都验证服务停止、端口释放、无本任务
   GPU 进程、receipt/私有对象清除；无法取得锁、watchdog 或资源计数器时停止，不绕过门禁。
10. **主仓 ignored 配置只做字段级迁移。** 修改前确认 `rondo.local.toml` 为普通非 symlink、mode `0600`，并记录
    `providers`/`paid_eval` 的规范化 digest；只改 local-model 直接字段，修改后严格重载并确认无关 digest 与权限不变。成功交付时
    ignored 配置、受跟踪的当前配置合同、资格 identity 与实际最终参数必须一致；失败交付时明确报告该 ignored 文件的最终状态，
    不把中间配置描述为正式资格。
11. **只跑必要门禁并按结果写文档。** 至少运行 local-approval 与配置加载/安全直接相关 focused tests，以及 `just eval-lock`
    或仓库现行等价的依赖锁检查；不扩大为 Rust、Docker、全 workspace 或全量 eval。成功后把当前路线推进到 WBS 指向的 L7/
    Local M3 交接，并向 WBS-COMPLETED 追加一次完成记录；若最终未成功，只记录明确工程结论和停止原因，不写完成项或成功 capability。
12. **worktree 交付。** tracked 实现、证据、文档、日志和提交只留在分支/worktree
    `030-local-12k-model-backed-qualification`；完成后检查 diff、tracked 大文件、ignored/私有对象及主工作区和全部 worktree 状态，
    然后提交并停止。未经用户批准不得合并、推送、删除 worktree 或重命名分支。

## 4. 软性建议

以下内容依据当前代码给出，但不是固定实现路线。执行者可以根据真实测试和 8GB 现场采用更窄、更清楚的等强方案。

- 当前 4k 单一漂移源集中在 `model_backed.py`，qualification 生命周期在 `qualification.py`，launcher/doctor 通过 strict loader
  投影 capability；优先复用这条现有链路，但可在能减少重复身份常量时做局部重构。
- 12k evidence 建议使用能从文件名和严格 schema 明确区分 4k 的新版本路径；是否递增内部 schema 版本由实际字段变化决定，
  不为了“看起来新”增加 registry 或迁移框架。
- 当前 `request_contract_sha256` 尚未显式纳入 input payload 版本。迁移时应以最小方式让 evidence identity 绑定 v3（例如纳入现有
  payload schema version 和/或 canonical request digest）；具体字段由执行者决定，不把完整请求或正文写入证据。
- 既有 selector 的 `E_final` SHA 与 census anchor SHA 相同，v3 实测 5,311 tokens；selector 本身无需迁移。运行前只需把这项
  tracked 事实与正式 census baseline 交叉检查，不重跑 47 条 census。
- 参数探索宜从已能加载 exact 模型的现有配置附近开始，每次只扩大到有诊断价值的组合；GPU layers 不要求预先等于总层数，
  但必须为正、真实记录并足以支持最终 12k 资格合同。不要为了追求“全层”牺牲 12,288、输出预算或稳定性。
- focused 门禁优先复用 `eval/tests/test_local_approval.py`、`test_config_hardening.py` 与
  `test_config_and_artifacts.py`；若实际改动更窄可说明并采用等价子集，若改变 evidence/lock schema 则必须覆盖 strict parse、
  missing/extra/identity mismatch 与旧 4k 不能晋级。
- `token_census.py` 会复用 live qualification contract，因此共享的当前合同 fixture 可能需要随 12k 迁移；不要机械替换历史
  4k/8k fit 边界、已发布 census baseline 或形成时点说明，也不为本任务重跑 47 条普查。
- 真实运行继续复用 common root 的 `eval/.venv`、`eval-data/uv-cache`、runtime、model 与归档；私有 server log 只用于本轮定位，
  普通输出只保留稳定错误码、allow-listed identity、计数和耗时。
- 正式 launcher 复验可复用现有 receipt + exact PID/start ticks/cmdline/listener 身份完成定点关停；若现有编排不适合，可采用经过
  focused test 的等强生命周期方案，不建立通用进程管理或审计设施。
- 文档只写最终参数、有效指标、模型生命周期用量、关键失败/修复结论、测试与清理；不堆工具流水，也不重复 WBS 的下游路线。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-15：主工作区 `main@ffd3cc6` 干净并与 `origin/main` 一致；从该提交创建分支/worktree
  `030-local-12k-model-backed-qualification`。
- 已阅读根/`mydev` 规则、README、两份 WBS、Plan 模板、Plan 023/029、相关日志和 live local-approval 实现/测试。
  当前 WBS 已把 12,288 冻结为首个 model-backed 资格目标，尚未声明真实可用。
- live code 的 4k 残留主要集中在 qualification identity/evidence path/schema 校验、launcher/doctor 文案和 focused fixtures；
  当前成功 evidence 文件不存在，capability 仍应为 `linux_cuda_built_model_unvalidated`。
- 既有 selector 绑定的真实样本 SHA 为 `eaa2dfb…9ebaca`，与正式 v3 census 的 5,311-token anchor 相同，
  `5,311 + 512 <= 12,288`；无需换样本或修改 selector。
- 主仓 ignored `rondo.local.toml` 是 mode 0600 普通文件，当前 local-model 为 4096 / `gpu_layers=auto` / `fit=on`；
  exact GGUF 与 CUDA server 文件存在。规划阶段未修改该文件。
- 规划阶段未读取 `.env.local` 或真实证据正文，未启动模型/GPU 服务，未运行测试；模型生命周期用量 **0/6**。

### 当前工作

- execplan 已形成，等待执行者在取得一次执行授权后实施。

### 本任务剩余步骤

1. 取得一次执行授权并完成现场、ignored 配置和旧 4k 漂移基线核对。
2. 迁移 12k 合同/evidence/capability 路径与直接测试，冻结首组候选配置并通过无模型门禁。
3. 在最多 6 个受监管生命周期内完成有依据的资格运行、诊断/局部修复和最终真实 qualification。
4. 晋级后用正式 launcher + doctor 独立复验并完成最终清理。
5. 按真实结果同步文档/日志，检查 diff 与所有现场，提交工作树后等待 Codex 独立验收。

### 阻塞项

- 实现本身无已知代码阻塞；首次真实模型加载前仍需用户明确授予本任务最多 6 个模型生命周期。

### 当前验收状态

- 仅完成规划。12k 尚未真实加载或推理，无有效 model-backed evidence，capability 未晋级。

### 交接边界

- 本任务成功后冻结本计划；L7/Local M3 及后续路线只交回两份 WBS，不在本计划继续安排。
- 若触发用户列明的宏观停止条件或耗尽授权，执行者应提交已定位事实与安全现场，等待重新规划或追加授权。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 首个 model-backed 资格档位固定为 12,288 | WBS 已按全集覆盖与 8GB 压力取舍定案；本任务不重新选择 8k/16k | 配置、资格身份、验收 | 已采纳 |
| 002 | 继续使用既有 selector 的 5,311-token 真实样本 | 它已被事前绑定且由 v3 census 精确确认适配 12k，避免事后换简单样本 | qualification 输入 | 已采纳 |
| 003 | 最终服务参数由 8GB 现场探索冻结，不在计划预设 | 用户要求给执行者合理调参空间；真正不可妥协的是 12k、资产/语义身份和 fail-closed | launcher、identity、evidence | 已采纳 |
| 004 | evidence 必须显式区分并严格绑定 12k，内部 schema 版本不预设 | 防止旧 4k/漂移证据晋级，同时避免无实际字段变化的版本体系膨胀 | model-backed evidence | 已采纳 |
| 005 | 上限按每个真实模型服务进程启动计 6 个生命周期 | 让诊断、最终资格和正式复验共享清楚的资源预算；次数不是技术失败阈值 | 真实执行 | 提议，待执行授权 |
| 006 | ignored `rondo.local.toml` 只在主仓原位字段级修改 | loader 通过 Git common root 让全部 worktree 共用该文件；复制到 worktree 不生效 | 本机配置、交接 | 已采纳 |
| 007 | 成功后的正式 launcher + doctor 复验属于本任务，L7 不属于 | 本任务要证明生产入口能消费资格；cloud/local Guardian 配置切换仍是独立工作包 | 验收、非目标 | 已采纳 |
