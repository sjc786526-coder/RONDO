# Plan 022 第四次独立验收

时间：2026-08-14 03:32 PDT
审查对象：`5cf3c44d5508389c9b18b01d1157bc2b1864ebc7`（父提交 `20b8e7874635b12e19a2c12ba4d3f9be1eb2d2de`）
分支：`worktree-023-rondo-multi-bootstrap`
结论：**实现与测试合同通过；交付有条件通过。合并前只需完成三处文档同步，不需要再次修改实现或重跑重型测试。**

## 1. 验收范围与边界

本轮只复验上一轮明确指出的相邻缺口，并检查与这些修复直接相连的生产入口：

1. publication 在任何持久化动作前是否绑定真实冻结 `CampaignIdentity`；
2. campaign、continuation、result digest 与 aggregate 是否统一经过完整 tracked record/private summary 校验；
3. 私有摘要缺失、篡改或目录缺失是否 fail-closed；
4. bool 是否还能冒充 schema version 或 profile 数字；
5. Plan 决策 011、精确复制合同、提交范围和当前文档是否一致。

未把审查扩展为新的数据资产审计或设施重构，也未运行 Cargo、Docker、真实 no-API 双侧执行、API、模型或付费测评。

## 2. 上轮问题闭环

### 2.1 冻结 campaign 身份已在落盘前绑定

通过。`CampaignIdentity.validate_publication_context()` 逐项绑定 campaign id、lock SHA、schema、taskset、catalog、类型严格的 selected profile、product、timeout 以及 slot 对应的 run/side/round/attempt。成功与失败 publisher 均要求调用方传入真实冻结 identity，并在创建有效持久化结果、写私有摘要及 `finalize()` 前完成校验；pair 路径则明确拒绝 campaign identity。

真实 campaign CLI 入口从同一冻结 identity 生成 publication context，并在成功、失败两条路径传入该 identity。独立变异探针覆盖 RONDO/Codex、成功/失败以及 lock、product、profile、slot、run 篡改，共 20 个场景全部拒绝，`ArtifactWriter.finalize()` 调用数为 0；错误产品探针也确认没有生成 tracked index 或私有目标目录。

关键位置：

- `eval/rondo_eval/terminal_bench/baseline.py:499`
- `eval/rondo_eval/terminal_bench/results.py:417`
- `eval/rondo_eval/terminal_bench/results.py:626`
- `eval/rondo_eval/terminal_bench/baseline_cli.py:2365`

### 2.2 durable reader 与 aggregate 恢复已统一闭环

通过。`read_validated_run_records()` 统一执行完整 tracked record 校验和版本化 private `run-summary.json` 校验，同时保留原始 JSONL 字节供 digest 使用。campaign、continuation 和 result digest reader 均复用该入口；aggregate 在生成或恢复终态前重新读取并验证这些来源，不再依赖两份 aggregate 自洽或缺少来源的早退。

独立探针确认 campaign、continuation、result digest 三个入口面对无效/缺失私有摘要时均 fail-closed。新增回归覆盖私有摘要缺失、内容篡改及整个 artifact tree 缺失。现存历史 `runs.jsonl` 244/244 仍可由完整 reader 读取；这些历史行均无新 private marker，兼容边界未被回填或改写。

关键位置：

- `eval/rondo_eval/artifacts.py:903`
- `eval/rondo_eval/artifacts.py:938`
- `eval/rondo_eval/terminal_bench/baseline_cli.py:2558`
- `eval/rondo_eval/terminal_bench/baseline_cli.py:2598`
- `eval/rondo_eval/terminal_bench/baseline_cli.py:2923`
- `eval/rondo_eval/terminal_bench/baseline_cli.py:3028`

### 2.3 类型严格性已闭环

通过。record、private summary、auto-review schema version 均显式拒绝 bool；冻结 selected profile 使用递归类型严格比较，`True` 不再等于 `1` 或 `1.0`。相关负向回归通过。

### 2.4 相邻遗漏审查

未发现新的 Blocker、Major 或需要扩大设施的实现问题。publication、durable reader、journal/private summary 与 aggregate 的生产链已形成足够且轻量的 fail-closed 边界。

## 3. 独立验证

本审查实际运行并通过：

- 四个直接相关 Python 模块：234/234，0 fail；
- publisher 额外定向：`test_terminal_bench_results` 56/56、`test_terminal_bench_baseline` 52/52；
- durable reader/aggregate/bool 独立定向：有效用例 6/6；
- 历史 durable index：244/244 可读；
- 错误冻结产品与错误私有摘要的独立复现探针：均在持久化/聚合前拒绝。

执行者报告但本轮未重复运行：完整无 API eval 610/610、`just eval-lock` 85 packages、Local/Multi watchdog helper 各 9/9。它们与本轮改动没有新的重型复验必要性。

## 4. Git、复制与决策 011

- HEAD 与父提交关系正确，worktree 在写本报告前受跟踪状态干净；未合并、未推送。
- `20b8e787..5cf3c44` 自身 `git diff --check` 通过。
- `6611683..5cf3c44` 排除 `multidev/**` 后 `git diff --check` 通过。
- 完整 Plan diff 的 12,707 行诊断仍全部来自 419 个精确复制文件；没有诊断位于 `multidev/**` 之外。
- `mydev/` 与 `multidev/` 各 6,011 个 tracked 条目，相对路径、Git type/mode/blob 及工作树字节逐项相同；六类排除残留不存在。
- 决策 011 已由用户采纳并写入 Plan。该窄例外在“非 `multidev/**` 全部干净 + `multidev/**` 全量精确等同 + 禁止改写复制内容或用 `.gitattributes` 掩盖”的边界内成立，不再是验收阻塞。

## 5. 合并前仅需修正的文档

以下不影响实现验收，不需要重跑代码或重型门禁，但属于当前事实源，应在合并前修正：

1. `doc/WBS/multi-agent-trusted-evidence.md:7` 仍写“实现与两轮独立验收修复”，应改为本轮后的准确状态，并在本次验收完成后表述为“独立验收通过、待合并”；
2. `plan/022-rondo-multi-product-baseline-execplan.md:165,169` 仍写“提交当前任务分支后停止”和“只剩提交当前修复”，但 `5cf3c44` 已提交；应改为验收通过、等待合并的冻结状态；
3. Plan 完成标准 `:40` 的“所有非 `multidev/**` 手写差异”应删去“手写”，改成“所有非 `multidev/**` 差异”，与决策 011 和实际执行的全量门禁完全一致。

这些是一次文档-only 收口；完成后只需 `git diff --check` 和状态核对，无需启动新一轮实现审查。

## 6. 工作区与交付提醒

主工作区 `main`/`origin/main` 仍为 `d84632fb74dbaad0b4b43c047d292dc46450bc77`，但主工作区当前有用户自己的 `AGENTS.md`、`CLAUDE.md` 修改。本审查只查看了 Git 状态，没有读取、覆盖或改动它们。任务分支也改过这两个文件中的 watchdog 路径，后续合并必须显式保留并协调用户修改，不得用覆盖、回退或 stash 处理。

ignored 现场保留约 20G Multi target、既有 build metrics、uv cache 和 `__pycache__`；未发现正式 Multi runtime bundle。它们均未作为本次完成能力证据，也未清理。

## 7. 最终判定

上一轮全部技术 finding 已闭环，未发现新的实现级阻断。Plan 022 可判定为**实现验收通过、文档收口后可合并交付**。文档三处小修与主工作区用户改动的安全合并是剩余交付动作；Cargo、Docker、真实 no-API/API/模型测评不属于本轮复验门禁。
