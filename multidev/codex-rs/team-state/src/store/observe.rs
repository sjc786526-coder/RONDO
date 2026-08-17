//! Bounded dump, change log and publication stats over the canonical store.

use super::TeamStore;
use crate::availability::AvailabilitySnapshot;
use crate::availability::ProducerAvailability;
use crate::model::ParticipantRole;
use crate::model::TeamEvent;
use crate::mutation::TeamError;
use crate::observe::ChangeLogPage;
use crate::observe::ChangeLogView;
use crate::observe::DumpCursor;
use crate::observe::DumpEntry;
use crate::observe::ObserveQuery;
use crate::observe::PublicationStats;
use crate::observe::StoredWake;
use crate::observe::TeamDumpPage;
use crate::observe::WakeDecisionView;
use codex_protocol::ThreadId;

impl TeamStore {
    /// Root-only dump of coordination metadata. One page is hard-capped; the rest is reached with
    /// a cursor that names the snapshot it belongs to.
    pub fn dump(
        &self,
        actor: ThreadId,
        availability: &AvailabilitySnapshot,
        wake_generation: u64,
        query: ObserveQuery,
        cursor: Option<DumpCursor>,
    ) -> Result<TeamDumpPage, TeamError> {
        self.require_root(actor)?;
        if cursor.is_none() && query.offset.is_some() {
            return Err(TeamError::InvalidRequest {
                reason: "dump pages continue with a snapshot cursor, not a raw offset",
            });
        }
        if let Some(cursor) = cursor
            && (cursor.revision != self.revision
                || cursor.availability_epoch != availability.epoch
                || cursor.observe_generation != self.observe_generation)
        {
            return Err(TeamError::DumpCursorStale {
                current_revision: self.revision,
                current_epoch: availability.epoch,
                current_observe_generation: self.observe_generation,
            });
        }

        let entries = self.dump_entries(availability);
        let total_entries = entries.len();
        let offset = cursor.map(|cursor| cursor.offset as usize).unwrap_or(0);
        let limit = query.limit();
        let end = (offset + limit).min(total_entries);
        let page = entries.get(offset..end).unwrap_or(&[]).to_vec();
        let next_offset = (end < total_entries).then_some(u32::try_from(end).unwrap_or(u32::MAX));
        Ok(TeamDumpPage {
            instance: self.instance,
            revision: self.revision,
            wake_generation,
            availability_epoch: availability.epoch,
            observe_generation: self.observe_generation,
            entries: page,
            total_entries,
            next_offset,
        })
    }

    pub fn change_log(
        &self,
        actor: ThreadId,
        wake_generation: u64,
        query: ObserveQuery,
    ) -> Result<ChangeLogPage, TeamError> {
        self.require_root(actor)?;
        let after = query.after;
        let eligible: Vec<_> = self
            .change_log
            .iter()
            .filter(|record| after.is_none_or(|after| record.revision > after))
            .collect();
        let total_entries = eligible.len();
        let offset = query.offset.unwrap_or(0) as usize;
        let limit = query.limit();
        let end = (offset + limit).min(total_entries);
        let page: Vec<ChangeLogView> = eligible
            .get(offset..end)
            .unwrap_or(&[])
            .iter()
            .map(|record| ChangeLogView {
                revision: record.revision,
                actor: self.label_of(record.actor),
                actor_thread_id: record.actor.to_string(),
                kind: record.kind,
                target: record.target.clone(),
                before: record.before.clone(),
                after: record.after.clone(),
                wake: match &record.wake {
                    StoredWake::Signalled { participant, rule } => WakeDecisionView::Signalled {
                        target: self.label_of(*participant),
                        target_thread_id: participant.to_string(),
                        rule: (*rule).to_string(),
                    },
                    StoredWake::None { rule } => WakeDecisionView::None {
                        rule: (*rule).to_string(),
                    },
                },
            })
            .collect();
        let next_offset = (end < total_entries).then_some(u32::try_from(end).unwrap_or(u32::MAX));
        Ok(ChangeLogPage {
            instance: self.instance,
            revision: self.revision,
            wake_generation,
            entries: page,
            total_entries,
            next_offset,
        })
    }

    pub fn publication_stats(
        &self,
        actor: ThreadId,
        wake_generation: u64,
        query: ObserveQuery,
    ) -> Result<crate::observe::PublicationStatsPage, TeamError> {
        self.require_root(actor)?;
        let rows = self.publication_stats_rows();
        let total_entries = rows.len();
        let offset = query.offset.unwrap_or(0) as usize;
        let limit = query.limit();
        let end = (offset + limit).min(total_entries);
        let page = rows.get(offset..end).unwrap_or(&[]).to_vec();
        let next_offset = (end < total_entries).then_some(u32::try_from(end).unwrap_or(u32::MAX));
        Ok(crate::observe::PublicationStatsPage {
            instance: self.instance,
            revision: self.revision,
            wake_generation,
            entries: page,
            total_entries,
            next_offset,
        })
    }

    fn require_root(&self, actor: ThreadId) -> Result<(), TeamError> {
        let role = self.require_participant(actor)?.role;
        if role.is_root() {
            Ok(())
        } else {
            Err(TeamError::NotPermitted {
                reason: "only the root may read the team dump, change log or publication stats",
            })
        }
    }

    fn dump_entries(&self, availability: &AvailabilitySnapshot) -> Vec<DumpEntry> {
        let mut entries = Vec::new();
        for participant in self.participants() {
            entries.push(DumpEntry::Participant {
                label: participant.label.clone(),
                thread_id: participant.thread_id.to_string(),
                role: participant.role,
                availability: availability
                    .class_of(participant.thread_id)
                    .unwrap_or(ProducerAvailability::Unknown),
            });
        }
        for event in &self.events {
            entries.push(DumpEntry::Event {
                event_id: event.id().to_string(),
                created_by: self.label_of(event.created_by()),
                created_by_thread_id: event.created_by().to_string(),
                version_count: event.versions().len(),
                route_count: event.routes().len(),
            });
            for version in event.versions() {
                let retirement = version.retirement();
                entries.push(DumpEntry::Version {
                    version_id: version.id().to_string(),
                    author: self.label_of(version.authored().author),
                    author_thread_id: version.authored().author.to_string(),
                    producer_state: version.producer_state(),
                    root_state: version.root_state(),
                    retired: retirement.is_some(),
                    retired_by: retirement.map(|record| self.label_of(record.retired_by)),
                    retired_by_thread_id: retirement.map(|record| record.retired_by.to_string()),
                    retired_at: retirement.map(|record| record.retired_at),
                    retire_reason: retirement.map(|record| record.reason.clone()),
                    retired_availability: retirement.map(|record| record.availability),
                    retired_availability_epoch: retirement.map(|record| record.availability_epoch),
                    fact_ref_count: version.authored().evidence_refs.len(),
                });
                for fact_id in &version.authored().evidence_refs {
                    entries.push(DumpEntry::VersionFact {
                        version_id: version.id().to_string(),
                        fact_id: fact_id.to_string(),
                    });
                }
            }
            for route in event.routes() {
                entries.push(DumpEntry::Route {
                    route_id: route.id().to_string(),
                    event_id: event.id().to_string(),
                    target: self.label_of(route.target()),
                    target_thread_id: route.target().to_string(),
                    duty: route.duty(),
                    delivery: route.delivery().label().to_string(),
                });
            }
        }
        for fact in &self.facts {
            entries.push(DumpEntry::Fact {
                fact_id: fact.id().to_string(),
                producer: self.label_of(fact.producer()),
                producer_thread_id: fact.producer().to_string(),
                category: fact.category().to_string(),
                item_id: fact.locator().item_id.clone(),
                call_id: fact.locator().call_id.clone(),
                tool: fact.locator().tool.clone(),
            });
        }
        for participant in self.participants() {
            for event in &self.events {
                let (visible, visibility_reasons) =
                    visibility_reasons(event, participant.thread_id, participant.role);
                entries.push(DumpEntry::Visibility {
                    participant: participant.label.clone(),
                    participant_thread_id: participant.thread_id.to_string(),
                    event_id: event.id().to_string(),
                    visible,
                    reasons: visibility_reasons,
                });
                let (active, activity_reasons) =
                    activity_reasons(event, participant.thread_id, participant.role);
                entries.push(DumpEntry::Activity {
                    participant: participant.label.clone(),
                    participant_thread_id: participant.thread_id.to_string(),
                    event_id: event.id().to_string(),
                    active,
                    reasons: activity_reasons,
                });
            }
        }
        for stats in self.publication_stats_rows() {
            entries.push(DumpEntry::Publication {
                participant: stats.participant,
                thread_id: stats.thread_id,
                version_count: stats.version_count,
                authored_chars: stats.authored_chars,
                fact_ref_count: stats.fact_ref_count,
            });
        }
        entries
    }

    fn publication_stats_rows(&self) -> Vec<PublicationStats> {
        let mut rows: Vec<PublicationStats> = self
            .participants()
            .into_iter()
            .map(|participant| PublicationStats {
                participant: participant.label,
                thread_id: participant.thread_id.to_string(),
                version_count: 0,
                authored_chars: 0,
                fact_ref_count: 0,
            })
            .collect();
        let index_of = |thread_id: ThreadId, rows: &[PublicationStats]| {
            let key = thread_id.to_string();
            rows.iter().position(|row| row.thread_id == key)
        };
        for event in &self.events {
            for (index, version) in event.versions().iter().enumerate() {
                let Some(row) =
                    index_of(version.authored().author, &rows).and_then(|i| rows.get_mut(i))
                else {
                    continue;
                };
                row.version_count += 1;
                row.fact_ref_count += version.authored().evidence_refs.len() as u64;
                row.authored_chars += version.authored().summary.chars().count() as u64;
                if let Some(handoff) = &version.authored().handoff {
                    row.authored_chars += handoff.chars().count() as u64;
                }
                if index == 0 {
                    row.authored_chars += event.title().chars().count() as u64;
                }
            }
        }
        rows
    }
}

fn visibility_reasons(
    event: &TeamEvent,
    participant: ThreadId,
    role: ParticipantRole,
) -> (bool, Vec<String>) {
    let mut reasons = Vec::new();
    if role.is_root() {
        reasons.push("root".to_string());
    }
    if event.created_by() == participant {
        reasons.push("created_event".to_string());
    }
    if event
        .versions()
        .iter()
        .any(|version| version.authored().author == participant)
    {
        reasons.push("authored".to_string());
    }
    if event
        .routes()
        .iter()
        .any(|route| route.target() == participant)
    {
        reasons.push("routed".to_string());
    }
    if reasons.is_empty() {
        (false, vec!["no_visibility_grant".to_string()])
    } else {
        (true, reasons)
    }
}

fn activity_reasons(
    event: &TeamEvent,
    participant: ThreadId,
    role: ParticipantRole,
) -> (bool, Vec<String>) {
    let mut reasons = Vec::new();
    if event.versions().iter().any(|version| {
        version.authored().author == participant && version.occupies_author_attention()
    }) {
        reasons.push("own_open_version".to_string());
    }
    if event.assignment_in_progress_for(participant).is_some() {
        reasons.push("assignment_in_progress".to_string());
    }
    if role.is_root()
        && event
            .versions()
            .iter()
            .any(|version| version.root_state().occupies_root_attention())
    {
        reasons.push("root_attention".to_string());
    }
    if reasons.is_empty() {
        (false, vec!["no_active_reason".to_string()])
    } else {
        (true, reasons)
    }
}

#[cfg(test)]
#[path = "observe_tests.rs"]
mod tests;
