# Plan 009 B2 轻量瘦身实施日志

## 范围与边界

本批只修复 no-API marker 假成功，并按 Plan 009 删除 B2 no-API 路径中过度维护的审计状态。没有运行
Docker、Cargo、真实 API 或模型，没有读取 `.env.local`，没有改动产品源码、冻结二进制、历史 ledger、
既有结果或历史日志。paid B3 的预算、不可复用 run、append-only publication 与恢复保持 hard-disabled。

## 实质修改

1. marker 改为解析 code-mode `custom_tool_call_output` 中的 JSON 字符串，只接受精确
   `{output, exit_code}` 两键、`exit_code == 0`，且 `output` 去除末尾 CR/LF 后精确等于
   `rondo_code_mode_smoke`。失败输出回显完整命令、额外文本、非零退出或额外字段均不能通过。
2. 删除 no-API permanent ledger、retirement registry、completed/failed summary 恢复状态机以及一次性
   `plan008_claimed_diagnostics` migration 和专用测试。历史数据不迁移、不改写。
3. Harbor preflight 从数千个依赖文件闭包收敛为 `eval/uv.lock` SHA、Harbor 0.20.0、console/interpreter
   以及三个入口相关模块。当前 pair lock SHA-256 为
   `02433f28d91810d9dd9b2cf1639ce86554e5045709e7aef545d3102cb3900e9a`。
4. `DockerExecutionResult.receipt()` 统一序列化已经由 supervisor 验证的 image、Docker Desktop VHDX、
   容器运行态、cgroup metrics、有效 seccomp 与 cleanup；B2 不再复制同一字段清单，也不保留 raw argv、
   stdout/stderr 或宿主 mount source。
5. 新增唯一 `just eval-b2-no-api` 入口：一个 watchdog 进程内预检两侧冻结 manifest，然后严格
   RONDO→Codex 串行；RONDO 失败时 Codex 不运行。只有双侧 completed 才原子替换
   `eval-data/b2/current.json`；普通 no-API 失败可以修复后由用户重新运行。
6. 删除围绕旧 retirement、migration、多版 no-API schema、崩溃恢复和依赖闭包的重复测试，保留 marker、
   公平性、付费边界、Docker fail-closed/cleanup 与当前收据的行为测试。

## 规模结果

以 worktree 起点 `a98914cf6bd621ce58051c38c3c6421735ab41e5` 为基线：

- 生产 Python：20,208 → 18,473 行，净删除 1,735 行；
- 测试 Python：11,552 → 10,171 行，净删除 1,381 行；
- 测试方法：286 → 260；
- `pair.py + docker_smoke.py`：3,432 → 2,133 行。

没有通过搬移文件、生成代码或放宽 Docker/watchdog、secret、budget、paid publication 边界取得减行结果。

## 验证

- 受影响模块：99 tests，全部通过；
- `just eval-test`：260/260，全部通过；
- 最终 marker 整数类型收紧后，`test_terminal_bench_docker_smoke`：7/7，通过；
- `just eval-lock`：85 packages，lock check 通过；
- `git diff --check`：通过。

上述均为 pure/fake/loopback 或静态锁验证。未运行真实 Docker，因此新单进程入口、两侧 adapter 和 current
receipt 仍待后续真实 B2 验收；B2、B3/M1 和 Plan 008 均不据此宣告完成。
