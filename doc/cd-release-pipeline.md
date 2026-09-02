# RONDO CD 发布流水线

最后同步：2026-09-02

**定义文件**：`.github/workflows/release.yml`（仓库根）

本文覆盖发布流水线的使用、原理、必须遵守的不变量、修改方法和排障。
日常质量验证是另一条独立管线，见 [`doc/ci-pipeline.md`](ci-pipeline.md)。

> **这里的 "CD" 指持续交付 GitHub Release**：构建产品包、验证、发布到 Releases 页面供人下载。
> **不包含**把服务部署到任何生产环境——本项目没有需要部署的服务。

---

## 0. 接手前必读：不变量与后果分档

**下面这些不是代码风格，是安全与合规控制。** 每条都标了"违反后会怎样"，
并且**后果分三档**——照着排查会快很多：

| 标记 | 含义 |
|---|---|
| 🔴 **静默失效** | 流水线全绿，产物已失去它声称具备的性质，没有任何提示 |
| 🟠 **延迟/间接失败** | 会红，但红在很后面的步骤上，报错信息指向的不是真正的原因 |
| 🟡 **明确失败** | 当场报错，信息基本能直指问题 |

注意：本流水线的多道自检（归档后逐字节复核、必需文件断言、A14 篡改测试）
正是为了把上面第一档尽量转成第二档。**但"有自检"不等于"可以随便改"**——
自检本身也可能被同一个改动绕过。

### 🟠 A. 构建顺序是冻结的，不能重排

```
① 取 V8 产物  →  ② 编 bwrap、strip、算摘要  →  ③ 编主程序  →  ④ 组包
                        ↑                          ↑
                   摘要在这里产生            摘要在这里被编进去
```

**②必须在③之前。**

`linux-sandbox/src/bundled_bwrap.rs` 通过 `option_env!("CODEX_BWRAP_SHA256")` 读取摘要，
这是**编译期**求值：

```rust
// bundled_bwrap.rs:116
fn expected_sha256() -> Option<[u8; 32]> {
    let raw_digest = option_env!("CODEX_BWRAP_SHA256")?;   // 缺失 → None
    ...
    (digest != NULL_SHA256_DIGEST).then_some(digest)        // 全零 → None
}

// bundled_bwrap.rs:126
fn verify_digest(file: &File, expected: Option<[u8; 32]>, path: &Path) -> Result<(), String> {
    let Some(expected) = expected else {
        return Ok(());                                      // None → 直接放行
    };
```

**有两条静默关闭路径**：环境变量缺失，或摘要为全零（`00…00`）。
两者都让校验变成无条件放行，且不产生任何警告。

**违反后会怎样**：bundled bwrap 的完整性校验**被静默跳过**。产物照样构建成功，
`--version`、doctor、sandbox 所有常规冒烟测试**全部通过**。

**唯一能抓到它的是 verify job 里的 A14 篡改测试**，而且报错是
"product accepted a tampered bundled bwrap"——**指向的是现象，不是"你改了构建顺序"这个原因**。
所以标🟠而不是🔴：会红，但排查方向容易走偏。
**如果 A14 同时被删或被绕过（见不变量 J、K），这一条就退化成完全静默。**

摘要覆盖的是 **strip 之后**的字节，因为那才是进包的字节。

### 🟠 B. 打包器必须显式传入三个已构建产物

```bash
python3 build_codex_package.py \
  --entrypoint-bin "${out}/codex" \
  --code-mode-host-bin "${out}/codex-code-mode-host" \
  --bwrap-bin "${out}/bwrap" \
  ...
```

传了这三个，打包器的内部 `binaries` 列表为空，**它自己的 cargo build 被完全跳过**。

**违反后会怎样**：打包器会跑它自己的构建，而那个构建 ① **不带 `--locked`**（可能拿到
与 `Cargo.lock` 不一致的依赖），② 会在摘要已经编进主程序之后**重新编译 bwrap**，
于是包里的 bwrap 和主程序里的摘要对不上——A14 会红，但你会先怀疑错方向。

### 🟠 C. `--entrypoint-bin` 不校验架构

打包器只检查文件存在且可执行，**不检查它是不是目标平台的产物**。

**违反后会怎样**：一个 host 架构的、debug profile 的二进制会被当成"musl release"
原样打包发布，用户下载后完全跑不起来。

因此：`cargo build` 必须显式 `--target "$TARGET" --release`，
并且有独立一步 `Verify the built artifacts are actually musl` 检查产物没有 ELF interpreter
（静态链接的 musl 产物不应该有）。这一步不能删。

### 🟠 D. 不能传 `--archive-output`

打包器会在校验完包目录后**立刻归档**。

**违反后会怎样**：之后注入的 `LICENSE`、`NOTICE`、`THIRD-PARTY-LICENSES/` **进不了归档**。
归档步骤本身不报错，但下一步"解包复核"的 19 项必需文件断言会红
（`archive is missing or has an empty LICENSE`）——**报的是缺文件，不是"你多传了一个参数"**。

所以流程是：组包 → 注入许可 → **自己手工 `tar`** → 算校验和。

### 🟠 E. V8 产物必须按 `$TARGET` 选，不能按 host

产品自带的 `with_codex_v8_artifacts.py` 按 `rustc -vV` 的 **host** 三元组选产物。
GitHub runner 的 host 是 `x86_64-unknown-linux-gnu`，而我们的目标是 `...-musl`。

**违反后会怎样**：把 GNU 版的 V8 静态库链进 musl 目标。

workflow 因此不调用那个 wrapper，而是直接 import 它用的同一批模块，按 `$TARGET` 取：

```python
spec = TARGET_SPECS[target]
artifacts = fetch_codex_v8_artifacts(spec, version=resolved_v8_crate_version())
```

⚠️ **注意这里也没有独立的"来源正确"断言**：`fetch_codex_v8_artifacts` 会用官方
`.sha256` 校验下载完整性，但那只证明"你拿到的就是你请求的那个文件"，
**不证明你请求的文件名对应正确的 target**。而"产物是静态 ELF"那一步也只看最终二进制，
同样推不出 V8 archive 来源正确。取错大概率会在链接期炸（符号不兼容），
但那是副作用，不是设计好的检查。改动这里时请特别小心。

### 🟠 F. 跨 step 传值必须写进 `$GITHUB_ENV`

每个 `run:` 是**独立的 shell**。`echo VAR=x` 只进日志，后续 step 看不到。

涉及的变量：`RUSTY_V8_ARCHIVE`、`RUSTY_V8_SRC_BINDING_PATH`、`CODEX_BWRAP_SHA256`、
`STAGE` / `PKGNAME` / `PKGDIR`、`CARGO_HOME`。

**违反后会怎样**：V8 那两个变量任一缺失 → cargo 回退去**从源码编译 V8**（几小时，
runner 撑不住）；摘要缺失 → 见 A。

### 🟠 G. `cargo install cargo-about` 必须带 `--features cli`

cargo-about 0.9.2 声明了 `[[bin]] required-features = ["cli"]`，**且没有 default feature**。

**违反后会怎样**：`cargo install cargo-about` **只编库、不装任何二进制，而且退出码是 0**，
只留一行 warning：`none of the package's binaries are available for install using the selected features`。
安装那步是绿的，几十分钟后在注入许可时才炸。

因此装完必须显式断言：

```bash
command -v cargo-about
cargo about --version
```

**退出码在这里不可单独采信。**

### 🟡 H. cargo-about 必须装在 musl 工具链之前

`install-musl-build-tools.sh` 会把 zig cc/c++ shim 导出为**全局 `CC`/`CXX`**。
cargo-about 有需要为 host 编译的原生依赖（mimalloc）。

**违反后会怎样**：cargo-about 编译失败，或编出 musl 产物在 host 上跑不了。

### 🔴 I. `about.hbs` 里不能有 handlebars 注释，且必须用三花括号

**这一条没有任何自动断言兜底**（原因见下方"已知缺口"）。

- **双花括号 `{{ }}` 会 HTML 转义**：会把许可原文里的 `PROVIDED "AS IS"` 变成
  `PROVIDED &quot;AS IS&quot;`。许可通知必须逐字复制，被转义就是坏的。
  已实测：一次生成里出现 **2084 处**转义。
- **`{{! }}` 注释里若含 `}}` 会提前结束**，剩下的散文被当正文渲染进许可文件。
  已实测泄漏过。

**现状：模板里一条注释都没有，全部用 `{{{ }}}`。** 说明文字写在 collect 脚本里。

> **⚠️ 已知缺口**
>
> release.yml 里那 6 条 `assert_contains` **全部作用在入库或复制的文件上**
> （V8×3、rusty_v8、ICU、bubblewrap），而 cargo-about **生成**的三份
> `rust-dependencies-*.md` **只有 `test -s`（非空）检查，没有任何内容断言**。
>
> 所以这一条违反后**没有任何自动检查能发现**：报告非空、文件齐全、流水线全绿，
> 只是里面的许可原文被转义坏了。目前只能靠人工抽查：
>
> ```bash
> # 复验已发布产物时顺手跑一下，正常应为 0
> grep -c '&quot;\|&#x27;\|&amp;' <pkg>/THIRD-PARTY-LICENSES/rust-dependencies-*.md
> ```
>
> 想补上这个缺口，最小做法是给生成的报告也加一条断言
> （例如断言 `PROVIDED "AS IS"` 逐字出现且 `&quot;` 出现 0 次）。
> **改完必须先发一个 RC 验证**，不要直接上正式版。

### 🟠 J. verify job 必须先断言 PATH 上没有 system bwrap

`linux-sandbox/src/launcher.rs` 的 `preferred_bwrap_launcher()` 先试
`find_system_bwrap_in_path()`，失败才回落到 `bundled_bwrap::launcher()`——
**系统 bwrap 优先于 bundled bwrap**。

**违反后会怎样**：runner 上若存在系统 bwrap，第 4/7 项 sandbox 检查测的都是**系统那个**，
通过了什么也没证明。

不过 **A14 仍会把它兜住**，所以标 🟠 而不是 🔴：篡改的是包内 bundled bwrap，
而产品用的是系统那个，于是 sandbox 正常退出 0 → A14 断言
"product accepted a tampered bundled bwrap" 变红。
**只是报错说的是"产品接受了被篡改的 bwrap"，不会告诉你"因为 PATH 上有个系统 bwrap"**——
这个预检的价值就在于把那句难懂的报错换成一句直白的。

### 🔴 K. A14 必须断言具体的 digest-mismatch 错误

做法是往 bwrap **尾部追加一个字节**（ELF 加载器忽略尾部多余字节），不是随机翻转字节。

**决定性证据不是"产品退出非零"，而是产品报出下面这条具体错误**：

```
bundled bubblewrap digest mismatch
```

只有这条错误能证明 `CODEX_BWRAP_SHA256` 真的被编进去了；如果只断言退出非零，
ELF 损坏、user namespace 不可用或其他无关故障都可能造成假阳性。

当前测试还会先单独运行篡改后的 bwrap，确认它仍能 `--version`。这是有价值的
**防御性检查和诊断增强**：它排除了"篡改动作直接破坏 ELF"这个混淆因素，
但不是唯一兜底；即使省略这一项，后面的具体错误文本断言仍会拒绝普通的加载或执行错误。

### 🟡 L. 正式版不能传 `--latest=false`

GitHub **不允许唯一的非 prerelease 版本退出仓库级 latest 指针**。已实测：
`local-v0.1.0` 创建时传了 `--latest=false`，随后又 `PATCH make_latest=false`（返回 200），
`isLatest` 全程都是 `true`。

所以现在：

- **prerelease**：传 `--prerelease --latest=false`，并**保留硬断言**"RC 绝不能是 latest"
  （rc4–rc6 实测这条守得住）
- **正式版**：不传该标志，只记录不判定

**latest 是平台展示状态，不代表任一产品线的版本权威。** 对外入口一律用 README 的固定 tag 链接。

### 🟡 M. `set -e` + `$(cmd)` 会吞掉唯一的诊断

```bash
set -e
out="$(some_command 2>&1)"   # 命令失败 → shell 立刻死
echo "$out"                  # 永远执行不到
```

已经踩过（rc3 的 sandbox 测试红了但零诊断信息）。**正确写法**是先关掉 `-e`、
捕获输出和退出码、**先打印再判断**：

```bash
set +e
out="$(cmd 2>&1)"; status=$?
set -e
echo "$out"
[[ $status -eq 0 ]] || { ...; exit 1; }
```

`Smoke test - arg0 and sandbox` 整步刻意用 `set -uo pipefail`（**没有 `-e`**），原因写在注释里。

### 🟡 N. CHANGELOG 必须有对应版本小节

发布说明由 `compose-release-notes.sh` 从 `<product>/CHANGELOG.md` 里抽 `## <base_version>`
那一节。**找不到就 `exit 1`**（fail closed，不发空说明）。

`base_version` 是去掉 `-rcN` 后缀的版本，所以 `multi-v0.1.0-rc6` 找的是 `## 0.1.0`。

---

## 1. 是什么 / 怎么触发

推送符合规则的 tag 即触发，**没有别的触发方式**（没有 `workflow_dispatch`）：

```
local-vX.Y.Z[-rcN]   →  构建并发布 mydev/     入口名 rondo
multi-vX.Y.Z[-rcN]   →  构建并发布 multidev/  入口名 rondo-multi
```

两条轨**绝不混跑**：`local-*` 不会构建 multidev，反之亦然。

产物目标目前只有 `x86_64-unknown-linux-musl` 一个。

---

## 2. 发布一个新版本（操作手册）

### 步骤

**顺序是有讲究的：README 的下载链接必须等 Release 真的成功之后再更新**，
否则一旦构建失败，公开 README 就指向一个不存在的资产。

```bash
# 1. 写 CHANGELOG —— 必做，否则发布会失败（见不变量 N）
#    在 mydev/CHANGELOG.md 或 multidev/CHANGELOG.md 顶部加一节：
#      ## 0.1.1 - 2026-10-01
#      这一版改了什么。
#    新版本在上，旧版本往下压。

# 2. 只提交这一个文件，不要用 git add -A
#    仓库规则要求保留来源不明的工作区修改（CLAUDE.md 第 4 节），
#    add -A 会把并行任务或你自己没写完的改动一起带进发布提交。
git add multidev/CHANGELOG.md
git commit -m "docs: RONDO Multi 0.1.1 changelog"
git push origin main

# 3. 等【这个 commit 的 ci workflow】跑绿再往下
#    必须按 workflow + commit 精确定位并等待退出码；
#    只敲 `gh run list --limit 1` 是不够的——它可能显示别的 workflow 或别的提交，
#    也不会等待、更不会在失败时返回非零。
sha="$(git rev-parse HEAD)"
run="$(gh run list --workflow=ci.yml --commit "$sha" --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run" --exit-status    # 绿了才返回 0；红了非零，就地停下

# 4. 打 tag 并推送 —— 这一步就是"按下发布按钮"
git tag -a multi-v0.1.1 -m "RONDO Multi 0.1.1"
git push origin multi-v0.1.1

# 5. 等约 1.5 小时，四个 job 全绿

# 6. 下载复验（见下一小节）

# 7. 复验通过后，才更新 README 的固定下载链接并单独提交
#    （tag 指向的提交里 README 仍指向上一版，这是正常的）
git add README.md
git commit -m "docs: point the download link at multi-v0.1.1"
git push origin main
```

### 发布后复验

```bash
gh api repos/sjc786526-coder/RONDO/releases/tags/multi-v0.1.1 \
  --jq '{tag:.tag_name,draft,prerelease,assets:[.assets[].name]}'

gh release download multi-v0.1.1 -R sjc786526-coder/RONDO --dir /tmp/rel
cd /tmp/rel && sha256sum -c SHA256SUMS
```

⚠️ 下载目录**不要放在项目根内**——归档约 150 MB，会计入本地磁盘门禁
（`CLAUDE.md` 第 3 节，350/365/370 GB 三档）。

### 要不要先发 RC

- **改动小**（只改产品代码）：直接发正式版。
- **动了流水线本身、许可材料、或升级了上游基线**：先发一个 `-rc1` 试跑。

RC 是 prerelease，不会占用 latest，也不会被误当成正式版。

### 失败了怎么办

**先分清是哪一类**。注意一个前提：**tag 一旦推送就已经是公开的远端状态**
（仓库已 public），而且 Actions 里留有运行记录——所以"还没 publish 就等于什么都没发生"
**不成立**，别拿它当作可以随便删 tag 的理由。

| 情况 | 做法 |
|---|---|
| **临时故障**（网络抖动、runner 抽风、下载超时） | **对原 tag 重跑失败的 job**，不用新 tag：`gh run rerun <run-id> --failed` |
| **需要改源码或 workflow** | **不动原 tag**，用**下一个 RC / 版本号**重发。已发布的 tag 永远不移动 |
| **tag 本身打错了**（版本号敲错、畸形 tag 被 validate 拒绝）且确定作废 | 才删除那一个 tag。这是例外处置，不是通用做法 |

删除 tag（仅限第三种情况）：

```bash
git push --delete origin multi-v0.1.1 && git tag -d multi-v0.1.1
```

**已经创建了 Release 的 tag 一律不删不改。** 历史上 `local-v0.1.0` 的 publish job
因一条错误断言变红，但产物完全正常——当时的决定是**保留那条红色记录**，
不为了好看而重建 Release。

---

## 3. 流程与实测耗时

`multi-v0.1.0` 实测（2026-09-02，ubuntu-24.04）：

| Job | 耗时 | 作用 |
|---|---|---|
| **validate** | 2 秒 | 校验 tag 格式，决定产品线 |
| **build** | 88m25s | 造包（详见下） |
| **verify** | 20 秒 | 干净 runner 上冒烟 + A14 |
| **publish** | 18 秒 | 生成说明、创建 Release、上传 |

整轮 **1h29m**。四轮实测区间 **1h21m – 1h31m**（rc1 1h21m / rc6 1h31m / local 1h25m / multi 1h29m）。

build job 内部最耗时的步骤：

| 步骤 | 耗时 |
|---|---|
| Build entrypoint and code-mode host | **75m59s** ← 绝对大头 |
| Inject license material | 5m49s |
| Install cargo-about | 2m51s |
| Free up runner disk space | 1m35s |
| Build bwrap + strip + digest | 32s |
| Archive and checksum | 20s |

**约 85% 的时间在编译主程序**（V8 + musl 静态链接）。这是固有成本，不是实现问题。

### build job 在干什么（按阶段）

下面按**阶段**讲，不按 step 序号——workflow 里增删一步就会让编号全错。
当前实际是 19 个 YAML step；**冻结顺序那四步的相对次序才是不可动的**，其余可增删。

```
准备环境
  1 checkout
  2 清 runner 磁盘        ← 必需，见排障"No space left on device"
  3 打印机器规格
  4 装系统依赖（binutils / pkg-config / libcap-dev）
  5 Rust 工具链 1.95.0
  6 隔离 CARGO_HOME
  7 装 cargo-about        ← 必须在 musl 之前（不变量 H）
  8 装 Zig 0.14.0
  9 装 musl 工具链         ← 调用产品树内上游脚本，不重写
 10 关 aws-lc jitter entropy（musl 兼容）

冻结的四步构建顺序
 11 取 V8 产物并校验（按 $TARGET）        ← 不变量 E、F
 12 编 bwrap → strip → 算摘要 → 导出      ← 不变量 A
 13 编主程序和 code-mode-host（摘要在此编入）
 14 验证产物确实是静态 musl                ← 不变量 C

组包与自检
 15 组装包目录（显式传三个产物）           ← 不变量 B、D
 16 注入 LICENSE / NOTICE / 17 份第三方许可
 17 归档 + 算校验和
 18 解开归档逐字节复核                     ← 真正的自检在这一步
 19 上传 artifact
```

第 18 步的"解开复核"会做四件事：三个二进制与打包前输入**逐字节比对**、
包内 bwrap 哈希 == 编进主程序的摘要、**19 项必需文件非空（`test -s`）**、
**6 条许可内容断言**。

### verify job：为什么单独一个 job

单独 job = **一台全新的、从没构建过 RONDO 的 runner**，这就是"干净机器"要求，
不需要 Docker。而且它跑在 publish **之前**，所以有问题的包发不出去。

按顺序做这些事：

1. 校验和 + 解包
2. **断言 PATH 上没有 system bwrap**（不变量 J）
3. `--version` 且必须输出 `0.147.0`（冻结基线，产品版本在 tag 里）
4. `doctor` 能解析出 bundled ripgrep（顺带证明改入口名没破坏包布局识别）
5. **A13**：默认配置下 `doctor --json` 的 `updates.status` 必须是 `not checked...`
6. 放开非特权 user namespace（Ubuntu 24.04 的 AppArmor 限制，bwrap 需要 `CLONE_NEWUSER`）
7. **arg0 与 sandbox 冒烟**：`<entrypoint> sandbox -- /bin/echo rondo-sandbox-ok`
   必须退出 0 且输出该标记；失败时自动打印 bundled bwrap 自检与 userns 探测
8. **A14**：bwrap 篡改检测（不变量 K）

第 6 步是环境准备不是检查，但**位置不能挪到第 7 步之后**，否则 sandbox 起不来，
测的就变成了 AppArmor 限制而不是产品。

第 5 项用真实发布物证明"不会去查上游版本"。它能真的变红——已用 rc5 产物验证过：
rc5 即使显式配置 `check_for_update_on_startup = false`，仍返回 `"latest version": "0.152.1"`。

---

## 4. 许可材料体系

产物里的 `THIRD-PARTY-LICENSES/` 共 **17 个文件**，由
`.github/scripts/collect-third-party-licenses.sh` 组装，来源如下：

| 来源 | 份数 | 内容 |
|---|---|---|
| **仓库内 vendor** | 11 | `.github/licenses/vendor/`：ripgrep×2、zsh、V8×6、rusty_v8、ICU |
| **构建时由 cargo-about 生成** | 3 | `rust-dependencies-<入口>.md` / `-codex-code-mode-host.md` / `-bwrap.md` |
| **产品树内复制** | 1 | `codex-rs/vendor/bubblewrap/COPYING` → `bubblewrap-0.11.2-COPYING` |
| **`.github/licenses/` 直接复制** | 1 | `v8-icu-NOTICE.md`（Cargo 看不到的原生闭包说明） |
| **collect 脚本现场生成** | 1 | `README.md`（本目录的索引表，含各组件版本与对应许可文件） |
| **合计** | **17** | |

### 为什么许可原文要入库而不是发布时下载

一次发布不应该依赖第三方站点可达。已经吃过亏：抓 ICU 的 `icu4c/LICENSE` 时
返回的是 **10 字节的软链接目标**（`../LICENSE`），不是许可正文。
所以 release.yml 里 `test -f` 改成了 `test -s`，并加了 **6 条 `grep -qF` 内容断言**
（V8 的 `.v8` / `.valgrind` / `.wasm-api`、rusty_v8、ICU、bubblewrap）——
**"文件存在"不等于"许可齐备"**。

⚠️ 这 6 条**都只覆盖入库或复制的文件**；cargo-about 生成的那 3 份报告只有非空检查。
见不变量 I 的"已知缺口"。

### V8 的许可为什么是 6 份

V8 自己的 `LICENSE` 枚举了 4 项"外部维护的库"：

| 条目 | 位置 | 是否进归档 | 处理 |
|---|---|---|---|
| PCRE 测试套件 | `test/mjsunit/` | ❌ 测试专用 | 不复制 |
| WebKit layout tests | `test/mjsunit/` | ❌ 测试专用 | 不复制 |
| Valgrind 客户端头 | `third_party/valgrind/` | ✅ | 随包（BSD） |
| Wasm C/C++ API 头 | `third_party/wasm-api/` | ✅ | 随包（Apache-2.0） |

加上 V8 根目录的 `LICENSE`、`LICENSE.fdlibm`、`LICENSE.strongtalk`、`LICENSE.v8` = 6 份。

⚠️ **Valgrind 那份必须是"仅适用于 valgrind.h"的 BSD 全文，不是 Valgrind 主体的 GPL-2。**
断言锁的是限定语 `"applies to this one"`，不是 "Valgrind" 这个词——发错文件会严重误述包内容。

### `about.toml` 的 accepted 是硬门禁

依赖出现未列出的许可时**发布直接失败**，而不是悄悄发一份不完整的通知。
遇到时应该修列表或换依赖，**不是放宽门禁**。

---

## 5. 怎么修改

### 加一个发布目标平台（如 aarch64）

> ⚠️ **这不是"改一行矩阵"就完事的改动。** 现在整条流水线在 build 之后的部分
> 都假设"只有一个目标"。下面每一项都得处理，漏一项就会发出坏包或发不出去。

先决条件（不满足就别开始）：

- **有一台能真正执行该目标二进制的 clean runner**，或者一个明确的模拟方案。
  KD-009 的原则是"**不发自己无法验证的平台**"——发一个自己跑不起来的产物比不发更糟。
- 确认 `rg`、`zsh`、V8 预编译产物在该目标上**都有可用版本**
  （V8 产物名带完整三元组，见 `codex_package/v8.py`）。

要改的地方：

| 位置 | 现状 | 需要 |
|---|---|---|
| `build` job matrix | 单目标 | 加目标 |
| `verify` job | 硬编码 artifact 名 `rondo-package-x86_64-unknown-linux-musl`，`env.TARGET` 也写死 | 矩阵化 |
| `publish` job | 同上，只下载一个 artifact | 下载并上传多个 |
| `SHA256SUMS` | 每个 build 各生成一份、文件名相同 | 决定是合并成一份还是按目标改名，两边都要一致 |
| `compose-release-notes.sh` | **包内容那段的目录树硬编码 `x86_64-unknown-linux-musl`** | 参数化 |
| `README.md` | 两个固定下载链接 | 每个目标各一条 |
| `install-musl-build-tools.sh` | 上游脚本，交叉编译目标相关 | 确认支持新目标 |

**做完必须先发 RC 验证**，不要直接上正式版。

### 升级上游基线时的 V8 / ICU 许可更新

> ⚠️ **这一节只覆盖"许可材料"这一块。完整的上游基线升级远不止于此**，
> 按 `CLAUDE.md` 第 3 节，**上游基线升级必须单独立任务并取得明确授权**，
> 不得混进普通开发。完整升级至少还牵动：
>
> - `rusty_v8` 版本号与文件名（`rusty_v8-150.4.0-LICENSE` 里的版本写死在文件名和索引表里）
> - ICU / `deno_core_icudata` 版本
> - `verify` job 里断言的 `0.147.0`，以及 Release notes 中"关于版本号"那段
> - `eval/rondo_eval/binary_freeze.py` 的 workspace 版本硬断言与整套冻结对比设施
> - Rust 工具链版本（CI 与 release 两处 `dtolnay/rust-toolchain` 的 SHA）
> - **两条产品树必须同步**，否则 Local/Multi 基线不一致

V8 revision 集中在一处：

```bash
# .github/scripts/collect-third-party-licenses.sh
V8_REVISION="ac1e23989121713ca642f6650b34deff7b686896"
```

升级步骤：

1. 查 rusty_v8 新版本 pin 的 v8 submodule：
   `gh api repos/denoland/rusty_v8/contents/v8?ref=v<新版本> --jq .sha`
2. 从 `denoland/v8` 该 revision 重新取 6 份许可原文到 `.github/licenses/vendor/`，
   按 `v8-<前12位>-LICENSE*` 命名
3. 更新脚本里的 `V8_REVISION` 和 README 索引表
4. 更新 `release.yml` 必需文件清单里的 6 个 `v8-<hash>-LICENSE*` 路径
5. 更新 `.github/licenses/v8-icu-NOTICE.md` 里的 revision
6. **先发一个 RC 验证**

V8 crate 版本本身不用手填——`resolved_v8_crate_version()` 从 `Cargo.lock` 读。

### 改发布说明的固定段落

改 `.github/scripts/compose-release-notes.sh`。注意它按 `PRODUCT_DIR` 分支：
Multi 输出"判官后端不在包内"，Local 输出"本地审批模型不在包内"，
**未知产品线 `exit 1`**（fail closed）。

⚠️ **这里出过 bug**：原先无条件输出 Publication Critic 那一节，而该 crate 只存在于 multidev，
导致 Local 的发布说明描述了一个它没有的子系统。**这类 bug 不会让任何 job 变红**，
只会把错的字发出去——加产品线相关内容时务必分支处理。

本地渲染验证（不需要构建）：

```bash
bash .github/scripts/compose-release-notes.sh \
  --product-dir mydev --variant rondo --version 0.1.1 --base-version 0.1.1 \
  --tag local-v0.1.1 --prerelease false --out /tmp/notes.md
```

### 本地测试许可收集（不跑真实 cargo-about）

用一个桩 `cargo-about` 放进 PATH，验证复制、索引、顺序等所有非 cargo-about 部分：

```bash
mkdir -p /tmp/fakebin && cat > /tmp/fakebin/cargo-about <<'EOF'
#!/usr/bin/env bash
out=""; while [[ $# -gt 0 ]]; do [[ "$1" == "--output-file" ]] && out="$2"; shift; done
printf 'STUB\n' > "$out"
EOF
chmod +x /tmp/fakebin/cargo-about
printf '#!/usr/bin/env bash\n[[ "${1:-}" == "about" ]] && { shift; exec cargo-about "$@"; }\nexec /usr/bin/cargo "$@"\n' > /tmp/fakebin/cargo
chmod +x /tmp/fakebin/cargo

PATH="/tmp/fakebin:$PATH" bash .github/scripts/collect-third-party-licenses.sh \
  --product-dir multidev --target x86_64-unknown-linux-musl \
  --out /tmp/lic --entrypoint rondo-multi
```

---

## 6. 排障

### `No space left on device`（链接期）

release 构建产出约 **2723 个目标文件**，runner 根分区放不下。已有两处对策，**都不能删**：

- `Free up runner disk space` 步骤（删预装的 dotnet / android / ghc / powershell / swift / boost / hostedtoolcache）
- `CARGO_PROFILE_RELEASE_DEBUG: "0"`（调试符号是体积主因；本发布不产出 symbols 归档）

### `cargo-about is not installed`（许可注入步骤）

回头看 `Install cargo-about` 的日志有没有那行
`none of the package's binaries are available...` —— 见不变量 G。

### sandbox 冒烟测试失败

Ubuntu 24.04 用 AppArmor 限制非特权 user namespace，而 bubblewrap 需要 `CLONE_NEWUSER`。
已有 `Allow unprivileged user namespaces` 步骤放开 `kernel.apparmor_restrict_unprivileged_userns`。
失败时该步骤会自动打印 bundled bwrap 自检和 userns 探测结果。

### A14 失败

**优先怀疑构建顺序**（不变量 A）。检查 build 日志里 `bwrap sha256:` 出现的位置
是否早于 `Build entrypoint and code-mode host`。

### publish job 红了但 Release 已经创建

Release 对象已经存在，**不要删了重发**。先看具体是哪条断言失败：
prerelease 属性 / draft / 资产数量 / RC 占用 latest。

历史上出现过一次：`local-v0.1.0` 因为一条基于错误 GitHub 语义的 latest 断言而变红，
产物完全正常。该红色记录**刻意保留**，未重建 Release。

### 想在本机复现整个构建

不建议。musl 交叉编译环境（Zig + 源码编译 libcap + cc shim）是为 runner 准备的，
本机重建代价高。**更划算的做法**是下载已发布产物在本机验证——
今天的 A14 就是这么在真实发布物上跑通的。

---

## 7. 相关文件

| 路径 | 作用 |
|---|---|
| `.github/workflows/release.yml` | 流水线定义，关键约束都写在就近注释里 |
| `.github/scripts/collect-third-party-licenses.sh` | 组装 `THIRD-PARTY-LICENSES/`；`V8_REVISION` 在这里 |
| `.github/scripts/compose-release-notes.sh` | 从 CHANGELOG 抽取 + 拼固定段落 |
| `.github/licenses/about.toml` | cargo-about 配置；`accepted` 是硬门禁 |
| `.github/licenses/about.hbs` | 报告模板；**无注释、全三花括号**（不变量 I） |
| `.github/licenses/v8-icu-NOTICE.md` | Cargo 看不到的原生闭包说明 |
| `.github/licenses/vendor/` | 11 份入库的许可原文 |
| `<product>/CHANGELOG.md` | 发布说明的内容来源 |
| `<product>/scripts/build_codex_package.py` | 打包器（上游资产，我们只调用不改） |
| `<product>/.github/scripts/install-musl-build-tools.sh` | musl 工具链（上游资产，不重写） |
| `README.md` | 两个固定 tag 下载链接，发版本时要同步更新 |

---

## 8. 版本号与命名约定

| 概念 | 值 | 说明 |
|---|---|---|
| Release tag | `local-v0.1.0` / `multi-v0.1.0` | **产品版本以此为准** |
| `--version` 输出 | `0.147.0` | 冻结的上游基线，**全程不改** |
| Cargo workspace version | `0.147.0` | 同上 |
| 入口可执行文件 | `rondo` / `rondo-multi` | 打包层改名，`cargo_bin` 仍是 `codex` |
| 归档文件名 | `<variant>-<version>-<target>.tar.gz` | |

**为什么 `--version` 不显示产品版本**：`eval/rondo_eval/binary_freeze.py` 硬断言
workspace 版本为 `0.147.0`，用于与上游 Codex 做字节级公平对比。改它会破坏整套测评设施。
这个不一致由 README 和发布说明各一段文字解释，**不通过改代码解决**。

tag 校验正则拒绝前导零（`local-v01.2.3`）和 `-rc0` / `-rc01`：

```bash
core='(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
# 正式版：^(local|multi)-v${core}$
# 预发布：^(local|multi)-v${core}-rc[1-9][0-9]*$
```

`on.push.tags` 的 glob 是宽的（glob 表达不了 SemVer），**真正的门禁是 validate job**。

---

## 9. 权限模型

```yaml
permissions:
  contents: read      # 工作流级默认：只读
```

只有 `publish` job 提升到 `contents: write`，用的是 `${{ github.token }}`，
**不引用任何 repository secret**。

`build` 和 `verify` 全程只读——它们不需要写权限，也就不可能造成远端副作用。

---

## 10. 完整取舍记录

设计决策与被推翻的方案见 `plan/103-release-engineering-and-cicd-execplan.md`（已冻结）第 7 节，
尤其：

- **KD-001**：产品版本由 tag 承载，不改 workspace 版本
- **KD-002**：二进制改名只在打包层
- **KD-009**：首发只发一个能自己验证的平台
- **KD-017 / KD-019**：许可原文必须随包，不能只给外链
- **KD-018**：latest 指针——含一次基于错误平台语义的整改被实测推翻的完整记录

执行过程中的实际翻车与教训见 `agent_log/2026-09-01-plan103-release-engineering-execution.md`。
