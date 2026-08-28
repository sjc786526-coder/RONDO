# M3-D dual-backend engineering formal evidence and remediation

Plan 097 completed one clean formal run from source
`0ae9623f3d0c2ce764f4b7c6e13994759b47746f`:

`M3_D_DUAL_BACKEND_ENGINEERING_PASS`

The initial independent review did not accept the implementation. Its four medium findings and
one low finding were remediated; final independent re-review accepted the task with zero remaining
High, Medium, or Low correctness/functionality findings. By reviewer decision, `formal-5`, its
real-model/API/Producer evidence, and its cumulative cost remain the historical formal evidence;
remediation did not rerun paid API calls or the real local model.

The result establishes the engineering chain and backend replacement seam only. The exact
Skywork 1.7B base remains `NO-GO / pending replacement`, DeepSeek V4 Flash remains
`NOT QUALIFIED`, product value remains unevaluated, Publication Critic remains default-off, and
production remains disabled.

| path | direct fixtures | branch coverage | publish / rewrite / cycle hop | canonical commit | Producer requests | Producer cost |
|---|---:|---|---:|---:|---:|---:|
| local exact Skywork 1.7B | 3/3 | PASS + REWRITE | 3 / 2 / 2 | 1 | 12 | $0.121840 |
| cloud DeepSeek V4 Flash | 3/3 | PASS + REWRITE | 3 / 2 / 2 | 1 | 11 | $0.179534 |

Both Producer paths ended with one Event, one Version, revision 1, one canonical mutation and a
Root wake. The first two rejected attempts did not create public state. The controlled Rust paths
proved one fallback commit and zero cancellation commits. The OFF path started no scorer, loaded
no scorer secret, created no review cycle, and preserved the canonical flow.

The two historical backend receipts also carry the same Producer runtime identity:
`gpt-5.6-terra`, effort `low`, provider profile
`29e0cded5a50f3f4666a6b915ac883f825c479ccadcd8a50bfcd25f9ffc8df98`. The current finalizer
requires this equality and records it in future summaries.

Formal integrity and resources:

- formal run: `plan097-formal-5`
- contract SHA-256: `7abdd900c4b2cc27fe4400edf534ac4ef8d175331b933d55e2c089149879cf87`
- body-free result SHA-256: `91a191f07c35575242eeaf478422e2efceac48f683cd91c61491e93b913f9b57`
- controlled process tests: 13/13, zero failure/error
- local ready: 5301 ms; cloud ready: 6 ms
- historical local worker/service and cloud service were recorded as reaped; paid proxies closed; private packet, wire and trace material was removed before summary
- shared Cargo target: physical-root `.codex/cargo-target/rondo-multi`

The historical local descriptor rendered the authoritative reference threshold one ULP low
(`0.935056901119612` rather than `0.9350569011196121`). The current contract and descriptor use
the authoritative value; no claim is made that `formal-5` ran with the corrected rendering. The
historical service receipts recorded process reap only. Current runs now require an accepted
shutdown probe, graceful completion, and zero exit before a backend receipt can be written.

Remediation additionally gives the cloud ledger a cross-process file lock with a fresh reload for
every reserve, settle, and snapshot, and removed the three exact task-owned temporary remnants
identified by review. The affected Python regression set passes 39/39; the full lightweight
Plan 097 Python unit set passes 51/51, independently repeated during final review. Final review
also exercised 16 concurrent independent ledger instances and observed 16 unique reservations
with the full conservative cap retained.

The cumulative Plan 097 conservative total is `21.4197186 RMB` of the `30 RMB` hard cap. This
includes all commissioning and unsuccessful technical attempts: Producer is `21.3455550 RMB`
across 172 requests, and the cloud scorer is `0.0741636 RMB` across 24 usage-priced attempts with
zero unknown-usage charge.

The complete body-free formal receipts remain in the task-owned ignored namespace
`eval-data/publication-critic/plan097/formal/plan097-formal-5/`.
The initial review report is
[`agent_log/2026-08-28-001531-plan097-independent-review.md`](../../../agent_log/2026-08-28-001531-plan097-independent-review.md).
The accepted final re-review is
[`agent_log/2026-08-28-004428-plan097-final-independent-review.md`](../../../agent_log/2026-08-28-004428-plan097-final-independent-review.md).
