# Plan 082 cloud continuous training

This directory contains the small, tracked cloud entry contract for Plan 082.
It keeps the exact Plan 081 route, exact 1.7B model revision, physical
train+validation-only Plan 066 projection, direct original-parameter update,
continuous validation, checkpoint qualification, formal freeze, and zero-Pod
handoff in one lifecycle.

`recipe-candidate-v1.json` is a commissioning starting point, not a formal
freeze. Actual parameter names, scope expansion points, observation/checkpoint
points and any adjusted recipe are recorded in a typed run spec after the real
parameter inventory and commissioning results are available. The formal
freeze must be written before its new artifact namespace exists.

`runbook.md` is the operator entry. The bootstrap verifies task-owned inputs;
the detach wrapper only enforces one launch, a unique local receipt set and a
finite timeout, while the typed Python CLI validates the command's training
paths and contracts. These scripts do not create or delete Pods or network
volumes. Stage A does not run the cloud commands, download the model, or access
RunPod.

The Plan 082 result can only be `TRAINING_IMPROVEMENT_FOUND`,
`VALID_NO_IMPROVEMENT`, or the plan-level externally justified
`INCONCLUSIVE`. It is never product GO, unseen evidence, deployment approval,
or M3-C2/M3-D evidence.
