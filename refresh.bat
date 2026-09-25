@echo off
setlocal
title WFM Trader - refresh
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

echo Refreshing prices and rebuilding the dashboard data...
echo (each step resumes where it stopped - safe to re-run any time)
echo.
%PY% scripts\fetch_prices.py
%PY% scripts\fetch_stats.py
%PY% scripts\fetch_lanes.py
%PY% scripts\report.py
%PY% scripts\sell_advisor.py --write
%PY% scripts\snapshot_plat.py
%PY% scripts\price_history.py
%PY% scripts\invdiff.py
%PY% scripts\sets.py
%PY% scripts\ducats.py
%PY% scripts\nudges.py

echo.
echo Done - reload http://127.0.0.1:8787 in your browser.
pause
