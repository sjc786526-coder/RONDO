use clap::Parser;
use clap::ValueEnum;
use codex_publication_critic::ComponentIdentity;
use codex_publication_critic::DEFAULT_FORCE_SHUTDOWN_TIMEOUT;
use codex_publication_critic::DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT;
use codex_publication_critic::ModelIdentity;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::PublicationScorer;
use codex_publication_critic::RawScorerOutput;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ScorerError;
use codex_publication_critic::ScorerProjection;
use codex_publication_critic::ScorerStatus;
use codex_publication_critic::ScoringContract;
use codex_publication_critic::ScoringIdentity;
use codex_publication_critic::ServiceConfig;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::controlled_test_descriptor;
use codex_publication_critic::serve;
use std::error::Error;
use std::io::Write;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::BufReader;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
enum ControlledBehavior {
    Fixed,
    BlockFirst,
    BackendFailureFirst,
    NanFirst,
    PositiveInfinityFirst,
    NegativeInfinityFirst,
    MultiScoreFirst,
    ModelDriftFirst,
    ScoringDriftFirst,
    StatusFailed,
    StatusModelDrift,
    StatusScoringDrift,
}

#[derive(Debug, Parser)]
struct Args {
    #[arg(long, default_value = "127.0.0.1:0")]
    listen: SocketAddr,
    #[arg(long, value_enum, default_value = "fixed")]
    behavior: ControlledBehavior,
    #[arg(long, default_value_t = 1)]
    affected_calls: usize,
    #[arg(long, default_value_t = 0.75)]
    score: f64,
    #[arg(long)]
    initially_unready: bool,
    #[arg(long, default_value_t = codex_publication_critic::DEFAULT_REQUEST_BYTES)]
    request_bytes: u32,
    #[arg(long, default_value_t = codex_publication_critic::DEFAULT_RESPONSE_BYTES)]
    response_bytes: u32,
    #[arg(long, default_value_t = codex_publication_critic::DEFAULT_MAX_CONCURRENCY)]
    max_concurrency: u16,
    #[arg(long, default_value_t = codex_publication_critic::DEFAULT_QUEUE_CAPACITY)]
    queue_capacity: u16,
    #[arg(long, default_value_t = 25_000)]
    job_timeout_ms: u64,
    #[arg(long, default_value_t = 2_000)]
    io_timeout_ms: u64,
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

#[derive(Clone)]
struct ControlledScorer {
    inner: Arc<ControlledScorerInner>,
}

struct ControlledScorerInner {
    model: ModelIdentity,
    scoring: ScoringContract,
    drifted_model: ModelIdentity,
    drifted_scoring: ScoringContract,
    behavior: ControlledBehavior,
    affected_calls: usize,
    score: f64,
    calls: AtomicUsize,
    ready: AtomicBool,
    release_gate: CancellationToken,
}

impl ControlledScorer {
    fn set_ready(&self) {
        self.inner.ready.store(true, Ordering::Release);
    }

    fn release(&self) {
        self.inner.release_gate.cancel();
    }
}

struct BlockedCallGuard {
    call: usize,
    completed: bool,
}

impl Drop for BlockedCallGuard {
    fn drop(&mut self) {
        if !self.completed {
            eprintln!("controlled_scorer_cancelled call={}", self.call);
        }
    }
}

impl PublicationScorer for ControlledScorer {
    fn status(&self) -> ScorerStatus {
        if !self.inner.ready.load(Ordering::Acquire) {
            return ScorerStatus::Loading;
        }
        match self.inner.behavior {
            ControlledBehavior::StatusFailed => ScorerStatus::Failed,
            ControlledBehavior::StatusModelDrift => ScorerStatus::Ready {
                model: self.inner.drifted_model.clone(),
                scoring: Box::new(self.inner.scoring.clone()),
            },
            ControlledBehavior::StatusScoringDrift => ScorerStatus::Ready {
                model: self.inner.model.clone(),
                scoring: Box::new(self.inner.drifted_scoring.clone()),
            },
            _ => ScorerStatus::Ready {
                model: self.inner.model.clone(),
                scoring: Box::new(self.inner.scoring.clone()),
            },
        }
    }

    async fn score(
        &self,
        _packet: PublicationPacket,
        cancellation: CancellationToken,
    ) -> Result<RawScorerOutput, ScorerError> {
        let call = self.inner.calls.fetch_add(1, Ordering::AcqRel) + 1;
        let affected = call <= self.inner.affected_calls;
        if affected && matches!(self.inner.behavior, ControlledBehavior::BlockFirst) {
            eprintln!("controlled_scorer_entered call={call}");
            let mut guard = BlockedCallGuard {
                call,
                completed: false,
            };
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => {
                    return Err(ScorerError::BackendUnavailable);
                }
                _ = self.inner.release_gate.cancelled() => {}
            }
            guard.completed = true;
            eprintln!("controlled_scorer_released call={call}");
        }

        if affected && matches!(self.inner.behavior, ControlledBehavior::BackendFailureFirst) {
            return Err(ScorerError::BackendUnavailable);
        }

        let mut model = self.inner.model.clone();
        let mut scoring = self.inner.scoring.clone();
        let scores = if affected {
            match self.inner.behavior {
                ControlledBehavior::NanFirst => vec![f64::NAN],
                ControlledBehavior::PositiveInfinityFirst => vec![f64::INFINITY],
                ControlledBehavior::NegativeInfinityFirst => vec![f64::NEG_INFINITY],
                ControlledBehavior::MultiScoreFirst => vec![self.inner.score, self.inner.score],
                ControlledBehavior::ModelDriftFirst => {
                    model = self.inner.drifted_model.clone();
                    vec![self.inner.score]
                }
                ControlledBehavior::ScoringDriftFirst => {
                    scoring = self.inner.drifted_scoring.clone();
                    vec![self.inner.score]
                }
                ControlledBehavior::Fixed
                | ControlledBehavior::BlockFirst
                | ControlledBehavior::BackendFailureFirst
                | ControlledBehavior::StatusFailed
                | ControlledBehavior::StatusModelDrift
                | ControlledBehavior::StatusScoringDrift => vec![self.inner.score],
            }
        } else {
            vec![self.inner.score]
        };
        Ok(RawScorerOutput {
            model,
            scoring,
            projection: ScorerProjection::Scalar { scores },
        })
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse();
    if !args.listen.ip().is_loopback() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "publication critic listen address must be loopback",
        )
        .into());
    }
    let limits = RuntimeLimits::new(
        args.request_bytes,
        args.response_bytes,
        args.max_concurrency,
        args.queue_capacity,
        Duration::from_millis(args.job_timeout_ms),
        Duration::from_millis(args.io_timeout_ms),
    )?;
    let descriptor = controlled_test_descriptor(limits);
    descriptor.validate()?;
    let drifted_model = ModelIdentity::new(
        ComponentIdentity::new("rondo-controlled-test-scorer", "v1")?,
        ComponentIdentity::new("rondo-controlled-test-tokenizer-drift", "v1")?,
    );
    let scalar = descriptor
        .identity
        .scoring
        .as_scalar()
        .ok_or("controlled test identity must stay scalar")?;
    let drifted_scoring = ScoringContract::from(ScoringIdentity::new(
        ComponentIdentity::new("controlled-test-scalar-drift", "v1")?,
        scalar.input_template.clone(),
        scalar.scalar_projection.clone(),
        scalar.domain.clone(),
        scalar.threshold(),
    )?);
    let scorer = ControlledScorer {
        inner: Arc::new(ControlledScorerInner {
            model: descriptor.identity.model.clone(),
            scoring: descriptor.identity.scoring.clone(),
            drifted_model,
            drifted_scoring,
            behavior: args.behavior,
            affected_calls: args.affected_calls,
            score: args.score,
            calls: AtomicUsize::new(0),
            ready: AtomicBool::new(!args.initially_unready),
            release_gate: CancellationToken::new(),
        }),
    };

    let controller = scorer.clone();
    tokio::spawn(async move {
        let mut lines = BufReader::new(tokio::io::stdin()).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            match line.as_str() {
                "ready" => controller.set_ready(),
                "release" => controller.release(),
                "exit" => std::process::exit(86),
                _ => {}
            }
        }
    });

    let listener = TcpListener::bind(args.listen).await?;
    let announcement = StartupAnnouncement {
        protocol: codex_publication_critic::ProtocolVersion::RondoPublicationCriticV1,
        endpoint: listener.local_addr()?,
        descriptor: descriptor.clone(),
    };
    let announcement = serde_json::to_string(&announcement)?;
    println!("{announcement}");
    std::io::stdout().flush()?;
    eprintln!("publication_critic_service_listening");

    let graceful_shutdown_timeout = Duration::from_millis(args.graceful_shutdown_ms);
    let force_shutdown_timeout = Duration::from_millis(args.force_shutdown_ms);
    serve(
        listener,
        ServiceConfig::new(
            descriptor,
            graceful_shutdown_timeout,
            force_shutdown_timeout,
        )?,
        scorer,
    )
    .await?;
    eprintln!("publication_critic_service_stopped");
    Ok(())
}
