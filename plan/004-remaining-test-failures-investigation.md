# 剩余 41 项全量失败：根因取证与修复方案

> **状态：调研方案，未落地任何代码。** 本文件只做取证、根因彻查和细化到可直接照做的修复设计。
> 执行者应把本文件当作唯一入口，不需要重新调研。
>
> 前置：`agent_log/2026-08-09-020200-baseline-p0-test-audit.md`（GPT 的分类归因）、
> `agent_log/2026-08-09-025644-claude-cross-review-of-baseline-p0-audit.md`（交叉复核）、
> `agent_log/2026-08-09-073528-test-hermeticity-batch-1.md`（已修复的 40 项）。
>
> 基线：`fix/005-test-hermetic` 分支 `de6f604`。全量 81 项中 40 项已修复并验证，本文件覆盖剩余 41 项。

## 1. 目标

### 最终目标

让剩余 41 项失败测试恢复为**在本机（WSL2 + Clash Verge TUN）与干净 CI 机器上都稳定通过**，
且不依赖任何宿主环境状态。修复手段一律是让测试自带确定性输入，不是放宽产品的安全判定、
不是改宿主网络、不是删除断言。

### 完成/验收标准

- 每一项失败都能指出：可复现的观测证据、代码级根因（精确到文件与函数）、修法、以及"为什么这样修
  不算凑绿"。
- 修完后 `just test -p <包名>` 在**保持 Clash TUN 开启、保持代理环境变量存在**的条件下通过。
  这是硬指标：如果必须关掉 Clash 才能绿，说明测试仍不 hermetic，不算完成。
- 不新增重型测试框架、不新增依赖、不新增常驻服务。
- 产品侧只允许加"注入点"（resolver / target OS / home 目录之类的可替换入口），
  不允许改变默认行为。任何产品默认行为的改变都要单独提出。

## 2. 范围

### 允许修改

- `mydev/codex-rs/` 下相关包的**测试代码与 fixture**。
- 为使测试可注入而必需的**最小产品级 seam**（见每项的"需要的产品改动"栏），默认值必须与现状一致。
- `doc/` 中受影响的事实描述；`agent_log/` 与本 `plan/`。

### 不允许修改

- 产品的 SSRF / 本地地址 / 私网 fail-closed 判定，尤其不得把 `198.18.0.0/15` 加入任何 allowlist。
- 安全命令分类（safe-command classifier）的判定规则。
- 宿主 Clash / DNS / 代理配置、`/tmp` 下的残留 marker、`~/.agents/` 内容。
- `codex-source-code/`、`codex-doc/`、`reference-agent-harness/`。
- 断言的强度：不得改成更弱的匹配、不得删断言、不得加 `#[ignore]`、不得靠加大超时凑绿。

### 不允许读取/查看

- 项目外个人文件、凭据、真实会话记录。

## 3. 硬约束

1. 所有重型 Cargo 构建/测试必须经 `mydev/scripts/with-build-lock.sh`（优先 `just`），一次只跑一组。
2. **验证时不得关闭 Clash / 不得 unset 代理变量**。要证明修复有效，就必须在污染环境下绿。
   可以临时用 `env -u` 做**对照实验**来定位根因，但不能把它当作修复。
3. 先复现、后修改。每项修改前必须先跑到失败并留下原始错误，再动手。
4. 一次提交只处理一个根因族，便于回退。
5. 真实网络调用只允许出现在明确标注为 live smoke 的测试里，且默认不跑。

## 4. 环境取证（本轮实测，是后面所有结论的基础）

以下三条是在本机直接测出来的，不是推断：

**证据 1 —— DNS 返回 fake-IP。**

```
$ getent hosts example.com      -> 198.18.0.88
$ getent hosts api.github.com   -> 198.18.0.133
```

两个地址都落在 `198.18.0.0/15`（RFC 2544 基准测试保留段），这是 Clash TUN 的 fake-ip 池。
`/etc/resolv.conf` 指向 `nameserver 10.255.255.254`（WSL 自动生成，转发到 Windows 侧的 Clash）。

**证据 2 —— 代理环境变量全量存在，且 NO_PROXY 写法无效。**

```
http_proxy  = https_proxy = HTTP_PROXY = HTTPS_PROXY = http://127.0.0.1:7897
all_proxy   = ALL_PROXY   = socks5h://127.0.0.1:7897
no_proxy    = NO_PROXY    = 172.31.*,...,10.*,192.168.*,127.*,localhost,<local>
```

关键在于 `no_proxy` 的写法。Rust 侧的解析在
`hyper-util-0.1.20/src/client/proxy/matcher.rs::NoProxy::from_string`（reqwest 0.13 转发给它）：

- 每个逗号分隔项先尝试解析为 IP 或 IP 网段，成功则进 `IpMatcher`；
- **失败则一律当作域名**，按后缀匹配；
- **唯一允许的通配符是单独一个 `*`**。

所以 `127.*` / `10.*` / `192.168.*` 既不是合法 IP 网段、也匹配不上任何主机名，
`<local>` 更是 Java/.NET 的写法，Rust 侧不认识。**实际生效的只有 `localhost` 一项。**
结论：任何以 `127.0.0.1:<port>` 字面量发起的请求都不会被 NO_PROXY 豁免，会被送进
`socks5h://127.0.0.1:7897`。这就是"预期 connection refused，实际拿到代理响应"的机制。

**证据 3 —— `/tmp` 下的祖先项目标记是沙箱残留。**

```
/tmp/.git  /tmp/.codex  /tmp/.agents   均为空目录，属主 sjc，创建时间 Aug 8 21:04
```

时间点与第一次沙箱化全量运行吻合，是沙箱为只读挂载而预建的目录。它们会让任何
`TempDir::new()`（默认落在 `/tmp`）的祖先游走把 `/tmp` 当成项目根 / git 仓库根。

> 顺带说明：`rmdir /tmp/.git /tmp/.codex /tmp/.agents` 能立刻"修好"这一族测试，
> 但那是改宿主机、且下次沙箱运行会重新生成。**不采用**，也不要在执行阶段顺手做。

## 5. 根因族 A：DNS fake-IP 污染 host_blocked（20 项，codex-network-proxy）

### 受影响测试

`network-proxy/src/runtime.rs`
1. `runtime::tests::host_blocked_requires_allowlist_match`
2. `runtime::tests::add_allowed_domain_removes_matching_deny_entry`
3. `runtime::tests::host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist`
4. `runtime::tests::host_blocked_subdomain_wildcards_exclude_apex`

`network-proxy/src/http_proxy.rs`
5. `http_proxy::tests::http_connect_accept_blocks_in_limited_mode`
6. `http_proxy::tests::http_connect_accept_blocks_hooked_host_in_full_mode_without_mitm_state`
7. `http_proxy::tests::http_connect_accept_passes_environment_id_to_decider`
8. `http_proxy::tests::http_connect_accept_defers_brokered_host_mitm_until_protocol_detection`

`network-proxy/src/mitm_tests.rs`
9. `mitm::tests::mitm_policy_blocks_disallowed_method_and_records_telemetry`
10. `mitm::tests::mitm_policy_allows_matching_hooked_write_in_full_mode`
11. `mitm::tests::mitm_policy_blocks_hook_miss_for_hooked_host_and_records_telemetry_in_full_mode`
12. `mitm::tests::mitm_policy_blocks_matching_hooked_write_in_limited_mode`

`network-proxy/src/network_policy.rs`
13. `network_policy::tests::evaluate_host_policy_emits_domain_event_for_decider_ask`
14. `network_policy::tests::evaluate_host_policy_emits_domain_event_for_decider_allow_override`
15. `network_policy::tests::evaluate_host_policy_emits_execution_id_for_baseline_allow`

`network-proxy/src/socks5.rs`
16. `socks5::tests::handle_socks5_tcp_blocks_limited_mode_without_mitm_state`
17. `socks5::tests::handle_socks5_tcp_blocks_hooked_non_https_host_in_full_mode`
18. `socks5::tests::handle_socks5_tcp_uses_mitm_for_hooked_host_in_full_mode`
19. `socks5::tests::handle_socks5_tcp_detects_tls_for_brokered_nonstandard_port_in_full_mode`
20. `socks5::tests::handle_socks5_tcp_uses_mitm_in_limited_mode`

这 20 项用到的主机名统计：`example.com` × 26、`api.github.com` × 24、`blocked.com` × 2、
`api.openai.com` × 2、`github.com` × 1。全部是真实可解析域名。

### 根因（代码级）

`NetworkProxyState::host_blocked`（`network-proxy/src/runtime.rs:497`）在
`allow_local_binding == false` 时做 DNS + IP 分类的纵深防御检查。第 551–560 行：

```rust
} else if host_resolves_to_non_public_ip(
    host_str,
    port,
    DNS_LOOKUP_TIMEOUT,
    |host, port| async move {
        lookup_host((host.as_str(), port)).await.map(Iterator::collect)
    },
)
.await
{
    return Ok(HostBlockDecision::Blocked(HostBlockReason::NotAllowedLocal));
}
```

`lookup_host` 是 `tokio::net::lookup_host`，走系统解析器 → 拿到 `198.18.x.x` →
`is_non_public_ip` 判为非公网 → 直接返回 `NotAllowedLocal`。于是所有本应得到
`Allowed` / `Blocked(NotAllowed)` / `Mitm{..}` 的断言全部落到 `NotAllowedLocal` 分支。

**产品行为是正确的**：把解析到私网/保留段的域名拦下来正是防 DNS rebinding 的设计意图，
上游注释（`runtime.rs:528-535`）写得很清楚。错的是测试依赖了环境 DNS。

上游其实已经踩过一次这个坑：`runtime.rs:1190-1191` 有注释
"Use a public IP literal to avoid relying on ambient DNS behavior (some networks resolve unknown
hostnames to private IPs, which would trigger `not_allowed_local`)"，但只对 IP 字面量做了规避，
主机名路径没管。

### 现成的注入点

`host_resolves_to_non_public_ip`（`runtime.rs:911`）**本来就是对解析闭包泛型的**：

```rust
async fn host_resolves_to_non_public_ip<F, Fut>(host: &str, port: u16, lookup_timeout: Duration, lookup: F) -> bool
where F: FnOnce(String, u16) -> Fut, Fut: Future<Output = std::io::Result<Vec<SocketAddr>>>
```

而且 `runtime.rs:1620/1635/1653/1666` 四个既有测试已经在给它传假解析器。
缺的只是把这个注入点提升到 `host_blocked` 这一层。

### 建议修法

在 `NetworkProxyState` 上加一个可替换的解析器，默认行为与现在完全一致：

```rust
// runtime.rs
pub(crate) type HostLookup = Arc<
    dyn Fn(String, u16) -> BoxFuture<'static, std::io::Result<Vec<SocketAddr>>> + Send + Sync,
>;

fn system_host_lookup() -> HostLookup {
    Arc::new(|host: String, port: u16| {
        Box::pin(async move { lookup_host((host, port)).await.map(Iterator::collect) })
    })
}
```

- `NetworkProxyState` 增加字段 `host_lookup: HostLookup`，构造时默认 `system_host_lookup()`。
- `host_blocked` 把闭包换成 `self.host_lookup.clone()`。
- 加一个 `#[cfg(test)] pub(crate) fn set_host_lookup_for_tests(&mut self, lookup: HostLookup)`，
  或者给测试专用构造函数加一个参数。
- 测试侧提供一个共享 helper（建议放在 `network-proxy/src/test_support.rs`，
  若无此文件则新建一个 `#[cfg(test)] mod`）：

```rust
/// Fixed DNS answers so policy tests do not depend on the host resolver.
///
/// A developer machine behind a TUN-mode proxy resolves every hostname into the
/// 198.18.0.0/15 fake-IP pool, which the product correctly treats as non-public and
/// blocks before any policy decision is reached.
pub(crate) fn static_host_lookup() -> HostLookup {
    Arc::new(|host: String, port: u16| {
        let addr = match host.as_str() {
            "example.com" | "www.example.com" => [93, 184, 216, 34],
            "api.github.com" | "github.com"   => [140, 82, 114, 6],
            "api.openai.com"                  => [104, 18, 6, 192],
            "blocked.com"                     => [203, 0, 113, 10],
            _                                 => [198, 51, 100, 10], // TEST-NET-3
        };
        Box::pin(async move {
            Ok(vec![SocketAddr::from((Ipv4Addr::from(addr), port))])
        })
    })
}
```

然后把 20 项测试里构造 state 的地方（`network_proxy_state_for_policy` / `state_for_settings`
这两个 helper 就是集中点）统一挂上这个解析器——**改两个 helper 就能覆盖绝大多数用例**，
不需要逐个测试改。

### 为什么这不算凑绿

被替换的只是"这台机器的 DNS 回答什么"，产品的分类逻辑、allowlist/denylist 判定、
MITM 决策路径一个字没动。相反，固定解析结果之后，
`host_blocked_requires_allowlist_match` 这类断言才第一次真正测到 allowlist 分支
（现在它们连那一步都走不到）。同时**必须保留**已有的四个直接测
`host_resolves_to_non_public_ip` 的用例，它们是私网判定本身的回归。

### 验证

```
just test -p codex-network-proxy
```
必须在 Clash TUN 开启状态下全绿。另外建议临时加一条断言型的自检：
用 `static_host_lookup` 把 `example.com` 映射到 `10.0.0.1`，确认仍返回 `NotAllowedLocal`，
证明注入没有把私网防护旁路掉；确认后可保留为一个新回归测试。

### 风险

- `HostLookup` 引入 `Arc<dyn Fn>` 会让 `NetworkProxyState` 不再是 `#[derive(Debug)]` 友好类型，
  需要手写 `Debug` 或给字段加 `#[debug(skip)]` 等价处理。**动手前先确认该结构体现有的 derive**。
- `NetworkProxyState` 若实现了 `Clone`/`PartialEq`，加函数指针字段会破坏它们；
  这时改用 `Option<HostLookup>` + `PartialEq` 手工实现（比较时忽略该字段），或把解析器放进
  已有的 `state: RwLock<...>` 内部。**这是本族唯一需要现场判断的点。**

## 6. 根因族 B：代理环境变量污染（8 项，跨 7 个包）

### 受影响测试与精确位置

| # | 测试 | 位置 |
|---|---|---|
| 1 | `route_aware_client_pool::tests::without_url_redacts_transport_error_urls` | `http-client/src/route_aware_client_pool_tests.rs:144` |
| 2 | `files::tests::upload_openai_file_reports_blob_transport_diagnostics_without_sas` | `codex-api/src/files.rs` |
| 3 | `doctor::tests::mcp_check_warns_for_optional_http_reachability` | `cli/src/doctor.rs` |
| 4 | `remote::search::tests::search_remote_plugins_redacts_sensitive_parameters_from_transport_errors` | `core-plugins/src/remote/search_tests.rs` |
| 5 | `delegated_http_failure_warning_redacts_request_url` | `exec-server/tests/http_request_logging.rs` |
| 6 | `session::tests::managed_network_proxy_decider_survives_full_access_start` | `core/src/session/tests.rs` |
| 7 | `session::tests::user_shell_commands_do_not_inherit_managed_network_proxy` | `core/src/session/tests.rs` |
| 8 | `suite::landlock::sandbox_blocks_wget` | `linux-sandbox/tests/suite/landlock.rs:495` |

### 根因（以 #1 为标本，其余同构）

```rust
let listener = TcpListener::bind(("127.0.0.1", 0)).expect(...);
let address = listener.local_addr().expect(...);
drop(listener);                                   // 端口现在是关闭的
let error = reqwest::Client::new()                // ← 默认 client，读环境代理
    .get(format!("http://{address}/upload?sig={secret}"))
    .send()
    .await
    .expect_err("closed listener should reject request");
```

测试的意图是"连一个已关闭端口 → 必然拿到 transport error → 断言错误信息里不含 secret"。
但按证据 2，`127.0.0.1` 不被 NO_PROXY 豁免，`reqwest::Client::new()` 会把请求交给
`socks5h://127.0.0.1:7897`。Clash 作为代理返回自己的错误/响应，`send()` 不再是预期的
连接层失败：轻则错误类型变了、重则返回 `Ok` 导致 `expect_err` 直接 panic。

#8 landlock 是同一机制的变体：沙箱内跑 `wget -qO- http://openai.com`，
`wget` 继承 `http_proxy` 后改连本机 `127.0.0.1:7897`。回环连接是否被 landlock 网络规则拦住，
与"直连公网被拦住"是两件事，断言因此不成立。

### 现成的注入点

仓库里**已经有**这套能力，不需要新造：

- `http-client/src/outbound_proxy.rs:99` 的 `OutboundProxyPolicy { ReqwestDefault, RespectSystemProxy }`
  与 `OutboundProxyRoute::{TransportDefault, Direct, ...}`；
- `outbound_proxy.rs:456` 已有 `OutboundProxyRoute::Direct => Ok(builder.no_proxy())`；
- `http-client/src/transport_tests.rs:33` 已经有测试直接用 `.no_proxy()` 的先例。

### 建议修法（按测试类型分两种）

**B-1：测试自己构造 reqwest client 的（#1、#2、#4、#5）**
把 `reqwest::Client::new()` 换成显式直连 client。建议在 `http-client` 里导出一个测试 helper，
避免每处重复：

```rust
/// Client that never consults ambient proxy settings.
///
/// Tests that assert on transport failures must reach the socket directly. A developer
/// machine usually exports HTTP(S)_PROXY/ALL_PROXY, and the common `NO_PROXY` glob syntax
/// (`127.*`) is parsed as a domain suffix, so loopback requests are proxied anyway and the
/// expected connection error never happens.
pub fn direct_client_for_tests() -> reqwest::Client {
    reqwest::Client::builder().no_proxy().build().expect("direct test client")
}
```

放在 `http-client` 的 `pub mod test_support`（该 crate 已被上述包依赖），
其他包在 `dev-dependencies` 里引用即可。**不要为此新建 crate。**

**B-2：测试断言产品内部构造的 client（#3、#6、#7）**
这类不能在测试里换 client，要走产品既有的策略参数。核实
`doctor` / `session` 构造出站 client 的路径是否已经吃 `OutboundProxyPolicy`；
若已吃，就在测试里传 `Direct`/等价值；若没吃，则加一个默认值不变的参数，
**默认必须仍是 `ReqwestDefault`**，只有测试传显式直连。

**B-3：landlock（#8）**
两件事一起做：
1. 给沙箱子进程清掉代理变量（`Command::env_remove` 掉 8 个变量，或用
   `env_clear` + 显式最小环境），让 `wget` 真的去连公网；
2. 按 GPT 的建议加一条**未沙箱化对照**：同样的命令在沙箱外应当能连通（或至少产生不同的失败），
   否则"被拦住"可能只是本机根本没网。对照失败时应 skip 并明确说明，不得默认当作通过。

### 为什么这不算凑绿

`no_proxy()` 恢复的是测试原本就想要的路径（直连一个关闭的端口），断言内容一字未改
（仍然断言错误信息里不含 secret、仍然断言网络被拦）。反过来说，现在这些测试在本机上
**根本没有测到它们声称要测的东西**。

### 可选的宿主侧改善（属于用户决定，不在本方案的执行范围）

把 `NO_PROXY` 改成 Rust 侧认识的写法能顺带减少大量本机干扰：

```
NO_PROXY=localhost,127.0.0.0/8,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

**但这不能替代 B-1～B-3**：CI 或别人的机器上环境变量不可控，测试仍必须自带确定性。

### 验证

```
just test -p codex-http-client -p codex-api -p codex-cli -p codex-core-plugins
just test -p codex-exec-server -E 'test(/delegated_http_failure_warning_redacts_request_url/)'
just test -p codex-core -E 'test(/managed_network_proxy/) or test(/user_shell_commands_do_not_inherit/)'
just test -p codex-linux-sandbox
```
同样必须在代理变量存在的情况下绿。定位阶段可以用
`env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY just test ...`
做对照来确认根因，但**对照通过不算修好**。

## 7. 根因族 C：`/tmp` 祖先项目标记（6 项）

共同机制见证据 3。以下逐项给出各自的注入点，因为它们走的不是同一条解析路径。

### C-1 `codex-core config::config_loader_tests::codex_home_is_not_loaded_as_project_layer_from_home_dir`
位置：`core/src/config/config_loader_tests.rs:3059`。
fixture 建 `<tmp>/home/.codex/config.toml`，cwd 设为 `<tmp>/home`，断言 codex_home 不会被当作项目层。
祖先游走走到 `/tmp` 命中 `/tmp/.codex`，多出一个项目层。

**修法**：在 fixture 已经写的那份 `config.toml` 里加一行 `project_root_markers = []`。
`config/src/project_root_markers.rs:29-31` 明确支持空数组（返回 `Ok(Some(vec![]))`），
语义正是"没有任何项目根标记"，与测试意图一致。

### C-2 `codex-core config::config_loader_tests::project_layers_disabled_when_untrusted_or_unknown`
位置：同文件 `:3169`。同样的加法，但要注意 marker 必须写进**非 Project 层**
（`ext/skills/src/host_roots.rs:215-222` 的 `project_root_markers_from_stack` 会跳过 Project 层，
config 侧大概率同构——**执行前先确认 config 侧的合并规则**）。
`make_config_for_test(&codex_home_untrusted, ...)` 写的是 user 层，是正确落点。

### C-3 `codex-core git_info_tests::resolve_root_git_project_for_trust_returns_none_outside_repo`
位置：`core/src/git_info_tests.rs:609`。
`resolve_root_git_project_for_trust(LOCAL_FS.as_ref(), &tmp.path().abs())` 只找 `.git`，
没有 marker 配置可用。**但第一个参数是 `&dyn ExecutorFileSystem`**，这就是注入点。

**修法**：写一个测试用的 FS 装饰器，把 `tmp.path()` 之外的路径一律报 `NotFound`：

```rust
/// File system that stops at a fixture root.
///
/// `TempDir` lives under the system temp directory, and a machine that has run a sandboxed
/// Codex leaves an empty `/tmp/.git` behind, so an unrestricted ancestor walk escapes the
/// fixture and reports the system temp directory as the repository root.
struct RootedFs { inner: Arc<dyn ExecutorFileSystem>, root: PathBuf }
```

`ext/skills/src/host_roots_tests.rs` 里已有同类装饰器（包着 `inner` 转发的写法，
见该文件 160-170 行附近）可以直接照抄结构。装饰器建议放到 `core` 的测试支持模块里复用给 C-4/C-5。

### C-4 `codex-core realtime_context::tests::workspace_section_requires_meaningful_structure`
位置：`core/src/realtime_context_tests.rs:247`。空 TempDir，断言 `build_workspace_section_with_user_root`
返回 `None`。祖先游走命中 `/tmp` 后拿到了 `/tmp` 的内容，于是返回了 `Some`。
**修法**：优先复用 C-3 的 `RootedFs`；若该函数没有 FS 参数，则退而求其次——
让 fixture 在自己的 TempDir 根写一个 `.git` 文件把游走截断，
并把断言从"没有 workspace"改为"workspace 为空结构"（**这一步要先跑一次确认语义没被削弱，
如果会削弱就必须走注入路线**）。

### C-5 `codex-core realtime_context::tests::recent_work_section_groups_threads_by_cwd`
位置：同文件 `:293`。fixture 自己 `git init` 了 `<tmp>/repo`，另有一个 `<tmp>/outside`
用来验证"不同 cwd 分组"。`outside` 因为 `/tmp/.git` 而被判进同一个"仓库"，分组结果错。
**修法**：同 C-3/C-4 的注入；或把 `outside` 移到 `repo` 的兄弟目录并在 `<tmp>` 根也 `git init`
一个独立仓库，让两侧都有明确的、fixture 自己控制的边界。后者更贴近测试本意，改动也更小。

### C-6 `codex-secrets tests::environment_id_fallback_has_cwd_prefix`
位置：`secrets/src/lib.rs:207`（被测函数 `environment_id_from_cwd` 在 `:159`）。

```rust
pub fn environment_id_from_cwd(cwd: &Path) -> String {
    if let Some(repo_root) = get_git_repo_root(cwd) && let Some(name) = repo_root.file_name() { ... return name; }
    // fallback: cwd-<sha256[..12]>
}
```

`get_git_repo_root(/tmp/xxx)` 因 `/tmp/.git` 返回 `/tmp` → 函数返回 `"tmp"`，
而测试断言的是 `cwd-<hash>` 这条 fallback。
**修法**：`environment_id_from_cwd` 目前没有注入点，最小改法是拆一个内部函数：

```rust
fn environment_id_from_cwd_with_repo_root(cwd: &Path, repo_root: Option<PathBuf>) -> String
pub fn environment_id_from_cwd(cwd: &Path) -> String {
    environment_id_from_cwd_with_repo_root(cwd, get_git_repo_root(cwd))
}
```

测试直接调内层并传 `None`，语义就是"这个 cwd 不在任何仓库里"，正是它要测的前提。

### 本族验证

```
just test -p codex-core -E 'test(/config_loader_tests/) or test(/git_info_tests/) or test(/realtime_context/)'
just test -p codex-secrets
```

## 8. 根因族 D：WSL PATH 互操作让 Linux 看见 Windows 可执行文件（1 项）

**测试**：`codex-core tools::handlers::shell::tests::commands_generated_by_shell_command_handler_can_be_matched_by_is_known_safe_command`
位置：`core/src/tools/handlers/shell_tests.rs:38`。

```rust
if let Some(path) = try_find_powershell_executable_blocking() {
    let powershell = Shell { shell_type: ShellType::PowerShell, shell_path: path.to_path_buf() };
    assert_safe(&powershell, "ls -Name");
}
if let Some(path) = try_find_pwsh_executable_blocking() { ...同上... }
```

**根因**：WSL 默认开启 interop，`PATH` 里带着 `/mnt/c/Windows/System32/WindowsPowerShell/v1.0` 等目录，
所以 `try_find_powershell_executable_blocking()` 在 Linux 上也能找到 `powershell.exe`，
于是走进了 PowerShell 分支。但 safe-command classifier 在非 Windows 目标上并不启用 PowerShell
安全名单，`ls -Name` 不被判为 safe，断言失败。

**修法**：这两段是"如果本机装了 PowerShell 就顺带测一下"的机会性断言，
应当按**分类器的目标平台**收口，而不是按 PATH 上能不能找到可执行文件：

```rust
if cfg!(windows) && let Some(path) = try_find_powershell_executable_blocking() { ... }
```

更好的做法是给 `assert_safe` / 分类器入口传显式 target OS，让 Linux 上也能测 PowerShell 分支
（把"宿主平台"和"被分类命令的目标平台"解耦）。若分类器 API 支持显式目标 OS，优先走这条，
覆盖率更高；不支持则用 `cfg!(windows)` 收口，并在测试里写清楚原因。

**绝对不能**：为了让本机绿，把 PowerShell 安全名单在 Linux 上打开。那是放宽安全分类。

**验证**：`just test -p codex-core -E 'test(/is_known_safe_command/)'`

## 9. 根因族 E：Cargo feature 统一（1 项）

**测试**：`codex-v8-poc tests::sandbox_feature_matches_linked_v8`，位置 `v8-poc/src/lib.rs:68`。

```rust
assert_eq!(super::linked_v8_has_sandbox(), cfg!(feature = "sandbox"));
```

**根因**：单独跑 `-p codex-v8-poc` 时两边一致。但 workspace 全量构建时，Cargo 的
feature unification 会把工作区里**其他成员**为 `v8` crate 打开的 `sandbox` feature 合并进来，
链接到的 V8 实际带 sandbox（`linked_v8_has_sandbox() == true`），
而 `cfg!(feature = "sandbox")` 求值的是 **`codex-v8-poc` 自己**的 feature，仍是 false。
断言比较的是两个不同层级的东西，在统一构建下必然不等。

另有一个独立的次要问题：默认的 denoland release archive 404，需要固定到
`.github/actions/setup-rusty-v8/action.yml` 指定的 OpenAI 资产（这条 GPT 已记录，且只在重新下载时触发）。

**修法（三选一，按推荐度排序）**：
1. 把断言改成"只在本 crate 独占构建时才有意义"的显式形式：读取 `v8` 依赖的实际 feature 状态
   而不是本 crate 的 `cfg!`，即断言 `linked_v8_has_sandbox()` 与**真实链接到的库**一致
   （这需要一个能反映统一后状态的入口；若拿不到，走 2）。
2. 保留断言但只在 `cargo test -p codex-v8-poc` 这种非统一构建下生效：
   加一个 build script 或 feature（如 `standalone-assertions`），全量 workspace 不启用。
   **要在测试里显式说明它在全量下被跳过的理由**，不能静默 skip。
3. 把 `codex-v8-poc` 从 workspace 默认成员里排除，单独跑。影响面最大，除非有别的理由，不建议。

**验证**：`just test -p codex-v8-poc` 与全量各跑一次，两种模式都必须给出确定结论。

## 10. 根因族 F：时序 / 并发欠账（2 项）

这两项 GPT 归为"全量并发波动"，未在前两次同环境结果中稳定出现，属于真正的时序问题，
**不要靠加大超时了事**。

### F-1 `codex-core::all suite::realtime_conversation::conversation_close_routes_only_remaining_transcript_tail_once`
位置：`core/tests/suite/realtime_conversation.rs`。
关闭时用 10ms 轮询 + 2s 等待收尾 transcript tail。全量并发下（`test-threads = 10` 且大量集成测试
拉子进程）2s 不够。

**调查步骤（先做这个，不要直接改）**：
1. 定点复跑 200 次，统计失败率：
   `just test -p codex-core -E 'test(/conversation_close_routes_only_remaining_transcript_tail_once/)'`
   配合 nextest 的重复运行参数；记录原始失败输出。
2. 在关闭路径加临时 trace，确认是"事件确实没发出"还是"发出了但测试没等到"。
3. 若是后者：把轮询改成**基于信号的确定性同步**（等待一个明确的关闭完成事件/通道），
   而不是把 2s 改成 10s。若是前者：是产品的关闭顺序问题，需要单独立 issue。

### F-2 `codex-core::all suite::unified_exec_process_events::exec_command_consumes_pushed_remote_process_events::truncated_event_replay`
位置：`core/tests/suite/unified_exec_process_events.rs`。
1024 条通知制造截断，固定 5s 等待。同样先做 200 次定点复跑取证，再决定是背压确定化还是产品问题。

**共同硬要求**：这两项在拿到稳定复现率之前不得修改。修完必须给出"修改前失败率 / 修改后失败率"
两个数字。

## 11. 根因族 G：单点问题（3 项）

### G-1 `codex-exec-server::exec_process remote_process_preserves_empty_workspace_roots`
位置：`exec-server/tests/exec_process.rs`。
GPT 已确认：本地 event wait 固定 2s，多轮复现，**不是 `/tmp` 也不是网络**。
**调查方向**：定向 trace 判断终态是"真挂起"还是"collector deadline 过紧"。
**红线**：不得弱化 empty-roots 的拒绝逻辑来换通过。

### G-2 external agent migration 间歇超时
测试里真实 `git clone` GitHub；生产代码的子进程没有 timeout / cancel。
**两件事分开**：
- 测试侧：注入一个 local cloner（用本地裸仓库代替 GitHub），让测试离线确定。
- 产品侧：给 git 子进程加超时和进程组终止——这是**真实缺陷**，应单独立任务，不要混进测试维护。
- 如果确实需要验证真实 GitHub 路径，另起一个默认不跑的 live smoke。

### G-3 managed OAuth 测试打开真实浏览器
测试当前是"通过"的，但会在 WSL 里拉起 Windows 浏览器，说明全量并非无副作用。
**修法**：stub `BROWSER` 环境变量，或给 launcher 注入 no-op 实现 / `--no-open-browser`。
优先注入 launcher，不要依赖环境变量。

## 12. 建议执行顺序

按"根因独立、可单独验证、互不阻塞"排：

| 批次 | 内容 | 数量 | 并行性 | 备注 |
|---|---|---:|---|---|
| 1 | 族 B 代理污染 | 8 | 内部可并行改，验证串行 | 先做，因为 helper 会被后面复用 |
| 2 | 族 A DNS 注入 | 20 | 单包，串行 | 收益最大，但要先解决 `NetworkProxyState` 的 derive 风险 |
| 3 | 族 C `/tmp` 标记 | 6 | C-1/C-2/C-6 可并行；C-3/C-4/C-5 共用 `RootedFs`，串行 | |
| 4 | 族 D + 族 E | 2 | 可并行 | 都是小改 |
| 5 | 族 G-3 浏览器副作用 | 1 | — | 消除全量的真实副作用，越早越好 |
| 6 | 族 F 时序 + G-1 + G-2 | 4 | 串行 | **只有这一批需要长时间复跑取证**，放最后 |

批次 1～5 做完，剩余失败应从 41 降到 4。批次 6 是需要耐心的部分，允许结论是"这是产品缺陷，
另立任务"，不必强行在测试侧解决。

每批次结束后跑一次对应包的 `just test -p <包>`，全部批次结束后再跑一次完整 workspace 全量
（一次即可，走看门狗）。

## 13. 硬性提醒（给执行者）

1. **不要 `rmdir /tmp/.git` 之类的宿主操作**，也不要建议用户长期关闭 Clash。
2. **不要把 `198.18.0.0/15` 或任何 fake-IP 段加进 allowlist**。
3. **不要用 `#[ignore]`、放宽断言、加大超时**来处理任何一项。加超时只有在 F 族取证证明是
   "确定性同步缺失"且已改为信号同步之后才允许作为附带调整。
4. 产品级 seam 的默认值必须与现状完全一致，改完要有一个测试证明默认路径没变。
5. 每批次改完，先在**保持污染环境**下验证，再考虑提交。
6. 每一项都要在 agent_log 里记录"修改前的原始失败输出"，这是这批工作最容易被省略、
   也最影响后续复盘的东西。

## 14. 当前状态

### 已完成

- 三条环境证据实测完毕（fake-IP DNS、代理变量 + NO_PROXY 解析失效、`/tmp` 残留 marker）。
- 41 项全部完成根因归属，其中 A、B、C、D、E 五族已定位到具体函数与行号，并确认注入点存在。
- F、G 族给出取证步骤而非结论——这两族必须先复跑取数据。

### 已核实的落地细节（原本列为风险，现已消解）

- **族 A 的 derive 风险不存在。** `NetworkProxyState`（`network-proxy/src/runtime.rs:230`）是裸结构体，
  没有任何 `#[derive]`，八个字段全是 `Arc<...>` / `Option<Arc<str>>`。
  直接加 `host_lookup: HostLookup` 字段即可，不会破坏 `Clone`/`Debug`/`PartialEq`。
  §5"风险"一节可以整节忽略。
- **族 B #6/#7 的落点已定位。** `core/src/session/tests.rs:651` 已经在写
  `HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault)`，改这一处即可覆盖两项测试。
  但注意：`OutboundProxyPolicy`（`http-client/src/outbound_proxy.rs:99`）目前**只有
  `ReqwestDefault` 和 `RespectSystemProxy` 两个变体，没有 Direct**。两种落法二选一：
  1. 给该枚举加 `Direct` 变体，映射到已有的 `OutboundProxyRoute::Direct`
     （`outbound_proxy.rs:456` 已经是 `Ok(builder.no_proxy())`），默认值不变；
  2. 测试改走 `HttpClientBuilder` + `.no_proxy()`（先例：`client_builder.rs:257`
     的 `ProxyRouting::Direct => builder.no_proxy()`）。
  推荐 1，因为 #3 doctor 侧大概率也需要同一个开关。
- **族 C-2 的合并规则可以合理推断。** `config/src/state.rs:534` 附近那段只做层序校验，不是 marker 合并。
  但项目层的**发现**必须先知道 marker 才能建层，存在鸡生蛋关系，因此 marker 只可能来自
  非 Project 来源（与 `ext/skills/src/host_roots.rs:215-222` 显式跳过 Project 层一致）。
  把 `project_root_markers = []` 写进 user 层是安全的。执行时顺手确认一次即可，不必重新调研。

### 仍需现场确认

- 族 C-4：把断言从"没有 workspace"改成"workspace 为空结构"是否削弱测试语义——必须先跑一次看输出，
  会削弱就走 `RootedFs` 注入路线。
- 族 F（2 项）、G-1：稳定复现率未测，必须先取数据。

### 遗留观察项（与本次 41 项无关，但会干扰构建）

`failed to connect to jobserver from environment variable CARGO_MAKEFLAGS="...--jobserver-fds=8,10..."：
file descriptor 8 ... is not a pipe`。修复 F1（rustc stderr 被吞）之后才显形。
已排除本仓两个包装脚本（`with-build-lock.sh` 与 `rustc-throttle.sh` 现在分别用 fd 199 / 200，
不再触碰 8/9/10），警告仍在，说明还有第二个来源。只影响 rustc 之间的并发协调，不影响正确性，
建议单独排查，不要混进测试维护。

## 15. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 验证必须在 Clash TUN 开启 + 代理变量存在的条件下进行 | 关掉污染源再验证等于没验证；CI 与他人机器同样不可控 | 全部批次 | 提议 |
| 002 | 一律走"注入确定性输入"，不改产品判定 | 失败的是测试的环境假设，不是产品逻辑；改判定就是降级安全 | 全部批次 | 提议 |
| 003 | 不删 `/tmp` 残留 marker | 属宿主机改动，且下次沙箱运行会重建 | 族 C | 提议 |
| 004 | 族 A 改两个 state 构造 helper 而不是逐测试改 | 20 项共用两个 helper，改动面从 20 处降到 2 处 | 族 A | 提议 |
| 005 | 直连 client helper 放 `http-client` 的 `test_support`，不新建 crate | 相关包都已依赖它；新建 crate 违反"不增设施"约束 | 族 B | 提议 |
| 006 | F 族在拿到稳定复现率前不动 | 时序问题最容易被"加超时"掩盖成假绿 | 族 F | 提议 |
| 007 | external migration 的产品侧超时缺陷另立任务 | 那是真实产品缺陷，不属于测试维护范围 | 族 G-2 | 提议 |
