# RONDO CI 流水线

最后同步：2026-09-02

**定义文件**：`.github/workflows/ci.yml`（仓库根，这是 GitHub 唯一会执行的 workflow 目录）

本文覆盖 CI 的使用、原理、必须遵守的不变量、修改方法和排障。发布流水线是另一条独立管线，见
[`doc/cd-release-pipeline.md`](cd-release-pipeline.md)。

---

## 0. 接手前必读：五条不变量

这些不是风格偏好。**前三条一旦违反，CI 会继续变绿但不再验证它声称在验证的东西**——
没有任何报错，你只会在很久以后才发现。后两条是范围与安全边界，违反的后果是别的性质，
每条都单独写明了。

### 不变量 1：新写的测试必须落在某条 gate 真正选中的 package 里

这是最容易踩的一条，本项目已经踩过一次。

**根因是 package 选择，不是 target 类型。** 先澄清一个容易搞反的事实：

> `cargo test -p <pkg>` **默认就会跑该 package 的 lib 和 bin 单元测试**
> （Cargo 的默认 target 选择里含 "bins as unit tests"），除非 target 显式设了 `test = false`。
> 所以 `--bin codex` 的作用是**限定**只测这一个 target，**不是**"让 Cargo 开始包含 bin"。

真正导致 doctor 测试漏跑的原因是两条叠加：

- Gate 3a 的 `TEST_PACKAGES` **根本没有选 `codex-cli`**（只有 `codex-config`、`codex-features`，
  Multi 多 `codex-team-state` 和 `codex-publication-critic`）
- Gate 2 是 `cargo build`，普通构建**不编译 `#[cfg(test)]`**

于是写在 `cli/src/doctor/` 里的测试既不会运行，也不会被类型检查。Gate 3c 为此存在：

```yaml
- name: cargo test (doctor update probe)
  run: "cargo test --locked -p codex-cli --bin codex -- doctor::updates"
```

这里用 `--bin codex` 是为了**只编译并运行这一个 target**，避开 `codex-cli` 其余 target
（库、`logs_client`）的测试 harness 编译开销——`codex-cli` 是重 crate，全测太贵。

**接手须知**：加测试时先问"哪条 gate 会选中这个 package？"。
如果答案是"没有"，就得新增一条 gate，或者把该 package 加进 `TEST_PACKAGES`（注意成本）。

**自检方法**：看 CI 日志里那一步的 `running N tests`。N 是 0 或少于预期，
说明 package 没选中或过滤器没匹配——**`cargo test` 匹配到 0 个测试时退出码是 0**，不会报错。

### 不变量 2：路径分流有三类，不是两类

```bash
mydev/*      → 只跑 local
multidev/*   → 只跑 multi
.github/* | scripts/* | eval/* | justfile | *.toml
             → 两条都跑（共享设施）
```

漏掉第三类的后果是：改了 `scripts/` 或 workflow 本身，**`check` job 一条产品线都不会跑**，
push 上去是绿的，但产品侧什么都没验证。

**新增会影响产品构建或两条线共用执行路径的顶层目录时，必须回来更新这个 `case` 分支。**
纯文档类目录（如 `doc/`、`plan/`、`agent_log/`）本来就不该触发产品 Rust 检查，不用加。

准确说，未加入分流的后果是**不触发 `check` job**；`package-scripts` job 无条件运行，
不受这里影响。

### 不变量 3：拿不到 diff base 时必须 fail open

手动触发（`workflow_dispatch`）、新分支、force push 都无法可靠 diff。这时代码走这条路：

```bash
echo "No usable diff base; running both product lines."
local_changed=true
multi_changed=true
```

**方向只能是"多跑"，绝不能是"少跑"。** 如果为了省时间改成"拿不到就不跑"，
force push 之后的代码将完全没有门禁。

### 不变量 4：CI 不跑全量，且"排除"永远不等于"通过"

每条产品线约 130 个 crate。本地全量门禁按 `MemoryHigh=21G` / `jobs=1` 配置，
而 GitHub 标准 runner 是 **4 vCPU / 16 GB**。硬跑要么 OOM 要么超时。

明确排除的部分（`ci.yml` 尾部注释里也记着）：

| 排除项 | 原因 |
|---|---|
| `codex-core` 集成测试 | workspace 里最重的 crate |
| 任何触及 V8 的东西 | 需要下载校验预编译 librusty_v8，属于发布流水线 |
| 需要密钥 / 真实模型 / 付费 API / Docker 的 | CI 不接触任何 secret |

**全量门禁仍在本机**：`just test-with-codex-v8-conservative`。

**不得为了让 CI 变绿而删测试或弱化断言。** 要缩范围就在 workflow 里排除并注明原因，
排除是"这里不跑"，不是"这里通过了"。

### 不变量 5：CI 不使用任何 secret，权限只读

```yaml
permissions:
  contents: read
```

CI 的所有 job 都不需要写权限，也**不得引用任何 repository secret**。
需要凭据的测试属于本地或发布流水线，不属于 push 门禁。

---

## 1. 是什么 / 什么时候跑

日常质量验证。**触发条件**：

- push 到 `main`
- 手动触发（Actions 页面的 `Run workflow`）

**准确定位**：本项目不使用 PR 流程，CI 在 push **之后**才启动，
所以它是**提交后的质量验证 + 发版前的门禁**，
**不能阻止一个坏提交先进入 `main`**——它只能让你尽快知道，并在打 tag 前拦住你。

真正的"不许发出去"由发布流水线保证（干净 runner 验证跑在 publish 之前）。
想要提交前保护，得靠本地跑 `just fmt-check` / `just test`，见第 6 节。

同一分支的新 push 会取消正在跑的旧运行（`concurrency` + `cancel-in-progress`）。

---

## 2. 流程

```
┌─ changed ────────────────── 约 8 秒
│  git diff 算出本次改动影响哪条产品线
│  输出 products=["local"] / ["multi"] / ["local","multi"] / []
└──────────┬────────────────
           │ products != []
┌─ check (矩阵，每条受影响的产品线一个) ─────
│  Gate 1  cargo fmt --check
│  Gate 2  cargo build --locked -p codex-cli --bin codex
│  Gate 3a cargo test --locked $TEST_PACKAGES
│  Gate 3b cargo test --locked -p codex-core --lib -- config::
│  Gate 3c cargo test --locked -p codex-cli --bin codex -- doctor::updates
└───────────────────────────
┌─ package-scripts ────────── 约 10 秒（总是跑）
│  两棵产品树的 codex_package Python 单元测试
└───────────────────────────
```

三个 job 里 `changed` 和 `package-scripts` 是无条件跑的；`check` 按矩阵展开。

`fail-fast: false`：一条产品线红了，另一条继续跑完，便于一次看到全部问题。

### 每条产品线测哪些包

| 产品线 | `PRODUCT_DIR` | `TEST_PACKAGES` |
|---|---|---|
| local | `mydev` | `-p codex-config -p codex-features` |
| multi | `multidev` | `-p codex-config -p codex-features -p codex-team-state -p codex-publication-critic` |

Multi 多两个方向 3 的 crate，两个都很轻，不碰 V8、不碰 core：

| crate | 作用 | 依赖 |
|---|---|---|
| `codex-team-state` | Event 驱动团队世界状态的 canonical 实现 | protocol/serde/sha2/tokio/uuid |
| `codex-publication-critic` | Publication Critic 的客户端接缝 | http-client/serde/tokio/url |

---

## 3. 实测耗时与预算

2026-09-01 实测，ubuntu-24.04，4 vCPU / 16 GB：

| | 冷（无缓存） | 热（有缓存） |
|---|---|---|
| check (multi) | 23m40s | 13m50s |
| check (local) | 23m24s | 12m02s |
| packaging scripts | ~10s | ~10s |
| detect changed | ~8s | ~8s |

**预算**：冷 90 分钟（`timeout-minutes: 90`）、热 30 分钟。余量充足。

> 这批数字实测于 `codex-team-state` 进入 Multi `TEST_PACKAGES` **之前**。该 crate 只依赖
> protocol/serde/sha2/tokio/uuid，增量预期在分钟级以内，但**尚未实测**；下一次 Multi 跑完后
> 若与上表明显不符，以实测为准更新本节。

**缓存**：local 1983 MB + multi 2058 MB，合计远低于 GitHub 单仓库 10 GB 上限。
缓存 key 按产品线分开，两个 workspace 不会互相挤掉对方的产物。

主要耗时在最后一道 gate 编译 `codex-core` 的测试 harness。

---

## 4. 内存与并发的硬约束

```yaml
env:
  CARGO_BUILD_JOBS: "2"       # runner 只有 4 vCPU
  CARGO_PROFILE_DEV_DEBUG: "0" # 调试符号是链接期内存的大头
  CARGO_INCREMENTAL: "0"       # CI 每次都是干净的，增量只是负担
  RUST_MIN_STACK: "8388608"    # 8 MiB，编译深层泛型需要
```

**改这几个值之前先想清楚 runner 只有 16 GB。** 本项目本地全量构建按 21 GB 配置，
CI 能跑起来正是因为砍了并发和调试信息。

---

## 5. 怎么修改

### 加一个新的测试 gate

在 `check` job 里追加一步。**先确认目标测试属于哪个 target**（见不变量 1）：

```yaml
- name: cargo test (你的说明)
  working-directory: ${{ env.PRODUCT_DIR }}/codex-rs
  run: "cargo test --locked -p <crate> -- <filter>"
```

含 `::` 的命令**必须加引号**——YAML 里以冒号结尾的裸标量会解析失败。

加完之后到日志里确认 `running N tests` 的 N 符合预期。

### 把某个 crate 加进常规测试范围

改 `Resolve product line` 那步的 `TEST_PACKAGES`。加之前先估算成本：
`codex-core` 这类重 crate 会让热跑从 13 分钟涨到不可接受，宁可像 Gate 3b 那样用过滤器只跑一小块。

### 新增顶层目录

回到 `Detect changed paths` 的 `case` 分支加上它，否则该目录的改动不触发任何测试。
判断标准：**这个目录只属于一条产品线，还是两条共用？** 共用的归第三类。

### 升级 action 版本

所有第三方 action 都**按 commit SHA 固定**，后面跟版本号注释：

```yaml
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
```

**不要改成 tag 引用**（如 `@v6`）——tag 可被移动，SHA 不能。升级时同时更新 SHA 和注释。

刻意没用 `Swatinem/rust-cache`：它没有在冻结的上游树里固定过，而 `actions/cache`（用了的这个）
够用。引入新 action 前先确认有没有必要。

---

## 6. 排障

### fmt 失败

```bash
cd mydev/codex-rs   # 或 multidev/codex-rs
cargo fmt -- --config imports_granularity=Item
```

`imports_granularity` 是 nightly-only 选项，在命令行传（和上游做法一致）。
稳定版 rustfmt 会忽略配置文件里的该项，但**命令行传入时会打一条 warning，属正常**。

也可以用 `just fmt`（走 `scripts/format.py`，同时管 Rust / Python / justfile）。

### 想在本机复现某一道 gate

> ⚠️ **先读这一条**：除 `fmt` 外，本地的 cargo 构建与测试都是重型任务，
> **必须走仓库根的 `scripts/with-build-lock.sh`**（优先用已接入的 `just` 配方）。
> 直接敲 `cargo build` / `cargo test` 拿不到单构建保证和资源看门狗，
> 违反 `CLAUDE.md` 第 3 节。下面给的就是合规命令，照抄即可。

**Gate 1（fmt）**——不编译，可以直接跑：

```bash
just --justfile mydev/justfile fmt-check      # 或 multidev/justfile
```

**Gate 2 / 3（build、test）**——走 `just`，它内部已接入构建锁与看门狗。
**`--locked` 必须自己显式传**：CI 的四条命令都带 `--locked`，而 justfile 配方**不会自动补**，
不传就可能用上与 `Cargo.lock` 不一致的依赖，复现的就不是 CI 跑的那次：

**两条产品线的 Gate 3a 选包不同，别照抄错**（见上面的 `TEST_PACKAGES` 表）：

```bash
# RONDO Local
just --justfile mydev/justfile build-codex-cli --locked
just --justfile mydev/justfile test --locked -p codex-config -p codex-features
just --justfile mydev/justfile test --locked -p codex-core --lib config::
just --justfile mydev/justfile test --locked -p codex-cli --bin codex doctor::updates

# RONDO Multi（Gate 3a 多 codex-team-state 与 codex-publication-critic）
just --justfile multidev/justfile build-codex-cli --locked
just --justfile multidev/justfile test --locked \
  -p codex-config -p codex-features -p codex-team-state -p codex-publication-critic
just --justfile multidev/justfile test --locked -p codex-core --lib config::
just --justfile multidev/justfile test --locked -p codex-cli --bin codex doctor::updates
```

注意 `just test` 用的是 **nextest**，过滤器是位置参数；CI 用的是 `cargo test`，
过滤器要放在 `--` 之后。两者跑的是同一批测试，写法不同，别照抄错。

**Gate「packaging scripts」**——纯 Python，秒级，无需锁。**必须从产品树的 `scripts/` 下跑**，
这正是 CI 里那条命令：

```bash
cd mydev/scripts && python3 -m unittest discover -s codex_package -p 'test_*.py' -t .
```

⚠️ **`just test-github-scripts` 不是它的等价物。** 那条配方跑的是
`<product>/.github/scripts/` 下上游继承的测试（`test_v8_canary_changes.py`、
`test_macos_signing_entitlements.py` 等），和 CI 跑的 `scripts/codex_package/` 是两套不相干的东西。

**全量门禁**（不在 CI 里，大阶段验收时才跑）：

```bash
just --justfile mydev/justfile test-with-codex-v8-conservative --locked
# 或 multidev/justfile；该配方内部 CARGO_BUILD_JOBS=1、LLD 单线程
```

### check job 被跳过了

看 `Detect changed product lines` 的日志，它会打印本次改动的文件列表和算出的 `products`。
如果是 `[]`，说明改动没落在任何已知路径类别里——大概率是新增了顶层目录（见不变量 2）。

### 缓存看起来没生效

缓存 key 含 **两个** `Cargo.lock` 的哈希：

```yaml
key: cargo-${{ runner.os }}-${{ matrix.product }}-${{ hashFiles('mydev/codex-rs/Cargo.lock', 'multidev/codex-rs/Cargo.lock') }}
```

所以**任一产品线的 lock 变化都会让两条线的缓存失效**，退化成冷跑（约 23 分钟）。
这是刻意的保守选择，不是 bug。

---

## 7. 相关文件

| 路径 | 作用 |
|---|---|
| `.github/workflows/ci.yml` | CI 定义，尾部注释记录实测数据与排除项理由 |
| `mydev/justfile`、`multidev/justfile` | 本地合规入口（`fmt-check` / `test` / `build-codex-cli`），记得自己传 `--locked`。**`test-github-scripts` 不是 CI 那条打包测试的等价物**，见第 6 节 |
| `scripts/with-build-lock.sh` | 本地重型构建的锁与资源看门狗，CI 不用 |
| `mydev/.github/`、`multidev/.github/` | **上游继承的惰性文件**，GitHub 不执行；保留是为了产品树能和上游直接 diff，且产品 justfile 引用了其中的 `.github/scripts/` |
| `.github/modernize/` | 同上，上游继承，与 RONDO 无关 |

---

## 8. 设计取舍备忘

- **不用 PR 流程**：单人开发，push 之后跑验证，**CI 绿是发布的前置门禁**
  （不是合并前保护，见第 1 节）。这是项目层面的决定（`CLAUDE.md` 第 7 节）。
- **路径分流自己用 `git diff` 算**，不引入第三方 action——上游 `rust-ci.yml` 自己就是这么做的。
- **`changed` job 需要 `fetch-depth: 0`**：要拿到完整历史才能 diff。
- 完整的取舍记录见 `plan/103-release-engineering-and-cicd-execplan.md`（已冻结）的 KD-006。
