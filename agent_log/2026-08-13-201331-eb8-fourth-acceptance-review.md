# E-B8 第四次验收审查（`0935dedf`）

## 结论

**未通过，E-B8 仍应保持 blocked。**

`0935dedf75b9b55e9e222f9226bca55edc3f188b` 对第三次审查的 2 个 blocker 与 1 个 receipt
半批次问题均做了真实、有效的定点修复；实现者随后完成的无 API Docker fix-git 和 10 题 canary
也补上了此前缺失的双侧 main → Guardian → main 实机证据。不过本轮把请求投影与冻结
Responses Lite 真实 wire shape 逐项对照后，发现 1 个直接击中 E-B8 核心合同的 blocker：当前投影会在
`AdditionalTools` 处提前停止，因而实际 Lite 请求的工具和 developer instructions 都没有进入对称性硬门。

另外有 1 个 identity 冻结缺口和 1 个完整请求 digest 落盘缺口。它们都能以窄改动闭合，不需要增加签名、
可信审计、鉴权系统、统计框架或新测评架构。

审查覆盖 `7a37cdf..0935dedf`，并回看当前 E-B8 请求投影、producer、receipt、harness identity 与 paid
proxy 生产路径。除本日志外没有修改实现、测试、WBS、plan 或冻结历史；没有运行 Docker、真实 API、
真实模型、Oracle、wire canary 或正式 campaign。

## 已确认闭合的三项修复

1. **harness commit 自引用已解除，且门禁已前移。** v7 worker 和 producer 都从 identity 取得冻结
   `eval_harness_commit`，在 receipt、Oracle、wire canary 和 Docker 前校验干净 checkout 与 harness
   投影；identity-only commit 可以推进 HEAD，而 `eval/rondo_eval`、tasksets、templates、seccomp、依赖锁等
   harness 路径漂移会被拒绝。此前“正常生成后必脏或 HEAD 必不相等”的死结已消除。
2. **Guardian 真实角色已进入 receipt。** stub 明确驱动 main → Guardian → main；producer 要求轨迹精确为
   `("main", "guardian", "main")`，并比较前后两个 main 的稳定合同；receipt 精确要求
   `{main, guardian}`，因此 main-only receipt 不再能进入付费门禁。
3. **receipt 批次失败与重试语义已闭合。** producer 先捕获并比较全部任务，再预扫描全部目的文件，最后发布；
   后题失败不会留下前缀 receipt。已存在的同字节 receipt 幂等接受，异字节或 symlink 冲突在发布前拒绝，
   支持中断后的安全重试。

实现者记录的 Docker 证据也与代码路径一致：fix-git 双侧均完成 main → Guardian → main；合成 v7 下完整
canary 10/10 题、20/20 side runs、10 份 receipt 加载、40/40 双侧/双角色 gate registration 均通过，
真实 API 请求与费用均为 0，临时对象已清理。本轮没有重复这些已结清的重型测试；这些数字作为
`agent_log/2026-08-13-195608-eb8-blocker-remediation.md` 的实现者证据纳入，而非本轮独立重跑结果。

## 未闭合问题

### BLOCKER：真实 Responses Lite 的 `AdditionalTools` 被投影跳过

`fair_comparison.py:42-43,98-125` 把稳定前缀 item type 限定为 `message`/缺省值，并在遇到其他 type 时
立即 `break`。但冻结产品源码 `mydev/codex-rs/core/src/client.rs:862-884` 明确先插入
`ResponseItem::AdditionalTools { role: "developer", tools }`，再插入 developer base instructions；
`mydev/codex-rs/core/tests/suite/responses_lite.rs:110-128` 还明确断言 Lite 请求顶层没有 `instructions` 和
`tools`，`input[0]` 是 `additional_tools`、`input[1]` 才是 developer message。

因此真实 Lite 请求进入 `_stable_input_prefix()` 时会在第一个 item 就停止并返回空列表：

- 顶层 `tool_specs` 读取缺失的 `tools`，得到空数组；
- 顶层 `instructions` 读取缺失字段，得到 `null`；
- `stable_input_prefix` 又因首个 `additional_tools` 返回空数组。

也就是说，历史 161-token 非对称所在的 catalog 派生 `spawn_agent` tool description，以及随后 developer
instructions，在实际 Lite 形状下都不受请求前置硬门保护。纯复现使用两份只有
`additional_tools.tools[0].description` 不同的真实形状请求，得到：

```text
rondo_prefix= []
codex_prefix= []
reasons= ()
```

现有 `test_trimmed_catalog_asymmetry_is_detected` 没抓到这一点，因为测试夹具把 AdditionalTools 文本塞进
`type: "message"` 的 developer item，与冻结 wire shape 不同。Docker 报告的“五个分区全部相同”也不能证明
这段被比较：在当前实现中，两侧该分区同为**空投影**就会得到相同结论。

这是核心 fail-closed 合同缺失，不是审计增强。最小修正是让稳定前缀接纳并规范化真实
`additional_tools` developer item，再继续读取其后的 developer/system message，直到首个非稳定角色；补一条
完全照冻结 Lite wire shape 的回归，证明 8-model/1-model tool description 差异被发送前拒绝，同时不同 user
task body 仍不被误判。

### HIGH：同代新 identity lock 提交后仍可在同 campaign ID 下改写

`results.py:203-229` 只看冻结 harness commit `H` 到当前 HEAD 的**净** `git diff --name-status`。相对 `H`
新增的 v23 lock 无论后来又提交改了多少次，在净 diff 中仍然只是 `A`，所以白名单继续接受。

本轮纯 Git 生命周期复现：先在 `H` 后提交新增 v23/active pointer，再把 v23 的重复值从 3 改为 5 并提交；
`_validate_eval_harness_projection(root, expected_commit=H, head=<second commit>)` 仍返回 `H`：

```text
ACCEPTED_MUTATED_NEW_LOCK expected=<H> head=<second commit>
```

新增回归只改了在 `H` 已存在的 v22，因此它看到 `M` 并拒绝，没有覆盖“本代新 lock 先新增、后修改”。receipt、
state 和 ledger 的 lock SHA 绑定会阻止**已有这些外部状态后**继续消费旧数据，所以这里不应夸大为已证明的
正式结果后 fail-open；实际缺口是正式 identity 已 mint、尚未产生外部状态时，可以在复用 campaign ID/run-ID
空间的情况下重新定义冻结合同。最小修正只需机械确认每个相对 `H` 新增的 identity 文件自首次 addition commit
后 blob 未再变化，并补对应生命周期回归；不需要签名或可信审计平台。

### MEDIUM：producer 捕获的完整请求 digest 没有随 receipt 保存

`SymmetryPreflight.register()` 会计算每个请求的 `full_request_sha256`，`provenance()` 也能输出它；付费 proxy 的
redacted metadata 另存实际付费请求的 body/canonical digest。但正式 stub producer 在
`_requests_by_role()` 中只返回首个 main 与 Guardian 请求，`preflight_receipt_from_stub_run()` 构造 receipt 后丢弃
`preflight.provenance()`，而 `PreflightReceipt.to_dict()` 只写 bindings 与稳定合同。因此两侧 stub 的完整请求
digest（以及 post-Guardian main）并没有落到 production receipt 或相邻工件。

这不削弱稳定分区的 fail-closed 门禁，也不需要发展成审计设施，但与
`doc/WBS/eval-benchmark.md:54`“完整请求 digest 各侧分别记录，只作 provenance/drift”的当前事实不符。
最小修正是在尚无正式 v7 receipt 的前提下，用一个固定、有限的 receipt 字段保存本次两侧
main/Guardian/main 的 side/role/sequence/full digest；不保存正文、不要求跨侧 digest 相同。

## 本轮验证

- `tests.test_fair_comparison`：83/83 通过，0 skip（纯/fake/loopback，已清除 ambient HTTP proxy）。
- `just eval-lock`：通过，`Resolved 85 packages`。
- `git diff --check 7a37cdf..0935dedf`：通过。
- 纯 Responses Lite 复现：8-model 与 1-model `additional_tools` 差异得到 `reasons=()`，确认 blocker。
- 纯 Git 生命周期复现：新增 v23 后再次提交修改仍被 harness projection 接受，确认 identity 缺口。
- `eval/locks/`、`eval/results/`、`mydev/`、`eval/uv.lock` 相对 `e23d82f` 无改动，`multidev/` 不存在；
  主工作区 `main` 与目标 worktree 在写本日志前均干净。
- 未重跑 `just eval-test` 574 项、Docker fix-git/全 canary、Oracle、wire 或真实 provider；前两类采用实现者已记录
  的证据，后几类仍因不存在正式 v7 identity 而未验收，也不应在本轮擅自创建。

## 验收判定与最小后续

`0935dedf` 已实质闭合第三次审查的三项问题，但 E-B8 尚不能据此宣告完成或启动正式 v7 campaign。下一轮只需：

1. 修正真实 Responses Lite `additional_tools`/developer 前缀投影并加入真实形状回归；这是唯一 blocker。
2. 拒绝同代新 identity lock 在 addition 后再被提交改写。
3. 将 producer 已计算的两侧完整请求 digest 以有限字段随 receipt 保存。

正式 identity → producer CLI → worker CLI、Oracle、wire 与付费 campaign 生命周期仍未运行；在以上 blocker
闭合且用户另行冻结重复合同/授权 cap 前，继续保持该边界。无需扩大鉴权、可信审计、统计显著性或 Multi 产品设施。
