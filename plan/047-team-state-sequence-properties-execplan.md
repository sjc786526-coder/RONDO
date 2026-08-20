# Plan 047：Team State 序列性质测试 ExecPlan

> 本计划是任务 A 的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在本地 `main @ 7ba7eb65e1105f608730fc716eb4e5958b94af3d` 的 RONDO Multi
`codex-team-state` 既有测试体系内，增加一项默认 ignored、可由固定 seed 主动运行的有限序列性质测试。
测试用一个只表达可观察事实的薄 reference state，探索 publish、producer/Root 双生命周期、route、delivery、
retry 与 wake 的跨功能组合，验证这些能力共同作用时仍满足现行产品合同。

这是正确性保障任务，不增加产品能力，不扩展到 Multi runtime 或性能测评。

### 完成/验收标准

- 默认 Team State 门禁通过；序列性质测试参与编译但不会默认执行，Nextest 结果清楚显示它是 ignored/skipped。
- 提供主动入口 `cd multidev && just team-state-sequence-properties`，无需手工拼接底层 Nextest 参数；其默认合同冻结为：
  - `64` 个 case；
  - 每个 case 最多 `32` 个候选步骤，最短可 shrink 到只保留触发问题所需的步骤；
  - 固定默认 seed `20260820047`；同一代码与同一 seed 产生同一候选操作序列；
  - 失败输出包含 seed、shrink 后步骤和足以定位断言的状态摘要，不生成 corpus 或回归文件。
- 指定 seed 的复现语法冻结为 `cd multidev && just team-state-sequence-properties <seed>`；recipe 只主动运行这一项
  ignored property test，不顺带运行其他 ignored 测试或扩大到其他 crate。普通、默认运行的轻量自测或同等检查须证明：
  同一 seed 生成相同的符号候选序列。
- 主动入口能证明其默认批次实际覆盖 publish、producer/Root 双生命周期、route、delivery、retry 和 wake；
  可以由生成器构造、共用 driver 的固定核心场景或同等简洁方案保证，不指定具体实现路线。
- 生成及 shrink 后的引用始终从 reference state 当前仍存在的 canonical 绑定中解析；没有适用对象的候选步骤只记为
  `not_applicable`，不得调用产品 API，也不得改变 reference state、真实 store、revision 或 wake 状态。
- 每个有意义的步骤后比较双方的可观察结果，至少覆盖：
  - success/no-op/deduplicated 等 outcome 类别与关键返回身份；
  - canonical instance、event/version/route 绑定；
  - revision 是否按现行合同推进或保持不变；
  - event、version、route 数量及它们的归属关系；
  - Root 与两个成员各自的权限视图；
  - producer/Root 生命周期独立终态、route/delivery/retry 与 participant-specific wake 的关键不变量。
- invariant checker 有普通、默认运行的自测，至少能拒绝人为构造的 canonical 绑定错误和一种跨状态不一致；
  checker 只服务本测试，不新增产品公开 API。
- 相同 request identity + 相同请求内容的 publish/route retry 不增对象、不增 revision、不产生新 wake，且返回原
  canonical identity；delivery failed 后的重试不回滚 route/assignment，delivered 终态符合现行合同。
- 若性质测试证实 Team State 产品缺陷：先把 shrink 后最小反例写成既有相关测试模块中的普通确定性回归，再做现行合同内
  的窄修并通过回归；没有证实缺陷时不修改产品语义代码。
- `codex-team-state` 格式、定向 lint、默认测试与主动序列性质入口均通过。只运行该 crate 及实际被窄修直接影响模块的
  必要门禁，不运行 workspace 全量测试。
- 工作树最终只有本任务预期变更和 git-ignored 构建/看门狗产物；执行者审查 diff 后提交本地工作树分支，
  不合并、不推送。

## 2. 范围

### 允许修改

#### 冻结写集（任务 A 独占）

- `multidev/codex-rs/team-state/src/` 下本任务新增的序列性质测试模块、现有测试挂载点与必要的测试支持代码。
- `multidev/justfile`：增加唯一的 Team State 序列性质主动入口 `team-state-sequence-properties`；不改无关 recipe。
- 若选择现有依赖无法完成的成熟性质测试库，可按需修改：
  - `multidev/codex-rs/team-state/Cargo.toml`
  - `multidev/codex-rs/Cargo.toml`
  - `multidev/codex-rs/Cargo.lock`
  - `multidev/codex-rs/team-state/BUILD.bazel`
  - `multidev/MODULE.bazel.lock`
  依赖及生成锁必须是完成本测试所需的最小集合；如果不用新直接依赖，则不碰这些文件。
- 本计划 `plan/047-team-state-sequence-properties-execplan.md` 的“当前状态”和“关键决策记录”。
- 一份本任务完成时的精炼 `agent_log/<timestamp>-plan047-team-state-sequence-properties.md`。
- 仅当性质测试已经给出可复现最小反例时，允许窄改 `multidev/codex-rs/team-state/src/` 下对应产品实现和既有相关
  确定性测试文件。

#### 写集冻结规则

- 并行任务 B（`.claude/worktrees/048-team-lens`）已存在于任务编排中。A 执行者不得切换、清理、stash、覆盖、提交、依赖或
  纳入 B 的未提交工作成果；B 首批也不应修改上述 Team State/Rust 依赖/主动测试入口写集。
- 如实现中发现确需修改写集外的共享文件，先把该项留给最终整合批次；只有不修改就无法完成 A 且不是 WBS/完成历史等
  共享规划文件时，才暂停并请求用户决定。

### 不允许修改

- `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md`、`README.md`；这些由 A/B
  都验收后的最终整合者统一同步。
- 并行任务 B 的 plan、Team Lens 代码、数据合同、静态报告或日志。
- `mydev/`、`codex-source-code/`、冻结第一期工件、`eval/`、`training/` 与真实结果资产。
- Team State crate 之外的 Multi runtime、原生 rollout trace、mailbox/residency、provider、compaction、Tokio 调度或
  异步工具接缝。
- 除性质测试证实的窄缺陷外，不改 Team State 产品语义；不做顺手重构。
- 不新建 crate、独立 runner、corpus、JSON 归档、fuzz daemon、通用 generator/shrinker 框架或常驻任务。

### 不允许读取/查看

- `.env.local` 的内容，以及任何项目外个人文件、密钥、凭据或私有数据。
- 本任务不需要读取 `codex-source-code/`；若执行者认为上游比较不可缺少，应先说明理由，不把上游升级或修改混入本任务。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部覆盖而违反。

### 3.1 基线、工作树与交付

- 只在 `.claude/worktrees/047-team-state-sequence-properties`、分支
  `worktree-047-team-state-sequence-properties` 中实施，基线固定为 `7ba7eb65e1105f608730fc716eb4e5958b94af3d`。
- 保护主工作区、现存 `046` 工作树及任务 B 工作树的状态；不切分支、不 stash、不回退、不覆盖、不清理来源不明的内容。
- 完成后只提交当前工作树分支。不得合并到 `main`、推送工作树分支、推送 `main` 或重命名完成分支；这些等待用户批准。
- 提交前检查主工作区与所有 worktree 状态、当前 diff、未跟踪文件和意外生成物；只 stage 本任务文件。

### 3.2 性质测试合同

- 固定参与者为一个 Root 与两个成员；参与者注册是可信 fixture，不作为随机身份测试。首版不重复一般无效输入、身份重复
  登记、猜测 foreign identity 等已有单点合同。
- 首版操作集合及相对权重冻结如下。权重是生成分布，不要求具体 Rust enum、索引表或 bootstrap 结构：

  | 操作族 | 候选操作 | 权重 |
  |---|---|---:|
  | publish | 新建 event | 4 |
  | publish | 向当前可见 event append version | 5 |
  | producer lifecycle | 作者关闭自己的 version | 2 |
  | Root lifecycle | Root 设为 tracking 或 resolved | 3 |
  | route | Root assign 给成员 | 3 |
  | route | Root notify 成员 | 1 |
  | delivery | 对现有 route 记录 failed | 2 |
  | delivery | 对 pending/failed route 记录 delivered | 2 |
  | retry | 精确重放已提交的 publish 或 route | 3 |
  | route lifecycle | 目标成员或 Root 结束现有 assignment | 1 |
  | wake | 查询并消费某参与者 pending wake | 2 |

- 生成器必须使用短、有界、确定性的 authored text/reason/note；不以随机长字符串重复已有 clamp/无效输入测试。
- reference state 只记录可观察抽象：参与者、当前 revision、canonical 绑定、对象归属/数量、生命周期、route delivery/duty、
  可见性及 wake 是否 pending。不得复制产品内部算法、读取产品私有字段后再把实际结果冒充期望值，也不得新增第二份
  production-like store。
- 新对象 ID 可以在首次成功 outcome 后绑定，但 reference state 必须独立预测对象是否应新增、归属、ordinal/revision 变化、
  retry 是否命中原对象及各 viewer 可见范围；不能仅做“产品输出与自己的 clone 相等”的循环断言。
- shrink 后的候选引用只允许通过当前 reference 绑定解析；解析不到即按 `not_applicable` 处理。禁止构造已知 stale/foreign/raw
  ID 去调用产品 API；本任务验证状态组合，不重复单点拒绝矩阵。
- `not_applicable` 步骤在双方都必须是纯跳过。driver 应能断言调用前后可观察状态相等，以防“跳过”偷偷消费 wake 或改状态。
- 不启用默认失败持久化，不生成 `proptest-regressions`、seed corpus 或 JSON 轨迹。失败诊断写标准测试输出；最小反例若证实为
  产品 bug，则人工转成普通确定性回归。
- availability/retire 本轮明确后移。只有核心合同已完整、diff 仍小且不会增加另一套 reference 语义时，执行者才可在请求用户
  调整本计划后加入；它不是本计划验收门，不能用它替代任一核心操作族。
- 不纳入 Fact、批量生命周期、真实 mailbox/residency、provider retry、compaction、Tokio 调度、异步工具接缝、Docker、API、
  本地模型或性能测评。

### 3.3 依赖与构建元数据

- 优先复用仓库已经锁定的成熟测试依赖或足够小的 crate-local 方案。选择哪一种由执行者根据实际 diff 与可维护性决定；不得
  为避免一个合理测试依赖而自建通用性质测试框架。
- 如新增/改变 Rust 直接依赖，Cargo manifest、`Cargo.lock` 与 `multidev/MODULE.bazel.lock` 必须按
  `multidev/AGENTS.md` 的既有 Cargo/Bazel 锁同步流程核对，只提交实际产生的最小元数据变化；只有生成规则或 Bazel
  target 确实需要时才改 Team State `BUILD.bazel`。允许下载普通 Rust/Bazel 依赖；不得修改全局工具链或宿主配置。
- 当前环境文档记录本机没有 Bazel。执行者可先采用仓库已有的项目内/临时工具路径或证明生成锁无需变化；不得全局安装或绕过
  锁一致性。如果必需的 Bazel lock 无法可靠生成/核验，应完成其余可验证工作并把这一项作为真实阻塞报告，不能伪造通过。

### 3.4 资源、测试与重试

- 所有重型 Cargo lint/test 必须从任务工作树通过 `multidev/justfile` 已接入的共享
  `scripts/with-build-lock.sh` 运行；不直接运行 `cargo test`，不禁用 build-lock/watchdog，不提高仓库并发上限。
- A/B 可以并行编码，但全项目重型构建同一时间只能有一个。若锁正忙，等待后重试；不得杀掉其他构建或改锁。
- 本轮不授权 Docker、真实 API、本地模型、完整数据集、workspace 全量测试、发布、上传、远端修改或费用。
- 小范围编译错误、测试实现错误、依赖解析问题、暂时锁忙和可恢复的定向测试失败，由执行者在本任务范围内诊断、窄修并重跑；
  不因第一次失败立即停下。可以调整实现细节，但不能改验收语义、弱化断言、删除覆盖或绕过资源门禁。
- 只有下列情况暂停并请求用户：需要重新定义产品语义；需要大范围重构；需要修改任务 B/共享规划写集；需要全局安装、Docker、
  API/模型/费用或其他未授权外部状态；资源门禁持续不满足且无法安全恢复。
- skip、未运行、环境阻塞和产品失败必须分别如实记录，不能写成通过。

## 4. 软性建议

以下内容用于根据当前代码给出执行建议，但不是固定实现路线。执行者可以依据 live code、实际测试与 review 采用更优的同等
简洁方案，并在关键决策记录中说明理由。

- 新测试宜放在 `multidev/codex-rs/team-state/src/` 的独立 `*_tests.rs` 模块，通过现有测试挂载点接入；尽量复用
  `test_support.rs` 的 fixture/helper，但不要为了复用而污染产品公开 API。
- 当前 `proptest 1.9.0` 已作为传递依赖出现在 Cargo lock 中，但尚不是 workspace/team-state 的直接依赖。若使用它能显著
  减少自制生成与 shrink 逻辑，可把它声明为最小 dev-dependency；若一个更小、同样可审查的 crate-local 方案更合适，也可
  自主选择。
- 可让生成步骤携带小整数 selector，在执行当下映射到 reference state 中当前有效的 event/version/route；这样 shrink 后仍
  保持引用有效，也无需预测随机 UUID。具体 bootstrap、映射表和 binding 结构由执行者决定。
- 失败摘要优先输出符号化步骤（参与者槽位、对象槽位、请求槽位），避免整份 store dump。只要能复现与理解，不需要新增审计
  schema、trace 文件或长期数据资产。
- `team-state-sequence-properties` recipe 宜在内部复用仓库已有的 `just test ... --run-ignored only <filter>` 形态，固定默认
  cases/steps/seed，并按硬约束接受一个 seed 参数；正式验收仍以冻结默认值为准。
- 产品缺陷回归放到最贴近该合同的既有 `store_tests.rs`、`store/route_tests.rs`、`handle_tests.rs` 等文件；性质测试保留发现能力，
  普通测试保留永久最小反例。
- 定向验证入口建议包括：
  - 在 `multidev/` 运行 `just fmt` 与 `just fmt-check`；
  - `just clippy -p codex-team-state -- -D warnings`；若实现体量或 lint 结果需要，可先用
    `just fix -p codex-team-state` 做同范围修正；
  - `just test -p codex-team-state --lib`，确认普通测试通过且性质测试 ignored；
  - `just team-state-sequence-properties`，按 `64 / 32 / 20260820047` 合同运行唯一的 ignored property test；必要时再用
    `just team-state-sequence-properties <failure-seed>` 复现失败。
  如果窄修真实产品缺陷，只补跑直接相关 filter/crate，不扩大到 core 或 workspace 全量。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已复核任务合同、共同基线、047 专用工作树及 A/B 冻结写集；实现期间未读取密钥文件、未触碰任务 B 或共享规划写集。
- 已增加默认 ignored 的有限序列性质测试：固定 Root + 两名成员、11 类冻结权重、薄 reference state、动态 canonical
  selector、64 cases / 最多 32 步 / 默认 seed `20260820047`、固定核心覆盖和失败诊断。
- reference 独立预测 revision、event/version/route ordinal 与归属、双生命周期、三方可见/active/route 视图和 participant
  wake；精确 publish/route retry 校验原 canonical identity、当前 route 状态、无 revision/wake 增量。
- 已增加两项默认 invariant checker 自测及同 seed 符号候选确定性自测；`not_applicable` 在不调用产品 API 的同时核对
  reference 与完整公开观察保持不变。
- 已增加唯一主动 `just` 入口，并以最小 `proptest 1.9.0` std-only dev-dependency 复用既有锁定依赖。
- 已用临时 Bazelisk/Bazel 9.0.0 运行锁更新与锁一致性检查；`MODULE.bazel.lock` 无实际差异，Cargo 锁只新增
  `codex-team-state -> proptest` 直接依赖边。
- 最终格式、fmt-check、定向 Clippy、默认 crate 测试、默认主动性质测试及显式 seed `424242` 复现均通过；默认门禁为
  `128 passed, 1 skipped`，主动入口为唯一目标测试 `1 passed`。未发现 Team State 产品缺陷。
- 实现提交 `b0a8db079a642a5ea965b2ff789c5460359c5eff` 后，干净上下文独立子智能体完成正确性/功能性审查，未发现
  finding 并明确“验收通过”；其独立复验还确认默认 ignored、默认/显式 seed 主动入口、Clippy 和非法 seed fail-fast。

### 当前工作

- Plan 047 实现、定向门禁、本地提交和用户要求的独立审查闭环均已完成，等待交回用户进行后续独立验收。

### 本任务剩余步骤

- 本任务内无剩余实现或验证步骤；最终状态核对后交回用户，不合并、不推送。

### 阻塞项

- 当前无阻塞。

### 当前验收状态

- 任务合同内实现、本地定向门禁和提交后独立正确性/功能性审查均已通过；这只表示任务 A 执行闭环完成，不代替用户或
  后续整合者的最终审查，也未合并或推送。

### 交接边界

- 本任务完成后冻结此计划。后续统一集成与主动委派收益对比只链接
  `doc/WBS.md` / `doc/WBS/multi-agent-trusted-evidence.md`，不在本计划中重复安排。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 首版固定 Root + 两名成员、64 cases、每 case 最多 32 候选步骤、默认 seed `20260820047` | 有限规模足以探索跨功能组合，又不会形成随机轰炸或重型设施 | 性质测试运行合同 | 已采纳 |
| 002 | 操作生成按 §3.2 的 11 类权重冻结；核心六族必须在默认主动批次中被实际覆盖 | 保证测试真正探索 publish/lifecycle/route/delivery/retry/wake 组合，同时不重复一般无效输入矩阵 | generator/driver | 已采纳 |
| 003 | shrink 后只从当前 reference 绑定解析 canonical 引用；无对象的步骤纯跳过 | 既保留 shrink 能力，也不把无效引用拒绝测试混入序列合同 | 引用与 shrink | 已采纳 |
| 004 | availability/retire 首版后移 | 它们会引入外部 epoch/overlay 轴；先保持 reference model 薄且审查体量可控 | 任务范围 | 已采纳 |
| 005 | 新依赖不是硬要求；若采用成熟库更简洁，则同步最小 Cargo/Bazel 元数据，不为回避依赖自建通用框架 | 兼顾实现自治、维护成本和当前 Bazel 可用性事实 | 依赖与构建 | 已采纳 |
| 006 | 本任务只提交 A 工作树，不同步 WBS、不合并、不推送 | A/B 并行开发，共享规划文档与集成由最终批次统一处理 | 并行与交付 | 已采纳 |
| 007 | 采用已锁定的 `proptest 1.9.0`，只启用 `std`，关闭默认失败持久化 | 直接获得成熟生成与 shrink，Cargo 锁只增加一条 crate 直接依赖边，不引入 corpus/runner | 测试依赖与性质入口 | 已采纳 |
| 008 | 用三方公开 history/snapshot/wake 观察对比薄 reference；retry 请求记录留在 driver，不进入 reference | 保持 reference 只表达可观察状态，同时能精确复放原请求身份并校验 canonical 结果 | reference/driver | 已采纳 |
| 009 | 用项目临时目录中的 Bazelisk 1.29.0 启动冻结 Bazel 9.0.0 完成锁核验，不全局安装工具 | 当前宿主未预装 Bazel，但普通临时依赖下载已授权；可靠核验后锁文件无需修改 | 构建元数据 | 已采纳 |
| 010 | 实现提交后由干净上下文子智能体只审正确性与功能性；真实问题才进入窄修/复验/复审循环 | 满足用户附加验收要求，同时不引入复杂审计或任务外设施 | 提交后审查 | 已完成，无 finding |
