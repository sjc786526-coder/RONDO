set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Materialize the ignored, lockfile-frozen eval environment. Keep the uv cache
# in the repository-level eval-data partition even though uv enters eval/.
eval-sync:
    UV_CACHE_DIR="$PWD/eval-data/uv-cache" uv sync --directory eval --frozen --python /usr/bin/python3

# Run the pure/fake/loopback suite without inheriting an ambient HTTP proxy.
eval-test:
    @test -x eval/.venv/bin/python || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR="$PWD/eval-data/uv-cache" \
        uv run --directory eval --frozen --no-sync \
        python -m unittest discover -s tests -v

# Check the eval dependency lock without updating it.
eval-lock:
    UV_CACHE_DIR="$PWD/eval-data/uv-cache" uv lock --directory eval --check

eval-check: eval-lock eval-test

# One supervised no-key oracle run. It must prove the frozen solution and
# verifier can produce reward=1 before any paid provider probe is allowed.
eval-b3-oracle-no-api docker_host_volume metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        "$PWD/mydev/scripts/with-build-lock.sh" \
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

# One supervised B2 attempt: RONDO first, Codex second, stop on the first failure.
# The caller supplies the Docker Desktop host-volume path and a fresh metrics dir.
eval-b2-no-api docker_host_volume metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        "$PWD/mydev/scripts/with-build-lock.sh" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.docker_smoke \
        --rondo-binary-manifest "$common_root/eval-data/bin/rondo/cb652e1418e06d53171755963ad9eb8075259ffc-x86_64-unknown-linux-musl-runtime-bundle/manifest.json" \
        --codex-binary-manifest "$common_root/eval-data/bin/codex/rust-v0.147.0-be6e8eac029b183056b7e4402879f15d2c85f61b-x86_64-unknown-linux-musl-runtime-bundle/manifest.json" \
        --docker-host-volume "{{docker_host_volume}}"

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
eval-b7-next-identity run_id_date run_id_sequence_base:
    @common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"; \
        UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
        UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.baseline_identity \
        --run-id-date "{{run_id_date}}" \
        --run-id-sequence-base "{{run_id_sequence_base}}"

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
