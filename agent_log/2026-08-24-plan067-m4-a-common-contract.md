# Plan 067：M4-A Durable Team Runtime 共同合同

日期：2026-08-24
结论：`M4_A_GO`（独立终审闭环后冻结）

## 实质结果

- 在 `doc/WBS/durable-team-runtime.md` 收敛第四期共同合同，分别给出 M4-S1、M4-C0、M4-W0 可直接建立 ExecPlan 的交接；未修改
  顶层 WBS、方向 3 总 WBS或 COMPLETED。
- 身份冻结为三类职责：`SessionId` 是 durable Session/root lineage，canonical Root `ThreadId` 是原生生命周期与 writer-authority
  anchor，`TeamInstanceId` 是该 lineage 的 canonical Team generation；当前 Session/root ID 同值不是永久表示承诺。
- 现有 Root Thread active-writer 是唯一排他基础，但须由 S1 架构内扩展，使 Root authority 连续覆盖 Root/child Team mutation 的
  durable commit 与成功返回。Team State 保持 canonical；新建的只会是与其集成的窄 durability/read 能力，不建设第二套 Team、
  writer authority、Session lifecycle 或控制面状态源。
- mutation success、committed read、owner/Team close、shutdown/task failure、process exit、archive/unarchive/delete、损坏/不兼容与
  旧引用都已有共同结果。online mutation 只由 owner runtime 执行；cold lifecycle 复用原生 Root 路径并诚实暴露 partial/unknown。
- 所有新能力默认关闭；可写 Durable Team 要求有效 V2 + Team State + durable backend + canonical Root authority。Control 可独立
  只读兼容的历史 durable 数据；正式 W1 还要求 W0 binding GO 与 S1，W0 自身不获得生产 trust 保证。

## 上游决定

- `#37198`：按 RONDO ThreadStore 窄适配，M4-S1 消费并在 S1 PASS 前进入主线。
- `#37847`：按 RONDO V2 residency/reload 窄适配，M4-S2 消费并在 S2 PASS 前进入主线。
- `#39616`：条件延期；W0 不以它为前置。只有 W0 binding GO 且 W1 消费 linked-worktree project trust 时适配，并在 W1 开始前
  进入主线。
- `#39153`：W0 binding GO 后按需适配；显式 override 仍优先，但 invalid/missing durable binding profile 必须
  unavailable/replacement，不能静默 fallback。若 W1 消费，须在 W1 PASS 前进入主线。

## 依据与验证

- 四路只读调研交叉核对了当前 Session/ThreadStore/V2/Team State/app-server/TUI/config/Git 源码与现有测试、Plans
  038/043/047/048、Plan 065 验收记录和冻结 `v0.147.0@be6e8eac...`；源码事实与设施分级见日期冻结 snapshot。
- 只读核对四项官方 PR exact head、diff、测试、依赖与 `rust-v0.149.1@ff29a443...` 最终形状；未 fetch、checkout、回移或升级。
- 初次文档检查：`git diff --check` 通过；本地链接目标存在；当前差异仅在 ExecPlan 允许写集内。
- 静态源码与现有测试定义足以支持合同，未运行 Cargo/Rust。也未运行 Docker、真实 API/模型、训练、测评、全 workspace、CI/PR，
  未修改远端状态。

## 独立审查

- 干净上下文终审发现 1 个中等级 correctness finding：合同只写了 unsubscribe/断连的即时 detach，遗漏零订阅 idle timeout 后的
  deferred unload，导致 S2/C0 对 close barrier 与 authority 释放可能作出两种实现。
- 已把即时 detach 与 deferred idle unload 分开：后者必须走同一 member unload 或 owner/Team close barrier，失败保持
  loaded/closing 且不得交接 Root authority；冻结 snapshot 同步补上现行源码事实。另补 legacy non-durable Session 和 Durable
  关闭时已有 durable lineage 不得空 Team fallback 的关闭态。
- 同一审查者复核确认 lifecycle finding 关闭；随后发现两份新 Markdown 的日期行尾双空格未被未暂存 diff 覆盖，已删除并对
  精确四文件 staged diff 重跑 `git diff --cached --check`。最终复核结果：`PASS`，无未关闭 correctness finding。
