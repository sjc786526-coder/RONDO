# Plan 066 RunPod runbook

1. Prepare and strictly extract a `prepare-plan066-bundle` archive locally.
2. Upload only that verified archive to the existing task root.
3. Run `plan066-commission-start` and a fresh-process
   `plan066-commission-resume` on the frozen v8 6/2 smoke.
4. Freeze the complete dependency identity with `capture-dependencies
   --profile plan066`; the CLI also rejects a profile that disagrees with the
   verified bundle schema. Freeze the recipe without changing the data body.
5. From the exact base model and a new output directory run
   `plan066-formal-start`, which consumes C1 128/0, C2 128/50 and C3 128/58,
   exports C1/C2/C3 candidates, and evaluates fixed validation without grads.
6. Run `plan066-formal-resume` in a fresh process. It verifies the full formal
   cursor and continues one bounded C3 smoke update without replacing C3.
7. Recover manifests/receipts/provider facts, then apply the ExecPlan terminal
   resource policy. Never upload or mechanically read unseen-test here.
