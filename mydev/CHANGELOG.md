# RONDO Local — 变更记录

本文件只记录 **RONDO Local**（`mydev/`）相对冻结上游基线的变化。
RONDO Multi（`multidev/`）是独立产品线，有独立的发布轨与独立的
[变更记录](../multidev/CHANGELOG.md)。

上游 OpenAI Codex CLI 自身的历史见[其 releases 页面](https://github.com/openai/codex/releases)。

> **版本号说明**：Release tag 形如 `local-vX.Y.Z`，与二进制 `--version` 输出的 `0.147.0` **不是同一个东西**。
> 后者沿用上游冻结基线版本号，以支持与原始 Codex 的字节级公平对比，全程不改。产品版本以 tag 为准。

## 0.1.0 - 2026-09-01

首次公开发布。**实验性研究产物，不是生产工具，不附带任何性能或质量承诺。**

### 相对上游 `v0.147.0` 的变化

- **Guardian 审批模型可配置**：可选择模型、reasoning effort 与 provider，不再固定单一后端。
- **可插拔的本地推理审批模型**：通过 OpenAI-compatible 接口接入，可一键在云端与本地之间切换。
  该能力**依赖未随仓库分发的模型权重与本地推理运行时**，不是下载即用。
- **若干 harness 热路径优化与观测设施**：面向工具路由等热路径的行为保持型改动，以及用于定位瓶颈的观测出口。
- **自建量化测评设施**（`eval/`，两条产品线共用）：离线冻结回放与真实 API 两层。

### 研究结论

- 方向 1（Harness 优化）：正式收口。**本项目不对外给出任务解决率或性能提升数字。**
- 方向 2（本地审批模型）：**保留为实验，未采用**。现有证据不足以证明它能安全地放行真实审批，
  因此不改动生产默认值。详见 README 的"诚实的结果"。

### 发布形态

- 首发目标仅 `x86_64-unknown-linux-musl`。不提供 macOS / Windows 产物——没有可验证的环境，
  发一个自己无法验证的平台产物比不发更糟。
- 归档为**完整产品包**（含 `codex-code-mode-host`、`bwrap`、`rg`、`codex-package.json`），
  不是裸二进制；入口可执行文件名为 `rondo`。
- 不发布到 npm。`codex-cli/package.json` 已标记 `private`。
- 默认不再检查上游 Codex 的版本更新：启动提示与 `doctor` 受同一开关控制，关闭时不发起请求，
  也不输出上游版本（fork 不应引导用户去安装上游产品）。
