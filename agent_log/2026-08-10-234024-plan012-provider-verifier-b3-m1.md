# Plan 012 provider/verifier 与 B3/M1 最小链路日志

## 1. 起点与边界

- Plan 011 readiness `e50a2343df7e08a96874d31ab0e4ada96b6a09ca` 和 results
  `c3411b9b77227e20ca2892ddc4b0245fe5d8a3be` 已分别合并；本地与远端 main 均为
  `7bb03d0e23bcbc27dd49e66485652a502e44b0d5`。
- v7 的 failed/blocked pair、budget reservation、artifact 和 append-only result 原样保留，没有复用或改写。
- 本批禁止 Cargo、本地模型、Docker pull/build、自动重试和隔离边界放宽。真实探针最多三请求/1 USD；只有全部
  前置门禁通过才允许唯一 v8，RONDO→Codex 各一次、零重试、5 USD/run、10 USD/pair。
- `.env.local` 未被打开、搜索、打印或复制；只通过既有严格 loader 静默确认目标 credential 可用。

## 2. 直接阻塞修复

### Provider transport

- 找到真实根因：`LoopbackResponsesProxy` 默认虽为 120 秒，paid live 路径却把 Harbor 的 1800 秒 task timeout
  显式传入，导致 Agent 先结束而 upstream request 仍 reserved。
- 上游 transport deadline 现独立固定为 90 秒；构造器拒绝更长值，paid live 不再复用 task timeout。
- SSE relay 改为有界逐行读取，只在完整 `response.completed` 且 usage 合法时结算成功并主动关闭 upstream，
  不再等待 `[DONE]` 或 EOF。timeout、断连、失败/不完整终态和非法 usage 仍按原预算合同结算并停 run。
- 新增保持 TCP 连接不关闭的 SSE fake，以及 headers 前 timeout fake；前者在 upstream EOF 前返回并 settlement，
  后者得到安全 502、reservation 归零并按最大 reservation 结算。

### Verifier 与 oracle

- frozen fix-git staging 现在明确写入 `[verifier] user="root"` 与 `[verifier.env] HOME="/root"`，并在消费端
  精确复核；Compose service 和 `[agent].user` 保持 `1000:1000`。
- 新增严格 oracle command：只允许 `harbor trials start ... --agent oracle --delete`，不含 model、provider kwarg、
  agent env 或真实 key；复用既有 DockerSupervisor、pinned image、custom seccomp、资源限制和 cleanup。
- oracle 结果必须解析 exact `result.json` 并满足 completed + reward=1，不能只看 Harbor host return code。

### 小额 provider 探针

- 新入口固定三步：authenticated `/models` status、non-stream Responses、stream Responses。两次 Responses 均为
  Luna + low、`max_output_tokens=64`，通过 loopback budget proxy 和 host-only key；不保存或打印响应正文。
- 探针使用一个 max 1 USD、单 run、零重试 ledger；redirect、非 2xx、timeout、terminal/usage 缺失或未 settlement
  会立即停止后续请求。

## 3. 当前验证

- `just eval-sync`：按 `uv.lock` 安装 83 个包到本 worktree ignored `.venv`。
- `just eval-lock`：85 packages。
- focused proxy/provider/Terminal-Bench：45/45。
- `just eval-test`：270/270。
- `py_compile` 与 `git diff --check`：通过。
- 未运行 Docker、真实 API、Cargo 或模型；未创建 Plan 012 probe ledger、v8 pair/budget/run 或 metrics。

## 4. 下一步

1. 从 clean Plan 012 commit 在 watchdog 内运行一次 oracle，要求 reward=1。
2. oracle 通过后运行现有 RONDO→Codex no-API；三者合计最多三个 Docker task run。
3. Docker 门禁通过后运行唯一三请求/1 USD provider 探针；任一异常停止。
4. 只有以上全部通过才冻结 v8 并执行授权的唯一 paid pair；双侧 completed 后才运行 M1。

## 5. Docker 尝试 0（未进入 Docker）

- clean commit `6a36560ce76550f8361ab07d68b445514e5c389c` 的首次 oracle 命令在 watchdog 内建立了
  `plan012-oracle-verifier/20260810-234558-1000-77761`，随后在 Harbor 安装预检处因 CLI 漏传 frozen
  executable 参数直接返回 1。
- watcher `status=1/command_status=1`、`stop=none/cleanup=none`；没有启动 Docker、没有读取 key、没有 API
  或费用，因此不计入三个 Docker task run。
- 只补齐 `validate_harbor_installation(..., executable=HARBOR_EXECUTABLE)`，不改变任何执行或隔离合同；后续使用
  全新的 metrics 目录。

## 6. Oracle Docker 运行 1（失败并已清理）

- clean commit `9eba57031c9f642f8d5b2a8ef5ec3a606427bb1c` 在规范 watchdog 内启动了一个 pinned
  fix-git 容器；没有 API 请求、没有加载 key，费用为 0。
- Docker 有效态门禁通过：exact pinned image、UID/GID `1000:1000`、`cap_drop=ALL`、private cgroup、custom
  seccomp、2 GiB memory、3 GiB memory+swap、256 pids。容器、network 与 volume 最终均为 0，cleanup 为
  `verified_empty`；watchdog 自身没有资源停机或清理异常。
- Harbor structured result 为 `infra_failed`：oracle stdout 是 `/solution/solve.sh: Permission denied`，verifier
  stdout 是 `/tests/test.sh: Permission denied`，最终 `RewardFileNotFoundError`。未把 reward=0 冒充验收通过。
- 根因是冻结 checkout 的 `solution/`、`tests/` 目录为 `0700`，`solve.sh` 为 `0600`。文件由 UID 1000 上传后，
  UID 1000 oracle 无执行位；root verifier 在 `cap_drop=ALL` 下也没有 `DAC_OVERRIDE/FOWNER` 去穿越或修正这些
  UID 1000 拥有的目录。
- 最小修复只在 task staging 中把固定 `solution/`、`tests/` 目录规范化为 `0555`，两个 shell 脚本为 `0555`，
  verifier Python 输入为 `0444`。没有增加 capability、改变容器用户或放宽 seccomp；相关 materializer 回归
  19/19 通过。
