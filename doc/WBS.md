# RONDO 长程规划（WBS）

最后更新：2026-08-09

本文件只记录**当前阶段**与**方向级路线、依赖和授权门**。方向内部的详细分解见 `doc/WBS/`，
单次任务的技术方案见 `plan/`，已完成成果见 `doc/WBS-COMPLETED.md`。

## 1. 当前状态

- 上游基线冻结在 Codex CLI `v0.147.0`（`rust-v0.147.0`，上游 commit
  `be6e8eac029b183056b7e4402879f15d2c85f61b`）。
- 开发环境已就绪（见 `doc/development-environment.md`）：Rust 1.95.0、pnpm 10.33.0、uv、Docker Desktop 可用；本机未装 Bazel。
- 本机推理硬件：RTX 4060 Laptop **8GB VRAM** / 32 核；RAM 与 WSL 配额见
  `doc/development-environment.md`。8B 级模型只能走 4-bit 量化，且上下文预算需实测。
- P0 共享地基已适配 `v0.147.0`，两个开关仍默认关闭。Guardian 证据在 HTTP/WS 各自的 transport
  send point 捕获，`call_id` / `turn_id` 只在 input 项的结构位点成对重映射，meta 带
  `guardian_source_baseline`；预取消轮、source baseline 与 builder-before-send 均有回归。
  P0 定向功能验收已收口（schema、fmt、clippy 与 16 项精确回归通过）；历史 workspace 的失败
  另见测试维护批次，不称“全量全绿”。
- `v0.147.0` 中 Guardian 默认模型候选由 provider/auth 决定：configured provider + API key
  候选为 `gpt-5.6-luna`，ChatGPT/无 key 候选为 `codex-auto-review`，Bedrock 使用自身模型 id；
  候选不在 catalog 且无 metadata override 时仍会回退主模型。RONDO 显式 `[auto_review].model`
  保持最高优先级。
- Luna 的 Responses Lite 线路并非 0.147 新增，但 API-key 默认改选 Luna 后成为默认可达路径。
  `E_final` 保存 transport 即将发送的完整逻辑请求而不是 WebSocket 增量 delta；消费者不得假设 policy
  和 tools 总在顶层 `instructions` / `tools`，也不得保留新增的 provider-private
  `encrypted_function_args`；新旧 Guardian 源码证据须按 meta 中的 source baseline 分层。实际有效
  policy 仍须由 P1 从 `E_final` 提取并哈希，不能用源码版本替代。
- 测评体系、教师 harness 研究尚未开始。
- **当前阶段：P1 草稿审查与 L1 / L2 准备**。P1 尚未实施，Docker 与小额真实 API 仍受 §6
  授权门约束。

## 2. 方向与依赖

方向编号沿用 `README.md` 的「研究方向」：

| 编号 | 方向 | 状态 |
|---|---|---|
| 0 | 量化测评基准（离线回放 + 真实 Terminal-Bench 2.1） | P0 定向复验通过；P1 草稿待审 |
| 1 | Harness 优化（Terminal-Bench 2.1 成功率） | 前置研究可并行，实施被方向 0 阻塞 |
| 2 | 本地审批模型接入与横评 | P0 定向复验通过；暂不进入实现 |
| 3 | 共享可信证据链的多智能体协作 | 未启动，排在方向 1 之后 |

依赖形状是 Y 形，不是两条平行线：

```
                    ┌─→ 方向0 测评基准 ─────────┐
P0 共享地基 ────────┤                          ├─→ 方向1 实施 ─→ 方向3
（S1 审批模型覆盖   └─→ 方向2 本地审批模型 ─────┘
  S2 证据包快照）        ↑ 需少量真实 E_final，切成互斥的 seed / holdout 两区

方向1 前置研究（T 轨，纯只读出文档）：现在即可并行，不依赖任何前置
```

关键依赖说明：

- **方向 0 和方向 2 共用 P0**。P0 不完成，两条线都会各自造一套临时开关，后面必然返工。P0 规模很小，应一次做完。
- **方向 2 的训练数据用 GPT 批量合成，不依赖真实跑批**，因此比原先设想更独立。真实 `E_final` 必须先按确定性哈希切成**互斥**的 `seed`（供合成器当模板）与 `holdout`（只做评测）两区：让同一批证据既当模板又当评测集，即使原文不进训练集，也会通过合成器把评测集分布带进训练数据。真实证据包本身**不得进入训练集**。
- **方向 1 的实施必须等测评基线可用**，否则没有"优化是否有效"的判据。但只读的教师研究不受此约束。

## 3. 阶段划分

| 阶段 | 内容 | 并行关系 | 依赖 | 授权门 | 状态 |
|---|---|---|---|---|---|
| P0 | 共享地基：审批模型显式覆盖（S1）、审批证据包快照（S2） | 单线，一次做完 | 无 | 无 | 本工作树复验通过，待审查/合并 |
| P1 | 方向 0：Terminal-Bench 2.1 最小真实链路跑通（E-B1~B3） | 与 L1、L2（仅搭建）、T 轨并行 | P0 | Docker 使用；小额真实 API | 未开始 |
| P2 | 方向 0：离线冻结回放（E-A）+ TB 分层任务集与首次基线（E-B4~B7） | 与 L2（验收）、L2a、L3、L4 并行 | P1 | canary 批量跑批预算 | 未开始 |
| P3 | 方向 2：合成数据（L5）→ 云 GPU 微调（L6）→ 一键切换（L7） | 与 P2 尾段并行 | L2a、L4、少量真实 `E_final` | GPT 批量合成费用；云 GPU 训练 | 未开始 |
| P4 | 方向 1：按测评基线驱动 harness 优化迭代 | 串行 | P2 完成 | 每轮跑批预算 | 未开始 |

阶段与任务编号一一对应，不重叠：L1/L2 属 P1，L2a/L3/L4 属 P2，L5/L6/L7 属 P3。
注意 **L2 可以在 P1 期间先把本地推理服务搭起来并量上下文预算，但它的验收要用真实 `E_final`，因此最终验收挂在 B3 之后**——搭建与验收分处两阶段，不是矛盾。

你选定的排序理由：**先打通真实链路（P1）而不是先做离线回放**。真实跑批同时产出离线回放需要的高保真录制素材和方向 2 需要的证据包模板，是双料解锁点；先做离线回放会拿合成 fixture 起步，后面大概率要按真实录制重做一遍。

## 4. 里程碑与验收口径

| 里程碑 | 验收口径 |
|---|---|
| M0 | `config.toml` 可显式指定 Guardian 审批模型与 effort 并在真实请求中生效；一轮审批能落盘一份规范化 `E_final` |
| M1 | TB 2.1 上冻结 codex 与 RONDO 各跑通同一任务的端到端，结果可归档 |
| M2 | 离线回放测评一键可跑并出曲线；canary 首次基线通过下述 **A/A 对称性检验** |
| M3 | Luna-static / Sol-static / Local-static 同证据横评首版报告（本地模型为**未微调** baseline） |
| M4 | 微调后本地模型横评报告 + 审批模型一键切换可用（依赖 L2a） |
| M5 | 方向 1 首个优化项在 canary 上取得**可复现**的成功率或成本改善 |

### M2 的可执行判据

"两侧分数接近"没有阈值就不是门禁。真实模型跑 10 个任务各一次的随机波动很大，不能直接拿跨侧差异下结论。改用**同一二进制自比得出的波动带宽当尺子**，不引入统计显著性框架：

1. **A/A**：用**同一个** RONDO 二进制在 canary 上跑 2 轮（同任务、同顺序、同配置）。两轮间结果不同的任务数记为 `σ`，作为**观测不一致预算**——它是一次经验观测，不是统计估计，不要按置信区间解读。
2. **A/B**：冻结 codex 与 RONDO 各跑 1 轮，条件与 A/A 完全相同。
3. **通过判据（纯机械，不含主观判断）**：
   - 跨侧结果不同的任务数 `≤ σ`；**且**
   - 出现任意「codex 通过 / RONDO 失败」的任务时，对该任务两侧各**加跑 2 轮**；若 RONDO 侧仍全败而 codex 侧全过，判定不通过。单轮结果不足以判断"稳定"，所以用加跑而不是靠人判断。
4. **基础设施失败**（容器/网络/超时）的任务不计入分子分母，单独重跑；单轮基础设施失败率 > 20% 则该轮作废重跑。
5. **预算口径**：10 任务 × 4 轮 = 40 次运行，外加可能的定点加跑（每个触发任务 4 次）。按 B6 出预估并单独授权。

不通过就先修测评设施，不得先推进优化。若 `σ` 本身大到接近任务总数（说明 canary 选得太不稳定），回到 B4 重挑任务，而不是放宽判据。

## 5. 当前阶段任务

P0 的 2026-08-09 复验修复已在独立工作树完成定向门禁；此前验收和失败差集见
`doc/WBS-COMPLETED.md` 与 `agent_log/2026-08-08-233753-p0-strict-acceptance.md`，本轮结论见
`agent_log/2026-08-09-020200-baseline-p0-test-audit.md`。P1 草稿见
`plan/003-p1-terminal-bench-minimal-chain-draft.md`，在本轮改动审查/合并和用户确认草稿前不进入实现；
涉及 Docker、真实 API 或数据外发时仍先走 §6 授权门。任务 4 的失败测试处置另立维护批次，不混入 P1。

P0 遗留的能力边界，进入后续阶段前必须记住：**S1 只覆盖审批模型名与 effort，不覆盖 provider**。
Guardian 仍克隆父会话的 provider 与 base_url，因此切换到本地审批模型需要独立的 provider 覆盖，
已拆为方向 2 的 **L2a**，是 L7 的前置。任何"P0 完成即可一键切换本地模型"的表述都不成立。
这一边界与 `v0.147.0` 的 provider 默认模型分流不矛盾：默认模型可随 provider/auth 变化，
但 Guardian 请求仍没有因此切到另一个 provider 或 base_url。

## 6. 授权门

以下动作必须在执行前单独取得授权，不随普通开发一起进行：

- 宿主机 Docker 拉镜像与运行容器（TB 2.1 任务环境）。
- 任何真实 API 批量跑批：需事先说明任务范围、轮数、模型与预算上限。
- GPT 批量合成训练数据（产生费用）。
- 项目外云 GPU 训练与权重上传下载。
- 上游基线升级（独立任务，不混入功能开发）。

## 7. 测试与测评体系原则

- **测试（test）** 直接继承并扩展 Codex 原有体系，不另建框架：保留全部上游测试作为兼容性基线，复用 Nextest、`TestCodexBuilder`、WireMock、临时 workspace、exec-server 与 app-server 测试客户端。RONDO 只为新增模块、改变后的行为和新性能路径补增量单元测试、集成测试与基准测试。
- 归属界定：Divan / Bazel benchmark 等属于**测评**设施，不算测试体系的一部分。
- 行为改变型优化：保留仍成立的原测试，修改已不成立的旧语义测试，并需要测评证据证明有效；修 bug 型优化：原测试保留，新增一个"旧实现失败、新实现通过"的回归测试；纯实现优化：原则上不改原测试，性能交给测评体系。
- **测评（eval）** 是有效代码的一部分，轻量、开箱即用，自动运行、自动记录、自动归档，可出曲线；不做数据资产审计等重机制。
- 探针只放少量关键节点，内存累积、轮末统一输出。**跨侧对比只用 runner 进程外采集的外部指标**（wall / CPU / RSS）；内部探针只存在于 RONDO，用于自身版本间对比，不往冻结 codex 里打补丁（详见 `doc/WBS/eval-benchmark.md` A4）。
- 原始 codex 与 RONDO 的对比测评统一关闭 websocket（provider 侧
  `ModelProviderInfo.supports_websockets = false`，见 `codex-rs/model-provider-info/src/lib.rs`）。

## 8. 子规划索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：量化测评基准
- `doc/WBS/local-approval-model.md` —— 方向 2：本地审批模型接入与横评
- `doc/WBS/teacher-harness-study.md` —— 方向 1 前置：教师 harness 只读研究
- `doc/eval-data-layout.md` —— 测评结果与数据资产的保存规范（目录、命名、结果库、保留与 git 边界）
