# RONDO 开发环境基线

最后核对时间：2026-08-04（Asia/Shanghai）

适用工作区：`/home/sjc/desktop/RONDO`，主要源码位于 `mydev/`。

本文记录当前 WSL 开发机的实际环境、版本固定方式、安装位置、验证结果和已知边界。文中不记录代理凭据、API Key 或其他密钥。

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

仓库初始化时曾存在锁文件基线不一致：`Cargo.toml` 的工作区版本是 `0.146.0`，但 `Cargo.lock` 中 132 个本地工作区包仍是 `0.0.0`。该问题已作为独立仓库修复处理，由仓库固定的 Cargo `1.95.0` 将这 132 个内部包版本同步为 `0.146.0`。

差异审查确认没有第三方包版本、依赖列表、source 或 checksum 变化，因此外部依赖图没有变化，不需要刷新 `MODULE.bazel.lock`。以下锁定验证均已通过：

```bash
cd /home/sjc/desktop/RONDO/mydev/codex-rs
cargo metadata --locked --offline --format-version 1 --no-deps
cargo check --locked --offline -p codex-cli
```

后续日常构建和 CI 可以使用 `--locked`，普通 Cargo 构建也不会再因为工作区版本不一致而弄脏 `Cargo.lock`。

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
