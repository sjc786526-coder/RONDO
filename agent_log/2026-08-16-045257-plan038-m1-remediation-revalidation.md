# Plan 038 / Multi M-1 整改复验

## 结论

- 复验对象：`worktree-039-multi-m1-team-world-state` 提交 `5ce7e4ca00ae3f2b9b8f30fba8b04f1ebc277537`，
  上次审查提交为 `5631de2`。
- **验收状态：不通过。**
- **任务目标：失败（当前提交仍未完整满足 M-1 冻结完成标准）。** 首轮审查的大部分缺口已正确整改，剩余问题都可
  在现有结构中窄修，不需要增加 ACL、审计、可信设施或改造调度器。

## 已确认修复

- ExistingEvent append 已按可见性检查，sibling member 不能再靠猜 ID 自行扩权；Root 全队、member 仅已有可见性/
  贡献资格的轻量边界成立。
- Event 与 Version 历史均增加 `before` / `next_before` 分页，列表只预览每个 Event 最新两条 Version；旧内容已有领域层
  可达路径，单页对象数与 authored 字段均有界。
- 单独调用时，Root 已 `resolved` 的 Version 不再允许原地重开；producer/root 双生命周期仍相互独立。
- Session 只登记用户面 Root 或带 agent path 的 ThreadSpawn member；Internal、Review、Compact、Unknown 与缺 path 的
  spawn 不登记。Event/Version 引用已携带完整 UUID 实例身份。
- authored 字段在 canonical 写入时有界并显式标记截断；普通的“同 retry ID、不同常规内容”已经返回冲突。
- protocol、projection、team tools 与 wait hook 对团队能力使用统一的 effective team-state 判断；默认关闭策略未改变。

## 仍阻断验收的问题

### 1. 整次请求预算仍未闭合，决策 015 不接受

- `team-state/src/render.rs:117-147` 在局部预算放不下最小通告时仍强制返回 `minimum_notice`；
  `render_tests.rs:115-185` 用 `max(budget, 64)` 明确允许它超出预算。这不是 hard cap。
- 更深一层的问题是预算输入并非实际待发送 request 的余量。`core/src/team/projection.rs:62-65` 使用
  `context_window_token_status`，其计数来自 Session 缓存的 provider usage；本轮刚写入的 user/tool output 与随后组装的
  实际 prompt 尚未计入。`session/turn.rs` 的 pre-compaction TODO 也明确承认 incoming items 没有预估。
- 因此即使删除 64-token 例外，当前算法仍不能证明投影计入了**整次实际请求**；大 fresh input/tool output 或
  `remaining < minimum_notice` 时仍可能由投影触发 `ContextWindowExceeded`。现有 compaction 不会因 renderer 的零预算
  状态被显式触发，新增 10k-window 测试也没有验证实际请求总量不越界。
- 裁决：显式 omission 很重要，但不能覆盖“不得由投影顶爆请求”。最小通告放不下时，应让调用层先 compaction 并按新
  prompt 重新计算，或采用其他确实以最终 request 为准的硬边界；具体实现路线由执行者选择。

### 2. 同一批 lifecycle target 可绕过 Root 终态

- `team-state/src/store.rs:323-369` 先用同一旧状态验证全部 target，`store.rs:374-385` 再顺序写入，没有拒绝同一 Version、
  同一生命周期维度的重复 target。
- 一个批次同时带 `pending -> resolved` 与同一 Version 的 `expected=pending -> tracking` 时，两项都在旧 pending 上通过，
  最终顺序写成 tracking，刚加入的终态检查被完整绕过。
- 应拒绝同一批对同一 Version 同一生命周期维度的重复修改，或按等价的 shadow state 顺序验证。producer 与 Root 两个
  独立维度仍可在同一批分别修改，不必扩大限制。

### 3. retry 指纹仍可能把不同请求静默合并

- `team-state/src/mutation.rs:42-52` 用 U+001E 拼接 model-controlled 字段，不是无歧义结构：
  `handoff=None` 与 `Some("")` 已会相撞，字段包含 U+001E 时也能跨字段构造相同字符串。
- 不同 `PublishRequest` 因而仍可能在 `store.rs:194-201` 被当作 deduplicated，第二份内容静默丢失。无需哈希或新设施；
  直接保存并比较已实现 `Eq` 的结构化请求，或使用同等无歧义表示即可。

### 4. 陈旧终态 mutation 没有返回最新完整状态

- producer 已 closed 或 Root 已 resolved 时，`store.rs:330-355` 在通用 expected-state 检查之前返回只含 Version ID 的终态
  错误；携带陈旧 expected 状态的调用因而到不了 `LifecycleConflict { current }`。
- M-1 明确要求陈旧 lifecycle mutation 被拒绝并返回最新 producer/root 状态。应先判断 expected 双状态是否仍匹配并在
  不匹配时返回当前快照，再判断匹配状态上的转换是否合法。

### 5. 新增真实 `team_history` 测试存在假阳性

- `core/tests/suite/team_world_state.rs:909-914` 将下一次完整 request JSON 转为字符串后搜索
  `orders.legacy_total`；该文本早已存在于最初 `team_publish` function-call arguments，并随 history 进入同一 request。
  即使 `history-1` 工具输出为空，这个断言也可能通过。
- 应精确读取 `history-1` 的 function-call output 再断言被省略内容；已有 responses helper 可直接做到。最好顺带让真实
  handler 至少走一次 `next_before -> before`，领域分页测试保留即可，无需建设新测试设施。

## 本次验证

- `just test -p codex-team-state -p codex-features`：76/76 通过。
- `just test -p codex-core -E 'test(/team_world_state/) + test(only_verifiable_sessions_get_a_team_identity)'`：7/7 通过，
  3329 skipped。
- `UV_CACHE_DIR=/home/sjc/desktop/RONDO/.uv-cache just fmt-check`：通过。
- `git diff --check 5631de2..5ce7e4c`：通过。
- 两组 Rust 测试均通过共享构建锁/cgroup 看门狗；最后一组记录 project 72.49 GB、target 53.09 GB，未触发资源停止。
- 未重跑全 workspace、Docker、真实 API、本地模型或 Bazel；这些不是本轮必要验收范围。

## 替用户作出的决策

1. **拒绝 ExecPlan 决策 015 的预算例外。** 保留“非空活动视图不得伪装成空闲”的目标，但必须通过 compaction 或最终
   request 级预算实现，不能让 omission marker 豁免硬边界。4k / 2k / 20% 数值本身继续接受。
2. **继续保留 `team_state_enabled = false`。** 默认开启不是 M-1 完成条件，不为此制造现有 Multi 快照 churn。
3. **权限政策维持最小实现。** Root 全队、member 仅已有可见性/贡献资格；M-2 route 再扩权，不建 ACL 或审计体系。
4. **`wait_agent_enabled` 保持独立可选开关。** 不强行并入 team-state gate；M-1 产品链验收配置必须同时启用 wait，现有主
   纵切已经这样覆盖。相关文档不要再把它表述为 team flag 单独开启即可拥有全部 wait 能力。
5. **Bazel 继续记为未验证、非阻断。** 不安装、不下载、不冒充通过；85 个宽门禁失败的前后集合一致，可视为本次整改
   无新增宽门禁失败，但其环境根因仍不宣称已独立证实，也不要求再跑全 workspace。

## 交付状态

- 本次仅新增本复验报告；未修改实现、ExecPlan、WBS、main 或 L6 工作树。
- `5ce7e4c` 的整改提交未合并、未推送。建议继续在原 M-1 工作树做一轮聚焦修复并提交后复验。
