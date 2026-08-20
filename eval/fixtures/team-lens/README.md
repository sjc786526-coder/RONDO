# Team Lens fixtures

The directed tests build small native `manifest.json` / `trace.jsonl` / `payloads/`
bundles in temporary directories. They use synthetic identities and sentinel bodies,
never retained rollout data. Keeping the builder in the test makes every raw body
ephemeral while preserving the native layout, direct/code-mode result shapes, and
the no-`state.json` acceptance case.

The renderer fixtures are the body-free `team_view` objects produced by that same
builder. Generated `team_view.json` and `team_report.html` files are test outputs and
are not stored here.
