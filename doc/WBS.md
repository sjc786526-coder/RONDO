# RONDO 长程规划（WBS）

最后更新：2026-08-22（Plan 052 已完成；方向 1 下一唯一工作包为 10 题 × 2 轮 RONDO Local 有界观测复测）

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段级状态、下一工作包、
跨方向顺序、依赖和授权门；方向内部的任务分解见子 WBS。已完成成果与详细证据见
`doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，研究与审计只作为形成时点的证据。

## 1. 当前阶段

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。
后续上游基线升级已经列为待办，但目标版本只在任务启动时按当时的目标稳定版本冻结，不预写为当前已发布版本。

项目由两条并列产品线组成：**RONDO Local**（`mydev/`，承载方向 1、2）与
**RONDO Multi**（`multidev/`，产品基线已完成并合入 `main`，承载方向 3）。两者地位相同，结构见 §4。

| 范围 | 当前结论 |
|---|---|
| P0 共享地基 | S1 审批模型覆盖与 S2 `E_final` 证据捕获已完成，开关默认关闭。S1 只覆盖模型与 effort，不覆盖 provider。 |
| 测试基线 | Plan 004 完成对旧 81 项失败的分批整改后，最近一次有记录的 `v0.147.0` RONDO 全 workspace 实际执行 14,092 项：14,060 通过、31 失败、1 超时，Nextest 另列 23 项 ignored；P0 仍以定向验收收口。此后未重跑全 workspace，不能把该历史快照表述为当前全绿或当前失败复现。 |
| P1 / M1 | B1、B2、B3 与 M1 已完成；冻结 Codex 与 RONDO 已在同一 TB 2.1 任务上完成真实端到端并归档。 |
| P2 / 方向 0 | B4—B7、E-B8 公平比较设施与 Plan 051 首次 schema v7 正式 canary 均已完成。v28 在冻结 Local `54f62e5...` / Codex `be6e8eac...`、Terra main-medium / Guardian-low 下得到 10/10 共同有效任务、双方各 5/10、`sigma=0`、`delta=0`，三层机械判据通过。稳定入口支持后续显式新 Local/bundle、campaign、价格与独立授权预算；passed/failed 自动且可恢复地收口并输出相对上一兼容正式基线的派生比较，blocked 保留给 successor；Plan 051 envelope 不会被复用。Plan 052 已决定当前不恢复 E-A（A1—A7）或其最小子集。 |
| v22 结论 | 机械一致性子门得到 `sigma=0`、`delta=3`，以 `ab_delta_exceeds_aa_sigma` failed；但 A/B 存在 catalog prompt 161-token 非对称、harness/deadline 混杂和非交错执行，因此**不能据此归因 RONDO 与 Codex 的能力或性能差异**。报告分歧已全部关闭。 |
| 结果数据 | P2 v2—v22 公共账本已有 244 条 `track=tb` 唯一 run；Plan 051 的 v28 新增 40 条、1 份 schema v7 aggregate 与 1 份 `first_formal_baseline` 派生比较，`track=tb` 现为 284 条。方向 2 另有 4 条 `track=shadow`，总账本为 288 条。v23—v27 的设施诊断 identity 保留在 ignored 运行资产，不伪装成产品基线。 |
| 方向 1 | 教师 harness 研究 T1—T3 与 Plan 052 聚合观测/首轮普查已完成。当前实际样本中 C2（2/24 可读 run）比 C1（1/24）更常见，但两者都缺少足够影响证据，不能据此回答“最值得处理”；C11 当前样本未观察到，C7 不可测。schema-v2 任务投影已补齐失败响应的 partial-usage、分表面 render 覆盖、精确重复调用 lifecycle 时长和真实 turn 时长。因此未选行为优化，下一唯一工作包仍是 10 题 × 2 轮 Local 有界观测复测。 |
| 方向 2 | **Local M4 已完成**：130 条 synthetic 主体与 16 条真实 holdout 锚点分开盲评、解盲与聚合，人判结论为**保留为实验**。微调侧在教师/裁判一致率、误拦、理由弱项和未被偏好数上均有明显改善（synthetic 教师一致 104/130 → 130/130、误拦 26 → 0；holdout 合规判定 14/16 → 16/16、误拦 6 → 1）；漏放两分区均维持 0，synthetic 结构化可用性两侧同为 130/130，`sole_preferred` 因一致度提高由 5 降为 0，并非全部指标单调改善；但 synthetic 增益很大程度来自同生成器的措辞线索，holdout 教师标签全为 allow，因此尚不能证明模型“安全地放行”。结论只记录，未改生产默认、provider、launcher 或部署。 |
| 方向 3 | 独立产品源码 **RONDO Multi**，不是 Local 内的可插拔模式。第一期、第二期 A/B/C 与 Plan 050 明确委派案例均已完成并通过独立验收；当前无已排期新包。 |

当前不再维护 v6—v22 的逐轮过程、请求数和费用流水；这些历史只保留在
`doc/WBS-COMPLETED.md`、对应 plan、agent log 与冻结结果中。

## 2. 下一工作包与顺序

工作包 1、工作包 2（Plan 022）、RONDO Multi 第二期 A/B/C、Plan 051 与 Plan 052 均已完成。当前唯一已排期
工作包是**方向 1 RONDO Local 10 题 × 2 轮有界观测复测**；E-A 当前仍不恢复，上游基线升级保留为不排期待办。

### 当前工作包：方向 1 RONDO Local 有界观测复测

- **状态**：Plan 052 已完成且没有选定行为优化；本包待建立独立 ExecPlan、冻结新运行身份并取得真实 API/Docker
  授权，本页参数不得在结果出来后改写。
- **范围**：同一冻结 10 题 canary，只运行 RONDO Local 2 个完整 round，共 20 个任务运行；main 固定
  `gpt-5.6-terra/medium`，Guardian 固定 `gpt-5.6-terra/low`，费用硬上限 20 USD。不运行 Codex 对照、
  validation、holdout、条件补题或 E-A。
- **唯一变量与预期**：只对这些 Local 测量请求开启既有 rollout trace，并在结果发布前用 API metadata 做严格的
  schema-v2 body-free 离线投影；不改变 prompt、输出、预算、compact、重试、Guardian、调度或其他产品行为。预期改善的是
  C1/C2/C11 的任务级覆盖和影响归因精度，不预先承诺成功率或耗时收益；C7 仍诚实保持不可测。
- **停止条件**：第一轮任一安全投影缺失，trace 完整性终态非零，trace/API population、终态、分角色 usage 覆盖或
  已知 usage 合计不一致，
  schema/body-free 校验失败或资源门失败即停止，不启动第二轮；
  任一新预算预留会使累计达到 20 USD 时停止；两轮完成后无条件停止，不事后加题、补轮或改分母。
- **有效/无效/回滚判据**：20/20 个预定 run 都产生唯一、完整、严格可校验的安全投影，才是有效测量；任一 run
  不满足即整包无效并停止，不把缺失计为 0。失败/取消 inference 缺 usage 可形成有效 observation，但 usage 必须
  标为不可测并保留类型化 C11 终态；completed response 缺 usage 仍失败关闭。若观测 opt-in 导致任务执行或发布链出现新的 infra 失败，则关闭该
  opt-in、保留产品默认并回到设施修复，不以残缺数据选候选。复测后，C1/C2 只有在两轮均出现、跨至少 2 个任务且
  对应表面的 render 覆盖足以支持 model-visible omission/truncation，或 schema-v2 的重复调用 lifecycle 时长形成
  实际负担时才可入选；partial/unmeasurable 覆盖不按 0 解释。C11 若出现类型化 request/context
  终态失败并影响任务，可按严重性入选。若无人满足，只保留“无候选”。多项满足时按任务覆盖、失败/耗时影响、行为
  风险依次只选一个；该候选的后续 ExecPlan 再冻结单一行为变量，并以主指标下降且不丢失原通过任务为有效，主指标
  恶化或丢失任一原通过任务即回滚。
- **实际证据来源**：判断来自 v28 冻结 schema-v7 campaign 的 10 个真实 canary、每题 3 次 Local 运行，而不是教师
  实现。30/30 API metadata（311 请求）和 24/30 exec JSONL 的选择、覆盖、四态结论与局限见日期冻结快照；6 个集中
  在 2 个任务的脱敏缺口不计为 0。结束后只选择一个证据支持的优化候选，或明确保留无优化结论。Plan 052 历史合同见
  `plan/052-direction1-local-harness-bottleneck-census-execplan.md`，首轮证据见
  `doc/audit-snapshots/2026-08-22-rondo-local-harness-bottleneck-census.md`。

### 最新收口：Multi 明确委派三任务比较案例

- **3a 测评设施**：按需要继续维护，但不恢复已挂起的 E-A。
- **3b RONDO Local**：**exact-token 普查（WP3b-A2）已完成并闭合**。
  **provider-neutral static-payload 兼容（WP3b-A2a/A2c）已完成**：static input payload 现为 v3，
  reasoning 投影与证据角色规范化统一落在公共 builder，raw content、encrypted 内容与 provider session id
  一律不出站，证据消息只以 `user`/`assistant` 出站且文本、顺序与消息边界不变；结构化决策输出 schema
  仍是 `rondo_static_approval_v1`。
  **47/47 普查（WP3b-A2e）已通过**：v3 锚点常量从 pre-v3 的 5,313 窄改为实测 5,311 后，同一正式入口
  从头独立跑两遍完整 count-only 普查，两遍均 `complete`、47/47 counted、0 refused、锚点精确 5,311、
  `generated_tokens=0`、三项 cleanup 全 true，逐条记录/摘要/digest 逐字节一致，
  唯一正式 baseline 已发布。全集分布 min 5,311 / p50 8,989 / p90 12,352 / p95 13,754 / max 22,499；
  按 `input+512`，4k 适配 0/47、8k 适配 11/47、12k（12,288）适配 42/47。
  **12k model-backed qualification 已通过（WP3b-A3）**：真实 `E_final`（5,311 tokens）在冻结 b10333 CUDA
  runtime、唯一 GGUF 与 12,288 / 512 合同下返回合规 `rondo_static_approval_v1` 判定，
  实际 `n_ctx=12288`、单 slot、GPU offload 33/35 层、峰值显存 7,855,931,392 B、TTFT 3,183 ms、
  总耗时 7,049 ms，现场四项清理全 true。capability 已晋级为 `gpu_model_serving_validated`，
  并由无资格特权的正式 launcher + 存活期 doctor 独立复验（`ready` / `model_schema_probe_passed`）。
  这只证明 12k 档位内的真实服务可用，**不代表剩余 5 条超窗证据可服务**。
  **L7 已通过独立验收（WP3b-A4），Local M3 随之收口**：正式 Guardian 直连冻结 b10333 存在三处不匹配
  （不映射 `text.format`、tools 与 grammar 并存即抛错、`developer` 角色经 `map_developer_role_to_system`
  触碰模板顺序限制），且通用 provider 路径不消费 launcher receipt。Plan 031 采用 eval-side
  身份门控适配器一次性关闭四点：`mydev/` Rust 源码未改，入站请求由公共 `build_static_payload()`
  归一化，响应完整缓冲并在身份后验通过前不交付，判定按 Guardian 自己送来的 schema 校验。
  真实 `--approve-for-me` 链在本地 12k 上取得合规 allow 并执行待审批动作；服务异常、身份漂移与
  请求契约不符三类都不执行动作、不伪装成业务 deny、不回退主 provider。
  **L3/L4 已完成（WP3b-A6）**：冻结教师批次经严格导入后，在同一已资格化 12k 服务上一次生命周期完成
  40 条 canonical static payload v3 回放，40/40 进入唯一终态（allow 16、deny 19、结构化输出失败 5，
  超时 0、基础设施失败 0、重试 0）。L4 指标口径在真实运行前冻结为 `rondo_l4_local_static_v1`
  并随 tracked 模板提交；未微调 baseline 与四条 shadow 记录（seed/holdout × imported/auto）已发布。
  教师一致率只在 35 条合规判定间计算（16/35；seed 9/21、holdout 7/14），有效判定覆盖 87.5%，
  峰值显存 8,048,869,376 B。**该批教师标签全部为 `allow`**，因此本轮一致率暂不构成有区分度的质量信号，
  只作为固定对照起点。
  **L5b 已完成（WP3b-A7）**：当前人在场 `gpt-5.6-sol` 只参考 seed 24 条，生成并冻结 600 条合成样本；
  六类与 allow/deny 均有覆盖，train/validation 按 120 个近重复组互斥，holdout 16 条只在本地内存中过滤且
  聚合命中 0。正文约 1.67 MB，随 prompt/schema、manifest 和数据卡进入 `training/`；私有 seed 投影、候选与
  逐条过滤明细留在 ignored `eval-data/`。
  **Local M4 输入已就绪（WP3b-A8—A10）**：全部 130 条 validation 已冻结为 body-free 65 / 65 两批；
  三方完整导入、L6 成对归因、匿名位置平衡、裁判 prompt/schema、私有解盲聚合及独立 holdout 批次摘要合同
  已就绪。Plan 037 已完成 470 条 train-only 训练、paired-GGUF 转换、两侧 130 条串行输出和 canonical
  pair receipt/private evidence；390 行正式导入为 `ready_for_blind_packaging`。
  **Local M4 已收口（Plan 041）**：synthetic 130 条与真实 holdout 16 条分区独立完成盲评、解盲与聚合，
  人判结论为**保留为实验**。方向 2 因此没有已排期的下一工作包；若将来要投入真实使用，必须先按本页
  §6 单独立项，建立面向生产的正确性与安全验收，并解决“合成集线索化”与“holdout 单侧标签”两项证据缺口。
  结论详情见 `doc/WBS/local-approval-model.md`。
- **3c RONDO Multi**：第一期已完成、归档并合入 `main`；第二期当前状态如下：
  - **包 A — Team State 序列性质测试：已完成。** 现有 crate 内已有默认 ignored、固定 seed、有限规模的性质测试与
    主动入口；它覆盖 publish、双生命周期、route、delivery、retry 与 wake，没有改变产品语义。
  - **包 B — Team Lens：已完成。** 同一离线消费者可读取冻结 Codex 与 RONDO 原生 trace，确定性输出 body-free
    `team_view.json`，再单向生成离线单文件 `team_report.html`；代表性证据支持保持零 runtime hook。
  - **后置包 C — 主动委派收益对比：阶段 A/B 已完成。** Root/Guardian 多 bundle 已通过共同 selector 和只读
    recovery identity 关闭，旧首槽没有重放。固定六个 pilot 全部有效且 trace 可用，2 个成功、4 个有效任务失败、
    累计 `2.533684 USD`；两侧 Root 均未主动委派，因此 activation 阴性并按冻结合同未运行正式十题。
  - **包 D — 明确委派三任务比较案例：已完成并通过修复后独立复验。** 三题六个有效槽位为 4 次通过、
    2 次有效任务失败；C01/C02 两侧均通过，C03 两侧均失败。C01 RONDO 的 completed member-to-Root
    `send_message` 现与 `agent_result` 同属 typed contribution return，且仍须另有实质成员活动；重归约后共有 2 个
    `collaboration_observed`、4 个 `policy_noncompliance`，影响链仍为 1 `observed`、5 `not_observed`。

包 D 的代码、回归、既有资产重归约与独立复验均已完成；任务目标、题目选择与判读边界见 Multi 子 WBS，完成证据见
WBS-COMPLETED。Multi 与本地审批模型方向当前都没有已排期下一包；Local 方向 1 的 Plan 052 已收口并只交接
有界观测复测，本包不恢复候选行为优化或本地审批模型开发。

### 已确认待办（不排期）

- **上游 Codex 基线升级**：作为横跨 `mydev/` 与 `multidev/` 的独立任务保留，不排期、不写死目标版本。
  启动时再冻结当时采用的上游版本与 commit，审查上游差异并分别合入两套产品，更新机器事实、构建身份与受影响测试；
  不混入普通功能任务。Plan 051 已冻结 v0.147.0，不受该未排期升级影响；未来升级只影响升级后的新 campaign。

### 挂起项（不排期）

- **E-A 轻量离线冻结回放（A1—A7）当前不恢复。** Plan 052 证明现有资产、原生 trace/API metadata 的安全
  task-level 投影与一次有界真实复测
  足以承接下一步；只有未来已选定机制确需反复低成本实验时才重新评估单独的最小 replay 能力。日常回归仍由
  **测试体系**保证正确性。

## 3. 方向与依赖

| 编号 | 方向 | 产品线 | 状态 | 解锁条件 |
|---|---|---|---|---|
| 0 | 量化测评基准 | Local | Plan 051 已完成首次正式 v7 十题基线与稳定重跑入口 | 当前无方向 0 新包；Plan 052 已决定不恢复 E-A |
| 1 | Harness 优化 | Local | **Plan 052 已完成，首轮证据不足以选优化项** | 当前只执行 10 题 × 2 轮 Local 有界观测复测；须另获真实 API/Docker 授权 |
| 2 | 本地审批模型接入与横评 | Local | **Local M4 已收口，结论为保留为实验** | 无下一工作包；生产启用须另行立项 |
| 3 | Event 驱动的团队世界状态多智能体协作 | Multi | 第一、二期与 Plan 050 明确委派案例均已完成并通过独立验收 | 当前无已排期新包 |

- **Local 与 Multi 地位相同**。Local 已完成 Plan 051/052，方向 1 当前进入有界观测复测；Multi 第一、二期及明确委派三任务案例均已完成。
  工程任务可以并行，重型任务仍因资源约束全局串行。
- 方向 0 与方向 2 共用 P0。方向 3 不再排在方向 1 之后；Plan 052 也不阻塞任何其他方向。
- Multi 新包只研究明确委派条件下的协作过程与外部结果；方向 0 面向 `mydev/` 的内核/行为优化基线。二者只共享排期、
  API 预算与 Docker/构建资源串行关系，结果不能互相替代。
- 方向 2 的真实 `E_final` 必须按稳定语义哈希切成互斥 `seed` / `holdout`，真实证据本身不得进入训练集。

## 4. 仓库与产品线结构

### 4.1 布局

单仓库、单长期 `main`、两套并列源码：

```text
RONDO/
├── mydev/        # RONDO Local（沿用现名，不改名）
├── multidev/     # RONDO Multi（工作包 2 产品基线已完成）
├── eval/         # 两条产品线共享的通用测评设施
├── scripts/      # 共享构建锁与看门狗入口（已由 mydev/scripts/ 迁出，见 §4.4）
├── eval-data/    # 内部按产品分命名空间，不顶层并列
├── test-data/    # 内部按产品分子目录
├── doc/
└── plan/
```

### 4.2 分支与任务隔离

- 不为 Multi 建立需要长期同步的永久产品分支；Local、Multi、公共文档和共享设施统一进入 `main`。
- 目录并列负责产品源码隔离；每个具体开发任务仍使用短期 worktree/任务分支。
- Local 任务只修改 `mydev/` 及必要共享文件；Multi 任务只修改 `multidev/` 及必要共享文件。
- `eval/`、WBS 和其他共享权威文件尽量（不强制）同一时段只由一个任务负责。
- 公共安全修复、provider/API 适配和构建修复按需选择性同步，**不追求两套核心长期提交级一致**。

### 4.3 磁盘预算：显式设计约束

- 项目容量看门狗量的是整个项目根 `du -sx`，阈值 180/195/200 GB；两套 workspace 的 target 自动计入同一预算，
  这是设计意图，门禁不改。
- 实测参考：一次全 workspace 冷构建 + 全量测试的 target 峰值约 126 GB；`eval-data/` 当前约 21 GB。
- 运行规则：**同一时刻只允许一个产品的 target 目录处于热状态**；切换产品线做重型任务前先清理另一侧。
- `.cargo/config.toml` 在仓库根，cargo 逐级向上合并，`multidev/` 自动继承 `jobs=6` 与 rustc-throttle。

### 4.4 共享外围设施

两条产品线不要求共用核心代码，但应尽量共享：构建锁与资源看门狗、Docker 与 Terminal Bench 任务执行、
API 预算与结算、BinaryManifest 与结果归档、本地模型 launcher/doctor/runtime、fake/loopback/replay 无 API 测试，
以及能接收不同二进制与产品 variant 的通用测试与测评入口。

**看门狗**：`with-build-lock.sh` 与 `build-watchdog-lib.sh` 位于仓库根 `scripts/`，逻辑、阈值与退出语义
与迁移前一致，两条产品线共用，**没有 shim 或兼容软链**。现行引用点全部使用根路径；
`eval/locks/*.json`、`agent_log/` 与 `doc/audit-snapshots/` 里的旧路径是冻结 provenance，不改写。

### 4.5 产品身份

- **产品身份与比较侧是正交的两个维度**：`product`（`rondo-local` / `rondo-multi`）说的是哪个 RONDO 产品，
  `side`（`rondo` / `codex`）说的是 RONDO 侧还是冻结上游侧。`codex` 不是产品取值。
- **历史结果只加不改**：既有 244 条 run 中 224 条 `side=rondo` 解释为 RONDO Local，20 条 `side=codex`
  是上游侧、不适用产品身份；一律不改名、不回填。
- Multi 必须显式带 `multi` 字样（`eval-data/bin/rondo-multi/`），产品身份贯通 binary freeze、
  源码/构建路径、manifest 与结果归档，不能只参数化一个 `bin/rondo/` 路径。
  唯一映射是 `eval/rondo_eval/contracts.py` 的 `product_layout()`；任一层缺失或矛盾都 fail-closed。
- **Multi 的产品基线是行为定义的**：`[auto_review]` 的 `model`、`model_provider`、`reasoning_effort`、
  `evidence_dir` 四项默认未配置，eval 也不为 Multi 注入它们，结果工件用版本化 `auto_review_config`
  记录该状态。Local 的既有公平运行合同不变。
- crate 名与二进制名沿用上游（`codex-cli` / `codex`），**不重命名**，保持与 `codex-source-code/` 可直接 diff。
- 数据目录不顶层并列，只在产品特定层级加命名空间；具体规则见 `doc/eval-data-layout.md`。

## 5. 阶段与里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | S1 审批模型显式覆盖、S2 审批证据快照 | 已完成 |
| P1 | B1—B3 最小真实链路；L1/L2 model-free 前置 | 已完成，M1 通过 |
| P2 | 公平比较设施闭合、B4—B7、L2a/L7 + 12k model-backed（收口 Local M3）、L5a 教师标签与 L3/L4 未微调 baseline | 已完成 |
| P3 | L5b 合成训练数据、L6 微调，收口为 Local M4 | 已完成：Local M4 人判结论为保留为实验 |
| P4 | harness 优化迭代 | Plan 052 已完成；当前只排期 10 题 × 2 轮 Local 有界观测复测，尚未进入候选实现 |
| P5 | RONDO Multi 产品线 | 第一、二期与明确委派三任务案例均已完成并通过独立验收；当前无已排期新包 |

| 里程碑 | 验收口径 | 性质 | 状态 |
|---|---|---|---|
| M0 | Guardian 模型/effort 显式生效并落盘规范化 `E_final` | 工程验收 | 已完成 |
| M1 | 冻结 Codex 与 RONDO 同一 TB 2.1 任务端到端可归档 | 工程验收 | 已完成 |
| Local M3 | 12k model-backed、结构化输出、真实 `E_final`、fail-closed 与配置切换形成真实本地审批闭环 | 工程验收 | 已完成 |
| Local M4 | 同一批冻结样本上正式比较 Sol / 未微调 Local / 微调后 Local，由人作采用/保留/停止决定 | 人判定 | 已完成（2026-08-16）：synthetic 130 与 holdout 16 分区盲评并解盲，人判为保留为实验 |
| Multi 二期 A | Team State 序列性质测试：在现有 Rust 测试体系内探索跨功能状态组合 | 测试 | 已完成（Plan 047） |
| Multi 二期 B | Team Lens：复用原生 rollout trace 的离线团队行为抽取与静态报告 | 工程/观测 | 已完成（Plan 048，零 hook） |
| Multi 二期 C | 相同 proactive policy 下，冻结 Codex 与 RONDO 的主动委派与收益对比 | 测评 | 已完成（Plan 049）：六个 pilot 均无 Root 主动委派，activation 阴性，正式十题不适用 |
| Multi 明确委派案例 | 同一明确 collaboration policy 下的三任务跨产品比较与 Team Lens 展示 | 案例研究/产品展示 | 已完成并通过修复后独立复验（Plan 050） |
| 方向 0 首次 v7 正式 canary | 10 个 canary 的 Local/冻结 Codex 公平基线；条件加跑，不扩到 validation/holdout | 测评 | 已完成（Plan 051）：v28 共同有效 10/10，双方 5/10，`sigma=0`、`delta=0`，三层通过 |
| 共享上游基线升级 | 选择任务启动时的目标上游版本，审查差异并同步两套产品与机器事实 | 工程 | 已确认待办，不排期；目标版本不预写死 |

**M2 与 M5 已退役**，历史文档中的这两个名字不再对应当前任何门禁：M2 的“测评设施就绪”部分成为工作包 1
（设施交付物，非里程碑），旧“方向 1 解锁”与 M5 均不再作为门禁；Plan 052 的重启不复活这些旧里程碑。
工作包 1 已闭合；后续 Multi 付费测评只保留具体运行时的合同冻结与真实 API 授权门。

### 公平比较设施保留的机械判据

公平比较设施在自身范围内保留三个**分别报告**的机械子门，不引入统计显著性框架，也不使用
pairwise-max `σ` 等事后放宽办法：

1. **A/A 行为一致性**：用同一二进制的预冻结重复观测形成不一致预算 `σ`；`σ` 是经验观测，不是统计估计。
2. **A/B 对称比较**：两侧在完全相同的 task-independent 合同下运行，跨侧差异 `delta ≤ σ`；
   `delta` 使用条件加跑聚合后的每题 outcome，不是基础轮的原始差异。
3. **重复与方向性兜底**：对一侧 pass、另一侧 fail 的任务（**两个方向都算**）使用预冻结重复并计入聚合；
   其中若 RONDO 全败而上游全过，则另由方向性子门判为不通过。
4. **infra**：基础设施失败不计能力分，只按同题运行链定点补跑；每轮后最终 infra 超过 2 项即 blocked；
   共同有效集合至少 8 项。
5. **预算**：基础运行、预冻结重复、infra attempts 与 wire canary 全部计入预先授权的预算上限。Plan 051 的
   v23 与全部 successor 共用同一个 `400 USD` 任务累计，换 identity 不能清零。

这套判据**只适用于该设施自身的等条件 A/A、A/B 比较**。Local M3、Local M4 与已完成的 Multi 第一期退化验收都
**不继承** `σ`/`delta`（理由分别见 `doc/WBS/local-approval-model.md` 与
`doc/WBS/multi-agent-trusted-evidence.md`）。

v22 使用“两轮 RONDO A/A + 两侧各一轮 A/B + 条件两侧各加跑两轮”的历史公式；它的机械结果保持不改写，
但不作为新 campaign 的默认重复合同。新 campaign（schema v7）必须在 lock 中预冻结差异题的重复数与聚合公式：
被跨侧差异触发的题每侧总观测数为奇数且不少于 3（基础 A/B 轮算其中一次），聚合固定为严格多数；
未触发题保持基础单次 A/B 观测。
若 catalog、请求冻结分区、harness、deadline、顺序、重复或聚合规则不对称，设施直接 blocked、不计算能力归因；
若 `σ` 接近任务总数，应回到 B4 重选 canary，而不是放宽判据。

## 6. 授权门

以下动作每次执行前都需单独授权，历史授权不自动延续：

- Docker 拉取、构建或运行。
- 按量付费真实 API 批量测评：须冻结任务范围、轮数、模型和预算上限。
- 真实本地模型加载或推理。
- 任何真实数据外发，包括把本项目自造的合成训练数据上传到云端。
- 云 GPU 训练、上传或下载权重、产生外部费用或状态变更。
- 上游基线升级。

Plan 051 已取得其 execplan 明列范围内的一次性构建、Docker、真实 API 与最多 `400 USD` 任务累计授权；
同一任务内按合同创建 successor 或恢复运行不构成新的批次授权。合并 `main` 与推送仍等待用户另行批准。

**订阅制入口不计入 API 预算门**：Sol 经开发用 Codex 生成教师标签、Opus 5 经 Claude Code 担任横评裁判，
二者不额外计费，因此不受 API 预算授权门约束，只受订阅速率与配额限制。相应地它们带两条限制：
模型版本不由本项目冻结，必须记录**生成/判定时点的模型标识与日期**；且只用于人在场、发送预写冻结 prompt 的
会话内工作，**不得**作为程序化批量后端接进 `eval/` —— `eval/` 只导入其冻结产物。
也不为这些角色另开按量付费 API 入口。数据外发门与订阅与否无关，仍然适用。

## 7. 测试与测评原则

- 测试验证代码与设施正确性，复用上游 Rust/Nextest 等体系，只补受影响模块的必要回归。
  **E-A 当前不恢复，日常回归仍由测试体系承担**（单测、fake/loopback/replay），不借测评设施兜底；只有未来已选定
  机制确需反复低成本实验时才重新评估最小 replay 能力。
- 测评提供性能指标，默认关闭、轻量、自动记录归档；离线、fake、真实 API、真实模型和 Docker 证据严格区分。
- 现有测评设施保留。修复公平性、任务与 prompt 对称性、二进制/结果身份和运行时混杂后，
  主要用于关键阶段不退化检查、产品变体对比和最终验收，不再承担高频回归。
- 冻结 Codex 与 RONDO 的公平横比只使用同口径外部指标；内部探针只用于自身版本间诊断。
- skip、未运行和无效比较不能表述为通过；测评设施合同不满足时不得解释产品能力。
- 结果与数据资产边界遵循 `doc/eval-data-layout.md`。

## 8. 子规划索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：量化测评基准
- `doc/WBS/local-approval-model.md` —— 方向 2：RONDO Local 本地审批模型接入与横评
- `doc/WBS/teacher-harness-study.md` —— 方向 1：教师研究、Plan 052 普查与后续单候选决策
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：RONDO Multi 产品语义合同与第二期路线
