//! Deterministic snapshots of the final Guardian approval request (`E_final`).
//!
//! When `[auto_review].evidence_dir` is configured, each review round opens a
//! [`GuardianEvidenceRound`]. Once the round has picked the guardian session that
//! will serve it, it binds that session's `thread_id` into a process-wide registry.
//! [`capture_final_request`] consults the registry from the request-assembly hook in
//! `client.rs` and keeps the most recent `request_kind == turn` request issued by
//! that session, so retries naturally leave the last attempt behind. When the round
//! ends, the captured request is normalized and written to
//! `<evidence_dir>/<review_id>/E_final.json` next to a `meta.json` describing the
//! round. A round that never reached the model writes only `meta.json`, marked
//! `evidence: none`, rather than passing off a stale request as this round's
//! evidence.
//!
//! Evidence bundles are raw session records, not redacted ones: the standard
//! Responses wire shape carries policy in `instructions`, while Responses Lite
//! carries it in a developer message inside `input`. Both forms can contain whatever
//! task context the parent turn accumulated. Normalization only strips structural
//! and provider-private transport fields, so bundles belong in a private,
//! git-ignored directory. This module never sends them anywhere.

use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::LazyLock;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::sync::RwLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use anyhow::Context;
use codex_analytics::GuardianReviewAnalyticsResult;
use codex_analytics::GuardianReviewDecision;
use codex_analytics::GuardianReviewFailureReason;
use codex_analytics::GuardianReviewTerminalStatus;
use codex_api::ResponsesApiRequest;
use codex_protocol::protocol::TokenUsage;
use serde::Serialize;
use serde_json::Value;
use tracing::warn;

use crate::config::Config;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;

/// Structural request fields that carry no review semantics and would otherwise
/// make two identical reviews produce different bytes.
const STRIPPED_REQUEST_FIELDS: &[&str] = &[
    "client_metadata",
    "prompt_cache_key",
    "store",
    "stream",
    "stream_options",
];

const E_FINAL_FILE_NAME: &str = "E_final.json";
const META_FILE_NAME: &str = "meta.json";

/// Guardian sessions that are currently serving a capturing review round.
///
/// Keyed by guardian session `thread_id`, which is the only correlation handle the
/// request-assembly hook has. Each spawned session gets a fresh `ThreadId`, and a
/// trunk session serves at most one review at a time (enforced by its review
/// semaphore), so concurrent rounds always land on distinct keys.
static CAPTURING_SESSIONS: LazyLock<RwLock<HashMap<String, Arc<GuardianEvidenceRound>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

/// Whether a captured request was available when the round finished.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum GuardianEvidenceKind {
    EFinal,
    None,
}

/// Summary of one review round, written next to `E_final.json`.
#[derive(Debug, Serialize)]
struct GuardianEvidenceMeta<'a> {
    review_id: &'a str,
    evidence: GuardianEvidenceKind,
    decision: GuardianReviewDecision,
    terminal_status: GuardianReviewTerminalStatus,
    failure_reason: Option<GuardianReviewFailureReason>,
    attempt_count: i64,
    duration_ms: u64,
    guardian_thread_id: Option<&'a str>,
    model: Option<&'a str>,
    reasoning_effort: Option<&'a str>,
    token_usage: Option<&'a TokenUsage>,
    time_to_first_token_ms: Option<u64>,
}

/// One capturing Guardian review round.
///
/// Created at the start of a review when evidence capture is enabled, handed down
/// to the review session so it can bind the session that serves the round, and
/// finalized exactly once when the round reaches a terminal decision.
#[derive(Debug)]
pub(crate) struct GuardianEvidenceRound {
    review_id: String,
    output_dir: PathBuf,
    captured: Mutex<Option<Value>>,
    finalized: AtomicBool,
}

impl GuardianEvidenceRound {
    /// Returns a round when `[auto_review].evidence_dir` is configured, `None`
    /// otherwise. `None` keeps the whole capture path inert.
    pub(crate) fn start(config: &Config, review_id: &str) -> Option<Arc<Self>> {
        let evidence_dir = config.guardian_evidence_dir.as_ref()?;
        Some(Self::new(evidence_dir.as_path().join(review_id), review_id))
    }

    fn new(output_dir: PathBuf, review_id: &str) -> Arc<Self> {
        Arc::new(Self {
            review_id: review_id.to_string(),
            output_dir,
            captured: Mutex::new(None),
            finalized: AtomicBool::new(false),
        })
    }

    /// Registers `thread_id` as the guardian session serving this round.
    ///
    /// The returned guard deregisters on drop, so early returns, timeouts, and
    /// panics all stop capture for that session.
    pub(crate) fn bind(self: &Arc<Self>, thread_id: String) -> GuardianEvidenceBinding {
        CAPTURING_SESSIONS
            .write()
            .unwrap_or_else(PoisonError::into_inner)
            .insert(thread_id.clone(), Arc::clone(self));
        GuardianEvidenceBinding { thread_id }
    }

    /// Writes the bundle for this round. Subsequent calls are no-ops.
    ///
    /// Write failures are logged and swallowed: evidence capture must never change
    /// an approval decision.
    pub(crate) fn finalize(&self, result: &GuardianReviewAnalyticsResult, duration_ms: u64) {
        if self.finalized.swap(true, Ordering::SeqCst) {
            return;
        }
        let e_final = self
            .captured
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take();
        let meta = GuardianEvidenceMeta {
            review_id: self.review_id.as_str(),
            evidence: match e_final {
                Some(_) => GuardianEvidenceKind::EFinal,
                None => GuardianEvidenceKind::None,
            },
            decision: result.decision,
            terminal_status: result.terminal_status,
            failure_reason: result.failure_reason,
            attempt_count: result.attempt_count,
            duration_ms,
            guardian_thread_id: result.guardian_thread_id.as_deref(),
            model: result.guardian_model.as_deref(),
            reasoning_effort: result.guardian_reasoning_effort.as_deref(),
            token_usage: result.token_usage.as_ref(),
            time_to_first_token_ms: result.time_to_first_token_ms,
        };
        if let Err(err) = self.write_bundle(&meta, e_final.as_ref()) {
            warn!(
                review_id = self.review_id,
                %err,
                "failed to write guardian approval evidence bundle"
            );
        }
    }

    fn store(&self, request: Value) {
        *self.captured.lock().unwrap_or_else(PoisonError::into_inner) = Some(request);
    }

    fn write_bundle(
        &self,
        meta: &GuardianEvidenceMeta<'_>,
        e_final: Option<&Value>,
    ) -> anyhow::Result<()> {
        create_private_dir(&self.output_dir)
            .with_context(|| format!("create evidence directory {}", self.output_dir.display()))?;
        if let Some(e_final) = e_final {
            write_json_atomically(&self.output_dir.join(E_FINAL_FILE_NAME), e_final)?;
        }
        write_json_atomically(&self.output_dir.join(META_FILE_NAME), meta)
    }
}

/// Deregisters a guardian session from evidence capture when dropped.
pub(crate) struct GuardianEvidenceBinding {
    thread_id: String,
}

impl Drop for GuardianEvidenceBinding {
    fn drop(&mut self) {
        CAPTURING_SESSIONS
            .write()
            .unwrap_or_else(PoisonError::into_inner)
            .remove(&self.thread_id);
    }
}

/// Records `request` as the latest `E_final` candidate when it belongs to a
/// capturing Guardian review round.
///
/// A request qualifies only when both conditions hold: it is a `turn` request, and
/// its session is currently bound to a round. The `turn` check is a whitelist on
/// purpose — prewarm, compaction, and memory requests all reach this hook, and a
/// compaction on a guardian session would otherwise overwrite the real approval
/// request.
pub(crate) fn capture_final_request(
    responses_metadata: &CodexResponsesMetadata,
    request: &ResponsesApiRequest,
) {
    let sessions = CAPTURING_SESSIONS
        .read()
        .unwrap_or_else(PoisonError::into_inner);
    if sessions.is_empty() {
        return;
    }
    if !matches!(
        responses_metadata.request_kind,
        Some(CodexResponsesRequestKind::Turn)
    ) {
        return;
    }
    let Some(round) = sessions.get(&responses_metadata.thread_id).cloned() else {
        return;
    };
    drop(sessions);
    match normalize_request(request) {
        Ok(normalized) => round.store(normalized),
        Err(err) => warn!(%err, "failed to normalize guardian approval evidence request"),
    }
}

/// Returns the deterministic, replayable form of an outbound approval request.
///
/// Normalization is idempotent: it strips a fixed set of structural fields, drops
/// the per-item response ids that the server assigns, and renumbers `call_id`s in
/// document order. `call_id` is renumbered rather than removed because it is the
/// only link between a tool call and its output.
fn normalize_request(request: &ResponsesApiRequest) -> serde_json::Result<Value> {
    let mut value = serde_json::to_value(request)?;
    if let Some(object) = value.as_object_mut() {
        for field in STRIPPED_REQUEST_FIELDS {
            object.remove(*field);
        }
        if let Some(input) = object.get_mut("input").and_then(Value::as_array_mut) {
            for item in input {
                if let Some(item) = item.as_object_mut() {
                    item.remove("id");
                    // OpenAI may attach this private collaboration transport marker
                    // to function calls. It is provider-specific and must not make
                    // otherwise equivalent E_final payloads compare differently.
                    item.remove("encrypted_function_args");
                }
            }
        }
    }
    let mut canonical_call_ids = HashMap::new();
    canonicalize_call_ids(&mut value, &mut canonical_call_ids);
    Ok(value)
}

fn canonicalize_call_ids(value: &mut Value, canonical: &mut HashMap<String, String>) {
    match value {
        Value::Array(items) => {
            for item in items {
                canonicalize_call_ids(item, canonical);
            }
        }
        Value::Object(object) => {
            for (key, entry) in object {
                match (key.as_str(), entry.as_str()) {
                    ("call_id", Some(call_id)) => {
                        let next = format!("call_{}", canonical.len());
                        let canonical_id =
                            canonical.entry(call_id.to_string()).or_insert(next).clone();
                        *entry = Value::String(canonical_id);
                    }
                    _ => canonicalize_call_ids(entry, canonical),
                }
            }
        }
        _ => {}
    }
}

fn create_private_dir(dir: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dir)?;
    set_private_mode(dir, /*mode*/ 0o700)
}

fn write_json_atomically(path: &Path, value: &impl Serialize) -> anyhow::Result<()> {
    let contents = serde_json::to_vec_pretty(value)?;
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, contents)
        .with_context(|| format!("write evidence file {}", tmp_path.display()))?;
    set_private_mode(&tmp_path, /*mode*/ 0o600)
        .with_context(|| format!("restrict evidence file {}", tmp_path.display()))?;
    fs::rename(&tmp_path, path)
        .with_context(|| format!("publish evidence file {}", path.display()))?;
    Ok(())
}

#[cfg(unix)]
fn set_private_mode(path: &Path, mode: u32) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;

    fs::set_permissions(path, fs::Permissions::from_mode(mode))
}

/// Windows has no POSIX mode bits; the bundle still lands in the configured
/// directory and inherits its ACL.
#[cfg(not(unix))]
fn set_private_mode(_path: &Path, _mode: u32) -> std::io::Result<()> {
    Ok(())
}

#[cfg(test)]
#[path = "evidence_tests.rs"]
mod tests;
