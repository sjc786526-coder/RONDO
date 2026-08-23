# Plan 058 可恢复中断交接

用户要求尽快安全中断并保留现场。执行者向正在运行的 supervised legacy musl build 发送 `SIGINT`；watchdog 停止
`rondo-build-1000-20260823030203-5464.scope`，summary 为 `wrapper_status=signal_INT`、`final_rc=130`。确认无残留
Cargo、rustc、rust-lld 或 build-lock 进程，worktree clean，HEAD 为
`9bdf51f516df46eb613810ef86e5a4cfb5683875`。

保留的增量 target：
`eval-data/build/rondo-9bdf51f516df46eb613810ef86e5a4cfb5683875-x86_64-unknown-linux-musl/`，中断时约
`7,180,648,448` bytes。中断 metrics 保存在
`eval-data/build-metrics/plan058-formal-v2-legacy-9bdf51f/20260823-030203-1000-5464/`。恢复时复用 target、另建
新的 metrics root 后重新运行同一 clean commit 的完整 legacy build；旧 metrics root 只能作中断证据，因为
BinaryManifest build proof 要求其绑定的 metrics root 恰有一个成功 summary。

尚未 prepare/publish `9bdf51f` binary、companion 或 runtime bundle，尚未初始化新 formal identity，尚未发送
formal API 请求。最近关闭的 task budget 状态为累计 `6.533427 USD`、reserved `0`；diagnostic-v2 已
`diagnostic_complete`，其后没有费用。未清理 target、metrics、campaign 或其他资产。
