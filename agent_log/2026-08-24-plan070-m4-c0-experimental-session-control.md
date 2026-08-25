# Plan 070：M4-C0 实验性 Session 控制原型实施日志

## 范围与数据来源

- 实施范围为 app-server v2 experimental → app-server-client → TUI 的默认关闭原型；不修改 Team State、Thread Store、
  069 durable read model/Root authority 或共享 WBS。
- discovery/list 固定从 state DB 读取并禁止 JSONL repair；单条 read 使用 `include_history=false` 的 Thread Store 只读入口；loaded
  owner/Team 事实只来自当前 ThreadManager 中身份可证明的 live Root。
- S1 尚未提供的 durable Team、closed/failed/partial/unknown 事实只允许以显式 prototype input 表达，并在协议/UI 标注来源；不会
  把进程内 Team 或客户端 cache 表述成 durable authority。

## 实现选择

- 产品 gate：独立、默认关闭的 `experimental_session_control` feature；experimental API capability 仅作为 RPC capability gate。
- 在线操作：Root-only canonical Team `SetRootState`，携带 expected producer/root state 并由领域层原子校验。
- 冷态操作：复用现有 `thread/unarchive` 权威入口，不直接写持久介质，也不为操作加载 Root。
- 客户端同步：connection/attachment/read generation 共同约束 response；lag/disconnect/EOF/response loss 先进入 stale 或
  result-unknown，非幂等 mutation 不自动重放，只有新权威 read 能恢复 fresh。

## 故障注入与验收

- app-server-client 的 11 条状态机测试覆盖：只接受最新 read ticket、读取失败保留 stale view、switch/detach 使旧 ticket 失效、
  pending mutation 在 detach/disconnect/EOF 后变为 unknown、lag 使 view stale 但不臆测独立 response 丢失、response loss 禁止重放、
  known success 强制重读、无副作用 rejection 保留 fresh，以及 reconnect 后拒绝旧 connection completion。
- app-server 公共 JSON-RPC 测试覆盖：experimental capability 与产品 gate 分离、state DB 不可用返回 incomplete、list/read 不激活
  Session、prototype lifecycle 保留来源、archive/unarchive 不加载 Session、loaded child 投影为 non-owner 且 mutation 拒绝、loaded
  Root canonical mutation 成功且 stale expected state fail-closed。正式聚焦轮结果为 8/8 通过。
- TUI 的命令/parser/default-off gate、真实 lag/EOF event path 与四份用户可见 snapshot 最终聚焦轮为 7/7 通过；snapshot 逐份审阅，当前没有 pending 或
  `*.snap.new`。snapshot 特别保留 stale/result-unknown、closing/failed/partial/unknown `not closed` 文案和每轴 provenance。
- app-server-protocol 完整 crate 为 291/291 通过、1 个 generator test ignored；app-server-client 在设置本地 loopback `NO_PROXY`
  后为 39/39 通过。稳定与 experimental schema generator 的现有 ignored test 均通过，且稳定输出无 `ExperimentalSession*` 泄漏。
- core `--lib` 早期运行 2256 项，其中 2248 通过；8 项未通过分别为生成前的 config schema fixture 1 项和 package-only 入口未提供
  `RONDO_PUBLICATION_CRITIC_SERVICE_BIN` 的既有 7 项。config schema 随后由权威 generator 更新；Plan 070 新增 core 测试最终 4/4 通过。
- 调试期如实保留三类非 correctness 失败：仓库现有 `just write-app-server-schema` 指向已不存在的 bin，故改用同一受锁 generator
  test；未设置 `NO_PROXY` 时 10 个既有 loopback websocket 测试被代理截获；一次 app-server 宽门禁在链接阶段被资源看门狗以
  `memory_full_psi_sustained_above_limit` 主动终止，随后保留缓存并收窄到 public integration target 成功。未放宽门禁。
- 范围内自审发现 live residency 曾被错误推断为 domain lifecycle：loaded owner 被标为 `open`，non-owner/child-only 被标为
  `partial`。现已移除该推断；除 archived 的 ThreadStore 权威事实外，非 archived lifecycle 只有显式 prototype input 才赋值，
  否则为 `unknown`/`unavailable`。对应 server 8/8 与 TUI 6/6 已复验，snapshot 仅接受这一保守化差异。
- 同一轮自审把 operation provenance 从整组字段下沉到单个操作：online track 可标 `live-owner`，cold unarchive 可独立标
  `thread-store`，未实现的 archive 为 `unavailable`；没有 stored metadata 时 unarchive 不再臆测 `not-archived`，而是
  `unknown/unavailable`。
- 最终 lookup 自审发现默认关闭时精确手输 `/sessions` 仍会被隐藏命令吞掉；lookup 现在同样服从产品 gate，关闭态保持原有未知命令/
  普通输入路径，dispatch 和 App 层的双重 gate 继续作为防御。
- 独立正确性复核第一轮发现两个真实问题：已停止但仍保留 ThreadManager map entry 的 Root 可能被投影为 loaded owner；lag/EOF 只失效
  内部 controller，历史区最后一份投影仍显示 fresh。前者现以 ThreadManager current-entry read lease 与 CodexThread 同步 residency
  read/write lease 共同闭合，shutdown 先标记不可用，dead-resident read/mutation 回归 4/4 聚焦集合通过；server 公共场景复验 8/8。
  后者现由真实 lag/disconnect/EOF App 路径追加 retained projection，明确显示 `view=stale`；对应 event-path snapshot 与 TUI 原型集合
  7/7 通过。两项修复均未引入 retry、relay 或新的权威状态。第二轮独立只读复核明确 PASS，确认两项 finding 实质关闭且没有新增
  correctness 问题。

## 正式完整门禁与资源恢复

- config schema generator 在取得 070 串行所有权后成功；生成差异仅为 managed/regular 两处默认关闭的
  `experimental_session_control: boolean`。普通 `just test` 在运行测试前因 denoland V8 上游资产返回 404 失败；随后使用仓库既有
  `just test-with-codex-v8`，其 archive/binding SHA-256 分别为
  `a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583` 与
  `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506`。
- checksum V8 完整门禁以 `CARGO_BUILD_JOBS=1` 完成编译和全部 14,380 项执行：14,364 通过、1 项重试后通过、16 项失败、24 项跳过，
  run ID `c8655ead-b003-45f5-8641-491d8e605770`。失败全部在 070 精确写集之外：7 项 Publication Critic process fixture 缺少 service
  binary、1 项 Publication Critic map-order 断言、2 项 sandbox approval 的 HTTP probe、2 项 realtime event timeout、4 项 zsh-fork
  timeout；070 新增 core/server/client/protocol/TUI 测试均通过。JUnit 保留在本次 watchdog 目录，未把这些基线/环境失败改成表面成功。
- 空间恢复只删除明确可再生资产：用户指定的 11 个被替代 eval 版本共 33 个 standalone/code-mode/runtime 目录释放
  43,520,647,168 bytes，保留四个里程碑版本；070 `target/debug/incremental` 首次释放 53,383,491,584 bytes，正式门禁后再次释放
  8,376,270,580 bytes，首次最终 clippy 后第三次释放 6,055,775,236 bytes，独立复核修复后的 clippy 又使 incremental 增至
  11,477,231,911 bytes，第四次精确清理；最终 clippy 后第五次清理 7,458,688,755 bytes。均保留 deps、fingerprint、build-script、
  gn/V8、产品/测试二进制；
  `eval-data/uv-cache` 未删除。最后一次 clippy 按用户授权仅对该命令设置 265/280/285GB warn/stop/max，Windows C: 50GB、内存、swap
  与其他看门狗门禁不变，没有修改脚本或文档默认值。
- 最终受影响六 crate `just fix` 无警告通过，随后 `just fmt` 通过；遵循仓库顺序，最终 fix/fmt 后不再运行测试。独立复核修复前最后一轮
  测试证据为 core 4/4、app-server 8/8、TUI event/projection 5/5 与 default-off lookup/dispatch 2/2。
- 最终可再生 incremental 清理后 RONDO 总占用为 241,746,420,779 bytes；`eval-data/uv-cache` 仍完整保留。

## 原型接缝与正式拆包输入

- 建议保留：独立的 identity/lifecycle/residency/availability/provenance 轴；state-DB-only discovery 与 historyless read；loaded Root
  窄 façade；server/TUI 双产品 gate；connection/attachment/read/mutation generation；stale/result-unknown 后只允许显式权威 read；
  在线 optimistic Root mutation 与既有 cold lifecycle API 分责。
- 建议丢弃或不直接正式化：C0 的 `prototypeFacts` wire 输入、CLI 参数密集的 `track` 交互和当前文本布局；它们是覆盖 S1 缺口与验证
  语义的试验接缝，不应成为正式 durable Session API/UI。不要把进程内 Team projection、state DB metadata 或 client cache 升格为
  canonical durable read model，也不要新增第二套 reconnect/notification/relay 体系。
- 交给 WBS 单一整合者的 query 输入（等待 S1）：以 durable Session/Team read model 替换 prototype input，保留 per-axis provenance、
  incomplete/unavailable 与 bounded omission；确认 canonical Root identity、cold lifecycle 和 freshness 所需 revision/cursor 后再冻结正式 RPC。
- 交给 WBS 单一整合者的 control/TUI 输入（等待 S2）：保留 loaded-owner 路由、expected-state conflict、结果 unknown/no replay 与显式
  reread；待恢复/close barrier 权威形成后再决定 owner unavailable 的恢复动作、正式 operation enum 和交互布局。cold unarchive 可继续
  复用现有 Thread lifecycle，switch/detach/unsubscribe 仍只改变客户端附着。

## 独立验收整改

- 用户指定审查者的提交 `1bfdaa0` 记录了 7 项真实 correctness/合同 finding。整改后，C0 TUI 对单次 mutation request 使用固定的
  confirmation deadline；server 已接收但 response 丢失且连接保持在线时有界进入 `stale + result-unknown`，不 retry。每次调用返回
  typed per-attempt 结果，因此历史 Unknown 保留为旧操作事实，但 preflight 未提交的新操作只显示 `not submitted`。
- 真实 fault injection 通过 WebSocket 代理转发 `thread/unarchive` 给嵌入式 app-server，确认权威 mutation 已执行后丢弃 response，再在
  同一连接上执行显式 read 并迟发旧 response。最终代码形态 1/1 通过（run
  `c88cb4e5-9393-46c7-b7a4-f23ad78ff5e7`）：attempt 未永久 pending、wire 只发送一次、read 恢复 fresh，迟到 response 不覆盖新 view。
- discovery 改为直接观察 `StateRuntime::list_threads` 的成功/失败，并根据持久化 `SessionSource` 在 400 row/16 page 上限内过滤 Root 后
  继续分页。DB query error 丢弃 partial data 并返回 `unavailable/incomplete`；分类或预算不足只报告 incomplete，不把 child-only 页显示为
  authoritative none。没有读取 rollout history、取得 writer、repair metadata 或触碰 069/thread-store/rollout 所有权。
- cold unarchive 只对 stored metadata 可证明的 canonical Root 开放；archived child 和 identity unavailable fail closed。直接 child
  query 会复核 canonical Root 是否 current/running，Root 不在 current map 时与 Root-id query 一致投影为
  `OwnerUnavailable/ChildOnly`，online/cold mutation 均不可用。
- 默认关闭 feature 的 announcement 为空，不再进入进程全局 startup tooltip pool；`/experimental` 内的 opt-in 名称和说明继续保留。
  v2 `prototypeFacts` 遵循局部 wire 规则，缺省反序列化为 None、序列化显式为 `null`。
- 整改聚焦证据：protocol/features 327 项通过、1 项跳过（run `e54f7082-8593-4dc3-ac77-74be1776cdd6`）；app-server/client
  `experimental_session` 23/23 通过（run `091844aa-8cdc-45e1-8604-a17ce29edc2e`）；TUI `experimental_session` 6/6 通过（run
  `b5e76c85-dba5-42a3-b375-7022a91e55a6`），tooltip 1/1 通过（run `b0b88cd6-c2b8-44a4-9ae4-ae5e1aeac48e`）。stable 与
  experimental schema generator 各 1/1 通过（runs `b8d405e2-1cb3-4f09-bed9-6d242a948f01`、
  `70e57e79-3e84-490e-9b29-1d67f34c2933`），没有 tracked schema 差异或 `*.snap.new`。按审查决策未重跑 14k 完整门禁。
- 正式拆包输入相应收紧：query 必须保留 source error/incomplete 与 Root-filter 后分页语义；control/TUI 必须保留 Root-only cold operation、
  bounded per-attempt certainty、unknown 后显式 reread 和 no replay。C0 固定 deadline、`prototypeFacts`、文本 UI 与 state-DB
  `SessionSource` 分类仍是原型接缝，不应直接冻结为正式 durable read model 或通用 transport 平台。
- 聚焦测试与 schema 完成后，受影响的 protocol/server/client/features/TUI 五个 crate scoped `just fix` 通过并应用 1 处等价的
  collapsible-if 整理，随后 `just fmt` 通过；按仓库规则未在 fix/fmt 后重跑测试。最终 clippy 前精确删除 070 可再生的
  `target/debug/incremental` 15,923,028,986 bytes，保留其余构建产物；clippy 后 RONDO 总占用 248,540,674,571 bytes，低于本轮
  265 GB 告警线。提交前再次删除 clippy 重建的 4,385,849,609 bytes incremental，最终总占用 244,310,411,952 bytes；未清理
  `eval-data/uv-cache`。

## 同毫秒 cursor 验收整改

- 用户指定审查者的提交 `2e8d027` 确认前次 7 项 finding 均已闭合，但发现 C0 的 CreatedAt keyset 不带 thread-id tie-breaker；相同
  `created_at_ms` 的 overflow row 会被下一页的严格 timestamp 条件永久跳过，随后仍可能报告 complete。
- 新增公共 JSON-RPC 回归创建 26 个相同 `2026-08-24T12:30:00.123Z` 的 Root，以 limit 25 逐页枚举。旧实现稳定复现第一页 25 条、
  timestamp-only cursor、第二页 0 条的错误（run `03d16a7a-9b6a-487b-8810-2a96cb18c083`，两次尝试均失败）。
- 最窄修复只把 C0-owned app-server discovery 的 state 查询键切换为现有 `RecencyAt`；该 state keyset 已以 thread id 作为同毫秒
  tie-breaker，现有 C0 cursor codec 也已支持 `timestamp|threadId`。没有改 protocol、state、thread-store、rollout 或 TUI，也没有新增通用
  分页设施。修复后同一回归 1/1 通过（run `23ab43b6-5423-41ba-8f44-83af3378b91f`），26 个 Root 无重复无遗漏，第二页返回最后一条并
  正确耗尽 cursor；app-server `experimental_session` 全集 13/13 通过（run `85e47146-0249-4c7f-a35b-e634691ab5bd`）。
- 本轮没有协议/schema 变化，按审查边界未重跑 generator、TUI/client/protocol 或 14k workspace 门禁。正式 query 拆包输入应保留稳定
  双键 cursor；C0 选择产品 recency 只是原型排序策略，不提前冻结正式 durable Session 排序合同。
- app-server scoped `just fix` 无 warning、无额外代码修正，随后 `just fmt` 通过；按仓库顺序未在 fix/fmt 后重跑测试。提交前精确删除
  本轮最终 clippy 重建的 7,291,357,600 bytes 070 incremental，保留其余构建产物和 uv cache；RONDO 最终约
  244,621,749,674 bytes，低于本轮 265 GB 告警线。
