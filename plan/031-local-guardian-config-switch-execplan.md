# Plan 031：RONDO Local Guardian 正式路由、L7 配置切换与 Local M3 收口

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理正式本地 Guardian 路由、L7 与 Local M3 收口；跨任务路线、优先级、顺序和依赖以
> `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

补齐正式 Guardian 接入冻结 llama.cpp b10333 所需的最小本地身份/wire bridge，并生成包含 L2a 的当前
RONDO Local 可执行文件。在此基础上，实际切换阶段只使用 S1 的 `[auto_review].model` /
`reasoning_effort` 与 L2a 的 `[auto_review].model_provider`，把 Guardian 从原云端配置切到已取得
`gpu_model_serving_validated` 资格的本地 12k 服务，通过正式 `--approve-for-me` 完成一次受控真实审批，
最后退出本地配置并清理现场，关闭 L7 和 Local M3。

本任务只为解除已确认的正式链缺口而增加小范围 eval-side 支持；不修改 `mydev/` 产品源码，不把 bridge
扩成通用代理、第二套审批系统或复杂可信设施，也不做模型质量/性能横评。

### 完成/验收标准

- 存在一个短生命周期、仅 loopback 的 Responses bridge。它复用既有 launcher/service identity 校验，
  在转发前和完整接收上游响应后验证同一 launcher 实例；receipt 缺失、替换或服务漂移均 fail-closed，
  后验通过前不向 RONDO 返回响应 bytes。
- bridge 只做正式链所需的兼容变换：把 Codex 原生
  `text.format={type,name,strict,schema}` 精确映射为冻结 b10333 使用的顶层
  `response_format={type:"json_schema",json_schema:{name,strict,schema}}`，并移除已消费的 `text.format`；
  `text` 中其他已支持成员与其余 Guardian 请求字段保持不变，未知成员/歧义形状拒绝，空 `text` 容器删除。
  focused test 比较完整 JSON，预期差异只能是该映射。bridge 不解析审批语义、不决定 allow/deny、不保存 `E_final`。
- focused pure/fake/loopback tests 覆盖 wire 保真、receipt 缺失/替换/响应期间漂移、服务身份不符、
  凭据不泄漏和清理，0 skip；`just eval-lock` 通过。
- 经仓库根受锁正式配方生成一个包含 L2a、与本任务配置 schema 相容的当前 RONDO Local `codex`；记录源码身份、
  binary SHA-256 与 watchdog 成功摘要，不运行 Rust 全量测试。
- current binary 通过一次无真实模型、无外网的最小 `--approve-for-me` loopback route smoke，证明实际
  `stream=true` Guardian transport 能经过 bridge 与 b10333-shaped fixture 往返。该 smoke 不冒充真实模型、
  真实审批证据或 Local M3。
- 本地切换时同时显式配置 Guardian model、reasoning effort、provider 三个轴，provider 指向 bridge，
  主 Agent provider 保持独立；正式入口使用 `--approve-for-me` 展开的
  `approvals_reviewer="auto_review"`、`approval_policy="on-request"`、`sandbox_mode="workspace-write"`。
- 正式 launcher 使用既有 12k qualification evidence 启动 exact runtime/model；存活期 doctor 为 `ready`，
  capability 为 `gpu_model_serving_validated`，model-backed validation 为 `model_schema_probe_passed`。
- 一个受控主 Agent turn 通过正式链产生真实 `E_final`，本地 Guardian 返回可被生产 parser 接受的结构化
  allow/deny 判定，审批流程达到与判定一致的终态；动作只在 allow 时执行。不得为凑指定 outcome 改 prompt、
  重试或放宽 schema。
- 正式链分别验证服务不可用、launcher/service 身份漂移、结构化输出不合规三类关键失败；“服务不可用”固定为
  bridge 可达但 exact upstream/llama 不可用或无法形成合法 service identity，不只测试 bridge 端口无人监听。
  三类均不执行待审批动作、不回退主/云 provider、不产生成功表述。
- 原云端配置全程不被修改。结束后无本地 provider override、bridge/model/fixture 进程、任务端口、launcher receipt、
  临时 Codex home、私有 evidence 或其他任务运行对象残留；不通过真实云端请求证明恢复。
- tracked diff 无 `mydev/` / `multidev/` 产品代码改动，只包含本任务允许的 eval 支持、focused tests、配置示例、
  本计划可变章节、两份 WBS、`doc/WBS-COMPLETED.md` 与一份精炼 `agent_log/`。
- 只有上述标准全部满足时，才把 L7 与 Local M3 标记完成；否则按真实 blocker/失败收口。
- 所有 tracked 改动在现有 `031-local-guardian-config-switch` worktree/分支自审并提交；不合并、不推送、
  不删除 worktree、不重命名分支。

## 2. 范围

### 允许修改

- `eval/rondo_eval/local_approval/`：增加最小 bridge 入口，并为复用既有 launcher receipt/service identity 做必要的
  小范围提取；不预设具体文件拆分。
- `eval/rondo_eval/config.py`、`rondo.local.example.toml`：仅增加 bridge loopback host/port 的严格配置合同。
- `eval/tests/` 中直接相关的 focused tests；优先复用现有 fake server、receipt、配置和 CLI 夹具。
- 本计划的“当前状态”和“关键决策记录”；成功后精炼更新 `doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md`，并新增一份 `agent_log/`。
- 专用 worktree 内、受仓库 watchdog 监控的 Cargo target/metrics，用于一次 current RONDO Local build；
  只处理本任务明确创建的产物，不清理来源不明对象。
- **因 Git common root / gitignore 只能在主工作区原位处理的 private 对象**：
  - `/home/sjc/desktop/RONDO/rondo.local.toml`：只补 bridge host/port，保持普通非 symlink、mode 0600 与其余配置不变；
  - `/home/sjc/desktop/RONDO/.env.local`：只由既有严格 loader 静默使用，不直接编辑或读取；
  - `/home/sjc/desktop/RONDO/eval-data/local-approval/`：receipt、临时 `CODEX_HOME`、私有 evidence 与运行对象；
  - `/home/sjc/desktop/RONDO/eval-data/tools/`、模型路径与合格 runtime：只按既有锁和身份只读使用。

### 不允许修改

- `mydev/` 或 `multidev/` 产品源码、测试、schema、Cargo/Bazel 文件、配置优先级或产品行为。若 eval-side bridge
  不能通过既有 L2a provider 完成正式路由，应暂停并报告新的最小产品缺口，不得偷偷改产品。
- Plan 030 qualification evidence、runtime/model/template lock、static payload v3、LocalApprovalClient 的审批语义、
  census baseline、run ledger、正式历史结果或旧日志。
- 通用反向代理、证书/签名/attestation、长期 daemon/service、审计账本、日志平台、多租户鉴权或第二套审批逻辑。
- 16k、剩余 5 条超窗证据、其余 41 条 12k 适配证据、47 条批量 generation、教师标签、指标横评、
  L3—L6、训练、模型优化、Docker、云 API、数据外发、全量测试或全量 eval。
- 项目外真实 Codex 配置、宿主机/全局工具链/系统服务或其他仓库。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash 或 shell source；只可静默检查它是普通非 symlink、
  mode 0600，以及任务所需变量存在且非空。测试只使用 synthetic secrets。
- 真实 `E_final.json` 正文、完整 Guardian 请求、rationale/risk tags、server 自由文本和任何真实凭据；
  只使用生产 parser 的成功/失败、evidence `meta.json` 必要 allow-list 字段及文件 stat/hash 证明结果。
- 项目外个人文件、真实 Codex home、认证文件、其他仓库或来源不明运行对象。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过验收或宣称里程碑完成而违反。

1. **授权与范围。** 执行提示词中的一次性授权只覆盖本计划列出的项目内代码/文档、主仓 ignored 字段级配置、
   loopback 进程、focused tests、一次受锁重型 build 和受控本地模型生命周期。任何 Docker、云端、项目外或
   产品源码扩张仍须停止并请求新授权。
2. **保持产品边界。** RONDO 只使用既有普通 OpenAI-compatible provider；receipt 校验与 b10333 适配放在
   local-approval bridge。bridge 不解析 prompt、不决定 allow/deny、不调用工具、不改证据内容。
3. **请求窗口内 fail-closed。** bridge 转发前与完整响应后复用生产 identity 校验并确认同一 launcher 实例；
   外部 doctor 或仅启动时检查不能替代。为完成后验校验可以有界缓冲单个 Guardian 响应。
4. **wire 变换窄且保真。** 只接受本任务冻结的 `text.format` JSON-schema 形状，映射后删除已消费字段，
   保留 `strict` 原值、其他已支持 `text` 成员和其余请求字段，删除空 `text`；未知控制、丢字段或歧义均拒绝。
   上游结构化内容仍由产品 Guardian parser 最终判定。
5. **配置切换仍是配置-only。** bridge 落地后，local/cloud 切换本身只能改变运行配置，不再改代码。Guardian 的
   provider/model/effort 必须显式且独立，主 Agent provider 不随之重定向；本地 provider 不回退到云端。
6. **密钥方向固定。** 禁止 source/打印秘密或写入 TOML、argv、日志/evidence。local key 只由严格 loader 提供给
   launcher/bridge 目标子进程，供 bridge→llama 使用；RONDO→bridge 设置为无鉴权，不配置 `env_key`，
   RONDO 与主 Agent fixture 不接收该 key。云端 key 本轮不加载、不注入。
7. **失败矩阵保持最小。** 服务不可用、身份漂移、输出不合规各用一个受控审批请求验证；服务不可用负例保持
   bridge 可达而 upstream/identity 不成立。异常必须与业务 deny 区分，不执行动作、不重试到云端。
   除这三项外不扩展排列组合或新审计体系。
8. **正式成功只认真本地模型。** current-binary loopback smoke 只验证 transport；qualification/doctor/fake/旧结果
   都不能替代本轮真实 `--approve-for-me`。真实 allow 或 deny 均可，只要结构化合同和终态成立。
9. **重型资源门。** build 只能经根 `scripts/with-build-lock.sh` 接入的现行 `just product-build rondo-local ...`
   配方运行；先确认 build lock/cgroup/Windows C: 实际余量/项目存储/单热 target，且无 Docker、其他 Cargo 或
   真实模型。真实 launcher 也必须经同一根锁持有效 lease，缺少任一资源事实即 fail-closed。
10. **验证分层诚实。** 只运行直接相关 unittest、`just eval-lock`、一个 current-binary formal loopback smoke、
    三个负例与一个真实 12k 正例；不跑 Rust 全量测试/全量 eval。fake、无模型、真实模型证据必须明确区分。
11. **私有证据与清理。** 不把 `E_final` 正文、模型输出或 secret 带入终端/Git。只停止本任务经身份确认的进程，
    来源不明端口/进程只报告。最终恢复/退出本地配置作用域，并清理 receipt、临时 home/evidence 与本任务对象。
12. **文档与交付。** 全部通过后才更新 WBS/WBS-COMPLETED 为 L7/Local M3 完成；失败只记 blocker。
    提交前检查 diff、敏感/大文件、ignored 残留及全部 worktree 状态，只提交本 worktree，未经用户批准不得合并或推送。

## 4. 软性建议

以下内容依据当前代码给出，不固定函数名或具体编排；执行者可采用更窄、同等可验证的实现。

- bridge 可用 Python 标准库实现短生命周期 HTTP 服务，复用 `identity.py`、`launcher.py`、
  `LocalApprovalSettings` 和现有 fake server 支持；不需要新 Web 框架或常驻服务。
- 建议使用 `[local_model.bridge] host/port`。Plan 031 的 `[model_providers.<local>]` 指向 bridge，
  bridge upstream 只从既有 local-model config/receipt 导出，不接受任意 URL。
- current-binary smoke 应让真实 RONDO 产生 Guardian `stream=true` 请求；fixture 只模拟 main Agent 与 b10333 upstream，
  不重新实现 Guardian payload builder。
- 先完成 pure/fake tests、eval lock、current build 与 formal loopback smoke，再做三个无模型负例，最后只加载一次
  12k 服务完成 doctor 和真实正例，减少 GPU 生命周期。
- local provider 优先放在项目内 ignored 临时 `CODEX_HOME/config.toml` 或等价 invocation-scoped 配置；
  `wire_api="responses"`、`supports_websockets=false`、`requires_openai_auth=false`，不设置 `env_key`。
- 云端恢复以“原配置未改 + 本地 override 作用域退出 + 无本地进程/端口/receipt”为证，不发云请求，
  也不另造配置审计器。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-15：核对主工作区 `main@26b4770` clean，较 `origin/main` ahead 8；Plan 030 已合入，
  12k capability 为 `gpu_model_serving_validated`，Local M3 尚未完成。
- 已阅读根/`mydev` AGENTS、README、两份 WBS、Plan 模板、Plan 019/030、相关日志和 live
  S1/L2a/launcher/doctor/evidence 代码；创建现有 `.claude/worktrees/031-local-guardian-config-switch` 与同名分支。
- 规划阶段仅 stat ignored 配置/目录：`rondo.local.toml` 与 `.env.local` 均为普通 mode 0600 文件，
  `eval-data/local-approval/` 为 mode 0700 目录；未读取两份 ignored 文件内容。
- live code 与独立审查确认：`require_launcher_identity()` / `revalidate_launcher_identity()` 目前只由 Python
  local-approval client 调用；正式 Guardian provider 直走通用 Responses transport，不读取 launcher receipt。
  外部 doctor 前后检查不能满足请求窗口内身份漂移 fail-closed。
- 冻结 b10333 不映射 Codex 原生 `text.format`；Plan 030 qualification client 使用顶层 `response_format`，
  因此既有资格证据没有证明正式 Guardian wire 可用。
- 当前无 `mydev/codex-rs/target/{debug,release}/codex`；ignored `eval-data/bin/rondo/` 唯一 `cb652e1…` bundle
  早于 L2a merge `6ffcfeb…`，不能用于本任务。
- 用户已明确允许 Plan 031 适当扩展，故把最小 eval-side bridge、focused tests 和一次受锁 current build 纳入
  同一任务；仍不允许修改产品源码或扩成通用基础设施。
- 两轮独立只读计划审查已完成：修正 RONDO→bridge 密钥方向，加入 current-binary formal loopback smoke，
  并冻结 wire 消费/删除语义和 bridge 可达时的 upstream 不可用负例；未发现剩余架构级 blocker。
- 规划阶段未启动模型/GPU、loopback server、网络、API、Cargo、Docker 或测试，未修改 ignored 配置。

### 当前工作

- ExecPlan 与 WBS 已完成独立复审，待提交规划 worktree 后交给执行者实施。

### 本任务剩余步骤

1. 实现最小 bridge、严格配置和 focused pure/fake/loopback tests，字段级同步主仓 ignored bridge 配置。
2. 完成 focused unittest 与 eval lock；在资源门下生成一次 current RONDO Local binary。
3. 用 current binary 完成无模型、无外网的 formal loopback route smoke。
4. 以正式链完成服务不可用、身份漂移、输出不合规三个无模型负例。
5. 在一个 formal launcher 生命周期内完成 doctor 与真实 `--approve-for-me` 本地 Guardian 审批。
6. 退出本地配置、清理本任务对象，按真实结果更新文档/日志，自审并提交工作树。

### 阻塞项

- 无已知外部阻塞；执行中若 bridge 无法在不修改 `mydev/` 的前提下满足正式链，则停止并报告最小产品缺口。

### 当前验收状态

- 仅完成规划；bridge、tests、current binary、正式负例/正例均未落地，L7 与 Local M3 未完成。

### 交接边界

- 执行者只完成本计划，不进入 16k、批量 generation、教师标签、横评、训练或模型优化。
- 本任务完成后冻结计划；后续路线只交回两份 WBS，不在本计划安排 L5a/L3/L4/L5b/L6。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响范围、执行方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 031 纳入最小 eval-side bridge 与一次 current build，但不修改产品源码 | 用户已明确允许适当扩展；现有正式链与 binary 无法在纯配置边界内完成 L7 | 范围 | 已采纳 |
| 002 | bridge 在完整响应后重验 launcher 身份，再向 RONDO 返回 bytes | 消除 doctor 前后检查和流式部分响应的请求窗口竞态 | fail-closed | 已采纳 |
| 003 | 只变换 `text.format`→`response_format`，保留 `strict` 和其他字段 | 修复冻结 b10333 的已知映射缺口，不暗改 Guardian 语义 | wire | 已采纳 |
| 004 | RONDO→bridge 无鉴权，bridge→llama 才使用严格加载的可选 local key | 避免凭据路径自相矛盾或云端 key 泄入本地 | 凭据 | 已采纳 |
| 005 | current binary 先做 formal loopback smoke，再加载真实模型 | 用实际 transport 低成本解除 wire 风险，不拿 fixture 冒充 L7 | 验收顺序 | 已采纳 |
| 006 | 三个失败路径各做一次，真实 outcome 允许 allow 或 deny | 覆盖用户点名风险，同时避免排列组合和为凑结果重试 | 负例/结果 | 已采纳 |
| 007 | 云端恢复只做离线无残留证明 | 真实云端复跑涉及数据外发/费用，本任务未授权 | 恢复 | 已采纳 |
