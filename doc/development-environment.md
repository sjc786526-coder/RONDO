# RONDO 开发环境基线

最后核对时间：2026-08-08（Asia/Shanghai）

适用工作区：`/home/sjc/desktop/RONDO`，主要源码位于 `mydev/`。

本文记录当前 WSL 开发机的实际环境、版本固定方式、安装位置、验证结果和已知边界。文中不记录代理凭据、API Key 或其他密钥。

## 0、本机硬件环境

CPU i9-13980HX
GPU RTX4060 laptop
总RAM 40GB，WSL分配到27GB，swap 10GB

## 1. 平台与网络代理

### 1.1 平台

- Windows 主机运行 Docker Desktop 和 Clash Verge。
- WSL 发行版为 Ubuntu 24.04，内核为 Microsoft WSL2 `6.6.87.2`，架构为 `x86_64`。
- Windows 的 `C:\Users\35283\.wslconfig` 使用以下 WSL2 网络配置：

  ```ini
  [wsl2]
  networkingMode=mirrored
  dnsTunneling=true
  autoProxy=true
  firewall=true
  ```

### 1.2 统一代理

交互式 Bash 在 `~/.bashrc` 中统一配置 Clash Verge：

```bash
export http_proxy=http://127.0.0.1:7897
export https_proxy=http://127.0.0.1:7897
export all_proxy=socks5h://127.0.0.1:7897
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export ALL_PROXY="$all_proxy"
```

APT、npm/pnpm、Cargo/Rustup 和 uv 的安装命令也显式指定了 `127.0.0.1:7897`，避免 `sudo` 丢弃代理变量或工具采用不同的代理发现机制。

Codex 的 `~/.codex/config.toml` 已启用 workspace-write 网络访问和 network proxy，并允许上游代理。域名策略采用开发所需的范围白名单，包括 Ubuntu、Rust/Cargo、npm、PyPI、GitHub 和 OpenAI 端点，没有使用全域 `*` 放行。

注意：Codex 沙箱进程可能注入临时的本地代理端口。这不代表 `~/.bashrc` 中的 `7897` 配置失效；新开的普通 WSL 交互式 shell 仍应使用 `127.0.0.1:7897`。任意程序如果主动忽略代理变量，当前配置不会通过系统防火墙强制劫持其流量。

## 2. git-stats 与提交钩子

### 2.1 安装状态

| 项目         | 当前状态                                      |
| ------------ | --------------------------------------------- |
| 固定版本     | `git-stats 3.5.0`                             |
| 安装方式     | `npm install --global git-stats@3.5.0`        |
| 可执行文件   | `~/.nvm/versions/node/v24.14.1/bin/git-stats` |
| 发布包大小   | 约 14.7 KB 压缩包、63.4 KB 解包后             |
| 默认数据文件 | `~/.git-stats`                                |
| 可选配置文件 | `~/.git-stats-config.js`                      |

安装包的 `postinstall` 只负责把旧版 `~/.git-stats` 数据迁移到 2.0.0 之后的 JSON 结构，不下载额外二进制，也不修改 Git 配置。npm 安装了 100 个 JavaScript 包；主体很小，但依赖树不是单文件工具。

安装后没有人为创建测试提交，也没有调用 `--record` 伪造记录。`~/.git-stats` 已由后续的首次真实仓库修复提交创建，当前记录可正常匹配该提交哈希；没有创建可选的 `~/.git-stats-config.js`，因此继续使用默认存储配置。

### 2.2 实际统计内容

钩子计算并传给 `git-stats --record` 的字段是：

- 提交时间：`git log -1 --format=%cI`
- `origin` 仓库 URL：`git config --get remote.origin.url`
- 提交哈希：`git rev-parse HEAD`

`git-stats 3.5.0` 的实际 `record()` 实现只把日期和提交哈希持久化为类似下面的结构：

```json
{
  "commits": {
    "YYYY-MM-DD": {
      "commit-hash": 1
    }
  }
}
```

仓库 URL 在该版本中会被接收和校验，但不会写入 `~/.git-stats`。工具也不会保存代码、diff、提交消息或文件名，更不会自动上传统计数据。主要用途是生成本地 GitHub 风格提交日历。

### 2.3 钩子状态

当前仓库和全局 Git 模板都安装了相同的 `post-commit` 钩子：

- 当前仓库：`.git/hooks/post-commit`
- 全局模板：`~/.git-templates/hooks/post-commit`
- Git 模板配置：`init.templateDir=~/.git-templates`

关键防护如下：

```sh
# Record commit date, repository URL, and commit hash in local git-stats data
command -v git-stats >/dev/null 2>&1 || exit 0
```

因此以后即使切换 NVM Node 版本或卸载 `git-stats`，提交钩子也会静默退出，不会再产生 `git-stats: not found`。两个钩子均保持 `0755` 权限并通过 `sh -n` 语法检查。按约定没有创建测试提交；钩子已由独立的 Cargo 锁文件修复提交完成真实验证。

## 3. Rust 开发环境

### 3.1 Rustup 与固定工具链

仓库的 `mydev/codex-rs/rust-toolchain.toml` 固定 Rust `1.95.0`。当前安装为：

| 组件            | 版本或状态                      |
| --------------- | ------------------------------- |
| Rustup          | `1.29.0`，minimal profile       |
| rustc           | `1.95.0 (59807616e 2026-04-14)` |
| cargo           | `1.95.0 (f2d3ce0bd 2026-03-21)` |
| rustfmt         | `1.9.0-stable`                  |
| clippy          | `0.1.95`                        |
| rust-src        | 已安装                          |
| GNU host target | `x86_64-unknown-linux-gnu`      |
| musl target     | `x86_64-unknown-linux-musl`     |

Rustup 数据位于 `~/.rustup`，Cargo 工具和缓存位于 `~/.cargo`。`~/.profile` 和 `~/.bashrc` 都会加载 `~/.cargo/env`。非交互式 shell 如果找不到 Cargo，可显式执行：

```bash
. "$HOME/.cargo/env"
```

### 3.2 Cargo 辅助工具

以下工具均通过 Rust `1.95.0` 执行 `cargo install --locked` 安装：

| 工具          | 当前版本  |
| ------------- | --------- |
| just          | `1.58.0`  |
| DotSlash      | `0.5.7`   |
| cargo-nextest | `0.9.140` |
| cargo-insta   | `1.48.0`  |

### 3.3 系统构建依赖

APT 已安装并复核以下开发包：

| 包               | Ubuntu 包版本            |
| ---------------- | ------------------------ |
| `pkg-config`     | `1.8.1-2build1`          |
| `libcap-dev`     | `1:2.66-5ubuntu2.4`      |
| `clang`          | `1:18.0-59~exp2`         |
| `musl-tools`     | `1.2.4-2`                |
| `libssl-dev`     | `3.0.13-0ubuntu3.12`     |
| `libsqlite3-dev` | `3.45.1-1ubuntu2.7`      |
| `zstd`           | `1.5.5+dfsg2-2build1.1`  |
| `jq`             | `1.7.1-3ubuntu0.24.04.2` |
| `ripgrep`        | `14.1.0-1`               |
| `fd-find`        | `9.0.0-1`                |
| `fzf`            | `0.44.1-1ubuntu0.3`      |

已有依赖保留并复核：`build-essential 12.10ubuntu1`、CMake `3.28.3`、Git `2.43.0`、Bubblewrap `0.9.0`。

### 3.4 编译验证与锁文件一致性

`cargo check -p codex-cli` 已成功完成，证明 Rust 编译器、Clang、OpenSSL、SQLite、Git 依赖和工作区主要 crate 能协同工作。首次检查约耗时 2 分钟，下载依赖后 `mydev/codex-rs/target` 当前约占 4.7 GB。

上游基线已从 `0.146.0` 更新到已发布的 `0.146.1`；`Cargo.toml` 和 `Cargo.lock` 的 132 个本地工作区包版本均保持为 `0.146.1`。该同步由仓库固定的 Cargo `1.95.0` 完成，第三方依赖版本、source 和 checksum 未变。

差异审查确认没有第三方包版本、依赖列表、source 或 checksum 变化，因此外部依赖图没有变化，不需要刷新 `MODULE.bazel.lock`。以下锁定验证均已通过：

```bash
cd /home/sjc/desktop/RONDO/mydev/codex-rs
cargo metadata --locked --offline --format-version 1 --no-deps
cargo check --locked --offline -p codex-cli
```

后续日常构建和 CI 可以使用 `--locked`，普通 Cargo 构建也不会再因为工作区版本不一致而弄脏 `Cargo.lock`。

### 3.5 构建与测试并发上限（OOM 防护）

2026-08-08 的一次全量测试把整个 WSL 实例打崩：`cargo nextest` 按逻辑 CPU 数（32）并行拉起
`rustc` / `rust-lld`，编译与链接阶段的内存峰值吃光内存和 swap，内核 OOM Killer 在 `Free swap = 0kB`
时开始杀进程，连 `systemd`、`sd-pam` 一起被 SIGKILL，于是 VS Code Remote 报 WebSocket 1006、
所有 agent 会话一并丢失。根因是**并发度超过内存承载能力**，不是 CPU 不足，也不是 VS Code 或 WSL 网络问题。

现在有四道固化在仓库里的闸门，不依赖人或 AI 记忆：

| 闸门 | 位置 | 作用维度 |
| ---- | ---- | -------- |
| `[build] jobs = 6` | 仓库根 `.cargo/config.toml` | 编译/链接阶段并发的 `rustc`、`rust-lld` 数量 |
| `test-threads = 10` | `mydev/codex-rs/.config/nextest.toml` 的 `[profile.default]` | 测试执行阶段并发的测试进程数量 |
| 全局互斥锁 | `mydev/scripts/with-build-lock.sh` | 同一时刻只允许一个重量级构建 |
| **cgroup 硬内存上限 16 GiB** | 同上脚本，`systemd-run --user --scope` | 兜底：超限只杀构建，不杀会话 |

前三道是**估算性**防护（靠把并发压到内存装得下），第四道是**结构性**防护（靠内核强制隔离）。
前者可能算错，后者不依赖算得准不准——这是唯一一道不靠估算的闸门。

#### 取值依据（2026-08-08 实测）

在 `jobs = 8` 下跑了一次全 workspace 测试二进制构建（`cargo nextest list --workspace`，
只编译链接不执行测试），每 2 秒采样一次 `/proc/meminfo`，共 217 个样本、约 11 分钟。
**这次构建是跑完的**——所有 workspace crate 和全部测试二进制都完成了链接，nextest 已进入枚举
约 1.3 万个测试的阶段，所以下面的峰值是一次完整构建的峰值，不是被截断的中间值：

| 指标 | 实测值 |
| ---- | ------ |
| 峰值已用内存 | 18.7 GB |
| 峰值时刻的并发情况 | `rustc = 8`、`rust-lld = 8`（8 个槽同时链接） |
| 最低可用内存 | 9.6 GB |
| 空载基线 | 约 4.8 GB（VS Code Server + 各 agent 会话） |
| 峰值期间 swap | 被动用约 0.9 GB |

峰值出现在**所有槽同时链接**的瞬间，链接是内存最贵的一步。由此得到线性估算模型：

```text
峰值已用内存 ≈ 4.8 GB（基线） + 1.74 GB × jobs
```

WSL 现分配 26 GB，按 25 GB 保守估算、且不把 10 GB swap 当作日常可用区域，`jobs = 6`
预计峰值约 15 GB，给页缓存和并行 agent 会话留出余量。以后要调这个值，按上面的公式算，
不要凭感觉试。

看任务管理器时注意两点：构建期间"内存占用 98%"里绝大部分是 `buff/cache`（写 `target/` 产生的
页缓存，可回收，不代表压力）；真正的压力信号是 `available` 和 **swap 是否被动用**——本次 swap
被吃掉 0.9 GB，这是把 `jobs` 从 8 降到 6 的直接理由。磁盘 100% 同样来自 `target/` 的写入
（当前约 16 GB），不致命；如果它成为瓶颈，下一个可用杠杆是把 `[profile.dev]` 的
`debug = "limited"` 降到 `"line-tables-only"`（backtrace 保留文件行号，丢失变量信息），
但这会牺牲调试体验，目前没有动。

#### 第四道闸门：cgroup 硬上限

`with-build-lock.sh` 拿到锁之后，把构建放进一个 systemd 临时 scope 里跑：

```bash
systemd-run --user --scope -p MemoryMax=16G -p MemorySwapMax=2G -- <构建命令>
```

要点是**上次的灾难不是"构建挂了"，而是全局 OOM Killer 挑中了 `systemd` 和 `sd-pam`，
把整个登录会话、VS Code Server 和所有 agent 一起带走**。放进 scope 之后，内核只会在这个 scope
内部杀进程：构建以退出码 137 失败，机器和会话活着，重跑即可。

取值：`jobs = 6` 时构建自身的匿名内存约 10.4 GB（`1.74 GB × 6`，基线不算在内，因为基线在 scope
外面），16 GiB 给了约 1.5 倍余量，剩下的额度留给构建自己的页缓存。`MemorySwapMax=2G` 保证构建
最多只能碰 2 GB swap，不会把 10 GB 交换区抖光。scope 内的页缓存超额时内核先回收缓存、再动 swap、
最后才杀进程，所以正常构建不会被误杀。

本机具备条件已验证：PID 1 是 `systemd`、cgroup v2、`memory` 控制器已委派给 user slice。
脚本每次运行前会探测一次，探测失败就降级为"不加内存上限"继续跑，而不是拒绝构建。

```bash
RONDO_BUILD_MEMORY_MAX=20G just test  # 单次放宽
RONDO_BUILD_SWAP_MAX=4G just test     # 单次放宽 swap
RONDO_BUILD_CGROUP=0 just test        # 单次关掉硬上限
```

被杀时脚本会打印明确提示，不会只留一个莫名其妙的 `Killed`。

三点说明：

- **两个维度必须分别限制，但吃内存的是编译阶段。** nextest 是先全量构建、再执行测试，两个阶段
  不重叠，所以峰值由 `build.jobs` 决定，它才是关键那一个。`test-threads` 是保守取值，执行阶段的
  峰值尚未实测；如果它从来不是瓶颈，可以按实测结果调回去。
- **`.cargo/config.toml` 放在仓库根而不是 `mydev/codex-rs/`。** cargo 会从 cwd 逐级向上合并配置，
  所以这一份同时覆盖 `mydev/codex-rs`、`mydev/tools`、`codex-source-code` 和 `.claude/worktrees/`
  下的全部构建，换 worktree 不会失效；同时不改动上游 codex 自带的配置文件，基线升级时不会冲突。
- **锁是机器级而不是 worktree 级。** 单次构建限到 8 jobs，但主工作区一个 agent、worktree 里另一个
  agent 各跑一次，叠加又回到 16 jobs 的危险区。`just test` / `just clippy` / `just fix`（Unix 分支）
  都走 `with-build-lock.sh`，等待时会打印提示，不会看起来像卡死。锁由被包裹的进程本身持有，
  进程退出/崩溃/被杀都自动释放，没有陈旧锁问题。

覆盖方式：

```bash
cargo build -j 16                  # 命令行 -j 优先于 .cargo/config.toml
CARGO_BUILD_JOBS=16 just test      # 环境变量次之
cargo nextest run --test-threads 4 # 单次收紧测试并发
RONDO_BUILD_LOCK=0 just test       # 明确知道自己在做什么时跳过互斥锁
```

单个重测试太吃内存时，**不要继续调低全局 `test-threads`**，那会让所有轻量测试一起变慢。用 nextest 的
按测试资源控制：`.config/nextest.toml` 里已有 `test-groups`（`app_server_integration` 等用 `max-threads`
限制同类重测试的并发数），需要更细的权重时用 `threads-required` 让单个重测试占多个线程槽。

Windows 分支的 `just` 配方保持上游行为（不加锁），因为本项目的开发机是 WSL。

已知的未覆盖面（互斥锁和 cgroup 上限只作用于 `just test` / `clippy` / `fix` 的 Unix 分支，
`jobs = 6` 则对所有 cargo 调用生效）：

- **直接敲 `cargo build` / `check` / `nextest` 不走锁也不进 scope。** 并发上限仍在（6 jobs），
  但两个 agent 同时直接调 cargo 就是 12 jobs，且都没有硬上限兜底。`mydev/AGENTS.md` 已要求走
  `just test`，这是纪律约束而非机制约束。
- **`just bench` 走的是 `cargo bench --workspace`，没有包进互斥锁和 scope**，因为它跨平台且极少运行。
  需要跑基准时确认没有别的构建在跑。
- **Bazel 路径没有加闸。** `mydev/.bazelrc` 的 `common --jobs=30` 仍是上游值。Bazel 本身按
  `--local_resources`（默认 `HOST_RAM*0.67`）做内存感知调度，不像 cargo 那样只按 CPU 数硬拉并发，
  风险低一档；且本机尚未安装 Bazel（见 §8）。等真正引入 Bazel 时再实测并决定是否收紧，这里不做未经验证的改动。
- **16 GiB 这个数字本身还没在真实全量构建里验过**，是按 `1.74 GB × 6` + 1.5 倍余量推的。
  首次全量构建时留意有没有出现退出码 137；出现了先看是不是页缓存被持续回收，再决定上调还是降 `jobs`。

## 4. Node 与 pnpm

| 项目     | 当前状态                                                  |
| -------- | --------------------------------------------------------- |
| Node.js  | `v24.14.1`，满足仓库要求 `>=22`                           |
| npm      | `11.11.0`                                                 |
| Corepack | `0.34.6`                                                  |
| pnpm     | 精确固定为 `10.33.0`                                      |
| 固定来源 | `mydev/package.json` 的 `packageManager` 字段及完整性摘要 |
| 依赖目录 | `mydev/node_modules`，约 145 MB                           |

已执行：

```bash
corepack prepare pnpm@10.33.0 --activate
corepack enable pnpm
cd /home/sjc/desktop/RONDO/mydev
pnpm install --frozen-lockfile
```

冻结安装覆盖 4 个 pnpm workspace 项目，共安装 529 个包。TypeScript SDK 的 `prepare` 阶段成功完成 ESM、source map 和类型声明构建。`pnpm-lock.yaml` 未被修改。pnpm 显示的新主版本提示不应直接采纳；应继续遵循仓库的 `packageManager` 固定版本。

Corepack shim 和 `git-stats` 都位于当前 NVM Node `v24.14.1` 的目录。以后切换或重装 Node 版本时，需要重新运行 `corepack enable pnpm`，并检查 `git-stats --version` 是否仍可用。

## 5. Python 辅助脚本环境

| 项目        | 当前状态                                    |
| ----------- | ------------------------------------------- |
| uv          | `0.11.7`，位于 `~/.local/bin/uv`            |
| 项目 Python | Ubuntu `/usr/bin/python3.12`，版本 `3.12.3` |
| 虚拟环境    | `mydev/scripts/.venv`，约 28 MB             |
| 锁文件      | `mydev/scripts/uv.lock`                     |
| 当前依赖    | `ruff 0.15.13`                              |

最终同步命令为：

```bash
cd /home/sjc/desktop/RONDO/mydev/scripts
uv sync --frozen --python /usr/bin/python3
```

虽然主机仍安装了 Miniconda，且 Bash 中保留其初始化配置，但本项目 `.venv` 已明确重建为基于 Ubuntu Python 3.12，不使用 Conda 环境，也不依赖 Miniconda 的 Python。`uv.lock` 未被修改。

## 6. 常用 CLI 与 PATH 优先级

除了 APT 版本，当前 PATH 中还有部分其他工具提供方：

- `fd` 当前来自 `~/.kimi-code/bin/fd`，版本 `10.4.2`；Ubuntu 的命令名仍是 `/usr/bin/fdfind`，版本 `9.0.0`。
- `rg` 当前优先使用 Codex npm 包附带的版本 `15.2.0`；APT 的 `/usr/bin/rg` 为 `14.1.0`。
- 普通 shell 可能优先看到 Miniconda 的 `zstd`；APT 版本仍可通过 `/usr/bin/zstd` 使用。
- `jq`、`fzf`、`clang`、`musl-gcc`、`pkg-config`、CMake、Git 和 Bubblewrap 均可直接调用。

这种 PATH 覆盖目前不影响仓库构建，但排查版本差异时应同时检查 `command -v <tool>` 和工具自身的 `--version`。

## 7. Docker Desktop / WSL 集成

Docker CLI 位于 `/usr/bin/docker`，默认 context 为 `default`。在 Codex 沙箱外对 Docker Desktop daemon 的只读握手已成功：

```text
client=29.6.2 server=29.6.2 api=1.55 os=linux/amd64
```

这证明 Docker Desktop 的 WSL 集成和 Linux daemon 当前可用。Codex 的 workspace-write 沙箱内直接访问 `/var/run/docker.sock` 可能显示 `permission denied`；沙箱外同一 WSL 环境连接成功，因此这不是 Docker Desktop 安装故障。需要运行 Docker 测试时，应明确允许对应 Docker 命令在沙箱外执行。

本次只做 daemon 握手，没有拉取镜像、创建容器或运行完整 Docker 测试套件。

## 8. 当前未安装或未执行的重型工具

以下项目不在本次批准的阶段二至四范围内，当前没有安装或没有执行：

- Bazel / Bazelisk 9 及其构建缓存
- Docker devcontainer 环境
- `cargo-dylint`、`dylint-link`、`cargo-shear`
- 额外的跨平台 Rust targets
- 工作区完整 `just test`、Bazel 测试或完整 Docker 测试

关于最后一项：完整 `just test` 已于 2026-08-08 在 §3.5 的闸门下跑完，**无 OOM**：
13135 项运行，13062 通过 / 73 失败 / 23 跳过 / 25 flaky，执行阶段 346.7 s，全程已用内存约 3.8 GB、
scope 内峰值约 5 GB、swap 未增长。73 项失败已定性为宿主环境与上游基线原因（版本号占位 25 项、
Clash fake-IP DNS 11 项、其余 37 项），与并发配置和 RONDO 改动均无关，详见
`agent_log/2026-08-08-031500-full-test-backfill.md`。**不声称全绿。**
Bazel 门禁与 `just argument-comment-lint` 仍未运行。

这些工具只在对应任务真正需要时安装，避免提前引入较大的下载、构建时间和缓存占用。DotSlash 已具备，可在仓库命令需要时获取其固定的预构建辅助工具。

## 9. 快速健康检查

```bash
. "$HOME/.cargo/env"

git-stats --version
sh -n .git/hooks/post-commit
sh -n ~/.git-templates/hooks/post-commit

rustc --version
cargo --version
rustup component list --installed
rustup target list --installed
just --version
dotslash --version
cargo nextest --version
cargo insta --version

cd /home/sjc/desktop/RONDO/mydev/codex-rs
cargo check --locked -p codex-cli

cd /home/sjc/desktop/RONDO/mydev
pnpm --version
pnpm install --frozen-lockfile

cd scripts
uv sync --frozen --python /usr/bin/python3
.venv/bin/python --version
.venv/bin/ruff --version

docker version
git -C /home/sjc/desktop/RONDO status --short --branch
```

环境配置和锁文件修复提交完成后，预期 Git 状态为干净的 `main...origin/main`；钩子位于 `.git/` 和用户模板目录，不属于仓库跟踪文件。
