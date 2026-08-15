# Plan 035 独立验收审查

日期：2026-08-15  
审查对象：`035-plan031-nonblocking-cleanup@25c491f`  
任务合同：`plan/035-plan031-nonblocking-cleanup-execplan.md`

## 结论

- **验收通过**：两项修改均正确，未发现生产身份门控、HTTP 错误语义、schema 校验或 fail-closed 行为被削弱。
- **任务目标完成**：原“服务不可达”测试现在确实越过身份前置门并命中受控 transport failure；bridge 文件头已准确收窄 qualification 能力口径。
- 本结论只适用于当前独立分支提交；该分支尚未合并或推送，`main` 仍为 `f98431e`。

## 独立审查判断

1. **测试覆盖已纠正。** 新 fixture 为配置模型建立真实 launcher receipt，并由同一进程真实持有 loopback
   监听端口；连接建立后服务端立即断开，使 `verify_service_identity()` 的 `/props` 请求得到真实
   transport error。异常随后按生产链转换为 `ServiceUnavailableError`、`UpstreamUnavailableError` 和
   HTTP 503，响应不含 `data:`、allow 或 deny。它不再与“未绑定 launcher 实例”测试命中同一道门。
2. **两个失败场景区分充分。** 未绑定实例测试证明 endpoint 虽可用却因没有绑定身份而拒绝，且 upstream
   未被调用；服务异常测试证明 endpoint 收到了实际连接，底层异常链包含 `OSError`。这些断言直接约束失败
   原因，没有依赖易漂移的错误文案。
3. **生产功能未被测试便利性改写。** 除文件头注释外，`eval/rondo_eval/local_approval/` 生产代码无变化；
   真实身份门、请求前后身份校验、结构化输出校验与失败映射保持原样。
4. **qualification 表述已经准确。** 文件头现在只主张复用公共 input 归一化和已资格化 serving contract、
   sampling/output budget，同时明确 Guardian instructions/schema 不同，完整请求不是 qualification static
   request，qualification/census 长度结论也不约束该路线。
5. **环境代理适配属于合理的测试修复。** `_post_to_bridge()` 是测试侧 loopback 客户端；让它像生产
   `client.py`/`launcher.py` 一样显式禁用 ambient proxy，避免 `127.0.0.1` 被代理接管，不改变生产路径，
   也没有建立新的设施。

## 独立复验

- `git diff --check f98431e..25c491f`：通过。
- 在故意把 HTTP/HTTPS proxy 指向无效地址、且 `NO_PROXY` 只包含 `localhost` 的环境下：
  - `GuardianBridgeTests`：**12/12 通过，0 skip**，8.620s；
  - `tests.test_local_approval`：**115/115 通过，0 skip**，22.259s。
- worktree 没有独立 `eval/.venv`；复验复用主工作区既有虚拟环境执行 worktree 源码。第一次尝试因该 venv
  不存在而未启动测试，不计作测试失败。
- 未运行 Cargo、Docker、本地模型、真实 API、正式 CLI、其他 eval 模块或全量测试；对本次两项小修没有必要。

## 非阻断记录问题

`plan/035-plan031-nonblocking-cleanup-execplan.md` 的“当前验收状态”误写为 13/13 和 155/155；提交内实际测试、
执行日志与本次独立复验一致，正确数字是 **12/12** 和 **115/115**。这是记录错误，不影响两项功能目标和验收
结论，但合并前应把计划中的两行改为真实数字，不能把错误计数带入 `main`。

## 代用户作出的决策

1. **接受“连接建立后立即断开”作为本测试的服务不可达形态。** 有效 receipt 要求对应进程仍持有监听端口，
   因而在身份门之后制造 connection-refused 结构上不可达；当前 fixture 是稳定、快速且语义真实的最窄替代，
   不要求为了字面上的 connection-refused 绕过身份门。
2. **接受 loopback 测试客户端禁用 ambient proxy。** 这是消除宿主环境污染的必要小修，不需要扩展为新的代理
   测试设施，也不要求修改生产代码。
3. **不要求重命名 `test_bridge_sends_the_qualified_request_shape_and_streams_one_decision`。** 该内部测试的断言和
   相邻注释已经明确验证 qualified serving 参数与 Guardian 自有 contract 的组合；真正承担能力表述的模块
   docstring 已收窄。仅为名称歧义再扩大改动收益不足。
4. **不重新打开 L7、Local M3 或 Plan 031，也不更新 WBS。** 本任务只补齐测试覆盖和注释精度，没有产生新的
   产品能力、阶段变化或真实运行结论。
5. **当前不合并。** 保持 Plan 035 分支隔离；先让正在执行的 Plan 034 完成，随后只修正上述测试计数、基于最新
   `main` 复验直接相关测试，再决定合并交付。无需追加 Cargo、模型、Docker或全量门禁。

## 边界与现场状态

- 提交只修改授权范围内 4 个文件；Plan 034 当前改动位于独立 worktree，未被本分支触碰。
- 审查开始时 Plan 035 worktree clean；本报告是本次审查唯一新增文件，尚未提交。
- 主工作区两个既有未跟踪 `doc/research/RONDO Multi*.md` 未触碰。

