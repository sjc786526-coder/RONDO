# Plan 093 RONDO Multi 干净全 workspace 基准

## 实现与现场

- 共享 watchdog 现在由物理 Git common root 与显式产品 identity 解析默认 target；Multi/Local 分别映射到
  `.codex/cargo-target/rondo-multi` 与 `rondo-local`。根及两产品正式 Unix 重型 Cargo 入口已统一接入，显式专用 target 仍保持优先。
- 永久项目门更新为十进制 `270000000000 / 285000000000 / 290000000000` bytes，永久 Windows C: 门保持
  `50000000000` bytes；summary 的全部完成/阻断形态记录产品、target 与四条实际门。本任务重型命令只在进程级使用获批 C30。
- 在 canonical lock 内完成 exact 安全检查后删除 069 target `212729303040` bytes；随后归档 069/091 分支并释放
  069/087/089/091/092 clean worktree，保留全部分支、提交和历史。主物理仓库只剩 main、090、093 worktree。
- 共享 target 从空目录开始建立冷编译现场。调试期只在无人使用且持锁时两次精确清理新 target 的
  `debug/incremental`，未清理 deps/release/registry/V8；最终 target 与正式证据均保留，`rondo-local` 从未创建或加热。

## 全量暴露与修复

- 冷系列最终完成 workspace 的完整枚举与执行：14657 tests run、14637 passed、20 failed、24 skipped、4 retry-pass，JUnit
  SHA-256 `96b43074c33661fe6be7b1ab672f416e42242f6bab7dcadfaf5d43e5f98e09c0`。20 项稳定失败分为：Publication Critic
  service binary 未绑定 7、map key 顺序 1、client 相对 cwd fixture 4、Realtime connect 无上界 2、空 rollout fixture 1、review
  相对 cwd fixture 1、并发 app-server/zsh initialize 4。
- Publication Critic process tests 通过 Nextest setup script 构建并传入本轮精确 binary，Unix/Windows host 规则互斥；Windows helper
  在普通入口缺少 `CARGO_TARGET_DIR` 时从 Nextest workspace-root cwd 推导绝对 target。Linux 聚焦 setup 与 7 项 process tests 通过；
  当前宿主无 PowerShell，未冒充原生 Windows 已运行。
- Realtime websocket timeout 被限定在每次握手，而不覆盖 session 初始化；sideband 重试保持 per-attempt。新增 API 层三项以及 Core
  两项回归覆盖延迟 session start、pending handshake、sideband retry 和既有 Error/Closed 合同。其余失败以绝对 TempDir、ephemeral
  history、稳定 key-set 与窄 test-group 修复，没有弱化断言、全局 timeout 或增加 skip。
- 修复后聚焦轮 29/29、review-fix 最终轮 13/13（含 setup）均为零 retry；独立只读复核关闭 Realtime 测试时序和 Windows setup
  两项 Medium，最终无 High/Medium finding。`just fmt-check` 在 task-owned UV cache 下通过，Cargo.lock 无漂移。

## 正式结果

- exact implementation commit `b25b5bb2e57490b8615a8c5c1c432c0fe39440db` 上复用共享 target 运行最终
  `just test-with-codex-v8 --locked`：14660/14660 passed、0 failure/error/timeout、24 skipped、4 slow、1 retry-pass，另有
  1/1 setup passed，359.431s；watchdog `run_rc=0 / stop=none / cleanup=none`。
- 正式 JUnit SHA-256 `ef2d16c4e1f4d1bfb411ddf7fe47127a0b7832cf7f35e649d1fe239e44f55e4b`。唯一 retry 为 loopback
  proxy test 首次 HTTP 502、第二次通过；新进程 `retries=0` 复核 1/1 一次通过。冷轮四项 retry 也已新进程 4/4 一次通过，最终轮均
  首轮通过。24 skip 与冷诊断一致，分类为平台 7、手工/生成/property 5、child helper 6、已延后不稳定 4、真实 API smoke 2。
- Plan 091 prompt-edit 保护项及 Plan 092 三项 Durable Session TUI 原失败均在最终 JUnit 通过。
- 正式采样峰值：项目 `255665065984` bytes、target `196718948352` bytes、memory `6700552192` bytes、swap `0`；项目结束占用为
  `255668121600` bytes，Windows C: 可用空间结束为 `46696902656` bytes。正式 manifest 与原始证据位于
  `test-data/_retained-test-evidence/plan093-clean-full-workspace-baseline/runs/final-b25b5bb2e574-20260827T071344Z/`。

## 诚实记录与边界

- 资源调试期间多个 jobs/LLD 组合被 watchdog 以持续 PSI 正确停止；门限与 memory cgroup 未放宽。最终沿用
  `CARGO_BUILD_JOBS=1` 与 LLD `--threads=1`，并按 ExecPlan 冷重建判据保留已完成冷编译缓存做最终增量全量。
- 一次把 `cargo nextest show-config` 误判为纯配置查询，在 watchdog 外触发了 worktree target 构建；发现后立即停止，确认无进程并在
  canonical lock 内精确删除该 target，未把结果计入验证。后续重型 Cargo 均经正式入口。另有 skip census 首次因 helper 路径笔误在
  wrapper 前 rc2；不计测试结果，正确命令只列出 ignored 测试且未执行它们。
- Plan 090 全程只做 path/branch/HEAD/status 级保护检查，未读取内容、diff 或 ignored 资产；退出时其 owner 已将 090 推进并归档，另创建
  clean 094 worktree，main 也已前进，本任务均未参与或清理。未读取 `.env.local`，未运行 Docker、真实 API/模型、eval、训练、云任务、
  发布上传或上游升级。
- 执行者技术实现与正式验证完成；独立验收、WBS-COMPLETED 与 Plan 验收收口由审查者处理。未合并、未推送、未归档或释放 093。
