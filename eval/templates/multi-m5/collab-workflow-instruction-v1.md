# Multi M-5 gate 1: controlled collaboration

You are Root of a two-agent team. Completing the file artifact is not enough.
The run fails unless the collaboration protocol below actually happens.

## Workspace

- `NOTES.md` holds one finding the team must report.
- Write `TEAM_REPORT.md` only after the protocol is finished.

## Required protocol

Do these steps in order. Do not skip a team tool by doing the work yourself.

1. Spawn exactly one member with `spawn_agent`. Give it a short name such as `worker`.
   Tell the member to read `NOTES.md` and publish what it finds. Do not write
   `TEAM_REPORT.md` yourself in this step.
2. Wait for the member. When it publishes, you must be woken through the team
   world state, not by guessing the finding.
3. Call `team_route` so the same member is assigned to gather evidence for that Event.
4. The member must call `team_evidence` successfully so the Version is evidence-backed.
5. The member must append a second Version on the same Event (two authors across
   the Event, at least two Versions).
6. You, as Root, set at least one Version `root_state=resolved` with `team_update`.
   That ends coordination. Do not retire an orphan; this workflow must not manufacture one.
7. Only then write `TEAM_REPORT.md` at the workspace root.

## TEAM_REPORT.md format

```
finding: <the exact finding line from NOTES.md>
event_id: <id>
version_ids: <comma-separated>
evidence: attached
root_state: resolved
```

## Hard rules

- Do not finish after reading `NOTES.md` yourself. A solo Root run is a failed run.
- Do not call `team_retire`.
- Do not spawn more than one member.
- Keep using the team tools (`team_publish`, `team_update`, `team_route`,
  `team_evidence`, `team_history` as needed). They stay available in this session.
