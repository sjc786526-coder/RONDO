# Plan 044 / Multi M-5 门 1 模板与判据不自洽整改

日期：2026-08-18 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation` ｜ 基线：`5bde52d`
｜ 审查报告：`agent_log/2026-08-18-050000-plan044-m5-phase-b-prep-review.md`（不通过）
｜ 本轮无费用：未跑 Docker、未调真实 API

## 结论

审查发现的缺陷**属实**，已修。冻结模板按字面执行必然过不了 `two_authors`，
彩排全绿只是因为 stub 多做了一次模板从未要求的 Root 发布。

## 独立复现（改冻结产物之前先自证）

模板步骤 1–8 里 Root 从未发布过 Version；`team_update` 只走 `LifecycleChange::SetRootState`
（`multidev/codex-rs/team-state/src/store.rs:583`），改的是生命周期，不产生 Version。
于是该 Event 上的 Version 全部由成员署名，`two_authors`（同一 Event ≥2 位作者）恒假。

在冻结二进制上实跑了"只跳过那次 Root 发布、其余与模板逐条一致"的序列：

```
passed=False
reasons=('predicate:two_authors',)
predicates={spawn_member:True, event_with_two_versions:True, two_authors:False,
            team_route:True, team_evidence:True, root_resolved:True, root_woken:True}
report_written=True  requests=15  rc=0
```

六项谓词全过、报告照常写出，唯独 `two_authors` 假 —— 与审查描述一致。
付费跑会连烧三次尝试，并产出一个看起来像产品缺陷的假失败。

## 改动

- **模板补第 3 步**：Root 被唤醒后，用 `team_publish` 带 `event_id` 在**同一个 Event** 上发布自己的
  Version，并在步骤里写明理由（需要两位作者，而 `team_update` 不产生 Version，跳过必失败）。
  原第 3–8 步顺延为 4–9。
- **修掉误导性表述**：原第 5 步括注"the member must append a second Version（two authors on that
  Event）"——成员追加并不会产生第二位作者，这句话很可能就是当初漏掉 Root 发布的原因。
  改为说明该 Event 由成员的两个 Version 加上 Root 第 3 步的 Version 构成。
- 重算 `instruction_sha256`：`b11136af…1b322` → `b0925723…3d1be`，写回 `multi-m5-workflow-v1.json`。
- **stub 未改**：它本来就在做这次 Root 发布，现在模板与 stub 的步骤序列一致了。

## 新增回归（防同类复发）

`MultiM5TemplateProtocolTests` 两条，把模板与判据绑在一起：

1. stub 的 Root 分支会发出的每个团队工具，都必须出现在模板的编号步骤里。
2. 必须存在一个**面向 Root**的 `team_publish` 步骤 —— 否则 `two_authors` 在单成员下无法满足。

已验证这两条能抓住旧模板（旧模板：9 步→8 步、编号步骤中根本不含 `team_publish` 字样、
Root 发布步骤 0 条），不是只在新模板下成立的马后炮。

## 顺带修掉的一处付费陷阱

审查把四项付费期问题并入 F3 清单。其中 `evidence_kind` 在 `gate2._record_for` 里写死为 `fake`，
付费执行器接上后会把真实证据写进 fake 分区——这直接违反"证据必须分区标注"的硬约束，
且属于会被后来者继承的陷阱，因此本轮就地修掉，不等 F3：

- `run_light_interleaved` 增加 `evidence_kind` 参数（默认 `fake`），逐条记录透传。
- fail-closed 守卫：`ScriptedSlotExecutor` / `DockerNotAuthorizedExecutor` 不得产出 `real_api` 记录。
- 配一条回归。

其余三项（forward 的 30s 超时与 SSE 全缓冲、转发丢头部、彩排超时不留 infra 记录）仍留在 F3 清单，
它们的正确形态取决于付费 forward 路径本身怎么设计，现在动等于凭空猜。
单次运行 $40 上限同样留待 F3 按实测 token 收紧，总额 $120 不变。

## 验证

- 修正模板后彩排复跑：`passed=True`、七项谓词全真、16 请求、无 stub 错误。
- `tests.test_multi_m5` + `tests.test_multi_m5_exec`：**44/44**。
- 完整离线 `just eval-test`：**868 项**（上轮 865 + 新增 3），仅剩既有的两项 Local 模块加载失败
  （干净 `main` 同样复现，属另一任务）。
- `just eval-multi-m5-ready` `ready=true`；fake 门 2 20 槽位、0 infra、未触停。
- 未跑 Rust（`multidev/` 零改动）、未跑 Docker、未调真实 API、未产生费用。

## 状态

门 1 现在"模板即协议、彩排即模板"：冻结模板自身足以满足全部七项谓词，
且有回归防止两者再次分叉。付费前仍缺门 1 付费入口与门 2 真实执行器，按 F3 决议实现后须先过独立审查。
