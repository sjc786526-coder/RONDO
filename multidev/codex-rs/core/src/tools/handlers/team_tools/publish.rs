use super::*;
use crate::config::PublicationCriticConfig;
use crate::tools::handlers::team_tools::publication_review::FinalReviewMetadata;
use crate::tools::handlers::team_tools::publication_review::ReviewPublishError;
use crate::tools::handlers::team_tools::publication_review::ReviewPublishResult;
use crate::tools::handlers::team_tools::publication_review::ReviewedPublishAttempt;
use crate::tools::handlers::team_tools::publication_review::RewriteRequired;
use crate::tools::handlers::team_tools::publication_review::review_and_publish;
use crate::tools::handlers::team_tools::spec::create_reviewed_team_publish_tool;
use crate::tools::handlers::team_tools::spec::create_team_publish_tool;
use codex_team_state::EventId;
use codex_team_state::FactId;
use codex_team_state::PublishOutcome;
use codex_team_state::PublishRequest;
use codex_team_state::PublishTarget;
use codex_team_state::Submission;
use codex_team_state::TeamRevision;
use codex_team_state::reported_evidence_refs;
use codex_tools::ToolSpec;
use serde_json::json;
use sha1::Digest;
use sha1::Sha1;
use std::borrow::Cow;

pub(crate) struct Handler {
    publication_critic: Option<PublicationCriticConfig>,
}

impl Handler {
    pub(crate) fn new(publication_critic: Option<PublicationCriticConfig>) -> Self {
        Self { publication_critic }
    }

    pub(crate) fn off() -> Self {
        Self::new(None)
    }
}

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_publish")
    }

    fn spec(&self) -> ToolSpec {
        if self.publication_critic.is_some() {
            create_reviewed_team_publish_tool()
        } else {
            create_team_publish_tool()
        }
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        let publication_critic = self.publication_critic.clone();
        Box::pin(async move {
            match publication_critic {
                Some(config) => handle_reviewed_call(invocation, config).await,
                None => handle_off_call(invocation).await,
            }
        })
    }
}

impl CoreToolRuntime for Handler {
    fn matches_kind(&self, payload: &ToolPayload) -> bool {
        matches!(payload, ToolPayload::Function { .. })
    }

    fn waits_for_runtime_cancellation(&self) -> bool {
        self.publication_critic.is_some()
    }

    fn redacts_tool_bodies(&self) -> bool {
        self.publication_critic.is_some()
    }

    fn log_payload<'a>(&'a self, invocation: &'a ToolInvocation) -> Option<Cow<'a, str>> {
        if self.publication_critic.is_none() {
            return None;
        }
        let ToolPayload::Function { arguments } = &invocation.payload else {
            return Some(Cow::Borrowed(r#"{"body":"omitted"}"#));
        };
        Some(Cow::Owned(reviewed_publish_log_payload(arguments)))
    }
}

fn reviewed_publish_log_payload(arguments: &str) -> String {
    match serde_json::from_str::<ReviewedPublishArgs>(arguments) {
        Ok(args) => {
            let observation = ReviewedAttemptObservation::from_args(&args);
            json!({
                "candidate_title_sha1": observation.title_sha1,
                "candidate_summary_sha1": observation.summary_sha1,
                "candidate_handoff_sha1": observation.handoff_sha1,
                "continuation_sha1": observation.continuation_sha1,
            })
            .to_string()
        }
        Err(_) => r#"{"body":"omitted","arguments_parseable":false}"#.to_string(),
    }
}

async fn handle_off_call(
    invocation: ToolInvocation,
) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
    let ToolInvocation {
        session,
        payload,
        call_id,
        ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    // Keep this parser distinct from the enabled contract: off must not silently accept a
    // continuation field that the original tool never exposed.
    let args: PublishArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session).await?;
    let (submission, request) = publish_request(
        args.event_id,
        args.title,
        args.summary,
        args.handoff,
        args.based_on_revision,
        args.request_id,
        call_id,
    )?;
    let outcome = access
        .handle()
        .publish(access.actor(), &submission, request)
        .map_err(team_error)?;
    Ok(boxed_tool_output(TeamPublishResult::from(outcome)))
}

async fn handle_reviewed_call(
    invocation: ToolInvocation,
    publication_critic: PublicationCriticConfig,
) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
    let ToolInvocation {
        session,
        turn,
        payload,
        call_id,
        cancellation_token,
        ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    let args = parse_reviewed_arguments(&arguments)?;
    let observation = ReviewedAttemptObservation::from_args(&args);
    let access = resolve_access(&session).await?;
    let (submission, request) = reviewed_publish_request(
        args.event_id,
        args.title,
        args.summary,
        args.handoff,
        args.based_on_revision,
        args.request_id,
        call_id,
    )?;

    match review_and_publish(
        &turn,
        &cancellation_token,
        &publication_critic,
        access.handle(),
        ReviewedPublishAttempt {
            actor: access.actor(),
            submission,
            request,
            continuation: args.review_cycle_id,
        },
    )
    .await
    .map_err(review_error)?
    {
        ReviewPublishResult::Committed { outcome, review } => {
            Ok(boxed_tool_output(ReviewedTeamPublishResult {
                publish: TeamPublishResult::from(outcome),
                publication_review: review,
                observation,
            }))
        }
        ReviewPublishResult::RewriteRequired(rewrite) => Ok(boxed_tool_output(RewriteToolOutput {
            rewrite,
            observation,
        })),
    }
}

fn publish_request(
    event_id: Option<String>,
    title: Option<String>,
    summary: String,
    handoff: Option<String>,
    based_on_revision: Option<u64>,
    request_id: Option<String>,
    call_id: String,
) -> Result<(Submission, PublishRequest), FunctionCallError> {
    let target = match event_id {
        Some(event_id) => PublishTarget::ExistingEvent {
            event_id: parse_event_id(&event_id)?,
        },
        None => PublishTarget::NewEvent {
            title: title.ok_or_else(|| {
                FunctionCallError::RespondToModel(
                    "title is required when opening a new event".to_string(),
                )
            })?,
        },
    };
    Ok((
        Submission {
            based_on: TeamRevision::from_raw(based_on_revision.unwrap_or_default()),
            request_id: request_id.unwrap_or(call_id),
        },
        PublishRequest {
            target,
            summary,
            handoff,
        },
    ))
}

fn reviewed_publish_request(
    event_id: Option<String>,
    title: Option<String>,
    summary: String,
    handoff: Option<String>,
    based_on_revision: Option<u64>,
    request_id: Option<String>,
    call_id: String,
) -> Result<(Submission, PublishRequest), FunctionCallError> {
    publish_request(
        event_id,
        title,
        summary,
        handoff,
        based_on_revision,
        request_id,
        call_id,
    )
    .map_err(|_| {
        FunctionCallError::RespondToModel(
            "invalid Publication Critic team_publish target; nothing was published".to_string(),
        )
    })
}

fn parse_reviewed_arguments(arguments: &str) -> Result<ReviewedPublishArgs, FunctionCallError> {
    parse_arguments(arguments).map_err(|_| {
        FunctionCallError::RespondToModel(
            "failed to parse Publication Critic team_publish arguments".to_string(),
        )
    })
}

fn review_error(error: ReviewPublishError) -> FunctionCallError {
    match error {
        ReviewPublishError::Team(error) => team_error(error),
        ReviewPublishError::CachedRefusal(message) => FunctionCallError::RespondToModel(message),
        ReviewPublishError::InvalidPreparation => FunctionCallError::RespondToModel(
            "publication review preparation failed; nothing was published".to_string(),
        ),
        ReviewPublishError::Cycle(message) => FunctionCallError::RespondToModel(message),
        ReviewPublishError::Cancelled => FunctionCallError::RespondToModel(
            "publication review was cancelled before commit; nothing was published".to_string(),
        ),
    }
}

pub(crate) fn parse_event_id(value: &str) -> Result<EventId, FunctionCallError> {
    value.parse().map_err(|_| {
        team_error(TeamError::MalformedReference {
            reference: value.to_string(),
        })
    })
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PublishArgs {
    event_id: Option<String>,
    title: Option<String>,
    summary: String,
    handoff: Option<String>,
    based_on_revision: Option<u64>,
    /// Optional caller-chosen retry identity. Omitted in the tool schema; the call id is the
    /// default and is what the harness itself can vouch for.
    #[serde(default)]
    request_id: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReviewedPublishArgs {
    event_id: Option<String>,
    title: Option<String>,
    summary: String,
    handoff: Option<String>,
    based_on_revision: Option<u64>,
    review_cycle_id: Option<String>,
    /// Optional caller-chosen retry identity. Omitted in the tool schema; the call id is the
    /// default and is what the harness itself can vouch for.
    #[serde(default)]
    request_id: Option<String>,
}

#[derive(Debug)]
struct ReviewedAttemptObservation {
    title_sha1: Option<String>,
    summary_sha1: String,
    handoff_sha1: Option<String>,
    continuation_sha1: Option<String>,
}

impl ReviewedAttemptObservation {
    fn from_args(args: &ReviewedPublishArgs) -> Self {
        Self {
            title_sha1: args.title.as_deref().map(body_sha1),
            summary_sha1: body_sha1(&args.summary),
            handoff_sha1: args.handoff.as_deref().map(body_sha1),
            continuation_sha1: args.review_cycle_id.as_deref().map(body_sha1),
        }
    }
}

pub(super) fn body_sha1(value: &str) -> String {
    format!("{:x}", Sha1::digest(value.as_bytes()))
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamPublishResult {
    event_id: String,
    version_id: String,
    revision: u64,
    /// The observations this version was published with. Read one with `team_evidence`.
    evidence_refs: Vec<String>,
    /// How many of this entry's references this answer left out. The entry keeps them all; read the
    /// rest with `team_history`.
    evidence_refs_omitted: usize,
    authored_on_stale_view: bool,
    deduplicated: bool,
}

impl From<PublishOutcome> for TeamPublishResult {
    fn from(outcome: PublishOutcome) -> Self {
        let (reported, omitted) = reported_evidence_refs(&outcome.evidence_refs);
        Self {
            event_id: outcome.event_id.to_string(),
            version_id: outcome.version_id.to_string(),
            revision: outcome.revision.get(),
            // Reported rather than requested: the harness chose these from what this author had
            // observed since its last successful publish, and they are part of the version.
            evidence_refs: reported.iter().map(FactId::to_string).collect(),
            evidence_refs_omitted: omitted,
            authored_on_stale_view: outcome.authored_on_stale_view,
            deduplicated: outcome.deduplicated,
        }
    }
}

impl ToolOutput for TeamPublishResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_publish")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_publish")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_publish")
    }
}

#[derive(Debug, Serialize)]
struct ReviewedTeamPublishResult {
    #[serde(flatten)]
    publish: TeamPublishResult,
    publication_review: FinalReviewMetadata,
    #[serde(skip)]
    observation: ReviewedAttemptObservation,
}

impl ToolOutput for ReviewedTeamPublishResult {
    fn log_preview(&self) -> String {
        json!({
            "tool": "team_publish",
            "mode": "publication_critic",
            "status": self.publication_review.status,
            "review_attempt": self.publication_review.review_attempt,
            "blocking_rewrite_count": self.publication_review.blocking_rewrite_count,
            "failure_kind": self.publication_review.failure_kind,
            "commit_outcome": "committed"
        })
        .to_string()
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_publish")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_publish")
    }

    fn post_tool_use_response(&self, _call_id: &str, _payload: &ToolPayload) -> Option<JsonValue> {
        Some(json!({
            "mode": "publication_critic",
            "status": self.publication_review.status,
            "review_attempt": self.publication_review.review_attempt,
            "blocking_rewrite_count": self.publication_review.blocking_rewrite_count,
            "failure_kind": self.publication_review.failure_kind,
            "commit_outcome": "committed",
            "candidate_title_sha1": self.observation.title_sha1,
            "candidate_summary_sha1": self.observation.summary_sha1,
            "candidate_handoff_sha1": self.observation.handoff_sha1,
            "continuation_sha1": self.observation.continuation_sha1,
            "next_review_cycle_sha1": JsonValue::Null
        }))
    }
}

#[derive(Debug, Serialize)]
struct RewriteToolOutput {
    #[serde(flatten)]
    rewrite: RewriteRequired,
    #[serde(skip)]
    observation: ReviewedAttemptObservation,
}

impl ToolOutput for RewriteToolOutput {
    fn log_preview(&self) -> String {
        json!({
            "tool": "team_publish",
            "mode": "publication_critic",
            "status": "rewrite_required",
            "review_attempt": self.rewrite.review_attempt,
            "blocking_rewrite_count": self.rewrite.blocking_rewrite_count,
            "commit_outcome": "blocked"
        })
        .to_string()
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_publish")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_publish")
    }

    fn post_tool_use_response(&self, _call_id: &str, _payload: &ToolPayload) -> Option<JsonValue> {
        Some(json!({
            "mode": "publication_critic",
            "status": "rewrite_required",
            "review_attempt": self.rewrite.review_attempt,
            "blocking_rewrite_count": self.rewrite.blocking_rewrite_count,
            "commit_outcome": "blocked",
            "feedback_version": self.rewrite.feedback_version,
            "candidate_title_sha1": self.observation.title_sha1,
            "candidate_summary_sha1": self.observation.summary_sha1,
            "candidate_handoff_sha1": self.observation.handoff_sha1,
            "continuation_sha1": self.observation.continuation_sha1,
            "next_review_cycle_sha1": body_sha1(&self.rewrite.review_cycle_id)
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_publication_critic::RuntimeLimits;
    use codex_publication_critic::controlled_test_descriptor;
    use std::time::Duration;

    #[test]
    fn off_spec_and_parser_preserve_the_original_contract() {
        let handler = Handler::off();
        assert_eq!(handler.spec(), create_team_publish_tool());
        assert!(!handler.waits_for_runtime_cancellation());
        assert!(!handler.redacts_tool_bodies());
        assert!(
            serde_json::from_value::<PublishArgs>(json!({
                "title": "title",
                "summary": "summary",
                "review_cycle_id": "not-valid-while-off"
            }))
            .is_err()
        );
    }

    #[test]
    fn enabled_spec_exposes_only_the_needed_continuation() {
        let config = PublicationCriticConfig::new(
            "127.0.0.1:43119".parse::<std::net::SocketAddr>().unwrap(),
            controlled_test_descriptor(RuntimeLimits::production()),
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .unwrap();
        let handler = Handler::new(Some(config));
        assert!(handler.waits_for_runtime_cancellation());
        assert!(handler.redacts_tool_bodies());
        let spec = serde_json::to_value(handler.spec()).unwrap();
        assert!(
            spec.to_string().contains("review_cycle_id"),
            "enabled schema must expose the opaque continuation"
        );
        assert!(
            !serde_json::to_value(create_team_publish_tool())
                .unwrap()
                .to_string()
                .contains("review_cycle_id")
        );

        let invalid = match parse_reviewed_arguments(
            &json!({
                "title": "title",
                "summary": { "private": "candidate-sentinel" }
            })
            .to_string(),
        ) {
            Ok(_) => panic!("invalid reviewed arguments should fail"),
            Err(error) => error,
        };
        assert!(!invalid.to_string().contains("candidate-sentinel"));

        let invalid_target = reviewed_publish_request(
            Some("candidate-sentinel".to_string()),
            None,
            "summary".to_string(),
            None,
            None,
            None,
            "call".to_string(),
        )
        .expect_err("invalid reviewed target should fail");
        assert!(!invalid_target.to_string().contains("candidate-sentinel"));
    }

    #[test]
    fn reviewed_log_payload_hashes_continuation_without_bodies() {
        let payload = reviewed_publish_log_payload(
            &json!({
                "title": "rewrite title",
                "summary": "candidate-sentinel",
                "review_cycle_id": "cycle-uuid"
            })
            .to_string(),
        );
        let value: serde_json::Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(
            value["candidate_summary_sha1"],
            json!(body_sha1("candidate-sentinel"))
        );
        assert_eq!(value["continuation_sha1"], json!(body_sha1("cycle-uuid")));
        assert!(!payload.contains("candidate-sentinel"));
        assert!(!payload.contains("cycle-uuid"));
        assert!(!payload.contains("rewrite title"));

        let unparseable = reviewed_publish_log_payload(r#"{"summary":{"private":"secret"}}"#);
        assert_eq!(
            unparseable,
            r#"{"body":"omitted","arguments_parseable":false}"#
        );
        assert!(!unparseable.contains("secret"));
        assert!(!unparseable.contains("private"));
    }
}
