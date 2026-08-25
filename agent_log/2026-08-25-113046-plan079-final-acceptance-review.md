# Plan 079 final acceptance review

## Conclusion

- Status: `CHANGES_REQUIRED` — acceptance not passed; the primary task objective is complete with a
  reliable `4B_BASE_QUALITY_NO_GO` formal terminal.
- The formal result itself is valid and must not be rerun. One focused off-path recovery defect remains
  in the delivered evaluator and should be fixed locally, followed by the focused pure tests and this
  review's reacceptance.

## Finding

### P2 — a valid formal `INCONCLUSIVE` prevents the allowed clean retry

`BaseQualityArchive.require_formal_unclaimed()` treats every other formal namespace containing
`final-evidence.json` as a pending authoritative quality result, without distinguishing a complete
GO/NO-GO from a legitimate incomplete `INCONCLUSIVE`
([archive.py](../eval/rondo_eval/publication_critic/base_quality/archive.py):67).

The formal runner catches a model/runtime failure, writes a typed failure, produces
`terminal=INCONCLUSIVE` with `valid_full_quality_run=false`, and persists `final-evidence.json`
([runner.py](../eval/rondo_eval/publication_critic/base_quality/runner.py):527,
[runner.py](../eval/rondo_eval/publication_critic/base_quality/runner.py):593). A subsequent formal run
using the required new empty namespace then fails with `formal_result_reconciliation_required`.
This contradicts the Plan 079 contract allowing infrastructure/compatibility failures to be repaired
and rerun from a new empty formal namespace.

The defect was reproduced with two temporary formal namespaces: the first contained an
`INCONCLUSIVE`/non-full final evidence document and no authority; the second was rejected by
`require_formal_unclaimed()` with exactly that code. It does not affect the already complete and
authoritative NO-GO evidence.

Required outcome: only a complete valid formal GO/NO-GO awaiting authority may block another formal
namespace; a well-formed `INCONCLUSIVE` must allow a new empty formal namespace, while malformed or
ambiguous evidence should continue to fail closed. A focused regression is sufficient. The executor
may choose the cleanest equivalent implementation; no new registry, campaign database, receipt chain,
or cloud rerun is needed.

## Accepted evidence

- Worktree was clean at executor HEAD `b671f51ff63f1f80aaddbd035e57634adb1838f5` before this review
  report. Main remained clean at `b077462`; neither branch was merged or pushed.
- Formal source tar is byte-identical to a fresh `git archive` of clean
  `610d880312c8ee9c98c28740f8b0b62c4fafb65f` with the frozen source path set; SHA-256 is
  `078be8a0bfd9817cc425526073b22e01de085f0c95e17b6ea1b430c8038c8287`.
- Exact model revision, two shards/index, full snapshot inventory, BF16/config/class, model lock,
  runtime receipt and dependency observations are mutually consistent.
- The uploaded bundle tar contains no unseen member; its verified Plan 066 manifest records zero
  unseen rows. Commissioning and formal releases are the same canonical 55-item, 19-boundary,
  7-within-PASS release at SHA-256
  `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`.
- Commissioning ends only as `COMMISSIONING_COMPLETE`; formal binds the completed commissioning and
  uses its own namespace. The three prior checkpoint blockers are closed: non-formal commissioning,
  bundle-derived release binding, and exact archive-to-executing-tree source binding.
- Independent recomputation with the current HEAD reproduced formal `result.json` byte for byte at
  SHA-256 `70c7272afbee9c9af746623245e1fb7045d934a8010c9ece2a36afde0f91911a`:
  55 scores, zero typed failures, 97 operating points, zero feasible points, False PASS `12/21`,
  False REWRITE `4/34`, balanced accuracy `0.6554621848739496`, ROC AUC `0.6218487394957983`,
  boundary `13/19`, and within-PASS `6/7`. Tracked JSON/Markdown, log, plan and sub-WBS agree.
- Formal-after-source commit changes only archive recovery/authority behavior. They do not change the
  frozen model, input, render, scores, metrics or formal terminal.
- Focused local tests passed: Plan 079 base quality plus initial Pod monitor `22/22` in `0.225s`.
  No Cargo, Docker, model load, Judge, training, quantization, full-repository suite or mixed/unseen
  read was run by this review.
- Cost arithmetic independently reproduces the conservative ceiling `$0.32060108` (reported upward
  as `$0.3207`), leaving at least `$14.6793`. Absence of a separate provider receipt for the stated
  1,535-second bound is not a blocker: even the wider create-to-billing-snapshot interval remains far
  below `$15`, and no additional billing audit facility is warranted.
- Live read-only RunPod MCP checks during review returned `404 pod not found` for Pod
  `iocp8k8w6zvh4s` and confirmed retained volume `v1us0nmk0p` as `STANDARD`, 20 GB, `US-IL-1`.

## Reviewer decisions

- Keep the valid `4B_BASE_QUALITY_NO_GO`; do not rerun the cloud model for this off-path lifecycle fix.
- Retain network volume `v1us0nmk0p` under the user's existing instruction; this review does not
  authorize deletion. Keep the Pod deleted.
- Do not start fine-tuning, quantization, local qualification or M3-D from this NO-GO. The next
  Publication Critic route remains unselected and requires a separate WBS decision and authorization.
- Do not add provider billing receipts or a broader campaign audit system solely for this review.

Final state for this review: **acceptance not passed + task objective complete**.
