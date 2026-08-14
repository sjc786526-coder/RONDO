# 方向 3：RONDO Multi（可信证据型多智能体产品线）

最后更新：2026-08-14 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 定位与状态

只读研究已完成；产品基线（M-0）的实现与独立验收修复已落在 Plan 022 任务分支，尚待独立复审，功能开发未开始。研究证据、开源系统比较、候选对象语义和风险分析见
`doc/research/multi-agent-trusted-evidence-research.md`；本页是是否实施、阶段顺序和验收边界的唯一规划来源。

**方向 3 现在是独立产品源码，不是 RONDO Local 内的可插拔模式。** `multidev/` 与 `mydev/` 并列，
共享测评、构建锁与工具设施，但不要求共用核心代码，也不要求与 Local 长期保持提交级一致。

目标不是让更多 agent 自由讨论，而是让工具观察和子任务原件可以持久注册、按 ID 引用、独立复核并由强 root
有界合成，同时保持私有上下文、写入所有权和恢复语义。Multi 的主要目标是验证和探索新技术、保证功能正确，
并相对冻结 Codex 不出现明显退化；**不要求昂贵的大规模统计性能证明**。

## 价值命题（当前倾向，D2 未决）

调研报告的关键警告是“同预算下多轮辩论常常不如独立采样”。当前倾向如下，最终措辞与对照合同由 D2 决定：

- **待证命题**：在证据密集的多智能体工作流中，RONDO Multi 的结构化证据共享能减少 token、信息失真和
  重复工具调用，并保留可恢复原件。
- **机制归因的主对照**倾向采用同一 Multi 系统的**朴素自然语言转述模式**：同一套 agent 与任务，
  主要差别是证据靠自由文本交接还是按 ID 引用原件。若 D2 采纳，这个对照组必须是 Multi 内部的一个
  可切换模式，而不是事后再造一个系统 —— 这会直接影响首个增量的设计。
- **单智能体只作 sanity reference**：用冻结 Codex 检查是否出现稳定单向退化，不把“全面胜过单体”作为准入门。
- **质量优势暂不主张**。若将来要证明“多智能体质量更好”，需要放开预算做公平对比，明确后置，不进入当前路线。
- 其他多智能体系统只作研究背景与必要时的外部参照，不作为首个增量必须复现的主基线。

好处是上述指标（token 数、工具调用次数、证据复述失真率）可以低成本记录和归档，不依赖大规模付费测评。

## 稳定原则

- 共享已持久化的工具观察与结果定位，不广播完整 transcript 或推理过程。
- root 初期是唯一 writer；child 的只读由宿主在 runtime override 后强制收窄，不能靠提示词。
- 主候选保留原件，审查者提供可定位的增量与验证动作；不投票，不让弱 summarizer 重写完整方案。
- 共享证据最终不能只存在 RAM；发布前必须取得可恢复 locator。
- Cargo、Docker、真实模型和外部操作继续服从项目既有锁、资源与授权门，不在协作层另造一套。
- **内核形态不受 Local 约束**：Multi 可以从线性 thread/rollout 演进为任务图和证据图，并自由调整上下文拼装与
  压缩、证据身份与来源、冲突处理、持久化与恢复、root/worker/writer 权限、调度和 TUI。此处仅举例，
  不约束具体实现。

## M-0 产品基线（实现待独立复审）

`multidev/` 由本任务基线 `mydev/` 的 Git 跟踪文件精确复制而成，未回退 Local 审批代码，也未从纯净
v0.147.0 或历史 commit 起步。落地证据见 `doc/WBS-COMPLETED.md`；取舍论证见
`agent_log/2026-08-13-strategy-consensus-landing.md`。

### “干净基线”的定义（持续约束）

> `multidev/` **尚未加入任何 Multi 产品行为**；Local 审批接口存在，但**默认关闭、不依赖本地模型、
> 不计入 Multi 基线能力**。基线继承公共测试与构建设施，并持有独立产品身份。

源码纯度门（“diff 里不许出现 `guardian/`”）**不可执行** —— Guardian 审批子系统是上游自带的，任何
v0.147.0 基线都带着它。因此基线由下面三条行为门定义，它们对后续每个 Multi 阶段继续生效：

1. **默认关闭可断言**：`[auto_review]` 的 `model`、`model_provider`、`reasoning_effort`、`evidence_dir`
   在空配置下经真实配置加载后全为 `None`。
2. **基线在关闭态取得**：Multi 的基线测试与退化验收在该关闭态下运行；eval 不为 Multi 注入这四项，
   结果工件用版本化 `auto_review_config` 记录该状态。
3. **不携带本地模型依赖**：`multidev/` 的配置与测试不引用任何 GGUF 路径或本地推理 runtime。

### 产品身份（持续约束）

产品身份贯通源码/构建路径、Cargo target、binary freeze、manifest、共享 catalog、adapter/RunSpec、
campaign 与结果归档，唯一映射是 `eval/rondo_eval/contracts.py` 的 `product_layout()`；
Multi 的工件命名空间是 `eval-data/bin/rondo-multi/`。规则见 `doc/eval-data-layout.md`。

Multi 目前**没有冻结的 runtime bundle**，因此还不能跑 Docker、no-API 双侧或付费验收；
首次这类验收前必须先按上述身份冻结一套 Multi bundle。

### 继承代码的处置约定

evidence capture 与 Guardian provider 覆盖位于 Multi 内核改造可能触及的区域。**不预设删除**：它们默认关闭、
不影响 Multi 开发，本质是预留接口，并保有“将来把本地 Guardian 接成 Multi provider”的期权价值。
处置原则只有一条：**不为保住它而对 Multi 内核做设计妥协**。将来真冲突时按当时成本决定 ——
顺手能适配就适配，适配代价超过它的价值就删，现在不预先承诺哪一种。

## 首个功能增量：待定（D1）

调研报告 §7 给了四个候选工作流（并行源码/资料调查、主方案 + 独立审查、Bug 诊断、计划审查），
§3 给了推荐的内核对象边界。**选哪个、是否先做证据层地基，待细读报告后决定**，本页不预先锁定。

在 D1 定下来之前，`doc/WBS.md` 工作包 3c 只包含 M-0 之后的环境就绪工作，不启动功能开发。

## 后续能力方向（顺序待 D1 定，均不排期）

以下是研究阶段收敛出的能力方向，作为候选池保留；具体拆包、顺序与是否立项在 D1 之后另定。

- **协作接缝与最小证据层**：`CollaborationRuntime` façade，最小 `EvidenceId`、typed locator、`ResultCard`、
  checked append 与版本化协作记录；功能开关关闭时旧行为不变且无额外历史扫描。
- **任务运行时与上下文投影**：把反复出现的任务身份、阶段、取消、超时、失败和恢复从自由文本抽成窄状态机；
  scheduler 只管模型槽、重工具槽、资源类别、排队和取消；统一初答隔离、证据可见性、定向 follow-up 与上下文预算。
- **需求驱动的持久投影与复用**：扫描成为瓶颈后再加 checkpoint/tail scan；恢复 reconcile 不足以满足投递时再加
  持久 outbox；只为语义稳定的纯读工具做 exact reuse/single-flight；大输出撑不住时才引入 artifact/blob 抽象。
- **Workspace Manager 与多 writer**：每个 writer 使用项目确认拥有的独立 worktree/lease，任务绑定 base commit、
  目标模块与输出，由一个强 integrator 串行选择与合并；起始工作区脏、非 Git 或所有权不明时退化为单 writer。
- **远期扩展**：通用 DAG、嵌套团队、动态验证轮次、更丰富 UI、跨 session 复用、非 Git workspace、多进程或
  远程 worker；每项必须由真实使用证据触发，不预先设计分布式协议。

无论首个增量选哪个，首个 plan 都必须先完成：对基线 agent/session/rollout 接缝做 live 源码复核；
冻结开关关闭时的行为与性能基线；明确最小持久记录 schema、写入顺序、恢复失败语义和 root/child 写入策略；
只选一个端到端工作流作为验收样例，不同时建设 scheduler、DAG、artifact store 和新 UI。

## 退化验收口径

“相对冻结 Codex 不明显退化”的判定方式：**固定一小组 TB 2.1 任务，Multi 与冻结 Codex 跑同题，
只记录任务是否完成。**

- **不计算 `σ` / `delta`，不做统计显著性，不继承旧 M2 的机械判据** —— 那套与“不要求昂贵统计证明”的定位冲突，
  且小样本下 `σ` 极不稳定。
- 只在 Multi 出现**稳定的单向失败**（Codex 完成、Multi 不完成，且重复出现）时判定为退化并回头修；
  没有观察到这种失败时，只表述为“该小样本下未观察到稳定单向退化”，不扩大成统计意义或全面能力上的通过。
- **任务集：直接复用 P2/B7 的同一个金丝雀集**（`eval/tasksets/p2-b7-canary-catalog-v*.json`），不另选任务。
  任务筛选、Docker 镜像、oracle 与 verifier 全部已就绪，边际成本最低，且与 Local 侧结果处在同一坐标系。
- **频次：只在 Multi 首个可用版本以及后续重大改动时跑。** 平时回归完全依赖测试体系
  （单测、fake/loopback/replay），不做周期性付费跑，也不依赖已挂起的 E-A。
- 这组同题运行属真实 API 测评，按 `doc/WBS.md` §6 授权门单独申请任务数、轮数与预算。

**前置依赖（硬条件）**：这是 Multi 与冻结 Codex 的跨二进制对比，v22 暴露的那批设施缺陷会原样适用 ——
catalog 非对称、harness/deadline 混杂、非交错执行都可能把设施伪影伪装成“Multi 单向失败”。
因此该付费验收**不得早于 `doc/WBS.md` 工作包 1（公平比较设施闭合）**。在那之前 Multi 只做离线验证与
功能正确性，不跑付费对比，也不得对外表述“未见退化”。这条不阻塞 Multi 的开发，只约束付费验收时点。

## 稳定非目标

- 合规/取证平台、完整 provenance graph、PKI/签名链、区块链或平行 ACL。
- trust score、长期 agent 排名、在线学习路由器、judge 集群或一智能体一票。
- 全量 transcript/CoT 广播、自由群聊、无限反思、固定大 swarm。
- 通用副作用缓存、任意工具透明重放、多 writer 共享 cwd。
- 为证明全面优于单体而建设庞大 benchmark；只测目标工作流的正确性与轻量开销。
