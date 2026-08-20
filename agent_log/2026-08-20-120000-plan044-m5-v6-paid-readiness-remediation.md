# Plan 044 / M-5 v6 正式付费前整改

## 结论

`2026-08-20-110000-plan044-m5-paid-readiness-independent-review.md` 的四项 NO-GO 均属实，已按新身份整改。
现行正式合同为 `multi-m5-workflow-v6 → multi-m5-runtime-v4 → multi-m5-nondegradation-v6`；v5 未改写，
runtime-v4 产品字节未变化。门前离线验收通过；正式 Gate 1 / Gate 2、Docker、v6 `$120` ledger、archive 与
identity receipt 均未启动或创建，M-5 仍未通过。

## 实质修改

- Gate 1 判据要求同一成员按首次 publish、Root publish、route、自身 exec Fact 的 completed `team_evidence`、
  二次 publish 的顺序闭环；Root 唤醒只认 completed `wait_agent` TeamActivity。缺调用、Root Fact、空/失败 evidence、
  仅两 Version 和 evidence 早于 route 均有反向回归。
- `persist=false` 必须显式使用 `eval-data/tmp` 下的隔离 capture；v6 rehearsal、正式 Gate 1 与历史 v5 分离，正式
  capture 非空即拒绝。旧 canonical 证据不再被测试覆盖或追加 metadata。
- Gate 2 provider 的 endpoint/model/effort/retry/rates 在 secret、receipt、ledger 与 claim 之前冻结，ready 同步核验。
  正式 Gate 2 还要求同一 v6 archive 已有 Gate 1 pass。
- v6 调度固定为 Gate 1 6 次、Gate 2 每槽 infra 5 次/全批 40 次、116 run 槽位；60 effective、80 requests/run、
  5 HTTP attempts 和 `$120` 不变。点估计 `$10.40`，最坏调度形状预测 `$67.80`。
- 新增正式 identity receipt 与严格 resume：归档完整结果按原分类跳过；pristine 零请求 run 原 id 重领；已请求
  未归档只落一次 abandoned infra 后进入下一 attempt；身份、未来行、非连续行、重复行和停止线冲突 fail-closed。
  账本重开会先按完整 reservation 保守结算悬挂请求。正常模型失败仍是 `agent_failed`，不伪装 infra。
- 独立复核时另发现 Gate 2 同槽的 infra 记录原先等槽位结束才批量归档；下一 attempt 请求中断会留下两个未归档
  run。现改为每个 attempt 分类后立即 fsync 再 claim 下一 id，并补中断恢复回归。
- 最终只读终审继续构造出六类边界，均确认属实并 fail-closed：成员 wait 不得冒充 Root；首个成员 Version 必须
  精确绑定被 `team_evidence` 下钻的 Fact；整条 trace 出现 Direct dispatch 即拒绝；明文投递从 telemetry 升为
  workflow-v6 机器判据；Gate 1/2 复用同一完整且有序的 Gate 1 archive 前缀验证；断链 archive symlink 在 claim
  前拒绝。Gate 2 每 attempt 先归档再 claim 的独立发现也保留。

## 验收证据

- Python M-5 定向：162/162（项目专用 `XDG_RUNTIME_DIR`；冻结 binary rehearsal 包含在内）。
- `just eval-lock`：通过；`just eval-multi-m5-ready`：`ready=true`，formal identity=`not_started`；
  `just eval-multi-m5-loopback`：通过。
- 全新 canonical `m5-g1-rehearsal-v6`：outcome=completed、七谓词全真、trace_error/taint/stop 均为空；
  20/20 nested dispatch 均为 code cell、0 Direct、0 failed；dump 7 页、log 2 页到 null；明文 9、加密/未知 0。
  协议序列为成员 publish seq35 → Root publish seq48 → route seq58 → 成员 evidence seq72 → 成员 publish seq79；
  evidence 返回 available/success/untruncated，producer=`/root/worker`、tool=`exec`，observation 含冻结 finding。
- runtime-v4 与历史 Rust build-lock 146/146 证据未变，本轮没有产品源码变化，未重跑重型 Cargo。

## 停止边界

正式 v6 设施已具备起跑条件，但两道门都没有执行；不能表述为 Gate 1 通过、M-5 通过或“小样本未见退化”。
下一动作只能是在未来单独启动正式 Gate 1；Gate 1 通过后才可启动 Gate 2。
