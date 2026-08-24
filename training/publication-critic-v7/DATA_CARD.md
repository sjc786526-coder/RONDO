# Publication Critic training data v7

This is the Plan 059 M3-B1a `formal` freeze. It contains PublicationPacket v1 model inputs plus separate Binary and pair supervision. Labels, splits, defects, source, pair direction, and teacher metadata are never included in model-visible messages.

## Contents

- Candidates: 72 (39 PASS, 33 REWRITE)
- Splits: train 42, validation 16, unseen_test 14
- Pairs: 30 Boundary Q+/Q- and 6 Within-PASS
- Exact-tokenizer census: 50073 total tokens, per-candidate range 553..1367, 0 total dropped oldest publications
- Near-duplicate edges: 12; these edges participate in group closure
- Plan 054 reference matches: 0
- Cross-split label-exclusive repeated model-visible fragments: 0
- Exact candidate-token threshold shortcuts: 0

## Identity and review

- Generator: `gpt-5.6-sol` / `runtime_not_exposed` / `01a02ec2-6085-73a1-95bf-dee63931a3c1`
- Independent reviewer: `gpt-5.6-sol` / `xhigh` / `/root/teacher_reviewer_v2`
- Generator prompt SHA-256: `a37213453e87c4b4d61dcdd2514b197bd4493f75dea242fee6edbc9b5ed191bf`
- Reviewer prompt SHA-256: `38235f56bcb3a0a29ce39dd90b6ca1d32dda4e6c9866c430bf9f72db25878d2c`

Every frozen candidate and pair has a terminal accepting independent review. Raw generator/reviewer records remain in the ignored Plan 059 namespace and are not training inputs.

The source composition is 34 synthetic product-shaped Scenarios and 2 bounded tracked public-anchor Scenarios.

## Consumer boundary

`membership.json` is cumulative: C1 is all train Binary supervision, C2 adds train Boundary pairs, and C3 adds train Within-PASS pairs. The default consumer physically retains only train packets, supervision, and pairs; explicit evaluation mode is required to construct a consumer containing validation or unseen-test rows. `train-only-smoke-bundle.json` physically contains only train members.

## Limits

Binary labels, pair directions, and accepting review decisions are synthetic GPT-5.6-sol teacher references, not human-labelled ground truth. They may encode teacher errors and must not be represented as human truth or an unbiased estimate of production quality.

This dataset has not been used for training and does not establish model quality or unlock M3-B1b. Plan 059 independent acceptance and user-approved integration remain separate decisions.
