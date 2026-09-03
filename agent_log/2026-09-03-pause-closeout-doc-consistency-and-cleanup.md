# 停更前收口：文档一致性修正与无争议资产释放

日期：2026-09-03 ｜ 起点 `main` `898a8216` ｜ 工作树 `116-pause-closeout-doc-and-cleanup`

用户决定项目暂停开发数月，本批次只做「盘点后达成共识、无争议」的部分：修正文档中的事实矛盾与陈旧计数，
释放可再生或已完全冗余的资产。**不改动任何产品代码、测试、默认值、workflow 或发布物。**

## 一、文档修正

- `README.md:149` 的 Multi 正确性基线 `14,660 / 14,660` 改为 `14,713 / 14,713`。这是与同文件
  `README.md:69` 的真实矛盾：`14,660` 是 Plan 093 在**增量开启**下建立的历史基线，`14,713` 才是 Plan 105
  建立的当前基线。`doc/development-environment.md` 中的 `14660` 有明确的 Plan 093 历史标注，**未改动**。
- `README.md` 的未锚定计数器分两种处理。**提交数与执行日志数直接删除**：它们在写入的那次提交本身发生时
  就已失真（写日志、合并各再加一次），锚定不如移除，「开发周期」只保留起始日期，过程证据一句改为
  「逐批执行日志（`agent_log/`）」。任务合同数按现场更新 `97 → 98`（两处）并保留——它只在立新 plan 时变动，
  项目停更后稳定；同句的审计快照 5、研究报告 14、测评结果 67 三个数当前准确且同样不再变动，一并保留。
- **未改动**「相对上游基线的改动量」表格：该表已显式锚定 commit `d82a07f1` 并附复现方法，属于有标注的
  历史快照。今日实测值为 Local `+6,855 / −786`、142 改动文件、11 新增条目（清理后）；
  Multi `+90,481 / −1,506`、292 改动文件、142 新增条目。若将来要更新应整行替换并标注新快照，
  不能只改单个数字。
- `.gitignore` 移除 `/codex-doc/`。该规则与目录职责冲突：现有 7 个文件均已 tracked 不受影响，
  但会把以后新增的文档快照静默隐藏。
- `doc/eval-data-layout.md` 清理 5 处「E-A 随方向 1 挂起」措辞（第 6、43、111、218、391 行），
  「最后更新」同步为 2026-09-03。**没有机械替换为「正式收口」**：这里混合了两个事实——方向 1 已正式收口
  但未来仍可重新立项，而 E-A/replay 轨是 schema 继续有效、历史数据保留、只是当前不启用。两者分开表述，
  轨的状态一律写「当前不启用」，方向状态仍只指向 `doc/WBS.md`。§8 保留策略表的
  `synthetic-training` / `local-approval/l6` 两行「至少保留到……收口」未改动：改它等于设定新的保留策略，
  属用户决定，不在本次文档修正范围。
- `doc/development-environment.md` 在 target 路由条目后补充现状说明。原路由描述本身正确，未修改；
  新增内容说明两个产品叶子当前均不存在、**路由规则不变**、下次重型构建仍写入同一路径并冷重建。
  保持同一路径是用户明确要求，目的是让后续构建的 target 口径与历史证据一致。

## 二、已执行的删除

三类对象，均在删除前逐个复核 canonical path、非符号链接、非挂载点、零打开句柄、无进程占用：

| 对象 | 释放 | 依据 |
|---|---|---|
| `eval-data/envs/publication-critic-plan068` | `6,897,892,345` B | uv 创建的 CPython 3.12.3 venv（`pyvenv.cfg` 确认），专属重建合同 `eval/environments/publication-critic-plan068/{pyproject.toml,uv.lock}` 受跟踪，完全可再生 |
| `.claude/worktrees/115-plan109-final-review` | `151,647,968` B | Plan 109 收口审查自身遗留；clean、无 ignored/untracked、HEAD `a7f01abd` 是 `main` 祖先且与 `main` tree 零差异 |
| `mydev/codex-rs/` 下 8 个空目录 | ~32 KB | 2026-08-07 测试残留，全部空且 untracked |

八个空目录为 `core/.agents`、`core/.codex`、`core/.git`、`core/absolute-turn`、`core/project`、
`core/request-permissions-environment`、`linux-sandbox/.agents`、`linux-sandbox/.codex`。
用逐个 `rmdir` 执行（非空即失败），未使用 glob 或 `find -delete`；`target/nextest/local` 两个正常构建骨架未受影响。
清理后 Local 相对上游的新增条目由 18 降至 11，全部为真实产品内容。`multidev/` 树本就无此问题。

`eval-data/` 由 `46,611,984,222` B 降至 `39,714,091,877` B，差额与 venv 实测大小逐字节闭合。
项目占用（不含本工作树）为 `40,745,013,352` B（37.95 GiB）。
`git worktree remove` 未加 `--force`，`zz-done/worktree-115-plan109-final-review` 分支保留。

## 三、明确未做

经与独立审查意见比对后保留、本轮不动：

- `eval-data/publication-critic/plan068/handoff`（13 GB）。实测其中 `runs/` 是 C1/C2/C3 三份各
  `3,441,189,792` B 的候选权重，加 `model/` 的 exact base 共四份，inode 各异、抽样内容哈希互不相同，
  云端卷 `mwemzrn33y` 已不存在，**不可恢复**。
- `eval-data/local-approval/l6/.../paired-gguf-02` 的两个 GGUF（约 9.7 GiB）。用户本轮明确不做可选删除。
  若将来释放，只能删两个 `.gguf`；同目录 12 个非 GGUF 文件必须保留——9 个顶层 receipt/manifest/日志，
  加 `tooling/` 内 3 个转换工具（`convert_hf_to_gguf.py`、`llama-quantize`、`merge_adapter.py`）。
- `eval-data/bin` 的 8 个 RONDO runtime bundle（约 10.4 GB）。经核实 8 个 commit 各有 2–41 处受跟踪引用，
  且 `doc/eval-data-layout.md` 将其定义为冻结 runtime bundle；当前占用远低于告警线，无释放压力。
- 138 条 `zz-done/` 分支、`test-data/_retained-test-evidence/`、`reference-agent-harness/`。

## 四、验证边界

只做只读核验与上述文件系统操作：`git diff --check`、README 统计复算、上游 diff 复算、Git/worktree 状态、
删除前后占用闭合。未运行 Cargo、全 workspace、Docker、真实 API/模型、训练或测评——本批次不改产品代码，
不需要也不触发这些门禁。

## 五、遗留观察（不属本批次，供将来参考）

CI 的 test 子集不覆盖两条线的 `codex-core` guardian 与 `codex-tui`（Local 仅
`-p codex-config -p codex-features`）。`.github/workflows/ci.yml` 已注明该窄覆盖与本地全量兜底的边界，
是有意取舍而非疏漏。停更期间无代码改动，不构成风险；将来重启开发并改动 Local guardian 时需注意
CI 绿灯不覆盖该面。两个产品 target 叶子均已删除，届时首次本地全量为冷构建。
