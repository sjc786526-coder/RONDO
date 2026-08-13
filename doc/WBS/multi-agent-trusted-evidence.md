# 方向 3：可信证据型多智能体内核

最后更新：2026-08-13 ｜ 启动依赖：方向 1 形成稳定优化循环 ｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 定位与状态

只读研究已完成，产品实现未开始。研究证据、开源系统比较、候选对象语义和风险分析见
`doc/research/multi-agent-trusted-evidence-research.md`；本页是是否实施、阶段顺序和验收边界的唯一规划来源。

目标不是让更多 agent 自由讨论，而是让工具观察和子任务原件可以持久注册、按 ID 引用、独立复核并由强 root
有界合成，同时保持私有上下文、写入所有权和恢复语义。

## 稳定原则

- 复用冻结 Codex 的 thread、AgentGraph、spawn/wait/resume、rollout 与 TUI，不新建第二套会话系统。
- 共享已持久化的工具观察与结果定位，不广播完整 transcript 或推理过程。
- root 初期是唯一 writer；child 的只读由宿主在 runtime override 后强制收窄，不能靠提示词。
- 主候选保留原件，审查者提供可定位的增量与验证动作；不投票，不让弱 summarizer 重写完整方案。
- 共享证据最终不能只存在 RAM；发布前必须取得可恢复 locator。
- Cargo、Docker、真实模型和外部操作继续服从项目既有锁、资源与授权门，不在协作层另造一套。

## 阶段路线

### C0 接缝与首个只读切片（A+B，同一对外里程碑）

- 在 `AgentControl` 后建立 `CollaborationRuntime` façade，功能开关关闭时旧行为不变且无额外历史扫描。
- 引入最小 `EvidenceId`、typed locator、`ResultCard`、checked append 与版本化协作记录。
- 固定 root + 默认两个只读 worker，打通并行调查、主方案 + 独立审查、bug diagnosis 三类工作流。
- 结果和发布边界可在重启后重建；canonical 写入成功而 metadata 失败时不得盲目重放或丢失原件。
- characterisation tests 固定旧 spawn/send/wait/resume 与 TUI 行为。

验收：私有历史不泄漏；同一持久证据可由其他 agent 按引用消费；悬空 ID 不发布；重启后 evidence、result、
原件和成员关系可恢复；root 能保留冲突与主候选。

### C1 Task Runtime 与 Context Projection

- 把反复出现的任务身份、阶段、取消、超时、失败和恢复从自由文本抽成窄状态机，不做通用 DAG。
- Scheduler 只管理模型槽、重工具槽、资源类别、排队和取消；语义拆解与裁决仍由 root 完成。
- Context Projection 统一初答隔离、证据可见性、定向 follow-up 与上下文预算。
- 按真实需求补 Code Mode、CustomTool、ToolSearch、Web/MCP 等 observation adapter。

### C2 需求驱动的持久投影与复用

以下能力分别立项，不打包建设：

- 扫描或查询成为瓶颈后，再加入 checkpoint/tail scan 或可从 rollout 重建的轻量 store。
- 恢复 reconcile 不足以满足投递时，再加入持久 outbox/delivery ID。
- 先为语义稳定的纯读工具加入 exact reuse/single-flight；只有
  `tool + canonical args + workspace snapshot` 完全匹配才可透明命中，并保留 `fresh=true`。
- rollout/项目文件无法承载大输出时才增加 artifact/blob abstraction；不预建全局 CAS。

### C3 Workspace Manager 与多 writer

开放第二个 writer 前必须：

- 每个 writer 使用项目确认拥有的独立 worktree/lease，evidence 携带 opaque `WorkspaceRef`。
- 任务绑定 base commit、目标模块和输出 commit/文件；一个强 integrator 串行选择与合并。
- 组合后的 tree 重新运行必要检查；起始工作区脏、非 Git 或所有权不明时退化为单 writer。
- UI 只清理 RONDO 确认拥有且无未保存工作的 worktree。

### C4 远期扩展

只有真实使用表明需要时，再评估通用 DAG、嵌套团队、动态验证轮次、更丰富 UI、跨 session 复用、非 Git workspace、
多进程或远程 worker。每项必须由使用证据触发，不预先设计分布式协议。

## 首个实施任务的前置

方向 1 形成稳定优化循环后，C0 才可立项。首个 plan 必须先完成：

- 对冻结 Codex 现有 agent/session/rollout 接缝做 live 源码复核。
- 冻结开关关闭时的行为与性能基线。
- 明确最小持久记录 schema、写入顺序、恢复失败语义和 root/child 写入策略。
- 只选一个端到端工作流作为验收样例，不同时建设 scheduler、DAG、artifact store 和新 UI。

## 稳定非目标

- 合规/取证平台、完整 provenance graph、PKI/签名链、区块链或平行 ACL。
- trust score、长期 agent 排名、在线学习路由器、judge 集群或一智能体一票。
- 全量 transcript/CoT 广播、自由群聊、无限反思、固定大 swarm。
- 通用副作用缓存、任意工具透明重放、多 writer 共享 cwd。
- 为证明全面优于单体而建设庞大 benchmark；只测目标工作流的正确性与轻量开销。
