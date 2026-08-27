# Plan 095：独立审查返修

日期：2026-08-27 ｜ worktree：`.claude/worktrees/095-publication-critic-cloud-reference-scorer`
｜ 返修基线：`e0f7470` ｜ 审查报告：`agent_log/2026-08-27-071711-plan095-review.md`

审查判定第一批次「验收不通过 / 任务目标失败」，列出 1 High、3 Medium、2 Low。全部 finding 复核后确认成立，逐项修复。

## 1. High：请求模型没有绑定到声明的 model identity（已修）

**复核**：成立。`validate_cloud_identity` 只校验 tokenizer/模板/投影/前缀/domain，没有比对
`provider.model` 与 `identity.model.model.name()`。因此一个 descriptor 可以请求模型 A、声明模型 B；service 的
equality check 两侧都是 B，A 的分数会被静默贴上 B 的身份。`provider_managed_model_identity` 的 `revision` 又是自由
字符串，正式值 `reference` 也没有表达“不可验证”。

**修复**（`cloud_config.rs`）：

- `validate_cloud_identity` 增加交叉校验，要求 `identity.model.model.name() == provider.model`。
- 新增冻结常量 `PROVIDER_MANAGED_MODEL_REVISION = "serving-revision-unverifiable"`，并要求 model 组件的 revision 恒等于它。
  chat-completions 请求只带 model 名、不带 serving revision，provider 也不返回，所以身份直接这么说。
- 公共构造函数签名收窄为 `provider_managed_model_identity(model: &str)`：调用方无法再自选 revision。

**顺带收紧**（`cloud_scorer.rs`）：交叉校验成立后，`observed_model` 改成单一规则——回复里带 model 就必须等于请求的
model，否则一律是 drift；`served_model` 模式只决定「回复完全不带 model」是否可接受。此前 `ProviderManaged` 模式会
无条件返回声明身份，即使 provider 明确回了另一个模型。

**新增反例测试**：`cloud_identity_cannot_claim_a_verified_tokenizer_or_local_template` 增加两条——
provider 请求 `example-cheaper-model` 而身份声明 `example-cloud-model`，以及 model revision 写成
pinned 风格 `2026-08-01`，两者都必须是 `DishonestIdentity`。
`served_model_drift_becomes_a_typed_model_identity_mismatch` 改为在 `echoed` 与 `provider_managed` 两种模式下都断言
`code=identity_mismatch`。

## 2. Medium：retry 最坏预算公式少算递增 backoff（已修）

**复核**：成立。运行时在第 `k` 次失败后 sleep `backoff × k`，`n` 次尝试的总退避是 `backoff × (n−1)n/2`；校验只算了
`backoff × (n−1)`。`n ≥ 3` 时会放行实际超出声明 job deadline 的配置。

**修复**：`worst_case_budget_ms` 改为 `request_timeout × n + backoff × (n−1) × n / 2`（`(n−1)n` 必为偶数，整除精确）。
保留递增退避而不是改成固定值——递增退避对限流更有用，且问题只在校验一侧。

**修复暴露的既有问题**：单测 fixture 自身 `8,000 × 3 + 400 × 2 = 25,200 ms` 已越过 25,000 ms 的 production job deadline，
旧公式算成 24,800 ms 才放行。fixture 的 `retry_backoff_ms` 改为 300（24,900 ms）。这正是该 finding 的实证。

**新增边界测试**：`the_retry_budget_accounts_for_every_increasing_backoff` 用 `n = 2/3/4` 各一组恰好通过与恰好超出的
参数，锁住三角和。

## 3. Medium：缺少真正的在途取消与 active shutdown 证据（已修）

**复核**：成立。原 cancel 断言在调用前就 cancel，只覆盖快捷路径；cloud 的 shutdown 都发生在请求完成之后。

**修复**（`tests/cloud_process.rs`，复用既有 delayed loopback fixture，没有新增框架）：

- `cancelling_an_in_flight_provider_call_drops_its_retry_and_frees_the_backend`：provider 第一次回复延迟 30 s，
  per-attempt timeout 300 ms、`max_attempts=2`、backoff 100 ms——不取消的话约 400 ms 后必然出现第二次 provider 请求。
  新增 `FakeProvider::wait_for_requests`（wiremock 在应用响应延迟**之前**记录到达的请求，所以这个等待返回时调用仍在途中），
  等 provider 确认收到后再 cancel，断言 `Cancelled`、等 800 ms 后 provider 请求数仍为 1（retry future 确实被丢弃）、
  下一次调用健康返回 `PASS`。
- `shutdown_during_an_in_flight_provider_call_exits_within_its_bounded_budget`：在途请求期间由第二个 client 发
  shutdown（避免被调用方自身的 shutting-down 标志短路），断言在途 review 得到 typed `ShuttingDown`、进程在
  graceful/force 预算内正常退出、整个过程短于 per-attempt timeout，且 shutdown 后 provider 没有新请求。

既有通用 queued cancel / job timeout / forced shutdown 测试保持不动，没有复制 Plan 055 的整套矩阵。

## 4. Medium：Bazel lock 门禁（已闭合，无漂移）

**复核**：`MODULE.bazel` 确实把 `//codex-rs:Cargo.lock` 作为 `crate.from_cargo` 的输入，所以「依赖 crate 已存在」不足以
证明无漂移，必须实跑。

**执行**：机器上 `bazel` 不在 PATH，但 `~/.cache/bazelisk` 已缓存与 `.bazelversion` 完全一致的 bazel `9.0.0`，因此
**没有下载任何东西**，只把该缓存二进制软链到任务局部 `/tmp/rondo-plan095-bazel/bin` 并加进本次命令的 PATH，
经仓库共享构建锁跑既有入口 `just bazel-lock-update`（`bazel mod deps --lockfile_mode=update`，无 `--config`，
因此不接触 BuildBuddy 等外部服务）。

**结果**：命令 `status=0`，`MODULE.bazel.lock` **逐字节未变**。随后直接跑检查模式
`bazel mod deps --lockfile_mode=error`，同样 exit 0。结构性原因是该 lock 的 `moduleExtensions` 只记录 6 个扩展
（`aspect_tools_telemetry` / `protobuf` / `pybind11_bazel` / `rules_kotlin` / `rules_python` ×2），
`@@rules_rs//rs:extensions.bzl%crate` 不在其中，所以 `Cargo.lock` 变化不进入该 lock。

**副作用**：跑完 `bazel shutdown` 关掉服务器并确认无残留进程；`~/.cache/bazel*` 四个缓存目录体积前后一致
（1.2G / 8.0K / 840M / 2.8G），Windows `C:` 余量 51.3 GB 前后不变；任务局部 `/tmp/rondo-plan095-bazel` 已删除。
未安装全局工具、未改 PATH 以外的任何机器配置。首次误用 bazelisk 尝试拉 9.2.0 时下载失败（EOF），未留下残留文件。

## 5. Low：测试计数与费用记账更正（已修）

- 实际计数：cloud 单测 12 项（`cloud_config_tests` 9 + `cloud_template_tests` 3），cloud 集成测试 11 项，
  合计新增 23 项；crate 全量 `57/57`。第一批次日志写的「10 单测 + 8 集成」已按本批次实际的「11 + 9」更正，
  本批次再增 1 单测 + 2 集成。
- 费用改按**实际可能计费的 provider HTTP request** 计数，不再按阶段计。全任务累计 **11 次**：
  批次一 8 次（首轮 commissioning 2、裸请求诊断 1、第二轮 commissioning 2、clean smoke 2、负向对照 1），
  返修批次 3 次（重跑 clean smoke 2、重跑负向对照 1）。金额未知按 1 USD/次保守计 = **11 USD**，低于 50 USD 上限。

## 6. 文档中过满表述的更正

「backend deadline 总先于 service deadline 触发」是过满的：service 的 job deadline 在排队之前就开始计时
（`service.rs` 在取得 admission permit 后立即设定 deadline），排队等待也算在内，所以排队的调用仍可能先撞上外层
`ExecutionTimeout`。准确表述是：descriptor 校验保证 backend 自身的最坏预算装得进 job deadline，因此**立即开始执行**的
调用通常先收敛为 typed backend failure；service 的 deadline 始终是外层兜底，排队或外层取消时可以先发生。
ExecPlan、两份 WBS、`WBS-COMPLETED` 与相关测试注释均按此改写，测试只断言外层界限而不冻结哪一种 failure 获胜。

## 7. 返修后门禁

| 门禁 | 结果 |
|---|---|
| `just test -p codex-publication-critic` | `57/57` passed、0 skip（新增 23 项 cloud 测试，既有 34 项无回归） |
| `just clippy -p codex-publication-critic` / `just fmt-check` | 通过 |
| `just bazel-lock-update` + `bazel mod deps --lockfile_mode=error` | 均 exit 0，lock 无漂移 |
| `just test -p codex-core --lib -E 'test(publication_review)'` | 未重跑：本批次未改 crate 公共 API 形状（只收窄 `provider_managed_model_identity` 参数，`codex-core` 不引用它，`rg` 复核 `codex-core` 无任何 cloud 符号引用），且批次一已 `17/17` 通过 |
| 全 workspace | 未运行（按合同只跑受影响模块） |

**返修后真实 API 重跑**（审查判定「不要求重新付费跑真实 API」，但 model revision 字面量已变，原 descriptor 不再通过校验；
为免留下无法复现的证据，用最终代码 + 最终 descriptor 在全新 `/tmp` 空间重跑一遍，成本 3 次请求）：

| 步骤 | 结果 | 耗时 | usage |
|---|---|---|---|
| `ready` | ready | 9 ms | 零 provider 请求 |
| 正面合成 packet | `PASS` | 9,466 ms | prompt 935 / completion 970 |
| 反面合成 packet | `REWRITE` | 4,873 ms | prompt 873 / completion 432 |
| `shutdown` | accepted | 5 ms | — |
| 负向对照（不存在的 model） | `code=backend`、`kind=status status=400` | 792 ms | 单次尝试、不重试、错误正文未外泄 |

最终正式 descriptor 与批次一日志中的 JSON 只有一处差异：
`service_descriptor.identity.model.model.revision` 由 `reference` 改为 `serving-revision-unverifiable`。
请求 wire、cloud prompt、response 解析与 scalar 投影完全未变。

## 8. 副作用复核

- 主工作区、093 worktree 全程 clean；`.env.local` 与 `rondo.local.toml` 未修改；密钥只经既有严格 loader 取单个
  allowlisted 变量注入子进程。
- 所有 Cargo 与 Bazel 命令走仓库共享构建锁；`CARGO_TARGET_DIR` 为主物理根 `.codex/cargo-target/rondo-multi`。
  Windows `C:` 停止线仅在本任务命令上下文临时 30 GB。
- `/tmp/rondo-plan095-*` 三个临时运行空间（commissioning、两次 clean smoke、bazel 工具）已全部删除；
  未创建 `eval-data/publication-critic/plan095/`。未使用 Docker、GPU、RunPod、真实本地模型。
