//! One-shot, eval/reference-only scalar observation for the cloud scorer.
//!
//! The product service and client intentionally expose only a verdict. This binary is the explicit
//! Plan 096 seam: it reads one bounded packet from stdin, runs the same cloud scorer once, and
//! writes one body-free JSON observation. It never accepts a credential argument; the validated
//! descriptor names the single environment variable the launching context may inject.

use clap::Parser;
use codex_publication_critic::CloudEvaluationObservation;
use codex_publication_critic::CloudPublicationScorer;
use codex_publication_critic::CloudScorerConfig;
use codex_publication_critic::CloudScorerDescriptor;
use codex_publication_critic::PublicationPacket;
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
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
enum EvalError {
    #[error("publication critic cloud eval descriptor is invalid")]
    Descriptor,
    #[error("publication critic cloud eval packet is invalid")]
    Packet,
    #[error("publication critic cloud eval configuration is invalid")]
    Configuration,
}

impl EvalError {
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
            "publication_critic_cloud_eval_failed code={}",
            failure.code()
        );
        std::process::exit(1);
    }
}

async fn run(args: Args) -> Result<(), EvalError> {
    let descriptor: CloudScorerDescriptor = read_json_file(&args.descriptor)?;
    descriptor.validate().map_err(|_| EvalError::Descriptor)?;
    let packet = read_stdin_packet().await?;
    if packet.qualification != descriptor.service_descriptor().identity.qualification {
        return Err(EvalError::Packet);
    }

    let scorer = CloudPublicationScorer::new(
        CloudScorerConfig::from_process_env(descriptor).map_err(|_| EvalError::Configuration)?,
    )
    .map_err(|_| EvalError::Configuration)?;
    let observation = scorer
        .score_for_evaluation(packet)
        .await
        .map_err(|_| EvalError::Packet)?;
    write_observation(&observation)
}

async fn read_stdin_packet() -> Result<PublicationPacket, EvalError> {
    let mut body = Vec::new();
    tokio::io::stdin()
        .take(MAX_PACKET_BYTES + 1)
        .read_to_end(&mut body)
        .await
        .map_err(|_| EvalError::Packet)?;
    let body_len = u64::try_from(body.len()).map_err(|_| EvalError::Packet)?;
    if body.is_empty() || body_len > MAX_PACKET_BYTES {
        return Err(EvalError::Packet);
    }
    let packet: PublicationPacket = serde_json::from_slice(&body).map_err(|_| EvalError::Packet)?;
    packet.validate().map_err(|_| EvalError::Packet)?;
    Ok(packet)
}

fn read_json_file(path: &Path) -> Result<CloudScorerDescriptor, EvalError> {
    let metadata = std::fs::symlink_metadata(path).map_err(|_| EvalError::Descriptor)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_DESCRIPTOR_BYTES
    {
        return Err(EvalError::Descriptor);
    }
    let body = std::fs::read(path).map_err(|_| EvalError::Descriptor)?;
    serde_json::from_slice(&body).map_err(|_| EvalError::Descriptor)
}

fn write_observation(observation: &CloudEvaluationObservation) -> Result<(), EvalError> {
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    serde_json::to_writer(&mut stdout, observation).map_err(|_| EvalError::Configuration)?;
    stdout
        .write_all(b"\n")
        .and_then(|()| stdout.flush())
        .map_err(|_| EvalError::Configuration)
}
