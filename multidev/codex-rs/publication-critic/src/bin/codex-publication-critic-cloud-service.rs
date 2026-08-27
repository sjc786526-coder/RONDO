//! Explicit launcher for the cloud reference scorer backend.
//!
//! Selecting this backend means running this binary with a validated cloud descriptor. No other
//! Publication Critic entry point reads a cloud credential, resolves a provider endpoint, or
//! sends provider traffic, so the product stays default-off until this launcher is used.

use clap::Parser;
use codex_publication_critic::CloudPublicationScorer;
use codex_publication_critic::CloudScorerConfig;
use codex_publication_critic::CloudScorerDescriptor;
use codex_publication_critic::DEFAULT_FORCE_SHUTDOWN_TIMEOUT;
use codex_publication_critic::DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT;
use codex_publication_critic::ServiceConfig;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::serve;
use std::error::Error;
use std::io::Write;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use thiserror::Error;
use tokio::net::TcpListener;

const MAX_DESCRIPTOR_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Parser)]
struct Args {
    #[arg(long, default_value = "127.0.0.1:0")]
    listen: SocketAddr,
    #[arg(long)]
    descriptor: PathBuf,
    #[arg(long, default_value_t = default_graceful_shutdown_ms())]
    graceful_shutdown_ms: u64,
    #[arg(long, default_value_t = default_force_shutdown_ms())]
    force_shutdown_ms: u64,
}

fn default_graceful_shutdown_ms() -> u64 {
    DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT
        .as_secs()
        .saturating_mul(1_000)
}

fn default_force_shutdown_ms() -> u64 {
    DEFAULT_FORCE_SHUTDOWN_TIMEOUT
        .as_secs()
        .saturating_mul(1_000)
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
enum LaunchError {
    #[error("publication critic cloud service requires a loopback listener")]
    NonLoopbackListener,
    #[error("publication critic cloud service descriptor is invalid")]
    InvalidDescriptor,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse();
    if !args.listen.ip().is_loopback() {
        return Err(LaunchError::NonLoopbackListener.into());
    }
    let descriptor: CloudScorerDescriptor = read_json_file(&args.descriptor)?;
    descriptor
        .validate()
        .map_err(|_| LaunchError::InvalidDescriptor)?;
    let service_descriptor = descriptor.service_descriptor().clone();
    // Fail closed before the listener exists: an unusable credential must never look like a
    // service that is merely unhealthy.
    let scorer = CloudPublicationScorer::new(CloudScorerConfig::from_process_env(descriptor)?)?;

    let listener = TcpListener::bind(args.listen).await?;
    let announcement = StartupAnnouncement {
        protocol: codex_publication_critic::ProtocolVersion::RondoPublicationCriticV1,
        endpoint: listener.local_addr()?,
        descriptor: service_descriptor.clone(),
    };
    println!("{}", serde_json::to_string(&announcement)?);
    std::io::stdout().flush()?;
    eprintln!("publication_critic_cloud_service_listening");

    serve(
        listener,
        ServiceConfig::new(
            service_descriptor,
            Duration::from_millis(args.graceful_shutdown_ms),
            Duration::from_millis(args.force_shutdown_ms),
        )?,
        scorer,
    )
    .await?;
    eprintln!("publication_critic_cloud_service_stopped");
    Ok(())
}

fn read_json_file<T>(path: &Path) -> Result<T, LaunchError>
where
    T: for<'de> serde::Deserialize<'de>,
{
    let metadata = std::fs::symlink_metadata(path).map_err(|_| LaunchError::InvalidDescriptor)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_DESCRIPTOR_BYTES
    {
        return Err(LaunchError::InvalidDescriptor);
    }
    let body = std::fs::read(path).map_err(|_| LaunchError::InvalidDescriptor)?;
    serde_json::from_slice(&body).map_err(|_| LaunchError::InvalidDescriptor)
}
