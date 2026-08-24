# Plan 062：教师源码热路径优化执行记录

状态：**实现已提交，等待独立审查**。本记录不宣布最终 PASS。

## 实质修改

- 提交三项学习教师源码后筛选并自主实现的优化：history orphan output 用借用 call ID 建索引并仅在命中时删除；
  `ToolRouter`/`Prompt` 以 `Arc<[ToolSpec]>` 共享模型可见工具规格；unified-exec 直接形成连续 retained bytes，合法
  UTF-8 denial 判定不再无条件复制 owned `String`。
- 直接回归覆盖 debug/release orphan 语义、匹配和 idless tool-search、survivor 顺序、工具规格 pointer sharing、
  普通/Lite/WebSocket/remote compact 请求一致性、head/tail/空/非 UTF-8/sandbox-denial 快照。
- 新增默认不运行的 Plan 062 Divan/just runner 和 body-free 聚合。Divan 对零分配省略 allocation block，解析器补零
  记录回归后废弃旧两侧数据，并重跑同一新哈希 baseline/candidate。
- crate 门禁另暴露两个既有窄 fixture：配置 schema 缺少已存在的 Plan 052 字段、realtime 测试假设固定端口会立即
  refused；分别同步 schema snapshot、改用动态 loopback reset server，没有改变产品语义或基线身份。

## 正式证据

- benchmark scaffold：`aa4c925`、`52e7302`；产品实现：`782baab`；clean baseline：`d5535fc`；clean candidate：
  `22b8766`。baseline/candidate 均 `dirty=false`，harness SHA-256 均为
  `ef8364c8a225226fa1085355ae447f55b9a0aabb3fab6d2f8f264703c77fd5f2`。
- 正式门禁：benchmark smoke 成功列出 9 case；定向 48/48；release exact 1/1；Python parser 4/4；
  `just test -p codex-core` 3332/3332（8 skipped、2 slow）；正式 candidate benchmark 9/9。
- 聚合：`eval/results/observations/plan062-direction1-teacher-hotpath-optimizations.json`。history allocation count
  `11/37/135 → 3/5/7`；tool specs `1296/5136/10256 → 0/0/0`；snapshot `3/3/4 → 1/1/1`。各 case
  allocated bytes 与 median time 均下降；只解释对应扫描、复制、分配和局部耗时。

## 资源、诊断与边界

- 所有 Rust 构建、测试和 benchmark 均经共享 build lock/watchdog 串行运行。正式轮采样峰值为内存
  13,327,609,856 bytes、swap 208,441,344 bytes、项目 159,741,849,600 bytes；Windows `C:` 可用空间最低
  约 193.87 GB，未触发资源 stop。正式 raw 和 JUnit 均保留在 062 worktree ignored namespace。
- 调试轮曾遇到缺少测试 helper binary、schema fixture 漂移、固定端口环境差异、一次 release 资源 exit 125、错误的
  release integration target 入口和一次零分配 parser failure；均按窄范围修复或改用正确入口。修复后从新 clean
  candidate 完整重启正式轮，调试结果未拼入聚合。
- ignored 工件包括约 36 GB 受监控 Cargo target、568 KB benchmark raw、4 MB watchdog/JUnit、29 MB 校验过的
  Rusty V8 构建依赖，以及格式/测试缓存；未删除共享 target/cache，未发现 `/tmp/rondo-plan062-*` scratch。
- 未运行全 workspace、Bazel、Docker、Terminal-Bench、真实 API、真实本地模型、训练、云任务、付费资源、CI 或
  PR；未读 `.env.local`，未修改主工作区，未合并、推送、重命名或归档分支。
