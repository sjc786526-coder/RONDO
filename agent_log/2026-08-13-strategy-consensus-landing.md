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

## 审查后修正（同批第二轮）

外部审查指出 4 处问题，经逐条核对全部属实，已修：

1. **Local M3 与 L3/L4 顺序自相矛盾**：顶层 WBS 三处分别写成“M3→L5/L6”“4k→L3/L4→M3”“L3/L4/L7 收口为 M3”，
   与子 WBS 冲突。统一为 **4k model-backed + L7 → Local M3 → L3/L4 → L5/L6 → Local M4**。
2. **`product` 字段历史兼容规则不自洽**：原写法把 `codex` 列为产品取值，又规定缺字段的 244 条一律按
   `rondo-local` 解释。实测 `runs.jsonl` 为 224 条 `side=rondo` + 20 条 `side=codex`，全部无 `product`，
   该规则会把 20 条上游侧误判为 Local。改为：`product` 只取 `rondo-local`/`rondo-multi`，
   `side=codex` 的行不写该字段；缺字段时按 `side` 分别解释。产品身份与比较侧确立为正交两维。
3. **L3 的 Sol 调用路径与订阅入口边界冲突**：原 L3 定义为批量把 `E_final` 喂给云端教师并写入结果库，
   等于把订阅制 Sol 当程序化后端，且排在产出标签的 L5 之前。按用户裁定采用「人在场、发送预写冻结 prompt、
   不另开按量 API」方案：L3 只程序化跑 `Local-static`，教师侧改为导入冻结标签；L5 拆为
   L5a 教师标签生成（先于 L3）与 L5b 合成训练数据（L3/L4 之后）。
4. **活 WBS 堆入废弃方案与实现级论证**（违反 AGENTS.md 文档纪律）：精简 shim 机制说明、multidev 回退方案
   论证与旧 M2/M5 退役段落，只保留决定、依赖与可执行约束；论证移到本日志附录。

## 审查后修正（同批第三轮）

第二轮修复留下 4 处未闭合，经核对全部属实，已修：

1. **顶层路线仍遗漏 L5a 前置**：第二轮只统一了"M3 → L3/L4 → L5/L6 → M4"，但子 WBS 规定 L5a 必须先于 L3。
   顶层三处（3b、方向表、阶段表）统一为 **M3 → L5a → L3/L4 → L5b/L6 → M4**，L5a 归 P2、L5b 归 P3。
2. **Sol 与 Opus 角色再次混用**：L3 一句"经开发用 Codex / Claude Code 生成"把裁判入口放回了教师标签生成。
   改为教师标签**只经开发用 Codex（Sol）**，明确不走 Claude Code / Opus 5。
3. **holdout 条款自相矛盾**：L5a 要把 holdout 发给 Sol 生成评测标签，分区表却绝对禁止 holdout 进入"提示词或
   人工参考"。把禁令范围收窄到**合成/训练**（L5b 合成上下文、合成 prompt、合成期人工参考），
   明确为评测生成教师标签与裁判判定属允许用途。
4. **导入式 shadow 行 schema 未闭合**：新增最小字段合同 —— `source` ∈ `auto`/`imported` 必填；
   `local-*` 写 `product=rondo-local`，`sol-static` 不写 `product`；导入行必填
   `teacher_model`/`generated_at`/`prompt_version`/`prompt_sha256`，`binary_sha256`/`metrics`/`actual_usd`
   必须显式 `null`，`estimated_usd=0.0`，`git_commit` 记导入时的 eval harness commit。
   同时把 shadow 的 `metrics` 口径限定为 `source="auto"` 的行，避免与 `metrics=null` 冲突。

## 附录：被移出活 WBS 的取舍论证

保留在此以免将来重新讨论；这些是形成时点的判断，不作为当前规划。

**为什么 multidev 直接复制而不回退**

- Guardian 审批子系统是上游自带的：`codex-source-code/codex-rs/core/src/guardian/` 下 8,457 行
  （`approval_request`、`metrics`、`prompt`、`review`、`review_session`、`tests`）。任何 v0.147.0 基线都带着它，
  所以“diff 里不许出现 `guardian/`”这条机械门不可执行。
- 回退收益极小而风险真实：`config/mod.rs` 的 Guardian 字段与无关的 `outbound_proxy_policy_from_config`
  重构混在同一份 diff；`session/mod.rs` 的 `model_provider_auth_manager` 是对通用 auth 装配路径的结构性改动，
  回退它是回退一次重构而不是删功能。
- 反向理由：未来可能把本地 Guardian 作为 Multi 的可选 provider，保留这些默认关闭的接口意味着那条路径较短。
- 不从纯净 v0.147.0 起步：会原样继承 Plan 004 已修掉的 81 项测试失败。
- 不用“回退到历史 commit 复制当时的 mydev”：仓库里不存在纯净 v0.147.0 的 mydev commit
  （初始导入 `0fe9217` 是 v0.146.0，P0 Guardian 改造 `95d3358` 在前，0.147.0 升级 `1001929` 叠在其上）。

**为什么看门狗迁移不走 shim**

`eval/` 侧存在 canonical wrapper 身份校验，把路径当安全断言用：`runtime_bridge.py` 硬编码
`<checkout>/mydev/scripts/with-build-lock.sh` 并做全等比较，随后再读 `/proc/<pid>/cmdline` 要求该路径逐字
出现在 watchdog 进程 argv 里；`binary_freeze.py` 另有一处同样的硬编码。shim 用 `exec` 转发会替换进程映像，
argv 里只剩根路径，因此无论走不走 shim，eval 侧硬编码都必须改成根路径 —— shim 省不下工作量，
还让“调用的东西”与“被校验的东西”差一跳，与 fail-closed 资源守卫的完整性方向相反。

## 自查

- 交叉引用与术语扫描：`M2` / `M5` / `E-A` / `方向 1` / `方向 3` / `可插拔` / `Luna` 在活文档中已无残留旧口径；
  `agent_log/`、`doc/audit-snapshots/`、`doc/research/`、`plan/` 作为冻结历史未改。
- 已核对 `eval/templates/local-approval/` 确实存在，`cross-eval-judge/` 作为待建目录写入规范。
