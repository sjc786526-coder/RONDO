# 2026-09-01 Plan 103 发布工程实施（阶段 A / B / C）

规划批次见 `2026-09-01-plan103-release-engineering-planning.md`。本篇只记录实施。

## 实质性改动

### 阶段 A｜发布身份

- `codex-cli/package.json` ×2：改名 `rondo-cli` / `rondo-multi-cli`，加 `private: true`；
  `description` 与 `repository` 同步修正（改名后原值即为错误陈述）。
- `CHANGELOG.md` ×2：原本各是一行"变更记录见上游 releases 页"，重写为 RONDO 自己的记录，
  首段 `## 0.1.0`，release 工作流按该标题提取 notes。
- `README.md`：补惰性 `.github` 说明与根 `.github/` 目录项。
- **窄例外 E-X1**：两条产品线各新增一个 `PackageVariant`（`cargo_bin` 保持 `"codex"`，
  `executable_stem` 为 `rondo` / `rondo-multi`），纯追加。
- **窄例外 E-X2**：`check_for_update_on_startup` 默认值 `true` → `false`；
  `config_toml.rs` 的文档注释同步修正（它是 JSON schema 描述的**来源**），
  用 `codex-write-config-schema` 重新生成两份 `config.schema.json`，各 1 行差异。

### 阶段 B｜CI

新建根 `.github/workflows/ci.yml`：三类 path filter、fmt/build/test 三门禁、
`actions/cache` 按产品线分 key、独立的 `package-scripts` job、工作流级 `permissions: contents: read`。

**不引入任何上游冻结树里没有固定 SHA 的第三方 action**：路径分流用 `git diff` 自算
（上游 `rust-ci.yml` 自己就是这么做的，步骤名直接写着 "no external action"），
缓存用 `actions/cache` 而不是未固定的 `Swatinem/rust-cache`。

### 阶段 C｜Release

新建根 `.github/workflows/release.yml` 与三个支撑件：
`.github/scripts/collect-third-party-licenses.sh`、`.github/scripts/compose-release-notes.sh`、
`.github/licenses/`（`about.toml`、`about.hbs`、`v8-icu-NOTICE.md`、`vendor/` 三份许可原文）。

ripgrep 与 zsh 的许可原文**入库**而不是发布期下载，避免一次发布依赖第三方站点可达。

## 疑难问题

### 一、musl 交叉编译远不是加个 `--target`

上游 `install-musl-build-tools.sh` 要装 Zig 0.14.0、**从源码编译 libcap**、生成 zig cc/c++ 包装脚本
（处理 `--target` 翻译、`/usr/include` 降序、`-Wp,-U_FORTIFY_SOURCE` 转写、关 UBSan），
再导出整套 `CC`/`CXX`/`CMAKE_*`/`PKG_CONFIG_*`。另需 `AWS_LC_SYS_NO_JITTER_ENTROPY=1`。
工作流直接复用产品树内的该脚本，不重写。

顺带发现：**上游 musl 用的是自建 XL runner**，本项目只有 4 vCPU / 16 GB 标准 runner。

### 二、`cargo-about` 的实际接口靠读源码确认，不靠猜

`--config` / `--target` / `--locked` / `--output-file` / `--manifest-path` 与 `about.toml` 的
`accepted`（**必填**）、`workarounds`、`ignore-build-dependencies`、`ignore-dev-dependencies`、`private`
全部对照 0.9.2 源码逐个核实。`--target` 确实存在且语义是"覆盖配置里的 targets"。

同时确认 **`cargo-about` 不在 `taiki-e/install-action` 的托管清单里**，会走 cargo-binstall 回退。

### 三、fmt 门禁第一次运行就抓到真问题

`mydev/codex-rs/core/src/config/config_loader_tests.rs:285` 有一处 RONDO 自己写的格式漂移。
仓库此前没有格式门禁，所以一直没人发现。multidev 侧本来就是干净的。

### 四、`codex doctor` 的更新检查绕过了 `check_for_update_on_startup`（未解决，待用户决定）

实测：即使显式写 `check_for_update_on_startup = false`，`codex doctor` 仍输出
`↑ updates 0.152.0 available (current 0.147.0)`。

读代码确认：`cli/src/doctor/updates.rs:88` **无条件**调用 `fetch_latest_version()`
→ `curl https://api.github.com/repos/openai/codex/releases/latest`；
该文件只在 36–40 行把配置值当作一条 detail **打印**出来，从不拿它做门禁。

对 fork 而言这条输出有误导性——它把上游 Codex 的版本当成"你该升级到的版本"。
E-X2 修好的是**启动期主动提示**（未经请求的那条路径），doctor 是用户显式运行的诊断命令，
但输出形态仍是提示。因此 **A13 目前不能判为达成**。
修复需要动 `doctor/updates.rs`，超出 E-X2 已批准范围（计划 §2 明确"不得顺带改动更新提示的其他逻辑"），
故只记录、不擅自扩大范围。见计划 KD-016。

### 五、本机磁盘余量成为实施约束

项目从 343 GB 增至 357 GB（告警 350 / 主动停 365 / 绝对停 370）。
Local 冷构建加 `CARGO_PROFILE_DEV_DEBUG=0`，target 只有 6.5 GB；
Multi **不加**该变量，否则指纹变化会让 294 GB 的既有缓存整个作废重建。
本地打包测试的产物放在项目外的 job tmp 目录，不计入该门禁。

## 验收结果

### 阶段 A（已闭合）

| 项 | 证据 |
|---|---|
| config 与快照测试 | Local `472 passed / 0 failed`，Multi `486 passed / 0 failed`；`config_schema_matches_fixture` 单独复跑通过 |
| 打包测试 | 每条产品线 13 项全绿；另经 `build_package_dir`/`validate_package_dir` 实测新变体产出 `bin/rondo` 与 `bin/rondo-multi`，既有 `codex` 变体产物不变 |
| A12 冻结契约 | 直接调 `binary_freeze._validate_workspace_manifests()`，两条产品线均 OK |
| A11 改动面 | `Cargo.toml` / `Cargo.lock` / `eval/` 零改动 |

### 阶段 B（已闭合）

| 项 | 结果 |
|---|---|
| 冷跑时长 | `check (multi)` 23m40s、`check (local)` 23m24s（预算 90 min） |
| 缓存 | 每条产品线约 2.0 GB（GitHub 单仓库上限 10 GB） |
| path filter · 共享类 | 改 `.github/**` → 两条产品线都跑 ✅ |
| path filter · `mydev/**` | 只跑 local ✅ |
| path filter · `multidev/**` | 待一次只改 multidev 的推送验证 |
| 门禁能变红 | 首次运行即因真实格式漂移变红，修复后转绿 ✅ |

### 阶段 C（进行中）

**rc1（`multi-v0.1.0-rc1`）：构建失败于链接期，耗时 1h26m。**

通过的步骤（都是事前判断风险最高的那几个）：
Zig 安装 ✅、**musl 工具链脚本** ✅、**按 `$TARGET`（而非 host）取 V8 产物** ✅、
bwrap 构建 + strip + 摘要导出 ✅。

失败原因与预期完全不同：

```
= note: /usr/bin/ld: final link failed: No space left on device
error: could not compile `codex-cli` (bin "codex")
```

链接命令里 **2723 个 object file**，runner 根文件系统撑不住。两处整改：

1. **构建前清理 runner 预装工具链**（dotnet / android / ghc / powershell / swift / boost /
   hostedtoolcache），只删明确已知路径，且 runner 本就是一次性 VM；
2. **`CARGO_PROFILE_RELEASE_DEBUG=0`**。workspace 的 release profile 是 `debug = "line-tables-only"`，
   那 2723 个 object 的体积主要就是它。本发布**不产出 symbols 归档**，
   line table 只有我们自己会读，没有理由为它付两次代价（磁盘 + 链接时间）。
   注意这是环境变量覆盖，**不改 `Cargo.toml`**。

顺带把 `cargo-about` 的安装**提到 musl 工具链脚本之前**：该脚本会把 zig cc/c++ 包装器设为全局
`CC`/`CXX`，而 cargo-about 自带需要为 host 编译的原生依赖（mimalloc）。
安装方式也从 `taiki-e/install-action` 改为 `cargo install --locked --version 0.9.2`——
已核实 cargo-about **不在**该 action 的托管清单里，会退化到 cargo-binstall，
白白多一个失败面。

另加了构建前后的 `df -h` 与 target 体积输出，下次再撞磁盘时可直接定位。

**rc2（`multi-v0.1.0-rc2`）：磁盘问题解决，改在许可注入步骤失败，耗时 1h18m。**

新通过的步骤：**构建入口与 code-mode-host** ✅、**产物确为静态 musl** ✅、
**打包器用真实 musl 产物走新变体产包** ✅。

失败信息是我自己脚本的 fail-closed 断言：

```
cargo-about is not installed; cannot produce the Cargo license closure
```

但上一步 `Install cargo-about` 是**绿的**。翻日志才看到它只留了一句 warning：

```
warning: none of the package's binaries are available for install using the selected features
```

对照 cargo-about 0.9.2 的 `Cargo.toml`：

```toml
[[bin]]
name = "cargo-about"
required-features = ["cli"]

[features]
cli = ["dep:nu-ansi-term", "dep:handlebars", "dep:mimalloc", "dep:jiff", "dep:fern", "dep:clap"]
```

**没有 `default` feature**，所以 `cargo install cargo-about` 只编库、不装任何二进制，
而且**退出码是 0**。整改：加 `--features cli`，并在安装后显式断言
`command -v cargo-about` 与 `cargo about --version`——退出码在这里不能单独采信。

这条和规划期那七条是同一类毛病：**以为现成工具会替我做的事，它其实没做**，
而且这次它连报错都懒得报。也正因为许可收集脚本自己是 fail-closed 的，
才没有把一个缺许可闭包的包悄悄归档发出去。

**rc3（`multi-v0.1.0-rc3`）：构建 job 全绿（1h30m），verify job 停在 sandbox 冒烟测试。**

构建侧全部通过，包括许可注入、归档、**解包复验**（三个预构建产物的 SHA-256 与
`CODEX_BWRAP_SHA256` 全部对上）、上传。verify job 也通过了校验和、
**"runner 上没有 system bwrap"守卫**、`--version`、bundled ripgrep 解析。

sandbox 那步失败，但**我自己的测试脚本把唯一的诊断信息弄丢了**：
`set -e` + `out="$(cmd)"` 在命令非零时直接终止 shell，后面的 `echo "$out"` 根本没机会跑。
已改为显式捕获 status、先打印再判定，并在失败时追加 bwrap 自检与 userns 探测。

### 用 rc3 的真实产物在本机定位

与其再等 1.5 小时，直接把 rc3 的 artifact 下下来在本机验：

- 校验和 ✅，包内容完整（10 个许可文件 + 三个二进制 + rg + zsh + `codex-package.json`）
- `bin/rondo-multi` 是静态 musl PIE ✅
- 造一个**不含 bwrap 的 PATH farm** 强制走 bundled 路径 →
  `sandbox -- /bin/echo` 输出正确、exit 0 ✅

所以 musl 产物本身没问题，runner 上的失败是**环境限制**：
Ubuntu 24.04 用 AppArmor 限制非特权 user namespace，而 bubblewrap 需要 `CLONE_NEWUSER`。
verify job 已加 `kernel.apparmor_restrict_unprivileged_userns=0`（一次性 VM 上的标准做法）。

### A14 已在真实发布产物上验证通过（本机）

```
exit=101
thread 'main' panicked at linux-sandbox/src/bundled_bwrap.rs:44:35:
bundled bubblewrap digest mismatch for …/codex-resources/bwrap:
  expected sha256:91d6120338523f6f…, got sha256:d44993ed59c90f95…
```

四步都成立：尾部追加一字节后摘要改变 → **篡改后的 bwrap 自身仍能运行**
（`bubblewrap built for Codex`，排除"跑不起来"这个假阳性）→ 经产品触发 →
命中**那一条具体错误**。而且 expected 值 `91d6120338523f6f…` 与构建日志里导出的
`CODEX_BWRAP_SHA256` **完全一致**——这就证明了冻结构建顺序确实把摘要编进了发布二进制，
H12 不是纸面约束。

### 许可报告的一处真实缺陷

生成出来的报告里有 **2084 处 HTML 实体**，
例如 `THE SOFTWARE IS PROVIDED &quot;AS IS&quot;`。原因是 handlebars 的 `{{ }}` 默认转义，
而许可全文必须逐字复制。模板已全部改为 `{{{ }}}`。

### 本机预跑（先于 rc1 降风险）

用 multidev 既有 debug 产物 + 新建 `bwrap`，走 C-3 的准确路径打了一个本机包：

- 打包器经三个 `--*-bin` 产包 → `bin/rondo-multi` ✅
- `rondo-multi --version` → `codex-cli 0.147.0` ✅（符合 KD-010）
- doctor：`runtime ✓` / `install ✓ consistent` / **`search ✓ file exists (bundled, …/codex-path/rg)`** ✅
- `rondo-multi sandbox -- /bin/echo rondo-sandbox-ok` → 输出正确、exit 0 ✅

这把 C-7 里"改名不破坏 arg0、不破坏包布局识别、附属组件仍可解析"三件事
从推理升级为实证。**同时确认了 verify job 那道守卫的必要性**：本机 PATH 上有
system `bwrap 0.9.0`，按 `launcher.rs` 的优先级根本不会走 bundled 路径——
runner 上若也有，A14 会在错误的代码路径上"通过"。

### 公开前复核（D-1 / D-2，只读，已完成）

- **D-1 密钥全量扫描**：14,305 个 blob / 1,289 个 commit，13 类凭据模式。
  10 处命中**全部**位于 `mydev/codex-rs/` 的上游文件，且这些文件与
  `codex-source-code/` 快照**逐字节相同**；命中字面量本身就是占位符
  （`sk-abcdefghijklmnopqrstuvwxyz123456`、`AKIAABCDEFGHIJKLMNOP`）；
  历史 blob 由基线导入提交引入。RONDO 自有目录零命中。
- **D-2**：`eval-data/`、`test-data/`、`reference-agent-harness/`、`rondo-backup-20260827/`、
  `codex-source-code/`、`.codex/` 的 tracked 文件数均为 **0**；
  `.env.local` 与 `rondo.local.toml` **从未**出现在任何历史提交中。
- **提交身份**：全历史 author/committer 只有 `3528349734@qq.com` 与 `sjc786526@gmail.com`，
  author name 只有 `sjc`。
