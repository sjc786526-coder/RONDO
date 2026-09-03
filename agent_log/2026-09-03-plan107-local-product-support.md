# 2026-09-03 Plan 107 Local 产品配套补齐（L-1 / L-2）

工作树 `.claude/worktrees/110-local-product-support`，分支 `worktree-110-local-product-support`，
基线 `main@58ed2f03`。本篇只记实施；本次授权止于工作树提交，未合并、未推送。

## 实质性改动

### L-1｜Local `/status` 显示 Guardian override

- 新增 `mydev/codex-rs/tui/src/status/guardian.rs`。不写进 `card.rs`：该文件已 945 行，
  超过 `mydev/AGENTS.md` 的 800 行门槛，与 Multi 当时同一判断。
- `card.rs` 四处窄改动：`use` 一行、`guardian_config: Option<String>` 字段、构造时调用
  `guardian_config_summary(config)`、`push_label` 与渲染行（位置在 `Permissions` 与 `Agents.md` 之间）。
- 摘要取自当前有效 `Config` 的四个字段：`guardian_model_config`、`guardian_model_provider_config`、
  `guardian_reasoning_effort_config`、`guardian_evidence_dir`。`guardian_policy_config` 不进摘要
  ——它是长文本策略，不是标识性配置。
- 三态与 Multi 完全一致：
  - 无任何 override → **不加行**；
  - `AutoReview` → `loaded for reviewer auto_review (model x, provider y, ...)`；
  - `User` → `loaded, unused by reviewer user (model x, ...)`。
- 每项值按 48 列截断（字符串走 `truncate_text`，证据目录走既有 `format_directory_display`）。
- 测试落在既有 `status/tests.rs`：三态断言各一，代表性快照一份。原 `permissions_text_for` 的抽取逻辑
  提成 `status_field_text_for(config, label, width)`，两个取值函数各自一行调用。

### L-2｜根 `doc/rondo-config.md` 补 Local 节

新增 §3「RONDO Local 专属配置」，原「不在本文范围内的」顺延为 §4 并删掉"留待第二阶段补充"那条。
另有两处必要衔接：§1.4 由"RONDO Multi 的 `/status`"改成"两条产品线的 `/status`"，顶部口径行同步。
§1、§2 的 Multi 内容与结论未动。

章节内容全部先对当前 Local 源码核实过（见下方"疑难问题"一节的核实口径）：

- **3.1** `features.exec_command_repeat_guidance`：默认 `false`、Stage `UnderDevelopment`；
  只往 `exec_command` 的**工具描述文本**追加一段有界提示，不拦截也不改写命令；`shell_command` 恒不带；
  子智能体与 Guardian 审批会话恒定关闭。Stage 不拦截配置覆盖，但打开会触发上游的 under-development 警告。
- **3.2** 本地推理审批：说明"接缝存在、资格没有"。接缝就是上游既有 `[model_providers]` 加 §1 的
  `[auto_review].model_provider` / `model`，Local **没有**为此新增任何产品字段。两个运行前提写明：
  `wire_api` 只接受 `"responses"`，显式 provider 不继承父会话凭据。结论保持"保留为实验、未采用"。
- **3.3** 明确区分两条独立链路：产品读 `config.toml`；根 `rondo.local.toml` / `.env.local` 只被
  `eval/` 测评设施读，改前者不改变 CLI 行为。
- **3.4** Local 没有专属 TUI 面板；`[features.multi_agent_v2]` 这张表**是上游的、Local 也有**，
  Multi 独有的只是 RONDO 往里加的三个字段，而且该表 `deny_unknown_fields`，在 Local 写这些键是报错
  而非静默忽略。

`README.md` 的配置入口段落同步改成"公共 Guardian / Multi 专属 / Local 专属"三节结构。

## 疑难问题

### 一、Local 到底有哪些"专属配置"，不能靠推定

历史计划和 Multi 都不能作为依据。实际做法是拿 git-ignored 的上游只读快照
`codex-source-code/codex-rs` 与 `mydev/codex-rs` 逐文件比：

- `core/config.schema.json` 是最可靠的配置面比较物。整份 diff 只有三类：
  `[auto_review]` 的四个 Guardian 字段（两条线共用）、`features.exec_command_repeat_guidance`
  （**Local 独有**，Multi 没有）、`check_for_update_on_startup` 的描述与默认值。
- `features/src/feature_configs.rs` 与上游逐字节相同；`features/src/lib.rs` 的唯一 diff 就是那一个
  FeatureSpec。所以"Local 只新增一个专属配置字段"这句是可核对的，不是概括。

### 二、`wire_api` 已经不接受 chat completions

冻结基线的 `WireApi` 只剩 `Responses` 一个变体，写 `"chat"` 会得到显式"已移除"错误。这直接决定了
3.2 里"本地服务必须讲 Responses 协议"这句——纯 chat-completions 的本地服务根本接不进来。
这条不写清楚，读者很容易照着一份旧的 ollama 教程去配然后加载失败。

### 三、配置可达 ≠ 用途已获资格

3.2 是这次最容易写歪的一节。一条能写进 `config.toml` 的路径，加上历史上确实存在的工程证据，
很容易被读成"方向 2 可以用了"。所以这节把三件事分层写死：字段可以配置、工程接缝存在、
用途资格**没有**取得，并明确指回 README 的"诚实的结果"。方向 2 的最终结论一个字没改。

## 首次独立审查的两项窄整改

审查报告：`agent_log/2026-09-03-plan107-independent-review.md`。两项发现都成立，均为本次执行引入。

### 一、§3.2 的 provider 示例缺配置层前提（已修）

我原先把这条当成"与本任务无关的历史缺口"记录后延期，这个判断是错的：**是新加的示例本身制造了这个坑**。
`PROJECT_LOCAL_CONFIG_DENYLIST` 里 `model_providers` 是上游就有的，RONDO 额外把
`auto_review.model_provider` 也加进项目层剥离（`config/src/loader/mod.rs` 的 `sanitize_project_config`）。
读者若照示例写进项目层 `.codex/config.toml`，两个键都会被剥掉、只留一条告警，Guardian 仍用父会话 provider。

按审查裁定作最小修订，未改产品代码、Multi 章节，也未另建说明设施：

- 开头"配置层完全沿用上游"的绝对表述收窄为"只有一处例外"，写明 RONDO 新增的是
  `auto_review.model_provider` 的项目层剥离，并给出实际告警文案（**告警不是报错**）。
- §3.2 的示例块顶部直接标注必须写在用户级 `~/.codex/config.toml`，并把"必须放在用户级配置层"
  列为四个运行前提中的第一条。

### 二、工作树内遗留第二个 Cargo target（待授权处理）

`mydev/codex-rs/target/` 16 KiB，只含 `.rustc_info.json`（1718 B）与空的 `nextest/local/`。
**成因是我自己**：接受快照时直接跑了裸 `cargo insta pending-snapshots` / `cargo insta accept`，
没走 `just` 入口，因而没有继承看门狗导出的 `CARGO_TARGET_DIR`，cargo 探测 rustc 时在默认位置
落了这个目录。受锁的 `just test` 两轮都正确写进了共享 `.codex/cargo-target/rondo-local`。

教训：快照接受也要走受跟踪入口或显式带上共享 target，不能因为"只是读取 pending"就绕过。
Plan 107 明确没有删除授权，故本轮不自行删除，已向用户申请对该精确路径的删除授权。

## 留待另行立项的文档缺口

- `check_for_update_on_startup` 的默认值在 RONDO 改为 `false`（发布工程的 E-X2 窄例外），两条线一致。
  它是相对上游的真实配置差异，但 `doc/rondo-config.md` 目前没提；现在只记在 WBS / WBS-COMPLETED /
  `doc/cd-release-pipeline.md`。首次独立审查裁定该项延期，不阻断 Plan 107。

## 验收结果

- 格式：`just fmt`（`mydev/`，走受跟踪的 `scripts/format.py`）无改动产出。
- 定向测试：`just test -p codex-tui status::`，经根共享构建锁与资源看门狗，复用物理仓库根下唯一的
  `.codex/cargo-target/rondo-local`，未覆盖 `CARGO_TARGET_DIR`。
  - 首轮 60 tests run：59 passed、1 failed，唯一失败就是新快照 pending。
  - 逐行阅读 `.snap.new` 后按单文件精确接受（`cargo insta accept --snapshot <path>`），
    未整包 accept。
  - 复跑 60 tests run：**60 passed、0 failed**、3359 filtered out。非零执行成立。
- 既有无 override 的状态界面没有漂移：本次只新增一份快照，其余 20 份既有 status 快照全部原样通过。
- 全仓库无遗留 `*.snap.new`。
- 未运行：最终全 workspace、clippy、Docker、训练、测评、真实 API、真实本地模型、空间盘点或清理、
  tag 与发布。未读取 `.env.local` 内容。未实质修改 `multidev/`。

### 整改轮复验（文档改动，不含 Rust）

按审查裁定只做轻量复核，不重跑重型 TUI、clippy 或全 workspace：

- `just fmt-check` 退出 0；`git diff --check` 干净。
- 整改只改 `doc/rondo-config.md` 与本日志，Rust、快照与测试代码零改动，因此 60/60 的既有 TUI 证据继续适用。
- 全仓库仍无 `*.snap.new`；受跟踪差异内无意外产物。
