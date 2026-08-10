# Plan 009 B2 wire 与 watchdog 断链修复

## 核对结论

两项审查结论均成立：

- 冻结 code-mode 将工具输出写为两个 `input_text` content item；第二项才是 `text(...)` 产生的 JSON。
  原 no-API fake 直接伪造单字符串，无法代表真实请求。
- linked worktree 的 `$PWD` 不是 Git common root；recipe 显式设置 `RONDO_PROJECT_ROOT="$PWD"` 会被
  runtime bridge 的 common-root 门禁拒绝。

## 修改

1. code-mode JS 只投影 `{output, exit_code}`；Python 要求真实两项 `input_text` wire shape，并只解析第二项。
   解析后的对象仍必须精确两键、整数退出码 0、stdout 去除末尾 CR/LF 后精确等于 marker。失败文本回显、
   单字符串、错误 item 数量、非零或布尔退出码、额外字段继续拒绝。
2. 删除 `just eval-b2-no-api` 的 `RONDO_PROJECT_ROOT="$PWD"`；`with-build-lock.sh` 按既有逻辑从
   `git rev-parse --git-common-dir` 推导真实项目根。

本批不修改 Docker、预算、paid publication、资源监督或其他审计范围；不运行 Docker、Cargo、真实 API
或模型。

## 验证

- `test_terminal_bench_docker_smoke`：7/7，通过；
- `just --dry-run eval-b2-no-api ...`：渲染命令不含 `RONDO_PROJECT_ROOT`，未启动 Docker；
- `just eval-test`：260/260，通过；
- `just eval-lock`：85 packages，通过；
- `git diff --check`：通过。
