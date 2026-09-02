#!/usr/bin/env bash
#
# Compose the GitHub Release notes for one RONDO release.
#
# The body comes from the product CHANGELOG rather than from an auto-summary of
# commit messages: commit granularity in this repo is far too fine for that to
# read as anything but noise.
#
# The banners are mandatory, not decoration. Plan 103 H3 forbids shipping any
# quality or performance claim, and the fork must state plainly that it is not
# an OpenAI product.

set -euo pipefail

PRODUCT_DIR=""
VARIANT=""
VERSION=""
BASE_VERSION=""
TAG=""
PRERELEASE="false"
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --product-dir)  PRODUCT_DIR="$2";  shift 2 ;;
    --variant)      VARIANT="$2";      shift 2 ;;
    --version)      VERSION="$2";      shift 2 ;;
    --base-version) BASE_VERSION="$2"; shift 2 ;;
    --tag)          TAG="$2";          shift 2 ;;
    --prerelease)   PRERELEASE="$2";   shift 2 ;;
    --out)          OUT="$2";          shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

: "${PRODUCT_DIR:?--product-dir is required}"
: "${VARIANT:?--variant is required}"
: "${VERSION:?--version is required}"
: "${BASE_VERSION:?--base-version is required}"
: "${TAG:?--tag is required}"
: "${OUT:?--out is required}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
changelog="${REPO_ROOT}/${PRODUCT_DIR}/CHANGELOG.md"

if [[ ! -f "$changelog" ]]; then
  echo "missing changelog: ${changelog}" >&2
  exit 1
fi

body="$(awk -v ver="$BASE_VERSION" '
  $0 ~ "^## " ver "( |$)" { flag = 1; next }
  /^## / && flag { exit }
  flag { print }
' "$changelog")"

if [[ -z "${body//[[:space:]]/}" ]]; then
  echo "no '## ${BASE_VERSION}' section found in ${changelog}" >&2
  exit 1
fi

{
  if [[ "$PRERELEASE" == "true" ]]; then
    printf '> **Pre-release.** 用于实跑验证发布流水线本身，不是正式版本。\n\n'
  fi

  printf '> **实验性研究产物，不是生产工具。**\n'
  printf '> 本项目不提供任何性能或质量承诺，也不发布任务解决率、准确率之类的数字。\n'
  printf '> 这是 OpenAI Codex CLI 的一个 fork，与 OpenAI 无关联，未获其背书。\n\n'

  printf '%s\n' "$body"

  printf '\n---\n\n'

  printf '### 关于版本号\n\n'
  printf '包内二进制 `--version` 输出的是 `0.147.0`——那是被冻结的上游基线版本号，全程不改，\n'
  printf '以支持与原始 Codex 的字节级公平对比。**产品版本以本 Release 的 tag 为准（`%s`）。**\n' "$VERSION"
  printf '`codex-package.json` 里的 `version` 字段同理。\n\n'

  printf '### 包内容\n\n'
  printf '归档是**完整产品包**，不是裸二进制：\n\n'
  printf '```text\n'
  printf '%s-%s-x86_64-unknown-linux-musl/\n' "$VARIANT" "$VERSION"
  printf '├── bin/%s                  # 入口\n' "$VARIANT"
  printf '├── bin/codex-code-mode-host\n'
  printf '├── codex-resources/bwrap           # bundled bubblewrap，带编译期摘要校验\n'
  printf '├── codex-resources/zsh/bin/zsh\n'
  printf '├── codex-path/rg\n'
  printf '├── codex-package.json\n'
  printf '├── LICENSE, NOTICE\n'
  printf '└── THIRD-PARTY-LICENSES/\n'
  printf '```\n\n'
  printf '安装：解压后直接运行 `bin/%s`，或把该目录加入 `PATH`。\n' "$VARIANT"
  printf '**不要**把 `bin/%s` 单独拷出来——附属组件是按包内相对路径解析的。\n\n' "$VARIANT"
  printf '校验：`sha256sum -c SHA256SUMS`\n\n'

  # The two product lines have different experimental subsystems, and neither
  # exists in the other tree: `publication-critic` is only under multidev/, and
  # the Guardian approval model is a RONDO Local topic. Emitting the wrong one
  # would describe a feature the package does not contain.
  case "$PRODUCT_DIR" in
    multidev)
      printf '### 判官后端不在包内\n\n'
      printf 'Publication Critic 的打分服务是独立二进制，**不随本 Release 分发**，需要自行从源码构建。\n'
      printf '本地后端依赖未分发的模型权重与推理运行时，云端后端需要你自备凭据。详见 README。\n\n'
      ;;
    mydev)
      printf '### 本地审批模型不在包内\n\n'
      printf '可插拔的本地推理审批模型**不随本 Release 分发**，也不是下载即用：\n'
      printf '它依赖未随仓库分发的模型权重与本地推理运行时，需要你自行准备并通过\n'
      printf 'OpenAI-compatible 接口接入。该方向的结论是**保留为实验、未采用**，\n'
      printf '产品默认值不变。详见 README 的"诚实的结果"。\n\n'
      ;;
    *)
      echo "unknown product dir for release notes: ${PRODUCT_DIR}" >&2
      exit 1
      ;;
  esac

  printf '### bubblewrap 源码与许可\n\n'
  printf '包内 `codex-resources/bwrap` 是把 `%s/codex-rs/vendor/bubblewrap/`\n' "$PRODUCT_DIR"
  printf '（bubblewrap 0.11.2，**LGPL-2.0-or-later**）的 C 源码经 `%s/codex-rs/bwrap/build.rs`\n' "$PRODUCT_DIR"
  printf '编译进 Rust 包装器得到的，不是随包的独立外部程序。\n'
  printf '对应源码即本 tag `%s` 下的该目录；许可全文见包内\n' "$TAG"
  printf '`THIRD-PARTY-LICENSES/bubblewrap-0.11.2-COPYING`。\n'
} > "$OUT"

echo "release notes written to ${OUT}"
