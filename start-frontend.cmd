@echo off
setlocal
set "REPO_ROOT=%~dp0"
powershell.exe -NoProfile -File "%REPO_ROOT%scripts\start_frontend_current_main.ps1" %*
exit /b %ERRORLEVEL%
