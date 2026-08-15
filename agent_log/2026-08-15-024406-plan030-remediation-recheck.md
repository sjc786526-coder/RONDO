# Plan 030 整改复审

日期：2026-08-15

审查对象：`3dcff1a fix(eval): stabilize 12k qualification delivery`

前次报告：`agent_log/2026-08-15-014216-plan030-independent-acceptance-review.md`

## 结论

- **验收：不通过。** `3dcff1a` 已正确修复前次三项发现并完成可信真实复证，但正式 launcher 仍把 b10333 的 stdout/stderr 继承到普通终端；verbosity 3 下仍有 WARN/ERROR 级的模型正文输出路径。
- **任务目标：失败（指当前提交形态）。** 12K qualification、稳定 capability 与 launcher/doctor 功能目标本身已经实现；剩余问题是正式入口的直接日志边界，属于 Plan 030 内可无模型窄修，不代表 12K 路线失败。
- 当前仍不合并、不推送，不进入 L7，也不新增日志审计或可信设施。

## 前次三项发现的复审结果

三项均已正确闭合：

1. 使用同一提交代码和当前 ignored 配置独立重算，Plan 030 worktree 与未来 main 的 `serve_config_sha256` 均为 `7cb5a45a7d7aa1810cc14da28ea7f09d0a3356765264c7a419b4b4ca038a477d`。两处构造的完整 `QualificationIdentity` 相同，且都与新 evidence identity 匹配；参数漂移测试仍会改变 hash。
2. qualification command 固定 verbosity 4 并写入 0600 私有临时日志；正式 command 固定 verbosity 3。两种策略均被稳定 fingerprint 绑定，正式入口不再输出 trace-only API key 后四位。
3. 失败摘要只返回 `ggml`、`srv`、`<payload-like>`、`<other>` 等固定类别及计数。独立用无分隔符文本、冒号前敏感文本、payload-like JSON 和 `srv` 前缀文本复现，输出中均不再出现输入原文。

新 tracked evidence 可由 strict loader 接受，并按当前 runtime identity 投影为
`gpu_model_serving_validated / structured_output_validated`。selector-bound `E_final` 与 meta SHA 分别仍为
`eaa2dfb1…9ebaca`、`40917cec…d59f`；evidence 记录 12,288、33/35 offload、TTFT 3,183.48 ms、
总耗时 7,048.56 ms、完整 VRAM 指标、schema compliance 和四项 cleanup，文档与整改日志已同步。

独立门禁：focused tests **140/140** 通过；`just eval-lock` **85 packages** 通过。

## 剩余阻断：verbosity 3 仍可能把模型正文写入普通终端

`eval/rondo_eval/local_approval/launcher.py:1227` 的正式 `Popen(command, env=environment)` 没有指定 stdout/stderr，
所以继承 launcher 的普通终端。把 verbosity 从 4 降到 3 只屏蔽 TRACE/DEBUG，并不屏蔽 WARN/ERROR。

冻结 b10333 中存在可达的正文输出：

- `common/chat.cpp:3482`：最终 structured/PEG parse 失败时，WARN 会输出未解析的
  `effective_input.substr(...)`；`tools/server/server-task.h:385-387` 的最终 response 以 `is_partial=false` 进入该解析。
  输出截断或格式异常即可触发，正属于本任务要求 fail-closed 的错误输出路径。
- `common/sampling.cpp:304-305`：grammar prefill 初始化异常时，ERROR 会输出 generation prompt。

因此正式服务遇到错误输出时，模型生成正文或请求派生内容仍可能进入普通终端/上层日志；这违反 Plan 030 已明确的
“模型输出、rationale、raw server log 不进入普通日志”边界。现有 140 项测试只断言正式 argv 使用 verbosity 3，
没有断言正式 `Popen` 的 stdio 去向。

## 替用户作出的整改决策

1. **只做一个窄修。** 正式 launcher 启动 b10333 时把 stdout/stderr 定向到 `subprocess.DEVNULL`（或严格等价的不可外泄 sink）；qualification 继续保留现有 0600 私有 trace 日志。不要新增日志文件轮转、过滤器、扫描器或审计设施。
2. **扩展现有测试，不增加重复套件。** 在已有正式 launcher/doctor 消费测试中记录 `Popen` kwargs，并断言正式 stdout/stderr 不继承终端；同时保留 qualification 仍写 0600 私有日志的现有覆盖。可保持 focused 总数 140。
3. **不改资格 identity，不重新加载模型。** stdio sink 不改变模型、请求、argv、serve fingerprint 或 evidence 内容；此前生命周期 7 的真实 qualification 与生命周期 8 的 launcher/doctor 复证继续有效。修复后只需重跑 140 项 focused tests、`just eval-lock`、diff/现场检查和无模型复审。
4. **保持所有冻结选择。** 继续使用 12,288、512、`gpu_layers=auto`、`fit=on`、batch 512、ubatch 256、flash on、K/V f16、现有 selector/static payload v3 和 `7cb5a45a…` evidence；不开展参数探索，不进入 L7。

## 现场边界

审查时主工作区仍为 `ffd3cc6` 且与 `origin/main` 一致，worktree 在写本报告前为 `3dcff1a` 且 clean；
`rondo.local.toml` 是 mode 0600 普通文件，`eval-data/local-approval/` 无对象，进程表未见本任务服务。
当前审查 sandbox 无 netlink/NVML 权限，未冒充重新确认 8080/GPU；沿用执行者复证后的清理记录。

本轮没有重新加载模型，没有运行 Cargo、Docker、云 API、全量 eval 或全量测试，也没有读取 `.env.local`。
