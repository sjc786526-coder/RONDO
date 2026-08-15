# Plan 033：L3/L4 未微调 Local-static baseline

日期：2026-08-15 ｜ 分支/worktree：`033-l3-l4-unfinetuned-baseline`
方案：`plan/033-l3-l4-unfinetuned-local-baseline-execplan.md`

## 实质性改动

- 新增 `eval/rondo_eval/local_approval/shadow_replay.py`：三个阶段——只读 `verify`（复用 Plan 032
  `build_summary` 做完整复验，并要求与 tracked 锁逐字节相等）、真实 `run`（一次受监管生命周期回放 40 条）、
  离线 `publish`（幂等重算 + 发布）。L4 指标是纯函数：同一个 `summarize()` 分别算 seed、holdout 与总体，
  逆序输入结果相同。
- 新增 tracked 指标合同 `eval/templates/local-approval/l4-metric-contract-v1.json`，由
  `metric_contract_document()` 生成、`load_metric_contract()` 逐字段比对；漂移即 fail-closed。
- `eval/rondo_eval/artifacts.py` 窄扩展 shadow 来源合同：`source` 成为 shadow 行必填字段（历史无 shadow 行，
  因此不做默认推定），imported 行必须带教师身份且 `binary_sha256`/`metrics`/`cost.actual_usd` 为 `null`、
  `estimated_usd=0.0`、不写 `product`，`artifacts` 指向 `eval-data/teacher-labels/<batch_id>`。
- 同时给 `ArtifactWriter` 加了**无工件树发布**：导入行不 claim `eval-data/runs/<run_id>`，只写 record，
  但仍走同一把结果锁、同一份 journal v2 与同一套恢复语义（`staging_name` 与 `tree_identity` 同为 `null`，
  半声明的 journal 直接判为损坏）。这是本任务唯一必要的基础设施改动，没有新建第二套结果库。
- 新增 `eval/tests/test_shadow_replay.py`（41 项）：指标合同与模板一致、nearest-rank 百分位、五类终态、
  一致率分母与 `null` 语义、token 缺失语义、allow/deny 分布、幂等重算、outcome 行矛盾拒绝、
  严格教师导入的六类漂移、重试允许/禁止边界、一次全 mock 生命周期（无模型/GPU/网络）、
  四条记录的 imported/auto 字段差异、holdout `tasks=null` 与逐条零泄漏、中断后按同一批 run id 恢复。
- `doc/eval-data-layout.md` 同步 live schema：`source` 必填、imported 行的工件引用与无 run 树发布、
  `local-*` 行 `binary_sha256` 记被评 GGUF 的 SHA-256（这条轨没有 RONDO 二进制参与，写产品二进制会是假证据）、
  auto 行在 `config` 声明所用冻结指标口径。

## 疑难问题

**教师批次是单极的。** 40 条标签全部是 `allow`（seed 24/0、holdout 16/0）。这不是本次运行的问题，
但直接决定了结论怎么读：在这种分布下"教师一致率"在数值上等于本地 allow 率，**无法区分"与教师一致"
和"倾向放行"**。本轮因此只把它当作微调前的固定对照起点，不作任何模型优劣判断，也不改指标定义去迁就它。
该事实已写进 WBS、完成历史和 baseline 的口径说明。

**5 条结构化输出失败全部撞输出上限。** 私有逐条数据显示这 5 条的 `output_tokens` 恰好等于 512
（即 `max_output_tokens`），返回被截断的不合规 JSON。它们按 `structured_output_failed` 归档并计入
fail-closed，没有被折算成 deny，也没有重跑——按 Plan §3.3.4，收到模型响应后的解析失败是结果不是重试理由。
放宽 schema 或抬高输出预算都会改变冻结合同，本轮不做。

**WSL 上 `nvidia-smi --query-compute-apps` 不返回任何行。** 即使 llama-server 正在占用约 6.4 GB 显存，
该查询也是空的，所以"无外来 CUDA compute 进程"这一子检查在本机实际上是空转；设备级 `memory.used`
采样本身正常（1,351 次、窗口完整）。这是既有 `qualification.py` 就有的现场限制，不是本次引入的，
如实记录而不在本任务里改动资格设施。

**一次运行前失败。** 首次以相对路径 `./scripts/with-build-lock.sh` 调用 wrapper，
`runtime_bridge` 要求 wrapper 进程 `/proc/<pid>/cmdline` 中出现解析后的绝对脚本路径，因此 lease 被拒
（`watchdog_unavailable`）。属调用方式问题，改用绝对路径即通过；该次未启动模型、未创建私有目录、未动 GPU。

## 验收结果

- 运行前 clean harness 提交 `bbb572d`，真实回放从该 commit 启动，`git_dirty=false` 由 runner 强制。
- 真实运行：1 个模型生命周期，40/40 终态（allow 16 / deny 19 / 结构化输出失败 5 / 超时 0 / infra 0），
  重试 0；总请求耗时 404.8 s；P50/P95 延迟 8,335.01 / 25,758.68 ms；峰值显存 8,048,869,376 B
  （基线 1,629,487,104 B、delta 6,419,382,272 B、1,351 次采样）；服务 input token 与冻结 census 40/40 一致；
  四项清理全 true。
- 教师一致 16/35（seed 9/21、holdout 7/14），教师不一致 19，有效判定覆盖 87.5%。
- 四条 shadow 记录 `20260815-082704844/845/846/847` 与 baseline
  `local-approval-unfinetuned-static-baseline-v1.json`（SHA-256 `ca0bbc21…9d4dcd`）已发布；
  重跑 publish 为空操作、baseline SHA 不变。公开 seed 逐条投影可独立重算出 9/21。
- focused tests 323/323 通过、0 skip；`uv lock --check` 85 packages 通过。
- 全量 tracked 文件扫描：holdout 逐条 semantic id / payload SHA 零命中；holdout 的 16 个
  `e_final_sha256` 只出现在 Plan 028/029 已发布的 census baseline 里（该文件列出全部 47 条归档哈希、
  不含分区归属，本任务未改写）。tracked 结果中无 rationale、risk_tags、guardian_policy 或证据正文。

## 边界

只覆盖 12k 档位内这 40 条冻结样本的未微调回放。未运行 16k、5 条超窗证据、L5b/L6、微调后模型、
Local M4、Opus 裁判、Docker、Cargo、云 API 或全量 eval；未重新 prepare 教师批次、未调用 Sol、
未改标签；未修改 `mydev/`、`multidev/`、正式 Guardian bridge、runtime、GGUF、prompt、static 合同、
资格 evidence 或 `rondo.local.toml`；未读 `.env.local` 内容。
