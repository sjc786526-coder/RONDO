//! Rendering of the request-only Active World Index.
//!
//! The rendered text is regenerated from the canonical state for every sampling and is never
//! recorded into conversation history or the rollout. It therefore has no history-side estimate
//! to fall back on, which is why the budget here is computed against the whole request's remaining
//! context and why anything dropped is reported rather than silently cut.

use crate::ids::FactId;
use crate::view::EventView;
use crate::view::RouteView;
use crate::view::TeamSnapshot;
use crate::view::VersionView;
use codex_utils_output_truncation::approx_tokens_from_byte_count_i64;

pub const TEAM_WORLD_STATE_OPEN_TAG: &str = "<team_active_world_index>";
pub const TEAM_WORLD_STATE_CLOSE_TAG: &str = "</team_active_world_index>";

/// Absolute ceiling on the projection regardless of how much room the request has.
pub const MAX_PROJECTION_TOKENS: i64 = 4_000;
/// Room left for the model's own reasoning and reply before the projection is allowed to grow.
const REQUEST_HEADROOM_TOKENS: i64 = 2_000;
/// Share of the remaining request context the projection may occupy at most.
const REMAINING_CONTEXT_SHARE_PERCENT: i64 = 20;
/// How many evidence references one version names in the projection before the rest is counted.
const MAX_PROJECTED_EVIDENCE_REFS: usize = 4;

/// How much room the projection may take in this request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProjectionBudget {
    max_tokens: i64,
}

impl ProjectionBudget {
    /// Derive the budget from the request's remaining context.
    ///
    /// `remaining_context_tokens` is `None` when the model's window is unknown, in which case only
    /// the absolute cap applies.
    pub fn from_remaining_context(remaining_context_tokens: Option<i64>) -> Self {
        let Some(remaining) = remaining_context_tokens else {
            return Self {
                max_tokens: MAX_PROJECTION_TOKENS,
            };
        };
        let usable = remaining.saturating_sub(REQUEST_HEADROOM_TOKENS).max(0);
        let share = usable.saturating_mul(REMAINING_CONTEXT_SHARE_PERCENT) / 100;
        Self {
            max_tokens: share.min(MAX_PROJECTION_TOKENS),
        }
    }

    pub fn max_tokens(&self) -> i64 {
        self.max_tokens
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RenderedProjection {
    pub text: String,
    /// Human-readable notes for everything the budget forced out, in the order they were dropped.
    pub omissions: Vec<String>,
    pub estimated_tokens: i64,
}

/// What rendering the active view produced for this request.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProjectionOutcome {
    /// Nothing is active for this participant, so the projection costs nothing.
    Idle,
    /// A view that fits the budget. It may have shed content, in which case `omissions` says so.
    Rendered(RenderedProjection),
    /// There are active items, but the request has no room for even a notice about them.
    ///
    /// The renderer refuses to overrun its budget, so the caller has to make room — which is what
    /// compaction is for — rather than the projection quietly taking space it was not given.
    NoRoom { active_events: usize },
}

fn estimate_tokens(text: &str) -> i64 {
    approx_tokens_from_byte_count_i64(i64::try_from(text.len()).unwrap_or(i64::MAX))
}

/// Render `snapshot` into the projection body, dropping the least useful material first if the
/// budget requires it.
///
/// The budget is a hard boundary with no exceptions: whatever comes back fits, or nothing comes
/// back at all. When content has to be shed, what went missing is named in the body itself, so an
/// abbreviated view never reads as a complete one.
pub fn render_active_world_index(
    snapshot: &TeamSnapshot,
    budget: ProjectionBudget,
) -> ProjectionOutcome {
    if snapshot.is_empty() {
        return ProjectionOutcome::Idle;
    }

    // Start from the full chain, then shed detail until it fits. Oldest versions of the longest
    // chains go first: the newest entry of every event is what coordination actually needs.
    let mut events: Vec<RenderableEvent> = snapshot
        .events
        .iter()
        .map(|event| RenderableEvent {
            event,
            shown_versions: event.versions.len(),
        })
        .collect();
    let mut dropped_events = 0usize;
    let mut omissions = Vec::new();
    let mut text = render(snapshot, &events, dropped_events, &omissions);

    while estimate_tokens(&text) > budget.max_tokens {
        let shed = if let Some(target) = events
            .iter_mut()
            .filter(|candidate| candidate.shown_versions > 0)
            .max_by_key(|candidate| candidate.shown_versions)
        {
            // Entries go before the events that hold them: an event line still carries the
            // identifier a participant needs to fetch the rest, so keeping it is what makes the
            // omission notice actionable rather than merely informative.
            target.shown_versions -= 1;
            true
        } else if !events.is_empty() {
            // Even the bare event lines do not fit; drop them, oldest first.
            events.remove(0);
            dropped_events += 1;
            true
        } else {
            false
        };
        if !shed {
            break;
        }
        omissions = collect_omissions(&events, dropped_events);
        text = render(snapshot, &events, dropped_events, &omissions);
    }

    if estimate_tokens(&text) > budget.max_tokens {
        // Everything has been dropped and the bare notice still does not fit.
        return ProjectionOutcome::NoRoom {
            active_events: snapshot.events.len(),
        };
    }

    let estimated_tokens = estimate_tokens(&text);
    ProjectionOutcome::Rendered(RenderedProjection {
        text,
        omissions,
        estimated_tokens,
    })
}

struct RenderableEvent<'a> {
    event: &'a EventView,
    shown_versions: usize,
}

fn collect_omissions(events: &[RenderableEvent<'_>], dropped_events: usize) -> Vec<String> {
    let mut omissions = Vec::new();
    if dropped_events > 0 {
        omissions.push(format!(
            "{dropped_events} older event(s) omitted from this view"
        ));
    }
    for candidate in events {
        let hidden = candidate.event.versions.len() - candidate.shown_versions;
        if hidden > 0 {
            let id = candidate.event.id;
            let scope = if candidate.shown_versions == 0 {
                "all"
            } else {
                "earlier"
            };
            omissions.push(format!("{id}: {hidden} {scope} version(s) omitted"));
        }
    }
    omissions
}

/// Name a version's evidence, keeping one entry's worth of references bounded.
///
/// A publication window has no fixed size, so a long-running author could otherwise put an unbounded
/// list into every sampling. The remainder is counted rather than dropped silently, and the whole
/// chain is still reachable through bounded history.
fn render_evidence(refs: &[FactId]) -> String {
    let shown = refs.len().min(MAX_PROJECTED_EVIDENCE_REFS);
    let named = refs
        .iter()
        .take(shown)
        .map(FactId::to_string)
        .collect::<Vec<_>>()
        .join(", ");
    match refs.len().saturating_sub(shown) {
        0 => named,
        rest => format!("{named} (+{rest} more, read with team_history)"),
    }
}

fn render(
    snapshot: &TeamSnapshot,
    events: &[RenderableEvent<'_>],
    dropped_events: usize,
    omissions: &[String],
) -> String {
    let TeamSnapshot {
        instance,
        revision,
        viewer_label,
        viewer_role,
        availability_epoch,
        ..
    } = snapshot;
    let role = if viewer_role.is_root() {
        "root"
    } else {
        "member"
    };
    let availability_epoch = availability_epoch
        .map(|epoch| format!(" availability_epoch={epoch}"))
        .unwrap_or_default();
    let mut out = String::with_capacity(512);
    out.push_str(TEAM_WORLD_STATE_OPEN_TAG);
    out.push('\n');
    out.push_str(&format!(
        "team_instance={instance} revision={revision}{availability_epoch} you={viewer_label} role={role}\n"
    ));
    out.push_str(
        "Harness-owned team state, regenerated every sampling. Echo `revision` as `based_on_revision` when you publish or update.\n",
    );

    if events.is_empty() {
        out.push_str(if dropped_events == 0 {
            "No active team items.\n"
        } else {
            "Active items exist but none fit in this request; retrieve them with team_history.\n"
        });
    }
    for candidate in events {
        let EventView { id, title, .. } = candidate.event;
        out.push_str(&format!("\n[{id}] {title}\n"));
        // Routes come before the chain: an assignment is usually the reason the event is in this
        // view at all, and it is the part the reader has to act on.
        for route in &candidate.event.routes {
            let RouteView {
                id,
                target_label,
                duty,
                delivery,
                note,
            } = route;
            out.push_str(&format!(
                "  {id} route to {target_label} duty={duty} notice={delivery}\n"
            ));
            if let Some(note) = note {
                out.push_str(&format!("    note: {note}\n"));
            }
        }
        let hidden = candidate.event.versions.len() - candidate.shown_versions;
        for version in candidate.event.versions.iter().skip(hidden) {
            let VersionView {
                id,
                author_label,
                summary,
                handoff,
                evidence_refs,
                producer_state,
                root_state,
                authored_on_stale_view,
                retired,
                producer_availability,
                ..
            } = version;
            let stale = if *authored_on_stale_view {
                " authored_on_stale_view=true"
            } else {
                ""
            };
            let retired = if *retired { " retired=true" } else { "" };
            let availability = producer_availability
                .map(|class| format!(" producer_availability={class}"))
                .unwrap_or_default();
            out.push_str(&format!(
                "  {id} by {author_label} producer={producer_state} root={root_state}{retired}{availability}{stale}\n"
            ));
            out.push_str(&format!("    {summary}\n"));
            if let Some(handoff) = handoff {
                out.push_str(&format!("    handoff: {handoff}\n"));
            }
            if !evidence_refs.is_empty() {
                out.push_str(&format!(
                    "    evidence: {}\n",
                    render_evidence(evidence_refs)
                ));
            }
        }
    }

    if !omissions.is_empty() {
        out.push_str("\nOmitted from this view (retrieve with team_history):\n");
        for omission in omissions {
            out.push_str(&format!("  - {omission}\n"));
        }
    }
    out.push_str(TEAM_WORLD_STATE_CLOSE_TAG);
    out
}

#[cfg(test)]
#[path = "render_tests.rs"]
mod tests;
