"""PowerShell 5 checks: side effects replaced by in-process stubs."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/start_candidate_management_interactive.ps1"
PS = shutil.which("powershell.exe")

def literal(value):
    return "'" + str(value).replace("'", "''") + "'"

def run_ps(body):
    assert SCRIPT.is_file(), "interactive wrapper not implemented"
    assert PS, "Windows PowerShell required"
    script = "$ErrorActionPreference='Stop'; . " + literal(SCRIPT) + "\n" + body
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run([PS, "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)

def test_cmd_delegates_without_raw_arguments():
    cmd = (ROOT / "start-candidate-management.cmd").read_text("ascii")
    assert "start_candidate_management_interactive.ps1" in cmd
    assert "%*" not in cmd and "-Command " not in cmd
    assert "-STA" in cmd and "pause" in cmd
    assert 'exit /b %RESULT%' in cmd

BASE = r"""
function Resolve-CandidateMain { return 'C:\dummy main' }
function Get-CandidatePortState { return 'free' }
function Get-CandidatePython { return 'C:\dummy main\python.exe' }
function Get-CandidateSavedPath { return '' }
function Select-CandidateConfig { return '' }
function Test-CandidateConfig { param($Path) return $Path }
function Confirm-CandidateRemember { return $false }
function Save-CandidatePath { throw 'unexpected persistence' }
function Invoke-CandidateHelper { param($Repo,$Python,$Config) Write-Host "DELEGATED:$Config"; $script:CandidateHelperExit = 0 }
"""

@pytest.mark.parametrize("overrides,argument,expected,marker", [
    ("", "", 0, "cancelled"),
    ("function Get-CandidatePortState { 'occupied' }", "C:\\dummy.json", 2, "existing_backend_kept"),
    ("function Get-CandidatePortState { throw 'unknown' }", "C:\\dummy.json", 2, "listener_state_unknown"),
    ("function Resolve-CandidateMain { throw 'registered_main_required' }", "C:\\dummy.json", 2, "registered_main_required"),
    ("function Get-CandidatePython { throw 'canonical_interpreter_missing' }", "C:\\dummy.json", 2, "canonical_interpreter_missing"),
    ("function Test-CandidateConfig { throw 'configuration_invalid' }", "C:\\bad.json", 2, "configuration_invalid"),
    ("function Invoke-CandidateHelper { $script:CandidateHelperExit = 17 }", "C:\\dummy.json", 17, "helper_exit=17"),
    ("", "C:\\中文 space\\config.json", 0, "DELEGATED:"),
])
def test_flow(overrides, argument, expected, marker):
    result = run_ps(BASE + overrides + "\nexit (Invoke-CandidateManagement " + literal(argument) + ")")
    assert result.returncode == expected, result.stdout + result.stderr
    assert marker in result.stdout + result.stderr
    if expected == 2 or not argument:
        assert "DELEGATED:" not in result.stdout

def test_remember_requires_explicit_opt_in_after_validation():
    result = run_ps(BASE + r"""
function Confirm-CandidateRemember { return $true }
function Save-CandidatePath { param($Path) Write-Host 'SAVED' }
exit (Invoke-CandidateManagement 'C:\dummy.json')
""")
    assert result.returncode == 0, result.stderr
    assert "SAVED" in result.stdout and "DELEGATED:" in result.stdout

@pytest.mark.parametrize("path", ['C:\\x"&whoami.json', "C:\\x\n.json", "C:\\x"+chr(96)+"whoami.json",
                                  "C:\\x&whoami.json", "C:\\x(a).json", "relative.json"])
def test_path_rejected_without_execution(path):
    result = run_ps("try { Test-CandidateConfig " + literal(path) +
                    "; exit 9 } catch { Write-Host $_.Exception.Message; exit 2 }")
    assert result.returncode == 2 and "configuration_path_invalid" in result.stdout

KEYS = [
    "QS_CANDIDATE_DELIVERY_ROOT", "QS_CANDIDATE_DELIVERY_OPERATOR",
    "QS_CANDIDATE_OFFLINE_CATALOG", "QS_CANDIDATE_OFFLINE_CATALOG_SHA256",
    "QS_CANDIDATE_OFFLINE_CATALOG_REVISION", "QS_CANDIDATE_OFFLINE_ENABLED",
    "QS_BACKEND_EVIDENCE_PROFILE", "QS_ALLOW_FIXTURE_FALLBACK", "QS_BTC_DEMO_CONTROL_ENABLED",
]

@pytest.mark.parametrize("kind", ["valid", "extra", "missing", "number", "array", "broken"])
def test_config_shape_and_unicode_literal_path(tmp_path, kind):
    path = tmp_path / "中文 space 'single'" / "deployment-enabled.json"
    path.parent.mkdir()
    value = dict.fromkeys(KEYS, "dummy")
    if kind == "extra": value["unexpected"] = "dummy"
    if kind == "missing": del value[KEYS[0]]
    if kind == "number": value[KEYS[0]] = 12
    if kind == "array": value = [value]
    path.write_text("{" if kind == "broken" else json.dumps(value), encoding="utf-8")
    result = run_ps("try { $v = Test-CandidateConfig " + literal(path) +
                    "; Write-Host 'VALID'; exit 0 } catch { Write-Host $_.Exception.Message; exit 2 }")
    assert result.returncode == (0 if kind == "valid" else 2), result.stdout + result.stderr

def test_actual_producer_worktree_cannot_launch():
    result = run_ps("try { Resolve-CandidateMain; exit 9 } catch { Write-Host $_.Exception.Message; exit 2 }")
    assert result.returncode == 2 and "registered_main_required" in result.stdout

def test_source_boundary():
    source = SCRIPT.read_text("utf-8-sig")
    assert "'--auth-mode' 'local_no_password'" in source
    assert "--prompt-auth" not in source and "getpass" not in source
    assert "QS_WEB_API_KEY" not in source
    for forbidden in ("Stop-Process", "taskkill", "Invoke-Expression", "Start-Process", "uvicorn", "Set-ExecutionPolicy"):
        assert forbidden not in source
    assert source.count("SetEnvironmentVariable(") == 1
    assert "'QS_CANDIDATE_DEPLOYMENT_CONFIG', $Path, 'User'" in source
    assert "GetActiveTcpListeners" in source


def test_saved_path_does_not_prompt_or_write_again():
    result = run_ps(BASE + r"""
function Get-CandidateSavedPath { 'C:\saved.json' }
function Confirm-CandidateRemember { throw 'unexpected preference prompt' }
exit (Invoke-CandidateManagement)
""")
    assert result.returncode == 0 and 'DELEGATED:C:\\saved.json' in result.stdout


def test_preference_write_failure_is_optional():
    result = run_ps(BASE + r"""
function Confirm-CandidateRemember { $true }
exit (Invoke-CandidateManagement 'C:\dummy.json')
""")
    assert result.returncode == 0
    assert 'without persistence' in result.stdout and 'DELEGATED:' in result.stdout


def test_delegate_literal_arguments_and_visible_output(tmp_path):
    result = run_ps(r"""
function dummy_python {
    if ($args.Count -ne 9 -or $args[4] -ne 'start' -or $args[5] -ne '--config' -or
        $args[6] -ne "C:\中文 space 'single'\config.json" -or $args[7] -ne '--auth-mode' -or $args[8] -ne 'local_no_password') {
        throw 'argument mismatch'
    }
    Write-Output 'VISIBLE_CHILD_OUTPUT'
    $global:LASTEXITCODE = 17
}
""" + 'Invoke-CandidateHelper ' + literal(tmp_path) + ' dummy_python ' +
                    literal("C:\\中文 space 'single'\\config.json") +
                    ' | Out-Host; exit $script:CandidateHelperExit')
    assert result.returncode == 17, result.stdout + result.stderr
    assert 'VISIBLE_CHILD_OUTPUT' in result.stdout


@pytest.mark.parametrize('mode', ['valid', 'head', 'sparse', 'unregistered'])
def test_main_guard_with_readonly_git_fixture(tmp_path, mode):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    body = '$script:CandidateScriptRoot = ' + literal(scripts) + '\n'
    body += '$script:MockRepo = ' + literal(tmp_path) + '\n'
    body += '$script:Mode = ' + literal(mode) + '\n'
    body += r"""
function git {
    $global:LASTEXITCODE = 0
    if ($args -contains 'config') { if ($script:Mode -eq 'sparse') { 'false' } else { 'true' }; return }
    if ($args -contains 'worktree') {
        "worktree $script:MockRepo"
        if ($script:Mode -ne 'unregistered') { 'branch refs/heads/main' }
        return
    }
    if ($args[-1] -eq 'HEAD' -and $script:Mode -eq 'head') { 'different' } else { 'same' }
}
try { Resolve-CandidateMain | Out-Null; exit 0 } catch { Write-Host $_.Exception.Message; exit 2 }
"""
    result = run_ps(body)
    assert result.returncode == (0 if mode == 'valid' else 2), result.stdout + result.stderr
