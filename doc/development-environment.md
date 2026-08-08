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

当前源码基线为 Codex CLI `v0.147.0`，来自上游 tag `rust-v0.147.0`（commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）。纯净只读快照 `codex-source-code/` 保持官方原样：
detached HEAD、工作区干净，`Cargo.toml` 的 workspace 版本为 `0.147.0`，但官方 `Cargo.lock`
仍将 135 个无 registry source 的本地 workspace package 写作 `0.0.0`。RONDO 产品树
`mydev/codex-rs/Cargo.lock` 为支持 `--locked` 构建，才把这 135 项机械规范化为 `0.147.0`；
相对纯净 `v0.147.0` 上游锁文件，产品树没有其他差异。新增的 workspace member 为
`app-server-protocol-noop-macros`、`code-mode-runtime`、`utils/audio`。

这次不是只改本地包版本：上游实质更新了 `Cargo.lock`、`MODULE.bazel.lock` 与
`pnpm-lock.yaml`中的第三方依赖图。旧基线下的"第三方依赖未变，无需刷新 Bazel lock"
结论不再适用。

基线升级期间在与产品源码隔离的 scratch source 上完成了一次上游 `v0.147.0`
`cargo build --workspace --locked` 与全量 `just test --test-threads 10`；为使官方 tag 可被
`--locked` 构建，scratch lock 中上游保留的 135 个 `0.0.0` 本地包条目被机械规范化为
`0.147.0`。该结果证明的是**原始上游基线与当前工具链**，不是 RONDO 合入改动后的
构建或 P0 验收证据。本次文档适配按要求未构建、未编译、未运行测试。

### 3.5 构建与测试并发上限（OOM 防护）

2026-08-08 的一次全量测试把整个 WSL 实例打崩：`cargo nextest` 按逻辑 CPU 数（32）并行拉起
`rustc` / `rust-lld`，编译与链接阶段的内存峰值吃光内存和 swap，内核 OOM Killer 在 `Free swap = 0kB`
时开始杀进程，连 `systemd`、`sd-pam` 一起被 SIGKILL，于是 VS Code Remote 报 WebSocket 1006、
所有 agent 会话一并丢失。根因是**并发度超过内存承载能力**，不是 CPU 不足，也不是 VS Code 或 WSL 网络问题。

提交 `1001929` 已保留前四层与旧 cgroup 保护；`v0.147.0` 升级工作树正依据本次校准把第五层
收口为 fail-closed watchdog：

| 闸门 | 位置 | 作用维度 |
| ---- | ---- | -------- |
| `[build] jobs = 6` | 仓库根 `.cargo/config.toml` | 编译/链接阶段并发的 `rustc`、`rust-lld` 数量 |
| `test-threads = 10` | `mydev/codex-rs/.config/nextest.toml` 的 `[profile.default]` | 测试执行阶段并发的测试进程数量 |
| rustc 总并发槽 = 6 | 仓库根 `.cargo/rustc-throttle.sh` | 所有 Cargo 入口、agent 与 worktree 共用同一组 rustc 槽 |
| 全局互斥锁 | `mydev/scripts/with-build-lock.sh` | 同一时刻只允许一个重量级构建 |
| fail-closed cgroup + watchdog（升级树待提交） | 同上脚本，`systemd-run --user --scope` | 限制内存/swap，监视磁盘、PSI 与外部构建，越界只终止构建 |

jobs、test-threads 与 rustc 槽限制并发；机器级 flock 阻止两个受支持的 `just` 重型入口同时运行。
下文 watchdog 数值与语义是 0.147 升级树当前的**待收口契约**；在其提交并合入前，不把它写成
产品树已验收能力。目标实现默认 fail-closed：找不到安全运行目录、systemd/cgroup 或关键计数器时
拒绝启动重型构建，不再静默降级为无上限运行。

#### `v0.147.0` 校准证据（2026-08-08）

原始上游 `v0.147.0` 的 scratch workspace build 完成，随后全量 nextest 完整结束：

- 14,065 项运行，13,981 通过，83 失败，1 超时，23 跳过，31 项首轮失败后重试通过。
- 项目峰值为 127,422,697,472 bytes，其中 Cargo target 最终为 126,174,883,840 bytes。
- cgroup 总内存采样峰值为 17,637,695,488 bytes；匿名内存峰值为 8,352,325,632 bytes，
  匿名内存加内核不可回收部分峰值为 8,620,105,728 bytes。
- swap 峰值 22,200,320 bytes，cgroup/host `full avg10` PSI 峰值分别为 0.56% / 0.80%。

`jobs = 6` 沿用旧基线校准；本轮验证了它在 0.147 全量负载下可用，没有重新比较并发档位。

这次结果推翻了"只看 `memory.current` 达到某个值就停"的旧思路：大型 Rust 构建的
`memory.current` 含大量可回收文件缓存。升级树目标脚本因此综合监控不可回收内存、swap、
host `MemAvailable`、PSI 和磁盘余量。

#### 第四、五道闸门：全局互斥与资源 watchdog（升级树待收口）

升级树中的 `with-build-lock.sh` 先取得机器级锁、拒绝已经存在的外部 Cargo/rustc/nextest 进程，再把构建放进
systemd 临时 scope。`v0.147.0` 校准后的默认 cgroup 配额是 `MemoryHigh=19G`、
`MemoryMax=21G`、`MemorySwapMax=5G`。项目目录在 180/195/200 GB 分别告警、主动停止、触及
绝对上限，文件系统至少保留 50 GB；其余停止条件综合不可回收内存、swap、宿主可用内存、PSI
与 scope 外构建进程，确切默认值以脚本为准。启动前发现外部构建返回 72，运行中主动停止返回 125；
若内核仍在 scope 内触发 OOM，构建返回 137，但机器、VS Code 与 agent 会话应继续存活。逐秒指标与摘要写入当前 worktree 的
`.codex/build-watchdog/`，不作为仓库交付物。

本机已具备 systemd、cgroup v2 与 user slice memory controller。脚本默认 fail-closed：锁、scope、
资源计数器或安全运行目录不可用时拒绝启动重型构建。只有明确设置
`RONDO_BUILD_WATCHDOG=0` 才关闭 cgroup/watchdog；机器级锁仍保留。阈值可以通过脚本列出的
`RONDO_BUILD_*` 环境变量做单次调整，必须结合监控结果，而不是凭估算放宽。

三点说明：

- **两个维度必须分别限制，但吃内存的是编译阶段。** nextest 是先全量构建、再执行测试，两个阶段
  不重叠，所以峰值由 `build.jobs` 决定，它才是关键那一个。`test-threads` 是保守取值，执行阶段的
  峰值尚未实测；如果它从来不是瓶颈，可以按实测结果调回去。
- **`.cargo/config.toml` 放在仓库根而不是 `mydev/codex-rs/`。** cargo 会从 cwd 逐级向上合并配置，
  所以这一份同时覆盖 `mydev/codex-rs`、`mydev/tools`、`codex-source-code` 和 `.claude/worktrees/`
  下的全部构建，换 worktree 不会失效；同时不改动上游 codex 自带的配置文件，基线升级时不会冲突。
- **锁是机器级而不是 worktree 级。** 单次构建限到 6 jobs，但主工作区一个 agent、worktree 里另一个
  agent 各跑一次，叠加仍会突破单构建的安全估算。`just test` / `just clippy` / `just fix`（Unix 分支）
  都走 `with-build-lock.sh`，等待时会打印提示，不会看起来像卡死。锁由被包裹的进程本身持有，
  进程退出/崩溃/被杀都自动释放，没有陈旧锁问题；在受支持入口启动前发现 scope 外已有相关进程时
  会直接拒绝第二次构建。
- **rustc wrapper 是跨入口总并发兜底，不是第二把 Cargo 构建锁。** 即使有人绕过 `just` 直接执行
  Cargo，所有 worktree 的 rustc 仍共享 6 个槽；但两个 Cargo 驱动仍可能同时存在，所以正式重型任务
  仍必须经过 `with-build-lock.sh`。信号量固定在当前用户的运行目录，不随 agent 的 `TMPDIR` 分裂。

单个重测试太吃内存时，**不要继续调低全局 `test-threads`**，那会让所有轻量测试一起变慢。用 nextest 的
按测试资源控制：`.config/nextest.toml` 里已有 `test-groups`（`app_server_integration` 等用 `max-threads`
限制同类重测试的并发数），需要更细的权重时用 `threads-required` 让单个重测试占多个线程槽。

Windows 分支的 `just` 配方保持上游行为（不加锁），因为本项目的开发机是 WSL。

已知的未覆盖面（互斥锁和 watchdog 只作用于 `just test` / `clippy` / `fix` 的 Unix 分支，
`jobs = 6` 与 rustc wrapper 则覆盖仓库内 Cargo/rustc）：

- **直接敲 `cargo build` / `check` / `nextest` 不走锁也不进 scope。** `jobs = 6` 与 rustc wrapper
  仍限制单次/总体 rustc 并发，但 direct Cargo 自身不受磁盘、PSI、swap watchdog 保护；正式重型任务
  必须使用受支持的 `just` 入口。
- **`just bench` 走的是 `cargo bench --workspace`，没有包进互斥锁和 scope**，因为它跨平台且极少运行。
  需要跑基准时确认没有别的构建在跑。
- **Bazel 路径没有加闸。** `mydev/.bazelrc` 的 `common --jobs=30` 仍是上游值。Bazel 本身按
  `--local_resources`（默认 `HOST_RAM*0.67`）做内存感知调度，不像 cargo 那样只按 CPU 数硬拉并发，
  风险低一档；且本机尚未安装 Bazel（见 §8）。等真正引入 Bazel 时再实测并决定是否收紧，这里不做未经验证的改动。
- **当前阈值来自一次上游 scratch 全工作区运行，不是永久常量。** 新基线明显改变构建体积或资源曲线时，
  应先用相同指标重新校准；出现 125/137 时先看摘要中的 stop reason、不可回收内存、swap 与 PSI。

## 4. Node 与 pnpm

| 项目     | 当前状态                                                  |
| -------- | --------------------------------------------------------- |
| Node.js  | `v24.14.1`，满足仓库要求 `>=22`                           |
| npm      | `11.11.0`                                                 |
| Corepack | `0.34.6`                                                  |
| pnpm     | 精确固定为 `10.33.0`                                      |
| 固定来源 | `mydev/package.json` 的 `packageManager` 字段及完整性摘要 |
| 依赖目录 | `mydev/node_modules`，约 145 MB（旧基线安装）              |

`v0.146.1` 环境准备时已执行：

```bash
corepack prepare pnpm@10.33.0 --activate
corepack enable pnpm
cd /home/sjc/desktop/RONDO/mydev
pnpm install --frozen-lockfile
```

上述冻结安装与 529 包是 `v0.146.1` 环境准备时的历史结果。`v0.147.0` 上游导入已经更新
`pnpm-lock.yaml`；本次文档适配没有重新执行 `pnpm install`，因此不把旧 node_modules 或旧包数
表述为新基线验收。pnpm 显示的新主版本提示不应直接采纳；仍应遵循仓库的 `packageManager`
固定版本，后续需要 Node 工作区时再用新锁文件做冻结安装并记录实际结果。

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

以下重型设施当前仍未安装或未执行：

- Bazel / Bazelisk 9 及其构建缓存
- Docker devcontainer 环境
- `cargo-dylint`、`dylint-link`、`cargo-shear`
- 额外的跨平台 Rust targets
- RONDO `v0.147.0` 产品树的完整 `just test`、Bazel 测试或完整 Docker 测试

`v0.146.1` 产品树曾于 2026-08-08 完整跑过 `just test`：13,135 项运行，13,062 通过 /
73 失败 / 23 跳过 / 25 flaky，且无 OOM；这是旧基线历史证据，详见
`agent_log/2026-08-08-031500-full-test-backfill.md`。§3.5 记录的 14,065 项结果则来自隔离 scratch
里的纯上游 `v0.147.0`，同样不是当前 RONDO 产品验收。本次文档任务未构建、未编译、未运行测试；
因此不声称 RONDO `v0.147.0` 已通过任何新门禁。Bazel 门禁与 `just argument-comment-lint` 仍未运行。

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
just --list
# 重型构建/测试只使用 §3.5 受监督的 just 入口；不要把本健康检查当成构建门禁

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
