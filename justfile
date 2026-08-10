set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Materialize the ignored, lockfile-frozen eval environment.
eval-sync:
    UV_CACHE_DIR=eval-data/uv-cache uv sync --directory eval --frozen --python /usr/bin/python3

# Run the pure/fake/loopback suite without inheriting an ambient HTTP proxy.
eval-test:
    @test -x eval/.venv/bin/python || { echo "eval environment is missing; run 'just eval-sync' first" >&2; exit 2; }
    env \
        -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
        -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
        UV_CACHE_DIR=eval-data/uv-cache \
        uv run --directory eval --frozen --no-sync \
        python -m unittest discover -s tests -v

# Check the eval dependency lock without updating it.
eval-lock:
    UV_CACHE_DIR=eval-data/uv-cache uv lock --directory eval --check

eval-check: eval-lock eval-test
