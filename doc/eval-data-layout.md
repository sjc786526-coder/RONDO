# 测评结果与数据资产保存规范

最后更新：2026-08-13

适用于全部测评产出：真实 Terminal-Bench 2.1 端到端（E-B）、静态影子审批横评（L3）、会话内人判定横评
（Local M4）。离线冻结回放（E-A）的 schema 保留在本文件中，但该轨已随方向 1 挂起（见 `doc/WBS.md`）。
目标是**结构清楚、便于管理、可长期追溯**，同时保持轻量——不做数据资产审计、可信链或权限系统。

## 1. 两个根目录，按"轻/重"分家

| 根目录 | 是否入库 | 放什么 | 判据 |
|---|---|---|---|
| `eval/` | **入库** | 运行配置、任务分层清单、结果库、报表 | 文本、体积小、需要跟随代码版本演进 |
| `eval-data/` | **git-ignored** | 录制包、证据包、单次运行原始产物、模型权重 | 体积大、可重生成或不可共享 |

分家的理由：结果库和清单必须跟着 commit 走才能回答"这个分数是哪版代码跑的"；而录制包和容器日志放进 git 会让仓库迅速不可用。

`.gitignore` 已包含：

```gitignore
# 测评重资产：录制包、证据包、运行产物、模型权重
/eval-data/
```

## 2. 目录布局

```
eval/                                  # 入库
├── rondo_eval/                        # 共享合同、runner、adapter、归档、doctor/fake
├── locks/                             # Harbor/TB、llama.cpp、bwrap 的版本与 SHA 冻结
├── tests/                             # pure/fake/loopback 设施测试
├── pyproject.toml / uv.lock           # 项目局部 Python/Harbor 依赖锁
├── tasksets/                          # 只存任务 id 与分区归属，不存任务正文
│   ├── canary.txt
│   ├── validation.txt
│   ├── holdout.txt                    # 只有 id，禁止查看内容
│   ├── p2-b7-canary-catalog.json      # canary 的 source/image/runtime freeze
│   └── p2-b7-cost-forecast.json       # B6 可复算估算合同
├── templates/                         # 版本化 prompt / 产物模板，冻结后按版本记哈希
│   ├── local-approval/                # 本地审批结构化输出模板
│   └── cross-eval-judge/              # Local M4 裁判 prompt 与判定标准
├── fixtures/                          # A3 冻结回放用例集（E-A 挂起；仅当体积可控时入库，见 §6）
├── results/
│   ├── runs.jsonl                     # 可见任务结果库主表，只追加
│   └── baselines/                     # campaign 公开聚合；holdout 未来只允许整批一条
└── reports/                           # 生成的对比表与曲线（可重生成）

eval-data/                             # git-ignored
├── bin/{rondo,rondo-multi,codex}/     # 已冻结的 runtime bundle + manifest（`rondo/` = RONDO Local；`codex/` 为上游侧，见 §3.1）
├── deps/                              # 按 SHA 验证的项目局部运行资产（例如 bwrap）
├── tools/                             # 项目局部工具（例如 llama.cpp runtime）
├── toolkits/                          # 项目局部 SDK/toolkit 与冻结 installer（不做系统安装）
├── sources/                           # 精确 revision 的大型上游源码快照
├── build/                             # 受项目锁/看门狗约束的临时构建树
├── build-metrics/                     # 看门狗 summary/JUnit/受限日志
├── budgets/                           # 持久费用预留/结算账本，0600
├── pairs/                             # 仅 paid 双侧顺序与发布恢复账本，0600
├── campaigns/<campaign_id>/           # B7 状态、wire/Oracle-manifest 引用与私有聚合，0600
├── oracle-proofs/p2-b7-v1/             # campaign-independent 单题 Oracle proof + 十题 manifest，0600
├── cross-eval/<batch_id>/              # Local M4 会话内人判定的冻结 JSONL 与证据哈希，0600
├── b2/current.json                    # 可替换的当前 no-API 双侧验收收据，0600
├── local-approval/                    # 本地模型 launcher 实例 receipt，0600
├── work/                              # materialize 和 no-API 工作目录
├── recordings/<recording_id>/         # A1 录制包（原始 HTTP exchange + SSE）
├── evidence/                          # 审批证据包
│   ├── raw/<review_id>/               # S2 直接落盘处；Unix/WSL 权限 0700，Windows 继承 ACL
│   ├── seed/<review_id>/              # 可用于指导合成
│   └── holdout/<review_id>/           # 只用于评测，禁止进入合成上下文
├── runs/<run_id>/                     # 已发布单次运行的原始日志、rollout、容器输出
└── models/                            # 本地权重、GGUF、LoRA adapter（永不入库）
```

## 3. 命名

### 3.1 产品身份

项目有两条产品线：**RONDO Local**（`mydev/`）与 **RONDO Multi**（`multidev/`）。产品身份是一个
**独立维度**，必须贯通 binary freeze、源码/构建路径、manifest 与结果归档，不能只靠参数化一个路径。

| 规则 | 内容 |
|---|---|
| 取值 | `rondo-local` ｜ `rondo-multi`。**`codex` 不是产品取值** —— 冻结上游是比较侧，不是本项目的产品线 |
| 适用范围 | 只在被评对象是本项目的 RONDO 产品时写。`side = "codex"`（冻结上游）与 `side = "sol-static"`（云端教师）等非本项目产品的行**不写 `product`**，读取方也不得为其推定产品身份 |
| 历史解释 | 缺字段且 `side = "rondo"` 的历史行按 `rondo-local` 解释；缺字段且 `side = "codex"` 的行视为不适用。当前 `runs.jsonl` 的 244 条中，224 条 `side=rondo`（即 RONDO Local）、20 条 `side=codex`（冻结上游侧） |
| 只加不改 | 历史结果**不改名、不回填新 schema**；新字段从后续 campaign 开始使用 |
| 目录 | 历史 `bin/rondo/` 保持原名不动，等价于 `rondo-local`；Multi 新增 `bin/rondo-multi/`，必须显式带 `multi` 字样。`bin/codex/` 是冻结上游侧的 bundle，不参与产品身份维度 |
| 落地位置 | `eval/rondo_eval/contracts.py` 的 `product_layout()` 是唯一映射：源码目录（`mydev` / `multidev`）、Cargo target 前缀、`bin/` 命名空间与 `models-manager/models.json` 催化路径都从它派生 |
| 工件字段 | 新冻结的 RONDO manifest 写 `product`；缺该键的历史工件按 `rondo-local` 读取，冻结上游的 manifest 不写也不推定 |
| 与比较侧的区别 | `run_id` 里的 `side`（`rondo` / `codex`）是**比较侧**语义，与产品身份是**正交的两个维度**，不得互相覆盖。跨产品对比时用 `product` 区分是哪个 RONDO，用 `side` 区分是 RONDO 侧还是上游侧 |
| 数据目录切分 | **不顶层并列**（不新开 `eval-data-multi/`），只在产品特定的层级加命名空间。`toolkits/`、`models/`、`tools/`、`sources/` 等共享资产保持单份 |
| crate / 二进制名 | 沿用上游 `codex-cli` / `codex`，**不重命名**；产品身份由本规范的路径与字段承担 |

`test-data/` 同理：内部按产品分子目录，不顶层并列。

### 3.2 标识符

**run_id**：`<YYYYMMDD-HHMMSSmmm>-<track>-<side>-r<round>`

- 时间戳精确到**毫秒**，并带轮次后缀。只精确到秒时，并行跑批或同秒重试会覆盖同一个 artifacts 目录。
- `track` ∈ `tb`（真实端到端）｜ `replay`（离线回放，随 E-A 挂起）｜ `shadow`（静态影子横评）
- `side` ∈ `rondo` ｜ `codex` ｜ 影子横评时用模型标识（`sol-static` / `local-static` / `local-ft-static`；
  历史批次的 `luna-static` 保留不改）。`side` 只表达比较侧，产品身份另用独立字段记录（§3.1）。
  教师侧（`sol-static`）的行是**人在场生成后导入的冻结标签**，不是 `eval/` 自动运行产物；
  字段合同见 §4「shadow 行的最小字段合同」。
- 例：`20260812-143005182-tb-codex-r1`、`20260815-091200047-shadow-local-static-r1`
- 生成时若目标 artifacts 目录已存在，视为冲突并直接报错，不覆盖。

**batch_id**（Local M4 会话内判定）：`<YYYYMMDD>-cross-eval-<序号>`，一批一目录一份冻结 JSONL。

**recording_id**：`<YYYYMMDD-HHMMSS>-<任务或场景短名>`
**review_id**：沿用 `new_guardian_review_id()` 的既有值，不另起体系。

## 4. 结果库 `eval/results/runs.jsonl`

一行一次运行，只追加，不改写历史行。三条 track 共用同一 schema，差异体现在 `summary` / `tasks` / `metrics` 三个字段上。

```json
{
  "run_id": "20260812-143005182-tb-rondo-r1",
  "created_at": "2026-08-12T14:30:05+08:00",
  "track": "tb",
  "side": "rondo",
  "product": "rondo-local",
  "git_commit": "4355362",
  "git_dirty": false,
  "binary_sha256": "…",
  "upstream_codex": {
    "tag": "rust-v0.147.0",
    "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
    "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0"
  },
  "config": {
    "main_model": "gpt-5.6-luna",
    "guardian_model": "gpt-5.6-luna",
    "guardian_effort": "low",
    "guardian_request_shape": "responses_lite",
    "guardian_source_baseline": "rust-v0.147.0",
    "guardian_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
    "guardian_effective_policy_sha256": "…",
    "approvals_reviewer": "auto_review",
    "approval_policy": "on-request",
    "sandbox_mode": "workspace-write",
    "websocket": false,
    "taskset": "canary",
    "round": 1,
    "harness_version": "terminal-bench 2.1.x"
  },
  "summary": { "success_rate": 0.6, "tasks_total": 10, "infra_failed": 0 },
  "tasks": [
    { "task_id": "…", "outcome": "pass|fail", "attribution": "agent|guardian_correct_deny|guardian_false_deny|infra", "duration_s": 182, "tokens_in": 0, "tokens_out": 0 }
  ],
  "metrics": { "wall_seconds": 182.0, "cpu_user_seconds": 21.0, "cpu_system_seconds": 3.0, "peak_rss_bytes": 536870912, "exit_code": 0 },
  "cost": { "estimated_usd": 1.2, "actual_usd": null },
  "artifacts": "eval-data/runs/20260812-143005182-tb-rondo-r1",
  "notes": ""
}
```

- `product` 按 §3.1 取值，只在被评对象是 RONDO 产品时出现；`side = "codex"` 与 `side = "sol-static"`
  的行不写该字段。历史行没有该字段时，`side = "rondo"` 按 `rondo-local` 解释，`side = "codex"` 视为不适用。
  **不回填历史行**。
- 带 `product` 的 Terminal-Bench 行还在 `config` 里写版本化的 `auto_review_config`，记录该次运行
  **配置了什么**：`model`、`model_provider`、`reasoning_effort`、`evidence_dir` 四项，未配置写 `null`。
  它记录配置状态，不是 provider 或 catalog 派生出的有效 Guardian 模型。RONDO Local 沿用既有公平合同
  （配置 model / effort / evidence_dir），RONDO Multi 的产品基线定义为四项全未配置。结果顶层与归档内
  `run-summary.json` 使用同一个投影，成功与失败发布路径不会分叉。
- 新写的 Terminal-Bench 行用 `config.private_summary_schema_version = 1` 声明私有摘要合同；publisher、journal
  recovery 与 durable index reader 都要求 `run-summary.json` 的 run/side/commit/outcome/config/summary/tasks
  与 tracked row 逐项相同。没有该版本标记的既有历史行继续只读兼容，不据文件是否碰巧存在来猜合同版本。
- campaign 新写结果同时记录 `config.campaign_schema_version`。schema v7 的 RONDO 与 Codex 两侧都必须写
  `config.campaign_product` 并等于冻结 lock 的产品；只有 RONDO 侧写顶层 `product`、`config.product`、
  `config.binary_product` 与 `auto_review_config`，Codex 侧不得携带这些 RONDO 字段。v1—v6 和未标版本的
  历史 campaign 结果不回填产品绑定。
- 当前 record schema v1 的终态为 `completed|agent_failed|infra_failed|budget_stopped|cancelled`；
  `completed` Terminal-Bench 行必须有非空 config/summary/tasks，失败行也不得伪造正常 evidence。
- Terminal-Bench 在任何外部执行前先 claim 唯一 run-id 的私有 staging 与持久预算槽；已 claim 后的
  Docker/watchdog/parser 异常也必须写分类失败行，不允许复用同一 run-id 绕过运行次数上限。
- Terminal-Bench 五键 host `metrics` 固定为 runner-host `self+children` 的 `wall_seconds`、
  `cpu_user_seconds`、`cpu_system_seconds`、`peak_rss_bytes` 与 `exit_code`，仅用于设施诊断。
  supervisor 在 daemon 确认 private cgroup namespace 后，另从 exact container 的 cgroup v2 生成
  `container_id`、`cpu_usage_seconds`、`peak_memory_bytes`；B2 当前收据直接复用 supervisor 的
  canonical Docker receipt，paid publication、pair ledger 与 M1 继续持有该组机器证据。B3/M1 已形成历史
  真实证据；完整探针和细粒度 Guardian 归因仍由当前 WBS 的 A4/B5 路线管理。
- 发布使用 journal v2：在同一结果锁内绑定工件树摘要、完整 record bytes 及 index 前/后长度与 SHA，
  以同目录临时文件写完整新 index、fsync 后原子 replace。恢复只接受精确 pre/post identity，并重新核对
  工件树；partial write、进程死亡或恢复前篡改均 fail-closed，不再原地 append 半行。paid 槽进入
  `publishing` 后，若确定性校验在 journal 创建前失败，则撤销未发布 staging 并使用既有失败 publication
  收敛；journal/target 一旦出现仍只走恢复路径。
- paid pair sequence 使用稳定 `<ledger>.lock` 侧车 flock，ledger 本体通过 0600 temp write + fsync +
  atomic replace + parent fsync 更新；已存在的空文件视为损坏，不能重置为 slot 1。两槽绑定
  同一 `eval_harness_commit`。paid 槽先进入 `publishing`，结果持久后回读 record SHA-256 再收敛为
  `completed`；M1 同时核对 durable ledger 与 result index，不仅聚合两条 record。
- no-API 不进入 paid ledger，也不维护 retirement 或崩溃恢复状态。唯一入口在一个进程中严格执行
  RONDO→Codex，首侧失败立即停止；两侧成功后以 temp+fsync+atomic replace 写
  `eval-data/b2/current.json`。新运行可替换该收据。收据只保留 harness/lock 身份、两侧状态、0 官方 API/
  0 USD 和 supervisor 已验证的 image、VHDX、容器资源/隔离、metrics、seccomp 与 cleanup；不保存 raw
  argv、stdout/stderr、密钥或宿主 mount source。
- B7 Oracle proof 按 task/source/image、taskset/catalog entry、共享 runner/materializer/verifier、Harbor/TB、
  seccomp 与稳定 Docker 兼容事实寻址；不绑定 paid campaign 或整个 Git commit。单题完成清理与最终资源计数后
  原子落盘，十题 manifest 只引用已验证 proof。paid coordinator 仅持有轻量 campaign lease；每个 Oracle/paid
  task 单独取得重型 lock/watchdog，slot durable 后释放。
- `git_commit` 记录冻结产品/二进制的 measurement commit；若 eval harness 从另一 clean worktree 加载，
  其独立 commit 必须写入 `config.eval_harness_commit`，并与 pair ledger 首次 claim 绑定的 commit 一致。
- Harbor 私有归档只保留主动 allowlist；RONDO `E_final/meta` 在复核完整生产 meta、Guardian source
  tag/commit 与 effective policy hash 后单独归档，不复制 config、lock、raw log 或 exception trace。
- `track = replay` 时 `tasks` 为 `null`，改填 `metrics`：`{ wall_ms, cpu_ms, peak_rss_kb, turns, tool_calls, drift }`。
  该 track 随 E-A 挂起，schema 保留但当前不产生新行；若 RONDO replay 行带 `product`，
  `config.product` 与 `config.binary_product` 必须三者相同，且不得携带 Terminal-Bench 的
  `auto_review_config` 或 campaign 产品字段。历史无产品行继续只读兼容。
- `track = shadow` 且 `source = "auto"` 时 `metrics` 填**教师一致率**（相对 Sol 教师标签）、
  结构化输出解析失败率、超时与 fail-closed 次数、P50/P95 延迟、显存峰值。
  **漏放 / 误拦只有在有独立裁判结果时才可填**（见 `doc/WBS/local-approval-model.md` L4）；
  单纯相对教师标签的差异不得写成 false allow / false deny。
  `source = "imported"` 的行 `metrics` 为 `null`（教师标签没有本地运行指标），见下文字段合同。
- **`git_dirty = true` 的运行结果只能用于调试，不得作为里程碑证据**。
- `upstream_codex.workspace_lock_normalization` 只描述构建只读官方基线时在隔离 scratch 副本中的
  机械变换；RONDO 运行也记录它，便于证明两侧基线来源一致。不得把规范化后的 lock 哈希写成
  官方 tag 文件哈希。
- `estimated_usd` 是本地冻结价格 × usage 的预算计价。没有查询供应商账单时，非零
  `actual_usd` 必须为 `null`；零请求/零费用可记 `0.0`。请求 role 允许为诊断做 shape inference，
  本地预算代理必须先验证请求形状，再把一致的 main/guardian role 投影为出站 declared header；调用方已有
  header 时必须与形状一致。只有该 declared+inferred 一致的元数据可满足 completed/M1。

### shadow 行的最小字段合同

`track = "shadow"` 有两类来源，必须靠字段区分，不能靠 `side` 猜：

| 类别 | `side` | `product` | `source` |
|---|---|---|---|
| 程序化运行的本地被评方 | `local-static` / `local-ft-static` | `rondo-local` | `auto` |
| 导入的教师标签 | `sol-static` | **不写**（教师不是本项目产品） | `imported` |

- `source` ∈ `auto` ｜ `imported`，**shadow 行必填**。历史行没有该字段时按 `auto` 解释（历史上不存在导入行）。
- `source = "imported"` 时**必填**：`config.teacher_model`（生成时点的模型标识）、`config.generated_at`
  （生成日期）、`config.prompt_version` 与 `config.prompt_sha256`（所用冻结 prompt 的版本标识与内容哈希）。
- `source = "imported"` 时下列运行字段无意义，**必须显式为 `null`，不得伪造**：`binary_sha256`、`metrics`、
  `cost.actual_usd`。`cost.estimated_usd` 记 `0.0`（订阅制入口不额外计费）。
- `git_commit` 对导入行记录**执行导入时**的 eval harness commit（谁做的导入），不是被测二进制的 commit；
  `git_dirty` 规则不变。
- `artifacts` 对导入行指向冻结标签文件所在目录。
- `local-*` 两类当前只允许 `product = "rondo-local"`，且 `config.product` / `config.binary_product` 必须同值；
  不得携带 Terminal-Bench 的 `auto_review_config` 或 campaign 产品字段。将来若 Multi 也做影子横评，必须先在
  本节定义独立 side/产品映射和写入合同，不能让现有 Local side 直接声明 `rondo-multi`。

### 隐藏集的特殊规则

`taskset = "holdout"` 的运行**只写 `summary`，`tasks` 必须为 `null`**。否则隐藏集会通过结果库逐次泄漏单任务结果，几轮之后就不再隐藏。

### 会话内人判定横评（Local M4）的产物

M4 由 Opus 5 在 Claude Code 会话内判定，**不满足“自动运行、自动记录、自动归档”**，因此不进 `runs.jsonl`，
改用固定产物格式约束：

1. 每批输出一份**冻结 JSONL**，落到 `eval-data/cross-eval/<batch_id>/`，权限 0600。
2. 每行至少含：证据哈希、所用裁判 prompt 文件的版本标识与内容哈希、各被评方输出、裁判结论与理由。
3. 被评方在裁判侧**匿名化且顺序随机**；匿名标签到真实被评方的映射与结果同批保存，不在判定时可见。
4. 必须记录**裁判模型标识与判定日期**，并把该批标注为“该时点判定”；订阅侧模型版本不由本项目冻结，
   不假装可重跑复现。
5. **合成证据主体与真实 `E_final` holdout 锚点分成两组记录，不混算**。真实 holdout 只作 sanity anchor。
6. 需要公共可见时，只在 `eval/results/baselines/` 登记一行人工摘要（批次 id、样本数、prompt 版本哈希、
   裁判模型与日期、结论），逐条判定留在 `eval-data/`。

## 5. 证据包分区

1. S2 运行时统一落到 `eval-data/evidence/raw/<review_id>/`（`review_id` 只作文件名，保证实例唯一）。
2. 划分到 `seed/` 与 `holdout/` 时，落桶键必须是**跨运行稳定的语义身份**：`sha256(task_id + 规范化待审批动作指纹)`，无 task_id 时退化为动作指纹本身。
   **不能用 `review_id` 落桶**——它是每轮新生成的 UUID v4，同一任务同一动作重跑会换 id，互斥就只对文件实例成立、对语义样本不成立，跨运行仍会污染。
3. 划分结果写入清单并冻结；后续新增证据按同一规则增量划分，不重划历史。
4. 证据包**按原始会话记录对待**：可能含任务上下文里出现的任何敏感内容，不入库；Unix/WSL 目录
   权限 `0700`，Windows 继承配置目录 ACL。
5. 外发给云端模型（Sol 等静态影子）属于数据外发，须单独授权；订阅制入口不额外计费，但不豁免该门。
6. `v0.147.0` 下 `E_final` 可以是标准 Responses 或 Responses Lite：前者的 policy 位于
   `instructions`，后者位于 `input` 的 developer message。规范化后两种形态都必须保留等价的
   policy / 任务上下文 / 工具调用结果，并剔除 `encrypted_function_args` 等 provider 私有运输字段。
7. 0.147 会把有界的 approval/retry reason 放进 Guardian prompt；它是有意义输入，规范化时必须保留。
   每份证据的meta从 `mydev/codex-rs/core/upstream-source-baseline.toml` 记录
   `guardian_source_baseline`（tag）与 `guardian_source_commit`（peeled commit）；P1消费者还必须从有效policy内容生成
   `guardian_effective_policy_sha256`。源码基线与实际 policy 身份分开分层，不能静默混作同一训练或
   评测总体。

## 6. 保留与清理

| 数据 | 保留策略 |
|---|---|
| `eval/results/runs.jsonl` | 永久。文本且体积小；合入主线后的内容是已交付公共结果的唯一历史真相 |
| `eval/reports/` | 可随时重生成，只保留最新一版 |
| `eval-data/runs/<run_id>/` | 保留最近 20 次 + 所有里程碑标记的运行 |
| `eval-data/cross-eval/<batch_id>/` | 永久。会话内判定不可重跑复现，删掉就没有第二份 |
| `eval-data/recordings/` | E-A 挂起期间不新增；已有录制按原规则保留 |
| `eval-data/evidence/` | `seed` 与 `holdout` 永久（体量小）；`raw` 在完成划分后可清 |
| `eval-data/models/` | 只保留当前在用与上一版权重，其余按需重新下载 |

当前尚未实现通用 `eval-gc`。清理只能针对本次已知的精确 target/scratch/任务容器，
必须在操作前打印目标和体积，重型产物仍经项目看门狗；不静默清理来源不明的历史资产。

tracked 结果可以先在专用本地 results 分支收敛，但该分支只算**待交付暂存**：必须核对结果差异、合入 `main`
并推送后，才进入已交付公共历史。关闭 results worktree 不等于删除分支；未合入结果不得因工作树清理而丢失，
也不得在文档中冒充已进入主线。当前具体分支状态只写 WBS，不固化在本规范。

`eval/fixtures/` 入库阈值：总量 ≤ 50MB 且单文件 ≤ 10MB。超过则只入库精简后的规范化包，原始录制留在 `eval-data/`。

## 7. 不做什么

- 不做数据资产审计、访问控制、可信链或签名体系。
- 不建数据库，`runs.jsonl` + 目录约定足够，需要查询时用 `jq`。
- 不自动上传或同步 ignored 私有资产；受跟踪的轻量公共结果按 Git 交付流程进入主线和远端。
- 不为"完整性"保留无人会看的中间产物。
