@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 scripts/launch_customer.py %*
) else (
  py -3 -X utf8 scripts/launch_customer.py %*
)
if errorlevel 1 (
  echo Startup or acceptance failed. See docs/CUSTOMER_WINDOWS.md
  pause
  exit /b 1
)
exit /b 0
