# RONDO Local approval synthetic dataset v1

## Identity and intended use

- Batch: `20260815-l5b-synthetic-training-v1`
- Generator: human-present development Codex `gpt-5.6-sol`
- Generation date: `2026-08-15`
- Status: `ready_for_l6`
- Intended use: the independent L6 local-approval fine-tuning work package.
- Not evidence of training, convergence, model quality, or Local M4 adoption.

The same Sol session authored the scenario blueprints and targets under the
frozen prompt; the local Python facility only expanded, validated, filtered,
split, and serialized those authored candidates. No API backend, local model,
training runtime, remote resource, or data upload was used.

## Source and privacy boundary

Plan 032 batch `20260815-sol-teacher-labels-v1` was revalidated as 40 frozen
records with `ready_for_l3=true`: seed 24 and holdout 16. Only a controlled
projection of the 24 seed canonical static-v3 contexts and teacher targets was
used as generation reference. Generated examples do not copy real `E_final`,
semantic/review/run identities, real workspace paths, or provider-private
fields.

Holdout bodies were not shown to the generator and did not enter the prompt or
training data. The finalizer read them only in memory for versioned word
5-gram near-duplicate exclusion and emitted aggregate statistics. Candidate,
seed-projection, and per-item filter details remain in the git-ignored private
batch `eval-data/synthetic-training/20260815-l5b-synthetic-training-v1/` with
0700 directories and 0600 files.

## Dataset contract

Each JSONL row contains one fully synthetic canonical static payload v3 and a
target accepted by `rondo_static_approval_v1`. Rows bind the generator/date,
prompt hash, category, source group, payload/sample identities, near-duplicate
split group, and split. L6 can deterministically consume `input` and `target`;
all other fields are provenance and grouping metadata.

Exact duplicate identity is the canonical static-payload SHA-256. Candidate
near-duplicate components use NFKC-normalized word 5-grams with maximum of
Jaccard and containment score at threshold 0.92; declared source variants are
always unioned first. The component SHA-256 is assigned wholly to train or
validation by `sha256_component_mod5_validation_v1`, so same-source and detected
near-duplicate variants cannot cross splits. Holdout exclusion uses the same
similarity representation at threshold 0.72.

## Distribution

| Category | Train | Validation | Total | Allow | Deny |
|---|---:|---:|---:|---:|---:|
| Clearly safe | 150 | 30 | 180 | 180 | 0 |
| Clearly dangerous | 80 | 20 | 100 | 0 | 100 |
| Boundary ambiguous | 90 | 30 | 120 | 60 | 60 |
| Evidence insufficient | 55 | 15 | 70 | 0 | 70 |
| Dangerous disguised as safe | 50 | 15 | 65 | 0 | 65 |
| Tool result/request mismatch | 45 | 20 | 65 | 0 | 65 |
| **Total** | **470** | **130** | **600** | **240** | **360** |

There are 120 split groups: train 94 and validation 26. Canonical row length is
2,653–2,914 bytes, with P50 2,792 and P95 2,878 bytes. The two dataset files
total 1,670,240 bytes, below the 100 MB total and 40 MB per-file tracked-data
limits.

## Filtering and validation

- Raw candidates: 600; unique candidates: 600; accepted final samples: 600.
- Exact duplicates removed: 0.
- Holdout near-duplicates excluded: 0; maximum aggregate score 0.202128.
- All six categories and both outcomes are present; train and validation are
  non-empty, disjoint, and group-safe.
- The release was recomputed from the private candidates and frozen teacher
  batch; tracked JSONL, hashes, schema, permissions, and aggregate manifest all
  matched.

Two authoring-script transport/format defects were found before candidate
recording: one unterminated synthetic command string and one brace-formatting
collision. Both were narrowly corrected before any candidate file existed.
There was no candidate retry, outcome-based re-asking, or batch regeneration.

## Hashes

| Asset | SHA-256 |
|---|---|
| Generation prompt v1 | `a320badb7ec6788586e0d3393f7fcd30717141efc290be2552bdb79a4f658194` |
| Sample schema v1 | `c1873349470e2f0718ea085495d1965cfa6166e2cd23246544c6714524d4c124` |
| `train.jsonl` | `1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a` |
| `validation.jsonl` | `cbab8084bfb78bc40f96ce9dfdb564f6fabea1d73c6d48f04ffee2c95aba8dd2` |
| `manifest.json` | `dbf5fffe1f26d7746acf43fdcd092ff3e9cd64ea1f40046cd3b7219a15107190` |

## Limitations

The dataset is deliberately lightweight and command-approval focused. It is
synthetic, template-expanded, limited to the current `exec_command` action
shape, and uses point-in-time Sol targets rather than human ground truth. It
does not establish behavior for future action schemas or real-world policy
distributions. Any training and post-training comparison require their own L6
and Local M4 contracts and authorization as directed by `doc/WBS.md`.
