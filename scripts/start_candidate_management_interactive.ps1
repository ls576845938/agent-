[CmdletBinding()]
param([string]$ConfigurationPath = '')

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$script:CandidateScriptRoot = $PSScriptRoot

function Resolve-CandidateMain {
    $repo = (Resolve-Path -LiteralPath (Join-Path $script:CandidateScriptRoot '..')).Path
    $sparse = @(& git -C $repo config --bool core.sparseCheckout)
    if ($LASTEXITCODE -ne 0 -or $sparse.Count -ne 1 -or $sparse[0] -ne 'true') {
        throw 'registered_main_required: sparse checkout required'
    }
    $entries = @(& git -C $repo -c core.quotePath=false worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'registered_main_required: cannot inspect worktrees' }
    $current = ''; $main = ''
    foreach ($line in $entries) {
        if ($line.StartsWith('worktree ')) { $current = $line.Substring(9) }
        if ($line -eq 'branch refs/heads/main') { $main = $current }
    }
    if (-not $main -or (Resolve-Path -LiteralPath $main).Path -ne $repo) {
        throw 'registered_main_required: use the CMD in registered main, not a ticket worktree'
    }
    $head = @(& git -C $repo rev-parse HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'registered_main_required: HEAD unavailable' }
    $mainHead = @(& git -C $repo rev-parse refs/heads/main)
    if ($LASTEXITCODE -ne 0 -or $head.Count -ne 1 -or $mainHead.Count -ne 1 -or $head[0] -ne $mainHead[0]) {
        throw 'registered_main_required: HEAD mismatch'
    }
    return $repo
}

function Get-CandidatePortState {
    try {
        $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        foreach ($endpoint in $listeners) {
            if ($endpoint.Port -eq 8765) { return 'occupied' }
        }
        return 'free'
    } catch { return 'unknown' }
}

function Get-CandidatePython {
    param([string]$Repo)
    $candidates = @($env:QS_CANONICAL_PYTHON, (Join-Path $Repo '.venv\Scripts\python.exe'),
        (Join-Path $Repo 'venv\Scripts\python.exe'))
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $resolved = (Resolve-Path -LiteralPath $candidate).Path
            if (-not $resolved.StartsWith($Repo.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw 'canonical_interpreter_outside_main'
            }
            return $resolved
        }
    }
    throw 'canonical_interpreter_missing: restore the canonical main virtual environment'
}

function Get-CandidateSavedPath {
    # This is the only User-scope environment variable read by this wrapper.
    if ($env:QS_CANDIDATE_DEPLOYMENT_CONFIG) { return $env:QS_CANDIDATE_DEPLOYMENT_CONFIG }
    return [Environment]::GetEnvironmentVariable('QS_CANDIDATE_DEPLOYMENT_CONFIG', 'User')
}

function Select-CandidateConfig {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    try {
        $dialog.Title = 'Select candidate deployment JSON (non-secret)'
        $dialog.Filter = 'Deployment JSON (*.json)|*.json'
        $dialog.FileName = 'deployment-enabled.json'
        $dialog.CheckFileExists = $true
        $dialog.Multiselect = $false
        $dialog.RestoreDirectory = $true
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $dialog.FileName }
        return ''
    } finally { $dialog.Dispose() }
}

function Test-CandidateConfig {
    param([string]$Path)
    # Literal Unicode/spaces/apostrophes supported; shell metacharacters are refused.
    if (-not $Path -or $Path -match '[\x00-\x1f"&|<>^();$]' -or $Path.Contains([char]96) -or
        $Path -notmatch '^[A-Za-z]:[\\/]' -or [IO.Path]::GetExtension($Path) -ine '.json') {
        throw 'configuration_path_invalid'
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'configuration_file_missing' }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -gt 2000000) { throw 'configuration_invalid: oversized' }
    try { $config = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'configuration_invalid: unreadable JSON' }
    $keys = @('QS_CANDIDATE_DELIVERY_ROOT', 'QS_CANDIDATE_DELIVERY_OPERATOR',
        'QS_CANDIDATE_OFFLINE_CATALOG', 'QS_CANDIDATE_OFFLINE_CATALOG_SHA256',
        'QS_CANDIDATE_OFFLINE_CATALOG_REVISION', 'QS_CANDIDATE_OFFLINE_ENABLED',
        'QS_BACKEND_EVIDENCE_PROFILE', 'QS_ALLOW_FIXTURE_FALLBACK', 'QS_BTC_DEMO_CONTROL_ENABLED')
    if ($config -isnot [System.Management.Automation.PSCustomObject]) { throw 'configuration_invalid: object required' }
    $names = @($config.PSObject.Properties.Name)
    if ($names.Count -ne $keys.Count) { throw 'configuration_invalid: non-secret keys required' }
    foreach ($key in $keys) {
        if ($names -cnotcontains $key -or $config.$key -isnot [string]) {
            throw 'configuration_invalid: non-secret string keys required'
        }
    }
    return $item.FullName
}

function Confirm-CandidateRemember {
    # Only a non-secret path preference, never an authentication prompt.
    return ((Read-Host 'Remember this configuration PATH for next time? [y/N]') -ceq 'y')
}

function Save-CandidatePath {
    param([string]$Path)
    [Environment]::SetEnvironmentVariable('QS_CANDIDATE_DEPLOYMENT_CONFIG', $Path, 'User')
}

function Invoke-CandidateHelper {
    param([string]$Repo, [string]$Python, [string]$Config)
    Push-Location -LiteralPath $Repo
    try {
        # Explicit local candidate mode; no generated or persisted password.
        & $Python '-B' '-X' 'utf8' 'scripts/candidate_management_deployment.py' 'start' '--config' $Config '--auth-mode' 'local_no_password'
        $script:CandidateHelperExit = $LASTEXITCODE
    } finally { Pop-Location }
}

function Invoke-CandidateManagement {
    param([string]$Path = '')
    try {
        $repo = Resolve-CandidateMain
        try { $state = Get-CandidatePortState } catch { $state = 'unknown' }
        if ($state -eq 'occupied') {
            Write-Host 'existing_backend_kept: port 8765 is occupied. Switch required; no process was stopped.'
            return 2
        }
        if ($state -ne 'free') { throw 'listener_state_unknown: startup blocked; existing backend unchanged' }
        $python = Get-CandidatePython $repo
        $saved = Get-CandidateSavedPath
        if (-not $Path) { $Path = $saved }
        if (-not $Path) { $Path = Select-CandidateConfig }
        if (-not $Path) { Write-Host 'cancelled: nothing started or saved'; return 0 }
        $Path = Test-CandidateConfig $Path
        if ($Path -ne $saved -and (Confirm-CandidateRemember)) {
            try { Save-CandidatePath $Path }
            catch { Write-Host 'Path preference could not be saved; continuing without persistence.' }
        }
        Write-Host 'Local candidate management: no password input. Only verified local requests are accepted.'
        Write-Host 'Local programs are trusted; trading stays disabled. Ctrl+C stops the foreground process.'
        $script:CandidateHelperExit = 2
        Invoke-CandidateHelper $repo $python $Path | Out-Host
        $result = $script:CandidateHelperExit
        Write-Host "helper_exit=$result (not a service readiness confirmation)"
        return [int]$result
    } catch {
        Write-Host ("Startup blocked: " + $_.Exception.Message)
        return 2
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-CandidateManagement $ConfigurationPath)
}
