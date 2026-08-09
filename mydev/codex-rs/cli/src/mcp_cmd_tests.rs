use clap::Parser;
use codex_rmcp_client::BrowserLaunch;
use pretty_assertions::assert_eq;

use super::LoginArgs;

#[test]
fn mcp_login_no_open_browser_propagates_launch_false() {
    let args = LoginArgs::try_parse_from(["login", "managed-server", "--no-open-browser"])
        .expect("parse MCP login arguments");

    assert_eq!(args.browser_launch(), BrowserLaunch::Disabled);
}
