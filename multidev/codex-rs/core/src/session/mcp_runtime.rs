//! Thread MCP runtime projection and publication.
//!
//! This module owns the small correctness boundary between immutable session
//! inputs and the mutable [`codex_mcp::McpRuntime`]. Background scheduling
//! belongs elsewhere.

use super::session::SessionConfiguration;
use super::*;
use crate::mcp::McpRuntimeProjection;
use codex_config::McpServerTransportConfig;
use codex_mcp::EffectiveMcpServer;
use codex_mcp::ElicitationReviewerHandle;
use codex_mcp::PreparedMcpCall;
use codex_protocol::capabilities::SelectedCapabilityRoot;

pub(super) struct McpDesiredState {
    pub(super) config: Arc<Config>,
    pub(super) auth: Option<CodexAuth>,
    pub(super) submit_id: String,
    pub(super) originator: String,
    pub(super) session_source: SessionSource,
    pub(super) environments: TurnEnvironmentSnapshot,
    pub(super) windows_sandbox_level: WindowsSandboxLevel,
    pub(super) writer_workspace_binding_active: bool,
}

impl McpDesiredState {
    pub(super) fn local_stdio_fallback_cwd(&self) -> PathBuf {
        self.environments
            .primary()
            .and_then(|environment| environment.cwd().to_abs_path().ok())
            .map(|cwd| cwd.to_path_buf())
            .unwrap_or_else(|| self.config.cwd.to_path_buf())
    }
}

impl Session {
    /// Waits on this session's refreshed server before tool execution is admitted.
    pub(crate) async fn wait_for_mcp_server(self: &Arc<Self>, server: &str) {
        self.refresh_mcp_if_dirty().await;
        self.services
            .mcp_runtime
            .wait_for_server_startup(server)
            .await;
    }

    /// Captures this session's current MCP client and catalog for one tool call.
    pub(crate) async fn prepare_mcp_call(
        self: &Arc<Self>,
        server: &str,
        tool: &str,
    ) -> Option<PreparedMcpCall> {
        self.refresh_mcp_if_dirty().await;
        self.services
            .mcp_runtime
            .current_binding_for_call(server)
            .await?
            .prepare_call(server, tool)
    }

    pub(super) async fn latest_mcp_desired_state(
        &self,
        auth: Option<CodexAuth>,
    ) -> McpDesiredState {
        let session_configuration = {
            let state = self.state.lock().await;
            state.session_configuration.clone()
        };
        let environments = self.services.turn_environments.snapshot().await;
        let cwd = environments
            .primary()
            .and_then(|environment| environment.cwd().to_abs_path().ok())
            .unwrap_or_else(|| session_configuration.cwd().clone());
        let config = Self::build_per_turn_config(&session_configuration, cwd);

        McpDesiredState {
            config: Arc::new(config),
            auth,
            submit_id: self.next_internal_sub_id(),
            originator: session_configuration.originator.clone(),
            session_source: session_configuration.session_source.clone(),
            environments,
            windows_sandbox_level: session_configuration.windows_sandbox_level,
            writer_workspace_binding_active: session_configuration
                .writer_workspace_binding
                .is_some(),
        }
    }

    pub(super) async fn install_initial_mcp_runtime(
        self: &Arc<Self>,
        session_configuration: &SessionConfiguration,
        auth: Option<CodexAuth>,
        mcp_projection: McpRuntimeProjection,
        resolved_environments: &TurnEnvironmentSnapshot,
        local_stdio_fallback_cwd: PathBuf,
    ) -> anyhow::Result<()> {
        let cwd = AbsolutePathBuf::from_absolute_path(local_stdio_fallback_cwd)
            .unwrap_or_else(|_| session_configuration.cwd().clone());
        let config = Self::build_per_turn_config(session_configuration, cwd);
        let desired = McpDesiredState {
            config: Arc::new(config),
            auth,
            submit_id: INITIAL_SUBMIT_ID.to_owned(),
            originator: session_configuration.originator.clone(),
            session_source: session_configuration.session_source.clone(),
            environments: resolved_environments.clone(),
            windows_sandbox_level: session_configuration.windows_sandbox_level,
            writer_workspace_binding_active: session_configuration
                .writer_workspace_binding
                .is_some(),
        };
        self.publish_mcp_runtime(
            &desired,
            mcp_projection,
            /*ready_selected_capability_roots*/ &[],
            Some(self.mcp_elicitation_reviewer()),
        )
        .instrument(info_span!(
            "session_init.mcp_manager_init",
            otel.name = "session_init.mcp_manager_init",
        ))
        .await;

        self.services.mcp_runtime.validate_required_servers().await
    }

    #[tracing::instrument(name = "mcp.runtime.refresh", skip_all)]
    pub(super) async fn publish_mcp_runtime(
        &self,
        desired: &McpDesiredState,
        mcp_projection: McpRuntimeProjection,
        ready_selected_capability_roots: &[SelectedCapabilityRoot],
        elicitation_reviewer: Option<ElicitationReviewerHandle>,
    ) {
        let input = self.build_mcp_runtime_input(
            desired,
            mcp_projection,
            ready_selected_capability_roots,
            elicitation_reviewer,
        );
        self.services.mcp_runtime.replace(input).await;
    }

    pub(super) fn build_mcp_runtime_input(
        &self,
        desired: &McpDesiredState,
        mcp_projection: McpRuntimeProjection,
        ready_selected_capability_roots: &[SelectedCapabilityRoot],
        elicitation_reviewer: Option<ElicitationReviewerHandle>,
    ) -> McpRuntimeInput {
        let auth = desired.auth.clone();
        let McpRuntimeProjection {
            mut config,
            plugins_available,
        } = mcp_projection;
        config.approval_policy = desired.config.permissions.approval_policy.clone();
        config.permission_profile = desired.config.permissions.effective_permission_profile();
        config.approvals_reviewer = desired.config.approvals_reviewer;
        config.environment_cwds = desired
            .environments
            .turn_environments()
            .map(|environment| {
                (
                    environment.environment_id.clone(),
                    environment.cwd().clone(),
                )
            })
            .collect();
        config
            .environment_cwds
            .entry(codex_config::DEFAULT_MCP_SERVER_ENVIRONMENT_ID.to_string())
            .or_insert_with(|| PathUri::from_abs_path(&desired.config.cwd));
        let mcp_config = Arc::new(config);
        let mut mcp_servers = effective_mcp_servers(&mcp_config, auth.as_ref());
        filter_stdio_servers_for_writer_binding(
            &mut mcp_servers,
            desired.writer_workspace_binding_active,
        );
        let local_stdio_fallback_cwd = desired.local_stdio_fallback_cwd();
        let runtime_context = McpRuntimeContext::new(
            self.services.turn_environments.environment_manager(),
            local_stdio_fallback_cwd,
        );
        let codex_apps_auth_manager =
            codex_mcp::host_owned_codex_apps_enabled(&mcp_config, auth.as_ref())
                .then(|| Arc::clone(&self.services.auth_manager));

        McpRuntimeInput {
            config: mcp_config,
            plugins_available,
            ready_selected_capability_roots: ready_selected_capability_roots.to_vec(),
            mcp_servers,
            submit_id: desired.submit_id.clone(),
            tx_event: Some(self.get_tx_event()),
            startup_cancellation_token: CancellationToken::new(),
            runtime_context,
            codex_apps_tools_cache: self.services.mcp_manager.codex_apps_tools_cache(),
            tool_catalog_cache: self.services.mcp_manager.tool_catalog_cache(),
            codex_apps_tools_cache_key: connector_runtime_context_key(auth.as_ref()),
            client_mcp_extensions: self.services.client_mcp_extensions.clone(),
            auth,
            codex_apps_auth_manager,
            elicitation_reviewer,
            elicitation_lifecycle: Some(self.mcp_elicitation_lifecycle()),
        }
    }
}

/// Removes MCP transports that can start a filesystem-unconstrained process for a bound writer.
///
/// Local stdio servers are ordinary host child processes, while executor-owned stdio servers are
/// currently launched without a filesystem sandbox. Filtering the effective server set here keeps
/// either process from starting at all. Streamable HTTP servers do not start such a process and
/// remain subject to the MCP handler's explicit `readOnlyHint` call gate.
fn filter_stdio_servers_for_writer_binding(
    mcp_servers: &mut HashMap<String, EffectiveMcpServer>,
    writer_workspace_binding_active: bool,
) {
    if !writer_workspace_binding_active {
        return;
    }

    mcp_servers.retain(|_, server| {
        !matches!(
            &server.config().transport,
            McpServerTransportConfig::Stdio { .. }
        )
    });
}

#[cfg(test)]
mod tests {
    use super::filter_stdio_servers_for_writer_binding;
    use codex_config::DEFAULT_MCP_SERVER_ENVIRONMENT_ID;
    use codex_config::McpServerConfig;
    use codex_config::McpServerTransportConfig;
    use codex_mcp::EffectiveMcpServer;
    use std::collections::HashMap;

    fn server(environment_id: &str, transport: McpServerTransportConfig) -> EffectiveMcpServer {
        EffectiveMcpServer::configured(McpServerConfig {
            transport,
            auth: Default::default(),
            environment_id: environment_id.to_string(),
            enabled: true,
            required: false,
            supports_parallel_tool_calls: false,
            omit_tools_from: None,
            disabled_reason: None,
            startup_timeout_sec: None,
            tool_timeout_sec: None,
            default_tools_approval_mode: None,
            enabled_tools: None,
            disabled_tools: None,
            scopes: None,
            oauth: None,
            oauth_resource: None,
            tools: HashMap::new(),
        })
    }

    fn stdio_server(environment_id: &str) -> EffectiveMcpServer {
        server(
            environment_id,
            McpServerTransportConfig::Stdio {
                command: "test-mcp".to_string(),
                args: Vec::new(),
                env: None,
                env_vars: Vec::new(),
                cwd: None,
            },
        )
    }

    fn http_server() -> EffectiveMcpServer {
        server(
            DEFAULT_MCP_SERVER_ENVIRONMENT_ID,
            McpServerTransportConfig::StreamableHttp {
                url: "https://example.invalid/mcp".to_string(),
                bearer_token_env_var: None,
                http_headers: None,
                env_http_headers: None,
            },
        )
    }

    fn mixed_servers() -> HashMap<String, EffectiveMcpServer> {
        HashMap::from([
            (
                "local-stdio".to_string(),
                stdio_server(DEFAULT_MCP_SERVER_ENVIRONMENT_ID),
            ),
            ("executor-stdio".to_string(), stdio_server("executor")),
            ("http".to_string(), http_server()),
        ])
    }

    #[test]
    fn bound_writer_filters_local_and_executor_stdio_but_retains_http() {
        let mut servers = mixed_servers();

        filter_stdio_servers_for_writer_binding(
            &mut servers,
            /*writer_workspace_binding_active*/ true,
        );

        assert_eq!(servers.len(), 1);
        assert!(servers.contains_key("http"));
    }

    #[test]
    fn unbound_session_retains_all_mcp_transports() {
        let mut servers = mixed_servers();

        filter_stdio_servers_for_writer_binding(
            &mut servers,
            /*writer_workspace_binding_active*/ false,
        );

        assert_eq!(servers.len(), 3);
        assert!(servers.contains_key("local-stdio"));
        assert!(servers.contains_key("executor-stdio"));
        assert!(servers.contains_key("http"));
    }
}
