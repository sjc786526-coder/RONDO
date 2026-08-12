# RONDO 长程规划（WBS）

最后更新：2026-08-11

本文件只记录**当前阶段**与**方向级路线、依赖和授权门**。方向内部的详细分解见 `doc/WBS/`，
单次任务的execplan见 `plan/`，已完成成果见 `doc/WBS-COMPLETED.md`。

## 1. 当前状态

- 上游基线冻结在 Codex CLI `v0.147.0`（`rust-v0.147.0`，上游 commit
  `be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
  `mydev/codex-rs/core/upstream-source-baseline.toml`。
- 开发环境已就绪（见 `doc/development-environment.md`）：Rust 1.95.0、pnpm 10.33.0、uv、Docker Desktop 可用；本机未装 Bazel。
- 本机推理硬件：RTX 4060 Laptop **8GB VRAM** / 32 核；RAM 与 WSL 配额见
  `doc/development-environment.md`。8B 级模型只能走 4-bit 量化，且上下文预算需实测。
- P0 共享地基已适配 `v0.147.0`，两个开关仍默认关闭。Guardian 证据在 HTTP/WS 各自的 transport
  send point 捕获，`call_id` / `turn_id` 只在 input 项的结构位点成对重映射，meta 带
  `guardian_source_baseline` 与 `guardian_source_commit`；预取消轮、source identity 与
  builder-before-send 均有回归。
  P0 定向功能验收已收口（schema、fmt、clippy 与 16 项精确回归通过）；历史 workspace 的失败
  另见测试维护批次，不称“全量全绿”。
- `v0.147.0` 中 Guardian 默认模型候选由 provider/auth 决定：configured provider + API key
  候选为 `gpt-5.6-luna`，ChatGPT/无 key 候选为 `codex-auto-review`，Bedrock 使用自身模型 id；
  候选不在 catalog 且无 metadata override 时仍会回退主模型。RONDO 显式 `[auto_review].model`
  保持最高优先级。
- Luna 的 Responses Lite 线路并非 0.147 新增，但 API-key 默认改选 Luna 后成为默认可达路径。
  `E_final` 保存 transport 即将发送的完整逻辑请求而不是 WebSocket 增量 delta；消费者不得假设 policy
  和 tools 总在顶层 `instructions` / `tools`，也不得保留新增的 provider-private
  `encrypted_function_args`；新旧 Guardian 源码证据须按 meta 中的 source tag/commit 分层。实际有效
  policy 仍须由 P1 从 `E_final` 提取并哈希，不能用源码版本替代。
- P1 已落地顶层 `eval/` 体系：Standard/Lite `E_final`、静态审批、严格本地配置、付费预算与发布恢复、
  Docker/watchdog 监督、Terminal-Bench 双适配器和 llama.cpp 前置设施。Plan 009 将 no-API 从付费式
  permanent ledger、retirement、崩溃恢复和一次性 migration 中解耦；这些历史机制不再是 B2 生产路径。
  Plan 010 的 paid v6 pair 已按授权执行 RONDO 首槽，但当时 ignored config、tracked pair 和 budget proxy 都把
  上游错误固定为官方 OpenAI endpoint，因而等待错误上游超时；该 pair 已失败并按零重试合同阻断，Codex 与 M1
  未运行。Plan 011 已恢复配置驱动的通用 OpenAI-compatible HTTPS endpoint，真实 provider 仅由 ignored 本地配置决定；
  v7 随后按单独授权执行 RONDO 首槽，但在没有响应或 usage 时以 `AgentTimeoutError` 收敛为 `infra_failed`。Codex 与
  M1 未运行，v7 pair 已 failed/blocked。Plan 012 已把 transport timeout 限为 90 秒、让 SSE 在合法 terminal
  event + usage 后主动结束，并修通 frozen solution/root verifier，真实 oracle 得到 `reward=1`。配置所指 provider
  Luna 主请求未通过门禁；随后 frozen Codex v0.147 的 Sol real-wire 在保留宿主网络代理时得到 terminal response、
  合法 usage 和 settled ledger。v8 RONDO slot 1 的 5 个 Sol main 请求均成功，但自然触发的 API-key Guardian
  仍按冻结公平合同请求 Luna 并收到 HTTP 503；pair 因而 `failed/blocked`，Codex slot 2 与 M1 未运行。
- Plan 013 已把 paid eval 的 provider、base URL、main/Guardian model、reasoning effort、官方价格快照和
  未计费 attempt 合同统一移入 ignored `rondo.local.toml` profile。proxy 对每个 main/Guardian downstream
  请求最多执行 5 个 operator-confirmed-unbilled upstream attempts，共用一次 reservation 与 90 秒 transport
  deadline；timeout、断连或无法完整分类的错误仍不重试并保守停止。后续真实 CLI 诊断修正了 synthetic
  Guardian 探针与实际请求的偏差：format 使用 `codex_output_schema` + `strict=false`，非 Azure Responses 请求带
  `store=false`；冻结 API-key Guardian 对 Luna/Sol/Terra 均优先使用 `low`，不能沿用主模型的 `medium`。
  冻结 Codex 与 RONDO 均已真实跑通 Luna main/Guardian。冻结 Codex 随后用与 bundle source commit 一致的
  最小 `model_catalog_json` 将 `auto_review_model_override` 设为 Sol，和 RONDO 的显式 `[auto_review]` 一起完成
  3 轮双端 Sol/Sol 零重试短测：24/24 个 upstream request 一次成功、usage valid，两端审批链均为
  `main → guardian → main`。早期同一路径出现过 403/429/503 与 200 缺 usage，因此该结论只说明当前短窗口
  Sol/Sol 稳定性良好，不替代 B3/M1。
- Terminal-Bench B1 固定 Harbor `0.20.0`、`uv.lock`、TB 2.1 commit、`fix-git` task/image digest 和两侧
  runtime bundle。Harbor 启动前只核对版本、console/interpreter 与三个关键模块，不再扫描数千个依赖文件。
  B2 由唯一入口在同一进程中严格执行 RONDO→Codex，首侧失败立即停止；成功后只替换一个
  `eval-data/b2/current.json` 当前收据。marker 必须来自 `exit_code=0` 且 stdout 精确等于固定值的结构化
  `exec_command` 结果。Plan 009 已在 clean commit `b47a7b4` 上通过受监督的真实 Docker
  no-API 双侧验收：RONDO、Codex 均 completed，各 2 次 fake 请求且 tool round-trip 成功，
  官方 API 0 次、费用 0 USD，两侧均精确清理为空。
- L1 协议与三组 consumer 协议/fixture 逐字节投影已完成，合法 `ToolSearchOutput` 可消费且最终 sink
  fail-closed；本阶段不宣称已有三套独立生产调用端。
  L2 项目局部 llama.cpp `b10333` 已冻结 CPU x64 前端/动态运行闭包、配置、client、
  doctor、fake 和启动入口。model-backed client 必须校验 launcher 私有 receipt，并在请求前后
  重验 PID/start ticks、cmdline、监听 socket、receipt 中的 runtime/model identity 与 endpoint；这
  仍未证明 server 实际加载字节，也未证明 launcher 死亡后 server 必然随之退出。当前无权重，
  CPU frontend/runtime closure 是已验边界；GPU runtime、model-backed 启动/推理、显存/延迟与
  L2a/L3/L4 均未实现验收，不称“只差权重”。
- **当前阶段：P1 的 B1、B2、B3、L1 与 L2 CPU x64 前置已整体完成，M1 已通过。Plan 014 v19 在同一冻结
  Sol/medium main + Sol/low Guardian profile 下按 RONDO→frozen Codex 完成 `fix-git` 双侧真实链路；两侧
  reward 均为 1、预算均 settled，RONDO 的两份自然 Guardian `E_final/meta` approved。不可改写的 v19 旧合同
  只能证明 task-scoped request/evidence count match；后续结果须通过 canonical request digest 一一绑定才称 S2 verified。
  `assess_m1` 返回 passed。P2 的 B4 分层清单、B5 计分归因与 B6 预算合同已冻结。v1—v14 均为只读终态。
  v15 在 fresh wire、db pass、extract 正常 reward 0 后，filter a1/a2 同类 Docker failure 触发诊断；no-API RCA
  证明 1024 PIDs 仅完成 9/28 个 Selenium batch，而 4096 PIDs 完成 28/28，并闭合自然 teardown 的
  inspect/remove 竞态。v16 的十题 Oracle 与 fresh wire 通过，但两轮 A/A 中 vulnerable 均三次命中
  provider-integrity，sanitize 一次后恢复；A/B RONDO 的 filter 随后触发第三个不同 task 的全局
  circuit breaker。v16 blocked 且 reservation 0，累计 debit `569.420620 USD`。v17 已以 run base
  `20260812-370000000`、唯一 lock/IDs 和精确 prior 冻结，700 USD 硬上限剩余
  `130.579380 USD`。**
  Plan 010 v6、Plan 011 v7 和 Plan 012 v8 的 paid RONDO 首槽均已失败。三次早期诊断均在
  付费 API 请求前停止，已一次性迁移为 `infra_failed` 永久记录并保留不可复用预算槽；实际 API 调用
  0 次、费用 0 USD。v6 固定 `fix-git`、RONDO→Codex 各一轮、零重试；RONDO 发起的一个 main 请求未收到
  上游响应或 usage，ledger 保留 0.755400 USD reservation，实际账单未查询。v6 已 `failed/blocked`，
  Codex 与 M1 未运行；继续 B3 需新 pair 与单独 API 授权。v7 同样只运行 RONDO：一个请求保留 0.755400 USD
  未结算 reservation，settled local spend 为 0，`actual_usd=null`；任务以 `AgentTimeoutError` 失败，Codex/M1
  未运行。v7 shell 清除了 ambient HTTP(S)/ALL proxy，仅保留 loopback `NO_PROXY`；tracked pair 不冻结供应商域名。
  Plan 012 所有真实探针与 v8 ledger 都已 settled、没有悬挂 reservation；v8 的 5 个 Sol main 请求成功，Guardian
  Luna 请求 HTTP 503/usage invalid，单 run 本地预算按合同完整结算为 `$5.000000`。后续模型诊断分别闭合
  Luna/Luna 与 Sol/Sol，并最终以冻结 Codex/RONDO 各 Sol main + Sol/low Guardian 连续跑完 3 轮；24 个请求
  零重试，本地价卡估算合计 `$1.234473`。短测只有显式选择时按每 upstream request 预留 1 USD；后续正式
  请求按所选价卡的最大合法 usage envelope 预留，当前 Sol 上界为 18.885000 USD。local profile 当前为 relay +
  Sol main + Sol Guardian/low；main/Guardian 可短暂重叠，后续新 pair 须据此冻结新 cap，但 paid identity/入口当前
  已关闭。实际中转账单未查询且 `actual_usd=null`；
  Plan 014 历史失败 identity 均保持不可复用；最终 v19 canary + 双侧 pair 连同此前保守结算后的本阶段累计
  本地估算为 `$6.988825 < $280`，全部 reservation 已结算，`actual_usd=null`。v19 的真实 evidence 可作为后续
  确定性 seed/holdout 切分输入，但不得直接进入训练集。

## 2. 方向与依赖

方向编号沿用 `README.md` 的「研究方向」：

| 编号 | 方向 | 状态 |
|---|---|---|
| 0 | 量化测评基准（离线回放 + 真实 Terminal-Bench 2.1） | P1/M1 完成；B4/B5/B6 与 B7 设施冻结，执行首次 B7 基线 |
| 1 | Harness 优化（Terminal-Bench 2.1 成功率） | 前置研究可并行，实施被方向 0 阻塞 |
| 2 | 本地审批模型接入与横评 | L1 与 L2 CPU x64 前置完成；已有真实 E_final，GPU/model-backed、L2a/L3/L4 待 P2 |
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
| P0 | 共享地基：审批模型显式覆盖（S1）、审批证据包快照（S2） | 单线，一次做完 | 无 | 无 | 已合并，定向验收完成；全量失败另列维护 |
| P1 | 方向 0：Terminal-Bench 2.1 最小真实链路跑通（E-B1~B3） | 与 L1、L2（仅搭建）、T 轨并行 | P0 | Docker 使用；小额真实 API | 已完成：B1/B2/B3、L1、L2 前置与 M1 均闭合 |
| P2 | 方向 0：离线冻结回放（E-A）+ TB 分层任务集与首次基线（E-B4~B7） | 与 L2（验收）、L2a、L3、L4 并行 | P1 | canary 批量跑批预算 | B4/B5/B6 完成；v1—v16 只读，v17 冻结待执行 |
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

P0 已完成定向门禁并合入主线；B2 合同见
`plan/009-p1-b2-lightweight-slimming-and-v5-execplan.md`。配置化 provider 与未计费 retry 见 Plan 013；
已完成的 paid pair/M1 合同见 `plan/014-p1-configured-provider-paid-pair-execplan.md`。共享 eval 合同、
B1 与 L1 保持可用。
B2 删除 no-API permanent ledger/retirement/summary recovery、一次性 migration 和 Harbor 全依赖闭包，
保留一个当前冻结输入、一个 supervisor Docker receipt 和一个 RONDO→Codex 串行入口。adapter 仍要求
UID/GID 1000、精确 `/app/personal-site` Git probe、custom seccomp、`cap_drop=ALL`、资源阈值和清理成功；
marker 只接受成功的结构化 `exec_command` 结果。双侧已在真实 Docker 中以同一 pinned
image 和同一运行合同完成 no-API 链路，current receipt 与看门狗 summary 保留在项目本地数据目录。
B3 使用 Plan 014 v19 的 source-bound Sol/Sol profile 与唯一 identity 完成。RONDO 和 frozen Codex 在同一
`fix-git` task/image 上分别 `completed`/reward 1，全部 35 个 upstream request 均 attempt 1、usage valid，双侧
预算 run 未停止且 reservation 为 0。RONDO 的两份 Sol/low Guardian `E_final/meta` 均自然 approved，S2 request/
evidence 在 v19 旧合同下为 task-scoped count match；两侧 public result、pair lock、sequence ledger、container metrics 和 profile/endpoint
hash 经既有 `assess_m1` 聚合为 `m1=passed`、`reasons=[]`。v19 正式费用 `$0.870787`，Plan 014 全阶段累计本地估算
`$6.988825 < $280`，供应商实际账单未知。历史失败 identity 及其 ledger/result/artifact 保持原终态，不回填。
运行后离线修复已使后续 completed/M1 强制消费未停止且完全 usage-priced 的预算终态、精确 request IDs 和 canonical
Guardian evidence digest；v8—v19 统一为只读历史 registry，v19 不再可由 paid CLI/canary 重跑。预算 overage 记录完整
估价并停止，Docker lease/cleanup 与 proxy deadline/claim 生命周期缺口也已闭合。完整 eval 349/349、lock 85 packages
通过；本批未调用 API、Docker 或 Cargo。
L2 的 CPU x64 前端/运行闭包前置与首批真实 E_final 输入现已具备；GPU/model-backed 实模验收、L2a/L3/L4 留在 P2。
Plan 015 已冻结 10/61/18 taskset、10-task exact image catalog与机械计分。v10 按原 161-slot/600 USD 合同
在全局 provider-integrity 熔断后只读退役，累计 debit 为 `343.896195 USD`。后继合同使用 321 个机械派生 slot、
700 USD 累计硬上限，并在同题同类第二次 infra 后暂停做结构化 RCA；只有外部瞬态才可继续，第三次同类停止该题。
campaign-independent Oracle、单 slot heavy lock、轻量 lease、安全恢复和 identity 生成入口保持复用。执行细节见 Plan 015。

P0 遗留的能力边界，进入后续阶段前必须记住：**S1 只覆盖审批模型名与 effort，不覆盖 provider**。
Guardian 仍克隆父会话的 provider 与 base_url，因此切换到本地审批模型需要独立的 provider 覆盖，
已拆为方向 2 的 **L2a**，是 L7 的前置。任何"P0 完成即可一键切换本地模型"的表述都不成立。
这一边界与 `v0.147.0` 的 provider 默认模型分流不矛盾：默认模型可随 provider/auth 变化，
但 Guardian 请求仍没有因此切到另一个 provider 或 base_url。

## 6. 授权门

以下动作必须在执行前单独取得授权，不随普通开发一起进行。Plan 008 已获得的
Docker/最多四个 run/总计 20 USD 授权只对该计划有效，不自动扩展到后续批次：

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
- 探针只放少量关键节点，内存累积、轮末统一输出。跨侧对比必须使用同口径的外部指标；runner-host
  `getrusage` 仍只是设施开销诊断。supervisor 已增加 exact container cgroup v2 CPU 与峰值内存采集，
  paid publication/pair/M1 要求该机器证据；v4 只走到 RONDO 失败路径，Plan 009 已以轻量
  current receipt 完成双侧 no-API 重验；该证据不代替付费批次。Plan 014 v19 已提供双侧 paid container
  metrics、durable publication 与 M1 联合通过证据；历史失败 identity 仍不可重试。
  完整探针和细粒度 Guardian 归因仍留给 A4/B5（详见 `doc/WBS/eval-benchmark.md`）。
- 原始 codex 与 RONDO 的对比测评统一关闭 websocket（provider 侧
  `ModelProviderInfo.supports_websockets = false`，见 `codex-rs/model-provider-info/src/lib.rs`）。

## 8. 子规划索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：量化测评基准
- `doc/WBS/local-approval-model.md` —— 方向 2：本地审批模型接入与横评
- `doc/WBS/teacher-harness-study.md` —— 方向 1 前置：教师 harness 只读研究
- `doc/eval-data-layout.md` —— 测评结果与数据资产的保存规范（目录、命名、结果库、保留与 git 边界）
