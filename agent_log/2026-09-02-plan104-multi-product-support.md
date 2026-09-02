# 2026-09-02 Plan 104 Multi 产品配套补齐（M-1 / M-2 / M-3）

工作树 `.claude/worktrees/106-multi-product-support`，分支 `worktree-106-multi-product-support`，
基线 `main@3f22453c`。本篇只记实施；本次授权止于工作树提交，未合并、未推送。

## 实质性改动

### M-1｜Multi CI 加入 `codex-team-state`

- `.github/workflows/ci.yml`：Multi 的 `TEST_PACKAGES` 由
  `codex-config / codex-features / codex-publication-critic`
  扩为再加 `codex-team-state`，注释同步说明两个方向 3 crate 都不碰 V8、不碰 core。
- `doc/ci-pipeline.md` 三处同步：不变量 1 的措辞、§2 的 package 表（改成两行小表列出两个 crate
  及其依赖）、§6 的本地复现命令块（**两条产品线的 Gate 3a 选包已经不同，原来只给 mydev 命令 +
  "或 multidev/justfile" 的写法会误导，改为显式给出两套**）。
- §3 的耗时表加了一条诚实标注：那批数字实测于该 crate 入 CI 之前，增量未实测。

### M-2｜Multi `/status` 显示 Guardian override

- 新增 `multidev/codex-rs/tui/src/status/guardian.rs`（约 60 行）。
  没有写进 `card.rs`：该文件已 945 行，超过 `multidev/AGENTS.md` 的 800 行门槛。
- `card.rs` 只加三处窄改动：`guardian_config: Option<String>` 字段、`push_label`、渲染行
  （位置在 `Permissions` 与 `Agents.md` 之间）。
- 覆盖项取自当前有效 `Config` 的四个字段：`guardian_model_config`、
  `guardian_model_provider_config`、`guardian_reasoning_effort_config`、`guardian_evidence_dir`。
  `guardian_policy_config` 不进摘要（是长文本策略，不是标识性配置）。
- 三态：
  - 无任何 override → **不加行**，既有快照全部保持不变（已实测）。
  - `AutoReview` → `loaded for reviewer auto_review (model x, reasoning effort y, ...)`
  - `User` → `loaded, unused by reviewer user (model x, ...)`
- 每项值按 48 列截断（字符串走 `truncate_text`，证据目录走既有 `format_directory_display`）。
- 测试落在既有 `status/tests.rs`：三态断言各一，代表性快照一份。
  把原 `permissions_text_for` 的抽取逻辑提成 `status_field_text_for(config, label, width)`，
  两个取值函数各自一行调用，没有新增重复代码。

### M-3｜根 `doc/rondo-config.md`

- 新建，只写 RONDO 相对冻结上游 `v0.147.0` 的**增量**：公共 Guardian 的 `[auto_review]` 四个新字段
  （两条产品线一致），以及 Multi 的 `team_state_enabled` / `durable_team_enabled` /
  `publication_critic` 子表。上游通用配置只给链接，不重建第二份手册。
- `README.md` 两处入口："从源码构建"末尾的配置段落，以及仓库结构树的 `doc/` 注释。

## 疑难问题

### 一、"配置已加载"和"某次审批用了它"必须分开说

`core/src/guardian/review.rs` 里 review 模型的解析顺序是
`[auto_review].model` → 模型目录 `auto_review_model_override` → provider 默认 review model，
都没命中目录时还会退回父会话模型 slug。也就是说**配置里写的 slug 不一定是某次 review 实际用的模型**。

所以状态行的措辞只说 `loaded`（配置已加载）+ reviewer 是谁，不说"已生效""正在使用"。
两态都点名 reviewer，用的是 config 里的字面值（`auto_review` / `user`），跟用户会写进 `config.toml`
的东西对得上。

### 二、80 列放不下太多 override

`Guardian config` 标签 15 列，value 只剩 56 列。四项全配时必然被卡片按宽度截断
（和 `Directory` 一样，是卡片既有行为）。因此快照测试用单项 override 保证不截断，
多项组合由全宽（`u16::MAX`）下的精确断言覆盖——这也是 `guardian_config_text_for` 用全宽渲染的原因。

### 三、`evidence_dir` 的证据是未脱敏的

`core/src/guardian/evidence.rs` 的模块文档写得很清楚：bundle 归一化只剥结构性和 provider 私有的
传输字段，`instructions` / `input` 里父轮累积的任务上下文原样保留。配置指南里把这点单独列了一节，
明确要求指向私有、git-ignored 目录。

## 验收结果

本地定向门禁（全部经根共享构建锁与资源看门狗，target 为物理仓库根下的
`.codex/cargo-target/rondo-multi`，未新建第二套 target）：

| 项 | 结果 |
|---|---|
| `just --justfile multidev/justfile fmt` | 通过 |
| `just ... test -p codex-tui -p codex-team-state` | 见下方最终一轮 |
| `cargo insta pending-snapshots` | `No pending snapshots.` |
| 新快照人工审读 | 已逐行确认：只新增一行，其余字段仅因标签列加宽 1 列而整体右移 |

**未运行 / 不在本次范围**：

- 推送后的轻量 CI 未触发，Actions 日志里 `codex-team-state` 的非零测试数**尚未核对**。
  M-1 的最终验收要等合并推送后才能完成，本任务不得表述为已通过。
- 全 workspace 测试不属于本任务（`test-with-codex-v8-conservative`）。
- 未跑 Local（`mydev/`）任何测试：本任务未触碰 Local 代码。
