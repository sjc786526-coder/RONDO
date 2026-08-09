use std::sync::Arc;
use std::sync::Mutex;

use clap::Parser;
use codex_mcp::McpOAuthScopesSource;
use codex_mcp::ResolvedMcpOAuthScopes;
use codex_rmcp_client::BrowserLaunch;
use codex_rmcp_client::OAuthProviderError;
use pretty_assertions::assert_eq;

use super::LoginArgs;
use super::perform_mcp_login_from_args_with;

#[tokio::test]
async fn mcp_login_no_open_browser_propagates_launch_false() {
    let args = LoginArgs::try_parse_from(["login", "managed-server", "--no-open-browser"])
        .expect("parse MCP login arguments");
    let resolved_scopes = ResolvedMcpOAuthScopes {
        scopes: vec!["discovered-scope".to_string()],
        source: McpOAuthScopesSource::Discovered,
    };
    let attempts = Arc::new(Mutex::new(Vec::new()));
    let recorded_attempts = Arc::clone(&attempts);

    perform_mcp_login_from_args_with(&args, &resolved_scopes, move |scopes, browser_launch| {
        let recorded_attempts = Arc::clone(&recorded_attempts);
        async move {
            let attempt_number = {
                let mut attempts = recorded_attempts.lock().expect("lock recorded attempts");
                attempts.push((scopes, browser_launch));
                attempts.len()
            };

            if attempt_number == 1 {
                Err(anyhow::Error::new(OAuthProviderError::new(
                    Some("invalid_scope".to_string()),
                    Some("fixture rejects discovered scopes".to_string()),
                )))
            } else {
                Ok(())
            }
        }
    })
    .await
    .expect("retry without scopes should succeed");

    assert_eq!(
        *attempts.lock().expect("lock recorded attempts"),
        vec![
            (
                vec!["discovered-scope".to_string()],
                BrowserLaunch::Disabled,
            ),
            (Vec::new(), BrowserLaunch::Disabled),
        ]
    );
}
