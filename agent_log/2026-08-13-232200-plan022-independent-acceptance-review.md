# Plan 022 独立审查验收报告

审查时间：2026-08-13（America/Los_Angeles）

审查对象：`worktree-023-rondo-multi-bootstrap@d2c16073beb94b45f2bacceb8b0fbae41ad65204`

实现基线：`66116831becaf4adfa3dd28396e07441617fe1d1`

主工作区：`main == origin/main == d84632fb74dbaad0b4b43c047d292dc46450bc77`，审查期间保持干净

外部边界：未运行 Docker、真实 API、真实本地模型或付费测评；未合并、未推送、未清理 Multi target

## 验收结论

**不通过，拒绝合并。**

看门狗迁根、`multidev/` 精确复制、默认关闭的 Rust 行为门、产品布局映射和 synthetic 结果生产者主体实现良好，
执行者报告的 592 项 Python 门禁与两次 watchdog 资源摘要也可复核。但是产品身份没有真正贯通到现有生产入口：

1. binary freeze 新写出的 manifest 会被 Terminal-Bench 的真实 loader 拒绝；
2. campaign 的 `product` 没有进入真实 `TerminalBenchRequest`，也没有与 bundle / `RunSpec` 交叉绑定；
3. 新增的 Multi no-API 入口仍被固定历史 Local `PairIdentity` 结构性阻断；
4. durable result validator 接受互相矛盾的产品与 `auto_review_config` 声明。

上述问题直接违反 Plan 022 硬约束 6、7、8，且使完成标准中的“eval 入口能显式选择 Multi、身份全链一致并
fail-closed”不成立。现有新增测试主要直接构造 `BinaryManifest` / `RunSpec` 或走 synthetic publication，绕开了
`_load_manifest -> campaign/no-API request -> prepare -> adapter` 这条真实入口链，所以全套无 API 单测为绿仍不能
支持验收通过。

## 阻断项

### B1. 新冻结 manifest 无法进入 Terminal-Bench 生产入口

严重度：**BLOCKER**

- `eval/rondo_eval/binary_freeze.py` 的三种发布函数都用 `asdict(manifest)` 写 JSON。新 RONDO Local 写
  `"product":"rondo-local"`，新 Multi 写 `"product":"rondo-multi"`，新 Codex 当前还会写
  `"product":null`。
- `eval/rondo_eval/terminal_bench/__main__.py:513-575` 的 `_load_manifest()` 仍要求旧 15 键集合严格相等，
  不允许 `product`；构造 `BinaryManifest` 时也没有传该字段。
- paid CLI、`baseline_cli` 与 `docker_smoke` 共用这个 loader。因此不是只有某个边缘 CLI 失败，而是任何新冻结的
  runtime bundle 都不能进入实际 Terminal-Bench。
- `doc/eval-data-layout.md` 要求新 RONDO manifest 写 `product`、Codex manifest 不写该字段；当前 writer 对
  Codex 写 `null` 也与权威布局不一致。

用仓库现有 binary-freeze fixture 真实生成一份新 Local runtime manifest，再交给生产 loader，复现为：

```text
new_runtime_product=rondo-local
new_runtime_loader=TerminalBenchRunError:binary manifest schema differs from v1
```

这同时说明当前新增的 freeze 测试与生产 loader 测试之间存在合同裂缝。`test_terminal_bench_docker_smoke.py` 的 loader
用例仍只覆盖旧 15 键与另一种废弃 16 键形状，没有覆盖合法的可选 `product`。

必须修复：loader 严格接受“历史精确键集”或“精确键集 + 合法 product”，继续拒绝未知字段，并把字段传入
`BinaryManifest`；publisher 对 `None` 应省略键，不能给 Codex 写 `null`。回归必须从 `prepare_runtime()` 产物
进入 `_load_manifest()`，覆盖历史 Local、现行 Local、Multi 与 Codex 四种形状。

### B2. campaign 产品身份没有进入真实请求，也没有绑定 bundle / RunSpec

严重度：**BLOCKER**

- `eval/rondo_eval/terminal_bench/live.py:104-142` 的 `campaign_terminal_bench_request()` 接收
  `CampaignIdentity`，但构造 `TerminalBenchRequest` 时没有设置 `product`。preflight producer 与 paid
  baseline 都复用该函数。
- 对 `product=rondo-multi` 的 campaign，真实 request 因而仍是 `product=None`，在 RONDO 侧会被解释为
  `rondo-local`。
- `eval/rondo_eval/terminal_bench/baseline.py:490-535` 的 `validate_manifest()` 只校验锁内 path / digest，
  `validate_spec()` 只校验 slot / task / provider 等字段；二者都不把 manifest / `RunSpec` 的有效产品与
  `identity.product` 比较。
- successor generator 在创建 v7 identity 时继承 predecessor 的 Local bundles，却允许 comparison 声明
  Multi，也没有在写锁前做产品交叉校验。

只读探针结果：

```text
campaign_product=rondo-multi request_product=None
multi_campaign_local_manifest=ACCEPTED manifest_product=rondo-local
```

因此正确的 Multi bundle 会因 request 被误投影成 Local 而失败；更危险的是，声明 Multi 的 campaign 可以继续
绑定历史 Local bundle 并通过 campaign 自身的 manifest 校验。`RunSpec.validate()` 只能校验 request 与 binary
彼此一致，无法发现两者一起偏离 campaign identity。

必须修复：RONDO request 显式使用 `identity.product`，Codex request 保持 `None`；campaign 的 manifest、
`RunSpec`、publication record / replay / aggregate 必须与 campaign product 逐层交叉校验；successor identity
不得把 Multi 声明绑定到继承的 Local bundle。应补从真实 campaign request producer 出发的正反回归。

### B3. `eval-b2-no-api rondo-multi` 只是表面可选，仍被历史 Local pair 固定绑定

严重度：**BLOCKER**

- 根 `justfile` 新增 `eval-b2-no-api product ...`，会按 `rondo-local|rondo-multi` 选择 bundle 命名空间。
- 但 `docker_smoke.main()` 固定调用 `load_no_api_pair_identity()`；
  `eval/rondo_eval/terminal_bench/pair.py:894-897` 始终返回最新历史 pair。
- 该 pair 的 RONDO bundle 固定为 `eval-data/bin/rondo/...`，`PairIdentity.validate_manifest()` 又会精确校验
  manifest path、digest 与二进制摘要。

所以即使后续已经冻结正确的 `eval-data/bin/rondo-multi/...` bundle，入口也会在真正 Docker / agent 执行前被
历史 Local pair 拒绝。当前 `eval-data/bin/rondo-multi/` 为空是本任务允许的边界，但不能掩盖入口自身在未来有
bundle 后仍结构性不可执行。

必须修复：no-API 身份与 manifest 绑定需要 product-aware；或者在本任务中诚实撤回“Multi no-API 入口已接入”
的完成声明，把该入口及其受跟踪身份合同明确留给冻结 Multi bundle 的后续任务。不能保留一个看似可选、实际必败
的入口。

## 主要缺陷

### M1. durable result validator 不校验 product / config / auto_review_config 一致性

严重度：**MAJOR**

`eval/rondo_eval/artifacts.py:416-451` 只检查顶层 `product` 是合法枚举、且 Codex / `sol-static` 不得携带产品；
`eval/rondo_eval/terminal_bench/results.py` 的 TB cross-field validator 也没有补以下约束：

- 顶层 `product` 必须与 `config.product` 相等；
- 带产品的 TB 新行必须带精确版本化 `auto_review_config`；
- Multi 四项必须全为 `null`，Local 必须与实际 configured override 投影一致；
- 产品必须与 binary / campaign identity 一致；
- shadow side 应遵循 `doc/eval-data-layout.md` 的产品映射，而不是只排除两个字符串。

对一条现有合法 RONDO 历史记录仅在内存中篡改，真实 generic validator 仍接受：

```text
top-level product       = rondo-multi
config.product          = rondo-local
auto_review_config      = forged non-null values
contradictory_record_validation=ACCEPTED
```

正常 producer 当前复用 `_product_config()`，可避免正常成功/失败路径自己分叉；但 tracked index 读取、journal
恢复、aggregate / replay 等 durable 消费边界并未强制该事实，不能满足“错误组合 fail-closed”。

必须修复：保留历史无 `product` 行的只读兼容；一旦新行带 `product`，就严格校验顶层、config、版本化配置块及
campaign/binary identity 的一致性，并补 tamper negative tests。

## 合同与文档问题

### C1. 完整 `git diff --check` 未通过，例外没有取得用户确认

严重度：**CONTRACT HOLD**

Plan 022 §1 明确把完整 `git diff --check` 通过列为完成标准，同时计划开头规定完成标准若需改变应暂停并取得用户
确认。实际结果：

```text
git diff --check 6611683..d2c16073
rc=2
419 files
6479 whitespace locations / 12707 output lines
```

排除 `multidev/**` 后手写部分 `rc=0`。这 419 个文件的空白确实来自 `mydev/` 原件；逐条 blob 比较也证明
修空白会违反更强的“精确复制”约束。执行者的技术取舍合理，但不能自行把明确完成标准改成“手写部分通过”后仍
宣称全部完成。复审前需要用户接受这个窄例外，并把合同记录改为可机器复算的 allowlist；或者采用不破坏精确复制
的等价验收表达。

### C2. 当前 WBS 仍含两处直接陈旧事实

严重度：**MAJOR DOC**

- `doc/WBS.md:68` 仍写“研究完成，产品基线未建立”，与同文件 16、28、35-47、84 行的“已建立/工作包 2
  已完成”矛盾。
- `doc/WBS/eval-benchmark.md:78` 仍写“未创建 multidev，实际接入仍在 Multi 基线任务中完成”。

WBS 是当前阶段与跨任务事实的唯一来源，这两处必须同步为当前事实。由于本次实现还未通过独立验收，修订时也应
避免在分支上先写成无条件“工作包 2 已完成”；更准确的状态是“实现待修复与复审”。

### C3. Plan 决策 009 / 实现日志与代码、权威数据布局互相矛盾

严重度：**MINOR DOC**

Plan 决策 009 和实现日志称 manifest 的 `product` 键只在非 Local 时出现，Local 保持历史形状；代码测试却明确
断言新 Local manifest 写 `product="rondo-local"`，`doc/eval-data-layout.md` 也规定“新冻结的 RONDO manifest
写 product”。真正保持历史形状的是 Local build-command 不加 `--product`，不是新 Local manifest 不写字段。
应修正文档，不要为迁就错误描述而回退权威布局。

### C4. no-API Codex 摘要的注释与实际形状不一致

严重度：**MINOR**

`docker_smoke.py:135-155` 注释称 Codex 不记录 product 与 auto-review state；实现虽省略 `product`，却始终输出
`"auto_review_config": null`。paid/result 路径对 Codex 是直接省略该字段。需要统一合同并补回归。

## 已通过项目

### Git、复制与范围

- 实现提交父子关系、分支与 worktree 正确；未合并、未推送。
- 主工作区 `main` 干净且与本地 `origin/main` 指针同为 `d84632f`。
- 受跟踪修改限于 Plan 022 允许范围；`README.md`、锁文件、历史 `eval/results`、历史 bundle / result / ledger、
  secrets 示例均未改。
- `mydev/` 与 `multidev/` 的 Git tree 映射逐条相同，共 6,011 项：5,951 个 `100644`、59 个 `100755`、
  1 个 `120000` symlink；blob、mode、相对路径全部一致。
- 唯一 symlink 均为 `codex-rs/vendor/bubblewrap/LICENSE -> COPYING`。
- `.git`、`.agents`、`.codex`、`project`、`absolute-turn`、`request-permissions-environment` 六个残留均未进入
  `multidev/codex-rs/core/`。

### Watchdog 迁根

- 两脚本是 Git 100% rename；父提交与当前提交 blob ID 完全相同。
- `with-build-lock.sh` 保持 `100755`，`build-watchdog-lib.sh` 保持 `100644`；`bash -n` 通过。
- 现行代码、测试、just 与安全文档均使用根路径；旧路径只留在冻结 plan / log / audit / lock provenance。
- runtime bridge 和 binary freeze 都精确绑定 checkout 根脚本并拒绝旧/近邻路径。
- Local helper 9/9、Multi helper 9/9 均通过。
- 历史 bundle 因旧 wrapper argv 不能再 re-verify 是 Plan 硬约束 5 / 决策 008 明示接受的代价，不另列缺陷；
  冻结 bundle bytes 与 `eval/locks/*.json` 未改。

### 默认关闭与构建现场

- Local / Multi 同源的 Rust 测试确实经 `ConfigBuilder` 的真实空配置加载路径断言四字段全 `None`，并断言
  `approvals_reviewer == User`；正向对照证明四字段仍有接线。
- 执行者保留的两份 watchdog summary 可复核：`wrapper_status=complete`、`final_rc=0`、
  `stop_reason=none`、`cleanup_reason=none`；项目峰值 43.6 GB、Multi target 21.3 GB、swap 峰值 0、
  Windows C 盘余量约 209.2 GB。
- 热 target 仅 `multidev/codex-rs/target`；Local target 不存在，符合单热产品 target 规则。
- 已构建二进制现场执行 `codex --version` 得 `codex-cli 0.147.0`。

### 审查者实际门禁

```text
完整 eval pure/fake/loopback：592/592，0 fail，0 skip，73.316s
uv lock --check：85 packages，pass
Local watchdog helper：9/9
Multi watchdog helper：9/9
bash -n 两个根 watchdog 脚本：pass
binary-freeze + runtime-bridge focused（并行独立复核）：74/74
product/result/binary-freeze focused（并行独立复核）：16/16
campaign contract/successor focused（并行独立复核）：15/15
```

这组绿灯证明既有测试稳定，也反证阻断来自覆盖缺口，而不是随机测试失败。

## 未运行与现场残留

- 按 Plan 禁止项未运行：Docker、no-API 双侧真实执行、真实 API、付费 TB、真实本地模型、全 workspace Rust、
  Local Rust build。
- `eval-data/bin/rondo-multi/` 仍为空；这是执行者已说明且 WBS 允许的当前边界，不是本报告的失败原因。
- ignored 现场有执行者已报告的 20 GB Multi target、两份 build metrics，另有 4 个 eval `__pycache__` 和
  1 个 `mydev/.github/scripts/__pycache__`。均未受跟踪；执行汇报遗漏了后五项。审查者运行 `uv lock --check`
  临时产生的 28 KB `eval-data/uv-cache` 已清除，未动来源不明的缓存或 target。
- 没有创建正式 campaign identity、run ID、结果行、预算账本或 `eval-data/runs/*`。

## 复审准入条件

执行者应在同一 worktree 分支提交修复后停止，仍不得合并或推送。至少完成：

1. 修 B1，并增加真实 freeze 产物到生产 loader 的新旧兼容回归；
2. 修 B2/B3，使 campaign、no-API、bundle、RunSpec、adapter、result/aggregate 的产品身份全链一致；
3. 修 M1，补 durable record tamper 负向回归；
4. 修 WBS 两处陈旧事实、Plan 决策 009 / 实现日志错误表述及 no-API Codex 摘要形状；
5. 由用户明确接受精确复制对完整 `git diff --check` 的窄例外，或恢复原完成标准；
6. 重跑受影响 focused Python 测试、完整 `just eval-test` 等价无 API门禁、`just eval-lock`、两侧 helper；
   如未修改 Rust 产品源码，不要求重复 20 GB Cargo 构建；如修改则仍须经根 watchdog 定向验证。

复审只需围绕上述阻断与回归，不应扩展到 Docker、真实 API、真实模型、全 workspace 或 Multi 功能开发。
