# E-B8 第四次审查缺口修复与无 API Docker 复验

## 范围与结论

- 接续 `agent_log/2026-08-13-201331-eb8-fourth-acceptance-review.md`，按冻结源码、当前实现和纯复现重新核对
  其中 1 个 blocker、1 个 HIGH、1 个 MEDIUM；三项均存在。
- 本批完成窄修复、回归测试，并按既有授权先复验 `fix-git` 双侧实机，再复验完整 10 题 canary catalog。
- 本批只使用进程内 synthetic schema-v7 identity、现有本地固定 digest 镜像与 127.0.0.1 capture stub；未创建或
  激活正式 campaign、lock、active pointer、ledger、run ID 或结果目录，真实 API 请求与费用均为 0。
- 第四次审查报告是形成时点的冻结证据，保持原文。本批证明报告指出的三个实现缺口已闭合；synthetic 结果不冒充
  正式 v7 identity 到 paid worker 的完整生命周期验收。

## 实质修复

1. **Responses Lite 投影 fail-closed**
   - `additional_tools` 只允许唯一出现在 `input[0]`，且必须是 developer role 和数组 tools；畸形、重复、移位，或与
     顶层 `tools` / `instructions` 混用均拒绝。
   - Lite tools 同时进入 `tool_specs` 分区，`additional_tools` 与后续 developer/system items 进入
     `stable_input_prefix`；首个非稳定 item 仍截断，因此 user task body 不进入任务无关合同。
   - `TASK_INDEPENDENT_PROJECTION_VERSION` 升至 2。真实形状 8-model/1-model 纯复现从原先 `reasons=()` 变为
     `task_independent_tool_specs_differs` 与 `task_independent_stable_input_prefix_differs`。
2. **identity lock 首次加入后不可改写**
   - 对 `H..HEAD` 净状态为新增的 campaign identity，以 `git log --full-history --no-renames` 枚举完整路径历史；
     merge 结果与任一 parent 相同不计为新变更，其余变更必须恰好一次且该次必须是 `A`。后续修改即使恢复原 blob
     也拒绝；active pointer 的既有可更新语义不变。
   - 临时 Git 回归覆盖 identity branch 经 `--no-ff` 合并后通过、无关提交后仍通过、修改后拒绝、恢复后仍拒绝，
     以及侧分支改写 identity、merge 时恢复主线原 blob 的 `TREESAME` 隐藏历史仍拒绝。
   - 独立实现审查先确认原报告三项均真实，随后额外发现默认 path-limited log 会裁剪上述第二父历史；本批将这一
     同级 HIGH 一并闭合。Lite 投影和 receipt v2 未发现其他 blocker/HIGH/MEDIUM。
3. **receipt 保存完整 stub 请求 provenance**
   - producer 不再把轨迹压成 role map，而是保留精确 `main -> Guardian -> main` 有序 trace，第三段 main 继续参与
     同侧稳定合同校验。
   - receipt 固定保存两侧共 6 条 `side/role/sequence/full_request_sha256`，不保存正文且不要求跨侧完整 digest 相同；
     缺行、乱序、非法 sequence 或 SHA 均拒绝。
   - `PREFLIGHT_RECEIPT_SCHEMA_VERSION` 升至 2；稳定合同仍只有 `main`、`guardian` 两类。

## 纯 / fake / loopback 验证

实际命令：

```text
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  PYTHONPATH=eval eval/.venv/bin/python -m unittest -q tests.test_fair_comparison
just eval-lock
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  UV_CACHE_DIR=.uv-cache uv run --directory eval --frozen --no-sync \
  python -m unittest discover -s tests -q
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  PYTHONPATH=eval eval/.venv/bin/python -m unittest -q \
  tests.test_fair_comparison.EvalHarnessLifecycleTests \
  tests.test_fair_comparison.TaskIndependentProjectionTests \
  tests.test_fair_comparison.PreflightReceiptTests \
  tests.test_fair_comparison.PreflightProducerTests
git diff --check
```

结果：

- focused `tests.test_fair_comparison`：最终 87 PASS / 0 FAIL / 0 ERROR / 0 SKIP，3.389s。
- no-ff/隐藏 merge 历史等四组最终定向复核：26 PASS / 0 FAIL / 0 ERROR / 0 SKIP，1.641s。
- `just eval-test` 对应的冻结、无同步等价入口：578 PASS / 0 FAIL / 0 ERROR / 0 SKIP，74.048s。
- `just eval-lock`：PASS，`Resolved 85 packages in 17ms`。
- `py_compile` 与 `git diff --check`：PASS。
- 以上是 pure/fake/127.0.0.1 loopback；不使用 Docker、真实 API 或真实模型。

## synthetic Harbor / Docker 验收

### 共同入口与命令

- synthetic identity 从真实 v22 provider profile、真实双侧 runtime bundle manifests、真实 canary catalog、tracked
  seccomp 与当前共享 8-model catalog 构造，只存在于进程内；共享 catalog SHA-256 为
  `357e5f2ecbe5a9f99cf59f2d06cacd9107de96d53cb423ec32e4fe78fe2a0cea`。
- 每个镜像先执行 `docker image inspect <fixed-digest-ref>` 确认本地存在；不 pull、不 build、并发 1。唯一 endpoint
  是容器回连的 loopback capture stub，固定假 bearer 不进入真实 provider。
- 两轮核心命令形状相同，分别运行一次性 `fix-git` 驱动与完整 catalog 驱动：

```text
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  PYTHONPATH=<worktree>/eval UV_CACHE_DIR=<common-root>/eval-data/uv-cache \
  UV_PROJECT_ENVIRONMENT=<common-root>/eval/.venv \
  RONDO_BUILD_METRICS_DIR=<本轮精确 metrics 根> \
  <absolute-worktree>/mydev/scripts/with-build-lock.sh \
  uv run --directory eval --frozen --no-sync python -B <一次性 /tmp 驱动>
```

### `fix-git` 先行结果

- 2/2 side runs PASS，0 FAIL，0 SKIP；RONDO 与 Codex 均精确观测
  `main -> Guardian -> main`。
- 六个请求都实际投影非空 Lite 前缀：main 为 `additional_tools` 后四个 message、Guardian 为
  `additional_tools` 后两个 message；main tool count 2，Guardian tool count 1。
- receipt schema/projection 均为 v2，6/6 provenance records、6/6 gate registrations 全部通过。
- `actual_api_requests=0`，`actual_usd=0.0`。
- 第一次驱动在 Docker 前 fail-closed：相对路径启动 wrapper，lease 检查发现进程 cmdline 不是 canonical absolute
  wrapper，rc=1、容器 0。改用同一 checkout 的绝对 wrapper 路径后整轮从头运行并通过；失败轮不计产品通过。

成功轮 watchdog：`final_rc=0`、`stop_reason=none`、`cleanup_reason=none`；project peak
`23,039,684,608` bytes，memory peak `3,333,824,512` bytes，nonreclaimable peak `146,190,336` bytes，
swap peak 0。

### 完整 canary catalog 结果

- 10/10 tasks PASS，20/20 side runs PASS，0 FAIL，0 SKIP；任务为 `db-wal-recovery`、`extract-elf`、
  `filter-js-from-html`、`fix-git`、`headless-terminal`、`openssl-selfsigned-cert`、`polyglot-c-py`、
  `sanitize-git-repo`、`sqlite-db-truncate`、`vulnerable-secret`（均带 `terminal-bench/` namespace）。
- 60/60 捕获请求均完成 Lite `tool_specs` 与非空稳定前缀检查；每个 side run 都是精确
  `main -> Guardian -> main`。
- production `produce_preflight_receipts()` 在一次性目录整批产出 10/10 schema-v2 receipts；campaign-wide loader
  全部加载；共 60/60 provenance records、60/60 gate registrations 通过。
- `actual_api_requests=0`，`actual_usd=0.0`；没有真实 provider、模型、预算或 capability score。
- watchdog `final_rc=0`、`stop_reason=none`、`cleanup_reason=none`；project peak `23,039,840,256` bytes，
  memory peak `286,179,328` bytes，nonreclaimable peak `152,064,000` bytes，swap peak 0。

## Docker / 宿主资源与清理

- 会话前基线 `docker system df`：Images 26 / 11.5GB、Containers 0 / 0B、Local Volumes 0 / 0B、
  Build Cache 88 / 13.22GB。PowerShell probe：VHDX `69,467,111,424` bytes，Windows C: free
  `209,767,018,496` bytes，明显高于 80GiB stop floor；未发现并行 Cargo/rustc/nextest 或本地模型进程。
- 最终 `docker system df` 与基线完全一致；网络只剩既有 `bridge`、`host`、`none`。最终 VHDX 仍为
  `69,467,111,424` bytes，Windows C: free `209,768,517,632` bytes。
- 成功 `fix-git` 清理 2/2、本轮 catalog 清理 20/20 自建 `tb-preflight-*` work roots；一次性 receipt 目录自动
  删除。三个本批 metrics 根（含 Docker 前失败轮）在读取 summary 后按精确路径删除，两个 `/tmp` 驱动已删除。
- 最终检查：本批 metrics、驱动、`tb-preflight-*`、`rondo-eb8-v2-receipts-*` 均为 0；Docker containers 0、
  volumes 0。未删除任何既有镜像、build cache 或来源不明对象。

## 未验收边界

1. 仓库仍无正式 v7 identity；未执行正式 active identity 加载、正式
   `identity commit -> producer CLI -> worker CLI` 串联，也未创建 campaign/ledger/run ID。
2. 未运行正式 B7 Oracle、wire canary、paid task、pilot/repeats/aggregation 或 capability comparison；没有真实 API、
   provider、模型调用或费用。synthetic Docker 结果不得计入正式评分。
3. 本批只修复第四次审查点，没有扩展签名、可信审计、鉴权或统计系统，也没有改写冻结审查日志。
