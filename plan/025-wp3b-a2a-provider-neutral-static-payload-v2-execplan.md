# Plan 025：WP3b-A2a provider-neutral static-payload v2 兼容

> 本计划是本任务的稳定合同。除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若需改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理 static payload 兼容；跨任务路线以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

把 OpenAI Responses `E_final` 中不能被各 provider 直接消费的 `reasoning` item，在公共
`build_static_payload()` 边界投影成显式版本化的 provider-neutral static payload v2，使
Luna-static、Sol-static、Local-static 对同一证据获得逐字节相同的规范化 payload。

本任务解决已证实的 21 份归档形状兼容，不做 llama.cpp 专用补丁。投影不生成原文中不存在的内容，
不暴露 encrypted/raw reasoning；没有公开内容、只用于原 provider 会话连续性的 item 可以删除；
只有语义明确的公开内容才转成普通、无 provider 私有字段的证据消息。未知、歧义或 malformed 形状继续
fail-closed。

## 2. 范围

### 允许修改

- `eval/rondo_eval/evidence.py` 的 static payload 构造、验证与 canonical bytes 合同。
- `eval/rondo_eval/local_approval/client.py`、`token_census.py` 及其他确有必要的 `eval/` 调用点，
  仅用于统一消费 v2 builder/API；不得顺带改变 qualification、launcher 或 capability 行为。
- `eval/tests/test_contracts_and_evidence.py`、`eval/tests/test_local_approval.py` 及少量直接相关 fixture。
  fixture 只能使用合成文本，不得复制 47 份真实归档正文。
- 本计划的当前状态；完成后精炼更新 `doc/WBS.md`、`doc/WBS/local-approval-model.md`、
  `doc/WBS-COMPLETED.md` 和一份 `agent_log/`。
- 只读使用主仓 ignored `eval-data/runs/*/guardian-evidence/*/E_final.json` 的既有 47 份归档，
  仅做内存中的结构解析和请求构造检查。

### 不进入

- `mydev/`、`multidev/`、上游基线、Cargo、Docker、真实/本地模型、GPU、云 API、训练或依赖升级。
- exact-token 重跑、那 2 条通用 500 的诊断或解决声明、token baseline 发布、4k/8k/12k 等档位选择。
- capability、qualification success evidence、model-backed evidence schema、正式 launcher gate、L7、
  Local M3、压缩或裁剪。
- 47 份归档、meta、现有 lock、ignored 本机配置的修改；真实正文、正文派生内容和完整请求体不得进入
  控制台、日志、fixture 或 Git。
- `.env.local` 内容：不得打开、搜索、打印、复制、hash、source 或通过测试/工具间接加载。

## 3. 完成合同与硬约束

1. **输入合同显式升为 v2。** 新 builder 产物、policy identity 和终端 validator 必须一致声明
   static payload schema v2；v1 payload 不能被 v2 sink 接受或被静默当成 v2。canonical JSON 继续使用稳定的
   UTF-8、sorted keys、无 NaN 序列化。
2. **版本边界清楚且不越界。** `rondo_static_approval_v1` 当前标识的是结构化判定输出 schema，并被
   qualification evidence 使用；本任务版本化的是输入 static payload。输出判定 schema 若未改变，应继续保持 v1，
   不得为了名称整齐而修改 qualification success evidence。
3. **唯一投影边界是公共 builder。** `reasoning` 规范化必须发生在 `build_static_payload()` 或其私有助手中；
   Local client、token census 和任何 provider consumer 不得各自再做删减或 provider-specific fallback。
4. **只保留明确公开的内容。** 当前 47 份归档中，21 份共含 24 个 `reasoning` item；只读结构扫描确认
   24 个都是 `type=reasoning`、字符串 `encrypted_content`、空 `summary`，且没有 `content`。
   v2 必须接受并移除这些 item，不得把原始 reasoning object 或 encrypted bytes 带入 canonical payload。
   有明确公开语义的 summary/content 必须按原顺序和原 UTF-8 文本转成统一的 provider-neutral 证据形态，
   不增加摘要、标签、占位符或推断内容；raw/encrypted reasoning 不得出站。未知、歧义或 malformed 形状继续
   fail-closed，不能因为最终可能删除而被静默吞掉。
5. **Standard/Lite 与三个 consumer 等价。** 逻辑等价的 Standard 与 Responses Lite 输入在 v2 中产生相同
   canonical bytes；policy exact bytes/hash、非 reasoning 证据的顺序与既有语义保持不变。
   `static_payload_bytes_for_consumer()` 对 Luna-static、Sol-static、Local-static 返回完全相同的 v2 bytes，
   且其中不再存在原始 `type=reasoning` item。
6. **工具与私有运输字段继续清除。** 顶层 `tools`、Lite `additional_tools`、
   `encrypted_function_args`、warehouse-only `executed_tool_calls` 和 reasoning 私有内容不得进入 static payload；
   已有合法 `tool_search_output.tools` 证据仍保留。最终 validator 必须能拒绝伪造回流。
7. **Local 与 census 共用同一请求构造。** Local client 必须只接收通过 v2 validator 的 payload；token census
   的归档请求和合成 probe 都继续调用同一个 Local v2 request builder，不得另造请求或重新引入 v1 路径。
8. **47 份真实归档只读通过。** 在任务 worktree 中通过 Git common root 访问既有 47 份归档，复用现有安全读取
   和请求构造设施完成 47/47 静态构造，其中已知 21 份 reasoning 归档全部成功。检查不调用网络或模型，
   不输出或保存正文、正文派生内容和完整请求体。
9. **状态边界不漂移。** 任务结束时 capability 仍为 `linux_cuda_built_model_unvalidated`；
    `eval/results/baselines/local-approval-exact-token-census-v1.json` 仍不存在；不得新增 census baseline、
    qualification evidence 或 launcher success evidence，也不得宣称那 2 条 500 已解决。
10. **只跑必要门禁。** evidence、local-approval、census focused tests 与 `just eval-lock` 通过；不运行
    Cargo、Docker、真实服务、真实模型、云 API 或全量 eval tests。skip/未运行不得表述为通过。
11. **及时同步权威文档。** 完成后更新本计划当前状态、`doc/WBS.md`、
    `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 和一份精炼 `agent_log/`；WBS 只保留当前状态、
    路线和交接，详细执行证据不在多份文档重复堆叠。
12. 实现、测试、文档和提交只在分支 `025-wp3b-a2a-static-payload-v2`、worktree
    `.claude/worktrees/025-wp3b-a2a-static-payload-v2` 内进行；执行者提交后停止，不合并、不推送、不删除 worktree，
    交由 Codex 独立审查。

## 4. 实现建议（非强制）

- 可把“static input payload schema version”和“structured decision schema name/version”拆成语义清楚的常量，
  以免把本任务的 v2 错套到现有 decision/qualification v1；不要求为此扩展成通用 schema registry。
- 可先验证已知 reasoning 字段和 subtype，再决定移除或投影，避免通用 recursive scrub 吞掉未知形状。
- 中立公开内容可复用 Responses 已有的 `message(role=assistant, content=[output_text...])` 形态；若现有代码与测试
  支持更简洁且同样 provider-neutral 的形态，执行者可以采用。无需建立新 evidence 类型或对话系统。
- census 复用同一 v2 builder 可用 deep equality、mock/spy 或其他直接测试证明，不固定测试技巧。
- 47 条只读检查优先复用 `token_census.collect_evidence_inputs()` 的完整集合、生产 reader 和 meta 校验，
  再完成三个 consumer 和 Local request 的内存构造；无需新增长期 CLI、审计报告、manifest 或 tracked fixture。
- 本任务没有依赖变化。focused tests 推荐使用主仓已有 ignored venv/cache，但从任务 worktree 加载当前代码：

  ```bash
  common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
  env \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
    UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
    UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
    uv run --directory eval --frozen --no-sync \
    python -B -m unittest -v \
      tests/test_contracts_and_evidence.py \
      tests/test_local_approval.py
  just eval-lock
  ```

  执行者可依据实际改动再缩小到具体 test class，或补一个直接相关的 config test；不得扩大成全量 eval。

## 5. 实施与验收顺序

1. 确认位于指定 worktree/分支并阅读相关实现；在完成合同内自行安排测试与实现顺序。
2. 落地公共 v2 投影，更新必要 consumer/census 调用点并补 focused regressions。
3. 运行 §4 的 focused tests、`just eval-lock` 和 47/47 只读静态构造检查；只修本任务直接原因。
4. 检查本任务 diff、正文泄露和意外生成物，及时同步本计划、两份 WBS、WBS-COMPLETED 与精炼日志。
5. 通过 `git diff --check` 后在任务分支提交，报告 commit、验收结果和未运行项，交给 Codex 审查。

## 6. 当前状态

### 已完成

- 2026-08-14：阅读根规则、README、当前 WBS、方向 2 子 WBS、Plan 模板、Plan 024、相关日志、
  `mydev/AGENTS.md` 及现有 evidence/client/census/tests 实现。
- 2026-08-14：确认主工作区 clean `main@a66f497` 且等于 `origin/main`；已有 024 worktree 为已完成分支，
  未发现冲突；创建本任务专用 worktree 和分支。
- 2026-08-14：只读聚合检查 shared ignored 47 份归档，未输出正文：47 份均为 Responses Lite；21 份包含
  24 个 reasoning item，24 个均为 `encrypted_content:string + summary:[]` 且无 `content`。
- 2026-08-14：确认公共 `build_static_payload()` 是三个 consumer 的共同规范化边界，Local client 与 token census
  已共享请求 builder；确认 linked worktree 的 `RepoPaths.common_root` 可直接只读访问主仓 ignored 归档。
- 2026-08-14：按用户反馈精简执行合同；保留文档及时同步和关键结果边界，把具体中立消息形态、测试技巧、
  验证顺序及不必要的标识输出限制改为软建议或删除。
- 2026-08-14：只读核对冻结 b10333 的 Responses adapter，确认拒绝原因是它要求 `reasoning.content` 为非空数组，
  而 `message(role=assistant, content=[output_text])` 是它接受的形态，据此选定中立消息形态。
- 2026-08-14：落地 static input payload v2：拆出 `STATIC_PAYLOAD_SCHEMA_VERSION=2` 与
  `STATIC_DECISION_SCHEMA_NAME`（决策输出仍为 v1），reasoning 投影只发生在公共 `build_static_payload()`，
  终端 validator 拒绝 v1 payload、残留 `type=reasoning` 与任何 `encrypted_content`。
- 2026-08-14：补 focused regressions（evidence 5 项、client 1 项、census 1 项），并以逐字节相等证明
  token census 的请求就是 Local client v2 builder 的产物。
- 2026-08-14：focused tests 106/106、`just eval-lock` 通过；47/47 归档完成无网络无模型的只读静态构造检查。
- 2026-08-14：首轮独立审查（`41bc1f3`）不通过，提出 F1（把 raw reasoning `content` 当公开内容投影）与
  F2（reasoning 的 passthrough metadata 任意值被静默丢弃）。已独立复核冻结上游确认两项成立：
  `event_mapping.rs` 把两个 content subtype 一并映射为 `raw_content`，`reasoning_text()` 只在
  `show_raw_agent_reasoning` 打开时才展示它们；`InternalChatMessageMetadataPassthrough` 是强类型可选对象。
- 2026-08-14：完成窄整改 —— 只有 `summary[].summary_text` 进入中立证据消息；`content[]` 的
  `reasoning_text`/`text` 先按已知 raw 形状校验再丢弃，没有公开 summary 的 item 整项删除；
  passthrough metadata 按冻结结构校验后丢弃。补 2 项新回归并扩充畸形形状用例，
  修正代码注释、测试命名与文档中的完成声明。
- 2026-08-14：整改后 focused tests 108/108、`just eval-lock` 通过；47/47 只读静态构造检查复跑仍为
  47/47 通过、24 个 item 全部删除、0 条走投影分支、私有运输残留 0。
- 2026-08-14：复审判定 F1 已闭环、F2 只闭到 metadata 外层（`executed_tool_calls` 元素未校验）。
  复核冻结 `ExecutedToolCall` 为 `name: String` + untagged JSON `arguments` 两个必备字段后完成补充整改：
  每个 call 必须是键恰为 `{name, arguments}`、`name` 为字符串的对象，`arguments` 保持任意 JSON，
  校验后 metadata 仍整体删除；补 1 项正向与 5 项畸形回归，并修正两处文档勘误。
- 2026-08-14：补充整改后 focused tests 109/109、`just eval-lock` 通过；47/47 只读静态构造检查结果不变。

### 当前工作

- 窄整改、补充整改、回归与文档修正已完成，等待独立复审。

### 本任务剩余步骤

- 交由 Codex 独立复审；复审通过后才写 `doc/WBS-COMPLETED.md` 完成记录，合并与推送由用户决定。

### 阻塞项

- 无。本任务已有普通项目内执行与只读处理 47 份归档的授权。

### 当前验收状态

- 首轮独立审查不通过；窄整改后待复审，因此本任务尚未收口，`doc/WBS-COMPLETED.md` 暂不写完成记录。
- 已运行（补充整改后）：`tests/test_contracts_and_evidence.py` 与 `tests/test_local_approval.py` 共 109/109 通过；
  `just eval-lock`（85 packages）通过；`tests.test_terminal_bench` 中唯一消费 `policy_identity` 的用例 1/1 通过；
  47/47 只读静态构造检查通过（47 份 payload v2、三 consumer 逐字节一致、47 条 Local 请求构造成功，
  21 份归档的 24 个 encrypted-only reasoning item 全部移除，出站请求无 `reasoning`、无 `encrypted_content`）。
- 未运行：真实模型、GPU、census 重跑、Cargo、Docker、云 API、全量 eval tests。
  因此本次只证明静态构造与合同等价，**不证明**那 21 份在真实 b10333 上可服务，也不涉及那 2 条通用 500。

### 交接边界

- 本任务完成后冻结此计划；后续重跑 47/47 exact-token census、诊断残留通用 500 和选择上下文档位，
  只按两份 WBS 的路线另行推进，不在本计划中追加。

## 7. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 兼容落在公共 `build_static_payload()` | 三个 static consumer 必须同源、同字节，不能形成 llama.cpp 旁路 | evidence 与所有 static 调用点 | 已采纳 |
| 002 | 已知 encrypted-only 空 summary item 删除 | 它没有可见证据，只承载原 provider 连续性；复制会泄露私有运输内容并破坏兼容 | 21 份归档、24 个 item | 已采纳 |
| 003 | 公开内容转为统一的 provider-neutral 证据形态，raw/encrypted 不出站 | 保留明确公开内容与顺序，不生成文本，也不泄露隐藏推理；具体合法消息形态由实现验证决定 | v2 input 规范化 | 已采纳 |
| 004 | static input 升 v2，decision/qualification schema v1 不随动 | 两者版本含义不同，任务明确禁止修改 qualification success evidence | 版本命名、validator、Local client | 已采纳 |
| 005 | 47 条只做一次聚合式只读检查，不建新审计设施 | 真实归档是本机 ignored 数据；一次结构兼容验收已足够且不应派生正文工件 | 验收与日志 | 已采纳 |
| 006 | 只有 `summary[].summary_text` 算公开内容；`content[]` 的 `reasoning_text`/`text` 校验后丢弃 | 冻结 Codex 把两个 content subtype 映射为 `raw_content` 并默认隐藏，属决策 003 所说的 raw reasoning | v2 投影与回归 | 独立审查要求，已采纳 |
