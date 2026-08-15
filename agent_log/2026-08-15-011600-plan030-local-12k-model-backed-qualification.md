# Plan 030：Local 12k model-backed qualification 与 capability 晋级

日期：2026-08-15 ｜ 分支/worktree：`030-local-12k-model-backed-qualification`
方案：`plan/030-local-12k-model-backed-qualification-execplan.md`

## 实质性改动

- `eval/rondo_eval/local_approval/model_backed.py`：资格合同从 4k 迁到 **12,288**。
  新增 `serving_contract()` 作为服务参数的唯一漂移源（context/gpu_layers/fit/batch/ubatch/
  flash/cache_type_k/cache_type_v），`require_qualification_contract()` 与 `_parse_identity()`
  都对它做整体比较，并额外硬校验 `max_output_tokens=512`。
  `QualificationIdentity` 增补 batch/ubatch/flash/K/V 与 `static_payload_schema_version` 字段；
  evidence 路径改为 `eval/locks/local-approval-b10333-ministral-12k-v1.json`、schema 升到 v2。
  `request_contract_sha256` 升到 v2 并纳入 `STATIC_PAYLOAD_SCHEMA_VERSION`——这是本次补齐的
  static payload v3 绑定，输入 payload 合同变版时旧资格会自动失配。
  identity 数值字段增加布尔拒绝（避免 `True == 1` 满足整数服务值）。
- `eval/rondo_eval/local_approval/client.py`：K/V cache 校验由“只允许 f16”改为冻结 b10333
  `common/arg.cpp` 的 `kv_cache_types` 白名单。这是为“f16 在 12k 装不下时可换低精度 KV”预留的
  授权空间；实际现场用不上，最终冻结值仍是 f16/f16。
- `eval/rondo_eval/local_approval/launcher.py`：serve 参数固定加 `--verbosity 4`（见下）。
- `eval/rondo_eval/local_approval/qualification.py`：失败诊断补齐——识别 `common_init` 无条件开启的
  时间戳+级别行前缀，新增不含任何行内容的行形状直方图，并对 trace 级新出现的请求形状行加 payload 护栏
  （含 `{}[]"` 的行一律不回显）。
- `rondo.local.example.toml`：改为表达冻结的 12k 合同，删掉 4k smoke 说明。
- `eval/tests/test_local_approval.py`：夹具迁到 12k；`_CUDA_LOAD_LOG` 改成**真实**的带前缀格式与
  真实的 33/35 层数（原注释自称 format-exact 但其实不是）；新增 5 项覆盖：b10333 KV 类型白名单、
  旧 4k 证据与被缩小的 effective context 不得晋级、static payload 版本漂移使资格失配、
  正式 launcher + doctor 消费晋级资格、失败诊断只泄漏行形状不泄漏内容。
- 主仓 ignored `rondo.local.toml`：**只改 `context_size` 4096→12288**；`providers`/`paid_eval`
  规范化 digest 与 0600 权限均已核对未变。

## 疑难问题：offload 计数在默认日志级别下根本不存在

前两个生命周期都以 `gpu_offload_not_reported` 收口，但决策与四项清理其实都成功了——只有从日志抽取
GPU offload 这一步失败。当时的诊断摘要是空的（白名单一条都不匹配），无法定位。

补上行形状直方图后看到 25 行全是 `<unlabelled>`，说明是格式不符而非日志丢失。随后用一次
**只加载、不发请求**的诊断生命周期取地面真相（不发请求，日志里就不可能有证据正文，可安全查看）：
模型其实在 12,288 下加载得好好的，但日志每行都带 `common_init` 无条件开启的时间戳+级别前缀，
而且完全没有 libllama 的 load 段。

根因在冻结源码里：`common/log.cpp` 的 `common_get_verbosity()` 把 libllama 的
`GGML_LOG_LEVEL_INFO` 映射成 **TRACE(4)**，默认阈值却是 **INFO(3)**，所以
`load_tensors: offloaded N/M layers to GPU` 与 `ggml_cuda_init:` 在默认级别下不会输出；
而 offload 这个事实又没有任何 endpoint 可取（已在 `tools/server/` 全量确认）。

修复是把 `--verbosity 4` 固化进 serve 参数——它和 `--offline`、`--split-mode none` 一样属于
不可调项，且已被 `serve_config_sha256` 绑定。不是重试掩盖，也没有放宽任何判据。

同一次诊断顺带确认了两件对 8GB 很关键的事实：`--fit` 只调整仍为默认值的参数、上下文**仅在等于 0 时**
才被改写（服务端逐字打印 `context size set by user to 12288 -> no change`），所以显式 12288 不会被缩小；
可用显存 7,096 MiB 下 fit 自动收敛到 33/35 层、6,049 MiB used、1,046 MiB free。

## 验收结果

- 首次模型加载前：focused tests 139/139、`just eval-lock` 85 packages；真实 12k 配置下 doctor 报
  `linux_cuda_built_model_unvalidated`，正式 launcher 在真实 watchdog lease 下以 exit 70 在 `Popen` 前拒绝
  （无进程、无 8080 监听、无 receipt）。
- 真实资格（生命周期 5）：`status=qualified`、`effective_context_size=12288`、offload 33/35、
  峰值显存 6,800,015,360 B、delta 6,463,422,464 B、TTFT 3,516.42 ms、总耗时 7,794.47 ms、
  结构化判定合规、四项清理全 true。证据由正式代码原子生成，未手工填写任何字段。
- 正式复验（生命周期 6）：无资格特权的 launcher 独立加载同一合同，receipt schema v2 的
  `serve_config_sha256=be95ab3e…` 与证据 identity 一致；存活期 doctor `status=ready`、exit 0、
  `gpu_model_serving_validated`、`model_schema_probe_passed`；定点 SIGTERM 后 launcher rc=0、
  receipt 自清、进程退出。
- 交付前复跑：focused tests 139/139、`just eval-lock` 通过；8080 空闲、无 llama-server、
  GPU 无 compute process、`eval-data/local-approval/` 为空。
- 模型生命周期共 6 个：2 次完整资格失败（同一根因）、2 次只加载不发请求的诊断、1 次成功资格、1 次正式复验。
  每次失败都先完整清理再定位。

## 边界

只证明 12k 档位内这条真实证据可服务。未验证其余 42 条适配证据、剩余 5 条超窗证据、16k、
47 条批量 generation、L7 配置切换或 Local M3；未运行 Cargo、Docker、云 API、训练、全量 eval 或全量测试；
未读 `.env.local`；未改 selector、census baseline、run ledger、历史 CUDA base lock 或 Plan 023—029。
真实证据正文、完整请求、模型输出、rationale 与 risk tags 均未进入 Git 或普通日志。
