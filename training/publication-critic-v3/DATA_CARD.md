# Publication Critic training data v3

This is the Plan 059 M3-B1a `formal` freeze. It contains PublicationPacket v1 model inputs plus separate Binary and pair supervision. Labels, splits, defects, source, pair direction, and teacher metadata are never included in model-visible messages.

## Contents

- Candidates: 72 (39 PASS, 33 REWRITE)
- Splits: train 42, validation 16, unseen_test 14
- Pairs: 30 Boundary Q+/Q- and 6 Within-PASS
- Exact-tokenizer census: 53294 total tokens, per-candidate range 553..2753, 0 total dropped oldest publications
- Near-duplicate edges: 11; these edges participate in group closure
- Plan 054 reference matches: 0
- Cross-split label-exclusive repeated model-visible fragments: 0
- Exact candidate-token threshold shortcuts: 0

## Identity and review

- Generator: `gpt-5.6-sol` / `runtime_not_exposed` / `01a02ec2-6085-73a1-95bf-dee63931a3c1`
- Independent reviewer: `gpt-5.6-sol` / `xhigh` / `/root/teacher_reviewer_v2`
- Generator prompt SHA-256: `0706c5be6d1e82ffebc4f54481dfb67f3a5ccbc46611bfcd978a769aeee5661a`
- Reviewer prompt SHA-256: `38235f56bcb3a0a29ce39dd90b6ca1d32dda4e6c9866c430bf9f72db25878d2c`

Every frozen candidate and pair has a terminal accepting independent review. Raw generator/reviewer records remain in the ignored Plan 059 namespace and are not training inputs.

## Consumer boundary

`membership.json` is cumulative: C1 is all train Binary supervision, C2 adds train Boundary pairs, and C3 adds train Within-PASS pairs. The default consumer denies validation and unseen-test access; explicit evaluation mode is required. `train-only-smoke-bundle.json` physically contains only train members.

## Limits

This dataset has not been used for training and does not establish model quality or unlock M3-B1b. Plan 059 independent acceptance and user-approved integration remain separate decisions.
