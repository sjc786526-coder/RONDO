# RONDO Local — 变更记录

本文件只记录 **RONDO Local**（`mydev/`）相对冻结上游基线的变化。
RONDO Multi（`multidev/`）是独立产品线，有独立的发布轨与独立的
[变更记录](../multidev/CHANGELOG.md)。

上游 OpenAI Codex CLI 自身的历史见[其 releases 页面](https://github.com/openai/codex/releases)。

> **版本号说明**：Release tag 形如 `local-vX.Y.Z`，与二进制 `--version` 输出的 `0.147.0` **不是同一个东西**。
> 后者沿用上游冻结基线版本号，以支持与原始 Codex 的字节级公平对比，全程不改。产品版本以 tag 为准。

## 0.1.1 - 2026-09-03

配套补齐与测试稳定性收口。**没有新增产品能力，没有改动任何默认值。**
可插拔的本地推理审批模型仍**保留为实验、未采用**——0.1.0 的研究结论逐条不变。

### 变化

- **`/status` 增加 `Guardian config` 行**：显示配置文件里显式写下的 Guardian override
  （`model` / `provider` / `reasoning effort` / `evidence dir`）。三态：reviewer 为 `auto_review`
  时显示"已加载"；reviewer 为 `user` 时显示配置存在但当前未选用；没有任何 override 时不增加这一行。
  措辞只声明**配置已加载**——某次 review 实际用了哪个模型，由 Guardian 在会话创建时按
  "显式配置 → catalog override → provider 默认"解析，状态面板证明不了这件事。
- **配置指南补齐 Local 节**：仓库根 `doc/rondo-config.md` 现按"公共 Guardian / Multi / Local"三节组织，
  README 有入口。Local 节说明唯一的 Local 专属配置字段 `features.exec_command_repeat_guidance`
  （默认关闭）、本地推理审批模型的配置层前提（必须写在用户级 `~/.codex/config.toml`，
  不能写进项目层 `.codex/config.toml`），以及它和 `rondo.local.toml` 是两条独立链路。
  产品树内继承自上游的 `docs/` 与 `codex-rs/config.md` 不改，以保持与上游可直接比较。
- **测试稳定性**：完整 workspace 暴露的两类测试编排问题已闭合。`sandbox_network_proxy` 的 loopback
  fixture 改为先读完请求头再应答，并有序半关闭连接——接收队列仍有未读字节时关闭 socket 会让内核发
  RST 而不是 FIN，代理把它当上游失败，于是在目标本已放行、204 也已写出的情况下仍向 curl 回 502。
  另有 4 个 zsh-fork app-server 集成测试并入既有的单线程 Nextest 组：它们与其它 app-server 用例同波
  启动时会耗尽初始化期限。修复只动测试 fixture 与 Nextest 分组，没有放宽 timeout、弱化断言，
  也没有增加 skip 或 ignore。

### 测试

Linux 完整 workspace（default features、checksum-verified V8、`CARGO_INCREMENTAL=0`）
`14122 / 14122` 通过，0 failure / 0 error / 0 timeout / 0 retry；另有 23 个 skip，不计入通过数。

这是**正确性与稳定性**的结果，不是性能数字，不构成任何质量资格或生产承诺。

### 不变

- 二进制 `--version` 仍报告冻结上游基线 `0.147.0`；产品版本以 tag 为准。
- 包布局、入口名 `rondo`、许可材料与发布目标（仅 `x86_64-unknown-linux-musl`）与 0.1.0 相同。
- 依赖与 lockfile 未变。

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
