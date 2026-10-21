@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0scripts\customer_windows.ps1" -Acceptance
if errorlevel 1 (
  echo Startup or acceptance failed. See docs/CUSTOMER_WINDOWS.md
  pause
  exit /b 1
)
exit /b 0
