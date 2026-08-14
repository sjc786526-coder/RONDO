# E-B8 修复后三次验收审查（`d34d4d7` → `7a37cdf` 实机更新）

## 结论

**未通过，E-B8 仍为 blocked。**

`d34d4d7` 对上一轮五项问题的定点修复均已实质落地。之后获授权的无 API Docker 冒烟首次证明冻结双侧在
`terminal-bench/fix-git` 首个 main 请求上的五个稳定分区全部对称，并暴露、修复了两个真实运行问题
（`d6958f8`、`2b8fda9`）。这些新证据显著提高了共享 catalog 与 producer 主链的可信度，但没有改变总体判定：
把“生成 v7 identity → 产出全角色/全任务 receipt → 启动正式 worker”串成生命周期后，仍有 2 项 blocker；另有
1 项不影响 fail-closed、但会使 receipt 批次无法重试的 medium 问题。

这些都属于现有入口的实践正确性，不需要新增签名、可信审计、鉴权体系或统计框架。

审查覆盖 `1f288b3..7a37cdf`，并回看 E-B8 的 identity、producer、paid proxy、worker、重复与聚合生产路径。
除本日志外未修改 E-B8 实现、测试、WBS、plan 或冻结历史。

## Docker 实机验证后的当前状态

Docker 授权已执行完毕并结清。由于仓库当前最高只有 v22/schema v6，active pointer 为 `null`，且没有 pilot 后冻结的重复合同
与单独授权 cap，本次没有也不应创建正式 v7 identity。Claude 使用字段均来自真实 catalog、v22 profile 与 fix-git 镜像的
一次性合成 v7 identity，直接调用 `capture_side_requests()` 完成 RONDO/Codex 双侧实机冒烟；没有创建 lock、registry、ledger、
run ID、campaign 目录或真实 API 请求。

实机证据确认：

- 两侧首个 main 请求的 `sampling_contract`、`tool_specs`、`instructions`、`output_schema`、`stable_input_prefix` 全部对称；
  历史 161-token catalog 不对称所在的 `stable_input_prefix` 本次一致。这是共享 8-model catalog 消除原不对称的首次双侧实机证据。
- 上游 `be6e8eac:codex-rs/models-manager/models.json` 与 RONDO
  `cb652e14:mydev/codex-rs/models-manager/models.json` 的 blob 均为 `fef0db08…`，来源字节相同。
- 实跑首次因 checkout dirty 得到 `eval harness checkout is dirty`，与下述 BLOCKER 1 的生命周期分析独立吻合。

实跑暴露并已修复：

1. `2b8fda9`：`_validate_stub_projection()` 原来读取不存在的 `spec.image_digest`，并错误地从 spec 读取 seccomp/catalog；
   现改为真实 `RunSpec.task_id/task_image_digest/provider` 与 request 上的 seccomp/catalog 字段。修后双侧冒烟通过。
2. `d6958f8`：`_unescape_mountinfo()` 原来会把合法 `\134` 解成反斜杠后再拒绝；现按 `proc(5)` 在原始字段上解析三位
   八进制转义，并保留对短转义、非八进制与 NUL 的拒绝。该问题只影响原生 Docker mountinfo 分支；现有 recipe 传入
   PowerShell probe，并未被它阻塞。

资源结算记录为镜像 26/11.5GB、构建缓存 13.22GB、容器 0 均无增量；Windows `C:` 196.2 → 196.1 GiB（约 -72 MiB）。
本次创建的 3 个 work 目录和 1 个 metrics 目录已清理，未清理其他 Docker 或项目对象；全程零真实 API、零付费、零真实模型。

## 已确认有效的修复

1. 正式 `terminal-bench/<task>` ID 已贯通 receipt 产出、加载与 seed；路径使用完整 task ID 摘要，不再只取 leaf。
2. `just eval-b7-preflight-receipts` 与 `preflight_producer.py` 已形成真实入口；stub 与付费路径复用
   `campaign_terminal_bench_request()` 和 `project_shared_model_catalog()`；worker 在 wire canary 前一次性加载全部 receipt。
3. successor 只生成 schema v7，continuation 恒为空、prior 为 0、cap 显式传入；catalog、task/image 与 provider profile
   在写 lock 前核对；5/7/9 次重复的 run-ID 区间按真实 slot 总数校验。
4. proxy 409 已优先返回具体分区原因；双向差异触发重复、三层 assessment 与最终多数聚合未发现回退。
5. `eval/locks/`、`eval/results/`、`mydev/`、`codex-source-code/`、`eval/uv.lock` 相对 `e23d82f` 无改动，
   `multidev/` 不存在。
6. `2b8fda9` 对真实 RunSpec/request 字段的修正与 producer 的实际对象布局一致；实机修后路径已走通。
7. `d6958f8` 的 mountinfo 解码对合法 Windows 9p 来源与非法转义的处理均有窄单测，未扩大 Docker 计数器架构。

## 未闭合问题

### BLOCKER 1：successor 的 harness commit 形成不可满足的自引用生命周期

`generate_successor_lock()` 先要求工作树干净，并要求 comparison 中的 `eval_harness_commit` 等于当前 `HEAD`；随后它在同一
工作树新增 tracked campaign lock，并改写 tracked active pointer。由此产生两种都不可执行的状态：

- 不提交 identity：工作树已脏，`preflight_producer.main()` 和正式 worker 的 `validate_eval_harness_checkout()` 立即拒绝。
- 提交 identity：`HEAD` 从冻结的 `H` 变为 `H2`，但 lock 内仍是 `H`。producer 只检查“当前 checkout 干净”而没有把返回的
  `H2` 与 identity 比较；正式 worker 也直到 `_execute_task_slot()` 才调用
  `identity.require_declared_conditions(eval_harness_commit=H2)`。这发生在 oracle 与 wire canary 之后，因此可能先产生 wire
  费用，再以 harness drift blocked。

当前没有一种正常 Git 状态能同时满足“active v7 lock 已存在、工作树干净、HEAD 等于该 lock 生成前冻结的 HEAD”。
这使唯一 successor 入口产出的 campaign 无法进入正式 task 执行。现有回归只分别测试生成时比较和 task-slot 漂移拒绝，
没有覆盖生成后的完整生命周期；本次实机在未提交修复存在时被同一 clean-check 拒绝，进一步证明该条件会真实生效，
但没有解除 commit 自引用。

最小修正应消除 commit 自引用，例如把 harness 身份定义为排除 campaign lock/pointer 的已提交代码投影，并在 worker 启动、
wire canary 之前核对；不应靠隐藏脏文件或手工伪造 commit 绕过。

### BLOCKER 2：stub producer 只冻结 `main`，合法 Guardian 请求必被付费门禁拒绝

`preflight_producer._terminal_sse()` 第一次响应就返回普通 assistant message，不产生 tool call；因此真实二进制的 stub 轨迹只会
发出首个 main 请求。`_requests_by_role()` 也只要求存在 `main`，`PreflightReceipt.validate()` 接受任意非空角色子集。

但正式 adapter 明确启用 `approvals_reviewer="auto_review"`，campaign profile 允许 Guardian 请求；付费 proxy 对每个实际请求都
使用 `SymmetryPreflight(require_expectation=True)`。所以只含 main 的 receipt 一旦遇到正常 Guardian review，会在预留与出站前
以 `preflight_expectation_missing` 拒绝。结果是配置中合法、且比较本来要保留的审批轨迹被设施机械截断。

现有测试恰好把缺口的两半分别固化了：

- `PreflightProducerTests.test_it_writes_one_bound_receipt_per_task` 用注入 capture 生成仅含 `main` 的成功 receipt；
- `PreflightReceiptTests.test_an_uncovered_request_is_refused_under_require_expectation` 证明未冻结的 `guardian` 必然被拒。

producer 应通过真实、受控的 stub 轨迹冻结所有付费路径允许出现的角色合同（当前为 main 与 Guardian），并让 receipt 对所需角色
集合 fail-closed；不能用人工构造 Guardian JSON 代替冻结二进制的实际请求。

本次 Docker 冒烟只捕获并比较了首个 main 请求，结果虽然对称，但没有触发 Guardian；因此它补强了 main 合同证据，
没有覆盖或推翻本 blocker。

### MEDIUM：多任务 receipt 产出失败后留下不可重试的半批次

`produce_preflight_receipts()` 每完成一题就立即发布最终 receipt。若后续任务不对称或执行失败，前面文件保留；再次执行从第一题
开始，`_atomic_receipt()` 又以 `preflight receipt already exists` 拒绝。单题测试只证明“当前题不对称时不写”，没有覆盖批次中途失败。

离线注入复现：两题中第二题不对称后，第一题的 `fix-git-fe7a9b10fec7.json` 已存在；把两题都改为对称后重试，立即得到
`PreflightProductionError: preflight receipt already exists`。这不造成 fail-open，但一次昂贵的双侧 Docker 预跑无法通过正式入口恢复。
采用批次成功后再发布，或对已存在且绑定/内容完全一致的 receipt 做幂等续跑即可；无需引入事务或审计平台。

## 尚未完成的测试与验收

1. **正式 receipt 产出未运行**：没有 active v7 identity，未执行 `just eval-b7-preflight-receipts` 的正式全任务产出，
   也没有生成可供 worker 消费的 receipt 文件。这不是 Docker 权限问题；pilot 后重复合同、cap 授权与 lifecycle blocker 均需先处理。
2. **Guardian 合同未实机捕获**：本次 stub 首轮立即结束，只验证 main；没有证明两侧 Guardian 的五个稳定分区对称，
   也没有证明 main+Guardian receipt 能被 paid proxy 完整消费。
3. **identity 到 worker 的入口级生命周期未验收**：没有覆盖生成/提交 v7 lock、产出 receipts、worker 在 wire 前核对 harness
   与全部 receipts 的完整路径；BLOCKER 1 仍使该路径不可满足。
4. **全任务与批次恢复未验收**：Docker 只跑 fix-git 一题，没有跑完整 canary catalog；第二题以后失败时半批次不可重试的问题未修。
5. **`2b8fda9` 缺少对象形状回归**：提交本身没有新增测试；568 项中的新增 3 项都来自 mountinfo。
   实机冒烟证明修后当前形状可运行，但仍应补一个使用真实 `PreparedTerminalBenchRun`/`RunSpec` 字段的窄回归，避免再次由假对象掩盖字段漂移。
6. **mountinfo 修复未做原生 Docker 分支实机验收**：现有 recipe 走 PowerShell probe，`d6958f8` 当前证据是 3 项 pure 回归；
   它不阻塞 E-B8 现有入口，因此无需为本工作包额外扩大 Docker 验收。
7. 未运行真实 API/provider、真实模型、正式 B7 campaign、oracle 或任何新的付费 identity；这些也不应拿本次合成身份冒烟替代。

## 验证记录

- 第三轮原审查 focused：`tests.test_fair_comparison` 77 项通过（禁 ambient proxy，仅使用 127.0.0.1 loopback）。
- Claude 实机修复后：`just eval-lock` 通过；`just eval-test` 568 项通过；无 Docker/API 资源残留。
- 本次报告更新复核当前 `7a37cdf`：`just eval-lock` 通过，`Resolved 85 packages`；`just eval-test` 通过，
  `Ran 568 tests in 71.193s`，`OK`。本次复核未再次使用 Docker。
- `git diff --check e23d82f..7a37cdf`：通过；受保护目录核对如上。
- 纯复现：main-only receipt 对 Guardian 得到 `preflight_expectation_missing`；两题批次第二题失败后留下一份 receipt，重试因
  `already exists` 失败；第三轮原审查的 clean checkout harness 校验曾返回当时 HEAD `d34d4d7`，而本次 Docker 首次尝试又以
  dirty checkout 被同一校验拒绝，两类状态共同支撑自引用分析。
- Docker 冒烟由 Claude 在单独授权内完成；本报告只核对其提交与记录。未创建/激活/消费 campaign、ledger 或 run ID；
  未读取 `.env.local`，未查看 holdout 正文、solution、verifier、日志或单题结果。

## 验收判定与最小后续

截至 `7a37cdf`，E-B8 仍不能作为闭环验收，也不应据此启动新的真实 campaign。下一轮只需窄修：

1. 解除 identity 文件与 harness commit 的自引用，并把实际 harness 条件校验前移到 wire canary 之前。
2. 让真实 stub producer 覆盖付费路径允许的 main/Guardian 角色合同，并补组合回归。
3. 让 receipt 批次可全量失败不落最终文件，或可安全幂等续跑；补 `_validate_stub_projection()` 的真实对象形状回归。

不需要扩大鉴权、可信审计、数据资产证明、统计显著性或 Multi 产品设施。
