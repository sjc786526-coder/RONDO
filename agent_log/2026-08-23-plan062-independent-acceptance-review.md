# Plan 062 独立验收审查

## 结论

- 验收状态：**通过**。
- 任务目标：**完成**。
- 三项学习教师源码后筛选并自主实现的优化均命中真实产品热路径，未发现行为等价、请求序列化、工具资格、
  sandbox diagnostics 或 history 顺序方面的剩余 correctness finding；正式测评足以证明对应扫描、深拷贝和中间分配
  已被消除，但不外推端到端 API、模型质量或任务成功率。

## 重点复核

- history orphan normalization 保持 FunctionCall/LocalShellCall 共用 output 匹配、client/server tool-search、idless
  output、custom output、debug panic 与 release 删除语义；无 orphan 时不再改写向量，多 orphan 时 survivor 顺序不变。
- `ToolRouter` 只在构造边界执行 `Vec<ToolSpec>` 到 `Arc<[ToolSpec]>` 的转换；普通 turn、remote compact 与 v2
  compact 共享不可变规格。Responses、Responses Lite 与 WebSocket 继续进入同一请求构造，变化只是以 slice 传给
  原序列化函数，没有可变别名或第二条工具暴露路径。
- unified-exec snapshot 只构造一份连续 retained bytes；合法 UTF-8 denial 判定借用该缓冲，非 UTF-8、空输出、
  head/tail、omission marker 和错误对象语义由直接回归锁定。
- baseline `d5535fc` 与 candidate `22b8766` 的 benchmark、适配器、runner、Cargo/just 配置内容一致，harness
  SHA-256 同为 `ef8364c...77fd5f2`。两份 raw 的 commit/dirty/return code、output SHA 和 watchdog 完成态均可对应；
  本轮从正式 raw 重新聚合，结果与 tracked JSON 逐字节相同。
- 执行者留下的最终 JUnit 对应 clean candidate：`codex-core` 3332/3332、failures=0。此前失败轮没有混入最终聚合；
  总 runner wall time 含 baseline 冷编译与 candidate 热缓存，现有文档已明确不把该差异当作产品收益。

## 已代用户作出的决策

1. **接受三项产品优化和当前轻量测评设施，不要求整改或重跑完整 crate。** 产品 diff 清楚且回归充分；重复重跑
   3332 项不会增加相称的正确性信息。
2. **接受配置 schema snapshot 与 realtime reset-server 两个窄 fixture 修复。** 前者同步已存在的配置字段，后者只把
   固定端口失败假设换成动态 loopback 失败源；二者不改变产品语义，不需要另立任务。
3. **不为旁支 baseline 增加 tag、签名链或额外可信设施。** `d5535fc` 当前可解析，正式 raw、同 harness 哈希和 tracked
   聚合足以支持本次验收；它不是当前分支祖先属于非阻断的长期复现限制。未来若需正式复测，应从届时 clean 基线
   重新冻结同口径 run，而不是把本次微测评扩成 provenance 平台。
4. **方向 1 在 Plan 062 后重新收口为无 active 工作包。** 保留三项优化、默认关闭的轻量 benchmark 与既有观测；
   不恢复开放式候选探索。只有未来出现高频、跨任务且影响明显的新瓶颈时，再由 WBS 另行立项。

## 独立验证与边界

- 本轮 Python parser `4/4` 通过；正式 baseline/candidate raw 重新聚合与 tracked JSON 完全一致；三个只读分项审查
  分别核对 history、tool specs、unified-exec/benchmark，均无 finding。history 分项另复用已编译产物运行 5 个精确
  debug/release 回归，全部通过，没有触发 Cargo 构建。
- `git diff --check 60ada10..a4eb529` 通过。审查开始时 062 worktree 与 main 均 clean；未覆盖其他 worktree 的现有
  内容。
- 本轮未重跑 Cargo crate 门禁、benchmark、Bazel、Docker、全 workspace、真实 API、本地模型、训练、CI 或 PR；
  未读取 `.env.local`，未合并、推送、重命名或归档分支。

## 当前交付状态

Plan 062 已通过独立验收并完成任务目标。062 分支只等待用户决定是否合并到主线；本审查不授权也未执行合并、推送
或分支归档。
