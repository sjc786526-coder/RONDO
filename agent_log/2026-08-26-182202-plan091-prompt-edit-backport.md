# Plan 091 #37421 prompt-edit 回归窄适配

## 结果

- `ForkSessionForPromptEdit` 现在从已加载 turn snapshot 与当前 `ThreadEventStore` replay buffer 构造一次性只读 lookup 视图；不写回 store，
  不新增 transcript/history authority，也不改变既有 backtrack 裁决和持久协议。
- 投影只合并 prompt 定位所需的 `TurnStarted`、用户消息、review 边界与 `TurnCompleted` 元数据，按 turn/item ID 去重并保持归属、顺序和
  已重建 items。
- 端到端回归把被选 turn 从 snapshot 移入 buffer 后验证正确 fork-before、composer 文本/attachment 恢复、新线程不重复所选 turn，且源
  rollout 字节不变；单测覆盖 buffer-only completed/interrupted、snapshot/buffer 重叠、重复通知、orphan item 和 completion 元数据。

## 验证与资源

- 最终聚焦稳定轮：Nextest `14e30ee7-43ad-49ce-b828-9aad98605836`，20/20 passed、3423 skipped；watchdog
  `plan091-focused-stable/20260826-181608-1000-638389`，`stop=none cleanup=none`。
- scoped fix：`just fix -p codex-tui` 通过；watchdog `plan091-fix/20260826-181854-1000-668880`，`stop=none cleanup=none`。
  `just fmt`、`just fmt-check`、`git diff --check` 通过，无 snapshot 交付差异。
- 完整 `codex-tui` crate 额外批次未通过：3436 passed（1 flaky retry 后通过）、3 failed、4 skipped。失败为既有
  `next_replaces_the_page_and_transport_loss_retires_late_completion` fixture 缺 `setRootState`，以及同字段造成的两项 durable-query stale
  snapshot；相关文件相对 `HEAD` 无 Plan 091 差异，本任务未跨范围代修，生成的 `.snap.new` 已清理。
- 分页 fixture 初次连接失败由宿主代理截获 `127.0.0.1` fake WebSocket 导致；正式离线测试只在命令级设置
  `NO_PROXY=127.0.0.1,localhost`，单测重跑和最终稳定轮均通过，未改产品或全局代理配置。
- 所有重型批次均复用唯一 Plan 069 target，经共享 lock/watchdog，以命令级 270/285/290GB 门和用户临时授权的 30GB Windows `C:`
  停止线运行。退出时 `C:` 余量 `48,965,611,520` bytes、项目 `262,085,918,121` bytes、target `203,508,220,866` bytes；lock 可取得，
  无 Cargo/rustc/nextest 和活跃 RONDO build scope。
- 资源恢复前曾按合同只清理 069 target 中 6 个明确可再生 `debug/incremental` 目录，约 `5,031,600,128` bytes；未继续扩大清理。

## 边界

- 未运行 full workspace、`--all-features`、真实 API/模型、Docker、训练、测评、发布或上传；完整 crate 的 3 项基线失败不表述为通过。
- ignored/task-owned 证据位于 091 `.codex/build-watchdog/plan091-*`；复用并更新 ignored 的 069 Cargo target；格式工具缓存位于
  `/tmp/plan091-uv-cache`。
- 独立只读 code review 未发现高/中 correctness finding。当前为 `REVIEW_PENDING`；不合并、不 rebase、不推送、不归档或删除 worktree。
