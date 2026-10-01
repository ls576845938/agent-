param(
    [string]$EnvVarName = "FRED_API_KEY",
    [switch]$UserScope
)

$clip = Get-Clipboard -Raw
if ([string]::IsNullOrWhiteSpace($clip)) {
    Write-Output "fred_key_candidate_missing"
    exit 2
}

$matches = [regex]::Matches($clip, "(?<![A-Za-z0-9])[A-Za-z0-9]{32}(?![A-Za-z0-9])")
if ($matches.Count -eq 0) {
    Write-Output "fred_key_candidate_missing"
    exit 2
}
if ($matches.Count -gt 1) {
    Write-Output ("fred_key_candidate_ambiguous=" + $matches.Count)
    exit 3
}

$key = $matches[0].Value
Set-Item -Path ("Env:" + $EnvVarName) -Value $key
if ($UserScope) {
    [Environment]::SetEnvironmentVariable($EnvVarName, $key, "User")
}

Write-Output "fred_key_candidate_loaded=1"
