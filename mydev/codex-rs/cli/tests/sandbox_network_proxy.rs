#![cfg(target_os = "linux")]

use std::net::TcpListener;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use tempfile::TempDir;

const BWRAP_UNAVAILABLE_ERR: &str = "bubblewrap is unavailable";
const MAX_REQUEST_HEAD_BYTES: usize = 64 * 1024;

/// Consume the request head so the socket can be closed without resetting the peer.
///
/// The proxied request is a bodyless GET, so the head is everything the client
/// sends; stopping at the blank line keeps this from blocking on a half-open
/// connection. The read timeout and size limit keep a broken fixture bounded.
fn drain_request_head(stream: &mut std::net::TcpStream) -> std::io::Result<()> {
    let mut request = Vec::new();
    let mut chunk = [0u8; 1024];
    while !request.windows(4).any(|window| window == b"\r\n\r\n") {
        match std::io::Read::read(stream, &mut chunk) {
            Ok(0) => {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::UnexpectedEof,
                    "loopback request ended before its header was complete",
                ));
            }
            Ok(read) => {
                request.extend_from_slice(&chunk[..read]);
                if request.len() > MAX_REQUEST_HEAD_BYTES {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::InvalidData,
                        "loopback request header exceeded fixture limit",
                    ));
                }
            }
            Err(err) if err.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(err) => return Err(err),
        }
    }
    Ok(())
}

#[test]
fn sandbox_with_network_proxy_blocks_direct_loopback_access() -> Result<()> {
    let codex_home = TempDir::new()?;
    let listener = TcpListener::bind("127.0.0.2:0")?;
    let port = listener.local_addr()?.port();
    std::fs::write(
        codex_home.path().join("config.toml"),
        r#"
default_permissions = "network-test"

[features]
network_proxy = true
use_legacy_landlock = true

[permissions.network-test]
extends = ":workspace"

[permissions.network-test.network]
enabled = true
mode = "full"
"#,
    )?;

    let url = format!("http://127.0.0.2:{port}/");
    let output = std::process::Command::new(codex_utils_cargo_bin::cargo_bin("codex")?)
        .env("CODEX_HOME", codex_home.path())
        .args([
            "sandbox",
            "--permission-profile",
            "network-test",
            "--",
            "curl",
            "--noproxy",
            "*",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "1",
            "--max-time",
            "2",
            url.as_str(),
        ])
        .output()?;

    let stderr = String::from_utf8_lossy(&output.stderr);
    if stderr.contains(BWRAP_UNAVAILABLE_ERR) {
        eprintln!("skipping network proxy sandbox test: bubblewrap is unavailable");
        return Ok(());
    }

    assert_eq!(
        output.status.code(),
        Some(7),
        "expected direct loopback access to be blocked; status={:?}; stdout={}; stderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        stderr,
    );

    Ok(())
}

#[test]
fn sandbox_with_network_proxy_allows_explicit_loopback_access() -> Result<()> {
    let codex_home = TempDir::new()?;
    let listener = TcpListener::bind("127.0.0.2:0")?;
    let port = listener.local_addr()?.port();
    listener.set_nonblocking(true)?;
    let server = std::thread::spawn(move || -> std::io::Result<()> {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    // Read the request before replying. Closing a socket whose receive
                    // queue still holds unread bytes makes the kernel send RST instead
                    // of FIN, and the proxy can observe that reset while it is still
                    // reading this response. It then reports an upstream failure and
                    // answers curl with 502 even though the target was allowlisted and
                    // a 204 had already been written.
                    stream.set_nonblocking(false)?;
                    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                    drain_request_head(&mut stream)?;
                    std::io::Write::write_all(
                        &mut stream,
                        b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n",
                    )?;
                    std::io::Write::flush(&mut stream)?;
                    // Half-close so the peer sees an orderly FIN for the response.
                    stream.shutdown(std::net::Shutdown::Write)?;
                    return Ok(());
                }
                Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                    if Instant::now() >= deadline {
                        return Err(std::io::Error::new(
                            std::io::ErrorKind::TimedOut,
                            "timed out waiting for allowlisted loopback request",
                        ));
                    }
                    std::thread::sleep(Duration::from_millis(10));
                }
                Err(err) => return Err(err),
            }
        }
    });
    std::fs::write(
        codex_home.path().join("config.toml"),
        r#"
default_permissions = "network-test"

[features]
network_proxy = true
use_legacy_landlock = true

[permissions.network-test]
extends = ":workspace"

[permissions.network-test.network]
enabled = true
mode = "full"
allow_local_binding = false

[permissions.network-test.network.domains]
"127.0.0.2" = "allow"
"#,
    )?;

    let url = format!("http://127.0.0.2:{port}/");
    let output = std::process::Command::new(codex_utils_cargo_bin::cargo_bin("codex")?)
        .env("CODEX_HOME", codex_home.path())
        .args([
            "sandbox",
            "--permission-profile",
            "network-test",
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "2",
            "--max-time",
            "4",
            url.as_str(),
        ])
        .output()?;

    let stderr = String::from_utf8_lossy(&output.stderr);
    if stderr.contains(BWRAP_UNAVAILABLE_ERR) {
        eprintln!("skipping network proxy sandbox test: bubblewrap is unavailable");
        return Ok(());
    }

    assert!(
        output.status.success(),
        "expected allowlisted loopback access to succeed; status={:?}; stdout={}; stderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        stderr,
    );
    server.join().expect("loopback server panicked")?;

    Ok(())
}
