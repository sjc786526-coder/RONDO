# Plan 079 Skywork 4B base quality execution

## Outcome

- Exact original BF16 `Skywork/Skywork-Reward-V2-Qwen3-4B@fd958fef475f323f4e6b195930e3dd918485c668`
  completed commissioning and one authoritative formal validation run on a Secure Cloud RTX 4090.
- Formal terminal is `4B_BASE_QUALITY_NO_GO`: 55/55 scores, zero typed failures, no admissible
  operating point. The selected fallback had False PASS `12/21`, False REWRITE `4/34`, balanced
  accuracy `0.6554621849`, ROC AUC `0.6218487395`, boundary `13/19`, and within-PASS `6/7`.
- Local independent recomputation reproduced both commissioning and formal `result.json` byte for
  byte. The valid quality failure was not rerun.

## Implementation

- Added the Plan 079 base-quality runner, exact two-shard model/snapshot identity, Plan 066 bundle
  derived validation release, stable scalar projection, runtime receipt, resumable write-once
  archive, source-tree binding, commissioning/formal gates, and first-complete-formal authority.
- Closed the `3bb1253` review blockers: commissioning cannot emit formal GO/NO-GO, freeze/run rebuild
  and compare the exact validation release, and a new source archive cannot execute a stale source
  root. Later review found campaign-level formal uniqueness missing; it was added before formal.
- Final executor review found a post-final-evidence/pre-authority crash window. The archive now blocks
  another formal namespace while reconciliation is pending, permits the same run to validate and
  recover complete evidence, and claims the authority idempotently. This post-formal lifecycle fix
  does not change scoring, inputs, metrics or the already authoritative formal result, so the valid
  NO-GO was not rerun.
- Added `scripts/create-runpod-plan079-initial-when-ready.py` and its focused tests. This optional
  helper owns only inventory polling, parameterized Pod creation, and exact-name reconciliation
  after an uncertain create; budget, price, volume validation, readiness and resource lifecycle
  remain controller responsibilities.

## Verification

- 16 Plan 079 base-quality tests plus 6 monitor tests passed (`22/22`); the 23 reused Plan 073
  threshold/validation/archive/freeze tests passed. Ruff check/format for the new monitor, targeted
  `py_compile`, Plan 079 shell syntax, JSON parsing, `git diff --check`, commissioning, formal
  execution, and independent recomputation passed. No Cargo, Docker, full-repository suite, Judge,
  training, quantization or conversion ran.
- Formal evidence tar SHA-256 is
  `200fa1fb105f0c707388ea4fcf73241effc88cd95add42836728e144283d782e`; formal result file SHA-256
  is `70c7272afbee9c9af746623245e1fb7045d934a8010c9ece2a36afde0f91911a`.

## Cloud and cost handoff

- Pod `iocp8k8w6zvh4s` was deleted and an exact-name query returned zero Pods. Network volume
  `v1us0nmk0p` is intentionally retained in `US-IL-1`: Standard, 20 GB, observed task usage
  8,242,665,809 bytes, rate `$0.00194444449/h` (`$0.07/GB/month`).
- At `2026-08-25T18:14:05Z`, provider billing had settled `$0.00194444449` for the volume but still
  showed no record for the deleted Pod. A conservative ceiling from at most 1,535 Pod seconds,
  container disk and two full volume hours is `$0.3207`; at least `$14.6793` remains. At the retained
  volume rate alone this reaches `$15` in at least about 7,549 hours / 314.5 days. Continuing GPU
  cost is zero; continuing volume cost is nonzero and deletion requires separate authorization.

## Ignored assets and boundary note

- Task-owned local assets remain under
  `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan079/local/` (8,755,699 bytes): final clean
  source tar, physically unseen-free Plan 066 bundle/release, bootstrap receipts, commissioning and
  formal evidence, independent recomputes, and controller SSH known-host state. Run evidence and
  inputs are mode `0600`; the two local uv tool marker files are non-secret cache metadata.
- One early broad read-only `rg` mechanically traversed the forbidden mixed v8 path and printed
  ordinary lines. No content from that path was filtered, interpreted, scored, uploaded or used;
  it was not touched again. Cloud/formal input was exclusively the physically unseen-free Plan 066
  train+validation bundle.

Plan 079 is ready for the plan author's independent acceptance. It has not been merged or pushed.
