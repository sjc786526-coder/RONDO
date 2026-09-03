# Plan 107 Local 产品配套补齐独立审查（2026-09-03）

审查对象：`worktree-110-local-product-support@5134a0074fe69fb725e9e42f3138d973d969dc14`，
基线 `main@58ed2f0385aa1e8d9466a79f9c2944714ca61315`。本轮只审查工作树候选，不合并、不推送，
也不以尚未触发的 GitHub Actions 代替本地 TUI 证据。

## 结论

- **验收不通过。** Local `/status` 实现和主要文档事实正确，但配置指南缺少一个会使新 Local provider 示例失效的
  配置层前提，工作树内另遗留一套任务时段生成的 `mydev/codex-rs/target/` 元数据目录。两项都违反 Plan 107
  的完成标准，须窄修后复验。
- **任务目标失败（当前提交）。** 这是可由窄文档修订和精确自产物处理闭合的提交状态，不是实现方向或功能方案失败；
  此外主线合入、推送和 Local 轻量 CI 本来就尚未授权，Plan 107 整体仍未完成。

## 审查发现

### 1. Local provider 示例缺少 user-level 配置前提

`doc/rondo-config.md` 开头仍绝对声称 RONDO 没有改变配置层规则，§3.2 随后给出
`[model_providers.my-local]` 与 `[auto_review].model_provider` 示例，却没有说明应写在哪一层。

当前 `mydev/codex-rs/config/src/loader/mod.rs` 的 `PROJECT_LOCAL_CONFIG_DENYLIST` 会从 project-local
`.codex/config.toml` 移除 `model_providers`，`sanitize_project_config()` 还会单独移除
`auto_review.model_provider`，并报告 `Ignored unsupported project-local config keys`。读者若把新示例放进项目层，
Local Guardian provider 不会被选中。因此这不是与本任务无关的历史说明缺口，而是 §3.2 本身缺失的运行前提。

整改只需明确该示例中的 provider 注册与选择应放在 user-level `${CODEX_HOME}/config.toml`，说明 project-local
层会被剥离并告警，并相应收窄开头“配置层完全未改”的绝对表述。无需改产品代码、Multi 章节或另建说明设施。

### 2. 工作树内遗留第二个 Cargo target

`mydev/codex-rs/target/` 当前占 16 KiB，创建于本任务执行时段，内容只有：

- `.rustc_info.json`（1718 bytes）；
- 空的 `nextest/local/` 目录。

它不是物理仓库根下获准复用的 `.codex/cargo-target/rondo-local`，与 Plan 107“不得在工作树新建第二套 target”以及
“无意外产物”不符。审查者本轮的受锁测试明确写入共享 Local target；发现该目录时，其时间戳早于审查测试。

应只精确移除这个任务自产目录并复核不存在，不得触碰共享 Local target、主工作区、其他缓存或任何父目录。
本轮审查没有删除授权，因此没有代为执行。

## 已确认正确

- `/status` 从当前有效 `Config` 读取 model、provider、reasoning effort、evidence directory 四项；无 override
  不增加行，`AutoReview` 显示已加载，`User` 明确显示当前未选用，`policy` 长文本不进入摘要。
- 实现没有修改 Guardian 配置解析、审批路由、provider、feature gate 或默认值；四个 Local status 文件与
  已验收的 Multi 对应版本逐字节一致，新增小模块符合 `card.rs` 的规模边界。
- 三态断言和代表性快照覆盖有效；候选只新增一份 status 快照，既有快照无漂移，当前没有 `*.snap.new`。
- `exec_command_repeat_guidance` 的默认值、Stage、提示性质、root/unified-exec 生效范围，以及 Local 本地推理
  “可配置 / 有工程接缝 / 未获审批用途质量资格”的分层说明与当前源码和既有结论相符。
- `multidev/`、根 CI、Local config/core/features、产品树继承文档与依赖均无改动；Multi 冻结状态保持有效。
- README、WBS、完成记录和实施日志总体按各自职责更新，没有提前声称 Local 全量通过、冻结或发布就绪。

## 独立复验

- `cargo fmt --all --check`（Local Rust workspace）通过；`git diff --check 58ed2f03..HEAD` 通过。
- 受锁且受看门狗保护的精确测试 `just --justfile mydev/justfile test -p codex-tui guardian_config`：
  **4 tests run / 4 passed**，3415 skipped；复用唯一 `.codex/cargo-target/rondo-local`。
- 三个核心 status 文件与 Multi 参考实现逐字节一致；范围检查确认 `multidev/`、`.github/`、产品树继承文档零差异。
- 根 `fmt-check` 的 Rust/Bazel 部分未报错，但 Python formatter 因审查沙箱不能写 `/home/sjc/.cache/uv` 而停；
  候选没有 Python 差异，执行者已有完整 `fmt-check` 通过证据，因此不把该环境限制判为产品失败。
- 未重跑 60 项 status 测试、全部 `codex-tui`、clippy 或全 workspace；现有 60/60 执行证据加本轮 4/4 精确复验
  足以覆盖本次代码风险。

## 代用户作出的决定

1. **不接受**把 `auto_review.model_provider` 的 project-local 限制整体延期。它直接决定新 §3.2 示例能否工作，
   本轮须作上述窄修；这不构成重写公共 Guardian 或改变 Multi 语义。
2. **延期**记录 `check_for_update_on_startup = false` 的公共配置差异。它不影响 L-1、Local 专属字段或 §3.2 的
   provider 使用路径，不阻断 Plan 107；本轮不为它新增 WBS 工作包或改动 Multi 文档语义。
3. **要求精确移除**任务自产的 `mydev/codex-rs/target/`，但不把该决定扩张成任何缓存或空间清理。
   因 Plan 107 明确没有删除授权，执行前仍需用户针对这一精确路径授权。
4. **接受**当前模块拆分、测试组合和未运行项。整改不涉及 Rust；完成文档修订和精确自产物处理后，只需格式、
   `git diff --check`、快照 pending/意外产物与范围复核，不要求重跑重型 TUI、clippy 或全 workspace。

整改提交完成后由计划制定者做一次窄复验；通过后再等待用户批准合并与推送。
