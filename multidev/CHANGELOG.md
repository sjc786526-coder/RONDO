# RONDO Multi — 变更记录

本文件只记录 **RONDO Multi**（`multidev/`）相对冻结上游基线的变化。
RONDO Local（`mydev/`）是独立产品线，有独立的发布轨与独立的
[变更记录](../mydev/CHANGELOG.md)。

上游 OpenAI Codex CLI 自身的历史见[其 releases 页面](https://github.com/openai/codex/releases)。

> **版本号说明**：Release tag 形如 `multi-vX.Y.Z`，与二进制 `--version` 输出的 `0.147.0` **不是同一个东西**。
> 后者沿用上游冻结基线版本号，以支持与原始 Codex 的字节级公平对比，全程不改。产品版本以 tag 为准。

## 0.1.0 - 2026-09-01

首次公开发布。**实验性研究产物，不是生产工具，不附带任何性能或质量承诺。**

### 相对上游 `v0.147.0` 的变化

多智能体共享证据架构，核心是一套 Event 驱动的团队世界状态：

- **Team State**：Event、Version、生命周期、可见性与指派的唯一 canonical 来源。
- **Fact 引用式共享证据**：Fact 是对 Codex 已保留的历史 observation 的可解析引用，**不复制 payload**。
  同一份证据被多个智能体按权限引用，而不是被复制成 N 份。
- **权限模型**：Root 可读本团队全部证据；子 Agent 只能读自己产生的、或从其可见 Event 可达的 Fact。
- **Durable Team Session**：app-server v2 / TUI 控制面与 Writer Workspace Binding。
- **Team Lens**：本地离线 reducer / viewer，不参与 runtime 调度。
- **Publication Critic 接缝**（实验性，**默认完全关闭**）：见下。

一条明确的自我约束是复用 Codex 原生的执行与通信机制，不另建 A2A 协议、调度器、全局订阅或 workspace 协调层。

### 实验性功能：Publication Critic（默认关闭）

- 它是**有界改写机制，不是发布门、不是安全审批**。一个 publication cycle 最多三次审查，
  **第三次审查非阻断**——即使判定为 `REWRITE` 也会提交；判官服务故障时 fail-open 提交当前稿并记为"审核未完成"。
- 启用需显式满足多个前置条件（`team_state_enabled`、字面量 loopback endpoint、服务描述符严格匹配），
  任一不满足即 fail-closed，不降级运行。
- **判官后端不在 Release 产物内**，需自行从源码构建；本地后端依赖未分发的模型权重，云端后端需自备凭据。

### 研究结论

方向 3 需要分两层看，两层结论不同：

- **RONDO Multi 产品本体**：架构与工程链通过。Linux 全量 workspace 正确性基线 `14,660 / 14,660` 通过、0 failure。
  `PublicationScorer → service → typed client → 发布` 整条链在 OFF / 本地模型 / 云端模型三态下均验证通过，
  双 backend 可替换性成立。
- **Publication Critic 判官模型**：**未获质量资格**。本地判官 `NO-GO`（多轮训练均未产生达到预冻结质量门的候选）；
  云端判官 `NOT_QUALIFIED`（ROC AUC 与 Boundary strict win 过线，但 False PASS 超限，
  整条 operating curve 上不存在同时满足全部质量门的工作点）。
  五维判官接缝本身为 `ENGINEERING_SEAM_PASS`，**该结论只覆盖工程接缝，不含任何质量或资格结论**。

详见 README 的"诚实的结果"与 `doc/rondo-multi-publication-critic-product-contract.md`。

### 发布形态

- 首发目标仅 `x86_64-unknown-linux-musl`。不提供 macOS / Windows 产物——没有可验证的环境，
  发一个自己无法验证的平台产物比不发更糟。
- 归档为**完整产品包**（含 `codex-code-mode-host`、`bwrap`、`rg`、`codex-package.json`），
  不是裸二进制；入口可执行文件名为 `rondo-multi`。
- 不发布到 npm。`codex-cli/package.json` 已标记 `private`。
- 默认不再检查上游 Codex 的版本更新（fork 不应引导用户去安装上游产品）。
