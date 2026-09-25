@echo off
cd /d "%~dp0"
start "WFM Trader" /min python server.py
echo WFM Trader starting... open http://127.0.0.1:8787/
timeout /t 2 /nobreak >nul
