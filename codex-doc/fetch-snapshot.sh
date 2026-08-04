#!/usr/bin/env bash
set -euo pipefail

snapshot_date="${1:-$(date +%F)}"
if [[ ! "${snapshot_date}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "usage: $0 [YYYY-MM-DD]" >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
destination="${script_dir}/snapshot-${snapshot_date}"

if [[ -e "${destination}" ]]; then
    echo "snapshot already exists: ${destination}" >&2
    exit 1
fi

staging="$(mktemp -d "${script_dir}/.snapshot-${snapshot_date}.XXXXXX")"
cleanup() {
    if [[ -d "${staging}" ]]; then
        find "${staging}" -mindepth 1 -delete
        rmdir "${staging}"
    fi
}
trap cleanup EXIT

download() {
    local url="$1"
    local output="$2"

    echo "Downloading ${url}"
    curl \
        --fail \
        --location \
        --silent \
        --show-error \
        --retry 3 \
        --retry-all-errors \
        --output "${output}" \
        "${url}"

    if [[ ! -s "${output}" ]]; then
        echo "downloaded file is empty: ${output}" >&2
        exit 1
    fi
}

download "https://developers.openai.com/codex/llms.txt" "${staging}/index.md"
download "https://developers.openai.com/codex/codex-manual.md" "${staging}/manual.md"
download "https://developers.openai.com/codex/llms-full.txt" "${staging}/full.md"

for document in index.md manual.md full.md; do
    if ! rg --quiet '^#' "${staging}/${document}"; then
        echo "downloaded file does not look like Markdown: ${document}" >&2
        exit 1
    fi
done

captured_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat >"${staging}/SOURCE.md" <<EOF
# OpenAI Codex documentation snapshot

- Snapshot date: ${snapshot_date}
- Captured at: ${captured_at}
- Source type: live OpenAI documentation, frozen after download
- RONDO Codex CLI source baseline: v0.146.0
- Upstream baseline tag: rust-v0.146.0
- Upstream baseline commit: e363b08c9175ac1cbe5893615dd2cb9ddf95043b
- Index source: https://developers.openai.com/codex/llms.txt
- Condensed manual source: https://developers.openai.com/codex/codex-manual.md
- Full documentation source: https://developers.openai.com/codex/llms-full.txt

This is a date-based snapshot of the live documentation. It is not a versioned
documentation release and is not guaranteed to describe the frozen source
baseline exactly. When documentation, source code, and tests disagree, the
behavior of the RONDO source tree and its tests is authoritative.
EOF

(
    cd "${staging}"
    sha256sum index.md manual.md full.md >SHA256SUMS
)

mv --no-target-directory "${staging}" "${destination}"
trap - EXIT

echo "Saved frozen OpenAI Codex documentation snapshot: ${destination}"
