# Plan 071：Publication Critic base 可比性重资格

## 结果

- 只读复盘 Plan 068 v3 后确认，base 的 CPU FP32→CUDA BF16 max raw-logit drift `0.1650810242` 低于事前冻结的 `0.25`
  raw cap；旧失败把 cross-dtype 的 sigmoid 后差异、near-threshold 临时 verdict 和同 runtime worker parity 混在同一个 projected gate。
  Plan 071 将三者分层：cross-runtime 使用统一 raw cap 及其 stable-sigmoid envelope，同 CUDA BF16 fresh worker 使用独立
  `0.25 raw / 0.005 projected` 门，真实 service 继续使用 descriptor 的精确 threshold，不改变 Plan 054/055/057 产品语义。
- 新增版本化 comparability/offline/observations/worker-parity 能力，并让既有 service runner 通过显式 `plan068`/`plan071`
  contract 复用同一真实 scorer/service。Plan 068 schema、模型、checkpoint、serving env、旧 target 与正式证据均保持只读；未修改 Rust。
- 独立预审发现两个异常分支：失败 warm review 被计入 bounded call 总数、base 合格但无合格锚点错误落入
  `BASE_NOT_COMPARABLE`。修复后只计算成功调用并要求精确 `18` 次，后一分支改为带原因的 `INCONCLUSIVE`；result schema 升为 v2，
  40 项回归覆盖这两个分支。预审 formal v1 因 source/schema 改变降为 superseded，未改门重算。

唯一有效正式轮为 `plan071-formal-20260825T064600Z-qualification-v5`，绑定 clean source
`90ce6ba5eb3ba3faa3ffa4db41934c1147e18653`，freeze canonical SHA-256
`02fbb85d9eb3c76a6761fd86b495d46a01720e13ced4fbac0b74e3cd8e831616`。它从新的空 namespace 完整覆盖相同 24 条 Plan 054
非 unseen cohort、exact base、C1、C3；C2 未重验并保持 Plan 068 历史 `NOT_QUALIFIED`。

| 对象 | 结论 | 关键事实 |
|---|---|---|
| base | `QUALIFIED` | cross raw max `0.165081`、projection envelope excess `0`；唯一临时 verdict flip 位于统一 `0.25` raw guard 内，stable flip `0`；worker raw/projected `0.03125/0.0021333`；18/18 service、15/15 stress、P95 `647.2ms` |
| C1 | `QUALIFIED` | cross raw max `0.176868`、envelope excess `0`；worker raw/projected `0.125/9.58e-10`；18/18 service、15/15 stress、P95 `653.4ms`；cancel/post-cancel ready/review 与 clean shutdown 通过 |
| C3 | `QUALIFIED` | cross raw max `0.027268`、envelope excess `0`；worker raw/projected `0.0078125/0.0009505`；18/18 service、15/15 stress、P95 `635.1ms` |

三对象 service verdict mismatch 均为 `0`，load 均低于 `4s`，process RSS 峰值约 `4.30GB`、VRAM 峰值约 `3.53GB`，orphan/body
leak 均为 `0`。任务终态是 `BASE_COMPARABILITY_GO`（`base_and_anchor_qualified`），因此 M3-C2 资格前置满足；本任务没有启动、排名、
配置或默认启用 M3-C2，也没有冻结最终 threshold。

## 正式身份、重型资源与异常轮

- v5 manifest file SHA-256 `9706d10142d0c4e92396e710d0e308772c27d361f96728f5d449164d31da6eb0`，observations canonical
  SHA-256 `46d7b4bfc725f61d66d2ca20030b7409f124467020b8201eec114c4cd93eb6ac`，result file SHA-256
  `66d12dff77995f23927b62d7c181d8eb993511a3a832641b88e9296535a4e20e`；archive 直接绑定 freeze、manifest 与 observations identity。
- 用户把重型资源所有权切换给 071 后才运行 v5。base/C1/C3 分别通过 canonical lock/watchdog；summary SHA-256 为
  `4880851d12e3c461eb43b5def07d6021f3aa803b2477f3e309a97060a20fee04`、
  `43cd7bf2872f248c0909a21249a5fc4e747faee6cce53159c588e0b9046c9748`、
  `0cffe1bd1549b1189f50b2b97f97c6d5f5a213f632c4bedaa86f20b56fca5868`，均为 `rc=0 / stop=none / cleanup=none`；
  cgroup sampled memory peak 约 `7.61/8.38/8.89GB`，swap peak `20.2MB/0/0`。
- v2 在 069 终态交接规则更新后、首个对象结果产生前主动中止；v3/v4 分别因 task-supplied watchdog override 和相对 wrapper 路径
  被 production proof 在模型加载前拒绝。三者均保留 `abort.json`，不属于正式证据且未被 v5 manifest 引用。没有把基础设施失败写成模型失败。
- v5 退出后确认 Cargo/rustc/nextest、Docker task、模型 service/worker、GPU compute 和 `rondo-build` scope 全部不存在；Windows C:
  前后均约 `95.58GiB` 可用。已向用户明确释放重型资源，后续不再需要 Cargo、Docker 或真实模型。

## 验证与保留

- 受影响 Python unittest：40/40；测试覆盖 Plan 068 qualification/service runner 与 Plan 071 comparability。serving env 不含 pytest，
  一次误选 pytest 入口在收集前失败，随后使用仓库既有 unittest 环境完成门禁；没有修改 serving env。
- 上下文独立轻量预审从 v5 manifest/raw 重新构建 observations/result，与 archive 完全一致；确认 v2/v3/v4 未被引用、两个异常分支
  回归有效，未发现 P1/P2/P3。预审未重跑模型、Cargo 或 Docker。
- Python compileall 与 `git diff --check` 作为最终提交门运行。Rust 源码未改，故未运行 Cargo；Docker、HF 下载、真实 API、远端写入、
  训练和 unseen-test 均未运行。Plan 068 已验收 failure/restart matrix 未受接缝变化，不机械重跑。
- ignored `eval-data/publication-critic/plan071/` 为 `585,558` bytes，20 个目录均 `0700`、96 个文件均 `0600`、无 symlink；
  commissioning、superseded/aborted 历史和唯一 v5 formal 均保留。未复制或改写约 24GB Plan 068 工件，也未创建 Plan 071 env/cache。
- 正式 archive：`eval-data/publication-critic/plan071/formal/runs/plan071-formal-20260825T064600Z-qualification-v5/`。

## 独立验收整改

独立验收提交 `a42a46515955e61a719bf68b8f4b54f0d7c2d2dc` 发现一个 P2：base、C1、C3 同时
`NOT_QUALIFIED` 时，旧分支仍输出 `BASE_NOT_COMPARABLE`。finding 属实；没有任何合格锚点时，共享环境和规则未建立有效对照，
应返回 `INCONCLUSIVE`。整改将 anchor 前置检查统一放在所有 formal 可比终态之前，无合格锚点使用既有 typed reason
`no_qualified_anchor_for_shared_comparability_rule`；base 不合格但至少一个锚点合格仍保持 `BASE_NOT_COMPARABLE / base_not_qualified`。

新增三对象同时不合格回归后，受影响 unittest 为 41/41，compileall 与 `git diff --check` 通过。修复后的
`build_observations/evaluate_run` 从 v5 manifest/raw 重建 observations，与 raw/archive 完全相等；重建 result 与归档完全相等，仍为
`BASE_COMPARABILITY_GO / base_and_anchor_qualified`，observations canonical SHA-256 仍为
`46d7b4bfc725f61d66d2ca20030b7409f124467020b8201eec114c4cd93eb6ac`。因此按审查者代用户作出的决定，保留 v5 为唯一真实
formal，不重跑模型、Cargo 或 Docker，也不为未命中分支 bugfix 改变 result schema。

WBS 建议 delta：记录 Plan 071 已用同一资格口径使 exact base、C1、C3 均取得 `QUALIFIED`，C2 保持历史 `NOT_QUALIFIED`，
M3-C2 的 base+anchor 前置可解除但不得自动启动；本 task branch 不抢写并行共享 WBS。
