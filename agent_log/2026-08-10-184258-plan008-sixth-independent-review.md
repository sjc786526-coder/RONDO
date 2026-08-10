# Plan 008 第六次独立审查：v5 第一阶段收口

时间：2026-08-10（Asia/Shanghai）

审查提交：`a98914cf6bd621ce58051c38c3c6421735ab41e5`

对比基线：`fe517bcf9bace5325d205803ff00e0c036008e8d`

## 结论

本轮严格限于第五次审查列出的第一阶段整改，不扩展 B3、L2、跨 clone 协调或新的审计体系。

`a98914c` 已实质关闭 scoped Git 配置、UID 1000 前置 Git probe、cleanup 明确证明、失败事实保留、
runtime 耐久字段、65/70 恢复分类和 agent-user 安全诊断。实现和测试口径均可信。

但 no-API tool marker 仍存在一个可复现的同范围 false-green，因此**第一阶段尚不能最终完成**。除这一项外，
本轮没有提出新的整改范围。

## 唯一剩余问题：失败文本回显 marker 会被当作成功

冻结命令已经正确改为：先执行固定 `/app/personal-site` 的 `git status`，成功后才 `printf` marker。adapter
也通过私有 `GIT_CONFIG_GLOBAL` 只配置精确 `safe.directory`，并在 secret/model 前以 UID 1000 执行
`rev-parse` 和 `git status`。这些整改成立。

问题在 fake 的返回值验证：

- `docker_smoke.py:69-76` 的命令文本本身包含 `rondo_code_mode_smoke`；
- `docker_smoke.py:655-661,851-857` 只递归检查任意字符串是否包含 marker；
- unified-exec 的部分错误会回显完整命令（`mydev/codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs:398-400`）。

纯 loopback 复现向第二轮 `custom_tool_call_output` 提交：

`Script error: exec_command failed for git status && printf rondo_code_mode_smoke: spawn failed`

结果为 HTTP 200、`accepted=true`、`tool_round_trip=true`。Git 和 `printf` 均未实际成功，失败文本只因包含
marker 就被接受。前置 Git probe 能证明 adapter 初始化时 Git 可用，但不能替代 code-mode 子进程执行成功证明，
所以这仍会削弱 v5 no-API 的核心验收语义。

修复应保持很窄：按 code-mode `text(JSON.stringify(exec_command_result))` 的冻结结构严格解码，只接受
`exit_code == 0` 且标准输出去除末尾换行后精确等于 marker；拒绝普通字符串、错误文本、额外 marker 和
非零退出。补一个“失败文本回显正确 marker 仍必须拒绝”的回归即可。

v5 尚未创建 ledger，修复后无需更换 identity。

## 已确认关闭

- cleanup 只有显式 `cleanup_verified` 且 container/network/volume 均为零才记录 `verified_empty`；旧空 sample
  或复采失败均为 `unverified`。
- typed failure context 保留实际 request/hit/tool、Harbor rc、Docker samples 和 artifact digest；未知字段为
  `null`，不补造零。
- durable summary 保存 container user、精确 memory/swap/pids、network mode 与 rootfs 状态；completed
  对 `1000:1000`、2 GiB/3 GiB/256、private cgroup、cap drop 与 NNP 做严格校验。
- summary 保存并回放原始退出分类；轻量注入确认 `65 -> 65`、`70 -> 70`。
- Git、secret、runtime、agent exec 和 cleanup 等 agent-user 命令均经过闭集安全诊断，不再传播 Harbor raw
  command/stdout/stderr。

## 验证与状态

- 独立 `just eval-test`：286/286，0 failure/error/skip；
- 独立 `just eval-lock`：85 packages；
- 组合口径静态核对为 142：18 + 18 + 13 + 38 + 31 + 24；
- `git diff --check fe517bc..a98914c`：通过；
- v5 ledger 在 common-root 和 worktree 均不存在；
- 审查前 worktree tracked clean；`a98914c` 未合并、未推送，`main == origin/main == 2cc9140`；
- 未运行 Docker、Cargo、真实 API 或模型，未读取 `.env.local`。

完成上述唯一 marker 严格解析修复并通过窄回归后，可再次做一次限域静态复核；不应再追加与第一阶段无关的
工作项。静态收口通过后再进入 v5 RONDO→Codex 真实 Docker 验收。
