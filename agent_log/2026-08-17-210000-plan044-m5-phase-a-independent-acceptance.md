# Plan 044 / Multi M-5 阶段 A 独立验收审查

日期：2026-08-17 ｜ 审查对象：`worktree-044-multi-m5-real-workflow-and-nondegradation` @ `02bfb78`
｜ 基线：`main@45efac6`（Plan 提交 `7a2ff68`）｜ 审查者：独立审查会话（未参与实现）

## 结论

**验收不通过**，需要一轮窄整改后复验。冻结物、接线与文档诚实度都站得住，缺陷集中在一处：
**门 1 的协作判据可以对"Root 独自完成 + 少量噪声"的运行给出通过**。门 1 是 M-5 的核心主张，
判据本身失真会让阶段 B 花掉的钱换回一个不成立的结论，因此必须先修再进入阶段 B。

阶段 A 的其余交付（bundle 冻结与身份自证、两份运行合同、最小接线、无 API loopback、文档口径）
质量良好，**不需要重做**。整改面很窄，且完全离线、不花钱。

## 已核验（本轮实际做的事）

- 分支只有 `02bfb78` 一个实现提交，25 文件、+2237/-40；主工作区 `main` 干净且仍为 `45efac6`，未合并未推送。
- 冻结 bundle 三个阶段产物的 CLI sha 完全一致（`2f5f25e0…0c32`），host `eb54cac2…6705`、
  bwrap `77360cb7…2c4c` 与受跟踪锁逐项相符；manifest `product=rondo-multi`、
  `source_commit=7a2ff68`、`source_dirty=false`。日志中"legacy CLI + 本次 host"的说法与现场一致，
  不是身份混用。
- 离线 Python 全量门禁自行重跑：841 项、2 项 error。两项 error 为
  `tests.test_l6_b10333_pair` 与 `tests.test_local_m4_holdout_anchor`，
  已在**干净的 `main@45efac6` 上复现**，属既有缺陷，与本任务无关。
- 定向重跑 `test_multi_m5` + `test_binary_freeze` + `test_terminal_bench`：86/86 通过。
- 未重跑 Rust 142/142（`multidev/` 本次零改动，无回归面），未运行 Docker、真实 API、付费或本地模型。
- `rondo.local.toml` 的 `paid_eval.active_provider = "relay"`、`api_key_env = "OPENAI_API_KEY"`
  与授权清单一致；`.env.local` 未打开。

## 发现

### P1-1 门 1 判据不关联同一 Event，可对"独角戏"误判通过（必须修）

`eval/rondo_eval/multi_m5/predicates.py:64-96` 的六项谓词各自独立扫全表：
`event_with_two_versions` 只问"有没有某个 Event 有两个 Version"，`two_authors` 只问"全表作者去重是否 ≥2"，
`team_route` / `team_evidence` / `root_resolved` 同理。四者可以落在互不相干的对象上。

实测反例（本轮构造并实际运行 `evaluate_collaboration`，结果 `passed=True`、六项全真、`reasons=()`）：

- Root 自己在 `e1` 上写了两个 Version，并 resolved 自己的 Version；
- 成员只在毫不相干的 `e2` 上写了一条 Version；
- route 挂在 `e2`，证据挂在 Root 自己的 Version。

也就是说：**同一 Event 上的多作者链条从未形成、Root 从未消费成员的发布，判据照样放行**。
现有 `test_two_singleton_events_are_not_a_shared_chain` 只覆盖"两个单 Version Event"，
挡不住"一个双 Version 的 Root 独角 Event + 一条游离的成员 Version"。

整改方向（不指定实现）：判据应先选出一个 Event，再在**该 Event 内部**验证
"≥2 Version / 作者含至少一个成员 / route 指向该 Event / 该 Event 的某个 Version 有证据 /
该 Event 的成员 Version 被 Root resolved"，并补上述反例的回归。

### P1-2 六项谓词里没有任何一项证明"Root 被唤醒"（必须修）

ExecPlan 门 1 的五项能力包含"Root 唤醒"，指令模板第 2 步也明写"你必须通过团队世界状态被唤醒"，
但判据里没有对应检查。`root_resolved` 当前只要求"存在任一 Version 是 resolved"，Root resolve
自己那条 tracking Version 同样满足 —— 唤醒路径可以整场不发生。M-1 "团队状态不依赖模型记住"
是这条产品线最核心的命题，门 1 不验它等于放掉了主证。

最省事的做法是把 P1-1 的整改顺带做掉：要求被 resolved 的是**成员作者的 Version**，
Root 要 resolve 它就必须先看见它。若 M-4 的 `team_inspect log` 能拿到 wake 决策，直接断言更好。

### P2-3 成员模型与 effort 没有被真正钉住

`multidev/codex-rs/core/src/tools/handlers/multi_agents_common.rs:277-282`：未请求模型且
`default_subagent_model` 未配置时函数直接返回，成员继承会话模型 —— 所以锁里
`member_model=gpt-5.6-sol` 在"模型不自己指定"的前提下成立。但 `spawn_agent` 允许显式传 `model`，
一旦模型自己传了别的，成员就跑在别的模型上，冻结合同的成员模型声明和 $40/$96 的费用估算同时失真，
而且没有任何地方会发现。

建议：在同一条 inline TOML 里补 `default_subagent_model` / `default_subagent_reasoning_effort`
（只改默认值，显式请求仍会覆盖），并在阶段 B 证据里如实记录**实际**成员模型。

### P2-4 门 2 的归因边界需要预先写清楚

`MultiAgentV2` 在冻结上游是 `default_enabled: false`，`Collab`（V1 spawn）两侧都是默认开。
本次只在 Multi 侧打开 V2 + team state，因此门 2 实际比较的是
"上游 V2 多智能体 + RONDO 团队状态" 对 "上游默认 V1"。这符合 ExecPlan §3.6（团队能力属于被测产品能力），
**不是公平性违规**，但一旦真出现稳定单向退化，现有证据无法区分退化来自上游 V2 后端还是 RONDO 的团队层。
应把这条归因边界现在就写进不退化锁/结论口径；真出现退化时，再补一次
"V2 开、team state 关"的定点诊断即可分离，不要在结论里含糊带过。

### P2-5 门 1 的 dump 从哪来还没定

`evaluate_collaboration` 的输入被文档描述为"一页 `team_inspect` dump"，但仓库里没有任何东西生产它。
`team_inspect` 是模型可见工具，如果最后靠模型把 dump 抄进文件，门 1 的判决就建立在模型自述之上，
可被编造。阶段 B 开工前必须定成 Harness 侧采集（例如由 harness 驱动的收尾轮或解析 JSON 事件流）；
确实做不到时，至少要有一条 Harness 侧信号交叉验证模型给出的 dump。

### P3 其它（不阻塞）

- `just eval-test` 无法加载两个 Local 测试模块（`ModuleNotFoundError: No module named 'eval'`），
  **既有缺陷，`main@45efac6` 同样复现**，与本任务无关。仓库级门禁因此并非真绿，值得单独窄修
  （统一 import 风格或补 `PYTHONPATH`），不要塞进 044。
- `doc/WBS-COMPLETED.md` 末尾多一个空行（`git diff --check` 唯一命中），随下次提交顺手去掉即可。
- 现场遗留：测量树 `.claude/worktrees/044-m5-multi-bundle-measurement`（detached，167M）、
  `eval-data/build` 26G、bundle 三阶段产物 3.7G。项目根 58G，离 180G 门禁很远，本轮不必清理。

## 替用户做出的决策

| # | 事项 | 决策 | 理由 |
|---|---|---|---|
| D1 | 是否现在批准阶段 B | **暂不批准，改为有条件批准**：P1-1、P1-2 整改并复验通过，且 P2-5 的 dump 采集方式定案后，阶段 B 自动获批，不必再走一轮完整审批 | 判据失真的成本是 $120 加一天机时换一个不成立的结论；整改是离线窄改，几乎零成本 |
| D2 | 授权清单其余各项（provider relay、双侧 `gpt-5.6-sol`+medium、门 1 三次 1800s、门 2 十题交错、有效运行 60、infra 12/槽 3、每 run 80 请求、$120 硬上限、十个 digest 镜像、外发边界、只提交不合并） | **整表照批**，不改动 | 与 ExecPlan 硬约束逐条对齐，冻结值具体可核验，预算留了合理余量 |
| D3 | 成员模型漂移（P2-3） | 补 `default_subagent_model` / `default_subagent_reasoning_effort` 默认值，并在阶段 B 证据里记录实际成员模型 | 让冻结合同和费用估算与现实一致；只补默认值不改产品语义 |
| D4 | 门 2 归因边界（P2-4） | 写进不退化锁与最终结论口径；真出现退化时再补"V2 开、team state 关"的定点诊断，本轮不预跑 | 结论要能说清退化归谁；不预跑省钱 |
| D5 | 门 1 最多一个成员的判据 | **维持现状**，不放宽 | 指令模板把"只准 spawn 一个成员"写成硬规则，超出即协议未被遵守，判失败是对的 |
| D6 | `just eval-test` 两个 Local 模块加载失败 | 不在 044 内修，单开窄任务 | 既有缺陷、属 Local 侧，混进来会污染本任务范围 |
| D7 | 测量树与 `eval-data/build` | 阶段 B 结束前保留，收口后再删 | 阶段 B 若需窄修重冻 bundle，重建成本远高于这点磁盘 |

## 验收判定

- **做得对不对**：不通过。门 1 判据存在可实证的误判路径（P1-1、P1-2），其余部分正确且诚实。
- **是否实现预期**：未完全达成。冻结、接线、无 API 演练、文档口径均达成；
  "已具备真实运行条件"这一表述在门 1 判据修好、dump 采集定案之前**尚不成立**。
- 阶段 A 的自我表述（"不是 M-5 通过、不是门 1 通过、未见退化"）经核对属实，没有拔高。
