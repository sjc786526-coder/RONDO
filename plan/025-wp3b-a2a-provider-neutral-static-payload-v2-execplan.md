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
- 47 份归档、meta、现有 lock、ignored 本机配置的修改；不得把正文、渲染请求、token、逐条摘要或
  派生 fixture 写入控制台、日志、临时文件或 Git。
- `.env.local` 内容：不得打开、搜索、打印、复制、hash、source 或通过测试/工具间接加载。

## 3. 完成合同与硬约束

1. **输入合同显式升为 v2。** 新 builder 产物、policy identity 和终端 validator 必须一致声明
   static payload schema v2；v1 payload 不能被 v2 sink 接受或被静默当成 v2。canonical JSON 继续使用稳定的
   UTF-8、sorted keys、无 NaN 序列化。
2. **版本边界必须说清。** `rondo_static_approval_v1` 当前标识的是结构化判定输出 schema，并被
   qualification evidence 使用；本任务版本化的是输入 static payload。输出判定 schema 若未改变，应继续保持 v1，
   不得为了名称整齐而修改 qualification success evidence。实现中应让两种版本含义从命名、验证和测试上可区分。
3. **唯一投影边界是公共 builder。** `reasoning` 规范化必须发生在 `build_static_payload()` 或其私有助手中；
   Local client、token census 和任何 provider consumer 不得各自再做删减或 provider-specific fallback。
4. **已知连续性 item 可安全移除。** 当前 47 份归档中，21 份共含 24 个 `reasoning` item；只读结构扫描确认
   24 个都是 `type=reasoning`、字符串 `encrypted_content`、空 `summary`，且没有 `content`。
   v2 必须接受并移除这些 item，不得把原始 reasoning object 或 encrypted bytes 带入 canonical payload。
5. **公开内容只做中立重表达。** 已知公开 `summary_text` 按原顺序和原 UTF-8 文本投影为普通
   assistant message / `output_text` 证据，不增加摘要、标签、占位符或推断内容。冻结 v0.147 源码归类为
   raw reasoning 的 `content` 和任何 `encrypted_content` 都不得出站；若执行者识别出其他确有公开语义的官方
   content 类型，必须用同一中立消息合同覆盖并补测试，不能仅凭字段名猜测其公开性。
6. **形状白名单、未知拒绝。** reasoning 顶层键、可选字段、summary/content 元素 discriminator 和值类型必须
   按冻结源码的已知合同验证。未知键、未知 subtype、错误容器、混合公开/不明语义等情形必须抛出稳定的
   `EvidenceError`，不能因“最后会删除”而吞掉 malformed 输入。
7. **Standard/Lite 等价不变。** 逻辑等价的 Standard 与 Responses Lite 输入在 v2 中产生相同 canonical bytes；
   policy exact bytes/hash、非 reasoning 证据的顺序与既有语义保持不变。
8. **工具与私有运输字段继续清除。** 顶层 `tools`、Lite `additional_tools`、
   `encrypted_function_args`、warehouse-only `executed_tool_calls` 和 reasoning 私有内容不得进入 static payload；
   已有合法 `tool_search_output.tools` 证据仍保留。最终 validator 必须能拒绝伪造回流。
9. **三个 consumer 同字节。** `static_payload_bytes_for_consumer()` 对 Luna-static、Sol-static、Local-static
   返回完全相同的 v2 canonical bytes；canonical input 中不再存在原始 `type=reasoning` item。
10. **Local 与 census 共用同一请求构造。** Local client 必须只接收通过 v2 validator 的 payload；token census
    的归档请求和合成 probe 都继续调用同一个 Local v2 request builder。focused test 应以 deep equality/spy 等
    方式证明 census 没有另造请求或重新引入 v1 路径。
11. **47 份真实归档只读通过。** 在任务 worktree 中通过 Git common root 访问既有 47 份归档，复用安全 reader、
    meta 校验、v2 builder、三个 consumer bytes 和 Local request builder 做静态构造；必须得到 47/47 成功，
    其中已知 21 份 reasoning 归档全部成功。命令只可输出聚合计数/状态，不得输出路径、ID、hash、正文或请求体，
    不保存检查工件。
12. **状态边界不漂移。** 任务结束时 capability 仍为 `linux_cuda_built_model_unvalidated`；
    `eval/results/baselines/local-approval-exact-token-census-v1.json` 仍不存在；不得新增 census baseline、
    qualification evidence 或 launcher success evidence，也不得宣称那 2 条 500 已解决。
13. **只跑必要门禁。** evidence、local-approval、census focused tests 与 `just eval-lock` 通过；不运行
    Cargo、Docker、真实服务、真实模型、云 API 或全量 eval tests。skip/未运行不得表述为通过。
14. 实现、测试、文档和提交只在分支 `025-wp3b-a2a-static-payload-v2`、worktree
    `.claude/worktrees/025-wp3b-a2a-static-payload-v2` 内进行；执行者提交后停止，不合并、不推送、不删除 worktree，
    交由 Codex 独立审查。

## 4. 实现建议（非强制）

- 可把“static input payload schema version”和“structured decision schema name/version”拆成语义清楚的常量，
  以免把本任务的 v2 错套到现有 decision/qualification v1；不要求为此扩展成通用 schema registry。
- 先对白名单 reasoning item 做完整验证，再决定移除或投影；避免通用 recursive scrub 在验证前吞掉未知字段。
- 中立公开摘要可以复用 Responses 已有的 `message(role=assistant, content=[output_text...])` 形态；一条 reasoning
  item 对应一条消息即可，保持原 item 顺序与摘要片段顺序，不需要建立新 evidence 类型或对话系统。
- 47 条只读检查优先复用 `token_census.collect_evidence_inputs()` 的完整集合、生产 reader 和 meta 校验，
  再对每个内存 payload 调三个 consumer 投影及 `LocalApprovalClient.build_request()`；无需新增长期 CLI、审计报告、
  manifest 或 tracked fixture。
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

1. 确认位于指定 worktree/分支，复核 main、024 worktree 和任务 worktree 状态；不处理未知修改。
2. 先补 v2 reasoning 投影、v1/v2 隔离、未知形状拒绝和 Standard/Lite 等价的 focused regressions，
   再在公共 builder 落地最小实现。
3. 更新 Local client 和必要调用点的 v2 sink；锁住 token census 归档请求与 probe 共用同一 request builder。
4. 运行 §4 的 focused tests 与 `just eval-lock`；失败时只修本任务直接原因，不扩大测试/重构范围。
5. 对 shared ignored 47 条归档做一次无网络、无模型、无正文输出的只读静态构造检查，确认 47/47 与已知 21/21。
6. 检查 diff 中不存在 reasoning/encrypted 正文、真实归档派生 fixture、baseline、capability、qualification evidence
   或 launcher gate 改动；确认主工作区和其他 worktree 未被修改。
7. 最小更新本计划状态、两份 WBS、WBS-COMPLETED 与一份精炼日志；WBS 只写当前状态与后续交接，
   详细测试/执行证据只写一次，不在多份文档堆叠。
8. 检查 `git diff --check`、提交范围和意外生成物，在任务分支提交，向 Codex 报告 commit、门禁结果和未运行项。

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

### 当前工作

- Execplan 已就绪，等待 Claude 在本 worktree 按合同实现并提交。

### 本任务剩余步骤

- 落地 static payload v2 与 reasoning 白名单投影。
- 更新必要 consumer/census 调用点并补 focused regressions。
- 通过 focused tests、`just eval-lock` 和 47/47 只读静态构造检查。
- 完成精炼文档/日志、范围检查和任务分支提交，交由 Codex 独立验收。

### 阻塞项

- 无。本任务已有普通项目内执行与只读处理 47 份归档的授权。

### 当前验收状态

- 未开始实现；没有运行测试、模型、Cargo、Docker、API 或全量 eval。

### 交接边界

- 本任务完成后冻结此计划；后续重跑 47/47 exact-token census、诊断残留通用 500 和选择上下文档位，
  只按两份 WBS 的路线另行推进，不在本计划中追加。

## 7. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 兼容落在公共 `build_static_payload()` | 三个 static consumer 必须同源、同字节，不能形成 llama.cpp 旁路 | evidence 与所有 static 调用点 | 已采纳 |
| 002 | 已知 encrypted-only 空 summary item 删除 | 它没有可见证据，只承载原 provider 连续性；复制会泄露私有运输内容并破坏兼容 | 21 份归档、24 个 item | 已采纳 |
| 003 | 公开 summary 转普通 assistant/output_text，raw/encrypted 不出站 | 保留明确公开内容与顺序，不生成文本，也不泄露隐藏推理 | v2 input 规范化 | 已采纳 |
| 004 | static input 升 v2，decision/qualification schema v1 不随动 | 两者版本含义不同，任务明确禁止修改 qualification success evidence | 版本命名、validator、Local client | 已采纳 |
| 005 | 47 条只做一次聚合式只读检查，不建新审计设施 | 真实归档是本机 ignored 数据；一次结构兼容验收已足够且不应派生正文工件 | 验收与日志 | 已采纳 |
