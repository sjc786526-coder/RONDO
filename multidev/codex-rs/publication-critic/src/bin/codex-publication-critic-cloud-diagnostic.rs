//! One-shot, eval-only Plan 100 diagnostic observation.
//!
//! This binary reads one bounded publication packet from stdin, selects one of the three strict
//! output contracts, and runs the existing cloud scorer provider path once. Credentials remain
//! descriptor-selected process environment only; neither arguments nor output can carry them.

use clap::Parser;
use codex_publication_critic::CloudDiagnosticTask;
use codex_publication_critic::CloudDiagnosticThinking;
use codex_publication_critic::CloudPublicationScorer;
use codex_publication_critic::CloudScorerConfig;
use codex_publication_critic::CloudScorerDescriptor;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::diagnostic_messages;
use serde::Serialize;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use thiserror::Error;
use tokio::io::AsyncReadExt;

const MAX_DESCRIPTOR_BYTES: u64 = 1024 * 1024;
const MAX_PACKET_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Parser)]
struct Args {
    #[arg(long)]
    descriptor: PathBuf,
    #[arg(long)]
    task: CloudDiagnosticTask,
    /// Eval-only thinking switch. Product scoring never uses this flag.
    #[arg(long, default_value = "disabled")]
    thinking: CloudDiagnosticThinking,
    /// Render the exact provider-visible messages without loading credentials or sending HTTP.
    #[arg(long)]
    render_messages: bool,
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
enum DiagnosticError {
    #[error("publication critic cloud diagnostic descriptor is invalid")]
    Descriptor,
    #[error("publication critic cloud diagnostic packet is invalid")]
    Packet,
    #[error("publication critic cloud diagnostic configuration is invalid")]
    Configuration,
}

impl DiagnosticError {
    fn code(self) -> &'static str {
        match self {
            Self::Descriptor => "invalid_descriptor",
            Self::Packet => "invalid_packet",
            Self::Configuration => "invalid_configuration",
        }
    }
}

#[tokio::main]
async fn main() {
    if let Err(failure) = run(Args::parse()).await {
        eprintln!(
            "publication_critic_cloud_diagnostic_failed code={}",
            failure.code()
        );
        std::process::exit(1);
    }
}

async fn run(args: Args) -> Result<(), DiagnosticError> {
    let descriptor: CloudScorerDescriptor = read_json_file(&args.descriptor)?;
    descriptor
        .validate()
        .map_err(|_| DiagnosticError::Descriptor)?;
    let packet = read_stdin_packet().await?;
    if packet.qualification != descriptor.service_descriptor().identity.qualification {
        return Err(DiagnosticError::Packet);
    }
    if args.render_messages {
        let messages = diagnostic_messages(&packet, args.task).ok_or(DiagnosticError::Packet)?;
        return write_json(&messages);
    }

    let scorer = CloudPublicationScorer::new(
        CloudScorerConfig::from_process_env(descriptor)
            .map_err(|_| DiagnosticError::Configuration)?,
    )
    .map_err(|_| DiagnosticError::Configuration)?;
    let observation = scorer
        .score_for_diagnostic(packet, args.task, args.thinking)
        .await
        .map_err(|_| DiagnosticError::Packet)?;
    write_json(&observation)
}

async fn read_stdin_packet() -> Result<PublicationPacket, DiagnosticError> {
    let mut body = Vec::new();
    tokio::io::stdin()
        .take(MAX_PACKET_BYTES + 1)
        .read_to_end(&mut body)
        .await
        .map_err(|_| DiagnosticError::Packet)?;
    let body_len = u64::try_from(body.len()).map_err(|_| DiagnosticError::Packet)?;
    if body.is_empty() || body_len > MAX_PACKET_BYTES {
        return Err(DiagnosticError::Packet);
    }
    let packet: PublicationPacket =
        serde_json::from_slice(&body).map_err(|_| DiagnosticError::Packet)?;
    packet.validate().map_err(|_| DiagnosticError::Packet)?;
    Ok(packet)
}

fn read_json_file(path: &Path) -> Result<CloudScorerDescriptor, DiagnosticError> {
    let metadata = std::fs::symlink_metadata(path).map_err(|_| DiagnosticError::Descriptor)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_DESCRIPTOR_BYTES
    {
        return Err(DiagnosticError::Descriptor);
    }
    let body = std::fs::read(path).map_err(|_| DiagnosticError::Descriptor)?;
    serde_json::from_slice(&body).map_err(|_| DiagnosticError::Descriptor)
}

fn write_json(value: &impl Serialize) -> Result<(), DiagnosticError> {
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    serde_json::to_writer(&mut stdout, value).map_err(|_| DiagnosticError::Configuration)?;
    stdout
        .write_all(b"\n")
        .and_then(|()| stdout.flush())
        .map_err(|_| DiagnosticError::Configuration)
}
