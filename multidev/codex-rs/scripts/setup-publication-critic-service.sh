#!/usr/bin/env bash
set -euo pipefail

: "${NEXTEST_ENV:?Nextest did not provide its environment output path}"
: "${CARGO_TARGET_DIR:?the publication critic process tests require an explicit Cargo target}"

case "$CARGO_TARGET_DIR" in
    /*) ;;
    *)
        echo "CARGO_TARGET_DIR must be absolute for publication critic process tests" >&2
        exit 2
        ;;
esac

cargo build --locked -p codex-publication-critic --bin codex-publication-critic-service

service_bin="$CARGO_TARGET_DIR/debug/codex-publication-critic-service"
if [[ ! -f "$service_bin" || ! -x "$service_bin" ]]; then
    echo "publication critic service binary was not built at $service_bin" >&2
    exit 2
fi

printf 'RONDO_PUBLICATION_CRITIC_SERVICE_BIN=%s\n' "$service_bin" >>"$NEXTEST_ENV"
