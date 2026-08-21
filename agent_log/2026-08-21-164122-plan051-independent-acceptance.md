# Plan 051 独立验收报告

## 结论

- **验收不通过。** v28 首次 schema v7 正式 canary 的运行、结算与结果本身未发现需要重跑的问题，但第二个核心目标
  “后续只替换新的 Local commit/bundle、identity、价格和任务预算即可稳定重跑”尚未实现，且合法的负向正式基线
  不能完成终态收口。
- **任务目标失败（部分成果有效）。** 第一个目标“形成首次正式 schema v7 基线”已经完成；第二个目标“固化可复用的
  统一稳定入口”未完成。因此 v28 数据继续只读保留，不选择性重跑；修复只应作用于入口、identity/任务预算初始化、
  终态收口和相对基线输出。

## 阻断发现

### P1：当前入口是一次性的 Plan 051 入口，不能创建下一份 Local 正式基线

`just eval-plan051` 只把 `status/prepare/run/resume/finalize` 转发给现有 campaign；identity 创建和 stub preflight
仍是另外两个独立 recipe（`justfile:467-515`）。其中 `prepare()` 只验证 active identity、现有 manifests、任务预算
envelope 和已有 receipts（`eval/rondo_eval/terminal_bench/formal_canary.py:54-134`），不会冻结新 Local bundle、初始化
新任务预算、生成新 identity 或生产 preflight receipts。

更关键的是，schema v7 loader/generator 把 Plan 051 的 Local commit `54f62e5...`、Codex commit、模型/effort 和
400 USD 固定为模块常量（`eval/rondo_eval/terminal_bench/baseline.py:58-66,1653-1663,1712-1730`）；identity 生成器
只接受固定 `TASK_BUDGET_ID`/400 USD，并强制 RONDO manifest 的 source commit 等于 `54f62e5...`
（`eval/rondo_eval/terminal_bench/baseline_identity.py:252-267,326-339`）。任务预算又使用唯一固定 ID、路径和上限
（`eval/rondo_eval/terminal_bench/task_budget.py:23-25`）。现场该 envelope 已存在且 `active_identity=null`；
`prepare()` 对未来 identity 不能新建 envelope，随后会在 active identity 校验处失败。

因此，未来新 Local 基线即使已经提供 commit 和 bundle，也必须修改代码并处理旧 envelope，不能按任务目标直接重跑。
现有发布聚合也只输出本 campaign 指标（`eval/rondo_eval/terminal_bench/baseline_cli.py:2700-2727`），没有输出相对上一份
正式基线的结果。

最小整改目标是把这些**每次运行输入**与**方向 0 稳定合同**分开：由一个统一命名入口（可以用子命令/阶段）复用现有
freeze、identity、preflight、runner、聚合与归档组件，显式接收并核对新的 Local commit/manifest、campaign identity、
价格快照和新授权任务预算；为新任务创建新的 envelope，不覆盖 Plan 051 历史；发布一份相对上一正式基线的简洁差异。
具体内部路线由执行者自主选择，不需要数据库、调度平台、签名链或新的评测框架。

### P1：合法 `failed` 正式基线会跳过任务预算关闭和 pointer 退役

`baseline_main()` 对 `BaselineStatus.FAILED` 正常返回退出码 2
（`eval/rondo_eval/terminal_bench/baseline_cli.py:420-426,1795-1807`）。但 `formal_canary finalize` 在任何非零退出码时
立即返回（`eval/rondo_eval/terminal_bench/formal_canary.py:239-242`），后面的 task envelope 关闭与 active pointer 退役
逻辑不会执行。按冻结合同，稳定 A/B 差异是有效正式基线而不是设施失败；当前实现会使这种有效结果残留 active identity，
违背终态清理和后续重跑要求。

应让 `passed` 与 `failed` 两种已发布正式终态都执行相同的结算确认、envelope 关闭和 pointer 退役，再保留各自退出码；
`blocked` 仍可保留给 successor。补一条只使用临时目录/mocks 的窄回归即可，不需要 Docker 或真实 API。

## 验收决策

1. **采纳本轮双方 main=`medium`、Guardian=`low`，v28 无需付费重跑。** 初始规划提交 `8222838` 确实写的是
   main/Guardian 均为 `medium`，执行者不应自行把它描述成天然满足。只读源码核验显示，冻结 Codex v0.147.0 对支持
   `low` 的审批模型会优先选择 `low`（`codex-source-code/codex-rs/core/src/guardian/review.rs:745-776`），而强制
   Guardian=`medium` 需要修改冻结上游行为，触碰本任务禁止边界。两侧实际请求保持对称，因此本次验收依据用户授予的
   代决策权，正式采纳 main-medium/Guardian-low 合同，v28 仍是有效首次基线。若没有执行者会话中的直接用户消息，
   Plan 中“用户在执行中明确修订”的表述应改为“独立验收采纳”，不得伪造授权来源。
2. **保留 v23-v28、全部费用和 v28 有效失败为只读事实。** 入口修复不得重写 lock、ledger、raw result 或公开结果，
   也不得因 5/10 成绩重跑。
3. **本轮不合并、不推送、不归档分支。** 继续遵守用户给本任务的 Git 边界；整改通过后仍由用户决定集成动作。

## 已核验证据

- execution worktree `1ec5d9a...`、results worktree `26a1d90...` 与 main 在审查开始时均干净；Local/Codex 产品源码
  未被本任务修改。
- v28 lock SHA-256 `a9567cb0...f7880b` 与公开 baseline 绑定一致；40 条正式 result 为 RONDO 30 / Codex 10，
  顺序为每题三条 RONDO 后一条 Codex，20 pass / 20 reward 0。10/10 common valid，双方均 5/10，`sigma=0`、
  `base_delta=0`、`delta=0`，无条件题。
- v27 wire 的 4 次请求与 12 个产品请求、v28 wire 的 4 次请求与 400 个产品请求均为 `usage_priced`、
  `usage_valid=true`、`settled`；累计 `$9.412888` 与 task envelope 六个闭合 identity 一致，未发现选择性重跑或未结算请求。
- execution active pointer 为 `null`，任务 envelope `active_identity=null`、`hard_stop=false`；v28 state 为 41 completed、
  280 skipped、0 running。公开资源记录满足门限；未额外启动 Docker、Cargo 或真实 API。
- 审查者只运行了相关 Python 单测 122/122，覆盖 task budget、formal entry、baseline/recovery 与 result publication；
  `git diff --check` 通过。默认入口在审查沙箱使用 `XDG_RUNTIME_DIR=/tmp` 后返回
  `{"active_lock": null, "paid_requests_sent": 0, "status": "idle"}`。未运行全 workspace、CI、Docker 或真实 API。

## 复验边界

修复后只需证明：新 Local commit/bundle 与新任务预算能在不改常量、不覆盖 Plan 051 envelope 的情况下，经统一入口完成
零 API prepare/identity/preflight 编排；`passed` 和 `failed` 都能闭合/退役；默认入口仍零 API；现有 v28 lock/result
仍可加载并保持字节不变；相对上一正式基线有简洁输出。只跑直接相关单测和无 API 演练，不重跑 v28、Docker 正式任务、
全 workspace 或其他未授权范围。
