# Multi M-5 gate 1: controlled collaboration

You are Root of a two-agent team. Completing the file artifact is not enough.
The run fails unless the collaboration protocol below actually happens on **one**
Event. A solo Root run, or a Root-only Event plus a disconnected member Event,
is a failed run.

## Workspace

- `NOTES.md` holds one finding the team must report.
- Write `TEAM_REPORT.md` only after the protocol is finished.

## Required protocol

Do these steps in order. Do not skip a team tool by doing the work yourself.

1. Spawn exactly one member with `spawn_agent`. Give it a short name such as `worker`.
   Do not pass `model` or `reasoning_effort`. Tell the member to read `NOTES.md` and
   publish what it finds. Do not write `TEAM_REPORT.md` yourself in this step.
2. Call `wait_agent`. When the member publishes, you must be woken through the team
   world state, not by guessing the finding.
3. You, as Root, publish your own Version onto **that same Event** with `team_publish`,
   passing its `event_id`. Record what you make of the member's finding. This step is
   required: the run needs two distinct authors on one Event, and `team_update` only
   changes lifecycle state — it never creates a Version. If you skip this, the run
   fails no matter how well the rest goes.
4. Call `team_route` so the same member is assigned to gather evidence for **that**
   Event.
5. The member must call `team_evidence` successfully so a **member-authored** Version
   on that Event is evidence-backed.
6. The member must append a second Version on the same Event, so that Event carries at
   least two Versions from the member plus yours from step 3.
7. You, as Root, set a **member-authored** Version on that Event to
   `root_state=resolved` with `team_update`. That ends coordination. Do not retire
   an orphan; this workflow must not manufacture one.
8. Call `team_inspect` with `action=dump`, then again with `action=log`. If a dump
   page returns a `next_cursor`, call `team_inspect` again with that cursor until it
   comes back null, so the whole page set is present. The harness reads those tool
   outputs directly. Do not copy them into `TEAM_REPORT.md`, and do not restate them
   through any other tool: only real `team_inspect` output counts as evidence.
9. Only then write `TEAM_REPORT.md` at the workspace root.

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
  `team_evidence`, `team_history`, `team_inspect`, `wait_agent` as needed). They
  stay available in this session.
