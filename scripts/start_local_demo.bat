@echo off
REM Wrapper to launch scripts\start_local_demo.ps1 under PowerShell Bypass.
REM Usage: .\scripts\start_local_demo.bat [any-args-passed-through]

setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_local_demo.ps1" %*
endlocal
