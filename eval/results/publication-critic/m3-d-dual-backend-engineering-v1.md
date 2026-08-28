# M3-D dual-backend engineering closure

Plan 097 completed one clean formal run from source
`0ae9623f3d0c2ce764f4b7c6e13994759b47746f`:

`M3_D_DUAL_BACKEND_ENGINEERING_PASS`

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

Formal integrity and resources:

- formal run: `plan097-formal-5`
- contract SHA-256: `7abdd900c4b2cc27fe4400edf534ac4ef8d175331b933d55e2c089149879cf87`
- body-free result SHA-256: `91a191f07c35575242eeaf478422e2efceac48f683cd91c61491e93b913f9b57`
- controlled process tests: 13/13, zero failure/error
- local ready: 5301 ms; cloud ready: 6 ms
- local worker/service and cloud service reaped; paid proxies closed; private packet, wire and trace material removed before summary
- shared Cargo target: physical-root `.codex/cargo-target/rondo-multi`

The cumulative Plan 097 conservative total is `21.4197186 RMB` of the `30 RMB` hard cap. This
includes all commissioning and unsuccessful technical attempts: Producer is `21.3455550 RMB`
across 172 requests, and the cloud scorer is `0.0741636 RMB` across 24 usage-priced attempts with
zero unknown-usage charge.

The complete body-free formal receipts remain in the task-owned ignored namespace
`eval-data/publication-critic/plan097/formal/plan097-formal-5/`.
