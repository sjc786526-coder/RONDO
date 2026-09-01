# Plan 103：发布工程与 CI/CD 流水线

> **状态：审查通过，待实施**（2026-09-01）
> 经五轮独立审查，全部阻塞项已复核并整改，规划层无待决问题。下一步从阶段 A-2 开始实施。
> 阶段 C 先用 `multi-v0.1.0-rc1` 预发布 tag 在 private 仓库实跑验证；
> 转 public（D-5）仍保留单独确认门。

> 本计划是任务的稳定约束文档。
> 除"当前状态"和"关键决策记录"外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

---

## 0. 任务背景

用户目标是**跑通一次完整的软件发布流程作为工程履历**，而不是把 RONDO 推向生产使用。因此本任务的产出是
**发布工程能力本身**（CI 门禁、Release 自动化、版本与产物管理、对外文档），不是产品质量或功能推进。

两条产品线都要有对外可见的发布物：

- **RONDO Local**（`mydev/`）：方向 1、2，均已收口
- **RONDO Multi**（`multidev/`）：方向 3，Plan 102 以 `ENGINEERING_SEAM_PASS` 收口，**质量与资格未授予**

`README.md` 已在本任务前置步骤中重写完成（对外门面版，含 fork 归属、诚实结果、实验性声明、开发方式说明），
本计划覆盖其余全部动作。

---

## 1. 目标

### 最终目标

在不改变测评身份和历史证据、且产品语义只允许两处受控窄例外（E-X1 打包变体、E-X2 更新检查默认值）的前提下，
为 RONDO 建立一条可重复的发布流水线，并完成首次公开发布：

1. 仓库转为公开，具备可供外部工程师评估的门面文档；
2. 根 `.github/workflows/` 下有 RONDO 自有的 CI，push 时自动编译并运行受影响产品线的测试子集；
3. 打 tag 即自动交叉编译多平台产物、生成校验和、创建 GitHub Release；
4. 两条产品线各完成一次 `v0.1.0` 发布，产物可下载、可运行；
5. 规划文档与工作流规则同步更新。

### 完成/验收标准

- [ ] **A1** 根 `.github/workflows/ci.yml` 存在，push/PR 到 `main` 时触发，按 path filter 只跑受影响产品线
- [ ] **A2** CI 包含至少三个门禁：`cargo fmt --check`、目标 crate 子集 `cargo build`、目标 crate 子集测试；任一失败则 CI 红
- [ ] **A3** CI 在缓存命中时单次总时长 ≤ 30 分钟；冷启动 ≤ 90 分钟（超出则按 KD-006 缩小范围并记录实测值）
- [ ] **A4** 根 `.github/workflows/release.yml` 存在，由 `local-v*` / `multi-v*` tag 分流触发
- [ ] **A5** Release 产物为 `build_codex_package.py` 生成的**完整产品包**（含 `codex-code-mode-host`、`bwrap`、`rg`、`codex-package.json`），目标为 `x86_64-unknown-linux-musl`，并附 `SHA256SUMS`
- [ ] **A6** 归档内入口可执行文件名为 `rondo`（Local）/ `rondo-multi`（Multi），且归档含 `LICENSE`、对应 `NOTICE` 与 `THIRD-PARTY-LICENSES/`（覆盖随包的 bwrap / rg / zsh **以及两个最终二进制的 Cargo 依赖闭包与 V8/ICU 原生闭包**）
- [ ] **A7** 产物在**干净环境**（未安装 RONDO 的机器或容器）中通过 smoke test：`--version`、一条触碰 arg0/sandbox 的命令、一条依赖附属组件（`rg` 或 `code-mode-host`）的功能
- [ ] **A8** 仓库 visibility 为 `PUBLIC`，且转换前完成密钥历史复核（见硬约束 H4）
- [ ] **A9** `local-v0.1.0` 与 `multi-v0.1.0` 两个 Release 均已发布，Release notes 明确标注实验性质与"无性能承诺"
- [ ] **A10** `doc/WBS.md` 增加发布工程条目；`CLAUDE.md` / `AGENTS.md` 中"不使用 CI 和 PR"的规则已更新为与本任务一致
- [ ] **A11** 全程未改变 workspace 版本号、crate 名与 `[[bin]]` 名；产品运行时语义除已批准的窄例外 E-X1 / E-X2 外未改变
- [ ] **A12** 执行前后 `eval/rondo_eval/binary_freeze.py` 的冻结断言仍然成立（见硬约束 H1）
- [ ] **A13** 发布物默认不再向用户提示上游 Codex 更新（窄例外 E-X2，已获批准）
- [ ] **A14** Linux 包通过 **bwrap 篡改测试（可判定版）**：向包内 `codex-resources/bwrap` **尾部追加一字节**（摘要变化但 ELF 仍可执行）→ 先确认该文件**自身仍能运行** → 再经产品触发 bundled bwrap → 必须观察到 `bundled bubblewrap digest mismatch` 这一**具体错误**（H12）

### 非目标（明确不做）

- 代码签名（Windows Authenticode / macOS notarization / Azure Key Vault）
- npm 发布、Homebrew tap、Docker 镜像、DotSlash、Bazel / RBE
- CLA 机器人、issue 自动标签、stale PR 清理、Dependabot
- 任何产品功能开发、性能优化、质量验收或资格授予
- 上游基线升级
- 解锁方向 3 工作包四

---

## 2. 范围

### 允许修改

- 根 `.github/workflows/`（新建）
- 根 `README.md`（已完成主体，发布后需按 E-0 补下载链接）
- 根 `doc/WBS.md`（仅追加发布工程条目与指针）
- 根 `CLAUDE.md`、`AGENTS.md`（仅更新 CI/PR 相关规则）
- 根 `doc/development-environment.md`（仅按 D-3 做个人信息脱敏）
- `doc/WBS-COMPLETED.md`（**仅追加**本次发布工程的完成条目，不改写既有历史条目）
- `mydev/codex-cli/package.json`、`multidev/codex-cli/package.json`（仅防误发布字段，见 KD-004）
- `mydev/CHANGELOG.md`、`multidev/CHANGELOG.md`（替换为 RONDO 自己的变更记录）
- `agent_log/` 新增本次执行日志
- 本计划的"当前状态"与"关键决策记录"两节

**两处受控的窄例外**（各自有独立验证要求，见 KD-002、KD-012）：

- **E-X1｜打包变体**：`mydev/scripts/codex_package/targets.py`、`multidev/scripts/codex_package/targets.py`
  中 `PACKAGE_VARIANTS` 的**新增条目**。只允许新增，不得修改既有 `codex` / `codex-app-server` 条目。
- **E-X2｜发布身份**（**批准记录**：用户于 2026-09-01 在被明确问及"批不批准动那一行默认值"后答复"批准"，并要求本轮只写进计划、暂不实施）：
  把 `check_for_update_on_startup` 的默认值从 `true` 改为 `false`，
  以及该改动必然牵动的 config requirements 层与快照测试。**不得**顺带改动更新提示的其他逻辑或文案。
  批准范围仅限该默认值本身；实施时机在阶段 A-6，仍需通过 A-6 的专项验证，未通过则按 R7 回退。

### 不允许修改

- `mydev/codex-rs/**`、`multidev/codex-rs/**` 的任何 Rust 源码、`Cargo.toml`、`Cargo.lock`
  ——**唯一例外为 E-X2**
- 两条产品线的 workspace 版本号、crate 名、`[[bin]]` 名（见 KD-001、KD-002）
- `<product>/scripts/**` ——**唯一例外为 E-X1**
- `mydev/.github/**`、`multidev/.github/**`（见 KD-005）
- `eval/**` 的任何文件（含冻结契约、manifest、lock、results）
- `doc/audit-snapshots/**`、`doc/research/**`、既有 `plan/**`、既有 `agent_log/**`、
  `doc/WBS-COMPLETED.md` 的既有条目
- `doc/rondo-multi-publication-critic-*.md`（产品与任务合同，本任务不改语义）
- `training/**`、`LICENSE`、`NOTICE`
- `.gitignore` 中已有的忽略规则（不得让 `eval-data/`、`test-data/`、`.env.local`、模型权重进入版本控制）

### 不允许读取/查看

- `.env.local`（只允许静默检查存在性、非符号链接、权限 `0600`、所需变量非空）
- `rondo.local.toml` 中的任何值（本任务不需要）
- 方向 3 的冻结测试集正文（`publication-critic-v9` test、`publication-critic-qualification-v1`）

---

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

- **H1｜不得改动 Cargo workspace 版本号。**
  `eval/rondo_eval/binary_freeze.py:1301` 硬断言 `workspace.package.version == "0.147.0"`，
  且 `_NORMALIZED_VERSION_LINE` 将上游 `0.0.0` 规范化为 `0.147.0` 以支持与 `codex-source-code/` 的字节级公平对比。
  改版本号会同时击穿冻结二进制身份、历史 manifest 与整个公平对比基础。**产品版本一律由 git tag 承载。**

- **H2｜不得改动 in-tree `[[bin]]` 名与 crate 名。**
  `eval/rondo_eval/binary_freeze.py` 有约 20 处硬编码可执行文件名 `"codex"`；历史冻结 binary、manifest、
  receipt 按 `doc/WBS.md` §4.5 属不可变历史证据。改名一律只发生在 **打包层**，
  且必须通过 `PACKAGE_VARIANTS` 的 `executable_stem`（`cargo_bin` 保持 `codex`），不得用 `cp` 手工拼装。
  注意打包器默认路径存在 build/lookup 名字不一致，实际必须走 `--entrypoint-bin`，详见 C-3 的说明。

- **H3｜发布物不得携带任何质量或性能声明。**
  方向 3 的模型质量为 `NO-GO`、云端 scorer 为 `NOT_QUALIFIED`、Plan 102 只交付 `ENGINEERING_SEAM_PASS`。
  Release notes、README 与仓库描述中不得出现任务解决率、准确率提升等未经验收的数字。
  实验性能力必须显式标注默认关闭。

- **H4｜转 public 前必须完成公开前复核，并由用户逐项知情确认。**
  转 public 不可逆——**即使事后转回 private，已经存在的克隆和缓存无法收回**。复核范围为四项：

  1. **密钥**：已完成的前置扫描结论为 1272 个 commit 全量扫描 API key / token / 私钥模式，
     自有目录（`eval/` `training/` `plan/` `agent_log/` `doc/` `scripts/`）零命中；`mydev/`、`multidev/` 内
     命中全部为上游 Codex 自带的测试假数据；`.env.local` 与 `rondo.local.toml` 从未被跟踪；
     `eval-data/`、`test-data/`、`reference-agent-harness/`、`rondo-backup-20260827/` tracked 文件数均为 0。
     **阶段 D 前必须重跑**（期间可能有新提交），结果留档。
  2. **提交身份**：全历史 author/committer 为两个邮箱（`3528349734@qq.com`、`sjc786526@gmail.com`）。
     公开后任何人可见。这是每个公开 GitHub 仓库的常态，但需用户知情确认；
     若不接受，唯一手段是改写全历史，**本任务不做，需另立任务**。
  3. **个人环境信息**：`doc/development-environment.md` 含本机绝对路径、Windows 用户名、硬件配置与代理配置。
     执行者在 D-3 备好**具体脱敏 diff** 供用户批准，不把选择题原样抛回。
  4. **再分发边界**：确认 `training/` 内受跟踪的数据集、`eval/results/` 内的测评结果不含第三方受限材料，
     可以公开再分发。

  以上四项完成后取得用户明确的转换确认，方可执行 D-5。

- **H5｜CI 不得调用 `scripts/with-build-lock.sh`。**
  该脚本会检查 Windows `C:` 盘余量、cgroup 与构建锁，在 GitHub runner 上必然 fail-closed。
  CI 直接使用 cargo；runner 是一次性环境，本就不需要本地那套资源看门狗。
  反之，**本地重型构建仍必须走 build lock**，本任务不放宽本地规则。

- **H6｜CI 不得引入需要密钥的步骤。**
  不配置任何 repository secret，不访问付费 API、不加载真实模型、不启动 Docker、不申请云 GPU。
  CI 只做编译与离线测试。

- **H7｜不得为了让 CI 变绿而弱化测试、跳过断言或缩减断言强度。**
  若某测试在 runner 上无法运行（资源/平台限制），只能将其**排除出 CI 范围并在工作流中显式注明原因**，
  不得修改测试本身。skip 与未运行不得表述为通过。

- **H8｜两条产品线的发布互不夹带。**
  `local-v*` tag 只构建与发布 `mydev/`，`multi-v*` tag 只构建与发布 `multidev/`。

- **H9｜发布物必须是完整产品包，不是裸二进制。**
  canonical 产品包除入口可执行文件外还包含 `codex-code-mode-host`、Linux 的 `bwrap`、
  受支持 Unix 的 `zsh`、`rg` 与 `codex-package.json`（见 `<product>/scripts/codex_package/README.md`）。
  必须复用 `<product>/scripts/build_codex_package.py` 生成，不得自行拼装。
  裸二进制通过 `--version` 不等于产品功能完整。

- **H10｜Release 归档必须包含许可材料。**
  每个归档内需含 `LICENSE`、对应产品的 `NOTICE`，以及**自建的 `THIRD-PARTY-LICENSES/`**。
  已核实：**打包器只搬可执行文件，不搬任何许可文本**，因此第三方许可必须由发布流程自己补齐，
  不得假设 canonical 打包器已经处理。清单见 C-4。
  覆盖范围**不止外部资源**：还必须包含两个最终二进制的 **Cargo 依赖闭包**（含 V8 / ICU），
  由锁文件按目标平台一条命令生成。
  这既是 Apache-2.0 §4 对再分发的要求，也是随包分发 LGPL 组件（bubblewrap）与
  MIT/BSD 类静态链接依赖的强制条件。

- **H11｜不得把测试专用的受控判官服务当作产品判官发布。**
  `codex-publication-critic-service`（受控测试服务）与 `-real-service` / `-cloud-service` 用途不同，
  发布物与文档中不得混淆。

- **H12｜Linux 发布物必须真正启用 bundled bwrap 完整性校验。**
  `CODEX_BWRAP_SHA256` 是**编译期**注入的；缺失时 `verify_digest()` 直接返回 `Ok(())`，
  校验被静默跳过且常规 smoke test 照样通过。因此构建顺序（bwrap → strip → 摘要 → 导出 → 构建 codex）
  是安全控制的一部分，不得调换，也不得依赖打包器的内部构建代劳。
  必须以 A14 的**可判定篡改测试**证明校验确实生效——尾部追加一字节、先确认该 bwrap 自身仍可执行、
  再断言出现 `bundled bubblewrap digest mismatch` 这一具体错误。
  "改一个字节后产品报错"不足以采信（坏掉的 ELF 本来就跑不起来，属假阳性），
  更不得以"命令没报错"当作通过。

---

## 4. 软性建议

以下内容是基于现有代码给出的执行建议，不是固定约束。执行者可依据实测采用更优方案。

- **CI 缓存**：使用 `Swatinem/rust-cache`，按产品线分 cache key（`rondo-local` / `rondo-multi`），
  避免两条产品线互相污染缓存。
- **CI 测试范围起点**：建议从小开始并实测，不要一上来跑全量 workspace。
  起点建议 `-p codex-publication-critic -p codex-features`（Multi）与 `-p codex-core --lib`（Local，若时间允许）。
  跑通并记录实测时长后，再按 A3 的时间预算决定是否扩容。
- **构建参数**：GitHub 标准 runner 为 4 vCPU / 16 GB，而本项目本地全量构建需 `MemoryHigh=21G` / `jobs=1`。
  建议 CI 使用 `CARGO_BUILD_JOBS=2`、`CARGO_PROFILE_DEV_DEBUG=0`（或 `-C debuginfo=0`）降低链接期内存峰值。
  若仍 OOM，优先拆分 job 而不是扩大 runner。
- **V8 依赖**：需要 V8 的测试要经 `<product>/scripts/with_codex_v8_artifacts.py` 获取 checksum 校验过的产物
  （联网下载）。建议 CI 的初始测试子集**避开需要 V8 的用例**，把 V8 相关留给本地全量门禁。
- **RUST_MIN_STACK**：产品 justfile 使用 `8388608`；若 CI 出现栈溢出，优先对齐该值。
- **平台**：首发只做 `x86_64-unknown-linux-musl`（KD-009）。选 musl 是为了避免分发出去的二进制
  依赖特定 glibc 版本；若 musl 工具链在 CI 上不通，按 R9 退回 gnu。
  工作流仍写成 matrix 形状（只含一个条目），日后要加 `aarch64-unknown-linux-gnu` 之类只需加一行。
- **Release notes 生成**：建议从 `<product>/CHANGELOG.md` 的对应版本段落提取，而不是自动汇总 commit message
  （本仓库 commit 粒度很细，自动汇总噪音大）。
- **产物命名建议**：`rondo-<version>-<target>.tar.gz` / `rondo-multi-<version>-<target>.tar.gz`，
  归档内可执行文件名为 `rondo` / `rondo-multi`。Windows 用 `.zip` 与 `.exe`。

---

## 5. 路线图

五个阶段串行推进。每个阶段有独立的退出条件，任一阶段可以单独停下而不留下半成品。

### 阶段 0｜环境与凭据前置（已于 2026-09-01 核验）

实施前所需的环境已实测确认，**只缺一项工具，且不需要用户做任何登录或授权操作**。

| 项 | 状态 | 说明 |
|---|---|---|
| `gh` CLI | ✅ 2.96.0 | |
| GitHub 认证 | ✅ `sjc786526-coder` | token scopes：`gist, read:org, repo, workflow` |
| └ `repo` scope | ✅ | 建 Release、改仓库可见性所需 |
| └ `workflow` scope | ✅ | 推送 `.github/workflows/*` 所需，**缺了会被 GitHub 拒绝推送** |
| 仓库权限 | ✅ `ADMIN` | 可改可见性 |
| GitHub Actions | ✅ 已启用 | `allowed_actions: all` |
| SSH 推送通道 | ✅ 已实测 | `git@github.com` 认证通过 |
| Rust 工具链 | ✅ 1.95.0 | |
| `x86_64-unknown-linux-musl` target | ✅ 已安装 | |
| `musl-gcc` | ✅ musl-tools 1.2.4-2 | |
| `strip` / `sha256sum` / `tar` | ✅ | |
| 网络（api.github.com 等） | ✅ | V8 / rg / zsh 产物下载可达 |
| **`cargo-about`** | ❌ **未安装** | C-4 生成 Rust 依赖许可报告所需 |
| Docker | ⚠️ 守护进程未运行 | **本任务不使用**，见下 |

**唯一缺口 `cargo-about`**：执行时用 `cargo install cargo-about --locked --version <锁定版本>` 安装即可。
这属于普通依赖下载，在已授权任务内可自主执行，**不需要用户介入**。

**Docker 明确不用。** 原计划的"干净环境 smoke test"改为在 **CI 里新开一个 job**：
从 Release 下载自己刚发布的产物、在全新 runner 上解压运行。这比 Docker 更干净（runner 本就是一次性的）、
免费、自动，还顺带演示了"验证自己的发布物"这一发布工程实践。
本地可再用 `env -i` + 临时 `HOME` 作补充验证。**因此本任务不触发 Docker 授权门。**

**结论：不需要用户登录或配置任何东西。** 现有凭据足以完成从 CI、Release 到转 public 的全部动作。

---

### 阶段 A｜发布身份收口（低风险，纯配置）

**目标**：让仓库在不触碰产品源码的前提下具备对外发布的身份。

| 步骤 | 动作 | 验证 |
|---|---|---|
| A-1 | `README.md` 重写为对外门面版 | ✅ 已完成（本计划前置步骤） |
| A-2 | 两条产品线的 `codex-cli/package.json` 加 `"private": true`，`name` 改为 `rondo-cli` / `rondo-multi-cli` | 确认无任何测试或脚本读取该 `name` 字段 |
| A-3 | 重写 `mydev/CHANGELOG.md`、`multidev/CHANGELOG.md` 为 RONDO 自己的记录，首条为 `0.1.0` | 内容不含性能声明（H3） |
| A-4 | 在 README 中加一句说明：`mydev/.github`、`multidev/.github` 是继承自上游的惰性文件，GitHub 只读根 `.github/workflows/` | 说明准确 |
| A-5 | **（窄例外 E-X1）** 在两条产品线的 `codex_package/targets.py` 的 `PACKAGE_VARIANTS` 中各新增一个变体：`cargo_bin="codex"` 保持不变，`executable_stem` 设为 `rondo` / `rondo-multi` | 跑 `codex_package/test_layout.py`、`test_archive.py`；确认既有 `codex` 变体行为不变 |
| A-6 | **（窄例外 E-X2）** 把 `check_for_update_on_startup` 默认值改为 `false`，更新受影响的 config requirements 层与快照 | 见下方专项验证 |

**A-6 的专项验证**（这是本任务唯一改动产品运行时行为的步骤，必须闭合）：

1. 跑 `mydev` / `multidev` 的 config 相关测试与快照测试，全绿；快照更新须逐条人工确认语义正确
2. 确认 `eval/rondo_eval/binary_freeze.py` 的冻结断言仍成立（A12），且公平对比设施未因该改动失效
3. 确认改动只涉及默认值与其连带快照，**未触碰** workspace 版本、crate 名、`[[bin]]` 名（A11）
4. 若第 2 项不成立，**立即回退 A-6**，转用 R7 的回退方案

**退出条件**：`git diff` 只涉及本阶段列出的文件与两处窄例外；`eval/**` 零改动。

---

### 阶段 B｜CI 流水线

**目标**：push 到 `main` 时自动验证两条产品线的健康度。

| 步骤 | 动作 | 验证 |
|---|---|---|
| B-1 | 新建根 `.github/workflows/ci.yml`，按**三类路径**分流（见下），不是两类 | 三类路径各验证一次触发结果 |
| B-2 | 加 `fmt` 门禁（`cargo fmt --check`），不需要编译，最快反馈 | 故意引入格式错误 → CI 红 |
| B-3 | 加 `build` 门禁 + `Swatinem/rust-cache`，按产品线分 cache key | 二次运行明显快于首次 |
| B-4 | 加 `test` 门禁，范围从软性建议的起点开始，**实测并记录时长** | 故意引入断言失败 → CI 红 |
| B-5 | 按 A3 的时间预算调整测试范围；把最终范围与"为什么不是全量"写进 `ci.yml` 的注释 | 说明诚实、可核查 |
| B-6 | 供应链与权限加固：第三方 Action 固定到 commit SHA；工作流默认 `permissions: contents: read` | 无浮动 tag 引用；无多余权限 |

**B-1 的三类路径**（只分两类会漏掉共享变更，导致改了共享设施却两个 job 都不跑）：

| 路径 | 触发 |
|---|---|
| `mydev/**` | 只跑 Local |
| `multidev/**` | 只跑 Multi |
| 根 `.github/**`、`scripts/**`、`eval/**`、`justfile`、根配置文件 | **两条都跑** |

**退出条件**：A1–A3 达成；三类路径的触发行为各验证一次；至少验证过一次"故意弄红"。

**风险点**：OOM 与超时。见 §8。

---

### 阶段 C｜Release 流水线

**目标**：打 tag 即自动出多平台产物。

| 步骤 | 动作 | 验证 |
|---|---|---|
| C-1 | 新建根 `.github/workflows/release.yml`，按 tag 前缀分流（H8）；tag 必须匹配**完整 SemVer**而非通配（见下方 tag 约定）；工作流默认 `permissions: contents: read`，**只有创建 Release 的 job 显式提升为 `contents: write`** | 打 `local-v*` 不构建 multidev；畸形 tag 被拒绝；非发布 job 无写权限 |
| C-2 | 构建 `x86_64-unknown-linux-musl`（musl 避免 glibc 版本依赖；上游亦为此备有 `install-musl-build-tools.sh`）。**首发只发 Linux**，见 KD-009 | 目标在 `TARGET_SPECS` 内；工作流保留 matrix 结构以便日后加目标 |
| C-3 | **按下方冻结顺序打包**：V8 就绪 → (Linux) 构建并 strip `bwrap`、算摘要并 `export CODEX_BWRAP_SHA256` → 构建 `codex` 与 `codex-code-mode-host` → 三者全部经 `--entrypoint-bin`/`--code-mode-host-bin`/`--bwrap-bin` 传入，只生成 `--package-dir`（H9、H12、KD-002） | 包内三个产物 SHA-256 与预构建一致；打包器未自行 `cargo build`；入口名为 `rondo`/`rondo-multi` |
| C-4 | 向该**包目录**注入 `LICENSE`、对应产品的 `NOTICE` 与自建的 `THIRD-PARTY-LICENSES/`（H10，清单见下） | 注入发生在归档生成之前 |
| C-5 | 从注入后的包目录生成归档，**解包复验许可文件确实在内**，再生成 `SHA256SUMS` | 解包后许可材料齐全；校验和与产物匹配 |
| C-6 | 创建 Release，notes 从 CHANGELOG 提取，附实验性与无性能承诺声明（H3），写明判官后端不在包内（KD-013）与 bubblewrap 源码/许可说明；**`-rcN` 必须 `prerelease=true` + `make_latest=false`** | notes 合规；rc 不会被标成 latest |
| C-7 | **干净环境 smoke test**：在未装过 RONDO 的容器/机器上解压运行 `--version`、一条触碰 arg0/sandbox 的命令、一条依赖 `rg` 或 `code-mode-host` 的功能；Linux 另做 **bwrap 篡改测试（可判定版，见下）** | A6、A7、A14 达成 |

**C-4 的第三方许可清单**（打包器目前**只搬可执行文件、不搬任何许可文本**，必须自建，不能假设它已处理）：

| 随包组件 | 平台 | 许可文本来源 |
|---|---|---|
| bubblewrap 0.11.2 (`bwrap`) | 仅 Linux | `<product>/codex-rs/vendor/bubblewrap/COPYING`（**LGPL-2.0-or-later**；`LICENSE` 只是指向 `COPYING` 的符号链接，**只需分发一份**） |
| ripgrep (`rg`) | 全平台 | 不在本仓库内，经 `scripts/codex_package/rg` 的 DotSlash 清单下载；需从 ripgrep 上游取 MIT / UNLICENSE 文本 |
| patched zsh | 仅受支持 Unix | 不在本仓库内，经 `scripts/codex_package/codex-zsh` 的 DotSlash 清单下载；需取 zsh 许可文本 |
| **`rondo` / `rondo-multi` 的 Cargo 依赖闭包** | 全平台 | 由锁文件按目标平台生成（见下） |
| **`codex-code-mode-host` 的 Cargo 依赖闭包**（含 **V8 / rusty_v8** 与 **ICU 数据**） | 全平台 | 同上；`code-mode-runtime` 直接依赖 `v8`（`v8_enable_sandbox`）与 `deno_core_icudata` |

要求：**按平台只放该平台包内实际包含的组件**（Windows 包无 `bwrap`/`zsh`），
并在 `THIRD-PARTY-LICENSES/README` 里写清每个组件的名称、版本、来源与许可类型。
现有 `NOTICE` 只提到 Ratatui，不覆盖上述任何一项，不得当作已闭环。

**依赖闭包分两层，不能用一份报告糊过去：**

**第一层 · Rust 依赖** —— 用**固定版本**的 `cargo-about`，带 `--locked --target "$TARGET"`
对两个最终二进制各生成一次，输出到 `THIRD-PARTY-LICENSES/rust-dependencies-<target>.*`。
工具版本要写进工作流并锁定，不用浮动版本。
（不要用 `cargo-bundle-licenses` 替代：其当前版本缺 `--target` / `--locked` / `--manifest-path`，
兑现不了"按锁文件、按目标平台、按二进制"的要求。此项未在本机实测，属工具选型建议。）

**第二层 · V8 原生闭包** —— **`cargo-about` 覆盖不到**。它只能把 `v8 = "=150.4.0"` 看成一个 Cargo 包，
而实际链接进去的是**另行下载的预编译 `librusty_v8_<profile>_<target>.a`**，
其内容来自 `denoland/rusty_v8` 在 `submodules: recursive` 下检出的 V8 及其子模块原生代码
（见上游 `rusty-v8-release.yml`）。因此必须**另外**纳入：
`rusty_v8 v150.4.0` 对应源码标签的 V8 / 原生第三方 notices，以及 ICU 数据来源
（`deno_core_icudata`）。

做法仍保持轻量：两条生成命令 + 一份手写的 V8/ICU 出处说明，**不人工逐条整理 crate，不建合规系统**。
但**不得把 Cargo 报告当成 V8 原生闭包报告**。在两层都完成前，H10 / A6 不得判为达成。

**bubblewrap 需要额外说明**（它不是普通的随包外部程序）：`bwrap` 是把 vendored C 源码
**编译进 Rust 包装器**得到的——`codex-rs/bwrap/build.rs` 用 `cc::Build` 编译
`vendor/bubblewrap/*.c` 并把 `main` 重命名为 `bwrap_main`，由 `bwrap/src/main.rs` 调用。
因此 `THIRD-PARTY-LICENSES/README` 至少要记录：版本 `0.11.2`、许可 `LGPL-2.0-or-later`、
**它是编入包装器的源码组件而非独立外部程序**、对应源码位于同一 Release tag 的
`<product>/codex-rs/vendor/bubblewrap/`、构建入口为 `<product>/codex-rs/bwrap/build.rs`；
Release notes 另给出该源码链接与显著许可说明。不建复杂合规系统，但这几项必须写清。

**tag 约定**（`local-v*` / `multi-v*` 作为通配过宽，会让 `local-vfoo` 之类也触发发布）：

| 形态 | 正则 | Release 属性 |
|---|---|---|
| 正式版 | `^(local\|multi)-v(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$` | `prerelease=false`，`make_latest=true` |
| 预发布 | `^(local\|multi)-v(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)-rc[1-9][0-9]*$` | `prerelease=true`，`make_latest=false` |

核心版本段用 `(0|[1-9][0-9]*)` 而不是 `[0-9]+`，否则 `local-v01.2.3`、`multi-v1.02.3` 这类前导零会被接受
（SemVer 规范禁止）；RC 序号从 `1` 起，用 `[1-9][0-9]*` 排除 `-rc0` 与 `-rc01`。

workflow 的 `on.push.tags` 可以先用宽匹配，但 job 内必须**用上述正则显式校验并对不匹配的 tag fail**，
不得静默按正式版发布。

**C-3 / C-4 / C-5 的冻结顺序**（顺序错了许可文件不会进归档）：

```bash
TARGET=x86_64-unknown-linux-musl          # 首发唯一目标（KD-009）
MANIFEST=<product>/codex-rs/Cargo.toml
OUT=<product>/codex-rs/target/"$TARGET"/release
PKGDIR="$(mktemp -d)/pkg"

# ① 按 $TARGET（不是 host）取 V8 产物并校验 —— 见"必须点 1"
#    输出的两行必须写入 $GITHUB_ENV，只 print 到日志不生效
python3 - "$TARGET" >> "$GITHUB_ENV" <<'PY'
import sys
sys.path.insert(0, "<product>/scripts")
from codex_package.targets import TARGET_SPECS
from codex_package.v8 import fetch_codex_v8_artifacts, resolved_v8_crate_version
spec = TARGET_SPECS[sys.argv[1]]
a = fetch_codex_v8_artifacts(spec, version=resolved_v8_crate_version())
print(f"RUSTY_V8_ARCHIVE={a.archive}")
print(f"RUSTY_V8_SRC_BINDING_PATH={a.binding}")
PY

# ② 先构建 bwrap，strip 后算摘要并导出；必须在构建 codex 之前
cargo build --locked --target "$TARGET" --release --bin bwrap --manifest-path "$MANIFEST"
strip --strip-debug --strip-unneeded "$OUT/bwrap"
echo "CODEX_BWRAP_SHA256=$(sha256sum "$OUT/bwrap" | awk '{print $1}')" >> "$GITHUB_ENV"

# ③ 构建入口与 code-mode-host（此步才把摘要编进 codex）
cargo build --locked --target "$TARGET" --release \
  --bin codex --bin codex-code-mode-host --manifest-path "$MANIFEST"

# ④ 三个预构建产物全部显式传入；只生成包目录，不传 --archive-output
python3 <product>/scripts/build_codex_package.py \
  --target "$TARGET" --cargo-profile release --variant rondo-multi \
  --entrypoint-bin "$OUT/codex" \
  --code-mode-host-bin "$OUT/codex-code-mode-host" \
  --bwrap-bin "$OUT/bwrap" \
  --package-dir "$PKGDIR"

# ⑤ 注入许可材料（C-4）→ ⑥ 自行归档、解包复验、算 SHA256SUMS（C-5）
```

**七个必须点：**

1. **V8 产物必须按 `$TARGET` 取，不能用 host-aware 的包装器。**
   `<product>/scripts/with_codex_v8_artifacts.py` 的 `main()` 用的是 `spec = rustc_host()`——
   **按 `rustc -vV` 的 host 选产物**。Ubuntu runner 的 host 是 `x86_64-unknown-linux-gnu`，
   而首发目标是 `x86_64-unknown-linux-musl`；而 `v8.py` 的产物文件名严格含三元组
   （`librusty_v8_<profile>_<target>.a.gz`）。直接拿它包裹交叉编译，会**把 GNU 的 V8 链进 musl 目标**。
   必须按 `TARGET_SPECS[$TARGET]` 调 `fetch_codex_v8_artifacts` —— 上游的
   `setup-rusty-v8` action 也是显式传 `target` 的。
   本步骤在**工作流层**完成（import 现有模块即可），**不改 `with_codex_v8_artifacts.py`**，
   因此不扩大 E-X1 范围。
2. **两个环境变量必须写进 `$GITHUB_ENV`，不能只 print。**
   `RUSTY_V8_ARCHIVE`、`RUSTY_V8_SRC_BINDING_PATH` 与 `CODEX_BWRAP_SHA256` 都要被**后续 step 的 cargo**
   读到；GitHub Actions 里每个 step 是独立 shell，只输出到日志不会传递。
   （若日后新增非 Linux 目标，bwrap 相关步骤必须加平台分支——
   `cargo.py:validate_prebuilt_resource_inputs` 对非 Linux 传 `--bwrap-bin` 会直接
   `RuntimeError("--bwrap-bin is only supported for Linux targets.")`。首发单一 Linux 目标不涉及。）
3. **bwrap 摘要必须在构建 `codex` 之前注入——这是安全控制，不是顺序洁癖。**
   `linux-sandbox/src/bundled_bwrap.rs` 的 `expected_sha256()` 读的是**编译期** `option_env!("CODEX_BWRAP_SHA256")`；
   取不到就返回 `None`，而 `verify_digest()` 拿到 `None` 直接 `return Ok(())`——
   **bundled bwrap 的完整性校验被静默跳过**。若先构建 `codex`、再让打包器构建 bwrap，
   发布出去的二进制就是"永不校验 bwrap"的版本，**而且任何常规 smoke test 都照样通过**。
   摘要必须对 **strip 之后**的字节计算，因为入包的就是那份字节（与上游 `rust-release.yml` 的顺序一致）。
4. **三个预构建 Cargo 产物全部显式传给打包器。** 否则打包器会自行 `cargo build`
   （`cargo.py` 的内部调用**不带 `--locked`**），既绕过锁文件，也会重新引入第 1 点的顺序问题。
   全部传入后 `binaries` 为空，内部构建被完全跳过。
5. **`--target` 与 `--profile release` 必须显式固定。** 裸 `cargo build --bin codex` 在 Linux runner 上
   产出的是 host GNU 的 **debug** 二进制；而 `--entrypoint-bin` 只检查文件存在且可执行，
   **不校验架构与目标平台**，打包元数据却仍按 `--target` 写入。不固定就会把 GNU debug 二进制
   包装成"musl release 包"。打包器的 `--cargo-profile` 默认是 `dev-small`，也必须显式改为 `release`。
6. **打包器不得同时收到 `--archive-output`。** 它在构造并校验包目录后会**立即**生成归档
   （`cli.py` 的 `for archive_output in args.archive_output: write_archive(...)`），
   之后再注入许可文件就进不了那个归档。必须只生成 `--package-dir`，注入后自行归档。
7. **归档后解包复验**各预构建产物的 SHA-256 与许可文件，不以"命令没报错"当作通过。

> V8 说明：`code-mode-runtime` 依赖 `v8`（`v8_enable_sandbox`）与 `deno_core_icudata`，
> 因此 `codex-code-mode-host` 内含 V8 与 ICU。自行预构建时必须先备好 checksum 校验过的 V8 产物，
> 不能依赖打包器内部那次已被跳过的构建来处理。

**C-3 为什么必须预构建入口（否则打包会失败）**：

打包器内部对入口二进制的"构建"与"查找"用了两个不同的名字：

- `cargo.py:source_binaries_for_target` 用 `variant.cargo_bin` 构建 → 产出 `target/<triple>/<profile>/codex` ✅
- 同文件随后用 `output_dir / variant.entrypoint_name(spec)` 查找 → 找 `target/<triple>/<profile>/rondo-multi` ❌

所以只新增一个 `cargo_bin="codex"` / `executable_stem="rondo-multi"` 的变体、直接跑打包器，**会在查找阶段失败**。

规避方式是走打包器已有的 `--entrypoint-bin`（其 help 原文即"Optional prebuilt entrypoint executable for the
selected package variant"）：传入后 `build_entrypoint=False`，cargo 不再尝试构建不存在的 `--bin rondo-multi`，
而 `layout.py` 仍按 `entrypoint_name` 把它复制成 `bin/rondo-multi`。

**这条路径的好处是 E-X1 可以保持纯追加**——只往 `PACKAGE_VARIANTS` 加一个 dict 条目，不改 `cargo.py`，
因此不需要为 `cargo_bin != executable_stem` 补 `test_cargo.py` 回归。
C-3 必须实测这条准确路径，不得假设默认路径可用。

**A14 篡改测试为什么必须是"尾部追加 + 断言具体错误"**：

"随便改一个字节然后看产品是否拒绝"**证明不了摘要校验生效**——被改坏的 ELF 本来就可能无法执行，
拒绝的原因可能只是"跑不起来"，与摘要无关，这是假阳性。可判定的做法是：

1. 向 `codex-resources/bwrap` **尾部追加一字节**：ELF 加载器忽略尾部多余数据，
   文件**仍可直接执行**，但 SHA-256 已改变；
2. 先单独运行篡改后的 `bwrap`，**确认它自身仍能跑**（排除"跑不起来"这个混淆因素）；
3. 再经产品触发 bundled bwrap；
4. 断言输出中出现 `bundled_bwrap.rs` 定义的具体错误
   **`bundled bubblewrap digest mismatch`**，而不是任何其他失败。

只有第 4 步命中，才能证明 `CODEX_BWRAP_SHA256` 真的编进了二进制。

**为什么 C-7 是硬性步骤**：`arg0` 通过 symlink `current_exe` 创建 `codex-linux-sandbox` 等 helper 别名
（`arg0/src/lib.rs`），代码上不依赖主二进制的文件名，因此换 `executable_stem` **预期安全**——
但这是推理不是证据，必须实测。而且 `--version` 能跑**不代表产品完整**（H9），所以 smoke test
必须至少覆盖一条依赖附属组件的功能。若 smoke test 失败，走 §8 的 R2。

**退出条件**：A4–A7 **与 A14** 达成。**先用预发布 tag（如 `multi-v0.1.0-rc1`）跑通整条链**，
确认无误后再打正式 tag，避免污染正式版本号。

---

### 阶段 D｜公开与首次发布

**目标**：仓库对外可见，两条产品线各发一个版本。

| 步骤 | 动作 | 验证 |
|---|---|---|
| D-1 | **重跑**密钥历史全量扫描（H4），结果留档到本次 agent_log | 零命中 |
| D-2 | 复核 `.gitignore` 与 `git ls-files` 输出，确认重资产目录 tracked 文件数仍为 0 | `eval-data/` `test-data/` 等为 0 |
| D-3 | 按 H4 的四项逐一复核，并**为每项准备好可直接采纳的具体结论与建议**（不是把问题抛回给用户）：密钥扫描结果、提交邮箱、`doc/development-environment.md` 的脱敏**具体 diff**、`training/` 与 `eval/results/` 的再分发结论 | 四项各有明确结论与建议动作 |
| D-4 | 通读 README 与仓库描述，确认无 H3 违规 | 人工确认 |
| D-5 | 把 D-3 的四项结论 + 建议 + 不可逆性，**一次性整理成一份可直接批准的清单**呈给用户；获批后执行转换 | A8 达成 |

**D-3 / D-5 的执行方式（重要）**：这四项复核**全部是项目内只读检查，不需要额外授权**，
执行者应当自主完成到"只差用户点头"的程度。呈给用户的必须是：
每项已经查完的结论 + 明确的推荐动作（例如"建议把 `C:\Users\35283` 替换为 `<Windows 用户名>`，
代理配置整段删除，diff 如下"），用户只需批准或否决，**不应从零开始做决策**。
| D-6 | 打 `multi-v0.1.0` 与 `local-v0.1.0`，等待流水线完成 | A9 达成 |
| D-7 | 下载正式 Release 产物，重跑一次 C-7 的 smoke test | 产物真实可用 |

**退出条件**：A8、A9 达成。

**授权门**：D-5 是本任务唯一不可逆的对外动作，**必须单独确认，不包含在一次性执行授权内**。

---

### 阶段 E｜文档回写与收口

| 步骤 | 动作 |
|---|---|
| E-0 | 更新 README 的安装一节：把"目前只提供源码构建 / 预编译二进制会随首个 Release 提供"换成**真实下载链接与安装步骤**；同步说明包内容与判官后端边界 |
| E-1 | `doc/WBS.md` 增加"发布工程"条目，记录当前发布能力、两条发布轨的约定、以及 E-X1/E-X2 两处窄例外；不复制本计划细节，只留指针 |
| E-2 | 更新 `CLAUDE.md` / `AGENTS.md`：把"不使用 CI 和 PR"改为"使用轻量 CI 作为门禁；仍不使用 PR 流程" |
| E-3 | `doc/WBS-COMPLETED.md` **追加**本次成果与证据（只追加，不改写既有条目） |
| E-4 | 写 `agent_log/` 执行日志：实质改动、CI 范围取舍的实测依据、smoke test 结果、A-6 的验证结论、遇到的问题 |
| E-5 | 冻结本计划，交接指向 WBS |

**退出条件**：A10 达成；全部验收项复核通过。

---

## 6. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。
> **维护约定**：本节与 §7 关键决策记录是本计划仅有的两个"活"章节，随任务进度实时更新；
> 执行细节、反复过程与证据留在 `agent_log/`，便于追溯与审查，不堆进本计划。

### 已完成

- 前置调研：仓库历史密钥扫描（零命中）、体积核算（`.git` 45 MB）、重资产跟踪状态核查（tracked 为 0）
- 前置调研：确认 `binary_freeze.py` 对 workspace 版本与二进制名的硬耦合（形成 H1、H2、KD-001、KD-002）
- 前置调研：确认 `multidev/justfile:139 test-github-scripts` 依赖 `.github/scripts`，
  且 `v8_canary_changes.py` 引用 `.github/workflows/*.yml` 路径（形成 KD-005，撤销原"删除上游 .github"步骤）
- 前置调研：确认 `arg0` 通过 symlink `current_exe` 建立 helper 别名，不依赖主二进制文件名（形成 C-7 的验证要求）
- 阶段 A-1：`README.md` 已重写为对外门面版

**第一轮独立审查（外部模型）后的修订**，以下结论均已复核证据后采纳：

- 判官语义在 README 中被写成发布门，实为有界改写机制
  （证据：`publication_review.rs:469`、产品合同 §4）→ 已改 README，形成 KD-015
- 原计划只发布裸二进制，但 canonical 产品包还含 `code-mode-host`/`bwrap`/`rg`/`codex-package.json`
  （证据：`codex_package/README.md`）→ 改用打包器，形成 H9、修订 KD-002
- 判官后端是独立二进制，不在主 CLI 内（证据：`publication-critic/Cargo.toml`）→ 形成 KD-013、H11
- 发布物会引导用户安装上游 `@openai/codex`
  （证据：`tui/src/updates.rs:62`、`update_action.rs:41`）→ 形成 KD-012 与窄例外 E-X2
- 公开前复核只覆盖密钥，遗漏提交邮箱与 `doc/development-environment.md` 的个人环境信息 → 已扩写 H4
- Multi 产品与 Critic 资格被混为一谈 → 已改 README，形成 KD-014
- CI path filter 只分两类会漏掉共享变更 → 已改为三类，并补供应链加固（B-6）
- README 事实问题：`14,660` 基线归属未限定为 Multi、LOC 数字缺复现口径、"关闭态与上游一致"过宽、
  快速开始两段 `cd` 连续复制会失败、threshold 描述属已废弃的单标量路径 → 均已改
- 本计划自相矛盾：§2 禁改 `doc/WBS-COMPLETED.md` 而 E-3 要求更新它 → 已改为"仅追加"
- Release 归档缺少许可材料 → 形成 H10

**第二轮独立审查后的修订**，同样逐条复核证据：

- **打包默认路径跑不通**（真阻塞）：`cargo.py` 用 `variant.cargo_bin` 构建、却用 `variant.entrypoint_name`
  查找产物，两者在新变体下不一致 → C-3 改为 `cargo build` + `--entrypoint-bin` 两步，E-X1 得以保持纯追加
- **R7 回退方案与 A13 冲突**（真阻塞）：原方案允许恢复默认值后靠文档警告继续发布，但默认值为 `true` 时程序
  仍会实际查询上游 Release → R7 改为"E-X2 不通过则停止正式发布"，明确文档警告不能替代 A13
- **第三方许可未真正入包**（真阻塞）：已核实打包器**零许可处理**，而随包分发 bubblewrap(LGPL)、rg、zsh
  → 新增 C-4 清单，改写 H10，A6 加入 `THIRD-PARTY-LICENSES/`
- README "所有新增能力都受 gate 控制"不准确：已合入的行为保持型热路径优化默认生效
  （如 `router.rs` 的 `Vec<ToolSpec>` → `Arc<[ToolSpec]>`）→ 已改 README 表述
- README 复现命令无法复现整张表：`diff -rN` 不输出 `Files`/`Only in` → 拆成两条命令；
  实测后"新增条目"按文档口径应为 **16 / 140**（原表 17/141 未排除 `.git`），已据实修正表格
- 判官构建命令 `-p` 会连带构建受控测试服务 → README 改为逐个 `--bin`，并单列诊断/测试二进制
- 最终目标"不改变任何产品语义"与 E-X2 冲突 → 已在最终目标处写明两处例外
- "131 个 crate"只对应 Multi → README 改为"约 130（Multi 131、Local 129）"

**未采纳的一条**：审查建议把 E-X2 标为"待确认"，理由是缺少独立批准记录。
实际存在明确记录——用户在被直接问及是否批准该默认值改动后答复"批准"，并要求本轮只写进计划、暂不实施。
故维持 `已采纳`，并已在 §2 写明批准出处与范围。

**第三轮独立审查后的修订**（4 项全部复核属实并已修）：

- **预构建命令缺 target/profile**（真阻塞）：裸 `cargo build --bin codex` 在 Linux runner 上产出 host GNU
  **debug** 二进制，而 `--entrypoint-bin` 只检查存在与可执行、**不校验架构与目标平台**，打包元数据却按
  `--target` 写入；且打包器 `--cargo-profile` 默认为 `dev-small` 而非 `release`
  → C-3 固定 `--locked --target --profile release`，并要求核验入口 SHA-256
- **许可文件注入晚于归档生成**（真阻塞）：`cli.py` 在 `validate_package_dir` 后**立即** `write_archive`
  → C-3/C-4/C-5 顺序冻结为「只生成 `--package-dir` → 注入许可 → 自行归档 → 解包复验 → 算校验和」
- **bubblewrap 描述不准确**：已核实 `bwrap` 是 `build.rs` 用 `cc::Build` 把 `vendor/bubblewrap/*.c`
  **编入 Rust 包装器**（`main` 改名为 `bwrap_main`），不是随包的独立外部程序；版本 `0.11.2`；
  `LICENSE` 是指向 `COPYING` 的符号链接，只需分发一份 → C-4 已补齐这些事实
- **Release 权限 / rc 语义 / 回退与 A6 冲突**：→ C-1 加"仅发布 job 提升 `contents: write`"与完整 SemVer 校验；
  C-6 加 `prerelease`/`make_latest`；R2、R8 删掉"退回 `codex` 入口名"这条与 A6 冲突的出路，
  改为"停止发布或先改 A6"（与 R7 同一规则）

**第四轮独立审查后的修订**（3 项全部复核属实并已修）：

- **只冻结了入口二进制，没冻结完整包的 Cargo 产物**（真阻塞，且是**安全缺陷**）：
  已核实 `bundled_bwrap.rs` 的 `expected_sha256()` 读**编译期** `option_env!("CODEX_BWRAP_SHA256")`，
  缺失即 `None`，而 `verify_digest()` 拿到 `None` **直接 `Ok(())` 跳过校验**。
  原 C-3 先构建 `codex`、再让打包器自行构建 bwrap，发布物就是"永不校验 bundled bwrap"的版本，
  **且任何常规 smoke test 都会通过**。上游 `rust-release.yml` 的顺序是
  build bwrap → strip → sha256 → 导出 → 构建 codex，摘要覆盖的是 strip 后的字节。
  另已核实打包器内部 `cargo build` **不带 `--locked`**。
  → C-3 冻结完整顺序，三个 Cargo 产物全部显式传入使内部构建被跳过；新增 H12 与篡改测试 A14
- **许可清单未覆盖依赖闭包**（真阻塞）：`code-mode-runtime` 直接依赖 `v8`（`v8_enable_sandbox`）
  与 `deno_core_icudata`，即 `codex-code-mode-host` 内含 V8 与 ICU；两个最终二进制还静态链接大量
  MIT/BSD 类 crate → C-4 增加两行依赖闭包，明确用 `cargo about` / `cargo bundle-licenses`
  一条命令按锁文件生成，**不人工整理、不建合规系统**；H10、A6 同步扩范围
- **SemVer 正则接受前导零**：`[0-9]+` 会放过 `local-v01.2.3` → 核心版本段改为 `(0|[1-9][0-9]*)`，
  RC 序号改为 `[1-9][0-9]*`。影响面小，但改动是两个字符，无理由不改

**第五轮独立审查后的修订**（4 项全部复核属实并已修）：

- **V8 包装器按 host 而非 `$TARGET` 选产物**（真阻塞）：`with_codex_v8_artifacts.py` 的 `main()` 用
  `spec = rustc_host()`，而 `v8.py` 的产物名严格含三元组
  （`librusty_v8_<profile>_<target>.a.gz`）。Ubuntu runner host 是 `…-linux-gnu`、首发目标是 `…-linux-musl`，
  直接包裹交叉编译会**把 GNU 的 V8 链进 musl 目标** → 命令块改为在工作流层按
  `TARGET_SPECS[$TARGET]` 调 `fetch_codex_v8_artifacts`（与上游 `setup-rusty-v8` 显式传 target 一致），
  **不改产品脚本**，故不扩大 E-X1
- **冻结命令对 macOS 无条件走 Linux bwrap 路径**（真阻塞）：`cargo.py:validate_prebuilt_resource_inputs`
  对非 Linux 传 `--bwrap-bin` 会直接 `RuntimeError`，macOS job 必然失败
  → 命令块按平台分支，macOS 不构建 bwrap、不传 `--bwrap-bin`
  （**该分支已被后续 KD-009 取代**：首发不再发 macOS，只剩单一 Linux 目标）
- **Cargo 许可报告覆盖不到预编译 V8 的原生内容**：已核实 `v8 = "=150.4.0"` 实际链接的是另行下载的
  `librusty_v8_*.a`，其内容来自 `denoland/rusty_v8` 在 `submodules: recursive` 下检出的原生代码
  → C-4 拆成两层：固定版本 `cargo-about --locked --target` 生成 Rust 依赖报告，
  **另外**手写 rusty_v8 v150.4.0 的 V8 / ICU 出处与 notices；明确不得用 Cargo 报告冒充 V8 原生闭包报告。
  （`cargo-bundle-licenses` 缺 `--target`/`--locked` 一说未在本机实测，按工具选型建议记录）
- **A14 可能假阳性 + 阶段 C 退出条件漏 A14**：随机改字节可能只是让 ELF 跑不起来，与摘要无关
  → 改为"尾部追加一字节（ELF 仍可执行）→ 先确认其自身可运行 → 再断言出现
  `bundled bubblewrap digest mismatch` 具体错误"；阶段 C 退出条件补上 A14

### 阶段 A｜已完成（2026-09-01，全部验证通过）

| 步骤 | 结果 |
|---|---|
| A-2 | 两条产品线 `codex-cli/package.json` 改为 `rondo-cli` / `rondo-multi-cli` + `private: true`；顺带修正 `description` 与 `repository`（改名后原值即为错误陈述）。**验证**：`build_npm_package.py` 用自带常量 `CODEX_NPM_NAME` 构造清单，只继承 `license`/`repository`/`engines`/`packageManager`，无任何测试或脚本读取 `name` |
| A-3 | 两份 CHANGELOG 重写（原为指向上游 releases 页的单行）。首条 `## 0.1.0`，供 release 工作流按版本段提取 |
| A-4 | README 增加惰性 `.github` 说明，并把根 `.github/` 补进仓库结构树 |
| A-5 | **E-X1**：两条产品线各新增一个 `PackageVariant`（`cargo_bin="codex"` 不变）。**验证**：既有 13 个打包测试全绿；另写临时脚本实测新变体经 `build_package_dir`/`validate_package_dir` 产出 `bin/rondo`、`bin/rondo-multi`，元数据 `entrypoint`/`variant`/`target` 正确，既有 `codex` 变体产物不变 |
| A-6 | **E-X2**：`unwrap_or(true)` → `unwrap_or(false)`，同步修正 `config_toml.rs` 的文档注释（原文写"Defaults to `true`"，是 JSON schema 描述的来源），并用 `codex-write-config-schema` 重新生成两份 `config.schema.json`（各 1 行差异） |

**A-6 专项验证（四项全部闭合）：**

1. ✅ config 与快照测试全绿：Local `472 passed / 0 failed`，Multi `486 passed / 0 failed`；
   其中 `config::schema::tests::config_schema_matches_fixture` 单独复跑通过
2. ✅ A12：直接调用 `binary_freeze._validate_workspace_manifests()`，两条产品线均 `OK`
   （workspace 版本、`codex-cli`/`codex-code-mode-host`/`codex-bwrap` 的 package 与 bin 契约全部成立）
3. ✅ A11：`git status` 确认 `Cargo.toml`/`Cargo.lock` 零改动、`eval/` 零改动，
   改动面仅限 §2 允许清单加两处窄例外
4. n/a（第 2 项成立，无需回退）

### 阶段 B / C｜已落地待实跑

已写出并通过本地可验证部分：

- `.github/workflows/ci.yml`：三类 path filter（用 git diff 自算，**不引入第三方 action**）、
  fmt / build / test 三门禁、`actions/cache` 分产品线 key、`package-scripts` job、
  工作流级 `permissions: contents: read`
- `.github/workflows/release.yml`：SemVer 严格校验 job、冻结构建顺序、musl 工具链、
  三产物显式传入、许可注入→归档→**解包复验**→`SHA256SUMS`、
  独立 `verify` job（干净 runner，含 A7 与 A14）、仅 `publish` job 提升 `contents: write`
- `.github/scripts/collect-third-party-licenses.sh`、`.github/scripts/compose-release-notes.sh`
- `.github/licenses/`：`about.toml`、`about.hbs`、`v8-icu-NOTICE.md`、
  `vendor/`（ripgrep 15.2.0 与 zsh `77045ef8` 的许可原文，**入库避免发布期依赖第三方站点可达**）

**本地已验证**：两份工作流 YAML 可解析；`compose-release-notes.sh` 实跑产出正确；
`collect-third-party-licenses.sh` 的文件搬运与 fail-closed 行为正确。
**待 rc1 实跑验证**：musl 交叉编译链、V8 按 target 取产物、cargo-about 的实际 flag、
`codex sandbox` 在 runner 上的可用性、A14 篡改测试。

### 实施期的新发现（均已落地，不改变计划契约）

1. **musl 交叉编译远不止 `--target`**：上游 `install-musl-build-tools.sh` 需要 Zig 0.14.0、
   从源码编译 libcap、注入 zig cc/c++ shim 与整套 `CC`/`PKG_CONFIG` 环境；另需
   `AWS_LC_SYS_NO_JITTER_ENTROPY=1`。工作流直接复用产品树内该脚本，不重写。
   （原计划 R9 已预见需要它，但低估了规模。）
2. **上游 musl 用的是自建 XL runner**，本项目只能用 4 vCPU/16 GB 标准 runner，
   release 构建时长与内存是 rc1 的主要风险点。
3. **包布局识别不依赖入口文件名**：`install-context/src/lib.rs` 按目录名 `bin/` 与
   `codex-package.json` 存在性判定，因此改名 `bin/codex` → `bin/rondo-multi` 对
   `rg`/`code-mode-host` 解析安全。这把 C-7 的"预期安全"从推理升级为代码证据，但仍需实测。
4. **`codex doctor` 的 `search` 检查**会经包布局解析 bundled ripgrep，
   正好用作 A7 中"依赖附属组件的功能"这一条，比直接运行 `rg --version` 更贴近产品行为。
5. **bundled bwrap 只在 PATH 上没有可用 system bwrap 时才启用**（`launcher.rs`），
   因此 verify job 必须先断言 runner 上没有 system bwrap，否则 A14 会在错误代码路径上"通过"。
6. **本机磁盘余量成为实施约束**：项目从 343 GB 增至 357 GB（告警 350 / 主动停 365）。
   Local 冷构建改用 `CARGO_PROFILE_DEV_DEBUG=0`（target 仅 6.5 GB）；Multi 复用既有缓存、
   **不加该变量**，否则会因指纹变化触发全量重建。
7. **`codex doctor` 的更新检查不受 `check_for_update_on_startup` 约束**（见下方 KD-016）。
   这是实测发现，直接影响 A13 的判定，**需要用户决定是否扩大窄例外**。

### 实施期的本地实测（用真实二进制，先于 rc1 降风险）

用 multidev 既有 debug 产物 + 新构建的 `bwrap`，走 C-3 的准确路径打了一个本机包并实测：

| 检查 | 结果 |
|---|---|
| 打包器经 `--entrypoint-bin`/`--code-mode-host-bin`/`--bwrap-bin` 产包 | ✅ 产出 `bin/rondo-multi`，rg/zsh 经 DotSlash 正常下载 |
| `rondo-multi --version` | ✅ `codex-cli 0.147.0`（符合 KD-010 预期） |
| 包布局识别（改名后） | ✅ doctor 报 `runtime ✓` / `install ✓ consistent`，package/bin/resources/path 四个目录全部正确解析 |
| bundled ripgrep 解析 | ✅ `search ✓ file exists (bundled, …/codex-path/rg)`，`search provider bundled` |
| `rondo-multi sandbox -- /bin/echo` | ✅ 输出 `rondo-sandbox-ok`，exit 0；arg0 与 sandbox 在改名后均正常 |

**结论**：C-7 原本"预期安全但未实测"的三件事（改名不破坏 arg0、不破坏包布局识别、
附属组件仍可解析）已在本机取得实证，rc1 只需再验 musl 链、cargo-about 与 A14。

**同时确认了 verify job 那道守卫的必要性**：本机 PATH 上有 system `bwrap 0.9.0`，
按 `launcher.rs` 的优先级根本不会走 bundled 路径——若 runner 上也有，A14 会在错误的代码路径上"通过"。

### 当前工作

**终审后的用户决策与收口（2026-09-01）：**

- **不发 macOS**：用户只在 Linux 上开发与使用，无 macOS 环境可验证。首发收敛为单一
  `x86_64-unknown-linux-musl`（KD-009）。副作用是 C-3 的平台分支复杂度与 macOS runner 风险一并消失。
- **环境与凭据已实测核验**（阶段 0）：`gh` 已认证且 scopes 含 `repo` 与 `workflow`、仓库权限 `ADMIN`、
  Actions 已启用、musl target 与 `musl-gcc` 均在位、SSH 推送通道已验证。
  **唯一缺口是 `cargo-about`**，属普通依赖下载，执行时自行安装即可，不需要用户做任何登录或配置。
- **Docker 不再使用**：干净环境 smoke test 改为 CI 内新开 job 下载并运行自己发布的产物，
  比 Docker 更干净且免费。**本任务不触发 Docker 授权门。**
- **D-3/D-5 的执行方式已明确**：四项公开前复核全部是项目内只读检查，执行者自主完成到
  "只差点头"，呈给用户的是结论 + 具体建议（含脱敏 diff），而非选择题。

**规划阶段已完成并通过终审（2026-09-01）。** 用户已批准 KD-012（窄例外 E-X2）与 KD-007
（现仓库整体转 public），并同意先在 private 仓库用 `multi-v0.1.0-rc1` 实跑验证。

**当前进度（2026-09-01）**：阶段 A 已完成并验证；阶段 B/C 的工作流与脚本已写出，待实跑。
`check_for_update_on_startup` 默认值已改为 `false`（E-X2 已实施并验证）。
**远端仓库仍为 `PRIVATE`，尚未打任何 tag，尚未创建任何 Release。**

**实施时的一个已知落地点**（终审提示，非计划阻塞）：C-3 第①步的 V8 脚本必须把
`RUSTY_V8_ARCHIVE` 与 `RUSTY_V8_SRC_BINDING_PATH` **真正写入 `$GITHUB_ENV`**，
只打印到日志不生效。命令块注释已写明，实现时照此落地。

**关于 rc 实跑的准确表述**：`multi-v0.1.0-rc1` 会在远端创建 tag 与 prerelease，
不能称为"完全无对外后果"；但在 `prerelease=true`、`make_latest=false` 且仓库仍为 `PRIVATE` 的前提下
风险足够低，验证价值高于继续静态审查。

### 本任务剩余步骤

阶段 A 已收口。剩余：B-4/B-5（CI 实测时长并据此定范围）→ C 的 rc1 实跑与迭代 →
D（四项复核 + 用户确认 + 转 public + 正式 tag）→ E（文档回写）。

### 阻塞项

**规划层已无阻塞项**（KD-007、KD-012 均已获批）。仅保留一个**执行时的授权门**：

- **D-5｜转 public 的执行确认**：方向已由用户批准，但 H4 要求在**实际切换前**先完成四项复核
  （重跑密钥扫描、邮箱知情、`doc/development-environment.md` 脱敏决定、再分发边界），
  并就复核结论与不可逆性取得用户当场确认。该确认不含在一次性执行授权内，
  这是一个执行时的最终确认，不是尚未决定的规划问题。

### 当前验收状态

**规划验收：通过。** 五轮独立审查累计提出的全部阻塞项均已逐条复核证据并整改，
无遗留规划问题；两处窄例外（E-X1、E-X2）与可见性方案（KD-007）均已获批。

**实施验收：A1–A14 全部未达成**，尚未开始。A-1（README 对外门面版）已完成，但不单独构成验收项。

### 交接边界

本任务完成后冻结此计划；后续发布节奏、版本策略与是否补 Windows 平台等，只在 `doc/WBS.md` 的发布工程条目维护，
不在本计划继续规划。

---

## 7. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| KD-001 | 产品版本由 git tag 承载，**不改 Cargo workspace 版本号** | `binary_freeze.py:1301` 硬断言版本为 `0.147.0`，并用它做与上游的字节级规范化对比 | 全仓库；`--version` 输出保持 `0.147.0` | 已采纳 |
| KD-002 | 二进制改名只发生在**打包层**，通过新增 `PackageVariant`（`cargo_bin="codex"` 不变、`executable_stem="rondo"/"rondo-multi"`）实现；发布物必须是 `build_codex_package.py` 生成的**完整产品包** | ① `binary_freeze.py` 约 20 处硬编码 `"codex"`，历史 manifest 为不可变证据；② `targets.py:PackageVariant.entrypoint_name` 本就把入口名设计成变体参数，是产品自带的正规接缝；③ 裸二进制缺 `code-mode-host`/`bwrap`/`rg`，功能不完整 | 窄例外 E-X1；release 工作流 | 已采纳（原"cp 改名 + 发布裸二进制"方案**已废弃**） |
| KD-003 | 单仓库 monorepo + 两条发布轨（`local-v*` / `multi-v*`），CI 用 path filter 分流 | 研究叙事（两条并列产品线 + 共享测评设施）是项目最强的部分，拆仓会散掉；流水线写一次复用两次 | CI 与 release 工作流 | 已采纳 |
| KD-004 | npm 包不发布，两个 `codex-cli/package.json` 设 `"private": true` 并改名 | 现名为 `@openai/codex`，既无发布权限也不应占用该命名空间；`private` 可防误发 | 两个 package.json | 已采纳 |
| KD-005 | **不删除** `mydev/.github`、`multidev/.github` 的上游继承文件 | 原计划要删，调研后撤销：① `test-github-scripts` 依赖 `.github/scripts`，`v8_canary_changes.py` 引用 workflows 路径；② 项目刻意保持产品树与上游可直接比较，删 184 个文件只增加 diff 噪音；③ 它们在子目录中本就不会被 GitHub 执行。改为在 README 中一句话说明 | README；撤销原步骤 3 | 已采纳（原方案已废弃） |
| KD-006 | CI **不跑全量 workspace**，只跑受影响产品线的 crate 子集，范围由实测时长决定 | workspace 有 131（Multi）/ 129（Local）个 crate；GitHub 标准 runner 为 4 vCPU/16 GB，而本项目本地全量需 `MemoryHigh=21G` / `jobs=1`。全量在 runner 上有 OOM 与超时风险 | `ci.yml`；全量门禁仍留本地 | 已采纳 |
| KD-007 | 可见性方案取 **现仓库整体转 public** | 历史扫描零命中、`.git` 仅 45 MB、重资产目录 tracked 为 0，故原先推荐的"另建干净仓库"已无必要收益；而过程证据（WBS / plan / agent_log / audit-snapshots / eval results）恰是项目最有说服力的部分，另建仓库会丢失 | 阶段 D | **已采纳**（用户 2026-09-01 明确批准转 public；仍要求先完成规划、暂不执行） |
| KD-008 | 文档语言：中文为主 + README 顶部英文摘要 | 全部既有文档为中文，全量翻译成本高收益低；英文摘要足以让非中文读者判断项目性质 | README | 已采纳 |
| KD-009 | **首发只发 `x86_64-unknown-linux-musl` 一个目标**，不发 macOS，不发 Windows | 用户只在 Linux 上开发与使用，没有 macOS 环境可验证。**发一个自己无法验证的平台产物，比不发更糟**——用户装了跑不起来，你也复现不了。这同时消掉了 C-3 的平台分支复杂度（`--bwrap-bin` 仅限 Linux）与 macOS runner 的全部风险。工作流仍保留 matrix 结构，日后要加目标是改配置而非改架构 | `release.yml`；A5、C-2、C-3 | 已采纳（原"Linux + macOS 双平台"方案**已废弃**） |
| KD-010 | `--version` 显示 `0.147.0` 与 Release tag `v0.1.0` 不一致的问题，通过 **文档说明** 解决，不改代码 | KD-001 的直接后果。可在 README/Release notes 用一句话说明："内部版本号沿用上游冻结基线以支持字节级公平对比，产品版本见 Release tag" | README、Release notes | 已采纳 |
| KD-011 | 可选增强：由 release 工作流注入构建期常量，让二进制同时报告 `RONDO Multi 0.1.0 / based on Codex CLI 0.147.0` | 能消除 KD-010 的不一致观感，但需要改产品源码且触及版本展示逻辑，范围明显大于 E-X2 | 需另立任务 | **提议，本任务不做** |
| KD-012 | **窄例外 E-X2**：把 `check_for_update_on_startup` 默认值改为 `false` | 这是**发布级缺陷**而非观感问题：`updates.rs` 会查询 `api.github.com/repos/openai/codex/releases/latest`，`update_action.rs` 会提示用户执行 `npm install -g @openai/codex` / `brew upgrade --cask codex`。发布一个引导用户去装上游产品的 fork 不可接受。已确认该行为受配置控制且默认为 `true`（`config/mod.rs:4007 unwrap_or(true)`），翻默认值是最小改动，不触碰 H1/H2 | 窄例外 E-X2；需跑 config 与快照测试 | **已采纳**（用户 2026-09-01 批准该窄例外；本轮只记录，不实施） |
| KD-013 | 判官后端**不随 Release 分发**，只在文档中给出源码构建方式 | scorer 是独立二进制（`codex-publication-critic-{service,real-service,cloud-service}`），不在主 CLI 内。但本地后端依赖未分发的模型权重与运行时、云端后端需用户自备凭据，**即使打包也不是下载即用**；而且本地模型 `NO-GO`、云端 `NOT_QUALIFIED`，主动分发会暗示可用性 | README、Release notes；H11 | 已采纳 |
| KD-014 | 对外文档必须把 **RONDO Multi 产品** 与 **Publication Critic 子系统** 分层表述 | 混为一谈会让读者误以为整个 Multi 未获验收，既不准确（Multi 有 14,660 全量通过的正确性基线）也低估了项目价值；分层后既更诚实也更有说服力 | README（已改）、Release notes | 已采纳 |
| KD-016 | **`codex doctor` 仍会查询并提示上游 Codex 版本**，`check_for_update_on_startup` 管不到它 | 实测：即使显式写入 `check_for_update_on_startup = false`，`codex doctor` 仍输出 `↑ updates 0.152.0 available (current 0.147.0)`。读代码确认 `cli/src/doctor/updates.rs:88` **无条件**调用 `fetch_latest_version()` → `curl https://api.github.com/repos/openai/codex/releases/latest`；该文件只在第 36–40 行把配置值当作一条 detail **打印**出来，从不用它做门禁。对 fork 而言这条输出具有误导性：它把上游 Codex 的版本当作"你该升级到的版本" | **A13 的判定**；如需修复，涉及 `doctor/updates.rs`，超出 E-X2 已批准范围（§2 明确"不得顺带改动更新提示的其他逻辑"） | **待用户决定**（建议见下） |
| KD-015 | Publication Critic 在所有对外文档中必须表述为**有界改写机制**，不得表述为发布门或安全审批 | 已核实产品合同与实现（`publication_review.rs:469` `Some(Verdict::Rewrite) if attempt.review_index < 2`）：第三次审查非阻断，即使 `REWRITE` 也提交；服务故障时 fail-open 提交当前稿并记为"审核未完成" | README（已改）、Release notes | 已采纳 |

---

## 8. 风险与回退

| 编号 | 风险 | 触发信号 | 回退方案 |
|---|---|---|---|
| R1 | CI 在 GitHub runner 上 OOM 或超时 | job 被 killed / 超过 A3 的时间预算 | 依次尝试：① `CARGO_BUILD_JOBS=2` + `debuginfo=0`；② 拆成多个 job；③ 缩小 crate 子集。**不得改用更大的付费 runner，也不得删测试凑绿（H7）** |
| R2 | 产物改名后 arg0 / sandbox 行为异常 | C-7 smoke test 失败 | 先试：归档内同时提供 `rondo` 与上游原名的可执行文件（或 symlink），保持 arg0 兼容。**若仍失败则停止正式发布**——A6 强制要求入口名为 `rondo`/`rondo-multi`，不得一边退回 `codex` 入口名一边宣布验收通过；要退回必须先取得用户批准并同步修改 A6 |
| R3 | V8 依赖导致 CI 测试无法运行 | 测试因缺 V8 产物失败 | 把相关用例移出 CI 范围并在 `ci.yml` 注释说明原因（H7 允许排除但不允许修改测试） |
| R4 | 转 public 后发现遗漏的敏感内容 | D-5 之后发现 | **不可逆，只能事后补救**：立即转回 private 并轮换任何暴露的凭据。这正是 H4 要求在 D-1 重跑扫描、D-5 单独确认的原因 |
| R5 | 阶段 A 的 `package.json` 改动意外影响构建或测试 | 相关测试变红 | 该改动是纯元数据，直接回滚这两个文件即可；不影响其他步骤 |
| R6 | ~~可见性方案变更~~（KD-007 已确认，风险关闭） | —— | 保留记录：即使日后改为另建干净仓库，阶段 A–C 的产出（README、CHANGELOG、两个工作流）仍可直接迁移，只有阶段 D 需重写 |
| R7 | A-6 翻转更新检查默认值后，config requirements 层或快照测试大面积变红，或影响冻结对比设施 | 相关测试红 / A12 不成立 | **立即回退 A-6**，并**停止正式发布**：A13 是发布前置条件，不得以 Release notes 文字警告替代——默认值为 `true` 时程序仍会实际查询上游 Release 并可能引导安装 `@openai/codex`，文档挡不住这个行为。允许的出路只有两条：① 另找同样能保证"默认关闭"的技术方案（如 KD-011 的构建期常量）；② 把该问题降级为独立任务解决后再发布。期间可以继续用 rc tag 验证流水线，但不打正式 tag。**不得**为了让测试变绿而改测试（H7） |
| R8 | 新增 `PackageVariant` 影响既有 `codex` 变体或打包器测试 | `codex_package/test_*.py` 变红 | 该改动是纯追加，直接删除新增条目即可回退。但回退后 A6 不成立，**同样适用 R2 的规则**：停止正式发布，或先取得用户批准并修改 A6 |
| R9 | musl 目标在 CI 上构建失败（缺工具链或依赖不兼容） | release job 红 | 参考上游 `.github/scripts/install-musl-build-tools.sh` 补工具链；仍失败则首发退回 `x86_64-unknown-linux-gnu`，并在 Release notes 注明 glibc 版本要求 |

---

## 9. 本任务的"完整软件流程"覆盖清单

供收口时自检——这是本任务的履历价值所在：

- [x] **需求与范围界定**：本计划的目标、非目标、范围三节
- [ ] **版本管理**：semver、两条独立发布轨、tag 约定
- [ ] **变更记录**：两份 CHANGELOG
- [ ] **持续集成**：格式门禁、编译门禁、测试门禁、缓存、path filter 分流
- [ ] **持续交付**：多平台交叉编译、产物校验和、自动 Release
- [ ] **发布验证**：干净环境 smoke test
- [ ] **对外文档**：README（含安装、用法、实验性声明、许可与归属）
- [ ] **合规与归属**：Apache-2.0、上游 NOTICE、非背书声明、商标规避
- [ ] **安全**：密钥历史审计、忽略规则复核、CI 无密钥原则
- [ ] **可观测性与诚实性**：负向结果公开、无性能承诺、默认关闭实验能力
