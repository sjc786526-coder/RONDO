# 2026-09-01 Plan 103 发布工程规划与 README 对外化

## 背景

用户目标是把 RONDO 跑通一次完整软件发布流程作为工程履历，而非推向生产。本批次只做规划与对外文档，
不实施任何构建、发布或产品源码改动。

## 实质性改动

1. **`README.md` 重写为对外门面版**：加入 fork 归属与非背书声明、实验性警告、双层结果表述
   （RONDO Multi 产品架构通过 / Publication Critic 判官未获质量资格）、负向结论公开、
   AI 驱动开发方式的主动说明、可复现的改动量统计口径。
2. **新建 `plan/103-release-engineering-and-cicd-execplan.md`**：14 项验收标准、12 条硬约束、
   15 条关键决策、9 条风险回退、五阶段路线图。

## 疑难问题

规划期做了五轮独立审查，每轮都发现真实阻塞项，且**全部属于同一类**——
"以为现成工具会替我做的事，它其实没做"。逐条核实证据后整改：

- `binary_freeze.py:1301` 硬断言 workspace 版本为 `0.147.0`，且 `binary_freeze.py` 约 20 处硬编码
  可执行名 `"codex"` → 产品版本改由 git tag 承载，改名只在打包层做
- 打包器 `cargo.py` 用 `cargo_bin` 构建、却用 `entrypoint_name` 查找产物，新变体下不一致
  → 走 `--entrypoint-bin`，E-X1 得以保持纯追加
- **`bundled_bwrap.rs` 的 `CODEX_BWRAP_SHA256` 是编译期注入，缺失时 `verify_digest()` 静默放行**
  → 若先构建 `codex` 再构建 bwrap，发布物即为"永不校验 bundled bwrap"版本，且常规 smoke test 照样通过。
  已冻结上游同款顺序（bwrap → strip → 摘要 → 导出 → 构建 codex），并新增可判定篡改测试 A14
- `with_codex_v8_artifacts.py` 按 `rustc -vV` 的 host 选 V8 产物，而产物名严格含目标三元组
  → 交叉编译 musl 时会链入 GNU 的 V8；改为工作流层按 `TARGET_SPECS[$TARGET]` 取
- `cargo.py:validate_prebuilt_resource_inputs` 对非 Linux 传 `--bwrap-bin` 直接抛错
  → 命令块按平台分支
- 打包器收到 `--archive-output` 会在校验后立即归档 → 许可材料必须先注入包目录再自行归档
- 打包器零许可处理；且 `cargo-about` 看不见预编译 `librusty_v8_*.a` 内的 V8/ICU 原生代码
  → 许可清单拆成 Rust 依赖闭包与 V8 原生闭包两层

另有两处本计划自身的自相矛盾（回退方案与验收标准冲突、禁改与要求更新同一文档）在审查中被发现并修正。

## 授权与决策

- **KD-007**（现仓库整体转 public）：已获用户批准。依据为 1272 commit 全量密钥扫描零命中、
  `.git` 仅 45 MB、`eval-data/` 等重资产 tracked 文件数为 0。
- **KD-012 / 窄例外 E-X2**（`check_for_update_on_startup` 默认值改 `false`）：已获用户批准，本批次只记录不实施。
  依据为发布物会查询 `openai/codex` 的 Release 并提示安装 `@openai/codex`。

## 验收结果

规划验收通过；实施验收 A1–A14 全部未开始。本批次未构建、未测试、未改动任何 Rust 源码，
远端仓库仍为 `PRIVATE`。下一步从阶段 A-2 开始，阶段 C 先用 `multi-v0.1.0-rc1` 在 private 仓库实跑。
