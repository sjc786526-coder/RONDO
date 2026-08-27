# Plan 092 Durable Session TUI 基线欠账窄修复

## 结果

- Durable Session 分页测试的 duplicate protocol fixture 继续通过 JSON response 反序列化验证，但 operation 子树改为 typed
  `DurableSessionOperations`；当前六个正式 operation（含 `set_root_state`）必须完整构造，未来新增字段会在编译期暴露欠账。
- 两个 query snapshot 只补入产品现有渲染的 `set-root-state` availability/provenance，分别保持 active、read-incomplete 与
  identity-unavailable 的原 reason；没有修改 protocol、schema、产品能力或 Plan 091 prompt-edit。
- 独立只读审查结论 `ACCEPT`，High/Medium correctness finding 均为 0。

## 验证

- 修复前直接复用 Plan 091 JUnit：3436 passed、3 failed、4 skipped；三项失败均重试后仍失败，精确指向 fixture 缺
  `setRootState` 和两个陈旧 snapshot。原 JUnit SHA-256 仍为
  `c4ca1b921297a7f4de67229051b4fff7b847631ec53788f3159986a2b00b2f03`，未覆盖或删除。
- 正式聚焦轮 Nextest `254006bd-0888-4669-9c9b-eb2f457cad5e` 为 22/22 passed，覆盖三项原失败、query/control 相邻行为、
  pagination/transport-loss/late completion 和 Plan 091 prompt-edit/Esc/分页回归；JUnit SHA-256
  `166cabf7d67fcaf0a309b9d1ca659d85b17a965f92c0938f46db039eca32523a`。
- 完整 `codex-tui` crate Nextest `499b4a7d-dc21-4749-9bb3-8959b5504e99` 为 3439 passed、0 failure、0 error、4 skipped；
  JUnit SHA-256 `8fa6b5badf8ac38e6ed99ffb7fbee964146160d774ad0df687ba51d53263ef1b`。唯一 retry 是 fake app-server teardown 的
  `experimental_session_response_loss_is_bounded_unknown_and_never_replayed` 首次 `Broken pipe`、第二次通过；定点复核 Nextest
  `c6f32bd7-757c-43a8-87a6-008b51e53a4f` 为 1/1 一次通过。
- 4 个 skip 不计通过：3 个显式 `#[ignore]` 的 tmux/local-binary manual resize smoke，以及 Linux 上按设计忽略的 Windows AltGr 测试。
- scoped `just fix -p codex-tui`、`just fmt`、`just fmt-check`、`git diff --check` 通过；无 `.snap.new` 或计划外生成物。

## 资源与边界

- 所有重型批次经共享 lock/watchdog 复用唯一 Plan 069 target，并逐命令设置 270/285/290GB 项目门和 Plan 092 临时 30GB Windows
  `C:` 门；每批前均确认真实 `/mnt/c` 余量、lock、user systemd/cgroup、active scope、进程、内存、swap 和 PSI。
- 首个聚焦尝试在测试前由 watchdog 以 `memory_full_psi_sustained_above_limit` 主动停止：final 125、payload 137、JUnit absent、
  `cleanup=none`。资源恢复后保留增量进度重跑通过；没有下调门限或清理 target。
- 正式成功批次均为 `stop=none / cleanup=none`。scoped fix 触及 270GB 告警但低于 285GB stop，且未执行清理。最终退出时项目
  `272354115584` bytes、target `212729303040` bytes、Windows `C:` 余量 `42414792704` bytes；canonical lock 可取得，无 active heavy
  scope 或 Cargo/rustc/nextest 进程，memory full PSI avg10 为 0。
- 未运行 full workspace、`--all-features`、Docker、真实 API/模型、训练、测评、发布或上传。Plan 090 既有未提交现场未读取内容且未改动；
  091、069 与其它 worktree 均未删除、迁移或清理。
- ignored/task-owned 证据位于 092 `.codex/build-watchdog/plan092-*`；共享构建资产位于既有 069 target；格式缓存位于
  `/tmp/plan092-uv-cache`。

当前为 `IMPLEMENTATION_COMPLETE / ACCEPTED / MAIN_INTEGRATION_PENDING`；主线集成完成事实将在集成后单独收口。
