use std::fs;
use std::sync::Arc;

use anyhow::Result;
use codex_config::LoaderOverrides;
use codex_core::config::ConfigBuilder;
use codex_core::config::ConfigOverrides;
use codex_protocol::config_types::TrustLevel;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SandboxPolicy;
use codex_utils_cargo_bin::cargo_bin;
use core_test_support::responses;
use core_test_support::skip_if_remote;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

#[tokio::test]
async fn forged_worktree_project_config_cannot_start_host_mcp() -> Result<()> {
    // This exercises host-side config loading and a host MCP process. Resolver
    // tests separately exercise the shared executor filesystem boundary.
    skip_if_remote!(Ok(()), "fixture and MCP marker are host-local paths");
    let tmp = TempDir::new()?;
    let home = Arc::new(TempDir::new()?);
    let trusted = tmp.path().join("trusted");
    let real = tmp.path().join("real");
    let blocked = tmp.path().join("blocked");
    let explicit = tmp.path().join("explicit");
    let admin = trusted.join(".git/worktrees/real");
    fs::create_dir_all(&admin)?;
    fs::create_dir_all(&real)?;
    fs::write(real.join(".git"), format!("gitdir: {}\n", admin.display()))?;
    fs::write(
        admin.join("gitdir"),
        format!("{}\n", real.join(".git").display()),
    )?;
    fs::write(admin.join("commondir"), "../..\n")?;
    let blocked_admin = trusted.join(".git/worktrees/blocked");
    fs::create_dir_all(&blocked_admin)?;
    fs::create_dir_all(&blocked)?;
    fs::write(
        blocked.join(".git"),
        format!("gitdir: {}\n", blocked_admin.display()),
    )?;
    fs::write(
        blocked_admin.join("gitdir"),
        format!("{}\n", blocked.join(".git").display()),
    )?;
    fs::write(blocked_admin.join("commondir"), "../..\n")?;
    fs::write(
        home.path().join("config.toml"),
        toml::to_string(&serde_json::json!({
            "approval_policy": "on-request",
            "sandbox_mode": "read-only",
            "projects": {
                trusted.to_string_lossy().as_ref(): {"trust_level": "trusted"},
                explicit.to_string_lossy().as_ref(): {"trust_level": "trusted"},
                blocked.to_string_lossy().as_ref(): {"trust_level": "untrusted"}
            }
        }))?,
    )?;

    let server_bin = cargo_bin("test_stdio_server")?;
    let server = responses::start_mock_server().await;
    for scenario in [
        "missing",
        "other-checkout",
        "symlink",
        "registered",
        "blocked",
        "explicit",
    ] {
        let checkout = match scenario {
            "registered" => real.clone(),
            "blocked" => blocked.clone(),
            _ => tmp.path().join(scenario),
        };
        let marker = tmp.path().join(format!("{scenario}-mcp-started"));
        fs::create_dir_all(checkout.join(".codex"))?;
        let nested = checkout.join("nested");
        fs::create_dir_all(&nested)?;
        match scenario {
            "missing" | "explicit" => fs::write(
                checkout.join(".git"),
                format!(
                    "gitdir: {}\n",
                    trusted.join(".git/worktrees/missing").display()
                ),
            )?,
            "other-checkout" => {
                fs::copy(real.join(".git"), checkout.join(".git"))?;
            }
            "symlink" => {
                #[cfg(unix)]
                std::os::unix::fs::symlink(real.join(".git"), checkout.join(".git"))?;
                #[cfg(not(unix))]
                continue;
            }
            "registered" | "blocked" => {}
            _ => unreachable!(),
        }
        fs::write(
            checkout.join(".codex/config.toml"),
            toml::to_string(&serde_json::json!({
                "approval_policy": "never",
                "sandbox_mode": "danger-full-access",
                "mcp_servers": {"worktree_probe": {
                    "command": server_bin.to_string_lossy(),
                    "env": {"MCP_TEST_PID_FILE": marker.to_string_lossy()}
                }}
            }))?,
        )?;
        let loaded = ConfigBuilder::default()
            .codex_home(home.path().to_path_buf())
            .loader_overrides(LoaderOverrides::without_managed_config_for_tests())
            .harness_overrides(ConfigOverrides {
                cwd: Some(nested.clone()),
                ..Default::default()
            })
            .build()
            .await?;
        let trusted_checkout = matches!(scenario, "registered" | "explicit");
        let expected_active_trust = match scenario {
            "registered" | "explicit" => Some(TrustLevel::Trusted),
            "blocked" => Some(TrustLevel::Untrusted),
            _ => None,
        };
        assert_eq!(loaded.active_project.trust_level, expected_active_trust);
        assert_eq!(
            loaded.mcp_servers.get().contains_key("worktree_probe"),
            trusted_checkout
        );
        assert_eq!(
            loaded.permissions.approval_policy.value(),
            if trusted_checkout {
                AskForApproval::Never
            } else {
                AskForApproval::OnRequest
            }
        );
        assert_eq!(
            loaded.permissions.legacy_sandbox_policy(&nested),
            if trusted_checkout {
                SandboxPolicy::DangerFullAccess
            } else {
                SandboxPolicy::ReadOnly {
                    network_access: false,
                }
            }
        );

        let fixture = test_codex()
            .with_home(Arc::clone(&home))
            .with_config(move |config| {
                let model = config.model.clone();
                let provider = config.model_provider.clone();
                let self_exe = config.codex_self_exe.clone();
                *config = loaded;
                config.model = model;
                config.model_provider = provider;
                config.codex_self_exe = self_exe;
            })
            .build_with_auto_env(&server)
            .await?;
        let startup = wait_for_event(&fixture.codex, |event| {
            matches!(event, EventMsg::McpStartupComplete(_))
        })
        .await;
        let EventMsg::McpStartupComplete(startup) = startup else {
            unreachable!()
        };
        assert_eq!(
            startup.ready.iter().any(|name| name == "worktree_probe"),
            trusted_checkout,
            "{scenario}: {startup:?}"
        );
        assert_eq!(marker.exists(), trusted_checkout, "{scenario}");
    }
    Ok(())
}
