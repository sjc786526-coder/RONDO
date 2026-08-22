# Plan 052 RONDO Local Harness 聚合观测与瓶颈普查

## 实质修改

- 在 `codex-exec` 增加默认关闭且要求 JSON 模式的 `--rondo-local-observation`。collector 复用 app-server 已有事件，
  聚合逐响应 usage、turn/tool/Guardian 时长、typed error、compact、命令输出字节和精确重复；只输出一个 body-free
  `task.observation`，不改变请求或执行行为。
- 在 eval 增加 observation/census exact schema、严格读取、聚合和 fail-closed compare；根 just 入口可重复生成
  tracked 机器结果。私有工件只在内存作长度、固定分类和精确重复判断。
- 固定 v28 Local cohort 为 30 run/10 task。API 30/30；exec 24/30、8/10 task，另外 6 个 redacted 集中在 2 个
  task。C1/C2 为弱信号，C11 为当前样本未观察到，C7 不可测；没有选择优化，E-A 不恢复。
- WBS 只保留一个后续测量包：10 题、2 个 Local round、Terra medium/Guardian low、20 USD 硬上限和显式停止条件，
  本任务未运行。

## 复核与问题收敛

独立复核首先发现初版全索引 reader 在 Local 筛选前打开 private summary、父目录 symlink 未被拒绝，以及 compare
在覆盖不足时仍给数值 delta。整改后，纯 tracked reader 先选样，只对 30 个 Local 槽使用 common-root
`dir_fd`/`O_NOFOLLOW` 逐级读取；report/delta 改为 exact schema，lag、非终态、usage/timing/compact/Guardian
缺失或未闭合、coverage/missing/unknown event 任一不足时 compare 全部返回 `null`。最终独立复验 PASS，无剩余
correctness finding。

## 验收

- Python：`tests.test_config_and_artifacts`、`tests.test_harness_observation`、`tests.test_harness_census`，47/47 通过。
- Rust：正式 `just test -p codex-exec` 138/138 通过；共享 build lock/watchdog `stop=none`。一次先行诊断未清除
  ambient proxy，33 个 loopback integration 统一收到 502；清除代理后同 crate 通过，未访问真实 API。
- 实时 census 与 tracked JSON 一致；`git diff --check` 与最终 scoped lint/format 通过。
- 未运行 Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI、PR 或 Bazel。

## 主物理根 ignored I/O

- 只读 v28 campaign identity，以及 30 个 Local run 的 private summary、API metadata、24 份 exec JSONL 和 6 份
  redaction marker；复用既有 `eval/.venv` 与 `eval-data/uv-cache`。
- 初版 reader 曾额外只读打开 v28 的 10 份 Codex private summary；没有打印/持久化正文，没有写入或改变资产，修复后
  的实现与复跑不再打开它们。
- 未创建 Plan 052 ignored 临时目录，未改写、移动或删除既有运行资产；未打开 `.env.local`、validation、holdout
  或主工作区来源不明的 untracked 研究文档。
