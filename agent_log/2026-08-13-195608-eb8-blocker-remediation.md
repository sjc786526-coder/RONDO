# E-B8 三次审查 blocker 修复与无 API Docker 验收

## 范围与结论

- 接续 `agent_log/2026-08-13-183355-eb8-third-acceptance-review.md`，先按当前源码、测试和入口复核了其中
  2 个 blocker 与 1 个 receipt 半批次问题；三项均存在。
- 本批完成对应窄修复、纯/假/loopback 回归和用户授权的无真实 API Harbor/Docker 验收。
- 修复后的 `fix-git` 双侧真实轨迹与完整 10 题 canary catalog 均通过；两侧每次都是严格的
  `main -> Guardian -> main`，receipt 同时冻结 `main`、`guardian`，完整批次可由 worker receipt loader 和
  `require_expectation=True` gate 消费。
- 当前仍无正式 schema-v7 identity。本批只使用进程内一次性 synthetic identity，未创建或激活正式 campaign、
  lock、active pointer、ledger、run ID、结果目录；没有真实 API 请求、真实模型调用或费用。因此本日志证明修复后的
  设施链可用，不把它表述为正式 v7 campaign 的 identity-to-worker 全生命周期验收，也不改写旧审查报告在形成时点的
  blocked 结论。

## 实质修复

1. **解除 identity commit 与 harness commit 自引用**
   - `validate_eval_harness_checkout(..., expected_commit=H)` 仍要求整个工作树（含 untracked）干净；`H` 必须是
     当前 `HEAD` 的 ancestor；只允许 `H..HEAD` 不改变已提交的 eval 运行投影。
   - 投影覆盖 `eval/rondo_eval`、依赖/锁、seccomp、taskset、templates、`justfile`、实际执行的
     `with-build-lock.sh` / `build-watchdog-lib.sh` 与 tracked secret-name allowlist。campaign lock 与 active pointer
     可单独提交而不会形成 `HEAD` 自引用，但不能靠未提交 identity 文件绕过 clean gate。
   - `eval/locks` 另做显式 identity-only 白名单：只允许新增 campaign lock 与 active pointer 的新增/修改；历史 lock
     的修改、删除及其他 lock 路径变化仍会拒绝。
   - producer 与 worker 都在任何 Harbor、Docker、oracle、wire canary 之前传入 identity 声明的 `H`，并立即调用
     `require_declared_conditions()`；task slot 的运行中复核使用同一 expected projection。
2. **冻结完整 main/Guardian 合同**
   - stub 第一次 main 响应给出一个 inert `exec_command(cmd=true)` 审批调用，第二次由真实 Guardian 请求取得四字段
     allow JSON，第三次回到 main 并正常结束。
   - 捕获端要求观测序列精确为 `main, guardian, main`，且第三次 main 的 task-independent contract 必须与第一次
     main 一致；receipt 产出和加载都要求角色集合精确为 `{main, guardian}`。
3. **消除 receipt 半批次与不可重试问题**
   - 先捕获、比较完整 catalog 的全部任务，成功后才进入最终文件发布；后题失败不会留下前缀 receipt。
   - 发布前先扫描全部 destination；任一 symlink 或不同字节冲突都会在写第一份文件前整批失败。完全相同的既有
     receipt 按 exact bytes 幂等接受，允许实际 I/O 中断后的安全重试。
4. **补真实对象形状与生命周期回归**
   - `_validate_stub_projection()` 使用实际 `RunSpec` / `PreparedTerminalBenchRun` dataclass 形状，防止假对象再次掩盖
     字段漂移。
   - 临时 Git 仓库回归覆盖：只生成未提交 lock/pointer 时拒绝；identity-only commit 后接受；未提交或已提交的
     harness 漂移都拒绝。

## 纯/假/loopback 测试

实际命令：

```text
just eval-lock
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  UV_CACHE_DIR=/home/sjc/desktop/RONDO/eval-data/uv-cache \
  uv run --directory eval --frozen --no-sync \
  python -m unittest tests.test_fair_comparison -v
just eval-test
```

结果：

- `just eval-lock`：PASS，最终复核 `Resolved 85 packages in 0.73ms`。
- `tests.test_fair_comparison`：83 PASS / 0 FAIL / 0 ERROR / 0 SKIP，最终复核 2.414s。
- `just eval-test`：574 PASS / 0 FAIL / 0 ERROR / 0 SKIP，最终复核 71.760s。
- `git diff --check`：PASS。
- 以上均为 pure/fake/127.0.0.1 loopback 测试；不使用 Docker、真实 API 或真实模型。

## synthetic Harbor/Docker 验收

### 身份与入口边界

- 一次性驱动从真实 v22 provider profile、真实双侧 bundle manifests、当前 successor canary catalog、真实共享
  8-model catalog 与 tracked seccomp 构造进程内 schema-v7 identity；shared catalog SHA-256 为
  `357e5f2ecbe5a9f99cf59f2d06cacd9107de96d53cb423ec32e4fe78fe2a0cea`。
- identity 只存在于进程内，receipt 只写入 `/tmp` 的 `TemporaryDirectory`，退出时自动删除。驱动和 `.pyc` 在验收后
  删除。没有写 `eval/locks`、active pointer、`eval-data/campaigns`、budget ledger 或正式 results。
- 每题先用 `docker image inspect` 确认 content-addressed 镜像在本地；没有 pull、build 或并行运行。冻结二进制通过
  生产 `capture_side_requests()`、真实 Harbor、Docker supervisor、共享 catalog 投影和本地 capture stub；唯一模型
  endpoint 是 `host.docker.internal` 回连的 127.0.0.1 stub，注入的是固定假 bearer。

核心实际命令（`phase` 分两次，先 `fix-git`，后完整 catalog）：

```text
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  PYTHONPATH=/home/sjc/desktop/RONDO/.claude/worktrees/022-p2-eb8-fair-comparison/eval \
  UV_CACHE_DIR=/home/sjc/desktop/RONDO/eval-data/uv-cache \
  UV_PROJECT_ENVIRONMENT=/home/sjc/desktop/RONDO/eval/.venv \
  RONDO_BUILD_METRICS_DIR=<本次精确 metrics 目录> \
  mydev/scripts/with-build-lock.sh \
  uv run --directory eval --frozen --no-sync python -B \
  /tmp/rondo-eb8-synthetic-preflight.py <fix-git|catalog>
```

### `fix-git` 先行结果

- 最终验收：2/2 side runs PASS，0 FAIL，0 SKIP；RONDO 与 Codex 都实际观测
  `main -> Guardian -> main`，并都返回 `main` / `guardian` receipt roles。
- main contract：`f627b2de76b0cd4b798d27b4a07ff4aa503ce36957888ee6b11a71cb4ae3ea3f`；
  Guardian contract：`872232da022970d76694a642b01340a2a83904cca7bbba1de8791bd95ad5584e`。
- receipt seed 后，RONDO/Codex x main/Guardian 共 4 次 gate registration 全部接受。
- `actual_api_requests=0`，`actual_usd=0.0`。

开始阶段另有 3 次驱动级失败，均未计为产品通过且均如实保留：

1. 第一次在 Docker 前因 `/tmp` 驱动未设置 `PYTHONPATH`，`ModuleNotFoundError: rondo_eval`，rc=1，容器 0。
2. 第二次完成 RONDO 捕获后，清理 Harbor 只读 `solve.sh` 时 `PermissionError`，rc=1；supervisor 已清容器，
   对应 exact work root 随后单独改权限并删除。
3. 第三次完成 RONDO 捕获后，递归 chmod 因 container-owned verifier 文件返回非零，驱动把该清理返回码误判为失败，
   rc=1；其父目录实际可安全删除，对应 exact work root 随后删除。驱动改为忽略这些不可改 mode 的文件、再删除自己
   创建的 exact root 后，重新从双侧起点完整运行并得到上述 PASS。

这 3 次是临时验收驱动的导入/清理缺陷，不是 main/Guardian 对称或产品链 fail；其中后两次的单侧结果也没有拼接进
最终结果。

### 完整 canary catalog 结果

- 10/10 tasks PASS，20/20 side runs PASS，0 FAIL，0 SKIP。任务为：
  `db-wal-recovery`、`extract-elf`、`filter-js-from-html`、`fix-git`、`headless-terminal`、
  `openssl-selfsigned-cert`、`polyglot-c-py`、`sanitize-git-repo`、`sqlite-db-truncate`、
  `vulnerable-secret`（均带正式 `terminal-bench/` namespace）。
- 每个 side run 都是严格 `main -> Guardian -> main`，每题两侧都冻结 `{main, guardian}`。
- `produce_preflight_receipts()` 在一次性目录整批产出 10/10 receipts；
  `_require_all_preflight_receipts()` 返回成功；逐题 seed 后的双侧/双角色共 40/40 gate registrations 全部接受。
- `actual_api_requests=0`，`actual_usd=0.0`。没有真实 provider、真实模型、付费预算或 capability score。

## Docker 与宿主资源证据

任务前基线：

- Docker：Images 26 / 11.5GB，Containers 0，Local Volumes 0，Build Cache 88 / 13.22GB。
- PowerShell Docker Desktop probe：VHDX `69,467,111,424` bytes；Windows `C:` free
  `209,758,318,592` bytes（约 195.35GiB），高于 80GiB stop floor。
- 未发现并行 Cargo/rustc/nextest、真实本地模型或既有容器任务。

`fix-git` 成功轮：

- watchdog `final_rc=0`、`stop_reason=none`、`cleanup_reason=none`；project peak
  `23,039,430,656` bytes；memory peak `1,602,269,184` bytes；swap peak 0。
- wrapper 记录 `C:` free `209,772,281,856 -> 209,772,376,064` bytes；阶段后 Docker 数量/字节与基线一致，
  容器 0。

完整 catalog 成功轮：

- watchdog `final_rc=0`、`stop_reason=none`、`cleanup_reason=none`；project peak
  `23,039,606,784` bytes；memory peak `287,289,344` bytes；nonreclaimable peak `156,323,840` bytes；swap peak 0。
- wrapper 记录 `C:` free `209,772,388,352 -> 209,772,150,784` bytes；最终独立 PowerShell probe 为
  `209,771,880,448` bytes，VHDX 仍为 `69,467,111,424` bytes。
- 最终 `docker system df` 与基线一致：Images 26 / 11.5GB、Containers 0 / 0B、Local Volumes 0 / 0B、
  Build Cache 88 / 13.22GB，即 Docker 计数与显示占用增量为 0。网络仅剩既有默认 `bridge` / `host` / `none`。

## 清理结算

- 成功的 `fix-git` 与 catalog 轮分别清理 2、20 个自己创建的 `tb-preflight-*` work roots；两个失败清理尝试
  各留下的 1 个 exact root 也分别核对名称后删除，共 24/24 本批 work roots 已清理。
- 5 个本批 build-metrics roots（含 3 个失败尝试、2 个成功轮）在读取 `summary.env` 后按 exact path 删除。
- 一次性 receipt `TemporaryDirectory` 自动删除；临时 Python 驱动与唯一 `.pyc` 已删除。
- 最终检查：`tb-preflight-*` 0 个，本批 `/tmp/rondo-eb8-receipts-*` 0 个，Docker containers 0、volumes 0；
  没有删除既有镜像、build cache 或来源不明对象。

## 尚未验收的边界

1. 仓库仍没有正式 v7 identity；遵守授权未生成正式 campaign、ledger、run ID 或 active pointer，因此没有执行正式
   `just eval-b7-preflight-receipts` CLI 的 active-identity 加载，也没有做真实“生成 identity commit -> producer CLI ->
   worker CLI”入口级串联。对应 Git lifecycle、producer startup ordering、全 receipt loader 已分别由回归和 synthetic
   实链覆盖，但不能替代正式 identity 生命周期。
2. 未运行正式 B7 oracle、wire canary、paid task slot、pilot/repeats/aggregation或 capability comparison；没有真实 API、
   provider、模型加载或费用，所有 synthetic Docker 结果都不得计入正式评分。
3. mountinfo 的原生 Docker 分支未为本批额外扩大实机覆盖；当前正式 recipe 继续使用已验证的 PowerShell probe。
4. 旧审查报告是日期冻结证据，保持原文；本批只新增此日志记录当前修复与证据。
