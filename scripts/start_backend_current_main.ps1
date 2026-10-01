[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

# Read this one non-secret, operator-configured location when the desktop parent
# predates it. Do not hydrate credentials or alter the promotion artifact root.
if (-not $env:QS_BTC_STRATEGY_HISTORY_ARTIFACT_ROOT) {
    $historyArtifactRoot = [Environment]::GetEnvironmentVariable('QS_BTC_STRATEGY_HISTORY_ARTIFACT_ROOT', 'User')
    if ($historyArtifactRoot) {
        $env:QS_BTC_STRATEGY_HISTORY_ARTIFACT_ROOT = $historyArtifactRoot
    }
}

$scriptRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sparse = (& git -C $scriptRepo config --bool core.sparseCheckout).Trim()
if ($LASTEXITCODE -ne 0 -or $sparse -ne 'true') {
    throw 'worktree_not_sparse'
}

$mainWorktree = $null
$currentWorktree = $null
foreach ($line in (& git -C $scriptRepo worktree list --porcelain)) {
    if ($line -like 'worktree *') {
        $currentWorktree = $line.Substring('worktree '.Length)
        continue
    }
    if ($line -eq 'branch refs/heads/main') {
        $mainWorktree = $currentWorktree
    }
}
if (-not $mainWorktree) {
    throw 'backend_launcher_registered_main_missing'
}
if ($env:QS_ALLOW_FIXTURE_FALLBACK -cne 'false') {
    throw 'backend_fixture_fallback_must_be_false'
}
$evidenceProfile = $env:QS_BACKEND_EVIDENCE_PROFILE
if (-not $evidenceProfile) {
    $evidenceProfile = 'promotion_strict'
}
if ($evidenceProfile -notin @('promotion_strict', 'demo_quasi_live', 'research_readonly', 'candidate_management')) {
    throw 'backend_evidence_profile_invalid'
}
if (
    $evidenceProfile -eq 'candidate_management' -and
    $env:QS_BTC_DEMO_CONTROL_ENABLED -cne 'false'
) {
    throw 'backend_candidate_management_control_must_be_false'
}
if (
    $evidenceProfile -eq 'research_readonly' -and
    $env:QS_BTC_DEMO_CONTROL_ENABLED -cne 'false'
) {
    throw 'backend_research_readonly_control_must_be_false'
}
if (
    $evidenceProfile -eq 'promotion_strict' -and
    -not $env:QS_BTC_RUNTIME_ARTIFACT_ROOT
) {
    throw 'btc_runtime_artifact_root_env_missing'
}
if (
    $evidenceProfile -eq 'demo_quasi_live' -and
    $env:QS_BTC_DEMO_CONTROL_ENABLED -cne 'true'
) {
    throw 'backend_demo_control_must_be_true'
}

$guard = Join-Path $mainWorktree 'scripts\start_backend_current_main.py'
if (-not (Test-Path -LiteralPath $guard -PathType Leaf)) {
    throw 'backend_canonical_guard_missing'
}

$pythonCandidates = @(
    @(
        $env:QS_CANONICAL_PYTHON,
        (Join-Path $mainWorktree '.venv\Scripts\python.exe'),
        (Join-Path $mainWorktree 'venv\Scripts\python.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
)
if (-not $pythonCandidates) {
    throw 'backend_launcher_canonical_interpreter_missing'
}
$canonicalPython = (Resolve-Path -LiteralPath $pythonCandidates[0]).Path
$mainRootPrefix = ((Resolve-Path -LiteralPath $mainWorktree).Path).TrimEnd('\') + '\'
if (-not $canonicalPython.StartsWith($mainRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'backend_launcher_canonical_interpreter_outside_registered_main'
}
$env:QS_CANONICAL_PYTHON = $canonicalPython

Push-Location $mainWorktree
try {
    $arguments = @(
        $guard,
        '--repo-root', $mainWorktree,
        '--host', '127.0.0.1',
        '--port', '8765'
    )
    if ($Check) {
        $arguments += '--check'
    }
    & $canonicalPython @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
