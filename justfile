set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Materialize the ignored, lockfile-frozen eval environment. Keep the uv cache
# in the repository-level eval-data partition even though uv enters eval/.
eval-sync:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
    UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv sync --directory eval --frozen --python /usr/bin/python3

# Run the pure/fake/loopback suite without inheriting an ambient HTTP proxy.
eval-test:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -m unittest discover -s tests -v

# Check the eval dependency lock without updating it.
eval-lock:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        uv lock --directory eval --check

eval-check: eval-lock eval-test

# Offline Plan 049 rehearsal entry; never starts Docker, provider I/O, or paid state.
eval-plan049-dry-run namespace="phase-a-final":
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.proactive_eval dry-run --namespace "{{namespace}}"

eval-plan049-fake namespace="phase-a-final":
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.proactive_eval fake --namespace "{{namespace}}"

eval-plan049-loopback namespace="phase-a-final":
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.proactive_eval loopback --namespace "{{namespace}}"

eval-plan049-replay:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.proactive_eval replay

eval-plan049-ready namespace="phase-a-final" loopback_namespace="phase-a-final":
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.proactive_eval ready --namespace "{{namespace}}" \
        --loopback-namespace "{{loopback_namespace}}"

# Authorized production entry.  The shell repeats the non-secret phrases so an
# unauthorized invocation never enters the heavy-operation watchdog.  The
# Python entry independently revalidates every gate before secret/formal state.
eval-plan049-phase-b-paid authorization="" activation_action="" balance="" local_activation="" review_commit="" phase="pilot" namespace="phase-a-final" loopback_namespace="phase-a-final":
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    test "{{authorization}}" = "AUTHORIZE RONDO PLAN 049 PHASE B REAL API AND DOCKER UP TO USD 100.00" || { echo "Plan 049 Phase B authorization is absent" >&2; exit 78; }
    test "{{activation_action}}" = "START RONDO PLAN 049 ACTIVATION PILOT" || { echo "Plan 049 activation action is absent" >&2; exit 78; }
    balance_value="{{balance}}"
    [[ "$balance_value" =~ ^[0-9]+([.][0-9]{1,2})?$ ]] || { echo "Plan 049 balance confirmation is invalid" >&2; exit 78; }
    balance_whole="${balance_value%%.*}"
    (( 10#$balance_whole >= 100 )) || { echo "Plan 049 confirmed balance is below USD 100.00" >&2; exit 78; }
    test "{{local_activation}}" = "CONFIRM RONDO PLAN 049 LOCAL ACTIVATION CONDITIONS READY" || { echo "Plan 049 local activation confirmation is absent" >&2; exit 78; }
    test "{{review_commit}}" = "$(git rev-parse HEAD)" || { echo "Plan 049 independent review commit differs" >&2; exit 78; }
    test "{{phase}}" = "pilot" || test "{{phase}}" = "formal" || { echo "Plan 049 paid phase is invalid" >&2; exit 78; }
    RONDO_BUILD_METRICS_DIR="$common_root/eval-data/plan-049/watchdog" \
    "$PWD/scripts/with-build-lock.sh" \
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.proactive_eval phase-b-paid \
        --authorize-phase-b "{{authorization}}" \
        --activation-action "{{activation_action}}" \
        --confirmed-balance-usd "{{balance}}" \
        --confirm-local-activation "{{local_activation}}" \
        --independent-review-commit "{{review_commit}}" \
        --phase "{{phase}}" \
        --namespace "{{namespace}}" \
        --loopback-namespace "{{loopback_namespace}}"

# No-API host drill: frozen Multi binary must register team tools and call team_publish.
eval-multi-m5-loopback:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.multi_m5 loopback

# Offline gate 1 dress rehearsal: stub plays Root and member against the frozen binary.
eval-multi-m5-rehearsal:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.multi_m5 rehearsal

# Offline M-5 readiness probe. Does not call Docker, APIs, or print secrets.
eval-multi-m5-ready:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.multi_m5 ready

# Fake gate 2 interleave: schedule, $120 ledger, archive. No Docker.
eval-multi-m5-gate2-fake:
    #!/usr/bin/env bash
    set -euo pipefail
    common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
    test -x "$common_root/eval/.venv/bin/python" || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync \
        python -B -m rondo_eval.multi_m5 gate2-fake

# Paid entries stay locked. The Python functions exist; these recipes never
# forward the frozen authorization phrase and never start API or Docker.
eval-multi-m5-gate1-paid:
    #!/usr/bin/env bash
    echo "rondo-multi-m5: paid gate 1 is locked until the user authorizes spending" >&2
    exit 78

eval-multi-m5-gate2-real:
    #!/usr/bin/env bash
    echo "rondo-multi-m5: paid gate 2 is locked until the user authorizes API and Docker" >&2
    exit 78

# Compare the task-independent partitions of two captured requests. The
# transport used here refuses to open any upstream connection, so this never
# reaches a provider and never spends budget. Exit 3 means the pair is not
# comparable; the printed reason codes say which partition drifted.
eval-preflight-symmetry task_id rondo_request codex_request:
    @env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$PWD/eval-data/uv-cache" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.preflight_cli \
        --task-id "{{task_id}}" \
        --rondo-request "{{rondo_request}}" \
        --codex-request "{{codex_request}}"

# One supervised no-key oracle run. It must prove the frozen solution and
# verifier can produce reward=1 before any paid provider probe is allowed.
eval-b3-oracle-no-api docker_host_volume metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        "$PWD/scripts/with-build-lock.sh" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.oracle_smoke \
        --docker-host-volume "{{docker_host_volume}}"

# One main and one Guardian-shaped Responses request, strictly sequential and
# capped by the remaining private 5 USD v2 ledger within Plan 013's 10 USD
# authorization, with at most 5 operator-confirmed-unbilled attempts per request.
eval-plan013-provider-probes:
    @env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$PWD/eval-data/uv-cache" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.provider_probe

# One supervised B2 attempt for one RONDO product: RONDO first, Codex second,
# stop on the first failure. `product` is `rondo-local` or `rondo-multi` and
# selects both the frozen bundle namespace and the recorded product identity;
# `rondo_bundle` is the runtime-bundle directory name inside that namespace.
# The frozen Local bundle is
# `cb652e1418e06d53171755963ad9eb8075259ffc-x86_64-unknown-linux-musl-runtime-bundle`.
eval-b2-no-api product rondo_bundle docker_host_volume metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @case "{{product}}" in \
        rondo-local) namespace=rondo ;; \
        rondo-multi) namespace=rondo-multi ;; \
        *) echo "product must be rondo-local or rondo-multi" >&2; exit 2 ;; \
        esac; \
        common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        "$PWD/scripts/with-build-lock.sh" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.docker_smoke \
        --product "{{product}}" \
        --rondo-binary-manifest "$common_root/eval-data/bin/$namespace/{{rondo_bundle}}/manifest.json" \
        --codex-binary-manifest "$common_root/eval-data/bin/codex/rust-v0.147.0-be6e8eac029b183056b7e4402879f15d2c85f61b-x86_64-unknown-linux-musl-runtime-bundle/manifest.json" \
        --docker-host-volume "{{docker_host_volume}}"

# One supervised lightweight `codex` build for one RONDO product line. Only one
# product target may be hot at a time (see doc/WBS.md 4.3), so clean the other
# side before switching. The Cargo target stays inside the monitored project
# root and the whole build runs under the shared root watchdog.
product-build product metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @case "{{product}}" in \
        rondo-local) source_dir=mydev ;; \
        rondo-multi) source_dir=multidev ;; \
        *) echo "product must be rondo-local or rondo-multi" >&2; exit 2 ;; \
        esac; \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        CARGO_TARGET_DIR="$PWD/$source_dir/codex-rs/target" \
        "$PWD/scripts/with-build-lock.sh" \
        cargo build --locked --manifest-path "$PWD/$source_dir/codex-rs/Cargo.toml" \
        -p codex-cli --bin codex

# The default-off product baseline gate: an unconfigured `[auto_review]` must
# leave every guardian override unset after a real config load.
product-default-off-test product metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @case "{{product}}" in \
        rondo-local) source_dir=mydev ;; \
        rondo-multi) source_dir=multidev ;; \
        *) echo "product must be rondo-local or rondo-multi" >&2; exit 2 ;; \
        esac; \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        CARGO_TARGET_DIR="$PWD/$source_dir/codex-rs/target" \
        "$PWD/scripts/with-build-lock.sh" \
        cargo test --locked --manifest-path "$PWD/$source_dir/codex-rs/Cargo.toml" \
        -p codex-core --lib -- config::config_loader_tests::

# One frozen P2/B7 campaign. The coordinator owns only a lightweight campaign
# lease; each Oracle/paid step obtains a fresh heavy lock and watchdog lease.
eval-b7-baseline docker_host_volume results_worktree_root rondo_measurement codex_measurement metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        test -x "$common_root/eval/.venv/bin/python" || { echo "shared eval environment is missing" >&2; exit 2; }; \
        env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.baseline_cli \
        --docker-host-volume "{{docker_host_volume}}" \
        --results-worktree-root "{{results_worktree_root}}" \
        --rondo-measurement-worktree-root "{{rondo_measurement}}" \
        --codex-measurement-worktree-root "{{codex_measurement}}"

# Generate and activate one successor identity after its predecessor is terminal.
# Only fair-comparison (schema v7) successors can be minted: the comparison
# contract file must carry the post-pilot frozen repeat contract, run
# conditions, shared catalog identity and product.
eval-b7-next-identity run_id_date run_id_sequence_base comparison_contract campaign_cap_usd:
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.baseline_identity \
        --run-id-date "{{run_id_date}}" \
        --run-id-sequence-base "{{run_id_sequence_base}}" \
        --comparison-contract "{{comparison_contract}}" \
        --campaign-cap-usd "{{campaign_cap_usd}}"

# Freeze one stub preflight receipt per task of the active v7 campaign. Both
# frozen binaries run the real Harbor/Docker chain against a loopback stub that
# answers every model call locally, so this makes zero API requests and costs
# nothing. The paid campaign refuses to start until every receipt exists.
eval-b7-preflight-receipts docker_host_volume metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        "$PWD/scripts/with-build-lock.sh" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.preflight_producer \
        --docker-host-volume "{{docker_host_volume}}"

# Resolve one durable schema-v2 RCA hold. This performs no Docker or API work.
eval-b7-resolve-diagnosis chain_id category disposition evidence_code:
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.baseline_diagnosis \
        --chain-id "{{chain_id}}" \
        --category "{{category}}" \
        --disposition "{{disposition}}" \
        --evidence-code "{{evidence_code}}"

# Retire an idle active campaign after a confirmed local implementation defect.
eval-b7-retire-local-defect:
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.baseline_diagnosis \
        --retire-local-defect
