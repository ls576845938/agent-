@echo off
setlocal
set "REPO_ROOT=%~dp0"
powershell.exe -NoProfile -File "%REPO_ROOT%scripts\start_backend_current_main.ps1" %*
exit /b %ERRORLEVEL%
