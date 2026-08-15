# Plan 030 独立验收整改

日期：2026-08-15

基于 `agent_log/2026-08-15-014216-plan030-independent-acceptance-review.md` 的三项直接发现，在原 Plan 030
范围内完成窄整改；没有新增通用审计、签名或 provenance 设施。

## 修改

- serve fingerprint 内部 schema 升为 v2：实际命令仍使用经过安全检查的 resolved 路径，稳定身份改用配置中的仓库相对
  模型/模板路径、模板 digest 与完整功能参数。相同配置在 Plan 030 worktree 和 main 路径下均得到
  `7cb5a45a7d7aa1810cc14da28ea7f09d0a3356765264c7a419b4b4ca038a477d`，参数漂移仍改变 hash。
- qualification 私有日志固定 verbosity 4，以取得冻结 b10333 唯一可见的 offload 事实；正式 launcher 固定 verbosity 3，
  不再把 trace-only API key 片段输出到终端。两条策略同时进入稳定启动指纹。
- 失败摘要删除动态原文 label，行形状与基础设施摘要都只返回固定类别；新增纯文本和冒号前敏感文本回归。
- 新增 linked-worktree/main 指纹稳定性、日志级别分离与固定日志类别覆盖。focused 门禁由 139 增至 140 项。

## 真实复证

- 生命周期 7，完整 qualification：真实 selector-bound static payload v3 `E_final` 返回 schema 合规判定；
  `n_ctx=12288`、单 slot、`build_info=b1-0865990`、GPU offload 33/35；显存 baseline 1,386,217,472 B、
  peak 7,855,931,392 B、delta 6,469,713,920 B；TTFT 3,183.48 ms、总耗时 7,048.56 ms；四项清理全 true。
  新 evidence 由正式代码原子生成，没有手工修改成功字段。
- 生命周期 8，正式 launcher + doctor：launcher 使用 verbosity 3 并发布相同 `serve_config_sha256=7cb5a45a…`；
  存活期 doctor 返回 `status=ready`、exit 0、`gpu_model_serving_validated`、`model_schema_probe_passed`。
  随后按 receipt 的 PID/start ticks/cmdline 精确校验并 SIGTERM，launcher rc=0。
- 最终现场：无 llama-server/qualification/launcher 进程，8080 无监听，GPU 无 compute process，receipt 与
  `eval-data/local-approval/` 私有对象为空。

## 门禁与边界

- 修复后、重新加载模型前：focused tests 140/140；`just eval-lock` 85 packages。
- 最终复跑：focused tests 140/140；`just eval-lock` 85 packages。
- 首次模型加载前的历史真实值为 138/138，首次诊断回归后为 139/139，本次整改新增一项后为 140/140。
- 12K 共 42 条适配样本，本次验证其中 1 条，未逐条验证的是其余 41 条；5 条超窗证据、16K、47 条批量
  generation、L7、Local M3、Cargo、Docker、云 API、训练、全量 eval 和全量测试均未执行。
