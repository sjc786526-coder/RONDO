# Plan 088 / #39153 Permission Restore Fail-Closed 适配实施日志

## 上游与现有缺口

- 只读核对 exact upstream `539a09cb28ca1ded4278c6d54716abbacab42428` 相对 parent
  `6f95f19103983e4d269609bff86c7dd20bd16c7c`，11 文件、`+935/-268`；保存于 `/tmp` 的 patch SHA-256 为
  `21f58639f92dbc86790359333fc8cf57c980afc5c29402bdaafe4fdf5cb8037b`。
- 上游恢复 policy、reviewer、active-profile identity 并按当前配置重解析，但 invalid/missing/disallowed profile 会宽松回退。RONDO
  live code 还只在 `ThreadSettingsApplied` 保存 identity，普通 turn/compaction 的 `TurnContext` 不保存，resume/fork 只恢复 reviewer。
- cold resume 与 fork 的 config load 均早于可执行 runtime/child 创建；paginated boundary fork 的设置语义来自 source 最新状态，而非历史边界。

## 实现

- 为 canonical `TurnContext` 增加 presence-aware active-profile 字段：missing 表示 legacy，`null` 表示最近明确无 named identity，object
  表示必须当前重解析的 ID。普通 turn 与所有本地/远程 compaction 复用同一 writer。
- 新增窄 recent-settings 投影，统一恢复 approval policy、approvals reviewer 与 identity；保留同一 turn 内 settings update 胜过 stale
  compaction context 的 RONDO 语义。最近 legacy/explicit-clear identity 边界都不向前复活旧 ID。
- cold resume、legacy/paginated fork、loaded source 与 boundary fork 收敛到同一 merge；typed/raw 请求 override 分域优先，state DB 仍不作为
  settings 权威。
- Config 增加内部 persisted-profile 来源并复用当前 catalog、profile inheritance、Plan 086 trust、workspace roots、network 与 requirements
  编译。missing/invalid/disallowed 或 concrete requirement 会 fallback 的历史 ID 明确报错；合法显式权限 override 先清除该来源。
- app-server 文档说明优先级、当前重解析、fail-closed 与 legacy 行为；测试均使用 task-owned `TempDir` 和 fake Responses server。

## 调试与修复

- 初次 fmt 仅因默认 uv cache 不可写失败，改用 worktree 内 ignored `.uv-cache` 后通过。
- 编译阶段补齐 `TurnContextItem` 构造器并修正 ts-rs nullable 标注；集成调试阶段把无效 TOML approval 值改为 `untrusted`，并将五项
  app-server 场景串行运行以避免并行初始化超时；concrete-requirement fixture 改为当前 parser 支持的有效 profile 定义。均为 fixture/
  构造问题，修复后形成下述干净正式结果。

## 正式验证

所有重型命令均在 `multidev/` 通过 `just`、共享 `scripts/with-build-lock.sh` 和用户指定的 069 target 运行，命令级项目门限为
270/285/290GB，`CARGO_BUILD_JOBS=1`。

- protocol 三态 serde 聚焦：`1/1` 通过。
- codex-core persisted-profile 当前重解析与 fail-closed 六项：`6/6` 通过，`2312` skipped。
- codex-app-server lib：`279/279` 通过。
- legacy/paginated cold resume、legacy/paginated fork、invalid profile 拒绝与显式 override 集成：`5/5` 通过，`883` skipped。
- `just fix -p codex-protocol -p codex-core -p codex-app-server -p codex-exec` 通过并做一处所有权简化；随后
  `UV_CACHE_DIR=.uv-cache just fmt` 通过。依就近规则，fix/fmt 后未再运行测试。
- 最终通过的测试/修复批次均为 `stop=none`、`cleanup=none`、swap peak `0`。通过批次最高项目采样为
  `273,409,286,144 B`（约 `273.41GB`），低于 `285GB` 主动停止线；调试失败轮最高为 `274,184,130,560 B`，同样未触发停止或清理。
  scoped fix 内存峰值约 `6.27GB`，低于 `21/22GB` 门限。未触发 target 清理。

未运行完整 workspace `just test`：实际风险已由 protocol、core、app-server 全库和端到端正反主链覆盖，继续扩大与本任务写集不成比例。
未运行 Docker、真实 API/模型、训练、云资源、性能测评、CI/PR 或远端操作。

## 自审

- `git diff --check` 通过。执行者静态自审与独立只读复核均未发现高/中等级 correctness finding。
- 独立复核指出 paginated invalid-profile 与 fork invalid-profile + override 可补直接集成证据；现有 paginated 正向主链、共享 merge/config
  seam、严格 config 反例和 legacy 负向端到端已组合覆盖，未扩成重复矩阵。
- 本分支不修改 WBS/COMPLETED，不宣称 `M4_W_39153_ADAPTATION_PASS`；等待指定审查者独立验收。不合并、不推送、不关闭 worktree，
  不启动 M4-W1。

## 验收后测试加固

- 独立验收提交 `4fc5dc7` 接受 `M4_W_39153_ADAPTATION_PASS`，同时记录 invalid-profile 集成未直接断言 child/started 不存在这一低风险
  测试余项。用户随后要求窄修关闭该余项。
- 仅修改既有负向 app-server 场景：失败前后通过现有 `thread/list` 比较完整 thread ID 集合，并在 list 响应已冲刷消息流后检查现有
  `pending_notification_methods()` 不含 `thread/started`。没有修改生产代码、增加 helper 或建设副作用审计设施。
- 首轮单项测试 run `20260826-083848-1000-3145407` 未触达断言，两次均在 app-server initialize 基线超时并由看门狗清理残留进程，
  `final_rc=100`，不记为产品失败。确认锁、残留进程和容量后，热目标 run `20260826-084312-1000-3172734` 为 `1/1` 通过、
  `887` skipped、`stop=none`、`cleanup=none`；随后 `UV_CACHE_DIR=.uv-cache just fmt` 通过，未再运行测试。
