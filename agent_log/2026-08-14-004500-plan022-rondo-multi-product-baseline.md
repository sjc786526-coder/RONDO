# Plan 022：RONDO Multi 产品基线建立（工作包 2）

分支 `worktree-023-rondo-multi-bootstrap`，基线 `6611683`。全程无真实 API、无 Docker、无本地模型加载。

## 实质改动

### 1. 共享看门狗迁到仓库根

`git mv mydev/scripts/{with-build-lock.sh,build-watchdog-lib.sh} scripts/`，blob 与 mode
（`100755` / `100644`）保持不变，脚本内容一个字节没改。两处路径推导天生可迁移：`script_dir` 由
`BASH_SOURCE` 的 `dirname` + `pwd -P` 得到，`project_root` 由 git common dir 得到。

现行引用点全部改为根路径，**没有 shim、软链或兼容分支**：根 `justfile`（3）、`mydev/justfile`
（引入 `watchdog := justfile_directory() / ".." / "scripts" / "with-build-lock.sh"`，8）、
`runtime_bridge` 的 canonical wrapper 校验、`binary_freeze._validate_build_command`、`baseline_cli`、
`results._EVAL_HARNESS_PATHS`、三个测试文件、`AGENTS.md` / `CLAUDE.md` / `doc/development-environment.md`。
`eval/locks/*.json`、`agent_log/`、`doc/audit-snapshots/`、既有 plan 里的旧路径是冻结 provenance，未动。

共享 helper 的 9 项回归留在两棵产品树的 `.github/scripts/`，把 `parents[2]` 改成 `parents[3]`，
于是 Local 与 Multi 的 `just test-github-scripts` 各自显式调用根 helper，不再去找产品内已不存在的脚本。

### 2. `multidev/` 精确复制

清单来自 `git ls-files --stage -z -- mydev/`，内容取自工作树（因此天生带上一步的根看门狗路径），
逐条按 mode 写出、symlink 按 `readlink` 重建。结果 6,011 条：5,951 个 `100644`、59 个 `100755`、
1 个 `120000`（`codex-rs/vendor/bubblewrap/LICENSE -> COPYING`）。

完整性用两种方式各证一遍：`git ls-files --stage` 的 blob 与 mode 逐条相同；工作树的路径、文件类型、
mode 与 sha256 逐条相同，且 `git ls-files --others --exclude-standard -- multidev/` 为空。
WBS 点名的六个未跟踪残留目录一个都没进来（它们本来也没在本 worktree 物化）。

### 3. 默认关闭行为门

两棵树同源的 `codex-rs/core/src/config/config_loader_tests.rs` 新增两项：
`empty_config_leaves_every_auto_review_override_unset` 写一个空的 `config.toml` 到临时 codex home，
经 `ConfigBuilder` 真实加载后断言四个 guardian 字段全 `None`，并顺带断言 `approvals_reviewer` 仍是上游
默认 `User` —— 关闭态来自四项未配置，不是把 reviewer 挪走伪造的。
`configured_auto_review_populates_every_override` 是反向对照，防止断言因为字段被拆线而空转。
两项都把 cwd 指向临时目录，避免读到仓库自身的 project 层配置。

### 4. 产品身份贯通

`Product` / `product_layout()` 成为唯一映射，一处决定源码目录、Cargo target 前缀、`bin/` 命名空间与
`models-manager/models.json` 路径。身份从此贯通：binary freeze 的源码根 / target / legacy artifact /
code-mode bundle / runtime bundle、三种 manifest、`exec_v8_build`、bwrap 源树 spec、`cleanup`、
共享 model catalog 来源、campaign lock 的 catalog provenance、adapter 与 agent kwargs、`RunSpec`、
结果记录与归档 `run-summary.json`。`RunSpec.validate()` 交叉校验运行声明的产品与其冻结二进制的产品。

### 5. 默认关闭的结果合同

新增版本化 `auto_review_config` 块，记录该次运行**配置了什么**（未配置写 `null`），
**不是** provider/catalog 派生出的有效 Guardian 模型。Multi 四项全 `null`；Local 沿用既有公平合同
（`model` / `reasoning_effort` / `evidence_dir`，`model_provider` 两边都没配过）；冻结上游不写该块。
adapter 的 `-c` 覆盖与该块出自同一个 `auto_review_overrides()`，运行命令与记录状态不可能互相矛盾；
结果顶层与归档 `run-summary.json` 共用同一个 `_product_config()`，成功与失败发布路径不分叉。

## 疑难与判断

- **历史 build-command 兼容**。冻结的 seven-key 工件把完整 argv 写进了 manifest。若无条件给 Multi 与
  Local 都追加 `--product`，历史 Local build-command 的合同形状就会被改写。因此 build-command 中的
  `--product` 只在非 Local 时出现，Local argv 保持逐字不变；新 RONDO manifest（Local/Multi）显式写
  `product`，Codex 与历史 manifest 省略该键，历史缺键按 `rondo-local` 只读解释且不回填。
- **看门狗改根的已知代价**。`binary_freeze verify*` 会精确比对 build-command 里的 wrapper 路径。
  改根后，历史 Local/Codex bundle 的 `verify-runtime` 会因记录的是旧 `mydev/scripts/` 路径而不再通过。
  WBS §4.4 与 Plan 022 硬约束 5 明确要求「精确接受根脚本并拒绝旧路径」，所以这是预期结果而非回归。
  影响面有界：`pair.validate_manifest` 只比对 digest 与路径，`eval/locks/*.json` 的冻结 provenance
  与 bundle 字节都没改，本任务也没有跑任何需要 re-verify 的流程。要恢复可重验证性只能重新冻结 bundle。
- **`git diff --check` 与精确复制冲突**。`multidev/` 的 6,011 个文件全是新增行，其中 419 个上游文件
  自带行尾空白（TUI ASCII 动画帧、prompt markdown、apply-patch 的空白填充 fixture），因此 `--check`
  必然报警。已逐一 `cmp` 确认它们与 `mydev/` 原件字节相同。修掉就违反「精确复制」这条更强的硬约束，
  故保留原样。**手写改动部分**（`git diff --cached --check -- . ':(exclude)multidev/'`）是干净的。
- **继承的 Local 向脚本**。`multidev/scripts/verify_upstream_source_baseline.py` 里硬编码了
  `mydev/codex-rs/core/upstream-source-baseline.toml` 这个字符串，用于核对文档引用。作为精确复制的
  一部分保留；它不在任何 just 入口里，也不参与本次任何门禁。

## 验收

全部本地执行，无真实 API、无 Docker、无本地模型、无正式 campaign identity / run ID / 结果行。

| 门禁 | 结果 |
| --- | --- |
| `just eval-lock` | 通过（85 packages resolved） |
| 完整 `just eval-test`（等价命令，复用主仓库 ignored venv 跑本 worktree 源码） | 592/592 通过，0 fail、0 skip |
| 共享 helper `test_build_watchdog_lib`（mydev 入口） | 9/9 |
| Multi `codex-core` 默认关闭回归（经迁移后根看门狗） | `config::config_loader_tests` 80/80，含两项新门 |
| Multi `cargo build --locked -p codex-cli --bin codex`（经迁移后根看门狗） | 成功，`codex-cli 0.147.0` |

新增回归：binary freeze 的 7 项 Multi 布局/fail-closed 用例（含「Multi 不能落进 `bin/rondo/`」、
「不能复用 Local target」、「Multi bundle 当 Local 验证要失败」、「去掉 `product` 后按 Local 读」、
「上游侧拒绝产品身份」、「cleanup 只针对所选产品」）与 6 项产品 / `auto_review_config` 结果合同用例。
`test_terminal_bench_results` 的 fixture 拆成 `_ResultFixture` mixin，新旧两个套件共用而不重复执行。

两次带锁运行的看门狗均 `wrapper_status=complete`、`final_rc=0`、`stop_reason=none`、`cleanup_reason=none`；
项目占用峰值 43.6 GB（告警线 180 GB），Multi target 21.3 GB，swap 峰值 0，Windows `C:` 余量 209 GB。

**未运行**：Docker、no-API 双侧真实执行、真实 API、真实本地模型、全 workspace Rust 测试、
Local 侧 Rust 构建。`eval-data/bin/rondo-multi/` 仍为空 —— Multi 还没有冻结 runtime bundle，
因此本工作包不做也不能做任何 Multi 能力或退化结论。
