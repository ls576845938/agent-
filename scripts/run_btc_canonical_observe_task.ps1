[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedMainHead,

    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [Parameter(Mandatory = $true)]
    [string]$GitPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedGitSha256,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,

    [Parameter(Mandatory = $true)]
    [string]$CandidateRuntimeRoot,

    [Parameter(Mandatory = $true)]
    [string]$SharedRoot,

    [Parameter(Mandatory = $true)]
    [string]$RetiredRuntimeRoot,

    [Parameter(Mandatory = $true)]
    [string]$PublicSwapManifestGitSpec,

    [Parameter(Mandatory = $true)]
    [string]$L2ManifestGitSpec
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

if (-not [IO.Path]::IsPathFullyQualified($PythonPath)) {
    throw 'btc_canonical_observe_python_path_must_be_absolute'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'btc_canonical_observe_python_path_invalid'
}
if (-not [IO.Path]::IsPathFullyQualified($GitPath)) {
    throw 'btc_observe_git_executable_must_be_absolute'
}
if (-not (Test-Path -LiteralPath $GitPath -PathType Leaf)) {
    throw 'btc_observe_git_executable_invalid'
}

$corePath = Join-Path $PSScriptRoot 'run_btc_canonical_observe_task.py'
if (-not (Test-Path -LiteralPath $corePath -PathType Leaf)) {
    throw 'btc_canonical_observe_core_missing'
}

& $PythonPath $corePath `
    --expected-main-head $ExpectedMainHead `
    --python-path $PythonPath `
    --git-path $GitPath `
    --expected-git-sha256 $ExpectedGitSha256 `
    --runtime-root $RuntimeRoot `
    --candidate-runtime-root $CandidateRuntimeRoot `
    --shared-root $SharedRoot `
    --retired-runtime-root $RetiredRuntimeRoot `
    --public-swap-manifest-git-spec $PublicSwapManifestGitSpec `
    --l2-manifest-git-spec $L2ManifestGitSpec `
    --launcher-path $PSCommandPath `
    --core-path $corePath
exit $LASTEXITCODE
