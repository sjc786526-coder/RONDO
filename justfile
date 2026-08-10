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

# One supervised B2 attempt: RONDO first, Codex second, stop on the first failure.
# The caller supplies the Docker Desktop host-volume path and a fresh metrics dir.
eval-b2-no-api docker_host_volume metrics_dir:
    @test ! -e "{{metrics_dir}}" || { echo "metrics dir already exists" >&2; exit 2; }
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        RONDO_BUILD_METRICS_DIR="{{metrics_dir}}" \
        mydev/scripts/with-build-lock.sh \
        uv run --directory eval --frozen --no-sync python -B -m rondo_eval.terminal_bench.docker_smoke \
        --rondo-binary-manifest "$PWD/eval-data/bin/rondo/cb652e1418e06d53171755963ad9eb8075259ffc-x86_64-unknown-linux-musl-runtime-bundle/manifest.json" \
        --codex-binary-manifest "$PWD/eval-data/bin/codex/rust-v0.147.0-be6e8eac029b183056b7e4402879f15d2c85f61b-x86_64-unknown-linux-musl-runtime-bundle/manifest.json" \
        --docker-host-volume "{{docker_host_volume}}"
