# Plan 035 关闭 Plan 031 的两项非阻断观察

日期：2026-08-15 ｜ 分支/worktree：`035-plan031-nonblocking-cleanup`（从 `main@f98431e` 切出）
针对：`agent_log/2026-08-15-050341-plan031-independent-acceptance-review.md` §非阻断观察 1、2

两项均属实并已修复。生产行为一字未改（除注释口径），只动测试与 bridge 文件头。

## 1. “服务不可达”测试真正覆盖服务不可达（观察 1）

先复现，确认旧 fixture 命中的门：旧测试用 `self._config("http://127.0.0.1:1/v1")`，不带 `model_path`，
直接调用 `bridge.decide()` 得到

```
UpstreamUnavailableError <- ServiceUnavailableError("local Guardian route is not bound to a launcher instance")
```

且对配置 endpoint 的 TCP 连接尝试为 **0 次**——与 `test_bridge_refuses_to_serve_without_a_bound_launcher_instance`
是同一道门，`127.0.0.1:1` 这个死端口从未被拨号。

设计约束（读代码得到，决定了 fixture 形态）：`require_launcher_identity()` 走
`_verify_process(require_listener=True)`，要求 receipt 里的 pid **真实持有** `127.0.0.1:<port>` 的 LISTEN
socket。所以在身份门通过之后，“connection refused”在结构上不可达——指向关闭的端口一定先被身份门拦下。
可达的“服务没了”形态是：端口仍被 receipt 进程持有，但连接建立后立刻断开。

实现：新增 `_UnreachableLocalService`（`socketserver.ThreadingTCPServer`，接受连接、计数、不作任何应答直接
关闭），复用既有 `_bound_bridge` 建立真实 receipt。`_bound_bridge` 原本只用到 `fake.base_url`，签名改为直接
收 `base_url`，3 处既有调用点同步更新。

修复后该测试实际抵达：`client.py:489 _get_json`（`verify_service_identity` 对 `/props` 的第一次真实网络接触）
拿到 `http.client.RemoteDisconnected` -> `ServiceUnavailableError("local approval identity endpoint is
unavailable")` -> `UpstreamUnavailableError` -> HTTP 503，响应体无 `data:`、无 allow/deny。

两个测试的失败原因用**异常链结构**区分，不依赖文案匹配：
- 未绑定身份：`ServiceUnavailableError.__cause__ is None`（门本身的拒绝）。
- 服务不可达：`ServiceUnavailableError.__cause__` 是 `OSError`（底下真有 transport 故障），
  且 dead endpoint 记录到 ≥2 次实际连接，证明两次尝试都越过了前面所有门。

## 2. bridge 文件头口径收窄（观察 2）

`guardian_bridge.py` 文件头删掉“pin 收到 exactly the request shape its 12k qualification covered”。
改为：复用的是 qualification 确立的两条边界（公共 `build_static_payload()` input 归一化 + 已资格化的
serving contract/采样/输出预算），而 Guardian 带的是自己的 instructions 和 output schema，因此**不是**
qualification 的 static request，qualification 与 token census 的长度结论**不构成**这条路径的长度边界。
docstring 后文原本就准确，未改写；未触碰 Plan 031 与旧日志。

## 3. 疑难问题：环境代理污染测试（顺带修）

首轮跑 `GuardianBridgeTests` 12 个里失败 10 个，且失败与我的改动无关（连“缺凭据应 401”都返回 502）。
定位：502 响应体为空、`front.failures` 为空，说明请求根本没到 bridge。原因是本次执行环境设置了
`http_proxy`，而 `no_proxy` 只覆盖 `localhost` 不覆盖 `127.0.0.1`；测试辅助函数 `_post_to_bridge()` 用裸
`urllib.request.urlopen`，于是所有 loopback 请求被代理接管。

已确认这是**测试侧**问题而非产品缺陷：生产的 `client.py:565` 与 `launcher.py:84` 本来就用
`ProxyHandler({})` 建 opener。修复即让测试客户端对齐生产：新增 `_LOOPBACK_OPENER`。
基线对照（同环境）：`main` 上 `tests.test_local_approval` 115 跑 10 败；本分支 115 全过。

## 验收结果

- `GuardianBridgeTests`：**12/12 通过，0 skip**，8.65s。
- `tests.test_local_approval`（local-approval focused 全模块）：**115/115 通过，0 skip**，22.9s。
- `git diff --check`：通过。
- 未运行：Cargo、Docker、本地模型、真实 API、正式 CLI 链路、全量测试、其他 eval 模块
  （`guardian_bridge` 在 `eval/tests/` 内只被 `test_local_approval.py` 引用）。
- 未合并 `main`、未推送、未删除 worktree、未触碰 Plan 034 worktree 与 `training/`。
