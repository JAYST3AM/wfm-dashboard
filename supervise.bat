@echo off
setlocal
title WFM Trader - supervisor
cd /d "%~dp0"

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python was not found - run setup.bat first.
  pause
  exit /b 1
)

echo Keeping the dashboard alive. Ctrl+C stops the supervisor (and the server it started).
echo Tip: a shortcut to supervise.bat in your Startup folder (Win+R, shell:startup)
echo      starts it automatically when you log in.
echo.
%PY% tools\supervise.py
pause
