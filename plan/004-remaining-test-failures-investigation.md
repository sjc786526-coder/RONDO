# 39 个严格失败与 2 个附加设施事项最终修复计划

> 状态：最终实施方案，39 个严格失败尚未落地修复。
>
> 计数基线：最新严格全量记录有 81 个失败名；第一批实际覆盖 42 个失败名，因此当前待修集合机械推导为
> 39 个严格失败。external-agent migration 是更早一轮的偶发超时，OAuth 是始终通过但会打开宿主浏览器的
> 副作用，二者是附加事项，不能称为“剩余失败”。在下一次完整全量前，“39”只表示与严格清单对齐的待修
> 集合，不表示已经实跑出一轮“仅失败39项”的新结果。
>
> 本计划已吸收 GPT/Claude 的历次交叉核验与分歧裁决。A-G、J/K 可按已冻结合同实施；H/I 是带证据门的
> 条件批次，必须先完成修改前取证，再把分流结论写入“当前状态/关键决策记录”后实施范围内的最小修法。
> 若 live code 或取证结论要求改变目标、范围、硬约束或完成标准，必须暂停并请求用户确认；私有 helper 名称、
> 等价的更窄 seam 和本计划“软性建议”可随证据调整，但不能静默降低验收强度。

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
- V8 full-workspace 保留“声明 sandbox 则链接库必须具备 sandbox”的兼容性蕴含；default=false 与
  sandbox=true 两条带显式期望值的独占 canary 成对通过，不能把 workspace 中的真值短路称为双向证明。
- 两项时序测试交付修改前/后各两组 200 次数据（单线程与10线程），不靠扩大 timeout 收口。
- 每个修改批次只跑相关包门禁；全部批次完成后只跑一次完整 workspace 全量，所有 Cargo 重型任务均走
  `just`/`mydev/scripts/with-build-lock.sh`，一次一组。
- 所有正式定向和全量 Nextest 门禁统一使用 `--retries 0 --flaky-result fail`；允许另跑带重试的诊断，
  但其结果不能计入验收。JUnit 必须核对实际执行、failure/flaky/skip，而不只检查文件完整性和哈希。
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
7. 原始失败输出、定向结果、JUnit 路径/SHA 和 watcher `summary.env` 写入该批 agent log；必须解析并记录
   failure/flaky/skip/实际执行次数，不能只凭 `junit_status=retained` 判绿。skip/未运行单列且阻止阶段完成。
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
- 不读取、修改或隔离用户profile。这是钉准原产品合同，不是降低安全断言。

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

1. 起受控loopback HTTP listener。
2. 同一个wget binary先跑未沙箱控制轮，使用 `--no-proxy --tries=1` 和局部短连接/读取超时；必须成功且
   listener收到恰好一个请求。控制轮失败不是skip，而是fixture失败。
3. 沙箱轮访问同一listener、同样单次尝试；要求快速返回明确 `SandboxErr::Denied`（或经源码证明等价的
   seccomp EPERM分类），listener不得收到第二个请求。
4. Timeout、binary缺失、DNS失败、connection refused、任意非零均不得被当作沙箱通过。

此方案理由是 hermetic 且断言更强，不写成“修复了已证实的代理污染”。

门禁：

```text
just test -p codex-linux-sandbox --retries 0 --flaky-result fail -E 'test(/sandbox_blocks_wget_tcp_connect/)'
just test -p codex-linux-sandbox --retries 0 --flaky-result fail
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

`<exact-name>` 分别替换为：

- `conversation_close_routes_only_remaining_transcript_tail_once`
- `exec_command_consumes_pushed_remote_process_events::truncated_event_replay`

### 13.2 realtime close

目标：`conversation_close_routes_only_remaining_transcript_tail_once`。

- 给既有 `ResponseMock` 增 `request_log_updated: Arc<Notify>` 与 `wait_for_request_count(count)`；在请求日志push后notify。
- 首个 `RealtimeConversationClosed` 后等待request count=2，替换10ms/2s轮询。
- 第二次Close后等待第二个 `RealtimeConversationClosed` 作为submission queue barrier，再断言请求仍恰好2个，
  替换固定200ms sleep。
- 不改产品close语义；若Notify后仍出现第三请求，按产品缺陷处理。

### 13.3 truncated replay

目标：`exec_command_consumes_pushed_remote_process_events::truncated_event_replay`。

- 保留1024通知，不能降低超过256 replay/queue容量的压力。
- fake server记录：已发output数、exited/start response/closed是否发送、`process/read`次数、terminate是否收到、
  Responses第二请求是否到达。
- 所有5秒等待在失败时输出phase，而不是裸 `expect`。
- 取证后仅允许：用Notify/barrier消除不可观察竞态，或确认terminal event真丢失并立产品缺陷；不得减事件或加时。

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

- 保留 `source_cla::marketplace_import_sources` 的纯测试，钉住缺省官方源
  `anthropics/claude-plugins-official`；既有显式本地marketplace import测试也继续覆盖添加、安装、配置写入管线。
  两者是补充合同，不能替代组合链路。
- 在external内部加私有 `import_plugins_with_marketplace_adder` closure（或等价的私有窄协作者），生产wrapper仍调用真实
  marketplace add，不扩成公共cloner框架。
- hermetic组合测试从“settings中只有已启用的官方插件、没有显式source”开始，调用真实import编排到fake adder；fake必须
  记录并断言source精确为 `anthropics/claude-plugins-official`、ref为None、sparse paths为空，然后返回本地installed root。
  继续断言适用的import outcome、错误传播与配置结果，证明“源推导→添加→安装/配置”没有断链。
- 测试期间不得发生GitHub DNS/connect或git子进程；用fake调用记录与进程fixture机械证明，而不是凭运行速度推断。

生产git缺timeout/cancel/后代清理是真实产品缺陷，另立任务并用本地挂起+派生后代wrapper验证；测试hermetic修复
不能宣称该产品缺陷闭环。

定向门禁必须覆盖纯source推导、显式本地marketplace和上述组合测试。

### 15.2 OAuth：显式禁止打开浏览器

给 `mcp login` 增 `--no-open-browser`，底层flow接收显式 `launch_browser`；false时仍打印authorization URL、等待
callback、换取并持久化token；初次授权和“去掉scopes后重试”两条路径都必须透传该值。

把 `webbrowser::open` 隔在私有可注入launcher/callback后，生产默认保持现行为。单元测试用计数fake机械证明false为
0次调用、true/default为1次；CLI解析/透传测试证明 `--no-open-browser` 最终得到false。
`login_and_logout_persist_only_cloud_managed_mcp_oauth_credentials` 使用该flag，现有authorization URL、callback、token
持久化与logout断言全部保留。只设 `BROWSER` 不是跨平台合同，Windows实现可能不尊重它。

`CloudManagedMcpFixture::new()` 的OAuth隔离失败不得再以 `Ok(None)` 配合测试中的 `return Ok(())` 静默通过：改成
显式preflight或 `Result<Self>`，不可用时让该阶段失败/记未运行。缺依赖、端口或隔离能力都不是功能通过证据。

```text
just test -p codex-external-agent-migration --retries 0 --flaky-result fail -E 'test(/marketplace_import_sources/) or test(/import_plugins/)'
just test -p codex-rmcp-client --retries 0 --flaky-result fail -E 'test(/browser/) or test(/oauth/)'
just test -p codex-cli --retries 0 --flaky-result fail -E 'test(/login_and_logout_persist_only_cloud_managed_mcp_oauth_credentials/)'
```

## 16. 串并行实施顺序

代码审查可按独立族并行；所有重型测试严格串行：

1. 前置：看门狗真实 `just test`/clippy smoke，确认JUnit `retained` 与非nextest `not_applicable`。
2. 批次A：resolver seam + 20 network-proxy + core decider。
3. 批次B/C：Direct policy与5项消费者；随后shell合同。
4. 批次E/F：fixture-bounded roots与PowerShell平台收口。
5. 批次D/G：Landlock诊断/强合同；V8既有feature的独占双canary与workspace单向兼容性。
6. 批次H/I：严格执行修改前双200取证；在第4节条件决策点确认仍属测试设施修复后再实施，改后同负载复验。
7. 附加J/K：源推导到fake adder的组合链路、`--no-open-browser`及launcher零调用证明。
8. 每批跑相关包；全部通过后执行一次完整workspace
   `just test --retries 0 --flaky-result fail`，核对JUnit中实际执行数、failure、flaky与skip清单及watchdog summary；
   受影响Cargo manifest另跑 `python3 ../.github/scripts/verify_cargo_workspace_manifests.py`，最后运行受影响包clippy/fmt，
   不重复全量。

若前5批完成，严格待定只应剩 H的2项与I的1项，即39→3；附加J/K不计入严格失败。任何实际数量差异都以
新的机器JUnit逐名对账，不能靠算术改口径。

## 17. 当前状态

### 已完成

- 核对81项严格清单与第一批42项覆盖，冻结39+2口径。
- 证实Clash fake-IP、ambient proxy和 `/tmp` marker是环境事实；没有修改宿主。
- 证实Landlock历史失败是10秒 `Sandbox(Timeout)`，不是沙箱击穿；代理归因撤回。
- 证实回环/公网走同一seccomp拒绝面；本地listener合同成立。
- 证实原V8断言受feature unification影响；确定workspace单向兼容性+既有feature的独占双向canary。
- 核对各现有seam：NetworkProxyState手写Clone/Debug、HTTP factory/selector/pool、realtime缺FS参数、
  external无公开cloner、OAuth硬编码开浏览器。

### 当前工作

- 本计划已完成可执行性审查，等待后续按批次实施39个严格失败与2个附加事项。

### 阻塞项

- H/I的最终代码修法必须由修改前取证决定；若证据指向产品缺陷或超出本计划的重构，停在决策点更新方案，不能
  用fixture改动掩盖。
- Windows PowerShell门禁、本地V8资产、bwrap或OAuth隔离条件缺失时必须如实记未运行/阶段未完成，需要相应
  平台或资产后补验。

### 当前验收状态

- 方案审查完成；39+2代码未实施、未通过新全量，不能称测试闭环。

## 18. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 使用39严格失败+2附加事项口径 | 第一批实际覆盖42；migration/OAuth不在严格失败清单 | 全计划 | 已采纳 |
| 002 | DNS用精确登记resolver，未知返回错误 | catch-all会破坏DNS失败安全回归 | A | 已采纳 |
| 003 | 增显式Direct policy，默认不变 | 5项已有pool/factory/selector seam，不能依赖NO_PROXY | B | 已采纳 |
| 004 | shell只排除本session managed proxy | login shell可合法重载用户profile | C | 已采纳 |
| 005 | Landlock使用本地listener+未沙箱对照 | seccomp无地址分支，合同更强且hermetic | D | 已采纳 |
| 006 | 项目根测试用非空marker或FS seam | 空marker直接禁用根发现，会弱化测试 | E | 已采纳 |
| 007 | PowerShell断言按编译目标平台收口 | WSL PATH不等于Windows分类目标 | F | 已采纳 |
| 008 | V8用workspace单向蕴含与既有feature独占双canary | workspace断言受unification影响；不新增违反manifest白名单的期望feature | G | 已采纳 |
| 009 | 时序修复前后都做1线程/10线程各200次 | 孤立通过不能覆盖workspace并发竞态 | H | 已采纳 |
| 010 | external产品git终止另立任务 | hermetic测试与产品子进程缺陷不能混称闭环 | J | 已采纳 |
| 011 | OAuth用CLI显式no-open-browser | BROWSER环境变量不是跨平台保证 | K | 已采纳 |
| 012 | 所有正式nextest门禁禁重试且flaky视为失败 | 仓库默认重试1次；仅看最终绿色会掩盖不稳定性 | 全计划 | 已采纳 |
| 013 | external保留源推导到fake adder的组合测试 | 两个分拆测试不能证明真实编排没有断链 | J | 已采纳 |
| 014 | empty roots使用同backend的正反对照并精确分类拒绝 | 任意非零可能来自helper/加载器/命令失败，不等于隔离生效 | I | 已采纳 |
| 015 | OAuth用注入launcher计数且隔离失败不得静默通过 | CLI flag本身不能证明所有分支都未调用浏览器 | K | 已采纳 |
