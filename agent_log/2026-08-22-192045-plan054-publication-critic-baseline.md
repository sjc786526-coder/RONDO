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
- Formal v2 run `plan054-20260823T042500Z-measurement-v2` completed once from clean commit
  `c9a5e4671c3f74381b2bade7300f5e96a24bcdc7`: 16/16 valid, zero typed failures, maximum all-row parity delta
  `4.523673587608634e-06`, accuracy/balanced accuracy 0.6875, ROC AUC 0.765625 and 7/8 atomic pair wins.
  Final independent review then found three declared slice names absent from annotation/result keys, so v2 is
  retained as a superseded attempt despite correct scalar/parity observations.
- v3 aligns declared slices to actual measurement keys, leaves pair ranking as its independent metric, and
  requires every declared slice in both the frozen cohort and `quality.by_slice`. Sample/model/render/scalar,
  the successful v2 calibration artifact and threshold remain unchanged. Formal run
  `plan054-20260823T051600Z-measurement-v3` completed once from clean commit
  `3206c953bcab506f6bff61297862fd274c5f6a3b`: 16/16 valid, zero failures, all ten declared slices present,
  maximum parity delta `4.523673587608634e-06`, accuracy/balanced accuracy 0.6875, AUC 0.765625 and 7/8 pair wins.
  Engineering/M3-B1a data work is GO; unfinetuned direct-product use is NO-GO.
- Focused verification: 25 Python tests, the Rust typed freeze identity test, `just fix -p codex-core`,
  `multidev/just fmt`, environment lock, strict freeze/calibration binding and diff checks passed. All real model
  runs used the shared watchdog. Successful calibration had zero swap; v3 measurement peaked at 14,467,072
  swap bytes, and both had `stop_reason=none`.
- The same clean-context independent reviewer verified the v3 slice remediation, identities, formal result and
  resource facts, then returned `FINAL PASS`. Exact temporary direct-download chunks (3,247,542,425 bytes) and
  one 256,000,000-byte incomplete blob were removed; the retained immutable HF snapshot still verifies 12/12.
