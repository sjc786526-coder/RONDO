# Plan 055 / M3-B2a Publication Critic 本地服务

日期：2026-08-22

分支：`worktree-055-publication-critic-service`

基线：`2bdd1f911e89046ddd8036e20f695f6371a06fc9`

## 实质修改

- 新建专用 `codex-publication-critic` crate，以公开 typed contract/client 和私有 wire/service 分离 B2b 消费面与进程实现；没有把
  服务依赖压入 `codex-core`、Team State 或 RONDO Local approval。
- 冻结 protocol v1 的严格 allowlist packet、loopback 一请求一连接的 4-byte 长度前缀 JSON、调用方可信 expected identity、
  单值 finite score 校验及 `score >= threshold` 映射。受控测试 identity 使用 `[0,1]`、threshold `0.5`，不代表真实模型参数。
- 服务以 admission/execution permit、有限队列、总 job deadline、连接关闭取消和 graceful/force 两阶段 shutdown 控制资源；
  client 只返回合法 `PASS/REWRITE` 或 `Contract/Infrastructure/Cancelled` typed failure，零 retry。
- 新增真实服务子进程的受控 scorer，覆盖 PASS/REWRITE、阻塞与 barrier、backend/shape/non-finite/identity 故障、异常退出和回收。
  受控 scorer 只替换 backend，仍经过正式 transport、协议解析、identity、admission、资源门和 typed client。
- 实现过程中修正了 permit 在响应写出前持有、force shutdown 未形成独立有界阶段、accept 永久错误可能忙循环等问题，并拆分
  contract 模块保持职责清晰。
- 首次独立审查确认公开 config 字段与未复验消费点可绕过 loopback/frame cap，且超大 timeout 可能令 deadline 算术 panic。
  修复后外部只能通过受检构造器获得配置，client/service 消费点仍作防御性复验，所有 timeout 统一限制在 5 分钟内。

## 验证

- `just test -p codex-publication-critic`：审查修复后最终 27/27 通过，0 skipped；新增回归覆盖非 loopback config 绕过、非法
  frame cap 和无界 client/shutdown timeout。
- `just clippy -p codex-publication-critic`：通过。
- `../scripts/with-build-lock.sh just argument-comment-lint -p codex-publication-critic`：通过；只出现既有依赖
  `codex-utils-cargo-bin` 的 unknown lint warning。
- `just fix -p codex-publication-critic`：通过；随后按 `multidev/AGENTS.md` 执行 `just fmt`：通过。
- `just bazel-lock-update` 与 `just bazel-lock-check`：通过；依赖均为 workspace 既有依赖，`MODULE.bazel.lock` 无差异。
- 重型 Cargo 入口均经过仓库共享构建锁与资源看门狗；未运行全 workspace、全 Bazel、CI 或 PR。

## 边界与当前状态

- 成功和代表性失败路径均用唯一正文 sentinel 验证普通错误、Debug、服务 stdout/stderr 不含 packet、candidate、continuity context
  或 raw body。typed schema 机械移除了任意 metadata 入口，但不宣称识别合法文本字段里被手工粘入的私密语义。
- 没有修改 `team_publish`、Team State、Team Lens、`eval/` 或 `training/`；没有构造 packet 的产品接入、mode/rewrite/fallback、
  committed replay fast path 或真实模型部署。
- 证据只证明受控 backend 下的正式进程/协议/资源/故障闭环。未下载或运行真实模型，未使用 Docker、真实 API、训练或云资源；
  真实 threshold、模型质量与部署资格仍待后续工作包。
- 实现与定向门禁已完成；首次本地提交后的单一干净上下文独立审查发现一项真实配置边界问题，修复提交 `dbc1d7a` 完成后由
  同一审查者复验为 `PASS`，无剩余 correctness/functionality finding。尚未合并、推送或归档分支。
