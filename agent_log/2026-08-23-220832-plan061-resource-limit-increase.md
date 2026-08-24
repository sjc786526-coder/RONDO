# Plan 061 固定资源门线调整

## 实质修改

- 将共享构建 wrapper 的固定默认值调整为 `MemoryHigh=21G`、`MemoryMax=22G`、
  `MemorySwapMax=5G`，项目十进制告警/主动停止/绝对线调整为 `240/255/260GB`。
- 同步 `runtime_bridge.py` 的 high/max 精确字节校验，并在现有测试内参数化覆盖
  `memory.high`、`memory.max`、`memory.swap.max` 三项漂移。
- 更新根开发规则与开发环境当前说明；override 的变量、解析和直接覆盖机制不变，未覆盖维度继承新默认。
- 保留 Plan 054 v4 evidence、测试夹具、冻结结果和旧 summary 原样；v4 只保留历史验证能力，
  新 campaign 需要另行升级证据版本。

## 验收

- `bash -n scripts/with-build-lock.sh` 与 `git diff --check` 通过。
- `WatchdogBridgeTests` 6/6 通过；Plan 054 v4 旧证据精确测试 1/1 通过。
- 最终单次真实 wrapper scope 为 `rondo-build-1000-20260823220746-3339026.scope`：production lease
  在两秒等待前后均有效，cgroup 读数为 `22548578304/23622320128/5368709120 B`；summary 为
  `command_name=python`、complete、run/final 0、stop/cleanup none、JUnit not_applicable，并记录
  `21G/22G/5G` 与 `255/260GB`。该 unit 最终不再 active/failed。
- 最终专属 ignored metrics 目录只有一份 summary；项目采样峰值 `139975536640 B`，低于 240GB 告警线。

首次沙箱内 scope 因无 systemd user bus 而按设计 fail-closed。宿主权限重试等待共享锁；一个失去会话句柄的
排队命令后来也串行完成，导致临时目录出现两份 summary，计数门禁正确拒绝。只删除本任务生成的该目录后，
重新执行上述单次最终验收并通过。

未运行 Cargo、Docker、模型、API 或全量测试；未修改 binary、target、产品源码、Plan 054/059/060 身份工件，
也未触碰 060、062 的并行修改。
