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

### 四、`codex doctor` 的更新检查绕过了 `check_for_update_on_startup`（当时未解决；同日已修复，见文末"外部复审后的整改"一）

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

改完之后 rc5 的报告确认逐字正确了，但**又冒出一个**：我写在模板里的 `{{! ... }}` 注释
被原样输出进了许可文件。因为那段注释里本身含 `}}`，handlebars 提前判定注释结束，剩下的当正文渲染。
最终处理是**模板里一条注释都不留**，说明全部搬进收集脚本——许可文件不该承载任何可能泄漏的散文。
这一处纯属观感，不影响许可全文的正确性，正式发布时复验。

**rc4：构建 + verify 全绿，publish 在"创建之后"失败。**

verify job 在干净 runner 上**全部通过**，包括 sandbox 冒烟与 **A14 篡改测试**——
证明 Ubuntu 24.04 的 userns 判断是对的。

publish 的失败很有意思：`gh release create` **成功了**（Release 已建、prerelease、双 asset、
`releases/latest` 返回 404 即未被标为 latest），失败的是紧随其后的
`gh release view --json tagName,isPrerelease,isLatest,assets`——`isLatest` 与 `assets`
**不是该子命令的合法字段**。等于说：真正的动作成功了，我用来"确认它成功"的那行把 job 弄红了。

顺手把它从"打印"改成"断言"：改走 REST API，逐项校验 prerelease 与 tag 要求一致、
不是 draft、两个 asset 都在、以及 **prerelease 绝不能成为 latest / 正式版必须是 latest**。
新写法先拿 rc4 这个真实 Release 在本机跑通再提交。

**rc5：整条流水线首次全绿。**

`Validate tag 2s → Build 1h22m38s → Verify（干净 runner）18s → Publish 27s`。
发布结果复验：`prerelease=true`、`draft=false`、
资产为 `rondo-multi-0.1.0-rc5-…tar.gz`（151,646,825 B）与 `SHA256SUMS`，
`releases/latest` 仍为 `<none>`——RC 没有污染 latest。

### 阶段 C 的一处自评

五轮 rc 里，**没有一次失败发生在事前评估为高风险的地方**（musl 交叉编译、V8 按 target 取产物、
bwrap 摘要顺序全部一次通过）。四次失败分别是：runner 磁盘、
cargo-about 的 feature gate、我自己的测试脚本吞掉诊断、我自己的验证命令写错字段。
**三次半是工具/自己的问题，不是产品问题。**

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
  （OpenAI 那条是 `sk-` 后面直接跟一串字母表，AWS 那条是 `AKIA` 后面跟 `ABCDEFG…`。
  这里**故意不抄全文**——把占位符原样写进自有目录，会让以后每次扫描都在自己的文档里假阳性，
  "自有目录零命中"这个不变量就废了）；
  历史 blob 由基线导入提交引入。RONDO 自有目录零命中。
  转 public 前的复跑（14,319 blob）另有 2 个命中，落在**本文件自己的历史版本**上——
  当时我把占位符原文抄进了日志。已改写为不抄全文；旧 blob 仍在历史里，
  但内容是上游公开的占位符，不是凭据。
- **D-2**：`eval-data/`、`test-data/`、`reference-agent-harness/`、`rondo-backup-20260827/`、
  `codex-source-code/`、`.codex/` 的 tracked 文件数均为 **0**；
  `.env.local` 与 `rondo.local.toml` **从未**出现在任何历史提交中。
- **提交身份**：全历史 author/committer 只有 `3528349734@qq.com` 与 `sjc786526@gmail.com`，
  author name 只有 `sjc`。
- **个人环境信息**：全仓库跟踪文件里，真正的个人标识只有一处——
  `doc/development-environment.md:22` 的 Windows 用户名。脱敏 diff 已备好，未应用，等用户批准。
  代理相关内容（`127.0.0.1:7897`、Clash TUN fake-IP 导致 11–20 项测试失败的分析）建议**保留**：
  loopback 端口不是凭据，而那段 fake-IP DNS 的排查本身是有价值的工程内容。
  `/home/sjc/...` 出现在 106 个文件里，建议**保留**：用户名 `sjc` 本就随提交历史公开，
  脱敏会破坏可直接复制的命令。
- **再分发边界**：`training/` 全部 600 行均为 `"origin":"synthetic"`、模板展开、
  由 `gpt-5.6-sol` 生成，DATA_CARD 明确写了隐私边界；`eval/results/` 67 个文件只有聚合指标与哈希，
  **没有任何** `prompt`/`instruction`/`transcript` 类字段，全库最长字符串是我们自己的 500 字符
  `operator_reason`。两者均无第三方受限材料，可公开再分发。

---

## 外部复审后的整改（2026-09-01，同日追加）

一次外部复审（GPT）提了 5 条。逐条核对源码后：3 条确认为真问题并已整改，
1 条是我已经报给用户的既有事实，1 条判断为过度设计、未采纳。

### 一、`codex doctor` 的上游查询（KD-016，已修复）

复审的判断与我自己的结论一致，但它多指出一点：两份 CHANGELOG 已经写着
"默认不再检查上游 Codex 的版本更新"，而代码不是这样——**文档在替代码许诺**。这条足以阻断正式发布。

修法是把探测门控到 `config.check_for_update_on_startup`，与 `tui/src/updates.rs:28,151`
已有的门控写法完全一致。之所以认为这仍在 E-X2 意图之内：开关本来就存在、语义也已定义，
`doctor` 是唯一漏网的调用点，补齐它不是新增逻辑，也没有改任何提示文案。

为了让"关闭时不发网络请求"可被机械验证，把逻辑拆成 `probe_latest_version(enabled, ctx)`
与 `push_latest_version_details(...)`：前者在 `!enabled` 时直接返回 `Disabled`，
`fetch_latest_version` 是全模块唯一的上游 API 调用者（已 grep 确认），
所以"返回早于它"就等于"没有网络访问"。新增 3 个离线确定性测试。

**这里有个更值得记的坑**：写完测试才发现它们根本不会被跑。
`mod doctor` 声明在 `cli/src/main.rs`，属于 `codex` bin target；而 CI 的 `TEST_PACKAGES`
不含 `codex-cli`，Gate 2 的 `cargo build` 又不编译 `#[cfg(test)]`。
也就是说这三个测试既不会运行、连类型检查都过不了。补了 Gate 3c
（`cargo test -p codex-cli --bin codex -- doctor::updates`）才真正接上。
**"写了测试"和"测试会跑"是两回事**，这次差点自己骗自己。

### 二、V8 / ICU 只有外链，没有原文（KD-017，已修复）

复审说得对。BSD-3-Clause 和 Unicode License 都要求在**二进制再分发**里复制通知原文，
而 `v8-icu-NOTICE.md` 当时只有组件表和链接——A6 的"完整许可材料"不成立。

已 vendor：rusty_v8 v150.4.0 所 pin 的 V8 submodule（`ac1e23989121`）的 `LICENSE`
及其 `LICENSE.fdlibm/.strongtalk/.v8`、rusty_v8 的 MIT、ICU 的 Unicode License V3。
submodule 指针是从 GitHub contents API 取的，不是猜的版本号。

**没有**采纳"收集 V8`third_party/` 全树"：V8 自己的 `LICENSE` 已枚举那些外部库并指向
随包的三个 `LICENSE.*`，扩到全树属于建设合规系统，超出本任务且违背项目的轻量取向。

抓取时 ICU 的 `icu4c/LICENSE` 返回了 **10 字节**——那是个 symlink，raw 接口给的是
指向目标的文本 `../LICENSE`。这直接说明"文件存在"不等于"许可齐备"，
所以 release 校验里 `test -f` 改成 `test -s`，并对四份许可各加一条 `grep -qF` 内容断言。
写断言时又抓到自己一个错：bubblewrap 的 `COPYING` 是 **LIBRARY** GPL v2（SPDX `LGPL-2.0-or-later`），
标题不是 "LESSER"，第一版断言写错了词。

### 三、两条产品线争抢仓库级 `latest`（KD-018，已修复）

这条是我漏掉的。原实现给每个正式版本设 `--latest=true` 并断言"正式版必须是 latest"。
GitHub 每个仓库只有一个 `latest` 指针，两条线从同一命名空间发布，
后发的会静默把先发的挤下去——不会让 job 变红，但访客看到的"当前版本"是错的。

改为两轨都 `--latest=false`。校验从"观察"改成"强制"：若 GitHub 仍指派，
先 PATCH 收回再断言。理由是 rc4 已经证明"Release 已经公开、job 却红"是会发生的，
在产物已对外可见之后才失败，除了留下一个红叉没有任何用处。

### 四、未采纳：先建 draft 再公开

复审建议改成 draft → 校验 → 公开。不采纳：verify job 已经在**发布之前**于干净 runner 上跑完，
publish 只在其后执行；rc4 的红是我自己断言命令写错了字段名，不是产物问题。
再加一层 draft 状态机只会引入"draft 悬挂"这一新失败模式，与项目的轻量取向相反。

### 五、本地重型验证被磁盘门禁拦下（如实记录）

想在本机跑 `just test -p codex-cli doctor` 做提交前验证，被看门狗按主动停线拦下：

```
[rondo] proactive stop: project_reached_proactive_stop
project=365130043392  (主动停线 365GB)
```

复测：项目 365.8GB，其中 `.codex/cargo-target/rondo-multi` 单独占 **296.8GB**、
`rondo-local` 20.6GB。**没有**删除任何缓存——297GB 的构建缓存虽可重建，
但重建成本以小时计，且可能影响用户或并行任务，不属于我能自己决定的清理。

因此 Rust 改动的编译与测试证据来自 CI，不来自本机。
本机只做了不需要构建的验证：`rustfmt --check`（两棵树均已合规）、
许可脚本的离线冒烟（用桩 `cargo-about`）、以及把 release.yml 的整段校验逻辑
拿真实 rc5 产物树重放一遍——17 项必需文件 + 4 条内容断言全过。
**在 CI 变绿之前，A13 与 A6 不表述为"已通过"。**

### 六、rc5 不能代表待发布源码（已用产物确认）

复审提出 rc5 构建自 `1a734d7e` 而当时 main 已到 `54c8a59e`。核对本机留存的 rc5 产物，
其 `rust-dependencies-*.md` 第 15 行确实还带着 handlebars 注释泄漏
（`... not HTML. }}`）——该修复在 rc5 之后才合入。许可原文本身是干净的
（转义修复在 rc5 之前已生效），但结论成立：**必须重跑 RC**。
叠加本轮 doctor 与许可整改，正式发布前需自同一个 CI 绿色 SHA 跑
`multi-v0.1.0-rc6` 与 `local-v0.1.0-rc1`（后者从未实跑过）。

### 七、脱敏已应用（但不改写历史）

`doc/development-environment.md:22` 的 Windows 用户名已替换为 `<Windows 用户名>`。
复审正确指出这**只清理当前文件**：该字符串已存在于早期提交，转 public 后旧提交仍可查到。
两个邮箱同理。是否接受这部分历史永久公开，仍是用户的决定，不是可以由脱敏 diff 解决的问题。

### 八、Release notes 会给 RONDO Local 写上它没有的功能

趁两条 RC 在跑，复查了从未实跑过的 `local-v*` 轨。构建侧没问题
（`mydev` 有 `rondo` 变体，`cli`/`code-mode-host`/`bwrap` 三个 crate 齐全），
但 `compose-release-notes.sh` 无条件输出"判官后端不在包内 / Publication Critic"一节——
而 `publication-critic` crate **只存在于 `multidev`**。
也就是说 RONDO Local 的 Release notes 会描述一个它根本没有的子系统。

这类 bug RC 抓不到：它不会让任何 job 变红，只是把错的文字发出去。
已改为按 `PRODUCT_DIR` 分支，Local 换成对应的"本地审批模型不在包内"（方向 2，未采用）。
本地对两条产品线各渲染一遍确认无误。

**注意**：本次 `local-v0.1.0-rc1` 是在该修复之前打的 tag，它发布的 notes 仍是错的；
修复已在 main 上，正式发布或后续 RC 才会带上。

## 整改后的实跑验证（2026-09-02）

### CI（run 33588375300，两条产品线全绿）

新增的 Gate 3c 确认**真的在跑**，不是零匹配空过：

```
running 5 tests
test doctor::updates::tests::probe_is_skipped_for_every_install_method_when_update_checks_are_off ... ok
test doctor::updates::tests::disabled_probe_states_the_reason_and_stays_ok ... ok
test doctor::updates::tests::failed_probe_degrades_the_row_to_a_warning ... ok
test result: ok. 5 passed; 0 failed; ... 234 filtered out
```

Local 与 Multi 各 5 passed。CI 全程 15m51s。

### 两条 RC 均全绿

| | tag | 结果 |
|---|---|---|
| Multi | `multi-v0.1.0-rc6` | validate → build → 干净 runner verify → publish 全绿 |
| Local | `local-v0.1.0-rc1` | **首次实跑该轨，一次通过**，四个 job 全绿 |

`local-v*` 轨此前从未跑过，这次证明它可用：tag 正确解析为 `mydev` + `rondo` 变体，
产出 `rondo-0.1.0-rc1-x86_64-unknown-linux-musl.tar.gz`（149,322,955 字节）。

两条 release 的 `prerelease=true`、`draft=false`、各 2 个资产；
`repos/.../releases/latest` 返回 **404**——KD-018 成立，两条产品线都没占用仓库级 latest 指针。

### 许可闭包在真实产物上复验（rc6）

下载 rc6 归档，`sha256sum -c` 通过，解包后：

- 16 个许可文件齐全，V8/rusty_v8/ICU 原文均在包内
- 三份 Cargo 闭包报告的 HTML 实体计数 **全部为 0**
- `PROVIDED "AS IS"` 逐字出现 **233 次**，被转义的变体 **0 次**
- rc5 里那条泄漏的 handlebars 注释**已消失**

构建日志里 4 条 `carries its license text` 断言两条产品线都通过。

### 一次自己差点骗自己的记录

第一次复验时写成 `if grep -c ... | head -3; then`。管道的退出码取自 `head`，
恒为 0，于是"检查"永远报告有问题；更早一次 `gh release download` 失败被
`2>&1 >/dev/null` 吞掉，后面的 grep 对着不存在的目录跑，反而输出了"none (fixed)"这种
**假阳性通过**。两次都重写后才拿到上面的真实数字。
和 rc3 那次 `set -e` 吞诊断是同一类错误：**验证脚本本身也需要被验证**。

### 尚未被实跑覆盖的两处（如实说明）

以下两个提交晚于上面两条 RC 的 tag，因此**没有**被这轮 RC 覆盖：

1. `fix(103)` release notes 按产品线分支——`local-v0.1.0-rc1` 已发布的 notes 里
   仍然带着"判官后端不在包内 / Publication Critic"一节（已在线确认，正文第 63–65 行）。
2. `test(103)` verify job 的 A13 断言（`doctor --json` 读 `updates.status`）。

两者都已在本机用真实数据验证：notes 对两条产品线各渲染一遍确认正确；
A13 断言拿 rc5 真实产物（读出 `0.152.1`）确认会红、拿修复后的结构确认会绿。
正式发布前建议再跑一轮 RC 把这两处也覆盖上——verify job 在 publish 之前执行，
所以即使直接发正式版，A13 断言失败也会挡在发布之前。

## 正式发布（2026-09-02）

### `local-v0.1.0`：产物全绿，publish job 记录为红

四个 job 里 build、干净 runner verify 全过，Release 正常创建
（`draft=false`、`prerelease=false`、2 个资产）。红的是**发布之后**的最后一条断言。

复验（本机下载真实归档）：校验和 OK；`bin/rondo --version` → `0.147.0`（冻结基线，符合设计）；
许可树 17 个文件，含本轮新补的 valgrind 与 wasm-api；发布说明第 61 行是
"本地审批模型不在包内"，**没有**再出现 Multi 专属的 Publication Critic 一节——
产品线分支修复在真实发布物上生效。

按用户批复：**保留这条红色 workflow 记录**，不为美化而重建 Release。它记录的是一个
发布后不可满足的错误断言，不是产品缺陷。

### KD-018 的第一版整改建立在错误的 GitHub 语义上

我原先假设"两条产品线都可以不占用仓库级 latest"。实测三次推翻：

| 动作 | 结果 |
|---|---|
| 创建时 `--latest=false` | 仍被设为 latest |
| 兜底 `PATCH make_latest=false`（HTTP 200） | GraphQL `isLatest` 仍为 `true` |
| 手动重放同一 PATCH | 仍为 `true` |

原因：**正式版里必须有一个是 latest**，仓库只有一个非 prerelease 版本时，
GitHub 静默忽略 `make_latest=false`。

这条正是我上一轮明确标记过的"唯一未被实跑覆盖的路径"。它按设计炸在了正确的位置——
构建、许可、A13、A14 四道门禁都在 publish **之前**跑完，没有任何产物被绕过。
但也说明一件事：**我给它写了"兜底自纠"，而那个兜底本身同样没被验证过**，
所以它没有起到兜底作用。给未验证的逻辑加未验证的兜底，不增加可靠性。

最终方案（用户批准的方案 B）：`--latest=false` 只用在它确实生效的 prerelease 上，
并保留"RC 绝不能是 latest"这条硬断言（rc4–rc6 已证明可满足）；正式版不传该标志，
只打印不判定。latest 被重新定义为**展示状态而非版本权威**，
两条产品线的权威入口是 README 里各自的固定 tag 链接。

### 两条正式 tag 不再要求同一 commit

Multi 必须包含上述 workflow 修复，因此必然位于新 SHA，而已发布的 `local-v0.1.0` tag
不得移动。改为要求**产品源码一致**，打 Multi tag 前须确认 `git diff --quiet
local-v0.1.0..HEAD -- mydev multidev` 为空。

### `multi-v0.1.0`：四个 job 全绿

方案 B 落地后，Multi 正式版一次通过。复验：校验和 OK；`bin/rondo-multi --version` → `0.147.0`；
许可树 17 个文件（含 valgrind/wasm-api）；三份 Cargo 闭包报告 HTML 实体计数全为 0、
`PROVIDED "AS IS"` 逐字 233 次；notes 含 Publication Critic 专属节。

两条正式版**不在同一 commit**（Multi 必须包含 latest 修复），但产品源码一致，
`git diff --quiet local-v0.1.0 multi-v0.1.0 -- mydev multidev` 为空。

`local-v0.1.0` → `3784994f`，`multi-v0.1.0` → `ce63cc1d`。

### 清理 4 个旧 RC Release

删除 `multi-v0.1.0-rc4/rc5/rc6` 与 `local-v0.1.0-rc1` 的 **Release 对象**。
理由：它们都早于许可整改，作为公开可下载物缺必需许可原文（rc4/rc5 更是完全没有 V8/ICU 原文），
且 `local-v0.1.0-rc1` 带着产品线错配的发布说明。

`gh release delete` 的 `--cleanup-tag` 是可选项，不传即保留 tag。删除后逐个复核：
7 个 RC tag 全部完好且指向未变，7 条 RC 相关 Actions 记录仍在。**只删了 Release 对象**。

### 最终 latest 状态

`multi-v0.1.0` 显示为 latest（它是最近创建的正式版），`local-v0.1.0` 为 false，
四个 RC 在删除前均为 false。这是平台行为，不解释为版本权威——
两条产品线的权威入口是 README 里各自的固定 tag 链接。

### 公开候选 HEAD 的复扫（2026-09-02，聚焦式）

全历史 blob 扫描跑了 40 分钟仍未完（14k blob × 13 条正则，大 lock 文件上回溯严重），
按用户指示改为**聚焦当前树**：核心功能代码是上游 fork，几乎不可能含个人信息，
重点放在自有的日志/文档。

**RONDO 自有内容（1,555 个受跟踪文件，排除两条产品树）**

| 项 | 结果 |
|---|---|
| 10 类凭据模式 | **全部 0 命中** |
| `C:\Users\<用户名>` | **0**（脱敏完整） |
| 真实邮箱 | 6 处，都在 plan/log 里描述"提交身份"这项复核时写的 |
| `/home/sjc` | 240 处（既定保留：用户名本就随提交公开，脱敏会破坏可复制命令） |
| 回环端口（含 7897） | 既定保留：loopback 端口不是凭据 |
| SSH 密钥 | 0 |

**产品树（12,247 个文件）**：凭据模式命中 14 个文件，逐一比对 `codex-source-code/` 快照，
**14/14 逐字节相同** → 确认是上游自带占位符。`C:\Users\` 里出现的用户名全是上游占位符
（Alice/dev/openai/fcoury…），无真实用户名；`/home/sjc`、真实邮箱、云资源 ID 均为 0。
产品树里唯一的 `7897` 出现在 `uv.lock` 的包哈希中间，是巧合。

**D-2 复核**：6 个排除目录（`eval-data/`、`test-data/`、`reference-agent-harness/`、
`rondo-backup-20260827/`、`codex-source-code/`、`.codex/`）tracked 文件数均为 **0**；
`.env.local` 与 `rondo.local.toml` **从未**出现在任何历史提交。
提交身份仍只有两个邮箱、一个 author name。

**本轮唯一的新发现：4 个 RunPod 网络卷 ID**
（`hi3iaz8rsr` 40 次、`mwemzrn33y` 101 次、`v1us0nmk0p` 13 次、`bbfxl15nqr` 5 次；
合计 159 处、78 个文件，分布在 agent_log / eval / plan / training / doc）。

判断：**不是凭据**——没有账号 API key 就用不了，性质接近 bucket 名。不建议脱敏：
它已进入历史，改当前文件无效，而且要动 78 个历史记录文件。若确实在意，
真正有效的处置是在 RunPod 侧删除这些卷，而不是改仓库。

**同时修掉一处自己造成的泄漏**：plan 第 517 行在描述"建议如何脱敏"时，
把待脱敏的 Windows 用户名原样抄了进去——和本文件早先记过的教训一模一样。
当前树已清理，历史仍有。
