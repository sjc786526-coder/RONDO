# Plan 101：B2 跑满与指标口径纠偏

原执行者在 B2 补轮阶段反复崩溃（`b2-run-stdout-sup11.json` 为 0 字节），由审查者接手完成剩余工作。
接手时账本无未结算预留、归档无半写记录，直接 `run-formal --resume` 续跑到满。

## B2 结果

`810/810` observation（6 单元 × 27 candidate × 5 次重复，两条件同 n），`809` success + `1` `response_size`
解析失败（`thinking_on:B`，按合同写成 terminal，未重试洗成成功）。logical key 唯一、单一 freeze SHA、
requested/served 模型一致。补轮到 5 次的决定只用已结算账目（`looked_at_unit_metrics=false`）。
任务累计结算 `6.6787625 RMB` / 上限 `20 RMB`。

主口径（单次调用 BA 均值）：`off:C 0.747` > `on:B 0.667` > `on:C 0.657` ≈ `on:A 0.653` >
`off:A 0.627` ≈ `off:B 0.625`。思考在 C 上为负（`-0.090`），在 A/B 上为小幅正（`+0.027` / `+0.042`）。
A 的 AUC `off 0.839` vs `on 0.728`，是该臂最干净的阈值无关读数，方向同样是关思考更好。
`on:C` 跨重复自洽率仅 `0.481`，且 `useful_state_transfer` 与 `scope_and_signal` 的 failure recall 掉到 `0`。

预登记现象被证伪：`thinking_off:B` 在 27 条上给出两种 verdict，打通三元组上的恒定 PASS 是 n=3 的假象。

## 指标口径纠偏（决策 011）

复审发现三处会影响结论的口径问题，均在指标/报告层修正，不重跑、不新增调用：

1. A 臂原先用在被评的同一批 gold 上择优的阈值，而 B/C 无任何可调参数。改为事前固定阈值 `0.5` 作主口径，
   择优阈值保留但标为 oracle 上界且不进跨臂差值表。
2. 头条原先是多数票。产品只调一次，故改为单次调用为主、多数票为次要。两者在 A/B 上符号相反
   （单次为正、多数票为负），差值表现在并列两列。
3. `balanced_accuracy_wilson` 更名 `balanced_accuracy_band` 并注明是两个 Wilson 区间端点平均、偏保守。

同时退役 §5.1 第 3c 项（A 臂非边界取值）：它与已被退役的 B 臂逐字节互异门同病，执行中已导致只给 A 臂
加入一句边界校准指令，构成跨臂提示词不对称，该不对称写入报告的局限一节。

修复 `runner.py` 中 `derive_verdict` 未导入的潜在缺陷——formal recompute 路径此前从未被跑到，一跑即 `NameError`。
`metrics.py` 的 `predicted[dimension]` 改 `.get`。

冻结合同 `plan101-thinking-comparison-contract-v1.json` 未改：其 SHA 已绑进 B2 freeze，事后回改既会破坏续跑
校验，也会让本轮看起来一开始就是这么配置的。口径变更只记在 plan 决策表与报告里。

## 验收

`eval` 定向测试 34 项通过（Plan 101 的 13 项含 3 项新增回归，Plan 100 的 21 项无回归）。
未改 Rust，未跑全量 workspace，未改产品默认 scorer。
