# 2026-09-02 Plan 104 Multi 产品配套补齐独立审查

审查对象：`worktree-106-multi-product-support@21ec8494`，基线 `main@3f22453c`。本次只审查工作树实现，
不合并、不推送，也不以尚未触发的 GitHub Actions 代替本地证据。

## 结论

- **验收不通过。** CI 选包与 `/status` 实现正确，范围也干净；阻断项集中在根配置指南、README 和任务状态记录，
  都是窄文档修订，不需要重做功能或新增设施。
- **任务目标失败（当前提交）。** 三项产品能力目标已实质落地，但 M-3 尚有错误/越界说明，Plan 状态没有反映本地验证已完成，
  且推送后轻量 CI 尚未执行，因此当前提交不能宣告整个任务完成。这不是方案性失败，修正文档后可直接复验。

## 审查发现

### 1. 显式 Guardian model 的回退说明与代码不符

`doc/rondo-config.md` §1.2 末尾称显式 `[auto_review].model` 的最终 slug 仍会经过目录查表与回退；执行日志
“配置已加载和某次审批使用”一节也用同一理由说明配置值未必是实际选择的模型。

实际解析中，`guardian_model_config` 优先于 catalog override 和 provider 默认值；即使目录中找不到 preset，
只要显式 override 存在，传给 Guardian session 的仍是这个 override。真正不能从 `/status` 推导的是“某轮 review
是否发生、请求是否成功到达 provider、provider 最终如何处理”，而不是显式 slug 会被目录回退替换。

应保留当前保守 UI 措辞，但修正文档和实施日志中的技术解释，避免与同页“最高优先级”表格互相矛盾。

### 2. 默认状态的总括措辞容易误报 Guardian feature

README 配置入口写“这些能力默认全部关闭”，配置指南开头也写“下面的实验性能力默认全部关闭”，但同一指南
§1.5 正确记录 `guardian_approval` 是 Stable 且默认开启。这里应区分：默认 reviewer 是 `user`、四个 override
默认不设置；Multi 的 `multi_agent_v2`、Team State、Durable Team 和 Publication Critic 默认关闭/缺省。

这只是措辞修正，不要求改变任何默认值。

### 3. 第一阶段文档夹带了一句 Local 专属结论

`doc/rondo-config.md` §3 对 Local 本地推理桥接、模型权重和推理运行时作了具体判断。Plan 104 只允许公共 Guardian
与 Multi 内容，Local 专属说明明确留到第二阶段；本阶段保留“Local 专属配置将在第二阶段补充”即可。

### 4. 任务状态记录落后于实际进度

Plan 104 仍标为 `LOCAL_VERIFICATION_IN_PROGRESS`，剩余步骤仍包含已经完成的定向测试与提交；实施日志的测试表写
“见下方最终一轮”，但文件中没有对应的最终一轮结果。应改为“本地验证完成、审查整改中/待复验”，并把最终
`3602/3602`、其中 `codex-team-state` 159 个非零测试与代理环境说明精炼补入实施日志。GitHub Actions 仍必须标成未触发。

## 已确认正确的部分

- Multi workflow 的 `TEST_PACKAGES` 确实加入 `-p codex-team-state`；`doc/ci-pipeline.md` 的 package 表与两条本地复现
  命令和 workflow 一致，没有把整个 `codex-tui` 加入 CI，也没有改 Local 选包。
- `/status` 从当前有效 `Config` 读取 model、provider、reasoning effort、evidence directory 四个显式 override。
  无 override 不增加字段；`AutoReview` 显示已加载；`User` 明确显示未选用。实现没有改审批路由、模型解析、feature
  gate 或默认值。
- 现有无 override 快照没有被批量改写；新增快照只覆盖代表性有配置状态。每项 48 列上限能约束自由文本和路径，
  沿用卡片最终宽度截断，未引入第二套布局设施。
- 最终差异没有触碰 `mydev/`、产品树继承文档、依赖/lockfile、研究设施或发布内容，也没有新增 Cargo target。

## 复验与证据

- 审查者窄门禁：`codex-team-state` 全包 + 4 个新增 Guardian status 测试，共 `163/163` 通过；JUnit 明确分为
  `codex-team-state 159/159`、`codex-tui 4/4`，证明 CI 新 package 不是零测试。
- 执行者保留的最终 JUnit：`3602` tests、`0` failures；其中 `codex-team-state` 为 `159` tests。
- Multi Rust workspace `cargo fmt --all --check` 通过；`git diff --check` 通过；没有 `.snap.new`。
- 审查者没有重跑全部 TUI、clippy、Local 或全 workspace。首次根 `fmt-check` 只因审查沙箱不能写用户级 UV cache
  而停在 Python formatter 启动前；本任务没有 Python 差异，故改用与改动直接相关的 Rust format check，不把环境拒绝
  记作产品失败。

## 代用户作出的决定

1. **接受** `loaded for reviewer auto_review` / `loaded, unused by reviewer user` 这组状态措辞。它只陈述已加载配置和
   reviewer 选择，没有声称某次 review 已运行或 provider 实际使用了该模型；只需修正错误的回退理由。
2. **接受** 新建 `status/guardian.rs`。`card.rs` 已超过局部文件规模门槛，新模块职责单一且复用现有格式设施，
   不属于过度抽象。
3. **不要求**补跑 clippy、Local 测试、全部 TUI 或全 workspace；现有全包证据和本次窄复验足以覆盖本轮代码风险。
   代理变量导致的 21 个 loopback 测试失败有随后同范围通过证据，按环境问题处理，不要求 bisect 产品代码。
4. **暂不合并、不推送。** 先在同一工作树完成上述四项窄文档/状态修订并提交；若不再改 Rust，复验只需格式、
   文档/diff 自检，不要求重跑 3602 个测试。工作树复验通过后，再按用户单独授权合并、推送并观察轻量 CI；Actions
   中必须确认 `codex-team-state` 非零运行后，任务才可转为完成。
