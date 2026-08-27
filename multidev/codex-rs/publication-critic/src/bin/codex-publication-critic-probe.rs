use clap::Args as ClapArgs;
use clap::Parser;
use clap::Subcommand;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::CloudScorerDescriptor;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::RealScorerDescriptor;
use codex_publication_critic::ServiceDescriptor;
use serde::Serialize;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

const MAX_INPUT_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Parser)]
struct Args {
    #[arg(long)]
    endpoint: SocketAddr,
    #[command(flatten)]
    expected: ExpectedDescriptor,
    #[arg(long, default_value_t = 30_000)]
    call_timeout_ms: u64,
    #[arg(long, default_value_t = 60_000)]
    startup_timeout_ms: u64,
    #[command(subcommand)]
    command: ProbeCommand,
}

/// Exactly one backend descriptor names the service this probe expects to be talking to.
#[derive(Debug, ClapArgs)]
#[group(required = true, multiple = false)]
struct ExpectedDescriptor {
    #[arg(long)]
    expected_descriptor: Option<PathBuf>,
    #[arg(long)]
    expected_cloud_descriptor: Option<PathBuf>,
}

impl ExpectedDescriptor {
    fn resolve(&self) -> Result<ServiceDescriptor, ProbeFailure> {
        if let Some(path) = &self.expected_descriptor {
            let descriptor: RealScorerDescriptor =
                read_json_file(path, ProbeFailure::InvalidDescriptor)?;
            descriptor
                .validate()
                .map_err(|_| ProbeFailure::InvalidDescriptor)?;
            return Ok(descriptor.service_descriptor().clone());
        }
        let path = self
            .expected_cloud_descriptor
            .as_ref()
            .ok_or(ProbeFailure::InvalidDescriptor)?;
        let descriptor: CloudScorerDescriptor =
            read_json_file(path, ProbeFailure::InvalidDescriptor)?;
        descriptor
            .validate()
            .map_err(|_| ProbeFailure::InvalidDescriptor)?;
        Ok(descriptor.service_descriptor().clone())
    }
}

#[derive(Debug, Subcommand)]
enum ProbeCommand {
    Liveness,
    Ready,
    Review {
        #[arg(long)]
        packet: PathBuf,
    },
    Cancel {
        #[arg(long)]
        packet: PathBuf,
        #[arg(long, default_value_t = 100)]
        cancel_after_ms: u64,
    },
    Shutdown,
}

#[derive(Clone, Copy, Debug)]
enum ProbeFailure {
    InvalidDescriptor,
    InvalidPacket,
    InvalidConfiguration,
    Critic(CriticFailure),
    CancellationDidNotWin,
}

impl ProbeFailure {
    fn code(self) -> &'static str {
        match self {
            Self::InvalidDescriptor => "invalid_descriptor",
            Self::InvalidPacket => "invalid_packet",
            Self::InvalidConfiguration => "invalid_configuration",
            Self::Critic(failure) => failure.log_code(),
            Self::CancellationDidNotWin => "cancellation_did_not_win",
        }
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct ProbeOutput<T> {
    operation: &'static str,
    result: T,
}

#[tokio::main]
async fn main() {
    if let Err(failure) = run(Args::parse()).await {
        eprintln!("publication_critic_probe_failed code={}", failure.code());
        std::process::exit(1);
    }
}

async fn run(args: Args) -> Result<(), ProbeFailure> {
    let expected = args.expected.resolve()?;
    let client = PublicationCriticClient::new(
        ClientConfig::new(
            args.endpoint,
            expected,
            Duration::from_millis(args.call_timeout_ms),
            Duration::from_millis(args.startup_timeout_ms),
        )
        .map_err(|_| ProbeFailure::InvalidConfiguration)?,
    )
    .map_err(|_| ProbeFailure::InvalidConfiguration)?;

    match args.command {
        ProbeCommand::Liveness => {
            let status = client.liveness().await.map_err(ProbeFailure::Critic)?;
            print_output(ProbeOutput {
                operation: "liveness",
                result: status,
            })
        }
        ProbeCommand::Ready => {
            client
                .wait_until_ready(CancellationToken::new())
                .await
                .map_err(ProbeFailure::Critic)?;
            print_output(ProbeOutput {
                operation: "ready",
                result: "ready",
            })
        }
        ProbeCommand::Review { packet } => {
            let packet = read_packet(&packet)?;
            let verdict = client.review(packet).await.map_err(ProbeFailure::Critic)?;
            print_output(ProbeOutput {
                operation: "review",
                result: verdict,
            })
        }
        ProbeCommand::Cancel {
            packet,
            cancel_after_ms,
        } => {
            if cancel_after_ms == 0 {
                return Err(ProbeFailure::InvalidConfiguration);
            }
            let packet = read_packet(&packet)?;
            let cancellation = CancellationToken::new();
            let cancel_after = cancellation.clone();
            tokio::spawn(async move {
                tokio::time::sleep(Duration::from_millis(cancel_after_ms)).await;
                cancel_after.cancel();
            });
            match client.review_with_cancellation(packet, cancellation).await {
                Err(CriticFailure::Cancelled) => print_output(ProbeOutput {
                    operation: "cancel",
                    result: "cancelled",
                }),
                Ok(_) | Err(_) => Err(ProbeFailure::CancellationDidNotWin),
            }
        }
        ProbeCommand::Shutdown => {
            client.shutdown().await.map_err(ProbeFailure::Critic)?;
            print_output(ProbeOutput {
                operation: "shutdown",
                result: "accepted",
            })
        }
    }
}

fn read_packet(path: &Path) -> Result<PublicationPacket, ProbeFailure> {
    let packet: PublicationPacket = read_json_file(path, ProbeFailure::InvalidPacket)?;
    packet.validate().map_err(|_| ProbeFailure::InvalidPacket)?;
    Ok(packet)
}

fn read_json_file<T>(path: &Path, failure: ProbeFailure) -> Result<T, ProbeFailure>
where
    T: for<'de> serde::Deserialize<'de>,
{
    let metadata = std::fs::symlink_metadata(path).map_err(|_| failure)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_INPUT_BYTES
    {
        return Err(failure);
    }
    let body = std::fs::read(path).map_err(|_| failure)?;
    serde_json::from_slice(&body).map_err(|_| failure)
}

fn print_output<T>(value: ProbeOutput<T>) -> Result<(), ProbeFailure>
where
    T: Serialize,
{
    let body = serde_json::to_string(&value).map_err(|_| ProbeFailure::InvalidConfiguration)?;
    println!("{body}");
    Ok(())
}
