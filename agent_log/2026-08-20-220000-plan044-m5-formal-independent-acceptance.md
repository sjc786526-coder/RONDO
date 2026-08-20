# Plan 044 / Multi M-5 正式结果独立验收

- 日期：2026-08-20
- 审查对象：正式执行提交 `c9fcb0fb1cd57254558e811ecddfab65e2c452df`、文档收口提交
  `5e14745d2e6c4d6c4c439b47b200a8bd63bbe020`、campaign `multi-m5-v6-c3`
- 范围：只读核对 Plan/WBS、Gate 1/2 archive、capture/trace、ledger/receipt、冻结锁、资源证据与 Git 边界；
  未调用真实 API，未运行 Docker、Rust 或重型测试，未修改有效代码

## 结论

**GO：验收通过，Plan 044 / M-5 的冻结任务目标完成。** 未发现 P0/P1。Gate 1 的真实协作链成立；Gate 2 在冻结
十题小样本中未观察到稳定的 Codex-pass / Multi-fail 单向退化。该结论不证明 Multi 质量或性能提升，也不证明
medium 会在未明确要求委派的真实任务中主动 spawn。

## 核验摘要

- Gate 1 正式前缀只有 a1/a2。a1 因一次 `upstream_unavailable` 正确归档为非有效 infra；a2 22 个 provider
  请求全部 settled，七谓词全真，`team_evidence=true`，明文 14、加密/未知 0。独立从 raw requests + trace
  重放得到同一 Event 下的成员首个 Version/Fact、Root wait/publish/route、成员 evidence、不同第二 Version 与
  Root update 完整链；协作调用均来自 code cell，两个 model requester 的调用仅是与既有 cell、call-id 和原始参数
  精确绑定的 runtime `wait` continuation，不贡献协作证据。
- Gate 2 archive 恰为十题 × 双侧的 20 个 round-1/base/effective 行，顺序逐项匹配冻结 task-major
  `Codex → Multi` 调度。4 对双方通过、6 对双方失败、0 个 Codex-only 完成；因此冻结规则下条件复跑与归因诊断
  均为 0。独立重放 resume prefix、`conditional_slots`、逐题 verdict 与 `gate2_passed` 得到十题全部
  `no_stable_one_way_degradation`、`next_run_id=None`、Gate 2 通过。合同中的 60 是最坏情况下的有效容量，
  不是固定必须跑满的样本数。
- c3 archive 22 行与 ledger 22 runs 的 run-id 集合完全一致。账本 237/237 request settled、0 held、最大 HTTP
  attempt 1；236 笔 usage-priced、1 笔 conservative reservation。c3 保守暴露 `$5.840974`，加 prior
  `$13.981683` 后为 `$19.822657 < $120`。这个数字是本地保守上界，不应称为已核实供应商实扣；可核对的
  usage-priced 跨代合计为 `$4.282657`，另保留 `$15.54` conservative exposure。
- Gate 2 的 20/20 Docker 行均 `returncode=0`、无 warning、末样本 `cleanup_verified`，十个 digest 各出现两次。
  单槽峰值 Docker 增长 2.556GB，VHDX 峰值增长 0，远低于停止线。
- receipt、22 行 archive 与 provider/三锁均绑定 clean formal harness `c9fcb0f`；Multi runtime 绑定产品
  `0eee6dc` / binary `c64ff…c631`，Codex baseline 绑定 `be6e8eac…` / binary `8bd5…f1a80`。`c9fcb0f..5e14745`
  只有 Plan/WBS/log 文档差异，`eval/`、`multidev/`、`mydev/` 和锁没有变化。任务树停在 `5e14745`；主工作区
  `main == origin/main == 45efac6`，尚未合并或推送。

## 非阻断问题与口径修正

1. `doc/WBS.md:147-149` 仍残留“c3 正式资产尚不存在、等待启动”的旧状态，与同文件前文和正式实物冲突。
   这是 P2 文档残留，不推翻两门结果；下次文档交付应做最小删除/改写。
2. 当前 docs HEAD `5e14745` 上重跑 `just eval-multi-m5-ready` 会得到 `ready=false`，唯一缺项是
   `formal_batch_identity`：receipt 正确绑定正式运行时的 `c9fcb0f`，而 ready 用当前完整 Git HEAD 重建身份。
   因此执行日志中的 ready 绿色只适用于 `c9fcb0f` 正式执行时点；不得声称当前 `5e14745` ready 绿色，也不得从
   `5e14745` 继续 resume 已终结的 c3。由于后继仅为事后结果文档，定 P2，不否定已完成的正式运行。
3. 执行日志把项目增长写为约 `6.32GB`；build-lock summary 的实际差值是
   `148065591296 - 148059275264 = 6,316,032 bytes`，约 6.316MB（0.006316GB）。这是 P2 单位错误。
4. 正式 archive 足以证明每槽清理并回到相同 Docker baseline；“最终 0 containers/volumes/build cache”只见于
   执行日志，未保存最终 `docker system df` 原始文本。本轮按审查边界不调用 Docker 现场复验，故只接受为运维
   汇报，不把它作为 Gate 通过的必要独立证据。

## 替用户作出的决策

1. 接受 `c9fcb0f` 为正式运行身份，`5e14745` 为事后文档提交；不为让当前 ready 重新变绿而新开 campaign、
   改 receipt 或重跑任何付费样本。
2. 按冻结合同关闭 M-5：门 1 证明 medium + 明确协作指令下真实多智能体链可达；门 2 只证明功能面开启后，
   该十题小样本没有稳定单向退化。两者合起来完成 Plan 044，但不得外推为主动委派、Ultra、不退化的统计结论、
   质量优势或性能提升。
3. RONDO 当前产品把 Ultra 映射为 proactive multi-agent，medium 映射为 `ExplicitRequestOnly`。Gate 1 模板明确
   要求 spawn，因此结果有效；Gate 2 没有明确委派要求，100/100 个 RONDO provider 请求均为 main role，未出现
   成员请求符合产品策略。若未来要证明“真实任务主动委派并带来收益”，应作为新的独立测评目标，不回改 M-5 结论。
4. 本轮不合并、不推送。先保留 044 分支和正式资产；是否合入 `main` 由后续明确交付指令决定。上述 WBS 残留和
   6.32GB 单位错误可在交付时做一次纯文档窄修，不要求重跑 Gate。

## 本轮验证

- `uv lock --directory eval --check`：通过。
- 用 receipt 中的历史正式 identity 只读加载 22 行 archive，重放 Gate 1 prefix、Gate 2 resume/order、条件调度、
  verdict 与 `gate2_passed`：通过；Gate 1 attempts `[1,2]` 且 a2 completed/pass，Gate 2 20 行、0 conditional，
  10/10 `no_stable_one_way_degradation`。
- 当前 `5e14745` ready：`false`，唯一因为上述 docs-only HEAD/receipt 差异；其余 provider、三锁、bundle、预算上界
  均绿色。

最终状态：**验收通过；任务目标完成；Multi M-5 按冻结工程里程碑通过；性能提升/主动委派收益未验收。**
