@echo off
setlocal
rem Double-click entry: no command-line arguments are forwarded.
rem Use the PS1 ConfigurationPath parameter for an explicit advanced invocation.
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\start_candidate_management_interactive.ps1"
set "RESULT=%ERRORLEVEL%"
echo Launcher exited with code %RESULT%. Existing services are not stopped by this wrapper.
pause
exit /b %RESULT%
