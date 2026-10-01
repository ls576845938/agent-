[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$scriptRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sparse = (& git -C $scriptRepo config --get core.sparseCheckout).Trim()
if ($LASTEXITCODE -ne 0 -or $sparse -ne 'true') {
    throw "FRONTEND_LAUNCH_REPO_NOT_SPARSE repo=$scriptRepo"
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
    throw 'FRONTEND_MAIN_WORKTREE_MISSING refs/heads/main has no registered worktree'
}

$frontendRoot = Join-Path $mainWorktree 'frontend'
$guard = Join-Path $frontendRoot 'scripts\start-current-main.mjs'
if (-not (Test-Path -LiteralPath $guard -PathType Leaf)) {
    throw "FRONTEND_CANONICAL_GUARD_MISSING path=$guard"
}

Write-Output "canonical_main_worktree=$mainWorktree"
Write-Output "canonical_frontend=$frontendRoot"

Push-Location $frontendRoot
try {
    if ($Check) {
        & node $guard --check
    }
    else {
        & npm.cmd run dev
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
