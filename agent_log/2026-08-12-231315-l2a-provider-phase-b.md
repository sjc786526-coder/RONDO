# L2a Guardian 独立 provider：阶段 B 验收

对应计划：`plan/019-l2a-guardian-provider-override-execplan.md`。最新
`main@73b05035c046c817a5c050faa9803f510856f83e` 已合入本工作树，merge commit 为
`1593ecf0d174d94ab0dc511685f61cdb9f2976b7`；独立只读重叠审查确认 main 与 L2a 源码路径零交集。

## 门禁与生成

- 主机级复核未发现 canary/TB 自动调度入口或活动进程；Cargo/rustc/nextest、Docker container、llama
  计算进程均为 0，全部 worktree 干净，结果目录无近期写入。Windows C 盘开始时可用约 213.2GB；项目内
  target、内存/swap/PSI 均满足门禁。
- `with-build-lock.sh /usr/bin/sleep 3` 实际验证 build lock/cgroup/计数器，summary
  `20260812-224241-1000-33861` 为 `status=0`、`stop=none`、`cleanup=none`。
- 受锁 `just fix -p codex-config -p codex-core -p codex-thread-manager-sample` 通过；诊断测试修改后再次受锁
  `just fix -p codex-core` 通过，最终 summary `20260812-230709-1000-32669` 为 `stop=none`。
- `just fmt`、`just fmt-check` 通过。`just write-config-schema` 通过；schema 只增加
  `auto_review.model_provider` 与关联说明，没有其他结构漂移。

## 定向验收

- 11 项 config/Guardian/schema/安全收缩精确回归全部通过，Nextest run
  `09d89510-6130-48a4-9235-fe3d18b9010f`；覆盖有效/无效 provider、项目层过滤、完整 provider + retry、
  主配置不变、无鉴权隔离、复用键失效、Bedrock/网络代理与 MCP/apps/plugins/memory 收缩。
- `codex-thread-manager-sample` 没有测试目标：普通 nextest 编译成功后按其 zero-tests 语义返回 4；随后使用
  `--no-tests pass` 完成明确的编译验收，run `48f188c3-145f-4000-bc3c-6ea9afec10b0`。
- 首次出站验收没有触发 skip，但宿主 HTTP 代理截获 loopback 并向正确的
  `http://127.0.0.1:<port>/v1/responses` 返回 502，两个 WireMock 因此收到 0 请求。测试补充终态错误和精确
  请求计数；验收进程显式设置 `NO_PROXY/no_proxy=127.0.0.1,localhost` 后直接连接 mock。
- 格式化后的最终出站 run `29e8ffe8-9cc3-4467-b955-57fe126e63f1` 为 2/2 通过、无 skip；summary
  `20260812-231031-1000-52162` 为 `stop=none`、`cleanup=none`。断言主 endpoint 精确 2 请求、Guardian
  endpoint 精确 1 请求；Guardian 请求携带独立 model/effort/header/query，不含主 Authorization 或
  ChatGPT account header。
- `git diff --check` 通过。未运行全量 workspace/Bazel；未调用真实 provider，未运行 Docker、本地模型或 GPU。
- 阶段 B 一度生成 git-ignored 构建/工具缓存：`mydev/codex-rs/target` 约 33GB、两个 `.venv` 合计约
  55MB、两个 Ruff cache 不到 1MB，以及约 452KB watchdog 临时目录；交付合并前按用户授权从本 worktree
  精确清理。未发现 `.snap.new`、`.rej`、`.orig` 或其他临时冲突产物，也未清理其他 worktree 资产。

## 结论

L2a provider 分流已完成阶段 B 验收。这不代表 L2 model-backed 推理或 L7 一键切换完成；本日志收口时
尚未合并/推送 main，后续交付动作按用户单独授权执行。
