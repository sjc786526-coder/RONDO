# 方向 2：RONDO Local 本地审批模型接入与横评

最后更新：2026-08-16（Plan 041 完成，Local M4 人判结论为“保留为实验”）｜ 产品线：RONDO Local（`mydev/`）｜ 依赖：P0（S1/S2）｜ 当前 Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 目标与定位

把 Codex `approve for me` 的审批模型换成可在本地推理的小模型，量化其审批质量与成本相对云端教师模型的差距。
能力必须**可插拔、一键切换**，且不影响原有功能与性能。

定位是**学习型教师蒸馏**：从云端教师（Sol）的判断中蒸馏出一个本地小模型，不是从零建立一套审批能力。
当前本地审批模型**不计划正式投入生产**，目标是机器学习、数据分析和工程实践，
不提前建设生产级安全与数据治理体系。将来若决定投入真实使用，再单独建立面向生产的正确性与安全验收。

## 角色分工：Sol 生成标签，Opus 5 担任裁判

二者不混用，避免“用 Sol 的标签去评 Sol”的循环。两条入口都是**订阅制、不额外计费**，
因此不占 API 预算授权门（见 `doc/WBS.md` §6）；数据外发门仍然适用。

### Sol —— 教师标签

- Sol 生成的标签作为训练、验证和离线测评的**教师标签**，用于衡量本地模型对教师判断的蒸馏效果，
  **不冒充独立人工 ground truth**；不要求人工逐条确认，也不设“高风险审批必须人工裁决”的门槛。
- 人工只在发现明显错误、数据冲突或训练结果异常时介入；不设固定抽检比例，不建设标签可信、审计或多模型共识系统。
- **调用入口：订阅制 Sol，经开发用 Codex 生成**，不走按量付费 API，因此合成数据规模不受 API 预算门约束，
  只受订阅速率与配额限制。开发用 Codex 还负责生成流程、整理、训练和分析。
- **使用方式：人在场，用仓库内预先写好的冻结 prompt 发送，不作为纯自动化后端。** 产物是冻结文件；
  `eval/` 只**导入**这些文件，不程序化调用 Sol，也不为教师侧另开按量付费 API 入口。
- 只保留机器学习实验所需的最低限度卫生：记录 Sol 模型标识与生成日期、生成 prompt 和数据版本；
  训练集与测试集去重并隔离。

### Opus 5 —— 横评裁判

- **正式同证据横评（Local M4）由 Opus 5 担任裁判**，通过 Claude Code 订阅账号在会话内完成。
- 订阅账号只用于会话内、人工在场监督的判定工作，**不得**作为程序化 provider 接进 `eval/` 当批量推理后端。
- 裁判独立性有一处已知瑕疵且接受：Opus 5 同时参与本项目开发。鉴于目标是工程与 ML 实践而非生产验收，
  不为此建设隔离机制，只在结果表述中注明。

## 当前状态

- **L1 完成，static input payload 现为 v3**：已落地 Standard/Responses Lite 双形态 `E_final` 解析、
  exact policy bytes 身份哈希、provider-neutral canonical payload 与结构化决策校验。出站静态 payload 同时排除
  顶层 `tools`、Lite `additional_tools`、warehouse-only metadata 和 provider-private 运输字段，
  malformed/歧义证据 fail-closed；合法 `ToolSearchOutput.tools` 作为既有证据保留，Luna/Sol/Local
  三组 consumer 协议投影对同一 Standard/Lite fixture 产生完全相同的 canonical bytes；这项验收不等同于
  三套生产调用端均已实现。公共 `build_static_payload()` 是唯一规范化边界，做且只做两件事：
  1. **reasoning 投影**：只有公开的 `summary[].summary_text` 按原序原样转成普通 assistant 证据消息；
     `content[]` 的 `reasoning_text` / `text` 按冻结 Codex 语义属于默认隐藏的 raw reasoning，只校验形状后丢弃，
     没有公开 summary 的 item 整项删除；`encrypted_content` 与 provider session id 一律不出站。
  2. **证据角色规范化（v3）**：证据消息的 `developer` 角色在原位改写为 `user`，文本、顺序、消息边界和
     其余字段都不变，内容仍留在 `input` 里作会话证据，不并入 Guardian policy/instructions。改写无条件执行，
     不按前驱角色分情况，也不含任何 provider 分支；出站证据只有 `user`/`assistant` 两种角色。
     理由是 `developer` 没有 provider-neutral 等价物；冻结模板中在所有前驱角色之后都合法的是 `user` 与
     `assistant`，而归档 developer 消息是输入侧 `input_text`，映射为 `user` 只换 role 标签，
     映射为 `assistant` 会改变说话者并被迫重写文本 subtype。

  未知/缺失 role、非消息 item 携带 role、空或畸形 content、与角色不匹配的文本 subtype 一律 fail-closed；
  终端 validator 拒绝 v1/v2 payload 和被手工回填的 `developer`/`system` 角色。输入 payload 版本与结构化
  **决策输出** schema（仍为 `rondo_static_approval_v1`）是两份合同，不随动。v2 实现已通过独立复审，
  v3 的角色兼容与终端消息形状校验已通过独立复验。
- **L2 的 CPU 与 Linux CUDA model-free 运行闭包均已就绪**：llama.cpp 固定为 `b10333`/commit
  `08659901c43b51de735740f1cf61bb82fbe0c4e4`，项目局部 CPU x64 runtime closure、Responses client、
  doctor、fake server、结构化输出本地校验和启动入口已实现。运行时 lock 覆盖项目目录
  52 个普通文件、10 个 symlink 和 8 个宿主动态依赖，启动环境移除 `LD_LIBRARY_PATH`。配置/命令现精确表达已冻结的
  12k `auto`/`fit=on` 合同，固定单卡 split/main GPU、F16 K/V、512/256 batch、no-mmproj、trace verbosity、
  Jinja 和显式官方模板。2026-08-13 已以项目局部 CUDA Toolkit 12.6.2、Ada `89-real` strict link 构建 exact
  b10333 CUDA runtime；独立 lock 冻结 source/tree、工具链、configure/build、9 个 ELF 文件、14 个 symlink、
  RUNPATH、cudart/cuBLAS、WSL `libcuda.so.1` 与系统闭包。清除 `LD_LIBRARY_PATH` 后 version/help 成功，model-free
  device/router probe 识别 RTX 4060 Laptop 并返回 `linux_cuda_built_model_unvalidated`。
- model-backed client 必须消费 launcher 写入主仓 `eval-data/local-approval/launcher-identity.json`
  的 0600 私有 receipt，绑定 nonce、PID/start ticks、实际 cmdline、监听 socket、runtime/model
  identity/path/id、endpoint 和实际服务参数指纹。schema v2 会拒绝旧 receipt；client 在 identity probe 后、decision 前以及 decision 返回后重验同一
  launcher 实例；redirect、receipt 替换、进程/监听者变化都 fail-closed。这是轻量实例身份
  约束，不是签名或权限系统，也不证明 server 实际加载了 receipt 所声明的全部字节，或 launcher 退出后
  server 必然随之退出。
- **12k model-backed qualification 已通过，capability 为 `gpu_model_serving_validated`**。受限 qualification
  入口、版本化 model-backed evidence 与单向 capability 投影已落地：正式 launcher 在证据缺失、无效或身份不匹配时
  一律在进程启动前拒绝，CUDA source build 与 CPU release 的服务身份分别精确绑定 `b1-0865990` 与
  `b10333-08659901c`；qualification 的输入由受跟踪 selector 预先绑定唯一 path、`E_final`/meta SHA 与期望
  Guardian 模型/effort，并复用生产 evidence reader 与 meta 校验。
  2026-08-15 该 selector 绑定的真实 `E_final`（5,311 tokens，与 v3 census 锚点同一 SHA）在 12,288 / 512 合同下
  返回合规 `rondo_static_approval_v1` 判定：服务实际 `n_ctx=12288`、单 slot、`build_info=b1-0865990`，
  GPU offload **33/35 层**，设备级显存 baseline 1,386,217,472 B、峰值 7,855,931,392 B、delta 6,469,713,920 B，
  TTFT 3,183 ms、结构化判定总耗时 7,049 ms，进程/端口/receipt/私有对象四项清理全 true。
  唯一正式证据是 `eval/locks/local-approval-b10333-ministral-12k-v1.json`（schema v2）。
  这只证明 12k 档位内这条真实证据可服务，**不代表其余 41 条已逐条验证，也不代表剩余 5 条超窗证据可服务**。
- **最终 12k 服务参数已冻结并三处对齐**：12,288 / `gpu_layers="auto"` / `fit="on"` / batch 512 / ubatch 256 /
  flash attention `on` / K,V 均 f16，输出预算 512。8GB 现场实测可用显存 7,096 MiB，`--fit` 自动收敛到 33 层
  offload、6,049 MiB used、1,046 MiB free，因此**未动用授权范围内的低精度 KV**。冻结 b10333 的 `--fit` 只调整
  仍为默认值的参数，且上下文仅在等于 0 时才被改写，所以显式 `--ctx-size 12288` 不会被缩小（服务端日志逐字
  打印 `context size set by user to 12288 -> no change`）。受跟踪 `rondo.local.example.toml`、主仓 ignored
  `rondo.local.toml`、启动指纹与资格 identity 现在表达同一组参数；任一项漂移都会让 capability 退回
  `linux_cuda_built_model_unvalidated`。
- **资格身份已显式绑定 static payload v3**：`request_contract_sha256` 升为 v2 并纳入
  `static_payload_schema_version`，identity 另存同名显式字段。以后输入 payload 合同变版时旧资格自动失配，
  不能沿用本次 capability。
- **正式入口已独立复验**：晋级后由无 qualification 特权的正式 launcher 用同一合同重新加载，receipt schema v2 的
  `serve_config_sha256` 与证据 identity 逐字节一致；服务存活期间正式 doctor 报告 `status=ready`、
  `runtime_capability=gpu_model_serving_validated`、`model_backed_validation=model_schema_probe_passed`。
  doctor 的 synthetic probe 只证明生产入口能消费该资格，**不替代**上面那条真实 `E_final` 判定。
- **正式 Guardian 路由已接通，L7 与 Local M3 已收口**：接通点是 eval-side 身份门控适配器，产品代码未改。
  冻结 b10333 与正式 Guardian wire 有三处不匹配——不映射 `text.format`、`tools` 与 grammar 并存即抛
  `Cannot specify grammar with tools`、`developer` 角色经 `map_developer_role_to_system` 撞上模板顺序限制；
  通用 provider 路径又不消费 launcher receipt。适配器复用公共 `build_static_payload()` 归一化入站请求
  （因此与 token census、qualification 共用同一条已被真实运行证明的边界），按冻结服务合同重建请求，
  完整缓冲响应并在身份后验通过前不交付，最后按 Guardian 自己送来的 schema 校验判定。
  一次 SIGTERM 缺陷同时修复：launcher 此前收到 SIGTERM 会留下活着的 llama-server 与陈旧 receipt。
- **一处工程事实值得记住**：冻结 b10333 把 libllama 自身的 `GGML_LOG_LEVEL_INFO` 映射为 verbosity TRACE(4)，
  而默认阈值是 INFO(3)，因此 GPU offload 计数在默认级别下根本不输出，且该事实没有任何 endpoint 可取。
  qualification 私有采集因而固定使用 verbosity 4；正式 launcher 使用 verbosity 3，并把 server stdout/stderr 定向到
  `DEVNULL`，避免 WARN/ERROR 错误路径的未解析模型正文进入普通终端。
  启动指纹 schema v2 同时绑定两条固定日志策略，但用仓库相对资源身份替代 checkout 绝对路径，故 linked worktree 与 main
  对同一合同计算相同 identity，功能参数漂移仍 fail-closed。
- **exact-token 普查（WP3b-A2）已完成**：v3 锚点常量窄改为实测 5,311 后，同一正式 census 入口从头
  独立运行两遍，两遍都 `status=complete`、47/47 取得 exact input-token 数、0 拒绝、0 缺失计数、
  锚点精确 5,311、`generated_tokens=0`，逐条记录、摘要与 digest 逐字节一致
  （`22b8452717f1bcfa692cffa69389ebb4a21a0aef1a9187cd066879a6b0831144`）。唯一正式结果见
  `eval/results/baselines/local-approval-exact-token-census-v1.json`。
  1. **全集长度分布（47/47）**：min 5,311、p50 8,989、p90 12,352、p95 13,754、max 22,499。
     按 `input+512`：4k 适配 **0/47**、8k 适配 **11/47**、12k（12,288）适配 **42/47**；
     对照 16k（16,384）为 **45/47**。4k 合同装不下任何一条真实证据，12k 相比 8k 多覆盖 31 条，
     与 16k 只差 3 条但显存压力更低。这些都是长度覆盖事实，不等于相应档位已经通过真实推理验收。
  2. **v3 关闭了服务侧差异**：47 条全部为 `responses_lite` 形态，全部被冻结 b10333 精确计数，
     包括此前从未被计过数、含 `assistant → developer` 相邻关系的 23 条。Plan 026 的通用 500
     未再复现；本次没有单独定位那一次失败，只能说它在 v3 下不再发生。
- **L5a 首批 Sol 教师标签已完成**：Plan 032 用 canonical static payload v3 和
  `rondo_static_approval_v1` 冻结 `rondo_sol_teacher_prompt_v1`。47 个真实实例重新通过 production meta、
  tracked ledger 与 census 对齐，得到 45 个稳定语义身份、2 个重复实例；42 个 12k 适配实例语义去重后
  形成 40 条标签（seed 24 / holdout 16），另有 5 个超窗实例与 2 个重复实例按聚合原因排除。
  教师为生成时点的 `gpt-5.6-sol`（2026-08-15）；完整 manifest、outbound、原始返回、标签与 L3 导入元数据
  只保存在 ignored `eval-data/teacher-labels/20260815-sol-teacher-labels-v1/`，tracked body-free 锁为
  `eval/locks/local-approval-sol-teacher-labels-v1.json`。该批次已通过完整集合/身份/用途校验，
  `ready_for_l3=true`；标签是 Sol 蒸馏目标，不是人工 ground truth，holdout 仍严禁用于合成或训练。
- **L3/L4 未微调 Local-static baseline 已完成**：Plan 033 严格导入上述冻结批次（复跑 Plan 032 verifier 并与
  tracked 锁逐字节一致），在同一已资格化 12k 服务上用一次生命周期回放 40 条 canonical static payload v3。
  40/40 首次尝试即进入唯一终态：allow 16、deny 19、结构化输出失败 5、超时 0、基础设施失败 0、重试 0；
  5 条失败全部撞上 512 输出上限并返回不合规 JSON，按 fail-closed 归档，不伪装成模型 deny。
  L4 指标口径在真实运行前冻结为 `rondo_l4_local_static_v1`（tracked 模板
  `eval/templates/local-approval/l4-metric-contract-v1.json`）并先行提交。教师一致率只在合规判定间计算：
  总体 16/35、seed 9/21、holdout 7/14，有效判定覆盖 35/40 = 87.5%，P50/P95 延迟 8,335 / 25,759 ms，
  输出 token P50/P95 92 / 512，峰值显存 8,048,869,376 B（基线 1,629,487,104 B，1,351 次采样）。
  服务返回的 input token 与冻结 census 40/40 完全一致。
  **该批教师标签全部为 `allow`**，所以本轮"教师一致率"等价于本地 allow 率，尚不能区分"与教师一致"和
  "倾向放行"；它只作为微调前的固定对照起点，不据此判断模型优劣。
  四条 shadow 记录（seed/holdout × `sol-static/imported`、`local-static/auto`）与聚合 baseline
  `eval/results/baselines/local-approval-unfinetuned-static-baseline-v1.json` 已发布；holdout 两条只有整批摘要、
  `tasks=null`，逐条正文、模型原始输出与 holdout 明细只在 ignored 私有批次。
- **角色顺序兼容已在 v3 关闭，并已由真实运行确认**：`developer` 消息在套用模板前被
  `map_developer_role_to_system` 统一改成 `system`；冻结 Ministral 模板规定 `assistant` 之后只能接
  `assistant`/`user`/`tool`、`tool` 之后只能接 `assistant`/`tool`/`user`，遇到 `system` 直接
  `raise_exception`，minja 抛 `std::runtime_error`，服务端兜底为 **HTTP 500 `server_error`**
  （`std::invalid_argument` 才是 400）。v2 下 23 条请求含 `… assistant → developer → user`，会触发该限制。
  v3 的角色规范化消除了这一形状：同一份从冻结模板资产解析规则的只读角色顺序门下，47/47 通过，
  规范化前为 24/47（23 条报 `Unexpected role 'system' after role 'assistant'`）。
  该门禁只存在于测试，不进入生产 consumer；它只证明请求可渲染，真实可计数由上面的 47/47 普查给出。
  它仍然不解释 Plan 026 的具体 500，也不追认 Plan 024 两条旧通用 500 的现场原因。
- **锚点口径已迁移到 v3**：census 的 `ANCHOR_INPUT_TOKENS` 现为 **5,311**，即冻结 tokenizer 对 v3 锚点
  请求的实测值，并已由两遍完整普查各自独立复证。历史 5,313 是 Plan 023/024 在 **v3 之前**测得的事实：
  当时该锚点的那条证据 `developer` 消息经 `map_developer_role_to_system` 以 `system` 进入冻结模板，
  v3 改为原位 `user` 后角色标签变化正好对应 2 个 token 的差。迁移只改常量与说明，
  没有引入容差、版本注册表或第二套锚点机制。
- **census 失败定位已补到最小可用**：通用计数失败现在附带有界 `stage`（`anchor_count` / `archive_count`）、
  当前 `e_final_sha256` 与 `counted_before_failure`（失败前已取得 exact count 的唯一归档数）。
  通用 500/transport 失败在两处仍然立即停止、不发布结果，也不会被降级成某条样本的拒绝属性；
  只有明确的 400 结构性拒绝沿用原 incomplete 语义。这些字段只用于定位下一次失败，
  **不能**回溯解释 Plan 026 已发生的那次 500。
- **static-payload 兼容已由真实运行确认**：reasoning 投影与角色规范化都只做在公共 builder，
  没有为 llama.cpp 做隐蔽的 provider-specific 删减或旁路；Local client 与 token census 共用同一
  v3 request builder（逐字节相等已回归）。47 条归档 47/47 构造出 v3 payload 与 Local 请求，
  三 consumer 逐字节一致，且这 47 条真实请求全部被冻结 b10333 精确计数。
  全集分布已有，档位可以定案；不把“只用合成证据、真实证据只取可服务子集”设为默认路线。
- **首个 model-backed 资格档位已定为 12k（12,288）**：它在现有全集上覆盖 42/47，明显高于 8k 的 11/47，
  同时不直接承担 16k 的更高 KV/显存压力。12k 的真实显存、offload、结构化输出与时延均已在 2026-08-15 验收；
  剩余 5 条超窗证据仍不冒充可服务。
- **唯一权重已下载且仅静态验收**：2026-08-12 已将未微调纯文本基线冻结为 Bartowski 模型卡声明从官方
  Ministral 3 8B Instruct 2512 BF16 转换的 `Q4_K_M`，固定 repo revision、文件、大小、LFS SHA、
  单文件下载/校验和 8GB 两阶段上下文方案。2026-08-13 唯一 GGUF 已通过普通文件、精确
  `5,198,387,456` bytes 与 SHA-256 `7deb50ec…54802a` 校验；Git 未跟踪。
  真实 ignored `rondo.local.toml` 已于 2026-08-15 迁移到 exact GGUF 与 12k 合同，
  `providers`、`paid_eval` 与价格配置未变、权限仍为 0600。冻结选择见 2026-08-12 快照，
  下载/CUDA 证据见 2026-08-13 快照。
- **Local M4 已完成，人判结论为“保留为实验”**：synthetic 主体用冻结 v1 裁判合同评完全部 130 条，真实
  holdout 16 条作为独立 sanity anchor 单独评、单独解盲、单独聚合，两者从不合并分母。裁判为经 Claude Code
  订阅入口、人在场的 `claude-opus-5`（2026-08-16，时点判定，不宣称可复现）。
  1. **synthetic（130 条）**：未微调侧教师一致 104/130（80.0%），微调侧 130/130；相对 Opus 独立判断，
     未微调误拦 26、微调 0，两侧漏放均为 0；理由被判“弱”的从 29 降到 5。两侧结构化输出均 130/130 成功。
  2. **真实 holdout（16 条）**：未微调侧只产生 14 条合规判定（2 次结构化输出失败），有效判定内教师一致
     8/14（57.1%）、误拦 6；微调侧 16/16 合规、教师一致 15/16、误拦 1；漏放均为 0。
  3. **两条必须同时记住的限制**：validation 与 470 条训练数据同源，且每条证据几乎逐字写明判定线索，
     所以 synthetic 的高一致率很大程度是“线索匹配”而非通用审批判断；holdout 的教师标签与裁判独立判断
     **全部为 allow**，因此该锚点只能发现误拦与可用性问题，**无法检验过度放行**。这两点正是“保留为实验”
     而非“采用”的直接依据。
  4. **顺带发现**：盲评中 130 条 synthetic 里有 10 条冻结 Sol 目标的理由被判为弱——它们断言了证据中
     并不存在的具体事实（如“校验和不匹配”、“dry-run 报告”）；其结论仍被判为成立。
  5. 因真实 holdout 出现 2 个既有结构化失败终态，经用户现场授权新增 **holdout 专用** terminal-carrying
     v2 裁判合同以完整表达 16/16；冻结 v1 未修改，synthetic 仍用 v1。无判定候选记为 `no_decision`，
     不得进入偏好，也不当作隐含 deny。
  6. 结论只记录，**未改动生产默认、provider、launcher 或部署**。body-free 结果锁为
     `eval/locks/local-approval-m4-formal-review-v1.json`；逐条输入、模型输出、seed、mapping、裁判理由与
     解盲明细永久留在 ignored `eval-data/cross-eval/20260816-cross-eval-01-synthetic/` 与 `…-02-holdout/`。
- **Local M4 正式输入（历史）**：tracked body-free cohort 精确绑定 L5b 全部 130 条 validation 与
  dataset/payload/target/source-group/near-duplicate-group 身份，确定性分为 65 / 65 两批。三方完整导入会重算
  canonical input，并要求未微调/微调 Local 同属一个 L6 pair，base lineage、runtime、chat template、request、
  sampling 和 output contract 相同；Plan 033 部署 baseline 不能冒充成对未微调工件。裁判 prompt/schema、私有
  seed/mapping、逐批位置平衡、裁判结果身份、私有解盲聚合及独立 holdout 批次摘要合同均已冻结。Plan 037 已用同源
  paired-GGUF 完成未微调/微调 Local 各 130 条诚实终态，连同 frozen Sol 侧形成 390 行；canonical pair receipt 与
  private evidence 已通过正式文件导入；这批输入随后被 Plan 041 直接消费，未重跑。

### 当前推进顺序

1. **L5b 与 M4 离线准备均已完成**：600 条合成训练资产及 130 条 validation 主体 cohort 已冻结；真实 holdout
   未被本次准备任务打开或物化。
2. **L6 已完成**：470 条 train-only completion-only QLoRA 完成真实 optimizer smoke、隔离 adapter reload、
   一个冻结 recipe 的正式训练与本地逐文件回收；paired-GGUF 两侧由冻结 b10333 串行生成 130×2，正式导入为
   `ready_for_blind_packaging`。任务 Pod/volume 已删除，未使用 HF，未依据 validation 重训。
3. **Local M4 已完成（Plan 041）**：390 行 synthetic 输入与新物化的 16 条真实 holdout 分别完成盲化、
   裁判、解盲与聚合，人判三选一结果为**保留为实验**。方向 2 没有已排期的下一工作包。
4. **若将来要投入真实使用**，必须另行立项并先补上两处证据缺口：合成集需要不逐字写明判定线索的样本，
   真实锚点需要包含 deny 的标签；在此之前不得据现有数字宣称模型可安全放行。

真实模型加载/推理与重型 Cargo、Docker 互斥。12k qualification 通过后能力为
`gpu_model_serving_validated`；该能力严格绑定当前 12k 服务参数与 static payload v3，任一项漂移即自动退回
`linux_cuda_built_model_unvalidated`。

## 核心设计（已定，不再反复讨论）

- **正式端到端测评统一用 `--approve-for-me` 对应的三项配置**：
  `approvals_reviewer = "auto_review"`、`approval_policy = "on-request"`、
  `sandbox_mode = "workspace-write"`。Guardian 另显式覆盖为指定云端模型 + `low` effort，继续使用
  Codex 原生 Guardian 框架与只读取证能力。0.147 的 CLI shorthand 一次展开这三项；测评元数据
  仍逐项记录，不能只写一个模糊的“approve for me”。
- **具体云端模型不在本页固定**：历史 v1—v22 使用 `gpt-5.6-luna` + `low`；**Luna 当前不可用**，
  新批次的供应商、base URL 与模型由 ignored `rondo.local.toml` 的 `paid_eval` profile 选择，
  再由每批的独立 pair lock 冻结实际条件。
- **为什么必须显式指定模型**：`v0.147.0` 的默认值已不是单一的
  `codex-auto-review`：OpenAI API key 路径默认 `gpt-5.6-luna`，ChatGPT 路径默认
  `codex-auto-review`，Bedrock 则返回 provider 自身模型 id；候选不在 catalog 且无 metadata
  override 时仍会回退主模型。测评必须显式写死模型与 effort，以免认证方式或 provider 变化暗中改变实验变量。
- **`Guardian-live` 是真实可部署系统的结果**；同证据 static 组才是严格的模型横向比较。
  static 组统一**不给模型任何工具与自主调查能力**：static consumer 必须移除顶层 `tools`，
  也必须移除 Lite `input` 中的 `additional_tools` developer item，再构造 provider-neutral 的单轮结构化请求。
  只检查“没有顶层 tools”不足以证明无工具。（这里说的“无网络”指模型侧没有自主联网能力；
  runner 仍需联网访问云端 API。）
- **`E_final` 有两种等价的完整逻辑请求形态**：标准 Responses 把 Guardian policy 放在顶层
  `instructions`、工具放在顶层 `tools`；Responses Lite 把 policy 改放
  `input` 里的 developer message，工具改放 `additional_tools` item，顶层 `instructions` 为空且
  `tools` 缺席。影子回放必须先解析成统一的逻辑 payload，不能假设固定 JSON 位置。
- 这组对比回答的是“面对实机 Guardian 实际收集到的同一组证据，不同模型会怎么判”，
  **不宣称**比较了各模型拥有工具后的完整 Agentic 调查能力。
- **严格耗时测评期间不在线运行影子模型**，尤其避免本地 8B 模型造成 GPU/CPU/内存/温度/调度波动；
  只记录证据包，任务结束后离线回放。
- 不自建第二套会话系统、不做证据链重建或工具状态机，只在 Guardian 请求发送前截快照（见 P0-S2）。
- `v0.147.0` 的 Guardian policy/template 与审批 prompt 已有实质变化，approval/retry reason 也会成为
  有意义输入。证据与标签必须记录 policy/baseline 版本，不把 0.146.1 和 0.147 样本静默混合训练或横评。
- **预留但不现在做**：若后续要研究“取证调查本身值多少分”，只需额外保存该审批轮的**首个**请求 `E0`，
  与 `E_final` 对比即可，仍然不引入会话管理或证据链重建。P0 只做 `E_final`。

## 任务分解

### L1 静态影子审批协议（规模 S）

状态：**已验收**。

- 输入：规范化 `E_final`；输出：结构化判定（allow / deny + 理由 + 风险标签）。
- 所有 static 组共用完全相同的输入与输出契约，任何一方多拿信息都视为设施 bug。
- 硬性：出站请求既不得包含顶层 `tools`，也不得在 `input` 中携带 `additional_tools`，
  也不得携带 `reasoning` item、`encrypted_content` 等 provider 私有运输内容。
- 验收：单测同时覆盖标准 Responses 与 Responses Lite 的 `E_final`，将两者解析为
  **规范化逻辑 payload**（policy/instructions + 任务 input + 输出 schema），再断言各 static 组
  逐字节一致；同时断言出站请求既无顶层 `tools`，也无 Lite `additional_tools`。provider URL、
  headers、认证方式天然不同，不在比较范围内。
- 原始 `E_final` 保留 `internal_chat_message_metadata_passthrough.executed_tool_calls` 以忠实记录 wire；
  该字段按上游契约仅供 warehouse，构造 static 逻辑 payload 时必须排除。

### L2 本地推理服务接入（规模 M）

- 形态：起本地 OpenAI 兼容 HTTP 服务（llama.cpp server，GGUF `Q4_K_M`），通过
  `codex-rs/model-provider-info` 的既有 OpenAI 兼容 provider 配置指向它。**不新增 provider crate**。
- 运行时固定为 **llama.cpp server**，统一使用 `/v1/responses`；根目录受跟踪的
  `rondo.local.example.toml` 定义参数合同，机器实际值写入忽略的 `rondo.local.toml`。API Key 只从根目录
  忽略且权限收紧的 `.env.local` 按变量名加载，不进入 TOML、命令行、日志或工件。linked worktree 的加载器
  必须通过 Git common dir 定位主仓库根，复用同一份本机配置，不在各 worktree 复制密钥。
- 硬件约束（RTX 4060 Laptop 8GB VRAM）：8B 级模型 Q4 权重约 4.8GB，剩余显存要留给 KV cache；
  **上下文预算已实测**。47 条真实 `E_final` 在 v3 下全部取得 exact input-token 数：5,311—22,499 tokens。
  按 `input+512`，4k/8k/12k/16k 分别覆盖 0/11/42/45 条；首个资格目标已在覆盖率与 8GB 显存压力之间
  选择 12k。能被计数或长度适配不等于能在该档位内完成真实推理，仍以 model-backed qualification 为准。
  12k 实测：`--fit` 自动收敛到 33/35 层 offload，资格运行峰值 7,855,931,392 B，f16 K/V 够用。
- 验收：**已通过**（2026-08-15）。本地服务对一条真实 `E_final` 返回合规结构化判定，并记录了显存峰值
  7,855,931,392 B、首 token 3,183 ms 与总耗时 7,049 ms。

### L2a Guardian provider 覆盖（规模 M，L7 的前置）

状态：**已验收**。实现与证据见 `plan/019-l2a-guardian-provider-override-execplan.md`。

- `[auto_review].model_provider` 引用合并后的 `model_providers` registry；未知或空白 ID 在配置加载时
  fail-closed，项目局部配置不能重定向 provider。
- Guardian 替换 provider ID 与完整配置后仍把 request/stream retry 固定为 `1/1`；未配置时继续继承
  主 Agent provider，主 Agent 配置与端点不变。
- 显式独立 provider 按自身 env/static bearer/command/无鉴权语义工作；无鉴权 endpoint 不接收主 Agent
  凭据，鉴权继承策略也参与 Guardian session 复用失效。
- 阶段 B 已通过 schema、config/Guardian 安全回归与两个 loopback mock endpoint 验收。该结论只证明
  provider 分流设施，不代表 L2 本地模型已经加载或 L7 端到端切换完成。

### L3 离线影子回放器（规模 M）

**只有 `Local-static` 由 `eval/` 程序化批量运行。** 教师侧判定不经程序化调用，而是人在场时用仓库内冻结的
prompt **经开发用 Codex（Sol）**生成，落成冻结标签文件供 L3 导入 —— **不走 Claude Code / Opus 5**，
那条入口只用于 M4 裁判，避免角色混用。这是订阅制入口边界的直接后果，
同时意味着**不为教师侧另开按量付费 API 入口**。

- 教师侧输入：导入 **L5a** 冻结的教师标签，按稳定语义身份与 `E_final` 对齐；
  每批必须带 Sol 模型标识与生成日期（字段合同见 `doc/eval-data-layout.md` §4）。
- 本地侧：批量读取 `E_final` 喂给 `Local-static`，记录判定、理由、耗时、token 与显存峰值。
- 与正式耗时测评完全解耦，不在线运行。
- 结果写入方向 0 的统一结果库（共用 schema）；教师侧的行必须标记为**导入**，不冒充自动运行产物。
- 产出：本地模型**未微调** baseline 相对教师标签的首版对比数据。
- **L3 不是里程碑**：Local M3 由真实本地审批闭环认定（见下文），L3 只提供数据。
- **顺序依赖**：L3 的教师侧输入依赖 L5a，因此 **L5a 先于 L3**；L5b 合成训练数据仍在 L3/L4 之后。

### L4 审批质量指标（规模 S）

固定一组指标口径，**在第一次正式 M4 横评前定死并写进模板，后续轮次只填数不改口径**：

- 未微调 Local、微调后 Local 各自与 **Sol 教师标签**的总体一致率（称“教师一致率”）。
- 按 **Opus 裁判结果**分开的两个数：该拒绝却批准（**漏放**）、该批准却拒绝（**误拦**）。
  只有相对独立裁判结果时才使用这两个质量名称；单纯相对 Sol 教师标签的差异只称“教师不一致”，不叫漏放/误拦。
- 工程可用性指标，与判断质量分开报告：结构化输出解析失败率、超时与 fail-closed 触发次数、
  单次审批 token 成本、P50/P95 延迟、本地侧显存峰值。
- 微调后 Local 与未微调底模的差值 —— 判断“这轮微调有没有用”的直接依据。

**不设“一致率 ≥ X%”这类机械门槛**，也不需要另建人工标注 ground truth 集；教师标签的性质见上文角色分工。

### L5 教师标签与合成训练数据管线（规模 M）

L5 分两部分，**执行时点不同**：

| 部分 | 内容 | 时点 |
|---|---|---|
| L5a 教师标签生成 | 用冻结 prompt 人在场经开发用 Codex 生成 Sol 判定，落成冻结标签文件 | **先于 L3**（L3 的教师侧输入） |
| L5b 合成训练数据 | 基于 `seed` 分区批量合成训练样本 | L3/L4 之后、L6 之前 |

L5a、L3/L4 与 L5b 均已于 2026-08-15 完成。L5a 的冻结合同和哈希见
`eval/locks/local-approval-sol-teacher-labels-v1.json`；L5b 的合同、数据卡、机器摘要及 470/130 split 见
`training/local-approval-synthetic-v1/`。

- 两部分都用**订阅制 Sol 经开发用 Codex 生成**，人在场、发送预写 prompt，不依赖真实跑批规模，
  也不占 API 预算门；`eval/` 只导入冻结产物，不程序化调用。
- L5a 覆盖 L3/L4 要回放的那批 `E_final`，**含 `holdout`**——按下表，为评测生成教师标签属允许用途。
  `seed`/`holdout` 切分先于 L5a 与 L5b 完成。

**真实 `E_final` 必须先做互斥切分，再谈用途。** 让同一批真实证据既当合成模板又当评测集，即使原文没进训练集，
基于评测样本生成训练数据仍是信息泄漏。因此：

| 分区 | 允许用途 | 禁止 |
|---|---|---|
| `seed` | 给合成器做格式与难度模板（几十条足够） | —— |
| `holdout` | 只用于**评测**：L3/L4 对比、M4 锚点，以及为这两者生成教师标签或裁判判定 | 进入 **L5b 合成上下文、合成 prompt 或合成期人工参考**；进入训练集 |

**禁令的范围是合成/训练，不是评测。** 把 holdout 证据放进评测用的标签生成 prompt 或 M4 裁判 prompt 是
允许且必要的 —— 没有教师标签就无法评测。被禁止的是它以任何形式影响训练样本的构造：
合成器的上下文、合成 prompt、以及人在做合成时对 holdout 的参考。

- 切分键必须是**跨运行稳定的语义身份**：`sha256(task_id + 规范化待审批动作指纹)`，无 task_id 时退化为
  动作指纹本身。不能用 `review_id`——`new_guardian_review_id`（`core/src/guardian/review.rs`）每轮生成新的
  UUID v4，互斥就只对文件实例成立、对语义样本不成立。
- 切分不按人工挑选，避免选择偏差；切分结果写入清单并冻结，后续增量按同一规则划分，不重划历史。
- **近重复检查**：合成产出的训练样本对 `holdout` 做一次近重复检测（n-gram Jaccard 或 MinHash 即可），
  命中阈值的样本剔除并记录数量。
- 合成要覆盖的分布：明确安全、明确危险、边界模糊、证据不足、伪装成安全的危险动作、工具结果与请求不一致。
- 产出：训练集 JSONL + 数据卡（Sol 模型标识与生成日期、合成方法、seed 分区来源、分布、去重与近重复检查结果、
  SHA256）。

L5b 冻结结果：当前人在场开发用 Codex `gpt-5.6-sol` 只使用 seed 24 条受控投影作为参考，生成 600 个唯一候选并
全部通过 strict static-v3/decision-v1 校验；六类分布为 180 / 100 / 120 / 70 / 65 / 65，allow 240、deny 360。
精确重复为 0；holdout 16 条只由本地程序在内存中按版本化 word 5-gram 规则比较，命中 0，未公开逐条映射。
最终 120 个近重复组整体划分为 train 470 / validation 130。两份正文共 1,670,240 bytes，单文件均低于 40 MB，
因此随 prompt/schema、manifest 和数据卡进入 `training/`；seed 投影、候选、authoring 与过滤明细留在 ignored 私有区。

### L6 微调回路（规模 L，三重授权门）

**路线：LoRA，训练在云 GPU 上进行。** 本地开发机为 RTX 4060 Laptop（8 GB 显存），8B 模型在 4k 序列下做
4-bit QLoRA 已经很勉强，8k 基本不现实；训练放本地会把上下文长度这个实验变量卡死在硬件上。

这条决定使 L6 落在 `doc/WBS.md` §6 的多个授权门之下，**必须作为独立任务单独申请**，不能顺带执行：

1. 云 GPU 训练本身（产生外部费用）；
2. **训练数据外发** —— Sol 生成的合成标签要上传到云端；即便都是本项目自造数据，也属于真实数据外发；
3. 权重下载回本地。

Plan 037 已按三重授权门完成：阶段一本地 mock/census/train-only bundle 与阶段二A转换/回收闭环先行交审，付费阶段
在唯一 RunPod A40 上完成真实 optimizer step、adapter 保存与隔离重载；smoke 不需技术漂移，随后冻结同一 recipe
完成一个有效正式训练。产物已逐文件回收，本地部署因 adapter converter 实证不兼容而改用同源 paired-GGUF；这只改变
部署格式，没有第二个训练 recipe。

- **推理仍在本地**：训练产出的 LoRA adapter 或由其生成的合并/量化工件必须能由本地 llama.cpp runtime 加载，
  **训练侧的量化、转换与格式选择必须以本地推理可落地为约束**，不能训完才发现用不了。
- **训练前后可比性**：两份 Local 工件必须来自同一底模谱系，并固定相同 runtime、prompt、采样和结构化输出条件。
  最终采用 adapter on/off 还是从同一训练谱系生成成对 GGUF，由 L6 实施计划按本地 runtime 兼容性决定；
  本页不预先写死，也不把当前部署用 GGUF 直接当作训练效果归因工件。
- **轮次封顶：只允许一个有效正式 recipe/训练。** 在成功 smoke 前，明确的依赖、OOM、target module、保存或基础设施
  技术失败可在预算内窄修并有界重试；一旦冻结 recipe 完成有效正式训练，不得因 validation、loss 或主观质量再改配重训。
  后续 Local M4 只做人判三选一 —— **采用 / 保留为实验 / 停止**。

仓库边界按数据体量决定（L5b 出数后立即确认）：

| 条件 | 处置 |
|---|---|
| 训练集总量 ≤ 100MB 且单文件 ≤ 40MB | 数据集与训练脚手架一起放仓库内独立板块 |
| 超过上述阈值 | 仓库只留训练脚手架 + 数据卡 + SHA256，数据集放仓库外 |
| 模型权重（GGUF / LoRA adapter） | **始终**在仓库外，无论大小 |

首批 L5b 正文已确认符合入库门限并落在 `training/local-approval-synthetic-v1/`；该结论只适用于此冻结批次，
后续新数据仍按同一门限重新判断。

- 目录形态：新增顶层 `training/`（脚手架、数据卡、模型版本登记表），与 `mydev/`、`multidev/` 严格隔离，
  不参与 Rust 构建。落地时需同步更新 `AGENTS.md` 的仓库边界一节。
- 仓库内必须留下的最小可复现信息：超参、基座模型与版本、数据卡、产出权重的哈希与对应横评结果。

### L7 一键切换与端到端可用性（规模 S，依赖 L2a）

状态：**已独立验收**（2026-08-15）。实现与证据见 `plan/031-local-guardian-config-switch-execplan.md`。

- 通过 **S1（模型/effort）+ L2a（provider）** 三个配置项把 Guardian 审批切到本地模型。
  **仅有 S1 做不到这件事**：实跑确认未设 `model_provider` 时 Guardian 请求落到主 Agent provider。
- 正式 Guardian 不能直连 raw llama endpoint。冻结 b10333 不映射 `text.format`、在 `tools` 与 grammar
  并存时抛错、并把 `developer` 角色映射成模板拒绝的 `system`；通用 provider 路径也不消费 launcher
  receipt，无法在请求窗口内判定身份漂移。接通方式是 eval-side 身份门控适配器
  （`eval/rondo_eval/local_approval/guardian_bridge.py`）：入站请求交给公共 `build_static_payload()`
  归一化后按冻结服务合同重建，响应完整缓冲且在身份后验通过前不交付，判定按 Guardian 自己送来的
  schema 校验。**产品代码未改**，通用 allow/deny、provider 选择与 fail-closed 语义不变。
- 仅在非严格耗时场景验证；正式耗时测评仍按核心设计走云端 `Guardian-live`。
- 验收（`eval/rondo_eval/local_approval/formal_switch.py` 五场景）：真实 `--approve-for-me` 链在本地
  12k 上返回生产 parser 可接受的 allow，待审批动作执行；服务异常、身份漂移与请求契约不符三类都不执行
  动作、记 `terminal_status=failed_closed`（与业务 deny 可区分）、不回退主 provider。
  cloud/local 差异只在 `[auto_review]` 的 model/effort/provider 三轴及其 provider registry 条目，
  主 Agent provider 不受影响。云端侧只做离线无残留证明，未发出云端请求。
- **L7 不单独构成里程碑**：它的配置切换验收并入 Local M3，因此归在 P2 而非 P3。

## 里程碑口径

### Local M3 —— 工程闭环（工程验收）

状态：**已完成并通过独立验收**（2026-08-15）。

12k model-backed、结构化输出、真实 `E_final`、错误 fail-closed，以及**仅通过配置**在 cloud/local Guardian
之间切换，共同形成真实本地审批闭环。用功能与失败语义验收，**不继承公平比较设施的 `σ`/`delta` 判据**。
该里程碑只证明 12k 档位内的真实闭环，不宣称剩余 5 条超窗证据已可服务。

两处覆盖边界如实保留：真实链上验证的失败通道是适配器的 HTTP 错误通道到 RONDO fail-closed 这一段；
“结构化输出不合规”与“响应读回后的身份后验”由定向回归端到端覆盖，因为要让已资格化的模型吐出不合规
判定只能改 prompt 或放宽 parser，两者都被硬约束禁止。

### L5/L6 前置 dry-run —— 不是里程碑

训练前用约 **5—10 条**样本排查：标签与审批场景是否清楚、Sol 教师输出是否适合作为训练目标、
未微调 Local 能否稳定输出规定结构，以及 Opus 判定标准与产物格式是否可操作。
它**不保存一套正式分数**，也不构成里程碑，更不是“训练前的一次完整横评”。

### Local M4 —— 人判定

状态：**已完成**（2026-08-16，Plan 041）。人判结论为**保留为实验**，数据与限制见上文“当前状态”。

在同一批冻结样本上正式比较**三方：Sol、微调后 Local、未微调 Local**。
加入未微调 Local 是为了把“微调带来多少增益”与“底模本身有多少能力”拆开；训练完成后同场运行即可，
无需训练前重复做一次完整横评。不设质量机械阈值，由人根据冻结对比结果作**采用 / 保留为实验 / 停止**决定。

**合成主体规模已冻结**：正式主体只使用 `training/local-approval-synthetic-v1/validation.jsonl` 的全部
130 条，不抽样、不混入 470 条 train。source 与近重复 group 的联合闭包不可跨批；当前确定性两批各 65 条，
单批 ≤100。两批使用同一裁判 prompt/schema；若以后必须换 prompt，应升级合同并形成新 cohort，不得在同一
正式主体内静默漂移。

**裁判 prompt 冻结**：裁判 prompt 与判定标准**预先设计成仓库内的版本化文件**
（放 `eval/templates/cross-eval-judge/`，与既有 `eval/templates/local-approval/` 并列），
使用时由人直接复制发送，不在会话里即兴撰写。每批 JSONL 记录所用 prompt 文件的版本标识与内容哈希。
理由：会话内即兴写 prompt 会让“标准”随批次漂移，而这恰是本方案唯一不可复现的环节；
prompt 是少数能被完全冻结的部分，必须冻死。首版为
`eval/templates/cross-eval-judge/local-m4-judge-prompt-v1.md`，结果与 blinding/holdout schema 同目录版本化。
三个被评方必须收到**同一份证据、同一 prompt**；裁判看到的三份输出必须**匿名化且顺序随机**，
否则“哪个是 Sol”这一信息本身就会影响判定。

**三方导入与成对归因**：`sol-static` 只取 validation 已有的 point-in-time target，不重新调用教师；
`local-static` 与 `local-ft-static` 必须由 L6 同一 pair 生成，除工件角色/身份与训练 receipt 外，共享 base lineage、
runtime、chat template、request、sampling 与 output contract。L6 还必须提供两侧 canonical b10333 deployment
manifest，绑定实际加载的 GGUF/adapter、共同转换/量化身份及 formal source adapter tree；正式私有文件导入从
0600 evidence locator 重建并重哈希这些来源。只有合同 JSON、输出自报字段或 Plan 033 baseline 均不被接受。三方每条都回显完整
canonical approval input，由导入器与冻结 validation 深比较；缺 side、重复/未知 side、正文/消息边界或任何身份
漂移都拒绝。

**证据来源：合成证据做主体，真实 `E_final` 做锚点，两组分开记录、不混算。**

- 现实约束：全项目目前只有 **47 条真实 `E_final`**（分布在 24 个 run 目录，内容互异）。
  47 条在 v3 下都已被冻结本地运行时精确计数，但**能被计数不等于能在选定档位内被推理**：
  锚点规模按定档后实际装得下的条数计，而不是默认 47；
  按稳定语义哈希规则预估切分后 holdout 约 20 条；**实际数量必须以尚待生成的冻结 manifest 为准**。
  无论最终数量多少，它都撑不起 200—300 条的判定规模，且这 47 条全部来自 TB 2.1 任务运行，审批情境单一。
- 因此主体横评使用 L5b 已冻结的 **130 条合成 validation 场景**；它们只提供时点 Sol 蒸馏目标，不冒充
  人工 ground truth。
- 真实 holdout 单独报一组数作为 **sanity anchor** —— 用途是发现“合成场景与真实分布严重脱节”，
  不用于比较三方强弱。真实证据的 `seed`/`holdout` 切分仍按 L5 的稳定语义哈希规则，不另立一套；
  真实证据不得进训练集这条不变。当前只冻结独立私有导入与批次级 tracked 摘要合同，没有读取正文或物化
  anchor 包；synthetic 与 holdout 聚合入口拒绝混算。

**两条必须写进合同的现实限制**：

1. **不可完全复现**。订阅侧模型版本不由本项目冻结，可能随时间变化。判定时必须记录 Claude 模型版本与
   判定日期，并把该批结果标注为“该时点判定”，不假装可重跑复现。
2. **不自动归档**。会话内判定不满足测评体系“自动运行、自动记录、自动归档”的默认要求，
   因此必须约定固定产物格式：每批判定输出一份**冻结 JSONL**，含证据哈希、prompt 版本、各被评方输出、
   裁判结论与理由，落到 `eval-data/` 下的独立命名空间。

## 与方向 0 的接口

- 消费：P0-S2 产出的规范化 `E_final`。
- 复用：方向 0 的结果库 schema、归档脚本与产品身份字段。
- 反馈：L4 的审批失败归因回流到方向 0 的 B5 失败归因分类。
- 不消费公平比较设施的 `σ`/`delta` 判据：Local M3/M4 都不继承那套机械门。

## 硬约束

- 各 static 组的**规范化逻辑 payload** 必须逐字节一致，不得任何一方多拿信息（provider URL / headers / 认证除外）。
- 静态影子一律不给模型工具与自主取证能力；runner 访问推理端点不受此限。
- 真实证据包不进训练集；`holdout` 分区不得进入合成上下文、合成 prompt 或合成期人工参考。
  为评测生成教师标签与裁判判定不受此限（见 L5 分区表）。
- 权重文件不进仓库。
- 严格耗时测评期间不在线跑本地模型。
- 一键切换不得以弱化审批逻辑为代价换取通过率。
- 把证据包或合成数据发给云端属于**数据外发**，须单独授权；首次外发前人工抽查一批样本，
  确认没有明显不应外传的内容。订阅制入口不额外计费，但不豁免数据外发门。
- 订阅制入口（Sol、Opus 5）只用于人在场监督的会话内工作，不作为程序化批量后端接进 `eval/`；
  每批必须记录所用模型标识与日期。
