$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:NEXTEST_ENV)) {
    throw "Nextest did not provide its environment output path"
}
$targetDir = $env:CARGO_TARGET_DIR
if ([string]::IsNullOrWhiteSpace($targetDir)) {
    $targetDir = Join-Path (Get-Location).Path "target"
}
if (-not [System.IO.Path]::IsPathRooted($targetDir)) {
    throw "CARGO_TARGET_DIR must be absolute for publication critic process tests"
}
$targetDir = [System.IO.Path]::GetFullPath($targetDir)

& cargo build --locked --target-dir $targetDir -p codex-publication-critic --bin codex-publication-critic-service
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$serviceBin = Join-Path $targetDir "debug/codex-publication-critic-service.exe"
if (-not (Test-Path -LiteralPath $serviceBin -PathType Leaf)) {
    throw "publication critic service binary was not built at $serviceBin"
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::AppendAllText(
    $env:NEXTEST_ENV,
    "RONDO_PUBLICATION_CRITIC_SERVICE_BIN=$serviceBin`n",
    $utf8NoBom
)
