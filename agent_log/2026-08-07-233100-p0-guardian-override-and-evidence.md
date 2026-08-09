# P0 共享地基：Guardian 审批模型覆盖（S1）+ 审批证据包快照（S2）

对应方案：`plan/001-p0-guardian-override-and-evidence.md`。

## 实质改动

**S1 —— `[auto_review]` 新增 `model` / `reasoning_effort`**

- `config/src/config_toml.rs`：`AutoReviewToml` 增加 `model` / `reasoning_effort` / `evidence_dir`，沿用
  `policy` 既有的配置链，不新设配置面。
- `core/src/config/mod.rs`：`Config` 增加 `guardian_model_config` / `guardian_reasoning_effort_config` /
  `guardian_evidence_dir`，解析位置紧邻 `guardian_policy_config`。
- `core/src/guardian/review.rs`：model 优先级改为 `config.toml` > `model_info.auto_review_model_override` >
  provider 默认；effort 在原有能力推导之后做一次 `config.or(derived)` 覆盖，未配置时推导结果原样保留。
- **只覆盖模型名与 effort**，provider 解析（`model_provider` / base_url / auth）未动，属方向 2 的 L2a。

**S2 —— 审批证据包 `E_final`**

- 新增 `core/src/guardian/evidence.rs`（322 行）：审批轮 `GuardianEvidenceRound` + RAII 绑定 +
  进程内 `thread_id → 轮` 注册表 + 规范化 + 原子落盘。
- `core/src/client.rs`：`ResponsesApiRequest` 组装完成处挂 1 行钩子。
- `core/src/guardian/review_session.rs`：`GuardianReviewSessionParams` 增加 `evidence_round`；
  `run_review_on_session` 选定 trunk / ephemeral 会话后立即绑定，函数退出即解绑。
- 捕获资格 = `request_kind == Some(Turn)` **且** 该会话登记着已开启的审批轮（白名单，
  预热 / 压缩 / memory 均排除）。
- 落盘 `<evidence_dir>/<review_id>/E_final.json` + `meta.json`，目录 `0700`、文件 `0600`，
  先写 `.tmp` 再 rename。
- 规范化剥离 `client_metadata` / `prompt_cache_key` / `store` / `stream` / `stream_options` 与
  `input` 项的 `id`；`call_id` 按出现顺序做成对确定性重映射（`call_0`、`call_1`…），保持工具调用与结果配对。
- 未配置 `evidence_dir` 时不产生任何文件；钩子首个判定是一次 RwLock 读 + `is_empty()`，无分配。
- `.gitignore` 追加 `/test-data/`。

## 疑难问题与处理

1. **证据固化点选在哪里**。`run_guardian_review` 有 5 条终止路径（cancel 预检、allow/deny、timeout、
   cancelled、failed-closed），逐条插入容易漏。最终选 `track_guardian_review` 作为唯一收口：
   5 条路径都要经过它，且它拿到的正是最终 `GuardianReviewAnalyticsResult`。
   meta 直接复用 analytics 字段，避免在 evidence 模块里重写一份 outcome→decision 映射。
2. **槽的 key**。`Arc<EvidenceSlot>` 下传需穿透 Config/Session/ModelClient，过于侵入；改用挂钩点
   已有的 `responses_metadata.thread_id`。安全性依赖两点：trunk 的 `review_lock` 信号量保证同一
   trunk 同时只有一轮审批，以及每次 spawn 会话都生成新 `ThreadId`，因此并发轮必然落到不同 key。
3. **`call_id` 是否重映射**。方案允许"保留或成对重映射"。选了重映射：`call_id` 由服务端随机生成，
   不归一则同一任务两次运行的 `E_final` 字节不同，对方向 0 的离线对比无用。重映射按文档顺序成对进行，
   对已规范化的输入是不动点。
4. **并发不串档的验收方式**。真实并发审批（trunk 忙 → fork ephemeral）在集成测试里难以稳定触发，
   改为：模块级测试直接同时绑定两个轮并交错投递请求（确定性），集成测试覆盖同一会话两轮串行复用
   不串档 + 主 Agent 不被捕获。见方案决策 012。

## 验收结果

- `just fmt` / `just fmt-check`：干净。
- `just fix -p codex-core`：干净（两处 8 参数函数加了 `#[expect(clippy::too_many_arguments)]`）。
- `just write-config-schema`：`core/config.schema.json` 差异仅为 `AutoReviewToml` 的三个新字段。
- 定向测试全绿：
  - `guardian::evidence::tests` 6 项（剥离清单 / 幂等 / `call_id` 配对 / 并发不串档 / 非 turn 与未绑定会话不捕获 / 文件权限）。
  - `suite::guardian_review` 5 项（含新增 2 项：一轮一包+主 Agent 不捕获、websocket 预热不产包）。
  - `suite::auto_review` 2 项（含新增 1 项：config.toml → 出站请求体 `model` / `reasoning.effort`）。
- `just test -p codex-core`：3100 passed / 17 failed。17 项全部为宿主机环境原因（缺 `codex` 等
  workspace 二进制、`/tmp/.codex` 目录污染），不涉及 guardian / config / client 路径。
- **未运行**：
  - 全量 `just test`。启动后由用户叫停——workspace 级并发测试在本机 19GB 内存下有 OOM 风险。
    **不声称通过**；合并前的一次性全量门禁留待后续在受控并发下补跑。
  - Bazel 相关门禁（本机未安装，见 `doc/development-environment.md` §8）与
    `just argument-comment-lint`（同为 Bazel 驱动）。**不声称通过**。
- 本次全程离线：未调用真实模型 API、未拉 Docker 镜像、未外发任何证据包。

## 规模

非测试、非生成物改动 104 行修改 + 322 行新模块 = 426 行，未超方案 500 行闸。
