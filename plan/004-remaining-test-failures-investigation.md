# 39 个严格失败与 2 个附加设施事项最终修复计划

> 状态：最终实施方案，39 个严格失败尚未落地修复。
>
> 计数基线：最新严格全量记录有 81 个失败名；第一批实际覆盖 42 个失败名，因此当前待修集合机械推导为
> 39 个严格失败。external-agent migration 是更早一轮的偶发超时，OAuth 是始终通过但会打开宿主浏览器的
> 副作用，二者是附加事项，不能称为“剩余失败”。在下一次完整全量前，“39”只表示与严格清单对齐的待修
> 集合，不表示已经实跑出一轮“仅失败39项”的新结果。
>
> 本计划已吸收 GPT/Claude 的历次交叉核验与分歧裁决。执行者可直接按本计划实施；若 live code 已发生变化，
> 只允许根据新证据更新“当前状态/关键决策记录”，不能静默放宽硬约束。

## 1. 目标

### 最终目标

在 WSL2 + Clash Verge TUN、fake-IP DNS、ambient proxy、`/tmp` 祖先 marker 和 Windows PATH 互操作均保持
存在的条件下，以确定性 fixture 修复 39 个严格失败，并消除 2 个附加 hermeticity 问题。产品安全默认值、
SSRF fail-closed、safe-command 分类和沙箱强度保持不变。

### 完成/验收标准

- 39 个严格失败逐项对应到本计划的 21+5+1+1+6+1+1+2+1 分类，无重计或漏计。
- 测试不依赖宿主 DNS、代理、home、`/tmp` 祖先、WSL PATH、真实 GitHub 或真实浏览器。
- resolver、HTTP direct、filesystem、probe、browser 等 seam 的生产默认行为与修改前一致。
- DNS 错误/超时/私网结果继续 fail-closed；不把 fake-IP、TEST-NET 或私网改判公网。
- Landlock 测试必须证明未沙箱控制轮可达、沙箱轮未到 listener，并验证具体拒绝语义；任意非零、超时、
  缺 binary 或 skip 都不算通过。
- V8 full-workspace 断言始终有信息量；default=false 与 sandbox=true 两条独占 canary 合同成对通过。
- 两项时序测试交付修改前/后各两组 200 次数据（单线程与10线程），不靠扩大 timeout 收口。
- 每个修改批次只跑相关包门禁；全部批次完成后只跑一次完整 workspace 全量，所有 Cargo 重型任务均走
  `just`/`mydev/scripts/with-build-lock.sh`，一次一组。
- 保持 Clash、代理变量和 `/tmp/.git|.codex|.agents` 原状完成验收；不得用宿主清理换绿色。

## 2. 范围

### 允许修改

- `mydev/codex-rs/` 内列出的测试、fixture 和实现确定性注入所需的最小私有 seam。
- 现有 HTTP client/factory/selector、filesystem abstraction、ResponseMock 等测试设施的窄扩展。
- 与 V8 本地 canary、测试入口和本计划直接相关的配置、文档与 agent log。
- external migration 的纯推导测试与 OAuth CLI 的 `--no-open-browser` 显式入口。

### 不允许修改

- 产品 SSRF、本地/私网地址、DNS rebinding、防 MITM、safe-command、审批或 Landlock/seccomp 策略。
- Clash、DNS、NO_PROXY、宿主代理、`/tmp` marker、真实 home、WSL interop、系统服务或全局工具链。
- `codex-source-code/`、真实 API/模型、远端仓库、发布/上传流程。
- 通过 `#[ignore]`、skip、删断言、任意非零即成功、降低事件量或单纯延长超时凑绿。
- 新建测试框架、重型测试 crate、常驻服务或无必要的公共 API。

### 不允许读取/查看

- 项目外个人文件、凭据、真实会话或无关仓库。fixture 不读取用户 shell profile 的内容。

## 3. 硬约束

1. 实施前确认本工作树看门狗 F2/F7 已通过轻量回归和至少一轮真实 `just test` JUnit 归属 smoke；看门狗
   不可靠时不得启动本计划的 Cargo 门禁。
2. 每族先用最小定向命令复现或取证。若历史失败在定向环境不复现，记录该事实，再以受控污染/注入验证合同；
   不得把未复现写成已修复。
3. 正式验证保持 Clash/TUN 与代理变量存在。允许测试自己的 Direct client、fixture resolver、`wget --no-proxy`
   来表达确定性合同；不允许在外层 `unset` 环境后把结果当正式证据。
4. 测试的真实网络路径一律替换为本地服务、fake collaborator 或纯函数合同；live smoke 必须另列且默认不跑。
5. 所有新 seam 必须有“生产默认仍走旧实现”的回归。测试专用入口优先 `#[cfg(test)] pub(crate)` 或私有 helper。
6. 任何一项最终为产品缺陷时，保留红色强断言并另立产品任务；不能在测试侧掩盖。
7. 原始失败输出、定向结果、JUnit 路径/SHA 和 watcher `summary.env` 写入该批 agent log；skip/未运行单列。

## 4. 集合与实施总览

| 族 | 根因/合同 | 严格项数 | 当前性质 |
|---|---|---:|---|
| A | ambient DNS/fake-IP 污染 host policy | 21 | 非 hermetic fixture；产品 fail-closed 正确 |
| B | ambient HTTP proxy 改变 transport path | 5 | 非 hermetic client/probe fixture |
| C | login shell profile 重新注入用户代理 | 1 | 原断言超出产品合同 |
| D | Landlock wget 固定10秒超时 | 1 | 历史为 `Sandbox(Timeout)`，具体重试机制待诊断 |
| E | `/tmp` 祖先 marker 泄漏 | 6 | 非 hermetic root discovery fixture |
| F | WSL PATH 暴露 Windows PowerShell | 1 | 平台条件测试错误，不能放宽分类器 |
| G | V8 feature unification | 1 | 原断言比较不同层级状态 |
| H | realtime/remote replay 时序 | 2 | 需200次双负载取证后确定化 |
| I | exec-server empty roots | 1 | 本地2秒超时，根因待按terminal状态分流 |
|  | **严格失败合计** | **39** |  |
| J | external migration 真 GitHub clone | 附加1 | 历史偶发，非当前严格失败 |
| K | OAuth 打开真实宿主浏览器 | 附加1 | 当前通过，但有副作用 |

## 5. A族：确定性 DNS（21项）

### 5.1 精确集合

`codex-network-proxy` 20项：

- `runtime`: `host_blocked_requires_allowlist_match`、`add_allowed_domain_removes_matching_deny_entry`、
  `host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist`、
  `host_blocked_subdomain_wildcards_exclude_apex`。
- `http_proxy`: `http_connect_accept_blocks_in_limited_mode`、
  `http_connect_accept_blocks_hooked_host_in_full_mode_without_mitm_state`、
  `http_connect_accept_passes_environment_id_to_decider`、
  `http_connect_accept_defers_brokered_host_mitm_until_protocol_detection`。
- `mitm`: `mitm_policy_blocks_disallowed_method_and_records_telemetry`、
  `mitm_policy_allows_matching_hooked_write_in_full_mode`、
  `mitm_policy_blocks_hook_miss_for_hooked_host_and_records_telemetry_in_full_mode`、
  `mitm_policy_blocks_matching_hooked_write_in_limited_mode`。
- `network_policy`: `evaluate_host_policy_emits_domain_event_for_decider_ask`、
  `evaluate_host_policy_emits_domain_event_for_decider_allow_override`、
  `evaluate_host_policy_emits_execution_id_for_baseline_allow`。
- `socks5`: `handle_socks5_tcp_blocks_limited_mode_without_mitm_state`、
  `handle_socks5_tcp_blocks_hooked_non_https_host_in_full_mode`、
  `handle_socks5_tcp_uses_mitm_for_hooked_host_in_full_mode`、
  `handle_socks5_tcp_detects_tls_for_brokered_nonstandard_port_in_full_mode`、
  `handle_socks5_tcp_uses_mitm_in_limited_mode`。

第21项是 `codex-core::session::managed_network_proxy_decider_survives_full_access_start`。

### 5.2 产品 seam

在 `network-proxy/src/runtime.rs` 给 `NetworkProxyState` 增私有、可克隆 resolver：

```rust
type HostLookupFuture =
    Pin<Box<dyn Future<Output = io::Result<Vec<SocketAddr>>> + Send + 'static>>;
type HostLookup = Arc<dyn Fn(String, u16) -> HostLookupFuture + Send + Sync>;
```

- 所有生产构造器默认安装 `system_host_lookup`，仍调用 `tokio::net::lookup_host`。
- `host_blocked` 只把现有内联闭包换成 state resolver；`for_execution_token`、reload、remote launch 保留同一resolver。
- 更新现有手写 `Clone`；手写 `Debug` 继续 `finish_non_exhaustive()`，不打印函数对象。
- 仅提供测试构造器，不新增公共设置项。

测试 resolver 使用精确登记表：只登记当前用例所需 hostname，统一返回 `8.8.8.8:<传入端口>` 只做地址分类，
不实际发包；未知 hostname 返回 `io::ErrorKind::NotFound`。禁止 catch-all，也禁止用 `192.0.2/24`、
`198.51.100/24`、`203.0.113/24` 或 `198.18/15`，这些在产品 policy 中均是非公网。

### 5.3 安全回归与 core 项

- DNS错误、DNS timeout、显式 `10.0.0.1` 仍必须得到 `NotAllowedLocal`。
- `does-not-resolve.invalid` 用错误 resolver，不依赖宿主DNS。
- 不设置 `allow_local_binding=true` 绕过纵深检查。
- core decider 项不验证域名语义，目标与 Host 可改为公网IP字面量 `8.8.8.8`；继续断言HTTP 403、
  `blocked-by-allowlist`、decider恰调用一次、原因是 `not_allowed` 而非 `not_allowed_local`。

### 5.4 门禁

```text
just test -p codex-network-proxy -E 'test(/host_blocked/) or test(/http_connect_accept/) or test(/mitm_policy/) or test(/evaluate_host_policy/) or test(/handle_socks5_tcp/)'
just test -p codex-network-proxy
just test -p codex-core -E 'test(/managed_network_proxy_decider_survives_full_access_start/)'
```

## 6. B族：确定性直连 HTTP（5项）

### 6.1 精确集合

1. `codex-http-client::without_url_redacts_transport_error_urls`
2. `codex-api::upload_openai_file_reports_blob_transport_diagnostics_without_sas`
3. `codex-cli::mcp_check_warns_for_optional_http_reachability`
4. `codex-core-plugins::search_remote_plugins_redacts_sensitive_parameters_from_transport_errors`
5. `codex-exec-server::delegated_http_failure_warning_redacts_request_url`

### 6.2 共用 Direct policy

给既有 `OutboundProxyPolicy` 增 `Direct`：

- 同步/异步 route resolver 直接返回 `OutboundProxyRoute::Direct`，不读取代理环境或 `NO_PROXY`，也不调用DNS resolver。
- client builder 必须落到既有 `.no_proxy()`；redirect继续直连。
- Direct不得退回 `ReqwestDefault` 的 transport-default/custom-CA 分支。
- 生产默认和所有现有构造仍用原策略。更新 `route_aware_client_pool.rs`、
  `core-plugins/startup_sync/http_client.rs`、相关测试和 `ollama/src/client.rs` 的穷举匹配。
- 用有毒 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY` 的 `MapEnv` 加单测，resolver设为panic，证明Direct不读它们。

### 6.3 各项落点

- #1 直接用 `reqwest::Client::builder().no_proxy().build()`，保留关闭端口和URL脱敏断言。
- #2 已有 `RouteAwareClientPool` 参数，测试传 Direct pool；保留 `failed after`、connect分类、Azure request ID、
  SAS不泄漏。
- #3 抽 `mcp_check_from_servers_with_probe`，生产wrapper仍调真实probe；测试注入确定的connect失败，保留Warning、
  optional issue与失败详情。既有本地listener probe也显式Direct。
- #4 已有 `RemotePluginServiceConfig.http_clients: Arc<dyn HttpClientSelector>`，给测试selector传Direct；保留
  accept后drop的中途transport错误和敏感参数脱敏。listener accept需有界等待。
- #5 已有 `HttpClientFactory` 注入，传Direct factory；继续要求请求失败、`error_is_connect=true`、path/query不泄漏。

### 6.4 门禁

```text
just test -p codex-http-client -E 'test(/without_url_redacts_transport_error_urls/) or test(/direct/)'
just test -p codex-api -E 'test(/upload_openai_file_reports_blob_transport_diagnostics_without_sas/)'
just test -p codex-cli -E 'test(/mcp_check_warns_for_optional_http_reachability/)'
just test -p codex-core-plugins -E 'test(/search_remote_plugins_redacts_sensitive_parameters_from_transport_errors/)'
just test -p codex-exec-server -E 'test(/delegated_http_failure_warning_redacts_request_url/)'
```

## 7. C族：登录 shell 的 managed proxy 合同（1项）

测试 `user_shell_commands_do_not_inherit_managed_network_proxy` 只承诺移除当前session的managed proxy；login
shell允许用户profile重新设置自己的代理。历史输出 `127.0.0.1:7897` 是宿主Clash，不是本session的随机代理。

最终断言：

- 从 `turn_context.network.apply_to_env` 取出本session managed `HTTP_PROXY`。
- shell同时输出 `HTTP_PROXY` 与 `CODEX_NETWORK_PROXY_ACTIVE`。
- active marker不存在，最终HTTP_PROXY不等于本session managed URL；允许是用户代理或 `not-set`。
- 不读取、修改或隔离用户profile。这是钉准原产品合同，不是降低安全断言。

门禁：

```text
just test -p codex-core -E 'test(/user_shell_commands_do_not_inherit_managed_network_proxy/)'
```

## 8. D族：Landlock wget TCP connect（1项）

### 8.1 已证事实

- 上游原始日志两次均为 `Sandbox(Timeout)`、exit 124、约10.003秒，panic在“expected sandbox denied error”分支；
  不是 `exit_code == 0` 的沙箱击穿。
- 源码 `NETWORK_TIMEOUT_MS=10_000`；“2-second timeout”注释过时。
- stdout/stderr为空由 `wget -q` 可完全解释，不能推断wget内部状态。
- RONDO较早一轮该项0.040秒通过；最新严格轮缺原始stderr，因此不是稳定必现。
- seccomp无条件拒绝 `connect`，且 `socket(AF_INET)` 也被拒；回环与公网不走不同规则面。
- “代理导致超时”尚未证明。可能是wget对EPERM的重试，也可能是其他fixture时序。

### 8.2 先诊断、再固定合同

先在看门狗内单跑一次诊断：去掉 `-q` 或加 `-d`，显式 `--tries=1`，记录完整 `SandboxErr`、duration和
wget stderr。只有日志能决定历史10秒的内部机制；最终方案不依赖该归因。

最终测试改名为 `sandbox_blocks_wget_tcp_connect`：

1. 起受控loopback HTTP listener。
2. 同一个wget binary先跑未沙箱控制轮，使用 `--no-proxy --tries=1` 和局部短连接/读取超时；必须成功且
   listener收到恰好一个请求。控制轮失败不是skip，而是fixture失败。
3. 沙箱轮访问同一listener、同样单次尝试；要求快速返回明确 `SandboxErr::Denied`（或经源码证明等价的
   seccomp EPERM分类），listener不得收到第二个请求。
4. Timeout、binary缺失、DNS失败、connection refused、任意非零均不得被当作沙箱通过。

此方案理由是 hermetic 且断言更强，不写成“修复了已证实的代理污染”。

门禁：

```text
just test -p codex-linux-sandbox -E 'test(/sandbox_blocks_wget_tcp_connect/)'
just test -p codex-linux-sandbox
```

## 9. E族：fixture边界内的项目根发现（6项）

1. `codex_home_is_not_loaded_as_project_layer_from_home_dir`：在home创建唯一非空marker，user config配置该marker；
   真实发现home为根后，再证明同一 `home/.codex` 不会作为Project层加载。
2. `project_layers_disabled_when_untrusted_or_unknown`：在project root创建唯一非空marker，untrusted与unknown
   两条配置均显式传入；保留nested cwd、trust entry和Project层被禁用的原语义。
3. `resolve_root_git_project_for_trust_returns_none_outside_repo`：复用现有FS参数，测试装饰器对fixture root外
   `get_metadata` 返回NotFound，其余转发 `LOCAL_FS`；不造畸形 `.git`。
4. `workspace_section_requires_meaningful_structure`：抽私有
   `build_workspace_section_with_user_root_with_fs`，生产传 `LOCAL_FS`，测试传fixture-bounded FS；不把None契约改为空结构。
5. `recent_work_section_groups_threads_by_cwd`：同样抽 `build_recent_work_section_with_fs`；不把两个目录改成两个repo。
6. `environment_id_fallback_has_cwd_prefix`：抽纯函数
   `environment_id_from_cwd_with_repo_root(cwd, Option<PathBuf>)`，public wrapper传真实结果；fallback传None，并补
   Some(repo_root)控制用例。

空 `project_root_markers=[]` 会直接短路根发现，不能用于 #1/#2。验证时保持 `/tmp/.git/.codex/.agents` 存在。

```text
just test -p codex-core -E 'test(/codex_home_is_not_loaded_as_project_layer_from_home_dir/) or test(/project_layers_disabled_when_untrusted_or_unknown/) or test(/resolve_root_git_project_for_trust_returns_none_outside_repo/) or test(/workspace_section_requires_meaningful_structure/) or test(/recent_work_section_groups_threads_by_cwd/)'
just test -p codex-secrets -E 'test(/environment_id_/)'
```

## 10. F族：PowerShell目标平台（1项）

在 `commands_generated_by_shell_command_handler_can_be_matched_by_is_known_safe_command` 中：

- 两个PowerShell finder import和两段PowerShell/Pwsh断言均用编译期 `#[cfg(windows)]`。
- Bash/Zsh断言所有平台继续运行；既有非Windows拒绝PowerShell分类的安全测试保留。
- 不使用运行时 `cfg!(windows)` 留下无用import/lint，也不在Linux开启Windows safelist。

```text
just test -p codex-core -E 'test(/commands_generated_by_shell_command_handler_can_be_matched_by_is_known_safe_command/)'
```

Windows平台同名测试属于平台验收；本地WSL通过不能代替Windows未运行事实。

## 11. G族：V8 feature unification（1项）

将单条错误等价断言拆为两层：

1. 全workspace始终执行：

   ```rust
   assert!(!cfg!(feature = "sandbox") || linked_v8_has_sandbox());
   ```

   声明本crate sandbox时，链接库必须具备sandbox；feature unification只会增加依赖feature，因此该蕴含在
   独占与workspace两种模式都有意义。
2. 独占canary严格钉住两个方向。给crate加互斥期望feature，例如
   `v8-canary-expect-default` 和 `v8-canary-expect-sandbox`（后者包含 `sandbox`）；同时启用必须compile error。
   default期望 `linked_v8_has_sandbox()==false`，sandbox期望true。两条必须成对，default=false负责抓恒true、stub
   或链错库。

本项目不依赖远端CI作为交付证据；沿用现有V8资产准备方式，在本地看门狗内分别运行独占default、独占sandbox
与workspace包含该测试的三种门禁。任何模式资产不可用都记未运行，不能把全量断言改成skip。

```text
just test -p codex-v8-poc --no-default-features --features v8-canary-expect-default
just test -p codex-v8-poc --no-default-features --features v8-canary-expect-sandbox
# 全部族完成后的唯一一次workspace门禁中必须实际执行codex-v8-poc的单向蕴含测试。
```

## 12. H族：两项时序测试（2项）

### 12.1 共用取证协议

每项在改代码前后分别运行：

```text
just test -p codex-core --test-threads 1 --stress-count 200 --retries 0 --flaky-result fail -E 'test(<exact-name>)'
just test -p codex-core --test-threads 10 --stress-count 200 --retries 0 --flaky-result fail -E 'test(<exact-name>)'
```

确认JUnit确实记录200次实际执行，分别给出失败次数/phase。单线程0/200不能推翻只在并发负载出现的问题；
10线程0/200也只能作为定向证据，最终仍需一次workspace默认10线程门禁。不得只增2秒/5秒timeout。

`<exact-name>` 分别替换为：

- `conversation_close_routes_only_remaining_transcript_tail_once`
- `exec_command_consumes_pushed_remote_process_events::truncated_event_replay`

### 12.2 realtime close

目标：`conversation_close_routes_only_remaining_transcript_tail_once`。

- 给既有 `ResponseMock` 增 `request_log_updated: Arc<Notify>` 与 `wait_for_request_count(count)`；在请求日志push后notify。
- 首个 `RealtimeConversationClosed` 后等待request count=2，替换10ms/2s轮询。
- 第二次Close后等待第二个 `RealtimeConversationClosed` 作为submission queue barrier，再断言请求仍恰好2个，
  替换固定200ms sleep。
- 不改产品close语义；若Notify后仍出现第三请求，按产品缺陷处理。

### 12.3 truncated replay

目标：`exec_command_consumes_pushed_remote_process_events::truncated_event_replay`。

- 保留1024通知，不能降低超过256 replay/queue容量的压力。
- fake server记录：已发output数、exited/start response/closed是否发送、`process/read`次数、terminate是否收到、
  Responses第二请求是否到达。
- 所有5秒等待在失败时输出phase，而不是裸 `expect`。
- 取证后仅允许：用Notify/barrier消除不可观察竞态，或确认terminal event真丢失并立产品缺陷；不得减事件或加时。

## 13. I族：exec-server empty workspace roots（1项）

目标：`remote_process_preserves_empty_workspace_roots`。超时时立即执行
`session.read(after_seq, None, Some(0))`，记录 `chunks/next_seq/exited/exit_code/closed/failure/sandbox_denied`，并记录
harness与child存活状态：

- read已terminal：push/replay交付问题；
- read仍running且无事件：sandbox helper/process卡住；
- read返回failure：拒绝走错误通道传播。

只有证明read稳定terminal且仓库已有独立pushed-event生命周期覆盖时，才可让本测试改用read collector。验收继续要求
stdout不含 `excluded`、非零或明确sandbox denial、terminal closed、empty roots不补默认根。缺bwrap是未运行。

```text
just test -p codex-exec-server --stress-count 200 --retries 0 --flaky-result fail -E 'test(/remote_process_preserves_empty_workspace_roots/)'
```

## 14. J/K附加设施事项

### 14.1 external migration：去真实GitHub

当前external层没有local cloner seam；core-plugins中的cloner helper是私有同步测试入口。最低成本收口：

- 在 `source_cla::marketplace_import_sources` 的纯测试钉住缺省官方源
  `anthropics/claude-plugins-official`。
- 既有本地marketplace import测试继续覆盖添加、安装、配置写入管线。
- 将真实GitHub集成测试拆为“官方源推导”与“本地导入管线”两个合同；不ignore。
- 若必须单测试贯通，只在external内部加 `import_plugins_with_marketplace_adder` closure，fake记录精确source；
  不扩成公共cloner框架。

生产git缺timeout/cancel/后代清理是真实产品缺陷，另立任务并用本地挂起+派生后代wrapper验证；测试hermetic修复
不能宣称该产品缺陷闭环。

定向门禁必须覆盖纯source推导和本地marketplace导入测试；运行过程中不得产生对GitHub的DNS、connect或git
子进程。用测试进程/fixture记录来证明“没有外部调用”，不能只凭测试快速通过推断。

### 14.2 OAuth：显式禁止打开浏览器

给 `mcp login` 增 `--no-open-browser`，底层flow接收显式 `launch_browser`；false时仍打印authorization URL、等待
callback、换取并持久化token。`login_and_logout_persist_only_cloud_managed_mcp_oauth_credentials` 使用该flag，现有
callback/token/logout断言全部保留。只设 `BROWSER` 不是跨平台合同，Windows实现可能不尊重它。

```text
just test -p codex-external-agent-migration -E 'test(/marketplace_import_sources/) or test(/import_plugins/)'
just test -p codex-cli -E 'test(/login_and_logout_persist_only_cloud_managed_mcp_oauth_credentials/)'
```

## 15. 串并行实施顺序

代码审查可按独立族并行；所有重型测试严格串行：

1. 前置：看门狗真实 `just test`/clippy smoke，确认JUnit `retained` 与非nextest `not_applicable`。
2. 批次A：resolver seam + 20 network-proxy + core decider。
3. 批次B/C：Direct policy与5项消费者；随后shell合同。
4. 批次E/F：fixture-bounded roots与PowerShell平台收口。
5. 批次D/G：Landlock诊断/强合同；V8三模式。
6. 批次H/I：严格执行修改前双200取证，再决定实现；改后同负载复验。
7. 附加J/K：纯推导+本地管线、`--no-open-browser`。
8. 每批跑相关包；全部通过后执行一次完整workspace `just test`，核对JUnit、失败/skip清单与watchdog summary；
   最后运行受影响包clippy/fmt，不重复全量。

若前5批完成，严格待定只应剩 H的2项与I的1项，即39→3；附加J/K不计入严格失败。任何实际数量差异都以
新的机器JUnit逐名对账，不能靠算术改口径。

## 16. 当前状态

### 已完成

- 核对81项严格清单与第一批42项覆盖，冻结39+2口径。
- 证实Clash fake-IP、ambient proxy和 `/tmp` marker是环境事实；没有修改宿主。
- 证实Landlock历史失败是10秒 `Sandbox(Timeout)`，不是沙箱击穿；代理归因撤回。
- 证实回环/公网走同一seccomp拒绝面；本地listener合同成立。
- 证实原V8断言受feature unification影响；确定全量单向蕴含+独占双向canary。
- 核对各现有seam：NetworkProxyState手写Clone/Debug、HTTP factory/selector/pool、realtime缺FS参数、
  external无公开cloner、OAuth硬编码开浏览器。

### 当前工作

- 本计划已定稿，等待后续按批次实施39个严格失败与2个附加事项。

### 阻塞项

- H/I的最终代码修法必须由修改前取证决定；本计划给出可执行诊断和分流，不预判产品/fixture结论。
- Windows PowerShell门禁、本地V8资产或bwrap缺失时必须如实记未运行，需要相应平台/资产后补验。

### 当前验收状态

- 方案审查完成；39+2代码未实施、未通过新全量，不能称测试闭环。

## 17. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 使用39严格失败+2附加事项口径 | 第一批实际覆盖42；migration/OAuth不在严格失败清单 | 全计划 | 已采纳 |
| 002 | DNS用精确登记resolver，未知返回错误 | catch-all会破坏DNS失败安全回归 | A | 已采纳 |
| 003 | 增显式Direct policy，默认不变 | 5项已有pool/factory/selector seam，不能依赖NO_PROXY | B | 已采纳 |
| 004 | shell只排除本session managed proxy | login shell可合法重载用户profile | C | 已采纳 |
| 005 | Landlock使用本地listener+未沙箱对照 | seccomp无地址分支，合同更强且hermetic | D | 已采纳 |
| 006 | 项目根测试用非空marker或FS seam | 空marker直接禁用根发现，会弱化测试 | E | 已采纳 |
| 007 | PowerShell断言按编译目标平台收口 | WSL PATH不等于Windows分类目标 | F | 已采纳 |
| 008 | V8全量蕴含与独占双canary成对 | 既覆盖unification又抓恒true/链错库 | G | 已采纳 |
| 009 | 时序修复前后都做1线程/10线程各200次 | 孤立通过不能覆盖workspace并发竞态 | H | 已采纳 |
| 010 | external产品git终止另立任务 | hermetic测试与产品子进程缺陷不能混称闭环 | J | 已采纳 |
| 011 | OAuth用CLI显式no-open-browser | BROWSER环境变量不是跨平台保证 | K | 已采纳 |
