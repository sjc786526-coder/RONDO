# Plan 054 Publication Critic baseline

- Added a strict PublicationPacket v1 parity fixture and Rust/Python checks, 24 physically separated
  packet/annotation samples, two exact cap census cases, deterministic render/tokenization/overflow/scoring,
  a write-once Publication Critic runner, exact environment/model locks, and focused tests.
- Downloaded and verified immutable Skywork revision
  `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` in the ignored Plan 054 cache. CPU BF16 produced finite scalar
  output but failed the declared single-vs-padded-batch tolerance; CPU FP32 passed repeat, padding and 16,384
  token context smoke and became the frozen measurement identity.
- The v1 freeze commit `4de338384f4d9303b56e9aba9a674a3f5cd59776` produced 16 finite measurement scores, but independent review
  found real qualification/output-shape identity, all-cohort parity, and render-description defects. The v1
  result remains an immutable superseded attempt and is not Plan 054 acceptance evidence.
- v2 binds the exact calibration artifact and canonical committed freeze, describes the title's real user-message
  placement while accounting its tokens as candidate semantics, and checks every scored row across single,
  repeat, right/left padded and alternate batch composition. Calibration run
  `plan054-20260823T040900Z-calibration-v2` passed 8-row parity (maximum projected delta
  `1.5709748450998262e-06`) plus a finite 16,384-token forward and retained threshold `0.9350569011196121`.
- Pre-measurement v2 verification: 24 Python focused tests, the Rust typed freeze identity test,
  `just fix -p codex-core`, `multidev/just fmt`, strict freeze verification and diff checks passed. Formal v2
  measurement and final independent acceptance remain pending.
