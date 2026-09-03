# RONDO

> **R**ONDO **O**ptimizes **N**etworked **D**eliberation and **O**rchestration

RONDO 是一个基于 [OpenAI Codex CLI](https://github.com/openai/codex) 源码的**实验性 Agent Harness 研究项目**，
目标是把 Agent Harness 的若干理论问题变成可运行、可测量、可迭代的工程实践——并且诚实地记录哪些走通了、哪些没有。

> **English summary** — RONDO is an experimental research fork of OpenAI Codex CLI (v0.147.0) exploring
> agent-harness engineering: multi-agent shared-evidence architecture, replacing the cloud approval model
> with a locally-inferenced small model, and a quantitative evaluation harness for both. It ships two
> parallel product lines and a full offline/online eval system. Several research tracks concluded with
> **negative results**, which are documented as first-class outcomes rather than removed. All experimental
> capabilities are **off by default**. Not a production tool.

---

## ⚠️ 请先读这一段

- **这是研究项目，不是生产工具。** 请不要在真实工作流里依赖它。
- **所有行为改变型、实验性的能力都由显式 feature gate 控制，默认关闭。**
  但**部分行为保持型的热路径优化是默认生效的**（例如工具路由的数据结构改造），它们不受 gate 控制。
  本项目没有逐项验证过"关闭态与上游逐字节等价"，因此不作这种承诺。
- **本项目不对外提供任何性能提升数字。** 项目内部的测评结论中，有相当一部分是**负向结果**
  （详见 [诚实的结果](#诚实的结果)）。没有经过验收的东西，这里不会声称它有效。
- **Publication Critic 不是安全门，也不是发布审批。** 它是一个有界改写机制，详见
  [实验性功能](#实验性功能publication-critic默认关闭)。
- **这是 fork，不是从零实现。** 上游 Codex 的绝大部分代码不是我写的，具体改了多少见下表。

---

## 项目概况

| | |
|---|---|
| 上游基线 | OpenAI Codex CLI `v0.147.0`（`rust-v0.147.0`，commit `be6e8eac`），全程冻结不升级 |
| 主要语言 | Rust（产品源码）+ Python（测评设施） |
| 产品线 | 两条并列：**RONDO Local**（`mydev/`）、**RONDO Multi**（`multidev/`） |
| 开发周期 | 2026-08-04 起，1355 次提交 |
| 许可证 | Apache-2.0（继承上游） |

**相对上游基线的改动量**（统计于 commit `d82a07f1`）：

| | 新增/改后行 | 删除/改前行 | 改动文件 | 新增条目 |
|---|---|---|---|---|
| RONDO Local (`mydev/codex-rs`) | +6,486 | −763 | 137 | 16 |
| RONDO Multi (`multidev/codex-rs`) | +90,165 | −1,483 | 289 | 140 |

> 复现方法需要**两条命令**（`-rN` 不产生 `Files`/`Only in` 行，`-rq` 不产生逐行差异）：
>
> ```bash
> SRC=codex-source-code/codex-rs; DST=<product>/codex-rs
> # 增删行数
> diff -rN -x target -x .git -x __pycache__ "$SRC" "$DST" \
>   | grep -c '^> '   # 新增/改后行；把 '^> ' 换成 '^< ' 得删除/改前行
> # 改动文件数与新增条目数
> diff -rq -x target -x .git -x __pycache__ "$SRC" "$DST" | grep -c '^Files '
> diff -rq -x target -x .git -x __pycache__ "$SRC" "$DST" | grep -c '^Only in '"$DST"
> ```
>
> "新增条目"含目录（`diff -rq` 对单侧目录只报一行，不展开）。
> `codex-source-code/` 是 git-ignored 的上游只读快照，需自行从上游 `rust-v0.147.0` 获取后才能复现。

**自建测评与测试设施：**

| | 规模 |
|---|---|
| 测评设施 `eval/`（Python） | 378 个文件，约 256,000 行 |
| 测评设施自身的测试 | 96 个测试文件，2,025 个测试函数 |
| RONDO Multi 的 Rust 正确性基线 | Linux 全量 workspace `14,713 / 14,713` 通过，0 failure/error/timeout/retry（24 个 skip 不计入通过） |
| RONDO Local 的 Rust 正确性基线 | Linux 全量 workspace `14,122 / 14,122` 通过，0 failure/error/timeout/retry（23 个 skip 不计入通过） |

> Multi 的当前基线由 Plan 105 建立，Local 的当前基线由 Plan 108 建立；两者是各自 workspace 的独立正确性结果，
> 测试数量不可跨产品线直接比较。

---

## 研究问题

项目围绕四个方向展开，其中方向 0 是支撑其他三个方向的基础设施：

**方向 0 · 量化测评基准**
先建立能说话的尺子，再谈优化。分两层：
- **离线冻结回放**——用于验证"行为保持型"改动（运行时、数据结构、工具执行），成本低、可反复跑，支持故障注入。
- **真实 API + Terminal-Bench 2.1**——用于验证"行为改变型"改动，作为最终可信指标。

**方向 1 · Harness 优化**
学习其他 agent harness 的实现，尝试提升 Terminal-Bench 2.1 的任务解决率，同时保证能与冻结的原始 Codex 做公平对比。

**方向 2 · 本地审批模型**
把 Codex `approve for me` 的云端审批模型换成微调后本地推理的小模型，量化审批质量与成本相对云端教师模型的差距。要求可插拔、一键切换。

**方向 3 · 多智能体共享证据架构**
让同一份工具调用结果等"证据"能成为多个智能体的共同参考，评估它在方案审查、代码审查和智能体间通信中的效果与开销。
这是唯一一个独立成产品线的方向。

---

## 两条产品线

两条产品线共享测评设施、构建锁与工具链，但**核心源码相互独立**，不追求提交级同步。

### RONDO Local（`mydev/`）

保持冻结 Codex 的单智能体 thread/rollout 语义，在此之上：

- 扩展 Guardian 的模型、reasoning effort 与 provider 选择
- 接入可插拔的本地推理审批模型（OpenAI-compatible 接口，一键切换）
- 若干 harness 热路径优化与观测设施

承载方向 1、2。两个方向目前均已收口。

> **本地审批模型不是下载即用。** 它依赖未随仓库分发的模型权重与本地推理运行时，
> 以及测评侧的桥接设施。方向 2 的最终结论也是"保留为实验，未采用"（见下）。

### RONDO Multi（`multidev/`）

方向 3 的独立产品源码，可自由演进任务图与证据图，不要求与 Local 同内核。核心是一套 **Event 驱动的团队世界状态**：

- **Team State** 作为 Event、Version、生命周期、可见性与指派的唯一 canonical 来源
- **Fact** 是对 Codex 已保留的历史 observation 的可解析引用，**不复制 payload**——这是"共享证据"的关键设计：
  证据不被复制成 N 份，而是被多个智能体按权限引用
- **权限模型**：Root 可读本团队全部证据；子 Agent 只能读自己产生的、或从其可见 Event 可达的 Fact
- **Durable Team Session**：app-server v2 / TUI 控制面与 Writer Workspace Binding
- **Team Lens**：本地离线 reducer / viewer，不参与 runtime 调度

一条明确的自我约束是：**复用 Codex 原生的执行与通信机制**，不另建 A2A 协议、调度器、全局订阅或 workspace 协调层。
"某个 Event 值不值得发布""Root 该怎么 route 和 resolve"仍然交给模型做语义判断，而不是由 harness 代劳。

---

## 诚实的结果

这是本项目最想强调的一节。研究做完了，结论有好有坏，这里如实列出。

| 方向 | 结论 | 说明 |
|---|---|---|
| 0 · 测评基准 | ✅ 设施建成可用 | 离线回放与真实 API 两层均已落地并产出过正式结果 |
| 1 · Harness 优化 | ⏸️ 正式收口 | 完成了观测、瓶颈普查与若干热路径优化并已合入。**本项目不对外给出任务解决率提升数字。** |
| 2 · 本地审批模型 | ⚠️ **保留为实验，未采用** | 微调模型在同源合成样本上明显改善，但样本与训练数据同源且存在措辞线索；真实 holdout 只含 allow 标签，只能暴露误拦、无法检验过度放行。**现有证据不足以证明它能安全地放行真实审批**，因此不改生产默认。 |
| 3 · 多智能体共享证据 | 🔶 分两层，见下 | 产品架构与工程链通过；其中的判官子系统未获质量资格 |

### 方向 3 需要分两层看

这两件事经常被混为一谈，但结论完全不同：

**第一层 · RONDO Multi 作为实验性研究产品** — 架构与工程链已通过

- ✅ Event 驱动的 Team State、Fact 引用式共享证据、权限模型、Durable Team Session 均已实现并进入主线
- ✅ Linux 全量 workspace 正确性基线 `14,713 / 14,713` 通过
- ✅ `PublicationScorer → service → typed client → 发布` 整条链在 OFF / 本地模型 / 云端模型三种状态下均验证通过，
  包括重写循环、唯一提交、失败与取消路径、状态不变量；**双 backend 可替换性成立**

**第二层 · Publication Critic 作为 Multi 内的可选子系统** — 判官模型未获质量资格

- ❌ **本地判官模型 NO-GO**：多轮训练实验（全参数微调、部分参数更新、多条路线）均未产生达到预冻结质量门的候选。
  最后一轮正式训练形成有效 `NO-GO`——训练本身有效、流程干净、结论是负的。
- ❌ **云端判官模型未获资格**：正式测评 ROC AUC `0.8403`、Boundary strict win `15/19` 均过线，
  但 False PASS `8/21` 超出 `5/21` 上限，整条 operating curve 上不存在同时满足全部质量门的工作点。
- 🔶 **五维判官接缝**：已从单标量改造为五维 hard decision + 本地非补偿合取，工程接缝可用（`ENGINEERING_SEAM_PASS`），
  **但不含任何质量或资格结论**。

**所以：RONDO Multi 本体是一个可以运行、有正确性基线的实验产品；Publication Critic 是它里面一个默认关闭、
判官质量未过关的可选子系统。** 后者保留在代码里不是因为它被证明有用，而是因为把它做出来并诚实地证明
"目前还不够好"本身就是研究结果。

---

## 快速开始

### 下载预编译产品包

只提供 `x86_64-unknown-linux-musl` 一个目标。**不提供 macOS / Windows 产物**——没有可验证的
环境，发一个自己无法验证的平台产物比不发更糟。

两条产品线各有独立的发布轨，链接固定指向各自的 tag：

```bash
# RONDO Multi
curl -fLO https://github.com/sjc786526-coder/RONDO/releases/download/multi-v0.1.1/rondo-multi-0.1.1-x86_64-unknown-linux-musl.tar.gz
tar xzf rondo-multi-0.1.1-x86_64-unknown-linux-musl.tar.gz
./rondo-multi-0.1.1-x86_64-unknown-linux-musl/bin/rondo-multi --version

# RONDO Local
curl -fLO https://github.com/sjc786526-coder/RONDO/releases/download/local-v0.1.1/rondo-0.1.1-x86_64-unknown-linux-musl.tar.gz
tar xzf rondo-0.1.1-x86_64-unknown-linux-musl.tar.gz
./rondo-0.1.1-x86_64-unknown-linux-musl/bin/rondo --version
```

每个 Release 另附 `SHA256SUMS`，校验：`sha256sum -c SHA256SUMS`。

> **不要把 `bin/` 下的可执行文件单独拷出来。** 附属组件按包内相对路径解析，
> 拷出来就找不到了。把整个解压目录留在原地，或把 `bin/` 加入 `PATH`。

> **版本号说明**：`--version` 输出 `0.147.0`，那是被冻结的上游基线版本号，全程不改，
> 以支持与原始 Codex 的字节级公平对比。**产品版本以 Release tag 为准。**

> 本仓库同时发布两条独立产品线，而 GitHub 的仓库级 "Latest" 指针只有一个，
> 它总是落在**最近发布的那个正式版**（当前是 `local-v0.1.1`）。这只是平台的展示状态，
> **不代表版本权威，也不表示另一条产品线过时**。请始终使用上面各自的固定 tag 链接。

### 从源码构建

需要 Rust 工具链（版本见各产品线的 `codex-rs/rust-toolchain.toml`）。

从仓库根目录执行（两条命令互相独立，不要连着 `cd`）：

```bash
# RONDO Multi
cargo build --release --manifest-path multidev/codex-rs/Cargo.toml -p codex-cli

# RONDO Local
cargo build --release --manifest-path mydev/codex-rs/Cargo.toml -p codex-cli
```

产物在对应的 `<product>/codex-rs/target/release/codex`。

> **注意：`cargo build` 出来的裸二进制不是完整产品包。**
> 完整产品还包含 `codex-code-mode-host`、Linux 的 `bwrap`、`rg`、平台资源与 `codex-package.json`，
> 由各产品线的 `scripts/build_codex_package.py` 组装（见 `<product>/scripts/codex_package/README.md`）。
> 裸二进制能启动，但依赖这些附属组件的功能不可用。要完整体验请用打包器构建。

基础用法与配置与上游 Codex CLI 一致，见各产品线下的 `docs/getting-started.md` 与 `docs/config.md`。

> **RONDO 相对上游新增的配置**单独整理在 **[`doc/rondo-config.md`](doc/rondo-config.md)**，按
> 公共 Guardian（模型 / provider / effort / 证据目录）、Multi 专属（Team State、Durable Team、
> Publication Critic）、Local 专属（`exec_command_repeat_guidance`）三节组织。
> Guardian 的 reviewer 默认仍为 `user`，四个 override 默认不设置；两条产品线的专属能力也都默认关闭。

> **构建资源提示**：这是一个约 130 个 crate 的 Rust workspace（Multi 131、Local 129），完整构建吃内存也吃时间。
> 本仓库的开发流程用 `scripts/with-build-lock.sh` 做单构建互斥和内存看门狗——那是为受限开发机准备的，
> 你自己构建时不需要它。

---

## 实验性功能：Publication Critic（默认关闭）

多智能体发布流程中的"判官"：Producer 智能体产出内容后，由 Critic 给出 `PASS` / `REWRITE` 判定。

### 它是有界改写机制，不是发布门

这一点务必看清楚。一个 publication cycle 最多包含原稿和两份改稿，共三次审查：

| 审查 | `PASS` | `REWRITE` |
|---|---|---|
| 第 1 次（原稿） | 提交 | **不提交**，给第一次重写机会 |
| 第 2 次（改稿一） | 提交 | **不提交**，给最后一次重写机会 |
| 第 3 次（改稿二） | 提交 | **仍然提交**（记为"重写机会已耗尽"） |

也就是说：**第三次审查是非阻断的，即使判定为 `REWRITE`，第二次改稿也会被提交。**

此外，当判官服务超时、不可用、排队失败、返回无效输出或任何无法形成有效 verdict 的情况下，
流程会**停止本轮审查并尝试提交当前稿**，状态记为"审核未完成"——不冒充 `PASS`，但也不阻断提交。

所以它的作用是**在有限次数内推动改写质量**，不是安全审批、不是发布门、也不是最终质量保证。
契约细节见 `doc/rondo-multi-publication-critic-product-contract.md` 第 4 节。

**默认状态：完全关闭。** 配置缺省即为 OFF，且启用需要显式满足多个前置条件：

```toml
[features.multi_agent_v2]
enabled = true
team_state_enabled = true          # Publication Critic 强制依赖此项

[features.multi_agent_v2.publication_critic]
endpoint = "127.0.0.1:PORT"        # 必须是字面量 loopback 地址
expected_descriptor_json = "..."   # 必须与服务描述符严格匹配，否则 fail-closed
```

设计上的几个保守选择：

- endpoint **只接受字面量 loopback 地址**，不接受主机名或外部地址
- 启动时严格校验服务描述符，不匹配直接 fail-closed，不降级运行
- 缺少 `team_state_enabled` 时拒绝启动，而不是静默忽略
- 当前采用五维 hard decision + 本地非补偿合取派生 verdict（任一维不达标即 `REWRITE`），
  历史上的单标量 threshold 路径已废弃，仅作为诊断/历史参考保留
- 云端 backend 的 scoring definition 强制带 `rondo-cloud-reference-` 前缀，避免与任何已验收结论混淆

### 判官后端需要自行从源码构建

主 CLI 里编进去的只是 **Critic 客户端接缝**。实际打分的服务是独立二进制，**不包含在 Release 产物中**：

| 二进制 | 用途 | 前提 |
|---|---|---|
| `codex-publication-critic-real-service` | 本地模型后端 | 需要未随仓库分发的模型权重与推理运行时 |
| `codex-publication-critic-cloud-service` | 云端模型后端 | 需要你自己的 API 凭据 |

要试用请分别构建（`-p` 会把包内全部二进制都编出来，所以指定 `--bin`）：

```bash
cargo build --release --manifest-path multidev/codex-rs/Cargo.toml \
  --bin codex-publication-critic-real-service
cargo build --release --manifest-path multidev/codex-rs/Cargo.toml \
  --bin codex-publication-critic-cloud-service
```

> 同一个包里还有 `codex-publication-critic-service`（**仅供测试的受控服务**）
> 以及若干 `-probe` / `-eval` / `-diagnostic` 诊断工具。
> 受控测试服务**不是产品判官，不要当判官用**。

**再次强调：这个功能的判官模型没有通过质量验收**（见 [诚实的结果](#诚实的结果)）。
它默认关闭不是因为还没做完，而是因为证据不支持默认打开。

---

## 这个项目是怎么开发的

**RONDO 主要由 AI 完成编码，人负责规划、约束、验收与叫停。** 这一点写在这里，而不是让你自己去 commit 记录里发现。

我认为这里真正的工程内容不是"手敲了多少行 Rust"，而是**如何让 AI 驱动的开发不失控**：

1. **规划与执行分离**——`doc/WBS.md` 是当前阶段与跨任务路线的唯一来源；每个任务先冻结一份 ExecPlan
   （目标、范围、硬约束、验收标准），执行期间不得自行修改目标。仓库里有 **98 份**这样的任务合同。
2. **先建尺子再优化**——方向 0 的测评设施是其他所有方向的前置。没有可量化指标的优化不做。
3. **验收门禁与证据分级**——fake / 离线 / 真实 API / 真实模型 / Docker 的证据严格区分；
   skip 与未运行**不得表述为通过**；不允许为了让指标好看而弱化测试或审批逻辑。
4. **敢于判负**——预先冻结通过门，达不到就是达不到。多个方向的最终结论是 `NO-GO` / `NOT_QUALIFIED` /
   `保留为实验`，这些结论连同证据完整保留在仓库里，没有被事后修饰。
5. **资源与安全边界前置**——重型构建互斥锁与内存/磁盘看门狗、密钥文件的只读存在性检查、
   云 GPU 与付费 API 的逐任务授权门和预算上限（每次任务的实际花费都有记录，精确到小数点后若干位）。

完整的过程证据都在仓库里：**581 份**执行日志（`agent_log/`）、**98 份**任务合同（`plan/`）、
**5 份**审计快照（`doc/audit-snapshots/`）、**14 份**研究报告（`doc/research/`）、
**67 份**测评结果（`eval/results/`）。

如果你想评估这个项目，我建议看的不是代码行数，而是 `doc/WBS.md` 和任意一份 `plan/` 里的验收标准怎么写的。

---

## 仓库结构

```text
RONDO/
├── .github/      # RONDO 自己的 CI / Release 工作流（唯一会被 GitHub 执行的一份）
│                 #   说明见 doc/ci-pipeline.md 与 doc/cd-release-pipeline.md
├── mydev/        # 产品源码：RONDO Local（方向 1、2）
├── multidev/     # 产品源码：RONDO Multi（方向 3）
├── eval/         # 两条产品线共用的测评设施
├── scripts/      # 共享构建锁与资源看门狗
├── training/     # 轻量训练合同与门限内数据集（权重与训练输出不入库）
├── doc/          # WBS 规划、研究报告、审计快照
│                 #   RONDO 增量配置说明见 doc/rondo-config.md
├── plan/         # 每次任务的冻结 ExecPlan
└── agent_log/    # 执行日志
```

> **关于 `mydev/.github/` 与 `multidev/.github/`**：这两份是从上游 Codex 原样继承下来的**惰性文件**。
> GitHub Actions 只执行仓库根的 `.github/workflows/`，子目录里的同名文件**不会被触发**。
> 它们被保留而不是删除，一是因为产品自身的构建脚本仍引用其中的内容
> （如 `justfile` 的 `test-github-scripts` 依赖 `.github/scripts/`），
> 二是本项目刻意保持产品树与上游可直接 `diff` 比较，删掉只会增加无意义的差异噪音。

未纳入版本控制的目录：`codex-source-code/`（上游只读快照，用于比较）、`eval-data/`（本地重资产与私有运行数据）、
`test-data/`（历史测试数据）、模型权重与训练输出。

---

## 与上游 Codex 的关系

- 上游项目：[openai/codex](https://github.com/openai/codex)，冻结在 `v0.147.0`
- 本项目**不是** OpenAI 的产品，与 OpenAI 无关联，也未获其背书
- 上游 Codex 源码继续受其原有 [LICENSE](LICENSE) 与 [NOTICE](mydev/NOTICE) 约束
- 研究周期内基线保持冻结；上游升级被视为独立任务，不混入功能开发

## 许可证

RONDO 采用 [Apache License 2.0](LICENSE)。基于或包含的上游 Codex 源码继续受其原有许可证和 NOTICE 约束。
