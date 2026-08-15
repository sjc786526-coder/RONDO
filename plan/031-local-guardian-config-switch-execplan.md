# Plan 031：RONDO Local Guardian 正式路由、L7 配置切换与 Local M3 收口

> 本计划是本任务的稳定约束文档。目标、完成标准、安全边界与非目标是任务合同；实现路线、文件拆分与执行顺序
> 不属于固定合同。执行者可依据 live code、定向测试和失败证据调整实现，并更新“当前状态”和“关键决策记录”。
> 用户下发本计划的最终实施提示词后，其中列明的单次执行授权生效；在该授权和风险边界内无需逐项请示。
> 只有需要改变目标、降低 fail-closed、触及云端/Docker/项目外状态或明显扩大产品范围时才暂停。
> 跨任务路线、优先级与依赖以 `doc/WBS.md` 和
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

选择并实现当前代码形态下最小、可靠的本地 Guardian 正式路由，使 RONDO Local 能仅通过 S1 的
`[auto_review].model` / `reasoning_effort` 与 L2a 的 `[auto_review].model_provider` 在云端 Guardian 和已取得
`gpu_model_serving_validated` 资格的本地 12k 模型之间切换。通过正式 `--approve-for-me` 链完成受控真实审批，
验证关键异常 fail-closed，恢复云端配置并清理现场，关闭 L7 和 Local M3。

默认优先复用现有 eval/local-approval 设施形成最小兼容层；若 live code 证明一个非常窄的产品改动更简单、
更可靠，且不改变通用 Guardian 语义，执行者可选择该路线，补定向回归并在决策记录中说明理由。

### 完成/验收标准

- 当前 RONDO Local 可执行文件的源码身份包含 L2a，并与本任务配置相容；正式运行仍使用现有
  OpenAI-compatible provider 机制，不以开发用 Codex、冻结上游 Codex 或早于 L2a 的旧 bundle 替代。
- 正式 `--approve-for-me` 链真实消费本轮 `E_final`，本地 12k Guardian 返回生产 parser 可接受的结构化
  allow/deny 判定，审批流程达到与判定一致的终态；待审批动作只在 allow 时执行。
- local/cloud 的最终切换只改变运行配置：Guardian 的 model、reasoning effort、provider 均显式生效，
  主 Agent provider 不被意外重定向；切换过程中不需要再次修改代码。
- 正式链对本地服务异常、launcher/service 身份漂移、结构化输出不合规三类关键失败均 fail-closed：
  不执行待审批动作，不把异常伪装成业务 deny，不静默回退主/云 provider。
- 身份判定覆盖真实请求窗口；在身份后验通过前，不得把可被 RONDO 接受为成功审批的结果交给正式链。
  具体校验点、进程布局和响应门控方式由执行者依据所选实现决定。
- 所选实现有直接相关的定向回归，证明正常路由、三类失败语义、凭据边界和清理；所有声称通过的测试实际运行，
  0 unexpected skip。fake/loopback、正式 CLI、真实模型证据明确区分。
- 原云端配置全程不被覆盖；结束后无本地 provider override、本任务 bridge/adapter/model/fixture 进程、任务端口、
  launcher receipt、临时配置、私有 evidence 或其他运行影响残留。恢复证明不依赖真实云端请求。
- 密钥、真实证据原文和模型自由文本不出现在终端、日志、Git 或交付摘要中。程序可以在内存中解析
  `E_final.json` 的最小请求字段，并单独读取 `meta.json` 的必要 allow-list 字段；不得打印、复制、长期保存或提交原文。
- tracked 改动只包含完成上述合同所必需的窄实现、相邻测试、配置示例和任务文档；无关产品行为和接口不变。
- 只有全部完成标准有实证支持时，才把 L7 与 Local M3 标记完成；否则按真实 blocker/失败收口。
- 所有 tracked 改动在现有 `031-local-guardian-config-switch` worktree/分支自审并提交；不合并、不推送、
  不删除 worktree、不重命名分支。

## 2. 范围

### 允许修改

- `eval/rondo_eval/local_approval/`、`eval/rondo_eval/config.py`、`eval/tests/` 和 `rondo.local.example.toml` 中
  为本地正式路由、身份校验、wire 兼容、严格配置或定向回归直接需要的窄改动。
- 若 live code 证明确有必要，允许修改 `mydev/` 中与 Guardian provider/transport/identity 直接相邻的最小产品代码
  与测试；必须保持通用 Guardian allow/deny、provider 选择和 fail-closed 语义不变，并在决策记录中解释为何
  比额外兼容层更简单可靠。
- 所选方案直接需要的相邻配置 schema/fixture/CLI 支持；不预先限定文件名、模块拆分或进程编排。
- 本计划的“当前状态”和“关键决策记录”；成功后精炼更新 `doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md`，并新增一份 `agent_log/`。
- 专用 worktree 内、受仓库 watchdog 监控的 Cargo target/metrics 和本任务明确创建的临时测试对象。
- **因 Git common root / gitignore 只能在主工作区原位处理的 private 对象**：
  - `/home/sjc/desktop/RONDO/rondo.local.toml`：只做所选方案需要的最小非密钥机器配置，保持普通非 symlink、
    mode 0600 与无关配置不变；
  - `/home/sjc/desktop/RONDO/.env.local`：只由既有严格 loader 静默使用，不直接编辑或查看；
  - `/home/sjc/desktop/RONDO/eval-data/local-approval/`：receipt、临时配置、私有 evidence 与运行对象；
  - `/home/sjc/desktop/RONDO/eval-data/tools/`、模型路径与合格 runtime：按既有资源锁和身份只读使用。

### 不允许修改

- 与本地 Guardian 正式路由无直接关系的 `mydev/` / `multidev/` 产品代码、测试、schema、Cargo/Bazel 文件、
  provider API、通用 Guardian 语义或其他功能；禁止无关重构和顺手清理。
- Plan 030 qualification evidence、runtime/model/template lock、static payload v3、census baseline、run ledger、
  正式历史结果或旧日志；若新实现需要新的验证证据，应另建本任务私有对象，不改写历史。
- 通用代理、证书/签名/attestation、审计账本、日志平台、多租户鉴权、第二套审批逻辑或不必要的长期服务。
- 16k、剩余 5 条超窗证据、其余 41 条 12k 适配证据、47 条批量 generation、教师标签、指标横评、
  L3—L6、训练、模型优化、Docker、云 API、数据外发、全量测试或全量 eval。
- 项目外真实 Codex 配置、宿主机/全局工具链/系统服务、其他仓库或来源不明运行对象。

### 不允许读取/查看

- `.env.local` 内容不得打开、搜索、打印、复制、hash 或 shell source；只可静默检查它是普通非 symlink、
  mode 0600，以及任务所需变量存在且非空。测试只使用 synthetic secrets。
- 项目外个人文件、真实 Codex home、认证文件、其他仓库或来源不明运行对象的正文。

## 3. 硬约束

以下约束只固定结果、安全与授权边界，不固定实现路线。

1. **执行入口与一次授权。** 用户下发最终 Claude 实施提示词即授权：本计划允许的项目内代码/文档与主仓 ignored
   配置修改、定向测试、loopback 进程、经资源门的重型 build 和受控本地模型生命周期。执行者先简要说明影响后
   直接实施；范围内纠错和有理由的定向重跑无需重复请示。Docker、云端、项目外状态或明显扩大产品范围仍需新授权。
2. **执行者拥有范围内自我纠错空间。** 可依据 live code 和定向证据选择 eval-side 兼容层或非常窄的产品改动，
   调整文件拆分、测试组织、执行顺序和合理重跑，并在计划状态/决策记录中说明重要变化。不得借此降低验收标准、
   扩大通用产品接口或夹带无关重构。
3. **正式链与真实 `E_final`。** 成功必须来自当前 RONDO Local 的真实 `--approve-for-me` turn 和本地 12k Guardian；
   qualification、doctor、fake、手工 JSON 或旧 evidence 只能作前置/定位证据，不能替代本轮正式闭环。
4. **失败必须 fail-closed。** 服务异常、身份漂移和输出不合规都必须阻止动作并保持明确失败；不得回退到云端、
   主 Agent provider 或宽松解析。allow/deny 是业务结果，transport/schema/identity 错误不是 deny。
5. **最终切换配置-only。** 支持代码落地后，cloud/local 切换只能通过运行配置完成；model、effort、provider
   三轴显式且独立，恢复后不存在有效的本地 provider override 或性能路径污染。
6. **秘密与私有证据不外泄。** 禁止 source 或输出秘密、把 key 写入受跟踪文件/argv/log/evidence，禁止把云端凭据
   送入本地链。允许程序在内存中解析 `E_final.json` 的最小请求字段（实际字段以 live schema 为准），并单独读取
   `meta.json` 中 `evidence` / `decision` / `terminal_status` / `model` / `reasoning_effort` 的必要 allow-list；
   禁止输出、复制或提交两者原文、rationale、risk tags 和模型自由文本。
7. **重型资源门。** 任何重型 Cargo 构建/测试必须经仓库根 `scripts/with-build-lock.sh` 接入的正式 `just` 配方，
   取得 build lock、cgroup、Windows C: 实际余量、项目存储与单热 target 事实，并与 Docker/其他 Cargo/真实模型互斥。
   真实 launcher 同样必须持有效 watchdog lease；任一资源事实缺失即 fail-closed。
8. **范围禁区。** 不运行 Docker、云 API、16k、超窗/其余 12k 证据、批量 generation、教师标签、横评、训练、
   模型优化、全量测试或全量 eval；不修改项目外状态。
9. **验证和重跑诚实。** 只跑所选实现直接需要的定向测试与正式验收；尽量减少 build、模型生命周期和重复负例，
   但失败后允许基于明确原因定向修复和重跑。日志必须区分首次结果、重跑原因、最终结果、skip 和未运行项。
10. **清理与里程碑。** 只停止本任务经身份确认的进程，来源不明对象只报告。全部证据和清理条件满足后才能更新
   WBS/WBS-COMPLETED 为 L7/Local M3 完成；否则记录 blocker，不写完成历史。
11. **工作树交付。** 提交前检查 diff、敏感/大文件、generated/ignored 残留及全部 worktree 状态；只提交当前
    worktree。未经用户批准不得合并、推送、删除 worktree 或重命名分支。

## 4. 软性建议

以下内容是基于当前代码的优先路线，不是实现合同。执行者可采用更简单、等强的方案。

- 优先考虑 eval-side 最小 loopback 兼容层，复用 `identity.py`、launcher 和既有 strict config；如果窄产品改动
  明显更简单可靠，可改选产品路线并补相邻回归。
- 若采用 bridge/adapter，建议在请求前后复用 launcher/service identity，并在身份后验通过前门控正式结果；
  有界完整缓冲是一个简单方案，但不是唯一实现。
- 冻结 b10333 当前不映射原生 `text.format`。若采用 wire 适配，可精确转换为其顶层 `response_format`，
  消费后移除原字段并对完整请求做保真回归；若产品侧有更窄可靠的请求生成方案，可按 live code 选择。
- bridge 的文件布局、是否使用 Python 标准库、host/port 配置形态和生命周期编排由执行者决定；只需保持本地范围、
  明确上游且不成为通用代理或长期服务。
- 本地链的具体鉴权实现由所选方案决定；只要 secret 经严格 loader 最小注入、云端凭据不进入本地链、
  secret 不落盘/日志即可。
- 临时 `CODEX_HOME` 与 invocation-scoped `-c` 都可采用；优先选择恢复最清楚、对原云配置零写入的方案。
- 建议先用 pure/fake/loopback 和当前 binary 的无模型 formal smoke 降低 wire 风险，再运行三类负例与真实模型；
  这只是推荐顺序，不限制基于证据的调整或定向重跑。
- 尽量复用现有测试文件和 fixture，但测试文件名、组织方式与数量由实现决定；不为本任务建立重复的长期套件。
- `E_final.json` 可由程序在内存中提取证明真实请求/model/effort/schema 所需的最小字段；`decision` /
  `terminal_status` 等结果从 `meta.json` 的必要 allow-list 读取。实际字段以 live schema 为准，不把两者原文
  带入终端、日志或 Git，也不另造证据审计系统。
- 云端恢复可用“原配置未改 + 本地 override 退出 + 无本地运行对象”证明，不需要真实云端复跑。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-15：核对主工作区 `main@26b4770` clean，较 `origin/main` ahead 8；Plan 030 已合入，
  12k capability 为 `gpu_model_serving_validated`，Local M3 尚未完成。
- 已阅读根/`mydev` AGENTS、README、两份 WBS、Plan 模板、Plan 019/030、相关日志和 live
  S1/L2a/launcher/doctor/evidence 代码；创建 `.claude/worktrees/031-local-guardian-config-switch` 与同名分支。
- 规划阶段仅 stat ignored 配置/目录：`rondo.local.toml` 与 `.env.local` 均为普通 mode 0600 文件，
  `eval-data/local-approval/` 为 mode 0700 目录；未读取两份 ignored 文件内容。
- live code 与独立审查确认：launcher identity 校验目前只由 Python local-approval client 使用；正式 Guardian
  provider 不读取 receipt，外部 doctor 前后检查不足以证明请求窗口内身份漂移 fail-closed。
- 冻结 b10333 不映射 Codex 原生 `text.format`；Plan 030 qualification 使用顶层 `response_format`，
  既有资格证据没有证明正式 Guardian wire 可用。
- 当前无 `mydev/codex-rs/target/{debug,release}/codex`；现成 `cb652e1…` bundle 早于 L2a，不能用于本任务。
- 用户已允许 Plan 031 适当扩展，并进一步明确：硬约束只固定结果/安全，优先 eval-side 路线但允许等强的
  非常窄产品改动；实现方式、顺序和有理由的定向重跑由执行者决定。
- 用户要求最终 Claude 提示词包含一次性执行授权；该提示词下发后，项目内窄改动、ignored 配置、定向测试、
  受锁 build、loopback 和受控本地模型生命周期均可直接实施。
- 规划阶段未启动模型/GPU、loopback server、网络、API、Cargo、Docker 或测试，未修改 ignored 配置。

- 2026-08-15：选定 **eval-side 最小兼容层**路线并实现完毕（决策 010—015）。`mydev/` Rust 源码未改，
  只在 `mydev/justfile` 增加一条受锁构建配方。
- 已用 `just build-codex-cli` 经 build lock/看门狗构建当前 worktree 的 RONDO Local binary（4m02s）；
  正式链实跑确认 S1 的 model/effort 与 L2a 的 provider 三轴都真实生效。
- focused tests 159/159、0 skip；`just eval-lock` 85 packages 通过。
- 正式 `--approve-for-me` 链五个场景全部完成：真实 12k 正例 allow 并执行动作，
  服务异常/身份漂移/请求契约不符三类均 fail-closed 且不伪装成业务 deny，主 provider 全程未被 Guardian 触及。
- 现场已清理：无残留进程、端口、receipt 或私有 evidence；显存回基线。
- 执行中修复了一处既有缺陷：launcher 收到 SIGTERM 不走清理路径（决策 015）。
- 独立审查发现并已整改：适配器原先在配置无 `model_path` 时会跳过全部身份校验照常返回判定，
  且新增 bridge 测试多数跑在身份门关闭状态（决策 017）；`switch_diff` 的主 provider 指标
  原为恒真，已改为对完整调用逐字比较并补反例测试。整改后在最终代码上重跑了真实 12k 正例与身份漂移。

### 当前工作

- 独立验收已通过；本任务冻结，后续路线交回 WBS。

### 本任务剩余步骤

- 无。四步（选路线、实现与回归、正式链证据、清理与记录）均已完成并提交。

### 阻塞项

- 无。

### 当前验收状态

- **L7 与 Local M3 的完成标准均有实证支持并已通过独立验收**（执行证据见
  `agent_log/2026-08-15-043608-plan031-local-guardian-config-switch.md`，验收报告见
  `agent_log/2026-08-15-050341-plan031-independent-acceptance-review.md`）。
- 两处覆盖边界如实记录，不冒充正式链证据：
  1. “结构化输出不合规”与“响应读回后的身份后验”只做到定向回归端到端；正式链上覆盖的是 bridge
     错误通道（400/503）到 RONDO fail-closed 这一段。要在真实 12k 上复现不合规输出必须改 prompt
     或放宽 parser，两者都被硬约束禁止。
  2. 云端侧只做离线无残留证明，未发出任何云端请求（决策 008）。

### 交接边界

- 执行者按结果合同完成本计划，不进入 16k、批量 generation、教师标签、横评、训练或模型优化。
- 审查者按完成标准和实际证据验收，不要求执行者逐字照抄建议步骤或预设架构。
- 本任务完成后冻结计划；后续路线只交回两份 WBS。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 031 不固定 bridge；优先 eval-side，允许等强的非常窄产品改动 | 用户要求让执行者依据 live code 选择更简单可靠的路线 | 实现边界 | 已采纳 |
| 002 | 身份后验通过前不得向正式链交付可接受结果，具体门控方式不固定 | 固定 fail-closed 结果，同时保留响应/进程实现选择 | 身份语义 | 已采纳 |
| 003 | b10333 `text.format` 缺口必须解除，但具体 wire 修复位置由 live code 决定 | 已知兼容事实不等于必须使用某一种 bridge 设计 | wire | 已采纳 |
| 004 | 只固定秘密最小注入和云凭据隔离，不固定本地链鉴权形态 | 不用安全结果反向绑死实现 | 凭据 | 已采纳 |
| 005 | build、测试、负例和真实模型顺序为建议；允许有理由的定向重跑 | 执行者需要依据失败证据自我纠错 | 执行 | 已采纳 |
| 006 | 程序可在内存解析 `E_final.json` 最小请求字段，结果字段从 `meta.json` allow-list 读取 | 同时满足字段真实来源、实证验收和私有证据保护 | 证据 | 已采纳 |
| 007 | 审查按合同与证据，不按预设步骤或文件布局 | 计划固定结果而非实现路线 | 验收 | 已采纳 |
| 008 | 云端恢复只做离线无残留证明 | 真实云端复跑涉及数据外发/费用，本任务未授权 | 恢复 | 已采纳 |
| 009 | 最终 Claude 提示词构成一次实施授权，范围内纠错无需重复请示 | 根 AGENTS 要求执行前明确授权入口 | 授权 | 已采纳 |
| 010 | 采用 eval-side loopback 适配器，不改 `mydev/` 产品代码 | 身份门控只有 eval 侧有 receipt 语义，放进产品会把测评专属身份塞进通用 Guardian；wire 适配同理。窄产品改动并不更简单 | 实现路线 | 已采纳 |
| 011 | 适配器用公共 `build_static_payload()` 归一化入站请求，不另写 builder | 正式链因此与 token census、12k qualification 共用同一条已被真实运行证明过的归一化边界，`developer→user` 与 reasoning 投影不存在第二套实现 | wire | 已采纳 |
| 012 | 不向冻结 b10333 转发 `tools` | 冻结源码在 tools 与 grammar 并存时直接抛错，且方向 2 硬约束本就规定 static 组不给模型工具与自主取证 | wire | 已采纳 |
| 013 | 判定按 Guardian 自己送来的 schema 校验，不改用 `rondo_static_approval_v1` | 本地模型应当回答 RONDO 的真实问题、满足生产 parser 的真实契约，无需再做一次结果翻译 | 输出契约 | 已采纳 |
| 014 | 主 Agent 用 loopback 脚本化端点，Guardian 侧走真链 | 本任务无云端授权；L7 验的是 Guardian 路由，主模型不是变量。RONDO 仍自行判定需要审批、自行发起 Guardian 复核并应用真实判定 | 验收 | 已采纳 |
| 015 | 顺带修复 launcher 的 SIGTERM 不清理现场 | 实跑中 `kill -TERM` 留下了活着的 llama-server 与陈旧 receipt，只有 build wrapper 兜底扫掉；这直接违反本计划的清理判据 | 清理 | 已采纳 |
| 016 | 适配器转发 Guardian 自己的 instructions，不套 `STATIC_INSTRUCTIONS` | 给一次真实审批 turn 前置测评侧指令会改变 Guardian 问的问题；因此这条路线不等于已资格化的 static 请求，census 长度分布也不用来给它定界 | 输出契约 | 已采纳 |
| 017 | `identity is None`（配置无 `model_path`）时适配器直接拒绝服务 | 独立审查发现原实现会在无 receipt 时跳过全部身份校验仍返回判定；无法说明是哪个实例作答的中继不得产出审批 | 身份语义 | 已采纳 |
