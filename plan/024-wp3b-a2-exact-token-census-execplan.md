# Plan 024：WP3b-A2 真实 E_final exact-token 普查与上下文预算决策输入

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

对当前项目内完整的 47 条真实 Guardian `E_final` 做一次可重复、无生成的 exact-token 普查，为本地审批服务选择
4k 或 8k 上下文档位提供真实分布。计数必须使用 Plan 023 已冻结的 GGUF tokenizer、官方 Jinja 模板和与
`LocalApprovalClient` 真实 `/v1/responses` 请求完全一致的输入构造；不得用字符数、经验比例或其他 tokenizer 代替。

本任务只产生“输入长度与窗口适配性”事实，不产生审批判定，不证明 4k/8k 的显存或推理可用性，也不改变现有资格档位、
model-backed evidence 或 capability。

### 完成/验收标准

- [ ] 输入全集由受跟踪 `eval/results/runs.jsonl` 与主仓 shared ignored `eval-data/runs/` 共同绑定：恰好 24 个关联
  RONDO run、47 个归档 `E_final.json`、47 个配对 `meta.json`、47 个唯一 review identity、47 个唯一
  `E_final` SHA-256，并且安全解析后的 47 个 canonical static payload identity 也全部唯一；不得按 run outcome、长度或 fit 结果
  筛选。缺失、重复、多出或身份无法绑定时整体失败，不能发布总体结论。
- [ ] 47 条每一条都经过现有生产安全读取、完整 meta schema/terminal combination 校验、Guardian baseline/commit、
  expected model/effort、review identity、run/artifacts/public evidence 双向绑定和读前/读后文件 identity 校验；不能只验证 JSON 可解析或
  相信归档自身声明。
- [ ] 每条 `E_final` 均从已经安全读取和验明身份的同一份 bytes 构造 `StaticApprovalPayload`，再复用生产
  `LocalApprovalClient.build_request()` 的同口径请求构造；禁止重新打开文件造成 TOCTOU，也禁止复制一份会独立漂移的请求拼装逻辑。
- [ ] 输入 token 数来自冻结 b10333 + 唯一 GGUF + 冻结官方 Jinja 模板的 exact Responses 计数路径。当前已验证的首选是
  `POST /v1/responses/input_tokens`：它与 `/v1/responses` 共用 b10333 的 Responses→Chat Completions 转换、模板解析与
  GGUF tokenizer。若执行者采用其他方法，必须先证明它调用同一 b10333 代码路径并在真实锚点及 focused fixtures 上与该端点
  逐项一致；近似 tokenizer 或自行复刻模板不合格。
- [ ] Plan 023 受跟踪 selector 指向的已知样本必须得到 **5,313 input tokens**。不是 5,313 时，整次普查无效，
  不得发布 47 条分布或路线建议。
- [ ] 固定 `max_output_tokens = 512`，每条计算 `required_context_tokens = input_tokens + 512`；
  `fits_4096`/`fits_8192` 分别按 `required_context_tokens <= 4096/8192` 判定。不得把 5,313 input tokens
  误当成总窗口需求，也不得仅用 input tokens 做 fit。
- [ ] 结果覆盖 4k/8k 可容纳数量与比例、超过 8k 数量，以及 input/required-context 两组分布的 min、P50、P75、P90、
  P95、max。分位数固定采用 nearest-rank，并在结果 schema 中声明算法，避免库默认值或插值差异。
- [ ] 产出受跟踪、确定性、机器可读的 JSON。`sample_sha256` 固定定义为安全解析后的
  `sha256(StaticApprovalPayload.canonical_bytes)`；每条记录只含 `sample_sha256`、`input_tokens`、
  `required_context_tokens`、`fits_4096`、`fits_8192`；不得保存 path、run id、review id、meta、证据正文、
  渲染后 prompt、token ids/pieces 或任何模型输出。记录按 `sample_sha256` 排序，JSON canonicalization 与换行固定。
- [ ] 至少执行两次完整的 47 条 pass；每次都重新完成来源绑定、安全读取、payload 构造和 exact 计数。两次 canonical records、
  summary、route recommendation 和最终 JSON bytes 必须一致后才能发布。为减少资源消耗，允许在同一个受控 server 生命周期内完成
  两个完整 pass；不得用复制第一遍内存结果冒充第二遍。
- [ ] 机器结果明确给出：`full_corpus_window_tokens = 4096|8192|null`、是否必须保留 oversize fail-closed、
  当前 47 条若要全覆盖是否已经必须考虑压缩/裁剪或更大窗口。这里的“足够覆盖”固定指当前 47/47 全覆盖；部分覆盖只报告比例，
  不冒充全体可服务。
- [ ] focused Python tests 覆盖全集绑定、legacy/public identity 差异、重复/缺失/额外归档、unsafe/meta 漂移、请求同构、
  anchor mismatch、512 输出预算边界、分位数、双 pass 不一致、确定性序列化、partial publication 和安全输出；相关测试通过，
  `just eval-lock` 通过。
- [ ] 唯一真实运行只计数、不生成：不调用 `/v1/responses` 生成端点，不产生 allow/deny/rationale/risk tags，
  不写 qualification success evidence。真实运行前后均持有共享 watchdog/lock，GPU 独占且与 Cargo、Docker和其他模型任务错峰。
- [ ] 本任务可验证身份的 llama-server、监听端口、receipt（若实现确实需要）、0600 私有日志和临时目录全部清理；
  未知对象只报告、不清理。清理不完整时普查失败，不发布结果。
- [ ] 运行前后 formal launcher 都继续在未晋级 capability 下拒绝启动；最终 capability 保持
  `linux_cuda_built_model_unvalidated`，`model_backed_structured_output` 保持 `not_run`，不存在新增 model-backed success evidence。
- [ ] 成功后只把总体分布、结果文件 digest、结论边界和下一步上下文决策输入同步到两份 WBS、WBS-COMPLETED 与一个精炼 agent log；
  不在权威文档写入逐条 hashes。失败时不发布总体分布，只记录非敏感 blocker 和清理状态。

## 2. 范围

### 允许修改

- `plan/024-wp3b-a2-exact-token-census-execplan.md`：仅更新本任务状态与关键决策。
- `eval/rondo_eval/local_approval/`：普查入口、全集绑定、安全读取复用、exact count client、确定性聚合和生命周期所需的
  最小 Python 实现；可以对现有纯请求构造做窄重构以消除双实现漂移。
- `eval/tests/`：与本任务直接相关的 pure/fake/loopback focused tests；优先融入现有 local-approval 测试组织，规模明显增大时
  可新建一个职责清楚的测试文件。
- `eval/results/baselines/`：新增一份版本化、机器可读的 exact-token 普查结果，建议命名
  `local-approval-e-final-token-census-v1.json`。它是长度测量结果，不是 qualification lock 或 capability evidence。
- `justfile`：只有新增一个窄、可复用的普查/验收入口确有价值时才允许修改；不为一次命令制造多层封装。
- 任务成功后的 `doc/WBS.md`、`doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 与一个
  `agent_log/<timestamp>-wp3b-a2-exact-token-census.md`。
- 主仓 shared ignored `eval-data/local-approval/` 下由本任务创建的 0700/0600 临时目录、server 日志和 runtime receipt；
  它们只允许用于运行期并必须清理，不是交付物。

### 不允许修改

- `mydev/`、`multidev/`、`codex-source-code/`、`reference-agent-harness/`。
- Plan 023、Plan 018 及其冻结日志/审计快照；已有 selector、CUDA/CPU runtime locks、chat-template lock、
  `eval/results/runs.jsonl` 和 47 条 `eval-data/runs/` 归档均只读。
- `eval/locks/local-approval-b10333-ministral-4k-v1.json` 或任何新的 model-backed qualification success evidence；
  不改 `model_backed.py` 中 4k 资格常量与 capability 投影，除非只是无语义的复用重构且 reviewer 明确确认没有合同变化。
- `rondo.local.toml`、`rondo.local.example.toml`、`rondo.secrets.example.env`、`eval/uv.lock` 与依赖集合。
- 模型、runtime、CUDA toolkit、模板和 47 条 E_final/meta 的内容、权限、名称或目录结构。
- L7、Guardian provider、Local M3、L3/L4、训练、摘要/裁剪/压缩、动态上下文和 8k runtime 验证相关实现。

### 不允许读取/查看

- `.env.local` 的内容。不得打开、搜索、打印、复制、hash 或通过 source/子 shell 加载它；本任务的 loopback count 请求必须采用
  不读取 secret 的窄 HTTP 路径。允许按根规则静默检查该文件存在性、普通文件/非 symlink 与 0600 权限，但本任务并不需要这样做。
- 证据正文、渲染后 prompt、token ids/pieces、模型 raw output、私有 server request dump。程序只能在内存中按验收所需处理
  E_final bytes 与构造后的 request，并且不得把正文写到 stdout/stderr、普通日志、Git、测试快照或错误消息。
- 与这 47 条归档无关的 holdout、私有测评、凭据和用户个人文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **全集先绑定，失败不出总体结论**：先从受跟踪 ledger 建立 expected manifest，再与 shared ignored archive 一一对应。
   当前集合包含 24 个 RONDO run、47 条 evidence；其中部分 run 的 outcome 为 `infra_failed`，但归档 evidence 仍属于 WBS 所称
   47 条真实全集。run outcome 只能作为身份事实，不得作为样本过滤条件。raw E_final、review identity 或 canonical static payload
   任一维度不满 47 个唯一值，或任何源不一致，都使整个 census blocked。
2. **生产读取与独立身份源**：复用 `terminal_bench.live` 的安全 reader、meta validator、policy identity 和 Plan 023 已验证的
   读前/读后 `(dev, ino, size, mtime_ns)` 做法。expected model/effort 与 artifacts 来自受跟踪 run record；每个归档的
   `meta.review_id` 必须与该 run 的 public `summary.evidence` 做唯一双向匹配，不由待验 meta 自证。早期 4 条 public evidence 的
   `relative_path` 是归档前 `agent/guardian-evidence/<review_id>`，不能与 numbered archive 直接 path join；另有 4 条早期 public
   evidence 没有 `canonical_request_sha256`，也不得为凑统一改历史或伪造值。现代字段存在时必须重算核对，旧行仍须靠完整 meta、
   policy identity、E_final SHA 和 review-id bijection 验明身份。
3. **请求同构**：token census 消费 `build_static_payload()` 的安全输出，并与生产 client 共用同一个请求 builder；
   request 必须包含 production 的 instructions+policy 合成、input、model、stream、temperature、top_p、seed、
   `max_output_tokens=512` 和 b10333 `response_format`。不得只 tokenise `input`、原始 E_final JSON 或删掉 schema 后的短 prompt。
4. **exact tokenizer-only**：只允许冻结 `b10333/08659901c...`、唯一 GGUF
   `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`、冻结模板
   `74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56` 的组合。真实 count 响应必须严格验证
   响应字段全集恰好为 `object=response.input_tokens` 与一个正整数 `input_tokens`；extra/missing/type drift、估算或 fallback
   均不接受。不得请求 token ids/pieces。
5. **锚点优先**：在形成任何总体 summary 前先确认 Plan 023 selector 对应 `e_final_sha256` 的计数为 5,313；
   selector/digest/请求身份或计数任一漂移都立即失败。锚点是计数口径校准，不是只测该一条的捷径。
6. **确定性 publication**：结果不含日期、PID、端口、绝对路径、耗时、worktree、随机 nonce 或当前 Git HEAD 等会导致重跑漂移的字段。
   measurement identity 只保存冻结 lock/content digests、request-contract digest、corpus aggregate digest、窗口与算法常量。
   两次 pass 一致后才以安全 temp+fsync+atomic/no-clobber 语义写结果；已有同 bytes 结果可视为幂等成功，已有不同 bytes 必须失败。
7. **统计与路线语义固定**：nearest-rank 的 Pq 为排序后第 `ceil(q*N)` 个值（N=47，1-based）。
   4k fit 等价于 `input_tokens <= 3584`，8k fit 等价于 `input_tokens <= 7680`；二者只表示 `input+512` 的静态预算适配，
   不表示 8k 已加载、显存足够、能生成或 qualification 通过。`recommended_window_tokens/full_corpus_window_tokens`
   在 4k=47 时为 4096，否则在 8k=47 时为 8192，否则均为 `null`。任何有限档位对未来输入都要求 oversize fail-closed，因此
   `oversize_fail_closed_required=true`；`compression_or_larger_window_required_for_full_corpus` 当且仅当 8k<47。
8. **无生成、无晋级、无审批副作用**：不得调用生成端点，不得写 allow/deny，不得写 model-backed evidence，不得修改 capability、
   资格常量或真实配置。普查入口必须是窄用途路径，不能成为 formal launcher 的通用 bypass，也不能接受任意外部证据目录/模型路径
   来规避冻结身份。
9. **资源与生命周期 fail-closed**：真实模型生命周期必须从任务 worktree 通过根 `scripts/with-build-lock.sh` 执行，并在进程内验证
   watchdog lease；共享锁、Windows C:、项目容量、内存/swap/cgroup 任一前置不可得即停止。模型启动前 GPU 必须无 foreign compute
   process，运行窗口持续独占；未知进程/端口/对象不清理。成功与失败路径都验证本任务 server、端口、receipt 和私有 temp 已消失。
10. **秘密与日志最小化**：所有 HTTP 只访问精确 loopback URL，禁用 ambient proxy 和 redirect；不调用会读取
    `load_local_model_secret()` 的路径。现有 `launcher.serve_environment()` 会尝试加载 local-model secret，因而本任务明确不得调用；
    server 必须使用不接触 `.env.local` 的 sanitized environment。server 不开 debug/request logging，raw 日志只落 0600 私有文件且最终
    删除；CLI/agent log 只输出 count、aggregate、digest、状态码和清理布尔值，不得回显请求、响应 prompt 或证据路径。
11. **测试不膨胀**：只跑受影响的 Python focused suite、`just eval-lock` 和必要的无模型 doctor/launcher gate；
    不跑 Rust/Cargo、Docker、全 workspace、全量 eval、云 API、训练或 8k smoke。skip/未运行必须单独列出，不能写成通过。
12. **交付边界**：执行者只在 `024-wp3b-a2-exact-token-census` 分支提交，提交前检查 diff、敏感正文、tracked 大文件、
    ignored 临时物和全部 worktree 状态；不得合并、推送、删除/重命名 worktree 或分支。由 Codex 独立审查后再决定交付。

## 4. 软性建议

以下内容用于根据现有代码给出的执行建议，但不是固定约束，也不代表代码变化之后的精准效果预测。执行者可以依据代码、
实际测试和运行结果采用更优方案；偏离时说明如何保持 §3 的等强结果。

- 优先新增窄的 `token_census.py`，复用 qualification 的 contract/runtime/model/template/ready/cleanup 设施，但不要把 count 逻辑塞进
  qualification success 路径，也不要发布 launcher identity receipt，除非现有生命周期复用使 receipt 真正必要。
- 可以把 `LocalApprovalClient.build_request()` 的纯构造部分提取为模块级 helper，让 production client 与 census 都调用它；
  保持已有 client API 不变，避免为普查复制请求 schema。
- 首选由 b10333 CUDA server 的 `POST /v1/responses/input_tokens` 直接计数完整 production request。该端点在冻结源码中先调用
  `server_chat_convert_responses_to_chatcmpl()`，再调用 `oaicompat_chat_params_parse()` 和 `tokenize_mixed(..., add_special=true,
  parse_special=true)`，最接近 Plan 023 失败日志的服务端口径，也不发生 decode/generation。
- expected corpus 可由一个纯函数从 `runs.jsonl` 投影：只接收 RONDO、带 public `summary.evidence` 且有对应 artifacts 的记录。
  每个 artifacts 下的 numbered archive 用安全读取后的 `meta.review_id` 与 public evidence 做 bijection；不要假设所有历史行的
  `relative_path` 已经是 numbered archive path。宽泛 glob 只用于证明没有额外/缺失归档，不作为唯一全集来源。
- 每条公开 ID 使用 `StaticApprovalPayload.canonical_bytes` 的 SHA-256；另计算一个 aggregate source-set digest，覆盖排序后的
  47 个 raw E SHA、meta SHA、ledger/review identity 与 request identity，但只把 aggregate digest 写入结果。这样既让逐条 ID 对齐
  实际被计数的静态 payload，也能检测源集合漂移而不暴露逐条 path/meta。
- 建议结果顶层分为 `schema_version`、`measurement_identity`、`corpus`、`records`、`summary`、`route_recommendation`。
  `records` 严守五字段；`summary` 同时报告 input 和 total-required 分布。路线建议使用稳定 reason codes，agent log 再用人话解释。
- 建议的结果决策表：4k=47 时 `full_corpus_window_tokens=4096`；否则 8k=47 时为 8192；否则为 `null`。
  任一档位都建议后续保留 oversize fail-closed，因为未来输入不受本次冻结全集保证。只有 `none` 时，才把“压缩/裁剪或更大窗口
  已成为全覆盖前置”标为 true；若 8k=47，则压缩对当前全集不是必需项。
- 双 pass 可在一次 server 生命周期中顺序执行，以避免第二次加载权重；每个 pass 仍重新枚举 ledger/archive、重验身份并重新发送
  47 个 count 请求。若实现更适合两个生命周期，也不得超过用户当前授权范围，且两次均须独立清理。
- server 命令可以继续复用 `build_serve_command()`，但环境应复用/提取 `_sanitized_environment()` 的无密钥部分或实现经测试的等价
  allowlist；不要调用 `serve_environment()`，也不要通过临时清空配置来绕过 secret loader。
- 私有 server log 只用于确认 frozen CUDA/load/build/context 事实；若 b10333 在非 debug 等级意外记录 request body，应立即失败并删除
  本任务日志，先修日志边界再重跑。错误报告采用稳定 reason code，不从 raw log 摘录与请求相关的行。
- focused tests 可以新增 loopback fake count endpoint，断言收到的 request 与 production builder 相同但不把 payload dump 到 assertion message；
  anchor 5,313 只能由真实 frozen service 验收，不能用 mock 伪造为“真实通过”。
- 推荐门禁命令（执行者可按实际文件组织等价缩小/补充）：

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
      tests/test_local_approval.py \
      tests/test_config_hardening.py \
      tests/test_config_and_artifacts.py

  just eval-lock
  ```

## 5. 实施与验证顺序

### A. 只读基线与全集 manifest

1. 在专用 worktree 核对 branch/HEAD/diff；核对主工作区与全部 worktree 状态。主仓只读检查 shared watchdog lock、GPU compute、
   本任务端口和 llama-server 现场；未知对象只报告。
2. 通过 tracked ledger 构造 47 条 expected evidence manifest，并与 shared ignored archive 做双向集合比较；验证 47 个唯一
   review identity、E_final SHA 和配对 meta。按安全读取后的 meta review id 与 public evidence 做一一匹配；现代行再核对
   `canonical_request_sha256`。只输出数量与 aggregate digest，不输出 path/review id。
3. 对每一条复用生产 safe reader/meta/policy 校验，并验证 run/artifacts/review identity。全集验证必须能在不启动模型的情况下先完成，
   任一失败在 `Popen` 前结束。
4. 读取并验证冻结 runtime/model/template/request contract；证明 model-backed evidence 不存在、capability 仍为
   `linux_cuda_built_model_unvalidated`，formal launcher 在 `Popen` 前拒绝。

### B. 最小实现与 focused tests

1. 实现共享 production request builder 或等价复用，加入无 secret、无 redirect、loopback-only 的 strict count client。
2. 实现 deterministic corpus loader、双 pass comparator、统计/fit/route 投影和安全 publication。
3. 实现受控单 server 生命周期：watchdog、GPU/port preflight、exact server identity、count-only、全路径 cleanup；不得连接生成端点。
4. 用 pure/fake/loopback tests 覆盖 §1 测试验收项；先跑 focused tests 与 `just eval-lock`，再进入真实模型阶段。

### C. 唯一真实 exact-token 普查

1. 从任务 worktree 通过 `scripts/with-build-lock.sh` 启动普查入口；不修改 shared `rondo.local.toml`，不读取 `.env.local`。
2. 加载 exact CUDA runtime/GGUF/template，验证 service build、model path/alias、effective context=4096 与 GPU 独占。
3. 对全集做 pass 1；先检查 Plan 023 anchor=5,313，再完成 47 条。重新读取/验证全集后做 pass 2，逐条和 summary 比较。
4. 两个 pass 完全一致且 cleanup 完整后，才生成/确认 tracked census JSON；再次运行纯 artifact verifier，确认 schema、47 条、
   aggregate digest、统计和 route recommendation 自洽。
5. 运行无模型 doctor/formal launcher gate 与现场清理检查，确认无 server、port、receipt、private temp，capability 未晋级。

### D. 结果解释、文档与交付

1. 按固定决策表说明：4k/8k 哪个覆盖 47/47；未覆盖数量；oversize fail-closed 是否必要；为全覆盖是否必须进入压缩/裁剪或更大窗口。
   明确 8k fit 只是静态预算事实，没有试跑 8k。
2. 成功时精简更新两份 WBS 当前事实/下一步，把本次普查作为历史进展追加到 WBS-COMPLETED，并写一个精炼 agent log；
   Plan 024 更新为完成状态并冻结。失败时不写总体分布或成功历史，只记录 blocker、未发布状态和清理结果。
3. 检查 `git diff --check`、tracked 文件、模型/正文泄漏、绝对 path/review id、异常大文件、主工作区与全部 worktree 状态。
4. 在任务分支提交；向 reviewer 交付 commit、diff、focused test 计数、`just eval-lock`、真实 anchor、aggregate summary、结果文件 SHA、
   两次 pass digest、无模型 doctor/formal gate 和最终清理状态。不得合并、推送或移除 worktree。

## 6. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-14：规划者读取根规则、README、两份当前 WBS、数据布局、Plan 模板、Plan 023 及其执行/审查/修复/交付日志，
  并检查 local-approval client/launcher/qualification/model-backed、生产 evidence loader、结果归档与 focused tests。
- 2026-08-14：确认主工作区为 clean `main@40f3099` 且等于 `origin/main`，进入时没有其他 linked worktree；从该提交创建
  `.claude/worktrees/024-wp3b-a2-exact-token-census` 与分支 `024-wp3b-a2-exact-token-census`。
- 2026-08-14：只读预检确认 shared ignored archive 当前有 47 个 `E_final.json`、47 个配对 `meta.json`、47 个唯一
  E_final SHA，分布于受跟踪 ledger 的 24 个 RONDO run；ledger 有 47 个唯一 review id。24 个 run 中 20 个 completed、
  4 个 infra_failed，对应 evidence 数分别为 41 与 6；后 6 条不能从 WBS 所称完整 47 条全集中删掉。
- 2026-08-14：独立只读解析确认 47 条均为 `responses_lite`，经现有 `build_static_payload()` 得到的 canonical static payload
  SHA 也是 47/47 唯一；该检查只输出计数，没有输出或持久化正文。
- 2026-08-14：确认 Plan 023 anchor selector 绑定 SHA
  `eaa2dfb178159b79f5e2e3fdb60179c5e9d729dfcff02c97b5a6acb5d09ebaca`；冻结结论是服务端
  5,313 input tokens。当前预检没有启动模型、没有自行计算其余 token 数，也没有打印任何 E_final/meta 正文。
- 2026-08-14：冻结 b10333 源码确认 `/v1/responses/input_tokens` 与生成端点共用 Responses→Chat Completions
  转换、`oaicompat_chat_params_parse()`、Jinja 模板和 `tokenize_mixed(..., true, true)`，返回 input token count 而不推理；
  CPU release 的 `llama-tokenize` 只接受已经渲染的 prompt，因此不应单独承担 production request/template 同构证明。
- 2026-08-14：确认 linked worktree 通过 Git common dir 读取主仓 shared ignored `rondo.local.toml`、47 条归档、唯一 GGUF、
  CUDA runtime 与共用 eval venv/cache。本任务不需要持久修改任何主工作区 ignored 文件；真实执行只会在 common-root
  `eval-data/local-approval/` 创建本任务临时对象，结束时必须删除。
- 2026-08-14：独立计划审查确认两个实现陷阱：早期 public evidence path 不是 numbered archive path，必须用 meta review id
  与 ledger 做 bijection；现有 `serve_environment()` 会触发 `.env.local` secret loader，census 必须改用无密钥 sanitized env。

### 当前工作

- Plan 024 已起草，等待执行者在本 worktree 实现；尚未启动模型或运行 exact-token census。

### 本任务剩余步骤

- 实现 §5.A—B 并通过 focused tests 与 `just eval-lock`。
- 在已授权边界内完成 §5.C 的唯一真实、双 pass exact-token census 和清理复核。
- 生成确定性结果，按 §5.D 更新最少权威文档、提交任务分支并交给 Codex 独立审查。

### 阻塞项

- 无已知外部阻塞。若真实 anchor 不是 5,313、全集不是严格 47 条、identity 漂移、共享重型锁/资源计数不可得、GPU 非独占或
  cleanup 不完整，则按合同失败，不得发布总体结论。

### 当前验收状态

- 仅规划完成；实现、focused tests、真实 token count、结果文件和文档收口均待执行。
- capability 当前仍为 `linux_cuda_built_model_unvalidated`；本计划不允许改变该事实。

### 交接边界

- 本任务完成后冻结此计划，并把上下文档位选择交还 `doc/WBS.md` 与 `doc/WBS/local-approval-model.md`。
  不在本计划内执行 4k/8k qualification、配置切换、压缩/裁剪或 Local M3。

## 7. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 把 b10333 `/v1/responses/input_tokens` 作为首选 exact 计数路径，不单独使用 `llama-tokenize` | 前者复用真实 Responses 转换、模板与 tokenizer；后者只处理已渲染 prompt，额外复制渲染会产生漂移 | token count、anchor | 已采纳 |
| 002 | 全集从 tracked ledger 期待值与 ignored archive 现实值双向绑定；不按 run outcome 过滤 | 防止缺失、额外归档与事后挑样，且 4 个 infra_failed run 中的真实归档属于当前 47 条全集 | corpus loader | 已采纳 |
| 003 | 每条公开标识使用 canonical static payload SHA，raw E/meta identity 只进入 aggregate source-set digest | 逐条 ID 与实际被计数的 payload 对齐并能发现语义重复，同时满足不持久化证据位置和正文的最小披露边界 | result schema | 已采纳 |
| 004 | fit 固定按 input+512 与 4096/8192 比较，足够覆盖定义为 47/47 | 输出预算是服务窗口的一部分；完整全集才可支持“该档位覆盖现有真实输入”的总体结论 | statistics、route | 已采纳 |
| 005 | 在一次受控 server 生命周期内做两次重新读取/重新计数的完整 pass | 验证确定性，同时减少重复模型加载与 GPU 占用；不复用第一遍 count 结果 | real run | 已采纳 |
| 006 | census 结果放 `eval/results/baselines/`，不放 `eval/locks/` | 这是上下文决策输入，不是 runtime/model qualification、capability 或批准证据 | artifact ownership | 已采纳 |
| 007 | 本任务不改 ignored config；worktree 直接复用 common-root 资产，临时对象也落 common root 后清理 | loader 已有明确 Git common-dir 语义，复制或改主仓配置没有必要且会制造漂移 | execution handoff | 已采纳 |
