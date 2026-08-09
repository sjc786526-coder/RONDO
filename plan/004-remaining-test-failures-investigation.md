# 39 个严格失败与 2 个附加设施事项最终修复计划

> 状态：当前平台实现、独立整改与可执行门禁已提交，并随主线合并提交 `8c185af` 推送远端；V8
> sandbox/full-workspace 受官方预编译资产404阻断，Windows目标平台未运行，因此本计划仍为部分通过，
> 不宣称跨平台或完整workspace全绿。
>
> 计数基线：最新严格全量记录有 81 个失败名；第一批实际覆盖 42 个失败名，因此当前待修集合机械推导为
> 39 个严格失败。external-agent migration 是更早一轮的偶发超时，OAuth 是始终通过但会打开宿主浏览器的
> 副作用，二者是附加事项，不能称为“剩余失败”。在下一次完整全量前，“39”只表示与严格清单对齐的待修
> 集合，不表示已经实跑出一轮“仅失败39项”的新结果。
>
> 本计划已吸收 GPT/Claude 的历次交叉核验、H/I取证和提交前独立差异审查。实施中的分流与审查修订均记录于
> 第17节和第18节；私有 helper 名称与更窄 seam 按证据调整，但没有静默降低验收强度。

## 1. 目标

### 最终目标

在 WSL2 + Clash Verge TUN、fake-IP DNS、ambient proxy、`/tmp` 祖先 marker 和 Windows PATH 互操作均保持
存在的条件下，以确定性 fixture 修复 39 个严格失败，并消除 2 个附加 hermeticity 问题。产品安全默认值、
SSRF fail-closed、safe-command 分类和沙箱强度保持不变。

### 完成/验收标准

- 39 个严格失败逐项对应到本计划的 21+5+1+1+6+1+1+2+1 分类，无重计或漏计。
- 本计划新建/修改并作为各族合同证据的测试不依赖宿主 DNS、代理、home、`/tmp` 祖先、WSL PATH、真实
  GitHub 或真实浏览器；唯一具名例外是§8的产品合同测试，它刻意走既有login-shell路径，只排除当前session
  managed proxy，不直接读取或记录profile内容。第9.2节点名的既有Landlock legacy测试本阶段不改、不作为D族
  hermetic证据，但仍参加最终workspace回归，失败仍会使全量失败。
- resolver、HTTP direct、filesystem、probe、browser 等 seam 的生产默认行为与修改前一致。
- DNS 错误/超时/私网结果继续 fail-closed；不把 fake-IP、TEST-NET 或私网改判公网。
- Landlock 测试必须证明未沙箱控制轮可达、沙箱轮未到 listener，并验证具体拒绝语义；任意非零、超时、
  缺 binary 或 skip 都不算通过。
- V8 full-workspace 保留“声明 sandbox 则链接库必须具备 sandbox”的兼容性蕴含；default=false 与
  sandbox=true 两条带显式期望值的独占 canary 成对通过，不能把 workspace 中的真值短路称为双向证明。
- 两项时序测试交付修改前/后各两组 200 次数据（单线程与10线程），不靠扩大 timeout 收口。
- 每个修改批次只跑相关包门禁；全部批次完成后只跑一次完整 workspace 全量，所有 Cargo 重型任务均走
  `just`/`mydev/scripts/with-build-lock.sh`，一次一组。
- 所有正式定向和全量 Nextest 门禁统一使用 `--retries 0 --flaky-result fail`；允许另跑带重试的诊断，
  但其结果不能计入验收。`--retries 0` 机械阻止重试吞红，`--flaky-result fail` 是纵深约束。watchdog的
  `junit_status=retained` 只证明文件收尾完整且哈希可读；执行者必须另行解析JUnit，核对实际执行、failure与skip。
- JUnit无法识别测试体内 `return Ok(())`/提前返回形成的“passed假绿”；H/I/K族必须删除对应静默返回，并由正对照、
  fake调用计数和代码审查直接证明，不得把这类语义交给JUnit推断。
- bwrap、wget、Windows、V8 资产或 OAuth 隔离前提不可用时，必须记为“未运行/阶段未完成”；测试内
  `return Ok(())`、打印 skipping、缺 binary 或基础设施启动失败不得在 JUnit 中伪装成通过。
- 保持 Clash、代理变量和 `/tmp/.git|.codex|.agents` 原状完成验收；不得用宿主清理换绿色。

## 2. 范围

### 允许修改

- `mydev/codex-rs/` 内列出的测试、fixture 和实现确定性注入所需的最小私有 seam。
- 现有 HTTP client/factory/selector、filesystem abstraction、ResponseMock 等测试设施的窄扩展。
  若跨 crate 确需 workspace-visible 的 Direct HTTP policy，只允许作为本文明确审计的例外：不得接入配置、
  CLI、wire schema 或任何生产构造路径，并须有静态检查/架构回归证明只被测试设施选择。
- 与 V8 本地 canary、测试入口和本计划直接相关的配置、文档与 agent log。
- external migration 的纯推导测试与 OAuth CLI 的 `--no-open-browser` 显式入口。

### 不允许修改

- 产品 SSRF、本地/私网地址、DNS rebinding、防 MITM、safe-command、审批或 Landlock/seccomp 策略。
- Clash、DNS、NO_PROXY、宿主代理、`/tmp` marker、真实 home、WSL interop、系统服务或全局工具链。
- `codex-source-code/`、真实 API/模型、远端仓库、发布/上传流程。
- 通过 `#[ignore]`、skip、删断言、任意非零即成功、降低事件量或单纯延长超时凑绿。
- 新建测试框架、重型测试 crate、常驻服务或本文未明确审计的公共 API。

### 不允许读取/查看

- 项目外个人文件、凭据、真实会话或无关仓库。测试代码不得直接打开、查看或记录用户 shell profile；§8仅通过
  产品既有login-shell执行路径观察最终两个环境变量值。

## 3. 硬约束

1. 实施前确认本工作树看门狗 F2/F7 已通过轻量回归和至少一轮真实 `just test` JUnit 归属 smoke；看门狗
   不可靠时不得启动本计划的 Cargo 门禁。
2. 每族先用最小定向命令复现或取证。若历史失败在定向环境不复现，记录该事实，再以受控污染/注入验证合同；
   不得把未复现写成已修复。
3. 正式验证保持 Clash/TUN 与代理变量存在。允许测试自己的 Direct client、fixture resolver、`wget --no-proxy`
   来表达确定性合同；不允许在外层 `unset` 环境后把结果当正式证据。
4. 本计划新建/修改并计入对应族验收的测试，其真实网络路径一律替换为本地服务、fake collaborator 或纯函数
   合同；live smoke 必须另列且默认不跑。第9.2节点名的未修改legacy测试是范围例外，不得作为新合同证据。
5. 所有新 seam 必须有“生产默认仍走旧实现”的回归。测试专用入口优先 `#[cfg(test)] pub(crate)` 或私有 helper。
6. 任何一项最终为产品缺陷时，保留红色强断言并另立产品任务；不能在测试侧掩盖。
7. 原始失败输出、定向结果、JUnit 路径/SHA 和 watcher `summary.env` 写入该批 agent log。当前watchdog没有
   JUnit语义解析器；执行者须从 `summary.env` 的 `junit_path` 用只读XML解析单独汇总testcase实际执行数、failure
   与skip，并记录正式命令已固定 `--retries 0 --flaky-result fail`，不能只凭 `junit_status=retained` 判绿。
   skip/未运行单列且阻止阶段完成；测试体提前成功返回只能由I/K的代码修复、正对照和调用计数排除。
8. 下文所有 `just`/Cargo 门禁默认从 worktree 的 `mydev/codex-rs/` 执行；Python 仓库门禁从同一目录按
   明示相对路径运行。不得依赖执行者碰巧位于 `mydev/` 或主工作区。

## 4. 软性建议与条件决策

- A-G、J/K 中写明的 seam 和 helper 名称是依据当前 live code 给出的首选落点；满足同一硬约束、覆盖同一
  组合链路且 API 面更窄的等价实现可以采用，并在关键决策记录中说明。
- H/I 先只做诊断性测试改动。取证结论落在既有允许修改范围且不改变完成标准时，可记录决策后继续；若指向
  产品缺陷、新公共协议或范围扩张，暂停该族并请求用户确认，不能为了维持“39项修完”口径改弱测试。
- 压力次数是验收强度，不是每次编辑后的默认回归。修改中先跑单次精确测试，候选修法稳定后再执行计划规定的
  修改后双200；修改前双200只执行一次并保留原始证据。
- Direct policy 若无法在不扩大生产能力面的前提下安全落地，优先改用消费者已有 selector/factory/probe seam；
  不因测试便利把“绕过代理”暴露为用户可配置能力。

## 5. 集合与实施总览

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

## 6. A族：确定性 DNS（21项）

### 6.1 精确集合

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

### 6.2 产品 seam

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

### 6.3 安全回归与 core 项

- DNS错误、DNS timeout、显式 `10.0.0.1` 仍必须得到 `NotAllowedLocal`。
- `does-not-resolve.invalid` 用错误 resolver，不依赖宿主DNS。
- 不设置 `allow_local_binding=true` 绕过纵深检查。
- core decider 项不验证域名语义，目标与 Host 可改为公网IP字面量 `8.8.8.8`；继续断言HTTP 403、
  `blocked-by-allowlist`、decider恰调用一次、原因是 `not_allowed` 而非 `not_allowed_local`。

### 6.4 门禁

```text
just test -p codex-network-proxy --retries 0 --flaky-result fail -E 'test(/host_blocked/) or test(/http_connect_accept/) or test(/mitm_policy/) or test(/evaluate_host_policy/) or test(/handle_socks5_tcp/)'
just test -p codex-network-proxy --retries 0 --flaky-result fail
just test -p codex-core --retries 0 --flaky-result fail -E 'test(/managed_network_proxy_decider_survives_full_access_start/)'
```

## 7. B族：确定性直连 HTTP（5项）

### 7.1 精确集合

1. `codex-http-client::without_url_redacts_transport_error_urls`
2. `codex-api::upload_openai_file_reports_blob_transport_diagnostics_without_sas`
3. `codex-cli::mcp_check_warns_for_optional_http_reachability`
4. `codex-core-plugins::search_remote_plugins_redacts_sensitive_parameters_from_transport_errors`
5. `codex-exec-server::delegated_http_failure_warning_redacts_request_url`

### 7.2 共用 Direct policy

给既有 `OutboundProxyPolicy` 增 `#[doc(hidden)] Direct`，作为跨 crate 测试确实需要的 workspace-visible 例外，
不把它表述成新的产品代理模式：

- 同步/异步 route resolver 直接返回 `OutboundProxyRoute::Direct`，不读取代理环境或 `NO_PROXY`，也不调用DNS resolver。
- client builder 必须落到既有 `.no_proxy()`；redirect继续直连。
- Direct不得退回 `ReqwestDefault` 的 transport-default/custom-CA 分支。
- 配置解析、CLI、app-server/wire schema 和生产 factory 选择不得产生 Direct；补回归钉住现有配置只能映射到
  `ReqwestDefault`/`RespectSystemProxy`，并在交付时审查 Direct 的选择调用点只位于测试/测试支持代码。
- 生产默认和所有现有构造仍用原策略。更新 `route_aware_client_pool.rs`、
  `core-plugins/startup_sync/http_client.rs`、相关测试和 `ollama/src/client.rs` 的穷举匹配。
- 用有毒 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY` 的 `MapEnv` 加单测，resolver设为panic，证明Direct不读它们。

### 7.3 各项落点

- #1 直接用 `reqwest::Client::builder().no_proxy().build()`，保留关闭端口和URL脱敏断言。
- #2 已有 `RouteAwareClientPool` 参数，测试传 Direct pool；保留 `failed after`、connect分类、Azure request ID、
  SAS不泄漏。
- #3 抽 `mcp_check_from_servers_with_probe`，生产wrapper仍调真实probe；测试注入确定的connect失败，保留Warning、
  optional issue与失败详情。既有本地listener probe也显式Direct。
- #4 已有 `RemotePluginServiceConfig.http_clients: Arc<dyn HttpClientSelector>`，给测试selector传Direct；保留
  accept后drop的中途transport错误和敏感参数脱敏。listener accept需有界等待。
- #5 已有 `HttpClientFactory` 注入，传Direct factory；继续要求请求失败、`error_is_connect=true`、path/query不泄漏。

### 7.4 门禁

```text
just test -p codex-http-client --retries 0 --flaky-result fail -E 'test(/without_url_redacts_transport_error_urls/) or test(/direct/)'
just test -p codex-api --retries 0 --flaky-result fail -E 'test(/upload_openai_file_reports_blob_transport_diagnostics_without_sas/)'
just test -p codex-cli --retries 0 --flaky-result fail -E 'test(/mcp_check_warns_for_optional_http_reachability/)'
just test -p codex-core-plugins --retries 0 --flaky-result fail -E 'test(/search_remote_plugins_redacts_sensitive_parameters_from_transport_errors/)'
just test -p codex-exec-server --retries 0 --flaky-result fail -E 'test(/delegated_http_failure_warning_redacts_request_url/)'
```

## 8. C族：登录 shell 的 managed proxy 合同（1项）

测试 `user_shell_commands_do_not_inherit_managed_network_proxy` 只承诺移除当前session的managed proxy；login
shell允许用户profile重新设置自己的代理。历史输出 `127.0.0.1:7897` 是宿主Clash，不是本session的随机代理。

最终断言：

- 从 `turn_context.network.apply_to_env` 取出本session managed `HTTP_PROXY`。
- shell同时输出 `HTTP_PROXY` 与 `CODEX_NETWORK_PROXY_ACTIVE`。
- active marker不存在，最终HTTP_PROXY不等于本session managed URL；允许是用户代理或 `not-set`。
- 测试代码不读取、修改、记录或隔离用户profile；产品既有login-shell执行仍可能加载它。该具名例外只观察最终
  两个环境变量并钉准原产品合同，不是一般hermetic fixture，也不是降低安全断言。

门禁：

```text
just test -p codex-core --retries 0 --flaky-result fail -E 'test(/user_shell_commands_do_not_inherit_managed_network_proxy/)'
```

## 9. D族：Landlock wget TCP connect（1项）

### 9.1 已证事实

- 上游原始日志两次均为 `Sandbox(Timeout)`、exit 124、约10.003秒，panic在“expected sandbox denied error”分支；
  不是 `exit_code == 0` 的沙箱击穿。
- 源码 `NETWORK_TIMEOUT_MS=10_000`；“2-second timeout”注释过时。
- stdout/stderr为空由 `wget -q` 可完全解释，不能推断wget内部状态。
- RONDO较早一轮该项0.040秒通过；最新严格轮缺原始stderr，因此不是稳定必现。
- seccomp无条件拒绝 `connect`，且 `socket(AF_INET)` 也被拒；回环与公网不走不同规则面。
- “代理导致超时”尚未证明。可能是wget对EPERM的重试，也可能是其他fixture时序。

### 9.2 先诊断、再固定合同

先在看门狗内单跑一次诊断：去掉 `-q` 或加 `-d`，显式 `--tries=1`，记录完整 `SandboxErr`、duration和
wget stderr。只有日志能决定历史10秒的内部机制；最终方案不依赖该归因。

最终测试改名为 `sandbox_blocks_wget_tcp_connect`：

该测试不得复用或修改 `landlock.rs::assert_network_blocked`，而应使用仅服务于本用例的窄helper/内联fixture。现有
shared helper把“任意非零”和“缺binary”都当作网络阻断，并由多项legacy测试共用；在其中收紧会把本次单项修复
扩张为未取证的批量合同变更。

1. 起受控loopback HTTP listener。
2. 同一个wget binary先跑未沙箱控制轮，使用 `--no-proxy --tries=1` 和局部短连接/读取超时；必须成功且
   listener收到恰好一个请求。控制轮失败不是skip，而是fixture失败。
3. 沙箱轮访问同一listener、同样单次尝试；要求快速返回明确 `SandboxErr::Denied`（或经源码证明等价的
   seccomp EPERM分类），listener不得收到第二个请求。
4. Timeout、binary缺失、DNS失败、connection refused、任意非零均不得被当作沙箱通过。

此方案理由是 hermetic 且断言更强，不写成“修复了已证实的代理污染”。

本阶段明确不修改 `assert_network_blocked` 及其另外6个现有调用者：`sandbox_blocks_curl`、
`sandbox_blocks_ping`、`sandbox_blocks_nc`、`sandbox_blocks_ssh`、`sandbox_blocks_getent`、
`sandbox_blocks_dev_tcp_redirection`。它们的真实域名/地址与宽松非零合同是具名legacy例外，不计入D族完成证据；
最终workspace仍会运行它们，任何失败仍按全量失败处理，不能skip或从全量过滤掉。后续若要hermetic化这些合同，
应作为独立范围取证后处理。

门禁：

```text
just test -p codex-linux-sandbox --retries 0 --flaky-result fail -E 'test(/sandbox_blocks_wget_tcp_connect/)'
```

## 10. E族：fixture边界内的项目根发现（6项）

1. `codex_home_is_not_loaded_as_project_layer_from_home_dir`：在home创建唯一非空marker，user config配置该marker；
   真实发现home为根后，再证明同一 `home/.codex` 不会作为Project层加载。
2. `project_layers_disabled_when_untrusted_or_unknown`：在project root创建唯一非空marker，untrusted与unknown
   两条配置均显式传入；保留nested cwd、trust entry和Project层被禁用的原语义。
3. `resolve_root_git_project_for_trust_returns_none_outside_repo`：复用现有FS参数，测试装饰器对fixture root外
   `get_metadata` 返回NotFound，其余转发 `LOCAL_FS`；不造畸形 `.git`。
4. `workspace_section_requires_meaningful_structure`：抽私有
   `build_workspace_section_with_user_root_with_fs`，生产传 `LOCAL_FS`，测试传fixture-bounded FS；不把None契约改为空结构。
5. `recent_work_section_groups_threads_by_cwd`：同样抽 `build_recent_work_section_with_fs`，并把同一 FS 继续传入
   `format_thread_group`，替换分组、current group 与 group label 三处 `LOCAL_FS`；不把两个目录改成两个repo。
6. `environment_id_fallback_has_cwd_prefix`：抽纯函数
   `environment_id_from_cwd_with_repo_root(cwd, Option<PathBuf>)`，public wrapper传真实结果；fallback传None，并补
   Some(repo_root)控制用例。

空 `project_root_markers=[]` 会直接短路根发现，不能用于 #1/#2。验证时保持 `/tmp/.git/.codex/.agents` 存在。

```text
just test -p codex-core --retries 0 --flaky-result fail -E 'test(/codex_home_is_not_loaded_as_project_layer_from_home_dir/) or test(/project_layers_disabled_when_untrusted_or_unknown/) or test(/resolve_root_git_project_for_trust_returns_none_outside_repo/) or test(/workspace_section_requires_meaningful_structure/) or test(/recent_work_section_groups_threads_by_cwd/)'
just test -p codex-secrets --retries 0 --flaky-result fail -E 'test(/environment_id_/)'
```

## 11. F族：PowerShell目标平台（1项）

在 `commands_generated_by_shell_command_handler_can_be_matched_by_is_known_safe_command` 中：

- 两个PowerShell finder import和两段PowerShell/Pwsh断言均用编译期 `#[cfg(windows)]`。
- Bash/Zsh断言所有平台继续运行；既有非Windows拒绝PowerShell分类的安全测试保留。
- 不使用运行时 `cfg!(windows)` 留下无用import/lint，也不在Linux开启Windows safelist。

```text
just test -p codex-core --retries 0 --flaky-result fail -E 'test(/commands_generated_by_shell_command_handler_can_be_matched_by_is_known_safe_command/)'
```

Windows平台同名测试属于平台验收；本地WSL通过不能代替Windows未运行事实。

## 12. G族：V8 feature unification（1项）

将单条错误等价断言拆为两层：

1. 全workspace始终执行兼容性蕴含：

   ```rust
   assert!(!cfg!(feature = "sandbox") || linked_v8_has_sandbox());
   ```

   声明本crate sandbox时，链接库必须具备sandbox；但workspace feature unification可能让依赖启用sandbox而本crate的
   `cfg!(feature = "sandbox")` 仍为false，所以这条只能证明单向兼容性，不能当作双向canary。
2. 不新增仅为测试期望服务的Cargo feature，避免违反workspace manifest白名单，也避免把测试控制面伪装成产品feature。
   既有测试仅在显式设置 `RONDO_V8_CANARY_EXPECT_SANDBOX` 时解析严格的 `0`/`1` 期望并断言
   `linked_v8_has_sandbox()`；非法值必须失败，未设置时只执行上面的兼容性蕴含。该环境变量只属于下面两条独占
   canary命令，不进入产品配置。
3. 两条独占canary必须成对：default=false负责抓恒true、stub或链错库，sandbox=true负责抓feature未传递。

本项目不依赖远端CI作为交付证据；沿用现有V8资产准备方式，在本地看门狗内分别运行独占default、独占sandbox
与workspace包含该测试的三种门禁。任何模式资产不可用都记未运行/阶段未完成，不能把全量断言改成skip。

```text
RONDO_V8_CANARY_EXPECT_SANDBOX=0 just test -p codex-v8-poc --no-default-features --retries 0 --flaky-result fail -E 'test(/sandbox_feature_matches_linked_v8/)'
RONDO_V8_CANARY_EXPECT_SANDBOX=1 just test -p codex-v8-poc --no-default-features --features sandbox --retries 0 --flaky-result fail -E 'test(/sandbox_feature_matches_linked_v8/)'
python3 ../.github/scripts/verify_cargo_workspace_manifests.py
# 全部族完成后的唯一一次workspace门禁中必须实际执行codex-v8-poc的单向兼容性测试。
```

## 13. H族：两项时序测试（2项）

### 13.1 共用取证协议

每项在改代码前后分别运行：

```text
just test -p codex-core --test-threads 1 --stress-count 200 --retries 0 --flaky-result fail -E 'test(<exact-name>)'
just test -p codex-core --test-threads 10 --stress-count 200 --retries 0 --flaky-result fail -E 'test(<exact-name>)'
```

确认JUnit确实记录200次实际执行，分别给出失败次数/phase。单线程0/200不能推翻只在并发负载出现的问题；
10线程0/200也只能作为定向证据，最终仍需一次workspace默认10线程门禁。不得只增2秒/5秒timeout。
本机Nextest 0.9.140实测 `--stress-count` 中有失败迭代时仍可能以0退出，且单个精确匹配测试每个stress iteration
仍只运行1项，`--test-threads 10`只是调度上限、不是10份并行副本。因此修改前/后压力结果一律以JUnit的200个
testcase及failure/error/skip语义判定；10线程命令保留作与历史配置一致的定向证据，但不夸称为10份并发复现。

`<exact-name>` 分别替换为：

- `conversation_close_routes_only_remaining_transcript_tail_once`
- `exec_command_consumes_pushed_remote_process_events::truncated_event_replay`

### 13.2 realtime close

目标：`conversation_close_routes_only_remaining_transcript_tail_once`。

- 给既有 `ResponseMock` 增 `request_log_updated: Arc<Notify>` 与 `wait_for_request_count(count)`；在请求日志push后notify。
- 诊断证明旧fixture的 `start_websocket_server` 默认 `close_after_requests=true`：脚本消费完后先产生
  `transport_closed`，tail被steer进尚未收尾的初始handoff turn，两个Responses POST只共享一个最终
  `TurnComplete`。因此旧测试并未真正证明“显式Close只flush一次tail”，也不存在可等待的
  第二个terminal event。
- 最终fixture改用 `start_websocket_server_with_headers` 且 `close_after_requests=false`，保持realtime
  transport存活到第一次显式Close。Responses侧改用既有 `StreamingSseServer`：初始handoff消费完
  首个响应并进入thread-idle后才Close；第二个POST到达后释放tail响应gate，同时等待server
  completion、tail `TurnComplete` 和第亊thread-idle，再发第二次Close。
- 两次Close都按submit返回的conversation id精确匹配对应 `RealtimeConversationClosed`；第二次closed只作为
  submission queue barrier，不能单独当作后台turn已静止的证明。
- 最后用 `StreamingSseServer::requests()` 核对真实POST body数恰好为2并重新断言两次输入语义，替换
  固定200ms sleep；`ResponseMock` 的 `up_to_n_times(2)`/内部日志长度不能单独排除未匹配的第3个请求。
- 不改产品close语义；若Notify后仍出现第三请求，按产品缺陷处理。

### 13.3 truncated replay

目标：`exec_command_consumes_pushed_remote_process_events::truncated_event_replay`。

- 保留1024通知，不能降低超过256 replay/queue容量的压力。
- fake server记录：已发output数、exited/start response/closed是否发送、`process/read`次数、terminate是否收到、
  Responses第二请求是否到达。
- 所有5秒等待在失败时输出phase，而不是裸 `expect`。
- 修改后单线程200次首轮证据为199通过/1失败；失败在 `waiting_for_process_start`，
  `output_events_sent=0`、`start_response_sent=false`、Responses POST=0、无 `ExecCommandBegin`。因此
  1024事件/replay路径未参与，不得把这次失败归因于terminal event丢失。
- 宿主同时设置了大小写HTTP/HTTPS/ALL proxy且大小写NO_PROXY均为空；该测试的loopback
  Responses请求会被环境代理影响。仅对truncated点名case采用仓库既有的exact-test子进程模式，
  在子进程环境中移除 `PROXY_ENV_KEYS`；父进程等待子进程成功并保留完整stdout/stderr失败上下文。
  这不改产品代理策略，也不降低1024事件或增加timeout。

## 14. I族：exec-server empty workspace roots（1项）

目标：`remote_process_preserves_empty_workspace_roots`。把 `Arc<dyn ExecProcess>` 的clone交给现有collector，测试本身
保留session；collector每收到一条事件都更新latest seq。超时时测试立即执行
`session.read(latest_seq, None, Some(0))`，记录 `chunks/next_seq/exited/exit_code/closed/failure/sandbox_denied`，并记录
harness与child存活状态。当前collector会消费session且忽略seq，实施时必须先补这两个诊断能力，不能写一条实际上
无法执行的timeout分支：

- read已terminal：push/replay交付问题；
- read仍running且无事件：sandbox helper/process卡住；
- read返回failure：拒绝走错误通道传播。

只有证明read稳定terminal且仓库已有独立pushed-event生命周期覆盖时，才可让本测试改用read collector；否则保留
pushed collector并修复已定位的交付问题。

实施取证表明旧event collector的修改前200次为3通过/197次无状态timeout；专用诊断进一步区分出：缺少与既有
remote helper相同的 `:minimal` 与 `PATH` 前提时正对照仍running，补齐后event collector可出现closed却漏stdout，
而同session的read collector能完整取得terminal输出。仓库独立的remote pushed与close后replay两条生命周期门禁均
通过。因此本用例最终采用专用read collector；正反对照仍保留session与latest seq，并在超时立即输出terminal read与
exec-server child状态，不把read替代误称为本用例的pushed-event覆盖。

验收必须使用同一remote backend、helper、命令和cwd做成对控制：

- 正对照把临时根显式放入workspace roots，要求stdout包含 `excluded`、exit 0、terminal closed且无failure；
- 负用例保持workspace roots为空，要求stdout不含 `excluded`、empty roots不补默认根、terminal closed，并得到明确
  sandbox denial，或得到已由源码和断言精确分类为文件访问被拒的exit/stderr；
- 任意非零退出、helper启动失败、动态加载器失败、命令缺失、timeout或harness提前退出都不能算负用例通过；
- bwrap或所需helper不可用时，本阶段记未运行/未完成，不允许 `return Ok(())` 静默变绿。

```text
just test -p codex-exec-server --stress-count 200 --retries 0 --flaky-result fail -E 'test(/remote_process_preserves_empty_workspace_roots/)'
```

## 15. J/K附加设施事项

### 15.1 external migration：去真实GitHub

当前external层没有local cloner seam；core-plugins中的cloner helper是私有同步测试入口。最低成本收口：

- 在external内部加私有 `import_plugins_with_marketplace_adder` closure（或等价的私有窄协作者），生产wrapper仍调用真实
  marketplace add，不扩成公共cloner框架。
- 必须原位改造 `marketplaces.rs` 中现有
  `import_plugins_infers_external_official_marketplace_when_missing_from_settings`，而不是在它仍会真实clone的情况下
  另加一条测试。改造后将其重命名为
  `import_plugins_infers_external_official_marketplace_with_fake_adder`：仍从“settings中只有已启用的官方插件、没有
  显式source”开始，调用真实import编排到fake adder；fake必须记录并断言source精确为
  `anthropics/claude-plugins-official`、ref为None、sparse paths为空，然后返回包含本地marketplace/plugin manifest的
  installed root。继续断言import outcome、错误传播与配置结果，证明“源推导→添加→安装/配置”没有断链。
- 增加纯测试 `marketplace_import_sources_infers_external_official_marketplace`，与既有
  `import_plugins_supports_relative_external_agent_plugin_marketplace_path` 一起作为补充合同；二者不能替代上述改造后的
  组合测试。
- 测试期间不得发生GitHub DNS/connect或git子进程；组合测试直接调用注入fake的私有编排helper，断言fake恰调用一次，
  且不触达生产 `add_marketplace` wrapper，以调用路径机械证明而不是凭运行速度推断。

生产git缺timeout/cancel/后代清理是真实产品缺陷，另立任务并用本地挂起+派生后代wrapper验证；测试hermetic修复
不能宣称该产品缺陷闭环。

定向门禁必须覆盖纯source推导、显式本地marketplace和上述组合测试。

### 15.2 OAuth：显式禁止打开浏览器

给 `mcp login` 增 `--no-open-browser`，底层flow接收显式 `launch_browser`；false时仍打印authorization URL、等待
callback、换取并持久化token；初次授权和“去掉scopes后重试”两条路径都必须透传该值。

签名变更后逐一处理所有生产调用点：`cli/src/mcp_cmd.rs` 的首次与去scopes重试都传
`!no_open_browser`；`core/src/mcp_skill_dependencies.rs` 的首次与去scopes重试、以及既有silent wrapper均显式传true，
保持turn期依赖登录和其他非CLI入口仍会按原行为尝试打开浏览器。不得因新增CLI flag顺手把core调用改成false。

把 `webbrowser::open` 隔在私有可注入launcher/callback后，生产默认保持现行为。单元测试用计数fake机械证明false为
0次调用、true/default为1次；测试分别命名为
`oauth_login_does_not_invoke_browser_launcher_when_disabled` 与
`oauth_login_invokes_browser_launcher_once_when_enabled`。CLI解析/透传测试命名为
`mcp_login_no_open_browser_propagates_launch_false`，证明 `--no-open-browser` 最终得到false。
`login_and_logout_persist_only_cloud_managed_mcp_oauth_credentials` 使用该flag，现有authorization URL、callback、token
持久化与logout断言全部保留。只设 `BROWSER` 不是跨平台合同，Windows实现可能不尊重它。

`CloudManagedMcpFixture::new()` 的OAuth隔离失败不得再以 `Ok(None)` 配合测试中的 `return Ok(())` 静默通过：改成
显式preflight或 `Result<Self>`，不可用时让该阶段失败/记未运行。缺依赖、端口或隔离能力都不是功能通过证据。

```text
just test -p codex-external-agent-migration --retries 0 --flaky-result fail -E 'test(/marketplace_import_sources_infers_external_official_marketplace$/) or test(/import_plugins_supports_relative_external_agent_plugin_marketplace_path$/) or test(/import_plugins_infers_external_official_marketplace_with_fake_adder$/)'
just test -p codex-rmcp-client --retries 0 --flaky-result fail -E 'test(/oauth_login_does_not_invoke_browser_launcher_when_disabled$/) or test(/oauth_login_invokes_browser_launcher_once_when_enabled$/)'
just test -p codex-cli --retries 0 --flaky-result fail -E 'test(/mcp_login_no_open_browser_propagates_launch_false$/) or test(/login_and_logout_persist_only_cloud_managed_mcp_oauth_credentials$/)'
```

## 16. 串并行实施顺序

代码审查可按独立族并行；所有重型测试严格串行：

1. 前置：看门狗真实 `just test`/clippy smoke，确认JUnit `retained` 与非nextest `not_applicable`。
2. 批次A：resolver seam + 20 network-proxy + core decider。
3. 批次B/C：Direct policy与5项消费者；随后shell合同。
4. 批次E/F：fixture-bounded roots与PowerShell平台收口。
5. 批次D/G：Landlock诊断后用独立wget helper落强合同，不动shared legacy helper；V8既有feature的独占双canary与
   workspace单向兼容性。
6. 批次H/I：H严格执行修改前后各单线程/10线程双200取证；I按第14节明确的一条默认线程200次门禁取证并用
   timeout read分流。二者都在第4节条件决策点确认仍属测试设施修复后再实施，改后以各自同负载复验。
7. 附加J/K：原位改造点名的真clone测试为fake-adder组合链路；`--no-open-browser`及launcher零调用证明，core
   两处生产登录路径保持显式true。
8. 每批跑相关包；全部通过后执行一次完整workspace
   `just test --retries 0 --flaky-result fail`；先核对watchdog summary中的JUnit路径/哈希，再以独立只读XML解析核对
   实际执行数、failure与skip，并记录正式命令禁重试；
   受影响Cargo manifest另跑 `python3 ../.github/scripts/verify_cargo_workspace_manifests.py`，最后运行受影响包clippy/fmt，
   不重复全量。

实施时以前5批完成后严格待定只剩H的2项与I的1项（39→3）作为机械对账点；附加J/K始终不计入严格失败。
实际实施结果与机器JUnit见第17节，不能靠算术改口径。

## 17. 当前状态

### 已完成

- 核对81项严格清单与第一批42项覆盖，冻结39+2口径。
- 证实Clash fake-IP、ambient proxy和 `/tmp` marker是环境事实；没有修改宿主。
- 证实Landlock历史失败是10秒 `Sandbox(Timeout)`，不是沙箱击穿；代理归因撤回。
- 证实回环/公网走同一seccomp拒绝面；本地listener合同成立。
- 证实原V8断言受feature unification影响；确定workspace单向兼容性+既有feature的独占双向canary。
- 核对各现有seam：NetworkProxyState手写Clone/Debug、HTTP factory/selector/pool、realtime缺FS参数、
  external无公开cloner、OAuth硬编码开浏览器。
- 已从本地 `main@37b0e66` 创建实施工作树 `.claude/worktrees/0809-remaining-test-failures` 与分支
  `0809-remaining-test-failures`；主工作区未修改。
- watchdog轻量回归9/9通过；宿主cgroup smoke返回0。真实Nextest/JUnit归属smoke实际执行1/1、failure/error/skip
  均为0，`junit_status=retained` 且summary SHA与重算一致，资源与清理stop reason均为none。
- A-F与J/K代码均已完成定向编译/门禁；A的network-proxy定向40/40、整包205/205与core decider 1/1均通过，
  B/C共24项定向通过，D 1/1、E 6/6、F 1/1、J 3/3、K 4/4均通过，全部禁重试且flaky视为失败。
  对应watchdog run依次包括 `20260809-191628-1000-800809`、`191709-1000-807694`、
  `191719-1000-808585`、`191735-1000-809139`、`191808-1000-814542`、`191900-1000-821764`、
  `192411-1000-875452`、`192437-1000-877154`、
  `192500-1000-877913`、`192759-1000-899499`、`192832-1000-900662`、`192844-1000-901190`、
  `192935-1000-908765`、`193058-1000-913811`、`193119-1000-915651`、`193245-1000-933424`。
- B族首轮core-plugins门禁在编译期发现测试缺少 `Arc`/`Duration` 导入，补齐后同门禁1/1通过；D族首轮明确失败
  为wget exit 4但 `-q` 抑制了EPERM诊断，移除quiet后现有分类器得到明确sandbox denial且listener仍证明没有第二个连接。
- G族default=false独占canary 1/1通过（run `20260809-192947-1000-909276`）；sandbox=true在编译测试前因
  rusty_v8没有发布 `librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz` 而HTTP 404，run
  `20260809-193011-1000-912361` 记为资产缺失/未运行，不能计通过。manifest校验同时发现并移除已无对应feature的
  `code-mode` stale exception，随后脚本通过。
- H修改前四组压力取证完成：realtime单线程200/200通过、10线程配置199/200通过且1次事件等待超时；truncated
  replay两组均197/200通过、各3次失败，覆盖模型请求前0 POST与首请求后未完成两种phase。四组均为0 skip，原始
  JUnit分别保存在watchdog run `20260809-180749-1000-445342`、`181248-1000-497867`、
  `181533-1000-522598`、`181756-1000-540888`。
- I修改前200次为3通过/197次timeout、0 skip；诊断确认旧event collector不可观测，补齐正对照的最小运行时读取与
  PATH后，专用read collector单次正反对照通过，且两条独立remote pushed/replay生命周期门禁2/2通过。
- I修改后正式200次压力门禁200/200通过，failure/error/skip均为0；原始JUnit保存于watchdog
  run `20260809-183819-1000-632851`，summary SHA-256为
  `7cf2b5f37327e43fcddc40327208275f837c036d8014f1de11f1e675df592a28`。
- H修改后轨迹定位到fixture的真实合同错位：第二次POST的tail被steer进初始turn，事件流显示
  `transport_closed`早于tail user message，而两次POST只有一个最终terminal。当前已切换到显式保持WebSocket存活和
  gated SSE的fixture；单项和修改后1/10线程配置各200次压力门禁均200/200通过。
- H truncated修改后首轮单线程压力门禁199/200通过；唯一失败是0 Responses POST的模型请求前阶段，
  无任何pushed/replay事件。依决策023改为proxy-free exact-test子进程后，1/10线程配置各200次
  压力门禁均200/200通过。
- H修改后四份JUnit均为200 testcase，failure/error/skip均为0；realtime 1/10线程run为
  `20260809-190338-1000-695860` / `20260809-190508-1000-720055`，SHA-256为
  `e2538b998c2b9e1015cf1ac36e06871a24527da187f151569f2c18e0d40372c4` /
  `c0f994937d3fd3680f1876312c610ec591dd54a7a456fc802a07dad9d73f3881`；truncated 1/10线程run为
  `20260809-191127-1000-763175` / `20260809-191322-1000-781597`，SHA-256为
  `f00da40dd0b41c78d2ddb07392af53760ba8a6f66ffccccbd72c7f6ced4f2d30` /
  `e160f5dd15806bcaa8e17179bd6352b6e7d4cfe3a834cec3274329153430ffdd`。
- 统一 `just fmt`/`fmt-check` 通过；受影响crate的 `just fix` 与严格 `just clippy` 均通过，watchdog run分别为
  `20260809-193437-1000-936925` 与 `20260809-193855-1000-971128`，二者stop/cleanup均为none且JUnit状态正确为
  `not_applicable`。clippy自动调整H的一处等价布尔表达式后，两条H最终文件具名回归2/2通过，run
  `20260809-194348-1000-1014436`，独立解析failure/error/skip均为0。提交前语义审查再补“子进程必须输出完整
  exact test名与1 passed”防零匹配假绿，最终truncated回归1/1通过（run `20260809-195026-1000-1037637`）。
- 计划规定的唯一一次workspace全量已执行，run `20260809-194124-1000-981676` 在测试启动前构建V8 sandbox
  组合时遇到同一官方资产HTTP 404而exit 101；summary为 `junit_status=absent`、stop/cleanup均为none，因此没有
  workspace testcase结果，未过滤V8重跑或宣称全量通过。
- 独立只读XML复核了I/H压力、A-F/G-default/J/K、H最终回归及提交前审查回归共26份JUnit：每份实际testcase与命令匹配，
  failure/error/skip均为0，文件SHA与watchdog summary一致。
- 提交前独立差异审查发现并处理4项：H目标测试的禁网静默成功改为显式失败；I新增import/struct/helper恢复
  `cfg(unix)`以保留macOS Seatbelt覆盖；三处失败HTTP fixture改为保持端口占用的非监听socket；C族文档明确为
  刻意观察真实login-shell结果的具名例外。审查前另发现的Landlock control `accept` 已改为2秒deadline。
- Landlock有界accept修订与I族Linux路径的中间回归2/2通过（run `20260809-195141-1000-1041018`，JUnit SHA-256
  `07fb3110ba7672530c0d161a5dad4f027c31920569f88e07f10bd9ee42f0851a`）；最终B/D/H/I联合回归6/6通过
  （run `20260809-195832-1000-1068951`，JUnit SHA-256
  `de9ae140ceb458613ea8b17b170f6e6b2380ceb3836074e59b054603ec42a7ef`）。两份均为0 failure/error/skip，
  summary的stop/cleanup均为none。
- 审查后严格clippy首轮（run `20260809-200154-1000-1088950`）发现truncated子进程失败上下文仍使用旧式
  format参数，在测试执行前exit 101；改为inline format args后原样重跑通过（run
  `20260809-200429-1000-1103492`），stop/cleanup均为none。最终fmt-check、manifest校验与diff-check也通过。
- H禁网fail-closed负对照显式设置 `CODEX_SANDBOX_NETWORK_DISABLED=1` 后同一exact test按预期失败（run
  `20260809-200731-1000-1108959`）：JUnit为1 testcase、1 failure、0 error/skip，SHA-256为
  `7ecb8037a47d9ae4931344ed47ca6c41ac7d4bb006eac3823842a0ed10dec152`。该诊断不计入绿色验收，机械证明不再
  由提前成功返回形成passed假绿。
- 独立验收发现并闭环D的宽分类假绿、H的请求计数假绿、K的浏览器禁用透传覆盖缺口与G的非Unicode环境值边界。
  整改树定向门禁合计409 testcase，0 failure/error/skip；其中H两组压力各200/200，五个受影响crate另以
  `-- -D warnings` 通过严格clippy（run `20260809-212921-1000-1487198`），统一fmt-check通过。
- 原实现提交 `216ccb7` 经合并提交 `06b2a0e` 进入主线；独立整改提交 `9570874` 经no-ff合并提交
  `8c185af` 进入主线并推送远端。完整独立验收、逐份JUnit哈希与交付核对见
  `agent_log/2026-08-09-203209-plan-004-independent-acceptance.md`。

### 当前工作

- 当前平台实现、独立整改、定向/压力/静态门禁、提交、主线合并与远端推送均已完成；当前没有待提交产品代码。

### 后续计划

- Windows环境可用时补PowerShell正向门禁；rusty_v8 sandbox资产前提恢复后成对补sandbox canary，再按本计划只运行
  一次完整workspace。已通过的当前平台定向门禁不作无意义重复运行。

### 阻塞项

- Windows PowerShell同名测试本机WSL无法提供目标平台证据，仍待Windows补验。
- G的sandbox=true canary因rusty_v8 v150.4.0对应官方预编译资产HTTP 404而未运行；不在本任务内自动扩大为
  `V8_FROM_SOURCE=1` 的重型源码构建；完整workspace也因此没有进入测试体。
- macOS Seatbelt入口已保留但未实机运行；这是必须披露的非阻断跨平台证据缺口，不是本计划WSL2完成门禁。

### 当前验收状态

- A-F/H-K当前平台定向/压力门禁、G default与manifest、独立整改回归、fmt/fix/clippy均已通过并交付；G sandbox与
  workspace全量被同一V8资产404阻断，Windows目标平台未运行。结论为部分通过，不能称41项跨平台/全量闭环。

## 18. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 使用39严格失败+2附加事项口径 | 第一批实际覆盖42；migration/OAuth不在严格失败清单 | 全计划 | 已采纳 |
| 002 | DNS用精确登记resolver，未知返回错误 | catch-all会破坏DNS失败安全回归 | A | 已采纳 |
| 003 | 增经审计的 `#[doc(hidden)] Direct，禁止配置/CLI/wire/生产路径构造并静态审查选择点 | 5项需确定性直连，但公开枚举variant不能被误当成私有测试能力 | B | 已采纳 |
| 004 | shell只排除本session managed proxy | login shell可合法重载用户profile | C | 已采纳 |
| 005 | wget使用独立本地listener helper，不改shared legacy helper | seccomp无地址分支；收紧共享helper会无取证扩张到另外6项 | D | 已采纳 |
| 006 | 项目根测试用非空marker或FS seam | 空marker直接禁用根发现，会弱化测试 | E | 已采纳 |
| 007 | PowerShell断言按编译目标平台收口 | WSL PATH不等于Windows分类目标 | F | 已采纳 |
| 008 | V8用workspace单向蕴含与既有feature独占双canary | workspace断言受unification影响；不新增违反manifest白名单的期望feature | G | 已采纳 |
| 009 | 时序修复前后都做1线程/10线程各200次 | 孤立通过不能覆盖workspace并发竞态 | H | 已采纳 |
| 010 | external产品git终止另立任务 | hermetic测试与产品子进程缺陷不能混称闭环 | J | 已采纳 |
| 011 | OAuth用CLI显式no-open-browser，core首次/重试保持true | BROWSER不是跨平台保证；CLI副作用修复不能改变turn期生产行为 | K | 已采纳 |
| 012 | 所有正式nextest门禁禁重试且flaky视为失败 | 仓库默认重试1次；仅看最终绿色会掩盖不稳定性 | 全计划 | 已采纳 |
| 013 | external原位改造点名的真clone测试为fake-adder组合测试 | 两个分拆测试不能证明真实编排没有断链；旧测试若并存仍会访问GitHub | J | 已采纳 |
| 014 | empty roots使用同backend的正反对照并精确分类拒绝 | 任意非零可能来自helper/加载器/命令失败，不等于隔离生效 | I | 已采纳 |
| 015 | OAuth用注入launcher计数且隔离失败不得静默通过 | CLI flag本身不能证明所有分支都未调用浏览器 | K | 已采纳 |
| 016 | watchdog retained只作JUnit完整性证据，语义另行解析 | 当前watchdog不统计failure/skip，passed也无法识别测试体提前返回 | 全计划 | 已采纳 |
| 017 | 6个shared Landlock helper调用者列为具名legacy例外 | 它们不在本次单个wget失败范围；全包门禁会混入真实域名与宽松合同 | D | 已采纳 |
| 018 | 在独立工作树按批次实施，exec plan与证据日志实时同步 | 保护主工作区，并确保H/I取证结论可恢复、可审查 | 全计划 | 已采纳 |
| 019 | H用close-id+最终TurnComplete+真实POST数屏障；I按§14单200而非双负载 | 第二次closed只屏障submission；§16旧文字与更具体的§13/§14及完成标准冲突 | H/I | 已采纳 |
| 020 | stress门禁以JUnit语义而非进程退出码判定，并如实限定10线程含义 | 本机复现1/200失败但Nextest退出0；精确单测试每轮只运行1项 | H/I | 已采纳 |
| 021 | I补齐`:minimal`/`PATH`同helper前提并改用专用read collector，pushed语义由既有两条remote门禁承担 | 修改前197/200无状态timeout；诊断见event closed漏stdout而read terminal完整，两条独立生命周期门禁2/2通过 | I | 已采纳 |
| 022 | H使WebSocket fixture保持存活到显式Close，并用gated SSE+TurnComplete+thread-idle屏障两个turn | 旧helper默认自动断开，tail被steer进初始turn，测试未实际覆盖显式Close且只会有一个terminal event | H | 已采纳 |
| 023 | truncated点名case在移除ambient proxy的exact-test子进程中运行 | 199/200轮的唯一失败为0 POST/0 exec event，与replay无关；宿主所有proxy已设且NO_PROXY为空 | H | 已采纳 |
| 024 | D最终wget命令保留stderr诊断，不使用quiet模式 | `-q`把seccomp EPERM抹成无输出exit 4，无法与任意非零区分；保留诊断后分类为明确Denied，listener未连接合同不变 | D | 已采纳 |
| 025 | 清理manifest校验器中已失效的code-mode feature例外 | code-mode已无feature而stale白名单令fail-closed校验自身失败；单行清理不改变产品manifest | G | 已采纳 |
| 026 | V8 sandbox预编译资产404记未运行，不自动源码构建 | ExecPlan要求资产缺失不得算通过；源码构建显著扩大资源与时长范围 | G | 已采纳 |
| 027 | 对 `OutboundProxyPolicy` 局部豁免manual_non_exhaustive lint | doc-hidden Direct是真实测试路由而非兼容哨兵；改用non_exhaustive不能替代跨crate可构造能力 | B | 已采纳 |
| 028 | workspace全量在V8资产404后不做过滤重跑 | 过滤V8就不再是方案要求的完整workspace；唯一尝试已给出明确absent JUnit构建阻断证据 | 全计划 | 已采纳 |
| 029 | truncated父测试校验子进程实际运行1个exact test | Rust测试二进制对零匹配也可能exit 0；仅检查子进程状态仍可能假绿 | H | 已采纳 |
| 030 | C族作为具名login-shell产品合同例外，不宣称fixture完全独立于profile执行 | 产品路径本就允许login shell加载profile；测试只观察最终env且不直接读取内容 | C | 已采纳 |
| 031 | Landlock control listener使用非阻塞accept与2秒deadline | 仅给accepted stream设read timeout无法约束accept本身，wget未连接时会卡在join | D | 已采纳 |
| 032 | empty-roots新增import/struct/helper均保持 `cfg(unix)` | 收窄为Linux会无声删除基线macOS Seatbelt覆盖；新增逻辑没有Linux专属API | I | 已采纳 |
| 033 | 三处失败HTTP fixture用保持绑定的非监听socket | bind后drop存在端口复用TOCTOU，可能偶发连到无关本地服务 | B | 已采纳 |
| 034 | H目标测试在禁网标记存在时显式失败 | `skip_if_no_network!`提前成功会被JUnit记为passed，200轮可整体假绿 | H | 已采纳 |
| 035 | 提交前严格clippy发现的inline-format lint原位机械修正并原样复验 | 保留完整子进程诊断，不以放宽lint或省略上下文换绿 | H | 已采纳 |
| 036 | D在同一沙箱命令用marker、精确endpoint和同一行connect/EPERM诊断证明拒绝来源 | 宽泛 `SandboxErr::Denied` 可把bwrap/userns或exec失败误算成网络隔离成功 | D | 已采纳 |
| 037 | H在终态后读取MockServer全局请求并断言真实POST总数恰为2 | sequence cap会让第三个请求绕过ResponseMock内部记录，形成计数假绿 | H | 已采纳 |
| 038 | K以CLI retry seam、rmcp finish launcher注入和cloud E2E组合证明Disabled贯穿首轮与去scopes重试 | 单测参数映射或launcher helper都不能独立证明完整链路 | K | 已采纳 |
| 039 | macOS未运行作为非阻断边界披露，Windows仍属原计划必需证据 | 目标环境与I族原失败为WSL2/Linux；F族本身是Windows合同 | F/I | 已采纳 |
