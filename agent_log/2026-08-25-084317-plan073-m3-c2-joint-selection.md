# Plan 073：M3-C2 Publication Critic 联合横评与最终选择

## 结果

任务终态 **`NO-GO`**。唯一有效正式轮 `plan073-formal-20260825T084317Z-selection-v1` 在冻结 v8 validation（55 条，34 PASS /
21 REWRITE，19 boundary + 7 within-PASS 对）上，用同一协议、同一目标 runtime 比较 exact base、C1、C3，三者都没有达到正式输出前
冻结的发布质量底线。没有产生 selection lock，因此 unseen-test 全程没有释放、render、打分或送 Judge。

| 指标 | base | C1 | C3 | 底线 |
|---|---|---|---|---|
| False PASS | 6/21 `0.286` | 20/21 `0.952` | 5/21 `0.238` | ≤`0.25` |
| False REWRITE | 13/34 `0.382` | 0/34 `0.000` | 18/34 `0.529` | ≤`0.35` |
| balanced accuracy | `0.666` | `0.524` | `0.616` | ≥`0.75` |
| ROC AUC | `0.6169` | `0.3894` | `0.5567` | ≥`0.80` |
| boundary pair | 15/19 `0.789` | 5/19 `0.263` | 10/19 `0.526` | ≥`0.70` |

关键点是这不是 threshold 选得不好：每个候选都在自己的完整 operating curve 上搜索（105 / 21 / 43 个点），全曲线可达的最高
balanced accuracy 分别只有 `0.666`、`0.524`、`0.616`，没有任何一点能同时满足门限。三者 typed failure 均为 0，runtime 门全过且几乎
完全一致（load `2.9–3.2s`、warm p95 `219–222ms`、RSS `4.30GB`、VRAM `3.64GB`），因此延迟/资源按事前冻结的规则只作可用性门，不参与排名。

## 异构横评

`claude-opus-5` 通过 Claude Code 订阅盲评全部 55 条：不含参考标签、pair 方向、split 名、模型身份和任何模型分数，item id 经 salt
确定性打乱，7 个批次分别由独立子智能体完成，全部通过身份/完整性/唯一性校验后才解盲。

- **Opus 5 与冻结 GPT-5.6-sol 标签一致 53/55 = `0.964`**，只在 `pc064-consistency-014-binary`、`pc064-useful-09-qminus` 分歧。
- 三个候选与 Opus 的一致率分别是 `0.655` / `0.600` / `0.582`。

两个互不可见的质量视角高度收敛，而三个模型同时以相近幅度偏离两者。证据指向模型能力，不指向 v8 标签质量。Judge 的 sanity gate
因此处于激活状态（`0.964 ≥ 0.70`），但没有领先候选可供检验，运行已先以 `NO-GO` 结束。

## 疑难与判断

- **微调把 reward head 的输出范围压塌了。** validation 上 raw logit 跨度：base `-2.34…7.22`（`9.56`），C1 `-19.25…-18.00`（`1.25`），
  C3 `-2.08…-1.78`（`0.30`）。C1 的 AUC `0.3894` 低于随机，即排序与质量反相关，几乎全部放行；C3 尺度接近 base 但近随机，且严重过度阻断。
- **这与 Plan 068/071 的 `QUALIFIED` 不矛盾。** 那两轮是部署可比性门：问的是"部署件是否复现自己的 CPU FP32 参考 / fresh worker /
  service verdict"。一个输出接近常数的模型天然满足这些。M3-C2 是第一个问"模型判得对不对"的门，塌缩才在这里暴露。
- **正式运行前的冻结确实起了作用。** 我在正式 freeze 之后追加 tracked 报告投影功能，`evaluate` 的 formal source 门立即拒绝执行。
  处理方式是先还原到冻结 commit 完成正式 `evaluate`，之后再提交报告功能——报告是对已归档证据的纯投影，不含任何判定逻辑。
- 首次重型运行因把主仓库根的 `scripts/with-build-lock.sh` 传给 worktree 内的进程而被 production proof 拒绝
  （`watchdog script differs from the active RONDO checkout`）。改用 worktree 自身的 wrapper 后正常；机器级锁仍是同一把。

## 验收结果

- 路径同一性：用 Plan 073 的打分路径在 Plan 054 的 24 条 cohort 上重跑 C3，raw logit 与 projected score 与 Plan 071 正式
  `c3-deployment.json` **24/24 逐值相等**，证明本任务与已验收的 Plan 071 是同一条产品路径。
- 可复算：从归档的 freeze / release / 三份 scores / Judge aggregate 重建 `evaluate_validation`，与归档 result **逐字节相等**；
  result canonical SHA-256 `2b36eb4b408ff9a1a6a9830429fb806e9e2df1e54b6374755b98febb3cc98915`，freeze
  `6740e4a4b663813d07f147240680a07f137b6154e8453943397916db09869600`，Judge package
  `85f1e1dd37938076a1d83d303638d9f5a71a8ba0b51611514f78379570b141d1`。
- 测试：Plan 073 新增 44 项 + 既有 publication-critic 套件共 167/167 通过（unittest）。`compileall` 与 `git diff --check` 通过。
- 未运行项：Rust 未改动，因此未跑任何 Cargo 门禁；未使用 Docker、付费 API、云资源、HF 下载或远端写入；未训练、未量化、未改权重；
  C2 未加载、未评价；unseen-test 未释放。因无暂定赢家，Plan 055 service descriptor 未更新，也未做 service parity 运行——该步骤按协议
  以选出赢家为前提。
- 重型运行：4 次真实模型加载全部经 worktree canonical wrapper/lock/watchdog，`rc=0 / stop=none / cleanup=none`；运行前后 Windows `C:`
  可用约 `103.3GB` / `96.2GiB`，项目占用约 `133.6GB`，均远离门限。

## 主物理根实际创建/修改的 ignored 路径

- `eval-data/publication-critic/plan073/` —— 新建，`2,012,268` bytes，18 个目录（均 `0700`）、54 个文件（均 `0600`）、0 个 symlink。
  含 commissioning 输入/raw/judge/runs 与唯一正式轮的 inputs/raw/judge/runs。未创建 Plan 073 专属 env、cache 或 target；
  只读复用了 Plan 068 handoff 的模型与 Plan 068 serving venv，未复制约 24GB 既有工件，未改写 Plan 066/068/071 任何 namespace。
- `.claude/worktrees/073-.../.codex/build-watchdog/` —— worktree 内 ignored 的 watchdog metrics，由共享 wrapper 自动生成。

## 独立验收整改

独立验收（`0841748`）判定不通过，两个 correctness 阻塞项均属实，已窄修并复验。

1. **validation release 在过滤前读取了完整 v8。** 原实现用 `DatasetConsumer.from_frozen_directory(allow_evaluation=True)`
   一次性载入全部 228 行再过滤，因此正式进程在 lock 前确实持有过 unseen 正文。新增 `selection/dataset_source.py`：
   先从 supervision 建立本 split 成员集，再逐行流式读取 packets/census/pairs，非成员行读到即丢弃，从不保留或返回；
   unseen 的门禁下沉到该 reader。完整性不降级——仍复用既有 `verify_freeze_manifest` 与 per-row 契约校验器。
   回归覆盖"validation 源不含任何 unseen id"以及"validation 路径不得调用全量 consumer"（mock 断言）。
2. **伪造的 `SELECTED` result 能开出有效 lock。** 新增 `validate_validation_result()`：从 result 自带的逐行分数重算
   threshold search、confusion、ROC AUC，再重算 admission、ranking 和 terminal，全部必须与文档记载一致；
   `build_selection_lock()` 与 `report` 都先过这道校验。审查演示的伪造样本（仅改 terminal/selected/ranking，
   以及进一步改 `admission.admissible`）现在均被拒绝。

一并处理的非阻塞项：Judge package id 不再允许包含 split 名（`validation`/`unseen`/`train`/`test`/`holdout`），本轮正式
package id 确实含明文 `validation`，属形式泄漏，不提供答案，按审查决定不重问 Opus；`evaluate` 增加可选 `--judge-package`
把 aggregate 绑定到实际发出的 package；Judge 模型身份改为对 `claude-opus-5` 硬校验，其它身份直接 `INCONCLUSIVE`；
scoring 不完整（typed failure 或行数不足）在 validation 与 unseen confirmation 两处都明确拒绝，不再让部分结果冒充可比证据；
`score` 今后记录整份 snapshot 的文件摘要。

关于 freeze 只绑定 `model.safetensors`：本轮已直接核验三份 snapshot 的 tokenizer/config 摘要，`tokenizer.json`、
`tokenizer_config.json`、`vocab.json`、`merges.txt`、`added_tokens.json`、`chat_template.jinja`、`config.json` 七项完全一致；
`special_tokens_map.json` 只是 pad token `<|vision_pad|>` 的字符串/对象两种序列化写法差异，pad id 仍为 `151654`。
更硬的证据是 55 行的 `token_count` 与 `dropped_oldest_publications` 在 base/C1/C3 之间逐值相等，输入身份同一性直接成立。

复验（未加载模型、未跑 Cargo/Docker、未碰 unseen）：

- 新 split-scoped reader 重建的 validation release 与归档逐字节相同，SHA-256 仍为
  `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`。
- 用归档 raw + Judge package 绑定重建 `evaluate_validation`，与归档 result 逐字节相同（`2b36eb4b…`）；归档 result 通过新的
  严格校验器，terminal 仍为 `NO_GO`。tracked JSON 重新生成后仍为 `f97fcdcc78c9932dd96eb17c419ef29bf574649d7b67c1c497e861daa2eee8e4`。
- 测试：Plan 073 focused `51/51`；全部 `test_publication_critic*.py` 共 `308` 项通过、`1` 项 skip（此前日志的 `167`/交接的
  `184` 是两次不同文件子集的口径，非全量）。

正式结论不变：`NO-GO`，不生成 selection lock，不释放 unseen，不解锁 M3-D，Publication Critic 保持 default-off。
整改只收紧门禁与校验，不改变任何指标定义、冻结底线或候选证据。

## 复验整改（第二轮）

复验（`71525eb`）判定第一轮整改未完整关闭两个原阻塞项，两条都属实：

1. **流式 reader 仍会解析 unseen。** 第一轮只做到"不保留"，每条 unseen row 仍被 `json.loads` 进入进程，
   `verify_freeze_manifest` 还会哈希读取全部混合文件。本轮改为：validation 从 Plan 066 `train+validation` 冻结 bundle
   读取——该资产物理上 0 条 unseen row、0 个 unseen body file，已用全文扫描确认 45 个 unseen id 一个都不出现；
   混合 v8 只在有效 lock 下为 unseen 打开。bundle 经 `bundle-manifest.json` 的 `content_sha256`、数据文件 size+sha256、
   `boundaries.unseen_test_rows/body_files == 0` 与 `source.v8_manifest_file_sha256` 四重校验绑定到同一冻结 v8。
   跨行完整性不再降级：train+validation 行仍交给既有 `DatasetConsumer`，packet/supervision 投影、pair 语义与
   omission 可应用性校验全部照常运行。回归用 `Path.open/read_text/read_bytes` 访问 spy 证明 validation 成功路径
   从未打开四个混合数据文件中的任何一个。
2. **lock 仍由 result 自证。** 复验演示：真实 freeze + 一份仅声明冻结 manifest hash 的 24 行合成 release，
   即可走完 `SELECTED` 并开出 lock。本轮 `build_selection_lock()` 先用冻结数据重建 validation release 并要求
   与传入 release 逐字节相等，再用真实 release + 三份 raw score + Judge package/aggregate 重算，要求与待锁 result
   逐字节相等。合成 release 与手改 result 两条路径现在都被拒绝，并各有回归。

一并处理：`report --unseen-confirmation` 现在必须同时给出 `--selection-lock`，并经
`validate_unseen_confirmation()` 校验 freeze/lock/locked combination 绑定后从自带 rows 重算 confusion/AUC/gates/terminal；
Judge aggregate 与 package 必须成对出现（缺 package 直接拒绝）；split 词改为分隔 token 判断，不再误伤 `contest/latest`；
三份 score 的 snapshot 摘要若都记录，则校验 tokenizer/config 身份一致。

复验（未加载模型、未跑 Cargo/Docker/Opus、未释放 unseen）：

- bundle 重建的 validation release 与归档逐字节相同（`757dd624…`）。
- 归档 raw + Judge package 绑定重算 result 与归档逐字节相同（`2b36eb4b…`），通过严格校验器，terminal 仍为 `NO_GO`。
- tracked JSON 重新生成仍为 `f97fcdcc78c9932dd96eb17c419ef29bf574649d7b67c1c497e861daa2eee8e4`。
- 测试：Plan 073 focused `55/55`；全部 `test_publication_critic*.py` 共 `312` 项通过、`1` 项 skip
  （skip 为 bundle 不在本机时的 Plan 073 隔离用例）。

## 交接建议

`NO-GO` 只关闭"从现有三个候选中选出可发布模型"这条路，不解锁 M3-D，也不改变 Publication Critic 默认关闭状态。证据同时给出两条
对上游有用的事实：v8 标签经异构盲评确认可靠（`0.964`），而 Plan 066 的分阶段全参数微调把 reward head 压塌，C1 甚至反相关。后续
方向（是否重训、换训练配置、换底模或调整数据）属于 WBS 决策，不在本计划内展开。WBS/WBS-COMPLETED 的最终同步留给独立验收后基于
届时最新 `main` 完成。
