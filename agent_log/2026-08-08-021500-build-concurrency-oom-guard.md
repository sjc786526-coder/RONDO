# 构建/测试并发上限：OOM 防护

起因：2026-08-08 00:04 全量测试触发 WSL2 全局 OOM，内核在 `Free swap = 0kB` 时杀掉 `systemd`、
`sd-pam`，连带 VS Code Remote（WebSocket 1006）和所有 agent 会话一起丢失。根因是 cargo 按逻辑
CPU 数（32）无上限并发拉起 `rustc` / `rust-lld`，不是 CPU 不足，也不是 VS Code 或 WSL 网络问题。

## 实质改动

**闸门一：编译并发**

- 新增仓库根 `.cargo/config.toml`：`[build] jobs = 6`。
- 放在仓库根而不是 `mydev/codex-rs/.cargo/config.toml`：cargo 从 cwd 逐级向上合并配置，一份即可覆盖
  `mydev/codex-rs`、`mydev/tools`、`codex-source-code` 和 `.claude/worktrees/` 下的全部构建，换
  worktree 不失效；同时不碰上游 codex 自带的配置文件，基线升级不会冲突。

**闸门二：测试执行并发**

- `mydev/codex-rs/.config/nextest.toml` 的 `[profile.default]` 加 `test-threads = 10`。
  `[profile.local]`（`just test` 用的那个）继承 default，两条路径都被覆盖。

**闸门三、四：跨 worktree / 跨 agent 互斥 + cgroup 硬内存上限**

- 新增 `mydev/scripts/with-build-lock.sh`：`flock` 机器级互斥锁 + `exec`，锁由被包裹的进程本身持有，
  退出/崩溃/被杀都自动释放，没有陈旧锁问题；抢不到锁时打印等待提示，避免看起来像卡死。
  逃生口 `RONDO_BUILD_LOCK=<path>` / `RONDO_BUILD_LOCK=0`。
- 同一脚本在拿到锁之后把构建放进 `systemd-run --user --scope -p MemoryMax=16G -p MemorySwapMax=2G`。
  这是唯一一道**不依赖估算**的闸门：上次的灾难不是构建挂了，而是全局 OOM Killer 挑中 `systemd` /
  `sd-pam` 把整个会话带走；放进 scope 后内核只在 scope 内部杀进程，构建以 137 失败、机器活着。
  取值依据：`jobs = 6` 时构建自身匿名内存约 10.4 GB（基线在 scope 外不计），16 GiB 约 1.5 倍余量，
  余下额度留给构建的页缓存。运行前探测一次，探测失败降级为不加上限继续跑，而不是拒绝构建。
  逃生口 `RONDO_BUILD_MEMORY_MAX` / `RONDO_BUILD_SWAP_MAX` / `RONDO_BUILD_CGROUP=0`。
- `mydev/justfile`：`test` / `clippy` / `fix` 的 Unix 分支走该包装脚本。`clippy` / `fix` 因此拆成
  `[unix]` / `[windows]` 两个配方，Windows 分支保持上游行为。

**顺带修复（阻塞验证，非本任务范围内的既有缺陷）**

- `thread-manager-sample/src/main.rs`：`Config` 初始化补上 `guardian_model_config` /
  `guardian_reasoning_effort_config` / `guardian_evidence_dir` 三个字段（均为 `None`）。
  这是 95d3358 引入 `Config` 新字段时的漏网 crate——上一批次因 OOM 风险没跑全量构建，
  所以 `main` 上其实一直编译不过。

**文档**

- `doc/development-environment.md` 新增 §3.5，记录三道闸门、实测数据、取值公式和两处未覆盖面；
  §8 如实说明"跑过全量构建、没跑过全量测试执行"。
- `mydev/AGENTS.md` 测试小节加第 4 条：不得为了跑快而抬高上限或绕过互斥锁。

## 疑难问题与处理

1. **配置放哪里才不会随 worktree 失效**。用 `jobs = 0`（cargo 会报 `jobs may not be 0`）分别在
   `mydev/codex-rs` 和 `.claude/worktrees/001-*/mydev/codex-rs` 下验证根配置确实被逐级合并读到，
   确认后再写回真实值。
2. **锁必须是机器级**。per-worktree 锁挡不住"主工作区一个 agent + worktree 里另一个 agent"的场景，
   各自守 6 jobs 叠加又回到危险区。
3. **`just test --no-run` 不可用**：nextest 的 `--no-run` 与 `--no-fail-fast` 互斥。验证构建阶段
   改用 `cargo nextest list --workspace`（编译链接全部测试二进制，但不执行）。
4. **第一次取 8 偏乐观**。见下。

## 验收结果

- 互斥锁：并发两次调用，后者打印等待提示并阻塞 3.5 s 直到前者的 4 s 任务结束；退出码透传（42）；
  `RONDO_BUILD_LOCK=0` 旁路生效；无参数报错退出 1。加入 scope 后重测，互斥仍成立（等待 4.07 s），
  说明 flock 的 fd 9 能穿透 `systemd-run --scope`。
- cgroup 上限：`systemd-run --user --scope` 退出码透传（42）；`-p MemoryMax` 确实落到
  `memory.max`（实测 16 GiB = 17179869184、`memory.swap.max` = 2 GiB）；在 256 M / swap 0 的 scope
  里申请 1.5 G 内存被 SIGKILL（退出 137），**swap 消耗 0 MB，宿主 `systemctl --user is-system-running`
  仍为 `running`、可用内存 24 GB**，确认只杀壳内、不波及会话；脚本对 137 打印了定位提示。
- 端到端：`just test -p codex-arg0` 经锁 + scope 跑通，nextest profile 为 `local`，7/7 通过。
- `just --list` / `just --dump`：justfile 解析正常，`test` / `clippy` / `fix` 的 unix / windows
  两份配方都正确展开。
- nextest 配置：故意插入未知键会得到 `ignoring unknown configuration key: profile.default.bogus-key-check`
  的告警，而 `test-threads` 无告警——说明该键在 profile 层被识别。配置在编译开始前即被解析。
- **`jobs = 8` 下的全 workspace 测试二进制构建实测**（217 个样本 / 约 11 分钟，每 2 秒采一次）。
  这次构建**跑完了**：全部 workspace crate 与测试二进制完成链接，nextest 已进入枚举约 1.3 万个
  测试的阶段，因此峰值是完整构建的峰值而非截断值。峰值已用内存 18.7 GB，出现在 t+259 s、
  `rustc = 8` 且 `rust-lld = 8`（8 个槽同时链接）时；最低可用 9.6 GB；空载基线约 4.8 GB；
  swap 在 11 分钟里被逐步吃掉 0.9 GB（t+100 s 首次明显下降，此时已用 16.2 GB），属于持续性轻压，
  不是断崖。得出 `峰值 ≈ 4.8 GB + 1.74 GB × jobs`，据此把 `jobs` 从 8 下调到 6（预计峰值约 15 GB），
  匹配 WSL 调整后 26 GB / 按 25 GB 保守估算、且不把 swap 计入可用区域的要求。
- **未运行**：完整 `just test` 的测试**执行**阶段（上面那次在枚举阶段按用户要求停止）。
  `jobs = 6` 的峰值是按公式推算而非实测。**不声称全量测试通过**。
- **cgroup 上限的实战值未验**：16 GiB 是按 `1.74 GB × 6` 推算 + 1.5 倍余量给的，还没在真实全量
  构建里跑过，不排除需要上调（页缓存被持续回收会拖慢 I/O）或下调。首次全量构建时留意是否出现 137。
- 未改 `mydev/.bazelrc` 的 `common --jobs=30`：本机未装 Bazel，且 Bazel 自带 `--local_resources`
  内存感知调度，风险低一档，留待真正引入 Bazel 时实测再定，不做未经验证的改动。
- 全程离线，未调用真实模型 API。
