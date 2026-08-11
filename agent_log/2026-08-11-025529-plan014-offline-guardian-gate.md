# Plan 014 单审批付费重放门禁

## 修改

- 在独立 worktree `0811-plan014-paid-pair` 开始 Plan 014 离线落地；没有复用或修改旧 v8 identity/result/ledger。
- `LoopbackResponsesProxy` 增加可选 `max_guardian_logical_requests=1` 合同。第一个 Guardian logical request 仍可在
  同一 reservation 和 90 秒 deadline 内执行 operator-confirmed-unbilled transport attempts；任何第二个
  Guardian downstream request 都在 reserve/forward 前返回本地非瞬态 409，并持久停止 run。
- 正式 Terminal-Bench live、CLI short diagnostic 和 provider short probe 均显式启用该限制；短测继续每 request
  预留 1 USD，正式 live 继续使用 5 USD（或 run 剩余额度）预留。

## 验收

- focused loopback 验证正常 `main → guardian → main` 不受影响，首个 Guardian request 的 503-unbilled→200
  两次 upstream attempts 可完成，模拟 charged parse replay 的第二个 Guardian request 没有新增 reservation、
  metadata 或 upstream request，ledger stop reason 为 `guardian_logical_request_limit_exceeded`。
- proxy、model CLI diagnostic、provider probe 与 Terminal-Bench live projection 共 58/58 通过；Python compile 与
  `git diff --check` 通过。
- 新 worktree 初次缺 Harbor 依赖，锁定 `uv.lock` 的项目局部 `uv sync` 后 focused live 用例通过；没有 Cargo、
  Docker、真实 API、paid pair 或 M1。

## 边界

- 这是固定单审批 Terminal-Bench task 的安全合同，不宣称已经解决任意任务中多个独立审批的通用 correlation。
- frozen Codex 未修改。catalog/source identity、新 pair/profile drift 与 public/redacted result 仍待后续离线落地；
  正式 canary、Docker 和 paid pair 仍需 Plan 014 自己的范围授权。
