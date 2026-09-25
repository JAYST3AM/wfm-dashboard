@echo off
setlocal
title WFM Trader - setup
cd /d "%~dp0"

echo ============================================
echo  WFM Trader - one-time setup
echo ============================================
echo.

echo [1/4] Looking for Python...
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo Python was not found.
  echo.
  echo Install Python 3.11 or newer, then run setup.bat again.
  echo Easiest:
  echo     winget install Python.Python.3.12
  echo or download from https://www.python.org/downloads/windows/
  echo ^(tick "Add python.exe to PATH" in the installer^)
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo       %PYVER%

echo [2/4] Installing the one dependency (cryptography)...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo Could not install dependencies - see the message above.
  pause
  exit /b 1
)

if /i "%~1"=="check" (
  echo.
  echo Check mode: Python and dependencies are ready.
  echo Run setup.bat to build the data.
  pause
  exit /b 0
)

echo [3/4] Building the data - 20-40 minutes the first time.
echo         Resumable: Ctrl+C any time, run setup.bat again to continue.
echo.
%PY% scripts\setup.py
if errorlevel 1 (
  echo.
  echo Setup stopped - read the message above, fix it, then run setup.bat again.
  pause
  exit /b 1
)

echo [4/4] Starting the dashboard...
netstat -ano | findstr /r /c:"LISTENING.*:8787" >nul 2>&1
if errorlevel 1 (
  start "WFM Trader" /min %PY% server.py
  timeout /t 3 /nobreak >nul
)
start "" http://127.0.0.1:8787/
echo.
echo Done - the dashboard is open in your browser.
echo Keep it fresh later with: refresh.bat
pause
