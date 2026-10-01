@echo off
setlocal

where python >NUL 2>NUL
if %ERRORLEVEL% EQU 0 (
  python "%~dp0scripts\win_make.py" %*
) else (
  py -3 "%~dp0scripts\win_make.py" %*
)
