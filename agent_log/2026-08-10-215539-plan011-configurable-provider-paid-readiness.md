# Plan 011：配置驱动 OpenAI-compatible paid readiness

## 1. 范围与历史边界

本批只修正 Plan 010 v6 暴露的 provider endpoint 绑定错误，并冻结新的最小 v7 paid pair。v6 的
`p1-fix-git-pair-v6`、budget/pair ledger、私有 artifact 与 `eval/results/runs.jsonl` append-only 行均保持原样；
v6 仍为 RONDO slot 1 `infra_failed`、Codex 未运行、M1 未运行，未结算 reservation 为 0.755400 USD，实际账单未知。

后续信息确认 v6 实际 provider 不是当时冻结的官方 OpenAI endpoint。用户提供的无认证探测证明当前 provider 在保留或
清除 ambient proxy 时都能快速返回 401，所以“清除 proxy 导致超时”不是根因；真正断链是 ignored config、tracked
pair 和 budget proxy 都错误固定 `https://api.openai.com/v1`。本批未运行 Docker、真实 API、Cargo 或模型，未产生费用。

## 2. 最小实现

### 配置与 endpoint

- ignored common-root `rondo.local.toml` 已由用户当前选择决定 `base_url`；Key 仍只由 ignored `.env.local` 提供。
  本批没有打开、搜索、打印或修改 `.env.local`，只通过既有严格 loader 做了无输出存在性/非空校验。
- `rondo.local.example.toml` 使用保留域名 `https://api.example.com/v1` 作为通用示例；
  `rondo.secrets.example.env` 未修改，仍只有空变量声明。
- budget proxy 不识别具体供应商：接受任意无凭据、无 query/fragment、无控制字符的 HTTPS base URL，去掉尾斜杠后
  拼接 `/responses`。HTTP、userinfo、非法端口及畸形 URL 在注册 run 和请求前拒绝。
- 既有 test-only loopback transport、禁止 redirect、host-only real key、临时 downstream key、declared role、预算和
  retry/hosted-tool 拒绝均保留。

### v7 公平与费用

- tracked pair 更新为 `p1-fix-git-pair-v7`，batch 为 `p1-fix-git-b3-m1-v2`：
  RONDO `20260810-233000000-tb-rondo-r1` → Codex `20260810-233000001-tb-codex-r1`，各一轮、零重试。
- pair lock 不再写 provider 域名；模型、API 形态、key 变量名、task/image、timeout、budget 与两侧 bundle 仍冻结。
  M1 复用结果中已有的 `provider_base_url` 和 `provider_config_sha256`，任一跨侧漂移都不能通过。
- Luna 继续按官方 Standard 价格计价：input 0.20、cached input 0.02、output 1.20 USD/百万 token；最大单请求
  reservation 0.755400 USD、5 USD/run、v7 最多 10 USD、底层 ledger 20 USD hard cap 均未改变。
- future record 在 `spent_usd == 0` 且没有 reserved request 时才写 `actual_usd=0.0`；存在未结算 reservation 或
  非零本地计价时写 `actual_usd=null`。这只改变未来 producer，不迁移 v6 行。
- main 提交 `fecd9f1d2fe162decfaf22d8771f8d75790c4552` 已合入本 readiness：重型构建容量只认 Windows
  `C:` 盘实际余量，低于 50GB 停止；Docker 仍以低于 80GiB 停止，无法读取时 fail-closed。旧日志中的约
  846GB 是无效的 WSL 虚拟容量证据，不用于门禁。
- canonical shell 启动时计算一次 common-root `rondo.local.toml` SHA-256，并在 RONDO、Codex 每侧进入
  watchdog 前重新计算并比较；配置漂移立即由 `set -e` 停止，不修改 ledger/schema。

当前 pair lock SHA-256：
`b9e38f51de548d2787ca80114b8df8eaaadc3138b05b3928a508eb5434bda29b`。

## 3. 验证

- `just eval-sync`：按 `eval/uv.lock` 为本 worktree 创建项目局部环境，83 packages；未运行产品构建。
- focused pure/fake/loopback 首轮：88 项通过；其中旧 v6 publication fixture 漂移导致的失败已更新为 v7。
- endpoint/config/pair/results 聚焦复跑：58 项通过。
- 最终相关六模块 pure/fake/loopback：87/87 通过（17.438 秒）。
- 严格 loader 无输出确认当前 local provider base URL 与 `OPENAI_API_KEY` 变量均可用；Key 内容未输出或记录。
- `py_compile`、`git diff --check` 通过。
- 合入 `fecd9f1` 后重新执行指定集成门禁：
  - `bash -n mydev/scripts/with-build-lock.sh`：通过；
  - `eval/.venv/bin/python -m unittest -q tests.test_runtime_bridge`：24/24 通过；
  - Plan 011 六模块 pure/fake/loopback：87/87 通过（17.390 秒）；
  - `git diff --check`：通过。
- canonical `HARNESS` 固定为本 readiness worktree，`WATCHDOG=$HARNESS/mydev/scripts/with-build-lock.sh`；因此后续
  命令使用的是已合入 Windows `C:` 容量门禁的看门狗，而非分叉前旧版本。
- tracked results 和 common `eval-data` 中 v7 pair、budget、两个 work/run/artifact 路径均不存在；本批没有创建
  v7 ledger、run、metrics 或 results worktree。

所有网络交互只有 `uv` 锁定依赖下载和此前用户提供/文档核对；测试 upstream 全部是 loopback fake。没有 Docker、
真实 API、Cargo、本地模型或费用证据。

本实现与本日志提交在独立 `0810-plan011-cctq-b3-paid-readiness` 分支；该分支已合入本地 main 的
`fecd9f1d2fe162decfaf22d8771f8d75790c4552`，未合并回 main、未推送。

## 4. 授权后唯一 canonical 命令

以下整段只供下一次单独真实 API 批量授权后执行，本批不执行。它从届时 clean readiness HEAD 创建独立 results
worktree，在项目 watchdog 内严格串行 RONDO→Codex；`set -e` 保证首侧失败不运行第二侧。host shell 清除大小写
HTTP(S)/ALL proxy，仅设置 loopback `NO_PROXY`；真实 upstream 由 common-root ignored `rondo.local.toml` 决定。

```bash
set -euo pipefail

COMMON=/home/sjc/desktop/RONDO
HARNESS=$COMMON/.claude/worktrees/0810-plan011-cctq-b3-paid-readiness
MEASUREMENT=$COMMON/.claude/worktrees/0810-p1-measurement
RESULTS=$COMMON/.claude/worktrees/0810-plan011-b3-m1-results
RESULTS_BRANCH=0810-plan011-b3-m1-results
PY=$HARNESS/eval/.venv/bin/python
WATCHDOG=$HARNESS/mydev/scripts/with-build-lock.sh
R_MANIFEST=$COMMON/eval-data/bin/rondo/cb652e1418e06d53171755963ad9eb8075259ffc-x86_64-unknown-linux-musl-runtime-bundle/manifest.json
C_MANIFEST=$COMMON/eval-data/bin/codex/rust-v0.147.0-be6e8eac029b183056b7e4402879f15d2c85f61b-x86_64-unknown-linux-musl-runtime-bundle/manifest.json
PAIR=p1-fix-git-pair-v7
BATCH=p1-fix-git-b3-m1-v2
R_RUN=20260810-233000000-tb-rondo-r1
C_RUN=20260810-233000001-tb-codex-r1
PROVIDER_CONFIG=$COMMON/rondo.local.toml
PROVIDER_CONFIG_SHA="$(sha256sum -- "$PROVIDER_CONFIG" | awk '{print $1}')"
printf 'provider_config_sha256=%s\n' "$PROVIDER_CONFIG_SHA"

READINESS_SHA="$(git -C "$HARNESS" rev-parse HEAD)"
test -z "$(git -C "$HARNESS" status --porcelain=v1 --untracked-files=all)"
test "$(git -C "$MEASUREMENT" rev-parse HEAD)" = cb652e1418e06d53171755963ad9eb8075259ffc
test -z "$(git -C "$MEASUREMENT" status --porcelain=v1 --untracked-files=all)"
test ! -e "$RESULTS"
test ! -e "$COMMON/eval-data/pairs/$PAIR-paid.json"
test ! -e "$COMMON/eval-data/budgets/$BATCH.json"
test ! -e "$COMMON/eval-data/work/$R_RUN"
test ! -e "$COMMON/eval-data/work/$C_RUN"
git -C "$COMMON" worktree add -b "$RESULTS_BRANCH" "$RESULTS" "$READINESS_SHA"

run_side() {
    side=$1
    run_id=$2
    manifest=$3
    metrics=$4
    test "$(sha256sum -- "$PROVIDER_CONFIG" | awk '{print $1}')" = "$PROVIDER_CONFIG_SHA"
    test ! -e "$metrics"
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        PYTHONPATH="$HARNESS/eval" \
        RONDO_BUILD_METRICS_DIR="$metrics" \
        "$WATCHDOG" "$PY" -B -m rondo_eval.terminal_bench \
        --side "$side" \
        --batch-id "$BATCH" \
        --run-id "$run_id" \
        --binary-manifest "$manifest" \
        --docker-host-volume /mnt/c \
        --results-worktree-root "$RESULTS" \
        --measurement-worktree-root "$MEASUREMENT" \
        --timeout-seconds 1800
}

cd "$HARNESS"
run_side rondo "$R_RUN" "$R_MANIFEST" \
    "$COMMON/eval-data/build-metrics/plan011-b3m1-v7-rondo"
run_side codex "$C_RUN" "$C_MANIFEST" \
    "$COMMON/eval-data/build-metrics/plan011-b3m1-v7-codex"

RESULTS_WORKTREE_ROOT="$RESULTS" RONDO_COMMON_ROOT="$COMMON" \
PYTHONPATH="$HARNESS/eval" "$PY" -B -c '
import json, os
from pathlib import Path
from rondo_eval.terminal_bench.pair import assess_m1, load_pair_identity
identity = load_pair_identity()
index = Path(os.environ["RESULTS_WORKTREE_ROOT"]) / "eval/results/runs.jsonl"
records = [json.loads(line) for line in index.read_text().splitlines() if line]
ledger = Path(os.environ["RONDO_COMMON_ROOT"]) / "eval-data/pairs" / f"{identity.pair_id}-paid.json"
result = assess_m1(records, identity, pair_ledger_path=ledger)
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
raise SystemExit(0 if result["m1"] == "passed" else 66)
'
```

## 5. 停止线

readiness 不等于 B3/M1 通过。下一次授权应明确：`terminal-bench/fix-git`，主 Agent 与 Guardian 均为
`gpt-5.6-luna`、Guardian effort low；RONDO 1 次→Codex 1 次、零重试；5 USD/run、pair 最多 10 USD、底层
20 USD hard cap；最多两个 Docker run。禁止 pull/build、Cargo、本地模型和自动重试。首侧失败立即停止。
