# Plan 023 Turn A 独立审查验收报告

- 日期：2026-08-14
- 审查对象：`023-local-4k-qualification@593147f`（parent `6cc9f11`）
- 审查范围：提交差异、Plan/WBS/agent log、qualification 与 capability 投影实现、focused tests、ignored 配置的非敏感状态、宿主清理现场
- 交付边界：未重新加载模型，未运行 Rust/Docker/云 API/全量 eval，未合并、未推送

## 结论

**验收不通过，暂不允许合并。**

Turn A 的最终目标没有完成：没有真实结构化判定，没有有效 VRAM/TTFT/总耗时指标，没有 model-backed evidence，能力没有晋级，
也没有晋级后的正式 launcher + doctor 复验。这一点执行者如实按 non-promotion 收口，没有冒充成功。

失败现场本身通过复核：当前 capability 确为 `linux_cuda_built_model_unvalidated`，证据文件不存在，正式服务未启动，端口、PID、
receipt 和私有临时目录均已清理。实现中的 production gate、Plan 018 历史保留、exact CUDA/CPU build identity 修正和大部分
fail-closed 流程方向正确。

但提交仍有 3 个会影响未来真实晋级可信性的阻断问题，其中前两个同时使当前 WBS blocker 结论不能按现状合并。应先做一次窄的
review remediation；在修复通过前不要增加模型生命周期，也不要选择 8k、压缩或 synthetic 路线。

## 阻断 findings

### F1（高）：qualification 不能证明输入是冻结的真实生产 `E_final`

`qualification.py:422-469` 只要求 CLI 路径位于 `eval-data/runs/.../E_final.json`，随后由待验文件自身计算 SHA，并只对同目录
`meta.json` 做少量字段/类型检查。它没有把输入绑定到预先冻结的 path/SHA/meta SHA，也没有调用现有生产 bundle validator。
因此任意 JSON 加一份自造的弱 meta 就能通过 source gate；`test_local_approval.py:1779-1824` 正是临时创建这样的文件，
`test_evidence_source_must_be_a_real_archived_e_final` 也只证明错误路径和明显坏 commit 被拒绝，没有证明伪造归档会被拒绝。

这不是纯 provenance 加固，而是核心完成条件：成功路径必须使用“一条既有真实 `E_final`”。若未来模型对这类自造短输入返回合规
结构，当前实现可能生成 `gpu_model_serving_validated` 证据。

同时存在同一读取链的 TOCTOU：`_select_evidence_source()` 对第一次读取的 bytes 计算 SHA，`_static_payload()` 又从路径重新读取；
若文件在两次读取间变化，tracked source digest 与真正发给模型的 payload 可以不一致。代码也只拒绝最终文件 symlink，没有按现有
生产 loader 的方式验证祖先和同一 bundle 的稳定身份。

修复要求：

- 优先复用 `terminal_bench.live.load_guardian_evidence_bundle()`（`live.py:417-477`），从关联 tracked run/profile 取得独立的
  expected model/effort；或建立更窄的 tracked selector，至少预先绑定唯一 relative path、E_final SHA 和 meta SHA。
- E_final/meta 必须安全单次读取并冻结 bytes，校验无 symlink 祖先、读取前后 stat identity 不变；后续 payload 直接从冻结 bytes
  构造，不得重新打开路径。
- 增加“伪造 E_final + 形式正确 meta 仍拒绝”、source/meta 漂移、symlink 祖先的分类回归。

### F2（高）：一条 5,313-token 实测不能证明 47 条真实归档全部不适配 4k

真实服务已经证明“本次选中的一条 static payload 为 5,313 tokens，超过 4096，因此该请求失败”。这条事实可以接受。

但 `doc/WBS.md:27,40-42`、`doc/WBS/local-approval-model.md:61-72`、Plan 当前状态和执行日志进一步写成：现存最小真实
`E_final` 是 5,313 tokens、47 条全部装不下、4k 已被整体证伪、上下文是当前唯一 blocker。现有记录只给出一次服务端 tokenizer
计数和其余归档的字符长度范围。字符数与该 GGUF tokenizer 的 token 数不严格单调；“按字符最短的样本”不能自动推出“按 token
最短的样本”。若公共 policy 本身已经超过 4096，也需要给出该 tokenizer 的精确计数，而不是由总字符数推断。

此外 Plan §2 明确禁止读取所选样本以外的 holdout/私有内容。审查材料没有说明 47 条 census 是来自既有可信聚合元数据、只读哈希，
还是遍历了原始 payload；因此该 census 的授权和获取方式也无法验收。

修复要求：

- 当前权威事实收敛为：“一条既有真实 E_final 实测 5,313 input tokens，不能在 4k 合同下服务；4k 对全部 47 条的可行性尚未
  形成 exact-token 证据。”删除“现存最小”“全部装不下”“唯一 blocker”等未证实表述。
- 若用户另行授权全体长度普查，必须用 frozen GGUF 的 exact tokenizer 对 47 条 canonical static payload 做 tokenizer-only
  计数，只持久化 path digest/count/min/max，不输出内容；还要明确 input 与最大输出预算如何共同占用 context。没有该授权则不得
  再读取其余 46 条。
- Plan 决策 009 仍写“待用户确认”，与 Plan `250-256` 已记录的“两次默认、上限 4 次”授权和实际消耗矛盾，应同步为已确认/已用满。

### F3（中高）：设备级 VRAM sampler 没有 fail-closed，也没有覆盖完整独占窗口

`qualification.py:329-335` 捕获并静默丢弃所有 sampler 异常；`343-347` 最多等待线程 5 秒后无条件丢弃 thread handle，既不确认线程
已经退出，也不传播后台错误。只要早先碰巧采到过一个正 delta，之后 sampler 持续失败，当前 evidence schema 仍可能接受这个并非
完整窗口峰值的数字。

GPU exclusivity 只在启动前和 ready 后检查一次（`qualification.py:181-184,230-232`）。真实 decision 期间若出现新的 foreign
compute process，device-level peak 可能被污染，但成功路径没有结束检查或持续监控。现有 tests 没覆盖动态 sampler failure、线程
退出超时或 decision 窗口中途出现 foreign PID。

修复要求：

- sampler 保存首个错误并在 stop/finalize 时抛出稳定 qualification blocker；后台线程必须确认退出，超时即失败。
- 对 device-level fallback 在请求前、请求期间/结束后维持 exclusivity；任意 foreign compute process 或计数缺口均不得写 evidence。
- 增加参数化回归，证明即使已经有正 delta，后续采样错误、join 超时或 foreign PID 仍阻止晋级。

## 已通过部分

- 提交严格位于专用 worktree/branch，基线 parent 为 `6cc9f11`；主工作区仍 clean，未合并、未推送。
- tracked 范围为 11 个文件；未修改 `mydev/`、`multidev/`、Plan 018 base locks、8k example、Docker/Rust/cloud/training。
- 实际提交规模为 **+2293/-54**，不是执行摘要中的 `+1138/-54`；文件数 11 正确。
- `model_backed.py` 保留 Plan 018 base lock，evidence missing/malformed/mismatch 均不能晋级；no-clobber publication 和 strict schema
  的总体方向正确。
- 正式 `run_server()` 的 capability gate 仍在 `Popen` 前，qualification 没有向 production launcher 增加通用 bypass。
- exact service build identity 修复正确：只读执行得到 CPU `version: 10333 (08659901c)`、CUDA `version: 1 (0865990)`；对应
  `/props.build_info` 常量 `b10333-08659901c` / `b1-0865990` 与源码行为一致，比较从模糊 substring 收紧为 exact。
- qualification 在真实模型路径进入 `model_path()` 时会重新校验 GGUF header 和实际 SHA；配置声明本身不能替代实际文件 hash。
- 失败后不写 evidence，Plan 018 `model_backed_structured_output=not_run` 未改写，WBS-COMPLETED 没有追加虚假成功项。
- agent log 没有记录 E_final 原文、rationale、risk tags、生成内容或密钥。
- ignored `rondo.local.toml` 当前为普通非 symlink、mode 0600；reviewer doctor 能严格加载该配置并识别模型存在。迁移前后的
  provider/paid_eval digest 没有留存可供 reviewer 独立比较，因此“未变”只能记为执行者报告，不能补做历史证明。

## 独立验证结果

| 验证 | 结果 |
|---|---|
| `git diff --check 6cc9f11..593147f` | 通过 |
| focused unittest 三文件 | **112 passed / 11.815s** |
| `just eval-lock` | reviewer 补跑通过；它只验证 `eval/uv.lock`，不替代 evidence schema tests |
| 宿主 doctor（不启动模型） | exit 70；configuration valid、model present、runtime/capability `linux_cuda_built_model_unvalidated`、model-backed `not_run` |
| tracked model-backed evidence | 不存在 |
| 宿主 8080 | 无 listener |
| 宿主 `llama-server` | 无进程 |
| private local-approval 目录 | 空；无 launcher receipt/qualification temp |
| GPU | RTX 4060 Laptop；当前无 compute process，device memory.used 1266 MiB |
| 真实 4k 再运行 | 未运行；授权上限已由执行者用满，reviewer 未增加生命周期 |

## 对 Turn A 的准确收口

- **通过**：真实模型至少成功加载过一次的执行记录、exact CUDA/service/context 身份记录、一次真实 E_final 因 5,313 > 4096 被服务
  拒绝、未晋级、production gate、focused tests 和现场清理。
- **未通过**：真实结构化判定、VRAM/TTFT/总耗时、model-backed evidence、capability 晋级、晋级后 formal launcher + doctor。
- **不得声称**：4k 对全部 47 条真实 E_final 已被 exact tokenizer 全面证伪；当前只证实所选一条失败。
- **合并决定**：阻塞。先修 F1—F3 和权威文档，再重新独立审查；修复阶段不需要真实模型生命周期。

## 下一阶段给执行者的指令

```text
你继续在以下 worktree/branch 工作：

/home/sjc/desktop/RONDO/.claude/worktrees/023-local-4k-qualification
branch: 023-local-4k-qualification

先完整阅读根 AGENTS.md、Plan 023 和本报告：
agent_log/2026-08-14-061059-plan023-independent-review.md

任务名称：Plan 023 review remediation 与 4k blocker 事实校正。

本轮目标不是晋级，也不是选择 8k/压缩/synthetic 路线；只修复 reviewer 的 F1—F3，使现有 qualification 设施达到可合并质量，
并把权威文档收敛到已经真实证明的事实。

硬边界：

- 不启动或加载模型；前一轮 4 次授权已经用满。若后续需要 tokenizer/model 生命周期，先停下等待用户新授权。
- 不进入 L7、Local M3、8k、Rust、mydev/、multidev/、Docker、云 API、训练或全量 eval。
- 不读取或遍历其余 46 条 E_final 内容。除非用户明确授权 exact-token census，否则只保留“一条 5,313-token 请求失败”的事实。
- 不改 Plan 018 base locks，不生成 model-backed success evidence，不手改 capability。

必须完成：

1. 修复真实 E_final source gate。优先复用生产 load_guardian_evidence_bundle，并从关联 tracked run/profile 提供独立 expected
   model/effort；若采用窄 selector，则必须预绑定唯一 path、E_final SHA、meta SHA。E_final/meta 安全单次读取，拒绝 symlink 祖先，
   前后 stat identity 不变，payload 从冻结 bytes 构造，消除二次读取 TOCTOU。
2. 修复 VRAM 采样：后台异常、线程无法按时退出、请求窗口内 foreign compute process 或计数缺口一律 fail-closed；即使已经采到
   正 delta 也不得晋级。保持 device-level fallback 仅用于真正独占窗口。
3. 用少量参数化测试覆盖伪造归档、source/meta 漂移、symlink 祖先、sampler 后台失败、join 超时和动态 foreign PID；避免逐字段
   mock 堆叠。保留当前 112 项回归。
4. 修正文档：WBS/方向 WBS/Plan/原执行日志不得再称“47 条全部装不下”“现存最小为 5,313”“4k 整体已证伪”或“上下文是唯一
   blocker”。准确写成“所选真实 E_final 实测 5,313 input tokens，不能服务于 4096；全体可行性未完成 exact-token 验证”。同步
   Plan 决策 009 为授权已确认且 4 次已用满。原 agent log 尚未合并，可直接校正错误事实，并新增一份精炼修复日志。
5. 运行 local-approval/config focused tests 和 just eval-lock，检查 diff/受保护目录/敏感内容/临时对象。

完成后在同一任务分支提交；报告 commit、diff、测试计数、所有未运行项。不要合并、不要推送、不要删除 worktree，交给 Codex复审。
```
