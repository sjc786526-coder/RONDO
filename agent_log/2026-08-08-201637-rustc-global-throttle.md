# 跨入口 rustc 总并发兜底

在既有 `build.jobs = 6`、Nextest 执行并发、机器级构建互斥锁和 16 GiB cgroup 上限之外，
仓库根新增 Cargo `rustc-wrapper`：裸 Cargo、不同 agent 与不同 worktree 启动的 rustc 共用
6 个用户级槽，并在可用内存低于 3072 MiB 时暂缓新编译单元。

审查时修正了两处保护边界：信号量目录固定到当前用户的运行目录，不再随 `TMPDIR` 分裂；
`slots` / 内存水位先校验，运行目录异常时明确告警并 fail-open。文档明确该脚本只限制 rustc
总并发，正式重型构建的“同一时刻只能有一个”仍由 `with-build-lock.sh` 保证。

本批只做静态和轻量脚本验证：`git diff --check`、`bash -n`、关闭闸门直通、非法参数降级及
正常单进程获取槽均成功；未运行 Rust 编译、构建或测试。
