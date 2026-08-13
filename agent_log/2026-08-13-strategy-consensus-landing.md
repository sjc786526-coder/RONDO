# 路线共识落地：双产品线、方向 1/E-A 挂起、里程碑重拆

- 输入：`TEMP-STRATEGY-CONSENSUS.md`（草稿）。本批把它拆进权威文档并删除该临时文件，避免与
  `doc/WBS.md` 并存形成第二个规划来源。只改文档，未运行 Cargo、Docker、真实 API 或本地模型。

## 实质变更

- **双产品线**：确立 RONDO Local（`mydev/`）与 RONDO Multi（`multidev/`，待建立）并列。README 新增产品线小节，
  研究方向 3 由“Local 内可插拔模式”改为独立产品源码。WBS 新增 §4 仓库与产品线结构（布局、分支隔离、
  磁盘预算、共享外围设施、产品身份）。
- **方向 1 与 E-A 挂起**：方向 1 完全挂起、不排期，重启时只针对 Local；E-A（A1—A7）随之挂起，
  日常回归改由测试体系承担。`eval-benchmark.md` 的 A1—A7 改标为历史设计，并移除“再跑 B7 需 E-A 完成”的前置。
- **旧 M2 拆解退役**：拆为公平比较设施（设施交付物，非里程碑）、Local M3（工程验收）、
  L5/L6 前置 dry-run（非里程碑）、Local M4（人判定）与 Multi 自定义里程碑。`σ`/`delta` 判据收窄为
  只适用于公平比较设施自身的 A/A、A/B 比较；M3、M4 与 Multi 退化验收都不继承。M5 随方向 1 挂起。
- **方向 2 口径重写**：定位改为学习型教师蒸馏；Sol（订阅制、经开发用 Codex）出教师标签，
  Opus 5（Claude Code 订阅）担任 M4 裁判，角色不混用。M4 被评三方为 Sol / 未微调 Local / 微调后 Local，
  单批 ≤100 条共 2—3 批，裁判 prompt 仓库内版本化冻结、输出匿名化随机序，证据以合成为主体、
  47 条真实 `E_final` 的 holdout 作 sanity anchor。微调路线固定为云 GPU LoRA，触发费用/数据外发/权重下载
  三重授权门。L3 不再等同 M3。Luna 当前不可用，具体云端模型不再写死在子 WBS。
- **方向 3 重写为产品线规划**：新增 M-0 产品基线工作包（直接复制不回退、三条行为验收门、看门狗迁移、
  独立产品身份），价值命题与首个增量列为 D1/D2 待定，退化验收改为“复用 B7 金丝雀集、只看完成与否、
  不算 σ/delta”，并保留“付费验收不早于公平比较设施闭合”这条依赖。
- **数据规范**：`doc/eval-data-layout.md` 新增 §3.1 产品身份（取值、缺字段按 `rondo-local` 解释、
  历史只加不改、不顶层并列），结果行新增 `product` 字段，新增 M4 会话内判定的冻结 JSONL 产物约定与
  `eval-data/cross-eval/` 命名空间，shadow 指标区分“教师一致率”与“漏放/误拦”。

## 有意识的偏离

共识 §9 要求把 `CLAUDE.md` / `AGENTS.md` 的构建锁路径改成根 `scripts/`。**本批未改**：脚本尚在
`mydev/scripts/`，提前改会让安全边界条款指向不存在的路径。该改动已写入 WBS §4.4 与方向 3 的 M-0，
要求与实际迁移在同一任务内完成。`doc/development-environment.md` 同理未改。

## 自查

- 交叉引用与术语扫描：`M2` / `M5` / `E-A` / `方向 1` / `方向 3` / `可插拔` / `Luna` 在活文档中已无残留旧口径；
  `agent_log/`、`doc/audit-snapshots/`、`doc/research/`、`plan/` 作为冻结历史未改。
- 已核对 `eval/templates/local-approval/` 确实存在，`cross-eval-judge/` 作为待建目录写入规范。
