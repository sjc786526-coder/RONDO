# Plan 095：Publication Critic 云端参考 Scorer 后端接入

日期：2026-08-27 ｜ worktree：`.claude/worktrees/095-publication-critic-cloud-reference-scorer`
｜ 分支：`worktree-095-publication-critic-cloud-reference-scorer` ｜ 起点：`main@76f3539`

合同：`plan/095-publication-critic-cloud-reference-scorer-backend-execplan.md`。

## 1. 实质性改动

只改 `multidev/codex-rs/publication-critic/`（外加其 `Cargo.toml` 与 workspace `Cargo.lock` 的依赖边）。
既有 `PublicationScorer` trait、`RawScorerOutput`/`ScorerError`、`service.rs`、transport/client/resource、
`PublicationPacket`/render、`team_publish` 接入与 `real_scorer.rs` 本地 worker 路径一行未改。

新增：

- `src/cloud_template.rs`：冻结云端模板身份 `rondo-publication-cloud-template@v1` 与投影身份
  `rondo-cloud-json-quality-scalar@v1`。系统消息是固定的 qualification rubric v1（五条硬要求 + 证据边界 + 字段说明 +
  输出契约），用户消息是既有 typed packet 的 `serde_json` 稳定投影。解析用 `deny_unknown_fields` 只接受
  `{"quality": <finite number>}`，拒绝 code fence、多字段、字符串、null、多值与 >4KiB 内容。
  **有意不在此判 domain**：finite 但越界是真实 provider 观测，`ScoreOutOfDomain` 应由既有 service 给出。
- `src/cloud_config.rs`：`CloudScorerDescriptor`（`backend_protocol` + provider 契约 + 既有 `ServiceDescriptor`）与
  全部校验；两个公共身份构造函数 `cloud_reference_scoring_identity` / `provider_managed_model_identity`。
- `src/cloud_scorer.rs`：`CloudPublicationScorer`，复用 `codex-http-client`（`without_redirects` +
  `without_request_logging` + `connect_timeout`）。
- `src/bin/codex-publication-critic-cloud-service.rs`：唯一的云端选择路径。
- probe 增加互斥参数组 `--expected-descriptor` / `--expected-cloud-descriptor`。

库公共 API 只增加 `CLOUD_BACKEND_PROTOCOL`、`CloudScorerDescriptor`、`CloudScorerConfig`、
`CloudScorerConfigError`、`CloudPublicationScorer` 与上述两个构造函数；provider 配置类型保持 `pub(crate)`。

## 2. 关键设计决定

- **选择路径 = 独立 binary。** `codex-core` 的 `PublicationCriticConfig` 只认 endpoint + expected descriptor，本来就是
  backend-neutral，所以不需要碰 core：换 backend 就是换启动哪个 service 二进制。因此“未选择 cloud 时不读 secret、不解析
  provider、不出网、不要求 cloud credential”是结构性成立而不是靠运行时开关。
- **identity 诚实靠校验强制，不靠约定。** descriptor 校验硬性要求 tokenizer 恒为
  `provider-managed-tokenizer@unverifiable`、input_template/scalar_projection 等于冻结的云端模板身份、scoring definition 带
  `rondo-cloud-reference-` 前缀、domain 恒为 `[0,1]`。任何试图写入 exact-looking tokenizer revision 或本地
  `rondo-publication-packet-render` 的 descriptor 会在建立监听前以 `DishonestIdentity` 被拒。
- **retry 预算必须装进 job deadline。** 校验强制
  `request_timeout_ms × max_attempts + retry_backoff_ms × (max_attempts − 1) ≤ job_timeout_ms`。
  后果是 backend 自己的 attempt deadline 总先于 service 的 `ExecutionTimeout` 触发，慢 provider 表现为 typed
  `BackendFailed` 而不是 `ExecutionTimeout`；service 的 job deadline 仍是外层兜底。这条差异如实记在测试注释里，
  没有为凑一个 `ExecutionTimeout` 断言去放宽校验。
- **model drift 复用本地 worker 的做法。** provider 回显的 served model 与请求不一致时，返回**观测到的**
  `ModelIdentity`，让既有 service 给出 typed `BackendModelIdentityMismatch`，而不是笼统的 backend 失败。
  `served_model` 有 `echoed` / `provider_managed` 两态，provider 不提供可核对 model 时明确走后者，不伪造 exact 值。
- **外发与日志。** endpoint 拒绝 userinfo/query/fragment 与非 HTTPS（仅 loopback 允许明文，用于离线注入）；
  provider 非 2xx 的错误正文**不读取**即丢弃，只保留状态码；响应体上限 64KiB；日志只有
  `attempts / elapsed_ms / kind / status / prompt_tokens / completion_tokens`。

## 3. 疑难问题与修复

1. **loopback 测试全部 `code=backend`，provider 收到 0 请求。** 本机设置了
   `HTTP(S)_PROXY=http://127.0.0.1:7897`，`NO_PROXY` 里的 `127.*` 是 Windows/WinHTTP 风格通配符，reqwest 的
   `NoProxy` 不识别，于是发往 loopback fake provider 的请求被路由进代理。修复：loopback provider 用
   `HttpClientBuilder::build_direct()`（该方法的文档用途正是 hermetic 本地 fixture），真实 HTTPS 仍走
   `RespectSystemProxy`。`CloudScorerConfig` 在构造时一次性判定 `loopback_provider`。
2. **首轮真实调用全部 `kind=malformed`。** 用 `/tmp` 里的一次性裸请求确认：`deepseek-v4-flash` 是 reasoning 模型，
   `max_tokens=64` 全部被 `reasoning_content` 吃掉，`content` 为空且 `finish_reason=length`。
   严格解析器正确拒绝了它（没有把截断当成 verdict）。修复是提高 `max_output_tokens` 到 4096 并放宽 per-attempt timeout；
   实测最大 completion 1,095 tokens、最大 9.7 s，据此把正式 descriptor 收敛到 `request_timeout_ms=60000` /
   `job_timeout_ms=130000`（最坏预算 121,000 ms）。

## 4. 验收结果

离线（确定性 loopback provider + 真实启动器 + 真实 typed client，`tests/cloud_process.rs` 8 项）：
ready 且零 provider 请求 → `PASS`/`REWRITE`；malformed 与 out-of-domain 分别为 `code=backend` / `code=invalid_score`
且都不重试；served-model drift → `code=identity_mismatch`；`provider_managed` descriptor 接受无 model 无 usage 的回复；
429 重试一次后成功（attempts=2）而 401 不重试且错误正文不外泄；慢 provider 在 job deadline 内收敛、取消立即生效、
随后调用正常；并发 1/队列 1 得到 2 verdict + 1 `queue_full`；缺凭据与身份不诚实的 descriptor 在监听前 fail closed 且
provider 零请求；非 cloud backend（controlled service）不需 cloud 凭据且 provider 零请求。

| 门禁 | 结果 |
|---|---|
| `just test -p codex-publication-critic` | `54/54` passed（新增 10 单测 + 8 集成，既有全部无回归） |
| `just test -p codex-core --lib -E 'test(publication_review)'` | `17/17` passed（含 default-off 与 measurement-freeze 身份门） |
| `just clippy -p codex-publication-critic` / `just fmt-check` | 通过 |
| 全 workspace | **未运行**（按合同只跑受影响模块） |
| `just bazel-lock-update` | **未运行**：本机无 bazel。`Cargo.lock` 只新增到已有 workspace crate 的依赖边，`codex-http-client`/`url`/`wiremock` 已分别被 25/20/15 个 crate 使用且已在 `MODULE.bazel.lock` 中，预期无 lock 漂移 |

真实 API（合成 packet，DeepSeek chat-completions，frozen commit `5b1d3b0` + frozen descriptor，全新 `/tmp` 运行空间）：

| 步骤 | 结果 | 耗时 | usage |
|---|---|---|---|
| `ready` | ready | 5 ms | 零 provider 请求（readiness 不发付费探针） |
| 正面合成 packet | `PASS` | 9,715 ms | prompt 935 / completion 896 |
| 反面合成 packet | `REWRITE` | 2,388 ms | prompt 873 / completion 153 |
| 负向对照（不存在的 model） | `code=backend`，`kind=status status=400` | 809 ms | 单次尝试，不重试，provider 错误正文未外泄 |

两个 verdict 是在冻结 threshold `0.5` 下自然取得的，没有为凑 `PASS`/`REWRITE` 调过 threshold，也没有扩成质量横评。
负向对照是“请求确实到达选定 provider”的独立证据：不存在的 model 由 `api.deepseek.com` 服务端返回 400。

正式 descriptor（非密钥，字段与 `rondo.local.example.toml` 的 `[providers.deepseek]` 一致，可据此复现）：

```json
{
  "backend_protocol": "rondo-publication-critic-cloud-v1",
  "provider": {
    "api": "chat_completions",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "model": "deepseek-v4-flash",
    "served_model": "echoed",
    "response_format": "json_object",
    "max_output_tokens": 4096,
    "temperature": 0.0,
    "request_timeout_ms": 60000,
    "max_attempts": 2,
    "retry_backoff_ms": 1000
  },
  "service_descriptor": {
    "identity": {
      "protocol": "rondo_publication_critic_v1",
      "implementation": { "name": "rondo-publication-critic-cloud-service", "revision": "v1" },
      "qualification": {
        "packet_schema": { "name": "rondo-publication-packet", "revision": "v1" },
        "rubric": { "name": "rondo-publication-qualification", "revision": "v1" }
      },
      "model": {
        "model": { "name": "deepseek-v4-flash", "revision": "reference" },
        "tokenizer": { "name": "provider-managed-tokenizer", "revision": "unverifiable" }
      },
      "scoring": {
        "definition": { "name": "rondo-cloud-reference-deepseek-v4-flash", "revision": "v1" },
        "input_template": { "name": "rondo-publication-cloud-template", "revision": "v1" },
        "scalar_projection": { "name": "rondo-cloud-json-quality-scalar", "revision": "v1" },
        "domain": { "min": 0.0, "max": 1.0 },
        "threshold": 0.5,
        "pass_rule": "score_greater_than_or_equal_to_threshold"
      }
    },
    "limits": {
      "request_bytes": 131072,
      "response_bytes": 16384,
      "max_concurrency": 1,
      "queue_capacity": 4,
      "job_timeout_ms": 130000,
      "io_timeout_ms": 2000
    }
  }
}
```

复现方式：用仓库既有严格 loader `eval/rondo_eval/config.py` 的 `load_allowlisted_secret_values(paths, ("DEEPSEEK_API_KEY",))`
取值并只注入到子进程，运行
`codex-publication-critic-cloud-service --descriptor <上述 JSON>`，再用
`codex-publication-critic-probe --endpoint <announced> --expected-cloud-descriptor <同一 JSON> --call-timeout-ms 140000 review --packet <packet.json>`。
`threshold: 0.5` 是显式非最终的参考 operating point，不是 Skywork 的最终标定。

## 5. 费用与副作用

- 可能计费事件 5 次（首轮 commissioning、裸请求诊断、第二轮 commissioning、clean smoke、负向对照）。DeepSeek 计费金额未知，
  按合同每次保守计 1 USD，合计 **5 USD**，低于 50 USD 上限。未使用 Docker、GPU、RunPod、真实本地模型。
- 未读取 `.env.local` 内容，只经既有严格 loader 取用单个 allowlisted 变量并注入目标子进程；`.env.local` 与
  `rondo.local.toml` 均未修改。
- 所有重型 Cargo 经仓库共享 `scripts/with-build-lock.sh`（`just` 配方）运行，`CARGO_TARGET_DIR` 为主物理根
  `.codex/cargo-target/rondo-multi`，未在 worktree 另建 target。Windows `C:` 停止线仅在本任务的命令上下文临时设为
  30,000,000,000 bytes，受跟踪默认阈值未改。运行期间项目占用 245 GB → 258 GB（告警线 270 GB 未触发），
  看门狗 `stop=none`。
- 真实 API 的临时 descriptor/packet/驱动脚本只存在于 `/tmp/rondo-plan095-*`，已全部删除；未创建
  `eval-data/publication-critic/plan095/`，主物理根未新增 ignored 任务资产。
- 主工作区与 093 worktree 全程无 tracked diff。真实 provider 的 request/response 正文、Authorization、API key
  未进入任何日志、提交或本报告。

## 6. 未做的事

不做质量横评、threshold 标定、operating point 选择、批量测评、产品启用或默认 backend 变更；不读取 v8/unseen；
不延续 Plan 094 训练路线；不解锁 M3-D。合并、推送、分支归档与 worktree 删除等待用户批准。
