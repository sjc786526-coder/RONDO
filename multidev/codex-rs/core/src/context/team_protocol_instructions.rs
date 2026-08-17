use super::ContextualUserFragment;

pub(crate) const TEAM_PROTOCOL_OPEN_TAG: &str = "<team_protocol>";
pub(crate) const TEAM_PROTOCOL_CLOSE_TAG: &str = "</team_protocol>";

/// Bumped whenever the wording below changes, so the fragment is re-emitted rather than silently
/// drifting from what the model was told earlier in the thread.
const TEAM_PROTOCOL_VERSION: u32 = 3;

const TEAM_PROTOCOL_BODY: &str = "\
This team keeps a canonical world state owned by the harness, not by your memory.

- An event is a matter the team tracks. A version is one immutable entry under it: once written, \
its author, summary and handoff never change. To revise a judgement, publish a new version; do not \
try to rewrite or reopen an old one.
- Every version carries two independent lifecycles. Producer state (`open`/`closed`) is the \
author's own view of whether the matter still needs their attention, and only the author changes \
it. Root state (`pending`/`tracking`/`resolved`) is the root's coordination attention, and only the \
root changes it. The root resolving something does not close the author's item, and an author \
closing an item does not decide anything for the root.
- `team_publish` records a checkpoint, `team_update` moves lifecycle state on versions you name, \
and `team_history` reads back anything the active view no longer shows.
- Events do not travel on their own. The root decides who else sees one with `team_route`, which \
grants access permanently and, when it assigns work, gives the target something to finish. Access \
and work are separate: `team_route_update` with `end` finishes the work, and what you were given \
access to stays readable afterwards. Being routed an event lets you add your own versions to it — \
the same event, not a copy of it.
- A route notice tells you which event to look at and nothing about what it says. Read the event \
with `team_history` rather than working from the notice.
- Versions carry evidence: references to tool results the harness recorded while you worked. You do \
not choose or list them — publishing attaches whatever you have observed since your last publish. \
`team_evidence` reads one back. It shows what was seen at that moment, not that it is still true, \
and it may report that the observation is no longer available.
- Submissions are incremental. Only what you name changes; everything else keeps its current state. \
You never need to restate active items to keep them alive.
- The active world index appended to each request is the current truth. It is regenerated every \
time and is not part of the conversation, so do not copy it into your replies to keep it around, \
and do not rely on remembering it.";

/// The stable, versioned half of the team protocol.
///
/// It belongs in the thread's instruction prefix because it never changes between turns: putting
/// it there keeps the shared prefix identical across requests, which is exactly what the volatile
/// active world index must not do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TeamProtocolInstructions;

impl ContextualUserFragment for TeamProtocolInstructions {
    fn role(&self) -> &'static str {
        "developer"
    }

    fn markers(&self) -> (&'static str, &'static str) {
        Self::type_markers()
    }

    fn type_markers() -> (&'static str, &'static str) {
        (TEAM_PROTOCOL_OPEN_TAG, TEAM_PROTOCOL_CLOSE_TAG)
    }

    fn body(&self) -> String {
        format!("v{TEAM_PROTOCOL_VERSION}\n{TEAM_PROTOCOL_BODY}")
    }
}
