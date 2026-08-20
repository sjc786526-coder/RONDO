# Plan 044 / M-5 v6 再整改与正式门前终验

- 日期：2026-08-20
- 边界：只修改 eval 合同、判据、恢复与定向测试；未运行 Docker、重型 Cargo、真实 API 或正式 Gate 1/2
- 产品身份：workflow-v6 → runtime-v4 (`0eee6dc`) → nondegradation-v6；v5 历史不改写

## 改动

- 关闭 Gate 1 协议假绿：采集 nested call 完成序号并拒绝乱序 trace；用 manifest actor/thread、trace start/end、
  dump 与 inspect-log revision 绑定 Root wait/publish/route/update、成员自身 Fact 的 evidence，以及不同的第二
  member Version。明文投递、零 Direct 与分页闭合条件保持不放宽。
- 恢复逻辑保留 terminal budget/capacity stop，幂等归档 `budget_stopped` 后停止；只允许精确白名单内的
  pre-Harbor 零请求自有产物追加一次 abandoned infra。未知、错型、symlink、exact trial dir 或 exact-label
  Docker/Compose 残留 fail-closed，等待后继受监督精确清理。
- Gate 2 在任何 claim/execution 前、持有 heavy lock 时按精确 run label 与 Compose project 探测 container、
  network、volume；探针错误同样 fail-closed。正常模型失败仍保持产品分类。
- 将 rehearsal identity 切到 append-only `m5-g1-rehearsal-v6-r2`，保留旧 v6 行和原始 capture。

## 验证

- M-5 三模块串行 Python：179/179；Docker resume 精确探针所属 `DockerCounterTests`：29/29。
- `just eval-lock`、`just eval-multi-m5-ready`（`ready=true`）与 `just eval-multi-m5-loopback` 均通过。
- v6-r2 rehearsal：23 requests，20/20 nested dispatch 均为 code cell，0 Direct/failed；dump 7 页、log 2 页
  到 null；七谓词全真，明文 9、加密/未知 0，trace_error/taint/stop 均为空。协议完成序列为
  `wait 23..38`、member publish `35..37`、Root publish `51..52`、route `58..59`、member evidence
  `72..73`、distinct member publish `79..82`、Root update `92..93`。
- 全套首次复跑暴露代理绕过测试的既有竞态：客户端只读 status 即关闭，服务端写入计数尚未发生而误报失败。
  测试改为完整读取本地 SSE 后断言；单例与全套复跑通过，产品路径未变。
- 独立终审结论 GO，未发现剩余 P0/P1；`git diff --check` 通过。

## 停止边界

正式 v6 archive、ledger、identity receipt 与 paid capture 仍不存在；本轮没有费用和 Docker 外部状态。
正式 Gate 1、Gate 2 均未启动，M-5 仍未通过。当前已停在正式大规模付费测评之前；未来只有在正式 Gate 1
按既有授权流程启动并通过后，才能进入 Gate 2。
