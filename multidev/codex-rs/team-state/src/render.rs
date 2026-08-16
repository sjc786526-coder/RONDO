//! Rendering of the request-only Active World Index.
//!
//! The rendered text is regenerated from the canonical state for every sampling and is never
//! recorded into conversation history or the rollout. It therefore has no history-side estimate
//! to fall back on, which is why the budget here is computed against the whole request's remaining
//! context and why anything dropped is reported rather than silently cut.

use crate::view::EventView;
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
/// Below this the projection collapses to its header plus the omission notice.
const MINIMUM_USEFUL_TOKENS: i64 = 120;

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

    /// Whether there is not even room for the header and an omission notice. The caller then skips
    /// the projection entirely for this request rather than pushing it over the window.
    pub fn is_exhausted(&self) -> bool {
        self.max_tokens < MINIMUM_USEFUL_TOKENS
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RenderedProjection {
    pub text: String,
    /// Human-readable notes for everything the budget forced out, in the order they were dropped.
    pub omissions: Vec<String>,
    pub estimated_tokens: i64,
}

fn estimate_tokens(text: &str) -> i64 {
    approx_tokens_from_byte_count_i64(i64::try_from(text.len()).unwrap_or(i64::MAX))
}

/// Render `snapshot` into the projection body, dropping the least useful material first if the
/// budget requires it.
///
/// Returns `None` when there is nothing active to show, so an idle team costs nothing.
pub fn render_active_world_index(
    snapshot: &TeamSnapshot,
    budget: ProjectionBudget,
) -> Option<RenderedProjection> {
    if snapshot.is_empty() || budget.is_exhausted() {
        return None;
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
        if let Some(target) = events
            .iter_mut()
            .filter(|candidate| candidate.shown_versions > 1)
            .max_by_key(|candidate| candidate.shown_versions)
        {
            target.shown_versions -= 1;
        } else if events.len() > 1 {
            // Every chain is down to its latest entry; start dropping whole events, oldest first.
            events.remove(0);
            dropped_events += 1;
        } else {
            break;
        }
        omissions = collect_omissions(&events, dropped_events);
        text = render(snapshot, &events, dropped_events, &omissions);
    }

    let estimated_tokens = estimate_tokens(&text);
    Some(RenderedProjection {
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
            omissions.push(format!("{id}: {hidden} earlier version(s) omitted"));
        }
    }
    omissions
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
        ..
    } = snapshot;
    let role = if viewer_role.is_root() {
        "root"
    } else {
        "member"
    };
    let mut out = String::with_capacity(512);
    out.push_str(TEAM_WORLD_STATE_OPEN_TAG);
    out.push('\n');
    out.push_str(&format!(
        "team_instance={instance} revision={revision} you={viewer_label} role={role}\n"
    ));
    out.push_str(
        "Harness-owned team state, regenerated every sampling. Echo `revision` as `based_on_revision` when you publish or update.\n",
    );

    if events.is_empty() && dropped_events == 0 {
        out.push_str("No active team items.\n");
    }
    for candidate in events {
        let EventView { id, title, .. } = candidate.event;
        out.push_str(&format!("\n[{id}] {title}\n"));
        let hidden = candidate.event.versions.len() - candidate.shown_versions;
        for version in candidate.event.versions.iter().skip(hidden) {
            let VersionView {
                id,
                author_label,
                summary,
                handoff,
                producer_state,
                root_state,
                authored_on_stale_view,
            } = version;
            let stale = if *authored_on_stale_view {
                " authored_on_stale_view=true"
            } else {
                ""
            };
            out.push_str(&format!(
                "  {id} by {author_label} producer={producer_state} root={root_state}{stale}\n"
            ));
            out.push_str(&format!("    {summary}\n"));
            if let Some(handoff) = handoff {
                out.push_str(&format!("    handoff: {handoff}\n"));
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
