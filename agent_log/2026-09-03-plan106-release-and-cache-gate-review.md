# Plan 106 第一阶段与缓存授权门独立验收（2026-09-03）

## 结论

`ACCEPT`。Plan 106 在强制删除授权门之前的工作做法正确，未发现需要整改的 correctness finding：
`multi-v0.1.1` 的候选、CI、tag、Release workflow、公开 Release、README 后置更新和权威状态记录彼此一致；
Multi 实质代码、测试口径、依赖、发布 workflow 与许可材料未被本任务修改，Plan 105 的最终全 workspace 结果继续有效。

缓存只读盘点覆盖了精确路径、符号链接、使用者、空间收益、重建代价和 WSL/VHDX 边界，删除方案合理。
本审查**不构成删除授权**，没有删除或修改任何缓存。当前正确停止状态保持为：

`RELEASE_VERIFIED / AWAITING_CACHE_DELETION_AUTHORIZATION`

状态拆分如下：

- 停止点验收：**通过**。
- Plan 106 第一阶段目标：**完成**。
- Plan 106 整体任务目标：**尚未完成，但没有失败**；只剩用户二次授权后的精确缓存删除、记录和最终复核。

## 审查范围与方法

本次只做 tracked diff、Git/远端身份、公开 GitHub 元数据、CD 文档、Release notes 和缓存现场的轻量复核。
没有重跑本地全 workspace，没有重新下载约 152 MB 归档，没有运行 Docker、真实 API/模型、训练、测评或其它重型任务，
也没有新建审计、可信、签名或证据设施。

## Git、范围与文档

- 主工作区 clean，`main == origin/main == e87aa3c8e96a42cf3b6867b83d1c5b2d5f1740d0`。
- 审查开始时，109 worktree clean 于 `f7b2f46c5d3034b5b1aaca2becb90f4aa0076e0d`，分支仍为
  `worktree-109-multi-v0.1.1-release-closeout`，worktree 未归档或释放。
- 候选 `29fb953e644611eb0a35f8817c97dc9edca2865f` 相对 Plan 106 基线只增加
  `multidev/CHANGELOG.md` 与 ExecPlan；发布后的差异只增加/修改 README、WBS、WBS-COMPLETED、Plan 动态状态和实施日志。
  `multidev/` 除 CHANGELOG 外零差异；release workflow、许可目录、许可/notes 脚本零差异；`git diff --check` 通过。
- CHANGELOG 如实覆盖 `/status` Guardian 配置摘要、根配置指南、`codex-team-state` CI 覆盖和 fuzzy-file-search
  Nextest 串行化；`14713/14713` 被限定为正确性与稳定性结果，没有新增质量资格、性能或生产承诺。
- README 只在公开复验后把 Multi 的下载、解压和入口路径切到 0.1.1；Local 仍为 `local-v0.1.0`。
- WBS 当前指针是 Plan 106 的精确缓存删除授权门；WBS-COMPLETED 只记录已完成的发布里程碑并明确“缓存收尾待补”，
  文档职责和停止状态正确。

## CI、tag 与公开 Release

远端 Git refs 复核：

- `origin/main` → `e87aa3c8e96a42cf3b6867b83d1c5b2d5f1740d0`。
- `multi-v0.1.1` tag 对象 → `2ae1fc1f23e22488771fd6050e1853bf37262583`；peeled →
  `29fb953e644611eb0a35f8817c97dc9edca2865f`，与候选一致。
- `multi-v0.1.0` tag 对象仍为 `d00df6b5f1666f5533ed1b61af4ba68f454095ba`；peeled 仍为
  `ce63cc1daa3424776717fbad24576376895cf863`。

未认证 GitHub REST 复核：

| run | workflow / head | 结论 |
|---|---|---|
| `33723597611` | `ci` / `29fb953e644611eb0a35f8817c97dc9edca2865f` | success；packaging、detect、`check (multi)` 三个 job 及其 steps 全部 success |
| `33724503639` | `release` / tag `multi-v0.1.1`，head `29fb953e…` | success；Validate、Build、clean-runner Verify、Publish 四个 job 及关键 steps 全部 success |
| `33731401389` | docs-only `ci` / `e87aa3c8e96a42cf3b6867b83d1c5b2d5f1740d0` | success；packaging 与 detect success，产品 check 按 path filter skipped，符合纯文档提交预期 |

公开 `multi-v0.1.1` Release 当前为非 draft、非 prerelease，`published_at == updated_at ==
2026-09-03T07:41:28Z`，两个资产均为 uploaded：

- `rondo-multi-0.1.1-x86_64-unknown-linux-musl.tar.gz`：151,675,378 B；GitHub 平台记录的 digest 为
  `sha256:090458103cbcb343e530eaecd2791f8dfe24a56ce1eb0aa5cb547caa06dc4e2c`。
- `SHA256SUMS`：117 B；未认证下载内容声明同一个归档摘要。

实施者已经从未认证公开下载字节完成归档、入口、版本、产品身份、19 项必需文件、17 份第三方许可和 6 条许可内容断言复验。
本审查不重复下载大包；GitHub 当前平台 digest、公开 `SHA256SUMS`、release run 的归档后复核与实施日志四者一致，足以复核该结论。

本审查另按 `doc/cd-release-pipeline.md` 重新渲染 0.1.1 正式 notes，并通过未认证 API 取得公开正文：两者均为
3923 B，SHA-256 均为 `c5fb94e403fe078c8cbcf330b4ea8a2636bcbf6736334fdd008b87ade09954dc`，逐字节相同。
实施者对 CD 文档不变量 I 的人工补检也覆盖了现行自动化缺口：三份 cargo-about 报告无 HTML 转义，原始许可短语存在。

历史 `multi-v0.1.0` Release 当前仍为非 draft、非 prerelease，`updated_at == published_at ==
2026-09-02T12:20:08Z`，两个历史资产的名称、大小、digest 和各自更新时间均无替换迹象。没有发现移动 tag 或改写历史 Release。

## 缓存删除方案复核

唯一候选目标仍是：

`/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`

当前轻量复核结果：

- `stat` 为真实目录（mode `0700`）；`readlink -f` 返回同一完整路径；`namei -l` 的每一段均不是符号链接。
- 实际分配空间 `du -sB1` 为 **257,889,263,616 B**，与实施记录逐字一致。
  审查初次使用 `du -sb` 得到 258,178,563,376 B；该选项统计 apparent size，而实施记录统计实际分配空间，
  改用同口径后完全一致，因此不是缓存漂移，也不是 correctness finding。
- `.codex/cargo-target/rondo-local` 的实际分配空间为 10,371,141,632 B，与实施记录一致，目录仍独立存在。
- 当前无 `cargo`、`rustc`、`cargo-nextest`、`nextest`、`ld.lld`/`lld` 进程；`lslocks` 未见持锁者，
  `fuser` 未见该目标使用者。实施者此前还完成了 build lock、RONDO scope、`lsof +D`、进程 cwd 等更完整的四路检查。
- `316,658,225,152 - 257,889,263,616 = 58,768,961,536 B`，所以删除后项目约 58.8 GB、
  350 GB 告警线余量约 291 GB 的估算成立。
- Multi 已冻结且下游 Local 使用独立 `rondo-local` target；删除只会让未来重新开展 Multi 重型任务承担一次冷编译，
  不阻塞当前 Local 阶段。WSL ext4 释放不会自动压缩 `.vhdx`、Windows `C:` 余量大概率不同步增长的提醒正确。
- 排除 Local target、retained test evidence、其它缓存、Docker、worktree 和父目录的边界明确，符合 WBS 与 Plan 106。

因此删除方案在功能、正确性、边界和收益上均合理。真正执行时仍应按 Plan 106 在删除前重新测量并复核无使用者，
只命中上述完整路径；这项审查意见不是用户的第二阶段删除授权。

## 审查决策

1. **接受第一阶段发布结果，不要求重跑本地全 workspace。** 本任务没有改变已冻结的 Multi 实质代码或测试口径，
   release workflow 已完成真实构建和 clean-runner verify，重复本地重型测试没有新增正确性价值。
2. **接受现有公开产物复验，不重复下载大归档。** 实施者已检查真实公开字节，本审查又独立确认公开平台 digest、
   SHA256SUMS、run identity、Release metadata 与 notes；轻量证据已经闭合。
3. **接受 docs-only CI 的产品 check skipped。** 它是现行 path filter 的预期结果，不冒充产品测试；发布前候选的
   `check (multi)` 已在 exact SHA 上真实成功。
4. **认可精确 Multi target 删除方案，继续保持授权门。** 用户若决定释放空间，可以只批准该完整路径；审查者无权代替用户授权。
5. **无整改要求。** 不修改已发布 tag/Release，不新增设施，不提前切换到 Local 实施，不把 Plan 106 标记为整体完成。

## 最终判定

- **验收状态（做得对不对）**：`通过 / ACCEPT`。
- **第一阶段目标（是否实现）**：`完成 / COMPLETED`。
- **Plan 106 整体任务目标**：`尚未完成，非失败 / PENDING AUTHORIZATION`。
- **当前项目状态**：`RELEASE_VERIFIED / AWAITING_CACHE_DELETION_AUTHORIZATION`。
