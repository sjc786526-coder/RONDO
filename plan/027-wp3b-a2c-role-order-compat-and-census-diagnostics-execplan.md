# Plan 027：WP3b-A2c provider-neutral 角色顺序兼容与 census 最小失败定位

> 本计划是本任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只处理角色顺序兼容与 census 最小失败定位；跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

在公共 `build_static_payload()` 边界无损规范化已确认的会话角色顺序，使 Luna-static、Sol-static、
Local-static 继续消费同一份 provider-neutral static payload，并让现有 23 条
`assistant → developer` 归档通过冻结模板的无模型兼容检查。

同时为 exact-token census 的通用计数失败补充最小、非敏感的定位字段，使后续失败至少能区分锚点计数与
全集遍历、定位当前归档，并知道失败前已有多少条成功计数。本任务不加载模型，也不重跑 census。

### 完成/验收标准

- static input payload 显式升级为 v3；旧 v2 不能被新 sink 静默接受。结构化决策输出 schema 继续保持
  `rondo_static_approval_v1`。
- 已知 23 条角色序列全部通过冻结模板的无模型兼容检查；既有 47 条归档 47/47 均能构造统一 static payload
  与 Local static 请求。
- 对每条归档，Luna-static、Sol-static、Local-static 的 provider-neutral canonical bytes 完全一致；
  Standard / Responses Lite 的既有等价合同不退化。
- 角色规范化不丢失、重排或改写归档中的可见文本；归档里的 developer 内容仍是会话证据，不能被提升为
  Guardian policy、塞进 provider 私有旁路或直接删除。未知、畸形或无法证明可无损解释的角色形状 fail-closed。
- raw reasoning、encrypted 内容、provider session id、warehouse-only metadata 与 provider 私有字段继续不出站；
  policy exact bytes/hash、非角色证据顺序和结构化输出合同保持不变。
- 模拟锚点通用失败与全集中某条归档通用失败时，错误分别给出有界阶段、当前 `e_final_sha256` 和失败前成功
  计数条数；不记录证据正文、完整请求、渲染 prompt 或服务端自由文本。
- 任一拒绝、通用失败或其他部分结果都不能生成正式 exact-token baseline；通用 500 仍 fail-closed，不得改成
  “样本拒绝后继续”。
- 直接相关 focused tests、47 条只读结构检查与 eval dependency lock 通过；capability、qualification 和
  baseline 状态不变。

## 2. 范围

### 允许修改

- `eval/rondo_eval/evidence.py` 中公共 static payload 的角色规范化、版本和终端验证合同。
- `eval/rondo_eval/local_approval/client.py` 及必要的直接调用点，仅用于一致消费 v3；不得在 consumer 侧增加
  provider-specific 二次转换。
- `eval/rondo_eval/local_approval/token_census.py` 中通用计数失败的最小阶段/归档定位。
- `eval/tests/test_contracts_and_evidence.py`、`eval/tests/test_local_approval.py` 及少量直接相关合成 fixture；
  若既有 policy identity consumer 因版本升级需要同步，可只补其直接 focused regression。
- 本计划的“当前状态”和“关键决策记录”；完成后精炼更新 `doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、成功记录所需的 `doc/WBS-COMPLETED.md`，以及一份 `agent_log/`。
- 只读使用 Git common root 下 ignored 的 47 份 `E_final`/meta 和既有冻结模板资产，只在内存中做聚合式
  结构、构造和兼容检查。

### 不允许修改

- 47 份真实归档/meta、冻结模板/runtime/model/lock、`rondo.local.toml`、资格档位、qualification、launcher、
  capability 投影或现有 qualification evidence。
- `eval/results/baselines/local-approval-exact-token-census-v1.json` 或任何新的 token baseline、token 统计结果、
  正式资格/能力成功 evidence。
- `mydev/`、`multidev/`、冻结上游源码、依赖版本或无关测试/测评设施。
- Plan 024—026、既有日志、研究报告或审计快照；它们是形成时点的历史记录。
- 不新增通用 schema registry、审计/provenance/attestation 系统、长期诊断数据库或专用批处理框架。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash、source 或经 secret loader 间接加载。
- 不把真实证据正文、正文派生文本、完整请求体、渲染 prompt、token ids/pieces 或服务端自由文本输出到
  控制台、测试失败信息、日志或 Git。

## 3. 硬约束

1. **版本必须前进。** 修复已知 23 条角色顺序会改变其规范化语义或 canonical bytes，因此 static input
   schema 从 v2 升为 v3；`PolicyIdentity`、logical payload、validator、consumer sink 与相关文案必须一致。
   不保留会静默改写 v2 的兼容入口。decision output schema 和 census result schema 不因名称整齐而随动。
2. **唯一规范化边界仍是公共 builder。** 角色兼容只能落在 `build_static_payload()` 或其私有助手中；三个
   consumer、Local client 和 token census 不得各自转换角色，也不得按 llama.cpp、Luna 或 Sol 分支处理。
3. **保留证据语义与顺序。** 已知 developer 消息的可见文本及相对顺序必须保留，不能并入 Guardian policy/
   instructions、不能丢弃或内容改写，也不能跨越 tool call/output 等证据重排。具体采用合并、分组或中立证据
   投影由执行者结合现有合同决定，只要能直接证明无损且三方同字节。
4. **角色形状 fail-closed。** 规范化只接受实现明确理解并能无损处理的消息角色/content 形状；未知 role、
   缺失 role、畸形 content、歧义边界或无法证明无损的组合必须抛出 `EvidenceError`。本任务不要求重建完整
   Responses schema，但不能用递归 scrub 或默认 passthrough 吞掉未知角色问题。
5. **既有出站边界不回退。** Plan 025 对 reasoning summary/raw content、encrypted/provider id、tool authorization、
   passthrough metadata 和未知形状的处理继续成立；最终 validator 仍要拒绝私有字段伪造回流。
6. **消费者合同不分叉。** 逻辑等价的 Standard/Lite 输入继续得到相同 canonical bytes；三 consumer 的
   `static_payload_bytes_for_consumer()` 逐字节一致。Local request 和 census 继续只从通过 v3 validator 的同一
   payload 构造，不另造“仅为计数可用”的请求。
7. **冻结模板验收只做无模型检查。** 23 条已知问题必须对冻结模板的角色顺序规则表现为兼容；检查可复用
   冻结模板资产或等价的窄结构检查，但不得启动服务、加载 GGUF、调用 count endpoint 或把 provider 特判写入
   生产 consumer。
8. **census 诊断保持最小。** 通用归档计数失败的稳定 facts 至少包含：
   `stage`（有界区分 `anchor_count` / `archive_count`）、当前 `e_final_sha256`、
   `counted_before_failure`（失败前已经成功取得 exact count 的唯一归档数）。可增加不泄露正文的稳定序号，
   但不得保存路径、请求、证据文本或自由格式追踪信息，也不建设通用事件系统。
9. **失败语义不变。** 锚点或全集遍历遇到通用 500/transport failure 时立即停止并不发布结果；仅既有明确
   structural refusal 可沿用原 incomplete 语义。新增诊断不能把 endpoint/infra 错误降级成某条样本的属性。
10. **只读 47 条聚合验收。** 复用生产 reader/meta 校验、公共 builder 与 Local request builder 检查完整集合；
    只报告计数、布尔门禁和稳定摘要，不生成 tracked/ignored 派生报告，不复制真实正文到 fixture。
11. **只跑必要门禁。** 运行 evidence/local-approval/census 直接相关 focused tests、47 条只读结构检查和
    eval lock；不运行全量 eval、Cargo、Docker、真实/本地模型、GPU、云 API、网络服务或 generation。
    skip/未运行不得表述为通过。
12. **状态与文档口径不漂移。** 完成后 WP3b-A2 仍是 blocked/incomplete，直到另行授权真实 census 并取得
    47/47 exact count；不得选择上下文档位、发布 token 分布、解释 Plan 026 的具体 500、晋级 qualification
    或 capability。WBS 只更新当前状态和后续授权门，详细证据只进计划/精炼日志/完成历史各自职责处。
13. 实现、测试、文档和提交只在分支 `027-wp3b-a2c-role-compat-census-diagnostics`、worktree
    `.claude/worktrees/027-wp3b-a2c-role-compat-census-diagnostics` 内进行；执行者提交后停止，不合并、不推送、
    不删除 worktree，交由 Codex 独立审查。

## 4. 软性建议

- 先用小型合成序列复现 `assistant → developer → user`，再选择最窄的无损规范化方式；不要为了适配单个模板
  建立通用对话重写器。固定的中立结构标记若确有必要，应保持最小、版本化并由三方共同消费。
- 角色规范化宜与现有 reasoning 投影相邻但职责分开，便于分别测试；不要求抽象成新 crate/package 或注册表。
- census 可在调用锚点/当前归档的窄边界为既有 `CensusError` 补 facts，不要求改写 HTTP helper 或引入 tracing。
  focused regression 至少直接覆盖“锚点通用 500”和“锚点成功后某条归档通用 500”。
- 47 条检查可从 worktree 通过 `RepoPaths.common_root` 读取主仓 ignored 归档；共享 ignored venv/cache 也可只读复用。
  这不要求在主工作区编辑文件。eval lock 可使用指向 common-root cache 的
  `uv lock --directory eval --check` 等价入口，避免在 worktree 复制缓存。
- 推荐复用 Plan 025 的 focused test 入口并按实际改动增加最少用例；若 static payload 版本影响
  `test_terminal_bench.py` 中唯一直接 consumer，再单独运行该用例，不扩大为全量 suite。

## 5. 当前状态

### 已完成

- 2026-08-14：核对主工作区 clean，`main == origin/main == 78aefb1`；024—026 worktree 均为保留的
  `zz-done/*`，未触碰。
- 2026-08-14：从 `78aefb1` 创建本任务专用分支与 worktree，阅读根规则、README、当前 WBS、方向 2 子 WBS、
  Plan 模板、Plan 024—026、相关日志、`mydev/AGENTS.md` 和当前 evidence/client/census/tests 实现。
- 2026-08-14：确认当前公共 static input schema 为 v2；`_neutral_items()` 只投影 reasoning，其他消息角色原样
  进入 payload；Local client 与 census 共用同一 validated request builder。
- 2026-08-14：确认 Plan 026 当前诊断缺口：锚点和集合归档的通用计数错误使用相同 code，失败 facts 不含
  当前归档与失败前成功计数数；已验收历史只证明真实归档计数阶段发生通用 500，不能定位具体请求或根因。
- 2026-08-14：完成本执行计划；未修改实现或 WBS，未读取真实正文，未运行测试、模型、Cargo、Docker 或网络。
- 2026-08-14：只读聚合扫描 47 条归档的 item 形状：全部 Responses Lite，只有 6 种 role 序列，消息 item 仅
  `user`/`developer`/`assistant`，content 全部是单一 `input_text`/`output_text`；据此确定唯一需要处理的
  不兼容形状是 `assistant`（及 `tool`）之后的 `developer`。
- 2026-08-14：只读核对冻结 llama.cpp b10333 的 `server_chat_convert_responses_to_chatcmpl`、
  `map_developer_role_to_system` 与冻结模板的顺序规则，确认在所有前驱角色之后都被接受的是 `user` 与
  `assistant` 两种角色；归档 developer 消息是输入侧 `input_text`，因此 `user` 是语义正确的那一个。
- 2026-08-14：落地 static input payload v3：公共 `build_static_payload()` 内把证据消息的 `developer` 原地
  改写为 `user`，只改 role，不动文本、顺序、消息边界与其余字段；未知/缺失 role、非消息 item 带 role、
  空或畸形 content、与 role 不匹配的文本 subtype 一律 `EvidenceError`。终端 validator 增加
  `_reject_unnormalized_roles`，v1/v2 payload 与手工回填的 `developer`/`system` 均无法通过 sink。
- 2026-08-14：为 census 补最小失败定位：`anchor_count` / `archive_count` 两个有界 stage、当前
  `e_final_sha256` 与 `counted_before_failure`。通用 500/transport 仍在两处立即停止，未降级为样本拒绝；
  `RequestRejected` 的 per-record `refusal` 字段未被污染。
- 2026-08-14：补 focused regressions —— 角色规范化保序保文本、17 种畸形/未知消息形状 fail-closed、
  v3 与旧版本 sink 拒绝、sink 拒绝回填 role、census 请求含 `assistant → developer` 归档、
  锚点通用 500 与锚点成功后归档通用 500 各 1 项，以及从冻结模板资产解析规则的角色顺序门（含反向控制）。
- 2026-08-14：focused tests 116/116、`test_terminal_bench` 中唯一 `policy_identity` 消费用例 1/1、
  `uv lock --directory eval --check` 85 packages 通过。
- 2026-08-14：47 条只读聚合检查（无模型、无网络、不输出正文）：47/47 构造 v3 payload 与 Local 请求，
  三 consumer 逐字节一致 47/47，出站无残留 `developer`/`system` role 与 reasoning/encrypted；同一冻结模板
  角色顺序门下 v3 为 47/47 通过，规范化前为 24/47 通过、23 条 `Unexpected role 'system' after role 'assistant'`，
  与 Plan 026 的离线结论一致。

- 2026-08-14：首轮独立审查（`0603008`）不通过，提出两处阻断与两处事实表述错误，已全部复核成立并完成窄整改：
  1. **拒绝后的健康探针失败缺定位**：`_probe_count_endpoint()` 在 `except RequestRejected` 分支内抛出的
     `CensusError` 不会被同级 `except CensusError` 捕获，因此没有 stage/digest/counted。已就地包一层，
     用当前归档与 `archive_count` 补齐同样三项，并把回归从「只断错误码」加强到断言三个字段。
  2. **终端 sink 只校验角色集合**：`role=user` 配 `output_text`、`content=[]`、`type=custom_tool_call`
     配 `role=user` 这类伪造 v3 payload 仍能通过 `validate_static_payload()` 抵达
     `LocalApprovalClient.build_request()`。已抽出共享的 `_require_neutral_message()`，由 builder 与
     final sink 复用同一份中立消息合同；未新增字段 allowlist、schema registry 或审计设施。
  3. 修正「`user` 是唯一合法后继」的事实错误：模板允许后继的交集是 `{user, assistant}`，
     选择 `user` 的真实理由是归档 developer 为输入侧 `input_text`，映射为 `user` 只换 role 标签。
  4. 修正 `build_request()` docstring 中「三 consumer 收到与 census 相同字节」的表述：
     三 consumer 共享的是 canonical logical payload，census 计数的是由它构造的 Local provider request。
- 2026-08-14：整改后复跑 focused tests 116/116、下游 `policy_identity` 用例 1/1、
  `uv lock --directory eval --check` 85 packages、47 条只读聚合检查（47/47 与 24/47 均不变）；
  另以审查者的伪造构造直接复现，三种畸形形状现在在 `validate_static_payload()` 与
  `build_request()` 两处都被拒绝。
- 2026-08-14：最终独立复验确认两处阻断均已闭环，未发现新的任务内阻断；独立复跑 focused tests
  116/116、下游用例 1/1、eval lock 与 47/47 聚合检查均通过，Plan 027 验收通过。

### 当前工作

- 任务已通过最终独立复验并完成；本计划冻结，后续路线只由两份 WBS 承接。

### 本任务剩余步骤

- 无。

### 阻塞项

- 无。用户已授权普通项目内开发与只读处理 47 条归档；本任务不需要 GPU、模型、网络或人工操作。

### 当前验收状态

- 最终独立复验通过：v3 角色兼容、终端消息形状 fail-closed、census 最小失败定位、focused tests、
  47 条只读检查与 eval lock 均已闭环。
- 未运行：真实模型、GPU、count endpoint、census 重跑、任何 generation、Cargo、Docker、云 API、全量 eval。
  因此本次只证明构造层与冻结模板角色顺序兼容，**不证明** 47 条在真实 b10333 上可完成计数。
- WP3b-A2 仍 blocked/incomplete；Plan 026 的具体通用 500 仍未定位，正式 exact-token baseline 仍不存在，
  未选上下文档位，capability 仍为 `linux_cuda_built_model_unvalidated`，qualification 状态不变。

### 交接边界

- 本任务完成后冻结本计划。后续真实 47/47 census 必须重新取得模型授权；重跑、档位选择与 qualification
  只按两份 WBS 推进，不在本计划追加。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 角色兼容只落在公共 static builder | 三个 consumer 必须同源同字节，不能形成 Local/llama.cpp 旁路 | evidence 与 static consumers | 已采纳 |
| 002 | static input schema 升 v3，decision output 保持 v1 | 23 条兼容会改变规范化语义/字节；两个版本合同相互独立 | 版本、validator、调用点与测试 | 已采纳 |
| 003 | 不预先固定具体角色转换算法 | 无损、保序、provider-neutral 和模板兼容是硬结果，实现可结合现有形状选择最窄方案 | builder 实现 | 已采纳 |
| 004 | 诊断只增加阶段、归档 digest 与失败前计数 | 足以区分 Plan 026 当前盲区，无需通用追踪/审计设施 | token census | 已采纳 |
| 005 | ignored 归档和共享 cache 只从 common root 复用 | worktree 已能安全解析主仓公共根，不需要在 main 直接开发或复制数据 | 验收环境 | 已采纳 |
| 006 | 角色转换选择「`developer` 原地改写为 `user`」 | 现有归档只有 user/developer/assistant 三种消息角色；冻结模板中在所有前驱角色之后都合法的是 `user` 与 `assistant`，而归档 developer 消息是输入侧 `input_text`，改成 `user` 只换 role 标签，改成 `assistant` 则会改变说话者并被迫重写文本 subtype。这是保留文本、顺序与消息边界的最窄改法，也不需要新增中立结构标记 | 公共 builder 与三 consumer 的 canonical bytes | 已采纳 |
| 007 | 改写无条件执行，不按前驱角色决定 | 按位置改写会让同样的证据因所处位置得到不同角色，并把某个模板的顺序规则暗中写进本应 provider-neutral 的 payload | 角色规范化语义 | 已采纳 |
| 008 | 只改 role，其余消息字段沿用 v2 处理 | `phase`、`id`、passthrough metadata 的处理属于 Plan 025 已定的合同，本任务不顺带改动；扩大到消息级 metadata 会超出角色兼容范围 | 规范化边界与既有回归 | 已采纳 |
| 009 | 冻结模板的角色顺序门只存在于测试，并从模板资产解析规则 | 硬约束 7 禁止把 provider 特判写进生产 consumer；从资产解析而非手抄规则可避免门禁与真实模板漂移 | `eval/tests/test_local_approval.py` | 已采纳 |
| 010 | builder 与 final sink 复用同一份 `_require_neutral_message()` | 硬约束 5 要求终端 validator 拒绝伪造回流，而 `build_request()` 把它当唯一 gate；只校验角色集合会放行 builder 绝不会产出的消息形状 | 规范化边界与终端校验 | 独立审查要求，已采纳 |
| 011 | 拒绝后的健康探针失败沿用同一组定位 facts | 它同样是遍历阶段的通用失败，Plan 026 的盲区正是「不知道停在哪」；stage 仍只有两个有界取值 | token census | 独立审查要求，已采纳 |
