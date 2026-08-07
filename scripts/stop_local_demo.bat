@echo off
REM Wrapper to launch scripts\stop_local_demo.ps1 under PowerShell Bypass.
REM Usage: .\scripts\stop_local_demo.bat [any-args-passed-through]

setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop_local_demo.ps1" %*
endlocal
