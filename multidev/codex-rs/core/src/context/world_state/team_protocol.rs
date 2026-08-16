use super::PreviousSectionState;
use super::WorldStateHash;
use super::WorldStateSection;
use crate::context::ContextualUserFragment;
use crate::context::team_protocol_instructions::TeamProtocolInstructions;

/// Whether the stable team protocol is currently part of this participant's instructions.
///
/// It is a world-state section rather than a per-request fragment precisely because it must be
/// stable: it is emitted once, survives compaction with the rest of the initial context, and only
/// reappears if its version changes.
#[derive(Clone, Debug)]
pub(crate) struct TeamProtocolState {
    instructions: Option<TeamProtocolInstructions>,
}

impl TeamProtocolState {
    pub(crate) fn new(enabled: bool) -> Self {
        Self {
            instructions: enabled.then_some(TeamProtocolInstructions),
        }
    }
}

impl WorldStateSection for TeamProtocolState {
    const ID: &'static str = "team_protocol";
    type Snapshot = Option<WorldStateHash>;

    /// Nothing to persist while the team world state is off, so a thread that never enables it
    /// carries no trace of this section.
    fn should_persist(&self) -> bool {
        self.instructions.is_some()
    }

    fn snapshot(&self) -> Self::Snapshot {
        self.instructions
            .as_ref()
            .map(WorldStateHash::from_fragment)
    }

    fn matches_current_legacy_fragment(&self, role: &str, text: &str) -> bool {
        self.instructions.as_ref().is_some_and(|instructions| {
            role == instructions.role() && text == instructions.render()
        })
    }

    fn render_diff(
        &self,
        previous: PreviousSectionState<'_, Self::Snapshot>,
    ) -> Option<Box<dyn ContextualUserFragment>> {
        let instructions = self.instructions.as_ref()?;
        match previous {
            PreviousSectionState::Known(previous) if previous == &self.snapshot() => None,
            PreviousSectionState::Unknown => None,
            PreviousSectionState::Known(_) | PreviousSectionState::Absent => {
                Some(Box::new(instructions.clone()))
            }
        }
    }
}
