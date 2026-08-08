# 测评结果与数据资产保存规范

最后更新：2026-08-08

适用于全部测评产出：离线冻结回放（E-A）、真实 Terminal-Bench 2.1 端到端（E-B）、静态影子审批横评（L3）。
目标是**结构清楚、便于管理、可长期追溯**，同时保持轻量——不做数据资产审计、可信链或权限系统。

## 1. 两个根目录，按"轻/重"分家

| 根目录 | 是否入库 | 放什么 | 判据 |
|---|---|---|---|
| `eval/` | **入库** | 运行配置、任务分层清单、结果库、报表 | 文本、体积小、需要跟随代码版本演进 |
| `eval-data/` | **git-ignored** | 录制包、证据包、单次运行原始产物、模型权重 | 体积大、可重生成或不可共享 |

分家的理由：结果库和清单必须跟着 commit 走才能回答"这个分数是哪版代码跑的"；而录制包和容器日志放进 git 会让仓库迅速不可用。

落地时需在 `.gitignore` 追加：

```gitignore
# 测评重资产：录制包、证据包、运行产物、模型权重
/eval-data/
```

## 2. 目录布局

```
eval/                                  # 入库
├── config/                            # 运行条件（模型、effort、超时、探针开关、websocket=false）
│   ├── tb-canary.toml
│   └── replay-default.toml
├── tasksets/                          # 只存任务 id 与分区归属，不存任务正文
│   ├── canary.txt
│   ├── validation.txt
│   └── holdout.txt                    # 只有 id，禁止查看内容
├── fixtures/                          # A3 冻结回放用例集（仅当体积可控时入库，见 §6）
├── results/
│   └── runs.jsonl                     # 结果库主表，只追加
└── reports/                           # 生成的对比表与曲线（可重生成）

eval-data/                             # git-ignored
├── recordings/<recording_id>/         # A1 录制包（原始 HTTP exchange + SSE）
├── evidence/                          # 审批证据包
│   ├── raw/<review_id>/               # S2 直接落盘处：E_final.json + meta.json，权限 0700
│   ├── seed/<review_id>/              # 可用于指导合成
│   └── holdout/<review_id>/           # 只用于评测，禁止进入合成上下文
├── runs/<run_id>/                     # 单次运行的原始日志、rollout、容器输出
└── models/                            # 本地权重、GGUF、LoRA adapter（永不入库）
```

## 3. 命名

**run_id**：`<YYYYMMDD-HHMMSSmmm>-<track>-<side>-r<round>`

- 时间戳精确到**毫秒**，并带轮次后缀。只精确到秒时，并行跑批或同秒重试会覆盖同一个 artifacts 目录。
- `track` ∈ `tb`（真实端到端）｜ `replay`（离线回放）｜ `shadow`（静态影子横评）
- `side` ∈ `rondo` ｜ `codex` ｜ 影子横评时用模型标识（`luna-static` / `sol-static` / `local-static`）
- 例：`20260812-143005182-tb-codex-r1`、`20260815-091200047-shadow-local-static-r1`
- 生成时若目标 artifacts 目录已存在，视为冲突并直接报错，不覆盖。

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
    "guardian_policy_baseline": "rust-v0.147.0",
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
  "metrics": null,
  "cost": { "estimated_usd": 1.2, "actual_usd": 1.05 },
  "artifacts": "eval-data/runs/20260812-143005182-tb-rondo-r1",
  "notes": ""
}
```

- `track = replay` 时 `tasks` 为 `null`，改填 `metrics`：`{ wall_ms, cpu_ms, peak_rss_kb, turns, tool_calls, drift }`。
- `track = shadow` 时 `metrics` 填一致率、false allow / false deny 率、P50/P95 延迟、显存峰值。
- **`git_dirty = true` 的运行结果只能用于调试，不得作为里程碑证据**。
- `upstream_codex.workspace_lock_normalization` 只描述构建只读官方基线时在隔离 scratch 副本中的
  机械变换；RONDO 运行也记录它，便于证明两侧基线来源一致。不得把规范化后的 lock 哈希写成
  官方 tag 文件哈希。

### 隐藏集的特殊规则

`taskset = "holdout"` 的运行**只写 `summary`，`tasks` 必须为 `null`**。否则隐藏集会通过结果库逐次泄漏单任务结果，几轮之后就不再隐藏。

## 5. 证据包分区

1. S2 运行时统一落到 `eval-data/evidence/raw/<review_id>/`（`review_id` 只作文件名，保证实例唯一）。
2. 划分到 `seed/` 与 `holdout/` 时，落桶键必须是**跨运行稳定的语义身份**：`sha256(task_id + 规范化待审批动作指纹)`，无 task_id 时退化为动作指纹本身。
   **不能用 `review_id` 落桶**——它是每轮新生成的 UUID v4，同一任务同一动作重跑会换 id，互斥就只对文件实例成立、对语义样本不成立，跨运行仍会污染。
3. 划分结果写入清单并冻结；后续新增证据按同一规则增量划分，不重划历史。
4. 证据包**按原始会话记录对待**：可能含任务上下文里出现的任何敏感内容，目录权限 `0700`，不入库。
5. 外发给云端模型（Luna / Sol 静态影子）属于数据外发，须单独授权。
6. `v0.147.0` 下 `E_final` 可以是标准 Responses 或 Responses Lite：前者的 policy 位于
   `instructions`，后者位于 `input` 的 developer message。规范化后两种形态都必须保留等价
   的 policy / 任务上下文 / 工具调用结果，并剔除 `encrypted_function_args` 等 provider 私有运输字段。
7. 0.147 会把有界的 approval/retry reason 放进 Guardian prompt；它是有意义输入，规范化时必须保留。
   每份证据还要记录 `guardian_policy_baseline`，不同 policy 版本先分层，不能静默混作同一训练或评测总体。

## 6. 保留与清理

| 数据 | 保留策略 |
|---|---|
| `eval/results/runs.jsonl` | 永久。文本且体积小，是唯一的历史真相 |
| `eval/reports/` | 可随时重生成，只保留最新一版 |
| `eval-data/runs/<run_id>/` | 保留最近 20 次 + 所有里程碑（M0~M5）标记的运行 |
| `eval-data/recordings/` | 冻结用例集对应的录制永久保留；探索性录制可清 |
| `eval-data/evidence/` | `seed` 与 `holdout` 永久（体量小）；`raw` 在完成划分后可清 |
| `eval-data/models/` | 只保留当前在用与上一版权重，其余按需重新下载 |

提供 `just eval-gc` 按上表清理，删除前打印将删除的路径与总体积，**不做静默删除**。

`eval/fixtures/` 入库阈值：总量 ≤ 50MB 且单文件 ≤ 10MB。超过则只入库精简后的规范化包，原始录制留在 `eval-data/`。

## 7. 不做什么

- 不做数据资产审计、访问控制、可信链或签名体系。
- 不建数据库，`runs.jsonl` + 目录约定足够，需要查询时用 `jq`。
- 不做自动上传或远端同步；所有产物留在本机。
- 不为"完整性"保留无人会看的中间产物。
